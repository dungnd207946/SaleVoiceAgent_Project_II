# 01 — STT + VAD + Smart Turn

> Voice input pipeline: how raw audio frames become a finalized user transcript that the LLM is allowed to see. Three components — VAD (when), STT (what), Smart Turn (really done?). All three are configurable; you can swap STT backends without touching anything else.

Read [`00-architecture-overview.md`](00-architecture-overview.md) first.

---

## 1. Pipeline overview

```
Browser/Phone audio 48 kHz / 8 kHz Opus or slin
         ↓ resample
   16 kHz mono PCM16  ──────────┬─────────────────────────────────┐
                                │                                 │
                                ▼                                 ▼
                   Silero VAD (barge-in only)        Streaming STT (push frames)
                   IDLE → SPEAKING → INTERRUPTED     on_partial / on_final
                   is_speech   → STT input gate (vad mode)
                   INTERRUPTED → cancel agent turn         │
                                │                          │
                                ▼                          │
                   Optional: Smart Turn ONNX gate          │
                   (last 8 s, semantic-end check)          │
                                │                          │
                                ▼                          ▼
                              Commit final transcript → LLM
```

VAD never decides when an utterance ends — the STT backend's endpoint does. VAD only decides barge-in. Both signals are merged in the session loop (`server/base_session.py`).

---

## 2. Silero VAD — state machine

File: `src/noble_agent/voice/vad/silero.py`. Wraps the upstream Silero model — pinned `silero-vad==6.2.1` wheel (no `torch.hub`, no network at boot), loaded **once per process** (`_load_shared_model`, warmed by `voice/prewarm.py`) and `deepcopy`'d per session because the JIT model carries LSTM state — and runs a 3-state barge-in machine over 32 ms chunks. It does **not** endpoint utterances; the STT backend does.

```
IDLE ──set_speaking()──> SPEAKING ──VAD_INTERRUPT_CONFIRM_CHUNKS speech chunks──> INTERRUPTED
  ▲                         ▲                                                        │
  └──────── set_idle() ─────┴──────────────────── set_speaking() ────────────────────┘
```

| State | Meaning | What changes |
|---|---|---|
| `IDLE` | Agent silent | `process_chunk` still reports `is_speech` (feeds the `vad` STT input gate / addressee tracker); no transition |
| `SPEAKING` | Agent turn armed (`_run_agent` / greeting) | Counting consecutive speech chunks; any non-speech chunk resets the count |
| `INTERRUPTED` | Barge-in confirmed | **Latches** until the session calls `set_speaking()` (re-arm) or `set_idle()` (turn over) |

### Tunables (via `.env` / `config.py`)

| Setting | Default | Notes |
|---|---:|---|
| `VAD_CHUNK_MS` | 32 | Fixed by Silero v5+: 512 samples @ 16 kHz — any other value fails at load with a clear error |
| `VAD_THRESHOLD` | 0.7 | Silero probability → `is_speech` |
| `VAD_INTERRUPT_CONFIRM_CHUNKS` | 3 | Consecutive speech chunks (96 ms) to confirm barge-in |
| `BARGE_IN_RMS_THRESHOLD` | 1500 | RMS floor (int16) each chunk must clear **while agent audio is actually playing** (`playback_active`) — rejects AEC echo residual; 0 = off; logs `rejected by RMS floor` once per turn |

Same values for WebRTC and telephony — there is no per-transport override; watch the `rejected by RMS floor` log on PSTN calls before tuning.

### Interrupt path (barge-in)

`SPEAKING → INTERRUPTED` after `VAD_INTERRUPT_CONFIRM_CHUNKS` consecutive speech chunks (each also above the RMS floor once audio is playing). The session then runs `_handle_interrupt`: `agent.pause_tts()` → cancel the agent task → `audio_output.clear()` → `vad.set_idle()`. With the addressee gate or the multi-speaker floor enabled it instead opens an episode and re-arms with `set_speaking()`. Walkthrough: `docs/walkthrough/audio-pipeline.md` §2–3.

