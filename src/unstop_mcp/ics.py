"""iCalendar (RFC 5545) export of upcoming deadlines: import into Google Calendar, Outlook or Apple Calendar."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from unstop_mcp import __version__
from unstop_mcp.models import Deadlines, parse_dt


def _escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Fold lines longer than 75 octets, as RFC 5545 §3.1 requires."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts: list[str] = []
    chunk = b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(chunk) + len(b) > (75 if not parts else 74):
            parts.append(chunk.decode("utf-8"))
            chunk = b""
        chunk += b
    parts.append(chunk.decode("utf-8"))
    return "\r\n ".join(parts)


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def deadlines_to_ics(deadlines: Deadlines, reminder_hours: int = 24) -> str:
    stamp = _utc(datetime.now(UTC))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//unstop-mcp//{__version__}//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Unstop deadlines",
    ]
    for item in deadlines.items:
        start = parse_dt(item.when)
        if start is None:
            continue
        uid = hashlib.sha256(f"{item.opportunity_id}|{item.kind}|{item.what}|{item.when}".encode()).hexdigest()[:24]
        desc = f"{item.action}\n{item.url or ''}".strip()
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}@unstop-mcp",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_utc(start)}",
            "DURATION:PT30M",
            _fold(f"SUMMARY:{_escape(f'{item.what}: {item.opportunity}')}"),
            _fold(f"DESCRIPTION:{_escape(desc)}"),
        ]
        if item.url:
            lines.append(_fold(f"URL:{item.url}"))
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            _fold(f"DESCRIPTION:{_escape(item.what)}"),
            f"TRIGGER:-PT{reminder_hours}H",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
