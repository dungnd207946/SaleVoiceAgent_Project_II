import json

import pytest
from evals.rag.golden import GoldenCase, GoldenChunk, load_golden, parse_golden, ranks_of


def _raw(**over):
    d = {"id": "g1", "tenant": "t", "query": "q?", "status": "approved",
         "golden_chunks": [{"chunk_id": "c1", "evidence": "khoáng nóng tự nhiên"}],
         "answer": "có khoáng nóng"}
    d.update(over)
    return d


def test_parse_ok_multi_chunk():
    case = parse_golden(_raw(golden_chunks=[
        {"chunk_id": "c1", "evidence": "e một"}, {"evidence": "e hai"}, {"chunk_id": "c3"},
    ]), source="x:1")
    assert len(case.chunks) == 3 and case.chunks[2].evidence == ""


def test_chunk_needs_id_or_evidence():
    with pytest.raises(ValueError, match="chunk"):
        parse_golden(_raw(golden_chunks=[{}]), source="x:1")


def test_old_schema_rejected():
    with pytest.raises(ValueError, match="unknown"):
        parse_golden(_raw(evidence="schema cũ"), source="x:1")


def test_empty_chunks_rejected():
    with pytest.raises(ValueError, match="golden_chunks"):
        parse_golden(_raw(golden_chunks=[]), source="x:1")


def test_loader_rejects_draft(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text(json.dumps(_raw(status="draft")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="approved"):
        load_golden(p)


def _case(*chunks):
    return GoldenCase(id="g", tenant="t", query="q", chunks=tuple(chunks))


def test_ranks_of_greedy_no_double_count():
    # 2 golden chunk cùng evidence — 1 hit chỉ được match 1 chunk
    c = _case(GoldenChunk(evidence="cùng câu"), GoldenChunk(evidence="cùng câu"))
    hits = [{"id": "h1", "text": "… cùng câu …"}]
    assert ranks_of(c, hits) == [0, None]


def test_ranks_of_id_beats_evidence():
    c = _case(GoldenChunk(chunk_id="c9", evidence="không xuất hiện"))
    hits = [{"id": "x", "text": "y"}, {"id": "c9", "text": "z"}]
    assert ranks_of(c, hits) == [1]