---

## 3. STT backends — interface + selection

All STT backends conform to the `STTBase` Protocol (`src/noble_agent/voice/stt/base.py`):

```python
class STTBase(Protocol):
    async def start(self) -> None: ...                   # open WS / load model
    async def send(self, pcm_bytes: bytes) -> None: ...  # push 16 kHz PCM16 frame
    async def stop(self) -> None: ...                    # commit + close
    on_partial: Callable[[str], Awaitable[None]] | None  # streaming partials
    on_final:   Callable[[str], Awaitable[None]] | None  # finalized transcript
```

Backend factory is **lazy-imported** in `src/noble_agent/server/session.py` so installing one backend's deps doesn't drag the others.

### 3.1 Selection matrix

| `STT_BACKEND` | Latency | Cost | Vietnamese quality | Use when |
|---|---|---|---|---|
| `soniox` | ~200 ms partial, ~600 ms final | $0.07/min | Best (multilingual realtime v4) | Production, cloud OK |
| `sherpa` | ~120 ms partial, ~400 ms final | Free (local) | Very good (Zipformer-30M-RNNT-Streaming) | Air-gapped / RunPod GPU available |
| `qwen3asr` | ~250 ms final | Free (vLLM) | Good (Qwen3-ASR via vLLM) | Already running vLLM for LLM |
| `elevenlabs` | ~300 ms final | $0.20/min | Acceptable | Same vendor as TTS for billing |

### 3.2 Soniox (`src/noble_agent/voice/stt/soniox.py`)

Cloud, WebSocket streaming. Class `SonioxSTT(model="stt-rt-v4", api_key)`.

**Hot-words** (in-domain biasing): comma-separated terms loaded from `data/hotwords.txt` and merged into the Soniox config block. Add Noble-specific terms (`Noble Crystal`, `Long Biên`, `NƠHTTL`) so the recognizer gets them right on first try.

**Config keys** (`.env`):

```bash
STT_BACKEND=soniox
SONIOX_API_KEY=
SONIOX_MODEL=stt-rt-v4
```

### 3.3 Sherpa-onnx (`src/noble_agent/voice/stt/sherpa.py`)

Local, on-device ONNX inference. Class `SherpaSTT(model_dir, hotwords_file)`.

**Model**: Zipformer-30M-RNNT streaming. Download once, point `SHERPA_MODEL_DIR` at the unpacked folder.

```bash
STT_BACKEND=sherpa
SHERPA_MODEL_DIR=/path/to/sherpa-onnx-streaming-zipformer-...
SHERPA_HOTWORDS_FILE=data/hotwords.txt
```

Hotwords format: one phrase per line, optional `:weight` suffix (`Noble Crystal:2.0`).

### 3.4 Qwen3-ASR via vLLM (`src/noble_agent/voice/stt/qwen3asr.py`)

OpenAI-compatible whisper-like endpoint served by vLLM.

```bash
STT_BACKEND=qwen3asr
QWEN3ASR_VLLM_URL=http://localhost:8000
```

This sits on the **same vLLM** as the LLM (`infra/runpod/start_vllm.sh` exposes `/v1/audio/transcriptions`).

### 3.5 ElevenLabs STT (`src/noble_agent/voice/stt/elevenlabs.py`)

Cloud WebSocket. Class shares the auth/voice-id config block with the TTS backend.

```bash
STT_BACKEND=elevenlabs
ELEVENLABS_API_KEY=
```

---

## 4. Smart Turn — semantic end-of-turn gate (optional)

File: `src/noble_agent/voice/turn_detection/smart_turn.py`. Wraps an ONNX model from `Ref/smart-turn` that returns `{prediction: 0|1, probability: float}` over the last 8 s of 16 kHz audio.

