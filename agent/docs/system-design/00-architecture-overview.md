# 00 — Architecture Overview

> Real-time voice hotline agent for Noble Real Estate. WebRTC + WebSocket + AudioSocket transports, pluggable STT / TTS / LLM, interrupt detection via VAD, multi-agent routing, RAG-powered Q&A. Python 3.11–3.13, single Python process per pod, Redis + MongoDB + (in-process) FlatStore for RAG.

This document is the **anchor for all other system-design docs**. Read it first; the topic-specific docs (`01–09`) drill into individual layers.

---

## 1. Big picture

```
                                      ┌────────────────────────────────────────────────┐
                                      │  Browser (WebRTC, port 8766 /ws)               │
                                      │  Phone (FreePBX → AudioSocket TCP, port 8090)  │
                                      └──────────────────────┬─────────────────────────┘
                                                             │ Opus 48 kHz / slin 8 kHz
                                                             ▼
                              ┌──────────────────────────────────────────────────────┐
                              │  Transport (`server/`, `telephony/`)                 │
                              │   ws_handler.py · audiosocket.py · ari_client.py     │
                              │   resampler 48↔16, 8↔16, 24↔8                        │
                              └─────────┬────────────────────────────────────────────┘
                                        │ 16 kHz mono PCM16
                                        ▼
              ┌─────────────────────────────────────────────────────────────────────┐
              │  Voice I/O (`voice/`)                                                │
              │   stt/{sherpa,soniox,elevenlabs,qwen3asr}.py  ← STT_BACKEND env      │
              │   vad/silero.py  ← Silero VAD state machine + interrupt detect       │
              │   turn_detection/smart_turn.py  ← optional ONNX semantic gate        │
              │   tts/{vieneu,elevenlabs}.py    ← TTS_BACKEND env                    │
              └─────────┬────────────────────────┬─────────────────────────────────┘
                        │ user_text on STT final │ TTS audio chunks
                        ▼                        ▲
        ┌─────────────────────────────────────────────────────────────────────────┐
        │  Agent Orchestrator (`agent/`)                                           │
        │   voice.py VoiceAgent — main turn loop                                  │
        │   sentence_buffer.py — clause/sentence segmentation for streaming TTS    │
        │   llm/streaming.py StreamingLLM — provider streaming + tool loop         │
        │   tools/* — OpenAI function tools (booking, switch_agent, noble_search…) │
        │   registry.py — multi-agent (router/consultant/support) + SOUL/SKILL MD  │
        │   summary/generator.py — async summarization context (long calls)        │
        │   rag/* — FlatStore + FAQ + SlowThinker prefetch (see 04)                │
        └─────────┬─────────────────────────────────────────────────────────────┘
                  │
                  ▼
        ┌─────────────────────────────────────────────────────────────────────────┐
        │  External / Storage                                                      │
        │   Redis (sessions, cache, customer canonical project codes)              │
        │   MongoDB (history, bookings, session_metrics)                           │
        │   FlatStore in-process (e5-large embeddings + BM25 indices)              │
        │   OpenAI / Gemini (LLM streaming + tool calling)                         │
        │   Soniox / ElevenLabs cloud (STT / TTS over WebSocket)                   │
        │   Sherpa-onnx / VieNeu local (STT / TTS — no internet)                   │
        │   Smart-Turn ONNX (optional turn-end semantic gate)                      │
        └─────────────────────────────────────────────────────────────────────────┘
```

Cross-reference: detailed audio pipeline → [`07-freepbx-asterisk-bridge.md`](07-freepbx-asterisk-bridge.md). Agent loop deep dive → [`02-llm-and-agents.md`](02-llm-and-agents.md).

---

## 2. End-to-end turn (full-duplex streaming)

```
Browser/Phone ──► resample 48→16 / 8→16 ──► Silero VAD ─┐
                                                        │ on_speech_start / _end
                                  ┌─────────────────────┘
                                  ▼
                  Streaming STT (sherpa/soniox/...)
                                  │ partial / final transcripts
                                  ▼
              Smart-Turn (optional, semantic-end gate)
                                  │ commit final
                                  ▼
              StreamingLLM ─── tool_loop ─── RAG prefetch
                                  │ token stream
                                  ▼
                    Sentence Buffer (clause/sentence split)
                                  │ chunks
                                  ▼
                    Streaming TTS (vieneu/elevenlabs)
                                  │ 24 kHz PCM16
                                  ▼
              resample 24→48 / 24→8 + bandpass 200–3400 Hz (telephony)
                                  │
                                  ▼
                            Browser / Asterisk
```

Latency targets (production):

| Stage | p50 | p95 | Source |
|---|---:|---:|---|
| `vad_speech_end` → STT final | 250 ms | 800 ms | sherpa local / soniox cloud |
| STT final → LLM TTFT | 300 ms | 1,800 ms | OpenAI gpt-5.4-nano |
| LLM TTFT → first TTS audio | 200 ms | 600 ms | sentence buffer + tts streaming |
| Total round-trip (no tool) | 1,100 ms | 4,200 ms | end-to-end |

