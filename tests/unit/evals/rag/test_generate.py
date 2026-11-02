"""Generation stage — mock judge_client, không network."""
from evals import judge_client
from evals.rag import generate
from evals.rag.golden import GoldenCase, GoldenChunk


def _case(cid="g1", answer="có khoáng nóng"):
    return GoldenCase(id=cid, tenant="t", query="q", chunks=(GoldenChunk(evidence="e"),), answer=answer)


def _row(cid="g1", retrieved=("chunk text",)):
    return {"id": cid, "ranks": [0], "hit": True, "latency_ms": 1.0, "n_hits": len(retrieved),
            "retrieved": list(retrieved), "error": ""}


def _patch(monkeypatch, *, gen_text="câu trả lời sinh", faithful=True, correctness=0.9):
    async def fake_llm(model, system, user, *, json_mode=True, max_tokens=800):
        assert not json_mode
        return gen_text

    async def fake_json(model, system, user, *, max_tokens=800):
        if "ĐỠ" in system or "đỡ" in system:
            return "", {"faithful": faithful, "unsupported_claims": [], "rationale": ""}
        return "", {"correct": correctness, "rationale": ""}

    monkeypatch.setattr(judge_client, "call_llm", fake_llm)
    monkeypatch.setattr(judge_client, "call_llm_json", fake_json)
    judge_client.set_cache_path(None)


async def test_happy_path(monkeypatch):
    _patch(monkeypatch)
    out = await generate.run_generation([_case()], [_row()], model="m")
    assert out["metrics"]["faithfulness_rate"] == 1.0
    assert out["metrics"]["rag_answer_correctness_mean"] == 0.9
    assert out["metrics"]["rag_refusal_rate"] == 0.0
    assert out["metrics"]["generation_coverage"] == 1.0


async def test_refusal_counted_when_context_had_hit(monkeypatch):
    _patch(monkeypatch, gen_text="Tôi không tìm thấy thông tin này.")
    out = await generate.run_generation([_case()], [_row()], model="m")
    assert out["metrics"]["rag_refusal_rate"] == 1.0


async def test_no_answer_or_empty_retrieved_skipped(monkeypatch):
    _patch(monkeypatch)
    out = await generate.run_generation(
        [_case("g1", answer=""), _case("g2")],
        [_row("g1"), _row("g2", retrieved=())], model="m")
    assert out["metrics"]["generation_coverage"] is None  # 0 case đủ điều kiện
    assert out["metrics"]["faithfulness_rate"] is None


async def test_judge_error_drops_coverage(monkeypatch):
    async def fake_llm(model, system, user, *, json_mode=True, max_tokens=800):
        return "câu trả lời"

    async def bad_json(model, system, user, *, max_tokens=800):
        return "", None

    monkeypatch.setattr(judge_client, "call_llm", fake_llm)
    monkeypatch.setattr(judge_client, "call_llm_json", bad_json)
    judge_client.set_cache_path(None)
    out = await generate.run_generation([_case()], [_row()], model="m")
    assert out["metrics"]["generation_coverage"] == 0.0
    assert out["metrics"]["faithfulness_rate"] is None
