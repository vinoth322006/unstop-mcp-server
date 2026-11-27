"""v1.3: audit fixes (session cache, dead refresh tokens, cache isolation on account switch, corrupt key files,
CSRF transport errors, sign-in race) and new operations (notifications, courses, organisations, leaderboard,
closing soon, calendar file, sign out)."""

import asyncio
import json
import threading
import time
from datetime import datetime, timedelta

import httpx
import pytest

from unstop_mcp.auth.api_keys import ApiKeyStore
from unstop_mcp.auth.session import UnstopSession
from unstop_mcp.client import parse_organisation_id
from unstop_mcp.errors import InvalidInput, UpstreamError
from unstop_mcp.http import UnstopHTTP
from unstop_mcp.models import IST, notification
from unstop_mcp.server import OppType, RegType, build_server

from .conftest import raw_opportunity


def _sc(res):
    return getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)


def _login(rt, tenant="default", token="tok"):
    rt.sessions.put(tenant, UnstopSession(access_token=token, name="Asha", expires_at=time.time() + 3600))


# ---------------------------------------------------------------- audit fixes

def test_type_literals_match_model_constants():
    from typing import get_args

    from unstop_mcp.models import OPPORTUNITY_TYPES, REGISTRATION_TYPES

    assert set(get_args(OppType)) == set(OPPORTUNITY_TYPES)
    assert set(get_args(RegType)) == {"all", *REGISTRATION_TYPES}


def test_session_store_caches_but_sees_external_changes(runtime, monkeypatch):
    _login(runtime, token="one")
    calls = []
    real = runtime.sessions._fernet.decrypt
    monkeypatch.setattr(runtime.sessions._fernet, "decrypt", lambda b: calls.append(1) or real(b))
    for _ in range(5):
        assert runtime.sessions.get("default").access_token == "one"
    assert len(calls) == 1  # decrypted once, then served from memory
    other = type(runtime.sessions)(runtime.sessions.directory, runtime.sessions._fernet)
    time.sleep(0.01)
    other.put("default", UnstopSession(access_token="two-longer"))  # e.g. `unstop-mcp login` in another process
    assert runtime.sessions.get("default").access_token == "two-longer"


def test_session_store_returns_copies(runtime):
    _login(runtime)
    s = runtime.sessions.get("default")
    s.access_token = "mutated"
    assert runtime.sessions.get("default").access_token == "tok"


async def test_login_clears_previous_accounts_cache(runtime, mock_api):
    _login(runtime, token="old-account")
    route = mock_api.get("/api/user/my-watchlist").mock(
        side_effect=lambda req: httpx.Response(200, json={"data": {"data": [], "total": 0, "who":
                                                                   req.headers["Authorization"]}}))
    await runtime.client.watchlist("default", "all", 1, 10)
    mock_api.get("/api/user/profile").mock(return_value=httpx.Response(200, json={"data": {"id": 2}}))
    await runtime.auth.complete_login("default", UnstopSession(access_token="new-account"))
    await runtime.client.watchlist("default", "all", 1, 10)
    assert [c.request.headers["Authorization"] for c in route.calls] == ["Bearer old-account", "Bearer new-account"]


def test_api_keys_survive_corrupt_file(tmp_path):
    store = ApiKeyStore(tmp_path / "keys.json")
    key, _ = store.create("alice")
    assert store.lookup(key)
    time.sleep(0.01)
    (tmp_path / "keys.json").write_text("{ half-written")
    assert store.lookup(key) is not None  # last good key set keeps working


def test_damaged_secret_key_file_has_clear_message(tmp_path):
    from unstop_mcp.crypto import build_fernet

    (tmp_path / "k").write_bytes(b"not a key")
    with pytest.raises(ValueError, match="damaged"):
        build_fernet(None, tmp_path / "k")


async def test_csrf_refresh_transport_error_is_mapped(settings, mock_api):
    mock_api.get("/api/micro/oauth/v2/generate/csrf-cookie").mock(side_effect=httpx.ConnectError("down"))
    mock_api.post("/api/x").mock(return_value=httpx.Response(419))
    async with UnstopHTTP(settings) as http:
        with pytest.raises(UpstreamError, match="security token"):
            await http.request("POST", "/api/x", json_body={})


