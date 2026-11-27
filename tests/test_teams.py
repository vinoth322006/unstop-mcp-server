"""Team tools: view, suggestions (privacy), inbox, invites, responses, removal, leaving, and hand-off messages."""

import json
import time

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from unstop_mcp.auth.session import UnstopSession
from unstop_mcp.server import build_server
from unstop_mcp.teams import invitation, mask_email

from .conftest import raw_opportunity

OPP, TEAM = 1829674, 70000001
ME, MATE = 7585045, 999


def _player(pid, uid, leader, name):
    return {"id": pid, "user_id": uid, "player_type": 1 if leader else 2, "name": name,
            "organisation": {"name": "SKCET"}, "course_specialization": "CSE", "passing_out_year": 2027,
            "mobile": "9999999999", "email": f"{name.lower()}@example.com"}


def _boot(players, max_size=2, invites=True):
    team = {"id": TEAM, "team_name": "rockets", "regi_status": "complete", "isTeamValid": "1",
            "invite_allowed": "1", "players": players} if players else None
    return {"oRegisteredTeam": team, "invitations_allowed": invites,
            "regnRequirements": {"max_team_size": max_size, "min_team_size": 1}, "user": {}}


@pytest.fixture
def mcp_and_mocks(settings, runtime, mock_api):
    runtime.sessions.put("default", UnstopSession(access_token="tok", user_id=ME, email="me@example.com",
                                                  expires_at=time.time() + 3600))

    def setup(boot):
        mock_api.get(f"/api/registration/restricted/{OPP}/").mock(
            return_value=httpx.Response(200, json={"status": True, "data": boot}))
        mock_api.get("/api/user/profile").mock(return_value=httpx.Response(200, json={"data": {"id": ME}}))
        mock_api.get(f"/api/public/competition/{OPP}").mock(
            return_value=httpx.Response(200, json={"data": {"competition": raw_opportunity(OPP)}}))
        return build_server(settings, runtime)

    return setup, mock_api


def _sc(res):
    return getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)


# ---------------------------------------------------------------- reads

async def test_my_team(mcp_and_mocks):
    setup, _ = mcp_and_mocks
    mcp = setup(_boot([_player(1, ME, True, "Me"), _player(2, MATE, False, "Mate")], max_size=4))
    team = _sc(await mcp.call_tool("my_team", {"opportunity": str(OPP)}))
    assert team["you_are_leader"] and team["spots_left"] == 2 and team["invites_allowed"]
    assert [(m["name"], m["is_leader"], m["is_you"]) for m in team["members"]] == [("Me", True, True),
                                                                                   ("Mate", False, False)]
    assert "9999999999" not in json.dumps(team) and "@" not in json.dumps(team)  # no phones or emails


async def test_suggestions_hide_contact_details(mcp_and_mocks):
    setup, mock_api = mcp_and_mocks
    mcp = setup(_boot([_player(1, ME, True, "Me")]))
    mock_api.get(f"/api/registration/previousTeams-player/{OPP}/{TEAM}").mock(return_value=httpx.Response(200, json={
        "data": [{"id": 501, "name": "Priya", "email": "priya@example.com", "mobile": "8888888888",
                  "organisation": {"name": "PSG"}, "aadhaar_no": "X"},
                 {"id": 502, "name": "Me", "email": "me@example.com"}]}))  # current members are filtered out
    out = _sc(await mcp.call_tool("suggest_teammates", {"opportunity": str(OPP)}))
    items = out["result"] if isinstance(out, dict) and "result" in out else out
    assert [i["name"] for i in items] == ["Priya"] and items[0]["teammate_id"] == 501
    blob = json.dumps(items)
    assert "priya@" not in blob and "8888888888" not in blob and "aadhaar" not in blob


