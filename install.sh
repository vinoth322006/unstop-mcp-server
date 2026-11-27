#!/usr/bin/env sh
# Unstop MCP installer for macOS / Linux.   Run from the project folder:  sh install.sh
set -eu
cd "$(dirname "$0")"

PY=""
for cand in python3.13 python3.12 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is required: https://www.python.org/downloads/" >&2
  exit 1
fi

echo "Installing Unstop MCP..."
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet .
echo "Installed."
exec .venv/bin/unstop-mcp setup
