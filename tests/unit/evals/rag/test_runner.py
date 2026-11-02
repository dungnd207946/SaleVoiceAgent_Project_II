from evals.rag.golden import GoldenCase, GoldenChunk
from evals.rag.runner import run_rag


def _g(i, ev, cid="", chunks=None):
    if chunks is None:
        chunks = (GoldenChunk(chunk_id=cid, evidence=ev),)
    return GoldenCase(id=f"g{i}", tenant="noble", query=f"q{i}", chunks=chunks, status="approved")


async def test_run_rag_ranks_and_aggregates():
    async def search(query, project_code):
        if query == "q1":
            return [{"id": "a", "text": "có Giá từ 3 tỷ ở đây"}]
        return []

    out = await run_rag([_g(1, "giá từ 3 tỷ"), _g(2, "không thấy")], search=search)
    assert out["metrics"]["recall_at_1"] == 0.5
    assert out["metrics"]["context_recall_at_5"] == 0.5
    assert out["metrics"]["empty_rate"] == 0.5
    rows = {r["id"]: r for r in out["rows"]}
    assert rows["g1"]["hit"] is True and rows["g2"]["n_hits"] == 0
    assert rows["g1"]["ranks"] == [0]
    assert rows["g1"]["retrieved"] == ["có Giá từ 3 tỷ ở đây"]
    assert rows["g2"]["retrieved"] == []


async def test_search_error_counts_as_empty_not_crash():
    async def search(query, project_code):
        raise ConnectionError("qdrant down")

    out = await run_rag([_g(1, "x")], search=search)
    assert out["metrics"]["empty_rate"] == 1.0
    assert out["rows"][0]["error"].startswith("ConnectionError")
    assert out["rows"][0]["ranks"] == [None]
    assert out["rows"][0]["retrieved"] == []


async def test_run_rag_empty_golden_list():
    async def search(query, project_code):
        return []

    out = await run_rag([], search=search)
    assert out["rows"] == []
    assert out["metrics"]["empty_rate"] is None


async def test_run_rag_respects_top_k_truncation():
    async def search(query, project_code):
        return [{"id": str(i), "text": f"chunk {i}"} for i in range(10)]

    golden = [_g(1, "chunk 7")]
    out = await run_rag(golden, search=search, top_k=3)
    assert out["rows"][0]["n_hits"] == 3
    assert out["rows"][0]["hit"] is False
    assert out["rows"][0]["retrieved"] == ["chunk 0", "chunk 1", "chunk 2"]


async def test_run_rag_multi_chunk_ranks():
    async def search(query, project_code):
        return [{"id": "", "text": "chunk vàng thứ nhất"}, {"id": "", "text": "chunk vàng thứ hai"}]

    chunks = (GoldenChunk(evidence="chunk vàng thứ nhất"), GoldenChunk(evidence="chunk vàng thứ hai"))
    golden = [_g(1, "", chunks=chunks)]
    out = await run_rag(golden, search=search)
    assert out["rows"][0]["ranks"] == [0, 1]
