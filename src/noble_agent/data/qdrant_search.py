"""KB Qdrant client — generic hybrid search over tenant collections.

Shared by the two in-process retrieval paths that replaced the retired query_rag /
query_media services:

  kb_search  → ``<tenant>_documents``, branches dense ("dense") + sparse ("bm25")
  send_media → ``<tenant>_media``,     branches dense ("text") + dense ("visual")

Both run the same pipeline, which is why one function serves both: ONE
``query_points`` call, one Prefetch per branch carrying the SAME filter, fusion
server-side via RRF, then ``limit`` and ``score_threshold`` applied to the FUSED
result. That last part is the easy thing to get wrong — after fusion the score is
RRF (``Σ 1/(2 + rank)``: rank0 = 0.5, rank1 = 0.333…), so a threshold here is NOT
a cosine similarity and is not comparable across queries.

Tenant isolation is enforced by the collection NAME, not by a filter: a caller
cannot read another tenant's points even with a hand-crafted filter. Within a
tenant, ``build_scope_filter`` scopes by ``project_id`` and always unions the
``__ALL__`` sentinel so tenant-wide documents/media stay visible.

Distinct from ``agent/rag/qdrant_store.py``: that module owns the unrelated
clone-from-root collection used by the ``qdrant``/``hipporag`` backends, reads its
config from settings, and targets a different deployment. This one is config-free
(base_url / api_key / collection come from the caller) so it stays testable and
can serve both tools.

qdrant-client is imported lazily (optional extra ``rag-qdrant``) so importing this
module never requires the dependency.
"""

from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass

logger = logging.getLogger("noble_agent.data.qdrant_search")

SYSTEM_ANCHOR = "__ALL__"

# Khoá và giá trị của mệnh đề lọc trạng thái. Hằng số cấp module để test canh import ĐÚNG
# thứ production dùng, không tự khai lại một bản sao — cùng lý lẽ `_CAU_NHAT_JOB` ở repo
# Portal: một test tự khai lại chuỗi chỉ chứng minh "Qdrant lọc được", không chứng minh
# "production có lọc".
CHI_HIEN_KHI = "status"
TRANG_THAI_HIEN = "published"

# Each branch fetches a wider pool than the final limit so RRF has candidates to
# fuse; matches the retired services' max(top_k * 4, 20).
MIN_PREFETCH = 20


@dataclass(frozen=True)
class DensePrefetch:
    """One dense branch: ``using`` is the named vector on the collection."""

    using: str
    vector: list[float]


@dataclass(frozen=True)
class SparsePrefetch:
    """One sparse branch (BM25). Indices/values come from the embed service so the
    query terms hash to the same ids the ingest side indexed."""

    using: str
    indices: list[int]
    values: list[float]


# ── client cache ─────────────────────────────────────────────────────────────
# Deliberately unlike the httpx clients in this package (one per call):
# AsyncQdrantClient holds a persistent connection, and rebuilding it every turn
# would add latency to a real-time voice path. Still config-free — the module only
# remembers what it was handed.
_clients: dict[tuple[str, str], object] = {}


def _import_async_client():
    from qdrant_client import AsyncQdrantClient

    return AsyncQdrantClient


def _get_client(base_url: str, api_key: str):
    key = (base_url, api_key)
    client = _clients.get(key)
    if client is None:
        client = _import_async_client()(url=base_url, api_key=api_key or None)
        _clients[key] = client
        logger.info("[qdrant_search] client → %s", base_url)
    return client


async def close_all() -> None:
    """Close and drop every cached client (shutdown / test cleanup)."""
    for client in list(_clients.values()):
        with contextlib.suppress(Exception):
            await client.close()
    _clients.clear()


# ── collection + filter helpers ──────────────────────────────────────────────


def collection_name(tenant_id: str, suffix: str) -> str:
    """``f"{tenant_id}_{suffix}"`` — the KB collection naming contract.

    Raises ``ValueError`` on a blank tenant: isolation hangs off this name, so an
    empty tenant must fail loudly rather than resolve to a real-looking
    collection (``_documents``) that might exist.
    """
    tid = (tenant_id or "").strip()
    if not tid:
        raise ValueError("tenant_id is required to resolve a collection name")
    return f"{tid}_{suffix}"


