import os

import pytest

pytestmark = pytest.mark.needs_qdrant

_QUERIES = [
    ("giá bán căn hộ", "NCLB"),
    ("tiện ích dự án", "NTTL"),
    ("chính sách thanh toán", ""),
]


@pytest.mark.skipif(not os.getenv("QDRANT_URL"), reason="QDRANT_URL not set")
async def test_qdrant_topk_overlaps_flat_store():
    from noble_agent.agent.rag.flat_store_adapter import query_flat_store_for_noble_kb
    from noble_agent.agent.rag.qdrant_adapter import query_qdrant_for_noble_kb

    for query, proj in _QUERIES:
        flat = await query_flat_store_for_noble_kb(query, proj, top_k=5)
        qdr = await query_qdrant_for_noble_kb(query, proj, top_k=5)
        # Both return non-empty formatted blocks of the same shape.
        assert flat and qdr
        assert qdr.startswith("[Nguon 1 | Du an:")
        # Dense vectors are identical, BM25 identical → top hit should match.
        flat_top = flat.splitlines()[0]
        qdr_top = qdr.splitlines()[0]
        assert flat_top.split("]")[0] == qdr_top.split("]")[0] or flat[:80] == qdr[:80]
