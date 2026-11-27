"""Toolset "teams": members, past teammates, invitations and join requests."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from unstop_mcp.auth.api_keys import SCOPE_READ, SCOPE_WRITE
from unstop_mcp.teams import Team, TeamActionResult, TeamInbox, TeammateSuggestion
from unstop_mcp.tools._common import (
    DESTRUCTIVE,
    READ_ONLY_PRIVATE,
    WRITE_OPEN,
    Email,
    InviteId,
    OppRef,
    ToolContext,
    audit,
    current_tenant,
    require_scope,
)

INSTRUCTIONS = """\
- Teams: my_team (members, spots left), suggest_teammates (people they've teamed with), invite_teammate (by email or
  teammate_id; confirm with the user first; it emails a real person), team_invitations, respond_to_invitation,
  respond_to_join_request, cancel_invitation, remove_team_member, leave_team."""


def register(ctx: ToolContext) -> None:
    mcp, guard, rt = ctx.mcp, ctx.guard, ctx.rt

    @mcp.tool(title="My team", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_team(opportunity: OppRef) -> Team:
        """The user's team for one opportunity: members (with player_id), who leads, team size limits, spots left
        and whether invitations are allowed."""
        require_scope(SCOPE_READ)
        return await rt.client.team(current_tenant(), opportunity)

    @mcp.tool(title="Suggest teammates", annotations=READ_ONLY_PRIVATE)
    @guard
    async def suggest_teammates(opportunity: OppRef) -> list[TeammateSuggestion]:
        """People the user has been in teams with before (name, organisation, course), each with a teammate_id that
        invite_teammate accepts. Contact details are never shown."""
        require_scope(SCOPE_READ)
        return await rt.client.teammate_suggestions(current_tenant(), opportunity)

    @mcp.tool(title="Team invitations and requests", annotations=READ_ONLY_PRIVATE)
    @guard
    async def team_invitations(opportunity: OppRef) -> TeamInbox:
        """For one opportunity: invitations the user's team sent, invitations the user received, requests to join
        their team, and their own join requests. Each has an id for the respond/cancel tools."""
        require_scope(SCOPE_READ)
        return await rt.client.team_inbox(current_tenant(), opportunity)

    if not ctx.writes:
        return

    @mcp.tool(title="Invite a teammate", annotations=WRITE_OPEN)
    @guard
    async def invite_teammate(
        opportunity: OppRef,
        email: Email = None,
        teammate_id: Annotated[int | None, Field(gt=0, description="From suggest_teammates")] = None,
    ) -> TeamActionResult:
        """Invite someone to the user's team for this opportunity, by email address or by a teammate_id from
        suggest_teammates. Unstop emails them an invitation. Confirm the person with the user first."""
        require_scope(SCOPE_WRITE)
        result = await rt.client.invite_teammate(current_tenant(), opportunity, email, teammate_id)
        audit("invite_teammate", opportunity_id=result.opportunity_id, by="teammate_id" if teammate_id else "email")
        return result

    @mcp.tool(title="Cancel an invitation", annotations=DESTRUCTIVE)
    @guard
    async def cancel_invitation(invitation_id: InviteId) -> TeamActionResult:
        """Withdraw an invitation the user's team sent (id from team_invitations.invitations_sent)."""
        require_scope(SCOPE_WRITE)
        result = await rt.client.cancel_invitation(current_tenant(), invitation_id)
        audit("cancel_invitation", invitation_id=invitation_id)
        return result

    @mcp.tool(title="Answer a team invitation", annotations=WRITE_OPEN)
    @guard
    async def respond_to_invitation(
        invitation_id: InviteId,
        accept: Annotated[bool, Field(description="true = join that team, false = decline")],
    ) -> TeamActionResult:
        """Accept or decline an invitation the user received (id from team_invitations.invitations_received).
        Accepting joins that team. Confirm with the user first."""
        require_scope(SCOPE_WRITE)
        result = await rt.client.respond_to_invitation(current_tenant(), invitation_id, accept)
        audit("respond_to_invitation", invitation_id=invitation_id, accept=accept)
        return result

    @mcp.tool(title="Answer a join request", annotations=WRITE_OPEN)
    @guard
    async def respond_to_join_request(
        request_id: InviteId,
        accept: Annotated[bool, Field(description="true = let them join, false = decline")],
    ) -> TeamActionResult:
        """Accept or decline someone's request to join the user's team (id from
        team_invitations.join_requests_received)."""
        require_scope(SCOPE_WRITE)
        result = await rt.client.respond_to_join_request(current_tenant(), request_id, accept)
        audit("respond_to_join_request", request_id=request_id, accept=accept)
        return result

    @mcp.tool(title="Remove a team member", annotations=DESTRUCTIVE)
    @guard
    async def remove_team_member(
        opportunity: OppRef,
        player_id: Annotated[int, Field(gt=0, description="player_id from my_team")],
    ) -> TeamActionResult:
        """Remove a member from the user's team (team leader only). Confirm with the user first."""
        require_scope(SCOPE_WRITE)
        result = await rt.client.remove_team_member(current_tenant(), opportunity, player_id)
        audit("remove_team_member", opportunity_id=result.opportunity_id, player_id=player_id)
        return result

    @mcp.tool(title="Leave a team", annotations=DESTRUCTIVE)
    @guard
    async def leave_team(opportunity: OppRef) -> TeamActionResult:
        """Leave a team the user joined (members only; a leader withdraws with cancel_registration)."""
        require_scope(SCOPE_WRITE)
        result = await rt.client.leave_team(current_tenant(), opportunity)
        audit("leave_team", opportunity_id=result.opportunity_id)
        return result
