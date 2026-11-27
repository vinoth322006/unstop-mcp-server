"""Browser sign-in page, saved searches + alerts, eligibility, snapshot, sign_in tool."""

import asyncio
import json
import re
import time

import httpx
import pytest

from unstop_mcp.auth.session import UnstopSession
from unstop_mcp.errors import AuthFailed, InvalidInput, NotFound
from unstop_mcp.insights import check_eligibility, user_status
from unstop_mcp.models import OpportunityDetail, Profile
from unstop_mcp.searches import MAX_SEARCHES, SavedSearch, SearchStore
from unstop_mcp.server import build_server
from unstop_mcp.weblogin import BrowserLogin

from .conftest import make_jwt, mock_live_lists, raw_opportunity


def _page(items, total=None):
    return {"data": {"data": items, "total": total if total is not None else len(items), "current_page": 1,
                     "last_page": 1}}


# ---------------------------------------------------------------- browser sign-in

class FakeAuth:
    def __init__(self, store):
        self.store = store
        self.sent = []
        self.codes = []

    async def send_otp(self, email, channel="email"):
        self.sent.append(email)
        return "Code sent."

    async def verify_otp(self, email, otp, channel="email"):
        self.codes.append(otp)
        if otp != "123456":
            raise AuthFailed("Incorrect OTP. Please try again.")
        return UnstopSession(access_token=make_jwt(), email=email, name="Asha")

    async def complete_login(self, tenant, session):
        self.store.put(tenant, session)
        return session


def _nonce(html: str) -> str:
    found = re.search(r'name="nonce" value="([^"]+)"', html)
    assert found, f"expected the sign-in form, got: {re.sub(r'<[^>]+>', ' ', html.split('<body>')[-1])[:200]!r}"
    return found.group(1)


async def test_browser_login_full_flow(runtime):
    auth = FakeAuth(runtime.sessions)
    login = BrowserLogin(auth, "default", asyncio.get_running_loop(), timeout=30)
    url = login.start(open_browser=False)
    assert url.startswith("http://127.0.0.1:")

    def drive():
        with httpx.Client() as c:
            page = c.get(url).text
            assert "Sign in to Unstop" in page
            n = _nonce(page)
            assert c.post(url + "send", data={"nonce": "forged", "email": "a@b.com"}).status_code == 403
            page = c.post(url + "send", data={"nonce": n, "email": "a@b.com"}).text
            assert "Enter your code" in page
            page = c.post(url + "verify", data={"nonce": n, "otp": "000000"}).text
            assert "Incorrect OTP" in page
            page = c.post(url + "verify", data={"nonce": n, "otp": "123456"}).text
            assert "signed in" in page.lower()
            time.sleep(1.2)  # a late refresh must get the "expired" page, not a connection reset
            return c.get(url).status_code

    status_after = await asyncio.to_thread(drive)
    assert await asyncio.wrap_future(login.result) == "Asha"
    assert status_after == 410  # link is dead once used
    assert runtime.sessions.get("default").name == "Asha"
    assert auth.sent == ["a@b.com"]


async def test_browser_login_rejects_wrong_host_and_path(runtime):
    login = BrowserLogin(FakeAuth(runtime.sessions), "default", asyncio.get_running_loop(), timeout=30)
    url = login.start(open_browser=False)
    port = url.split(":")[2].split("/")[0]

    def drive():
        with httpx.Client() as c:
            wrong_path = c.get(f"http://127.0.0.1:{port}/guess/").status_code
            wrong_host = c.get(url, headers={"Host": "evil.example"}).status_code
            headers = c.get(url).headers
            return wrong_path, wrong_host, headers

    wrong_path, wrong_host, headers = await asyncio.to_thread(drive)
    login.stop()
    assert wrong_path == 404 and wrong_host == 421
    assert headers["Cache-Control"] == "no-store" and "frame-ancestors 'none'" in headers["Content-Security-Policy"]


async def test_browser_login_locks_after_too_many_codes(runtime):
    login = BrowserLogin(FakeAuth(runtime.sessions), "default", asyncio.get_running_loop(), timeout=30)
    url = login.start(open_browser=False)

    def drive():
        with httpx.Client() as c:
            n = _nonce(c.get(url).text)
            c.post(url + "send", data={"nonce": n, "email": "a@b.com"})
            for _ in range(5):
                page = c.post(url + "verify", data={"nonce": n, "otp": "999999"}).text
            return page

    page = await asyncio.to_thread(drive)
    login.stop()
    assert "Too many wrong codes" in page


async def test_browser_login_expires(runtime):
    login = BrowserLogin(FakeAuth(runtime.sessions), "default", asyncio.get_running_loop(), timeout=0.5)
    login.start(open_browser=False)
    assert await asyncio.wait_for(asyncio.wrap_future(login.result), 5) is None


# ---------------------------------------------------------------- saved searches

def test_search_store_crud_and_limits(tmp_path):
    store = SearchStore(tmp_path)
    store.upsert("t", SavedSearch(name="AI", query="ai"))
    store.upsert("t", SavedSearch(name="ai", query="ml"))  # same name (case-insensitive) replaces
    assert [(s.name, s.query) for s in store.load("t")] == [("ai", "ml")]
    with pytest.raises(InvalidInput):
        store.upsert("t", SavedSearch(name="<script>"))
    for i in range(MAX_SEARCHES - 1):
        store.upsert("t", SavedSearch(name=f"s{i}"))
    with pytest.raises(InvalidInput):
        store.upsert("t", SavedSearch(name="one too many"))
    store.delete("t", "AI")
    with pytest.raises(NotFound):
        store.delete("t", "AI")


