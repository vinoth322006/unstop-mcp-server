# Installing Unstop MCP

Pick **one** option. Not sure? Use the first row that matches you.

| You use… | Best option | Needs Python? | Time |
|---|---|---|---|
| **Claude Desktop on Windows** | [A. One-click extension](#a-one-click-claude-desktop-extension-windows) | No | 30 s |
| **Windows**, any AI app | [B. One-line installer](#b-one-line-installer-windows) | No | 1 min |
| **macOS / Linux** | [C. One-line installer](#c-one-line-installer-macos--linux) | uv, pipx or Python 3.11+ | 1 min |
| You already have Python tools | [D. uv / pipx / pip](#d-uv--pipx--pip) | Yes | 1 min |
| No installing at all | [E. Portable .exe](#e-portable-exe-windows) | No | 30 s |
| You downloaded the source | [F. From source](#f-from-source) | Yes | 2 min |
| A shared server for a team | [G. Docker](#g-docker-server-for-teams) | No (Docker) | 5 min |

After any option, **sign in** (optional, but needed for your registrations, deadlines and recommendations)
in one of two ways:
- Ask your AI app: *"Sign me in to Unstop"*. A secure page opens in your browser.
- Or run `unstop-mcp login --browser`.

Either way, your one-time code goes only into that page, never into the chat.

---

## A. One-click Claude Desktop extension (Windows)

1. Download **`unstop-mcp-<version>.mcpb`** from the [latest release](https://github.com/vinoth322006/unstop-mcp-server/releases/latest).
2. Double-click it. Claude Desktop shows an install dialog. Click **Install**.
3. In a chat, ask *"Sign me in to Unstop"*, then *"What are my upcoming Unstop deadlines?"*

To update or remove it: **Settings → Extensions → Unstop**.

## B. One-line installer (Windows)

Open **PowerShell** and paste:

```powershell
irm https://raw.githubusercontent.com/vinoth322006/unstop-mcp-server/master/get.ps1 | iex
```

This downloads the standalone program, **verifies its checksum**, adds `unstop-mcp` to your PATH and starts the
guided setup, which signs you in and connects Claude Desktop, Claude Code, Cursor and Windsurf.

- Run the same line again to update.
- To uninstall, download `get.ps1` and run `.\get.ps1 -Uninstall`.

## C. One-line installer (macOS / Linux)

```sh
curl -LsSf https://raw.githubusercontent.com/vinoth322006/unstop-mcp-server/master/get.sh | sh
```

It uses `uv` if you have it, otherwise `pipx`, otherwise `pip --user`, and then runs `unstop-mcp setup`.

## D. uv / pipx / pip

```sh
uv tool install git+https://github.com/vinoth322006/unstop-mcp-server     # recommended
pipx install git+https://github.com/vinoth322006/unstop-mcp-server        # or
pip install --user git+https://github.com/vinoth322006/unstop-mcp-server  # or
unstop-mcp setup
```

You can also run it without installing, straight from an AI app's MCP config:

```json
{ "mcpServers": { "unstop": { "command": "uvx",
  "args": ["--from", "git+https://github.com/vinoth322006/unstop-mcp-server", "unstop-mcp", "serve"] } } }
```

## E. Portable .exe (Windows)

Download **`unstop-mcp-<version>-windows-x64.exe`** from the release, put it anywhere (for example on a USB stick),
then run:

```powershell
.\unstop-mcp-1.5.0-windows-x64.exe setup
```

Setup points your AI apps at that file, so keep it in the same place afterwards.

## F. From source

```powershell
git clone https://github.com/vinoth322006/unstop-mcp-server
cd unstop-mcp-server
powershell -ExecutionPolicy Bypass -File .\install.ps1     # Windows
sh install.sh                                              # macOS / Linux
```

## G. Docker (server for teams)

```sh
docker run -d --name unstop-mcp -p 127.0.0.1:8000:8000 -v unstop-data:/data \
  -e UNSTOP_MCP_SECRET_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" \
  ghcr.io/vinoth322006/unstop-mcp:latest
docker exec -it unstop-mcp unstop-mcp login --tenant asha
docker exec -it unstop-mcp unstop-mcp keys create --tenant asha --scopes unstop:read,unstop:write
```

Clients connect to `http(s)://your-host/mcp` with `Authorization: Bearer usk_…`. Put a TLS proxy in front.
See the README section *Run it on a server* for details.

---

## Connecting apps manually

`unstop-mcp setup` and `unstop-mcp connect all` do this for you, but here are the details if you prefer.

| App | Where |
|---|---|
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json`. For the Microsoft Store build: `%LOCALAPPDATA%\Claude-Data\anthropicpbc.claude_*\claude_desktop_config.json`. On macOS: `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Claude Code | `claude mcp add --scope user unstop -- unstop-mcp serve` |
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| VS Code (Copilot) | Command palette → **MCP: Add Server** → command `unstop-mcp serve` |

```json
{ "mcpServers": { "unstop": { "command": "unstop-mcp", "args": ["serve"] } } }
```

To load only some tool groups, add `"env": { "UNSTOP_MCP_TOOLSETS": "discover,account" }` to that entry (or pass
`--toolsets discover,account` to `setup` / `connect`). The groups are `discover`, `account`, `alerts`,
`registration` and `teams`.

## Check your install

```powershell
unstop-mcp doctor
```

This checks your connection to Unstop, your sign-in and every AI app, and prints the exact command to fix anything
that isn't right.
