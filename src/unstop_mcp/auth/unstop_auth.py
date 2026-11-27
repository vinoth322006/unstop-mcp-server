"""Login to Unstop as a user (OTP or password), refresh tokens, and hand out valid sessions per tenant.

Endpoints and payloads mirror the unstop.com web client (``/api/micro/oauth/v2/...``).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal

from unstop_mcp.auth.session import DEFAULT_TENANT, UnstopSession, jwt_expiry
from unstop_mcp.auth.store import SessionStore
from unstop_mcp.crypto import maybe_decrypt
from unstop_mcp.errors import AuthExpired, AuthFailed, AuthRequired, InvalidInput, UnstopError
from unstop_mcp.http import UnstopHTTP

log = logging.getLogger(__name__)

OTP_SEND = "/api/micro/oauth/v2/login/otp/send"
OTP_VERIFY = "/api/micro/oauth/v2/login/otp/verify"
PASSWORD_LOGIN = "/api/micro/oauth/v2/user/login"  # noqa: S105 - endpoint path
TOKEN = "/api/micro/oauth/v2/token"  # noqa: S105 - endpoint path, not a secret
LOGOUT = "/api/logout"

Channel = Literal["email", "whatsapp"]


def _unwrap(payload: Any) -> dict[str, Any]:
    """Find the dict that holds ``access_token`` (responses vary: flat, under data, or encrypted)."""
    payload = maybe_decrypt(payload)
    if isinstance(payload, dict):
        if "access_token" in payload:
            return payload
        data = maybe_decrypt(payload.get("data"))
        if isinstance(data, dict):
            if "access_token" in data:
                return data
            return {**payload, **data}
        return payload
    return {}


def _session_or_raise(payload: Any, email: str | None) -> UnstopSession:
    data = _unwrap(payload)
    if data.get("access_token"):
        return UnstopSession.from_token_response(data, email=email)
    if data.get("status") == "mfa_required":
        raise AuthFailed("This account requires multi-factor sign-in. Use OTP login (`unstop-mcp login`).")
    if data.get("passkey_login"):
        raise AuthFailed("This account is set to passkey sign-in. Use OTP login, which skips passkeys.")
    message = data.get("message") or data.get("msg") or "Login failed."
    raise AuthFailed(str(message))


class UnstopAuth:
    def __init__(self, http: UnstopHTTP, store: SessionStore, fallback_token: str | None = None) -> None:
        self.http = http
        self.store = store
        self.fallback_token = fallback_token
        self._locks: dict[str, asyncio.Lock] = {}

    # ----- interactive login (run by the account owner, e.g. via the CLI) -----------------------------
    async def send_otp(self, email: str, channel: Channel = "email", user_category: str = "candidate") -> str:
        body = {"email": email, "otp_channels": [channel], "user_category": user_category, "skip_passkey": True}
        resp = maybe_decrypt(await self.http.request("POST", OTP_SEND, json_body=body))
        data = resp.get("data", resp) if isinstance(resp, dict) else {}
        if isinstance(data, dict) and data.get("status") is False:
            raise AuthFailed(str(data.get("message") or data.get("msg") or "Unstop could not send the OTP."))
        return str((data or {}).get("message") or f"OTP sent via {channel}.")

    async def verify_otp(self, email: str, otp: str, channel: Channel = "email") -> UnstopSession:
        otp = otp.strip()
        if not otp.isdigit() or not 4 <= len(otp) <= 8:
            raise InvalidInput("The OTP should be the 4-8 digit code Unstop sent you.")
        body = {
            "grant_type": "otp",
            "email": email,
            "otp": otp,
            "scope": "*",
            "network": "",
            "channels": [channel],
            "verify_via": [channel],
            "with_access_token": True,
            "e": True,
        }
        return _session_or_raise(await self.http.request("POST", OTP_VERIFY, json_body=body), email)

    async def password_login(self, email: str, password: str) -> UnstopSession:
        body = {
            "grant_type": "password",
            "username": email,
            "email": email,
            "password": password,
            "scope": "*",
            "network": "",
            "access_token": "",
            "e": True,
        }
        return _session_or_raise(await self.http.request("POST", PASSWORD_LOGIN, json_body=body), email)

    async def complete_login(self, tenant: str, session: UnstopSession) -> UnstopSession:
        """Fill in profile details, then persist the session for ``tenant``."""
        try:
            profile = await self.http.request("GET", "/api/user/profile", params={"e": "true"},
                                              token=session.access_token)
            user = profile.get("data", profile) if isinstance(profile, dict) else {}
            if isinstance(user, dict):
                uid = user.get("id")
                session.user_id = session.user_id or (int(str(uid)) if str(uid).isdigit() else None)
                session.email = session.email or user.get("email")
                session.name = session.name or user.get("name") or " ".join(
                    filter(None, [user.get("first_name"), user.get("last_name")])
                ) or None
        except UnstopError as exc:
            log.warning("Logged in, but could not load the profile: %s", exc.message)
        self.store.put(tenant, session)
        self.http.invalidate(tenant)  # never serve the previous account's cached data
        return session

    # ----- token lifecycle ------------------------------------------------------------------------------
    async def refresh(self, session: UnstopSession) -> UnstopSession:
        if not session.refresh_token:
            raise AuthExpired("Unstop session expired and has no refresh token. Log in again.")
        body = {"grant_type": "refresh_token", "scope": "", "network": "", "refresh_token": session.refresh_token}
        try:
            payload = await self.http.request("POST", TOKEN, json_body=body)
        except AuthExpired as exc:
            raise AuthExpired("Unstop refresh token was rejected. Log in again.") from exc
        data = _unwrap(payload)
        if not data.get("access_token"):
            raise AuthExpired("Unstop did not return a new access token. Log in again.")
        return session.model_copy(
            update={
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token") or session.refresh_token,
                "expires_at": jwt_expiry(data["access_token"])
                or (time.time() + float(data["expires_in"]) if data.get("expires_in") else None),
                "refreshed_at": time.time(),
            }
        )

    def _lock(self, tenant: str) -> asyncio.Lock:
        return self._locks.setdefault(tenant, asyncio.Lock())

    async def get_session(self, tenant: str) -> UnstopSession:
        """Return a usable session, refreshing (once, under a per-tenant lock) when close to expiry."""
        async with self._lock(tenant):
            session = self.store.get(tenant)
            if session is None:
                if tenant == DEFAULT_TENANT and self.fallback_token:
                    return UnstopSession(access_token=self.fallback_token,
                                         expires_at=jwt_expiry(self.fallback_token))
                if tenant == DEFAULT_TENANT:
                    raise AuthRequired(
                        "Not logged in to Unstop. Use the sign_in tool (opens a secure page in your browser), "
                        "or run `unstop-mcp login` in a terminal."
                    )
                raise AuthRequired(
                    f"Not logged in to Unstop. The server owner must run `unstop-mcp login --tenant {tenant}`."
                )
            if session.needs_refresh():
                session = await self._refresh_or_forget(tenant, session)
            return session

    async def _refresh_or_forget(self, tenant: str, session: UnstopSession) -> UnstopSession:
        """Refresh; if Unstop definitively rejects the refresh token, delete the dead session so later calls
        say "sign in" immediately instead of retrying the refresh on every request."""
        try:
            session = await self.refresh(session)
        except AuthExpired as exc:
            self.store.delete(tenant)
            self.http.invalidate(tenant)
            log.warning("Unstop session for tenant %s is no longer valid; removed it", tenant)
            raise AuthRequired(f"{exc.message} Sign in again (sign_in tool or `unstop-mcp login`).") from exc
        self.store.put(tenant, session)
        log.info("Refreshed Unstop session", extra={"tenant": tenant})
        return session

    async def force_refresh(self, tenant: str, stale_token: str) -> UnstopSession:
        """Called after a 401. Skips the refresh if another request already replaced the token."""
        async with self._lock(tenant):
            session = self.store.get(tenant)
            if session is None:
                raise AuthExpired("Unstop rejected the access token. Log in again.")
            if session.access_token != stale_token:
                return session
            return await self._refresh_or_forget(tenant, session)

    async def logout(self, tenant: str) -> bool:
        session = self.store.get(tenant)
        if session is not None:
            try:
                await self.http.request("GET", LOGOUT, token=session.access_token)
            except UnstopError:
                pass  # revoke is best effort; local deletion is what matters
        self.http.invalidate(tenant)
        return self.store.delete(tenant)
