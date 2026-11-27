"""Account commands: login/logout/status, `me`, `inbox` and `deadlines`."""
from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import time
from pathlib import Path
from typing import Any

from unstop_mcp.auth.session import DEFAULT_TENANT, validate_tenant
from unstop_mcp.cli._ui import _c, _runtime, _settings, _short_date, fail, ok, warn
from unstop_mcp.errors import AuthRequired, UnstopError


async def _do_login(rt: Any, tenant: str, email: str | None, channel: str, use_password: bool) -> bool:
    email = email or (await asyncio.to_thread(input, "  Your Unstop email: ")).strip()
    if not email or "@" not in email:
        fail("That doesn't look like an email address.")
        return False
    try:
        if use_password:
            password = getpass.getpass("  Unstop password (hidden): ")
            session = await rt.auth.password_login(email, password)
        else:
            ok(await rt.auth.send_otp(email, channel=channel))
            for attempt in range(3):
                code = getpass.getpass(f"  Enter the code Unstop sent you by {channel} (hidden while typing): ")
                try:
                    session = await rt.auth.verify_otp(email, code, channel=channel)
                    break
                except UnstopError as exc:
                    fail(exc.message + ("" if attempt == 2 else " Try again."))
                    if attempt == 2:
                        return False
        session = await rt.auth.complete_login(tenant, session)
    except UnstopError as exc:
        fail(f"Login failed: {exc.message}")
        return False
    days = int((session.expires_at - time.time()) / 86400) if session.expires_at else None
    ok(f"Signed in as {session.name or session.email or 'your account'}"
       + (f" (session valid {days} days, renews automatically)" if days and session.refresh_token else ""))
    return True


async def _browser_login(rt: Any, tenant: str) -> bool:
    from unstop_mcp.weblogin import BrowserLogin

    login = BrowserLogin(rt.auth, tenant, asyncio.get_running_loop())
    url = login.start(open_browser=True)
    print(f"  A sign-in page opened in your browser. If it didn't, open:\n    {_c('34', url)}")
    print("  Waiting for you to finish (Ctrl+C to cancel)...")
    try:
        name = await asyncio.wrap_future(login.result)
    finally:
        login.stop()
    if name:
        ok(f"Signed in as {name}")
        return True
    fail("The sign-in page expired. Run the command again.")
    return False


async def _login(args: argparse.Namespace) -> int:
    settings = _settings(args)
    rt = _runtime(settings)
    try:
        tenant = validate_tenant(args.tenant)
        if args.browser:
            return 0 if await _browser_login(rt, tenant) else 1
        return 0 if await _do_login(rt, tenant, args.email, args.channel, args.password) else 1
    finally:
        await rt.http.aclose()


async def _logout(args: argparse.Namespace) -> int:
    rt = _runtime(_settings(args))
    try:
        removed = await rt.auth.logout(validate_tenant(args.tenant))
        (ok if removed else warn)("Signed out." if removed else f"No stored session for '{args.tenant}'.")
        return 0
    finally:
        await rt.http.aclose()


async def _status(args: argparse.Namespace) -> int:
    rt = _runtime(_settings(args))
    try:
        tenants = [args.tenant] if args.tenant else (rt.sessions.list_tenants() or [DEFAULT_TENANT])
        report = {}
        for t in tenants:
            try:
                session = await rt.auth.get_session(t)
                report[t] = {"logged_in": True, **session.public_view()}
            except UnstopError as exc:
                report[t] = {"logged_in": False, "detail": exc.message}
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        await rt.http.aclose()


async def _me(args: argparse.Namespace) -> int:
    rt = _runtime(_settings(args))
    try:
        s = await rt.client.snapshot(DEFAULT_TENANT)
        if args.json:
            print(s.model_dump_json(indent=2))
            return 0
        print(f"\n{_c('1', s.name or 'You')}  ·  {s.status or ''} · class of {s.graduation_year or '?'} · "
              f"profile {s.profile_completion_percent or 0}% complete\n")
        print(f"  Registrations  {s.total_registrations}  " + "  ".join(f"{k} {v}" for k, v in
                                                                        s.registrations_by_type.items()))
        print(f"  Certificates   {s.certificates_total}  (wins: {s.wins})")
        print(f"  Watchlist      {s.watchlist_total}")
        print(f"  Coins          {s.coins if s.coins is not None else '-'}")
        nd = s.next_deadline
        print(f"  Next deadline  {f'{_short_date(nd.when)} · {nd.what}: {nd.opportunity}' if nd else 'none in 30 days'}\n")
        return 0
    except AuthRequired:
        fail("Sign in first:  unstop-mcp login --browser")
        return 1
    except UnstopError as exc:
        fail(exc.message)
        return 1
    finally:
        await rt.http.aclose()


async def _inbox(args: argparse.Namespace) -> int:
    rt = _runtime(_settings(args))
    try:
        page = await rt.client.notifications(DEFAULT_TENANT, args.page, args.unread)
        if args.json:
            print(page.model_dump_json(indent=2))
            return 0
        print(f"\nNotifications (page {page.page}){' · unread only' if args.unread else ''}\n")
        for n in page.items:
            dot = _c("34", "●") if not n.read else " "
            print(f"  {dot} {_short_date(n.at)}  {n.text[:110]}")
            if n.url:
                print(f"               {_c('2', n.url)}")
        if not page.items:
            print("  Nothing here.")
        if page.has_more:
            print(f"\n  More: unstop-mcp inbox --page {page.page + 1}")
        return 0
    except AuthRequired:
        fail("Sign in first:  unstop-mcp login --browser")
        return 1
    except UnstopError as exc:
        fail(exc.message)
        return 1
    finally:
        await rt.http.aclose()


async def _deadlines(args: argparse.Namespace) -> int:
    from unstop_mcp.ics import deadlines_to_ics

    rt = _runtime(_settings(args))
    try:
        dl = await rt.client.deadlines(DEFAULT_TENANT, args.days)
        if args.ics:
            await asyncio.to_thread(Path(args.ics).write_text, deadlines_to_ics(dl), encoding="utf-8", newline="")
            ok(f"Saved {dl.total} event(s) to {args.ics}. Import it into Google Calendar / Outlook / Apple Calendar.")
            return 0
        if args.json:
            print(dl.model_dump_json(indent=2))
            return 0
        print(f"\nNext {args.days} days: {dl.total} item(s)\n")
        if not dl.items:
            print("  Nothing due. Find something new:  unstop-mcp search --type hackathons\n")
        for it in dl.items:
            urgent = it.days_left <= 3
            when = _short_date(it.when)
            print(f"  {_c('31' if urgent else '1', when)}  {it.what}: {_c('1', it.opportunity)}")
            print(f"            {it.action}  {_c('34', it.url or '')}")
        for e in dl.partial_errors:
            warn(f"Could not load {e}")
        return 0
    except AuthRequired:
        fail("Sign in first:  unstop-mcp login")
        return 1
    except UnstopError as exc:
        fail(exc.message)
        return 1
    finally:
        await rt.http.aclose()
