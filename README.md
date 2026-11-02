# odyssey-models

Standalone, reusable **model microservices** for the Odyssey platform —
decoupled from any agent. Any service consumes them over the network like a
cloud vendor (Soniox/ElevenLabs): just a URL + protocol, no shared code.

## Services

| Service | Port | What | Notes |
|---|---|---|---|
| `embed` | 8013 | Nhà máy vector: e5-large (dense, 1024d) + BM25 (sparse) + SigLIP2 (visual, 768d), **GPU** | `POST /embed` với `side: index\|query` (bắt buộc — quên là 422, không lệch âm thầm). 4 `kind`: `dense` · `sparse` · `visual_image`/`visual_text`. Xem [embed/README.md](embed/README.md). |
| `stt`   | 8012 | Streaming STT — sherpa-onnx Zipformer (CPU), WebSocket | `ws://host:8012/stt` — client streams PCM16/16k binary frames → `{"type":"partial"\|"final","text"}`; ends the session with `{"type":"eos"}`. Server-side endpointing. |
| `speaker` | 8014 | Speaker embedding — sherpa-onnx CAM++ (CPU), HTTP | `POST http://host:8014/embed` `{audio_b64}` (base64 PCM16/16k) → `{"embedding": [...]}` (empty list = unusable audio). `GET /health` → 200. |
| `tts-omnivoice` | 8016 | OmniVoice (santa-tts-omnivoice, our own fine-tune, masked-diffusion — **not** autoregressive), **GPU** | `ws://host:8016/tts` — one WS per clause: `{"type":"synthesize","text",…}` → binary PCM16 @ 24k → `{"type":"end"}`. `.generate()` returns the whole utterance at once, so TTFB ≈ total synth time. Voice cloning (`enroll_voice`, needs `ref_text`) — see [docs/voice_cloning.md](docs/voice_cloning.md). PRIVATE HF repo, needs `HF_TOKEN`. |
| `lipsync-musetalk` | 8020 | Lip sync thời gian thực — MuseTalk 1.5, **GPU** | Client là **trình duyệt** (portal tab Voice), không phải agent. Một phiên một lúc. Weights + avatar dựng tự động lúc boot đầu, cache vào volume — xem [lipsync_musetalk/README.md](lipsync_musetalk/README.md). |

Both STT and TTS speak the **`remote` WebSocket contract** in
[docs/remote_stt_tts_spect.md](docs/remote_stt_tts_spect.md) (source of truth).

## Run

**stt + speaker** (CPU) run with a bare `docker compose up -d` — works on any box,
no GPU needed:
```bash
docker compose up -d            # builds + starts stt + speaker
curl localhost:8014/health      # speaker
```

**embed + tts-omnivoice + lipsync-musetalk** (GPU) sit behind the `gpu` compose profile:
```bash
docker compose --profile gpu up -d     # + embed, tts-omnivoice, lipsync-musetalk
curl localhost:8013/health      # embed
curl localhost:8016/health      # tts-omnivoice
```
Needs `nvidia-container-toolkit` on the host. Watch VRAM headroom — they share
one GPU.

Build context of `embed` is the **repo root** (not `embed/`), because the image
needs `pyproject.toml`. Build by hand: `docker build -f embed/Dockerfile .`

All services bind **`0.0.0.0`** (LAN-visible) — see `docker-compose.yml`. Access
is gated by a shared bearer token (`ODYSSEY_MODELS_TOKEN` from `.env`); health
endpoints stay open.

Test:
```bash
pip install -e ".[dev]"
pytest -q
ruff check .
```

`pytest` covers the stt/tts-omnivoice WS protocol too (stubbed engines, no GPU/model files).

## Running OmniVoice locally

`tts-omnivoice` serves `NobleX-AI/santa-tts-omnivoice` — our LoRA fine-tune of
`k2-fsa/OmniVoice` on the santa voice clips. A **private** HF repo, so it
needs `HF_TOKEN`.

⚠️ **CC-BY-NC-4.0 (non-commercial).** The restriction rides on the base model's
Emilia training data, so it applies to our fine-tune too — see
[tts_omnivoice/README.md](tts_omnivoice/README.md) before deploying anywhere
commercial.

⚠️ **Not autoregressive.** OmniVoice is masked-diffusion: every audio-token position is
refined simultaneously across denoising steps, so there is no "early part first"
and nothing to stream. `OMNIVOICE_NUM_STEP` (default 16) trades quality for
speed on the same weights.

### Run via Docker Compose (recommended)

```bash
docker compose --profile gpu up -d tts-omnivoice
```

### Run natively (no Docker)

