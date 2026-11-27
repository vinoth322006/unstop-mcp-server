"""Shared pieces for every toolset: context, guard (rate limit + error mapping + logging), scopes, audit, and the
annotated argument types the tools use."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any, Literal, ParamSpec, TypeVar

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from unstop_mcp.auth.session import DEFAULT_TENANT
from unstop_mcp.config import Settings
from unstop_mcp.errors import PermissionDenied, RateLimited, UnstopError
from unstop_mcp.http import TokenBucket

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from unstop_mcp.runtime import Runtime

log = logging.getLogger("unstop_mcp")
audit_log = logging.getLogger("unstop_mcp.audit")

P = ParamSpec("P")
R = TypeVar("R")


def current_tenant() -> str:
    """HTTP: the tenant bound to the caller's API key. stdio: the local owner ('default')."""
    token = get_access_token()
    return token.client_id if token else DEFAULT_TENANT


def require_scope(scope: str) -> None:
    token = get_access_token()
    if token is not None and scope not in token.scopes:
        raise PermissionDenied(f"This API key lacks the '{scope}' scope. Ask the server owner for a key with it.")


def audit(action: str, **fields: Any) -> None:
    token = get_access_token()
    key_id = (token.claims or {}).get("key_id") if token else "local"
    audit_log.info("%s %s", action, json.dumps(fields, default=str),
                   extra={"tenant": current_tenant(), "tool": action, "path": f"key:{key_id}"})


class ToolGuard:
    """Wraps every tool: per-tenant rate limit, clean error messages, structured call logging.

    The per-tenant limit protects a shared remote (HTTP) server from one noisy client. It is off for a local stdio
    server (one owner; the upstream limiter already keeps traffic to Unstop polite). Bursts wait up to ``max_wait``
    seconds for capacity before being refused, so a parallel-calling AI is smoothed rather than rejected."""

    def __init__(self, per_minute: int, enabled: bool = True, max_wait: float = 2.0) -> None:
        self.per_minute = per_minute
        self.enabled = enabled
        self.max_wait = max_wait
        self._buckets: dict[str, TokenBucket] = {}
        self.calls = 0

    async def _admit(self, tenant: str) -> None:
        if not self.enabled:
            return
        bucket = self._buckets.get(tenant)
        if bucket is None:
            bucket = self._buckets[tenant] = TokenBucket(self.per_minute / 60.0, max(5, self.per_minute // 4))
        if bucket.try_acquire():
            return
        if self.max_wait > 0:
            try:
                await asyncio.wait_for(bucket.acquire(), timeout=self.max_wait)
                return
            except TimeoutError:
                pass
        raise RateLimited(f"Too many requests ({self.per_minute}/minute). Slow down and try again shortly.")

    def __call__(self, func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            started = time.monotonic()
            tenant = current_tenant()
            outcome = "ok"
            self.calls += 1
            try:
                await self._admit(tenant)
                return await func(*args, **kwargs)
            except UnstopError as exc:
                outcome = type(exc).__name__
                raise ToolError(exc.message) from exc
            except ToolError:
                outcome = "tool_error"
                raise
            except Exception as exc:
                outcome = "crash"
                log.exception("Unhandled error in %s", func.__name__, extra={"tenant": tenant, "tool": func.__name__})
                raise ToolError("Internal error while talking to Unstop. The server log has details.") from exc
            finally:
                log.info("tool %s -> %s", func.__name__, outcome,
                         extra={"tenant": tenant, "tool": func.__name__,
                                "duration_ms": round((time.monotonic() - started) * 1000)})

        return wrapper


@dataclass
class ToolContext:
    """What a toolset needs to register its tools."""

    mcp: MCPServer
    rt: Runtime
    settings: Settings
    guard: ToolGuard

    @property
    def writes(self) -> bool:
        return self.settings.enable_write_tools

    @property
    def local(self) -> bool:
        return self.settings.transport == "stdio"


# ---------------------------------------------------------------- annotations and argument types

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)
READ_ONLY_PRIVATE = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE_OPEN = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True)
DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=True)
LOCAL_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                              open_world_hint=False)
LOCAL_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True,
                                    open_world_hint=False)

OppType = Literal["all", "hackathons", "competitions", "jobs", "internships", "quizzes", "scholarships",
                  "workshops", "conferences", "cultural"]
RegType = Literal["all", "competitions", "hackathons", "quizzes", "scholarships", "internships", "jobs",
                  "workshops", "conferences", "cultural"]
OppRef = Annotated[str, Field(min_length=1, max_length=300,
                              description="Opportunity id (e.g. '1817824') or its unstop.com URL")]
PageNo = Annotated[int, Field(ge=1, le=500, description="1-based page number")]
PerPage = Annotated[int, Field(ge=1, le=30, description="Results per page (max 30)")]
TeamName = Annotated[str | None, Field(max_length=60, description="Optional team name (team events only)")]
Email = Annotated[str | None, Field(max_length=320, description="Invitee's email address")]
InviteId = Annotated[int, Field(gt=0, description="Id from team_invitations")]
