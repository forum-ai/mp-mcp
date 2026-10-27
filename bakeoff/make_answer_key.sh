#!/usr/bin/env bash
# Build a local venv with mp-api inside this folder (first run only) and compute answer_key.md.
# Needs MP_API_KEY exported in your shell; the key is read from the environment and never written to disk.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"
if [ ! -x "$HERE/.venv/bin/python" ]; then
  uv venv -q --python 3.12 "$HERE/.venv"
  VIRTUAL_ENV="$HERE/.venv" uv pip install -q mp-api
fi
"$HERE/.venv/bin/python" -I "$HERE/answer_key.py"
