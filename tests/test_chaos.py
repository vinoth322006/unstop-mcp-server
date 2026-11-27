"""Chaos + fuzz: no tool may ever crash.

Every one of the 41 tools is called while Unstop answers with each kind of broken response (server errors, HTML,
empty bodies, wrong JSON shapes, network failure), and with hostile inputs. A tool may succeed or raise a clean
ToolError, but it must never fall through to the generic "Internal error" (an unhandled exception) and the server
must stay usable afterwards.
"""

from __future__ import annotations

import time

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from unstop_mcp.auth.session import UnstopSession
from unstop_mcp.server import build_server

OPP = "1829674"

# Minimal valid arguments for every tool.
ARGS: dict[str, dict] = {
    "search_opportunities": {"query": "ai"},
    "get_opportunity": {"opportunity": OPP},
    "compare_opportunities": {"opportunities": [OPP, "1817798"]},
    "auth_status": {},
    "sign_in": {},
    "check_eligibility": {"opportunity": OPP},
    "my_snapshot": {},
    "save_search": {"name": "chaos", "query": "ai"},
    "check_saved_searches": {},
    "list_saved_searches": {},
    "delete_saved_search": {"name": "chaos"},
    "my_profile": {},
    "my_deadlines": {},
    "recommended_for_me": {},
    "my_registrations": {},
    "my_participation": {"opportunity": OPP},
    "my_watchlist": {},
    "my_certificates": {},
    "add_to_watchlist": {"opportunity": OPP},
    "remove_from_watchlist": {"opportunity": OPP},
    "closing_soon": {"days": 3},
    "get_organisation": {"organisation": "2159613"},
    "unstop_leaderboard": {},
    "my_notifications": {},
    "my_courses": {},
    "save_deadlines_calendar": {"file_name": "chaos-test.ics"},
    "mark_notifications_read": {},
    "sign_out": {},
    "prepare_registration": {"opportunity": OPP},
    "register_for_opportunity": {"opportunity": OPP, "confirmation_token": "9999999999.000000000000000000000000"},
    "cancel_registration": {"opportunity": OPP},
    "my_team": {"opportunity": OPP},
    "suggest_teammates": {"opportunity": OPP},
    "team_invitations": {"opportunity": OPP},
    "invite_teammate": {"opportunity": OPP, "email": "friend@example.com"},
    "cancel_invitation": {"invitation_id": 11},
    "respond_to_invitation": {"invitation_id": 12, "accept": False},
    "respond_to_join_request": {"request_id": 13, "accept": False},
    "remove_team_member": {"opportunity": OPP, "player_id": 2},
    "leave_team": {"opportunity": OPP},
    "server_status": {},
}

SKIP_SIDE_EFFECTS = {"sign_in"}  # would open a real browser window

BROKEN = {
    "500": lambda req: httpx.Response(500, text="oops"),
    "502-html": lambda req: httpx.Response(502, text="<html>Bad gateway</html>", headers={"content-type": "text/html"}),
    "200-html": lambda req: httpx.Response(200, text="<html>maintenance</html>", headers={"content-type": "text/html"}),
    "200-empty": lambda req: httpx.Response(200, content=b""),
    "200-null": lambda req: httpx.Response(200, json=None),
    "200-list": lambda req: httpx.Response(200, json=[1, "two", None]),
    "200-wrong-shape": lambda req: httpx.Response(200, json={"data": "unexpected string", "status": True}),
    "200-nested-junk": lambda req: httpx.Response(200, json={"data": {"data": [None, 5, "x", {"id": None}],
                                                                       "competition": [], "oRegisteredTeam": "x",
                                                                       "total": "many", "current_page": "one"}}),
    "200-bad-types": lambda req: httpx.Response(200, json={"data": {"data": [{"id": "abc", "title": 7,
                                                                              "regnRequirements": "nope",
                                                                              "organisation": "str", "prizes": "none",
                                                                              "filters": {"a": 1}}],
                                                                     "competition": {"id": "x1", "title": None,
                                                                                     "rounds": "none", "prizes": 5}}}),
    "401": lambda req: httpx.Response(401, json={"message": "Unauthenticated."}),
    "429": lambda req: httpx.Response(429, json={"message": "slow down"}),
    "network-down": "network",
}


@pytest.fixture
def chaos_server(settings, runtime, tmp_path, monkeypatch):
    settings.max_retries = 0
    settings.breaker_threshold = 10_000  # keep the breaker out of the way; it has its own tests
    settings.client_rate_limit_per_minute = 100_000
    monkeypatch.setattr("unstop_mcp.tools.account.downloads_dir", lambda: tmp_path / "Downloads")
    (tmp_path / "Downloads").mkdir()

    def make():
        runtime.sessions.put("default", UnstopSession(access_token="tok", refresh_token="r", user_id=1,
                                                      email="me@example.com", expires_at=time.time() + 3600))
        runtime.http.cache.clear()
        return build_server(settings, runtime)

    return make


def _call_all_kinds(mock_api, mode):
    behaviour = BROKEN[mode]
    if behaviour == "network":
        mock_api.route().mock(side_effect=httpx.ConnectError("unreachable"))
    else:
        mock_api.route().mock(side_effect=behaviour)


async def test_every_tool_is_covered(chaos_server):
    names = {t.name for t in await chaos_server().list_tools()}
    assert names == set(ARGS), f"missing args for: {names ^ set(ARGS)}"


