"""Resilient async HTTP layer for unstop.com.

Features, in the order a request meets them:

1. **Cache** (fresh hit returns immediately). Public GETs are shared by everyone; private GETs are cached per
   tenant for a few seconds and invalidated on writes.
2. **Single-flight**: concurrent identical GETs share one upstream call.
3. **Circuit breaker**: after repeated upstream failures we stop hammering Unstop for a cool-down period.
4. **Token bucket**: a global request budget so the whole server stays polite.
5. **Retries** with exponential backoff + jitter, honouring ``Retry-After``.
6. **Stale-if-error**: if Unstop is down, a recently cached public answer is served instead of an error.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections import OrderedDict
from typing import Any
from urllib.parse import unquote

import httpx

from unstop_mcp import __version__
from unstop_mcp.config import Settings
from unstop_mcp.crypto import maybe_decrypt
from unstop_mcp.errors import (
    AuthExpired,
    InvalidInput,
    NotFound,
    PermissionDenied,
    RateLimited,
    UnstopError,
    UpstreamError,
)

log = logging.getLogger(__name__)

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class TokenBucket:
    """Async token bucket. ``rate`` tokens/second, holding at most ``burst``."""

    def __init__(self, rate: float, burst: int) -> None:
        self.rate = rate
        self.capacity = float(burst)
        self.tokens = float(burst)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
        self.updated = now

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                self._refill()
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)

    def try_acquire(self) -> bool:
        """Non-blocking variant used for per-client rate limiting."""
        self._refill()
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class TTLCache:
    """LRU cache with per-entry expiry plus a stale window used only when the upstream is failing."""

    def __init__(self, max_entries: int, stale_seconds: float = 3600.0) -> None:
        self.max_entries = max_entries
        self.stale_seconds = stale_seconds
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str, *, allow_stale: bool = False) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        now = time.monotonic()
        if expires >= now or (allow_stale and expires + self.stale_seconds >= now):
            self._data.move_to_end(key)
            return value
        if expires + self.stale_seconds < now:
            self._data.pop(key, None)
        return None

    def set(self, key: str, value: Any, ttl: float) -> None:
        if self.max_entries <= 0 or ttl <= 0:
            return
        self._data[key] = (time.monotonic() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def invalidate(self, prefix: str) -> int:
        doomed = [k for k in self._data if k.startswith(prefix)]
        for k in doomed:
            del self._data[k]
        return len(doomed)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


class CircuitBreaker:
    """Opens after ``threshold`` consecutive upstream failures; half-opens after ``cooldown`` seconds."""

    def __init__(self, threshold: int, cooldown: float) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half-open" if time.monotonic() - self.opened_at >= self.cooldown else "open"

    def check(self) -> None:
        if self.state == "open":
            wait = int(self.cooldown - (time.monotonic() - (self.opened_at or 0))) + 1
            raise UpstreamError(f"Unstop is not responding right now. Paused requests; retrying in ~{wait}s.")

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold or self.state == "half-open":
            if self.opened_at is None or self.state == "half-open":
                log.warning("Circuit breaker opened after %d upstream failures", self.failures)
            self.opened_at = time.monotonic()


def _extract_message(body: Any) -> str | None:
    if isinstance(body, dict):
        for key in ("message", "msg", "error"):
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        data = body.get("data")
        if isinstance(data, dict):
            return _extract_message(data)
        errors = body.get("errors")
        if isinstance(errors, dict):
            flat = [m for v in errors.values() for m in (v if isinstance(v, list) else [v])]
            if flat:
                return "; ".join(str(m) for m in flat[:3])
    return None


class UnstopHTTP:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=httpx.Timeout(settings.timeout_seconds, connect=min(10.0, settings.timeout_seconds)),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30),
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Origin": settings.base_url,
                "Referer": settings.base_url + "/",
                "X-Client": f"unstop-mcp/{__version__}",
            },
            follow_redirects=False,
            transport=transport,
        )
        self._bucket = TokenBucket(settings.rate_limit_per_second, settings.rate_limit_burst)
        self.cache = TTLCache(settings.cache_max_entries, settings.stale_cache_seconds)
        self.breaker = CircuitBreaker(settings.breaker_threshold, settings.breaker_cooldown_seconds)
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._csrf: str | None = None
        self.stats = {"requests": 0, "cache_hits": 0, "stale_served": 0, "deduplicated": 0, "errors": 0}

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> UnstopHTTP:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @staticmethod
    def cache_key(path: str, params: dict[str, Any], scope: str | None) -> str:
        return f"{scope or 'public'}|{path}?{json.dumps(params, sort_keys=True, default=str)}"

    def invalidate(self, scope: str, path_prefix: str = "") -> int:
        return self.cache.invalidate(f"{scope}|{path_prefix}")

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        token: str | None = None,
        cache: bool = False,
        cache_scope: str | None = None,
    ) -> Any:
        """Return decoded (and decrypted) JSON or raise an :class:`UnstopError`.

        ``cache=True`` caches GETs: publicly when ``token`` is None, or per ``cache_scope`` (the tenant) when
        authenticated. Authenticated requests are never cached without an explicit scope.
        """
        if not path.startswith("/api/"):
            raise InvalidInput("Only /api/ paths may be requested.")
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        key: str | None = None
        ttl = 0.0
        if cache and method == "GET" and (token is None or cache_scope):
            key = self.cache_key(path, clean, cache_scope if token else None)
            ttl = self.settings.cache_ttl_seconds if token is None else self.settings.private_cache_ttl_seconds
            hit = self.cache.get(key)
            if hit is not None:
                self.stats["cache_hits"] += 1
                return hit
            inflight = self._inflight.get(key)
            if inflight is not None:
                self.stats["deduplicated"] += 1
                return await asyncio.shield(inflight)

        if key is None:
            return await self._send(method, path, clean, json_body, token)

        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            try:
                result = await self._send(method, path, clean, json_body, token)
            except (UpstreamError, RateLimited):
                stale = self.cache.get(key, allow_stale=token is None)
                if stale is None:
                    raise
                self.stats["stale_served"] += 1
                log.warning("Serving stale cache for %s (Unstop unavailable)", path)
                result = stale
            else:
                self.cache.set(key, result, ttl)
            future.set_result(result)
            return result
        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                future.cancel()
            else:
                future.set_exception(exc)
                future.exception()  # mark retrieved so a future with no waiters doesn't warn
            raise
        finally:
            self._inflight.pop(key, None)

    async def _refresh_csrf(self) -> None:
        try:
            resp = await self._client.get("/api/micro/oauth/v2/generate/csrf-cookie")
        except httpx.HTTPError as exc:
            raise UpstreamError("Could not reach Unstop to refresh its security token.") from exc
        token = resp.cookies.get("XSRF-TOKEN") or self._client.cookies.get("XSRF-TOKEN")
        self._csrf = unquote(token) if token else None

    async def _send(
        self, method: str, path: str, params: dict[str, Any], json_body: dict[str, Any] | None, token: str | None
    ) -> Any:
        self.breaker.check()
        headers: dict[str, str] = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        attempt = 0
        csrf_retried = False
        while True:
            attempt += 1
            if self._csrf:
                headers["X-XSRF-TOKEN"] = self._csrf
            await self._bucket.acquire()
            started = time.monotonic()
            self.stats["requests"] += 1
            try:
                resp = await self._client.request(method, path, params=params, json=json_body, headers=headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt <= self.settings.max_retries:
                    await self._backoff(attempt, None)
                    continue
                self.breaker.failure()
                self.stats["errors"] += 1
                raise UpstreamError(f"Could not reach Unstop ({type(exc).__name__}). Try again shortly.") from exc

            log.debug(
                "%s %s -> %s", method, path, resp.status_code,
                extra={"status": resp.status_code, "path": path,
                       "duration_ms": round((time.monotonic() - started) * 1000)},
            )
            if resp.status_code == 419 and not csrf_retried:
                csrf_retried = True
                await self._refresh_csrf()
                continue
            if resp.status_code in _RETRY_STATUSES and attempt <= self.settings.max_retries:
                await self._backoff(attempt, resp.headers.get("Retry-After"))
                continue
            try:
                result = self._handle(resp)
            except (UpstreamError, RateLimited):
                self.breaker.failure()
                self.stats["errors"] += 1
                raise
            except UnstopError:
                self.breaker.success()  # a clean 4xx means Unstop itself is healthy
                raise
            self.breaker.success()
            return result

    async def _backoff(self, attempt: int, retry_after: str | None) -> None:
        if retry_after and retry_after.isdigit():
            delay = min(float(retry_after), 30.0)
        else:
            delay = min(0.5 * (2 ** (attempt - 1)), 8.0) + random.uniform(0, 0.25)  # noqa: S311
        await asyncio.sleep(delay)

    @staticmethod
    def _handle(resp: httpx.Response) -> Any:
        status = resp.status_code
        body: Any = None
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype or resp.content[:1] in (b"{", b"["):
            try:
                body = resp.json()
            except ValueError:
                body = None
        msg = _extract_message(body)

        if 200 <= status < 300:
            if status == 204 or not resp.content:
                return {}
            if body is None:
                raise UpstreamError("Unstop returned a non-JSON response (endpoint may have changed).", status=status)
            return maybe_decrypt(body)
        if status == 401:
            raise AuthExpired(msg or "Unstop rejected the session.", status=status)
        if status == 403:
            raise PermissionDenied(msg or "Unstop refused access to this resource.", status=status)
        if status == 404:
            raise NotFound(msg if msg and "not found" in msg.lower() else "Not found on Unstop.", status=status)
        if status == 429:
            raise RateLimited("Unstop is rate limiting requests. Wait a minute and retry.", status=status)
        if status in (400, 409, 422):
            raise InvalidInput(msg or "Unstop rejected the request.", status=status)
        if status >= 500:
            raise UpstreamError(f"Unstop server error ({status}). Try again shortly.", status=status)
        raise UnstopError(msg or f"Unexpected response from Unstop ({status}).", status=status)
