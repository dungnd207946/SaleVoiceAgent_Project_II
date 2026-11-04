"""Standalone speaker-embedding service — sherpa-onnx CAM++ over HTTP.

Self-contained: depends only on sherpa-onnx + numpy + fastapi + huggingface_hub.
NO dependency on any agent codebase — like a cloud vendor, any service uses it by
POSTing PCM16 audio and reading back a speaker embedding vector.

Protocol (http://host:8014) — mirrors the agent's SPEAKER_REMOTE_URL contract:
  POST /embed   {"audio_b64": "<base64 PCM16 LE mono 16k>"} → {"embedding": [float, ...]}
                empty/unusable audio → {"embedding": []}
  GET  /health  → {"status": "ok"|"warming", "model": ...}

Config (env):
  SPEAKER_MODEL_DIR    dir holding the CAM++ ONNX (auto-pulled from HF if missing)
  SPEAKER_MODEL_NAME   ONNX filename (single-file provision)
  SPEAKER_HF_REPO      HF repo to pull the single ONNX file from
  SPEAKER_HF_REVISION  HF branch/tag
  HF_TOKEN             HF auth token ("" = anonymous)
  SPEAKER_NUM_THREADS  sherpa extractor threads
  SPEAKER_SAMPLE_RATE  16000
  ODYSSEY_MODELS_TOKEN shared bearer token — enforced on /embed when set; /health open
"""
from __future__ import annotations

import base64
import logging
import os
import time

import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("speaker-svc")

MODEL_DIR = os.environ.get("SPEAKER_MODEL_DIR", "/models/speaker")
MODEL_NAME = os.environ.get("SPEAKER_MODEL_NAME", "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx")
HF_REPO = os.environ.get("SPEAKER_HF_REPO", "csukuangfj/speaker-embedding-models")
HF_REVISION = os.environ.get("SPEAKER_HF_REVISION", "main")
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
NUM_THREADS = int(os.environ.get("SPEAKER_NUM_THREADS", "2"))
SAMPLE_RATE = int(os.environ.get("SPEAKER_SAMPLE_RATE", "16000"))
# Shared bearer token — enforced on /embed when set (LAN-visible service). Empty
# = open (loopback-only dev). /health stays open regardless.
TOKEN = os.environ.get("ODYSSEY_MODELS_TOKEN", "").strip()

app = FastAPI(title="Odyssey Speaker Service", version="1.0.0")


def require_token(authorization: str = Header(default="")):
    if TOKEN and authorization.removeprefix("Bearer ").strip() != TOKEN:
        logger.warning("🔒 embed auth rejected (bad/missing bearer token)")
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


_extractor = None


def _ensure_model_present() -> str:
    """Return the local ONNX path, pulling the single file from HF if absent."""
    path = os.path.join(MODEL_DIR, MODEL_NAME)
    if os.path.exists(path):
        logger.info("📂 Speaker model found: %s", path)
        return path
    from huggingface_hub import hf_hub_download

    os.makedirs(MODEL_DIR, exist_ok=True)
    logger.info("📥 Speaker model missing — pulling %s/%s@%s ...", HF_REPO, MODEL_NAME, HF_REVISION)
    return hf_hub_download(
        repo_id=HF_REPO, filename=MODEL_NAME, local_dir=MODEL_DIR, token=HF_TOKEN or None, revision=HF_REVISION
    )


def _load():
    global _extractor
    if _extractor is not None:
        return _extractor
    import sherpa_onnx

    t0 = time.monotonic()
    model_path = _ensure_model_present()
    logger.info("⏳ Loading speaker extractor: %s (threads=%d) ...", model_path, NUM_THREADS)
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model_path, num_threads=NUM_THREADS)
    _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
    logger.info("✅ Speaker extractor ready (dim=%d) in %.2fs.", _extractor.dim, time.monotonic() - t0)
    return _extractor


def _embed_local(pcm16: bytes) -> np.ndarray | None:
    if not pcm16:
        return None
    extractor = _load()
    samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
    stream = extractor.create_stream()
    stream.accept_waveform(SAMPLE_RATE, samples)
    stream.input_finished()
    if not extractor.is_ready(stream):
        return None
    return np.array(extractor.compute(stream), dtype=np.float32)


class EmbedRequest(BaseModel):
    # Tolerant like the original service: empty/unusable audio → {"embedding": []}
    # (not a 422). The worker guards empty PCM client-side, so this is defensive.
    audio_b64: str = ""


class EmbedResponse(BaseModel):
    embedding: list[float]


@app.on_event("startup")
def _startup():
    logger.info("🚀 Speaker service starting on :8014 (auth=%s)", "on" if TOKEN else "off")
    _load()


@app.get("/health")
def health():
    return {"status": "ok" if _extractor is not None else "warming", "model": MODEL_NAME}


@app.post("/embed", response_model=EmbedResponse, dependencies=[Depends(require_token)])
def embed(req: EmbedRequest):
    t0 = time.monotonic()
    pcm16 = base64.b64decode(req.audio_b64)
    emb = _embed_local(pcm16)
    dur_ms = (time.monotonic() - t0) * 1000
    n = len(pcm16)
    if emb is None:
        logger.info("🧑 embed: %d PCM bytes → no embedding (unusable) in %.1fms", n, dur_ms)
    else:
        logger.info("🧑 embed: %d PCM bytes (~%.2fs) → dim=%d in %.1fms", n, n / 2 / SAMPLE_RATE, len(emb), dur_ms)
    return EmbedResponse(embedding=[] if emb is None else [float(x) for x in emb])
