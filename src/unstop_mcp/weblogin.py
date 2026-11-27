"""Sign in to Unstop from a local browser page.

A tiny HTTP server binds to 127.0.0.1 on a random port under an unguessable path. The user types their email and the
one-time code into that page; the code goes straight from the browser to this process and on to Unstop. It never
passes through the chat, the AI model or any log. The page shuts itself down after success or after a timeout.

Hardening: loopback only, 128-bit random path token, per-page CSRF nonce, Host header pinned to the bound address,
strict Content-Security-Policy, no caching, small request bodies, max 5 code attempts.
"""

from __future__ import annotations

import asyncio
import html
import logging
import secrets
import socket
import socketserver
import threading
import time
import webbrowser
from concurrent.futures import Future
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

from unstop_mcp.auth.unstop_auth import UnstopAuth
from unstop_mcp.errors import UnstopError

log = logging.getLogger(__name__)

_MAX_BODY = 4096
_MAX_CODE_ATTEMPTS = 5


class _LoginServer(ThreadingHTTPServer):
    """The sign-in page's server. It must own its port alone: the one-time code is posted to it."""

    allow_reuse_address = False  # HTTPServer turns SO_REUSEADDR on, which lets another socket share the port
    daemon_threads = True

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows: refuse any other socket on this port
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)  # skip HTTPServer's getfqdn() lookup, which can stall
        host, port = self.server_address[:2]
        self.server_name, self.server_port = str(host), int(port)

