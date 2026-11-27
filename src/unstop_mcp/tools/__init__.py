"""MCP toolsets. Each module registers its own tools/resources/prompts and contributes lines to the AI's
instructions, so a deployment can load only what it needs (``UNSTOP_MCP_TOOLSETS=discover,account``)."""

from __future__ import annotations

from collections.abc import Callable
from types import ModuleType

from unstop_mcp.tools import account, alerts, discover, registration, system, teams
from unstop_mcp.tools._common import ToolContext

#: name -> module, in registration order. "system" is always loaded.
TOOLSETS: dict[str, ModuleType] = {
    "discover": discover,
    "account": account,
    "alerts": alerts,
    "registration": registration,
    "teams": teams,
}
ALWAYS: tuple[ModuleType, ...] = (system,)

BASE_INSTRUCTIONS = """\
Unstop (unstop.com) is India's largest platform for student and early-career opportunities: hackathons,
competitions, quizzes, jobs, internships and scholarships.

Which tool to use:
{lines}
- When a tool says "Can't do this automatically", tell the user plainly that this step is theirs to do on unstop.com
  and give them the link. Don't retry or work around it.

Rules:
- If a tool says "Not logged in", call sign_in (it opens a secure page in the user's browser). Never ask the
  user to type their one-time code into the chat.
- Always include the opportunity URL.
- Dates are ISO-8601 in IST (+05:30). Prize amounts are in prize_currency (usually INR).
"""


def selected(names: list[str]) -> list[ModuleType]:
    return [TOOLSETS[n] for n in names]


def instructions_for(names: list[str]) -> str:
    lines = [m.INSTRUCTIONS for m in selected(names) if getattr(m, "INSTRUCTIONS", "")]
    return BASE_INSTRUCTIONS.format(lines="\n".join(lines))


def register_toolsets(ctx: ToolContext, names: list[str]) -> None:
    register: Callable[[ToolContext], None]
    for module in (*selected(names), *ALWAYS):
        register = module.register
        register(ctx)


__all__ = ["ALWAYS", "TOOLSETS", "ToolContext", "instructions_for", "register_toolsets"]
