## What and why

<!-- What does this change, and why? Link an issue if there is one. -->

## How I checked it

<!-- Tests added or run, and anything you tried by hand. -->

- [ ] `ruff check src tests packaging`, `mypy src` and `pytest -m "not live"` pass
- [ ] New or changed tools are in the README tool table and `CHANGELOG.md`
- [ ] Nothing private (phone numbers, other people's emails, tokens) can reach the AI or the logs
- [ ] Anything that changes an account asks the user first and respects `UNSTOP_MCP_ENABLE_WRITE_TOOLS=false`