_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Sign in to Unstop · Unstop MCP</title>
<style>
:root{{--bg:#f4f6fb;--card:#fff;--ink:#14213d;--mute:#5b6478;--brand:#1c4ed8;--err:#b42318;--ok:#067647;--line:#d9deea}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1424;--card:#151d31;--ink:#e8ecf6;--mute:#9aa4bb;--line:#26314d}}}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;padding:16px}}
.card{{width:100%;max-width:400px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px}}
h1{{font-size:20px;margin:0 0 4px}}p{{margin:0 0 18px;color:var(--mute)}}
label{{display:block;font-weight:600;margin-bottom:6px}}
input{{width:100%;padding:12px 14px;border:1px solid var(--line);border-radius:10px;font-size:16px;background:transparent;color:inherit}}
input:focus{{outline:2px solid var(--brand);outline-offset:1px}}
button{{margin-top:14px;width:100%;padding:12px;border:0;border-radius:10px;background:var(--brand);color:#fff;
font-size:16px;font-weight:600;cursor:pointer}}
.msg{{margin:0 0 14px;padding:10px 12px;border-radius:10px;font-size:14px}}
.err{{background:color-mix(in srgb,var(--err) 12%,transparent);color:var(--err)}}
.ok{{background:color-mix(in srgb,var(--ok) 12%,transparent);color:var(--ok)}}
.foot{{margin-top:18px;font-size:12px;color:var(--mute)}}
</style></head><body><main class="card">{body}
<div class="foot">Runs only on this computer. Your code goes straight to Unstop and is never stored.</div></main></body></html>"""


def _email_form(nonce: str, error: str = "", email: str = "") -> str:
    return f"""<h1>Sign in to Unstop</h1><p>We'll ask Unstop to email you a one-time code.</p>
{f'<div class="msg err">{html.escape(error)}</div>' if error else ''}
<form method="post" action="send"><input type="hidden" name="nonce" value="{nonce}">
<label for="email">Your Unstop email</label>
<input id="email" name="email" type="email" required autocomplete="email" autofocus value="{html.escape(email)}">
<button type="submit">Email me a code</button></form>"""


def _code_form(nonce: str, email: str, info: str, error: str = "") -> str:
    return f"""<h1>Enter your code</h1><p>Sent to <b>{html.escape(email)}</b>.</p>
{f'<div class="msg ok">{html.escape(info)}</div>' if info and not error else ''}
{f'<div class="msg err">{html.escape(error)}</div>' if error else ''}
<form method="post" action="verify"><input type="hidden" name="nonce" value="{nonce}">
<label for="otp">One-time code</label>
<input id="otp" name="otp" inputmode="numeric" pattern="[0-9]{{4,8}}" maxlength="8" required autocomplete="one-time-code" autofocus>
<button type="submit">Sign in</button></form>
<form method="post" action="restart"><input type="hidden" name="nonce" value="{nonce}">
<button type="submit" style="background:transparent;color:var(--brand);margin-top:6px">Use a different email</button></form>"""


def _done(name: str) -> str:
    return f"""<h1>You're signed in ✓</h1><p>Signed in as <b>{html.escape(name)}</b>.</p>
<div class="msg ok">You can close this tab and go back to your AI app.</div>"""


class BrowserLogin:
    """One sign-in attempt. ``start()`` returns the URL; ``result`` resolves to the signed-in name (or None)."""

    def __init__(self, auth: UnstopAuth, tenant: str, loop: asyncio.AbstractEventLoop, timeout: float = 600) -> None:
        self.auth = auth
        self.tenant = tenant
        self.loop = loop
        self.timeout = timeout
        self.token = secrets.token_urlsafe(16)
        self.nonce = secrets.token_urlsafe(16)
        self.email: str | None = None
        self.attempts = 0
        self.result: Future[str | None] = Future()
        self._done_lock = threading.Lock()
        self.deadline = time.monotonic() + timeout
        self._server: ThreadingHTTPServer | None = None
        self.url = ""

    # -- lifecycle -------------------------------------------------------------------------------------
    def start(self, open_browser: bool = True) -> str:
        login = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "unstop-mcp"
            sys_version = ""

            def log_message(self, *args: Any) -> None:  # keep codes and emails out of logs entirely
                return

            def do_GET(self) -> None:  # noqa: N802
                login._dispatch(self, "GET")

            def do_POST(self) -> None:  # noqa: N802
                login._dispatch(self, "POST")

        self._server = _LoginServer(("127.0.0.1", 0), Handler)
        port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{port}/{self.token}/"
        threading.Thread(target=self._serve, name="unstop-browser-login", daemon=True).start()
        if open_browser:
            try:
                webbrowser.open(self.url, new=2)
            except Exception as exc:  # noqa: BLE001 - no browser available; the URL is returned to the caller
                log.debug("Could not open a browser: %s", exc)
        return self.url

    def _finish(self, value: str | None) -> bool:
        with self._done_lock:
            if self.result.done():
                return False
            self.result.set_result(value)
            return True

    def _serve(self) -> None:
        assert self._server is not None
        self._server.timeout = 1
        while not self.result.done() and time.monotonic() < self.deadline:
            self._server.handle_request()
        self._finish(None)
        # Keep answering briefly, so a refresh or late request gets the "link has expired" page instead of a
        # connection reset (closing the socket with a queued connection resets it; macOS hits this reliably).
        self._server.timeout = 0.2
        grace_until = time.monotonic() + 2
        while time.monotonic() < grace_until:
            self._server.handle_request()
        self._server.server_close()

    def stop(self) -> None:
        self._finish(None)

    @property
    def active(self) -> bool:
        return not self.result.done() and time.monotonic() < self.deadline

    # -- request handling ----------------------------------------------------------------------------
    def _send(self, h: BaseHTTPRequestHandler, status: int, body: str) -> None:
        data = _PAGE.format(body=body).encode()
        h.send_response(status)
        h.send_header("Content-Type", "text/html; charset=utf-8")
        h.send_header("Content-Length", str(len(data)))
        h.send_header("Cache-Control", "no-store")
        h.send_header("X-Frame-Options", "DENY")
        h.send_header("Referrer-Policy", "no-referrer")
        h.send_header("Content-Security-Policy",
                      "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'")
        h.end_headers()
        h.wfile.write(data)

    def _run(self, coro: Any) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=60)

    def _dispatch(self, h: BaseHTTPRequestHandler, method: str) -> None:
        port = self._server.server_address[1] if self._server else 0
        if h.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self._send(h, 421, "<h1>Wrong address</h1>")
            return
        prefix = f"/{self.token}/"
        if not h.path.startswith(prefix):
            self._send(h, 404, "<h1>Not found</h1>")
            return
        if self.result.done():
            self._send(h, 410, "<h1>This sign-in link has expired</h1><p>Ask your AI app to start a new one.</p>")
            return
        action = h.path[len(prefix):].split("?", 1)[0]
        if method == "GET":
            self._send(h, 200, _code_form(self.nonce, self.email, "") if self.email else _email_form(self.nonce))
            return
        length = int(h.headers.get("Content-Length") or 0)
        if length > _MAX_BODY:
            self._send(h, 413, "<h1>Request too large</h1>")
            return
        form = {k: v[0] for k, v in parse_qs(h.rfile.read(length).decode("utf-8", "replace")).items()}
        if not secrets.compare_digest(form.get("nonce", ""), self.nonce):
            self._send(h, 403, "<h1>Session mismatch</h1><p>Reload the page and try again.</p>")
            return

        if action == "restart":
            self.email = None
            self._send(h, 200, _email_form(self.nonce))
        elif action == "send":
            email = form.get("email", "").strip()
            if "@" not in email or len(email) > 254:
                self._send(h, 200, _email_form(self.nonce, "Enter a valid email address.", email))
                return
            try:
                info = self._run(self.auth.send_otp(email))
            except UnstopError as exc:
                self._send(h, 200, _email_form(self.nonce, exc.message, email))
                return
            self.email, self.attempts = email, 0
            self._send(h, 200, _code_form(self.nonce, email, info))
        elif action == "verify" and self.email:
            self.attempts += 1
            try:
                session = self._run(self.auth.verify_otp(self.email, form.get("otp", "")))
                session = self._run(self.auth.complete_login(self.tenant, session))
            except UnstopError as exc:
                if self.attempts >= _MAX_CODE_ATTEMPTS:
                    self.email = None
                    self._send(h, 200, _email_form(self.nonce, "Too many wrong codes. Request a new one."))
                else:
                    self._send(h, 200, _code_form(self.nonce, self.email, "", exc.message))
                return
            name = session.name or session.email or "your Unstop account"
            self._send(h, 200, _done(name))
            log.info("Signed in via browser", extra={"tenant": self.tenant})
            self._finish(name)
        else:
            self._send(h, 200, _email_form(self.nonce))
