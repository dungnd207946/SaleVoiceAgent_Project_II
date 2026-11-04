"""Streaming TTS via a SEPARATE vLLM OpenAI server (santa-tts).

Phase-2 client backend. The agent worker process does NOT load the GPU transformers
backbone — vLLM owns it. This module is only:

  SOURCE  : `_vllm_token_source` — POST `/v1/completions` with `stream=true`, parse
            the SSE, yield each `<|speech_N|>` text fragment as it arrives.
  SINK    : `stream_speech_tokens_to_audio` (the Phase-1 codec sink, imported from
            `.vieneu`) — turns the speech-token fragments into float32 audio frames.

The client needs only a LIGHTWEIGHT local vieneu instance for the sink's codec
(`_decode` / `_apply_watermark` / `streaming_*` attrs / `to_list`), plus the presets
+ a standalone HF tokenizer + the phonemizer to build the prompt token ids. The
codec-only instance loads the ONNX int8 CPU decoder — NO GPU backbone (mirrors
`_load_tts_local_gguf`'s bare-instance construction).

Output: PCM int16, 24kHz, mono — identical contract to AsyncVieNeuTTS / RemoteTTS.

Singletons: codec-only instance + tokenizer loaded once, reused across all sessions.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

from noble_agent.config import settings
from noble_agent.voice.tts.vieneu import (
    _REFERENCE_DIR,
    _f32_to_pcm16,
    _normalize_for_vieneu,
    _resolve_voice,
    stream_speech_tokens_to_audio,
)

logger = logging.getLogger("vieneu_vllm")

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="vieneu_vllm")

# ── Module-level singletons ───────────────────────────────────────────────────

_tts_instance = None
_voice_data: dict[str, Any] | None = None
_tokenizer = None


def _load_codec_only():
    """Construct a codec-only vieneu instance (ONNX int8 decoder, NO GPU backbone).

    Mirrors `_load_tts_local_gguf`'s bare-instance pattern: `backbone_repo=None`
    skips the HF backbone download; the library's warmup-failed WARNING (backbone is
    None, expected) is silenced. Then load the precomputed presets and resolve the
    configured voice. Cached as a module-level singleton so the codec loads once.
    """
    global _tts_instance, _voice_data
    if _tts_instance is not None:
        return _tts_instance, _voice_data

    import logging as _logging

    from vieneu.standard import VieNeuTTS as _VieNeuTTS

    _vieneu_logger = _logging.getLogger("Vieneu.Standard")
    _orig_level = _vieneu_logger.level
    _vieneu_logger.setLevel(_logging.ERROR)  # suppress WARNING: Warmup failed (no backbone)
    # backbone_repo="" (NOT None): the lib's __init__ does `backbone_repo.rstrip("/")`
    # unconditionally before the `if backbone_repo:` load guard, so None crashes; ""
    # is falsy → skips the GPU backbone load (vLLM owns it) without the AttributeError.
    tts = _VieNeuTTS(
        backbone_repo="",
        codec_repo=settings.vieneu_codec_repo,
        codec_device=settings.vieneu_codec_device,
    )
    _vieneu_logger.setLevel(_orig_level)

    presets_path = (
        Path(settings.vieneu_presets_path) if settings.vieneu_presets_path else _REFERENCE_DIR / "presets.json"
    )
    tts._load_voices_from_file(presets_path)
    logger.info("vieneu_vllm: codec-only instance ready, presets from %s", presets_path)

    voice = _resolve_voice(tts, settings.vieneu_voice_id or None)
    _tts_instance, _voice_data = tts, voice
    return _tts_instance, _voice_data


def _get_tokenizer():
    """A standalone HF tokenizer for prompt-token-id construction (NOT the backbone).

    Cached as a module-level singleton. trust_remote_code mirrors the library's own
    `AutoTokenizer.from_pretrained(..., trust_remote_code=True)`.
    """
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    from transformers import AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained(
        settings.vieneu_vllm_model, trust_remote_code=True, token=settings.hf_token or None
    )
    return _tokenizer


def _phonemize_ref(text: str) -> str:
    from vieneu_utils.phonemize_text import phonemize_with_dict

    return phonemize_with_dict(text)


def _phonemize_chunk(text: str) -> str:
    from vieneu_utils.phonemize_text import phonemize_with_dict

    return phonemize_with_dict(text, skip_normalize=True)


def _build_prompt_token_ids(tok: Any, voice: dict[str, Any], text: str) -> list[int]:
    """Build the santa-tts prompt as a flat list of token ids (spike form).

    Mirrors `vieneu.standard._apply_chat_template` (standard.py:313-341) field-for-
    field, branching on `settings.vieneu_use_chat_format` the same way the library
    branches on `self.use_chat_format`. The local santa path applies the same
    operator override (vieneu.py:203-205), so the vLLM backend must too — else
    setting VIENEU_USE_CHAT_FORMAT=true (the documented fix for garbled santa-tts
    audio) would silently keep the non-chat prompt here → garbled audio only on
    this backend.

    Non-chat branch (default for santa-tts, flag None/False):
        [<|TEXT_PROMPT_START|>] + emotion(<|emotion_0|>) + encode(f"{ref_ph} {chunk_ph}")
        + [<|TEXT_PROMPT_END|>, <|SPEECH_GENERATION_START|>]
        + encode("".join(<|speech_i|> for i in ref_codes))

    Chat branch (flag True): the lib's chat wrapper with the text/codes spliced in.
    Reference phonemes use the full normalize pass; the chunk skips it (already done
    by `_normalize_for_vieneu` upstream).
    """
    ref_ph = _phonemize_ref(voice["text"])
    chunk_ph = _phonemize_chunk(text)
    full_phonemes = f"{ref_ph} {chunk_ph}"

    text_prompt_start = tok.convert_tokens_to_ids("<|TEXT_PROMPT_START|>")
    text_prompt_end = tok.convert_tokens_to_ids("<|TEXT_PROMPT_END|>")
    speech_gen_start = tok.convert_tokens_to_ids("<|SPEECH_GENERATION_START|>")

    input_ids = tok.encode(full_phonemes, add_special_tokens=False)
    codes_str = "".join(f"<|speech_{i}|>" for i in voice["codes"])
    codes_ids = tok.encode(codes_str, add_special_tokens=False)

    if settings.vieneu_use_chat_format:
        # Mirrors standard.py:325-336 chat branch (NB: no emotion prefix there).
        text_replace = tok.convert_tokens_to_ids("<|TEXT_REPLACE|>")
        speech_replace = tok.convert_tokens_to_ids("<|SPEECH_REPLACE|>")

        chat = "user: Convert the text to speech:<|TEXT_REPLACE|>\nassistant:<|SPEECH_REPLACE|>"
        ids = tok.encode(chat)  # default add_special_tokens=True, as the lib does

        text_replace_idx = ids.index(text_replace)
        ids = ids[:text_replace_idx] + [text_prompt_start] + input_ids + [text_prompt_end] + ids[text_replace_idx + 1 :]

        speech_replace_idx = ids.index(speech_replace)
        return ids[:speech_replace_idx] + [speech_gen_start] + list(codes_ids)

    emotion_ids = tok.encode("<|emotion_0|>", add_special_tokens=False)  # default_emotion "natural"
    return [text_prompt_start] + emotion_ids + input_ids + [text_prompt_end, speech_gen_start] + codes_ids


# Process-level latch: the `/health` probe is a startup liveness gate, not a
# per-clause check. The resident TTS service builds a fresh client per WS
# connection (i.e. per clause), so without this we'd re-probe vLLM on every
# clause. Cache ONLY success — a failed probe must keep raising every
# construction until the server comes up (startup fail-fast preserved).
_probed_ok = False


def _ensure_probed() -> None:
    """Probe the vLLM `/health` at most once per process (on success).

    Returns early if a previous probe already succeeded. On failure the latch is
    left unset, so the next construction re-probes and the init-time fallback
    chain still reaches local vieneu when the server is down.
    """
    global _probed_ok
    if _probed_ok:
        return
    _probe_server_alive()
    _probed_ok = True


def _probe_server_alive() -> None:
    """Cheap liveness check against the vLLM server's `/health`.

    Raises on connection error / non-200 so the init-time TTS fallback chain is
    meaningful: a down vLLM server makes `AsyncVieNeuVLLMTTS()` construction fail,
    so `_create_tts` moves on to the next backend (elevenlabs → local vieneu)
    instead of returning a backend that only errors on the first `stream()` (there
    is NO mid-session fallback). Heavy import function-local.
    """
    import requests

    url = f"{settings.vieneu_vllm_url.rstrip('/')}/health"
    resp = requests.get(url, timeout=2)
    resp.raise_for_status()


def _post_completions(url: str, payload: dict[str, Any]):
    """POST a streaming `/v1/completions` request; return the streaming response.

    Sync (the source runs in the executor thread), heavy import function-local.
    Factored out so the unit tests can monkeypatch it without a live server.
    """
    import requests

    resp = requests.post(url, json=payload, stream=True, timeout=(5, 300))
    resp.raise_for_status()
    return resp


def _vllm_token_source(text: str, *, stop_event: threading.Event) -> Iterator[str]:
    """Stream `<|speech_N|>` text fragments from the vLLM `/v1/completions` server.

    Builds the prompt token ids (standalone tokenizer + phonemizer), POSTs with the
    spike-verified payload, and parses the SSE: each `data:` line is JSON
    `{"choices":[{"text": "<|speech_N|>", ...}]}`, terminated by `data: [DONE]`. The
    `stop_event` is checked between lines and closes the HTTP response on barge-in so
    the remote generation is cancelled (not just the socket dropped).

    Each SSE piece carries exactly one speech token (vLLM `skip_special_tokens=false`
    + one-token-per-piece), so a fragment == one frame for the sink.
    """
    _, voice = _load_codec_only()
    tok = _get_tokenizer()
    prompt_ids = _build_prompt_token_ids(tok, voice, text)
    speech_end_id = tok.convert_tokens_to_ids("<|SPEECH_GENERATION_END|>")

    # Degenerate case: the prompt alone already meets/exceeds the context. No
    # max_tokens floor can save it — vLLM would 400 ("maximum context length")
    # regardless. This is a misconfig (max_model_len too small / a huge ref voice
    # `text`); raise a clear error rather than firing a doomed request.
    max_model_len = settings.vieneu_vllm_max_model_len
    if len(prompt_ids) >= max_model_len:
        raise ValueError(
            f"vieneu_vllm prompt ({len(prompt_ids)} tokens) exceeds vieneu_vllm_max_model_len "
            f"({max_model_len}); no output budget remains. Increase the server's --max-model-len "
            f"(and VIENEU_VLLM_MAX_MODEL_LEN) or shorten the reference voice text."
        )

    # Clamp the output budget to fit the context: prompt_len + max_tokens must not
    # exceed the server's --max-model-len, else vLLM returns HTTP 400 → no audio.
    effective_max = max(1, min(settings.vieneu_vllm_max_tokens, max_model_len - len(prompt_ids)))
    # Never send min_tokens > max_tokens (also a 400). When a near-limit prompt
    # clamps max below the configured min, lower min to match.
    effective_min = min(settings.vieneu_vllm_min_tokens, effective_max)

    payload = {
        "model": settings.vieneu_vllm_model,
        "prompt": prompt_ids,
        "stream": True,
        "min_tokens": effective_min,  # REQUIRED — else EOS immediately → empty audio
        "max_tokens": effective_max,
        "temperature": settings.vieneu_vllm_temperature,
        "top_k": settings.vieneu_vllm_top_k,
        "stop_token_ids": [speech_end_id],
        "skip_special_tokens": False,  # REQUIRED — keep <|speech_N|> in the streamed text
    }

    url = f"{settings.vieneu_vllm_url.rstrip('/')}/v1/completions"
    resp = _post_completions(url, payload)
    try:
        for raw in resp.iter_lines():
            if stop_event.is_set():
                break
            if not raw:
                continue
            line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            fragment = obj["choices"][0].get("text") or ""
            if fragment:
                yield fragment
    finally:
        with contextlib.suppress(Exception):
            resp.close()


# ── Sync wrapper ──────────────────────────────────────────────────────────────


class VieNeuVLLMTTS:
    """Synchronous streaming TTS — yields PCM int16 bytes per audio chunk."""

    def __init__(self):
        # Probe FIRST (before the codec load) so a down vLLM server raises here and
        # the init-time fallback chain moves on to a working backend — we don't pay
        # the codec load when the server is unreachable. Guarded so the per-clause
        # client construction in the resident service does not re-probe each time.
        _ensure_probed()
        self._tts, self._voice = _load_codec_only()
        self._stop_event = threading.Event()
        # Guards read/write of `_stop_event` so a `pause()` from a different task than
        # the one running `stream()` reaches the active stream (mirrors VieNeuTTS H5).
        self._lock = threading.Lock()

    def set_voice(self, voice_id: str) -> None:
        try:
            self._voice = self._tts.get_preset_voice(voice_id)
            logger.info("Voice switched to: %s", voice_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Voice %r not found: %s", voice_id, exc)

    async def pause(self) -> None:
        """Barge-in: signal the active stream to stop (cancels the vLLM HTTP stream).

        Async to match RemoteTTS.pause — `VoiceAgent.pause_tts` awaits it.
        """
        with self._lock:
            self._stop_event.set()

    def stream(self, text: str, stop_event: threading.Event | None = None) -> Iterator[bytes]:
        text = _normalize_for_vieneu(text)
        with self._lock:
            if stop_event is None:
                self._stop_event = threading.Event()
                stop_event = self._stop_event
            else:
                self._stop_event = stop_event

        source = _vllm_token_source(text, stop_event=stop_event)
        audio_iter = stream_speech_tokens_to_audio(self._tts, self._voice, source, stop_event=stop_event)
        t0 = time.monotonic()
        first_chunk = True
        for audio_chunk in audio_iter:
            if audio_chunk is None or len(audio_chunk) == 0:
                continue
            if first_chunk:
                logger.info("🔊 [TTS] TTFB: %.0fms  text=%r", (time.monotonic() - t0) * 1000, text)
                first_chunk = False
            pcm = _f32_to_pcm16(audio_chunk)
            if pcm:
                yield pcm


# ── Async wrapper ─────────────────────────────────────────────────────────────


class AsyncVieNeuVLLMTTS:
    """Async-friendly wrapper — runs the sync generator in a thread pool."""

    def __init__(self):
        self._tts = VieNeuVLLMTTS()

    def set_voice(self, voice_id: str) -> None:
        self._tts.set_voice(voice_id)

    async def pause(self) -> None:
        await self._tts.pause()

    def list_voices(self) -> list[str]:
        return [v[1] for v in self._tts._tts.list_preset_voices()]

    async def stream(self, text: str, stop_event: threading.Event | None = None) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()

        def _produce():
            try:
                for chunk in self._tts.stream(text, stop_event=stop_event):
                    loop.call_soon_threadsafe(q.put_nowait, chunk)
            except Exception as exc:  # noqa: BLE001
                logger.error("❌ [TTS] vieneu_vllm produce error: %s", exc)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)

        loop.run_in_executor(_executor, _produce)

        while True:
            chunk = await q.get()
            if chunk is None:
                break
            yield chunk
