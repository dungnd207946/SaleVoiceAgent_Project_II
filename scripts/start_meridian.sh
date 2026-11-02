#!/usr/bin/env bash
# Start Meridian proxy — exposes Claude Max subscription as Anthropic-compat
# API at http://127.0.0.1:3456. Requires `claude` CLI logged in and the
# @rynfar/meridian npm package installed globally.
#
# Why passthrough mode: our app owns the tool dispatcher (noble_search,
# update_customer, switch_agent, booking…). Meridian must NOT try to execute
# tools itself — it must forward tool_use blocks back to us so our orchestrator
# runs them and feeds tool_result back.
set -euo pipefail

if ! command -v meridian >/dev/null 2>&1; then
  echo "✘ meridian not installed. Run: npm install -g @rynfar/meridian" >&2
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "✘ claude CLI not installed (https://claude.com/code)" >&2
  exit 1
fi

# Auth sanity check — `claude -p` will prompt to login if no valid session.
if ! claude -p "echo ok" --max-turns 1 >/dev/null 2>&1; then
  echo "✘ claude CLI not authenticated. Run: claude /login" >&2
  exit 1
fi

export MERIDIAN_PASSTHROUGH=${MERIDIAN_PASSTHROUGH:-true}
export MERIDIAN_PORT=${MERIDIAN_PORT:-3456}
export MERIDIAN_HOST=${MERIDIAN_HOST:-127.0.0.1}

echo "→ Starting Meridian on http://${MERIDIAN_HOST}:${MERIDIAN_PORT}"
echo "  passthrough=${MERIDIAN_PASSTHROUGH}"
echo "  Claude auth: $(claude -p 'whoami' --max-turns 1 2>/dev/null | head -c 80 || echo 'unknown')"
exec meridian
