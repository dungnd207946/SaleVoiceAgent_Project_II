#!/usr/bin/env bash
# Launch the SEPARATE vLLM OpenAI server that serves santa-tts speech tokens for
# the `vieneu_vllm` TTS backend. This runs in its OWN venv (vLLM pins older
# torch/cu12x) — it MUST NOT use the main project `.venv` (torch 2.11+cu130).
#
# The agent worker is a client (TTS_BACKEND=vieneu_vllm, VIENEU_VLLM_URL=...); it
# parses the streamed `<|speech_N|>` tokens and feeds them to the local codec sink.
#
# Required server flags (verified on this Blackwell sm_120 host WITHOUT a CUDA
# toolkit / nvcc): FlashInfer sampler off, FLASH_ATTN backend, eager mode (no
# CUDA-graph capture, which needs nvcc). skip_special_tokens=false is sent
# per-request by the client so `<|speech_N|>` survive in the stream.
#
# Usage:
#   scripts/run_vllm_tts.sh                 # port 8000
#   VLLM_TTS_PORT=8001 scripts/run_vllm_tts.sh
set -euo pipefail

VLLM_BIN="${VLLM_BIN:-$HOME/.cache/vllm-spike-venv/bin/vllm}"
VLLM_TTS_MODEL="${VLLM_TTS_MODEL:-NobleX-AI/santa-tts}"
VLLM_TTS_PORT="${VLLM_TTS_PORT:-8000}"
VLLM_TTS_GPU_UTIL="${VLLM_TTS_GPU_UTIL:-0.5}"
VLLM_TTS_MAX_LEN="${VLLM_TTS_MAX_LEN:-2048}"

if [ ! -x "$VLLM_BIN" ]; then
  echo "vllm binary not found at $VLLM_BIN — set VLLM_BIN to the vLLM venv's vllm." >&2
  exit 1
fi

export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=FLASH_ATTN

exec "$VLLM_BIN" serve "$VLLM_TTS_MODEL" \
  --port "$VLLM_TTS_PORT" \
  --dtype bfloat16 \
  --max-model-len "$VLLM_TTS_MAX_LEN" \
  --gpu-memory-utilization "$VLLM_TTS_GPU_UTIL" \
  --enforce-eager \
  --trust-remote-code
