"""Standalone TTS microservice — OmniVoice (single-speaker Vietnamese,
masked-diffusion, GPU/torch). Serves santa-tts-omnivoice by default, our own
fine-tune on the santa voice. See README.md for the licensing note and the
non-streaming/no-cancellation caveats before deploying this.

Self-contained: depends only on `omnivoice` (+ torch/websockets). NO agent
dependency — any service uses it like a cloud vendor by opening a WS and
streaming text/PCM.

Protocol (ws://host:8016/tts) — the `remote` WebSocket contract (see
odyssey-models/docs/remote_stt_tts_spect.md):
  client → server : {"type":"synthesize","text":"...","voice":"<optional>"}
  server → client : binary frame(s) = raw PCM16 LE, mono, 24 kHz (native — no resample needed)
  server → client : {"type":"end"}  (exactly one, when the synth is done)
  empty text      : server replies {"type":"end"} immediately, no audio.
`voice` selects a previously-ENROLLED cloned voice (see below); omit it (or
give an unknown id) and the model falls back to its single built-in speaker
(Luna).

Voice cloning — enroll once, reuse by name (see docs/voice_cloning.md):
  client → server : {"type":"enroll_voice","voice_id":"...","ref_audio_b64":"<wav bytes, base64>","ref_text":"<transcript of the clip>"}
  server → client : {"type":"enrolled","voice_id":"..."}  on success
  server → client : {"type":"error","message":"..."}      on failure
`ref_text` is REQUIRED — this service has no ASR model loaded to auto-
transcribe the reference clip, unlike the omnivoice package's own optional
auto-transcribe path. After enrolling, "voice_id" is a normal `voice` value
for "synthesize" — no extra latency vs. any other request (the reference
audio is only processed once, at enroll time). Persisted under
CUSTOM_VOICES_DIR (one `<voice_id>.pt` file per voice, via
`VoiceClonePrompt.save`/`.load` — see the omnivoice package), so it survives
restarts (same cache volume as the HF model cache).

Config (env):
  OMNIVOICE_MODEL_REPO      HF repo id (default NobleX-AI/santa-tts-omnivoice —
                             PRIVATE, needs HF_TOKEN)
  OMNIVOICE_DEVICE           cuda:0 | cpu  (default cuda:0)
  OMNIVOICE_NUM_STEP         diffusion denoising steps (default 16 — see README.md)
  OMNIVOICE_GUIDANCE_SCALE   classifier-free guidance (default 2.0)
  TTS_PORT                    8016
  TTS_MAX_CONCURRENT          bound concurrent generations (default 2 — diffusion
                               batch calls are more VRAM-hungry per request than
                               vieneu/zerotts's streamed autoregressive decode)
  OMNIVOICE_CUSTOM_VOICES_DIR where enrolled voices persist (default ~/.cache/omnivoice_custom_voices)
  ODYSSEY_MODELS_TOKEN        shared bearer token; empty = auth off (loopback dev)
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import tempfile
import threading
import time
from http import HTTPStatus
from pathlib import Path

import numpy as np
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("tts-omnivoice-service")

MODEL_REPO = os.environ.get("OMNIVOICE_MODEL_REPO", "NobleX-AI/santa-tts-omnivoice")
DEVICE = os.environ.get("OMNIVOICE_DEVICE", "cuda:0")
NUM_STEP = int(os.environ.get("OMNIVOICE_NUM_STEP", "16"))
GUIDANCE_SCALE = float(os.environ.get("OMNIVOICE_GUIDANCE_SCALE", "2.0"))
SR = 24000  # model's native output rate
PORT = int(os.environ.get("TTS_PORT", "8016"))
TOKEN = os.environ.get("ODYSSEY_MODELS_TOKEN", "").strip()
_GEN_SEM = threading.Semaphore(int(os.environ.get("TTS_MAX_CONCURRENT", "2")))
CUSTOM_VOICES_DIR = Path(
    os.environ.get("OMNIVOICE_CUSTOM_VOICES_DIR") or (Path.home() / ".cache" / "omnivoice_custom_voices")
)

# Model handle, populated by _ensure_loaded() at boot — kept as a global so the
# WS handler/worker reach it, and so tests can inject a stub.
MODEL = None

# Enrolled voices: voice_id -> VoiceClonePrompt, populated by _load_custom_voices()
# at boot and by _enroll_voice() at runtime. omnivoice has no built-in named-voice
# registry (unlike vieneu's Vieneu.add_voice/save_voices) — this dict + the .pt
# files under CUSTOM_VOICES_DIR ARE the registry, built here.
_CUSTOM_VOICES: dict[str, object] = {}


def _load_model():
    import torch
    from omnivoice import OmniVoice

    dtype = torch.float16 if DEVICE.startswith("cuda") else torch.float32
    log.info("📦 Loading OmniVoice: %s on %s (dtype=%s) ...", MODEL_REPO, DEVICE, dtype)
    model = OmniVoice.from_pretrained(MODEL_REPO, device_map=DEVICE, dtype=dtype)
    log.info("✅ OmniVoice ready.")
    return model


def _load_custom_voices() -> None:
    """Load any voices enrolled in a previous run — see module docstring."""
    if not CUSTOM_VOICES_DIR.is_dir():
        return
    from omnivoice.models.omnivoice import VoiceClonePrompt

    for p in sorted(CUSTOM_VOICES_DIR.glob("*.pt")):
        try:
            _CUSTOM_VOICES[p.stem] = VoiceClonePrompt.load(str(p))
        except Exception as exc:  # noqa: BLE001 — a broken/stale file shouldn't stop boot
            log.warning("⚠️  could not load custom voice %s: %s", p, exc)
    if _CUSTOM_VOICES:
        log.info("📢 Loaded %d previously-enrolled custom voice(s): %s", len(_CUSTOM_VOICES), sorted(_CUSTOM_VOICES))


def _ensure_loaded():
    global MODEL
    if MODEL is None:
        MODEL = _load_model()
        _load_custom_voices()
    return MODEL


def _f32_to_pcm16(a) -> bytes:
    return np.clip(np.asarray(a, dtype=np.float32).reshape(-1) * 32767.0, -32768, 32767).astype(np.int16).tobytes()


async def _enroll_voice(ws, voice_id: str, ref_audio_b64: str, ref_text: str) -> None:
    """Clone a voice from one reference clip + its transcript and register it
    under `voice_id` for future "synthesize" requests — see module docstring.
    Runs the actual enrollment (a few seconds of GPU work) in a worker thread
    so it doesn't block other connections' synth requests."""
    if not voice_id or not ref_audio_b64:
        await ws.send(json.dumps({"type": "error", "message": "voice_id and ref_audio_b64 are required"}))
        return
    if not ref_text:
        await ws.send(json.dumps({"type": "error", "message": "ref_text is required (transcript of ref_audio_b64)"}))
        return
    try:
        audio_bytes = base64.b64decode(ref_audio_b64, validate=True)
    except Exception:
        await ws.send(json.dumps({"type": "error", "message": "ref_audio_b64 is not valid base64"}))
        return

    def _enroll():
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:
            f.write(audio_bytes)
            f.flush()
            with _GEN_SEM:
                prompt = MODEL.create_voice_clone_prompt(ref_audio=f.name, ref_text=ref_text)
        CUSTOM_VOICES_DIR.mkdir(parents=True, exist_ok=True)
        prompt.save(str(CUSTOM_VOICES_DIR / f"{voice_id}.pt"))
        return prompt

    t0 = time.monotonic()
    try:
        _CUSTOM_VOICES[voice_id] = await asyncio.to_thread(_enroll)
    except Exception as exc:  # noqa: BLE001
        log.warning("❌ enroll %r failed: %s", voice_id, exc)
        await ws.send(json.dumps({"type": "error", "message": f"enroll failed: {exc}"}))
        return
    log.info("➕ enrolled voice %r in %.1fs (persisted to %s)", voice_id, time.monotonic() - t0, CUSTOM_VOICES_DIR)
    await ws.send(json.dumps({"type": "enrolled", "voice_id": voice_id}))


async def _synthesize(ws, text: str, voice_id):
    """Run one blocking (non-streaming) generate() in a worker thread, then
    send the whole result as fixed-size chunks so no single WS frame is huge.
    No mid-generation cancellation — see module docstring / README.md."""
    t0 = time.monotonic()
    clone_prompt = _CUSTOM_VOICES.get(voice_id) if voice_id else None
    if voice_id and clone_prompt is None:
        log.info("ℹ️  voice=%r not a known enrolled voice — using the single built-in speaker", voice_id)
    preview = text if len(text) <= 60 else text[:60] + "..."
    log.info("🔊 synth start: %r", preview)

    def _generate() -> bytes:
        with _GEN_SEM:
            wav = MODEL.generate(
                text=[text],
                language="vi",
                voice_clone_prompt=clone_prompt,
                num_step=NUM_STEP,
                guidance_scale=GUIDANCE_SCALE,
                pad_duration=0.0,
                fade_duration=0.02,
            )[0]
        return _f32_to_pcm16(wav)

    try:
        pcm = await asyncio.to_thread(_generate)
    except Exception as exc:  # noqa: BLE001
        log.warning("❌ synth error: %s", exc)
        pcm = b""
    first_ms = (time.monotonic() - t0) * 1000 if pcm else None
    total_bytes = 0
    chunk_bytes = SR * 2  # ~1s of audio per WS frame
    try:
        for i in range(0, len(pcm), chunk_bytes):
            chunk = pcm[i : i + chunk_bytes]
            total_bytes += len(chunk)
            await ws.send(chunk)
        await ws.send(json.dumps({"type": "end"}))
    except websockets.exceptions.ConnectionClosed:
        log.info("✂️  client closed after %d bytes (generation not cancellable — worker finishes in background)", total_bytes)
        raise
    ttfb = f"{first_ms:.0f}ms" if first_ms is not None else "n/a"
    log.info(
        "🎵 synth done: %d bytes (~%.2fs audio), ttfb=%s total=%.0fms",
        total_bytes, total_bytes / 2 / SR, ttfb, (time.monotonic() - t0) * 1000,
    )


async def handler(ws):
    if TOKEN:
        try:
            auth = ws.request.headers.get("Authorization", "")
        except Exception:  # noqa: BLE001
            auth = ""
        if auth.removeprefix("Bearer ").strip() != TOKEN:
            log.warning("🔒 auth rejected %s", getattr(ws, "remote_address", None))
            await ws.close(code=1008, reason="unauthorized")
            return
    log.info("🔌 session open %s", getattr(ws, "remote_address", None))
    try:
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                continue
            try:
                req = json.loads(msg)
            except (ValueError, TypeError):
                continue
            if req.get("type") == "enroll_voice":
                await _enroll_voice(
                    ws, (req.get("voice_id") or "").strip(), req.get("ref_audio_b64") or "", req.get("ref_text") or ""
                )
                continue
            if req.get("type") != "synthesize":
                continue
            text = (req.get("text") or "").strip()
            log.info("📥 text: %r", text)
            voice_id = req.get("voice") or None
            if not text:
                await ws.send(json.dumps({"type": "end"}))
                continue
            await _synthesize(ws, text, voice_id)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        log.info("👋 session closed %s", getattr(ws, "remote_address", None))


async def _process_request(connection, request):
    if request.path.split("?", 1)[0] == "/health":
        return connection.respond(HTTPStatus.OK, "ok")
    return None


async def main():
    _ensure_loaded()
    log.info("🚀 OmniVoice WS service listening on 0.0.0.0:%d/tts (auth=%s, sr=%d, num_step=%d)", PORT, "on" if TOKEN else "off", SR, NUM_STEP)
    async with websockets.serve(
        handler, "0.0.0.0", PORT, process_request=_process_request,
        max_size=20 * 1024 * 1024, ping_interval=20, ping_timeout=20,
    ):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
