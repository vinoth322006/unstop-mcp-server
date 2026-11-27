"""Encrypted, per-tenant session storage on disk (Fernet / AES-128-CBC + HMAC-SHA256)."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from unstop_mcp.auth.session import UnstopSession, validate_tenant
from unstop_mcp.errors import AuthRequired


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:  # pragma: no cover
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class SessionStore:
    def __init__(self, directory: Path, fernet: Fernet) -> None:
        self.directory = directory
        self._fernet = fernet
        # tenant -> ((mtime_ns, size), session). Avoids a disk read + decrypt on every tool call while still
        # picking up logins done by another process (e.g. the CLI) because the file stat changes.
        self._cache: dict[str, tuple[tuple[int, int], UnstopSession]] = {}

    def _path(self, tenant: str) -> Path:
        return self.directory / f"{validate_tenant(tenant)}.session"

    def get(self, tenant: str) -> UnstopSession | None:
        path = self._path(tenant)
        try:
            st = path.stat()
        except FileNotFoundError:
            self._cache.pop(tenant, None)
            return None
        stamp = (st.st_mtime_ns, st.st_size)
        hit = self._cache.get(tenant)
        if hit and hit[0] == stamp:
            return hit[1].model_copy()
        try:
            raw = self._fernet.decrypt(path.read_bytes())
        except InvalidToken as exc:
            raise AuthRequired(
                f"Stored session for '{tenant}' cannot be decrypted (secret key changed?). Log in again."
            ) from exc
        session = UnstopSession.model_validate_json(raw)
        self._cache[tenant] = (stamp, session)
        return session.model_copy()

    def put(self, tenant: str, session: UnstopSession) -> None:
        atomic_write(self._path(tenant), self._fernet.encrypt(session.model_dump_json().encode()))
        self._cache.pop(tenant, None)

    def delete(self, tenant: str) -> bool:
        path = self._path(tenant)
        self._cache.pop(tenant, None)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_tenants(self) -> list[str]:
        if not self.directory.exists():
            return []
        return sorted(p.stem for p in self.directory.glob("*.session"))
