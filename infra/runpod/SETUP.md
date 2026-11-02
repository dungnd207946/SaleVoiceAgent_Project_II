# RunPod Deployment — 1-Pod Setup

Triển khai full stack (vLLM Qwen3.6-35B-A3B + noble-agent + Redis) lên **1 GPU pod** thông qua **1 script duy nhất**: `infra/runpod/setup.sh`.

---

## TL;DR — Pod tươi → đang chạy (3 lệnh)

```bash
# 1. SSH vào pod
ssh root@<pod_ip> -p <ssh_port> -i ~/.ssh/id_ed25519

# 2. Clone + setup .env
cd /workspace && git clone https://oauth2:<GITLAB_PAT>@gitlab.noble.vn/.../santa-hotline-agent.git && cd santa-hotline-agent && cp infra/runpod/env.runpod.example .env && nano .env
#    Trong nano: chỉnh HF_TOKEN=hf_... rồi Ctrl+O Enter Ctrl+X

# 3. Bootstrap (đọc HF_TOKEN + NOBLE_DATA_HF_REPO từ .env tự động)
bash infra/runpod/setup.sh
```

**Hoặc skip nano** nếu bạn có sẵn .env trên Mac:
```bash
# Mac:
scp -P <ssh_port> -i ~/.ssh/id_ed25519 .env root@<pod_ip>:/workspace/santa-hotline-agent/.env
# Pod:
cd /workspace/santa-hotline-agent && bash infra/runpod/setup.sh
```

**Lưu ý**: KHÔNG `cp env.runpod.example .env` SAU khi `scp` — sẽ ghi đè .env thật bằng template.

`setup.sh` mất ~20-25 phút (đa phần là 70GB Qwen3.6 model). Khi xong, **script in URL + ROOM + TOKEN** → copy vào https://agents-playground.livekit.io/ → kết nối → nói thử.

---

## Pod tươi: cần gì? (full lifecycle)

### 1. Tạo pod (RunPod Console)

| Field | Value |
|-------|-------|
| GPU | 1× RTX PRO 6000 Blackwell 97GB (hoặc H100 SXM 80GB với MAX_MODEL_LEN=16384) |
| Template | `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` |
| Pricing | **On-Demand** (Spot bị reclaim giữa demo) |
| Container Disk | 50 GB |
| Volume Disk | 150 GB (model 70GB + deps + data) |
| Expose HTTP | `8000` |
| Expose TCP | `22` |
| Env Vars | **để trống** (RunPod UI có bug duplicate giá trị có whitespace) |

Click Deploy → đợi `Running` → ghi nhận `<pod_ip>:<ssh_port>` ở tab Connect.

### 2. Data — chọn nguồn

`scripts/data_sync.sh` quản lý 3 thư mục gitignored: `data/rag` (~82MB) + `data/flat_store` (~36MB) + `data/faq_cache` (~1.7MB) — tổng ~120MB.

**Tại sao gitignored**: `rag/` là source từ sibling repo (license-restricted), `flat_store/` + `faq_cache/` là derived (.npy/BM25 binary, không hợp git).

**Chọn 1 trong 3**:

| Mode | Khi dùng | Lệnh Mac | Lệnh Pod |
|------|----------|----------|----------|
| **consolidate + push** | Dev iter, có sibling repos | `bash scripts/data_sync.sh consolidate && bash scripts/data_sync.sh push <ip> <port>` | (auto khi setup.sh thấy data sẵn) |
| **HF Dataset** ⭐ | Prod, nhiều pod, no Mac dependency | `data_sync.sh consolidate && data_sync.sh hf-upload <repo>` (1 lần) | `NOBLE_DATA_HF_REPO=<repo> bash setup.sh` |
| **rebuild** | No Mac, no cloud, có rag/ | — | `data_sync.sh rebuild` (~30 phút CPU) |

**Setup HF Dataset** (đường B, 1 lần đầu):

```bash
hf auth login                                          # Mac, paste HF token
bash scripts/data_sync.sh consolidate                  # gom từ sibling
bash scripts/data_sync.sh hf-upload your-org/santa-data-private
# → tạo private dataset, upload 3 thư mục
```

