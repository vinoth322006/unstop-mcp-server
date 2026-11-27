"""Registration: gates, payload, confirmation tokens, and the full prepare -> register -> cancel flow (mocked)."""

import json
import time

import httpx
import pytest

from unstop_mcp.auth.session import UnstopSession
from unstop_mcp.errors import InvalidInput
from unstop_mcp.registration import build_payload, check_token, evaluate, make_token, summary_of
from unstop_mcp.server import build_server

from .conftest import raw_opportunity

OID = 1829321

PROFILE = {"id": 7, "name": "Asha K", "first_name": "Asha", "last_name": "K", "email": "a@b.com", "mobile": "9876543210",
           "gender": "F", "mobile_verified_at": "2024-01-01", "email_verified_at": "2024-01-01",
           "organisation": {"id": 55, "name": "IIT", "logo": "x"}, "course_specialization": "CSE",
           "passing_out_year": 2099, "aadhaar_no": "SECRET-ID", "otp_code_email": None}


def _boot(**req_over):
    req = {"min_team_size": 1, "max_team_size": 1, "extendRegForm": 0, "extendedFormData": None, "consent_needed": 0,
           "verified_aadhaar": 0, "proctoring": {}, "verified_mobile": 1, "verified_email": 1,
           "player_extended_form": {"resume_field": {"enabled": False, "customFields": [{"mandatory": -1}]}},
           "core_req_fields": {"name": {"mandatory": True}, "email": {"mandatory": True},
                               "mobile_no": {"mandatory": True}, "gender": {"mandatory": False}}}
    req.update(req_over)
    return {"oRegisteredTeam": None, "regnRequirements": req, "linkedPayment": False, "extendedForm": False,
            "user_restricted_to_register": False,
            "user": {"first_name": "Asha", "last_name": "K", "email": "a@b.com", "mobile": "9876543210", "gender": "F",
                     "organisation": {"id": 55, "name": "IIT"}, "passing_out_year": 2099}}


def _opp(**over):
    return raw_opportunity(OID, **{"paid": 0, "regn_url": None, **over})


# ---------------------------------------------------------------- gates

def test_simple_solo_event_has_no_blockers():
    blockers, notes = evaluate(_boot(), PROFILE, _opp())
    assert blockers == [] and notes == []


@pytest.mark.parametrize(
    "boot_over,req_over,opp_over,expect",
    [
        ({"linkedPayment": True}, {}, {}, "fee"),
        ({}, {"enable_payment": 1}, {}, "fee"),
        ({}, {}, {"paid": 1}, "fee"),
        ({}, {"extendRegForm": 1}, {}, "extra questions"),
        ({}, {"player_extended_form": {"resume_field": {"enabled": True}}}, {}, "extra questions"),
        ({}, {"player_extended_form": {"q": {"customFields": [{"mandatory": 1}]}}}, {}, "extra questions"),
        ({}, {"consent_needed": 1}, {}, "consent"),
        ({}, {"verified_aadhaar": 1}, {}, "Aadhaar"),
        ({}, {"proctoring": {"face": True}}, {}, "proctored"),
        ({}, {"min_team_size": 3, "max_team_size": 4}, {}, "team of at least 3"),
        ({"user_restricted_to_register": True, "user_restricted_to_register_message": "Cool-off period"}, {}, {},
         "Cool-off"),
        ({}, {}, {"regn_url": "https://example.org/apply"}, "organiser's own website"),
        ({}, {}, {"status": "FINISHED"}, "closed"),
    ],
)
def test_blockers(boot_over, req_over, opp_over, expect):
    boot = _boot(**req_over)
    boot.update(boot_over)
    blockers, _ = evaluate(boot, PROFILE, _opp(**opp_over))
    assert any(expect.lower() in b.lower() for b in blockers), blockers


def test_unverified_mobile_and_missing_profile_fields_block():
    blockers, _ = evaluate(_boot(), {**PROFILE, "mobile_verified_at": None, "mobile": None}, _opp())
    assert any("verified mobile" in b for b in blockers) and any("missing your mobile" in b for b in blockers)


def test_optional_team_is_a_note_not_a_blocker():
    blockers, notes = evaluate(_boot(min_team_size=1, max_team_size=4), PROFILE, _opp())
    assert blockers == [] and "up to 4" in notes[0]


# ---------------------------------------------------------------- payload

def test_payload_mirrors_site_and_never_subscribes():
    body = build_payload(_boot(), PROFILE, None)
    player = body["team"]["players"][0]
    assert body["subscription"] == 0 and body["team"]["subscription"] == 0 and player["subscription"] == 0
    assert player["user_id"] == 7 and player["id"] == 0 and player["player_type"] == 1
    assert player["organisation"] == {"id": 55, "name": "IIT"} and player["organisation_id"] == 55
    assert "aadhaar_no" not in json.dumps(body) and "otp_code" not in json.dumps(body)  # only whitelisted fields


def test_summary_masks_mobile():
    s = summary_of(build_payload(_boot(), PROFILE, "Rockets"))
    assert s["mobile"] == "98******10" and s["team_name"] == "Rockets" and s["newsletter_subscription"] is False


