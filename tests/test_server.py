"""End-to-end tests through the MCP layer: tool calls in-process, and the HTTP app with API-key auth."""

import json
import time

import httpx
import pytest
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError
from starlette.testclient import TestClient

from unstop_mcp.auth.api_keys import SCOPE_READ, SCOPE_WRITE
from unstop_mcp.auth.session import UnstopSession
from unstop_mcp.server import build_server

from .conftest import mock_live_lists, raw_opportunity


def _structured(result):
    return result.structured_content if hasattr(result, "structured_content") else result.structuredContent


def _page(items, total=None):
    return {"data": {"data": items, "total": total or len(items), "current_page": 1, "last_page": 1, "per_page": 10}}


async def test_search_tool(settings, runtime, mock_api):
    route = mock_api.get("/api/public/opportunity/search-result").mock(
        return_value=httpx.Response(200, json=_page([raw_opportunity(1), raw_opportunity(2)], total=191))
    )
    mcp = build_server(settings, runtime)
    out = _structured(await mcp.call_tool("search_opportunities", {"query": "ai", "opportunity_type": "hackathons",
                                                                  "payment": "free"}))
    assert out["total"] == 191 and len(out["results"]) == 2
    params = dict(route.calls[0].request.url.params)
    assert params["searchTerm"] == "ai" and params["opportunity"] == "hackathons"
    assert params["payment"] == "unpaid" and params["oppstatus"] == "open"


async def test_search_validates_input(settings, runtime):
    mcp = build_server(settings, runtime)
    with pytest.raises(ToolError):
        await mcp.call_tool("search_opportunities", {"opportunity_type": "spaceships"})
    with pytest.raises(ToolError):
        await mcp.call_tool("search_opportunities", {"per_page": 500})


async def test_get_opportunity_tool_by_url(settings, runtime, mock_api):
    mock_api.get("/api/public/competition/1817824").mock(
        return_value=httpx.Response(200, json={"data": {"competition": raw_opportunity()}})
    )
    mcp = build_server(settings, runtime)
    out = _structured(await mcp.call_tool("get_opportunity", {"opportunity": "https://unstop.com/hackathons/x-1817824"}))
    assert out["id"] == 1817824 and out["rounds"][0]["title"] == "Round 1"


async def test_not_found_is_clean_tool_error(settings, runtime, mock_api):
    mock_api.get("/api/public/competition/5555").mock(return_value=httpx.Response(404, text="<html>"))
    mcp = build_server(settings, runtime)
    with pytest.raises(ToolError, match="Not found"):
        await mcp.call_tool("get_opportunity", {"opportunity": "5555"})


async def test_account_tool_without_login(settings, runtime):
    mcp = build_server(settings, runtime)
    with pytest.raises(ToolError, match="unstop-mcp login"):
        await mcp.call_tool("my_watchlist", {})
    status = _structured(await mcp.call_tool("auth_status", {}))
    assert status["logged_in"] is False


# Shapes below mirror real Unstop account responses (values are made up).
REG_ITEM = {
    "id": 1677472, "title": "Far Away ", "type": "hackathons", "public_url": "hackathons/far-away-1677472",
    "seo_url": "https://unstop.com/hackathons/far-away-1677472", "status": "FINISHED",
    "start_date": "2026-06-05T21:51:00+05:30", "end_date": "2026-10-02T08:56:00+05:30",
    "end_regn_dt": "2026-05-23 00:00:00+05:30", "max_team_size": 5, "userRejectedRoundStatus": False,
    "organisation": {"id": 9, "name": "Zuup"},
    "players_registration": [{"id": 1, "email": "teammate@example.com", "player_valid": 1}],
    "registered_teams": [{"team_name": "Rockets", "isTeamValid": "1", "regi_status": "complete",
                          "created_at": "2026-05-01T10:00:00+05:30",
                          "registeredBy": {"name": "Someone", "email": "lead@example.com"}}],
}
CERT_ITEM = {
    "id": 77, "cert_id": "e8f00", "certificate_type": "winners", "certificate_url": None, "title": None,
    "sent_at": "2026-07-01 10:00:00",
    "certData": {"event": "Far Away", "organiser": "Zuup", "team": "Rockets", "team_name_visibiilty": True,
                 "winnerString": "First Runner Up", "rankString": None},
    "round_details": {"title": "Grand Finale", "opportunity": [{"title": "Far Away"}]},
}


def _round(order, registered, status="FINISHED", participated=None):
    return {"round_order": order, "start_date": "2026-06-05 21:51:00", "end_date": "2026-06-17 21:15:00",
            "status": status, "details": [{"title": f"Round {order}"}],
            "play_status": {"round_status": status, "registered": registered, "participated": participated,
                            "can_play": False, "can_play_msg": "", "opportunity_title": "Far Away",
                            "opportunity_url": "hackathons/far-away-1677472",
                            "player": {"name": "private", "organisation": "private"}}}


def _login(runtime):
    runtime.sessions.put("default", UnstopSession(access_token="tok", expires_at=time.time() + 3600))


async def test_registrations_tool(settings, runtime, mock_api):
    mock_live_lists(mock_api)
    _login(runtime)
    route = mock_api.get("/api/user/registered-opportunities").mock(
        return_value=httpx.Response(200, json=_page([REG_ITEM], total=58))
    )
    mcp = build_server(settings, runtime)
    out = _structured(await mcp.call_tool("my_registrations", {"opportunity_type": "hackathons"}))
    item = out["items"][0]
    assert out["total"] == 58
    assert item["title"] == "Far Away" and item["team_name"] == "Rockets"
    assert item["registration_complete"] is True and item["team_valid"] is True and item["team_members"] == 1
    assert "@" not in json.dumps(out)  # teammates' emails never leave the server
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer tok" and req.url.params["filterValue"] == "hackathons"


