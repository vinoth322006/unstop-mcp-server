"""Toolset "system" (always on): sign-in status, sign in/out, server health and the HTTP health route."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from unstop_mcp import __version__
from unstop_mcp.errors import AuthRequired, UnstopError
from unstop_mcp.tools._common import (
    LOCAL_DESTRUCTIVE,
    LOCAL_WRITE,
    READ_ONLY_PRIVATE,
    ToolContext,
    audit,
    current_tenant,
)

INSTRUCTIONS = ""


def register(ctx: ToolContext) -> None:
    mcp, guard, rt, settings = ctx.mcp, ctx.guard, ctx.rt, ctx.settings

    @mcp.tool(title="Unstop login status", annotations=READ_ONLY_PRIVATE)
    @guard
    async def auth_status() -> dict[str, Any]:
        """Whether this connection is linked to a signed-in Unstop account, and when the session expires.
        Never returns tokens."""
        tenant = current_tenant()
        try:
            session = await rt.auth.get_session(tenant)
        except AuthRequired as exc:
            return {"logged_in": False, "tenant": tenant, "how_to_fix": exc.message}
        token = get_access_token()
        return {"logged_in": True, "tenant": tenant, "scopes": token.scopes if token else ["local-owner"],
                **session.public_view()}

    @mcp.tool(title="Sign in to Unstop", annotations=LOCAL_WRITE)
    @guard
    async def sign_in(
        switch_account: Annotated[bool, Field(description="Sign in again even if already signed in")] = False,
    ) -> dict[str, Any]:
        """Open a secure sign-in page in the user's browser. The user types their email and the one-time code
        Unstop sends them on that page, never in the chat. Call auth_status afterwards to confirm."""
        from unstop_mcp.weblogin import BrowserLogin  # loaded only when someone actually signs in

        tenant = current_tenant()
        if not ctx.local:
            return {"signed_in": False, "message": "This server runs remotely. Its owner links your account with "
                    f"`unstop-mcp login --tenant {tenant}`."}
        if not switch_account:
            try:
                session = await rt.auth.get_session(tenant)
                return {"signed_in": True, "message": f"Already signed in as {session.name or session.email}."}
            except UnstopError:
                pass
        existing = rt.logins.get(tenant)
        if existing and existing.active:
            return {"signed_in": False, "url": existing.url, "message": "A sign-in page is already open. "
                    "Finish there (or open the link), then ask me to check your Unstop status."}
        login = BrowserLogin(rt.auth, tenant, asyncio.get_running_loop())
        url = login.start(open_browser=True)
        rt.logins[tenant] = login
        audit("sign_in_started")
        return {"signed_in": False, "url": url, "expires_in_minutes": 10,
                "message": "I opened an Unstop sign-in page in your browser (link above if it didn't open). Enter "
                           "your email, then the code Unstop sends you. Tell me when you're done."}

    @mcp.tool(title="Sign out of Unstop", annotations=LOCAL_DESTRUCTIVE)
    @guard
    async def sign_out() -> dict[str, Any]:
        """Sign out of Unstop on this computer: revokes the session and deletes the stored login."""
        if not ctx.local:
            return {"signed_out": False, "message": "This server runs remotely; ask its owner to run "
                    f"`unstop-mcp logout --tenant {current_tenant()}`."}
        removed = await rt.auth.logout(current_tenant())
        audit("sign_out", removed=removed)
        return {"signed_out": removed, "message": "Signed out." if removed else "You were not signed in."}

    @mcp.tool(title="Server status", annotations=READ_ONLY_PRIVATE)
    @guard
    async def server_status() -> dict[str, Any]:
        """Health of this server: version, uptime, enabled toolsets, Unstop connectivity and cache statistics."""
        return {
            "version": __version__,
            "uptime_seconds": int(time.time() - rt.started_at),
            "toolsets": settings.active_toolsets,
            "unstop_connection": rt.http.breaker.state,
            "http": dict(rt.http.stats),
            "cached_entries": len(rt.http.cache),
            "tool_calls": guard.calls,
            "write_tools_enabled": settings.enable_write_tools,
        }

    @mcp.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_: Request) -> JSONResponse:
        state = rt.http.breaker.state
        return JSONResponse({"status": "ok" if state == "closed" else "degraded", "version": __version__,
                             "unstop": state}, status_code=200)
