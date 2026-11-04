"""Shared startup pre-warm for the heavy in-process voice models.

Called once at boot by BOTH transports (aiortc HTTP `_run_server_async` and the
livekit `_prewarm`). Eagerly constructs the configured STT (sherpa recognizer)
and TTS (vieneu) singletons plus the shared Silero VAD model so the first real
call isn't cold.

Pre-warm is best-effort: each load is wrapped in its own try/except — a failure
logs and the server STILL boots. The runtime nets (lazy-load + the init-time
fallback chains in base_session / VoiceAgent) cover a primary that fails here.

Only the configured primary backend is warmed (sherpa / vieneu hold heavy local
models); cloud backends (soniox / elevenlabs) have no in-process model to warm.
Heavy loaders are imported function-locally so importing this module stays cheap
and dep-free (works under `make test-unit` without sherpa-onnx / vieneu).
"""

from __future__ import annotations

import logging

from noble_agent.config import settings

logger = logging.getLogger(__name__)


def prewarm_voice_models() -> None:
    """Eager-load the configured STT + TTS singletons; log + continue on failure."""
    if settings.stt_backend == "sherpa":
        try:
            from noble_agent.voice.stt import sherpa as sherpa_mod

            logger.info("prewarm: loading STT (sherpa) ...")
            sherpa_mod._get_recognizer()
        except Exception as exc:  # noqa: BLE001 — never abort boot
            logger.warning("prewarm: STT (sherpa) failed: %s", exc)

    if settings.tts_backend == "vieneu":
        try:
            from noble_agent.voice.tts import vieneu as vieneu_mod

            logger.info("prewarm: loading TTS (vieneu) ...")
            vieneu_mod._load_tts()
        except Exception as exc:  # noqa: BLE001 — never abort boot
            logger.warning("prewarm: TTS (vieneu) failed: %s", exc)

    from noble_agent.config import resolve_speaker_mode  # function-local, matches other imports above

    if resolve_speaker_mode() in ("single", "multi") and not settings.speaker_remote_url:
        try:
            from noble_agent.voice.speaker_verifier import _get_extractor

            _get_extractor()
            logger.info("[prewarm] speaker embedding model ready")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[prewarm] speaker model load failed (continuing): %s", exc)

    # Silero VAD is one process-wide model deep-copied per session; warming it
    # here keeps the first call on the aiortc/WS + telephony loops from paying
    # the blocking torch.hub load (the LiveKit path also prewarms in worker.py).
    try:
        from noble_agent.voice.vad.silero import _load_shared_model

        _load_shared_model()
    except Exception as exc:  # noqa: BLE001 — never abort boot
        logger.warning("prewarm: Silero VAD failed: %s", exc)
