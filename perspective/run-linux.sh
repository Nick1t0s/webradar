#!/bin/sh
set -eu
REPO_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$REPO_DIR"
if [ -n "${PYTHON:-}" ]; then
    PYTHON_BIN="$PYTHON"
elif [ -x "$REPO_DIR/helper/linux/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_DIR/helper/linux/.venv/bin/python"
else
    PYTHON_BIN=python3
fi
exec "$PYTHON_BIN" -m perspective
