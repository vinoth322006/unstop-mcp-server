"""Circuit breaker, stale-if-error, single-flight, private cache isolation and invalidation, rate limits."""

import asyncio
import time

import httpx
import pytest

from unstop_mcp.auth.session import UnstopSession
from unstop_mcp.errors import RateLimited, UpstreamError
from unstop_mcp.http import CircuitBreaker, TTLCache, UnstopHTTP
from unstop_mcp.server import ToolGuard


async def test_breaker_opens_and_fails_fast(settings, mock_api):
    settings.breaker_threshold = 2
    settings.max_retries = 0
    route = mock_api.get("/api/public/x").mock(return_value=httpx.Response(503))
    async with UnstopHTTP(settings) as http:
        for _ in range(2):
            with pytest.raises(UpstreamError):
                await http.request("GET", "/api/public/x")
        assert http.breaker.state == "open"
        with pytest.raises(UpstreamError, match="not responding"):
            await http.request("GET", "/api/public/x")
    assert route.call_count == 2  # third call never left the process


def test_breaker_half_open_then_closes():
    b = CircuitBreaker(threshold=1, cooldown=0.01)
    b.failure()
    assert b.state == "open"
    time.sleep(0.02)
    assert b.state == "half-open"
    b.check()  # allowed through
    b.success()
    assert b.state == "closed"


def test_breaker_half_open_failure_reopens():
    b = CircuitBreaker(threshold=3, cooldown=0.01)
    for _ in range(3):
        b.failure()
    time.sleep(0.02)
    b.failure()
    assert b.state == "open"


async def test_client_errors_do_not_trip_breaker(settings, mock_api):
    settings.breaker_threshold = 1
    mock_api.get("/api/public/x").mock(return_value=httpx.Response(404))
    async with UnstopHTTP(settings) as http:
        for _ in range(3):
            with pytest.raises(Exception, match="Not found"):
                await http.request("GET", "/api/public/x")
        assert http.breaker.state == "closed"


async def test_stale_served_when_upstream_down(settings, mock_api):
    settings.cache_ttl_seconds = 1
    settings.max_retries = 0
    route = mock_api.get("/api/public/x").mock(
        side_effect=[httpx.Response(200, json={"v": 1}), httpx.Response(503)]
    )
    async with UnstopHTTP(settings) as http:
        assert await http.request("GET", "/api/public/x", cache=True) == {"v": 1}
        http.cache._data[next(iter(http.cache._data))] = (time.monotonic() - 5, {"v": 1})  # force expiry
        assert await http.request("GET", "/api/public/x", cache=True) == {"v": 1}
        assert http.stats["stale_served"] == 1
    assert route.call_count == 2


async def test_private_data_never_served_stale(settings, mock_api):
    settings.max_retries = 0
    mock_api.get("/api/user/x").mock(side_effect=[httpx.Response(200, json={"v": 1}), httpx.Response(503)])
    async with UnstopHTTP(settings) as http:
        await http.request("GET", "/api/user/x", token="t", cache=True, cache_scope="alice")
        http.cache._data[next(iter(http.cache._data))] = (time.monotonic() - 5, {"v": 1})
        with pytest.raises(UpstreamError):
            await http.request("GET", "/api/user/x", token="t", cache=True, cache_scope="alice")


async def test_single_flight_dedupes_concurrent_calls(settings, mock_api):
    async def slow(_request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"ok": 1})

    route = mock_api.get("/api/public/x").mock(side_effect=slow)
    async with UnstopHTTP(settings) as http:
        results = await asyncio.gather(*(http.request("GET", "/api/public/x", cache=True) for _ in range(10)))
    assert all(r == {"ok": 1} for r in results)
    assert route.call_count == 1


async def test_single_flight_propagates_errors_to_all_waiters(settings, mock_api):
    settings.max_retries = 0

    async def slow_fail(_request):
        await asyncio.sleep(0.05)
        return httpx.Response(500)

    mock_api.get("/api/public/x").mock(side_effect=slow_fail)
    async with UnstopHTTP(settings) as http:
        results = await asyncio.gather(*(http.request("GET", "/api/public/x", cache=True) for _ in range(3)),
                                       return_exceptions=True)
    assert all(isinstance(r, UpstreamError) for r in results)


async def test_private_cache_isolated_per_tenant_and_invalidated(settings, runtime, mock_api):
    for t, tok in (("alice", "a-tok"), ("bob", "b-tok")):
        runtime.sessions.put(t, UnstopSession(access_token=tok, expires_at=time.time() + 3600))

    def handler(request):
        who = request.headers["Authorization"].split()[-1]
        return httpx.Response(200, json={"data": {"data": [], "total": 0, "who": who}})

    route = mock_api.get("/api/user/my-watchlist").mock(side_effect=handler)
    await runtime.client.watchlist("alice", "all", 1, 10)
    await runtime.client.watchlist("alice", "all", 1, 10)  # cached
    await runtime.client.watchlist("bob", "all", 1, 10)  # different tenant -> new request
    assert route.call_count == 2
    assert [c.request.headers["Authorization"] for c in route.calls] == ["Bearer a-tok", "Bearer b-tok"]

    mock_api.get("/api/addToWatchlist/5555/opportunity").mock(return_value=httpx.Response(200, json={"status": True}))
    await runtime.client.set_watchlist("alice", "5555", add=True)
    await runtime.client.watchlist("alice", "all", 1, 10)  # invalidated -> refetch
    assert route.call_count == 3


def test_ttl_cache_lru_and_invalidate():
    c = TTLCache(max_entries=2)
    c.set("a|1", 1, 60)
    c.set("a|2", 2, 60)
    c.set("b|3", 3, 60)  # evicts a|1
    assert c.get("a|1") is None and c.get("a|2") == 2
    assert c.invalidate("a|") == 1 and len(c) == 1


async def test_tool_guard_rate_limits_per_tenant():
    guard = ToolGuard(per_minute=5, max_wait=0)

    @guard
    async def tool() -> str:
        return "ok"

    for _ in range(5):
        assert await tool() == "ok"
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError, match="Too many requests"):
        await tool()


async def test_tool_guard_buckets_are_per_tenant():
    guard = ToolGuard(per_minute=5, max_wait=0)
    for _ in range(5):
        await guard._admit("a")
    with pytest.raises(RateLimited):
        await guard._admit("a")
    await guard._admit("b")  # unaffected


async def test_tool_guard_queues_short_bursts_instead_of_refusing():
    guard = ToolGuard(per_minute=600, max_wait=2.0)  # 10/s, burst 150
    for _ in range(150):
        await guard._admit("a")
    started = time.monotonic()
    await guard._admit("a")  # bucket empty: waits ~0.1 s for a token instead of failing
    assert time.monotonic() - started < 1.5


async def test_tool_guard_disabled_for_local_owner():
    guard = ToolGuard(per_minute=1, enabled=False)
    for _ in range(100):
        await guard._admit("default")


def test_http_mode_requires_secret(tmp_path):
    from unstop_mcp.config import Settings
    from unstop_mcp.server import build_runtime

    with pytest.raises(ValueError, match="UNSTOP_MCP_SECRET_KEY"):
        build_runtime(Settings(transport="http", data_dir=tmp_path, _env_file=None))
    build_runtime(Settings(transport="http", data_dir=tmp_path, allow_generated_secret_in_http=True, _env_file=None))
