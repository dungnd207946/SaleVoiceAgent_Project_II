# Gateway Static Tester — Design

**Date:** 2026-08-06
**Branch:** feat/share-agent
**Status:** approved (design), pending implementation plan

## Goal

A standalone static test tool ("provider client simulator") that lets a human
test the **chat** and **voice** features through the multi-tenant **gateway**,
by entering a **Gateway host URL + Bearer token** (the browser equivalent of
`scripts/e2e_dbmode/chat_via_gateway.py`). Behavior and look mirror the current
`static/chat.html` / `static/livekit.html` as far as the gateway path allows.

Non-goals: no agent logic, no proxying, no changes to `src/noble_agent/`, no
changes to the existing `static/` pages. The tool is pure frontend + a trivial
static file server; it only connects *out* to whatever gateway URL is pasted in.

## Context (verified against the code)

- Gateway (`src/noble_agent/gateway/server.py`) exposes two WS routes:
  - `/v1/chat` → `authorize` → reverse-proxy to the tenant worker's `/chat`.
  - `/v1/stream` → `authorize` → `_bridge_voice`: joins the tenant LiveKit room
    as a participant and relays audio both ways.
- **Auth:** tenant is resolved from the **Host subdomain** (e.g. `acme.lvh.me`
  with `GATEWAY_BASE_DOMAIN=lvh.me` → tenant `acme`). Bearer comes from the
  `Authorization` header **or**, when absent, from a `?key=` / `?token=` query
  param (`_extract_request`). Browsers cannot set `Authorization` on a WS, so the
  tester uses `?key=`.
- **Handshake:** after authorize, the gateway waits (timeout `_HANDSHAKE_TIMEOUT_SEC`)
  for one JSON frame `{identity, call_id}` before running the per-route protocol.
- **Chat protocol** (already handled by `static/chat.html` gateway-mode): client
  sends `{type:"user_text", text, tts?}`; server streams `session_id`, `token`,
  `tool_start`, `done`, `items[]`, etc.
- **Voice protocol** (`_bridge_voice`): **binary frames = raw PCM16 @ 16 kHz mono**
  both directions; text frames from the client are **ignored** ("reserved").
  The bridge pumps only the agent **audio** track back (`_pump_agent_audio` sends
  `event.frame.data` bytes). **No data-channel relay** → no media `items[]`, no
  transcript on the voice path.

## Architecture & layout

Self-contained directory, imports nothing from `noble_agent`, does not touch
`static/`:

```
tools/gateway-tester/
├── chat.html      # copy of static/chat.html shell, forced gateway-mode
├── voice.html     # copy of static/livekit.html shell, transport = PCM-over-WS
├── serve.py       # ~20-line stdlib static server, own port (default 9300)
└── README.md      # how to run + meaning of each input + acceptance checklist
```

Each HTML stays **single-file** (inline CSS/JS) like the originals, so the look
is preserved and pages can be opened independently.

## Component 1 — Connection bar (shared by both pages)

Inputs, persisted to `localStorage` for quick re-testing:

- **Gateway host** — e.g. `wss://acme.lvh.me`. Tenant = the subdomain. The page
  appends the path per feature: chat → `/v1/chat`, voice → `/v1/stream`.
- **Bearer token** — sent as `?key=<token>` on the WS URL.
- **Identity** (optional: name / phone / …) — folded into the handshake frame
  `{identity, call_id}`; `call_id` = a random session id. Reuse the identity
  sheet already present in `static/chat.html`.

## Component 2 — Chat page

Copy `static/chat.html`, **remove the local `/chat/ws` fallback branch**, always
gateway-mode:

1. Connect `wss://<host>/v1/chat?key=<token>`.
2. Send `{identity, call_id}` handshake frame.
3. Run the existing chat protocol **unchanged**: `session_id` → enable input;
   `{type:"user_text", text}` on send; render streamed `token`, `tool_start`,
   `done`, and `items[]` media/chips exactly as the current page does.

## Component 3 — Voice page

Keep the **visual shell** of `static/livekit.html` (idle → call screen, Mic /
Speaker / End controls, waveform, timer). **Replace the transport** (drop the
LiveKit SDK + `/livekit/token` fetch):

1. "Call" → open `wss://<host>/v1/stream?key=<token>`; send `{identity, call_id}`.
2. **Mic uplink:** `getUserMedia` → AudioWorklet → downsample to **16 kHz mono
   Int16 PCM** → `ws.send(<binary>)`.
3. **Agent downlink:** receive binary → interpret as PCM16 → play via AudioContext.

**Accepted constraints (gateway-imposed, not fixable in frontend):**

1. **Audio-only** — no media cards / transcript on the voice path (bridge relays
   only audio, ignores text/data).
2. **Downlink sample rate is not declared** by the gateway (raw bytes). We pin a
   constant (start by ear; adjust if pitch is wrong — expected 24 kHz or 48 kHz).
   Uplink is fixed at 16 kHz (bridge hardcodes it).

## Component 4 — Static server & run

`serve.py`: stdlib `http.server` bound to `127.0.0.1:9300` (localhost is a secure
context, so mic capture works). Serves the `tools/gateway-tester/` dir.

Run:
```
python tools/gateway-tester/serve.py
# open http://localhost:9300/chat.html  or  /voice.html
```
No agent needs to run alongside — only the target gateway must be reachable.

## Acceptance

- **Chat:** paste acme host + token → ask one question → observe streamed
  `token`s + `done` (parity with `chat_via_gateway.py`).
- **Voice:** call → speak → hear the agent reply (two-way audio).
- Record both as a checklist in `README.md`.

## Risks / open items

- Voice downlink sample-rate constant is empirical; may need one tweak after a
  live listen. Documented as expected, not a blocker.
- The voice path depends on a live LiveKit server + a registered worker for the
  tenant (integration-level, same prerequisite as `SMOKE.md` voice).
