# STT Noise Gate + Speaker Verification — Design

**Date:** 2026-06-30
**Branch:** `feat/seperate-service`
**Status:** Approved (brainstorming) → ready for implementation plan

## Problem

The STT path sometimes emits spurious / garbage transcripts when the caller is
not speaking. Two distinct failure modes:

1. **Noise → garbage text.** With no VAD/energy gate on the STT input (the energy
   gate `audio_guard_frames_gate_enabled` defaults to `false`), the streaming
   Zipformer recognizer continuously decodes silence and background noise and
   hallucinates tokens. The only downstream defense is `WhisperHallucinationFilter`,
   a *static phrase blocklist* that misses novel hallucinations — hence the
   "thỉnh thoảng" (intermittent) nature.
2. **Other speakers in a noisy environment.** On a single mono channel, another
   person's speech is valid speech — energy/VAD gating cannot reject it. When the
   caller is silent but a background talker is the loudest source, any energy
   heuristic self-triggers on the wrong voice.

### Root cause (verified)

- `server/base_session.py::process_audio_frame` feeds **every** chunk to
  `stt.send(data)` unless `_frames_gate` (off by default) drops it. The Silero
  VAD that runs there is used **only** for interrupt detection, not to gate STT
  input.
- `voice/stt/sherpa.py` decodes every chunk; on `is_endpoint` it emits
  `on_final(text)` regardless of whether the audio was speech.
- `_on_final` guards are `WhisperHallucinationFilter` (static list) +
  `EchoCooldown` (only blocks during/after TTS). Neither rejects a novel
  hallucination nor a different speaker.

## Goals

- **Problem 1:** stop noise/silence from being transcribed, transport-agnostic
  (works for browser WebRTC, telephony, LiveKit — must live in the shared
  `base_session`/`voice` layer). Selectable gate strategy + recover the lead-in
  audio the gate would otherwise clip.
- **Problem 2:** reject transcripts that don't come from the enrolled primary
  caller, via speaker verification, behind a master flag, defaulting to a remote
  embedding service (with a local fallback) — mirroring the existing
  remote/local backend pattern.
- All flags, thresholds and tuning parameters live in `.env` so the operator can
  find the optimal operating point without code changes.

### Non-goals

- No new heavy ML dependency (reuse `sherpa-onnx`, already present).
- No multi-speaker diarization / multi-party transcription.
- No mid-call re-enrollment of a new primary speaker (v1 enrolls once).
- No new output filter beyond what exists — sherpa `enable_endpoint_detection`
  + `WhisperHallucinationFilter` remain the output layer unchanged.

## Decisions (from brainstorming)

- Problem 1 = **A3 defense-in-depth**, input-gate flavored: an input gate with a
  **selectable mode** (`off` | `rms` | `vad`) + a shared **pre-roll** buffer.
  Output layer unchanged (endpoint detection + hallucination filter).
- Problem 2 = **B1 sherpa `SpeakerEmbeddingExtractor`**, coded with a
  remote/local switch like `gender_detector`, **defaulting to remote**.
- Error tolerance = **balanced** (tune thresholds empirically; no hard bias).

---

## Design

### Part 1 — Input gate (Problem 1)

A single config selects the strategy; all modes funnel through one shared
send-with-pre-roll block so the K-chunk lookback applies uniformly.

`STT_INPUT_GATE_MODE ∈ {off, rms, vad}`

- **off** — passthrough; identical to today's behavior. Code default (safe).
- **rms** — `ConsecutiveFramesGate` (energy: N consecutive 20 ms frames ≥ RMS
  threshold). Cheap. Replaces the old `audio_guard_frames_gate_enabled=true`.
- **vad** — gate on Silero `is_speech` (reuses the inference already run for
  interrupts — the VAD model is **not** run twice) plus a hangover so word-final
  consonants and short pauses are not clipped.

**Pre-roll** (`AUDIO_GATE_PREROLL_CHUNKS = K`): a `collections.deque(maxlen=K)`
holds the most recent chunks withheld while the gate is *not* active. On the
**rising edge** (gate inactive → active) the deque is drained into STT *before*
the current chunk, recovering ~K×chunk of lead-in. `K=0` disables pre-roll.

`process_audio_frame` restructure (order: VAD first so the vad-gate flag is fresh):

