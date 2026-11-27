"""Crypto helpers.

1. ``decrypt_enc_data`` -- some Unstop auth/profile responses wrap their payload as ``{"encData": "..."}``.
   The web app decrypts it client-side: base64(JSON{iv, value, mac}) -> AES-256-CBC with a key shipped in the
   public JS bundle -> a PHP-serialised string ``s:<len>:"<json>";``. We mirror that exactly.

2. ``build_fernet`` -- at-rest encryption for stored sessions.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from unstop_mcp.errors import UpstreamError

# Public constant from unstop.com's front-end bundle (base64 of a 32-char ASCII key -> AES-256).
_UNSTOP_ENC_KEY = base64.b64decode("NEpLU3BZQlFvWkJxdStCOUpIVFJhSWkwMlpmRHhmREM=")


def decrypt_enc_data(enc: str) -> Any:
    try:
        envelope = json.loads(base64.b64decode(enc))
        iv = base64.b64decode(envelope["iv"])
        ciphertext = base64.b64decode(envelope["value"])
        decryptor = Cipher(algorithms.AES(_UNSTOP_ENC_KEY), modes.CBC(iv)).decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        text = (unpadder.update(padded) + unpadder.finalize()).decode("utf-8")
        # PHP serialised string: s:123:"<payload>";
        start = text.index('"')
        return json.loads(text[start + 1 : -2])
    except Exception as exc:  # noqa: BLE001 - any failure means the upstream format changed
        raise UpstreamError("Could not decode an encrypted Unstop response (format may have changed).") from exc


def encrypt_enc_data(obj: Any, iv: bytes | None = None) -> str:
    """Inverse of :func:`decrypt_enc_data`; used by tests to build realistic fixtures."""
    payload = json.dumps(obj, separators=(",", ":"))
    serialised = f's:{len(payload.encode())}:"{payload}";'.encode()
    iv = iv or os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(serialised) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_UNSTOP_ENC_KEY), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    envelope = {"iv": base64.b64encode(iv).decode(), "value": base64.b64encode(ct).decode(), "mac": ""}
    return base64.b64encode(json.dumps(envelope).encode()).decode()


def maybe_decrypt(payload: Any) -> Any:
    """Transparently unwrap ``{"encData": ...}`` payloads (top level or under ``data``)."""
    if isinstance(payload, dict):
        if isinstance(payload.get("encData"), str):
            return decrypt_enc_data(payload["encData"])
        inner = payload.get("data")
        if isinstance(inner, dict) and isinstance(inner.get("encData"), str):
            return {**payload, "data": decrypt_enc_data(inner["encData"])}
    return payload


def _restrict(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:  # pragma: no cover - best effort on Windows
        pass


def build_fernet(secret: str | None, key_file: Path) -> tuple[Fernet, bool]:
    """Return (fernet, generated). Uses ``secret`` if given, else loads/creates ``key_file``."""
    if secret:
        raw = secret.encode()
        try:
            return Fernet(raw), False
        except ValueError:
            derived = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())
            return Fernet(derived), False
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        try:
            return Fernet(key_file.read_bytes().strip()), False
        except ValueError as exc:
            raise ValueError(f"The encryption key file {key_file} is damaged. Restore it from a backup, or delete "
                             "it and sign in again.") from exc
    key = Fernet.generate_key()
    fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key)
    _restrict(key_file)
    return Fernet(key), True
