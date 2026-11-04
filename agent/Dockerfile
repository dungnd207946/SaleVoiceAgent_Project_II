# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1 \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only torch first, as its own cached layer, at the SAME version
# bound pyproject pins (torch>=2.11). Trong container này KHÔNG có gì cần CUDA:
# torch chỉ phục vụ Silero VAD (CPU), gender_detector (remote-default) và
# sentence-transformers — mọi đường GPU (vieneu TTS, embed) sống ở service
# odyssey-models riêng. Bản PyPI mặc định bundle nguyên bộ wheel nvidia-* (~6GB)
# đẩy image lên 11GB chỉ để làm dead weight (đo 2026-08-24).
# Index whl/cpu là index CHÍNH THỨC đang được cập nhật (torch 2.13+cpu đã có,
# probe 2026-08-24) — khác index cu124 đã chết ở torch 2.6 từng gây vụ churn
# 6GB/build ngày 2026-08-05: bước `pip install -e .` phía sau thấy torch đã
# thoả >=2.11 nên không tải lại.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu \
    "torch>=2.11.0" "torchaudio>=2.11.0"

# Install remaining deps (cached across builds)
COPY requirements.txt pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# vieneu TTS runtime. Only the `vieneu` package itself is needed for the santa
# (safetensors GPU) path — it pulls onnxruntime (int8 codec decode), tokenizers,
# perth, sea-g2p, soxr. The full `.[tts-vieneu]` extra additionally pulls
# llama-cpp-python (GGUF path only) + neucodec/librosa/datasets (offline
# voice-building only), none of which the runtime uses — so install just vieneu.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "vieneu>=2.4"

# App code (changes here don't re-download deps)
COPY src/ src/
COPY data/ data/
COPY static/ static/
COPY assets/ assets/
COPY scripts/pull-rag-data.sh /app/scripts/pull-rag-data.sh
# rag-qdrant is required, not optional: kb_search/send_media need qdrant-client, and
# it's lazy-imported → missing it degrades silently instead of failing boot.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -e ".[tracing,postgres,rag-qdrant]"

RUN mkdir -p /app/logs /app/sessions /app/data && \
    chmod +x /app/scripts/pull-rag-data.sh

EXPOSE 8768 8090

ENV PYTHONUNBUFFERED=1

# pull-rag-data.sh pulls the HF RAG dataset (cached by SHA marker) and
# then exec's the command (default below, or compose-overridden for agent-lk).
ENTRYPOINT ["/app/scripts/pull-rag-data.sh"]
CMD ["noble-agent", "--no-reload"]
