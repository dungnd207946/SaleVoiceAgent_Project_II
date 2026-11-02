# Load / Capacity Stress Test — Design

**Date:** 2026-07-14
**Status:** Phase A + B complete (see report); Phase C design added 2026-07-14 for build.
**Scope of this spec:** Phase A (per-service isolation) + Phase B (chat WS end-to-end) — both **done**. Phase C (end-to-end voice: aiortc `:8766` then LiveKit Cloud) is now **in scope** — see §11.

## 1. Objective

Find the **breaking point** (max sustainable concurrency) of the santa-hotline-agent microservice stack on the current single-box deployment, and identify **which resource saturates first** for each channel. Generate load from the Mac over LAN; observe resource saturation on the server over SSH; roll up per-stage latency from MongoDB `session_metrics` + Phoenix.

This is a measurement campaign that produces (a) reusable load tooling and (b) a capacity report. It is **not** a change to production behavior — the only prod mutation is a reversible LLM-stub reconfigure for Phase B (§7).

## 2. Environment (confirmed 2026-07-14)

Single box `thebc-server.local` = `10.50.12.70` (LAN RTT ~0.6 ms from the Mac):

| Resource | Spec |
|---|---|
| CPU | Intel i5-14600KF — 14 cores / **20 threads** |
| RAM | 30 GiB (≈21 GiB free at idle) |
| GPU | 1× RTX 5060 Ti, **16 GB** VRAM (7.2 GB resident for the TTS model at idle) |

**Co-tenants on the same box** (share the 20 threads): `santa-chat-agent` (a second live agent), `santa-agent-cms`, Grafana/Loki/Alloy logging, Phoenix, Caddy, plus the model services and stores. Idle loadavg ≈ 0.08. Co-tenancy is a result-interpretation caveat, not a blocker (all co-tenants idle during the test window; no real hotline traffic).

Ports reachable from the Mac (all confirmed OPEN):

| Port | Service | Transport | LLM in path? |
|---|---|---|---|
| `:8011` | **TTS** (vieneu/santa-tts, **sole GPU tenant**) | WS `/tts` | no |
| `:8012` | STT (sherpa, CPU) | WS `/stt` | no |
| `:8013` | embed (e5-large, Bearer) | HTTP POST | no |
| `:8014` | speaker embed | HTTP | no |
| `:8766` | agent (aiortc): chat WS `/chat` + WebRTC + `/health` + `/api/config` | WS / HTTP | yes |
| `:27017` | MongoDB (`session_metrics`, auth OK from Mac) | — | — |
| `:6379` | Redis (auth) | — | — |
| `:6333` | Qdrant | HTTP | — |
| `:6006` | Phoenix (LLM traces, Bearer) | HTTP | — |

`agent` + `agent-lk` + the model services run `network_mode: host` (no published port rows in `docker ps`). Chat WS needs no connect token (`CHAT_WS_REQUIRE_TOKEN=false`). **Voice runs on LiveKit Cloud** (`wss://santahotlin-…livekit.cloud`); there is no self-hosted LiveKit — the legacy sipp harness (`scripts/load_test/`, targeting a self-hosted LiveKit SIP on `:7880`) is dead and is not reused.

**Bottleneck hypothesis:** for any audio load the first thing to break is **TTS on the single GPU** — `vieneu` synthesizes under a `threading.Lock` (serial). STT (sherpa CPU) is the second suspect. Phase A tests this hypothesis head-on.

## 3. Definitions

**Warm baseline:** p50/p95 latency of a component measured at concurrency = 1, after a warm-up call, on an otherwise idle box.

**Breaking point (per concurrency step):** the lowest concurrency level at which **any** of these holds while load is held steady for ~90 s:
- p95 end-to-end latency > **2× warm baseline p95**, or
- error/timeout rate > **1%**, or
- a server resource is pinned (GPU util ~100% with a growing synth backlog / any CPU thread-set saturated / RAM exhaustion / swap).

**Knee:** the highest concurrency step that still passes all criteria — the reported "max sustainable concurrency."

Latency is recorded as p50/p95/p99 + max per step.

## 4. Observation architecture

Two independent observation planes, both off the load-generation critical path:

