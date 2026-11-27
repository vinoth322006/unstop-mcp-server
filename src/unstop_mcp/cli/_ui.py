"""Terminal helpers shared by every command: colours, prompts, settings and runtime construction."""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from unstop_mcp.config import Settings

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass


_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def ok(msg: str) -> None:
    print(f"  {_c('32', '✔')} {msg}")


def warn(msg: str) -> None:
    print(f"  {_c('33', '!')} {msg}")


def fail(msg: str) -> None:
    print(f"  {_c('31', '✘')} {msg}")


def heading(msg: str) -> None:
    print(f"\n{_c('1;36', msg)}")


def ask_yes(question: str, default: bool = True, assume: bool = False) -> bool:
    if assume:
        return default
    hint = "Y/n" if default else "y/N"
    try:
        answer = input(f"  {question} [{hint}] ").strip().lower()
    except EOFError:
        return default
    return default if not answer else answer in ("y", "yes")


def _settings(args: argparse.Namespace) -> Settings:
    overrides = {}
    for key in ("transport", "host", "port", "public_url", "data_dir"):
        val = getattr(args, key, None)
        if val is not None:
            overrides[key] = val
    return Settings(**overrides)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _runtime(settings: Settings) -> Any:
    from unstop_mcp.runtime import build_runtime  # no MCP SDK import: keeps terminal commands fast

    return build_runtime(settings)


WELCOME = """\
{title}  v{version}
Lets AI assistants (Claude, Cursor, ...) search Unstop and work with your Unstop account.

  Get started (one time):   unstop-mcp setup
  Try it in the terminal:   unstop-mcp search "AI hackathon"
                            unstop-mcp deadlines
  Check everything:         unstop-mcp doctor
  All commands:             unstop-mcp --help

AI apps start this program by themselves; you don't need to keep it running.
"""


def _short_date(value: str | None) -> str:
    from unstop_mcp.models import parse_dt

    dt = parse_dt(value)
    return dt.strftime("%d %b %Y") if dt else "-"
