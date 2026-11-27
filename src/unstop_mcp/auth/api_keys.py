"""Bearer API keys for MCP clients connecting over HTTP.

Keys look like ``usk_<43 url-safe chars>`` (256 bits). Only a SHA-256 hash is stored; the plaintext is shown
once at creation. The file is re-read when it changes on disk, so keys issued or revoked with the CLI take effect
without restarting the server.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from unstop_mcp.auth.session import validate_tenant
from unstop_mcp.auth.store import atomic_write

if TYPE_CHECKING:
    from mcp.server.auth.provider import AccessToken

KEY_PREFIX = "usk_"
SCOPE_READ = "unstop:read"
SCOPE_WRITE = "unstop:write"
ALL_SCOPES = (SCOPE_READ, SCOPE_WRITE)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class ApiKeyRecord(BaseModel):
    id: str
    tenant: str
    label: str = ""
    key_hash: str
    hint: str  # first chars, to recognise a key in listings
    scopes: list[str] = Field(default_factory=lambda: [SCOPE_READ])
    created_at: float = Field(default_factory=time.time)
    expires_at: float | None = None
    revoked_at: float | None = None

    @property
    def active(self) -> bool:
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > time.time()


class ApiKeyStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._records: list[ApiKeyRecord] = []
        self._stamp: tuple[int, int] | None = None

    def _load(self) -> None:
        try:
            st = self.path.stat()
        except FileNotFoundError:
            self._records, self._stamp = [], None
            return
        stamp = (st.st_mtime_ns, st.st_size)
        if stamp == self._stamp:
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8") or "[]")
            records = [ApiKeyRecord.model_validate(r) for r in raw]
        except (OSError, ValueError) as exc:
            # Keep serving the last good key set rather than locking everyone out.
            logging.getLogger(__name__).error("Could not read %s (%s); keeping previous keys", self.path, exc)
            return
        self._records, self._stamp = records, stamp

    def _save(self) -> None:
        data = json.dumps([r.model_dump() for r in self._records], indent=2).encode()
        atomic_write(self.path, data)
        self._stamp = None  # force reload on next read

    def create(
        self, tenant: str, scopes: list[str] | None = None, label: str = "", ttl_days: int | None = None
    ) -> tuple[str, ApiKeyRecord]:
        validate_tenant(tenant)
        scopes = scopes or [SCOPE_READ]
        bad = [s for s in scopes if s not in ALL_SCOPES]
        if bad:
            raise ValueError(f"Unknown scope(s): {bad}. Valid: {list(ALL_SCOPES)}")
        self._load()
        key = KEY_PREFIX + secrets.token_urlsafe(32)
        record = ApiKeyRecord(
            id=secrets.token_hex(4),
            tenant=tenant,
            label=label,
            key_hash=hash_key(key),
            hint=key[:8] + "…",
            scopes=sorted(set(scopes)),
            expires_at=time.time() + ttl_days * 86400 if ttl_days else None,
        )
        self._records.append(record)
        self._save()
        return key, record

    def list(self) -> list[ApiKeyRecord]:
        self._load()
        return list(self._records)

    def revoke(self, key_id: str) -> bool:
        self._load()
        for rec in self._records:
            if rec.id == key_id and rec.revoked_at is None:
                rec.revoked_at = time.time()
                self._save()
                return True
        return False

    def lookup(self, key: str) -> ApiKeyRecord | None:
        if not key.startswith(KEY_PREFIX) or len(key) > 128:
            return None
        self._load()
        digest = hash_key(key)
        match = None
        for rec in self._records:  # constant-time compare against every record
            if hmac.compare_digest(rec.key_hash, digest):
                match = rec
        return match if match and match.active else None


class ApiKeyVerifier:
    """``mcp`` TokenVerifier: maps a bearer API key to an AccessToken whose client_id is the tenant."""

    def __init__(self, store: ApiKeyStore, resource: str | None = None) -> None:
        self.store = store
        self.resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        from mcp.server.auth.provider import AccessToken  # the SDK is only needed in HTTP mode

        rec = self.store.lookup(token)
        if rec is None:
            return None
        return AccessToken(
            token=token,
            client_id=rec.tenant,
            subject=rec.tenant,
            scopes=list(rec.scopes),
            expires_at=int(rec.expires_at) if rec.expires_at else None,
            resource=self.resource,
            claims={"key_id": rec.id},
        )
