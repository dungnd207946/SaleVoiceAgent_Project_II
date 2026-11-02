"""Streaming TTS via VieNeu-TTS.

Loading mode auto-detected from `VIENEU_BACKBONE_REPO` (see `_load_tts`):
  1. Local directory containing *.gguf → `_load_tts_local_gguf` (Llama direct; Metal on Apple Silicon).
  2. HuggingFace repo_id ending in "gguf" → `_load_tts_hf` (legacy quantized download).
  3. HuggingFace safetensors repo (e.g. NobleX-AI/santa-tts) → `_load_tts_santa`:
       → snapshot the backbone at `VIENEU_HF_REVISION` (default `prod`) out-of-band
         (the library has no revision kwarg) and feed the local snapshot dir to Vieneu
       → transformers backbone on `VIENEU_BACKBONE_DEVICE` (gguf_filename=None forces this branch)
       → decode-only ONNX int8 codec on `VIENEU_CODEC_DEVICE`
       → voice from a precomputed `reference/presets.json` (built offline by
         scripts/build_vieneu_voices.py); optional `VIENEU_USE_CHAT_FORMAT` override.

Output: PCM int16, 24kHz, mono — identical to ElevenLabs/OpenAI PCM path.

Singleton: model loaded once, reused across all sessions.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import numpy as np

try:
    from huggingface_hub import snapshot_download
except ImportError:  # huggingface_hub is part of the tts-vieneu extra
    snapshot_download = None

from noble_agent.config import settings

logger = logging.getLogger("vieneu")

_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="vieneu")
_inference_lock = threading.Lock()

# ── Module-level singleton ────────────────────────────────────────────────────

_tts_instance = None
_voice_data: dict[str, Any] | None = None

# ── Phoneme normalize (shared utility) ──────────────────────────────────────

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_PHONEME_FILE = _PROJECT_ROOT / "data" / "tts_phoneme.json"

from noble_agent.voice.tts._normalize import apply_normalize, load_normalize_map

_normalize_map_cache: dict[str, str] | None = None


def _normalize_for_vieneu(text: str) -> str:
    global _normalize_map_cache
    if _normalize_map_cache is None:
        _normalize_map_cache = load_normalize_map(_PHONEME_FILE)
    return apply_normalize(text, _normalize_map_cache, word_boundary=False)


def _load_tts_local_gguf(local_dir: Path, gguf_file: Path):
    """
    Load VieNeu-TTS from a local GGUF file, bypassing HuggingFace entirely.
    Uses VieNeuTTS internal API: create instance without backbone, inject Llama directly.
    On Apple Silicon: n_gpu_layers=-1 enables Metal acceleration.
    """
    from llama_cpp import Llama
    from vieneu.standard import VieNeuTTS as _VieNeuTTS

    logger.info("Loading VieNeu-TTS (local GGUF): %s", gguf_file)
    logger.info("  codec=neucodec-onnx-decoder-int8 (cpu)")

    # Step 1: Create bare instance — backbone_repo=None skips HF download.
    # _warmup_model() inside __init__ will fail silently (backbone=None, expected).
    # We silence Vieneu.Standard logger during construction to avoid misleading warning.
    import logging as _logging

    _vieneu_logger = _logging.getLogger("Vieneu.Standard")
    _orig_level = _vieneu_logger.level
    _vieneu_logger.setLevel(_logging.ERROR)  # suppress WARNING: Warmup failed
    tts = _VieNeuTTS(
        backbone_repo=None,
        codec_repo="neuphonic/neucodec-onnx-decoder-int8",
        codec_device="cpu",
    )
    _vieneu_logger.setLevel(_orig_level)  # restore

    # Step 2: Inject GGUF backbone — Metal on Apple Silicon (n_gpu_layers=-1)
    import platform

    n_gpu_layers = -1 if platform.system() == "Darwin" else 0
    logger.info("  backbone: %s  gpu_layers=%d", gguf_file.name, n_gpu_layers)
    tts.backbone = Llama(
        model_path=str(gguf_file),
        n_ctx=tts.max_context,
        n_gpu_layers=n_gpu_layers,
        verbose=False,
        mlock=True,
    )
    tts._is_quantized_model = True

    # Step 3: Load voices from local voices.json
    voices_path = local_dir / "voices.json"
    if voices_path.exists():
        tts._load_voices_from_file(voices_path)
        logger.info("  voices loaded: %d presets", len(tts._preset_voices))
    else:
        logger.warning("  voices.json not found in %s", local_dir)

    # Step 4: Warmup with backbone now active
    tts._warmup_model()

    # Resolve voice preset
    voice_id = settings.vieneu_voice_id or None
    try:
        voice = tts.get_preset_voice(voice_id)
        logger.info("  voice: %s", voice_id or "(default)")
    except Exception as exc:
        logger.warning("  voice %r not found (%s), using first available", voice_id, exc)
        voices = tts.list_preset_voices()
        voice = tts.get_preset_voice(voices[0][1]) if voices else None

    logger.info("VieNeu-TTS (local) ready.")
    return tts, voice


_REFERENCE_DIR = Path(__file__).resolve().parent / "reference"


def _resolve_voice(tts, voice_id: str | None):
    """Resolve a preset voice, falling back to the first available on miss."""
    try:
        voice = tts.get_preset_voice(voice_id)
        logger.info("  voice: %s", voice_id or "(default)")
        return voice
    except Exception as exc:
        logger.warning("  voice %r not found (%s), using first available", voice_id, exc)
        voices = tts.list_preset_voices()
        return tts.get_preset_voice(voices[0][1]) if voices else None


def _resolve_backbone_repo(repo: str, revision: str, token: str) -> str:
    """Resolve a santa backbone repo to a local snapshot dir at the given revision.

    The vieneu library has no `revision` kwarg, so we fetch the pinned revision
    out-of-band and hand the local snapshot dir to `Vieneu(backbone_repo=...)`.
    A local dir (already-resolved path) passes through unchanged. On download
    failure we log and return the original repo id so the library's own download
    path / fallback chain still runs (pre-warm-failure-mode = continue).
    """
    if Path(repo).is_dir():
        return repo
    if snapshot_download is None:
        return repo
    try:
        local = snapshot_download(repo_id=repo, revision=revision, token=token or None)
        logger.info("VieNeu backbone %s@%s → %s", repo, revision, local)
        return local
    except Exception as exc:  # noqa: BLE001 — log + fall back to library download
        logger.warning("VieNeu backbone snapshot %s@%s failed: %s — using repo id as-is", repo, revision, exc)
        return repo


def _fast_stream_single_delta(self, text, ref_codes, ref_text, emotion_tag=None):
    """Drop-in for FastVieNeuTTS._infer_stream_single fixed for lmdeploy>=0.14,
    whose stream_infer yields DELTA text (not cumulative). Otherwise identical
    windowed-decode + overlap-add incremental streaming (TTFB ~175ms, RTF ~0.1)."""
    from vieneu.utils import _linear_overlap_add

    ref_codes_list = self.to_list(ref_codes)
    prompt = self._format_prompt(
        ref_codes_list, ref_text, text, use_chat_format=self.use_chat_format, emotion_tag=emotion_tag
    )
    audio_cache = []
    token_cache = [f"<|speech_{i}|>" for i in ref_codes_list]
    n_decoded_samples = 0
    n_decoded_tokens = len(ref_codes_list)
    for response in self.backbone.stream_infer([prompt], gen_config=self.gen_config, do_preprocess=False):
        new_tokens = response.text  # lmdeploy>=0.14: each yield is the new delta directly
        if new_tokens:
            token_cache.append(new_tokens)
        if len(token_cache[n_decoded_tokens:]) >= self.streaming_frames_per_chunk + self.streaming_lookforward:
            ts = max(n_decoded_tokens - self.streaming_lookback - self.streaming_overlap_frames, 0)
            te = (
                n_decoded_tokens
                + self.streaming_frames_per_chunk
                + self.streaming_lookforward
                + self.streaming_overlap_frames
            )
            ss = (n_decoded_tokens - ts) * self.hop_length
            se = ss + (self.streaming_frames_per_chunk + 2 * self.streaming_overlap_frames) * self.hop_length
            recon = self._apply_watermark(self._decode("".join(token_cache[ts:te])))[ss:se]
            audio_cache.append(recon)
            proc = _linear_overlap_add(audio_cache, stride=self.streaming_stride_samples)
            ne = len(audio_cache) * self.streaming_stride_samples
            out = proc[n_decoded_samples:ne]
            n_decoded_samples = ne
            n_decoded_tokens += self.streaming_frames_per_chunk
            yield out
    rem = len(token_cache) - n_decoded_tokens
    if rem > 0:
        ts = max(len(token_cache) - (self.streaming_lookback + self.streaming_overlap_frames + rem), 0)
        ss = (len(token_cache) - ts - rem - self.streaming_overlap_frames) * self.hop_length
        recon = self._apply_watermark(self._decode("".join(token_cache[ts:])))[ss:]
        audio_cache.append(recon)
        proc = _linear_overlap_add(audio_cache, stride=self.streaming_stride_samples)[n_decoded_samples:]
        yield proc


def _load_tts_santa(repo_id: str):
    """Load a safetensors VieNeu backbone (e.g. NobleX-AI/santa-tts) on GPU.

    `gguf_filename=None` forces the transformers branch (the library default
    filename would otherwise force GGUF even for a safetensors repo). Voices come
    from a precomputed reference/presets.json (built offline with the full torch
    codec), not from the repo. The ONNX int8 decoder runs on CPU.
    """
    from vieneu import Vieneu

    backbone = _resolve_backbone_repo(repo_id, settings.vieneu_hf_revision, settings.hf_token)
    logger.info(
        "Loading VieNeu-TTS (santa/safetensors): %s on %s, codec=%s/%s ...",
        backbone,
        settings.vieneu_backbone_device,
        settings.vieneu_codec_repo,
        settings.vieneu_codec_device,
    )
    import types

    try:
        # Preferred: lmdeploy turbomind → true incremental streaming (TTFB ~175ms).
        # backbone = revision-pinned local snapshot (see _resolve_backbone_repo).
        tts = Vieneu(
            mode="fast",
            backbone_repo=backbone,
            backbone_device=settings.vieneu_backbone_device,
            codec_repo=settings.vieneu_codec_repo,
            codec_device=settings.vieneu_codec_device,
            memory_util=0.3,
            hf_token=settings.hf_token,
        )
        # lmdeploy>=0.14 stream_infer yields DELTA text; vieneu's fast.py assumes
        # cumulative → patch the per-sentence windowed-stream decode.
        tts._infer_stream_single = types.MethodType(_fast_stream_single_delta, tts)
        logger.info("  TTS engine: fast (lmdeploy turbomind, incremental streaming)")
    except Exception as exc:  # noqa: BLE001 — lmdeploy missing/incompatible → batch fallback
        logger.warning("  fast mode unavailable (%s) — falling back to standard (batch, higher latency)", exc)
        tts = Vieneu(
            mode="standard",
            backbone_repo=backbone,
            backbone_device=settings.vieneu_backbone_device,
            gguf_filename=None,
            codec_repo=settings.vieneu_codec_repo,
            codec_device=settings.vieneu_codec_device,
            hf_token=settings.hf_token,
        )

    presets_path = (
        Path(settings.vieneu_presets_path) if settings.vieneu_presets_path else _REFERENCE_DIR / "presets.json"
    )
    tts._load_voices_from_file(presets_path)
    logger.info("  presets loaded from %s", presets_path)

    if settings.vieneu_use_chat_format is not None:
        tts.use_chat_format = settings.vieneu_use_chat_format
        logger.info("  use_chat_format override → %s", settings.vieneu_use_chat_format)

    _accelerate_backbone(tts)

    voice = _resolve_voice(tts, settings.vieneu_voice_id or None)
    logger.info("VieNeu-TTS (santa) ready.")
    return tts, voice


_DTYPE_MAP: dict[str, str] = {"bfloat16": "bfloat16", "float16": "float16", "float32": "float32"}


def _accelerate_backbone(tts) -> None:
    """Cast the safetensors backbone to bf16/fp16 and optionally torch.compile it.

    transformers' `from_pretrained` (in the library's `_load_backbone`) loads with no
    `torch_dtype` → fp32, which leaves the GPU tensor cores idle and roughly doubles
    per-step latency. We cast post-load, then optionally torch.compile to cut the
    launch overhead of the batch=1 autoregressive `generate` loop. A final warmup
    re-traces the graph so the first real call doesn't pay the cast/compile cost.

    No-op for the gguf/quantized backbone or a cpu device (cast/compile don't apply).
    """
    backbone = getattr(tts, "backbone", None)
    if backbone is None or getattr(tts, "_is_quantized_model", False):
        return
    if not settings.vieneu_backbone_device.lower().startswith("cuda"):
        return

    import torch

    dtype_name = _DTYPE_MAP.get(settings.vieneu_backbone_dtype.lower())
    if dtype_name and dtype_name != "float32":
        tts.backbone = tts.backbone.to(getattr(torch, dtype_name))
        logger.info("  backbone cast → %s", dtype_name)

    if settings.vieneu_compile_backbone:
        try:
            tts.backbone = torch.compile(tts.backbone, mode="reduce-overhead")
            logger.info("  backbone torch.compile(reduce-overhead) enabled")
        except Exception as exc:  # noqa: BLE001 — compile is best-effort; fall back to eager
            logger.warning("  torch.compile failed (%s) — continuing uncompiled", exc)

    try:
        tts._warmup_model()
    except Exception as exc:  # noqa: BLE001 — warmup is best-effort (matches library behavior)
        logger.warning("  post-accelerate warmup failed: %s", exc)


def _load_tts_hf(repo_id: str):
    """Load VieNeu-TTS from HuggingFace (downloads ~800MB on first run)."""
    from vieneu import Vieneu

    logger.info("Loading VieNeu-TTS from HuggingFace: %s ...", repo_id)
    tts = Vieneu(
        mode="standard",
        backbone_repo=repo_id,
        backbone_device="cpu",
        codec_repo="neuphonic/neucodec-onnx-decoder-int8",
        codec_device="cpu",
    )

    voice_id = settings.vieneu_voice_id or None
    try:
        voice = tts.get_preset_voice(voice_id)
        logger.info("  voice: %s", voice_id or "(default)")
    except Exception as exc:
        logger.warning("  voice %r not found (%s), using first available", voice_id, exc)
        voices = tts.list_preset_voices()
        voice = tts.get_preset_voice(voices[0][1]) if voices else None

    logger.info("VieNeu-TTS (HuggingFace) ready.")
    return tts, voice


def _load_tts():
    """
    Load VieNeu model once, cache as module-level singleton.

    Auto-detects loading mode:
      - Local directory with *.gguf → fast local load, no download
      - HuggingFace repo_id → download on first run
    """
    global _tts_instance, _voice_data
    if _tts_instance is not None:
        return _tts_instance, _voice_data

    repo = settings.vieneu_backbone_repo

    # ── Detect local GGUF directory ───────────────────────────────────────────
    local_path = Path(repo)
    if local_path.is_dir():
        gguf_files = sorted(local_path.glob("*.gguf"))
        if gguf_files:
            _tts_instance, _voice_data = _load_tts_local_gguf(local_path, gguf_files[0])
            return _tts_instance, _voice_data
        else:
            logger.warning("Directory %s has no *.gguf files — falling back to HF load", repo)

    # ── HuggingFace repo ──────────────────────────────────────────────────────
    # Non-local, non-gguf safetensors repo (e.g. NobleX-AI/santa-tts) → santa
    # loader (GPU backbone + precomputed presets.json). gguf HF repos keep the
    # legacy _load_tts_hf path.
    if "gguf" in repo.lower():
        _tts_instance, _voice_data = _load_tts_hf(repo)
    else:
        _tts_instance, _voice_data = _load_tts_santa(repo)
    return _tts_instance, _voice_data


def _f32_to_pcm16(audio: np.ndarray) -> bytes:
    """Convert float32 [-1.0, 1.0] → PCM int16 little-endian bytes."""
    return np.clip(audio * 32767.0, -32768.0, 32767.0).astype(np.int16).tobytes()


# ── Codec SINK (source-agnostic incremental decoder) ──────────────────────────


def stream_speech_tokens_to_audio(
    tts: Any,
    voice: dict[str, Any],
    token_text_iter: Iterator[str],
    *,
    stop_event: threading.Event | None = None,
) -> Iterator[np.ndarray]:
    """Incrementally decode a stream of speech-token text fragments to audio.

    Source-agnostic SINK (Phase 1 = local generate, Phase 2 = vLLM client feed the
    same function). `tts` is a vieneu lib instance, used ONLY for `_decode` /
    `_apply_watermark` / the `streaming_*` attrs — never for generation. `voice`
    seeds the initial `token_cache` with the reference `codes` (so chunk windows
    have lookback context, matching `_infer_stream_ggml`). `token_text_iter` yields
    str fragments each containing zero or more `<|speech_N|>` tokens. Honors
    `stop_event` (barge-in) between chunks. Yields float32 audio frames.

    Mirrors `vieneu/standard.py:_infer_stream_ggml` (lines 394-432) verbatim for the
    chunk window math, `_linear_overlap_add`, and trailing-remainder flush.
    """
    from vieneu.utils import _linear_overlap_add

    ref_codes_list = tts.to_list(voice["codes"]) if hasattr(tts, "to_list") else list(voice["codes"])

    audio_cache: list[np.ndarray] = []
    token_cache: list[str] = [f"<|speech_{idx}|>" for idx in ref_codes_list]
    n_decoded_samples = 0
    n_decoded_tokens = len(ref_codes_list)

    for fragment in token_text_iter:
        if stop_event is not None and stop_event.is_set():
            return
        token_cache.append(fragment)

        if len(token_cache[n_decoded_tokens:]) >= tts.streaming_frames_per_chunk + tts.streaming_lookforward:
            tokens_start = max(n_decoded_tokens - tts.streaming_lookback - tts.streaming_overlap_frames, 0)
            tokens_end = (
                n_decoded_tokens
                + tts.streaming_frames_per_chunk
                + tts.streaming_lookforward
                + tts.streaming_overlap_frames
            )
            sample_start = (n_decoded_tokens - tokens_start) * tts.hop_length
            chunk_frames = tts.streaming_frames_per_chunk + 2 * tts.streaming_overlap_frames
            sample_end = sample_start + chunk_frames * tts.hop_length
            curr_codes = token_cache[tokens_start:tokens_end]
            recon = tts._decode("".join(curr_codes))
            recon = tts._apply_watermark(recon)
            recon = recon[sample_start:sample_end]
            audio_cache.append(recon)

            processed_recon = _linear_overlap_add(audio_cache, stride=tts.streaming_stride_samples)
            new_samples_end = len(audio_cache) * tts.streaming_stride_samples
            processed_recon = processed_recon[n_decoded_samples:new_samples_end]
            n_decoded_samples = new_samples_end
            n_decoded_tokens += tts.streaming_frames_per_chunk
            yield processed_recon

    if stop_event is not None and stop_event.is_set():
        return

    remaining_tokens = len(token_cache) - n_decoded_tokens
    if remaining_tokens > 0:
        window = tts.streaming_lookback + tts.streaming_overlap_frames + remaining_tokens
        tokens_start = max(len(token_cache) - window, 0)
        start_frames = len(token_cache) - tokens_start - remaining_tokens - tts.streaming_overlap_frames
        sample_start = start_frames * tts.hop_length
        curr_codes = token_cache[tokens_start:]
        recon = tts._decode("".join(curr_codes))
        recon = tts._apply_watermark(recon)
        recon = recon[sample_start:]
        audio_cache.append(recon)
        processed_recon = _linear_overlap_add(audio_cache, stride=tts.streaming_stride_samples)
        processed_recon = processed_recon[n_decoded_samples:]
        yield processed_recon


# ── Local token SOURCE (Phase 1) ──────────────────────────────────────────────


def _build_speech_token_streamer(tts: Any):
    """A `BaseStreamer` that emits one `<|speech_N|>` text fragment per generated id.

    Why not `TextIteratorStreamer`: it (a) defaults `skip_prompt=False` so it decodes
    the WHOLE prompt first (ref phonemes + specials + ref codes), and (b) buffers
    space-less `<|speech_N|>` tokens and only flushes near the last space → fragments
    carry an unpredictable number of speech tokens and arrive late, breaking BOTH the
    sink's one-entry==one-frame invariant AND the TTFA win. This subclass instead:

      * skips the FIRST `put` (the prompt tensor) — the `skip_prompt` behavior;
      * for every later id, converts it to its token string and emits it ONLY if it
        starts with `<|speech_` (so each fragment is exactly ONE speech token →
        fragment == frame; the EOS / non-speech tokens are dropped, matching
        `_infer_stream_ggml`'s speech-only `token_cache`);
      * pushes fragments to a `queue.Queue`, `end()` pushes a sentinel.

    Returns `(streamer, queue, SENTINEL)`. The generator drains the queue.
    """
    import queue as _queue

    from transformers.generation.streamers import BaseStreamer

    sentinel = object()

    class _SpeechTokenStreamer(BaseStreamer):
        def __init__(self) -> None:
            self.queue: _queue.Queue = _queue.Queue()
            self._prompt_seen = False

        def put(self, value: Any) -> None:
            if not self._prompt_seen:
                # First call carries the prompt tensor → skip it entirely.
                self._prompt_seen = True
                return
            # `value` is a tensor of one (or a few) freshly generated ids.
            ids = value.flatten().tolist() if hasattr(value, "flatten") else list(value)
            for tok_id in ids:
                token = tts.tokenizer.convert_ids_to_tokens(int(tok_id))
                if isinstance(token, str) and token.startswith("<|speech_"):
                    self.queue.put(token)

        def end(self) -> None:
            self.queue.put(sentinel)

    streamer = _SpeechTokenStreamer()
    return streamer, streamer.queue, sentinel


def _local_token_source(
    tts: Any,
    voice: dict[str, Any],
    text: str,
    *,
    stop_event: threading.Event,
    do_sample: bool = True,
    temperature: float = 1.0,
    top_k: int = 50,
) -> Iterator[str]:
    """Stream speech-token text fragments from the local transformers backbone.

    Builds the prompt via the lib's `_apply_chat_template`, then runs
    `backbone.generate(..., streamer=_SpeechTokenStreamer(), stopping_criteria=[...])`
    on a CHILD thread (HF's streamer pattern needs generate on its own thread while we
    drain the streamer queue). We do NOT acquire `_inference_lock` here — the caller
    (executor thread) already holds it; the child runs only `generate`. The child is
    `join`ed in `finally`.

    The streamer (see `_build_speech_token_streamer`) emits exactly one `<|speech_N|>`
    per fragment (skipping the prompt + non-speech tokens), satisfying the sink's
    one-entry==one-frame contract and preserving the per-token TTFA win.

    `do_sample`/`temperature`/`top_k` default to the library's `_infer_torch` values;
    the bench round-trip test passes `do_sample=False` to make generation deterministic
    so the streamed ids can be compared id-for-id against a one-shot `_infer_torch`.
    """
    import threading as _threading

    import torch
    from transformers import StoppingCriteria, StoppingCriteriaList
    from vieneu_utils.phonemize_text import phonemize_batch

    class _EventStop(StoppingCriteria):
        """Abort generate() between tokens when the barge-in event is set (Hazard / barge-in)."""

        def __init__(self, event: _threading.Event):
            self._event = event

        def __call__(self, input_ids, scores, **kwargs) -> bool:
            return self._event.is_set()

    ref_phonemes = tts.get_ref_phonemes(voice["text"])
    chunk_phonemes = phonemize_batch([text], skip_normalize=True)[0]
    prompt_ids = tts._apply_chat_template(voice["codes"], ref_phonemes, chunk_phonemes, emotion_tag=tts.default_emotion)

    streamer, q, sentinel = _build_speech_token_streamer(tts)
    speech_end_id = tts.tokenizer.convert_tokens_to_ids("<|SPEECH_GENERATION_END|>")
    prompt_tensor = torch.tensor(prompt_ids).unsqueeze(0).to(tts.backbone.device)

    def _generate():
        with torch.no_grad():
            tts.backbone.generate(
                prompt_tensor,
                max_length=tts.max_context,
                eos_token_id=speech_end_id,
                do_sample=do_sample,
                temperature=temperature,
                top_k=top_k,
                use_cache=True,
                min_new_tokens=50,
                streamer=streamer,
                stopping_criteria=StoppingCriteriaList([_EventStop(stop_event)]),
            )

    gen_thread = _threading.Thread(target=_generate, name="vieneu-generate", daemon=True)
    gen_thread.start()
    try:
        while True:
            if stop_event.is_set():
                break
            fragment = q.get()
            if fragment is sentinel:
                break
            yield fragment
    finally:
        gen_thread.join()


# ── Sync wrapper ──────────────────────────────────────────────────────────────


class VieNeuTTS:
    """Synchronous streaming TTS — yields PCM int16 bytes per audio chunk."""

    def __init__(self):
        self._tts, self._voice = _load_tts()
        self._stop_event = threading.Event()
        # Guards the read/write of `_stop_event` so a `pause()` (from a different task
        # than the one running `stream()`) reliably reaches the active stream and a
        # `pause()` arriving between turns can't wedge (H5: stop_event race).
        self._lock = threading.Lock()

    def set_voice(self, voice_id: str) -> None:
        """Switch to a different preset voice by ID (e.g. 'Ly', 'Doan')."""
        try:
            self._voice = self._tts.get_preset_voice(voice_id)
            logger.info("Voice switched to: %s", voice_id)
        except Exception as exc:
            logger.warning("Voice %r not found: %s", voice_id, exc)

    async def pause(self) -> None:
        """Barge-in: signal the currently active stream to stop (generate thread + sink).

        Async to match `RemoteTTS.pause` — `VoiceAgent.pause_tts` does `await pause()`;
        a sync def would make `await None` raise TypeError (swallowed every barge-in,
        leaving the event unset). Sets the event captured under `_lock` so it always
        targets the stream currently in flight (H5).
        """
        with self._lock:
            self._stop_event.set()

    def stream(self, text: str, stop_event: threading.Event | None = None) -> Iterator[bytes]:
        text = _normalize_for_vieneu(text)
        # Bind the per-turn event under the lock so a concurrent `pause()` reads/sets
        # the same event this stream uses (no read/write race on the attribute). A
        # caller-supplied event (e.g. the remote service) wires barge-in directly.
        with self._lock:
            if stop_event is None:
                self._stop_event = threading.Event()
                stop_event = self._stop_event
            else:
                self._stop_event = stop_event

        with _inference_lock:
            t0 = time.monotonic()
            first_chunk = True
            if settings.tts_streaming:
                source = _local_token_source(self._tts, self._voice, text, stop_event=stop_event)
                audio_iter = stream_speech_tokens_to_audio(self._tts, self._voice, source, stop_event=stop_event)
            else:
                audio_iter = self._tts.infer_stream(text, voice=self._voice)

            for audio_chunk in audio_iter:
                if audio_chunk is None or len(audio_chunk) == 0:
                    continue
                if first_chunk:
                    logger.info("🔊 [TTS] TTFB: %.0fms  text=%r", (time.monotonic() - t0) * 1000, text)
                    first_chunk = False
                pcm = _f32_to_pcm16(audio_chunk)
                # Re-chunk into ~20ms frames: the fast (lmdeploy) path emits large
                # ~1s blobs that the LiveKit AudioSource rejects (capture_frame
                # InvalidState). Uniform small frames feed cleanly + pace naturally.
                frame_bytes = int(settings.tts_sample_rate * 0.02) * 2  # 20ms int16, even
                for i in range(0, len(pcm), frame_bytes):
                    sub = pcm[i : i + frame_bytes]
                    if sub:
                        yield sub


# ── Async wrapper ─────────────────────────────────────────────────────────────


class AsyncVieNeuTTS:
    """Async-friendly wrapper — runs sync VieNeu generator in thread pool."""

    def __init__(self):
        self._tts = VieNeuTTS()

    def set_voice(self, voice_id: str) -> None:
        self._tts.set_voice(voice_id)

    async def pause(self) -> None:
        """Barge-in: delegate to the sync wrapper's (async) stop-event setter."""
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
            except Exception as exc:
                logger.error("❌ [TTS] VieNeu produce error: %s", exc)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)

        loop.run_in_executor(_executor, _produce)

        while True:
            chunk = await q.get()
            if chunk is None:
                break
            yield chunk
