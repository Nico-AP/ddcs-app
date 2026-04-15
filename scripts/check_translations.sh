#!/usr/bin/env bash
set -euo pipefail

# Resolve Python from the venv (Unix or Windows layout) or fall back to PATH.
if [ -f ".venv/bin/python" ]; then
    PYTHON=".venv/bin/python"
elif [ -f ".venv/Scripts/python.exe" ]; then
    PYTHON=".venv/Scripts/python.exe"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "ERROR: No Python interpreter found. Create a virtual environment at .venv or ensure python3 is on PATH." >&2
    exit 1
fi

$PYTHON manage.py makemessages -l de --no-obsolete
git diff --exit-code locale/
