# 03 — TTS + Audio I/O

> Output side of the voice loop. The sentence buffer hands clauses to TTS; TTS streams 24 kHz PCM16; the transport layer resamples and packetizes to whatever the wire wants (Opus 48 kHz for browser, slin 8 kHz for phone). Two TTS backends live behind one factory.

Read [`00-architecture-overview.md`](00-architecture-overview.md) and [`02-llm-and-agents.md`](02-llm-and-agents.md) first.

---

## 1. Output pipeline

```
LLM token stream → Sentence buffer flushes a clause
                              │ str
                              ▼
                Text normalization (TTS-specific)
                              │ str
                              ▼
                  Streaming TTS (vieneu or elevenlabs)
                              │ async iterator of bytes (24 kHz PCM16 mono)
                              ▼
              Transport-layer resampler
                  ├── Browser (WebRTC):  24 → 48 kHz, encode Opus
                  └── Telephony:         24 →  8 kHz + bandpass 200–3400 Hz
                              │
                              ▼
                  Wire (RTP / AudioSocket TCP frames)
```

Choices baked in:

- **TTS always emits 24 kHz PCM16 mono.** No backend ever returns Opus or 8 kHz directly. This keeps the resample chain in one place.
- **Sentence buffer is the only producer.** Don't call `tts.stream()` from anywhere else — it bypasses pacing and breaks barge-in.
- **One TTS task per turn.** When VAD says "user interrupted", the orchestrator cancels the task; pending audio in the resampler is discarded; comfort noise plays for ~80 ms before STT kicks in.

---

## 2. Backends

Selection via `TTS_BACKEND` env var. Both expose `async stream(text: str) -> AsyncIterator[bytes]`.

| `TTS_BACKEND` | Latency | Cost | Vietnamese | Use when |
|---|---|---|---|---|
| `vieneu` | ~120 ms first-byte (warm), ~600 ms cold | Free (local) | Native Vietnamese voice (Northern dialect) | Have GPU, want zero per-call cost |
| `elevenlabs` | ~200 ms first-byte (warm WS), ~400 ms cold | $0.10/1k chars | Multilingual, less natural for Vietnamese | Cloud-only deployments / fast iteration |

The factory is `agent/voice.py::_make_tts()`. To swap, edit `.env` and restart — no code change.

### 2.1 VieNeu (`src/noble_agent/voice/tts/vieneu.py`)

Local GGUF + neucodec. Loaded once on agent startup (~3 s cold). Both sync and async wrappers exist:

- `VieNeuTTS` — sync iterator (used in benchmarks)
- `AsyncVieNeuTTS` — async wrapper, used by production agent

**Voices** — pre-baked voice embeddings under `data/vieneu_voices/` (gitignored). Set `VIENEU_VOICE_ID` to one of the listed IDs. Auto-discovered via `list_voices()`.

**Model loading** — first looks for a local GGUF dir (`VIENEU_BACKBONE_REPO` pointing to a path), falls back to HF repo download. Caches to `~/.cache/huggingface/hub`.

**Config**:

```bash
TTS_BACKEND=vieneu
VIENEU_BACKBONE_REPO=/workspace/models/vieneu-tts-q5_k_m   # local GGUF dir, or HF repo
VIENEU_VOICE_ID=                                            # optional; default voice if blank
```

**Text normalization** — `_normalize_for_vieneu` lower-cases ASCII letters, expands abbreviations from `data/tts_pronunciation.json` (e.g. `"Q.7" → "Quận 7"`), strips emoji.

### 2.2 ElevenLabs (`src/noble_agent/voice/tts/elevenlabs.py`)

Cloud, **WebSocket streaming** (`wss://api.elevenlabs.io/v1/text-to-speech/<voice_id>/stream-input`). The WS stays open across multiple `stream()` calls within a session — `warm_up()` pre-opens it on agent startup so the first turn doesn't pay handshake.

**Config**:

```bash
TTS_BACKEND=elevenlabs
ELEVENLABS_API_KEY=
ELEVENLABS_TTS_VOICE_ID=pNInz6obpgDQGcFmaJgB    # default Adam — replace with your cloned voice
ELEVENLABS_TTS_MODEL=eleven_flash_v2_5           # flash = lower latency, lower quality
ELEVENLABS_TTS_LANGUAGE_CODE=vi
ELEVENLABS_TTS_STABILITY=0.5
ELEVENLABS_TTS_SIMILARITY_BOOST=0.75
ELEVENLABS_TTS_SPEED=1.0
```

`stability` controls expressiveness (0 → varied, 1 → flat); `similarity_boost` controls how closely the output matches the cloned voice. Start at the defaults and tune by ear.

**Text normalization** — `normalize_for_elevenlabs` is gentler than VieNeu's (ElevenLabs handles abbreviations natively). Mostly strips emoji and zero-width characters.

---

## 3. Audio resampling

File: `src/noble_agent/telephony/resampler.py` (telephony) and `src/noble_agent/voice/audio/transport.py` (WebRTC).

### 3.1 Sample-rate matrix

| Source | Target | Where | Library |
|---|---|---|---|
| 48 kHz (Opus decoded) | 16 kHz (STT) | WebRTC inbound | scipy.signal / `aiortc` resampler |
| 8 kHz slin (Asterisk) | 16 kHz (STT) | Telephony inbound | soxr HQ |
| 24 kHz (TTS out) | 48 kHz (browser) | WebRTC outbound | scipy.signal |
| 24 kHz (TTS out) | 8 kHz slin (phone) | Telephony outbound | soxr HQ + bandpass + pre-emphasis |

