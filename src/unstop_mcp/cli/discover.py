"""Public commands: `search`, `closing` and saved-search `alerts`."""
from __future__ import annotations

import argparse

from unstop_mcp.auth.session import DEFAULT_TENANT
from unstop_mcp.cli._ui import _c, _runtime, _settings, _short_date, fail, ok, warn
from unstop_mcp.errors import UnstopError


async def _search(args: argparse.Namespace) -> int:
    rt = _runtime(_settings(args))
    try:
        res = await rt.client.search(query=" ".join(args.query) or None, opportunity_type=args.type,
                                     sort=args.sort, per_page=args.limit, payment=args.payment)
        if args.json:
            print(res.model_dump_json(indent=2))
            return 0
        print(f"\n{res.total:,} results" + (f" for {' '.join(args.query)!r}" if args.query else "") + "\n")
        for i, o in enumerate(res.results, 1):
            prize = f" · ₹{o.total_cash_prize:,.0f}" if o.total_cash_prize else ""
            team = f" · team {o.team_size}" if o.team_size else ""
            print(f"{_c('1', f'{i:>2}. {o.title}')}  {_c('2', o.organisation or '')}")
            print(f"    {o.type} · closes {_short_date(o.registration_deadline)} ({o.time_left or '-'}){prize}{team}")
            print(f"    {_c('34', o.url or '')}")
        return 0
    except UnstopError as exc:
        fail(exc.message)
        return 1
    finally:
        await rt.http.aclose()


async def _closing(args: argparse.Namespace) -> int:
    rt = _runtime(_settings(args))
    try:
        res = await rt.client.closing_soon(days=args.days, opportunity_type=args.type, query=" ".join(args.query) or None)
        if args.json:
            print(res.model_dump_json(indent=2))
            return 0
        print(f"\n{res.total} open listing(s) closing within {args.days} day(s)\n")
        for o in res.results[: args.limit]:
            print(f"  {_c('1', _short_date(o.registration_deadline))}  {o.title}  {_c('2', o.organisation or '')}")
            print(f"              {o.type} · {o.time_left or ''}  {_c('34', o.url or '')}")
        return 0
    except UnstopError as exc:
        fail(exc.message)
        return 1
    finally:
        await rt.http.aclose()


async def _alerts(args: argparse.Namespace) -> int:
    rt = _runtime(_settings(args))
    try:
        if args.add:
            from unstop_mcp.searches import SavedSearch

            res = await rt.client.save_search(DEFAULT_TENANT, SavedSearch(
                name=args.add, query=" ".join(args.query) or None, opportunity_type=args.type))
            ok(f"Saved '{res.name}' ({res.new_count} open listings right now). New ones will show up in "
               "`unstop-mcp alerts`.")
            return 0
        if args.remove:
            rt.client.delete_search(DEFAULT_TENANT, args.remove)
            ok(f"Deleted '{args.remove}'.")
            return 0
        if not rt.client.list_searches(DEFAULT_TENANT):
            print('\n  No saved searches yet. Add one:\n    unstop-mcp alerts --add "AI hackathons" AI --type hackathons\n')
            return 0
        report = await rt.client.check_searches(DEFAULT_TENANT)
        if args.json:
            print(report.model_dump_json(indent=2))
            return 0
        print(f"\n{report.total_new} new listing(s)\n")
        for s in report.searches:
            print(f"  {_c('1', s.name)}: {s.new_count} new")
            for o in s.new[:10]:
                print(f"    • {o.title}  ({o.time_left or _short_date(o.registration_deadline)})  {_c('34', o.url or '')}")
        for name, err in report.errors.items():
            warn(f"{name}: {err}")
        return 0
    except UnstopError as exc:
        fail(exc.message)
        return 1
    finally:
        await rt.http.aclose()
