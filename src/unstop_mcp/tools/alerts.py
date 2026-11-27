"""Toolset "alerts": saved searches that report what's new since the last check (stored on the user's machine)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from unstop_mcp.auth.api_keys import SCOPE_READ
from unstop_mcp.models import AlertsReport, SearchAlert
from unstop_mcp.searches import SavedSearch
from unstop_mcp.tools._common import (
    LOCAL_DESTRUCTIVE,
    LOCAL_WRITE,
    READ_ONLY_PRIVATE,
    OppType,
    ToolContext,
    current_tenant,
    require_scope,
)

INSTRUCTIONS = """\
- "Tell me when new X appear" -> save_search; later "anything new?" -> check_saved_searches."""


def register(ctx: ToolContext) -> None:
    mcp, guard, rt = ctx.mcp, ctx.guard, ctx.rt

    @mcp.tool(title="Save a search", annotations=LOCAL_WRITE)
    @guard
    async def save_search(
        name: Annotated[str, Field(min_length=1, max_length=60, description="Short name, e.g. 'AI hackathons'")],
        query: Annotated[str | None, Field(max_length=120, description="Keywords")] = None,
        opportunity_type: Annotated[OppType, Field(description="Category")] = "all",
        payment: Annotated[Literal["free", "paid", "all"], Field(description="Entry fee")] = "all",
        region: Annotated[Literal["online", "offline", "all"], Field(description="Mode")] = "all",
    ) -> SearchAlert:
        """Save a search so the user can later ask "anything new?". Returns what currently matches; future
        check_saved_searches calls report only listings that appeared after this. Saving the same name replaces it."""
        require_scope(SCOPE_READ)
        search = SavedSearch(name=name.strip(), query=query, opportunity_type=opportunity_type, payment=payment,
                             region=region)
        return await rt.client.save_search(current_tenant(), search)

    @mcp.tool(title="Check saved searches for new listings", annotations=READ_ONLY_PRIVATE)
    @guard
    async def check_saved_searches(
        name: Annotated[str | None, Field(description="Only this saved search (default: all)")] = None,
    ) -> AlertsReport:
        """New open listings for the user's saved searches since the last check (each listing is reported once)."""
        require_scope(SCOPE_READ)
        return await rt.client.check_searches(current_tenant(), name)

    @mcp.tool(title="List saved searches", annotations=READ_ONLY_PRIVATE)
    @guard
    async def list_saved_searches() -> list[dict[str, Any]]:
        """The user's saved searches (name, keywords, type, filters, when last checked, how many listings tracked)."""
        require_scope(SCOPE_READ)
        return [s.model_dump(exclude={"seen_ids"}) | {"tracked_listings": len(s.seen_ids)}
                for s in rt.client.list_searches(current_tenant())]

    @mcp.tool(title="Delete a saved search", annotations=LOCAL_DESTRUCTIVE)
    @guard
    async def delete_saved_search(name: Annotated[str, Field(min_length=1, max_length=60)]) -> dict[str, Any]:
        """Delete one of the user's saved searches by name."""
        require_scope(SCOPE_READ)
        rt.client.delete_search(current_tenant(), name)
        return {"deleted": name}
