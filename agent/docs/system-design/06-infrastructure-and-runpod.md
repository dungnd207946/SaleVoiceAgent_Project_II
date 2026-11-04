# 06 — Infrastructure & RunPod Deployment

> Three deployment shapes: local dev (Docker compose + agent on host), AWS EC2 (Mongo/Redis/Qdrant shared services), and RunPod single-pod GPU (vLLM + agent + Redis on one box). Setup is one script (`infra/runpod/setup.sh`, ~25 min on a fresh pod). Env vars are grouped by component; secrets never enter git.

Read [`00-architecture-overview.md`](00-architecture-overview.md) §5 for the port map first.

---

## 1. Deployment shapes

### 1.1 Local dev (host machine)

```
[Host Mac/Linux]
  python -m venv .venv (or uv sync) → ~5 min
  docker compose up -d redis mongodb        # storage on local Docker
  scripts/run.sh                            # agent on port 8766
  ↓ open http://localhost:8766              # browser test
```

For end-to-end tests including LLM, set `OPENAI_API_KEY` + `SONIOX_API_KEY`. Vector store optional (`NOBLE_RAG_BACKEND=empty` for offline).

### 1.2 EC2 (shared services + agent on a phone-capture box)

```
[AWS ec2-47-129-187-61.ap-southeast-1.compute.amazonaws.com]
   • MongoDB :27017
   • Redis   :6379
   • Qdrant  :6333

[Asterisk/FreePBX box voip.noble.vn]
   • port 5060/UDP SIP
   • port 8090/TCP AudioSocket → agent

[Phone-capture EC2 box]
   • noble-agent :8766
   • dials shared services on EC2 above
```

Detail: `docs/deploy-ec2-phone-capture-checklist.md`. EC2 runs `noble-agent` only; LLM is OpenAI cloud.

### 1.3 RunPod single-pod (full stack on 1× GPU)

```
[RunPod pod — RTX PRO 6000 Blackwell 97 GB or H100 SXM 80 GB]
   • vLLM     :8000  (Qwen3.6-35B-A3B, ~70 GB on disk)
   • embed    :8081  (multilingual-e5-large or bge-m3)
   • redis    :6379
   • noble-agent :8082 (livekit transport, no SIP)
```

