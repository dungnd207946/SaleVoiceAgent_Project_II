"""Ingest the FlatStore KB into Qdrant (dense e5-large, cosine).

Reuses the exact FlatStore the runtime flat_store path builds (same chunks,
same .npy-cached embeddings), so the vectors in Qdrant match the local matmul
path → answer-quality parity.

Open the SSH tunnel to the remote Qdrant first (see the plan header), then:
    python scripts/build_qdrant.py             # idempotent upsert
    python scripts/build_qdrant.py --recreate  # drop + recreate collection
    python scripts/build_qdrant.py --project NCLB
"""

from __future__ import annotations

import argparse
import logging
import uuid

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("build_qdrant")

# Stable namespace so re-runs upsert (not duplicate) the same chunk.
_NS = uuid.UUID("00000000-0000-0000-0000-0000000000ab")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recreate", action="store_true", help="drop + recreate the collection")
    ap.add_argument("--project", default="", help="only ingest this canonical code (e.g. NCLB)")
    ap.add_argument("--batch", type=int, default=256)
    args = ap.parse_args()

    from qdrant_client import QdrantClient, models

    from noble_agent.agent.rag.flat_store import FlatStore
    from noble_agent.config import settings

    store = FlatStore()
    store.load()  # chunks + embeddings (uses .npy cache, encodes if missing)
    assert store.embeddings is not None
    dim = int(store.embeddings.shape[1])

    client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    coll = settings.qdrant_collection

    exists = client.collection_exists(coll)
    if args.recreate and exists:
        client.delete_collection(coll)
        exists = False
        log.info("dropped existing collection %s", coll)
    if not exists:
        client.create_collection(
            coll,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        client.create_payload_index(coll, field_name="project", field_schema=models.PayloadSchemaType.KEYWORD)
        log.info("created collection %s (%dd cosine)", coll, dim)

    points: list = []
    total = 0
    for i, ch in enumerate(store.chunks):
        if args.project and ch.project != args.project:
            continue
        points.append(
            models.PointStruct(
                id=str(uuid.uuid5(_NS, ch.id)),
                vector=store.embeddings[i].tolist(),
                payload={
                    "chunk_id": ch.id,
                    "project": ch.project,
                    "text": ch.text,
                    "is_faq": ch.is_faq,
                    "tokens": ch.tokens,
                    "chunk_order": ch.chunk_order,
                },
            )
        )
        if len(points) >= args.batch:
            client.upsert(coll, points=points)
            total += len(points)
            points = []
            log.info("upserted %d", total)
    if points:
        client.upsert(coll, points=points)
        total += len(points)
    log.info("done: %d points in %s", total, coll)


if __name__ == "__main__":
    main()