Numbers come from `tests/bench_estate/` real runs and the `metrics/session_metrics` MongoDB collection.

---

## 3. Module layering

| Layer | Modules | Responsibility |
|---|---|---|
| **Transport** | `server/{ws_handler.py, http.py, base_session.py}`, `telephony/{audiosocket.py, ari_client.py, session.py}` | WebSocket routing, AudioSocket TCP, ARI WS, session lifecycle, rate limits |
| **Voice I/O** | `voice/stt/`, `voice/tts/`, `voice/vad/silero.py`, `voice/turn_detection/smart_turn.py`, `voice/audio/transport.py` | Pluggable backends, VAD state machine, audio framing/resampling |
| **Orchestration** | `agent/{app.py, voice.py, sentence_buffer.py, registry.py}` | Turn loop, sentence segmentation, multi-agent registry |
| **Agent definitions** | `agent/definitions/agents/{router,consultant,support}/{SOUL.md, SKILL.md, config.json}` | Multi-agent personas + tool whitelist |
| **LLM** | `agent/llm/streaming.py` | Provider streaming, retry, tool loop |
| **Tools** | `agent/tools/{schemas.py, __init__.py, booking.py, ...}` | OpenAI function tools |
| **RAG** | `agent/rag/{flat_store.py, faq_searcher.py, slow_thinker.py, ...}` | FlatStore hybrid + FAQ + prefetch |
| **Summary** | `agent/summary/generator.py` | Async summarization context for long calls |
| **Services** | `services/{crm_service.py, structured_data_service.py}` | External REST integrations |
| **Storage** | `storage/{connection.py, session_store.py}` | Redis + MongoDB pools |
| **Metrics** | `metrics/{collector.py, store.py, reporter.py}` | TTFT/TTFA + session_metrics MongoDB |
| **Config** | `src/noble_agent/config.py` | Pydantic settings, every env var |

Each layer **depends downward only**. Transport ↛ orchestration ↛ voice I/O is the dependency direction; cycles trip CI imports.

---

## 4. Pluggable backends — how to swap

| Capability | Env var | Backends |
|---|---|---|
| STT | `STT_BACKEND` | `soniox` (cloud WS) · `sherpa` (local Zipformer ONNX) · `qwen3asr` (vLLM) · `elevenlabs` (cloud WS) |
| TTS | `TTS_BACKEND` | `vieneu` (local GGUF, Vietnamese) · `elevenlabs` (cloud WS) |
| LLM | `OPENAI_API_KEY` / `GEMINI_API_KEY` | OpenAI gpt-5.4-nano · Gemini 2.5 Flash · vLLM Qwen3.6 · DashScope (Qwen) |
| Vector store | `NOBLE_RAG_BACKEND` | `flat_store` (default, in-process) · `memory_router` · `empty` |

Backend factories are lazy-imported in `src/noble_agent/server/session.py` (STT) and `src/noble_agent/agent/voice.py` (TTS). To add a new STT, implement `STTBase` in `src/noble_agent/voice/stt/<name>.py`, register lazy import, set `STT_BACKEND=<name>`. Detail in [`01-stt-and-vad.md`](01-stt-and-vad.md).

---

## 5. Port map

| Port | Listener | Purpose |
|---|---|---|
| 8766 | `noble-agent` | WebSocket (browser) + HTTP REST + static |
| 8090 | `telephony.audiosocket` | AudioSocket TCP (FreePBX/Asterisk) |
| 8088 | Asterisk | ARI HTTP+WS (subscriber, not server) |
| 6379 | Redis | sessions + cache + customer canonical |
| 27017 | MongoDB | history, bookings, session_metrics |
| 6333 | Qdrant | (kept 1 sprint as RAG fallback only) |
| 8000 | vLLM | Qwen3.6 generation server (RunPod pod) |
| 8081 | embed_server | bge-m3 embedding (RunPod pod) |

`scripts/run.sh` brings up the agent on 8766; the docker-compose stack adds Redis + MongoDB. RunPod single-pod stack adds vLLM on 8000 + embed_server on 8081 (see [`06-infrastructure-and-runpod.md`](06-infrastructure-and-runpod.md)).

---

## 6. Configuration surface

`src/noble_agent/config.py` is a Pydantic `Settings` class — **single source of truth** for ~120 env vars. Everything reads `from noble_agent.config import settings`. Sections:

