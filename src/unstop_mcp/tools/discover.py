"""Toolset "discover": public Unstop data, no sign-in needed."""

from __future__ import annotations

import json
from typing import Annotated, Literal

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from unstop_mcp.errors import UnstopError
from unstop_mcp.models import (
    OPPORTUNITY_TYPES,
    REGISTRATION_TYPES,
    Comparison,
    Leaderboard,
    OpportunityDetail,
    Organisation,
    SearchResult,
)
from unstop_mcp.tools._common import READ_ONLY, OppRef, OppType, PageNo, PerPage, ToolContext

INSTRUCTIONS = """\
- "Find me X" -> search_opportunities (no login needed). Then get_opportunity for full details of the best ones,
  or compare_opportunities to put 2-5 side by side.
- "What closes this week?" -> closing_soon. "Who runs this?" -> get_organisation (use organisation_id)."""


def register(ctx: ToolContext) -> None:
    mcp, guard, rt = ctx.mcp, ctx.guard, ctx.rt

    @mcp.tool(title="Search Unstop opportunities", annotations=READ_ONLY)
    @guard
    async def search_opportunities(
        query: Annotated[str | None, Field(max_length=120,
                                           description="Keywords, e.g. 'AI', 'case study', 'python intern'")] = None,
        opportunity_type: Annotated[OppType, Field(description="Category to search")] = "all",
        status: Annotated[Literal["open", "closed", "all"], Field(description="Registration status")] = "open",
        payment: Annotated[Literal["free", "paid", "all"], Field(description="Entry fee filter")] = "all",
        region: Annotated[Literal["online", "offline", "all"], Field(description="Mode")] = "all",
        sort: Annotated[
            Literal["relevance", "prize", "deadline"],
            Field(description="relevance (Unstop default), prize (biggest first, across all pages), "
                              "deadline (soonest first within the returned page)"),
        ] = "relevance",
        page: PageNo = 1,
        per_page: PerPage = 10,
    ) -> SearchResult:
        """Search live Unstop listings (hackathons, competitions, jobs, internships, quizzes, scholarships...).

        Returns compact summaries with deadline, prize, team size, eligibility and URL.
        Use get_opportunity for full details or compare_opportunities to weigh several."""
        return await rt.client.search(opportunity_type=opportunity_type, query=query, status=status, payment=payment,
                                      region=region, sort=sort, page=page, per_page=per_page)

    @mcp.tool(title="Get opportunity details", annotations=READ_ONLY)
    @guard
    async def get_opportunity(opportunity: OppRef) -> OpportunityDetail:
        """Full details of one Unstop opportunity: description, prizes, rounds/timeline, eligibility,
        team size, job details (for jobs/internships) and registration deadline."""
        return await rt.client.get_opportunity(opportunity)

    @mcp.tool(title="Compare opportunities", annotations=READ_ONLY)
    @guard
    async def compare_opportunities(
        opportunities: Annotated[list[OppRef], Field(min_length=2, max_length=5,
                                                     description="2-5 ids or unstop.com URLs")],
    ) -> Comparison:
        """Fetch 2-5 opportunities in parallel for a side-by-side comparison of prizes, deadlines, team size,
        eligibility, rounds and (shortened) descriptions. Ids that fail are listed under errors."""
        return await rt.client.compare(list(opportunities))

    @mcp.tool(title="Closing soon", annotations=READ_ONLY)
    @guard
    async def closing_soon(
        days: Annotated[int, Field(ge=1, le=30, description="Registration closes within this many days")] = 7,
        opportunity_type: Annotated[OppType, Field(description="Category")] = "all",
        query: Annotated[str | None, Field(max_length=120, description="Optional keywords")] = None,
    ) -> SearchResult:
        """Open listings whose registration closes within the next N days, soonest first. Scans the 120 most
        recent open listings for the type/keywords (Unstop has no deadline sort), so narrow with a type or query."""
        return await rt.client.closing_soon(days=days, opportunity_type=opportunity_type, query=query)

    @mcp.tool(title="Organisation details", annotations=READ_ONLY)
    @guard
    async def get_organisation(
        organisation: Annotated[str, Field(min_length=1, max_length=300,
                                           description="Organisation id (organisation_id from a listing) or its URL")],
    ) -> Organisation:
        """About an organiser/company/college on Unstop: name, location, website, about, mission, profile URL."""
        return await rt.client.get_organisation(organisation)

    @mcp.tool(title="Unstop leaderboard", annotations=READ_ONLY)
    @guard
    async def unstop_leaderboard(page: PageNo = 1, per_page: PerPage = 20) -> Leaderboard:
        """Unstop's global leaderboard (points earned across competitions): rank, name, organisation, points."""
        return await rt.client.leaderboard(page, per_page)

    @mcp.resource("unstop://opportunity-types", name="opportunity-types", mime_type="application/json")
    def opportunity_types() -> str:
        """Valid values for opportunity_type in search_opportunities and my_registrations."""
        return json.dumps({"search": OPPORTUNITY_TYPES, "registrations": REGISTRATION_TYPES}, indent=2)

    @mcp.resource("unstop://opportunity/{opportunity_id}", name="opportunity", mime_type="application/json")
    async def opportunity_resource(opportunity_id: str) -> str:
        """One opportunity as JSON (same data as get_opportunity)."""
        try:
            item = await rt.client.get_opportunity(opportunity_id)
        except UnstopError as exc:
            raise ToolError(exc.message) from exc
        return item.model_dump_json(indent=2)

    @mcp.prompt(name="find_opportunities", title="Find opportunities for me")
    def find_opportunities(goal: str, constraints: str = "") -> str:
        """Shortlist live Unstop opportunities that fit a goal."""
        return (
            f"Find Unstop opportunities for this goal: {goal}.\n"
            + (f"Constraints: {constraints}.\n" if constraints else "")
            + "If I'm signed in, call my_profile and recommended_for_me first. Then use search_opportunities with 2-3 "
            "keyword variations and the right opportunity_type, and compare_opportunities on the best 3-5. Check "
            "eligibility and team size against the constraints. Return a ranked shortlist: title, why it fits, "
            "deadline, prize/stipend, team size, and the URL."
        )