async def test_registrations_all_sends_no_filter(settings, runtime, mock_api):
    mock_live_lists(mock_api)
    _login(runtime)
    route = mock_api.get("/api/user/registered-opportunities").mock(
        return_value=httpx.Response(200, json=_page([REG_ITEM]))
    )
    await build_server(settings, runtime).call_tool("my_registrations", {})
    assert "filterName" not in route.calls[0].request.url.params


async def test_watchlist_sends_required_filter(settings, runtime, mock_api):
    _login(runtime)
    route = mock_api.get("/api/user/my-watchlist").mock(
        return_value=httpx.Response(200, json=_page([raw_opportunity()], total=14))
    )
    out = _structured(await build_server(settings, runtime).call_tool("my_watchlist", {}))
    assert out["total"] == 14 and out["items"][0]["title"] == "PromptWars"
    params = route.calls[0].request.url.params
    assert params["filterName"] == "type" and params["filterValue"] == "all"


async def test_certificates_tool(settings, runtime, mock_api):
    _login(runtime)
    mock_api.get("/api/user/certificates").mock(return_value=httpx.Response(200, json=_page([CERT_ITEM])))
    out = _structured(await build_server(settings, runtime).call_tool("my_certificates", {}))
    cert = out["items"][0]
    assert cert["event"] == "Far Away" and cert["achievement"] == "First Runner Up" and cert["round"] == "Grand Finale"
    assert cert["url"] == "https://unstop.com/certificate-preview/e8f00"


@pytest.mark.parametrize(
    "rounds,expected",
    [
        ([_round(1, True), _round(2, True, participated=False)], True),
        ([_round(1, False, "LIVE"), _round(2, False, "NOT_STARTED")], False),  # job listing, never applied
        ([], False),
    ],
)
async def test_participation_tool(settings, runtime, mock_api, rounds, expected):
    mock_live_lists(mock_api)
    _login(runtime)
    mock_api.get("/api/user/check-opportunity-participation/1677472").mock(
        return_value=httpx.Response(200, json={"data": rounds})
    )
    out = _structured(await build_server(settings, runtime).call_tool("my_participation", {"opportunity": "1677472"}))
    assert out["registered"] is expected
    assert len(out["rounds"]) == len(rounds)
    assert "private" not in json.dumps(out)  # the nested player record is not exposed


async def test_auth_status_never_leaks_tokens(settings, runtime):
    runtime.sessions.put("default", UnstopSession(access_token="SECRET", refresh_token="RSECRET",
                                                  expires_at=time.time() + 3600))
    mcp = build_server(settings, runtime)
    out = _structured(await mcp.call_tool("auth_status", {}))
    assert out["logged_in"] and "SECRET" not in json.dumps(out)


async def test_write_scope_enforced(settings, runtime, monkeypatch):
    runtime.sessions.put("alice", UnstopSession(access_token="tok", expires_at=time.time() + 3600))
    token = AccessToken(token="k", client_id="alice", scopes=[SCOPE_READ])
    monkeypatch.setattr("unstop_mcp.tools._common.get_access_token", lambda: token)
    mcp = build_server(settings, runtime)
    with pytest.raises(ToolError, match="unstop:write"):
        await mcp.call_tool("add_to_watchlist", {"opportunity": "1817824"})


async def test_write_tool_uses_callers_tenant(settings, runtime, mock_api, monkeypatch):
    runtime.sessions.put("alice", UnstopSession(access_token="alice-tok", expires_at=time.time() + 3600))
    runtime.sessions.put("bob", UnstopSession(access_token="bob-tok", expires_at=time.time() + 3600))
    token = AccessToken(token="k", client_id="bob", scopes=[SCOPE_READ, SCOPE_WRITE])
    monkeypatch.setattr("unstop_mcp.tools._common.get_access_token", lambda: token)
    route = mock_api.get("/api/addToWatchlist/1817824/opportunity").mock(
        return_value=httpx.Response(200, json={"status": True})
    )
    mcp = build_server(settings, runtime)
    out = _structured(await mcp.call_tool("add_to_watchlist", {"opportunity": "1817824"}))
    assert out["watchlisted"] is True
    assert route.calls[0].request.headers["Authorization"] == "Bearer bob-tok"


async def test_write_tools_can_be_disabled(settings, runtime):
    settings.enable_write_tools = False
    mcp = build_server(settings, runtime)
    names = {t.name for t in await mcp.list_tools()}
    assert "add_to_watchlist" not in names and "search_opportunities" in names


# ---------------------------------------------------------------- HTTP transport + API keys

def _http_client(settings, runtime):
    settings.transport = "http"
    mcp = build_server(settings, runtime)
    app = mcp.streamable_http_app(streamable_http_path=settings.path)
    return TestClient(app, base_url="http://127.0.0.1:8000")


INIT = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "test", "version": "1"}},
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_http_requires_api_key(settings, runtime):
    with _http_client(settings, runtime) as client:
        assert client.get("/healthz").json()["status"] == "ok"
        r = client.post("/mcp", json=INIT, headers=HEADERS)
        assert r.status_code == 401
        assert "www-authenticate" in {k.lower() for k in r.headers}
        r = client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": "Bearer usk_wrong"})
        assert r.status_code == 401


def test_http_accepts_valid_api_key(settings, runtime):
    key, _ = runtime.api_keys.create("default")
    with _http_client(settings, runtime) as client:
        r = client.post("/mcp", json=INIT, headers={**HEADERS, "Authorization": f"Bearer {key}"})
        assert r.status_code == 200, r.text
        assert "unstop" in r.text
