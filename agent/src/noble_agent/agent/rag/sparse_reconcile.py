"""One-shot: clone the root Qdrant collection into the app-owned clone with a
BM25 sparse vector per point, and build the local BM25 fallback from the same
snapshot. Runs once at server-agent startup (single process, no lock) and is
also a standalone console command (`noble-rag-sync`).
"""

from __future__ import annotations

import logging

from noble_agent.agent.rag import bm25_fallback, qdrant_store, sparse_encoder
from noble_agent.agent.rag.flat_store import Chunk
from noble_agent.config import settings

logger = logging.getLogger("rag.sparse_reconcile")


async def reconcile() -> int:
    """Rebuild the clone (dense+sparse) and the local fallback from root. Returns point count."""
    if not settings.qdrant_collection_root:
        logger.warning("[reconcile] QDRANT_COLLECTION_ROOT unset — skipping")
        return 0

    from qdrant_client import models

    dim, distance = await qdrant_store.get_root_dense_params()
    await qdrant_store.recreate_clone(dim, distance)

    dense_name = settings.qdrant_dense_vector_name
    sparse_name = settings.qdrant_sparse_vector_name

    batch_points: list = []
    chunks: list[Chunk] = []
    total = 0

    async for point_id, dense_vec, payload in qdrant_store.iter_root_points():
        text = payload.get("text", "") or ""
        project_id = payload.get("project_id", "") or ""
        idx, val = sparse_encoder.encode_document(text)
        batch_points.append(
            models.PointStruct(
                id=point_id,
                vector={
                    dense_name: dense_vec,
                    sparse_name: models.SparseVector(indices=idx, values=val),
                },
                payload=payload,
            )
        )
        chunks.append(Chunk(id=str(point_id), project=project_id, text=text))
        total += 1
        if len(batch_points) >= 256:
            await qdrant_store.upsert_clone_points(batch_points)
            batch_points = []

    if batch_points:
        await qdrant_store.upsert_clone_points(batch_points)

    bm25_fallback.build(chunks, settings.qdrant_fallback_dir)
    logger.info("[reconcile] synced %d points → clone + local fallback", total)
    return total


async def _sync_and_build_graph(*, renew_graph: bool) -> None:
    """Reconcile the clone, then (re)build the HippoRAG graph from it.

    The KG build is best-effort and only runs here (the console command), NOT in
    the in-process startup reconcile — so a boot never pays the OpenIE LLM cost.
    """
    await reconcile()
    try:
        from noble_agent.agent.rag.hipporag import builder

        n = await builder.run_sync(renew=renew_graph)
        logger.info("[reconcile] hipporag graph %s (%d passages)", "renewed" if renew_graph else "updated", n)
    except Exception as exc:  # noqa: BLE001
        logger.error("[reconcile] hipporag graph build skipped: %s", exc)


def main() -> None:
    import argparse
    import asyncio

    from noble_agent.server.logging_config import setup_logging

    parser = argparse.ArgumentParser(description="Sync the Qdrant clone from root and update the HippoRAG graph.")
    parser.add_argument(
        "--renew-graph",
        action="store_true",
        help="Rebuild the HippoRAG graph from scratch (re-runs OpenIE on every chunk). "
        "Default: incremental — only NEW chunks (by content_hash) are extracted.",
    )
    args = parser.parse_args()

    setup_logging()
    asyncio.run(_sync_and_build_graph(renew_graph=args.renew_graph))


if __name__ == "__main__":
    main()