def test_search_store_survives_corrupt_file(tmp_path):
    (tmp_path / "t.json").write_text("{broken")
    assert SearchStore(tmp_path).load("t") == []


async def test_alerts_report_only_new_open_listings(runtime, mock_api):
    responses = [
        _page([raw_opportunity(1001), raw_opportunity(1002)]),
        _page([raw_opportunity(1003), raw_opportunity(1001), raw_opportunity(1004, status="FINISHED")]),
        _page([raw_opportunity(1003), raw_opportunity(1001)]),
    ]
    mock_api.get("/api/public/opportunity/search-result").mock(
        side_effect=[httpx.Response(200, json=r) for r in responses]
    )
    runtime.http.cache.clear()
    first = await runtime.client.save_search("default", SavedSearch(name="AI", query="ai"))
    assert first.first_check and first.new_count == 2
    runtime.http.cache.clear()
    report = await runtime.client.check_searches("default")
    assert report.total_new == 1 and [o.id for o in report.searches[0].new] == [1003]
    runtime.http.cache.clear()
    again = await runtime.client.check_searches("default")
    assert again.total_new == 0  # each listing is reported once
    with pytest.raises(NotFound):
        await runtime.client.check_searches("default", "nope")


# ---------------------------------------------------------------- eligibility

def _opp(**rules):
    return OpportunityDetail(id=1, title="Hack", url="https://unstop.com/x-1", registration_open=True, eligibility=rules)


STUDENT = Profile(name="A", graduation_year=2099, specialization="Computer Science and Engineering")


def test_user_status():
    assert user_status(STUDENT) == "student"
    assert user_status(Profile(graduation_year=1990)) == "professional"
    assert user_status(Profile()) == "unknown"


def test_eligible_student_cse():
    rules = {"sector": ["students"], "engineering": [{"course": "btech", "specialization": [
        "Computer Science and Engineering"], "passoutYear": ["all"]}]}
    e = check_eligibility(STUDENT, _opp(**rules))
    assert e.verdict == "likely_eligible" and {c.rule for c in e.checks} == {"Open to", "Course"}


def test_not_eligible_wrong_specialization_and_year():
    rules = {"engineering": [{"course": "btech", "specialization": ["Civil Engineering"], "passoutYear": ["all"]}],
             "studentPassoutYearsSelected": [2026]}
    e = check_eligibility(STUDENT, _opp(**rules))
    assert e.verdict == "likely_not_eligible"
    assert {c.rule: c.result for c in e.checks} == {"Student graduation year": "fail", "Course": "fail"}


def test_professionals_only_and_experience():
    e = check_eligibility(STUDENT, _opp(sector=["corporates"], experience=["2 years"]))
    assert e.verdict == "likely_not_eligible"


def test_unknown_profile_is_unclear_not_wrong():
    e = check_eligibility(Profile(), _opp(sector=["students"]))
    assert e.verdict == "unclear"


def test_closed_registration_fails():
    opp = _opp(sector=["students"])
    opp.registration_open = False
    assert check_eligibility(STUDENT, opp).verdict == "likely_not_eligible"


# ---------------------------------------------------------------- snapshot + tools

async def test_snapshot(runtime, mock_api):
    mock_live_lists(mock_api)
    runtime.sessions.put("default", UnstopSession(access_token="tok", expires_at=time.time() + 3600))
    mock_api.get("/api/user/profile").mock(return_value=httpx.Response(200, json={"data": {
        "id": 1, "name": "Asha", "passing_out_year": 2099, "profile_percent": 80}}))

    def regs(request):
        totals = {"hackathons": 5, "competitions": 2}
        t = request.url.params.get("filterValue")
        return httpx.Response(200, json=_page([], total=totals.get(t, 7 if t is None else 0)))

    mock_api.get("/api/user/registered-opportunities").mock(side_effect=regs)
    mock_api.get("/api/user/certificates").mock(return_value=httpx.Response(200, json=_page([
        {"id": 1, "certificate_type": "winners"}, {"id": 2, "certificate_type": "opportunity-participation"}])))
    mock_api.get("/api/user/my-watchlist").mock(return_value=httpx.Response(200, json=_page([], total=3)))
    mock_api.get("/api/user/my-rounds").mock(return_value=httpx.Response(200, json=_page([])))
    s = await runtime.client.snapshot("default")
    assert (s.name, s.status, s.total_registrations, s.watchlist_total, s.wins) == ("Asha", "student", 7, 3, 1)
    assert s.registrations_by_type == {"hackathons": 5, "competitions": 2} and s.partial_errors == []


async def test_new_tools_registered(settings, runtime):
    names = {t.name for t in await build_server(settings, runtime).list_tools()}
    assert {"sign_in", "check_eligibility", "my_snapshot", "save_search", "check_saved_searches",
            "list_saved_searches", "delete_saved_search"} <= names


async def test_sign_in_tool_when_already_signed_in(settings, runtime):
    runtime.sessions.put("default", UnstopSession(access_token="t", name="Asha", expires_at=time.time() + 3600))
    res = await build_server(settings, runtime).call_tool("sign_in", {})
    out = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
    assert out["signed_in"] is True and "Asha" in out["message"]


async def test_sign_in_tool_refused_in_http_mode(settings, runtime):
    settings.transport = "http"
    mcp = build_server(settings, runtime)
    from mcp.server.auth.provider import AccessToken

    import unstop_mcp.tools._common as srv

    srv_get = srv.get_access_token
    srv.get_access_token = lambda: AccessToken(token="k", client_id="bob", scopes=["unstop:read"])
    try:
        res = await mcp.call_tool("sign_in", {})
    finally:
        srv.get_access_token = srv_get
    out = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
    assert out["signed_in"] is False and "--tenant bob" in out["message"]
    assert "url" not in json.dumps(out)
