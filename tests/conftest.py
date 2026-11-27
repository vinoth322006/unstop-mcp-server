from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import httpx
import pytest
import respx

from unstop_mcp.config import Settings
from unstop_mcp.server import Runtime, build_runtime

BASE = "https://unstop.com"


def make_jwt(exp_in: float = 3600, **claims) -> str:
    def b64(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64({'exp': time.time() + exp_in, **claims})}.sig"


def raw_opportunity(oid: int = 1817824, **over) -> dict:
    raw = {
        "id": oid,
        "title": "PromptWars ",
        "type": "hackathons",
        "subtype": "online_coding_challenge",
        "regn_open": 1,
        "region": "online",
        "status": "LIVE",
        "isPaid": False,
        "seo_url": f"https://unstop.com/hackathons/promptwars-{oid}",
        "short_url": "https://unstop.com/o/abc",
        "organisation": {"name": "NEXORA"},
        "details": "<p><strong>About</strong></p><ul><li>Build &amp; ship</li><li>Win</li></ul><script>x</script>",
        "prizes": [{"rank": "Winner", "cash": 15000, "currency": "fa-rupee", "currencyCode": "INR",
                    "others": "<p>Pool up to 50k</p>"}],
        "regnRequirements": {"start_regn_dt": "2026-11-18T17:39:00+05:30", "end_regn_dt": "2099-12-12T23:59:00+05:30",
                             "min_team_size": 1, "max_team_size": 4, "remain_days": "16 days left",
                             "eligibility": '{"sector":["students"],"others":["all"],"minMarks":{"a":0}}'},
        "required_skills": [{"skill_name": "AI"}, {"skill": "Python"}, {"skill_name": "AI"}],
        "filters": [{"name": "Engineering Students"}],
        "registerCount": 25,
        "viewsCount": 1562,
        "rounds": [{"subtype": "quiz", "details": [{"title": "Round 1", "start_date": "2026-12-01",
                                                     "end_date": "2026-12-02"}]}],
    }
    raw.update(over)
    return raw


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        secret_key="test-secret",
        max_retries=2,
        rate_limit_per_second=1000,
        rate_limit_burst=1000,
        log_json=False,
        _env_file=None,
    )


@pytest.fixture
async def runtime(settings: Settings):
    rt: Runtime = build_runtime(settings)
    yield rt
    await rt.http.aclose()


@pytest.fixture
def mock_api():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make retry backoff instant."""
    import asyncio

    real_sleep = asyncio.sleep

    async def fast_sleep(delay, *a, **k):
        await real_sleep(0)

    monkeypatch.setattr("unstop_mcp.http.asyncio.sleep", fast_sleep)


def mock_live_lists(router, teams=None, team=None):
    """Mocks for the two live lookups that back up Unstop's lagging indexes: your team list and the registration
    page bootstrap (used by my_registrations and my_participation)."""
    router.get("/api/user/teams/").mock(return_value=httpx.Response(200, json={"data": teams or []}))
    router.get(url__regex=r"/api/registration/restricted/\d+/").mock(
        return_value=httpx.Response(200, json={"status": True, "data": {"oRegisteredTeam": team}}))
    router.get(url__regex=r"/api/public/competition/\d+$").mock(return_value=httpx.Response(404))
