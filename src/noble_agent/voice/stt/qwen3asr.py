"""Streaming STT via Qwen3-ASR — DashScope cloud API or self-hosted vLLM.

Two modes (controlled by settings.qwen3asr_mode):
  "dashscope" — WebSocket to DashScope Realtime API (cloud, server-side VAD)
  "vllm"      — HTTP POST to self-hosted vLLM streaming server (local endpoint detect)

Drop-in replacement for SherpaSTT / SonioxSTT:
    stt = Qwen3ASRSTT(on_partial=..., on_final=...)
    await stt.start()
    await stt.send(pcm_bytes)   # PCM int16, 16kHz, mono
    await stt.stop()
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Callable

import numpy as np

from noble_agent.config import settings

logger = logging.getLogger(__name__)


class Qwen3ASRSTT:
    """Facade — delegates to _DashScopeBackend or _VllmBackend."""

    def __init__(
        self,
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
    ):
        self.on_partial = on_partial
        self.on_final = on_final
        self._impl = None

    async def start(self):
        if settings.qwen3asr_mode == "vllm":
            self._impl = _VllmBackend(self.on_partial, self.on_final)
        else:
            self._impl = _DashScopeBackend(self.on_partial, self.on_final)
        await self._impl.start()
        logger.info("Qwen3ASRSTT started (mode=%s).", settings.qwen3asr_mode)

    def is_alive(self) -> bool:
        """Liveness probe for ReconnectingSTT: delegate to the active backend."""
        if self._impl is None:
            return False
        probe = getattr(self._impl, "is_alive", None)
        return probe() if callable(probe) else True

    async def send(self, pcm_bytes: bytes):
        if self._impl:
            await self._impl.send(pcm_bytes)

    async def stop(self):
        if self._impl:
            await self._impl.stop()
            self._impl = None
        logger.info("Qwen3ASRSTT stopped.")


# ═════════════════════════════════════════════════════════════════════════════
#  Backend A: DashScope Realtime WebSocket (cloud, has server-side VAD)
# ═════════════════════════════════════════════════════════════════════════════


class _DashScopeBackend:
    """WebSocket streaming to DashScope Realtime API."""

    WS_URL_INTL = "wss://dashscope-intl.aliyuncs.com/api-ws/v1/realtime"
    WS_URL_CN = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"

    def __init__(self, on_partial, on_final):
        self.on_partial = on_partial
        self.on_final = on_final
        self._ws = None
        self._recv_task = None
        self._partial_text = ""

    async def start(self):
        import websockets

        base = self.WS_URL_CN if settings.qwen3asr_region == "cn" else self.WS_URL_INTL
        url = f"{base}?model={settings.qwen3asr_model}"
        self._ws = await websockets.connect(
            url,
            additional_headers={
                "Authorization": f"Bearer {settings.qwen3asr_api_key}",
                "OpenAI-Beta": "realtime=v1",
            },
            max_size=15 * 1024 * 1024,
            ping_interval=20,
        )

        # Wait for session.created
        created_raw = await self._ws.recv()
        created = json.loads(created_raw)
        if created.get("type") == "session.created":
            actual_model = created.get("session", {}).get("model", "?")
            logger.info("DashScope session created (model=%s)", actual_model)

        # Send session config (model already set via URL)
        session_cfg = {
            "turn_detection": {"type": "server_vad"},
            "voice_activity_detection": {
                "threshold": 0.5,
                "vad_events": True,
            },
            "input_audio_format": "pcm",
        }
        lang = getattr(settings, "qwen3asr_language", "")
        if lang:
            session_cfg["transcription"] = {"language": lang}

        await self._ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": session_cfg,
                }
            )
        )
        self._recv_task = asyncio.create_task(self._receive_loop())
        logger.info(
            "DashScope Qwen3-ASR connected (%s, model=%s, lang=%s).",
            url.split("//")[1].split("/")[0],
            settings.qwen3asr_model,
            lang or "auto",
        )

    def is_alive(self) -> bool:
        """Liveness probe for ReconnectingSTT: is the stream still usable?"""
        return bool(self._ws and getattr(self._ws, "state", None) and self._ws.state.name == "OPEN")

    async def send(self, pcm_bytes: bytes):
        if self._ws and getattr(self._ws, "state", None) and self._ws.state.name == "OPEN":
            b64 = base64.b64encode(pcm_bytes).decode("ascii")
            try:
                await self._ws.send(
                    json.dumps(
                        {
                            "type": "input_audio_buffer.append",
                            "audio": b64,
                        }
                    )
                )
            except Exception:
                pass

    async def stop(self):
        if self._ws and getattr(self._ws, "state", None) and self._ws.state.name == "OPEN":
            try:
                await self._ws.send(json.dumps({"type": "session.finish"}))
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

    async def _receive_loop(self):
        try:
            async for raw in self._ws:
                evt = json.loads(raw)
                etype = evt.get("type", "")

                # Interim/partial transcript
                if etype == "conversation.item.input_audio_transcription.text":
                    text = evt.get("transcript", "")
                    if text and text != self._partial_text:
                        self._partial_text = text
                        if self.on_partial:
                            await _safe_call(self.on_partial, text)

                # Final completed transcript
                elif etype == "conversation.item.input_audio_transcription.completed":
                    text = evt.get("transcript", "") or self._partial_text
                    if text and self.on_final:
                        await _safe_call(self.on_final, text.strip())
                    self._partial_text = ""

                elif etype == "input_audio_buffer.speech_started":
                    logger.debug("DashScope: speech started")
                elif etype == "input_audio_buffer.speech_stopped":
                    logger.debug("DashScope: speech stopped")
                elif etype == "session.updated":
                    logger.info("DashScope session config applied")
                elif etype == "session.finished":
                    logger.info("DashScope session finished")
                    break

                elif etype == "error":
                    logger.error("DashScope error: %s", evt.get("error", evt))

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("DashScope receive error: %s", exc, exc_info=True)


# ═════════════════════════════════════════════════════════════════════════════
#  Backend B: Self-hosted vLLM streaming server (HTTP chunks, local EP detect)
# ═════════════════════════════════════════════════════════════════════════════


class _VllmBackend:
    """HTTP POST chunks to self-hosted Qwen3-ASR vLLM streaming server.

    Endpoint detection: simple energy-based silence tracking (self-contained,
    no dependency on external VAD).
    """

    SILENCE_ENERGY_THRESHOLD = 200.0  # int16 RMS below this → silence
    SILENCE_DURATION_SEC = 1.2  # silence after speech → endpoint
    MIN_SPEECH_SEC = 0.3  # minimum speech before allowing endpoint

    def __init__(self, on_partial, on_final):
        self.on_partial = on_partial
        self.on_final = on_final
        self._session_id: str | None = None
        self._http = None
        self._audio_buf = bytearray()
        self._last_send_time = 0.0
        self._accumulated_text = ""
        # Silence tracking
        self._is_speaking = False
        self._silence_start = 0.0
        self._speech_start = 0.0
        self._send_task = None

    async def start(self):
        import aiohttp

        self._http = aiohttp.ClientSession()
        url = f"{settings.qwen3asr_vllm_url}/api/start"
        async with self._http.post(url) as resp:
            data = await resp.json()
            self._session_id = data.get("session_id", "default")
        self._last_send_time = time.monotonic()
        self._send_task = asyncio.create_task(self._chunk_sender())
        logger.info("vLLM Qwen3-ASR session started: %s", self._session_id)

    async def send(self, pcm_bytes: bytes):
        self._audio_buf.extend(pcm_bytes)

        # Track energy for endpoint detection
        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(samples**2)))
        now = time.monotonic()

        if rms > self.SILENCE_ENERGY_THRESHOLD:
            if not self._is_speaking:
                self._is_speaking = True
                self._speech_start = now
            self._silence_start = 0.0
        else:
            if self._is_speaking and self._silence_start == 0.0:
                self._silence_start = now

        # Check endpoint: speaking → silence > threshold
        if (
            self._is_speaking
            and self._silence_start > 0
            and (now - self._silence_start) >= self.SILENCE_DURATION_SEC
            and (self._silence_start - self._speech_start) >= self.MIN_SPEECH_SEC
        ):
            await self._finalize()

    async def stop(self):
        if self._send_task:
            self._send_task.cancel()
            try:
                await self._send_task
            except asyncio.CancelledError:
                pass
        if self._http and self._session_id:
            try:
                url = f"{settings.qwen3asr_vllm_url}/api/finish"
                async with self._http.post(url, params={"session_id": self._session_id}) as resp:
                    data = await resp.json()
                    text = data.get("text", "").strip()
                    if text and self.on_final:
                        await _safe_call(self.on_final, text)
            except Exception:
                pass
        if self._http:
            await self._http.close()
            self._http = None
        self._audio_buf.clear()
        self._accumulated_text = ""
        self._is_speaking = False

    async def _chunk_sender(self):
        """Periodically flush buffered audio to vLLM."""
        chunk_bytes = int(settings.qwen3asr_chunk_size_sec * settings.stt_sample_rate * 2)
        try:
            while True:
                await asyncio.sleep(settings.qwen3asr_chunk_size_sec * 0.8)
                if len(self._audio_buf) >= chunk_bytes:
                    chunk = bytes(self._audio_buf[:chunk_bytes])
                    self._audio_buf = self._audio_buf[chunk_bytes:]
                    await self._send_chunk(chunk)
        except asyncio.CancelledError:
            pass

    async def _send_chunk(self, pcm_int16: bytes):
        """POST one audio chunk to vLLM, update partial."""
        if not self._http or not self._session_id:
            return
        # Convert int16 → float32 (vLLM expects float32)
        samples = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0
        try:
            url = f"{settings.qwen3asr_vllm_url}/api/chunk"
            async with self._http.post(
                url,
                params={"session_id": self._session_id},
                data=samples.tobytes(),
                headers={"Content-Type": "application/octet-stream"},
            ) as resp:
                data = await resp.json()
                text = data.get("text", "")
                if text and text != self._accumulated_text:
                    self._accumulated_text = text
                    if self.on_partial:
                        await _safe_call(self.on_partial, text)
        except Exception as exc:
            logger.warning("vLLM chunk error: %s", exc)

    async def _finalize(self):
        """Fire on_final, flush remaining audio, reset state."""
        # Send any remaining audio
        if self._audio_buf:
            remaining = bytes(self._audio_buf)
            self._audio_buf.clear()
            await self._send_chunk(remaining)

        # Call finish on vLLM
        if self._http and self._session_id:
            try:
                url = f"{settings.qwen3asr_vllm_url}/api/finish"
                async with self._http.post(url, params={"session_id": self._session_id}) as resp:
                    data = await resp.json()
                    text = data.get("text", "").strip()
                    if text:
                        self._accumulated_text = text
            except Exception as exc:
                logger.warning("vLLM finish error: %s", exc)

        # Emit final
        text = self._accumulated_text.strip()
        if text and self.on_final:
            await _safe_call(self.on_final, text)

        # Reset for next utterance — re-init session
        self._accumulated_text = ""
        self._is_speaking = False
        self._silence_start = 0.0
        try:
            url = f"{settings.qwen3asr_vllm_url}/api/start"
            async with self._http.post(url) as resp:
                data = await resp.json()
                self._session_id = data.get("session_id", self._session_id)
        except Exception:
            pass


# ── Shared helper ────────────────────────────────────────────────────────────


async def _safe_call(fn: Callable, text: str) -> None:
    try:
        result = fn(text)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.error("STT callback error: %s", exc)
