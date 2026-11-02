"""Sentence-transformers-backed embedder for the semantic cache.

Singleton, lazy-loaded. e5-small multilingual is the default — 384-dim,
~470MB on disk, ~3-5s cold load, ~10-30ms per encode on CPU. Cosine match
uses dot product on l2-normalized vectors.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("noble_agent.semcache.embedder")

_model: Any = None
_model_lock = asyncio.Lock()
_model_name: str | None = None


def _e5_format(text: str, *, is_query: bool) -> str:
    """e5 family expects ``query:`` / ``passage:`` prefixes. For other models
    these are usually harmless extra tokens."""
    prefix = "query: " if is_query else "passage: "
    return prefix + (text or "").strip()


async def _load_model(name: str):
    """Off-thread load — sentence-transformers import is heavy."""
    loop = asyncio.get_running_loop()

    def _do_load():
        from sentence_transformers import SentenceTransformer  # noqa: I001

        return SentenceTransformer(name)

    return await loop.run_in_executor(None, _do_load)


async def get_embedder(model_name: str):
    """Return a singleton SentenceTransformer for ``model_name``.

    If a model with a different name is requested after the first load, we
    log a warning and keep the original — switching models mid-session would
    invalidate the cache vectors anyway.
    """
    global _model, _model_name
    if _model is not None:
        if model_name != _model_name:
            logger.warning(
                "semcache.embedder: model already loaded as %r, ignoring %r",
                _model_name,
                model_name,
            )
        return _model
    async with _model_lock:
        if _model is not None:
            return _model
        logger.info("semcache.embedder: loading %s (first use)", model_name)
        _model = await _load_model(model_name)
        _model_name = model_name
        logger.info("semcache.embedder: ready")
        return _model


async def encode(text: str, *, model_name: str, is_query: bool) -> list[float]:
    """Encode a single string. Returns a python list (JSON-serializable)."""
    model = await get_embedder(model_name)
    loop = asyncio.get_running_loop()
    formatted = _e5_format(text, is_query=is_query)

    def _do_encode():
        vec = model.encode(formatted, normalize_embeddings=True)
        return vec.tolist()

    return await loop.run_in_executor(None, _do_encode)


async def encode_batch(texts: list[str], *, model_name: str, is_query: bool) -> list[list[float]]:
    """Batch-encode for efficiency when caching multiple predicted queries."""
    if not texts:
        return []
    model = await get_embedder(model_name)
    loop = asyncio.get_running_loop()
    formatted = [_e5_format(t, is_query=is_query) for t in texts]

    def _do_encode():
        vecs = model.encode(formatted, normalize_embeddings=True, batch_size=8)
        return [v.tolist() for v in vecs]

    return await loop.run_in_executor(None, _do_encode)


def cosine(a: list[float], b: list[float]) -> float:
    """Dot product — vectors are pre-normalized by ``encode``."""
    n = min(len(a), len(b))
    return sum(a[i] * b[i] for i in range(n))


def reset_for_tests() -> None:
    global _model, _model_name
    _model = None
    _model_name = None
