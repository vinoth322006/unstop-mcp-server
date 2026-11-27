# Unstop MCP

**Ask your AI assistant about Unstop.** Find hackathons, internships, jobs and competitions, see
what's due this week, and keep track of your registrations, without opening the Unstop site.

> "Find AI hackathons on Unstop that close this week"
> "What are my upcoming Unstop deadlines?"
> "Compare these three internships for me"
> "Recommend competitions for a 3rd-year CSE student"

Works with **Claude Desktop, Claude Code, Cursor and Windsurf**, and anything else that supports the
[Model Context Protocol](https://modelcontextprotocol.io).

---

## Install

**Claude Desktop on Windows:** download `unstop-mcp-<version>.mcpb` from the
[latest release](https://github.com/vinoth322006/unstop-mcp-server/releases/latest) and double-click it. That's all.

**Windows, any app, no Python needed:**

```powershell
irm https://raw.githubusercontent.com/vinoth322006/unstop-mcp-server/main/get.ps1 | iex
```

**macOS / Linux:**

```sh
curl -LsSf https://raw.githubusercontent.com/vinoth322006/unstop-mcp-server/main/get.sh | sh
```

There are also a portable `.exe`, `uv` / `pipx` / `pip`, a from-source script and Docker. See
**[INSTALL.md](INSTALL.md)** for every option.

The installers finish with a short guided setup:

1. **Checks Unstop** is reachable.
2. **Signs you in** (optional) with a one-time code from Unstop. No password is stored.
3. **Connects your AI apps.** It finds Claude Desktop, Claude Code, Cursor and Windsurf and adds Unstop to each
   one you approve. Your existing settings are kept, and a backup is made first.

Then **restart your AI app** and start asking. To sign in later, just ask your AI app *"Sign me in to Unstop"*.
A secure page opens in your browser, and your code never goes through the chat.

---

## What it can do

| Ask about… | Tool | Needs sign-in |
|---|---|---|
| Finding opportunities by keyword, type, fee, mode | `search_opportunities` | no |
| Everything about one listing (prizes, rounds, eligibility, job details) | `get_opportunity` | no |
| Putting 2–5 listings side by side | `compare_opportunities` | no |
| **What's due soon**: live rounds, unfinished registrations, closing watchlist items | `my_deadlines` | yes |
| **Am I eligible?** Your profile checked against the listing's rules | `check_eligibility` | yes |
| **Alerts**: save a search, then later ask "anything new?" | `save_search`, `check_saved_searches`, `list_saved_searches`, `delete_saved_search` | no* |
| Your Unstop at a glance: registrations by type, wins, coins, next deadline | `my_snapshot` | yes |
| **What closes in the next few days** | `closing_soon` | no |
| Your notifications (results, registrations, team activity), and marking them read | `my_notifications`, `mark_notifications_read` | yes |
| Your enrolled courses and progress | `my_courses` | yes |
| About an organiser or company | `get_organisation` | no |
| Unstop's global points leaderboard | `unstop_leaderboard` | no |
| Putting your deadlines into your calendar app | `save_deadlines_calendar` | yes |
| Signing out | `sign_out` | – |
| Unstop's personalised picks for you | `recommended_for_me` | yes |
| Signing in from a secure browser page | `sign_in` | – |
| **Registering you** for free, simple events (preview first, then your OK) | `prepare_registration`, `register_for_opportunity`, `cancel_registration` | yes |
| **Your team**: members, invite by email or past teammate, answer invites and join requests, remove or leave | `my_team`, `suggest_teammates`, `invite_teammate`, `team_invitations`, `respond_to_invitation`, `respond_to_join_request`, `cancel_invitation`, `remove_team_member`, `leave_team` | yes |
| Your profile | `my_profile` | yes |
| Everything you've registered for, and whether each registration is complete | `my_registrations` | yes |
| Your status in each round of one event | `my_participation` | yes |
| Your watchlist / save or unsave a listing | `my_watchlist`, `add_to_watchlist`, `remove_from_watchlist` | yes |
| Your certificates, with links | `my_certificates` | yes |
| Is the connection healthy? | `server_status`, `auth_status` | no |

\* Saved searches are kept on your computer and work without signing in.

Ready-made prompts: **Find opportunities for me**, **What's due soon**, and **Plan my week on Unstop**.
Your deadlines are also available as a calendar file (`unstop://me/deadlines.ics`).

**Registering:** it can register you for free events that need nothing beyond your Unstop profile. It always shows you
exactly what it will submit and waits for your yes. Events with fees, custom questions or resumes, ID/face checks,
proctoring, or a minimum team size are handed back with a link: *"Can't do this automatically … please do it
yourself on unstop.com"*.

### Load only the tools you need

Tools come in five groups. All of them load by default; pick fewer to keep your AI app's tool list short.

| Group | Tools |
|---|---|
| `discover` | search, details, compare, closing soon, organisers, leaderboard |
| `account` | profile, snapshot, deadlines (+ calendar), registrations, rounds, watchlist, certificates, notifications, courses, picks for you, eligibility |
| `alerts` | saved searches and "anything new?" |
| `registration` | prepare, register, cancel |
| `teams` | your team, invites, join requests, remove or leave |

Sign-in and status tools are always on.

```powershell
unstop-mcp connect claude-desktop --toolsets discover,account
unstop-mcp setup --toolsets discover,alerts
```

or set `UNSTOP_MCP_TOOLSETS=discover,account` in any app's server config. A misspelt group name is refused before
anything is changed. In the Claude Desktop extension, use the **Tool groups** setting.

### Without an AI app

```powershell
unstop-mcp search AI hackathon --sort prize
unstop-mcp deadlines
unstop-mcp deadlines --ics my-deadlines.ics     # import into Google Calendar / Outlook / Apple Calendar
unstop-mcp me                                   # your Unstop at a glance
unstop-mcp alerts --add "AI hackathons" AI --type hackathons
unstop-mcp alerts                               # what's new since last time
```

---

## Everyday commands

| Command | What it does |
|---|---|
| `unstop-mcp setup` | Guided setup (safe to run again) |
| `unstop-mcp login --browser` / `logout` | Sign in (on a browser page) or out of Unstop |
| `unstop-mcp me` | Your registrations, wins, coins and next deadline |
| `unstop-mcp inbox` | Your notifications (`--unread`) |
| `unstop-mcp closing` | Listings closing soon (`--days 3 --type hackathons`) |
| `unstop-mcp alerts` | New listings for your saved searches (`--add NAME keywords`, `--remove NAME`) |
| `unstop-mcp connect claude-desktop` | Connect one app (`claude-code`, `cursor`, `windsurf`, or `all`). Add `--remove` to undo, `--toolsets` to pick tool groups |
| `unstop-mcp doctor` | Checks the connection, your sign-in and every app, and says how to fix anything wrong |
| `unstop-mcp search …` / `deadlines` | Use Unstop from the terminal |

On Windows the program is at `.venv\Scripts\unstop-mcp.exe` inside this folder. The installer
connects your apps to it, so you never have to start it yourself.

### Something not working?

Run `unstop-mcp doctor`. It tells you what's wrong and the exact command to fix it.

| You see | Do this |
|---|---|
| "Not logged in to Unstop" | `unstop-mcp login` |
| The AI app doesn't show Unstop | `unstop-mcp connect all`, then fully quit and reopen the app |
| "Unstop is not responding right now" | Unstop is having trouble; the server retries by itself within a minute |
| "Too many requests" | Wait a minute. There's a per-user limit that protects your account |

---

## How it's built

**Reliable**
- Retries with exponential backoff and jitter, and honours Unstop's `Retry-After` header.
- A **circuit breaker**: if Unstop goes down, calls fail fast with a clear message instead of
  hanging, and resume automatically.
- **Stale-if-error**: during an outage, recently fetched public listings are still served.
- `my_deadlines` **degrades gracefully**: if one source fails, you get the rest plus a note.
- Login sessions **renew themselves** before they expire. After a rejected token the server renews
  it once and retries.

**Fast**
- Shared connection pool, 5-minute cache for public data, and a 30-second cache per user for
  account data that is cleared when you change your watchlist.
- **Single-flight**: identical requests made at the same moment share one network call.
- Comparisons and deadlines fetch their sources **in parallel**, with a concurrency cap.
- Responses are trimmed from Unstop's 150+ raw fields to what's useful, which saves AI tokens.

**Secure**
- The one-time code is typed into a hidden prompt and never stored. Session tokens are
  **encrypted at rest** (Fernet: AES + HMAC), and the files and folders are readable only by you.
- **Privacy filtering**: your phone number and your teammates' emails come back from Unstop but are
  **never** passed to the AI. Tests enforce this.
- Remote mode requires **API keys**. They are 256-bit random, stored only as a SHA-256 hash and
  checked in constant time. They have read/write scopes, can expire, and can be revoked
  instantly.
- **Per-user rate limiting**, a **write audit log**, Host/Origin checks against DNS rebinding,
  secrets redacted from all logs, and clean error messages with no stack traces sent to the AI.
- HTTP mode **refuses to start** without an explicit encryption key.

**Well-engineered**: typed end to end (pydantic models, mypy clean, ruff clean, no dead code); 200+ offline tests
plus live smoke tests; CI on Python 3.11–3.13; a non-root, read-only Docker image with a healthcheck.

---

## Run it on a server (for teams)

```powershell
copy .env.example .env          # set UNSTOP_MCP_SECRET_KEY and UNSTOP_MCP_PUBLIC_URL
docker compose up -d --build
docker compose exec unstop-mcp unstop-mcp login --tenant asha
docker compose exec unstop-mcp unstop-mcp keys create --tenant asha --scopes unstop:read,unstop:write
```

Each person gets their own **tenant**: their own Unstop sign-in and their own API key, which only ever acts as
them. Clients connect to `https://your-host/mcp` with `Authorization: Bearer usk_…`:

```powershell
claude mcp add --transport http unstop https://mcp.example.com/mcp --header "Authorization: Bearer usk_..."
```

Manage keys with `keys list`, `keys revoke <id>` and `keys create --ttl-days 90`. Changes apply without a
restart. `GET /healthz` reports `ok` or `degraded`. Put a TLS proxy (Caddy, nginx or Cloudflare Tunnel) in
front: compose binds to 127.0.0.1 only.

<details>
<summary>All settings</summary>

Environment variables (or `.env`). See [.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `UNSTOP_MCP_TRANSPORT` | `stdio` | `stdio` (desktop apps) or `http` (server) |
| `UNSTOP_MCP_SECRET_KEY` | generated file | Encrypts stored sessions; **required** for `http` |
| `UNSTOP_MCP_PUBLIC_URL` | – | External URL (also added to the Host allow-list) |
| `UNSTOP_MCP_DATA_DIR` | `~/.unstop-mcp` | Sessions, keys, generated key |
| `UNSTOP_MCP_CLIENT_RATE_LIMIT_PER_MINUTE` | `120` | Tool calls per user per minute |
| `UNSTOP_MCP_RATE_LIMIT_PER_SECOND` | `4` | Total requests to Unstop |
| `UNSTOP_MCP_CACHE_TTL_SECONDS` / `PRIVATE_CACHE_TTL_SECONDS` | `300` / `30` | Cache freshness |
| `UNSTOP_MCP_STALE_CACHE_SECONDS` | `3600` | How long stale public data may be served during outages |
| `UNSTOP_MCP_BREAKER_THRESHOLD` / `BREAKER_COOLDOWN_SECONDS` | `5` / `30` | Circuit breaker |
| `UNSTOP_MCP_ENABLE_WRITE_TOOLS` | `true` | `false` hides every tool that changes your account (register, teams, watchlist, mark read) |
| `UNSTOP_MCP_TOOLSETS` | `all` | Comma list of tool groups: `discover`, `account`, `alerts`, `registration`, `teams` |

</details>

<details>
<summary>Architecture</summary>

Each layer only imports the ones below it, and each tool group is a separate module with its own instructions.

```
src/unstop_mcp/
  cli/            one module per command group: setup/connect/doctor · account · discover · keys · serve
  server.py       builds the MCP server from the chosen tool groups; resources and prompts
  tools/          one module per tool group (discover, account, alerts, registration, teams, system)
                  _common.py: ToolGuard (rate limit, errors, logging), scopes, audit log, shared types
  client/         Unstop operations, layered: catalog → account/alerts → registration → teams
  models/         schemas.py (what tools return) · normalize.py (type-safe parsing of raw Unstop JSON)
  runtime.py      shared HTTP client, session store and cache (no MCP import, so the CLI starts fast)
  http.py         Pool · cache + stale-if-error · single-flight · circuit breaker · token bucket · retries
  registration.py · teams.py   registration rules and confirmation tokens · team normalisers and privacy
  clients.py      Detects AI apps and safely merges their config files
  ics.py          RFC 5545 calendar export
  crypto.py       Unstop encData decryption; Fernet keys
  auth/           OTP/password login + refresh · encrypted session store · hashed API keys
```

Unstop endpoints (from the unstop.com web app): search `/api/public/opportunity/search-result`, detail
`/api/public/competition/{id}`, login `/api/micro/oauth/v2/*`, account `/api/user/*`, recommendations
`/api/opportunity/recommendations`, rounds `/api/user/my-rounds`, notifications `/api/get-notifications`,
courses `/api/user/enrolled-courses`, organisations `/api/public/organisation/with-opportunity/{id}`, leaderboard
`/api/public/gamification/get-paginated-leaderboard/global`. Details and findings are in [ANALYSIS.md](ANALYSIS.md).

</details>

## Development

```powershell
pip install -e ".[dev]"
pytest -m "not live"      # offline suite (CI: Windows, macOS, Linux × Python 3.11–3.13)
pytest -m live            # against the real Unstop API
ruff check src tests; mypy src
```

## Good to know

- Unstop has no official public API. This uses the same endpoints as unstop.com, so they can change. If that
  happens you get a clear error, and `unstop-mcp doctor` shows what's broken.
- Only the account owner should sign in. Never share your one-time code.
- Not affiliated with or endorsed by Unstop.