```python
# 1) Update VAD (serves BOTH interrupt detection AND the vad-gate flag)
self._vad_buf += data
while len(self._vad_buf) >= VAD_CHUNK_BYTES:
    chunk = self._vad_buf[:VAD_CHUNK_BYTES]; self._vad_buf = self._vad_buf[VAD_CHUNK_BYTES:]
    r = self.vad.process_chunk(chunk)
    self._update_vad_gate(r)                 # _vad_gate_active + hangover countdown
    if r["state"] == VADState.INTERRUPTED:
        await self._handle_interrupt()

# 2) Gate STT input (shared pre-roll path)
if self.stt:
    active = self._stt_gate_decision(data)   # off→True | rms→frames_gate.confirmed | vad→_vad_gate_active
    if active:
        if not self._gate_was_active:        # rising edge
            for c in self._preroll:
                await self.stt.send(c)
            self._preroll.clear()
            self._stt_audio_start = time.monotonic()   # TTFA anchor at utterance start
        await self.stt.send(data)
    else:
        self._preroll.append(data)
    self._gate_was_active = active

self._audio_ring_append(data)
```

Helpers:

```python
def _stt_gate_decision(self, data: bytes) -> bool:
    mode = settings.stt_input_gate_mode
    if mode == "off":
        return True
    if mode == "rms":
        self._frames_gate.feed(data)         # frames_gate constructed only in rms mode
        return self._frames_gate.confirmed
    if mode == "vad":
        return self._vad_gate_active
    return True                              # unknown → fail open (safe)

def _update_vad_gate(self, r: dict) -> None:
    if r["is_speech"]:
        self._vad_gate_active = True
        self._vad_hangover_left = self._vad_hangover_chunks
    elif self._vad_hangover_left > 0:
        self._vad_hangover_left -= 1
    else:
        self._vad_gate_active = False
```

- `_vad_hangover_chunks = ceil(STT_VAD_GATE_HANGOVER_MS / vad_chunk_ms)`.
- The Silero interrupt state machine is **untouched**; the gate reads only the
  raw `is_speech` decision.
- `ConsecutiveFramesGate.__init__` now takes `min_rms`, `required_consecutive`,
  `barge_in_rms` from config (currently module constants).
- The old boolean `audio_guard_frames_gate_enabled` is **removed**; `rms` mode is
  its replacement.

### Part 2 — Speaker verification (Problem 2)

New module `voice/speaker_verifier.py`, modeled on `voice/gender_detector.py`:

- **`SpeakerEmbedder` (singleton)** — `embed(pcm16: bytes) -> np.ndarray`.
  - Remote (default when `SPEAKER_REMOTE_URL` set): httpx POST PCM → JSON
    embedding (mirrors `gender_detector` remote mode; optional bearer via
    `SPEAKER_REMOTE_TOKEN`).
  - Local: `sherpa_onnx.SpeakerEmbeddingExtractor` over an ONNX model in
    `SPEAKER_MODEL_DIR`, self-provisioned from `SPEAKER_HF_REPO@SPEAKER_HF_REVISION`
    (reuse the `sherpa.py::_ensure_model_present` pattern).
- **`SpeakerVerifier` (per session)** — holds the enrolled `centroid`:
  - `enroll(emb)` — set centroid (first valid utterance).
  - `verify(emb) -> (ok: bool, sim: float)` — cosine vs centroid;
    `ok = sim >= SPEAKER_MATCH_THRESHOLD`.
  - `maybe_adapt(emb)` — if `SPEAKER_ADAPT_ENABLED`, running-mean update
    `centroid = normalize((1-w)·centroid + w·emb)`, `w = SPEAKER_ADAPT_WEIGHT`.

Wiring in `_on_final` (inserted **after** echo-cooldown, **before** smart_turn):

```python
if self._speaker_verifier is not None:
    window = int(settings.speaker_embed_window_sec * settings.stt_sample_rate) * 2
    seg = bytes(self._audio_ring[-window:])
    dur_ok = self._utterance_duration() >= settings.speaker_min_enroll_sec
    emb = await asyncio.to_thread(_embedder.embed, seg)   # ONNX off the event loop
    if not self._speaker_verifier.enrolled:
        if dur_ok:
            self._speaker_verifier.enroll(emb)            # anchor on first valid utterance
        # first utterance always passes (nothing to compare against)
    else:
        ok, sim = self._speaker_verifier.verify(emb)
        logger.info("[Speaker] sim=%.3f thr=%.2f ok=%s", sim, settings.speaker_match_threshold, ok)
        if not ok:
            return                                        # drop — different speaker
        self._speaker_verifier.maybe_adapt(emb)
```

- Master flag `SPEAKER_VERIFICATION_ENABLED` (default `false`). When off,
  `self._speaker_verifier is None` and the block is skipped entirely (zero cost).