Sau đó pod mới chỉ cần:
```bash
hf auth login                                          # paste cùng token (read access)
NOBLE_DATA_HF_REPO=your-org/santa-data-private bash infra/runpod/setup.sh
```

### 3. (chỉ đường A) Push data Mac → Pod

```bash
bash scripts/data_sync.sh push <pod_ip> <ssh_port>
# rsync 3 thư mục, resume-friendly nếu mạng đứt
```

### 4. (Pod) Clone repo

Mở SSH (`ssh root@<pod_ip> -p <port>`) hoặc Web Terminal:

```bash
cd /workspace
git clone https://oauth2:<GITLAB_PAT>@gitlab.noble.vn/fintech-and-ai-development-center/ai-projects/santa-project/santa-hotline-agent.git
cd santa-hotline-agent
git checkout feat/summarization-context   # hoặc branch của bạn
```

### 5. (Pod) Chạy 1 lệnh duy nhất

```bash
bash infra/runpod/setup.sh
```

13 stage tuần tự — idempotent, an toàn re-run:

| # | Stage | Việc |
|---|-------|------|
| 0 | preflight | check GPU + disk + git |
| 1 | system | apt: tmux, redis, ffmpeg, python3.11, build-essential |
| 2 | uv | install `uv` (10× faster pip) |
| 3 | vllm_pkg | system Python: `vllm>=0.17.0` + transformers + hf-transfer + flashinfer |
| 3 | vllm_pkg | `uv venv --system-site-packages /opt/vllm-venv` + `uv pip install -r infra/runpod/requirements-pod.txt` (vllm/flashinfer/hf-transfer — pod-only) |
| 4 | agent_venv | `uv sync --extra stt-soniox --extra tts-elevenlabs` → `.venv` (project deps từ pyproject) |
| 5 | **data** | check `data/{rag,flat_store,faq_cache}`; auto `hf-download` từ `NOBLE_DATA_HF_REPO` |
| 6 | model | `hf download Qwen/Qwen3.6-35B-A3B` (~70GB, ~10-15 phút) |
| 7 | embeddings | pre-cache fastembed e5-large ONNX (~500MB) |
| 8 | patches | apply streaming.py + tool_hint.py vLLM-compat patches (idempotent) |
| 9 | paths | symlink `data/faq/source/*_faq.json → ../*` |
| 10 | env | apply pod overrides (TELEPHONY=false, port 8082, vLLM endpoint…) — không ghi đè .env |
| 10.5 | **migrate** | `mongo_migrate_noble_profile.py` + `mongo_migrate_outbound.py` — idempotent indexes/TTL trên MongoDB |
| 11 | services | redis + tmux:vllm + tmux:agent |
| 12 | verify | đợi vLLM ready (15min max) + agent registered (60s) |
| 13 | connect | **in URL + ROOM + TOKEN** sẵn để paste |

> **2 venv, 2 declarative source — đều `uv` engine**:
> - `pyproject.toml` (commit) → `.venv` qua `uv sync` — Mac + pod giống nhau
> - `infra/runpod/requirements-pod.txt` (commit) → `/opt/vllm-venv` qua `uv pip install -r` — chỉ pod
> - vLLM-only deps không vào pyproject vì chúng cần CUDA → Mac không install được

> **uv compliance** (Ubuntu 24.04 + Python 3.12): `/opt/vllm-venv` dùng `--system-site-packages` để kế thừa CUDA torch sẵn của pod image (không re-download 8GB), và để tôn trọng PEP 668 EXTERNALLY-MANAGED của system Python. `start_vllm.sh` tự dùng `$VLLM_VENV/bin/python`.

> **`.env` safe-load**: `setup.sh` parse `.env` qua pure-bash loop (không `source` để tránh exec value có space, e.g. `EMAIL_APP_PASSWORD=kkos vwqi qvvs jykw`). Mọi env var trong `.env` (HF_TOKEN, NOBLE_DATA_HF_REPO, HF_MODEL_REPO…) tự propagate xuống stages — không cần inline `KEY=val bash setup.sh`.

