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


_BLOCK_START = re.compile(r"^\s*(?:[-*+] |\d+\. |#|\||```|>)")


def unwrap(markdown: str) -> str:
    """Join hard-wrapped lines. Release pages show every newline as a line break, unlike README files."""
    out: list[str] = []
    for line in markdown.splitlines():
        prev = out[-1] if out else ""
        joinable = prev.strip() and not prev.lstrip().startswith(("|", "#", "```"))
        if line.strip() and joinable and not _BLOCK_START.match(line):
            out[-1] = f"{prev.rstrip()} {line.strip()}"
        else:
            out.append(line)
    return "\n".join(out)


def notes(version: str, changelog: str) -> str:
    version = version.removeprefix("v")
    body = changelog_section(changelog, version) or f"See [CHANGELOG.md]({REPO}/blob/master/CHANGELOG.md)."
    raw = "https://raw.githubusercontent.com/vinoth322006/unstop-mcp-server/master"
    return unwrap(f"{body}\n\n{DOWNLOADS.format(v=version, raw=raw, repo=REPO)}") + "\n"


if __name__ == "__main__":
    text = notes(sys.argv[1], (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"))
    sys.stdout.buffer.write(text.encode("utf-8"))  # UTF-8 even where the console default is not (Windows)
