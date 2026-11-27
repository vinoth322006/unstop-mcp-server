"""Structured logging to stderr (stdout belongs to the stdio MCP transport) with secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
import time

_SECRET_PATTERNS = [
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-~+/=]+", re.I),
    re.compile(r"(usk_)[A-Za-z0-9_\-]+"),
    re.compile(r"(eyJ)[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"),  # JWTs
    re.compile(r'("?(?:access_token|refresh_token|password|otp)"?\s*[:=]\s*"?)[^",\s}]+', re.I),
]


def redact(text: str) -> str:
    for pat in _SECRET_PATTERNS:
        text = pat.sub(lambda m: m.group(1) + "***", text)
    return text


class RedactingFormatter(logging.Formatter):
    def __init__(self, as_json: bool) -> None:
        super().__init__()
        self.as_json = as_json

    def format(self, record: logging.LogRecord) -> str:
        msg = redact(record.getMessage())
        if self.as_json:
            payload = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
                "level": record.levelname,
                "logger": record.name,
                "msg": msg,
            }
            for key in ("tenant", "tool", "status", "duration_ms", "path"):
                if hasattr(record, key):
                    payload[key] = getattr(record, key)
            if record.exc_info:
                payload["exc"] = redact(self.formatException(record.exc_info))
            return json.dumps(payload, ensure_ascii=False)
        base = f"{record.levelname:<7} {record.name}: {msg}"
        if record.exc_info:
            base += "\n" + redact(self.formatException(record.exc_info))
        return base


def configure_logging(level: str = "INFO", as_json: bool = True) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(RedactingFormatter(as_json))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # httpx logs full URLs at INFO; keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