@pytest.mark.parametrize("mode", list(BROKEN))
async def test_no_tool_crashes_on_broken_upstream(chaos_server, mock_api, mode):
    _call_all_kinds(mock_api, mode)
    crashes = []
    for name, args in ARGS.items():
        if name in SKIP_SIDE_EFFECTS:
            continue
        mcp = chaos_server()
        try:
            await mcp.call_tool(name, args)
        except ToolError as exc:
            if "Internal error" in str(exc):
                crashes.append(f"{name}: {exc.__cause__!r}")
        except Exception as exc:  # anything that escapes the ToolGuard is a crash too
            crashes.append(f"{name}: escaped {exc!r}")
    assert not crashes, f"[{mode}] tools crashed:\n" + "\n".join(crashes)


HOSTILE_STRINGS = ["", " ", "0", "-1", "99999999999999999999", "1e9", "../../etc/passwd", "https://evil.example/x-123",
                   "'; DROP TABLE x;--", "<script>alert(1)</script>", "\x00\x01", "🙂" * 50, "a" * 299,
                   "https://unstop.com/hackathons/", "javascript:alert(1)", "%00", "unstop.com/o/rWFUSQv"]


@pytest.mark.parametrize("value", HOSTILE_STRINGS)
async def test_hostile_ids_never_crash_or_reach_unstop_unsafely(chaos_server, mock_api, value):
    route = mock_api.route().mock(return_value=httpx.Response(404))
    mcp = chaos_server()
    for name, args in ARGS.items():
        targets = [k for k in ("opportunity", "organisation") if k in args]
        if not targets or name in SKIP_SIDE_EFFECTS:
            continue
        try:
            await mcp.call_tool(name, {**args, **{k: value for k in targets}})
        except ToolError as exc:
            assert "Internal error" not in str(exc), f"{name}({value!r}) crashed: {exc.__cause__!r}"
    for call in route.calls:  # whatever got through must stay on unstop.com /api/ paths with a numeric id
        assert call.request.url.host == "unstop.com"
        assert ".." not in call.request.url.path and "<" not in call.request.url.path


@pytest.mark.parametrize("args", [
    {"query": "x" * 5000}, {"page": 0}, {"page": -5}, {"per_page": 0}, {"per_page": 10_000},
    {"opportunity_type": "spaceships"}, {"sort": "random"}, {"status": None},
])
async def test_search_rejects_bad_arguments_cleanly(chaos_server, mock_api, args):
    mock_api.route().mock(return_value=httpx.Response(200, json={"data": {"data": []}}))
    with pytest.raises(ToolError) as err:
        await chaos_server().call_tool("search_opportunities", args)
    assert "Internal error" not in str(err.value)


async def test_server_stays_healthy_after_chaos(chaos_server, mock_api):
    mock_api.route().mock(side_effect=lambda req: httpx.Response(500))
    mcp = chaos_server()
    for _ in range(3):
        with pytest.raises(ToolError):
            await mcp.call_tool("get_opportunity", {"opportunity": OPP})
    mock_api.reset()
    mock_api.routes.clear()
    mock_api.route().mock(return_value=httpx.Response(200, json={"data": {"data": [], "total": 0}}))
    res = await mcp.call_tool("search_opportunities", {"query": "ok"})
    assert res is not None


# ---------------------------------------------------------------- regressions found by this pass

def test_source_has_no_control_characters():
    """An invisible backspace once slipped into a regex ("\b" in a normal string) and silently disabled it."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent / "src"
    bad = [(str(f.relative_to(root)), n) for f in root.rglob("*.py")
           for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
           if any(ord(c) < 32 and c != "\t" for c in line)]
    assert bad == []


def test_one_day_left_wording():
    from unstop_mcp.models import summarize

    from .conftest import raw_opportunity

    raw = raw_opportunity(regnRequirements={"remain_days": "1 days left", "end_regn_dt": "2099-01-01T00:00:00+05:30"})
    assert summarize(raw).time_left == "1 day left"
    raw["regnRequirements"]["remain_days"] = "11 days left"
    assert summarize(raw).time_left == "11 days left"


async def test_bad_records_are_skipped_not_fatal(runtime, mock_api):
    from .conftest import raw_opportunity

    good = raw_opportunity(1001)
    junk = [None, 5, {"id": "abc"}, {"id": -3, "title": "neg"}, {"title": "no id"}, {**raw_opportunity(1002), "prizes": 7}]
    mock_api.get("/api/public/opportunity/search-result").mock(return_value=httpx.Response(
        200, json={"data": {"data": [good, *junk], "total": "lots", "current_page": None, "last_page": "x"}}))
    res = await runtime.client.search(per_page=10)
    assert [r.id for r in res.results] == [1001, 1002]  # 1002 survives a junk prizes field
    assert res.total == 2 and res.last_page == 1


def test_unix_files_have_lf_line_endings():
    """A CR in get.sh/install.sh breaks `curl ... | sh` on macOS/Linux; in the Dockerfile it breaks builds."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    files = [root / n for n in ("get.sh", "install.sh", "Dockerfile", "docker-compose.yml", "pyproject.toml")]
    files += [f for d in ("src", "tests", "packaging") for f in (root / d).rglob("*.py")]
    bad = [str(f.relative_to(root)) for f in files if b"\r" in f.read_bytes()]
    assert bad == [], f"Windows line endings in: {bad}"
