"""`setup`, `connect` and `doctor`: get Unstop into the user's AI apps and check everything works."""
from __future__ import annotations

import argparse
import json
import sys
import time

from pydantic import ValidationError

from unstop_mcp import __version__
from unstop_mcp.auth.session import DEFAULT_TENANT
from unstop_mcp.cli._ui import _c, _runtime, _settings, ask_yes, fail, heading, ok, warn
from unstop_mcp.cli.account import _do_login
from unstop_mcp.config import TOOLSET_NAMES, Settings
from unstop_mcp.errors import AuthRequired, UnstopError

TOOLSETS_HELP = ("Tool groups to load (default: all): discover, account, alerts, registration, teams. "
                 "Fewer tools = a faster, more focused AI.")


def _toolsets(args: argparse.Namespace) -> list[str] | None:
    """Validated toolset list from --toolsets (None = all). Raises ValueError with a clear message."""
    raw = getattr(args, "toolsets", None)
    if not raw:
        return None
    try:
        chosen = Settings(toolsets=raw, _env_file=None)  # type: ignore[call-arg]
    except ValidationError as exc:  # show the validator's sentence, not pydantic's report
        msgs = [str(e.get("msg", "")).removeprefix("Value error, ") for e in exc.errors()]
        raise ValueError("; ".join(m for m in msgs if m) or "Invalid --toolsets value.") from None
    # "all" (or every group) stays implicit, so tool groups added in future versions load automatically.
    if "all" in chosen.toolsets or set(chosen.active_toolsets) == set(TOOLSET_NAMES):
        return None
    return chosen.active_toolsets


def cmd_connect(args: argparse.Namespace) -> int:
    from unstop_mcp import clients

    toolsets = None if args.remove else _toolsets(args)  # validate once, before touching any config
    apps = {a.key: a for a in clients.detect_clients()}
    targets = list(apps) if args.app == "all" else [args.app]
    rc, changed = 0, False
    for key in targets:
        app = apps[key]
        if args.app == "all" and not app.detected:
            continue
        try:
            result = clients.uninstall(app) if args.remove else clients.install(app, toolsets)
            ok(f"{app.name}: {result}")
            changed = True
        except (ValueError, OSError) as exc:
            fail(f"{app.name}: {exc}")
            rc = 1
    if changed and not args.remove:
        print("  Restart the app to load Unstop.")
    return rc


async def _setup(args: argparse.Namespace) -> int:
    from unstop_mcp import clients

    toolsets = _toolsets(args)  # validate first: a typo should fail before anything is changed
    settings = _settings(args)
    rt = _runtime(settings)
    try:
        print(_c("1", f"\nUnstop MCP setup  (v{__version__})"))
        print("This connects Unstop to your AI apps. It takes about a minute.")

        heading("Step 1 of 3 · Checking Unstop")
        try:
            res = await rt.client.search(per_page=1)
            ok(f"Unstop is reachable ({res.total:,} open opportunities)")
        except UnstopError as exc:
            fail(f"Unstop is not reachable right now: {exc.message}")
            warn("You can continue; searching will work once your connection is back.")

        heading("Step 2 of 3 · Your Unstop account (optional)")
        print("  Signing in lets the AI see your registrations, deadlines, watchlist and certificates.")
        try:
            session = await rt.auth.get_session(DEFAULT_TENANT)
            ok(f"Already signed in as {session.name or session.email or 'your account'}")
        except UnstopError:
            if args.skip_login:
                warn("Skipped. Run `unstop-mcp login` any time.")
            elif ask_yes("Sign in now with a one-time code from Unstop?", True, args.yes and not sys.stdin.isatty()):
                if not await _do_login(rt, DEFAULT_TENANT, args.email, "email", False):
                    warn("Not signed in. Search still works; run `unstop-mcp login` later.")
            else:
                warn("Skipped. Run `unstop-mcp login` any time.")

        heading("Step 3 of 3 · Connect your AI apps")
        apps = [a for a in clients.detect_clients() if a.detected]
        if args.clients:
            wanted = {c.strip() for c in args.clients.split(",")}
            apps = [a for a in clients.detect_clients() if a.key in wanted]
        if not apps:
            warn("No supported AI app found (Claude Desktop, Claude Code, Cursor, Windsurf).")
            command, cargs = clients.server_command()
            print("  Add this to your app's MCP settings manually:")
            print("  " + json.dumps({"mcpServers": {"unstop": {"command": command, "args": cargs}}}))
        connected = []
        for app in apps:
            if not ask_yes(f"Connect Unstop to {app.name}?", True, args.yes):
                continue
            try:
                ok(f"{app.name}: {clients.install(app, toolsets)}")
                connected.append(app.name)
            except (ValueError, OSError) as exc:
                fail(f"{app.name}: {exc}")

        heading("All set!")
        if connected:
            print(f"  Restart {', '.join(connected)}, then try asking:")
        else:
            print("  Once your AI app is connected, try asking:")
        for example in ('"Find AI hackathons on Unstop that close this week"',
                        '"What are my upcoming Unstop deadlines?"',
                        '"Recommend internships for me on Unstop"'):
            print(f"    {_c('36', example)}")
        print()
        return 0
    finally:
        await rt.http.aclose()


async def _doctor(args: argparse.Namespace) -> int:
    from unstop_mcp.clients import SERVER_NAME, detect_clients

    settings = _settings(args)
    rt = _runtime(settings)
    healthy = True
    try:
        heading("Unstop connection")
        try:
            started = time.monotonic()
            res = await rt.client.search(opportunity_type="hackathons", per_page=1)
            ok(f"Unstop reachable in {int((time.monotonic() - started) * 1000)} ms ({res.total} open hackathons)")
        except UnstopError as exc:
            healthy = False
            fail(f"Cannot reach Unstop: {exc.message}")

        heading("Your account")
        for t in rt.sessions.list_tenants() or [DEFAULT_TENANT]:
            label = "" if t == DEFAULT_TENANT else f" [{t}]"
            try:
                p = await rt.client.profile(t)
                ok(f"Signed in{label} as {p.name or p.email or 'user'}")
            except AuthRequired:
                warn(f"Not signed in{label}. Run: unstop-mcp login")
            except UnstopError as exc:
                fail(f"Session problem{label}: {exc.message}")

        heading("AI apps")
        for app in detect_clients():
            if not app.detected:
                print(f"  - {app.name}: not installed" + (f" ({app.note})" if app.note else ""))
                continue
            if app.config_path is None:
                ok(f"{app.name}: found (connect with: unstop-mcp connect {app.key})")
                continue
            try:
                servers = json.loads(app.config_path.read_text(encoding="utf-8") or "{}").get("mcpServers", {})
            except (OSError, ValueError):
                servers = {}
            if SERVER_NAME in servers:
                ok(f"{app.name}: connected")
            else:
                warn(f"{app.name}: installed but not connected. Run: unstop-mcp connect {app.key}")

        heading("Server")
        keys = [k for k in rt.api_keys.list() if k.active]
        print(f"  version {__version__} · data in {settings.data_dir} · {len(keys)} active API key(s)")
        return 0 if healthy else 1
    finally:
        await rt.http.aclose()