- Embedding runs in a worker thread → does not block the event loop. Adds
  ~20–40 ms to TTFA per turn **only when enabled**.
- **Known risk (accepted for v1):** if a background speaker talks before the
  caller, enrollment anchors on the wrong voice. Mitigated only by the
  `SPEAKER_MIN_ENROLL_SEC` minimum-duration guard. Documented, not solved.

Remote service: thin `voice/service/speaker_server.py` + console script
`noble-speaker-service`, mirroring `voice/service/{stt_server,tts_server}.py`,
so the embedder can be split onto a separate (GPU) host. Wraps the same
`SpeakerEmbedder` local singleton; HTTP/WS contract = PCM in → embedding out.

### Prewarm

`voice/prewarm.py::prewarm_voice_models()` eagerly loads the local speaker model
once at boot when `SPEAKER_VERIFICATION_ENABLED` and **not** remote (gated like
the sherpa/vieneu prewarm; failure logs and boot continues).

---

## Configuration (`.env`)

### Problem 1 — input gate

| Var | Default | Meaning |
|---|---|---|
| `STT_INPUT_GATE_MODE` | `off` | `off` \| `rms` \| `vad` |
| `AUDIO_GATE_PREROLL_CHUNKS` | `3` | K chunk lookback (all modes); 0 = off |
| `AUDIO_GATE_MIN_RMS` | `160` | (rms) per-frame energy threshold |
| `AUDIO_GATE_REQUIRED_CONSECUTIVE` | `3` | (rms) consecutive frames to confirm |
| `AUDIO_GATE_BARGE_IN_RMS` | `2400` | (rms) high-energy barge-in threshold |
| `STT_VAD_GATE_HANGOVER_MS` | `300` | (vad) keep gate open after speech ends |

### Problem 2 — speaker verification

| Var | Default | Meaning |
|---|---|---|
| `SPEAKER_VERIFICATION_ENABLED` | `false` | master opt-in |
| `SPEAKER_REMOTE_URL` | (set in `.env`) | non-empty → remote (default); empty → local |
| `SPEAKER_REMOTE_TIMEOUT` | `3.0` | remote client timeout (s) |
| `SPEAKER_REMOTE_TOKEN` | empty | optional bearer for remote |
| `SPEAKER_MODEL_DIR` | `models/speaker` | (local) ONNX dir |
| `SPEAKER_HF_REPO` | (chosen in plan) | (local) HF repo for self-provision — candidate: a sherpa-onnx 3D-Speaker / wespeaker embedding ONNX (language-agnostic); final model selection is a planning task |
| `SPEAKER_HF_REVISION` | `prod` | (local) pinned revision |
| `SPEAKER_MATCH_THRESHOLD` | `0.5` | min cosine to accept as same speaker |
| `SPEAKER_MIN_ENROLL_SEC` | `1.0` | min utterance length to enroll |
| `SPEAKER_EMBED_WINDOW_SEC` | `3.0` | trailing audio from `_audio_ring` to embed |
| `SPEAKER_ADAPT_ENABLED` | `false` | running-mean centroid update |
| `SPEAKER_ADAPT_WEIGHT` | `0.1` | adapt weight |

---

## Testing

Unit (`tests/unit/`, no real model):

- Gate decisions per mode (off/rms/vad) via injected/faked signals.
- **Pre-roll: rising edge drains exactly K withheld chunks before the current
  chunk; deque respects `maxlen`; resets to refill after a silence reset.**
- `_stt_gate_decision` dispatch on `STT_INPUT_GATE_MODE`.
- `_update_vad_gate` hangover countdown.
- `SpeakerVerifier` enroll → verify → adapt with synthetic embeddings: first
  utterance passes; cosine below threshold drops; adapt moves the centroid.

Integration / model-gated (marked `needs model`, not in unit run):

- Local sherpa embedder loads + embeds; remote client round-trip.

Latency:

- `make bench` before/after; confirm `off` mode is a no-op and speaker verify
  cost is incurred only when enabled (thread-offloaded).

Run `src/noble_agent/SMOKE.md` — change touches the turn loop / audio pipeline.

---

## CLAUDE.md updates (on implementation)

- Backends/STT section: document `STT_INPUT_GATE_MODE` + pre-roll and that the
  Silero VAD now also (optionally) gates STT input, not just interrupts.
- New "Speaker verification" subsection (remote/local, enroll-once, flag).
- Change Log row.
- Add the new env vars to the Key configuration table.