async def test_inbox_maps_lists_and_status(mcp_and_mocks):
    setup, mock_api = mcp_and_mocks
    mcp = setup(_boot([_player(1, ME, True, "Me")]))
    base = "/api/registration"
    mock_api.get(f"{base}/team/target/getAll/invitation/{OPP}").mock(return_value=httpx.Response(200, json={
        "data": {"outgoingInvitation": [{"id": 11, "status": 0, "email": "friend@example.com"}]}}))
    mock_api.get(f"{base}/team/source/getAll/invitation/{OPP}").mock(return_value=httpx.Response(200, json={
        "data": {"incomingInvitation": [{"id": 12, "status": 0, "target_team": {"team_name": "Blue"},
                                         "source_player": {"name": "Ravi"}}]}}))
    mock_api.get(f"{base}/team/target/getAll/request/{OPP}").mock(return_value=httpx.Response(200, json={
        "data": {"incomingRequets": [{"id": 13, "status": 2}]}}))
    mock_api.get(f"{base}/user/getAll/request/{OPP}").mock(return_value=httpx.Response(200, json={"data": []}))
    inbox = _sc(await mcp.call_tool("team_invitations", {"opportunity": str(OPP)}))
    assert inbox["invitations_sent"][0] == {**inbox["invitations_sent"][0], "id": 11, "status": "pending",
                                            "person": "fr***@example.com"}
    assert inbox["invitations_received"][0]["team_name"] == "Blue" and inbox["invitations_received"][0]["person"] == "Ravi"
    assert inbox["join_requests_received"][0]["status"] == "declined" and inbox["join_requests_sent"] == []


def test_invitation_and_mask_helpers():
    assert mask_email("priya.k@example.com") == "pr***@example.com" and mask_email(None) is None
    assert invitation({"status": 0}, "sent") is None  # no id -> skipped
    assert invitation({"id": "5", "status": "7"}, "sent").status == "unknown (7)"


# ---------------------------------------------------------------- writes

async def test_invite_by_email_sends_exact_request(mcp_and_mocks):
    setup, mock_api = mcp_and_mocks
    mcp = setup(_boot([_player(1, ME, True, "Me")]))
    route = mock_api.post("/api/registration/send-invitation-request-by-email").mock(
        return_value=httpx.Response(200, json={"status": True, "message": "Invitation sent"}))
    out = _sc(await mcp.call_tool("invite_teammate", {"opportunity": str(OPP), "email": "friend@example.com"}))
    assert out["ok"] and json.loads(route.calls[0].request.content) == {"targetTeamId": TEAM,
                                                                        "email": "friend@example.com"}


async def test_invite_by_teammate_id_resolves_email_server_side(mcp_and_mocks):
    setup, mock_api = mcp_and_mocks
    mcp = setup(_boot([_player(1, ME, True, "Me")]))
    mock_api.get(f"/api/registration/previousTeams-player/{OPP}/{TEAM}").mock(return_value=httpx.Response(
        200, json={"data": [{"id": 501, "name": "Priya", "email": "priya@example.com"}]}))
    route = mock_api.post("/api/registration/send-invitation-request-by-email").mock(
        return_value=httpx.Response(200, json={"status": True}))
    out = _sc(await mcp.call_tool("invite_teammate", {"opportunity": str(OPP), "teammate_id": 501}))
    assert "Priya" in out["message"] and "priya@" not in out["message"]
    assert json.loads(route.calls[0].request.content)["email"] == "priya@example.com"


@pytest.mark.parametrize(
    "boot,args,expect",
    [
        (_boot([_player(1, ME, True, "Me"), _player(2, MATE, False, "Mate")], max_size=2), {"email": "x@example.com"},
         "already full"),
        (_boot([_player(1, ME, True, "Me")], max_size=1), {"email": "x@example.com"}, "solo event"),
        (_boot([_player(1, ME, True, "Me")], invites=False), {"email": "x@example.com"}, "doesn't allow"),
        (_boot([_player(1, ME, True, "Me")]), {"email": "me@example.com"}, "invite yourself"),
        (_boot([_player(1, ME, True, "Me")]), {"email": "bad"}, "valid email"),
        (_boot([_player(1, ME, True, "Me")]), {}, "either an email"),
        (_boot([]), {"email": "x@example.com"}, "not registered"),
    ],
)
async def test_invite_guards_never_call_unstop(mcp_and_mocks, boot, args, expect):
    setup, mock_api = mcp_and_mocks
    mcp = setup(boot)
    route = mock_api.post("/api/registration/send-invitation-request-by-email").mock(
        return_value=httpx.Response(200, json={"status": True}))
    with pytest.raises(ToolError, match=expect):
        await mcp.call_tool("invite_teammate", {"opportunity": str(OPP), **args})
    assert route.call_count == 0


