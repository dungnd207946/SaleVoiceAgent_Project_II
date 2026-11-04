#!/usr/bin/env bash
# Launch vLLM OpenAI-compatible server for Qwen3.6-35B-A3B.
# Ported from voiceagentrag/tests/benchllm/start_vllm.sh — RunPod container entrypoint.
set -euo pipefail

MODEL="${MODEL:-/workspace/Qwen3.6-35B-A3B}"
SERVED_NAME="${SERVED_NAME:-Qwen/Qwen3.6-35B-A3B}"
PORT="${PORT:-8000}"
HOST="${HOST:-0.0.0.0}"
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.90}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"
TENSOR_PARALLEL="${TENSOR_PARALLEL:-1}"
ATTN_BACKEND="${ATTN_BACKEND:-FLASHINFER}"
VLLM_VENV="${VLLM_VENV:-/opt/vllm-venv}"
VPY="${VLLM_VENV}/bin/python"
[[ -x "$VPY" ]] || VPY="python3"   # fallback to system python (legacy installs)

echo "→ GPU info:"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.free --format=csv,noheader || {
    echo "ERROR: nvidia-smi not found. Is this running on a GPU pod?"
    exit 1
}

echo "→ vLLM version (via $VPY):"
"$VPY" -c "import vllm; print(f'vLLM: {vllm.__version__}')"

# Auto-download if local path missing AND HF_MODEL_REPO is set (RunPod-friendly cold boot).
if [[ "$MODEL" == /* && ! -d "$MODEL" ]]; then
    if [[ -n "${HF_MODEL_REPO:-}" ]]; then
        echo "→ Model dir missing — cloning $HF_MODEL_REPO to $MODEL ..."
        cd /workspace
        GIT_LFS_SKIP_SMUDGE=0 git clone "https://huggingface.co/${HF_MODEL_REPO}" "$(basename "$MODEL")"
        cd "$(basename "$MODEL")" && git lfs pull
        cd /workspace
    else
        echo "ERROR: $MODEL not found and HF_MODEL_REPO unset. Set one of:"
        echo "  HF_MODEL_REPO=Qwen/Qwen3.6-35B-A3B   (auto-download on first boot)"
        echo "  MODEL=Qwen/Qwen3.6-35B-A3B            (let vLLM resolve from HF cache)"
        exit 1
    fi
fi

# Safetensors sanity check (catch LFS pointer files)
if [[ -d "$MODEL" ]]; then
    first_st=$(ls "$MODEL"/*.safetensors 2>/dev/null | head -1 || true)
    if [[ -n "$first_st" ]]; then
        size_bytes=$(stat -c%s "$first_st" 2>/dev/null || echo 0)
        if [[ "$size_bytes" -lt 1000000 ]]; then
            echo "ERROR: safetensors look like LFS pointers. Run: cd $MODEL && git lfs pull"
            exit 1
        fi
    fi
fi

echo "→ Launching vLLM:"
echo "   Model:         $MODEL"
echo "   Served as:     $SERVED_NAME"
echo "   Port:          $PORT"
echo "   GPU mem util:  $GPU_MEM_UTIL"
echo "   Max model len: $MAX_MODEL_LEN"
echo "   Attn backend:  $ATTN_BACKEND"
echo ""

exec "$VPY" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" \
    --tensor-parallel-size "$TENSOR_PARALLEL" \
    --gpu-memory-utilization "$GPU_MEM_UTIL" \
    --max-model-len "$MAX_MODEL_LEN" \
    --max-num-seqs "$MAX_NUM_SEQS" \
    --enable-auto-tool-choice \
    --tool-call-parser qwen3_coder \
    --reasoning-parser qwen3 \
    --default-chat-template-kwargs '{"enable_thinking": false}' \
    --language-model-only \
    --enable-prefix-caching \
    --prefix-caching-hash-algo sha256 \
    --attention-backend "$ATTN_BACKEND" \
    --host "$HOST" \
    --port "$PORT" \
    --served-model-name "$SERVED_NAME" \
    --trust-remote-code
