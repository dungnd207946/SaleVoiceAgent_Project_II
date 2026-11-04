"""Build / incrementally update the HippoRAG knowledge graph (BUILD-TIME ONLY).

``build_or_update_graph`` is pure over an injected chunk list + extract function
(so it is unit-tested without Qdrant or an LLM). ``run_sync`` is the thin
orchestration wired into ``noble-rag-sync``: read the Qdrant clone, build an LLM
completion function from the configured provider chain, extract triples for the
NEW chunks only (or all, when ``renew=True``), and persist the graph.

Never imported on the query hot path.
"""

from __future__ import annotations

import logging

import numpy as np

from noble_agent.agent.rag.hipporag import openie, triple_index
from noble_agent.agent.rag.hipporag.graph import HippoGraph, load_graph, save_graph

logger = logging.getLogger("rag.hipporag.builder")


def build_and_save_triple_index(graph: HippoGraph, path: str, encode_batch_fn) -> int:
    """Embed every triple ("subject relation object") and persist the sidecar
    index next to the graph, aligned with each triple's (subject, object) phrase
    keys. Built on every sync (independent of the runtime sparse-seed flag) so the
    flag can be toggled without a rebuild. ``encode_batch_fn`` is an injected
    ``list[str] -> ndarray`` (the FlatStore embedder in production). Returns the
    triple count, or 0 on any failure (sparse-seed then simply stays off)."""
    triples = graph.triples
    if not triples:
        return 0
    try:
        emb = np.asarray(encode_batch_fn([t.get("text", "") for t in triples]), dtype=np.float32)
        triple_index.save_triple_index(path, [t.get("s", "") for t in triples], [t.get("o", "") for t in triples], emb)
        logger.info("[hipporag.builder] triple index saved (%d triples)", len(triples))
        return len(triples)
    except Exception as exc:  # noqa: BLE001
        logger.error("[hipporag.builder] triple index build skipped: %s", exc)
        return 0


async def build_or_update_graph(chunks, extract_fn, *, graph: HippoGraph | None = None, renew: bool = False):
    """Add passages to ``graph`` (fresh one if None / renew).

    ``chunks`` — iterable of mappings with keys ``point_id``, ``content_hash``,
    ``project``, ``text``. ``extract_fn`` — async ``(text) -> list[triple]``.

    Incremental (default): a chunk whose ``content_hash`` is already in the graph
    is skipped (no extraction). ``renew=True`` starts from an empty graph and
    re-extracts everything. Returns the graph.
    """
    if renew or graph is None:
        graph = HippoGraph()

    n_new = 0
    n_skip = 0
    for ch in chunks:
        chash = str(ch.get("content_hash") or "")
        if not renew and chash and graph.has_passage(chash):
            n_skip += 1
            continue
        triples = await extract_fn(ch.get("text") or "")
        graph.add_passage(
            str(ch.get("point_id") or ""),
            ch.get("text") or "",
            str(ch.get("project") or ""),
            chash,
            triples,
        )
        n_new += 1

    logger.info("[hipporag.builder] extracted=%d skipped=%d passages=%d", n_new, n_skip, graph.num_passages())
    return graph


def _openie_primary(settings) -> str | None:
    """Resolve which provider extracts triples. ``HIPPORAG_OPENIE_MODEL`` pins it
    independently of the main agent; empty → fall back to ``NOBLE_AGENT_MODEL``."""
    from noble_agent.config import primary_for

    return primary_for(settings, settings.hipporag_openie_model or settings.agent_model)


def _make_complete_fn():
    """Build an async ``(prompt) -> str`` completion over the configured LLM
    chain (thinking off, temperature 0). Raises if no provider is configured.
    The primary provider is pinned by ``HIPPORAG_OPENIE_MODEL`` (or the main
    agent's ``NOBLE_AGENT_MODEL`` when unset)."""
    from noble_agent.agent.facade import build_llm_providers
    from noble_agent.agent.llm.client import StreamingClient
    from noble_agent.config import get_settings, provider_model_map

    settings = get_settings()
    providers = build_llm_providers()
    if not providers:
        raise RuntimeError("hipporag build: no LLM providers configured")
    client = StreamingClient(providers=providers, enable_thinking=False)
    model_map = provider_model_map(settings)
    primary = _openie_primary(settings)
    max_tokens = settings.hipporag_openie_max_tokens

    async def complete(prompt: str) -> str:
        return await client.complete_once(
            messages=[{"role": "user", "content": prompt}],
            model=model_map,
            temperature=0.0,
            max_tokens=max_tokens,
            primary=primary,
            request_timeout=60.0,
            purpose="rag_build",
        )

    return complete


