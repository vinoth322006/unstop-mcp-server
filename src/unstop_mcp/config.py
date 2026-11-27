"""Runtime configuration, read from environment variables (prefix ``UNSTOP_MCP_``) or a ``.env`` file."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: Optional groups of MCP tools ("system" is always on). Kept here, not imported from tools/, so reading the
#: config never pulls in the MCP SDK.
TOOLSET_NAMES = ("discover", "account", "alerts", "registration", "teams")


def _default_data_dir() -> Path:
    return Path.home() / ".unstop-mcp"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="UNSTOP_MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Transport -------------------------------------------------------
    transport: Literal["stdio", "http"] = "stdio"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    path: str = "/mcp"
    public_url: str | None = Field(
        default=None,
        description="Externally reachable base URL (e.g. https://mcp.example.com). Required for http behind a proxy.",
    )
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Comma-separated Host header allow-list (DNS-rebinding protection). Defaults from host/public_url.",
    )
    allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Storage & secrets -----------------------------------------------
    data_dir: Path = Field(default_factory=_default_data_dir)
    secret_key: SecretStr | None = Field(
        default=None,
        description="Encryption key for stored Unstop sessions. Any string; a Fernet key is used as-is.",
    )

    # --- Upstream (unstop.com) -------------------------------------------
    base_url: str = "https://unstop.com"
    timeout_seconds: float = Field(default=20.0, gt=0)
    max_retries: int = Field(default=3, ge=0, le=10)
    rate_limit_per_second: float = Field(default=4.0, gt=0, description="Upstream request budget (all tenants).")
    rate_limit_burst: int = Field(default=8, ge=1)
    cache_ttl_seconds: int = Field(default=300, ge=0, description="Freshness of public (anonymous) responses.")
    private_cache_ttl_seconds: int = Field(default=30, ge=0, description="Per-user cache for account reads.")
    stale_cache_seconds: int = Field(default=3600, ge=0, description="Serve stale public data this long if down.")
    cache_max_entries: int = Field(default=1024, ge=0)
    breaker_threshold: int = Field(default=5, ge=1, description="Consecutive upstream failures before pausing.")
    breaker_cooldown_seconds: float = Field(default=30.0, gt=0)
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0 Safari/537.36 unstop-mcp/1.4"
    )

    # Optional pasted token for single-user stdio setups (used when no stored session exists).
    access_token: SecretStr | None = None

    # --- Behaviour --------------------------------------------------------
    enable_write_tools: bool = True
    toolsets: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["all"],
        description="Comma-separated toolsets to load: all, or any of " + ", ".join(TOOLSET_NAMES) +
                    ". Loading fewer tools keeps the AI's context small and fast.",
    )
    client_rate_limit_per_minute: int = Field(
        default=120, ge=1, description="Tool calls per minute allowed per tenant (abuse protection)."
    )
    allow_generated_secret_in_http: bool = Field(
        default=False,
        description="HTTP mode refuses to start without UNSTOP_MCP_SECRET_KEY unless this is true.",
    )
    description_max_chars: int = Field(default=6000, ge=500)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = True

    @field_validator("toolsets", mode="before")
    @classmethod
    def _split_toolsets(cls, v: object) -> object:
        if isinstance(v, str):
            v = [p.strip().lower() for p in v.split(",") if p.strip()]
        if isinstance(v, list):
            unknown = [n for n in v if n not in ("all", *TOOLSET_NAMES)]
            if unknown:
                raise ValueError(f"Unknown toolset(s) {unknown}. Choose from: all, {', '.join(TOOLSET_NAMES)}")
            return v or ["all"]
        return v

    @property
    def active_toolsets(self) -> list[str]:
        """Enabled toolsets in canonical order ("system" is always on and not listed)."""
        if "all" in self.toolsets:
            return list(TOOLSET_NAMES)
        return [n for n in TOOLSET_NAMES if n in self.toolsets]

    @field_validator("allowed_hosts", "allowed_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v

    @field_validator("path")
    @classmethod
    def _path_slash(cls, v: str) -> str:
        return v if v.startswith("/") else "/" + v

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def api_keys_file(self) -> Path:
        return self.data_dir / "api_keys.json"

    @property
    def secret_key_file(self) -> Path:
        return self.data_dir / "secret.key"

    @property
    def resolved_public_url(self) -> str:
        if self.public_url:
            return self.public_url.rstrip("/")
        host = "localhost" if self.host in ("0.0.0.0", "::", "127.0.0.1") else self.host  # noqa: S104
        return f"http://{host}:{self.port}"

