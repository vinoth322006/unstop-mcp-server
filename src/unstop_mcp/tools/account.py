"""Toolset "account": the signed-in user's own Unstop data, plus watchlist/notification writes and calendar export."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from unstop_mcp.auth.api_keys import SCOPE_READ, SCOPE_WRITE
from unstop_mcp.errors import PermissionDenied, UnstopError
from unstop_mcp.ics import deadlines_to_ics
from unstop_mcp.insights import Eligibility
from unstop_mcp.models import (
    CertificatePage,
    Course,
    Deadlines,
    NotificationPage,
    Participation,
    Profile,
    RegistrationPage,
    SearchResult,
    Snapshot,
    WatchlistPage,
)
from unstop_mcp.runtime import downloads_dir
from unstop_mcp.tools._common import (
    LOCAL_WRITE,
    READ_ONLY_PRIVATE,
    WRITE,
    OppRef,
    OppType,
    PageNo,
    PerPage,
    RegType,
    ToolContext,
    audit,
    current_tenant,
    require_scope,
)

INSTRUCTIONS = """\
- "Can I apply? / Am I eligible?" -> check_eligibility (compares the user's profile with the published rules).
- "What should I apply to?" -> recommended_for_me (personalised by Unstop) plus my_profile for context.
- "What's due / what's next?" -> my_deadlines (rounds, unfinished registrations, watchlist deadlines, in date order).
- "How am I doing on Unstop?" -> my_snapshot (registrations by type, wins, certificates, coins, next deadline).
- "Any updates?" -> my_notifications (results, registrations, team activity). my_courses for learning progress.
- "Put my deadlines in my calendar" -> save_deadlines_calendar (writes an .ics file the user can import).
- "Did I register / how did I do?" -> my_registrations, my_participation, my_certificates.
- Save a listing for later -> add_to_watchlist."""


def register(ctx: ToolContext) -> None:
    mcp, guard, rt = ctx.mcp, ctx.guard, ctx.rt

    @mcp.tool(title="My Unstop profile", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_profile() -> Profile:
        """The signed-in user's Unstop profile: name, specialization, study/graduation year, summary,
        profile completion. Never includes the phone number."""
        require_scope(SCOPE_READ)
        return await rt.client.profile(current_tenant())

    @mcp.tool(title="My Unstop snapshot", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_snapshot() -> Snapshot:
        """One-glance overview: registrations by type, certificates and wins, watchlist size, profile
        completion and the next upcoming deadline."""
        require_scope(SCOPE_READ)
        return await rt.client.snapshot(current_tenant())

    @mcp.tool(title="Am I eligible?", annotations=READ_ONLY_PRIVATE)
    @guard
    async def check_eligibility(opportunity: OppRef) -> Eligibility:
        """Check the signed-in user's profile (graduation year, course/specialization, student/fresher status)
        against an opportunity's published eligibility rules. Returns a verdict with a reason per rule."""
        require_scope(SCOPE_READ)
        return await rt.client.eligibility(current_tenant(), opportunity)

    @mcp.tool(title="My upcoming deadlines", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_deadlines(
        days: Annotated[int, Field(ge=1, le=180, description="How far ahead to look")] = 30,
    ) -> Deadlines:
        """Everything coming up in date order: rounds that are live or about to start, registrations the user
        hasn't finished, and watchlisted listings whose registration closes soon, each with what to do next."""
        require_scope(SCOPE_READ)
        return await rt.client.deadlines(current_tenant(), days)

    @mcp.tool(title="Recommended for me", annotations=READ_ONLY_PRIVATE)
    @guard
    async def recommended_for_me(
        opportunity_type: Annotated[OppType, Field(description="Category")] = "all",
        page: PageNo = 1,
        per_page: PerPage = 10,
    ) -> SearchResult:
        """Open opportunities Unstop recommends for the signed-in user (based on their profile and activity)."""
        require_scope(SCOPE_READ)
        return await rt.client.recommendations(current_tenant(), opportunity_type, page, per_page)

    @mcp.tool(title="My registrations", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_registrations(
        opportunity_type: Annotated[RegType, Field(description="Which kind of registrations")] = "all",
        page: PageNo = 1,
        per_page: PerPage = 10,
    ) -> RegistrationPage:
        """Opportunities the signed-in user registered or applied for, newest first: opportunity status,
        deadline, team name/size, whether the registration is complete, and whether they were rejected."""
        require_scope(SCOPE_READ)
        return await rt.client.registrations(current_tenant(), opportunity_type, page, per_page)

    @mcp.tool(title="Check my participation", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_participation(opportunity: OppRef) -> Participation:
        """Whether the signed-in user is registered for one opportunity, and their status in each round
        (round dates, finished/live, participated, can play now)."""
        require_scope(SCOPE_READ)
        return await rt.client.participation(current_tenant(), opportunity)

    @mcp.tool(title="My watchlist", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_watchlist(
        opportunity_type: Annotated[RegType, Field(description="Filter by kind")] = "all",
        page: PageNo = 1,
        per_page: PerPage = 10,
    ) -> WatchlistPage:
        """Opportunities the signed-in user saved to their Unstop watchlist (same summary shape as search)."""
        require_scope(SCOPE_READ)
        return await rt.client.watchlist(current_tenant(), opportunity_type, page, per_page)

    @mcp.tool(title="My certificates", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_certificates(page: PageNo = 1, per_page: PerPage = 12) -> CertificatePage:
        """Certificates the signed-in user earned (winner / participation / merit), with event, organiser,
        achievement and a link to view the certificate."""
        require_scope(SCOPE_READ)
        return await rt.client.certificates(current_tenant(), page, per_page)

    @mcp.tool(title="My notifications", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_notifications(
        page: PageNo = 1,
        unread_only: Annotated[bool, Field(description="Only unread notifications")] = False,
    ) -> NotificationPage:
        """The user's Unstop notifications, newest first: results, registration confirmations/cancellations,
        team activity and rewards, each with a link."""
        require_scope(SCOPE_READ)
        return await rt.client.notifications(current_tenant(), page, unread_only)

    @mcp.tool(title="My courses", annotations=READ_ONLY_PRIVATE)
    @guard
    async def my_courses(page: PageNo = 1) -> list[Course]:
        """Courses the user is enrolled in on Unstop, with progress, completion and certificate links."""
        require_scope(SCOPE_READ)
        return await rt.client.courses(current_tenant(), page)

    @mcp.tool(title="Save deadlines to a calendar file", annotations=LOCAL_WRITE)
    @guard
    async def save_deadlines_calendar(
        days: Annotated[int, Field(ge=1, le=180, description="How far ahead to include")] = 60,
        file_name: Annotated[str, Field(pattern=r"^[\w .-]{1,80}\.ics$",
                                        description="File name ending in .ics")] = "unstop-deadlines.ics",
    ) -> dict[str, Any]:
        """Save the user's upcoming deadlines as an .ics calendar file in their Downloads folder (with 24-hour
        reminders), ready to import into Google Calendar, Outlook or Apple Calendar. Local use only."""
        require_scope(SCOPE_READ)
        if not ctx.local:
            return {"saved": False, "message": "Saving files only works when Unstop MCP runs on your own computer. "
                    "Read the unstop://me/deadlines.ics resource instead."}
        deadlines = await rt.client.deadlines(current_tenant(), days)
        folder = downloads_dir()
        target = (folder / file_name).resolve()
        if target.parent != folder.resolve():  # pattern already forbids separators; belt and braces
            raise PermissionDenied("The calendar file must be saved directly in your Downloads folder.")
        await asyncio.to_thread(target.write_bytes, deadlines_to_ics(deadlines).encode("utf-8"))
        audit("save_deadlines_calendar", file=str(target), events=deadlines.total)
        return {"saved": True, "path": str(target), "events": deadlines.total,
                "message": f"Saved {deadlines.total} deadline(s) to {target}. Open the file to add them to your calendar."
                if deadlines.total else f"Saved an empty calendar to {target}: nothing is due in the next {days} days."}

    if ctx.writes:

        @mcp.tool(title="Add to watchlist", annotations=WRITE)
        @guard
        async def add_to_watchlist(opportunity: OppRef) -> dict[str, Any]:
            """Save an opportunity to the signed-in user's Unstop watchlist (reversible)."""
            require_scope(SCOPE_WRITE)
            result = await rt.client.set_watchlist(current_tenant(), opportunity, add=True)
            audit("add_to_watchlist", opportunity_id=result["opportunity_id"], ok=result["ok"])
            return result

        @mcp.tool(title="Remove from watchlist", annotations=WRITE)
        @guard
        async def remove_from_watchlist(opportunity: OppRef) -> dict[str, Any]:
            """Remove an opportunity from the signed-in user's Unstop watchlist."""
            require_scope(SCOPE_WRITE)
            result = await rt.client.set_watchlist(current_tenant(), opportunity, add=False)
            audit("remove_from_watchlist", opportunity_id=result["opportunity_id"], ok=result["ok"])
            return result

        @mcp.tool(title="Mark notifications read", annotations=WRITE)
        @guard
        async def mark_notifications_read() -> dict[str, Any]:
            """Mark all of the user's Unstop notifications as read."""
            require_scope(SCOPE_WRITE)
            result = await rt.client.mark_notifications_read(current_tenant())
            audit("mark_notifications_read", ok=result["ok"])
            return result

    @mcp.resource("unstop://me/deadlines.ics", name="deadlines-calendar", mime_type="text/calendar")
    async def deadlines_calendar() -> str:
        """The next 60 days of the user's Unstop deadlines as an iCalendar file (import into any calendar)."""
        try:
            return deadlines_to_ics(await rt.client.deadlines(current_tenant(), 60))
        except UnstopError as exc:
            raise ToolError(exc.message) from exc

    @mcp.prompt(name="deadline_digest", title="What's due soon")
    def deadline_digest(days: str = "14") -> str:
        """Summarise what the user needs to do in the coming days."""
        return (
            f"Call my_deadlines with days={days}. Group the items by day, say exactly what I need to do for each, "
            "flag anything due within 72 hours at the top, and include every URL. If nothing is due, say so and "
            "suggest recommended_for_me."
        )

    @mcp.prompt(name="weekly_plan", title="Plan my week on Unstop")
    def weekly_plan(interests: str = "") -> str:
        """A one-week plan combining deadlines and new opportunities."""
        return (
            "Build my Unstop plan for the next 7 days. 1) my_deadlines(days=7) for commitments. 2) recommended_for_me "
            + (f"and search_opportunities for: {interests}. " if interests else "for new options. ")
            + "3) Propose at most 3 new things to register for that fit around the deadlines. Output a day-by-day "
            "table with links."
        )
