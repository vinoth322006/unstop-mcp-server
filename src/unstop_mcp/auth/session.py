from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

from pydantic import BaseModel, Field

TENANT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,63}$")
DEFAULT_TENANT = "default"


def validate_tenant(tenant: str) -> str:
    if not TENANT_RE.fullmatch(tenant):
        raise ValueError("Tenant names must be 1-64 chars: letters, digits, '-' or '_' (starting alphanumeric).")
    return tenant


def jwt_expiry(token: str) -> float | None:
    """Read ``exp`` from a JWT without verifying it (we only need it to schedule refreshes)."""
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded))
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except (ValueError, TypeError):
        return None


class UnstopSession(BaseModel):
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None
    user_id: int | None = None
    email: str | None = None
    name: str | None = None
    created_at: float = Field(default_factory=time.time)
    refreshed_at: float | None = None

    def needs_refresh(self, skew: float = 120.0) -> bool:
        return self.expires_at is not None and time.time() >= self.expires_at - skew

    def public_view(self) -> dict[str, Any]:
        """Session info without secrets."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "name": self.name,
            "expires_at": self.expires_at,
            "expires_in_seconds": int(self.expires_at - time.time()) if self.expires_at else None,
            "can_refresh": bool(self.refresh_token),
            "logged_in_at": self.created_at,
        }

    @classmethod
    def from_token_response(cls, data: dict[str, Any], email: str | None = None) -> UnstopSession:
        access = data["access_token"]
        expires_at = jwt_expiry(access)
        if expires_at is None and isinstance(data.get("expires_in"), int | float):
            expires_at = time.time() + float(data["expires_in"])
        user_id = data.get("id") or data.get("user_id")
        return cls(
            access_token=access,
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            user_id=int(user_id) if isinstance(user_id, int | str) and str(user_id).isdigit() else None,
            email=data.get("email") or email,
            name=data.get("name"),
        )
