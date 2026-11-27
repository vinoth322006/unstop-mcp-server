"""Toolset "registration": two-step, token-confirmed registration and cancellation."""

from __future__ import annotations

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from unstop_mcp.auth.api_keys import SCOPE_READ, SCOPE_WRITE
from unstop_mcp.registration import RegistrationPlan, RegistrationResult
from unstop_mcp.tools._common import (
    DESTRUCTIVE,
    READ_ONLY_PRIVATE,
    OppRef,
    TeamName,
    ToolContext,
    audit,
    current_tenant,
    require_scope,
)

INSTRUCTIONS = """\
- "Register me for X" -> prepare_registration, show the user the title and will_submit details, and ONLY after they
  explicitly confirm call register_for_opportunity with the confirmation_token. Never register without a clear yes.
  If prepare_registration lists blockers, give the user the URL instead. Undo with cancel_registration."""

REGISTER = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True)


def register(ctx: ToolContext) -> None:
    mcp, guard, rt = ctx.mcp, ctx.guard, ctx.rt

    @mcp.tool(title="Check if I can register (no changes)", annotations=READ_ONLY_PRIVATE)
    @guard
    async def prepare_registration(opportunity: OppRef, team_name: TeamName = None) -> RegistrationPlan:
        """Step 1 of registering. Checks whether the user can be registered automatically (free, no custom form,
        no verification, eligible, not already registered), shows exactly what would be submitted, and returns a
        confirmation_token. Changes nothing. Show the result to the user and ask them to confirm."""
        require_scope(SCOPE_READ)
        return await rt.client.prepare_registration(current_tenant(), opportunity, team_name)

    if not ctx.writes:
        return

    @mcp.tool(title="Register for an opportunity", annotations=REGISTER)
    @guard
    async def register_for_opportunity(
        opportunity: OppRef,
        confirmation_token: Annotated[str, Field(min_length=10, max_length=80,
                                                 description="From prepare_registration, after the user said yes")],
        team_name: TeamName = None,
    ) -> RegistrationResult:
        """Step 2: register the user on Unstop. Only call after prepare_registration and the user's explicit
        confirmation. Re-checks every rule before submitting; registering twice is harmless."""
        require_scope(SCOPE_WRITE)
        result = await rt.client.register(current_tenant(), opportunity, confirmation_token, team_name)
        audit("register_for_opportunity", opportunity_id=result.opportunity_id, registered=result.registered,
              team_id=result.team_id)
        return result

    @mcp.tool(title="Cancel a registration", annotations=DESTRUCTIVE)
    @guard
    async def cancel_registration(opportunity: OppRef) -> RegistrationResult:
        """Cancel the user's registration for an opportunity (withdraws them and their team). Confirm with the
        user first."""
        require_scope(SCOPE_WRITE)
        result = await rt.client.cancel_registration(current_tenant(), opportunity)
        audit("cancel_registration", opportunity_id=result.opportunity_id, team_id=result.team_id)
        return result