**Why**: Silero VAD only knows "is there voice?". It can't tell that "tôi muốn hỏi về" is mid-thought vs "tôi không cần nữa." being a real end. Smart Turn's prosodic + semantic features close that gap.

**When it kicks in**: only after Silero VAD says silence-end. If `smart_turn_enabled=true`, the session loop holds the STT final for up to `smart_turn_max_hold_sec` (default 2.0 s) waiting for Smart Turn's verdict before passing the transcript to the LLM.

**Config**:

```bash
SMART_TURN_ENABLED=false                 # opt-in
SMART_TURN_MODEL_PATH=                   # path to .onnx
SMART_TURN_THRESHOLD=0.5
SMART_TURN_MAX_HOLD_SEC=2.0              # hard cap so a stuck model doesn't freeze the call
```

**When to enable**: production calls where users speak in halting, multi-clause sentences. Disable for short Q&A flows where users reliably pause.

---

## 5. Adding a new STT backend

1. Create `src/noble_agent/voice/stt/<name>.py` exporting `<Name>STT` that conforms to `STTBase`.
2. Lazy-import in `src/noble_agent/server/session.py:_make_stt()`:
   ```python
   if backend == "<name>":
       from noble_agent.voice.stt.<name> import <Name>STT
       return <Name>STT(api_key=settings.<name>_api_key, ...)
   ```
3. Add settings in `src/noble_agent/config.py` (one section block, following the existing layout).
4. Add `.env.example` entry.
5. Add lint extras to `pyproject.toml` `[project.optional-dependencies]` if the backend has heavy deps.
6. Add a unit test under `tests/unit/voice/stt/` that mocks the WS / model and asserts `on_partial` / `on_final` fire correctly.
7. Add a smoke entry in `tests/bench_llm.py` style — point a real call at the backend and measure TTFT.

The `STTBase` Protocol contract is the only API surface. Don't reach into internals from `voice.py` or `session.py`.

---

## 6. Common debugging

| Symptom | Most likely cause | Fix |
|---|---|---|
| Long silence before LLM responds | STT endpoint / Smart Turn hold — VAD does not endpoint | Check the STT backend's endpoint setting and `STT_GATE_KEEPALIVE_MAX_SEC`; `SMART_TURN_*` if enabled |
| Caller can't barge in on the phone | `BARGE_IN_RMS_THRESHOLD` (1500) above that caller's speech level | Look for `rejected by RMS floor` in logs; lower it (or 0 = off) |
| First STT call adds 2–3 s latency | Model load (Silero / Sherpa) blocks event loop | `noble-agent` warms both at startup; verify by `grep "Loading Silero" logs` |
| Hot-words ignored | File path wrong / not parsed | Confirm `SHERPA_HOTWORDS_FILE` exists and is one-phrase-per-line UTF-8 |
| Soniox returns garbled text | Wrong sample rate fed in | All STT expects 16 kHz mono PCM16; verify resample in `voice/audio/transport.py` |
| Barge-in feels sluggish | `vad_interrupt_confirm_chunks` too high | 3 chunks ≈ 96 ms; drop to 2 if VAD is reliable |
| Smart Turn never fires | `SMART_TURN_MODEL_PATH` empty | Module silently disables when path is empty (logs a warning at startup) |

---

## 7. References

- Silero VAD repo: https://github.com/snakers4/silero-vad (loaded via `torch.hub`)
- Smart Turn v3: `Ref/smart-turn` (vendor in repo)
- Soniox docs: https://soniox.com/docs/speech-to-text/api-reference/websocket-api
- Sherpa-onnx model zoo: https://k2-fsa.github.io/sherpa/onnx/pretrained_models
- Qwen3-ASR vLLM endpoint: see `infra/runpod/start_vllm.sh`

Continue → [`02-llm-and-agents.md`](02-llm-and-agents.md) for what happens once a final transcript is committed.
