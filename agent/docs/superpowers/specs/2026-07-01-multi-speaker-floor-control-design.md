# Multi-Speaker Floor Control — Design

**Date:** 2026-07-01
**Branch:** `feat/seperate-service`
**Status:** Approved (brainstorming) → ready for implementation plan
**Builds on:** `2026-06-30-stt-noise-gate-speaker-verification-design.md` (shipped) + fast-follow `9dd07cd` (per-utterance PCM buffer `_utterance_pcm`).

## Problem

The shipped speaker feature only supports a single enrolled primary speaker
(`single` policy: drop every non-primary utterance). That is too strict for a
hotline where more than one person may legitimately talk to the agent. The user
wants a **multi-speaker** policy: multiple people may converse with the agent
turn-by-turn, but **while the agent is playing TTS, only the person who asked
the current question may interrupt** it. Once the agent finishes, the floor is
open again and any speaker may ask next. In short: *whoever asked owns the
interrupt right for that turn.*

Additional hard constraint: all speaker + gate features must be **STT-backend-
agnostic** — they must work identically whether STT is self-hosted sherpa or the
Soniox cloud API, so the operator can switch backends freely.

## Goals

- A `multi` speaker policy: turn-taking across speakers when the agent is idle;
  asker-only interrupt while the agent is speaking.
- Backend-agnostic: identity decided by **our** speaker embeddings on raw PCM
  (`SpeakerEmbedder`), never by STT-provided diarization labels (sherpa has
  none; Soniox does — using them would break sherpa parity).
- Opt-in, off by default; `off`/`single` behavior unchanged.
- All thresholds/params in `.env`.

### Non-goals

- Telephony (`TelephonySession`) — a separate pipeline that does not inherit
  `BaseSession` and lacks even the base gate/verify. Out of scope; follow-up.
- Resuming TTS mid-utterance after a mis-identified interrupt (rejected in
  brainstorming — too complex with the sentence-buffer + pacer).
- Persisting speaker identities across turns/sessions; per-turn asker only.

## Decisions (from brainstorming)

- **Mode model:** a single selector `SPEAKER_MODE = off | single | multi`
  replaces the shipped bool `SPEAKER_VERIFICATION_ENABLED` (`single` == old
  `true`). One source of truth; the three policies are mutually exclusive.
- **Interrupt mechanism (multi):** when the agent is speaking and someone talks,
  the agent **keeps talking** while we collect ~`SPEAKER_INTERRUPT_MIN_SEC` of
  the interrupter's audio and embed it. Match asker → honor the interrupt
  (barge-in, delayed by the identification window). No match → ignore (agent
  finishes; the utterance is dropped if it finalizes while the agent is still
  speaking). No immediate-pause-then-resume.

## Architecture

### Layer / transport scope

Lives entirely in `server/base_session.py` (+ a small pure helper in
`voice/speaker_verifier.py`), so **both** transports that inherit `BaseSession`
— browser aiortc (`server/session.py`) and LiveKit (`transport/livekit/
room_session.py`) — get it. Because identity is computed from raw caller PCM via
`SpeakerEmbedder`, it is backend-agnostic (works with sherpa and Soniox alike).

### Mode resolution

`config.py`: remove `speaker_verification_enabled: bool`; add
`speaker_mode: str = "off"`. A resolver (helper on the session, or
`config.resolve_speaker_mode()`) computes the effective mode:
`speaker_mode` if set to a known value; else if a legacy
`SPEAKER_VERIFICATION_ENABLED=true` is present and `speaker_mode == "off"`,
resolve to `single` and log a deprecation warning. Everything that currently
gates on `speaker_verification_enabled` (base_session `__init__`, `prewarm.py`)
switches to `mode in ("single", "multi")` for the "load model / build guard"
decision.

### Components

- **`SpeakerVerifier`** (single mode) — unchanged (enroll/verify/adapt).
- **`SpeakerFloor`** (new, pure, in `voice/speaker_verifier.py`) — per-turn asker
  identity:
  - `set_asker(emb: np.ndarray) -> None`
  - `clear_asker() -> None`
  - property `has_asker: bool`
  - `matches_asker(emb: np.ndarray, threshold: float) -> bool` (cosine ≥ threshold;
    reuse `_cosine`/`_normalize`; if no asker set → returns `False`, caller
    treats "no asker" as "floor open" separately)
  Pure vector logic, unit-testable without a model. All stateful orchestration
  (when to embed, delayed-interrupt bookkeeping) lives in `BaseSession`, which
  owns the turn/interrupt state machine.

### Multi-mode state machine (in `BaseSession`)

State the session tracks in `multi` mode:
- `self._floor: SpeakerFloor`
- `self._current_asker_emb` held inside `SpeakerFloor`.
- An interrupt-episode guard so the candidate is embedded once per episode, not
  per frame.

Wiring points:

