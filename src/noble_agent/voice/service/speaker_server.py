"""Resident speaker-embedding HTTP service.

Mirrors the remote STT/TTS service pattern: wraps the local SpeakerEmbedder
singleton so the GPU/CPU model loads once and the worker talks to it over HTTP
(SPEAKER_REMOTE_URL). Contract: POST /embed {"audio_b64": ...} -> {"embedding": [...]}.
"""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from noble_agent.voice.speaker_verifier import SpeakerEmbedder

        # Force LOCAL mode in the service even if SPEAKER_REMOTE_URL is set for workers.
        emb = SpeakerEmbedder.__new__(SpeakerEmbedder)
        emb._remote_client = None
        emb._remote_url = ""
        from noble_agent.voice.speaker_verifier import _get_extractor

        emb._extractor = _get_extractor()
        _embedder = emb
    return _embedder


def _handle_embed(payload: dict) -> dict:
    pcm16 = base64.b64decode(payload["audio_b64"])
    emb = _embedder.embed(pcm16)
    return {"embedding": [] if emb is None else [float(x) for x in emb]}


def run_server() -> None:
    import uvicorn
    from fastapi import Body, FastAPI

    app = FastAPI()
    _get_embedder()  # warm at boot

    @app.post("/embed")
    async def embed(payload: dict = Body(...)):  # noqa: B008
        return _handle_embed(payload)

    from noble_agent.config import settings

    host = settings.speaker_service_host
    port = int(settings.speaker_service_port)
    logger.info("Speaker service on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_server()


if __name__ == "__main__":
    main()
