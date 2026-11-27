# Contributing

Thanks for helping. Bug reports, fixes, new tools and docs are all welcome.

## Set up

```sh
git clone https://github.com/vinoth322006/unstop-mcp-server && cd unstop-mcp-server
python -m venv .venv
.venv/Scripts/activate        # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -e ".[dev]"
```

Python 3.11, 3.12 or 3.13.

## Before you open a pull request

```sh
ruff check src tests packaging
mypy src
pytest -m "not live"
```

CI runs the same checks on Windows, macOS and Linux with every supported Python, builds the Windows `.exe` and `.mcpb`,
and checks the Docker image. Failures show up as annotations on the run page.

### Live tests

`pytest -m live` talks to the real unstop.com. It only reads public data. If you add a live test that uses an account,
make it read-only: never register, cancel, invite, leave a team or mark notifications read against a real account.

## Adding or changing a tool

1. **Pick the group.** Tools live in `src/unstop_mcp/tools/<group>.py` (`discover`, `account`, `alerts`,
   `registration`, `teams`; sign-in and status are in `system.py`). Each group has its own instructions for the AI.
2. **Put the Unstop call in `client/`**, at the lowest layer that has what it needs:
   catalog → account/alerts → registration → teams.
3. **Return a model from `models/schemas.py`** and parse raw JSON in `models/normalize.py`. Normalisers must be
   type-safe: a missing or oddly typed field gives `None`, never an exception, and one bad record in a list is skipped.
4. **Keep private data out.** Phone numbers and other people's emails must never reach the AI. If your tool touches profiles or teams,
   extend the privacy checks in `tests/test_teams.py`.
5. **Anything that changes an account** needs the write scope, a preview the user confirms, an audit-log entry, and must
   be hidden when `UNSTOP_MCP_ENABLE_WRITE_TOOLS=false`.
6. **Test it:** a normal case with mocked responses (see `tests/conftest.py`), plus the chaos suite in
   `tests/test_chaos.py`, which runs every tool against broken responses and hostile inputs automatically.
7. **Document it** in the README tool table and in `CHANGELOG.md`.

## Style

- Plain, specific error messages that tell the user what to do next. No stack traces reach the AI.
- Small modules with one job. Each layer imports only the ones below it.
- Comments explain *why*, not *what*.

## Commits and pull requests

- One topic per pull request. Describe what changed and how you checked it.
- Commit messages: a short imperative summary line ("Fix …", "Add …"), then the reason if it isn't obvious.
- Don't commit tokens, `.env` files, session files or one-time codes.

## Releasing (maintainers)

1. Update the version in `pyproject.toml`, `src/unstop_mcp/__init__.py` and `docker-compose.yml`, and add a
   `CHANGELOG.md` entry headed `## <version> — <date>`.
2. Push to `master` and wait for CI to pass. It includes the release build.
3. Tag and push: `git tag -a v<version> -m "..." && git push origin v<version>`. The release workflow builds every
   download, publishes the GitHub release with notes taken from the changelog, and pushes the Docker image.

By contributing you agree that your contributions are licensed under the [MIT License](LICENSE).
