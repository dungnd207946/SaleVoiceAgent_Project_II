"""FastEmbed e5-large REST wrapper for Noble Voice Agent.

POST /embed   — batch encode texts to L2-normalized float32 vectors
GET  /health  — liveness probe

Keeps the exact same model + normalization as src/noble_agent/agent/rag/flat_store.py
so remote and local paths return identical vectors (bit-level on ONNX INT8).
"""
from __future__ import annotations

import logging
import os
import time
from typing import List

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("embed-svc")

MODEL_NAME = os.environ.get("FLAT_STORE_MODEL", "intfloat/multilingual-e5-large")
THREADS = int(os.environ.get("EMBED_THREADS", "4"))

app = FastAPI(title="Noble Embed Service", version="1.0.0")

_impl = None


def _load():
    global _impl
    if _impl is not None:
        return _impl
    from fastembed import TextEmbedding
    t0 = time.monotonic()
    _impl = TextEmbedding(model_name=MODEL_NAME, threads=THREADS)
    logger.info("fastembed loaded %s in %.2fs (threads=%d)", MODEL_NAME, time.monotonic() - t0, THREADS)
    return _impl


class EmbedRequest(BaseModel):
    texts: List[str] = Field(..., min_length=1)
    normalize: bool = True


class EmbedResponse(BaseModel):
    embeddings: List[List[float]]
    dim: int
    model: str
    count: int


@app.on_event("startup")
def _startup():
    _load()


@app.get("/health")
def health():
    return {"status": "ok" if _impl is not None else "warming", "model": MODEL_NAME}


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest):
    if not req.texts:
        raise HTTPException(status_code=400, detail="texts is empty")
    impl = _load()
    t0 = time.monotonic()
    # fastembed returns a generator; materialize.
    vecs = [np.asarray(v, dtype=np.float32) for v in impl.embed(req.texts, batch_size=32)]
    arr = np.stack(vecs, axis=0)
    if req.normalize:
        norms = np.linalg.norm(arr, axis=1, keepdims=True) + 1e-12
        arr = arr / norms
    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info("embed n=%d dim=%d in %.1fms", len(req.texts), arr.shape[1], elapsed_ms)
    return EmbedResponse(
        embeddings=arr.tolist(),
        dim=int(arr.shape[1]),
        model=MODEL_NAME,
        count=len(req.texts),
    )
