"""Speaker embedding and model loading utilities.

Provides SpeakerEmbedder (singleton) for extracting speaker embeddings
from audio, supporting both local (sherpa ONNX) and remote modes.
The embedding extraction replaces the superseded SpeakerVerifier/SpeakerFloor
(deleted 2026-08-28); speaker matching is now handled by SpeakerTracker.
"""

from __future__ import annotations

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

_extractor = None


def _ensure_speaker_model_present(model_dir: str, model_name: str, repo_id: str, token: str, revision: str) -> str:
    """Return the local ONNX path, pulling the single file from HF if absent."""
    path = os.path.join(model_dir, model_name)
    if os.path.exists(path):
        return path
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:  # part of the stt-sherpa extra
        raise ImportError('huggingface_hub not installed. Run: pip install -e ".[stt-sherpa]"') from exc
    os.makedirs(model_dir, exist_ok=True)
    logger.info("Speaker model missing — pulling %s/%s@%s ...", repo_id, model_name, revision)
    downloaded = hf_hub_download(
        repo_id=repo_id, filename=model_name, local_dir=model_dir, token=token or None, revision=revision
    )
    return downloaded


def _get_extractor():
    """Load or return the cached sherpa SpeakerEmbeddingExtractor (local mode)."""
    global _extractor
    if _extractor is not None:
        return _extractor
    import sherpa_onnx

    from noble_agent.config import settings

    model_path = _ensure_speaker_model_present(
        settings.speaker_model_dir,
        settings.speaker_model_name,
        settings.speaker_hf_repo,
        settings.hf_token,
        settings.speaker_hf_revision,
    )
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model_path, num_threads=settings.sherpa_num_threads)
    _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
    logger.info("Speaker embedding extractor ready (dim=%d).", _extractor.dim)
    return _extractor


class SpeakerEmbedder:
    """Singleton embedder: remote (default when SPEAKER_REMOTE_URL set) or local sherpa."""

    _instance: SpeakerEmbedder | None = None

    @classmethod
    def get_instance(cls) -> SpeakerEmbedder:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._extractor = None
        self._remote_client = None
        self._remote_url = ""
        self._load()

    def _load(self) -> None:
        from noble_agent.config import settings

        if settings.speaker_remote_url:
            import httpx

            self._remote_url = settings.speaker_remote_url.rstrip("/")
            headers = {}
            if settings.speaker_remote_token:
                headers["Authorization"] = f"Bearer {settings.speaker_remote_token}"
            self._remote_client = httpx.Client(timeout=settings.speaker_remote_timeout, headers=headers or None)
            logger.info("Speaker verification: remote mode → %s", self._remote_url)
            return
        self._extractor = _get_extractor()

    def embed(self, pcm16: bytes) -> np.ndarray | None:
        if not pcm16:
            return None
        if self._remote_client is not None:
            return self._embed_remote(pcm16)
        return self._embed_local(pcm16)

    def _embed_remote(self, pcm16: bytes) -> np.ndarray | None:
        import base64

        try:
            resp = self._remote_client.post(
                f"{self._remote_url}/embed",
                json={"audio_b64": base64.b64encode(pcm16).decode("ascii")},
            )
            resp.raise_for_status()
            return np.array(resp.json()["embedding"], dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Speaker] remote embed failed: %s", exc)
            return None

    def _embed_local(self, pcm16: bytes) -> np.ndarray | None:
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        stream = self._extractor.create_stream()
        stream.accept_waveform(16000, samples)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            return None
        return np.array(self._extractor.compute(stream), dtype=np.float32)
