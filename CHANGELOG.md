# Changelog

## 1.5.0 — 2026-11-27 (modular, runs everywhere)

**Pick your tools**
- Tools are now in five groups: `discover`, `account`, `alerts`, `registration` and `teams`. Sign-in and status
  are always on. Load fewer with `--toolsets` on `setup`/`connect`, `UNSTOP_MCP_TOOLSETS`, or the **Tool groups**
  setting in the Claude Desktop extension. A misspelt name is refused before any config file is touched.
- `server_status` reports which groups are loaded.

**Modular code (no behaviour change)**
- The four largest files were split into packages, each module with one job:
  - `client/`: catalog → account/alerts → registration → teams, each layer using only the ones below it;
  - `tools/`: one module per tool group, each with its own instructions;
  - `models/`: schemas and normalisers;
  - `cli/`: one module per command group.
- `from unstop_mcp.models import …` and the other public imports still work.

**Runs everywhere**
- CI now runs on Windows, macOS and Linux with Python 3.11, 3.12 and 3.13. It also checks the installers (shell
  syntax, no Windows line endings), installs the wheel into a clean environment, and builds the Docker image and
  checks its health endpoint.
- Line endings are fixed by `.gitattributes`. `get.sh`, `install.sh` and the `Dockerfile` had Windows line endings,
  which break `curl … | sh` and Docker builds. A test now guards this.
- The full offline suite (268 tests) passes on Python 3.11, 3.12 and 3.13.

## 1.4.1 — 2026-11-27 (reliability pass)

Each tool is now tested under every way Unstop can fail, and the issues found are fixed:

- **Chaos tests (new):** all 41 tools run against 12 kinds of broken Unstop responses: server errors, HTML pages,
  empty bodies, `null`, wrong JSON shapes, junk field types, expired sessions, rate limiting and the network being
  down. They also run against 17 hostile inputs. 20 tools used to crash with "Internal error" on malformed data.
  Now every normaliser is type-safe, one bad record in a list is skipped instead of failing the whole list, and a
  record that can't be read at all returns a clear "unexpected format" message.
- **Fixed a hidden character bug:** `"1 days left"` was never corrected to `"1 day left"` because an invisible
  backspace character had got into the regex. A test now fails if any control character appears in the source.
- **Fixed calendar files saving to the wrong folder:** files went to the home folder when Windows' Downloads folder
  had been moved. The real location now comes from the OS (Windows registry, `XDG_DOWNLOAD_DIR` on Linux).
- **Made `my_snapshot` 3× faster** (9.6 s → 3.4 s, about 95 → 17 requests). The fresh-registration merge used a
  per-type baseline, which made newer teams of other types look "missing".
- **Rate limit fixed for your own computer:** parallel calls were refused ("Too many requests") even when served
  from cache. The per-user limit now applies only to remote HTTP servers, and short bursts there wait up to 2 s
  instead of being refused.
- **Live results:** a sweep of 36 tools on a real account had 0 failures. 30 concurrent calls had 0 errors, taking
  7.2 s cold and 0.47 s cached (median 47 ms).

## 1.4.0 — 2026-11-27

**Register for opportunities (verified live)**
- `prepare_registration` checks every rule without changing anything:
  - free, no custom questions or resume, no Aadhaar/face/audio checks, no proctoring consent;
  - registration happens on unstop.com itself, with no minimum team size above one;
  - you're eligible and not already registered.
  It shows exactly what will be submitted (mobile masked, newsletters off) and returns a signed confirmation token
  that is bound to you and that listing and lasts 10 minutes.
- `register_for_opportunity` needs that token and re-checks every rule before submitting. `cancel_registration`
  undoes a registration.
- A dry run on 31 live listings registered 21 cleanly and blocked the other 10 with the exact reason. A real
  registration (AI Agent Development & Enhancement Hackathon) succeeded and was confirmed by Unstop.

**Teams**
- `my_team`, `suggest_teammates` (past teammates, with contact details hidden), `team_invitations`,
  `invite_teammate` (by email or past teammate), `cancel_invitation`, `respond_to_invitation`,
  `respond_to_join_request`, `remove_team_member` and `leave_team`. That brings the total to 41 tools.

**Clear hand-offs**
- Anything that can't be automated (fees, custom forms, verification, full teams, leader-only actions, or Unstop
  rejecting the request) now returns one standard message: *"Can't do this automatically: … Please do it yourself on
  unstop.com: link"*. The AI is told not to retry.

**Fixes found during live testing**
- `my_participation` said "not registered" for events whose rounds aren't published yet. It now uses Unstop's own
  team record.
