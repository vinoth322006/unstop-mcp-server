"""Wiring of the long-lived objects (HTTP client, session store, auth, client, API keys).

Kept free of the MCP SDK on purpose: terminal commands (search, deadlines, login...) build a Runtime without
paying the ~2 s import cost of the MCP server stack. Only ``unstop_mcp.server`` imports the SDK.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from unstop_mcp.auth.api_keys import ApiKeyStore
from unstop_mcp.auth.store import SessionStore
from unstop_mcp.auth.unstop_auth import UnstopAuth
from unstop_mcp.client import UnstopClient
from unstop_mcp.config import Settings
from unstop_mcp.crypto import build_fernet
from unstop_mcp.http import UnstopHTTP
from unstop_mcp.searches import SearchStore

if TYPE_CHECKING:
    from unstop_mcp.weblogin import BrowserLogin

log = logging.getLogger("unstop_mcp")


@dataclass
class Runtime:
    settings: Settings
    http: UnstopHTTP
    sessions: SessionStore
    auth: UnstopAuth
    client: UnstopClient
    api_keys: ApiKeyStore
    started_at: float = field(default_factory=time.time)
    logins: dict[str, BrowserLogin] = field(default_factory=dict)


def private_dir(path: Path) -> None:
    """Create a directory only the current user can read (POSIX 0700; NTFS inherits the user profile ACL)."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover
        pass


def build_runtime(settings: Settings) -> Runtime:
    if settings.transport == "http" and not settings.secret_key and not settings.allow_generated_secret_in_http:
        raise ValueError(
            "HTTP mode needs UNSTOP_MCP_SECRET_KEY so stored sessions aren't protected by a key sitting next to them. "
            "Generate one: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    private_dir(settings.data_dir)
    private_dir(settings.sessions_dir)
    fernet, generated = build_fernet(
        settings.secret_key.get_secret_value() if settings.secret_key else None, settings.secret_key_file
    )
    if generated:
        log.info("Created a new session-encryption key at %s. Keep it safe; losing it means logging in again.",
                 settings.secret_key_file)
    http = UnstopHTTP(settings)
    sessions = SessionStore(settings.sessions_dir, fernet)
    auth = UnstopAuth(http, sessions, settings.access_token.get_secret_value() if settings.access_token else None)
    return Runtime(
        settings=settings,
        http=http,
        sessions=sessions,
        auth=auth,
        client=UnstopClient(http, auth, settings.description_max_chars, SearchStore(settings.data_dir / "searches")),
        api_keys=ApiKeyStore(settings.api_keys_file),
    )


def downloads_dir() -> Path:
    """The user's real Downloads folder. Windows lets users move it to another drive, so ask the OS:
    the User Shell Folders registry key on Windows, XDG_DOWNLOAD_DIR on Linux, ~/Downloads elsewhere."""
    home = Path.home()
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                raw, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            path = Path(os.path.expandvars(str(raw)))
            if path.is_dir():
                return path
        except OSError:
            pass
    else:
        cfg = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "user-dirs.dirs"
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                if line.startswith("XDG_DOWNLOAD_DIR="):
                    path = Path(line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home)))
                    if path.is_dir():
                        return path
        except OSError:
            pass
    default = home / "Downloads"
    return default if default.is_dir() else home
