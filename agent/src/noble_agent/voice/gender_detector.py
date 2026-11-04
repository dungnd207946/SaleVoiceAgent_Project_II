import base64
import logging

import numpy as np
import torch

logger = logging.getLogger("gender")


class GenderDetector:
    _instance = None

    def __init__(self):
        self.model = None
        self.processor = None
        self.id2label = {"0": "female", "1": "male"}
        self._remote_url = ""
        self._remote_timeout = 3.0
        self._remote_client = None

        self._load_model()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _load_model(self):
        """Load local Wav2Vec2 OR configure remote client.

        Remote mode (hosting sidecar): set GENDER_REMOTE_URL — skips the
        in-process transformers load entirely. Local mode: GENDER_MODEL_DIR
        must point to a valid Wav2Vec2 checkpoint.
        """
        try:
            from noble_agent.config import settings

            # Remote-first: if a sidecar URL is configured, never load the
            # local model. This keeps the agent container small on hosted setups.
            if settings.gender_remote_url:
                import httpx

                self._remote_url = settings.gender_remote_url.rstrip("/")
                self._remote_timeout = settings.gender_remote_timeout
                self._remote_client = httpx.Client(timeout=self._remote_timeout)
                logger.info("Gender detection: remote mode → %s", self._remote_url)
                return

            model_dir = settings.gender_model_dir
            if not model_dir:
                logger.info("Gender detection disabled: GENDER_MODEL_DIR not set.")
                return

            from transformers import Wav2Vec2FeatureExtractor, Wav2Vec2ForSequenceClassification

            logger.info("Đang tải model nhận diện giới tính từ: %s ...", model_dir)
            self.model = Wav2Vec2ForSequenceClassification.from_pretrained(model_dir)
            self.processor = Wav2Vec2FeatureExtractor.from_pretrained(model_dir)
            logger.info("Đã nạp model nhận diện giới tính vào RAM thành công.")
        except Exception as e:
            logger.warning(f"Không thể tải model nhận diện giới tính. Tính năng nhận diện bị tắt. Lỗi: {e}")

    def _predict_remote(self, raw_audio_bytes: bytes) -> str | None:
        """POST base64 audio to the sidecar gender service."""
        try:
            resp = self._remote_client.post(
                f"{self._remote_url}/predict",
                json={"audio_b64": base64.b64encode(raw_audio_bytes).decode("ascii")},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("gender")  # "M" | "F" | None
        except Exception as e:
            logger.warning("[GENDER] remote call failed: %s", e)
            return None

    def predict(self, raw_audio_bytes: bytes) -> str | None:
        """
        Phân tích giới tính trực tiếp từ mảng byte âm thanh (Raw 16-bit 16kHz PCM).
        Không dùng librosa hay audioread để tránh các lỗi IO và chậm luồng.
        Trả về 'M' (nam) hoặc 'F' (nữ), hoặc None nếu không đủ dữ liệu.
        """
        if not raw_audio_bytes:
            return None

        # Minimum-audio check shared for both modes; do it once up front
        # so the remote call doesn't waste a round-trip on too-short clips.
        if len(raw_audio_bytes) < int(16000 * 0.5) * 2:  # 2 bytes per int16 sample
            return None

        if self._remote_client is not None:
            return self._predict_remote(raw_audio_bytes)

        if not self.model or not self.processor:
            return None

        try:
            # Chuyển đổi Raw bytes (int16) sang mảng numpy (float32) -> chia 32768.0 theo chuẩn torchaudio
            audio_array = np.frombuffer(raw_audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

            inputs = self.processor(audio_array, sampling_rate=16000, return_tensors="pt", padding=True)

            with torch.no_grad():
                outputs = self.model(**inputs)
                logits = outputs.logits
                probs = torch.nn.functional.softmax(logits, dim=1).squeeze().tolist()

            prediction = {self.id2label[str(i)]: probs[i] for i in range(len(probs))}
            detected = max(prediction, key=prediction.get)
            confidence = prediction[detected]

            # Require minimum confidence of 0.6 to avoid false positives
            if confidence < 0.6:
                logger.debug("[GENDER] Low confidence (%.2f) — skipping", confidence)
                return None

            return "M" if detected == "male" else "F"
        except Exception as e:
            logger.warning(f"Lỗi khi dự đoán giới tính: {e}")
            return None