- `my_registrations` missed new sign-ups because Unstop's list is a search index that lags. Your live team list
  now fills the gap.

## 1.3.0 — 2026-11-27

**New operations (29 tools in total)**
- `my_notifications` and `mark_notifications_read`: results, registration confirmations and cancellations, team
  activity and rewards, each with a link. In the terminal: `unstop-mcp inbox`.
- `closing_soon`: open listings whose registration closes within N days, soonest first. In the terminal:
  `unstop-mcp closing`.
- `get_organisation`: organiser details. Listings now include `organisation_id` so the AI can look it up.
- `unstop_leaderboard`: Unstop's global points leaderboard.
- `my_courses`: enrolled courses with progress, certificate and continue links.
- `save_deadlines_calendar`: writes an `.ics` file straight to your Downloads folder.
- `sign_out`: signs you out from the chat.
- `my_snapshot` now includes your coins and counts wins across every certificate page (it used to stop at 50).

**Fixes from a full code audit**
- Sessions were read and decrypted from disk on every tool call. They are now cached in memory and still pick up
  sign-ins done in another process. Snapshots got about 40% faster.
- A rejected refresh token was retried on every request. The dead session is now removed and you are asked to
  sign in again.
- Switching accounts could serve the previous account's cached data for up to 30 seconds. Sign-in and sign-out now
  clear that account's cache.
- `1` and `0` in Unstop data were being read as missing values, because in Python `1 == True`.
- A damaged API-key file locked out every client. The last good key set now stays active.
- A damaged encryption-key file now gives a clear message. A network error during Unstop's CSRF refresh is
  reported cleanly instead of showing as an internal error.
- The browser sign-in page could hit a race when finishing from several threads at once.
- Round lists with unexpected entries no longer crash. Rounds now include their ids.
- Removed dead code: an unused `Page` model, `compact_record`, `is_expired`, `get_settings` and the `Scope` alias.
- A test now checks that the tool type lists match the model constants and that every tool has a useful description.

## 1.2.0 — 2026-11-27

**New features**
- **Sign in from the browser:** the `sign_in` tool (or `unstop-mcp login --browser`) opens a local, single-use
  page where you type your email and one-time code. The code never goes through the chat. The page is
  loopback-only and protected by an unguessable link and a CSRF nonce; it pins the Host header, sets a strict
  CSP, locks after 5 wrong codes and expires after 10 minutes.
- **Saved searches and alerts:** `save_search`, `check_saved_searches`, `list_saved_searches` and
  `delete_saved_search`, plus `unstop-mcp alerts` in the terminal. Each new listing is reported once.
- **Am I eligible?:** `check_eligibility` compares your graduation year, specialization and student/fresher status
  with the listing's published rules, and gives a reason for each rule.
- **Snapshot:** `my_snapshot` and `unstop-mcp me` show registrations by type, certificates and wins, watchlist size
  and your next deadline.

**New ways to install**
- One-click **Claude Desktop extension** (`.mcpb`), validated with the official `mcpb` tool.
- **Standalone Windows `.exe`**: no Python needed. Double-clicking it starts the guided setup.
- One-line installers: `get.ps1` (Windows, checksum-verified, keeps PATH exactly as it was on uninstall) and
  `get.sh` (macOS/Linux via uv, pipx or pip).
- `uv tool install` / `pipx install` / `uvx` from git, a Docker image on GHCR, and a tag-triggered release workflow
  that builds everything with SHA-256 checksums.
- See [INSTALL.md](INSTALL.md).

**Fixes**
- Claude Desktop from the Microsoft Store is now detected in `%LOCALAPPDATA%\Claude-Data\…`.

## 1.1.0 — 2026-11-27

- `my_deadlines`, `recommended_for_me`, `compare_opportunities`, `server_status`, and calendar (`.ics`) export.
- Guided `setup`, `connect`/`disconnect` for Claude Desktop, Claude Code, Cursor and Windsurf, `doctor`, and
  terminal `search`/`deadlines`.
- Circuit breaker, stale-if-error cache, single-flight request de-duplication, per-user cache, and per-user rate
  limits. Watchlist changes go to an audit log. HTTP mode requires an encryption key.
- Fixes: finished listings no longer show as open; "soonest deadline" sorting now compares real dates.

## 1.0.0 — 2026-11-26

- Rewrite of the original mock-data prototype: live Unstop data, OTP login with encrypted sessions that refresh
  automatically, API keys for HTTP clients, multi-tenant support, and typed outputs with privacy filtering.
