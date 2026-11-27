"""Shared plumbing: HTTP access as the signed-in user, pagination, and safe parsing."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from datetime import datetime
from typing import Any, TypeVar

from pydantic import ValidationError

from unstop_mcp.auth.unstop_auth import UnstopAuth
from unstop_mcp.errors import AuthExpired, InvalidInput, UpstreamError
from unstop_mcp.http import UnstopHTTP
from unstop_mcp.models import (
    IST,
    SearchResult,
    parse_dt,
    summarize,
)
from unstop_mcp.searches import SearchStore

T = TypeVar("T")
log = logging.getLogger(__name__)

_DATA_ERRORS = (TypeError, ValueError, KeyError, AttributeError, IndexError, ValidationError)


def _each(fn: Callable[[Any], T], items: Iterable[Any]) -> list[T]:
    """Normalise a list of raw Unstop records; a malformed record is logged and skipped, never fatal."""
    out: list[T] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        try:
            out.append(fn(raw))
        except _DATA_ERRORS as exc:
            log.warning("Skipped a malformed Unstop record (%s: %s)", type(exc).__name__, exc)
    return out


def _parse(fn: Callable[..., T], *args: Any) -> T:
    """Normalise a single record; if Unstop's format changed, fail with a clear message instead of crashing."""
    try:
        return fn(*args)
    except _DATA_ERRORS as exc:
        log.warning("Could not read Unstop data (%s: %s)", type(exc).__name__, exc)
        raise UpstreamError("Unstop sent this data in an unexpected format. Try again later, or check unstop.com "
                            "directly.") from exc


def _num(value: Any, default: int) -> int:
    try:
        return int(str(value)) if value not in (None, "") else default
    except ValueError:
        return default


def _dig(obj: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj

_ID_IN_URL = re.compile(r"-(\d{4,})(?:[/?#]|$)")
_ORG_ID_IN_URL = re.compile(r"(?:^|[-/])(\d{3,})(?:[/?#]|$)")
_MAX_PARALLEL = 5


def parse_opportunity_id(value: str | int) -> int:
    """Accept 1817824, "1817824", or any unstop.com opportunity URL ending in -<id>."""
    if isinstance(value, int):
        if value <= 0:
            raise InvalidInput("Opportunity ids are positive numbers.")
        return value
    text = str(value).strip()
    if text.isdigit() and len(text) <= 12:
        return int(text)
    match = _ID_IN_URL.search(text)
    if match and len(match.group(1)) <= 12:
        return int(match.group(1))
    raise InvalidInput("Give an Unstop opportunity id (e.g. 1817824) or its unstop.com URL.")


def parse_organisation_id(value: str | int) -> int:
    """Accept 2159613, "2159613" or an unstop.com organisation URL like https://unstop.com/c/name-2159613."""
    if isinstance(value, int) and value > 0:
        return value
    text = str(value).strip()
    if text.isdigit() and len(text) <= 12:
        return int(text)
    match = _ORG_ID_IN_URL.search(text)
    if match and len(match.group(1)) <= 12:
        return int(match.group(1))
    raise InvalidInput("Give an Unstop organisation id (e.g. 2159613) or its unstop.com URL.")


def _paged(payload: Any) -> tuple[list[Any], dict[str, Any]]:
    """Unwrap Laravel-style pagination: {data: {data: [...], total, current_page, last_page}}."""
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if not isinstance(data, dict | list):
        return [], {}
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"], data
    if isinstance(data, list):
        return data, {}
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, dict) and isinstance(value.get("data"), list):
                return value["data"], value
    return [], {}


def _search_result(payload: Any, page: int, per_page: int, sort: str = "relevance") -> SearchResult:
    items, meta = _paged(payload)
    results = _each(summarize, items)
    if sort == "deadline":
        far = datetime.max.replace(tzinfo=IST)
        results.sort(key=lambda r: parse_dt(r.registration_deadline) or far)
    return SearchResult(
        total=_num(meta.get("total"), len(results)),
        page=_num(meta.get("current_page"), page),
        last_page=max(1, _num(meta.get("last_page"), 1)),
        per_page=_num(meta.get("per_page"), per_page),
        results=results,
    )


async def gather_limited(coros: Iterable[Awaitable[T]], limit: int = _MAX_PARALLEL) -> list[T | BaseException]:
    """Run awaitables concurrently (bounded), returning results or exceptions in input order."""
    sem = asyncio.Semaphore(limit)

    async def run(c: Awaitable[T]) -> T:
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)



class BaseClient:

    def __init__(
        self, http: UnstopHTTP, auth: UnstopAuth, description_max_chars: int = 6000,
        searches: SearchStore | None = None,
    ) -> None:
        self.http = http
        self.auth = auth
        self.description_max_chars = description_max_chars
        self.searches = searches

    # ------------------------------------------------------------------ authenticated

    async def _user_get(
        self, tenant: str, path: str, params: dict[str, Any] | None = None, *, cache: bool = True
    ) -> Any:
        session = await self.auth.get_session(tenant)
        kwargs: dict[str, Any] = {"params": params, "cache": cache, "cache_scope": tenant}
        try:
            return await self.http.request("GET", path, token=session.access_token, **kwargs)
        except AuthExpired:
            session = await self.auth.force_refresh(tenant, session.access_token)
            return await self.http.request("GET", path, token=session.access_token, **kwargs)

    # ------------------------------------------------------------------ registration

    async def _user_call(self, tenant: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        """Authenticated write with the same refresh-on-401 behaviour as reads. Never cached."""
        session = await self.auth.get_session(tenant)
        try:
            return await self.http.request(method, path, json_body=body, token=session.access_token)
        except AuthExpired:
            session = await self.auth.force_refresh(tenant, session.access_token)
            return await self.http.request(method, path, json_body=body, token=session.access_token)

    async def _paged_items(
        self, tenant: str, path: str, params: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        payload = await self._user_get(tenant, path, params)
        items, meta = _paged(payload)
        info = {
            "total": _num(meta.get("total"), len(items)),
            "page": _num(meta.get("current_page"), _num(params.get("page"), 1)),
            "last_page": max(1, _num(meta.get("last_page"), 1)),
        }
        return [i for i in items if isinstance(i, dict) and i.get("id")], info

    @staticmethod

    def _team_info(boot: dict[str, Any]) -> dict[str, Any] | None:
        team = boot.get("oRegisteredTeam")
        return team if isinstance(team, dict) and team.get("id") else None
