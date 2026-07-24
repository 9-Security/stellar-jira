#!/usr/bin/env bash
# (Re)create .venv and install requirements.txt. Use when upgrading Python or deps.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
if ! python3 -m venv --help &>/dev/null; then
  echo "Install: sudo apt-get install -y python3-venv python3-pip" >&2
  exit 1
fi
rm -rf "$ROOT/.venv"
python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -q --upgrade pip
"$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt"
echo "OK: $ROOT/.venv"
