# `infra/runpod/` — RunPod Deployment

**→ Xem [SETUP.md](./SETUP.md)** cho hướng dẫn triển khai chi tiết (1 script duy nhất `setup.sh`).

## Quick reference

```bash
# Pod tươi → đang chạy:
git clone <repo-url> /workspace/santa-hotline-agent
cd /workspace/santa-hotline-agent
bash infra/runpod/setup.sh
# → script in URL/ROOM/TOKEN khi xong, paste vào https://agents-playground.livekit.io/
```

## Files

| File | Chạy ở | Vai trò |
|------|--------|---------|
| [`SETUP.md`](./SETUP.md) | read | Main guide |
| [`setup.sh`](./setup.sh) | **Pod** | **Single-shot bootstrap (13 stages)** |
| [`../scripts/data_sync.sh`](../../scripts/data_sync.sh) | Mac/Pod | **Universal data sync** — consolidate / push / hf-upload / hf-download / rebuild / mongo-check |
| [`start_vllm.sh`](./start_vllm.sh) | Pod tmux | Launch vLLM (gọi bởi `setup.sh` stage 10) |
| `env.runpod.example` | ref | Template `.env` (đã có LiveKit/MongoDB/STT/TTS keys) |

Các Dockerfile + compose: **không dùng trên RunPod** (RunPod không hỗ trợ Docker-in-Docker). Giữ làm reference cho Fly.io / VPS / EC2.