1. **Server-side resource sampler** (SSH, run by Claude): a shell loop sampling `nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw` + `docker stats --no-stream` for the hotline/model containers every 2 s → CSV under a per-run dir on the server, pulled back to the Mac after each run. GPU is the headline metric.
2. **Client-side latency** (Mac): each load client records its own per-request timings (connect, TTFB, total) → JSON/CSV per step. For Phase B, agent-internal per-stage latency (STT/LLM/TTS/e2e) is read post-run from Mongo `session_metrics` via the existing `noble_agent.metrics.reporter.aggregate_report()`, windowed to the run; Phoenix supplies LLM span detail.

Each run writes one artifact dir: client CSVs + server sampler CSV + an aggregated `RESULTS.md` step table.

## 5. Phase A — per-service isolation (no server change)

Directly saturate each model service; no LLM, no transport, no `.env` change. Highest signal-to-effort — likely answers the core "how many concurrent voice calls" question because the voice ceiling is bounded by TTS-GPU measured here.

**Wire protocol:** reuse `src/noble_agent/voice/service/protocol.py` helpers verbatim (binary frame = PCM int16; text frame = JSON control). Load clients are thin asyncio WS/HTTP clients built directly on `protocol.py` — **not** the `RemoteTTS`/`SherpaSTT` classes, which are shaped for one-synth-per-turn; a tight measurement loop is clearer and avoids per-turn object churn.

| Service | Client action | Primary metric | Ramp (concurrency) |
|---|---|---|---|
| **TTS `:8011`** | open WS, send `synthesize_msg(text, voice)`, drain binary PCM until `{"type":"end"}`; measure TTFB (first PCM byte) + total + realtime-factor | TTFB p95, total p95, **GPU util / synth serialization** | 1 → 2 → 4 → 8 → 16 → … until knee |
| **STT `:8012`** | open WS, stream a fixed PCM utterance in 20 ms frames at realtime pace, send `eos`, wait for `{"type":"final"}`; measure final latency | final-emit p95, **CPU threads** | same ramp |
| **embed `:8013`** | HTTP POST `{"texts":[q],"is_query":true}` + Bearer (`EMBED_REMOTE_TOKEN`); measure round-trip | p95 latency | same ramp |

Fixtures: a representative Vietnamese synth sentence (TTS) and a ~3–5 s PCM utterance (STT) — reuse an ack asset from `assets/voice/acks/` (24 kHz PCM). Hold each step ~90 s; ramp until a breaking-point criterion trips. Record the knee + the binding resource per service.

## 6. Phase B — chat WS end-to-end (`:8766`)

N concurrent WS clients to `ws://10.50.12.70:8766/chat?session=<uid-N>` (no token). Each client drives a fixed scripted turn sequence (e.g. greeting → project question → booking-ish turn) and measures per-turn wall-clock (send → `done`). This exercises the full agent turn: orchestrator + Redis (3-key state) + Mongo + Qdrant + embed + LLM.

**LLM handling:** stubbed (§7) so the measured ceiling is the agent/orchestration + stores, not gemini rate limits or cost. Agent-side per-stage latency read from Mongo post-run.

Same ramp + 90 s hold + knee methodology as Phase A. Binding resource is expected to be CPU (agent process orchestration + Qdrant/embed) rather than GPU.

## 7. LLM stub (Phase B only)

Isolate infra by replacing gemini with a deterministic fake, reversibly:

- Run a minimal **OpenAI-compatible streaming server** (single-file `aiohttp`/`fastapi`) that answers `POST /v1/chat/completions` with `stream=true`, emitting a canned Vietnamese answer as SSE token deltas paced at ~50 tok/s (realistic pipeline timing without external variance). Host it where the server can reach it (on the box, or on the Mac at `http://10.50.12.206:<port>` — server→Mac LAN reachability to be confirmed at setup; on-box is the safe default).
- On the server, point the agent's **OpenAI slot** at it and pin it primary: set `OPENAI_BASE_URL=http://<stub-host>:<port>/v1`, `OPENAI_MODEL=<stub-model>`, `NOBLE_AGENT_MODEL=<stub-model>`; then `docker compose -f docker-compose.local.yml up -d agent agent-lk` to recreate (editing `.env` alone does not restart — per deploy topology).
- **Revert** after Phase B: restore the original `.env` values + recreate. The original `.env` is backed up before the edit.

