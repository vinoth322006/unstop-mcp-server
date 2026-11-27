import httpx
import pytest

from unstop_mcp.errors import AuthExpired, InvalidInput, NotFound, RateLimited, UpstreamError
from unstop_mcp.http import UnstopHTTP


async def test_retries_then_succeeds(settings, mock_api):
    route = mock_api.get("/api/public/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": 1})]
    )
    async with UnstopHTTP(settings) as http:
        assert await http.request("GET", "/api/public/x") == {"ok": 1}
    assert route.call_count == 2


async def test_rate_limited_after_retries(settings, mock_api):
    route = mock_api.get("/api/public/x").mock(return_value=httpx.Response(429))
    async with UnstopHTTP(settings) as http:
        with pytest.raises(RateLimited):
            await http.request("GET", "/api/public/x")
    assert route.call_count == settings.max_retries + 1


async def test_transport_error_maps_to_upstream(settings, mock_api):
    mock_api.get("/api/public/x").mock(side_effect=httpx.ConnectError("boom"))
    async with UnstopHTTP(settings) as http:
        with pytest.raises(UpstreamError):
            await http.request("GET", "/api/public/x")


@pytest.mark.parametrize(
    "status,body,exc",
    [
        (401, {"message": "Unauthenticated."}, AuthExpired),
        (404, None, NotFound),
        (422, {"errors": {"email": ["bad email"]}}, InvalidInput),
        (500, None, UpstreamError),
    ],
)
async def test_error_mapping(settings, mock_api, status, body, exc):
    mock_api.get("/api/user/x").mock(return_value=httpx.Response(status, json=body))
    async with UnstopHTTP(settings) as http:
        with pytest.raises(exc):
            await http.request("GET", "/api/user/x", token="t")


async def test_html_200_is_upstream_error(settings, mock_api):
    mock_api.get("/api/public/x").mock(return_value=httpx.Response(200, text="<html>", headers={"content-type": "text/html"}))
    async with UnstopHTTP(settings) as http:
        with pytest.raises(UpstreamError):
            await http.request("GET", "/api/public/x")


async def test_cache_only_for_anonymous_get(settings, mock_api):
    route = mock_api.get("/api/public/x").mock(return_value=httpx.Response(200, json={"n": 1}))
    async with UnstopHTTP(settings) as http:
        await http.request("GET", "/api/public/x", params={"a": 1}, cache=True)
        await http.request("GET", "/api/public/x", params={"a": 1}, cache=True)
        assert route.call_count == 1
        await http.request("GET", "/api/public/x", params={"a": 1}, cache=True, token="t")
        assert route.call_count == 2


async def test_bearer_header_sent(settings, mock_api):
    route = mock_api.get("/api/user/x").mock(return_value=httpx.Response(200, json={}))
    async with UnstopHTTP(settings) as http:
        await http.request("GET", "/api/user/x", token="tok123")
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok123"


async def test_csrf_refresh_on_419(settings, mock_api):
    mock_api.get("/api/micro/oauth/v2/generate/csrf-cookie").mock(
        return_value=httpx.Response(204, headers={"set-cookie": "XSRF-TOKEN=abc%3D; Path=/"})
    )
    route = mock_api.post("/api/x").mock(side_effect=[httpx.Response(419), httpx.Response(200, json={"ok": 1})])
    async with UnstopHTTP(settings) as http:
        assert await http.request("POST", "/api/x", json_body={}) == {"ok": 1}
    assert route.calls[1].request.headers["X-XSRF-TOKEN"] == "abc="


async def test_rejects_non_api_paths(settings):
    async with UnstopHTTP(settings) as http:
        with pytest.raises(InvalidInput):
            await http.request("GET", "https://evil.example/")