`soxr` is preferred (clean phase, good aliasing rejection). `scipy.signal.resample_poly` is the fallback. Naive numpy is a last-resort path that exists for unit tests.

### 3.2 Bandpass + pre-emphasis (telephony only)

Phones use 200–3400 Hz with a μ-law-shaped speech band. Naively dumping 24 kHz speech into 8 kHz introduces high-frequency aliasing that **sounds like static**. The chain:

```
24 kHz PCM16
    → pre-emphasis 0.95 (boost high freq before resample)
    → soxr resample 24 → 8 kHz
    → bandpass 200–3400 Hz IIR
    → output PCM16
```

Implementation in `telephony/resampler.py`. Don't disable bandpass for "cleaner" audio — it's there to remove what isn't supposed to be in the band.

### 3.3 Comfort noise during silence

Asterisk drops a connection that goes silent for >5 s on AudioSocket. To keep the channel alive while the agent isn't speaking (waiting on LLM, between sentences), the telephony session emits 320-byte frames at 20 ms cadence with `np.random.normal(0, 32)` — comfort noise. Inaudible, keeps the FreePBX peer happy.

---

## 4. Pacing — why 20 ms

AudioSocket and RTP both send fixed-size frames (320 bytes for 8 kHz slin = 20 ms; 960 samples for 48 kHz = 20 ms). The transport layer paces reads from the TTS iterator so one frame goes out per 20 ms tick:

```
TTS iterator yields chunk (variable size, often 480-2400 samples)
    → producer task pushes to bounded queue
    → consumer task pops every 20 ms, slices to 320 B / 960 samples
    → write to socket
```

**100 ms warmup** before pacing starts — the producer accumulates the first 5 frames before the consumer fires, so playback doesn't underrun on the first turn. After warmup, queue depth stays ≤ 3 frames (60 ms) — enough buffer to absorb scheduler jitter, low enough that a late LLM token still feels live.

---

## 5. Adding a new TTS backend

Same pattern as STT (see [`01-stt-and-vad.md`](01-stt-and-vad.md) §5):

1. Implement `async stream(text: str) -> AsyncIterator[bytes]` in `src/noble_agent/voice/tts/<name>.py`. **Must yield 24 kHz PCM16 mono bytes.** If the backend returns a different rate, resample inside the module — don't push that responsibility upward.
2. Optional: implement `async warm_up()` to pre-open connections / pre-load models.
3. Add factory branch in `agent/voice.py::_make_tts`.
4. Add settings + `.env.example` entry.
5. Add a benchmark to `tests/bench_tts/` that measures first-byte latency over a fixed Vietnamese sentence.

The 24 kHz PCM16 contract is non-negotiable. If you have a backend that wants Opus end-to-end, route it directly into the transport layer at the right rate — but that's a different feature, not a "new TTS".

---

## 6. Sentence buffer ↔ TTS contract

The buffer (`agent/sentence_buffer.py`) hands single clauses to `tts.stream(clause)`. Important guarantees:

- **Whitespace is collapsed** before flush. The buffer never emits "  Em xin "; it'd be "Em xin".
- **Each clause is a self-contained TTS unit.** ElevenLabs WS streams them in one logical turn (so prosody flows), but the boundaries are still flush points.
- **End-of-stream flush** is best-effort: the orchestrator awaits the buffer's `close()` which flushes whatever's left, even if it doesn't end in punctuation.

---

## 7. Common debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| Audio cuts in half mid-word on barge-in | Resampler drained queue but socket already wrote frame | This is correct — frame is in flight. Tune pacing buffer depth |
| Phone audio "tinny" / static | Bandpass + pre-emphasis disabled or applied in wrong order | Check `telephony/resampler.py:_resample_24k_to_8k` order |
| First TTS chunk takes 600 ms when warmup says 200 | Cold WebSocket / cold model | Confirm `warm_up()` ran (logged at agent startup) |
| ElevenLabs returns 401 mid-call | Concurrent connection limit on plan | Upgrade plan or set `ELEVENLABS_MAX_CONCURRENT=1` |
| VieNeu emits silence for unicode-heavy text | `_normalize_for_vieneu` dropped the chars; check pronunciation map | Add entries to `data/tts_pronunciation.json` |
| Browser hears glitches on long sentences | Producer-consumer queue overflow → frames dropped | Logged as `audio_underrun_count`. Sentence too long; tune buffer flush threshold |
| `data/vieneu_voices/` missing on a fresh checkout | Voice presets are gitignored | Re-run `python -m tests.train_vietneu_tts.export_voices` or copy from a known-good pod |

---

## 8. References

- soxr Python wrapper: https://github.com/dofuuz/python-soxr
- ElevenLabs WS streaming docs: https://elevenlabs.io/docs/api-reference/websockets
- VieNeu TTS upstream: https://huggingface.co/AILAB-VN/VieNeu-TTS
- AudioSocket framing (320 B / 20 ms slin) → [`07-freepbx-asterisk-bridge.md`](07-freepbx-asterisk-bridge.md)
- WebRTC ↔ Opus encoding: aiortc handles this transparently; resample sits before the encoder

Continue → [`04-rag-and-knowledge.md`](04-rag-and-knowledge.md) for what feeds the LLM with project knowledge.
