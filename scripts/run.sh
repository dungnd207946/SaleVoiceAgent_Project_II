#!/usr/bin/env bash
# Noble Voice Agent — dev runner
# Usage:
#   scripts/run.sh              # with hot-reload
#   scripts/run.sh --no-reload  # without hot-reload
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PYTHONPATH:-}:$(pwd)/src"
exec python -m noble_agent "$@"
