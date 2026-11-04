"""Noble knowledge-base entry point for the `noble_search` tool.

Backend selection via `settings.noble_rag_backend`:

  - "flat_store" (default) → flat_store_adapter.query_flat_store_for_noble_kb
      Hybrid BM25 + dense RRF fusion, best quality, <50ms warm.
  - "grep_faq" → substring grep over data/faq/<CODE>.md.
      Mirrors post-training mock_noble_search exactly. Use to A/B test against
      flat_store, or as a stdlib-only fallback when FlatStore artifacts are
      unavailable.
  - "empty" → return "" (degraded mode for when FlatStore artifacts missing)
  - "hipporag_kb" → hipporag/kb_adapter over the live per-tenant collection.
      Seeds from kb_service, PPR over the Portal-written graph, RRF fuse; degrades
      to the plain kb_service result when the graph artefact is absent.

Note: the legacy "memory_router" backend (FastTalker / SlowThinker
context-prefetch) was removed when the semantic RESPONSE cache landed in
`noble_agent.semcache` — response cache supersedes context cache.

Project disambiguation uses `agent.project_catalog.normalize()` instead of
substring heuristics.
"""

from __future__ import annotations

import logging

from noble_agent.config import settings

logger = logging.getLogger("rag.noble_kb")


def _resolve_project(query: str, project_filter: str) -> str:
    """Normalise project_filter to a canonical code. If ambiguous/missing and
    the query text contains a unique alias, fall back to that. Returns '' when
    nothing can be resolved — adapter handles empty filter by searching all
    projects."""
    from noble_agent.agent import catalog as _catalog

    code = _catalog.normalize(project_filter)
    if code:
        return code
    if query:
        inferred = _catalog.normalize(query)
        if inferred:
            return inferred
    return ""


async def query_noble_kb(
    query: str,
    project_filter: str,
    dinh_kem: list[dict] | None = None,
    du_an: list[str] | None = None,
    numbers: dict[str, int] | None = None,
) -> str:
    """Entry point called by the `noble_search` LLM tool.

    Returns the retrieved context as a formatted string (one block per hit),
    or empty string if the backend returns nothing / is disabled.

    ``dinh_kem`` là BỒN CHỨA tệp/ảnh nguồn để client gửi kèm câu trả lời. Chỉ backend
    ``kb_service`` đổ vào nó — năm backend còn lại không có khái niệm tệp nguồn, nên chúng
    để nguyên bồn rỗng thay vì phải đổi kiểu trả về của cả sáu. ``numbers`` cùng lý do:
    sổ số ảnh theo phiên, chỉ `kb_service` biết đọc/ghi nó.
    """
    query = (query or "").strip()
    if not query:
        return ""

    project = _resolve_project(query, project_filter)

    backend = (settings.noble_rag_backend or "flat_store").lower()

    if backend == "empty":
        logger.info("[noble_kb] backend=empty — returning no context")
        return ""

    if backend == "grep_faq":
        return _query_via_grep_faq(query, project)

    if backend == "qdrant":
        return await _query_via_qdrant(query, project)

    if backend == "kb_service":
        return await _query_via_kb_service(query, project, dinh_kem, du_an, numbers)

    if backend == "hipporag":
        return await _query_via_hipporag(query, project)

    if backend == "hipporag_kb":
        return await _query_via_hipporag_kb(query, project, dinh_kem, du_an, numbers)

    # Default: flat_store direct hybrid search
    return await _query_via_flat_store(query, project)


async def _query_via_flat_store(query: str, project_filter: str) -> str:
    """Primary path: FlatStore hybrid (BM25 + dense RRF). <50ms warm."""
    try:
        from noble_agent.agent.rag.flat_store_adapter import query_flat_store_for_noble_kb

        result = await query_flat_store_for_noble_kb(
            query,
            project_filter,
            top_k=settings.rag_top_k if settings.rag_top_k > 0 else 5,
        )
        if result:
            logger.info(
                "[noble_kb] flat_store returned %d chars (project=%s)",
                len(result),
                project_filter or "ALL",
            )
        return result or ""
    except Exception as exc:
        logger.warning("[noble_kb] flat_store error: %s — returning empty", exc)
        return ""


async def _query_via_qdrant(query: str, project_filter: str) -> str:
    """Qdrant dense + local BM25 RRF. Falls back to BM25-only on Qdrant error."""
    try:
        from noble_agent.agent.rag.qdrant_adapter import query_qdrant_for_noble_kb

        result = await query_qdrant_for_noble_kb(
            query,
            project_filter,
            top_k=settings.rag_top_k if settings.rag_top_k > 0 else 5,
        )
        if result:
            logger.info("[noble_kb] qdrant returned %d chars (project=%s)", len(result), project_filter or "ALL")
        return result or ""
    except Exception as exc:
        logger.warning("[noble_kb] qdrant error: %s — returning empty", exc)
        return ""


