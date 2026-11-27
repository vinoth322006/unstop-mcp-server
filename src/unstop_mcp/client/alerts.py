"""Saved searches that report listings which are new since the last check."""

from __future__ import annotations

from datetime import datetime

from unstop_mcp.client._base import (
    gather_limited,
)
from unstop_mcp.client.catalog import CatalogService
from unstop_mcp.errors import InvalidInput, NotFound
from unstop_mcp.models import (
    IST,
    OPPORTUNITY_TYPES,
    AlertsReport,
    SearchAlert,
    SearchResult,
    iso_ist,
)
from unstop_mcp.searches import SavedSearch, SearchStore


class AlertsService(CatalogService):

    # ------------------------------------------------------------------ saved searches

    def _store(self) -> SearchStore:
        if self.searches is None:
            raise InvalidInput("Saved searches are not available on this server.")
        return self.searches

    async def _run_saved(self, s: SavedSearch) -> SearchResult:
        return await self.search(query=s.query, opportunity_type=s.opportunity_type, payment=s.payment,
                                 region=s.region, per_page=30)

    async def save_search(self, tenant: str, search: SavedSearch) -> SearchAlert:
        """Save (or replace) a search and set its baseline, so later checks report only new listings."""
        if search.opportunity_type not in OPPORTUNITY_TYPES:
            raise InvalidInput(f"Unknown type '{search.opportunity_type}'.")
        result = await self._run_saved(search)
        search.seen_ids = [r.id for r in result.results]
        self._store().upsert(tenant, search)
        current = [r for r in result.results if r.registration_open is not False]
        return SearchAlert(name=search.name, query=search.query, opportunity_type=search.opportunity_type,
                           first_check=True, new_count=len(current), new=current[:10])

    def list_searches(self, tenant: str) -> list[SavedSearch]:
        return self._store().load(tenant)

    def delete_search(self, tenant: str, name: str) -> None:
        self._store().delete(tenant, name)

    async def check_searches(self, tenant: str, name: str | None = None) -> AlertsReport:
        store = self._store()
        saved = store.load(tenant)
        if name:
            saved = [s for s in saved if s.name.lower() == name.lower()]
            if not saved:
                raise NotFound(f"No saved search called '{name}'.")
        results = await gather_limited([self._run_saved(s) for s in saved], limit=3)
        report = AlertsReport(checked_at=iso_ist(datetime.now(IST)), total_new=0, searches=[])
        for s, res in zip(saved, results, strict=True):
            if not isinstance(res, SearchResult):
                report.errors[s.name] = getattr(res, "message", type(res).__name__)
                continue
            seen = set(s.seen_ids)
            fresh = [r for r in res.results if r.id not in seen and r.registration_open is not False]
            store.mark_seen(tenant, s.name, [r.id for r in res.results])
            report.searches.append(SearchAlert(name=s.name, query=s.query, opportunity_type=s.opportunity_type,
                                               first_check=not s.seen_ids, new_count=len(fresh), new=fresh))
            report.total_new += len(fresh)
        return report
