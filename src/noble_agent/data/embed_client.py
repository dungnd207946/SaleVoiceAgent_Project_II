"""Embedding for kb_search + send_media — the single seam.

Switch the backend with EMBED_BACKEND (gemini | service | hf); no caller changes.
`service` means exactly that — dense AND sparse go over HTTP and NO model is
loaded in-process. On the other backends, sparse (BM25) runs in-process via
fastembed: verified bit-identical to the service's own sparse leg, so term ids
match what ingest wrote either way. visual_text is service-only regardless
(SigLIP2 has no API equivalent).

⚠ The dense backend must match what ingest indexed with. Same dimension is not
enough — a different model is a different vector space, and Qdrant then returns
noise with no error.

Unrelated to `flat_store._Embedder` / EMBED_REMOTE_*, which serves the legacy
flat_store/qdrant/hipporag backends over an older wire contract.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

import httpx

from noble_agent.config import get_settings

logger = logging.getLogger("noble_agent.data.embed_client")

SIDES = frozenset({"index", "query"})
_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = {"gemini": "gemini-embedding-001", "hf": "intfloat/multilingual-e5-large"}

_hf_cache: dict[str, object] = {}
_sparse_cache: dict[str, object] = {}


def _check_side(side: str) -> str:
    if side not in SIDES:
        raise ValueError(f"side must be one of {sorted(SIDES)}, got {side!r}")
    return side


def _model(s) -> str:
    return s.embed_model or _DEFAULT_MODEL.get((s.embed_backend or "").lower(), "")


def _meter_embed(provider: str, model: str, chars: int, t0: float) -> None:
    """Ghi một lời gọi embed vào meter hiện hành (contract §2.1 ``embed``).

    No-op khi không có meter — cờ ``BILLING_METERING_ENABLED`` tắt, hoặc lời gọi
    đến từ script ingest/offline ngoài phiên. Không bao giờ raise: đo lường không
    được phép làm hỏng một truy vấn tri thức.

    ``chars`` = tổng KÝ TỰ đem embed (cơ sở tính tiền, cột ``text_units``);
    ``chars=0`` nghĩa là lời gọi đã THẤT BẠI — ``wall_ms`` vẫn được ghi (giá vốn
    thật đã tiêu) nhưng khách không trả tiền cho lỗi của ta.

    ``(provider, model)`` phải phân biệt được từng nhánh, vì chúng là các thang
    giá khác nhau và khoá gộp của meter là ``(component, purpose, provider,
    model)``. Hai nhánh cùng cặp này sẽ bị cộng vào MỘT dòng.
    """
    try:
        from noble_agent.billing.context import current_meter

        meter = current_meter()
        if meter is None:
            return
        meter.add_embed(
            provider=provider,
            model=model,
            chars=chars,
            wall_ms=(time.perf_counter() - t0) * 1000.0,
        )
    except Exception:  # noqa: BLE001 — đo lường không được làm hỏng truy vấn
        logger.debug("billing: embed metering failed", exc_info=True)


# ── dense: pluggable ─────────────────────────────────────────────────────────


async def embed_dense(texts: list[str], *, side: str = "query") -> list[list[float]]:
    """Dense text vectors from the configured backend."""
    _check_side(side)
    if not texts:
        return []
    s = get_settings()
    backend = (s.embed_backend or "gemini").lower()
    if backend == "gemini":
        return await _gemini_dense(texts, side, s)
    if backend == "hf":
        return await _hf_dense(texts, side, s)
    if backend == "service":
        body = await _service_post({"side": side, "kind": "dense", "texts": texts})
        return body.get("embeddings", []) or []
    raise ValueError(f"unknown EMBED_BACKEND {backend!r} (gemini | service | hf)")


async def _gemini_dense(texts: list[str], side: str, s) -> list[list[float]]:
    if not s.gemini_api_key:
        raise ValueError("EMBED_BACKEND=gemini needs GEMINI_API_KEY")
    model = _model(s)
    payload = {
        "requests": [
            {
                "model": f"models/{model}",
                "content": {"parts": [{"text": t}]},
                "outputDimensionality": s.embed_dim,
                "taskType": "RETRIEVAL_QUERY" if side == "query" else "RETRIEVAL_DOCUMENT",
            }
            for t in texts
        ]
    }
    url = f"{_GEMINI_BASE}/{model}:batchEmbedContents?key={s.gemini_api_key}"
    t0, billed = time.perf_counter(), 0
    try:
        async with httpx.AsyncClient(timeout=s.embed_timeout) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        out = [e.get("values", []) for e in data.get("embeddings", [])]
        billed = sum(len(t) for t in texts)
        return out
    finally:
        _meter_embed("gemini", model, billed, t0)


async def _hf_dense(texts: list[str], side: str, s) -> list[list[float]]:
    """Local sentence-transformers, loaded once per process and run off the loop."""
    name = _model(s)
    model = _load_hf(name)
    prefix = "query: " if side == "query" else "passage: "
    loop = asyncio.get_running_loop()
    t0, billed = time.perf_counter(), 0
    try:
        vecs = await loop.run_in_executor(
            None, lambda: model.encode([prefix + t for t in texts], normalize_embeddings=True)
        )
        out = [[float(x) for x in v] for v in vecs]
        billed = sum(len(t) for t in texts)
        return out
    finally:
        # Chạy trên CPU của ta, không phải API trả phí — `wall_ms` là giá vốn
        # thật, còn `text_units` để Portal tự quyết có thu của khách hay không.
        _meter_embed("hf", name, billed, t0)


def _load_hf(name: str):
    m = _hf_cache.get(name)
    if m is None:
        from sentence_transformers import SentenceTransformer

        m = _hf_cache[name] = SentenceTransformer(name)
        logger.info("[embed] loaded HF model %s", name)
    return m


# ── sparse: in-process ───────────────────────────────────────────────────────


async def embed_sparse(texts: list[str], *, side: str = "query") -> list[dict]:
    """BM25 sparse, from the service when EMBED_BACKEND=service, else in-process.

    Honouring the flag here is what makes `EMBED_BACKEND=service` mean "load NO
    model at all" — otherwise the sparse leg silently pulls fastembed even though
    every other leg is remote. The two are interchangeable: the service runs the
    same `Qdrant/bm25` and returns bit-identical indices AND values (verified
    live), so term ids still match what ingest wrote either way.

    `side` is validated but unweighted: BM25 encodes both sides identically,
    which is what ingest did.

    EMBED_SPARSE_MODEL must equal the model ingest used, else the ids are a
    different vocabulary and the sparse branch silently contributes nothing. It
    only applies to the in-process path — the service owns its own model name.
    """
    _check_side(side)
    if not texts:
        return []
    s = get_settings()
    if (s.embed_backend or "gemini").lower() == "service":
        # No in-process fallback on purpose: falling back would load the very model
        # the flag says not to. A service error surfaces like the dense leg's does.
        body = await _service_post({"side": side, "kind": "sparse", "texts": texts})
        return body.get("sparse", []) or []
    model = _load_sparse(s.embed_sparse_model)
    loop = asyncio.get_running_loop()
    t0, billed = time.perf_counter(), 0
    try:
        vecs = await loop.run_in_executor(None, lambda: list(model.embed(texts)))
        out = [
            {"indices": [int(i) for i in v.indices], "values": [float(x) for x in v.values]}
            for v in vecs
        ]
        billed = sum(len(t) for t in texts)
        return out
    finally:
        _meter_embed("fastembed", s.embed_sparse_model or "", billed, t0)


def _load_sparse(name: str):
    m = _sparse_cache.get(name)
    if m is None:
        from fastembed import SparseTextEmbedding

        m = _sparse_cache[name] = SparseTextEmbedding(model_name=name)
        logger.info("[embed] loaded sparse model %s", name)
    return m


# ── service-only kinds ───────────────────────────────────────────────────────


async def embed_visual_text(texts: list[str]) -> list[list[float]]:
    """SigLIP2 text tower — service only, query side only."""
    if not texts:
        return []
    body = await _service_post({"side": "query", "kind": "visual_text", "texts": texts})
    return body.get("embeddings", []) or []


async def _service_post(payload: dict) -> dict:
    """Raises httpx.HTTPError — the tool layer owns the degrade."""
    s = get_settings()
    if not s.embed_service_url:
        raise ValueError(f"EMBED_SERVICE_URL is required for kind={payload.get('kind')!r}")
    token = os.environ.get("SANTA_MODELS_TOKEN", "").strip()
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    # `kind` đi vào cột `model` để ba loại (dense / sparse / visual_text) thành ba
    # dòng riêng — cùng provider="service" mà gộp một dòng thì Portal không tách
    # được thang giá của SigLIP2 khỏi thang giá của BM25.
    kind = str(payload.get("kind") or "")
    t0, billed = time.perf_counter(), 0
    try:
        async with httpx.AsyncClient(timeout=s.embed_timeout) as client:
            resp = await client.post(s.embed_service_url, json=payload, headers=headers)
            resp.raise_for_status()
            out = resp.json()
        billed = sum(len(t) for t in (payload.get("texts") or []))
        return out
    finally:
        _meter_embed("service", kind, billed, t0)
