"""Streaming STT via Soniox cloud — stt-rt-v4 WebSocket.

Drop-in replacement for SherpaSTT: identical interface (on_partial / on_final),
identical audio format: PCM int16, 16kHz, mono.

Soniox handles endpoint detection (semantic endpointing) server-side.
Supports 60+ languages, mid-sentence code-switching, speaker diarization,
and custom vocabulary via structured context.

Architecture:
  Main asyncio thread  →  send(pcm_bytes)  →  Soniox WebSocket (binary frames)
  Soniox WebSocket     →  _receive_loop()  →  on_partial / on_final callbacks

Usage (same as SherpaSTT):
    stt = SonioxSTT(on_partial=..., on_final=...)
    await stt.start()
    await stt.send(pcm_bytes)   # called per audio chunk
    await stt.stop()
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from collections.abc import Callable

import websockets
from websockets.protocol import State as WsState

from noble_agent.config import settings

logger = logging.getLogger(__name__)

SONIOX_WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"

# Soniox terminates the stream with error 408 after ~20s without audio frames
# or keepalive messages. With STT_INPUT_GATE_MODE=vad/rms the input gate sends
# NOTHING during silence, so the adapter must emit `{"type": "keepalive"}`
# itself whenever no audio has flowed for this long.
KEEPALIVE_INTERVAL_S = 5.0


def _load_hotwords() -> list[str]:
    """Load terms from sherpa hotwords file (shared with SherpaSTT)."""
    hw_path = settings.sherpa_hotwords_file
    if not hw_path:
        # SHERPA_HOTWORDS_FILE= (rỗng) đè mất default: join("", dir) trả về
        # chính thư mục voice/ → open(dir) nổ IsADirectoryError và giết cả
        # backend lúc start. Rỗng = không dùng hotwords, như SherpaSTT.
        return []
    if not os.path.isabs(hw_path):
        hw_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), hw_path)
    if not os.path.isfile(hw_path):
        return []
    terms = []
    with open(hw_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                terms.append(line)
    logger.info("Soniox context: loaded %d terms from %s", len(terms), hw_path)
    return terms


class SonioxSTT:
    """
    One streaming STT session backed by Soniox cloud.

    Drop-in replacement for SherpaSTT:
        on_partial(text)  — called when interim text changes (UI update)
        on_final(text, speaker=None)  — called when endpoint detected (triggers LLM)

    When speaker diarization is enabled, speaker ID is tracked per token
    and passed to on_final as keyword argument.
    """

    def __init__(
        self,
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
    ):
        self.on_partial = on_partial
        self.on_final = on_final
        self._ws = None
        self._recv_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._last_audio_ts = 0.0
        self._partial_text = ""
        self._final_text = ""
        self._current_speaker: str | None = None

    async def start(self):
        """Connect to Soniox WebSocket and send config."""
        self._ws = await websockets.connect(
            SONIOX_WS_URL,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        )
        config = self._build_config()
        await self._ws.send(json.dumps(config))
        self._recv_task = asyncio.create_task(self._receive_loop())
        self._last_audio_ts = time.monotonic()
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())
        logger.info(
            "SonioxSTT session started (model=%s, langs=%s).",
            settings.soniox_model,
            settings.soniox_language_hints,
        )

    def is_alive(self) -> bool:
        """Liveness probe for ReconnectingSTT: is the stream still usable?"""
        return self._ws is not None and self._ws.state == WsState.OPEN

    async def send(self, pcm_bytes: bytes):
        """Send a raw PCM int16 chunk to Soniox (non-blocking)."""
        if self._ws and self._ws.state == WsState.OPEN:
            try:
                await self._ws.send(pcm_bytes)
                self._last_audio_ts = time.monotonic()
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Soniox WS closed during send")

    async def _keepalive_loop(self):
        """Hold the stream open through silence (gate closed → no audio flows)."""
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL_S)
                if self._ws is None or self._ws.state != WsState.OPEN:
                    continue
                if time.monotonic() - self._last_audio_ts < KEEPALIVE_INTERVAL_S:
                    continue
                try:
                    await self._ws.send(json.dumps({"type": "keepalive"}))
                except websockets.exceptions.ConnectionClosed:
                    logger.warning("Soniox WS closed during keepalive")
                    return
        except asyncio.CancelledError:
            pass

    async def stop(self):
        """Signal end-of-audio and tear down."""
        if self._keepalive_task:
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None
        if self._ws and self._ws.state == WsState.OPEN:
            try:
                await self._ws.send("")  # end-of-audio signal
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        self._ws = None
        self._recv_task = None
        self._partial_text = ""
        self._final_text = ""
        logger.info("SonioxSTT session stopped.")

    # ── Config builder ───────────────────────────────────────────────────────

    def _build_config(self) -> dict:
        lang_hints = [s.strip() for s in settings.soniox_language_hints.split(",") if s.strip()]

        cfg: dict = {
            "api_key": settings.soniox_api_key,
            "model": settings.soniox_model,
            "audio_format": "pcm_s16le",
            "sample_rate": settings.stt_sample_rate,
            "num_channels": 1,
            "enable_endpoint_detection": settings.soniox_enable_endpoint_detection,
        }
        if lang_hints:
            cfg["language_hints"] = lang_hints
        if settings.soniox_language_hints_strict:
            cfg["language_hints_strict"] = True
        if settings.soniox_enable_language_identification:
            cfg["enable_language_identification"] = True
        if settings.soniox_enable_speaker_diarization:
            cfg["enable_speaker_diarization"] = True
        if settings.soniox_max_endpoint_delay_ms != 2000:
            cfg["max_endpoint_delay_ms"] = settings.soniox_max_endpoint_delay_ms

        # Build structured context
        context = self._build_context()
        if context:
            cfg["context"] = context

        return cfg

    @staticmethod
    def _build_context() -> dict | None:
        ctx: dict = {}

        # Load terms: from config, or fall back to sherpa hotwords file
        terms = [t.strip() for t in settings.soniox_context_terms.split(",") if t.strip()]
        if not terms:
            terms = _load_hotwords()
        if terms:
            ctx["terms"] = terms

        general = []
        if settings.soniox_context_domain:
            general.append({"key": "domain", "value": settings.soniox_context_domain})
        if settings.soniox_context_organization:
            general.append({"key": "organization", "value": settings.soniox_context_organization})
        if general:
            ctx["general"] = general

        return ctx or None

    # ── Receive loop ─────────────────────────────────────────────────────────

    async def _receive_loop(self):
        """Read Soniox responses and emit on_partial / on_final callbacks."""
        try:
            async for raw in self._ws:
                data = json.loads(raw)

                if data.get("error_code"):
                    logger.error(
                        "Soniox error [%s]: %s",
                        data["error_code"],
                        data.get("error_message"),
                    )
                    continue

                tokens = data.get("tokens", [])
                if not tokens:
                    if data.get("finished"):
                        await self._flush_final()
                    continue

                for tok in tokens:
                    text = tok.get("text", "")
                    is_final = tok.get("is_final", False)
                    speaker = tok.get("speaker")

                    if speaker:
                        self._current_speaker = speaker

                    if text == "<end>":
                        await self._flush_final()
                        continue

                    if is_final:
                        self._final_text += text
                        self._partial_text = ""
                        if self.on_partial:
                            await _safe_call(self.on_partial, self._final_text)
                    else:
                        self._partial_text = text
                        if self.on_partial:
                            await _safe_call(
                                self.on_partial,
                                self._final_text + self._partial_text,
                            )

                if data.get("finished"):
                    await self._flush_final()
                    break

        except websockets.exceptions.ConnectionClosed:
            logger.info("Soniox WS closed")
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Soniox receive error: %s", exc, exc_info=True)

    async def _flush_final(self):
        """Emit on_final for accumulated text and reset for next utterance."""
        text = self._final_text.strip()
        if text and self.on_final:
            await _safe_call(self.on_final, text, speaker=self._current_speaker)
        self._final_text = ""
        self._partial_text = ""


async def _safe_call(fn: Callable, text: str, **kwargs) -> None:
    try:
        result = fn(text, **kwargs)
        if asyncio.iscoroutine(result):
            await result
    except TypeError:
        # Fallback for callbacks that don't accept speaker kwarg
        try:
            result = fn(text)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.error("STT callback error: %s", exc)
    except Exception as exc:
        logger.error("STT callback error: %s", exc)
