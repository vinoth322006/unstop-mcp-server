"""Error hierarchy. Every message here is safe to show to an MCP client (no tokens, no internals)."""

from __future__ import annotations


class UnstopError(Exception):
    """Base class for all errors raised by this package."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class AuthRequired(UnstopError):
    """No Unstop session exists for the caller."""


class AuthExpired(UnstopError):
    """The Unstop session was rejected and could not be refreshed."""


class AuthFailed(UnstopError):
    """Login failed (wrong OTP/password, MFA required, etc.)."""


class PermissionDenied(UnstopError):
    """The MCP caller lacks the scope for this operation, or Unstop returned 403."""


class NotFound(UnstopError):
    pass


class RateLimited(UnstopError):
    pass


class UpstreamError(UnstopError):
    """Unstop returned something unexpected (5xx, HTML, malformed JSON)."""


class InvalidInput(UnstopError):
    pass


class ManualStep(UnstopError):
    """The action exists on unstop.com but can't (or shouldn't) be done automatically. Tells the AI to hand off."""

    def __init__(self, reason: str, url: str | None = None) -> None:
        where = f" Please do it yourself on unstop.com: {url}" if url else " Please do it yourself on unstop.com."
        super().__init__(f"Can't do this automatically: {reason.rstrip('.')}.{where}")
        self.url = url
