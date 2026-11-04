#!/usr/bin/env bash
# Install all dependencies into the ACTIVE venv/conda environment.
# Usage: source .venv/bin/activate && bash install.sh
set -e

VIENEU_SRC="$(cd "$(dirname "$0")/../Ref/VieNeu-TTS" 2>/dev/null && pwd || echo "")"

echo "==================================================================="
echo " Noble Voice Agent — dependency installer"
echo " Python: $(python3 --version)"
echo " Env:    $(which python3)"
echo " VieNeu: ${VIENEU_SRC:-not found}"
echo "==================================================================="

# ── 1. Core (from pyproject.toml) ────────────────────────────────────────────
echo ""
echo "[1/6] Core packages (pip install -e .[dev])..."
pip install -q --upgrade pip
pip install -q -e ".[dev]"

# ── 2. VAD: Silero (torch) ────────────────────────────────────────────────────
echo ""
echo "[2/6] VAD — PyTorch + torchaudio..."
pip install -q torch torchaudio

# ── 3. STT: sherpa-onnx ───────────────────────────────────────────────────────
echo ""
echo "[3/6] STT — sherpa-onnx..."
pip install -q "sherpa-onnx>=1.9.0"

# ── 4. TTS: VieNeu-TTS (local) ───────────────────────────────────────────────
echo ""
echo "[4/6] TTS — VieNeu-TTS..."
if [ -n "$VIENEU_SRC" ] && [ -d "$VIENEU_SRC" ]; then
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "  macOS — installing llama-cpp-python with Metal..."
        pip install -q "llama-cpp-python==0.3.16" \
            --extra-index-url "https://abetlen.github.io/llama-cpp-python/whl/metal/"
    fi
    pip install -q "onnxruntime>=1.18.0" "librosa>=0.10.0" "soundfile>=0.12.0" \
        "sea-g2p>=0.2.1" "neucodec>=0.0.4"
    pip install -q "perth>=0.2.0" 2>/dev/null || true
    pip install -q --no-deps -e "$VIENEU_SRC"
else
    echo "  WARNING: VieNeu-TTS not found. Set TTS_BACKEND=elevenlabs in .env."
fi

# ── 5. Optional backends ─────────────────────────────────────────────────────
echo ""
echo "[5/6] Optional backends (soniox, elevenlabs)..."
pip install -q -e ".[stt-soniox,tts-elevenlabs]" 2>/dev/null || true

# ── 6. .env ──────────────────────────────────────────────────────────────────
echo ""
echo "[6/6] Checking .env..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  Created .env from .env.example — edit it before running."
fi

echo ""
echo "==================================================================="
echo " Done! Next:"
echo "   1. Edit .env (set API keys)"
echo "   2. noble-agent   (or: python app.py)"
echo "   3. Open http://localhost:8766"
echo "==================================================================="
