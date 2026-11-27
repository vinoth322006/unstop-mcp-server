"""AI-app config merging and CLI behaviour."""

import json

import pytest

from unstop_mcp import cli, clients


def test_install_merges_and_backs_up(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    assert clients.install_json(cfg, "exe", ["serve"]).startswith("added (backup:")
    data = json.loads(cfg.read_text())
    assert data["mcpServers"]["other"] == {"command": "x"} and data["theme"] == "dark"
    assert data["mcpServers"]["unstop"] == {"command": "exe", "args": ["serve"]}
    assert len(list(tmp_path.glob("*.bak-*"))) == 1
    assert clients.install_json(cfg, "exe", ["serve"]) == "already set up"
    assert len(list(tmp_path.glob("*.bak-*"))) == 1  # no backup when nothing changes


def test_install_creates_missing_file(tmp_path):
    cfg = tmp_path / "new" / "mcp.json"
    assert clients.install_json(cfg, "exe", ["serve"]) == "added"
    assert json.loads(cfg.read_text())["mcpServers"]["unstop"]["command"] == "exe"


def test_install_refuses_invalid_json(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text("{ not json")
    with pytest.raises(ValueError, match="untouched"):
        clients.install_json(cfg, "exe", ["serve"])
    assert cfg.read_text() == "{ not json"


def test_uninstall_keeps_other_servers(tmp_path):
    cfg = tmp_path / "mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {"unstop": {}, "other": {}}}))
    assert clients.uninstall_json(cfg).startswith("removed")
    assert json.loads(cfg.read_text()) == {"mcpServers": {"other": {}}}
    assert clients.uninstall_json(cfg) == "not installed"


def test_detect_clients_uses_overridden_home(tmp_path, monkeypatch):
    (tmp_path / ".cursor").mkdir()
    monkeypatch.setenv("UNSTOP_MCP_CLIENT_HOME", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    found = {c.key: c for c in clients.detect_clients()}
    assert found["cursor"].detected and found["cursor"].config_path == tmp_path / ".cursor" / "mcp.json"


def test_server_command_points_at_this_install():
    command, args = clients.server_command()
    assert args[-1] == "serve"
    assert "unstop" in command.lower() or "python" in command.lower()


def test_bare_command_in_terminal_shows_welcome(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "unstop-mcp setup" in out and "search" in out


def test_help_lists_friendly_commands(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for command in ("setup", "search", "deadlines", "connect", "doctor"):
        assert command in out


def test_connect_command_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("UNSTOP_MCP_CLIENT_HOME", str(tmp_path))
    (tmp_path / ".cursor").mkdir()
    assert cli.main(["connect", "cursor"]) == 0
    assert "unstop" in json.loads((tmp_path / ".cursor" / "mcp.json").read_text())["mcpServers"]
    assert cli.main(["connect", "cursor", "--remove"]) == 0
    assert "unstop" not in json.loads((tmp_path / ".cursor" / "mcp.json").read_text())["mcpServers"]


def test_claude_desktop_store_location_preferred(tmp_path, monkeypatch):
    """Store builds keep data in LOCALAPPDATA/Claude-Data and leave a marker in APPDATA/Claude."""
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Windows")
    roaming, local = tmp_path / "Roaming", tmp_path / "Local"
    (roaming / "Claude").mkdir(parents=True)
    (roaming / "Claude" / ".user-data-left.anthropicpbc.claude_x").write_text("")
    store = local / "Claude-Data" / "anthropicpbc.claude_x"
    store.mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    assert clients._claude_desktop_path() == store / "claude_desktop_config.json"
    (roaming / "Claude" / "claude_desktop_config.json").write_text("{}")  # an existing config always wins
    assert clients._claude_desktop_path() == roaming / "Claude" / "claude_desktop_config.json"


def test_double_clicked_exe_runs_setup_and_waits(monkeypatch):
    calls = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr(cli, "_setup", lambda args: calls.append(("setup", args.cmd)) or _done())
    monkeypatch.setattr("builtins.input", lambda prompt="": calls.append(("input", prompt)) or "")
    assert cli.main([]) == 0
    assert calls[0] == ("setup", "setup") and calls[1][0] == "input"


async def _noop():
    return 0


def _done():
    return _noop()


def test_connect_with_toolsets_writes_env(tmp_path, monkeypatch):
    monkeypatch.setenv("UNSTOP_MCP_CLIENT_HOME", str(tmp_path))
    (tmp_path / ".cursor").mkdir()
    assert cli.main(["connect", "cursor", "--toolsets", "Account,discover"]) == 0
    entry = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())["mcpServers"]["unstop"]
    assert entry["env"] == {"UNSTOP_MCP_TOOLSETS": "discover,account"}  # validated + canonical order
    assert cli.main(["connect", "cursor", "--toolsets", "all"]) == 0
    entry = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())["mcpServers"]["unstop"]
    assert "env" not in entry  # "all" is the default: keep the config clean


def test_connect_rejects_unknown_toolset_before_changing_anything(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("UNSTOP_MCP_CLIENT_HOME", str(tmp_path))
    (tmp_path / ".cursor").mkdir()
    assert cli.main(["connect", "cursor", "--toolsets", "discover,magic"]) != 0
    assert not (tmp_path / ".cursor" / "mcp.json").exists()
    out = capsys.readouterr().out
    assert "Unknown toolset(s) ['magic']" in out
    assert "pydantic" not in out and "Restart the app" not in out  # one clear sentence, no false "done"


def test_claude_code_gets_env_flags(monkeypatch):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(clients, "_run_claude_cli", lambda *a: calls.append(a) or Done())
    app = clients.ClientApp("claude-code", "Claude Code", None, True)
    clients.install(app, ["discover"])
    add = calls[-1]
    assert add[:5] == ("mcp", "add", "--scope", "user", "-e") and add[5] == "UNSTOP_MCP_TOOLSETS=discover"
    assert add[6] == "unstop" and add[7] == "--"


def test_prizes_show_their_own_currency():
    from unstop_mcp.cli._ui import _money

    assert _money(80000, "USD") == "$80,000"  # a US-dollar prize must not be printed as rupees
    assert _money(1500000, "INR") == "₹1,500,000"
    assert _money(5000, None) == "₹5,000"
    assert _money(2500, "aed") == "AED 2,500"


def test_release_notes_come_from_the_changelog():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "packaging" / "release_notes.py"
    spec = importlib.util.spec_from_file_location("release_notes", path)
    assert spec and spec.loader
    rn = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rn)
    log = "# Changelog\n\n## 2.0.0 — 2027-01-01 (big)\n\n- New thing\n\n## 1.9.0 — 2026-12-01\n\n- Old thing\n"
    out = rn.notes("v2.0.0", log)
    assert out.startswith("- New thing") and "Old thing" not in out
    assert "unstop-mcp-2.0.0.mcpb" in out and "ghcr.io/vinoth322006/unstop-mcp:v2.0.0" in out
    assert "See [CHANGELOG.md]" in rn.notes("v3.0.0", log)  # unknown version still gets a useful body
