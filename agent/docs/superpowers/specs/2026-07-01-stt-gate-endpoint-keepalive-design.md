# STT Gate ↔ Endpoint Keepalive — Design

**Date:** 2026-07-01
**Branch:** `feat/seperate-service`
**Status:** Approved (brainstorming) → ready for implementation plan
**Builds on:** `2026-06-30-stt-noise-gate-speaker-verification-design.md` (shipped `SttInputGate`).

## Problem

The STT input gate (`STT_INPUT_GATE_MODE=rms|vad`) withholds caller-audio
frames from the STT engine while it judges them non-speech. When the caller
stops talking, the gate closes and stops forwarding the **trailing silence**.

But sherpa (local and via the resident remote service) finalizes an utterance
only when `recognizer.is_endpoint()` is True, and that endpoint fires only
after ~1.2s of *continuous trailing silence* fed to the recognizer
(`rule2_min_trailing_silence`, `voice/stt/sherpa.py`). The decode loop only
re-checks `is_endpoint()` after receiving a new audio chunk. So when the gate
withholds the trailing silence, the recognizer never sees the silence, the
endpoint never fires, no `final` is emitted, and `_on_final` is never called →
**partials stream correctly but nothing is ever submitted to the agent.**

Evidence (worker session metrics on disconnect): `guard.frames_gated_bytes
count=3359` over a 35.7s call — ~96% of audio gated — with zero
`Final transcript` events. The metric is recorded only when the gate returns
an empty chunk list, which never happens in `off` mode; so the running worker
had the gate enabled, confirming the mechanism.

This is a latent design conflict: **any gate mode other than `off` breaks
endpoint-based finalization.** With `off` the gate forwards everything
(including trailing silence) and finalization works.

## Goals

- Make `rms` and `vad` gate modes usable: STT still finalizes utterances.
- **Preserve today's finalization timing** — do not change *when* a final
  fires. The endpoint keeps firing at its normal ~1.2s trailing-silence point.
- **Backend-agnostic** with **no protocol / `STTBase` interface change**:
  identical behavior for local sherpa, remote(sherpa), and Soniox.
- Preserve the gate's noise-blocking purpose: real (noisy) trailing audio is
  still blocked; only clean synthetic silence reaches STT.
- Opt-in surface unchanged: `off` mode behavior is byte-for-byte identical.

### Non-goals

- Changing finalization latency (rejected approach A — explicit `finalize()`
  on gate-close). The user chose to keep timing identical.
- Forwarding real trailing audio to the recognizer (rejected approach C —
  extended hangover — re-admits background noise / other speakers).
- Telephony (`TelephonySession`): a separate pipeline that does not inherit
  `BaseSession` and has no gate. Out of scope, consistent with the gate/speaker
  features being `base_session`-only.

## Decision (from brainstorming)

**B2 — "silence keepalive" during gate-close.** When the gate withholds a
frame *and* an utterance is still pending (real audio was forwarded since the
last final), the worker feeds a synthetic silence frame (zeros, same byte
length) to STT instead of forwarding nothing. One silence frame per incoming
frame, at real-time rate, so the recognizer sees a continuous trailing-silence
stream and its endpoint fires at the normal ~1.2s. Injection stops on the next
`final` (utterance done) or at a safety cap (long idle silence).

Zeros are just PCM bytes: local sherpa consumes them directly; remote(sherpa)
receives them over the existing binary WS frame → the service's recognizer
endpoints and returns `FINAL`; Soniox endpoints on silence too. No new control
message, no `STTBase` method.

## Architecture

### Layer / scope

All keepalive state lives in `SttInputGate` (pure, unit-testable without a
model or a session). `BaseSession.process_audio_frame` wires it: on an empty
gate result it asks the gate for a keepalive frame and forwards it to STT.
Because `BaseSession` is shared by browser aiortc (`server/session.py`) and
LiveKit (`transport/livekit/room_session.py`), both transports get the fix.

### `SttInputGate` changes (`voice/stt_input_gate.py`)

The `gate(data) -> list[bytes]` signature is unchanged. Add:

- **State:** `_pending: bool = False` (real audio forwarded since the last
  final), `_keepalive_bytes: int = 0`, and constructor param
  `keepalive_max_bytes: int = 0` (0 → keepalive disabled).
- In `gate(data)`, on the **active** branch (real audio is being forwarded):
  set `_pending = True` and reset `_keepalive_bytes = 0`.
- **`keepalive(frame_len: int) -> bytes | None`:** if `_pending` and
  `_keepalive_bytes < keepalive_max_bytes`, increment `_keepalive_bytes` by
  `frame_len` and return `bytes(frame_len)` (a zero-filled silence frame);
  otherwise return `None`.