vLLM serves the LLM tools via OpenAI-compatible HTTP. The agent connects to LiveKit Cloud for browser playback (no AudioSocket / Asterisk in this shape — that's for the EC2 hotline path).

---

## 2. Local dev — quick start

```bash
# 1. Python env (uv preferred — 10× faster than pip)
uv sync --extra dev --extra stt-soniox --extra tts-elevenlabs
# OR fallback:
# python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"

# 2. Storage
docker compose up -d redis mongodb            # add `--profile qdrant` if you want vector DB

# 3. Configure
cp .env.example .env
# Edit: GEMINI_API_KEY (or OPENAI_API_KEY), SONIOX_API_KEY, ELEVENLABS_API_KEY

# 4. Run
scripts/run.sh                                # hot-reload, port 8766
# OR
scripts/run.sh --no-reload
# OR
noble-agent                                   # via installed CLI entry
```

> **Operator env preference**: project owner uses `conda activate test-voice-alt`. `.venv/` and `uv` paths exist but are **not** the working environment. Override defaults in `.env`; don't `source .venv/bin/activate` in production scripts.

Open `http://localhost:8766/` for the browser tester.

---

## 3. RunPod — the one-script deploy

File: `infra/runpod/setup.sh`. 13 stages, idempotent, safe to re-run.

### 3.1 TL;DR — fresh pod → running in 3 commands

```bash
ssh root@<pod_ip> -p <ssh_port> -i ~/.ssh/id_ed25519
```

```bash
cd /workspace && git clone https://oauth2:<GITLAB_PAT>@gitlab.noble.vn/.../santa-hotline-agent.git && cd santa-hotline-agent && cp infra/runpod/env.runpod.example .env && nano .env
```

(In nano: set `HF_TOKEN=hf_...`, save with Ctrl+O Enter Ctrl+X.)

```bash
bash infra/runpod/setup.sh
```

`setup.sh` runs ~25 minutes (most of it is the 70 GB Qwen3.6 model pull). At the end it prints `URL + ROOM + TOKEN` for the LiveKit Playground (https://agents-playground.livekit.io/) — paste, click Connect, talk.

### 3.2 Pod spec (RunPod console)

| Field | Value |
|---|---|
| GPU | 1× RTX PRO 6000 Blackwell 97 GB (or H100 SXM 80 GB with `MAX_MODEL_LEN=16384`) |
| Template | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` |
| Pricing | **On-Demand** (Spot gets reclaimed mid-call) |
| Container Disk | 50 GB |
| Volume Disk | 150 GB (model 70 GB + deps + data) |
| Expose HTTP | `8000` (vLLM) |
| Expose TCP | `22` (SSH) |
| Env vars | **leave empty** in console (RunPod UI duplicates whitespace values) |

### 3.3 setup.sh stages

| # | Stage | What |
|---|---|---|
| 0 | `preflight` | GPU present, disk free, git working |
| 1 | `system` | apt-install tmux, redis, ffmpeg, python3.11, build-essential |
| 2 | `uv` | install `uv` (10× pip) |
| 3 | `vllm_pkg` | system Python: `vllm>=0.17.0, <0.20`, transformers, hf-transfer, flashinfer; create `/opt/vllm-venv` with `--system-site-packages` |
| 4 | `agent_venv` | `uv sync --extra stt-soniox --extra tts-elevenlabs` → `.venv` |
| 5 | `data` | check `data/{rag,flat_store,faq_cache}`; auto `hf-download` from `NOBLE_DATA_HF_REPO` |
| 6 | `model` | `hf download Qwen/Qwen3.6-35B-A3B` (~70 GB, ~10–15 min) |
| 7 | `embeddings` | pre-cache fastembed e5-large ONNX (~500 MB) |
| 8 | `patches` | apply streaming.py + tool_hint.py vLLM-compat patches (idempotent) |
| 9 | `paths` | symlink `data/faq/source/*_faq.json → data/faq/*` |
| 10 | `env` | apply pod overrides (TELEPHONY_ENABLED=false, port 8082, vLLM endpoint…) — does NOT overwrite your `.env` |
| 10.5 | `migrate` | `mongo_migrate_noble_profile.py` + `mongo_migrate_outbound.py` — idempotent indexes/TTL |
| 11 | `services` | start redis + tmux:vllm + tmux:agent |
| 12 | `verify` | wait vLLM ready (15 min cap) + agent registered (60 s) |
| 13 | `connect` | print `URL + ROOM + TOKEN` ready to paste |

### 3.4 Two virtualenvs, why

`pyproject.toml` (committed) → `.venv` via `uv sync` — same on Mac and pod (project deps).

`infra/runpod/requirements-pod.txt` (committed) → `/opt/vllm-venv` via `uv pip install -r` — pod-only (vllm/flashinfer/hf-transfer; need CUDA, can't install on Mac).

`/opt/vllm-venv` uses `--system-site-packages` to inherit pod-image CUDA torch (avoids re-downloading 8 GB). `start_vllm.sh` invokes `$VLLM_VENV/bin/python`.

### 3.5 Data sync — three modes

`scripts/data_sync.sh` manages 3 gitignored folders: `data/rag` (~82 MB) + `data/flat_store` (~36 MB) + `data/faq_cache` (~1.7 MB). Total ~120 MB.

| Mode | When | Mac side | Pod side |
|---|---|---|---|
| `consolidate + push` | Dev iter, sibling repos available | `data_sync.sh consolidate && data_sync.sh push <ip> <port>` | (auto when `setup.sh` finds data) |
| **HF Dataset** ⭐ | Prod, multiple pods | `data_sync.sh consolidate && data_sync.sh hf-upload <repo>` (one-time) | `NOBLE_DATA_HF_REPO=<repo> bash setup.sh` |
| `rebuild` | No Mac, no cloud, only `data/rag` | — | `data_sync.sh rebuild` (~30 min CPU) |

HF Dataset is the path most pods take after the first one. One private dataset, every pod pulls.

### 3.6 Operator commands (`scripts/noble-pod`)

```bash
noble-pod doctor              # health check (vLLM ready? agent connected? redis up?)
noble-pod logs --watch        # live tail filtered (no spam)
noble-pod metrics             # latest TTFT/TTFA/fallback aggregates
noble-pod connect             # print URL+TOKEN again
noble-pod restart             # restart agent only (keeps vLLM running)
```

These wrap `tmux send-keys` and Mongo queries. Read `scripts/noble-pod` if you need to extend.

---

## 4. Environment variables — by component

`src/noble_agent/config.py` is the canonical schema. Group below maps to the section header in `.env.example`.

### 4.1 LLM

```bash
OPENAI_API_KEY=                      # required if STT_BACKEND uses Whisper or LLM is OpenAI
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-5.4-nano-2026-03-17
OPENAI_REASONING_EFFORT=none         # none|low|medium|high
GEMINI_API_KEY=                      # fallback or primary
GEMINI_MODEL=gemini-2.5-flash
DASHSCOPE_API_KEY=                   # Qwen via DashScope
DASHSCOPE_BASE_URL=
```

For RunPod (local vLLM):

```bash
OPENAI_BASE_URL=http://localhost:8000/v1
OPENAI_MODEL=Qwen/Qwen3.6-35B-A3B
OPENAI_API_KEY=dummy
```

### 4.2 STT / VAD / Smart Turn

```bash
STT_BACKEND=soniox                   # sherpa|soniox|qwen3asr|elevenlabs
SONIOX_API_KEY=
SONIOX_MODEL=stt-rt-v4
SHERPA_MODEL_DIR=
SHERPA_HOTWORDS_FILE=data/hotwords.txt
QWEN3ASR_VLLM_URL=http://localhost:8000

VAD_SILENCE_MS=400                   # 700 for browser, 400 for telephony
VAD_MIN_SPEECH_MS=250
VAD_CHUNK_MS=32
VAD_INTERRUPT_CONFIRM_CHUNKS=3

SMART_TURN_ENABLED=false
SMART_TURN_MODEL_PATH=
SMART_TURN_THRESHOLD=0.5
```

Detail per setting → [`01-stt-and-vad.md`](01-stt-and-vad.md).

### 4.3 TTS

```bash
TTS_BACKEND=elevenlabs               # vieneu|elevenlabs
ELEVENLABS_API_KEY=
ELEVENLABS_TTS_VOICE_ID=
ELEVENLABS_TTS_MODEL=eleven_flash_v2_5
ELEVENLABS_TTS_LANGUAGE_CODE=vi
ELEVENLABS_TTS_STABILITY=0.5
ELEVENLABS_TTS_SIMILARITY_BOOST=0.75
ELEVENLABS_TTS_SPEED=1.0
VIENEU_BACKBONE_REPO=                # local GGUF dir or HF repo
VIENEU_VOICE_ID=
```

### 4.4 Storage

```bash
REDIS_URL=redis://localhost:6379/0
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=noble_voice_agent
QDRANT_URL=http://localhost:6333    # optional, fallback only
QDRANT_API_KEY=
```

For shared EC2 services replace localhost with `ec2-...:port`.

### 4.5 RAG

```bash
NOBLE_RAG_BACKEND=flat_store         # flat_store|memory_router|empty
FLAT_STORE_SKIP_FAQ=true
FAQ_INJECT_IN_PROMPT=true
FAQ_SEMANTIC_INJECT_ENABLED=true
FAQ_SEMANTIC_THRESHOLD=0.45
FAQ_SEMANTIC_TOP_K=5
SLOW_THINKER_ENABLED=true
SLOW_THINKER_MODEL=gpt-4o-mini
SEMANTIC_CACHE_TTL_S=300
EMBEDDING_MODEL=intfloat/multilingual-e5-large
```

### 4.6 Transport

```bash
WS_HOST=0.0.0.0
WS_PORT=8766
TRANSPORT_BACKEND=aiortc             # aiortc (browser/SIP) | livekit (RunPod cloud)
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
LIVEKIT_AGENT_NAME=noble-hotline-agent
WORKER_MAX_CONCURRENT_SESSIONS=50
```

### 4.7 Telephony (only when on the EC2 phone-capture path)

```bash
TELEPHONY_ENABLED=true
ASTERISK_ARI_HOST=voip.noble.vn
ASTERISK_ARI_PORT=8088
ASTERISK_ARI_USER=noble-voice-agent
ASTERISK_ARI_PASS=
AUDIOSOCKET_PORT=8090
TELEPHONY_SAMPLE_RATE=8000
```

Detail → [`07-freepbx-asterisk-bridge.md`](07-freepbx-asterisk-bridge.md).

### 4.8 Profile / outreach / SMS / email

`NOBLE_PROFILE_*`, `HOTLINE_OUTREACH_*`, `EMAIL_*`. See `.env.example`. Most are optional features gated behind `*_ENABLED` flags.

---

## 5. Secrets — what NOT to commit

`.gitignore` covers:

- `.env`, `.env.local`, `.env.runpod` (all variants)
- `data/flat_store/`, `data/faq_cache/`, `data/rag/`, `data/vieneu_voices/`
- `runs/` (eval artifacts)
- `.claude/`, `.omc/`, `.cursor/` (per-user agent state)

If you ever see `OPENAI_API_KEY=sk-...` in a diff, **stop and rewrite history** before pushing. The HF token is the most-leaked one — keep it in `.env` only.

`infra/runpod/env.runpod.example` ships **example values for shared services** but real keys belong nowhere in git. The example file uses placeholders like `<MONGO_PASSWORD>` deliberately.

---

## 6. Scaling & multi-pod

Single pod handles ~50 concurrent voice sessions (`WORKER_MAX_CONCURRENT_SESSIONS=50`). Beyond that:

1. **Shared MongoDB + Redis + Qdrant on EC2** — every pod points at the same shared instances. Data stays consistent.
2. **Multiple LiveKit-connected pods** — LiveKit dispatch routes new rooms to whichever pod has capacity. No coordination needed; pods are stateless w.r.t. sessions.
3. **vLLM is per-pod** — model weights are 70 GB. Sharing across pods would need an inference cluster (vLLM + Ray or Triton). Not on the roadmap.

For deeper scaling pattern → `docs/runbooks/runpod.md` §3.

---

## 7. Observability

| Signal | Where |
|---|---|
| Per-turn TTFT/TTFA | MongoDB `session_metrics` collection (`metrics/store.py`) |
| Live logs (filtered) | `noble-pod logs --watch` or `journalctl -u noble-agent -f` |
| LLM trace | Langfuse (every LLM call traced when `LANGFUSE_*` env set) |
| Audio underrun count | `session_metrics.audio_underrun_count` per session |
| Cost (judge LLM) | `runs/<id>/report.json:judge_stats.cost_usd` (eval only) |

Cost tracker for LLM in production runs through OpenAI billing dashboard — no per-call cost tracking in `session_metrics` (yet).

---

## 8. Common debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| `setup.sh` stuck on stage 6 | HF token missing or rate-limited | Verify `HF_TOKEN` in `.env`; HF model pulls under `HF_HUB_ENABLE_HF_TRANSFER=1` |
| vLLM OOM at startup | `MAX_MODEL_LEN` too high for GPU | Drop to 16384 on H100 80 GB; default 32768 only fits 97 GB |
| Agent connects but no audio | `TRANSPORT_BACKEND=aiortc` on RunPod | Switch to `livekit` (RunPod has no public SIP) |
| pod loses connection mid-call | Spot pod reclaimed | Use On-Demand pricing |
| `setup.sh` re-runs hangs at stage 5 | leftover partial download | `rm -rf data/{rag,flat_store,faq_cache}` and re-run |
| `noble-pod doctor` says "agent dead" | tmux session died | `noble-pod restart`; check `tmux attach -t agent` for stack trace |
| Mongo migrations time out (stage 10.5) | EC2 Mongo unreachable | confirm security group allows pod IP on 27017 |

---

## 9. References

- `infra/runpod/SETUP.md` — full deploy guide + troubleshooting + `noble-pod` CLI
- `infra/runpod/setup.sh` — the script itself
- `docs/runbooks/runpod.md` — strategy, scale patterns, limits, stress-test checklist
- `docs/deploy-ec2-phone-capture-checklist.md` — EC2 telephony deploy

Continue → [`07-freepbx-asterisk-bridge.md`](07-freepbx-asterisk-bridge.md) for the phone path.
