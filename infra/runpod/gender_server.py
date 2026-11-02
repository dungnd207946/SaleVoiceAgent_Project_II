"""Wav2Vec2 gender detection REST wrapper for Noble Voice Agent.

POST /predict  — base64-encoded 16kHz int16 PCM → "M" | "F" | null
GET  /health   — liveness probe

Wraps the same inference logic as src/noble_agent/voice/gender_detector.py.
Requires GENDER_MODEL_DIR env var (local path or HF repo id).
"""
from __future__ import annotations

import base64
import logging
import os
import time

import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gender-svc")

MODEL_DIR = os.environ.get("GENDER_MODEL_DIR", "")
MIN_CONFIDENCE = float(os.environ.get("GENDER_MIN_CONFIDENCE", "0.6"))
MIN_AUDIO_MS = int(os.environ.get("GENDER_MIN_AUDIO_MS", "500"))

app = FastAPI(title="Noble Gender Service", version="1.0.0")

_model = None
_processor = None
_id2label = {"0": "female", "1": "male"}


def _load():
    global _model, _processor
    if _model is not None:
        return
    if not MODEL_DIR:
        logger.warning("GENDER_MODEL_DIR not set — service will return null for every request")
        return
    from transformers import Wav2Vec2ForSequenceClassification, Wav2Vec2FeatureExtractor
    t0 = time.monotonic()
    _model = Wav2Vec2ForSequenceClassification.from_pretrained(MODEL_DIR)
    _processor = Wav2Vec2FeatureExtractor.from_pretrained(MODEL_DIR)
    _model.eval()
    logger.info("gender model loaded from %s in %.2fs", MODEL_DIR, time.monotonic() - t0)


class PredictRequest(BaseModel):
    # Base64-encoded int16 16kHz mono PCM. Same raw bytes the agent passes
    # to GenderDetector.predict(raw_audio_bytes) in-process.
    audio_b64: str


class PredictResponse(BaseModel):
    gender: str | None  # "M" | "F" | None
    confidence: float | None = None
    reason: str | None = None


@app.on_event("startup")
def _startup():
    _load()


@app.get("/health")
def health():
    return {
        "status": "ok" if _model is not None else "disabled",
        "model_dir": MODEL_DIR or "(not set)",
        "min_confidence": MIN_CONFIDENCE,
    }


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if _model is None or _processor is None:
        return PredictResponse(gender=None, reason="model_not_loaded")

    try:
        raw = base64.b64decode(req.audio_b64)
    except Exception:
        raise HTTPException(status_code=400, detail="audio_b64 is not valid base64")

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    min_samples = int(16000 * MIN_AUDIO_MS / 1000)
    if len(audio) < min_samples:
        return PredictResponse(gender=None, reason="too_short")

    try:
        inputs = _processor(audio, sampling_rate=16000, return_tensors="pt", padding=True)
        with torch.no_grad():
            logits = _model(**inputs).logits
            probs = torch.nn.functional.softmax(logits, dim=1).squeeze().tolist()
    except Exception as e:
        logger.exception("inference failed: %s", e)
        raise HTTPException(status_code=500, detail=f"inference_failed: {e}")

    pred = {_id2label[str(i)]: probs[i] for i in range(len(probs))}
    detected = max(pred, key=pred.get)
    conf = float(pred[detected])
    if conf < MIN_CONFIDENCE:
        return PredictResponse(gender=None, confidence=conf, reason="low_confidence")

    return PredictResponse(gender="M" if detected == "male" else "F", confidence=conf)
