"""Toolsets: configuration, selective registration, composed instructions, and module independence."""

import subprocess
import sys

import pytest

from unstop_mcp.config import TOOLSET_NAMES, Settings
from unstop_mcp.server import build_server
from unstop_mcp.tools import TOOLSETS

SYSTEM = {"auth_status", "sign_in", "sign_out", "server_status"}


def _settings(tmp_path, **kw):
    return Settings(data_dir=tmp_path, _env_file=None, **kw)


def test_toolset_names_match_modules():
    assert tuple(TOOLSETS) == TOOLSET_NAMES


@pytest.mark.parametrize("value,expected", [
    ("all", list(TOOLSET_NAMES)),
    ("discover", ["discover"]),
    ("Account, discover", ["discover", "account"]),  # canonical order, case-insensitive
    (["teams", "alerts"], ["alerts", "teams"]),
    ("", list(TOOLSET_NAMES)),
])
def test_active_toolsets(tmp_path, value, expected):
    assert _settings(tmp_path, toolsets=value).active_toolsets == expected


def test_unknown_toolset_is_a_clear_error(tmp_path):
    with pytest.raises(ValueError, match="Unknown toolset"):
        _settings(tmp_path, toolsets="discover,magic")


def test_toolsets_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSTOP_MCP_TOOLSETS", "discover,alerts")
    assert Settings(data_dir=tmp_path, _env_file=None).active_toolsets == ["discover", "alerts"]


async def test_only_selected_tools_are_registered(tmp_path):
    mcp = build_server(_settings(tmp_path, toolsets="discover"))
    names = {t.name for t in await mcp.list_tools()}
    assert names == {"search_opportunities", "get_opportunity", "compare_opportunities", "closing_soon",
                     "get_organisation", "unstop_leaderboard"} | SYSTEM


@pytest.mark.parametrize("toolset", TOOLSET_NAMES)
async def test_each_toolset_registers_alone(tmp_path, toolset):
    """Every toolset can be loaded on its own: no hidden dependency on another toolset's registration."""
    mcp = build_server(_settings(tmp_path, toolsets=toolset))
    names = {t.name for t in await mcp.list_tools()}
    assert SYSTEM < names


async def test_instructions_follow_toolsets(tmp_path):
    small = build_server(_settings(tmp_path, toolsets="discover"))
    full = build_server(_settings(tmp_path))
    small_text = small._lowlevel_server.instructions or ""
    full_text = full._lowlevel_server.instructions or ""
    assert "search_opportunities" in small_text and "register_for_opportunity" not in small_text
    assert "register_for_opportunity" in full_text and "invite_teammate" in full_text


async def test_write_tools_off_removes_every_write(tmp_path):
    mcp = build_server(_settings(tmp_path, enable_write_tools=False))
    tools = await mcp.list_tools()
    writes = {t.name for t in tools if t.annotations and t.annotations.read_only_hint is False}
    # only local, owner-only actions remain (sign in/out, saving files/searches on this machine)
    assert writes <= {"sign_in", "sign_out", "save_deadlines_calendar", "save_search", "delete_saved_search"}


def test_terminal_commands_never_import_the_mcp_sdk():
    """CLI paths (search, deadlines, login...) must stay fast: building a runtime must not load the MCP SDK."""
    code = ("import sys; from unstop_mcp import cli; from unstop_mcp.runtime import build_runtime; "
            "import unstop_mcp.client; print('mcp' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,  # noqa: S603 (fixed args)
                         timeout=60, check=True)
    assert out.stdout.strip() == "False"