The stub is opt-in and confined to Phase B; Phase A never touches the agent config.

## 8. Run procedure (per phase, per step)

1. Confirm idle baseline (loadavg, GPU 0%, no competing load).
2. Start the server sampler (SSH, background) into the run dir.
3. Warm-up call at concurrency 1 → record warm baseline.
4. For each concurrency step: ramp clients, hold ~90 s, record steady-state client latency; watch sampler live for saturation.
5. Stop at the first step tripping a breaking-point criterion; record the knee.
6. Stop sampler; pull CSVs; aggregate Mongo window (Phase B); write `RESULTS.md`.

## 9. Deliverable

A capacity report (`docs/…/load-capacity-report-2026-07-14.md` or similar) covering, per channel:
- warm baseline vs knee (max sustainable concurrency),
- the **binding constraint** (which resource saturated, with sampler evidence),
- headroom framing (what the knee implies for concurrent-call capacity given a per-call resource profile),
- recommendations (e.g. if TTS-GPU is the ceiling: micro-batching, a second GPU, quantized/faster codec, or a hard cap on concurrent audio sessions).

## 10. Safety & cleanup

- No real traffic in the test window (confirmed). Free to push services to failure/restart.
- Revert the Phase B `.env` stub + recreate `agent`/`agent-lk`; verify `/api/config` shows `gemini-2.5-flash` again.
- Stop the SSH sampler; remove server-side run dirs after pulling artifacts.
- Note co-tenancy: heavy hotline load competes with `santa-chat-agent` for the same 20 threads — flag any cross-impact in the report.
- SSH credential handling: used only for sampling + the reversible stub reconfigure; never echoed into artifacts.

## 11. Phase C — end-to-end voice ceiling (in scope)

