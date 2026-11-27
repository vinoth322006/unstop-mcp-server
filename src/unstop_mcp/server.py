"""Builds the MCP server: auth wiring plus the selected toolsets (see ``unstop_mcp.tools``)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl

from unstop_mcp import __version__
from unstop_mcp.auth.api_keys import SCOPE_READ, ApiKeyVerifier
from unstop_mcp.config import TOOLSET_NAMES, Settings
from unstop_mcp.runtime import Runtime, build_runtime
from unstop_mcp.tools import TOOLSETS, ToolContext, instructions_for, register_toolsets
from unstop_mcp.tools._common import OppType, RegType, ToolGuard, current_tenant, require_scope

log = logging.getLogger("unstop_mcp")

assert tuple(TOOLSETS) == TOOLSET_NAMES, "config.TOOLSET_NAMES and tools.TOOLSETS must list the same toolsets"


def build_server(settings: Settings, runtime: Runtime | None = None) -> MCPServer:
    rt = runtime or build_runtime(settings)
    toolsets = settings.active_toolsets

    auth_settings = None
    verifier = None
    if settings.transport == "http":
        public = settings.resolved_public_url
        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl(public),
            resource_server_url=AnyHttpUrl(public + settings.path),
            required_scopes=[SCOPE_READ],
            validate_token_resource=False,
        )
        verifier = ApiKeyVerifier(rt.api_keys, resource=public + settings.path)

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[Runtime]:
        try:
            yield rt
        finally:
            await rt.http.aclose()

    mcp = MCPServer(
        name="unstop",
        title="Unstop",
        description="Search Unstop opportunities, track your registrations and deadlines, register and manage teams.",
        instructions=instructions_for(toolsets),
        website_url="https://unstop.com",
        version=__version__,
        token_verifier=verifier,
        auth=auth_settings,
        lifespan=lifespan,
        log_level=settings.log_level,
    )
    guard = ToolGuard(settings.client_rate_limit_per_minute, enabled=settings.transport == "http")
    register_toolsets(ToolContext(mcp=mcp, rt=rt, settings=settings, guard=guard), toolsets)
    return mcp


# Re-exported for callers and tests.
__all__ = ["OppType", "RegType", "Runtime", "ToolGuard", "build_runtime", "build_server", "current_tenant",
           "log", "require_scope"]