# ---------------------------------------------------------------- tokens

def test_token_round_trip_and_binding():
    tok = make_token("alice", OID)
    check_token(tok, "alice", OID)
    for tenant, oid in (("bob", OID), ("alice", OID + 1)):
        with pytest.raises(InvalidInput, match="different"):
            check_token(tok, tenant, oid)


def test_token_expiry_and_garbage():
    tok = make_token("alice", OID, now=time.time() - 3600)
    with pytest.raises(InvalidInput, match="expired"):
        check_token(tok, "alice", OID)
    for bad in ("", "nope", "123.abc", "x.y"):
        with pytest.raises(InvalidInput):
            check_token(bad, "alice", OID)


# ---------------------------------------------------------------- full flow (mocked Unstop)

def _mock_unstop(mock_api, boot, opp=None, create=None, cancel=None):
    mock_api.get(f"/api/registration/restricted/{OID}/").mock(return_value=httpx.Response(200, json={"status": True,
                                                                                                     "data": boot}))
    mock_api.get("/api/user/profile").mock(return_value=httpx.Response(200, json={"data": PROFILE}))
    mock_api.get(f"/api/public/competition/{OID}").mock(
        return_value=httpx.Response(200, json={"data": {"competition": opp or _opp()}}))
    routes = {}
    if create is not None:
        routes["create"] = mock_api.post(f"/api/registration/team/{OID}/create").mock(
            return_value=httpx.Response(200, json=create))
    if cancel is not None:
        routes["cancel"] = mock_api.delete(f"/api/registration/cancel/{OID}/999").mock(
            return_value=httpx.Response(200, json=cancel))
    return routes


def _sc(res):
    return getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)


@pytest.fixture
def signed_in(runtime):
    runtime.sessions.put("default", UnstopSession(access_token="tok", expires_at=time.time() + 3600))
    return runtime


async def test_prepare_then_register(settings, signed_in, mock_api):
    routes = _mock_unstop(mock_api, _boot(), create={"status": True, "message": "Registered!", "data": {
        "oRegisteredTeam": {"id": 999, "regn_id": "R-1", "regi_status": "complete"}}})
    mcp = build_server(settings, signed_in)
    plan = _sc(await mcp.call_tool("prepare_registration", {"opportunity": str(OID)}))
    assert plan["can_register"] and plan["confirmation_token"] and plan["will_submit"]["name"] == "Asha K"
    assert "create" in routes and routes["create"].call_count == 0  # preparing changes nothing

    res = _sc(await mcp.call_tool("register_for_opportunity", {"opportunity": str(OID),
                                                               "confirmation_token": plan["confirmation_token"]}))
    assert res == {**res, "registered": True, "team_id": 999, "registration_id": "R-1", "complete": True}
    sent = json.loads(routes["create"].calls[0].request.content)
    assert sent["team"]["players"][0]["email"] == "a@b.com" and sent["subscription"] == 0
    assert routes["create"].calls[0].request.headers["Authorization"] == "Bearer tok"


async def test_register_requires_valid_token(settings, signed_in, mock_api):
    routes = _mock_unstop(mock_api, _boot(), create={"status": True, "data": {}})
    mcp = build_server(settings, signed_in)
    from mcp.server.mcpserver.exceptions import ToolError

    for token in ("forged.000000000000", make_token("default", OID + 1)):
        with pytest.raises(ToolError):
            await mcp.call_tool("register_for_opportunity", {"opportunity": str(OID), "confirmation_token": token})
    assert routes["create"].call_count == 0


async def test_register_rechecks_gates(settings, signed_in, mock_api):
    """A listing that became paid between prepare and register must not be submitted."""
    routes = _mock_unstop(mock_api, {**_boot(), "linkedPayment": True}, create={"status": True, "data": {}})
    mcp = build_server(settings, signed_in)
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="fee"):
        await mcp.call_tool("register_for_opportunity", {"opportunity": str(OID),
                                                         "confirmation_token": make_token("default", OID)})
    assert routes["create"].call_count == 0


async def test_unstop_rejection_is_reported(settings, signed_in, mock_api):
    _mock_unstop(mock_api, _boot(), create={"status": False, "message": "Team name already taken"})
    mcp = build_server(settings, signed_in)
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="Team name already taken"):
        await mcp.call_tool("register_for_opportunity", {"opportunity": str(OID),
                                                         "confirmation_token": make_token("default", OID)})


async def test_blocked_and_already_registered(settings, signed_in, mock_api):
    _mock_unstop(mock_api, _boot(min_team_size=2, max_team_size=4))
    plan = await signed_in.client.prepare_registration("default", OID)
    assert not plan.can_register and plan.confirmation_token is None and "team of at least 2" in plan.blockers[0]
    mock_api.reset()
    _mock_unstop(mock_api, {**_boot(), "oRegisteredTeam": {"id": 999, "regn_id": "R-1"}})
    signed_in.http.cache.clear()
    plan = await signed_in.client.prepare_registration("default", OID)
    assert plan.already_registered and not plan.can_register


