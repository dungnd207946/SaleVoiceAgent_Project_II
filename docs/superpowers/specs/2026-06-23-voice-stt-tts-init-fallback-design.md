# Design: Init-time fallback for voice STT & TTS

**Date:** 2026-06-23
**Status:** Approved (brainstorming → spec)

## Goal

Make the voice pipeline resilient at startup: if the configured primary backend
cannot be brought up, automatically fall through to the next backend in a fixed
order instead of failing silent.

- **STT** order: `sherpa → soniox`
- **TTS** order: `vieneu → elevenlabs`

`.env` is unchanged: `STT_BACKEND=sherpa`, `TTS_BACKEND=vieneu` remain the
primaries (head of each chain). No new env vars — the fallback chains are code
constants.

## Semantics (confirmed with user)

- **Init-time only.** Fallback triggers when a backend fails to *construct / start*
  (missing optional dep, model-load error, connect/auth failure). A backend that
  starts healthy but later mis-hears or dies mid-call does NOT trigger fallback
  (explicitly out of scope).
- **Effective order = `[configured] + [rest of chain in documented order]`**, dedup
  preserving order. So `STT_BACKEND=sherpa` → `[sherpa, soniox]`;
  `TTS_BACKEND=vieneu` → `[vieneu, elevenlabs]`. If the operator changes the env
  primary, it stays the head and the rest of the chain follows.
- The first backend that comes up is used for the **whole session**.
- A fallback backend missing its API key fails at `start()` like any other failure;
  if every backend in the chain fails, STT ends as `None` and the existing
  "STT failed" client callback fires **exactly once** (only when the chain is
  exhausted).

## Current code (verified)

- **STT:** `server/base_session.py::_init_stt()` (≈ lines 172-204) — an `if/elif`
  on `settings.stt_backend` constructs the backend, then `await self.stt.start()`
  inside a `try`; on exception logs, sends an error callback, sets `self.stt = None`.
  Branches: `soniox | qwen3asr | elevenlabs | else→sherpa`.
- **TTS:** `voice/voice_agent.py::_create_tts()` — static, sync; `if tts_backend ==
  "elevenlabs"` → `AsyncElevenLabsTTS()` else `AsyncVieNeuTTS()`. `AsyncVieNeuTTS()`
  construction eagerly loads the model (`_load_tts`), so a load failure raises at
  construct time → catchable for fallback.

## Architecture

### Pure helper (testable, no I/O)
`resolve_order(configured: str, chain: list[str]) -> list[str]`:
- if `configured` **not in** `chain` → return `[configured]` (no auto-fallback —
  non-chain primaries like `qwen3asr` behave exactly as today);
- else → return `[configured]` followed by the other chain members in documented
  order.

Lives next to its use (or one shared small util). Unit-tested in isolation.

Chain constants:
- `STT_FALLBACK_CHAIN = ["sherpa", "soniox"]`
- `TTS_FALLBACK_CHAIN = ["vieneu", "elevenlabs"]`

### STT — `_init_stt` rewrite
1. Build a `{name: builder}` map where each builder constructs the corresponding
   STT instance (lifting the existing `if/elif` bodies verbatim into small
   closures/functions; `on_partial`/`on_final` wired the same).
2. For each name in `resolve_order(settings.stt_backend, STT_FALLBACK_CHAIN)`
   (a non-chain primary like `qwen3asr` yields a single-element order → behavior
   unchanged):
   - `stt = builder()`, `await stt.start()`. On success: set `self.stt`, log
     (note fallback if name ≠ primary), stop.
   - On exception: log a warning, continue to the next name.
3. If the loop exhausts without success: `self.stt = None`, fire the existing
   "STT (chain) failed" client error callback once.

### TTS — `_create_tts` rewrite
1. `{name: builder}` map: `vieneu → AsyncVieNeuTTS`, `elevenlabs → AsyncElevenLabsTTS`.
2. Loop `resolve_order(settings.tts_backend, TTS_FALLBACK_CHAIN)`; return the first
   `builder()` that constructs without raising; log the chosen backend (note
   fallback if ≠ primary).
3. If all raise: re-raise the last exception (TTS is required for a voice session;
   there is no silent-None equivalent — surfacing the error is correct).

## Testing

- **Unit `resolve_order`:** `("sherpa", stt_chain)→["sherpa","soniox"]`;
  `("vieneu", tts_chain)→["vieneu","elevenlabs"]`; `("soniox", stt_chain)→["soniox","sherpa"]`
  (configured stays head); `("qwen3asr", stt_chain)→["qwen3asr"]` (not in chain → single).
- **STT fallback:** inject builders via the map; sherpa builder's `start()` raises →
  assert soniox selected and `self.stt` is the soniox instance; both raise → `stt is
  None` and the error callback fired exactly once. (Extract the loop into a testable
  unit so `base_session` heavy deps aren't needed — e.g. an
  `async def _start_first_available(order, builders, on_exhausted)` helper.)
- **TTS seam:** patch the vieneu builder to raise → `_create_tts()` returns
  `AsyncElevenLabsTTS`; vieneu OK → returns `AsyncVieNeuTTS`; both raise → raises.
- Follow `testing-conventions` (pytest `asyncio_mode=auto`, mock heavy backends,
  no live services in unit tests, ruff clean).

## Out of scope
- Runtime / mid-session fallback (health-monitoring, switching after a started
  backend dies). Init/start failures only.
- New env vars or per-deployment chain configuration.
- Other backends (`qwen3asr`, `elevenlabs`-STT) remain selectable via `STT_BACKEND`
  but are not part of the automatic chain.
- Smart Turn / VAD / resample / LLM layers — unchanged.

## Docs
Update `CLAUDE.md` (STT/TTS backend bullets note the init-time fallback chains) +
a Change Log row.