def test_browser_login_finish_is_race_free(runtime):
    from unstop_mcp.weblogin import BrowserLogin

    login = BrowserLogin(runtime.auth, "default", asyncio.new_event_loop(), timeout=5)
    wins = []
    threads = [threading.Thread(target=lambda i=i: wins.append(login._finish(f"n{i}"))) for i in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert wins.count(True) == 1 and login.result.done()


def test_rounds_tolerate_junk_and_keep_ids():
    from unstop_mcp.models import detail

    d = detail(raw_opportunity(rounds=["junk", None, {"id": "77", "details": [{"title": "Final"}]}]))
    assert [(r.id, r.title) for r in d.rounds] == [(77, "Final")]


def test_summary_exposes_organisation_id():
    from unstop_mcp.models import summarize

    assert summarize(raw_opportunity(organisation={"id": 2159613, "name": "X"})).organisation_id == 2159613


# ---------------------------------------------------------------- notifications & courses

NOTE = {"id": "abc", "type": "App\\Notifications\\Results\\ResultDeclarationNotification", "read_at": None,
        "created_at": "2026-11-01T10:00:00+05:30",
        "data": {"text": "<b>Results</b> are out for X", "actionUrl": "/hackathons/x-1/results"}}


def test_notification_normaliser():
    n = notification(NOTE)
    assert (n.kind, n.text, n.url, n.read) == ("result", "Results are out for X",
                                               "https://unstop.com/hackathons/x-1/results", False)
    assert notification({**NOTE, "type": "Weird", "data": {"text": "hi", "actionUrl": "javascript:alert(1)"}}).url is None


async def test_notifications_and_mark_read(settings, runtime, mock_api):
    _login(runtime)
    read = {**NOTE, "id": "r", "read_at": "2026-11-02"}
    route = mock_api.get("/api/get-notifications").mock(return_value=httpx.Response(200, json={"data": {
        "current_page": 1, "data": [NOTE, read], "next_page_url": "https://unstop.com/api/get-notifications?page=2"}}))
    mock_api.get("/api/markasread-notifications").mock(return_value=httpx.Response(200, json={"status": True}))
    mcp = build_server(settings, runtime)
    page = _sc(await mcp.call_tool("my_notifications", {}))
    assert page["has_more"] and page["unread_on_page"] == 1 and len(page["items"]) == 2
    assert len(_sc(await mcp.call_tool("my_notifications", {"unread_only": True}))["items"]) == 1
    assert route.call_count == 1  # second call served from the per-user cache
    assert _sc(await mcp.call_tool("mark_notifications_read", {}))["ok"] is True
    await mcp.call_tool("my_notifications", {})
    assert route.call_count == 2  # marking read invalidated the cached list


async def test_courses(runtime, mock_api):
    _login(runtime)
    mock_api.get("/api/user/enrolled-courses").mock(return_value=httpx.Response(200, json={"data": {
        "data": [{"id": 9, "course_id": 5, "title": "DSA", "module_percent": "40", "module_count": 10,
                  "cert_id": "c1", "lastVisitedModuleLink": "courses/dsa/m3", "public_url": "courses/dsa"}],
        "total": 1, "current_page": 1, "last_page": 1}}))
    [c] = await runtime.client.courses("default")
    assert (c.id, c.progress_percent, c.modules) == (5, 40, 10)
    assert c.certificate_url.endswith("/c1") and c.continue_url == "https://unstop.com/courses/dsa/m3"


# ---------------------------------------------------------------- public extras

@pytest.mark.parametrize("value,expected", [(2159613, 2159613), ("2159613", 2159613),
                                            ("https://unstop.com/c/nexora-navyug-2159613", 2159613),
                                            ("https://unstop.com/c/nexora-navyug-2159613?ref=x", 2159613)])
def test_parse_organisation_id(value, expected):
    assert parse_organisation_id(value) == expected


def test_parse_organisation_id_rejects_garbage():
    with pytest.raises(InvalidInput):
        parse_organisation_id("nexora")


async def test_get_organisation(runtime, mock_api):
    mock_api.get("/api/public/organisation/with-opportunity/2159613").mock(return_value=httpx.Response(200, json={
        "data": {"id": 2159613, "name": "NEXORA", "public_url": "c/nexora-2159613", "city": "Pune",
                 "country": "India", "description": "<p>We run <b>hackathons</b></p>"}}))
    org = await runtime.client.get_organisation("https://unstop.com/c/nexora-2159613")
    assert (org.name, org.location, org.about, org.url) == ("NEXORA", "Pune, India", "We run hackathons",
                                                            "https://unstop.com/c/nexora-2159613")


async def test_leaderboard_drops_private_fields(runtime, mock_api):
    mock_api.get("/api/public/gamification/get-paginated-leaderboard/global").mock(return_value=httpx.Response(
        200, json={"data": {"data": [{"rank": 1, "name": "A", "points": "99.5", "avatar": "x", "id": 5,
                                      "organisation_name": "IIT"}], "current_page": 1, "last_page": 9}}))
    lb = await runtime.client.leaderboard()
    assert lb.entries[0].model_dump(exclude_none=True) == {"rank": 1, "name": "A", "organisation": "IIT",
                                                            "points": 99.5}


async def test_closing_soon_filters_sorts_and_dedupes(runtime, mock_api):
    now = datetime.now(IST)

    def opp(oid, delta_days, **kw):
        return raw_opportunity(oid, regnRequirements={"end_regn_dt": (now + timedelta(days=delta_days)).isoformat()},
                               **kw)

    pages = {"1": [opp(1001, 5), opp(1002, 1), opp(1003, 40)], "2": [opp(1002, 1), opp(1004, -1)],
             "3": [opp(1005, 2, status="FINISHED")], "4": []}
    mock_api.get("/api/public/opportunity/search-result").mock(side_effect=lambda req: httpx.Response(
        200, json={"data": {"data": pages[req.url.params["page"]], "total": 99, "current_page": 1, "last_page": 4}}))
    res = await runtime.client.closing_soon(days=7)
    assert [o.id for o in res.results] == [1002, 1001]


# ---------------------------------------------------------------- calendar file & sign out

async def test_save_deadlines_calendar(settings, runtime, mock_api, tmp_path, monkeypatch):
    _login(runtime)
    (tmp_path / "Downloads").mkdir()
    monkeypatch.setattr("unstop_mcp.tools.account.downloads_dir", lambda: tmp_path / "Downloads")
    empty = {"data": {"data": [], "total": 0, "current_page": 1, "last_page": 1}}
    for path in ("/api/user/my-rounds", "/api/user/registered-opportunities", "/api/user/my-watchlist"):
        mock_api.get(path).mock(return_value=httpx.Response(200, json=empty))
    mcp = build_server(settings, runtime)
    out = _sc(await mcp.call_tool("save_deadlines_calendar", {"file_name": "mine.ics"}))
    assert out["saved"] and (tmp_path / "Downloads" / "mine.ics").read_text().startswith("BEGIN:VCALENDAR")
    from mcp.server.mcpserver.exceptions import ToolError

    for bad in ("../../evil.ics", "x.exe", "a/b.ics"):
        with pytest.raises(ToolError):
            await mcp.call_tool("save_deadlines_calendar", {"file_name": bad})


async def test_sign_out_tool(settings, runtime, mock_api):
    _login(runtime)
    mock_api.get("/api/logout").mock(return_value=httpx.Response(200, json={}))
    mcp = build_server(settings, runtime)
    assert _sc(await mcp.call_tool("sign_out", {}))["signed_out"] is True
    assert runtime.sessions.get("default") is None
    assert _sc(await mcp.call_tool("sign_out", {}))["signed_out"] is False


async def test_tool_count_and_unique_names(settings, runtime):
    tools = await build_server(settings, runtime).list_tools()
    names = [t.name for t in tools]
    assert len(names) == len(set(names)) == 41
    for t in tools:  # every tool must explain itself to the model
        assert t.description and len(t.description) > 30, t.name
    json.dumps([t.model_dump(mode="json") for t in tools])  # schemas serialise cleanly
