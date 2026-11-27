"""Public Unstop data (no sign-in): search, details, comparisons, organisations, leaderboard."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from unstop_mcp.client._base import (  # noqa: F401
    BaseClient,
    _dig,
    _each,
    _num,
    _paged,
    _parse,
    _search_result,
    gather_limited,
    parse_opportunity_id,
    parse_organisation_id,
)
from unstop_mcp.errors import AuthRequired, InvalidInput, NotFound, UnstopError
from unstop_mcp.models import (
    IST,
    OPPORTUNITY_TYPES,
    Comparison,
    Leaderboard,
    OpportunityDetail,
    Organisation,
    SearchResult,
    detail,
    leaderboard_entry,
    organisation,
    parse_dt,
)


class CatalogService(BaseClient):

    # ------------------------------------------------------------------ public (no login needed)

    async def search(
        self,
        *,
        opportunity_type: str = "all",
        query: str | None = None,
        status: Literal["open", "closed", "all"] = "open",
        payment: Literal["free", "paid", "all"] = "all",
        region: Literal["online", "offline", "all"] = "all",
        sort: Literal["relevance", "prize", "deadline"] = "relevance",
        page: int = 1,
        per_page: int = 10,
    ) -> SearchResult:
        if opportunity_type not in OPPORTUNITY_TYPES:
            raise InvalidInput(f"Unknown type '{opportunity_type}'. Use one of: {', '.join(OPPORTUNITY_TYPES)}.")
        page, per_page = max(1, page), min(max(1, per_page), 30)
        params: dict[str, Any] = {
            "opportunity": opportunity_type,
            "page": page,
            "per_page": per_page,
            "oppstatus": None if status == "all" else status,
            "payment": {"free": "unpaid", "paid": "paid", "all": None}[payment],
            "region": None if region == "all" else region,
            "searchTerm": (query or "").strip()[:120] or None,
            # Unstop only honours sort=prize server-side; "deadline" is applied to the returned page.
            "sort": "prize" if sort == "prize" else None,
            "dir": "desc" if sort == "prize" else None,
        }
        payload = await self.http.request("GET", "/api/public/opportunity/search-result", params=params, cache=True)
        return _search_result(payload, page, per_page, sort)

    async def get_opportunity(self, opportunity: str | int) -> OpportunityDetail:
        oid = parse_opportunity_id(opportunity)
        payload = await self.http.request("GET", f"/api/public/competition/{oid}", cache=True)
        raw = _dig(payload, "data", "competition")
        if not isinstance(raw, dict) or not raw.get("id"):
            raise NotFound(f"No Unstop opportunity with id {oid}.")
        return _parse(detail, raw, self.description_max_chars)

    async def compare(self, opportunities: list[str]) -> Comparison:
        if not 2 <= len(opportunities) <= 5:
            raise InvalidInput("Compare between 2 and 5 opportunities.")
        ids = list(dict.fromkeys(parse_opportunity_id(o) for o in opportunities))
        results = await gather_limited(self.get_opportunity(i) for i in ids)
        out = Comparison(items=[])
        for oid, res in zip(ids, results, strict=True):
            if isinstance(res, OpportunityDetail):
                out.items.append(res.model_copy(update={"description": res.description[:1200]}))
            elif isinstance(res, UnstopError):
                out.errors[str(oid)] = res.message
            elif isinstance(res, BaseException):
                raise res
        return out

    async def closing_soon(
        self, days: int = 7, opportunity_type: str = "all", query: str | None = None, pages: int = 4,
    ) -> SearchResult:
        """Open listings whose registration closes within ``days``, soonest first. Unstop can't sort by deadline,
        so this scans the first ``pages`` x 30 open listings in parallel and filters them."""
        now = datetime.now(IST)
        horizon = now + timedelta(days=days)
        results = await gather_limited([self.search(opportunity_type=opportunity_type, query=query, page=n,
                                                    per_page=30) for n in range(1, pages + 1)], limit=4)
        seen: dict[int, Any] = {}
        for r in results:
            if isinstance(r, SearchResult):
                for o in r.results:
                    end = parse_dt(o.registration_deadline)
                    if o.registration_open is not False and end is not None and now <= end <= horizon:
                        seen.setdefault(o.id, (end, o))
            elif isinstance(r, AuthRequired | InvalidInput):
                raise r
        ordered = [o for _, o in sorted(seen.values(), key=lambda x: x[0])]
        return SearchResult(total=len(ordered), page=1, last_page=1, per_page=len(ordered), results=ordered)

    # ------------------------------------------------------------------ public extras

    async def get_organisation(self, org: str | int) -> Organisation:
        oid = parse_organisation_id(org)
        payload = await self.http.request("GET", f"/api/public/organisation/with-opportunity/{oid}", cache=True)
        raw = _dig(payload, "data")
        if not isinstance(raw, dict) or not raw.get("id"):
            raise NotFound(f"No Unstop organisation with id {oid}.")
        return _parse(organisation, raw)

    async def leaderboard(self, page: int = 1, per_page: int = 20) -> Leaderboard:
        payload = await self.http.request("GET", "/api/public/gamification/get-paginated-leaderboard/global",
                                          params={"page": page, "per_page": per_page}, cache=True)
        items, meta = _paged(payload)
        return Leaderboard(page=_num(meta.get("current_page"), page), last_page=_num(meta.get("last_page"), 1),
                           total=_num(meta.get("total"), 0) or None, entries=_each(leaderboard_entry, items))