> **PATH boost**: sau stage 3, `setup.sh` prepend `$VLLM_VENV/bin` vào PATH → `hf` CLI + `huggingface_hub` Python module dùng được trong stage 5 (model download), data_sync.sh, v.v.

Output cuối:

```
URL:   wss://santahotlin-d1hph5oo.livekit.cloud
ROOM:  smoke
TOKEN: eyJhbGciOiJIUzI1NiIsInR5cCI...

▶ https://agents-playground.livekit.io/
  Settings → Manual → paste URL + Token → Connect
```

### 6. Test

Vào Playground → Settings ⚙ → Manual connection → paste URL + Token → Connect → Allow microphone → nói thử *"Giới thiệu dự án Noble Crystal Long Biên"*.

---

## Pod đã setup rồi: cập nhật code

```bash
cd /workspace/santa-hotline-agent && git pull && bash scripts/noble-pod restart
```

Hoặc qua GitLab CI: push branch `feat/deploy-runpod` → job `deploy:runpod` tự `git pull + setup.sh --only patches + agent_venv + services` (xem `.gitlab-ci.yml`).

---

## Cờ tiện ích cho `setup.sh`

```bash
bash infra/runpod/setup.sh --check          # dry-run, không edit/install gì
bash infra/runpod/setup.sh --no-model       # cloud LLM only (skip vLLM)
bash infra/runpod/setup.sh --no-services    # provision only, không start
bash infra/runpod/setup.sh --only env       # 1 stage
bash infra/runpod/setup.sh --from services  # resume từ stage X
bash infra/runpod/setup.sh --skip model     # bỏ stage này

# GPU < 24GB → model nhỏ:
HF_MODEL_REPO=Qwen/Qwen2.5-14B-Instruct bash infra/runpod/setup.sh --from model
```

---

## Logs

| File | Nội dung |
|------|----------|
| `/workspace/logs/setup-YYYYMMDD-HHMMSS.log` | Toàn bộ output `setup.sh` (tee) |
| `/workspace/vllm.log` | vLLM server (Qwen3.6 + tool parser + Uvicorn) |
| `/workspace/agent.log` | noble-agent worker (TTFT, TTFA, fallback, tool calls) |

---

## CLI ops

`scripts/noble-pod` là CLI cho mọi thao tác sau setup:

```bash
noble-pod doctor              # health check 1 dòng/check
noble-pod start | stop | restart
noble-pod logs --watch        # live tail filtered
noble-pod logs --ttft         # TTFT events (>1s đỏ)
noble-pod logs --fallback     # cloud-fallback events
noble-pod logs --turns        # per-turn pretty summary
noble-pod metrics             # tổng hợp TTFT/TTFA/fallback từ agent.log
noble-pod token [room]        # gen LiveKit JWT bất cứ lúc nào
noble-pod connect [room]      # in URL+TOKEN format paste-into-Playground
noble-pod bench "câu test"    # đo TTFT vLLM trực tiếp
noble-pod model info|test     # vLLM model info + tool-call test
noble-pod env show|edit|set K=V|reload
noble-pod ports               # ss -tlnp filter cổng quan trọng
noble-pod setup [args]        # alias cho infra/runpod/setup.sh
```

Symlink để gõ ngắn:

```bash
ln -sf /workspace/santa-hotline-agent/scripts/noble-pod /usr/local/bin/noble-pod
```

---

## Architecture (1-pod)

