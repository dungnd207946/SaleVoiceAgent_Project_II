"""Tải artefact HippoRAG Portal ghi ra, về cache cục bộ theo tenant.

Hợp đồng: `odyssey-portal-backend/docs/contracts/hipporag-graph.md`. Mọi thất bại trả
`None` — thiếu artefact là đường thường, và caller degrade về `kb_service`.
"""

from __future__ import annotations

import logging
import os

from noble_agent.config import settings
from noble_agent.tenant.current import current_tenant

logger = logging.getLogger("rag.hipporag.artefact_store")

TIEN_TO = "tenants"
GRAPH_OBJECT = "hipporag/graph.json"
TRIPLE_OBJECT = "hipporag/triple_emb.npz"


def khoa(tenant_id: str, obj: str) -> str:
    return f"{TIEN_TO}/{tenant_id}/{obj}"


def duong_dan_cache(tenant_id: str) -> tuple[str, str]:
    """npz PHẢI là `<stem của graph>.triple_emb.npz` — `triple_index.triple_emb_path()`
    suy nó từ graph path."""
    graph = os.path.join(settings.hipporag_cache_dir, tenant_id, "graph.json")
    return graph, os.path.splitext(graph)[0] + ".triple_emb.npz"


def _client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.hipporag_artefact_endpoint,
        aws_access_key_id=settings.hipporag_artefact_access_key or None,
        aws_secret_access_key=settings.hipporag_artefact_secret_key or None,
    )


def tai_ve(tenant_id: str = "") -> str | None:
    """Tải graph (+ sidecar nếu có) về cache; trả đường dẫn graph, hoặc `None`."""
    tenant_id = tenant_id or current_tenant()
    if not (settings.hipporag_artefact_endpoint and settings.hipporag_artefact_bucket and tenant_id):
        return None
    graph_path, npz_path = duong_dan_cache(tenant_id)
    bucket = settings.hipporag_artefact_bucket
    try:
        c = _client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.artefact] no s3 client (%s)", exc)
        return None
    try:
        os.makedirs(os.path.dirname(graph_path), exist_ok=True)
        c.download_file(bucket, khoa(tenant_id, GRAPH_OBJECT), graph_path)
    except Exception as exc:  # noqa: BLE001
        logger.info("[hipporag.artefact] no graph for %s (%s) — degrade to kb_service", tenant_id, exc)
        return None
    try:
        c.download_file(bucket, khoa(tenant_id, TRIPLE_OBJECT), npz_path)
    except Exception as exc:  # noqa: BLE001
        logger.info("[hipporag.artefact] no triple sidecar for %s (%s) — passage-only seeding", tenant_id, exc)
    return graph_path