- **`notify_final() -> None`:** `_pending = False; _keepalive_bytes = 0`.
- **`from_settings`:** `keepalive_max_bytes = int(settings.stt_gate_keepalive_max_sec
  * settings.stt_sample_rate * 2)`.

`off` mode: `gate()` never returns empty, so `BaseSession` never calls
`keepalive()` → behavior byte-for-byte identical to today. `_pending` may be
set but is never read in `off`.

### `BaseSession` wiring (`server/base_session.py`)

In `process_audio_frame`, the empty-chunk branch (currently only records the
metric) additionally requests and forwards a keepalive frame:

```python
if not chunks:
    self.metrics.record_latency("guard", "frames_gated_bytes", len(data))
    s = self._input_gate.keepalive(len(data))
    if s is not None:
        await self.stt.send(s)
```

The silence frame goes straight to `stt.send`. It does **not** enter the
`for chunk in chunks` loop, so it never touches `_utterance_pcm` (the speaker
embedding buffer) or `_stt_audio_start`.

In `_on_final`, immediately after the metric-reset block and **before** any
drop gate (hallucination / echo / speaker), call
`self._input_gate.notify_final()`. This stops keepalive whenever STT emits a
final, even one that is later dropped, because the utterance has ended.

### Data flow (one utterance, gate = vad/rms)

```
caller speaks → gate active → real chunks → stt.send  (_pending=True)
                                          → _utterance_pcm extends
caller stops  → gate closed → keepalive() → silence frame → stt.send
                (repeats per incoming frame, real-time)
              → recognizer sees ~1.2s trailing silence
              → is_endpoint() True → FINAL → _on_final
              → notify_final() (_pending=False) → keepalive stops
```

## Configuration (`.env`)

| Var | Default | Meaning |
|---|---|---|
| `STT_GATE_KEEPALIVE_MAX_SEC` | `2.0` | Max synthetic silence fed after a pending utterance before giving up (safety cap for long idle). Covers the ~1.2s endpoint + margin. |

`stt_gate_keepalive_max_sec: float = 2.0` in `config.py` (`UnifiedSettings`).
Documented in `.env` / `.env.example` near the existing `STT_INPUT_GATE_*`
block.

## Edge cases

- **No speaker-embedding pollution:** injected silence bypasses the real-chunk
  loop, so `_utterance_pcm` never contains zeros.
- **Unbounded idle silence:** the `keepalive_max_bytes` cap stops injection
  after ~2.0s if no final ever arrives (e.g., empty-text utterance). Speaking
  again resets `_pending` and the counter.
- **Async race (remote):** a few extra silence frames may be sent between the
  endpoint firing and `on_final` arriving over the WS. Harmless — post-reset
  silence produces no tokens, no extra final; also bounded by the cap.
- **multi-speaker mode:** keepalive lets a barge-in utterance finalize; the
  existing `_on_final` asker gate then decides accept/drop. No interaction.
- **`off` mode:** keepalive path is never reached.

## Testing

Unit — `SttInputGate` (pure, no model, no session):
- `keepalive` returns a zero-filled frame of the requested length while
  pending and under the cap.
- `keepalive` returns `None` when not pending (fresh gate).
- `keepalive` returns `None` after `notify_final()`.
- `keepalive` returns `None` after the `keepalive_max_bytes` cap is reached.
- returned silence is all-zero and exactly `frame_len` bytes.
- `off` mode: `gate()` always returns a non-empty list (keepalive never
  invoked by the caller).

Session-wiring (`base_session` harness, stub STT recording sends):
- gate in `rms`/`vad`: after real speech frames then silence frames, the stub
  STT receives zero-filled keepalive frames.
- `_utterance_pcm` contains only the real speech bytes, none of the zeros.
- `_on_final` calls `input_gate.notify_final()`.

Config default: `stt_gate_keepalive_max_sec == 2.0`
(assert on `UnifiedSettings.model_fields[...].default`, env-independent).

Regression: run `src/noble_agent/SMOKE.md` (turn loop + STT path touched).

## CLAUDE.md updates (on implementation)

- In the STT backends section, document that `rms`/`vad` gate modes now feed
  synthetic silence (`STT_GATE_KEEPALIVE_MAX_SEC`) so the recognizer's
  endpoint still fires — timing unchanged, real noise still blocked, backend-
  agnostic (no protocol change).
- Add `STT_GATE_KEEPALIVE_MAX_SEC` to the key-configuration table.
- One Change Log row dated 2026-07-01.
