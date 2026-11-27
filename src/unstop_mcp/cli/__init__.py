"""Command-line entry point: ``unstop-mcp <command>``.

Human-facing commands print to stdout with friendly formatting; ``serve`` keeps stdout for the MCP protocol.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

from unstop_mcp import __version__
from unstop_mcp.auth.api_keys import ALL_SCOPES, SCOPE_READ
from unstop_mcp.auth.session import DEFAULT_TENANT
from unstop_mcp.cli._ui import WELCOME, _c, fail
from unstop_mcp.cli.account import _deadlines, _inbox, _login, _logout, _me, _status
from unstop_mcp.cli.discover import _alerts, _closing, _search
from unstop_mcp.cli.keys import cmd_keys
from unstop_mcp.cli.serve import cmd_serve
from unstop_mcp.cli.setup import TOOLSETS_HELP, _doctor, _setup, cmd_connect
from unstop_mcp.logging_setup import configure_logging


def _run(coro_fn: Any) -> Any:
    return lambda a: asyncio.run(coro_fn(a))


def build_parser() -> argparse.ArgumentParser:
    from unstop_mcp.models import OPPORTUNITY_TYPES

    p = argparse.ArgumentParser(
        prog="unstop-mcp",
        description="Unstop for AI assistants. Start with:  unstop-mcp setup",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"unstop-mcp {__version__}")
    p.add_argument("--data-dir", dest="data_dir", help="Where sessions and keys are stored")
    sub = p.add_subparsers(dest="cmd", metavar="command")

    st = sub.add_parser("setup", help="Guided one-time setup: sign in and connect your AI apps")
    st.add_argument("--yes", "-y", action="store_true", help="Accept all defaults without asking")
    st.add_argument("--skip-login", action="store_true")
    st.add_argument("--email")
    st.add_argument("--clients", help="Comma list: claude-desktop,claude-code,cursor,windsurf")
    st.add_argument("--toolsets", help=TOOLSETS_HELP)
    st.set_defaults(func=_run(_setup))

    se = sub.add_parser("search", help="Search Unstop from the terminal")
    se.add_argument("query", nargs="*")
    se.add_argument("--type", default="all", choices=list(OPPORTUNITY_TYPES))
    se.add_argument("--sort", default="relevance", choices=["relevance", "prize", "deadline"])
    se.add_argument("--payment", default="all", choices=["free", "paid", "all"])
    se.add_argument("--limit", type=int, default=10, choices=range(1, 31), metavar="1-30")
    se.add_argument("--json", action="store_true")
    se.set_defaults(func=_run(_search))

    dl = sub.add_parser("deadlines", help="Your upcoming rounds and registration deadlines")
    dl.add_argument("--days", type=int, default=30)
    dl.add_argument("--ics", metavar="FILE", help="Save as a calendar file instead of printing")
    dl.add_argument("--json", action="store_true")
    dl.set_defaults(func=_run(_deadlines))

    lg = sub.add_parser("login", help="Sign in to Unstop with a one-time code")
    lg.add_argument("--tenant", default=DEFAULT_TENANT)
    lg.add_argument("--email")
    lg.add_argument("--channel", choices=["email", "whatsapp"], default="email")
    lg.add_argument("--password", action="store_true", help="Use your password instead of a code")
    lg.add_argument("--browser", action="store_true", help="Sign in on a page in your browser")
    lg.set_defaults(func=_run(_login))

    al = sub.add_parser("alerts", help="New listings for your saved searches (add/remove searches too)")
    al.add_argument("query", nargs="*", help="Keywords (with --add)")
    al.add_argument("--add", metavar="NAME", help="Save a search under this name")
    al.add_argument("--type", default="all", choices=list(OPPORTUNITY_TYPES))
    al.add_argument("--remove", metavar="NAME")
    al.add_argument("--json", action="store_true")
    al.set_defaults(func=_run(_alerts))

    ib = sub.add_parser("inbox", help="Your Unstop notifications")
    ib.add_argument("--unread", action="store_true")
    ib.add_argument("--page", type=int, default=1)
    ib.add_argument("--json", action="store_true")
    ib.set_defaults(func=_run(_inbox))

    cl = sub.add_parser("closing", help="Open listings whose registration closes soon")
    cl.add_argument("query", nargs="*")
    cl.add_argument("--days", type=int, default=7, choices=range(1, 31), metavar="1-30")
    cl.add_argument("--type", default="all", choices=list(OPPORTUNITY_TYPES))
    cl.add_argument("--limit", type=int, default=20)
    cl.add_argument("--json", action="store_true")
    cl.set_defaults(func=_run(_closing))

    me = sub.add_parser("me", help="Your Unstop at a glance: registrations, wins, next deadline")
    me.add_argument("--json", action="store_true")
    me.set_defaults(func=_run(_me))

    lo = sub.add_parser("logout", help="Sign out and delete the stored session")
    lo.add_argument("--tenant", default=DEFAULT_TENANT)
    lo.set_defaults(func=_run(_logout))

    co = sub.add_parser("connect", help="Add Unstop to an AI app (or remove it with --remove)")
    co.add_argument("app", choices=["all", "claude-desktop", "claude-code", "cursor", "windsurf"])
    co.add_argument("--remove", action="store_true")
    co.add_argument("--toolsets", help=TOOLSETS_HELP)
    co.set_defaults(func=cmd_connect)

    dr = sub.add_parser("doctor", help="Check connection, sign-in and AI app setup")
    dr.set_defaults(func=_run(_doctor))

    sa = sub.add_parser("status", help="Session details as JSON (no secrets)")
    sa.add_argument("--tenant")
    sa.set_defaults(func=_run(_status))

    s = sub.add_parser("serve", help="Run the MCP server (AI apps do this for you)")
    s.add_argument("--transport", choices=["stdio", "http"])
    s.add_argument("--host")
    s.add_argument("--port", type=int)
    s.add_argument("--public-url", dest="public_url")
    s.set_defaults(func=cmd_serve)

    k = sub.add_parser("keys", help="API keys for remote (HTTP) clients")
    ksub = k.add_subparsers(dest="keys_cmd", required=True)
    kc = ksub.add_parser("create")
    kc.add_argument("--tenant", default=DEFAULT_TENANT, help="Unstop session this key acts as")
    kc.add_argument("--scopes", default=SCOPE_READ, help=f"Comma-separated: {','.join(ALL_SCOPES)}")
    kc.add_argument("--label")
    kc.add_argument("--ttl-days", dest="ttl_days", type=int)
    ksub.add_parser("list")
    kr = ksub.add_parser("revoke")
    kr.add_argument("key_id")
    k.set_defaults(func=cmd_keys)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        if sys.stdin.isatty():
            if getattr(sys, "frozen", False):
                # Double-clicked standalone .exe: run the guided setup and keep the window open at the end.
                configure_logging("WARNING", as_json=False)
                try:
                    return int(_run(_setup)(argparse.Namespace(
                        cmd="setup", yes=False, skip_login=False, email=None, clients=None, data_dir=None)) or 0)
                finally:
                    try:
                        input("\nPress Enter to close this window.")
                    except EOFError:
                        pass
            # A person ran it by hand: show a guide instead of silently waiting for MCP messages.
            print(WELCOME.format(title=_c("1;36", "Unstop MCP"), version=__version__))
            return 0
        args.cmd, args.func = "serve", cmd_serve  # an AI app launched us over stdio
    if args.cmd != "serve":
        configure_logging("WARNING", as_json=False)
    try:
        return int(args.func(args) or 0)
    except ValueError as exc:
        fail(str(exc))
        return 2
    except KeyboardInterrupt:
        print()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
