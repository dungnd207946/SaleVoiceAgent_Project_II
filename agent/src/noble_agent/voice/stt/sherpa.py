"""Streaming STT via sherpa-onnx — Zipformer transducer, in-process.

Model-agnostic: the encoder/decoder/joiner ONNX filename stem is auto-discovered
by globbing SHERPA_MODEL_DIR for the family selected by SHERPA_MODEL_QUANTIZE
(false → `encoder-*.onnx` excluding `*.int8.onnx`; true → `encoder-*.int8.onnx`),
so swapping models is a config change, not a code change. On a missing dir the
model self-provisions from SHERPA_HF_REPO at revision SHERPA_HF_REVISION
(default `prod`, etag-cached, idempotent) then re-globs. Interface
(on_partial / on_final) and audio format (PCM int16, 16kHz, mono) are fixed.
Feature extraction (25ms frame / 10ms shift / 80 mel bins) uses sherpa-onnx
defaults, matching the training config.

Currently serves: hynt-bilingual (Vietnamese + English streaming Zipformer,
WER ~1.9% streaming on the hotline test set). It emits ALL-CAPS text with
punctuation; SHERPA_PRESERVE_CASE=false (the configured default for it)
lowercases and sentence-caps the result, true keeps the raw caps.
Speed: decoded well above realtime on CPU.

Architecture:
  Main asyncio thread  →  stdlib Queue  →  Background decode thread
  Background thread    →  asyncio.run_coroutine_threadsafe  →  callbacks

The recognizer singleton is shared across sessions (thread-safe at stream level).
Each session gets its own OnlineStream via recognizer.create_stream().
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue as stdlib_queue
import threading
from collections.abc import Callable

import numpy as np

try:
    from huggingface_hub import snapshot_download
except ImportError:  # huggingface_hub is part of the stt-sherpa extra
    snapshot_download = None

from noble_agent.config import settings

logger = logging.getLogger(__name__)


# ── Pure helpers ──────────────────────────────────────────────────────────────


def _compose_model_paths(model_dir: str, model_name: str) -> dict[str, str]:
    """Build the encoder/decoder/joiner/tokens paths for a sherpa transducer.

    The fp32-vs-int8 choice is carried purely by `model_name` (append `.int8`).
    """
    return {
        "encoder": f"{model_dir}/encoder-{model_name}.onnx",
        "decoder": f"{model_dir}/decoder-{model_name}.onnx",
        "joiner": f"{model_dir}/joiner-{model_name}.onnx",
        "tokens": f"{model_dir}/tokens.txt",
    }


def _postprocess_text(raw: str, preserve_case: bool) -> str:
    """Trim recognizer output; legacy mode also lower-cases + capitalizes."""
    return raw.strip() if preserve_case else raw.strip().lower().capitalize()


def _discover_model_stem(filenames: list[str], quantize: bool) -> str | None:
    """Find the encoder filename stem in a dir listing for the requested family.

    `quantize=False` selects `encoder-*.onnx` excluding `*.int8.onnx`;
    `quantize=True` selects only `encoder-*.int8.onnx`. The stem is the encoder
    filename with the `encoder-` prefix and trailing `.onnx` stripped (the int8
    stem retains its `.int8` suffix so `_compose_model_paths` composes correctly).

    Returns None when no encoder matches (the caller then downloads from HF and
    re-globs). Raises ValueError when more than one stem matches — boot must not
    silently pick the wrong checkpoint; the operator must clean the model dir to
    exactly one triplet per quantize mode.
    """
    stems = []
    for name in filenames:
        if not name.startswith("encoder-") or not name.endswith(".onnx"):
            continue
        is_int8 = name.endswith(".int8.onnx")
        if quantize != is_int8:
            continue
        stems.append(name[len("encoder-") : -len(".onnx")])
    if not stems:
        return None
    if len(stems) > 1:
        conflict = ", ".join(sorted(stems))
        raise ValueError(
            f"Ambiguous sherpa model dir: {len(stems)} encoder stems match "
            f"quantize={quantize} ({conflict}). Clean the model dir to exactly "
            "one encoder/decoder/joiner triplet per quantize mode."
        )
    return stems[0]


def _ensure_model_present(model_dir: str, *, quantize: bool, repo_id: str, token: str, revision: str) -> str:
    """Discover the model stem in `model_dir`, pulling from HuggingFace if absent.

    Globs `model_dir` for the requested family (see `_discover_model_stem`); if a
    stem and `tokens.txt` are present, returns it (the common case + persistent
    volumes). Otherwise pulls `repo_id` at `revision` (etag-cached, idempotent)
    and re-globs. Raises FileNotFoundError if still missing after the download.
    """

    def _discover() -> str | None:
        try:
            listing = os.listdir(model_dir)
        except FileNotFoundError:
            return None
        stem = _discover_model_stem(listing, quantize)
        if stem is not None and "tokens.txt" in listing:
            return stem
        return None

    stem = _discover()
    if stem is not None:
        return stem

    if snapshot_download is None:
        raise ImportError(
            'huggingface_hub not installed — needed to pull the sherpa model. Run: pip install -e ".[stt-sherpa]"'
        )
    logger.info("Sherpa model missing in %s — pulling %s@%s from HuggingFace ...", model_dir, repo_id, revision)
    snapshot_download(repo_id=repo_id, local_dir=model_dir, token=token or None, revision=revision)
    logger.info("Sherpa model download complete: %s", model_dir)

    stem = _discover()
    if stem is not None:
        return stem
    raise FileNotFoundError(
        f"Sherpa model still missing in {model_dir} after pulling {repo_id}@{revision} "
        f"(quantize={quantize}). No encoder/decoder/joiner triplet + tokens.txt found."
    )


# ── Recognizer singleton ──────────────────────────────────────────────────────

_recognizer = None
_recognizer_lock = threading.Lock()


def _get_recognizer():
    """Load or return the cached OnlineRecognizer (thread-safe, called once)."""
    global _recognizer
    if _recognizer is not None:
        return _recognizer
    with _recognizer_lock:
        if _recognizer is not None:
            return _recognizer
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise ImportError("sherpa-onnx not installed. Run: pip install sherpa-onnx") from exc

        d = settings.sherpa_model_dir
        c = settings.sherpa_chunk_size
        stem = _ensure_model_present(
            d,
            quantize=settings.sherpa_model_quantize,
            repo_id=settings.sherpa_hf_repo,
            token=settings.hf_token,
            revision=settings.sherpa_hf_revision,
        )
        model_paths = _compose_model_paths(d, stem)

        # Resolve hotwords file path (relative to this file's directory)
        hotwords_file = ""
        if settings.sherpa_hotwords_file:
            hw_path = settings.sherpa_hotwords_file
            if not os.path.isabs(hw_path):
                hw_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), hw_path)
            if os.path.exists(hw_path):
                hotwords_file = hw_path
                logger.info("Hotwords file: %s", hw_path)
            else:
                logger.warning("Hotwords file not found: %s (biasing disabled)", hw_path)

        # Hotwords biasing requires beam search, so it forces the method on.
        decoding_method = settings.sherpa_decoding_method
        if hotwords_file and decoding_method != "modified_beam_search":
            logger.info("Hotwords file set — forcing decoding_method=modified_beam_search.")
            decoding_method = "modified_beam_search"

        logger.info(
            "Loading Zipformer recognizer: %s (chunk=%d, decoding=%s) ...",
            d,
            c,
            decoding_method,
        )
        kwargs = dict(
            encoder=model_paths["encoder"],
            decoder=model_paths["decoder"],
            joiner=model_paths["joiner"],
            tokens=model_paths["tokens"],
            num_threads=settings.sherpa_num_threads,
            sample_rate=settings.stt_sample_rate,
            feature_dim=80,
            decoding_method=decoding_method,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=settings.sherpa_rule1_min_trailing_silence,
            rule2_min_trailing_silence=settings.sherpa_rule2_min_trailing_silence,
            rule3_min_utterance_length=settings.sherpa_rule3_min_utterance_length,
        )
        if decoding_method == "modified_beam_search":
            kwargs["max_active_paths"] = int(settings.sherpa_max_active_paths)
        if hotwords_file:
            kwargs["hotwords_file"] = hotwords_file
            kwargs["hotwords_score"] = float(settings.sherpa_hotwords_score)

        try:
            _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**kwargs)
            logger.info("Zipformer recognizer ready (hotwords=%s).", "yes" if hotwords_file else "no")
        except Exception as exc:
            if hotwords_file:
                logger.warning("Hotwords failed (%s) — retrying without hotwords (greedy_search).", exc)
                for key in ("hotwords_file", "hotwords_score", "decoding_method", "max_active_paths"):
                    kwargs.pop(key, None)
                _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(**kwargs)
                logger.info("Zipformer recognizer ready (hotwords=no, fallback).")
            else:
                raise
        return _recognizer


# ── Per-session STT ───────────────────────────────────────────────────────────


class SherpaSTT:
    """
    One streaming STT session backed by sherpa-onnx Zipformer.

    Drop-in replacement for DeepgramSTT:
        on_partial(text)  — called when interim text changes (UI update)
        on_final(text)    — called when endpoint detected (triggers LLM)

    Usage (same as DeepgramSTT):
        stt = SherpaSTT(on_partial=..., on_final=...)
        await stt.start()
        await stt.send(pcm_bytes)   # called per audio chunk
        await stt.stop()
    """

    def __init__(
        self,
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
    ):
        self.on_partial = on_partial
        self.on_final = on_final
        self._stream = None
        self._audio_q: stdlib_queue.Queue = stdlib_queue.Queue()
        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._last_partial: str = ""

    async def start(self):
        recognizer = _get_recognizer()
        self._stream = recognizer.create_stream()
        self._loop = asyncio.get_running_loop()
        self._running = True
        self._thread = threading.Thread(target=self._decode_loop, daemon=True, name="sherpa-decode")
        self._thread.start()
        logger.info("SherpaSTT session started.")

    async def send(self, pcm_bytes: bytes):
        """Queue a raw PCM int16 chunk for decoding (non-blocking)."""
        if self._running:
            self._audio_q.put_nowait(pcm_bytes)

    async def stop(self):
        self._running = False
        self._audio_q.put_nowait(None)  # unblock the decode thread
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("SherpaSTT session stopped.")

    # ── Background decode thread ──────────────────────────────────────────────

    def _decode_loop(self):
        """
        Runs in a daemon thread.
        Reads PCM chunks → feeds to sherpa-onnx → emits callbacks via event loop.
        """
        recognizer = _get_recognizer()

        while self._running:
            try:
                item = self._audio_q.get(timeout=0.5)
            except stdlib_queue.Empty:
                continue

            if item is None:
                break

            # PCM int16 → float32 in [-1, 1]
            samples = np.frombuffer(item, dtype=np.int16).astype(np.float32) / 32768.0
            self._stream.accept_waveform(settings.stt_sample_rate, samples)

            # Drain the recognizer's internal buffer
            while recognizer.is_ready(self._stream):
                recognizer.decode_stream(self._stream)

            # sherpa-onnx >= 1.10: get_result() returns str directly
            text = _postprocess_text(recognizer.get_result(self._stream), settings.sherpa_preserve_case)

            # Emit partial only when text actually changes
            if text and text != self._last_partial:
                self._last_partial = text
                if self.on_partial and self._loop:
                    asyncio.run_coroutine_threadsafe(_safe_call(self.on_partial, text), self._loop)

            # Endpoint detected → emit final, reset stream for next utterance
            if recognizer.is_endpoint(self._stream):
                if text and self.on_final and self._loop:
                    asyncio.run_coroutine_threadsafe(_safe_call(self.on_final, text), self._loop)
                recognizer.reset(self._stream)
                self._last_partial = ""


async def _safe_call(fn: Callable, text: str) -> None:
    try:
        result = fn(text)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.error("STT callback error: %s", exc)
