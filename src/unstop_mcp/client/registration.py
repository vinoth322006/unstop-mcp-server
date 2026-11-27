"""Registering for opportunities (two-step, token-confirmed) and cancelling."""

from __future__ import annotations

import asyncio
from typing import Any

from unstop_mcp.client._base import (
    _dig,
    _parse,
    parse_opportunity_id,
)
from unstop_mcp.client.account import AccountService
from unstop_mcp.errors import InvalidInput, ManualStep, NotFound, UnstopError, UpstreamError
from unstop_mcp.insights import check_eligibility
from unstop_mcp.models import (
    detail,
    profile,
)
from unstop_mcp.registration import (
    RegistrationPlan,
    RegistrationResult,
    build_payload,
    check_token,
    evaluate,
    make_token,
    summary_of,
)


class RegistrationService(AccountService):

    async def _registration_context(self, tenant: str, oid: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        boot_p, prof_p, opp_p = await asyncio.gather(
            self._user_get(tenant, f"/api/registration/restricted/{oid}/", {"editMode": "false"}, cache=False),
            self._user_get(tenant, "/api/user/profile", cache=False),
            self.http.request("GET", f"/api/public/competition/{oid}", cache=True),
        )
        boot = _dig(boot_p, "data")
        prof = prof_p.get("data", prof_p) if isinstance(prof_p, dict) else None
        opp = _dig(opp_p, "data", "competition")
        if not isinstance(opp, dict) or not opp.get("id"):
            raise NotFound(f"No Unstop opportunity with id {oid}.")
        if not isinstance(boot, dict) or not isinstance(prof, dict):
            raise UnstopError("Unstop did not return the registration form for this opportunity.")
        if not isinstance(boot.get("regnRequirements"), dict | type(None)):
            raise UpstreamError("Unstop sent the registration form in an unexpected format. Try again later.")
        return boot, prof, opp

    async def prepare_registration(self, tenant: str, opportunity: str | int,
                                   team_name: str | None = None) -> RegistrationPlan:
        oid = parse_opportunity_id(opportunity)
        boot, prof, opp = await self._registration_context(tenant, oid)
        title, url = str(opp.get("title") or "").strip(), _parse(detail, opp).url
        if self._team_info(boot):
            return RegistrationPlan(opportunity_id=oid, title=title, url=url, can_register=False, already_registered=True,
                                    next_step="You're already registered. Use my_participation to see your rounds.")
        blockers, notes = _parse(evaluate, boot, prof, opp)
        verdict = _parse(check_eligibility, _parse(profile, prof), _parse(detail, opp))
        if verdict.verdict == "likely_not_eligible":
            blockers.append(verdict.summary)
        elif verdict.verdict == "unclear" and verdict.checks:
            notes.append(verdict.summary)
        payload = _parse(build_payload, boot, prof, (team_name or "").strip() or None)
        if blockers:
            return RegistrationPlan(opportunity_id=oid, title=title, url=url, can_register=False, blockers=blockers,
                                    notes=notes, next_step=f"Can't register automatically. Tell the user to register "
                                                           f"themselves on unstop.com: {url}")
        return RegistrationPlan(
            opportunity_id=oid, title=title, url=url, can_register=True, notes=notes,
            will_submit=_parse(summary_of, payload), confirmation_token=make_token(tenant, oid),
            next_step="Show the user the title and will_submit details and ask them to confirm. Only after they say "
                      "yes, call register with this confirmation_token.",
        )

    async def register(self, tenant: str, opportunity: str | int, confirmation_token: str,
                       team_name: str | None = None) -> RegistrationResult:
        oid = parse_opportunity_id(opportunity)
        check_token(confirmation_token, tenant, oid)
        boot, prof, opp = await self._registration_context(tenant, oid)  # re-check: things may have changed
        title, url = str(opp.get("title") or "").strip(), _parse(detail, opp).url
        if self._team_info(boot):
            team = self._team_info(boot) or {}
            return RegistrationResult(opportunity_id=oid, title=title, registered=True, team_id=int(team["id"]),
                                      registration_id=team.get("regn_id"), message="You were already registered.",
                                      url=url)
        blockers, _ = _parse(evaluate, boot, prof, opp)
        verdict = _parse(check_eligibility, _parse(profile, prof), _parse(detail, opp))
        if verdict.verdict == "likely_not_eligible":
            blockers.append(verdict.summary)
        if blockers:
            raise ManualStep(" ".join(blockers), url)
        payload = _parse(build_payload, boot, prof, (team_name or "").strip() or None)
        resp = await self._user_call(tenant, "POST", f"/api/registration/team/{oid}/create", payload)
        self.http.invalidate(tenant)  # registrations, deadlines, participation all changed
        if not isinstance(resp, dict) or not resp.get("status"):
            msg = (resp.get("message") if isinstance(resp, dict) else None) or "Unstop did not accept the registration"
            raise ManualStep(f"Unstop said: {msg}", url)
        team = _dig(resp, "data", "oRegisteredTeam")
        team = team if isinstance(team, dict) else {}
        return RegistrationResult(
            opportunity_id=oid, title=title, registered=True,
            team_id=int(team["id"]) if str(team.get("id", "")).isdigit() else None,
            registration_id=team.get("regn_id"),
            complete=(team.get("regi_status") == "complete") if team.get("regi_status") else None,
            message=str(resp.get("message") or "Registered."), url=url,
        )

    async def cancel_registration(self, tenant: str, opportunity: str | int) -> RegistrationResult:
        oid = parse_opportunity_id(opportunity)
        boot, _, opp = await self._registration_context(tenant, oid)
        title, url = str(opp.get("title") or "").strip(), _parse(detail, opp).url
        team = self._team_info(boot)
        if not team:
            return RegistrationResult(opportunity_id=oid, title=title, registered=False,
                                      message="You are not registered for this one.", url=url)
        resp = await self._user_call(tenant, "DELETE", f"/api/registration/cancel/{oid}/{team['id']}")
        self.http.invalidate(tenant)
        if not isinstance(resp, dict) or not resp.get("status"):
            msg = (resp.get("message") if isinstance(resp, dict) else None) or "Unstop did not cancel it."
            raise InvalidInput(f"Unstop said: {msg}")
        return RegistrationResult(opportunity_id=oid, title=title, registered=False, team_id=int(team["id"]),
                                  message=str(resp.get("message") or "Registration cancelled."), url=url)
