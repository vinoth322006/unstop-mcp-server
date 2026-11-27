# Security policy

## Supported versions

Security fixes go into the latest release. Please update before reporting.

| Version | Supported |
|---|---|
| 1.5.x | Yes |
| < 1.5 | No |

## Reporting a vulnerability

**Please don't open a public issue for security problems.**

Report it privately through GitHub:
**[Report a vulnerability](https://github.com/vinoth322006/unstop-mcp-server/security/advisories/new)**
(the **Security** tab → **Report a vulnerability**).

Please include:
- what an attacker could do, and what they need first (local access, a stolen API key, a malicious web page…);
- steps to reproduce, and the version (`unstop-mcp --version`) and OS;
- whether it affects desktop mode (`stdio`), server mode (`http`), or both.

Never include your real one-time codes, session files, API keys or `secret.key`.

The maintainer aims to reply within a week. Once a fix is released, the advisory is published with credit to you, unless you'd
rather stay anonymous.

## What's in scope

- Leaking a session, API key, one-time code or encryption key.
- One user or tenant reading or acting on another's account.
- The local sign-in page being reachable or usable by another site or program.
- Private data (phone numbers, other people's emails) reaching the AI.
- An account-changing action happening without the user's confirmation.
- Remote code execution, path traversal or unsafe file writes, for example in the config files the setup edits.

Problems in Unstop itself (unstop.com) should go to Unstop.

## How this project protects you

- One-time codes are typed into a page on `127.0.0.1`, never into the chat, and never stored.
- Sessions are encrypted at rest (Fernet), in files readable only by your user account.
- Server-mode API keys are 256-bit random, stored only as SHA-256 hashes, compared in constant time, scoped, can
  expire, and can be revoked instantly.
- Per-user rate limits, a write audit log, Host and Origin checks, and secrets redacted from logs.
