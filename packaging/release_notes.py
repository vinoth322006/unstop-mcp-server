"""Write the GitHub release notes for a version: its CHANGELOG.md section plus a "which file do I need?" table.

    python packaging/release_notes.py 1.5.0 > notes.md
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = "https://github.com/vinoth322006/unstop-mcp-server"

DOWNLOADS = """\
## Which file do I need?

| You use | Download | Then |
|---|---|---|
| **Claude Desktop** (Windows) | `unstop-mcp-{v}.mcpb` | Double-click it and choose **Install** |
| **Windows**, any AI app, no Python | `unstop-mcp-{v}-windows-x64.exe` | Run `unstop-mcp-{v}-windows-x64.exe setup` |
| **macOS / Linux** | nothing | `curl -LsSf {raw}/get.sh \\| sh` |
| **Python** (uv / pipx / pip) | `unstop_mcp-{v}-py3-none-any.whl` | `pipx install unstop_mcp-{v}-py3-none-any.whl` |
| **Docker** | nothing | `docker pull ghcr.io/vinoth322006/unstop-mcp:v{v}` |

Check a download with `sha256sum -c SHA256SUMS.txt --ignore-missing`. Every option is explained in
[INSTALL.md]({repo}/blob/master/INSTALL.md).
"""


def changelog_section(text: str, version: str) -> str:
    """The body under `## <version> …` up to the next `## ` heading, or '' if there is none."""
    match = re.search(rf"^## {re.escape(version)}(?=\s).*?$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    return match.group(1).strip() if match else ""


def notes(version: str, changelog: str) -> str:
    version = version.removeprefix("v")
    body = changelog_section(changelog, version) or f"See [CHANGELOG.md]({REPO}/blob/master/CHANGELOG.md)."
    raw = "https://raw.githubusercontent.com/vinoth322006/unstop-mcp-server/master"
    return f"{body}\n\n{DOWNLOADS.format(v=version, raw=raw, repo=REPO)}"


if __name__ == "__main__":
    sys.stdout.write(notes(sys.argv[1], (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")))
