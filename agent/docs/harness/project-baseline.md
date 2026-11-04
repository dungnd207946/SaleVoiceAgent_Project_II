# Project Baseline — Noble Voice Agent

Anchor for harness project-drift detection. When the top-level modules, tech stack, or target below no longer match reality, the harness (agents + skills) likely needs a re-sync. Regenerated on deliberate re-sync, not per-commit.

_Last synced: 2026-07-10 (branch `develop`, reflecting `feat/connect-db` → `feat/refactor2` → `feat/app-integration`)._

## Target

Real-time Vietnamese voice hotline for **Noble Real Estate**. One unified agent (**Luna**) answers callers end-to-end over four transports, with low-latency full-duplex audio, VAD-based barge-in, and RAG-grounded answers about **15 Noble projects**. Serves port **8766**.

Product-defining constraints:
- **Latency is the product** — TTFA (time to first audio) is what the caller feels; a change that adds ~150 ms is a regression even if tests pass.
- **Answer accuracy** — wrong/empty retrieval = a wrong answer on a live call.
- **Single agent** — no router / registry / `switch_agent`; human handoff is the `escalate` tool.

## Tech stack

- **Language:** Python 3.11–3.13. Package `noble-voice-agent` (import `noble_agent`, CLI `noble-agent`).
- **Config:** `pydantic-settings` (`config.UnifiedSettings`) — all env vars in one place.
- **Async:** `asyncio` throughout the audio + LLM spine.
- **Transports:** browser WebRTC (aiortc), text chat (`/chat`), telephony (Asterisk ARI + AudioSocket), LiveKit RTC.
- **Storage:** Redis (3-key session state), MongoDB (shared DB `noble_agent`; hotline collections `hotline_`-prefixed; project truth in `project_du_an`/`project_can_ho`), Qdrant (production RAG). FAISS only for semcache hot layer.
- **RAG:** server-side hybrid on an app-owned Qdrant clone (e5-large dense + pyvi BM25 sparse, RRF fused by Qdrant; startup reconcile + `noble-rag-sync`; disk BM25 fallback); FlatStore dev-only; remote embed service (Bearer + `is_query`).
- **Observability:** boot-gated OTEL LLM tracing to self-hosted Arize Phoenix (`observability/phoenix_tracing.py`).
- **STT backends:** `soniox | sherpa | elevenlabs | qwen3asr | remote`.
- **TTS backends:** `vieneu | vieneu_vllm | elevenlabs | remote | hotline_ws`.
- **LLM providers:** `anthropic | vllm | openai | dashscope | gemini` (ordered fallback, per-path primary pins).
- **Voice services:** resident `noble-stt-service` / `noble-tts-service` / `noble-speaker-service` (WS/HTTP, model loaded once).
- **Test/lint:** pytest (`asyncio_mode=auto`), markers `requires_docker/bench/needs_mongo/needs_redis/needs_qdrant`; ruff (line 120, `E,F,W,I,UP,B,SIM`); ≥80% coverage target.

## Top-level modules (`src/noble_agent/`)

| Module | Role | Harness coverage |
|---|---|---|
| `__main__.py`, `config.py` | CLI entry + settings | `noble-voice-architecture` |
| `agent/` (`facade`, `orchestrator`, `runner`, `base`, `catalog`, `definitions/`, `prompts/`, `llm/`, `rag/`, `summary/`, `tools/`, `qwen_transcript`) | Unified agent core, turn loop, LLM, tools, RAG, catalog | `noble-voice-architecture` (core/tools/LLM), `rag-quality` (rag/catalog) |
| `voice/` (`stt/`, `tts/`, `service/`, `vad/`, `turn_detection/`, `audio/`, `voice_agent`, `sentence_buffer`, `fallback`, `prewarm`, `stt_input_gate`, `speaker_verifier`) | Pluggable STT/TTS, resident services, VAD, endpointing, gate, speaker policy | `noble-voice-architecture` (seams), `latency-discipline` (streaming path) |
| `server/` | Browser/WS transport, sessions, `/chat`, NobleX-app provisioning (`app_session.py`: chat connect-token + voice LiveKit token), outbound API, rate limit | `noble-voice-architecture` |
| `telephony/` | PSTN via Asterisk ARI + AudioSocket | `noble-voice-architecture` |
| `transport/livekit/` | LiveKit RTC worker + room session | `noble-voice-architecture` |
| `storage/` | Redis `StateRepo` (3 keys) + Mongo | `noble-voice-architecture` |
| `services/`, `metrics/`, `semcache/` | CRM/structured-data, `session_metrics`, optional response cache | `noble-voice-architecture` (services/metrics), `rag-quality` (semcache) |
| `observability/` | Phoenix OTEL LLM tracing (boot-gated no-op) | `noble-voice-architecture` |
| tests (`tests/{unit,integration,e2e_scenarios,bench,bench_estate,bench_rag}/`) | pytest suites + scripted-conversation e2e (`make e2e`) + evals | `testing-conventions`, `rag-quality` (estate eval), `latency-discipline` (bench) |

## Known drift risks to watch

- New STT/TTS/LLM backend → check the backend lists above + the seam recipes in `noble-voice-architecture`.
- Project roster / code rename (currently 15, DB-aligned) → `agent/catalog.py` `_REGISTRY` must re-sync to `project_du_an.ma_du_an`; enums + prompt table come from `data/db_project_registry.py` (`rag-quality`).
- New pytest marker or `make` target → `testing-conventions`.
- Turn-loop / prompt-injection change → `noble-voice-architecture` (invariants) + `rag-quality` (freshness).
- New app-facing endpoint / auth gate (NobleX app surface) → `noble-voice-architecture` (server layer row).