Phase A derived the voice ceiling from TTS-GPU math (~8–12 practical / ~20 theoretical concurrent calls). Phase C **measures it directly** by driving synthetic voice calls through the real transports, and reveals any limit the transport layer adds *before* the GPU (aiortc handshake capacity; the LiveKit worker's per-job subprocess RAM/CPU). Build order (approved): **aiortc first, then LiveKit** — aiortc `:8766` is a clean LAN-only measure of the server STT→LLM→TTS ceiling with no LiveKit-Cloud variable; LiveKit then gives the production-path number + the worker-pool limit. Both transports converge on the same remote STT `:8012` + TTS `:8011`, so both hit the shared GPU ceiling.

### 11.1 What "breaking" means for voice (distinct from A/B)

Voice degradation is **audio-quality**, not throughput/error-rate. Per concurrent call, per turn:

- **turn TTFA** — wall time from end-of-caller-utterance to first agent audio frame (primary signal). Also record **greet TTFA** (the auto-greet after connect).
- **audio underruns** — count of gaps > ~150 ms *inside* an agent utterance in the received stream (detected by RMS-energy gating on received frames). This is the "choppy audio" signal Phase A predicts at ~8–12 calls.
- **dropped/failed calls** — connect failure, track never arrives, or call teardown error.

**Breaking point:** the lowest concurrent-call count where any holds over a ~60–90 s hold: turn-TTFA p95 > **2× warm baseline** (or absolute > 2.5 s), **or** underruns appear on ≥1 call, **or** failed-call rate > 1%. **Knee** = highest step still passing. Ramp is voice-scaled: `1, 2, 4, 6, 8, 10, 12, 16` (Phase A puts the cliff at ~8–12; go a bit past to confirm the vertical wall — not the `→128` of A/B).

### 11.2 Driving a call

Each concurrent call is a long-lived session running a turn-taking script:

1. connect (aiortc: `rtc_offer`→`negotiate`→answer; LiveKit: mint token → join room `session_id`). Agent auto-greets → record greet TTFA.
2. loop until `hold_s`: publish one real Vietnamese utterance (~2–4 s of actual Luna-voice speech from `assets/voice/acks/`, so the server VAD/STT endpoint fires) followed by trailing silence; wait for the agent audio track to start (→ turn TTFA) then fall quiet (turn done); short gap; repeat.

**LLM = stub** (§7, the approved "isolate infra" choice) so the ceiling reflects transport + STT + TTS + orchestration, not gemini. The stub is extended to emit 2–3 varied-length Vietnamese sentences so the sentence-buffer → multi-clause TTS load is realistic. (Voice reuses the same stub + revert checklist as Phase B.)

### 11.3 Architecture

A transport-agnostic call driver over a thin adapter interface — one driver, two adapters — so the campaign runner and metrics are shared:

- `voice_call.py` — the call script + per-turn/underrun metrics + the adapter `Protocol` (`connect()`, `publish_utterance(pcm)`, `on_agent_audio(cb)`, `close()`).
- `transport_aiortc.py` — aiortc `RTCPeerConnection` **client**: publishes a `MediaStreamTrack` sourced from the utterance fixture (aiortc negotiates Opus), signals `rtc_offer` over WS `:8766`, subscribes to the agent's returned `ServerAudioTrack`.
- `transport_livekit.py` — `livekit.rtc` client: token minted with `livekit-api` + `LIVEKIT_API_KEY/SECRET` from `.env` (room = `session_id`; worker auto-dispatches because `LIVEKIT_AGENT_NAME` is empty), publishes an audio track, subscribes to the agent participant's track.
- `phase_c_voice.py` — campaign runner: ramp + hold + knee (`--transport aiortc|livekit`), writes `out/phaseC/voice_<transport>_RESULTS.md`. Reuses `common.percentiles`/`knee_by_plateau`; the results table gains voice columns (greet TTFA, turn TTFA p50/p95, underruns, failed calls).
- A voice fixture built from an ack asset (speech + trailing silence, at the frame format each transport wants: aiortc 48 kHz mono for Opus; LiveKit PCM16 frames).

Server-side sampling reuses `sampler.sh` (`nvidia-smi` + `docker stats`) to correlate the client TTFA/underrun curve with GPU util and the TTS + worker container CPU/RAM.

### 11.4 Risks

- **LiveKit Cloud plan cap** may trip *before* the GPU (max rooms/participants). If so it's a real finding (Cloud is the production media plane) — record it; optionally fall back to the self-hosted LiveKit in `docker-compose.deploy.yml` to isolate the server ceiling.
- **VAD must fire on synthetic audio** → the fixture must be genuine speech (Luna TTS) + trailing silence; precedent = `fixture_16k.pcm`.
- **"First agent frame" detection** uses a simple RMS threshold to separate silence from speech on the received track; the same gate counts mid-utterance underruns.
- **aiortc-as-client Opus**: aiortc auto-encodes a raw PCM track to Opus on negotiation; the client feeds 48 kHz mono frames.

## 12. Module / file layout (proposed)

```
scripts/load_test/v2/            # new; the sipp-era scripts/load_test/*.py stays untouched
├── common.py                    # ramp loop, step timing, percentile calc, RESULTS.md writer
├── sampler.sh                   # server-side nvidia-smi + docker stats → csv (run over SSH)
├── phase_a_tts.py               # WS load client for :8011  (uses voice/service/protocol.py)
├── phase_a_stt.py               # WS load client for :8012
├── phase_a_embed.py             # HTTP load client for :8013
├── phase_b_chat.py              # WS load client for :8766 /chat
├── llm_stub.py                  # OpenAI-compatible streaming fake (Phase B + C)
├── voice_call.py                # Phase C: transport-agnostic call driver + adapter Protocol + metrics
├── transport_aiortc.py          # Phase C: aiortc RTCPeerConnection client (:8766 rtc_offer)
├── transport_livekit.py         # Phase C: livekit.rtc client (token + room join)
├── phase_c_voice.py             # Phase C: campaign runner (--transport aiortc|livekit)
└── README.md                    # run recipes + revert checklist
```

Percentile/ramp helpers are pure and unit-testable; the network clients are integration-only (need live services). Phase C adds pure helpers too — the RMS energy-gate (first-frame + underrun detection) and the voice results-table writer — which are unit-tested in `test_common.py` alongside the existing helpers.