```
┌──────────────────────────────────────────────────────────────────┐
│ 1× RunPod Pod (RTX PRO 6000 97GB, ~$1.89/h on-demand)            │
│                                                                   │
│  tmux:vllm   → vLLM OpenAI server :8000                          │
│                  • model /workspace/Qwen3.6-35B-A3B (~70GB VRAM) │
│                  • --tool-call-parser qwen3_coder                │
│                  • thinking=false                                │
│                                                                   │
│  tmux:agent  → noble-agent --transport livekit                   │
│                  • FlatStore e5-large (load .npy ~5s)            │
│                  • Silero VAD + fastembed + FAQ searcher         │
│                  • health :8082 (LIVEKIT_WORKER_PORT)            │
│                                                                   │
│  redis-server :6379   (session state, agent tracker)             │
│                                                                   │
│  /workspace/santa-hotline-agent/                                 │
│   ├── .venv/        (uv sync — CPU torch, 230 packages, ~950MB) │
│   ├── .env          (API keys, vLLM endpoint, overrides)        │
│   └── data/                                                      │
│       ├── rag/         (~82M, gitignored — pushed from Mac)     │
│       ├── flat_store/  (~36M, gitignored)                       │
│       ├── faq_cache/   (~1.7M, gitignored)                      │
│       └── faq/, faq.json (committed)                            │
└──────────────────────────────────────────────────────────────────┘
            │ outbound TLS only
            ▼
  LiveKit Cloud  • MongoDB Atlas  • Cloud LLM fallback (Gemini/Soniox/ElevenLabs)
            ▲ WebRTC
            │
        Browser (LiveKit Playground)
```

Tại sao 1 pod thay vì tách microservices: RunPod không cho Docker-in-Docker; RTX PRO 6000 dư thừa RAM/CPU cho agent CPU workload; latency localhost ~0.1ms; chi phí thấp hơn ~15%.

---

## Troubleshoot nhanh

| Triệu chứng | Sửa |
|-------------|-----|
| `RuntimeError: NVIDIA driver too old (found version 12080)` | vllm 0.20+ cần CUDA 13. Pod CUDA 12.8 → pin `vllm<0.20.0` (default trong `requirements-pod.txt`) + `UV_TORCH_BACKEND=cu128`. Re-run: `rm -rf /opt/vllm-venv && bash infra/runpod/setup.sh --from vllm_pkg` |
| `Engine core initialization failed` (multi-GPU pod) | OOM single-GPU. setup.sh tự detect và set `TENSOR_PARALLEL=$GPU_COUNT`. Override: `TENSOR_PARALLEL=2 bash infra/runpod/setup.sh --from services` |
| `vLLM not on :8000` | `tail /workspace/vllm.log` — thường model dir LFS pointer (`cd $MODEL_DIR && git lfs pull`) hoặc OOM |
| `[ToolHint] Pre-compute failed: 404` | Set `OPENAI_EMBEDDING_API_KEY=sk-...` thật trong `.env` (vLLM không có /v1/embeddings) |
| `Falling back from openai` | Patch chưa apply: `bash infra/runpod/setup.sh --only patches` |
| `[V10] FAQ semantic inject error: NO_SUCHFILE` | e5-large ONNX miss: `bash infra/runpod/setup.sh --only embeddings` |
| `[faq_search] missing source/*_faq.json` | `bash infra/runpod/setup.sh --only paths` |
| Agent NOT registered | `noble-pod doctor`; thường `LIVEKIT_*` thiếu trong `.env` |
| Port 8082 zombie | `pkill -9 -f noble-agent && pkill -9 -f livekit.agents && noble-pod start` |
| safetensors look like LFS pointers | `cd $MODEL_DIR && git lfs pull` |
| Qwen `content: null + reasoning: ...` | thinking chưa tắt — restart vLLM (`start_vllm.sh` đã có `--default-chat-template-kwargs '{"enable_thinking": false}'`) |
| `OSError: bind 8081 in use` | RunPod nginx chiếm 8081; `.env` đã set `LIVEKIT_WORKER_PORT=8082` qua setup.sh |
| Memory warning spam | Harmless. Filter: `tail -f agent.log \| grep -v "memory usage is high"` |

---

## File map