```bash
python -m venv .venv-omnivoice && .venv-omnivoice/bin/pip install -r tts_omnivoice/requirements.txt
ODYSSEY_MODELS_TOKEN=<your-token> HF_TOKEN=<your-hf-token> .venv-omnivoice/bin/python tts_omnivoice/tts_server.py
```

Point `OMNIVOICE_MODEL_REPO` at a local directory or another HF repo to serve
different weights without rebuilding the image.

### Testing speech generation end-to-end (real audio, not just protocol tests)

`scripts/try_tts.py` sends one text through the WS protocol to a running TTS
service and saves the reply as a playable `.wav`:

```bash
python scripts/try_tts.py --text "Xin chào" --voice TuLinh
```

Defaults to localhost:8016; use `--url`/`--host`
to point elsewhere (e.g. a Docker host or onprem server). Add `--token` if
the target service has `ODYSSEY_MODELS_TOKEN` set.

Voice cloning (enroll a custom voice from a reference clip): see
[docs/voice_cloning.md](docs/voice_cloning.md).

### Pointing `odyssey-agent` at it

No agent code changes needed — `odyssey-agent`'s `RemoteTTS` client already
speaks this exact protocol. In `odyssey-agent/.env`:

```bash
TTS_BACKEND=remote
TTS_SERVICE_URL=ws://localhost:8016/tts
VOICE_SERVICE_AUTH_TOKEN=<same token as ODYSSEY_MODELS_TOKEN>
VIENEU_VOICE_ID=<voice_id from voices/omnivoice/, or empty for the built-in speaker>
```

`VIENEU_VOICE_ID` is the historical env var name `RemoteTTS` reads regardless
of which engine `TTS_SERVICE_URL` actually points to.

## Models (not in git)

Model weights live under `models/` (gitignored) and are bind-mounted:
- `embed`: downloads e5-large + SigLIP2 to the `model_cache` volume on first boot.
- `stt`: sherpa Zipformer at `models/odyssey-stt/` (`encoder/decoder/joiner-epoch.onnx`
  + `.int8.onnx` + `tokens.txt`), from the public `NobleX-AI/santa-stt` (no `HF_TOKEN`
  needed). **Every boot** compares the HF commit of `STT_HF_REPO@STT_HF_REVISION`
  (`prod` everywhere; override with `STT_HF_REVISION`) with `models/odyssey-stt/.revision`; on a
  mismatch it downloads all 7 files into `odyssey-stt.new/`, swaps it in and keeps the
  previous weights at `odyssey-stt.prev/`. So shipping a new model = push it to the HF
  branch, then re-run the `deploy:dev` job on GitLab (it always `--force-recreate`s `stt`),
  or `docker compose restart stt` on the box.
  Roll back with `mv models/odyssey-stt.prev models/odyssey-stt` + restart, or pin
  `STT_HF_REVISION=<old sha>`. HF unreachable → keeps serving the local weights.
  `STT_HF_REPO=` (empty) disables the HF check for a hand-placed fine-tune.
- `speaker`: single CAM++ ONNX auto-pulled from HF to the `speaker_cache` volume.
- `tts-omnivoice`: `NobleX-AI/santa-tts-omnivoice` (~2.5GB) pulled from HF to the
  `omnivoice_cache` volume on first boot, plus the Higgs audio tokenizer (~800MB)
  it falls back to when the repo ships no bundled `audio_tokenizer/`. Budget the
  first boot accordingly — the compose healthcheck allows 600s.
- `lipsync-musetalk`: ~3,9 GB (MuseTalk 1.5 UNet, sd-vae, whisper-tiny, DWPose ONNX,
  face-parsing, S3FD) pulled from public HF repos to the `lipsync_cache` volume on first
  boot, each file SHA-256-checked; then the avatar is built ONCE from
  `lipsync_musetalk/avatars/nguoi-dan.mp4` (~2 min GPU) and cached next to the weights,
  keyed by the video's SHA-256. Healthcheck allows 1200s for that first boot.

## View logs

All services log with icon-prefixed lines for easy scanning (🚀 boot · 📦 load ·
✅ ready · 🔌/👋 session open/close · 🔒 auth reject · 📝 STT final · 🔊/🎵 TTS
synth+ttfb · 🧑 speaker embed · ⚠️/❌ warn/error).

Follow with `docker compose logs`:
```bash
docker compose logs -f embed      # e5-large + BM25 + SigLIP2 embeddings
docker compose logs -f stt        # 📝 finals only
docker compose logs -f speaker    # 🧑 per-embed size + dim + latency
docker compose logs -f tts-omnivoice   # 🔊 synth start / 🎵 done + ttfb
docker compose logs -f            # stt + speaker only by default (add `--profile gpu` for the rest)
docker compose logs --tail=100 stt   # last 100 lines, no follow
```