def build_scope_filter(
    project_codes: list[str] | None,
    *,
    category: str | None = None,
    content_type: str | None = None,
    sentinel: str = SYSTEM_ANCHOR,
):
    """Qdrant filter cho ``project_id`` (+ optional ``category``/``content_type``), hoặc None.

    No project codes → no project condition, i.e. search the whole tenant. With
    codes → ``project_id IN sorted({*codes, sentinel})``: the sentinel union is
    what keeps tenant-level content (a shared brochure, a tenant-wide policy doc)
    visible when the customer asked about one project. ``category`` và
    ``content_type`` là exact match ANDed in — chỉ send_media truyền, kb_search
    không bao giờ truyền. Mỗi param rỗng/blank → không thêm điều kiện, tức là
    không lọc theo chiều đó.
    """
    from qdrant_client import models

    # ĐIỀU KIỆN ĐẦU TIÊN, KHÔNG ĐIỀU KIỆN NÀO TẮT ĐƯỢC NÓ.
    #
    # Portal ghi point cho CẢ hàng nháp từ 2026-08-14 (trước đó hàng nháp không có point,
    # nên "nội dung nháp không tới khách" là một bảo đảm CẤU TRÚC). Đổi lại, mệnh đề này là
    # thứ DUY NHẤT còn ngăn nó — và không test nào ở repo Portal bắt được nếu nó biến mất.
    #
    # Phải là `== 'published'`, KHÔNG phải `!= 'draft'`: khoá có ba giá trị
    # (`published`/`draft`/`archived`) nên `!=` để `archived` lọt ra khách. `==` cũng là thứ
    # giữ tính FAIL-CLOSED — point THIẾU khoá `status` không khớp nên bị ẩn, đúng ý muốn.
    # Hệ quả vận hành: Portal phải nạp lại toàn bộ tenant TRƯỚC khi bản này lên, không thì
    # mọi point cũ (chưa có khoá) biến mất khỏi kết quả.
    #
    # Chi tiết ở docs/contracts/payload-qdrant.md §4.
    must = [models.FieldCondition(key=CHI_HIEN_KHI, match=models.MatchValue(value=TRANG_THAI_HIEN))]
    codes = [c.strip() for c in (project_codes or []) if (c or "").strip()]
    if codes:
        must.append(
            models.FieldCondition(
                key="project_id",
                match=models.MatchAny(any=sorted({*codes, sentinel})),
            )
        )
    cat = (category or "").strip()
    if cat:
        must.append(models.FieldCondition(key="category", match=models.MatchValue(value=cat)))
    ctype = (content_type or "").strip()
    if ctype:
        must.append(models.FieldCondition(key="content_type", match=models.MatchValue(value=ctype)))
    # LUÔN trả filter: `must` không bao giờ rỗng nữa vì mệnh đề trạng thái luôn có mặt.
    # Trước 2026-08-14 hàm này trả `None` khi không lọc gì — trả `None` bây giờ nghĩa là
    # tìm cả nội dung nháp.
    return models.Filter(must=must)


async def collection_exists(base_url: str, api_key: str, collection: str) -> bool:
    """Whether the collection exists — callers check this BEFORE embedding so an
    unprovisioned tenant costs no embed round-trip (fail-closed, no error)."""
    client = _get_client(base_url, api_key)
    return bool(await client.collection_exists(collection))


# ── search ───────────────────────────────────────────────────────────────────


async def search_hybrid(
    *,
    base_url: str,
    api_key: str,
    collection: str,
    prefetches: list[DensePrefetch | SparsePrefetch],
    limit: int,
    score_threshold: float | None = None,
    filter_=None,
    prefetch_limit: int | None = None,
    timeout: float | None = None,
) -> list[dict]:
    """One hybrid query: N prefetch branches → server-side RRF → top ``limit``.

    Returns ``[{**payload, "id": str, "score": float}, ...]`` in fused order.
    Raises on any Qdrant error — the caller owns the degrade decision.
    """
    from qdrant_client import models

    if not prefetches:
        raise ValueError("search_hybrid needs at least one prefetch branch")

    candidates = prefetch_limit if prefetch_limit is not None else max(limit * 4, MIN_PREFETCH)
    branches = []
    for pf in prefetches:
        if isinstance(pf, SparsePrefetch):
            query = models.SparseVector(indices=pf.indices, values=pf.values)
        else:
            query = pf.vector
        # Same filter on every branch: filtering before fusion (rather than
        # post-filtering the fused head) is what keeps recall intact when a
        # project scope is applied.
        branches.append(models.Prefetch(query=query, using=pf.using, limit=candidates, filter=filter_))

    kwargs: dict = {
        "collection_name": collection,
        "prefetch": branches,
        "query": models.FusionQuery(fusion=models.Fusion.RRF),
        "limit": limit,
        "score_threshold": score_threshold,
        "with_payload": True,
    }
    if timeout is not None:
        kwargs["timeout"] = int(timeout)

    client = _get_client(base_url, api_key)
    resp = await client.query_points(**kwargs)

    out: list[dict] = []
    for p in resp.points:
        row = dict(p.payload or {})
        row["id"] = str(p.id)
        row["score"] = float(p.score)
        out.append(row)
    return out
