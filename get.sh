#!/usr/bin/env sh
# Unstop MCP one-line installer for macOS / Linux:
#   curl -LsSf https://raw.githubusercontent.com/vinoth322006/unstop-mcp-server/master/get.sh | sh
# Uses uv if available, else pipx, else pip --user. Then runs the guided setup.
set -eu
REPO="${UNSTOP_MCP_REPO:-vinoth322006/unstop-mcp-server}"
REF="${UNSTOP_MCP_REF:-main}"
SPEC="git+https://github.com/${REPO}@${REF}"

say() { printf '  > %s\n' "$1"; }

printf '\nInstalling Unstop MCP\n'
if command -v uv >/dev/null 2>&1; then
  say "Installing with uv"
  uv tool install --force --python 3.12 "unstop-mcp @ ${SPEC}"
  uv tool update-shell >/dev/null 2>&1 || true
elif command -v pipx >/dev/null 2>&1; then
  say "Installing with pipx"
  pipx install --force "${SPEC}"
  pipx ensurepath >/dev/null 2>&1 || true
else
  PY=""
  for c in python3.13 python3.12 python3.11 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then PY="$c"; break; fi
  done
  if [ -z "$PY" ]; then
    echo "Python 3.11+ is required (or install uv: https://docs.astral.sh/uv/)." >&2
    exit 1
  fi
  say "Installing with pip --user"
  "$PY" -m pip install --user --upgrade "${SPEC}"
fi

BIN="$(command -v unstop-mcp || true)"
[ -z "$BIN" ] && [ -x "$HOME/.local/bin/unstop-mcp" ] && BIN="$HOME/.local/bin/unstop-mcp"
if [ -z "$BIN" ]; then
  echo "Installed, but unstop-mcp is not on PATH yet. Open a new terminal and run: unstop-mcp setup"
  exit 0
fi
exec "$BIN" setup
