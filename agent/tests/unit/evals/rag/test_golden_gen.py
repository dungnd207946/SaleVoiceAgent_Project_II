import json

import evals.rag.golden_gen as gg
from evals.rag.golden_gen import gen_questions, write_draft


async def test_gen_questions_validates_evidence_verbatim(monkeypatch):
    async def fake_llm(model, system, user):
        return json.dumps({"pairs": [
            {"query": "giá bao nhiêu?", "evidence": "Giá từ 3 tỷ", "answer": "Giá từ 3 tỷ"},
            {"query": "bịa", "evidence": "câu này không có trong chunk", "answer": "bịa luôn"},
            {"query": "thiếu answer", "evidence": "Bàn giao 2027", "answer": ""},
        ]})

    monkeypatch.setattr(gg, "_call_llm", fake_llm)
    chunk = {"id": "abc123", "text": "Dự án X. Giá từ 3 tỷ. Bàn giao 2027.", "project_code": "NCLB"}
    pairs = await gen_questions(chunk, model="m", n=3)
    assert len(pairs) == 1
    assert pairs[0]["evidence"] == "Giá từ 3 tỷ"
    assert pairs[0]["answer"] == "Giá từ 3 tỷ"


def test_write_draft_schema(tmp_path):
    p = tmp_path / "draft.jsonl"
    write_draft([{"id": "gg-abc-0", "tenant": "noble", "query": "q", "evidence": "e",
                  "golden_chunk_id": "abc", "project_code": "NCLB"}], p)
    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "draft" and row["golden_chunk_id"] == "abc"