async def _query_via_kb_service(
    query: str,
    project_filter: str,
    dinh_kem: list[dict] | None = None,
    du_an: list[str] | None = None,
    numbers: dict[str, int] | None = None,
) -> str:
    """Qdrant hybrid (dense + BM25 sparse, server-side RRF) over the tenant's
    `<tenant>_documents` collection, embedded via the shared embed service.
    Runs in-process — the query_rag:8016 hop it used to make is retired. Wraps all
    errors → "" so a Qdrant/embed failure never breaks the turn."""
    try:
        from noble_agent.agent.rag.kb_service_adapter import query_kb_service_for_noble_kb

        result = await query_kb_service_for_noble_kb(
            query,
            project_filter,
            top_k=settings.kb_search_top_k if settings.kb_search_top_k > 0 else 5,
            dinh_kem=dinh_kem,
            du_an=du_an,
            numbers=numbers,
        )
        if result:
            logger.info("[noble_kb] kb_service returned %d chars (project=%s)", len(result), project_filter or "ALL")
        return result or ""
    except Exception as exc:
        logger.warning("[noble_kb] kb_service error: %s — returning empty", exc)
        return ""


async def _query_via_hipporag(query: str, project_filter: str) -> str:
    """HippoRAG 2: hybrid seed → Personalized PageRank on the KG → RRF fuse.
    Degrades to the qdrant hybrid result when the graph artifact is missing."""
    try:
        from noble_agent.agent.rag.hipporag.adapter import query_hipporag_for_noble_kb

        result = await query_hipporag_for_noble_kb(
            query,
            project_filter,
            top_k=settings.hipporag_top_k if settings.hipporag_top_k > 0 else 5,
        )
        if result:
            logger.info("[noble_kb] hipporag returned %d chars (project=%s)", len(result), project_filter or "ALL")
        return result or ""
    except Exception as exc:
        logger.warning("[noble_kb] hipporag error: %s — returning empty", exc)
        return ""


async def _query_via_hipporag_kb(
    query: str,
    project_filter: str,
    dinh_kem: list[dict] | None,
    du_an: list[str] | None,
    numbers: dict[str, int] | None,
) -> str:
    """Seed từ `kb_service`, PPR trên graph Portal ghi, RRF fuse. Degrades về
    đúng kết quả `kb_service`."""
    try:
        from noble_agent.agent.rag.hipporag import kb_adapter

        result = await kb_adapter.query_hipporag_kb_for_noble_kb(
            query,
            project_filter,
            top_k=settings.kb_search_top_k if settings.kb_search_top_k > 0 else 5,
            dinh_kem=dinh_kem,
            du_an=du_an,
            numbers=numbers,
        )
        if result:
            logger.info("[noble_kb] hipporag_kb returned %d chars (project=%s)", len(result), project_filter or "ALL")
        return result or ""
    except Exception as exc:
        logger.warning("[noble_kb] hipporag_kb error: %s — returning empty", exc)
        return ""


def _query_via_grep_faq(query: str, project_filter: str) -> str:
    """Substring grep on data/faq/<CODE>.md — same algorithm as
    post-training/src/post_training/data/mock_tool_env/tools/search.py.

    Reproduces the exact tool output shape the SFT data was generated against,
    so we can A/B compare LoRA behaviour vs the flat_store hybrid path without
    confounding gains from a richer retrieval algorithm.
    """
    from pathlib import Path

    from noble_agent.agent.catalog import all_projects

    # parents: rag→agent→noble_agent→src→<repo root> → 4 levels up.
    faq_dir = Path(__file__).resolve().parents[4] / "data" / "faq"
    codes = [project_filter] if project_filter else [p.code for p in all_projects()]
    all_chunks: list[str] = []
    for code in codes:
        md = faq_dir / f"{code}.md"
        if not md.is_file():
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        all_chunks.extend(_grep_chunks(text, query, max_chunks=2))
        if len(all_chunks) >= 5:
            break

    if not all_chunks:
        logger.info("[noble_kb] grep_faq: no match for query=%r project=%s", query[:60], project_filter or "ALL")
        return ""
    logger.info("[noble_kb] grep_faq: %d chunks (project=%s)", len(all_chunks[:5]), project_filter or "ALL")
    return "\n---\n".join(all_chunks[:5])


def _grep_chunks(text: str, query: str, window: int = 400, max_chunks: int = 3) -> list[str]:
    """Find lines containing any query token; return surrounding windows.
    Verbatim port of post_training mock_tool_env tools.search._grep_chunks so
    output ordering + dedupe behaviour matches the SFT data byte-for-byte.
    """
    if not text:
        return []
    tokens = [t.lower() for t in query.split() if len(t) > 2]
    if not tokens:
        return [text[:window]]
    chunks: list[str] = []
    low = text.lower()
    seen_pos: set[int] = set()
    for tok in tokens:
        idx = 0
        while idx < len(low) and len(chunks) < max_chunks:
            pos = low.find(tok, idx)
            if pos < 0:
                break
            start = max(0, pos - window // 2)
            end = min(len(text), pos + window // 2)
            if any(abs(start - s) < window for s in seen_pos):
                idx = pos + len(tok)
                continue
            seen_pos.add(start)
            chunks.append(text[start:end])
            idx = end
    return chunks
