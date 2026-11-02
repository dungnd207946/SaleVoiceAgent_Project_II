"""Smart Turn v3 — semantic turn-completion detection.

Wraps the ONNX model from Ref/smart-turn.
Determines whether the user has finished speaking based on
prosodic/semantic cues in the last 8 seconds of audio.

Input:  16 kHz mono float32 NumPy array (any length, truncated to last 8s).
Output: {"prediction": 0|1, "probability": float}.

Used as an optional gate between STT on_final and LLM trigger.
Enable via SMART_TURN_ENABLED=true in .env.
"""

from __future__ import annotations

import logging

import numpy as np
import onnxruntime as ort
from transformers import WhisperFeatureExtractor

from noble_agent.config import settings

logger = logging.getLogger(__name__)

_detector = None

SAMPLE_RATE = 16000
MAX_SECONDS = 8
MAX_SAMPLES = MAX_SECONDS * SAMPLE_RATE  # 128000


def _truncate_pad(audio: np.ndarray) -> np.ndarray:
    """Keep the last 8 seconds; zero-pad at the start if shorter."""
    if len(audio) > MAX_SAMPLES:
        return audio[-MAX_SAMPLES:]
    if len(audio) < MAX_SAMPLES:
        return np.pad(audio, (MAX_SAMPLES - len(audio), 0))
    return audio


class SmartTurnDetector:
    """Singleton ONNX inference wrapper for Smart Turn v3."""

    def __init__(self):
        so = ort.SessionOptions()
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        so.inter_op_num_threads = 1
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(settings.smart_turn_model_path, sess_options=so)
        self._extractor = WhisperFeatureExtractor(chunk_length=MAX_SECONDS)
        logger.info("Smart Turn v3 loaded: %s", settings.smart_turn_model_path)

    def predict(self, audio_float32: np.ndarray) -> dict:
        """Run turn-completion inference.

        Args:
            audio_float32: 16 kHz mono float32, range [-1, 1], any length.

        Returns:
            {"prediction": 0 or 1, "probability": float}
        """
        audio = _truncate_pad(audio_float32)

        inputs = self._extractor(
            audio,
            sampling_rate=SAMPLE_RATE,
            return_tensors="np",
            padding="max_length",
            max_length=MAX_SAMPLES,
            truncation=True,
            do_normalize=True,
        )
        features = inputs.input_features.squeeze(0).astype(np.float32)
        features = np.expand_dims(features, axis=0)  # (1, 80, 800)

        outputs = self._session.run(None, {"input_features": features})
        prob = float(outputs[0][0].item())

        return {"prediction": 1 if prob >= 0.5 else 0, "probability": prob}


def get_detector() -> SmartTurnDetector:
    """Return the singleton detector (lazy init)."""
    global _detector
    if _detector is None:
        _detector = SmartTurnDetector()
    return _detector
