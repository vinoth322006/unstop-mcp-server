# Analysis of the original `vinoth322006/unstop-mcp-server`

The original is a 4-commit repo of 208 lines across `server.py`, `tools.py`, `run.py`,
`requirements.txt`, `README.md` and `claude_desktop_config.json`. The first commit is titled
"Production-ready Unstop MCP Server".

## What it actually does

| Piece | Reality |
|---|---|
| `discover_contests` | Filters a **hard-coded list of 4 fake contests** ("Hack the Future 2026", "MIT", "$10,000") |
| `track_participation(user_id)` | Looks up `user123` / `user456` in a dict |
| `get_analytics(contest_id)` | Returns fake participant counts and colleges for `c1`–`c4` |
| `unstop://rules` | Three invented "platform rules" |
| `unstop://categories` | `["Hackathon","Coding","AI","Design"]`, which are not Unstop's categories |
| Auth | **None**: no Unstop login, and no protection of the server itself |
| Network | **No HTTP calls at all** |

The README admits this ("runs on some mocked data"), and also claims there is no public API.
In practice the unstop.com website's JSON API is public for listings: `/api/public/*` is
explicitly allowed in `robots.txt`.

## Defects

**Functional**
1. All data is fake, so an assistant using it confidently invents contests, prizes and colleges.
2. `track_participation(user_id)` would leak data across users if it were real: any caller
   could query anyone. Real per-user data needs the user's own authenticated session.
3. "Analytics" (average score, top college) isn't exposed by Unstop to participants at all. It
   was designed around data that doesn't exist.
4. The status and category vocabularies don't match Unstop's (`hackathons`, `competitions`,
   `jobs`, `internships`, `quizzes`, `scholarships`, …; `open`/`closed`).

**Engineering**
5. `requirements.txt` lists `fastapi`/`uvicorn` but never uses them, and leaves `mcp` unpinned
   (`>=1.2.0`). The current `mcp` 2.x removed `mcp.server.fastmcp`, so **a fresh install crashes
   on import**.
6. `run.py --port` is parsed but never passed to `mcp.run()`, so the SSE port is ignored. SSE is
   also deprecated in favour of Streamable HTTP.
7. `run.py` prints to **stdout** before `mcp.run()`, which would corrupt the JSON-RPC stream on
   stdio.
8. Importing a module for its side effects (`import tools` to register decorators) plus a
   global server instance gives you circular-import-prone wiring.
9. `claude_desktop_config.json` hard-codes the author's machine path
   (`C:\Users\vinot\OneDrive\...`).
10. No tests, no linting, no CI, no Docker, no logging config, no error mapping, no retries,
    no rate limiting, no caching, no config management.
11. `AnalyticsModel.average_score: Any`: weak typing presented as "strict validation".

## How the rewrite addresses each

| # | Fix |
|---|---|
| 1, 4 | Live Unstop search/detail endpoints with Unstop's real type and status vocabulary. Responses normalised to compact models (deadline, prize, team size, eligibility, rounds, URL) |
| 2 | Per-user data only through the caller's own Unstop session. Over HTTP the tenant is taken from the verified API key, never from arguments |
| 3 | Dropped. Replaced with things Unstop really exposes to a user: registrations, participation status, watchlist, certificates |
| 5 | `mcp>=2.3,<3` on the new `MCPServer` API. Dependencies pinned by range, packaged with `pyproject.toml` and a console script |
| 6 | Streamable HTTP with host/port/path config and DNS-rebinding protection; stdio for desktop clients |
| 7 | All logs and CLI messages go to stderr |
| 8 | `build_server(settings, runtime)` factory, no import-time side effects, easy to test |
| 9 | Config examples use placeholders; `.env` / environment variables |
| 10 | 65 tests (62 offline + 3 live), ruff, GitHub Actions, multi-stage non-root Docker image with healthcheck, JSON logs with redaction, error hierarchy, retries/backoff, token-bucket limiter, TTL cache |
| 11 | Typed pydantic output models; tools return structured content |

## How the Unstop API was mapped

- Listing and detail endpoints were found by probing `unstop.com/api/public/*` and checking
  the pagination envelope (Laravel style: `data.data[]`, `total`, `last_page`).
- Auth endpoints come from the public Angular bundle: `/api/micro/oauth/v2/login/otp/send`,
  `/login/otp/verify` (`grant_type=otp`), `/user/login` (`grant_type=password`), and `/token`
  (`grant_type=refresh_token`). The client sends `Authorization: Bearer <accessToken>`.
- Some auth responses are wrapped as `{"encData": …}`. The web client decrypts them in the
  browser (AES-256-CBC, key in the bundle, PHP-serialised payload). `crypto.py` does the same.
- Unstop doesn't currently require a CSRF token on these POSTs. A fallback that fetches
  `generate/csrf-cookie` on HTTP 419 is built in anyway.
- Of the sort parameters, only `sort=prize` is honoured server-side. `deadline` sorting is
  applied to the returned page and documented that way in the tool schema.

## Verified vs not verified

- **Verified live:** search (all filters), detail by id and URL, error mapping for unknown ids,
  401 on account endpoints without a session, stdio end to end with a real MCP client, and HTTP
  with no/bad/good API key and a spoofed Host header.
- **Verified with mocks:** OTP login (plain and encrypted responses, wrong code, MFA),
  proactive and on-401 refresh, refresh rejection, tenant isolation, scope enforcement.
- **Verified against a real logged-in account (2026-11-26):** profile, registrations (all and
  filtered by type), watchlist, certificates and per-opportunity participation all return typed
  data. Findings from that run, now handled in code:
  - `my-watchlist` returns HTTP 500 unless `filterName=type&filterValue=<all|type>` is sent.
  - `check-participation` is broken upstream (null when registered, 500 otherwise), so the server
    uses `check-opportunity-participation` instead.
  - That endpoint returns rounds even for listings you never applied to (with `registered:false`),
    so registration is decided from the per-round flag, not from whether rounds exist.
  - Certificate titles live in `certData`, and the viewer link is `/certificate-preview/{cert_id}`.
  - Raw responses contain the user's phone number and teammates' emails. Both are stripped by the
    typed models, and tests assert they never appear in tool output.
- **Watchlist writes verified live:** `add_to_watchlist` then `remove_from_watchlist` on one listing
  (14 → 15 → 14 items, ending identical to the starting watchlist). Unstop answers both with
  `{"status": true}`.
