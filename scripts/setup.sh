#!/usr/bin/env bash
# Quick setup — create venv + install deps + prepare .env.
# Run once from the project root.
set -e
cd "$(dirname "$0")/.."

PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON="$candidate"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    echo "ERROR: Python 3.10+ not found. Install with: brew install python@3.12"
    exit 1
fi

echo "=== Noble Voice Agent — setup ==="
echo "Using $PYTHON ($($PYTHON --version))"

if [ ! -d ".venv" ]; then
    echo "[1/2] Creating venv..."
    $PYTHON -m venv .venv
else
    echo "[1/2] Venv exists, reusing."
fi

source .venv/bin/activate

echo "[2/2] Installing dependencies..."
bash scripts/install.sh

echo ""
echo "Activate: source .venv/bin/activate"
echo "Run:      noble-agent"