- LLM (provider keys, model, reasoning effort, retry)
- STT (backend select, Soniox key, sherpa model dir, qwen3asr vLLM URL)
- VAD (silence ms, min speech ms, interrupt confirm chunks, sample rate)
- Smart Turn (enable, threshold)
- TTS (backend select, ElevenLabs voice ID, VieNeu repo)
- WebSocket (host, port)
- Telephony (AudioSocket port, ARI host/port/user/pass, sample rate)
- Storage (Redis URL, MongoDB URI, MongoDB database)
- RAG (Qdrant URL/collection, TEI URL, embedding model, NOBLE_RAG_BACKEND)
- Summary / FAQ / Slow-thinker tunables
- Profile API (Noble customer profile)
- Outreach / SMS / Email
- Transport backend (`aiortc` | `livekit`), LiveKit credentials

Defaults are dev-friendly (localhost), `cp .env.example .env` then edit. Production overrides come via `infra/runpod/env.runpod.example` or `docker-compose.runpod.yml`.

Detail per env-var category → [`06-infrastructure-and-runpod.md`](06-infrastructure-and-runpod.md) §3.

---

## 7. Data stores

| Store | Workload | Detail |
|---|---|---|
| **Redis** | Hot path: session state, customer canonical project codes (`project_interest` always 4-char code), L1 caches, LangGraph-style checkpoints | Connection-pooled in `storage/connection.py`. TTL 24 h on session keys |
| **MongoDB** | Conversation history (turn-by-turn), bookings, customers, `session_metrics` (TTFT/TTFA percentiles) | Motor async client. Collections: `conversations`, `messages`, `bookings`, `customers`, `session_metrics` |
| **FlatStore** (in-process) | Dense (e5-large, 1024-dim) + sparse (BM25S) hybrid search over Noble project chunks. ~30 MB resident, ~50 ms warm | `agent/rag/flat_store.py`. Built once via `python -c "from noble_agent.agent.rag.flat_store import FlatStore; s=FlatStore(); s.load(); s.build_bm25()"` |
| **FAISS** (in-memory) | Per-turn FAQ semantic match (e5-large cosine), SemanticCache for SlowThinker prefetch | `agent/rag/{faq_searcher.py, semantic_cache.py}` |
| **Qdrant** | Fallback RAG when `NOBLE_RAG_BACKEND=memory_router` (kept one sprint for emergency) | Optional extra `rag-qdrant` |

Detail → [`04-rag-and-knowledge.md`](04-rag-and-knowledge.md).

---

## 8. Non-negotiables

These are baked into the architecture and changing them breaks downstream assumptions:

1. **Single source of truth for project codes**: `agent/project_catalog.py` normalizes any user mention or alias (`"Lakeside"`, `"NƠHTTL"`, `"Bình"`) to one of 5 canonical codes (`NCLB`, `NCTH`, `NPLB`, `NTTL`, `SSLC`). Redis only stores canonical. Anything that reads `customer.project_interest` must call `catalog.normalize()` first.
2. **STT runs on 16 kHz mono PCM16**, end of story. AudioSocket inbound 8 kHz is resampled at the session boundary, never inside the STT module.
3. **TTS streams 24 kHz PCM16**, period. The transport layer owns resampling out (24→48 for browser, 24→8 + bandpass for phone).
4. **Sentence buffer is the only thing that talks to TTS**. The LLM token stream goes into the buffer; the buffer flushes on clause/sentence boundaries; only flushed segments hit TTS. This avoids choppy audio.
5. **Tool calls block the LLM stream** but never block VAD/audio out. While a tool is running, the agent emits a deferred-narration ack ("Em đang tra ngay…") so the user doesn't hear silence.
6. **`develop` is the user's branch**. Claude / agents work on feature branches only (`feat/...`). See repo `CLAUDE.md` for the absolute rules.

---

## 9. Where to go next

| Question | Doc |
|---|---|
| How does STT work? Which backend should I pick? | [`01-stt-and-vad.md`](01-stt-and-vad.md) |
| How does the agent decide what to say + when to switch personas? | [`02-llm-and-agents.md`](02-llm-and-agents.md) |
| Why is TTS still streaming when the LLM stops mid-sentence? | [`03-tts-and-audio.md`](03-tts-and-audio.md) |
| Where does noble_search look for project info? | [`04-rag-and-knowledge.md`](04-rag-and-knowledge.md) |
| How do I evaluate a regression in agent quality? | [`05-benchmarking-and-testing.md`](05-benchmarking-and-testing.md) |
| How do I deploy on a fresh RunPod GPU? | [`06-infrastructure-and-runpod.md`](06-infrastructure-and-runpod.md) |
| How does a phone call enter the agent? | [`07-freepbx-asterisk-bridge.md`](07-freepbx-asterisk-bridge.md) |
| What does the browser send / receive on the WebSocket? | [`08-api-contracts-websocket-http.md`](08-api-contracts-websocket-http.md) |
| What's the wire format for AudioSocket? Which fields are in a tool call? | [`09-api-contracts-audiosocket-tools.md`](09-api-contracts-audiosocket-tools.md) |