def _build_triple_index_from_embedder(graph: HippoGraph, path: str) -> None:
    """Embed triples with the shared FlatStore embedder (remote-aware) and persist
    the sidecar. Best-effort — a missing/unavailable embedder just leaves
    sparse-seed disabled at runtime."""
    try:
        from noble_agent.agent.rag.flat_store import _Embedder

        embedder = _Embedder()

        def _encode(texts: list[str]):
            return embedder.encode_batch(texts, show_progress=False)

        build_and_save_triple_index(graph, path, _encode)
    except Exception as exc:  # noqa: BLE001
        logger.error("[hipporag.builder] triple embedder unavailable: %s", exc)


async def _build_triple_qdrant(graph: HippoGraph) -> None:
    """Embed triples and (re)build the Qdrant triple collection — the backup source
    for the local npz. Built on every sync so HIPPORAG_TRIPLE_STORE can be toggled
    without a rebuild. Best-effort: any failure just logs (runtime cascade
    qdrant→local→hybrid covers it)."""
    triples = graph.triples
    if not triples:
        return
    try:
        from qdrant_client import models

        from noble_agent.agent.rag import qdrant_store
        from noble_agent.agent.rag.flat_store import _Embedder

        embedder = _Embedder()
        emb = np.asarray(
            embedder.encode_batch([t.get("text", "") for t in triples], show_progress=False),
            dtype=np.float32,
        )
        dim = int(emb.shape[1])
        await qdrant_store.recreate_triple_collection(dim)
        points = [
            models.PointStruct(
                id=i,
                vector=emb[i].tolist(),
                payload={"s": t.get("s", ""), "o": t.get("o", ""), "text": t.get("text", "")},
            )
            for i, t in enumerate(triples)
        ]
        await qdrant_store.upsert_triples(points)
        logger.info("[hipporag.builder] qdrant triple collection built (%d triples)", len(triples))
    except Exception as exc:  # noqa: BLE001
        logger.error("[hipporag.builder] qdrant triple build skipped: %s", exc)


async def _read_clone_chunks() -> list[dict]:
    """Scroll the Qdrant clone collection into build-shaped chunk dicts."""
    from noble_agent.agent.rag import qdrant_store

    out: list[dict] = []
    async for point_id, payload in qdrant_store.iter_clone_points():
        out.append(
            {
                "point_id": str(point_id),
                "content_hash": str(payload.get("content_hash") or ""),
                "project": str(payload.get("project_id") or ""),
                "text": payload.get("text") or "",
            }
        )
    return out


async def run_sync(*, renew: bool = False) -> int:
    """Read the Qdrant clone, (incrementally) extract triples, persist the graph.

    Returns the passage count. Best-effort: logs and returns 0 on any failure so
    it never wedges ``noble-rag-sync``.
    """
    from noble_agent.config import get_settings

    settings = get_settings()
    path = settings.hipporag_graph_path
    try:
        chunks = await _read_clone_chunks()
        if not chunks:
            logger.warning("[hipporag.builder] clone empty — graph not built")
            return 0
        existing = None if renew else load_graph(path)
        extract_fn = _make_complete_fn()

        async def _extract(text: str):
            return await openie.extract(text, extract_fn)

        graph = await build_or_update_graph(chunks, _extract, graph=existing, renew=renew)
        save_graph(graph, path)
        _build_triple_index_from_embedder(graph, path)
        await _build_triple_qdrant(graph)
        logger.info(
            "[hipporag.builder] graph %s → %s (%d passages, %d phrases)",
            "rebuilt" if renew else "updated",
            path,
            graph.num_passages(),
            graph.num_phrases(),
        )
        return graph.num_passages()
    except Exception as exc:  # noqa: BLE001
        logger.error("[hipporag.builder] run_sync failed: %s", exc)
        return 0
