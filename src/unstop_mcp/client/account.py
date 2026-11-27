"""The signed-in user's own data.

Profile, registrations, watchlist, certificates, deadlines, notifications, courses, eligibility and the
snapshot.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from unstop_mcp.client._base import (
    _dig,
    _each,
    _num,
    _paged,
    _parse,
    _search_result,
    gather_limited,
    parse_opportunity_id,
)
from unstop_mcp.client.catalog import CatalogService
from unstop_mcp.errors import AuthRequired, InvalidInput, UnstopError
from unstop_mcp.insights import Eligibility, check_eligibility, user_status
from unstop_mcp.models import (
    IST,
    OPPORTUNITY_TYPES,
    Certificate,
    CertificatePage,
    Course,
    DeadlineItem,
    Deadlines,
    NotificationPage,
    OpportunityDetail,
    Participation,
    Profile,
    Registration,
    RegistrationPage,
    SearchResult,
    Snapshot,
    WatchlistPage,
    certificate,
    course,
    iso_ist,
    notification,
    parse_dt,
    participation,
    profile,
    registration,
    summarize,
)


class AccountService(CatalogService):

    async def profile(self, tenant: str) -> Profile:
        payload = await self._user_get(tenant, "/api/user/profile", {"e": "true"})
        user = payload.get("data", payload) if isinstance(payload, dict) else {}
        return _parse(profile, user if isinstance(user, dict) else {})

    async def registrations(self, tenant: str, opportunity_type: str, page: int, per_page: int) -> RegistrationPage:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if opportunity_type != "all":
            params |= {"filterName": "type", "filterValue": opportunity_type}
        items, info = await self._paged_items(tenant, "/api/user/registered-opportunities", params)
        regs = _each(registration, items)
        if page == 1:
            fresh = await self._unindexed_registrations(tenant, regs, opportunity_type)
            if fresh:
                regs = fresh + regs
                info["total"] += len(fresh)
        return RegistrationPage(**info, items=regs)

    async def _unindexed_registrations(self, tenant: str, indexed: list[Registration],
                                       opportunity_type: str) -> list[Registration]:
        """Unstop's registrations list is a search index that lags behind new sign-ups. Your team list is
        live, so any team created after the newest indexed registration is fetched directly (max 10)."""
        try:
            payload = await self._user_get(tenant, "/api/user/teams/")
        except UnstopError:
            return []
        teams = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(teams, list):
            return []
        # The baseline is the newest indexed registration of ANY type: the index lags as a whole, so a typed
        # page (e.g. quizzes) must not treat newer hackathon teams as missing.
        if opportunity_type == "all":
            baseline = indexed
        else:
            items, _ = await self._paged_items(tenant, "/api/user/registered-opportunities", {"page": 1, "per_page": 5})
            baseline = _each(registration, items)
        stamps = [ts for r in baseline if (ts := parse_dt(r.registered_at)) is not None]
        if not stamps:
            return []  # nothing indexed to compare against: don't guess
        newest = max(stamps)
        known = {r.id for r in indexed} | {r.id for r in baseline}
        missing = []
        for t in teams:
            if not isinstance(t, dict) or not t.get("opportunity_id") or t["opportunity_id"] in known:
                continue
            created = parse_dt(t.get("created_at"))
            if created is not None and created > newest:
                missing.append(t)
        missing = sorted(missing, key=lambda t: str(t.get("created_at")), reverse=True)[:10]
        details = await gather_limited([self.get_opportunity(t["opportunity_id"]) for t in missing], limit=4)
        out: list[Registration] = []
        for t, d in zip(missing, details, strict=True):
            if not isinstance(d, OpportunityDetail):
                continue
            if opportunity_type not in ("all", d.type) and not (opportunity_type == "internships" and
                                                                  d.subtype == "internships"):
                continue
            regi = t.get("regi_status")
            out.append(Registration(
                id=d.id, title=d.title, type=d.type, opportunity_status=d.status, url=d.url,
                organisation=d.organisation, start_date=d.start_date, end_date=d.end_date,
                registration_deadline=d.registration_deadline, team_name=t.get("team_name"),
                registration_complete=(regi == "complete") if regi else None,
                team_valid=str(t.get("isTeamValid")) == "1" if t.get("isTeamValid") is not None else None,
                registered_at=t.get("created_at"),
            ))
        return out

    async def watchlist(self, tenant: str, opportunity_type: str, page: int, per_page: int) -> WatchlistPage:
        # Unstop answers 500 without a filter; filterValue=all returns everything.
        params = {"page": page, "per_page": per_page, "filterName": "type", "filterValue": opportunity_type}
        items, info = await self._paged_items(tenant, "/api/user/my-watchlist", params)
        return WatchlistPage(**info, items=_each(summarize, items))

    async def certificates(self, tenant: str, page: int, per_page: int) -> CertificatePage:
        items, info = await self._paged_items(tenant, "/api/user/certificates", {"page": page, "per_page": per_page})
        return CertificatePage(**info, items=_each(certificate, items))

    async def _all_certificates(self, tenant: str, max_pages: int = 5) -> list[Certificate]:
        """Every certificate (up to ``max_pages`` x 50), so counts like wins are not limited to one page."""
        first = await self.certificates(tenant, 1, 50)
        items = list(first.items)
        pages = min(first.last_page, max_pages)
        if pages > 1:
            rest = await gather_limited([self.certificates(tenant, n, 50) for n in range(2, pages + 1)], limit=3)
            for r in rest:
                if isinstance(r, CertificatePage):
                    items.extend(r.items)
        return items

    async def participation(self, tenant: str, opportunity: str | int) -> Participation:
        """Round-by-round status plus the authoritative team record. The rounds endpoint returns nothing for
        events whose rounds aren't published yet, so registration is decided by the team record when present."""
        oid = parse_opportunity_id(opportunity)
        pair: tuple[Any, ...] = await asyncio.gather(
            self._user_get(tenant, f"/api/user/check-opportunity-participation/{oid}"),
            self._user_get(tenant, f"/api/registration/restricted/{oid}/", {"editMode": "false"}),
            return_exceptions=True,
        )
        rounds_p, boot_p = pair
        if isinstance(rounds_p, AuthRequired):
            raise rounds_p
        data = rounds_p.get("data") if isinstance(rounds_p, dict) else None
        result = _parse(participation, oid, data if isinstance(data, list) else [])
        boot = _dig(boot_p, "data")
        team = self._team_info(boot) if isinstance(boot, dict) else None
        if team:
            regi = team.get("regi_status")
            result.registered = True
            result.team_id = int(team["id"]) if str(team["id"]).isdigit() else None
            result.team_name = team.get("team_name")
            result.registration_id = team.get("regn_id")
            result.registration_complete = (regi == "complete") if regi else None
        elif isinstance(boot, dict) and not result.rounds:
            result.registered = False
        if not result.title or not result.url:
            try:
                opp = await self.get_opportunity(oid)
                result.title, result.url = result.title or opp.title, result.url or opp.url
            except UnstopError:
                pass
        return result

    async def recommendations(self, tenant: str, opportunity_type: str, page: int, per_page: int) -> SearchResult:
        """Unstop's own personalised picks for the signed-in user (open listings only)."""
        if opportunity_type not in OPPORTUNITY_TYPES:
            raise InvalidInput(f"Unknown type '{opportunity_type}'.")
        params = {"opportunity": opportunity_type, "payment": "all", "oppstatus": "open", "eligible": "all",
                  "page": page, "per_page": per_page}
        payload = await self._user_get(tenant, "/api/opportunity/recommendations", params)
        result = _search_result(payload, page, per_page)
        result.results = result.results[:per_page]
        return result

    async def set_watchlist(self, tenant: str, opportunity: str | int, add: bool) -> dict[str, Any]:
        oid = parse_opportunity_id(opportunity)
        path = f"/api/{'addToWatchlist' if add else 'removeFromWatchlist'}/{oid}/opportunity"
        payload = await self._user_get(tenant, path, cache=False)
        self.http.invalidate(tenant, "/api/user/my-watchlist")
        self.http.invalidate(tenant, "/api/getMyWatchlist")
        ok = not (isinstance(payload, dict) and payload.get("status") is False)
        return {"opportunity_id": oid, "watchlisted": add if ok else (not add), "ok": ok}

    # ------------------------------------------------------------------ notifications, courses

    async def notifications(self, tenant: str, page: int = 1, unread_only: bool = False) -> NotificationPage:
        payload = await self._user_get(tenant, "/api/get-notifications", {"page": page})
        items, meta = _paged(payload)
        notes = _each(notification, [i for i in items if isinstance(i, dict) and i.get("id")])
        if unread_only:
            notes = [n for n in notes if not n.read]
        return NotificationPage(page=_num(meta.get("current_page"), page), has_more=bool(meta.get("next_page_url")),
                                unread_on_page=sum(1 for n in notes if not n.read), items=notes)

    async def mark_notifications_read(self, tenant: str) -> dict[str, Any]:
        payload = await self._user_get(tenant, "/api/markasread-notifications", cache=False)
        self.http.invalidate(tenant, "/api/get-notifications")
        ok = not (isinstance(payload, dict) and payload.get("status") is False)
        return {"ok": ok, "message": "All notifications marked as read." if ok else "Unstop did not confirm."}

    async def courses(self, tenant: str, page: int = 1) -> list[Course]:
        items, _ = await self._paged_items(tenant, "/api/user/enrolled-courses", {"page": page})
        return _each(course, items)

    # ------------------------------------------------------------------ aggregated views

    async def deadlines(self, tenant: str, days: int = 30) -> Deadlines:
        """Everything with a date coming up: live/upcoming rounds, unfinished registrations, watchlisted
        listings whose registration closes soon. Sources are fetched in parallel; a failing source degrades
        the result instead of failing it."""
        await self.auth.get_session(tenant)  # fail fast with a clear "not logged in"
        now = datetime.now(IST)
        horizon = now + timedelta(days=days)

        results: tuple[Any, ...] = await asyncio.gather(
            self._user_get(tenant, "/api/user/my-rounds",
                           {"page": 1, "per_page": 50, "filterName": "status", "filterValue": "live"}),
            self._user_get(tenant, "/api/user/my-rounds",
                           {"page": 1, "per_page": 50, "filterName": "status", "filterValue": "upcoming"}),
            self.registrations(tenant, "all", 1, 30),
            self.watchlist(tenant, "all", 1, 30),
            return_exceptions=True,
        )
        live, upcoming, regs, watch = results
        items: list[DeadlineItem] = []
        errors: list[str] = []

        def add(when: datetime | None, **kw: Any) -> None:
            if when is not None and now <= when <= horizon:
                items.append(DeadlineItem(when=iso_ist(when), days_left=round((when - now).total_seconds() / 86400, 1),
                                          **kw))

        for label, payload, kind in (("live rounds", live, "live"), ("upcoming rounds", upcoming, "upcoming")):
            if isinstance(payload, BaseException):
                if isinstance(payload, AuthRequired):
                    raise payload
                errors.append(f"{label}: {getattr(payload, 'message', type(payload).__name__)}")
                continue
            for rd in _paged(payload)[0]:
                if not isinstance(rd, dict):
                    continue
                entity: dict[str, Any] = rd["entity"] if isinstance(rd.get("entity"), dict) else {}
                common = {
                    "opportunity_id": rd.get("opportunity_id") if isinstance(rd.get("opportunity_id"), int) else None,
                    "opportunity": str(rd.get("opp_title") or rd.get("title") or "Unstop opportunity").strip(),
                    "url": f"https://unstop.com/{str(rd['opp_url']).lstrip('/')}"
                    if isinstance(rd.get("opp_url"), str) and rd["opp_url"] else None,
                    "source": "my_round",
                }
                name = str(entity.get("title") or f"Round {rd.get('round_order') or ''}").strip()
                if kind == "live":
                    add(parse_dt(rd.get("end_date")), kind="round_ends", what=f"{name} ends",
                        action="Take part / submit before the round closes.", **common)
                else:
                    add(parse_dt(rd.get("start_date")), kind="round_starts", what=f"{name} starts",
                        action="Be ready: the round opens at this time.", **common)

        if not isinstance(regs, RegistrationPage):
            errors.append(f"registrations: {getattr(regs, 'message', type(regs).__name__)}")
        else:
            for r in regs.items:
                if r.registration_complete is False:
                    add(parse_dt(r.registration_deadline), kind="registration_closes",
                        what="Registration closes (yours is incomplete)",
                        action="Finish your registration: the form or team is not complete yet.",
                        opportunity_id=r.id, opportunity=r.title, url=r.url, source="incomplete_registration")

        if not isinstance(watch, WatchlistPage):
            errors.append(f"watchlist: {getattr(watch, 'message', type(watch).__name__)}")
        else:
            for w in watch.items:
                if w.registration_open is not False:
                    add(parse_dt(w.registration_deadline), kind="registration_closes", what="Registration closes",
                        action="Register on Unstop if you still want to take part.",
                        opportunity_id=w.id, opportunity=w.title, url=w.url, source="watchlist")

        items.sort(key=lambda i: i.when)  # all ISO strings share the IST offset, so string order is time order
        return Deadlines(generated_at=iso_ist(now), window_days=days, total=len(items), items=items,
                         partial_errors=errors)

    # ------------------------------------------------------------------ insights

    async def eligibility(self, tenant: str, opportunity: str | int) -> Eligibility:
        prof, opp = await asyncio.gather(self.profile(tenant), self.get_opportunity(opportunity))
        return _parse(check_eligibility, prof, opp)

    async def snapshot(self, tenant: str) -> Snapshot:
        """Profile, registration counts per type, certificates/wins, watchlist size and next deadline."""
        types = ["hackathons", "competitions", "quizzes", "jobs", "internships", "scholarships", "workshops"]
        prof = await self.profile(tenant)  # also fails fast with "not logged in"
        reg_calls = [self.registrations(tenant, t, 1, 1) for t in ["all", *types]]
        results: list[Any] = await gather_limited(
            [*reg_calls, self._all_certificates(tenant), self.watchlist(tenant, "all", 1, 1),
             self.deadlines(tenant, 30)],
            limit=6,
        )
        regs = results[: len(reg_calls)]
        certs, watch, dl = results[len(reg_calls):]
        snap = Snapshot(name=prof.name, status=user_status(prof), graduation_year=prof.graduation_year,
                        profile_completion_percent=prof.profile_completion_percent, coins=prof.coins)
        if isinstance(regs[0], RegistrationPage):
            snap.total_registrations = regs[0].total
        else:
            snap.partial_errors.append("registrations")
        for t, r in zip(types, regs[1:], strict=True):
            if isinstance(r, RegistrationPage) and r.total:
                snap.registrations_by_type[t] = r.total
        if isinstance(certs, list):
            snap.certificates_total = len(certs)
            for cert in certs:
                kind = cert.kind or "other"
                snap.certificates_by_kind[kind] = snap.certificates_by_kind.get(kind, 0) + 1
            snap.wins = sum(n for k, n in snap.certificates_by_kind.items()
                            if any(w in k for w in ("winner", "merit", "rank")))
        else:
            snap.partial_errors.append("certificates")
        if isinstance(watch, WatchlistPage):
            snap.watchlist_total = watch.total
        else:
            snap.partial_errors.append("watchlist")
        if isinstance(dl, Deadlines):
            snap.upcoming_deadlines = dl.total
            snap.next_deadline = dl.items[0] if dl.items else None
        else:
            snap.partial_errors.append("deadlines")
        return snap
