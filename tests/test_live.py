"""Smoke tests against the real public Unstop API. Run with: pytest -m live"""

import pytest

pytestmark = pytest.mark.live


async def test_live_search_and_detail(runtime):
    result = await runtime.client.search(opportunity_type="hackathons", per_page=3)
    assert result.total > 0 and result.results
    first = result.results[0]
    assert first.url and first.url.startswith("https://unstop.com/")
    detail = await runtime.client.get_opportunity(first.url)
    assert detail.id == first.id and detail.title


async def test_live_keyword_search(runtime):
    result = await runtime.client.search(query="AI", opportunity_type="all", per_page=5)
    assert result.total > 0


async def test_live_account_endpoint_rejects_anonymous(runtime):
    from unstop_mcp.errors import AuthExpired

    with pytest.raises(AuthExpired):
        await runtime.http.request("GET", "/api/user/profile", token="invalid")
