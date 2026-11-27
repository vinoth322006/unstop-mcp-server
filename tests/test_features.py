"""Deadlines aggregation, calendar export, recommendations, compare, registration-open logic, dates."""

import time
from datetime import datetime, timedelta

import httpx
import pytest

from unstop_mcp.auth.session import UnstopSession
from unstop_mcp.errors import InvalidInput
from unstop_mcp.ics import deadlines_to_ics
from unstop_mcp.models import IST, parse_dt, summarize

from .conftest import mock_live_lists, raw_opportunity


def _iso(delta_days: float, naive: bool = False) -> str:
    dt = datetime.now(IST) + timedelta(days=delta_days)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if naive else dt.isoformat()


def _page(items):
    return {"data": {"data": items, "total": len(items), "current_page": 1, "last_page": 1}}


@pytest.mark.parametrize(
    "value,expected_hour",
    [
        ("2026-12-12T23:59:00+05:30", 23),
        ("2026-05-23 00:00:00+05:30", 0),
        ("2026-06-05 21:51:00", 21),  # naive = IST
        ("2026-11-26 17:38:46 GMT+0530", 17),
    ],
)
def test_parse_dt_formats(value, expected_hour):
    dt = parse_dt(value)
    assert dt is not None and dt.astimezone(IST).hour == expected_hour


def test_parse_dt_garbage():
    assert parse_dt("soon") is None and parse_dt(None) is None and parse_dt("") is None


@pytest.mark.parametrize(
    "over,expected",
    [
        ({}, True),
        ({"status": "FINISHED"}, False),  # Unstop leaves regn_open=1 on finished listings
        ({"is_expired": True}, False),
        ({"regn_open": 0}, False),
        ({"regnRequirements": {"end_regn_dt": "2020-01-01T00:00:00+05:30"}}, False),
    ],
)
def test_registration_open_logic(over, expected):
    assert summarize(raw_opportunity(**over)).registration_open is expected


async def test_deadlines_aggregates_sources(runtime, mock_api):
    mock_live_lists(mock_api)
    runtime.sessions.put("default", UnstopSession(access_token="tok", expires_at=time.time() + 3600))

    def rounds(request):
        status = request.url.params["filterValue"]
        if status == "live":
            return httpx.Response(200, json=_page([{
                "opportunity_id": 1, "opp_title": "Live Hack", "opp_url": "hackathons/live-1",
                "round_order": 2, "start_date": _iso(-1, naive=True), "end_date": _iso(2, naive=True),
                "entity": {"title": "Round 2: Build"}}]))
        return httpx.Response(200, json=_page([{
            "opportunity_id": 2, "opp_title": "Quiz Night", "opp_url": "quizzes/q-2", "round_order": 1,
            "start_date": _iso(5), "end_date": _iso(6), "entity": {"title": "Round 1"}},
            {"opportunity_id": 3, "opp_title": "Far Future", "start_date": _iso(400), "end_date": _iso(401)}]))

    mock_api.get("/api/user/my-rounds").mock(side_effect=rounds)
    mock_api.get("/api/user/registered-opportunities").mock(return_value=httpx.Response(200, json=_page([
        {"id": 10, "title": "Unfinished", "type": "hackathons", "end_regn_dt": _iso(1),
         "registered_teams": [{"regi_status": "incomplete"}]},
        {"id": 11, "title": "Done", "type": "hackathons", "end_regn_dt": _iso(1),
         "registered_teams": [{"regi_status": "complete"}]},
    ])))
    mock_api.get("/api/user/my-watchlist").mock(return_value=httpx.Response(200, json=_page([
        raw_opportunity(20, regnRequirements={"end_regn_dt": _iso(3)}),
        raw_opportunity(21, status="FINISHED"),
    ])))

    dl = await runtime.client.deadlines("default", days=30)
    kinds = [(i.source, i.kind, i.opportunity) for i in dl.items]
    assert kinds == [
        ("incomplete_registration", "registration_closes", "Unfinished"),
        ("my_round", "round_ends", "Live Hack"),
        ("watchlist", "registration_closes", "PromptWars"),
        ("my_round", "round_starts", "Quiz Night"),
    ]
    assert dl.items[1].url == "https://unstop.com/hackathons/live-1" and dl.items[1].what == "Round 2: Build ends"
    assert dl.partial_errors == []

    ics = deadlines_to_ics(dl)
    assert ics.count("BEGIN:VEVENT") == 4 and ics.endswith("END:VCALENDAR\r\n")
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


async def test_deadlines_degrades_when_a_source_fails(runtime, mock_api):
    mock_live_lists(mock_api)
    runtime.sessions.put("default", UnstopSession(access_token="tok", expires_at=time.time() + 3600))
    runtime.settings.max_retries = 0
    mock_api.get("/api/user/my-rounds").mock(return_value=httpx.Response(500))
    mock_api.get("/api/user/registered-opportunities").mock(return_value=httpx.Response(200, json=_page([])))
    mock_api.get("/api/user/my-watchlist").mock(return_value=httpx.Response(200, json=_page([])))
    dl = await runtime.client.deadlines("default")
    assert dl.total == 0 and len(dl.partial_errors) == 2


def test_ics_escapes_special_characters():
    from unstop_mcp.models import DeadlineItem, Deadlines

    item = DeadlineItem(when=_iso(1), days_left=1, kind="registration_closes", what="Closes",
                        action="Do it, now; really\nnext line", opportunity="A, B; C", url="https://x",
                        source="watchlist", opportunity_id=1)
    ics = deadlines_to_ics(Deadlines(generated_at=_iso(0), window_days=7, total=1, items=[item]))
    assert "A\\, B\\; C" in ics and "\\n" in ics


async def test_recommendations(runtime, mock_api):
    runtime.sessions.put("default", UnstopSession(access_token="tok", expires_at=time.time() + 3600))
    route = mock_api.get("/api/opportunity/recommendations").mock(
        return_value=httpx.Response(200, json=_page([raw_opportunity(i) for i in range(1, 16)]))
    )
    res = await runtime.client.recommendations("default", "hackathons", 1, 5)
    assert len(res.results) == 5
    assert route.calls[0].request.url.params["opportunity"] == "hackathons"


async def test_compare_parallel_with_partial_failure(runtime, mock_api):
    for oid in (1101, 1102):
        mock_api.get(f"/api/public/competition/{oid}").mock(
            return_value=httpx.Response(200, json={"data": {"competition": raw_opportunity(oid)}})
        )
    mock_api.get("/api/public/competition/1103").mock(return_value=httpx.Response(404))
    res = await runtime.client.compare(["1101", "https://unstop.com/hackathons/x-1102", "1103", "1101"])
    assert [i.id for i in res.items] == [1101, 1102] and "1103" in res.errors


async def test_compare_bounds(runtime):
    with pytest.raises(InvalidInput):
        await runtime.client.compare(["1"])
