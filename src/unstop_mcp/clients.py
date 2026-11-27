"""Connect this server to MCP client apps (Claude Desktop, Claude Code, Cursor, Windsurf) automatically.

Config files are merged, never overwritten: the existing file is backed up first, other servers are kept, and an
unreadable (invalid JSON) file is left untouched with an explanation.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from unstop_mcp.auth.store import atomic_write

SERVER_NAME = "unstop"


def server_command() -> tuple[str, list[str]]:
    """The command an MCP client should launch. Prefers the console script next to the running Python."""
    if getattr(sys, "frozen", False):  # standalone build: the executable is the server itself
        return sys.executable, ["serve"]
    scripts = Path(sys.executable).parent
    for name in ("unstop-mcp.exe", "unstop-mcp"):
        candidate = scripts / name
        if candidate.exists():
            return str(candidate), ["serve"]
    found = shutil.which("unstop-mcp")
    if found:
        return found, ["serve"]
    return sys.executable, ["-m", "unstop_mcp", "serve"]


@dataclass
class ClientApp:
    key: str
    name: str
    config_path: Path | None  # None = configured through its own CLI
    detected: bool
    note: str = ""


def _home() -> Path:
    return Path(os.environ.get("UNSTOP_MCP_CLIENT_HOME") or Path.home())


def _claude_desktop_path() -> Path:
    system = platform.system()
    home = _home()
    if system == "Windows":
        appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        name = "claude_desktop_config.json"
        candidates = [
            # Microsoft Store build (current): data moved out of %APPDATA% into Claude-Data.
            *sorted((local / "Claude-Data").glob("anthropicpbc.claude_*")),
            # Older MSIX builds: virtualised %APPDATA% inside the package.
            *(p / "LocalCache" / "Roaming" / "Claude" for p in sorted((local / "Packages").glob("*Claude*"))),
            appdata / "Claude",  # classic installer
        ]
        for folder in candidates:  # an existing config wins
            if (folder / name).is_file():
                return folder / name
        for folder in candidates:  # else the first folder the app has created
            if folder.is_dir() and not any(folder.glob(".user-data-left*")):
                return folder / name
        return appdata / "Claude" / name
    if system == "Darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def detect_clients() -> list[ClientApp]:
    home = _home()
    desktop = _claude_desktop_path()
    cursor = home / ".cursor" / "mcp.json"
    windsurf = home / ".codeium" / "windsurf" / "mcp_config.json"
    claude_cli = shutil.which("claude")
    return [
        ClientApp("claude-desktop", "Claude Desktop", desktop, desktop.parent.exists()),
        ClientApp("claude-code", "Claude Code", None, claude_cli is not None,
                  "" if claude_cli else "the `claude` command was not found on PATH"),
        ClientApp("cursor", "Cursor", cursor, cursor.parent.exists()),
        ClientApp("windsurf", "Windsurf", windsurf, windsurf.parent.exists()),
    ]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.read_text(encoding="utf-8").strip():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object.")
    return data


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    return backup


def install_json(path: Path, command: str, args: list[str], env: dict[str, str] | None = None) -> str:
    try:
        data = _read_json(path)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"Left {path} untouched: it is not valid JSON ({exc}). Fix it and run setup again.") from exc
    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"Left {path} untouched: 'mcpServers' is not an object.")
    entry: dict[str, Any] = {"command": command, "args": args}
    if env:
        entry["env"] = env
    if servers.get(SERVER_NAME) == entry:
        return "already set up"
    backup = _backup(path)
    servers[SERVER_NAME] = entry
    atomic_write(path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
    return f"added (backup: {backup.name})" if backup else "added"


def uninstall_json(path: Path) -> str:
    try:
        data = _read_json(path)
    except (ValueError, json.JSONDecodeError):
        return "skipped (config is not valid JSON)"
    servers = data.get("mcpServers")
    if not isinstance(servers, dict) or SERVER_NAME not in servers:
        return "not installed"
    backup = _backup(path)
    del servers[SERVER_NAME]
    atomic_write(path, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
    return f"removed (backup: {backup.name if backup else '-'})"


def _run_claude_cli(*args: str) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("claude")
    if exe is None:
        raise ValueError("The `claude` command was not found on PATH.")
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=60, check=False)  # noqa: S603


def server_env(toolsets: list[str] | None = None) -> dict[str, str]:
    """Environment for the app's config entry. Empty means "all toolsets" (the default)."""
    if toolsets and "all" not in toolsets:
        return {"UNSTOP_MCP_TOOLSETS": ",".join(toolsets)}
    return {}


def install(client: ClientApp, toolsets: list[str] | None = None) -> str:
    command, args = server_command()
    env = server_env(toolsets)
    if client.key == "claude-code":
        _run_claude_cli("mcp", "remove", "--scope", "user", SERVER_NAME)  # idempotent re-install
        env_args = [a for k, v in env.items() for a in ("-e", f"{k}={v}")]
        res = _run_claude_cli("mcp", "add", "--scope", "user", *env_args, SERVER_NAME, "--", command, *args)
        if res.returncode != 0:
            raise ValueError((res.stderr or res.stdout).strip() or "claude mcp add failed")
        return "added (user scope)"
    assert client.config_path is not None
    return install_json(client.config_path, command, args, env or None)


def uninstall(client: ClientApp) -> str:
    if client.key == "claude-code":
        res = _run_claude_cli("mcp", "remove", "--scope", "user", SERVER_NAME)
        return "removed" if res.returncode == 0 else "not installed"
    assert client.config_path is not None
    return uninstall_json(client.config_path)