async def test_ineligible_profile_blocks(signed_in, mock_api):
    opp = _opp(regnRequirements={"eligibility": '{"studentPassoutYearsSelected": [2020]}',
                                 "end_regn_dt": "2099-01-01T00:00:00+05:30"})
    _mock_unstop(mock_api, _boot(), opp=opp)
    plan = await signed_in.client.prepare_registration("default", OID)
    assert not plan.can_register and any("eligible" in b.lower() for b in plan.blockers)


async def test_cancel(settings, signed_in, mock_api):
    routes = _mock_unstop(mock_api, {**_boot(), "oRegisteredTeam": {"id": 999}},
                          cancel={"status": True, "message": "Registration cancelled"})
    res = _sc(await build_server(settings, signed_in).call_tool("cancel_registration", {"opportunity": str(OID)}))
    assert res["registered"] is False and res["message"] == "Registration cancelled"
    assert routes["cancel"].call_count == 1


async def test_write_tools_hidden_when_disabled(settings, signed_in):
    settings.enable_write_tools = False
    names = {t.name for t in await build_server(settings, signed_in).list_tools()}
    assert "prepare_registration" in names and "register_for_opportunity" not in names


# ---------------------------------------------------------------- regressions found during the live test

async def test_participation_uses_team_record_when_no_rounds(signed_in, mock_api):
    """Unstop returns no rounds for events whose rounds aren't published; the team record still says registered."""
    from .conftest import mock_live_lists

    mock_api.get(f"/api/user/check-opportunity-participation/{OID}").mock(
        return_value=httpx.Response(200, json={"data": []}))
    mock_live_lists(mock_api, team={"id": 70000001, "team_name": "me", "regn_id": "X-1", "regi_status": "complete"})
    p = await signed_in.client.participation("default", OID)
    assert (p.registered, p.team_id, p.registration_id, p.registration_complete) == (True, 70000001, "X-1", True)


async def test_registrations_include_new_team_missing_from_index(signed_in, mock_api):
    """The registrations list is a lagging search index; brand-new teams are added from the live team list."""
    from .conftest import mock_live_lists

    old = {"id": 1001, "title": "Old", "type": "hackathons", "end_regn_dt": "2026-01-01",
           "registered_teams": [{"regi_status": "complete", "created_at": "2026-06-01T10:00:00+05:30"}]}
    mock_api.get("/api/user/registered-opportunities").mock(return_value=httpx.Response(200, json={
        "data": {"data": [old], "total": 1, "current_page": 1, "last_page": 1}}))
    teams = [{"id": 9, "opportunity_id": OID, "team_name": "me", "regi_status": "complete", "isTeamValid": "1",
              "created_at": "2026-11-27T09:40:38+05:30"},
             {"id": 8, "opportunity_id": 1001, "created_at": "2026-06-01T10:00:00+05:30"}]
    mock_api.get(f"/api/public/competition/{OID}").mock(  # before the helper's catch-all 404
        return_value=httpx.Response(200, json={"data": {"competition": _opp(type="hackathons")}}))
    mock_live_lists(mock_api, teams=teams)
    page = await signed_in.client.registrations("default", "all", 1, 10)
    assert [r.id for r in page.items] == [OID, 1001] and page.total == 2
    assert page.items[0].registration_complete is True
    quizzes = await signed_in.client.registrations("default", "quizzes", 1, 10)
    assert OID not in [r.id for r in quizzes.items]  # type filter respected


async def test_typed_registrations_do_not_fetch_other_types(signed_in, mock_api):
    """A quizzes page must compare against the newest registration of ANY type, so newer hackathon teams are not
    treated as missing (that once made my_snapshot fetch ~80 listings)."""
    from .conftest import mock_live_lists

    quiz = {"id": 2001, "title": "Old quiz", "type": "quizzes",
            "registered_teams": [{"regi_status": "complete", "created_at": "2024-01-01T10:00:00+05:30"}]}
    newest_any = {"id": 2002, "title": "Recent hackathon", "type": "hackathons",
                  "registered_teams": [{"created_at": "2026-11-20T10:00:00+05:30"}]}

    def regs(request):
        typed = request.url.params.get("filterValue") == "quizzes"
        return httpx.Response(200, json={"data": {"data": [quiz] if typed else [newest_any], "total": 1,
                                                  "current_page": 1, "last_page": 1}})

    mock_api.get("/api/user/registered-opportunities").mock(side_effect=regs)
    teams = [{"id": 1, "opportunity_id": 2002, "created_at": "2026-11-20T10:00:00+05:30"},
             {"id": 2, "opportunity_id": 3003, "created_at": "2025-05-05T10:00:00+05:30"}]  # older than baseline
    detail_route = mock_api.get(url__regex=r"/api/public/competition/\d+$").mock(return_value=httpx.Response(404))
    mock_live_lists(mock_api, teams=teams)
    page = await signed_in.client.registrations("default", "quizzes", 1, 10)
    assert [r.id for r in page.items] == [2001]
    assert detail_route.call_count == 0  # nothing newer than the overall baseline -> no detail fetches
