"""Backend `hipporag_kb`: HippoRAG trên đường dữ liệu per-tenant đang sống.

Khác `adapter.py` legacy: seed từ `kb_service_adapter.hits_for` (`<tenant>_documents`)
thay vì clone `noble_kb_hybrid`; graph cache THEO TENANT; render bằng chính formatter
của `kb_service`. Thiếu artefact hoặc lỗi bất kỳ ⇒ degrade về đúng kết quả `kb_service`.
"""

from __future__ import annotations

import asyncio
import logging

from noble_agent.agent.rag import kb_service_adapter as ksa
from noble_agent.agent.rag.hipporag import artefact_store, expander
from noble_agent.agent.rag.hipporag.graph import HippoGraph, load_graph
from noble_agent.agent.rag.hipporag.triple_index import TripleIndex, load_triple_index
from noble_agent.config import settings
from noble_agent.data import qdrant_search
from noble_agent.tenant.current import current_tenant

logger = logging.getLogger("rag.hipporag.kb_adapter")

_RRF_K = 60

# Cache THEO TENANT. `expander.load()` legacy là một singleton toàn cục — dùng nó ở đây
# nghĩa là workspace mở sau đọc graph của workspace mở trước.
_graph_cache: dict[str, HippoGraph | None] = {}
_triple_cache: dict[str, TripleIndex | None] = {}


def reset_cache_for_tests() -> None:
    _graph_cache.clear()
    _triple_cache.clear()


def _doc_graph(path: str) -> HippoGraph | None:
    return load_graph(path)


def load_graph_for_tenant(tenant_id: str) -> HippoGraph | None:
    if tenant_id in _graph_cache:
        return _graph_cache[tenant_id]
    path = artefact_store.tai_ve(tenant_id)
    g = _doc_graph(path) if path else None
    _graph_cache[tenant_id] = g
    if g is not None:
        logger.info(
            "[hipporag.kb] graph %s loaded (%d passages, %d phrases)",
            tenant_id,
            g.num_passages(),
            g.num_phrases(),
        )
    return g


def load_triple_for_tenant(tenant_id: str) -> TripleIndex | None:
    if tenant_id in _triple_cache:
        return _triple_cache[tenant_id]
    graph_path, _npz = artefact_store.duong_dan_cache(tenant_id)
    idx = load_triple_index(graph_path)
    _triple_cache[tenant_id] = idx
    return idx


def thu_tu_rrf(hybrid_rows, ppr_rows) -> list[str]:
    """RRF hai danh sách đã xếp hạng, trả THỨ TỰ point id — hàng thật đến từ hit Qdrant
    (chữ mới) khi có, từ node graph (chữ snapshot) khi chỉ graph có."""
    fused: dict[str, float] = {}
    for rank, row in enumerate(hybrid_rows):
        fused[row[0]] = fused.get(row[0], 0.0) + 1.0 / (_RRF_K + rank + 1)
    for rank, row in enumerate(ppr_rows):
        fused[row[0]] = fused.get(row[0], 0.0) + 1.0 / (_RRF_K + rank + 1)
    return [pid for pid, _s in sorted(fused.items(), key=lambda kv: kv[1], reverse=True)]


async def _sparse_seed(tenant_id: str, query: str, top_m: int) -> dict[str, float]:
    """Khớp câu hỏi với triple đã embed; top-M seed PPR ở cả hai phrase node.

    Chỉ đường npz cục bộ: `HIPPORAG_TRIPLE_STORE=qdrant` không dùng được vì JWT Qdrant
    của pod chỉ mở đúng collection `<tenant>_documents`.
    """
    from noble_agent.data import embed_client

    idx = load_triple_for_tenant(tenant_id)
    if idx is None:
        return {}
    vecs = await embed_client.embed_dense([query], side="query")
    if not vecs:
        return {}
    loop = asyncio.get_running_loop()
    triples = await loop.run_in_executor(None, idx.search, vecs[0], top_m)
    seeds: dict[str, float] = {}
    for s_key, o_key, score in triples:
        if score <= 0:
            continue
        for key in (s_key, o_key):
            if key:
                seeds[key] = max(seeds.get(key, 0.0), score)
    return seeds


async def query_hipporag_kb_for_noble_kb(
    query: str,
    project_filter: str,
    top_k: int = 5,
    dinh_kem: list[dict] | None = None,
    du_an: list[str] | None = None,
    numbers: dict[str, int] | None = None,
) -> str:
    tenant_id = current_tenant()
    seed_k = max(settings.hipporag_seed_k, top_k)
    hits = await ksa.hits_for(query, project_filter, seed_k)

    try:
        graph = load_graph_for_tenant(tenant_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.kb] graph load failed (%s) — kb_service fallback", exc)
        graph = None
    if graph is None or not hits:
        return ksa.render(hits[:top_k], dinh_kem, du_an, numbers)

    try:
        seed_rows = [
            (
                str(h.get("id") or ""),
                str(h.get("project_id") or ""),
                str(h.get("text") or ""),
                float(h.get("score") or 0.0),
            )
            for h in hits
        ]
        phrase_seeds = (
            await _sparse_seed(tenant_id, query, settings.hipporag_sparse_seed_top_m)
            if settings.hipporag_sparse_seed_enabled
            else {}
        )
        loop = asyncio.get_running_loop()
        ppr_rows = await loop.run_in_executor(
            None,
            lambda: expander.expand(
                graph,
                seed_rows,
                alpha=settings.hipporag_ppr_alpha,
                iters=settings.hipporag_ppr_iters,
                seed_k=settings.hipporag_seed_k,
                top_k=max(top_k * 2, top_k),
                project_filter=project_filter,
                extra_seeds=phrase_seeds,
                sparse_weight=settings.hipporag_sparse_seed_weight if phrase_seeds else 0.0,
                passage_threshold=settings.hipporag_passage_seed_threshold,
                phrase_threshold=settings.hipporag_phrase_seed_threshold,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[hipporag.kb] expand failed (%s) — kb_service fallback", exc)
        return ksa.render(hits[:top_k], dinh_kem, du_an, numbers)

    if not ppr_rows:
        return ksa.render(hits[:top_k], dinh_kem, du_an, numbers)

    # Sentinel đi cùng dự án đã ghim: `build_scope_filter` cố tình union `__ALL__` vào,
    # nên lọc `== project_filter` trần sẽ vứt đúng tài liệu dùng chung mà nó vừa kéo về.
    cho_qua = {project_filter, qdrant_search.SYSTEM_ANCHOR} if project_filter else set()
    theo_id = {str(h.get("id") or ""): h for h in hits}
    tu_graph = {row[0]: row for row in ppr_rows}
    ra: list[dict] = []
    for pid in thu_tu_rrf(seed_rows, ppr_rows):
        if len(ra) >= top_k:
            break
        h = theo_id.get(pid)
        if h is None:
            row = tu_graph.get(pid)
            if row is None:
                continue
            # Passage chỉ có trong graph: chữ là snapshot lúc build, không mang
            # `file_public_url`/`section_path` — `_format_kb_hits` chỉ đòi `text`.
            h = {"id": pid, "project_id": row[2], "text": row[3], "score": row[1]}
        if cho_qua and str(h.get("project_id") or "") not in cho_qua:
            continue
        ra.append(h)

    logger.info("[hipporag.kb] %d hybrid + %d ppr -> %d (tenant=%s)", len(hits), len(ppr_rows), len(ra), tenant_id)
    return ksa.render(ra, dinh_kem, du_an, numbers)