1. **Turn start → set asker.** When an accepted utterance triggers an agent
   turn, embed its `_utterance_pcm` (the per-utterance buffer from `9dd07cd`,
   snapshotted before the `await`) via `asyncio.to_thread` and
   `floor.set_asker(emb)`. This is the same embed cost as `single`-mode verify.

2. **Agent turn done → open floor.** On the agent-done callback (`on_done`),
   `floor.clear_asker()`. Now `has_asker` is False → the next speaker is
   unconditionally accepted and becomes the new asker.

3. **Interrupt path** (`process_audio_frame`, VAD `INTERRUPTED`, `multi` mode,
   agent currently speaking): do **not** call `_handle_interrupt` immediately.
   Instead mark an interrupt episode active. The gate keeps forwarding caller
   audio to STT, so `_utterance_pcm` accumulates the interrupter's speech. Once
   `len(_utterance_pcm) >= SPEAKER_INTERRUPT_MIN_SEC * rate * 2` AND no candidate
   embed is already in flight for this episode, kick a single
   `asyncio.to_thread` embed. On result:
   - matches asker → `await self._handle_interrupt()` (barge-in honored);
     end episode. The interrupter's utterance proceeds to `_on_final` → new turn.
   - no match → end episode; set a per-utterance "suppress" flag so this
     utterance is dropped at `_on_final` if the agent is still speaking.
   If the agent finishes speaking before the candidate resolves, the episode is
   abandoned (floor now open; the utterance is treated as a normal next turn).

4. **`_on_final` gate** (`multi` mode): if the agent was speaking when this final
   arrived and the speaker does not match the asker (embed `_utterance_pcm`,
   `floor.matches_asker`) → drop (return, no trigger). Otherwise accept; if the
   floor was open, this utterance becomes the new turn/asker (handled at turn
   start, step 1).

`off` and `single` paths are unchanged: `off` → immediate `_handle_interrupt`,
no speaker work; `single` → existing `_verify_speaker` drop-non-primary.

## Configuration (`.env`)

| Var | Default | Meaning |
|---|---|---|
| `SPEAKER_MODE` | `off` | `off` \| `single` \| `multi` (replaces `SPEAKER_VERIFICATION_ENABLED`) |
| `SPEAKER_INTERRUPT_MIN_SEC` | `0.8` | (multi) interrupter audio to collect before the embed/decide |

Reused as-is: `SPEAKER_REMOTE_URL`/`_TIMEOUT`/`_TOKEN`, `SPEAKER_MODEL_*`,
`SPEAKER_HF_*`, `SPEAKER_MATCH_THRESHOLD` (also the asker-match threshold in
multi), `SPEAKER_EMBED_WINDOW_SEC`. `SPEAKER_MIN_ENROLL_SEC` /
`SPEAKER_ADAPT_*` apply to `single` only (ignored in `multi`).

Backward-compat: legacy `SPEAKER_VERIFICATION_ENABLED=true` with unset
`SPEAKER_MODE` → resolves to `single` + deprecation warning. `.env` /
`.env.example` migrate to `SPEAKER_MODE`.

## Testing

Unit — `SpeakerFloor` (no model): `set_asker`/`clear_asker`/`has_asker`;
`matches_asker` above/below threshold; no-asker → `False`.

Unit — mode resolution: `SPEAKER_MODE` values map correctly; legacy bool →
`single` with warning.

Session-wiring (base_session harness, stub embedder/floor — no real model):
- `multi` + agent idle → any speaker accepted (no gate; becomes asker).
- `multi` + agent speaking + `_on_final` non-asker → dropped (no trigger).
- `multi` + agent speaking + `_on_final` asker → accepted.
- `multi` VAD-interrupt: candidate matches asker → `_handle_interrupt` called;
  no match → `_handle_interrupt` NOT called (agent keeps speaking).
- `off`/`single` unchanged (regression guard).

Latency: `multi` adds one embed at interrupt-candidate time → asker barge-in
delayed by ~`SPEAKER_INTERRUPT_MIN_SEC` (accepted). `off`/`single` unchanged;
embeds run via `asyncio.to_thread` (never block the loop).

Backend-agnostic check: identity path uses `SpeakerEmbedder` on `_utterance_pcm`
only — no dependence on the STT backend or its `speaker` label. Confirm no
Soniox/sherpa-specific branch in the multi-mode code.

Run `src/noble_agent/SMOKE.md` (turn loop + interrupt path touched).

## CLAUDE.md updates (on implementation)

- Replace `SPEAKER_VERIFICATION_ENABLED` references with `SPEAKER_MODE`
  (`off`/`single`/`multi`); document the multi policy (asker-only interrupt,
  floor opens on agent-done), the backend-agnostic guarantee, and the
  `SPEAKER_INTERRUPT_MIN_SEC` latency trade-off.
- Note telephony is out of scope for speaker/gate features.
- Key configuration table + one Change Log row dated 2026-07-01.
