"""Streaming TTS via ElevenLabs WebSocket — real-time text-to-speech.

Drop-in replacement for AsyncVieNeuTTS:
    tts = AsyncElevenLabsTTS()
    async for chunk in tts.stream("Xin chào"):
        send_audio(chunk)  # PCM int16 bytes

Output: PCM int16, sample rate from config (default 24kHz), mono.
Uses eleven_flash_v2_5 for lowest latency (supports Vietnamese).
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import AsyncIterator
from pathlib import Path

import websockets
from websockets.protocol import State as WsState

from noble_agent.config import settings

logger = logging.getLogger("elevenlabs_tts")

# ── Normalize map for ElevenLabs (shared utility) ───────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_NORMALIZE_FILE = _PROJECT_ROOT / "data" / "tts_normalize_elevenlabs.json"

from noble_agent.voice.tts._normalize import apply_normalize, load_normalize_map

_normalize_map_cache: dict[str, str] | None = None


def normalize_for_elevenlabs(text: str) -> str:
    global _normalize_map_cache
    if _normalize_map_cache is None:
        _normalize_map_cache = load_normalize_map(_NORMALIZE_FILE)
    return apply_normalize(text, _normalize_map_cache, word_boundary=True)


class AsyncElevenLabsTTS:
    """Async streaming TTS via ElevenLabs WebSocket."""

    def __init__(self):
        self._voice_id = settings.elevenlabs_tts_voice_id
        self._warm_ws: websockets.WebSocketClientProtocol | None = None

    def set_voice(self, voice_id: str) -> None:
        self._voice_id = voice_id
        logger.info("ElevenLabs TTS voice set to: %s", voice_id)

    async def warm_up(self) -> None:
        """Pre-open a WebSocket connection so the first stream() avoids ~200ms handshake."""
        if not settings.elevenlabs_api_key:
            return
        try:
            url = (
                f"wss://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream-input"
                f"?model_id={settings.elevenlabs_tts_model}"
                f"&output_format=pcm_{settings.tts_sample_rate}"
            )
            if settings.elevenlabs_tts_language_code:
                url += f"&language_code={settings.elevenlabs_tts_language_code}"
            self._warm_ws = await websockets.connect(
                url,
                additional_headers={"xi-api-key": settings.elevenlabs_api_key},
                max_size=10 * 1024 * 1024,
                ping_interval=20,
            )
            logger.info("[TTS] ElevenLabs WebSocket pre-warmed")
        except Exception as exc:
            logger.warning("[TTS] ElevenLabs warm-up failed: %s", exc)
            self._warm_ws = None

    def list_voices(self) -> list[dict]:
        """Return available voices (ElevenLabs API call)."""
        try:
            import httpx

            resp = httpx.get(
                "https://api.elevenlabs.io/v1/voices",
                headers={"xi-api-key": settings.elevenlabs_api_key},
                timeout=5.0,
            )
            if resp.status_code == 200:
                return [{"voice_id": v["voice_id"], "name": v["name"]} for v in resp.json().get("voices", [])]
        except Exception as exc:
            logger.warning("ElevenLabs list_voices failed: %s", exc)
        return [{"voice_id": self._voice_id, "name": "current"}]

    # Allowed ElevenLabs v3 audio tags — only these pass through to TTS
    _ALLOWED_TAGS = frozenset(
        {
            "warmly",
            "softly",
            "enthusiastically",
            "reassuringly",
            "pause",
            "short pause",
            "long pause",
            "gently",
            "cheerfully",
            "calmly",
        }
    )

    @staticmethod
    def _clean_for_tts(text: str) -> str:
        """Strip markdown/emoji that TTS shouldn't read. Whitelist emotion tags."""
        import re

        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*", r"\1", text)
        text = re.sub(r"__(.+?)__", r"\1", text)
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*[-*]\s+", "", text, flags=re.MULTILINE)
        # Strip markdown links but preserve standalone [tags] for TTS
        text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
        text = re.sub(
            r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF"
            r"\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
            r"\U0001F900-\U0001F9FF\U0000200D]+",
            "",
            text,
        )

        # Whitelist filter on complete [tag] patterns (no length cap).
        # Whitelisted → keep for ElevenLabs emotion rendering.
        # Non-whitelisted → DROP entirely (brackets + content).
        # Dropping is correct: long brackets are LLM reasoning annotations
        # (e.g. [Dựa trên ngữ cảnh...]) — speaking them aloud is worse than silence.
        def _tag_filter(m):
            tag = m.group(1).strip().lower()
            return m.group(0) if tag in AsyncElevenLabsTTS._ALLOWED_TAGS else ""

        text = re.sub(r"\[([^\]]+)\](?!\()", _tag_filter, text)

        # Strip bare [ with no closing ] (SentenceBuffer mid-tag splits).
        text = re.sub(r"\[(?![^\]]*\])", "", text)

        return text.strip()

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        """Stream text → PCM int16 audio chunks via ElevenLabs WebSocket."""
        text = self._clean_for_tts(text)
        text = normalize_for_elevenlabs(text)
        if not text:
            return

        t0 = time.monotonic()
        first_chunk = True

        url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream-input"
            f"?model_id={settings.elevenlabs_tts_model}"
            f"&output_format=pcm_{settings.tts_sample_rate}"
        )
        if settings.elevenlabs_tts_language_code:
            url += f"&language_code={settings.elevenlabs_tts_language_code}"

        ws = None
        try:
            # Reuse pre-warmed WebSocket if available and still open
            if self._warm_ws is not None and self._warm_ws.state == WsState.OPEN:
                ws = self._warm_ws
                self._warm_ws = None  # consume — one use per warm-up
                logger.debug("[TTS] Reusing pre-warmed WebSocket")
            else:
                ws = await websockets.connect(
                    url,
                    additional_headers={"xi-api-key": settings.elevenlabs_api_key},
                    max_size=10 * 1024 * 1024,
                    ping_interval=20,
                )

            # Init message (required first message)
            await ws.send(
                json.dumps(
                    {
                        "text": " ",
                        "voice_settings": {
                            "stability": settings.elevenlabs_tts_stability,
                            "similarity_boost": settings.elevenlabs_tts_similarity_boost,
                            "speed": settings.elevenlabs_tts_speed,
                        },
                        "generation_config": {
                            "chunk_length_schedule": [50, 80, 120, 160],
                        },
                    }
                )
            )

            # Send text + flush
            await ws.send(
                json.dumps(
                    {
                        "text": text + " ",
                        "flush": True,
                    }
                )
            )

            # Signal end of input
            await ws.send(json.dumps({"text": ""}))

            # Receive audio chunks
            async for raw in ws:
                msg = json.loads(raw)

                if msg.get("isFinal"):
                    break

                audio_b64 = msg.get("audio")
                if audio_b64:
                    pcm_bytes = base64.b64decode(audio_b64)
                    if pcm_bytes:
                        if first_chunk:
                            logger.info(
                                "[TTS] ElevenLabs TTFB: %.0fms  text=%r",
                                (time.monotonic() - t0) * 1000,
                                text[:50],
                            )
                            first_chunk = False
                        yield pcm_bytes

        except Exception as exc:
            logger.error("ElevenLabs TTS error: %s", exc, exc_info=True)
        finally:
            if ws and ws.state == WsState.OPEN:
                try:
                    await ws.close()
                except Exception:
                    pass