| File | Chạy ở | Vai trò |
|------|--------|---------|
| `setup.sh` | **Pod** | **Single-shot bootstrap (14 stages incl. data sync)** |
| `requirements-pod.txt` | Pod | Pod-only deps (vllm/flashinfer/hf-transfer) — installed via `uv pip install -r` vào `/opt/vllm-venv` |
| `../scripts/data_sync.sh` | Mac/Pod | **Universal data sync** — consolidate, push, hf-upload, hf-download, rebuild, mongo-check |
| `start_vllm.sh` | Pod (tmux:vllm) | Launch vLLM với flags đúng — gọi bởi `setup.sh` stage 10 |
| `env.runpod.example` | ref | `.env` template (đã có LiveKit/MongoDB/STT/TTS keys cho dev pod) |
| `Dockerfile.{vllm,embed,gender}` | non-RunPod | Cho Fly.io/VPS, **không dùng trên RunPod** (no Docker-in-Docker) |
| `docker-compose.runpod.yml` | non-RunPod | Same |
| `embed_server.py`, `gender_server.py` | external | FastAPI wrappers cho microservice path |

---

## MongoDB — runtime storage (không "push data")

**Insight first-principles**: MongoDB lưu state mà agent tạo ra (conversations, messages, bookings, session_metrics) — **không phải shipped data**. Agent tự tạo collection khi ghi turn đầu. Vì vậy "push data lên MongoDB" không tồn tại trong workflow này. Chỉ cần **đảm bảo connection đúng**.

### Setup MongoDB Atlas free tier (M0, 512MB)

1. Tạo account: https://www.mongodb.com/cloud/atlas
2. Create cluster → M0 Free Shared (region gần pod, e.g. AWS Singapore)
3. Database Access → tạo user `noblex-cs` + password
4. Network Access → Allow `0.0.0.0/0` (RunPod IP không stable)
5. Connect → `Drivers` → copy SRV string:
   ```
   mongodb+srv://noblex-cs:<password>@<cluster>.mongodb.net/?retryWrites=true&w=majority&appName=NobleX
   ```
6. Paste vào `.env`:
   ```bash
   MONGODB_URI=mongodb+srv://noblex-cs:...@noblex.f9fnsus.mongodb.net/...
   MONGODB_DATABASE=noblex
   ```

### Verify

```bash
bash scripts/data_sync.sh mongo-check
```

Expected output:
```
✓ MongoDB reachable
✓ DB 'noblex' — 4 collections: ['conversations', 'messages', 'bookings', 'session_metrics']
  • conversations: ~123 docs
  • messages: ~890 docs
```

### Hai loại data trên Mongo

| Collection | Loại | Ai tạo? |
|-----------|------|---------|
| `conversations`, `messages`, `bookings` | **Runtime** — agent tạo mỗi turn | agent tự ghi |
| `session_metrics` | **Runtime** — TTFT/TTFA/fallback per session | agent tự ghi end-of-session |
| `noble_profile` (optional) | **Migration** — nếu chuyển từ schema cũ | `python scripts/mongo_migrate_noble_profile.py` |
| `outbound_*` (optional) | **Migration** — outbound calling schema | `python scripts/mongo_migrate_outbound.py` |

→ Pod tươi không cần chạy migration. Chỉ chạy nếu chuyển từ DB cũ sang.

### Cost

Free tier 512MB ≈ 50k conversations × 5 turns × 2KB avg. Vượt → upgrade M10 ($0.08/h shared, ~$58/tháng).

---

## Monitoring & Alerting

→ **[docs/runbooks/monitoring-alerting.md](../../docs/runbooks/monitoring-alerting.md)** — 4 layer (HTTP health, process logs, MongoDB metrics, cloud alerting).

Quick smoke check:
```bash
noble-pod doctor                       # toàn cảnh ✓/✗
curl -sf localhost:8082/health/ready   # service-level (mongo+redis+llm+embeddings)
noble-pod logs --watch                 # live tail filtered
noble-pod metrics                      # P50/P95/P99 + fallback count
```

Khi user "agent không trả lời" → flowchart 5 bước trong monitoring-alerting.md §"Backend server không call?".

---

## Cost (RTX PRO 6000)

| Item | $/h | Note |
|------|-----|------|
| Pod running | $1.89 | Stop khi không dùng → $0.056/h disk only |
| LiveKit Cloud | $0 | Free 500 min/month |
| MongoDB Atlas M0 | $0 | Free 512 MB |

Demo 1h: ~$1.94. Standby 24h (stopped): ~$1.34/ngày.
