"""Standalone streaming STT service — sherpa-onnx Zipformer over WebSocket.

Self-contained: depends only on sherpa-onnx + numpy + websockets. NO dependency
on any agent codebase — like a cloud STT vendor (Soniox/ElevenLabs), any service
can use it by streaming PCM and reading transcripts.

Protocol (ws://host:8012/stt) — the `remote` WebSocket contract (see
docs/remote_stt_tts_spect.md). ONE WS per call, kept open the whole session:
  client → server : binary frames = raw PCM16 LE, mono, 16 kHz (STT_SAMPLE_RATE)
  client → server : {"type":"config","hotwords":"..."} = optional, BEFORE first
                    audio frame — per-session hotword biasing (see Hotwords)
  client → server : {"type":"eos"} = end of session (client closes WS next)
  server → client : JSON {"type":"partial"|"final","text": "..."} (never empty text)
  endpoint detection is server-side (sherpa rules) → "final" per endpoint, many
  "final"s per session.

Hotwords (contextual biasing, à la Soniox context): transducer-only sherpa
feature, needs decoding_method=modified_beam_search (greedy ignores them —
setting STT_HOTWORDS_FILE auto-upgrades decoding with a warning). Phrases are
'/'-separated, optional per-phrase boost suffix " :2.0". With bpe.vocab present
(STT_BPE_VOCAB, matched against tokens.txt at boot) phrases are plain words —
uppercased server-side since the BPE was trained on uppercase text.

Merge semantics: STT_HOTWORDS_FILE is the BASE list, applied to every session.
A session's config-frame hotwords are merged on top — a phrase already in the
base (same words, case/spacing-insensitive) takes the CLIENT's score for that
session only — but only when the client gives one: a bare client phrase keeps the
base's explicit score. The base itself is never mutated: a new session (including one
running concurrently) always starts from the pristine file list. The server
parses the file itself and feeds the merged list per-stream — sherpa's own
hotwords_file would blindly union both entries instead of overriding.

Config (env):
  STT_MODEL_DIR        dir with encoder/decoder/joiner-*.onnx + tokens.txt
  STT_MODEL_QUANTIZE   false → encoder-*.onnx (excl. int8); true → *.int8.onnx
  STT_SAMPLE_RATE      16000
  STT_NUM_THREADS      2
  STT_DECODING_METHOD  greedy_search | modified_beam_search (needed for hotwords)
  STT_HOTWORDS_FILE    global hotwords file, one phrase per line ("" = off)
  STT_HOTWORDS_SCORE   default boost per hotword token (1.5)
  STT_BPE_VOCAB        bpe.vocab for word-level hotwords (/app/bpe.vocab)
  STT_PRESERVE_CASE    false → lowercase+capitalize; true → raw
  STT_RULE1/2/3        endpoint silence/length thresholds
  STT_WS_PORT          8012
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import queue as stdlib_queue
import re
import shutil
import threading
from pathlib import Path

import numpy as np
import sherpa_onnx
import websockets

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("stt-svc")

MODEL_DIR = os.environ.get("STT_MODEL_DIR", "/models/odyssey-stt")
QUANTIZE = os.environ.get("STT_MODEL_QUANTIZE", "false").lower() == "true"
SAMPLE_RATE = int(os.environ.get("STT_SAMPLE_RATE", "16000"))
NUM_THREADS = int(os.environ.get("STT_NUM_THREADS", "2"))
DECODING = os.environ.get("STT_DECODING_METHOD", "greedy_search")
HOTWORDS_FILE = os.environ.get("STT_HOTWORDS_FILE", "").strip()
HOTWORDS_SCORE = float(os.environ.get("STT_HOTWORDS_SCORE", "1.5"))
BPE_VOCAB = os.environ.get("STT_BPE_VOCAB", "/app/bpe.vocab")
if HOTWORDS_FILE and DECODING != "modified_beam_search":
    logging.getLogger("stt-svc").warning(
        "STT_HOTWORDS_FILE set but decoding=%s — hotwords need modified_beam_search, upgrading.", DECODING
    )
    DECODING = "modified_beam_search"
PRESERVE_CASE = os.environ.get("STT_PRESERVE_CASE", "false").lower() == "true"
RULE1 = float(os.environ.get("STT_RULE1", "2.4"))
RULE2 = float(os.environ.get("STT_RULE2", "1.2"))
RULE3 = float(os.environ.get("STT_RULE3", "20.0"))
PORT = int(os.environ.get("STT_WS_PORT", "8012"))
# Nguồn model khi thư mục bind-mount còn trống — giống SPEAKER_HF_REPO của speaker.
HF_REPO = os.environ.get("STT_HF_REPO", "NobleX-AI/santa-stt")
HF_REVISION = os.environ.get("STT_HF_REVISION", "main")
HF_TOKEN = os.environ.get("HF_TOKEN", "").strip()
# Shared bearer token — checked on the WS handshake when set (LAN-visible).
# Empty = open (loopback-only dev).
TOKEN = os.environ.get("ODYSSEY_MODELS_TOKEN", "").strip()

_recognizer: sherpa_onnx.OnlineRecognizer | None = None
# Base hotwords từ STT_HOTWORDS_FILE — nạp 1 lần lúc boot, BẤT BIẾN sau đó.
# Mỗi session merge client hotwords lên một BẢN SAO nên các phiên không lây nhau.
_base_hotwords: dict[str, float | None] = {}


def _discover_stem(model_dir: str, quantize: bool) -> str:
    """Find the encoder filename stem for the requested fp32/int8 family."""
    stems = []
    for name in os.listdir(model_dir):
        if not name.startswith("encoder-") or not name.endswith(".onnx"):
            continue
        if quantize != name.endswith(".int8.onnx"):
            continue
        stems.append(name[len("encoder-") : -len(".onnx")])
    if not stems:
        raise FileNotFoundError(f"No encoder-*.onnx (quantize={quantize}) in {model_dir}")
    if len(stems) > 1:
        raise ValueError(f"Ambiguous model dir {model_dir}: {sorted(stems)}")
    return stems[0]


REVISION_FILE = ".revision"


def _local_revision(model_dir: str) -> str | None:
    try:
        return (Path(model_dir) / REVISION_FILE).read_text().strip() or None
    except OSError:
        return None


def _has_model(model_dir: str, quantize: bool) -> bool:
    try:
        _discover_stem(model_dir, quantize)
    except FileNotFoundError:
        return False
    return os.path.isfile(os.path.join(model_dir, "tokens.txt"))


def _ensure_model_present(model_dir: str, quantize: bool) -> None:
    """Đưa `model_dir` về đúng commit của HF_REPO@HF_REVISION, mỗi lần boot.

    Bản mới tải vào `<model_dir>.new` rồi đổi chỗ; bản cũ giữ ở `<model_dir>.prev`
    (đúng một bản) để lùi tay bằng đổi tên. HF không nối được thì chạy bản đang có.
    HF_REPO rỗng = không đụng HF (fine-tune đặt tay).
    """
    if not HF_REPO:
        _discover_stem(model_dir, quantize)
        logger.info("📂 STT model from %s (STT_HF_REPO empty, no HF check)", model_dir)
        return

    local_sha = _local_revision(model_dir)
    try:
        from huggingface_hub import HfApi

        remote_sha = HfApi(token=HF_TOKEN or None).repo_info(HF_REPO, revision=HF_REVISION, timeout=15).sha
    except Exception as exc:  # noqa: BLE001 — mạng/401/repo sai đều về cùng một nhánh
        if _has_model(model_dir, quantize):
            logger.warning(
                "⚠️ HF unreachable (%s) — using local STT model @%s", exc, (local_sha or "unknown")[:7]
            )
            _discover_stem(model_dir, quantize)
            return
        raise

    if local_sha == remote_sha and _has_model(model_dir, quantize):
        _discover_stem(model_dir, quantize)
        logger.info("📂 STT model up to date @%s", remote_sha[:7])
        return

    from huggingface_hub import snapshot_download

    new_dir, prev_dir = model_dir + ".new", model_dir + ".prev"
    shutil.rmtree(new_dir, ignore_errors=True)
    logger.info(
        "📥 STT model %s → %s, pulling %s@%s ...",
        (local_sha or "none")[:7],
        remote_sha[:7],
        HF_REPO,
        HF_REVISION,
    )
    snapshot_download(repo_id=HF_REPO, local_dir=new_dir, revision=remote_sha, token=HF_TOKEN or None)
    try:
        _discover_stem(new_dir, quantize)
        if not os.path.isfile(os.path.join(new_dir, "tokens.txt")):
            raise FileNotFoundError(f"tokens.txt missing in {new_dir}")
    except (FileNotFoundError, ValueError):
        shutil.rmtree(new_dir, ignore_errors=True)
        raise
    (Path(new_dir) / REVISION_FILE).write_text(remote_sha)

    had_previous = os.path.isdir(model_dir)
    if had_previous:
        shutil.rmtree(prev_dir, ignore_errors=True)
        os.rename(model_dir, prev_dir)
    os.rename(new_dir, model_dir)
    kept = f" (previous kept at {prev_dir})" if had_previous else ""
    logger.info("✅ STT model @%s in %s%s", remote_sha[:7], model_dir, kept)


_SCORE_SUFFIX = re.compile(r"\s+:([0-9]+(?:\.[0-9]+)?)\s*$")


def _parse_hotword(entry: str) -> tuple[str, float | None] | None:
    """'noble city :2.0' → ('NOBLE CITY', 2.0); no suffix → score None (dùng
    HOTWORDS_SCORE mặc định). Key chuẩn hóa HOA + gộp khoảng trắng để phrase
    trùng giữa base và client match được nhau."""
    m = _SCORE_SUFFIX.search(entry)
    score = float(m.group(1)) if m else None
    phrase = " ".join((entry[: m.start()] if m else entry).split()).upper()
    return (phrase, score) if phrase else None


def _load_base_hotwords(path: str) -> dict[str, float | None]:
    if not path:
        return {}
    base: dict[str, float | None] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parsed = _parse_hotword(line)
            if parsed:
                base[parsed[0]] = parsed[1]
    logger.info("🔥 Base hotwords: %d phrases from %s", len(base), path)
    return base


def _merge_hotwords(base: dict[str, float | None], session: str) -> dict[str, float | None]:
    """Base (file) làm nền, phrase phiên trùng key (HOA + gộp space) chỉ đè score
    khi client TỰ ghi score — phrase trần của client (agent đọc từ bảng không có
    cột score) không được hạ score riêng của base về mặc định. Base không đổi."""
    merged = dict(base)
    for entry in session.split("/"):
        parsed = _parse_hotword(entry)
        if parsed and (parsed[1] is not None or parsed[0] not in merged):
            merged[parsed[0]] = parsed[1]
    return merged


def _hotwords_arg(merged: dict[str, float | None]) -> str:
    return "/".join(p if s is None else f"{p} :{s}" for p, s in merged.items())


def _bpe_vocab_for(model_dir: str) -> str:
    """bpe.vocab path if it matches the model's tokens.txt, else '' (word-level
    hotwords off — phrases must then be pre-tokenized tokens.txt entries)."""
    if not BPE_VOCAB or not os.path.isfile(BPE_VOCAB):
        return ""
    with open(f"{model_dir}/tokens.txt", encoding="utf-8") as f:
        n_tokens = sum(1 for _ in f)
    with open(BPE_VOCAB, encoding="utf-8") as f:
        n_vocab = sum(1 for _ in f)
    if n_vocab != n_tokens:
        logger.warning("⚠️ %s (%d) doesn't match tokens.txt (%d) — word-level hotwords off.", BPE_VOCAB, n_vocab, n_tokens)
        return ""
    return BPE_VOCAB


def _build_recognizer() -> sherpa_onnx.OnlineRecognizer:
    global _recognizer
    if _recognizer is not None:
        return _recognizer
    _ensure_model_present(MODEL_DIR, QUANTIZE)
    stem = _discover_stem(MODEL_DIR, QUANTIZE)
    hotword_kwargs = {}
    if DECODING == "modified_beam_search":
        # KHÔNG đưa hotwords_file cho sherpa: sherpa sẽ union file + session
        # (2 entry trùng phrase). Server tự nạp file làm base rồi merge với
        # client theo kiểu ghi-đè trong _make_stream.
        _base_hotwords.update(_load_base_hotwords(HOTWORDS_FILE))
        bpe_vocab = _bpe_vocab_for(MODEL_DIR)
        hotword_kwargs = dict(
            hotwords_score=HOTWORDS_SCORE,
            **(dict(modeling_unit="bpe", bpe_vocab=bpe_vocab) if bpe_vocab else {}),
        )
        logger.info("🔥 Hotwords enabled (base=%d phrases, score=%.1f, bpe_vocab=%r)", len(_base_hotwords), HOTWORDS_SCORE, bpe_vocab)
    logger.info("📦 Loading Zipformer: %s (stem=%s, decoding=%s, rate=%d)", MODEL_DIR, stem, DECODING, SAMPLE_RATE)
    _recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
        encoder=f"{MODEL_DIR}/encoder-{stem}.onnx",
        decoder=f"{MODEL_DIR}/decoder-{stem}.onnx",
        joiner=f"{MODEL_DIR}/joiner-{stem}.onnx",
        tokens=f"{MODEL_DIR}/tokens.txt",
        num_threads=NUM_THREADS,
        sample_rate=SAMPLE_RATE,
        feature_dim=80,
        decoding_method=DECODING,
        enable_endpoint_detection=True,
        rule1_min_trailing_silence=RULE1,
        rule2_min_trailing_silence=RULE2,
        rule3_min_utterance_length=RULE3,
        **hotword_kwargs,
    )
    logger.info("✅ Zipformer recognizer ready.")
    return _recognizer


def _postprocess(raw: str) -> str:
    return raw.strip() if PRESERVE_CASE else raw.strip().lower().capitalize()


async def handler(ws):
    """One STT session per WebSocket connection.

    A daemon thread runs the blocking sherpa decode loop; transcripts are pushed
    back to this event loop via run_coroutine_threadsafe.
    """
    if TOKEN:
        try:
            auth = ws.request.headers.get("Authorization", "")
        except Exception:  # noqa: BLE001 — older websockets w/o .request
            auth = ""
        if auth.removeprefix("Bearer ").strip() != TOKEN:
            logger.warning("🔒 STT auth rejected %s", getattr(ws, "remote_address", None))
            await ws.close(code=1008, reason="unauthorized")
            return
    recognizer = _build_recognizer()
    loop = asyncio.get_running_loop()
    audio_q: stdlib_queue.Queue = stdlib_queue.Queue()
    running = True
    last_partial = ""
    session_hotwords = ""  # set by a "config" frame BEFORE the first audio frame
    stream = None  # created lazily on first audio so session_hotwords can apply

    def _send(payload: dict):
        fut = asyncio.run_coroutine_threadsafe(ws.send(json.dumps(payload, ensure_ascii=False)), loop)
        try:
            fut.result(timeout=2)
        except Exception:
            pass

    def _make_stream():
        if session_hotwords and DECODING != "modified_beam_search":
            logger.warning("🔥 session hotwords ignored: decoding=%s (need modified_beam_search)", DECODING)
        if DECODING != "modified_beam_search":
            return recognizer.create_stream()
        merged = _merge_hotwords(_base_hotwords, session_hotwords)
        if not merged:
            return recognizer.create_stream()
        try:
            return recognizer.create_stream(hotwords=_hotwords_arg(merged))
        except Exception:
            logger.exception("🔥 bad hotwords (session=%r) — falling back to no biasing", session_hotwords)
            return recognizer.create_stream()

    def _decode_loop():
        nonlocal last_partial, stream
        while running:
            try:
                item = audio_q.get(timeout=0.5)
            except stdlib_queue.Empty:
                continue
            if item is None:
                break
            if stream is None:
                stream = _make_stream()
            samples = np.frombuffer(item, dtype=np.int16).astype(np.float32) / 32768.0
            stream.accept_waveform(SAMPLE_RATE, samples)
            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)
            text = _postprocess(recognizer.get_result(stream))
            if text and text != last_partial:
                last_partial = text
                logger.debug("✏️  partial: %r", text)
                _send({"type": "partial", "text": text})
            if recognizer.is_endpoint(stream):
                if text:
                    logger.info("📝 final: %r", text)
                    _send({"type": "final", "text": text})
                recognizer.reset(stream)
                last_partial = ""

    thread = threading.Thread(target=_decode_loop, daemon=True, name="sherpa-decode")
    thread.start()
    logger.info("🔌 STT session open %s", getattr(ws, "remote_address", None))
    try:
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                audio_q.put_nowait(bytes(msg))
                continue
            # Text frame = JSON control. {"type":"eos"} ends the session (client
            # closes WS next); {"type":"config","hotwords":...} sets per-session
            # hotwords and only counts before the first audio frame. Unknown
            # control frames are ignored.
            try:
                ctrl = json.loads(msg)
            except (ValueError, TypeError):
                continue
            if ctrl.get("type") == "eos":
                break
            if ctrl.get("type") == "config":
                hw = ctrl.get("hotwords") or ""
                if stream is not None:
                    logger.warning("🔥 config frame after audio started — hotwords %r ignored", hw)
                elif isinstance(hw, str):
                    session_hotwords = hw.strip()
                    if session_hotwords:
                        logger.info("🔥 session hotwords: %r", session_hotwords)
                    # Dựng stream (kèm context graph) NGAY BÂY GIỜ thay vì đợi audio
                    # frame đầu — client VAD-gate chỉ gửi audio khi có tiếng nói, đừng
                    # để việc dựng cây (dù <1ms) chen vào frame tiếng nói đầu tiên.
                    # An toàn thứ tự: frame WS xử lý tuần tự nên audio sau config luôn
                    # thấy stream đã sẵn sàng qua hàng đợi (queue lock = memory barrier).
                    stream = _make_stream()
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        running = False
        audio_q.put_nowait(None)
        logger.info("👋 STT session closed")


async def main():
    _build_recognizer()  # warm once at boot
    logger.info("🚀 STT WS service listening on :%d (auth=%s)", PORT, "on" if TOKEN else "off")
    async with websockets.serve(handler, "0.0.0.0", PORT, max_size=None, ping_interval=20, ping_timeout=20):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
