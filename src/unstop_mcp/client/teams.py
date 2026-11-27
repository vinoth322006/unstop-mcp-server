"""Team management: members, past teammates, invitations and join requests."""

from __future__ import annotations

import asyncio
from typing import Any

from unstop_mcp.client._base import (
    _each,
    _parse,
    parse_opportunity_id,
)
from unstop_mcp.client.registration import RegistrationService
from unstop_mcp.errors import AuthRequired, InvalidInput, ManualStep
from unstop_mcp.models import (
    detail,
)
from unstop_mcp.teams import (
    EMAIL_RE,
    Team,
    TeamActionResult,
    TeamInbox,
    TeammateSuggestion,
    invitation,
    list_from,
    suggestion,
    team_from_boot,
)


class TeamsService(RegistrationService):

    # ------------------------------------------------------------------ teams

    async def _my_user_id(self, tenant: str) -> int | None:
        session = await self.auth.get_session(tenant)
        if session.user_id:
            return session.user_id
        return (await self.profile(tenant)).id

    async def team(self, tenant: str, opportunity: str | int) -> Team:
        oid = parse_opportunity_id(opportunity)
        boot, _, opp = await self._registration_context(tenant, oid)
        result = _parse(team_from_boot, boot, oid, await self._my_user_id(tenant))
        result.opportunity, result.url = str(opp.get("title") or "").strip(), _parse(detail, opp).url
        if result.registered and not result.invites_allowed and (result.max_team_size or 1) > 1:
            result.message = "This team is full or the organiser doesn't allow invitations."
        elif result.registered and (result.max_team_size or 1) <= 1:
            result.message = "This is a solo event; there is no team to manage."
        return result

    async def _require_team(self, tenant: str, opportunity: str | int) -> Team:
        team = await self.team(tenant, opportunity)
        if not team.registered or team.team_id is None:
            raise InvalidInput("You're not registered for this one yet. Use prepare_registration first.")
        return team

    async def _previous_teammates(self, tenant: str, team: Team) -> list[dict[str, Any]]:
        payload = await self._user_get(tenant, f"/api/registration/previousTeams-player/{team.opportunity_id}/"
                                               f"{team.team_id}")
        return list_from(payload)

    async def teammate_suggestions(self, tenant: str, opportunity: str | int) -> list[TeammateSuggestion]:
        """People you've been in a team with before (privacy-filtered: no emails or phone numbers)."""
        team = await self._require_team(tenant, opportunity)
        members = {m.name.lower() for m in team.members}
        out = []
        for s in _each(suggestion, await self._previous_teammates(tenant, team)):
            if s and s.name.lower() not in members:
                out.append(s)
        return out

    async def team_inbox(self, tenant: str, opportunity: str | int) -> TeamInbox:
        oid = parse_opportunity_id(opportunity)
        base = "/api/registration"
        calls: tuple[Any, ...] = await asyncio.gather(
            self._user_get(tenant, f"{base}/team/target/getAll/invitation/{oid}", cache=False),
            self._user_get(tenant, f"{base}/team/source/getAll/invitation/{oid}", cache=False),
            self._user_get(tenant, f"{base}/team/target/getAll/request/{oid}", cache=False),
            self._user_get(tenant, f"{base}/user/getAll/request/{oid}", cache=False),
            return_exceptions=True,
        )
        if any(isinstance(c, AuthRequired) for c in calls):
            raise next(c for c in calls if isinstance(c, AuthRequired))
        sent, received, req_in, req_out = (c if not isinstance(c, BaseException) else {} for c in calls)

        def conv(payload: Any, key: str, direction: str) -> list[Any]:
            return [i for i in _each(lambda r: invitation(r, direction), list_from(payload, key)) if i]

        return TeamInbox(
            opportunity_id=oid,
            invitations_sent=conv(sent, "outgoingInvitation", "sent"),
            invitations_received=conv(received, "incomingInvitation", "received"),
            join_requests_received=conv(req_in, "incomingRequets", "request_received"),  # sic: Unstop's key
            join_requests_sent=conv(req_out, "outgoingRequests", "request_sent"),
        )

    async def _team_write(self, tenant: str, method: str, path: str, body: dict[str, Any] | None,
                          ok_message: str, opportunity_id: int | None = None, url: str | None = None) -> TeamActionResult:
        resp = await self._user_call(tenant, method, path, body)
        self.http.invalidate(tenant)
        if not isinstance(resp, dict) or not resp.get("status"):
            msg = (resp.get("message") if isinstance(resp, dict) else None) or "Unstop did not accept this"
            raise ManualStep(f"Unstop said: {msg}", url)
        return TeamActionResult(ok=True, message=str(resp.get("message") or ok_message),
                                opportunity_id=opportunity_id, url=url)

    async def invite_teammate(self, tenant: str, opportunity: str | int, email: str | None = None,
                              teammate_id: int | None = None) -> TeamActionResult:
        team = await self._require_team(tenant, opportunity)
        if (team.max_team_size or 1) <= 1:
            raise ManualStep("this is a solo event, so it has no team to invite people to", team.url)
        if not team.spots_left:
            raise ManualStep(f"your team is already full ({team.max_team_size} members)", team.url)
        if not team.invites_allowed:
            raise ManualStep("the organiser doesn't allow invitations for this event", team.url)
        if bool(email) == bool(teammate_id):
            raise InvalidInput("Give either an email address or a teammate_id from suggest_teammates.")
        if teammate_id is not None:
            match = next((r for r in await self._previous_teammates(tenant, team) if str(r.get("id")) == str(teammate_id)),
                         None)
            if not match or not match.get("email"):
                raise InvalidInput("That teammate_id isn't in your suggestions. Call suggest_teammates again.")
            email = str(match["email"])
            who = _each(suggestion, [match])
            label = who[0].name if who and who[0] else "your teammate"
        else:
            email = (email or "").strip()
            if not EMAIL_RE.fullmatch(email):
                raise InvalidInput("That doesn't look like a valid email address.")
            label = email
        me = await self.auth.get_session(tenant)
        if me.email and email.lower() == me.email.lower():
            raise InvalidInput("You can't invite yourself.")
        return await self._team_write(
            tenant, "POST", "/api/registration/send-invitation-request-by-email",
            {"targetTeamId": team.team_id, "email": email}, f"Invitation sent to {label}.", team.opportunity_id, team.url)

    async def cancel_invitation(self, tenant: str, invitation_id: int) -> TeamActionResult:
        return await self._team_write(tenant, "POST", f"/api/registration/invitation/team/delete/{int(invitation_id)}",
                                      {}, "Invitation cancelled.")

    async def respond_to_invitation(self, tenant: str, invitation_id: int, accept: bool) -> TeamActionResult:
        action = "accept" if accept else "decline"
        return await self._team_write(tenant, "POST", f"/api/registration/invitation/{action}/{int(invitation_id)}", {},
                                      "Invitation accepted: you joined the team." if accept else "Invitation declined.")

    async def respond_to_join_request(self, tenant: str, request_id: int, accept: bool) -> TeamActionResult:
        action = "accept" if accept else "decline"
        return await self._team_write(tenant, "POST", f"/api/registration/request/{action}/{int(request_id)}", {},
                                      "Request accepted: they joined your team." if accept else "Request declined.")

    async def remove_team_member(self, tenant: str, opportunity: str | int, player_id: int) -> TeamActionResult:
        team = await self._require_team(tenant, opportunity)
        if not team.you_are_leader:
            raise ManualStep("only the team leader can remove members", team.url)
        member = next((m for m in team.members if m.player_id == int(player_id)), None)
        if member is None:
            raise InvalidInput("That player_id isn't on your team. Call my_team to see member ids.")
        if member.is_you:
            raise InvalidInput("You can't remove yourself. To withdraw the whole team use cancel_registration.")
        return await self._team_write(tenant, "DELETE", f"/api/registration/delete/player/{team.opportunity_id}/"
                                                        f"{member.player_id}", None,
                                      f"Removed {member.name} from the team.", team.opportunity_id, team.url)

    async def leave_team(self, tenant: str, opportunity: str | int) -> TeamActionResult:
        team = await self._require_team(tenant, opportunity)
        me = next((m for m in team.members if m.is_you), None)
        if me is None or me.player_id is None:
            raise ManualStep("Unstop didn't show you as a member of this team", team.url)
        if team.you_are_leader:
            raise ManualStep("you're the team leader. Use cancel_registration to withdraw the whole team, or hand "
                             "leadership to a teammate", team.url)
        return await self._team_write(tenant, "DELETE", f"/api/registration/delete/player/{team.opportunity_id}/"
                                                        f"{me.player_id}", None,
                                      "You left the team.", team.opportunity_id, team.url)