async def test_unstop_rejection_becomes_hand_off_message(mcp_and_mocks):
    setup, mock_api = mcp_and_mocks
    mcp = setup(_boot([_player(1, ME, True, "Me")]))
    mock_api.post("/api/registration/send-invitation-request-by-email").mock(
        return_value=httpx.Response(200, json={"status": False, "message": "User is already in another team"}))
    with pytest.raises(ToolError) as err:
        await mcp.call_tool("invite_teammate", {"opportunity": str(OPP), "email": "x@example.com"})
    msg = str(err.value)
    assert "Can't do this automatically: Unstop said: User is already in another team" in msg
    assert "do it yourself on unstop.com: https://unstop.com/" in msg


@pytest.mark.parametrize("tool,args,method,path", [
    ("cancel_invitation", {"invitation_id": 11}, "POST", "/api/registration/invitation/team/delete/11"),
    ("respond_to_invitation", {"invitation_id": 12, "accept": True}, "POST", "/api/registration/invitation/accept/12"),
    ("respond_to_invitation", {"invitation_id": 12, "accept": False}, "POST", "/api/registration/invitation/decline/12"),
    ("respond_to_join_request", {"request_id": 13, "accept": True}, "POST", "/api/registration/request/accept/13"),
    ("respond_to_join_request", {"request_id": 13, "accept": False}, "POST", "/api/registration/request/decline/13"),
])
async def test_invitation_responses_hit_exact_endpoints(mcp_and_mocks, tool, args, method, path):
    setup, mock_api = mcp_and_mocks
    mcp = setup(_boot([_player(1, ME, True, "Me")]))
    route = mock_api.request(method, path).mock(return_value=httpx.Response(200, json={"status": True}))
    assert _sc(await mcp.call_tool(tool, args))["ok"]
    assert route.call_count == 1


async def test_remove_member_and_leave(mcp_and_mocks):
    setup, mock_api = mcp_and_mocks
    mcp = setup(_boot([_player(1, ME, True, "Me"), _player(2, MATE, False, "Mate")], max_size=4))
    route = mock_api.delete(f"/api/registration/delete/player/{OPP}/2").mock(
        return_value=httpx.Response(200, json={"status": True}))
    out = _sc(await mcp.call_tool("remove_team_member", {"opportunity": str(OPP), "player_id": 2}))
    assert out["ok"] and "Mate" in out["message"] and route.call_count == 1
    for args, expect in (({"player_id": 1}, "remove yourself"), ({"player_id": 77}, "isn't on your team")):
        with pytest.raises(ToolError, match=expect):
            await mcp.call_tool("remove_team_member", {"opportunity": str(OPP), **args})
    with pytest.raises(ToolError, match="team leader"):  # leaders withdraw via cancel_registration
        await mcp.call_tool("leave_team", {"opportunity": str(OPP)})


async def test_member_can_leave_but_not_remove(mcp_and_mocks):
    setup, mock_api = mcp_and_mocks
    mcp = setup(_boot([_player(1, MATE, True, "Lead"), _player(2, ME, False, "Me")], max_size=4))
    route = mock_api.delete(f"/api/registration/delete/player/{OPP}/2").mock(
        return_value=httpx.Response(200, json={"status": True}))
    with pytest.raises(ToolError, match="only the team leader"):
        await mcp.call_tool("remove_team_member", {"opportunity": str(OPP), "player_id": 1})
    assert _sc(await mcp.call_tool("leave_team", {"opportunity": str(OPP)}))["ok"] and route.call_count == 1
