"""Judge 3-rubric — mock judge_client.call_llm_json, không network."""
import json

from evals import judge_client
from evals.quality import judge
from evals.quality.cases import EvalCase, EvalTurn, TurnGolden
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn


def _case(*turns, reviewed=True):
    return EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=reviewed,
                    tags=("qa",), turns=tuple(turns))


def _qa_turn(answer="đáp án chuẩn"):
    return EvalTurn(user="hỏi", expect={}, golden=TurnGolden(answer=answer))


def _trace(*turns, error=None):
    return TraceCase(case_id="C1", tags=("qa",), tenant="t", channel="chat", reviewed=True,
                     turns=tuple(turns), error=error)


def _kb_turn(reply="trả lời", result='{"chunks": ["giá 2 tỷ"]}'):
    return TraceTurn(user="hỏi", reply=reply,
                     tool_calls=(TracedToolCall("kb_search", {"query": "giá"}, raw_result=result),))


def _patch(monkeypatch, payloads: dict[str, dict]):
    """payloads: map rubric-name → dict judge trả về. Nhận diện rubric qua system prompt."""
    async def fake(model, system, user, *, max_tokens=800):
        for name, payload in payloads.items():
            if judge._SYSTEMS[name] == system:
                return json.dumps(payload), payload
        raise AssertionError(f"unexpected system prompt: {system[:60]}")
    monkeypatch.setattr(judge_client, "call_llm_json", fake)
    judge_client.set_cache_path(None)


async def test_correctness_and_groundedness_graded(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 0.8, "intent_aligned": True, "hallucinated": False, "rationale": "ok"},
        "groundedness": {"grounded": True, "unsupported_claims": [], "rationale": "ok"},
    })
    axes = await judge.score_judge([_case(_qa_turn())], [_trace(_kb_turn())])
    by = {a.axis: a for a in axes}
    assert by["correctness"].metrics["answer_correctness_mean"] == 0.8
    assert by["correctness"].metrics["hallucination_rate"] == 0.0
    assert by["correctness"].metrics["intent_alignment_rate"] == 1.0
    assert by["groundedness"].metrics["grounded_rate"] == 1.0
    assert by["multiturn"].metrics["context_retention_score"] is None  # case 1 turn → không chấm multiturn


async def test_hallucination_and_ungrounded_findings(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 0.2, "intent_aligned": False, "hallucinated": True, "rationale": "bịa"},
        "groundedness": {"grounded": False, "unsupported_claims": ["sổ hồng trao tay"], "rationale": "x"},
    })
    axes = await judge.score_judge([_case(_qa_turn())], [_trace(_kb_turn())])
    by = {a.axis: a for a in axes}
    assert by["correctness"].metrics["hallucination_rate"] == 1.0
    assert any(f.kind == "hallucination" for f in by["correctness"].findings)
    assert any("sổ hồng" in f.detail for f in by["groundedness"].findings)


async def test_groundedness_skipped_without_tool_calls(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 1.0, "intent_aligned": True, "hallucinated": False, "rationale": ""},
    })
    bare = TraceTurn(user="hỏi", reply="trả lời")  # 0 tool call
    axes = await judge.score_judge([_case(_qa_turn())], [_trace(bare)])
    by = {a.axis: a for a in axes}
    assert by["groundedness"].metrics["grounded_rate"] is None
    assert by["groundedness"].metrics["groundedness_coverage"] is None


async def test_multiturn_judged_on_multi_turn_case(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 1.0, "intent_aligned": True, "hallucinated": False, "rationale": ""},
        "groundedness": {"grounded": True, "unsupported_claims": [], "rationale": ""},
        "multiturn": {"context_retention": 0.9, "consistency": 1.0, "issues": [], "rationale": ""},
    })
    case = _case(_qa_turn(), _qa_turn())
    trace = _trace(_kb_turn(), _kb_turn())
    axes = await judge.score_judge([case], [trace])
    by = {a.axis: a for a in axes}
    assert by["multiturn"].metrics["context_retention_score"] == 0.9
    assert by["multiturn"].metrics["multiturn_coverage"] == 1.0


async def test_judge_error_drops_coverage_not_score(monkeypatch):
    async def boom(model, system, user, *, max_tokens=800):
        return "", None  # judge parse fail toàn tập
    monkeypatch.setattr(judge_client, "call_llm_json", boom)
    judge_client.set_cache_path(None)
    axes = await judge.score_judge([_case(_qa_turn())], [_trace(_kb_turn())])
    by = {a.axis: a for a in axes}
    assert by["correctness"].metrics["correctness_coverage"] == 0.0
    assert by["correctness"].metrics["answer_correctness_mean"] is None  # thiếu mẫu ≠ điểm 0
    assert any(f.kind == "judge_ungraded" for f in by["correctness"].findings)


async def test_unreviewed_and_no_answer_skipped(monkeypatch):
    _patch(monkeypatch, {})
    no_answer = EvalTurn(user="u", expect={"reply_contains": ["x"]}, golden=None)
    axes = await judge.score_judge([_case(no_answer)], [_trace(_kb_turn())])
    assert all(a.checks == 0 for a in axes)


# ── tiến độ pha judge (thêm 2026-08-25 sau khi một lượt 100 case bị Ctrl-C vì im lặng) ──


def _mt_case():
    return EvalCase(id="C1", origin="handwritten", tenant="t", channel="chat", reviewed=True,
                    tags=("qa",), turns=(_qa_turn(), _qa_turn()))


def test_plan_dem_dung_so_call():
    """1 correctness + 1 groundedness mỗi lượt có evidence, + 1 multiturn cho case ≥2 lượt."""
    trace = TraceCase(case_id="C1", tags=("qa",), tenant="t", channel="chat", reviewed=True,
                      turns=(_kb_turn(), _kb_turn()))
    assert judge.plan_judge_calls([_mt_case()], [trace]) == 5


def test_plan_bo_qua_case_chua_duyet_va_case_loi():
    trace = _trace(_kb_turn())
    assert judge.plan_judge_calls([_case(_qa_turn(), reviewed=False)], [trace]) == 0
    assert judge.plan_judge_calls([_case(_qa_turn())], [_trace(_kb_turn(), error="boom")]) == 0


def test_plan_khong_dem_groundedness_khi_khong_co_evidence():
    """Lượt không gọi tool nào thì không có gì để chấm groundedness."""
    trace = _trace(TraceTurn(user="hỏi", reply="trả lời", tool_calls=()))
    assert judge.plan_judge_calls([_case(_qa_turn())], [trace]) == 1


async def test_progress_duoc_goi_du_va_bao_cache_hit(monkeypatch):
    _patch(monkeypatch, {
        "correctness": {"correct": 1.0, "intent_aligned": True, "hallucinated": False, "rationale": ""},
        "groundedness": {"grounded": True, "unsupported_claims": [], "rationale": ""},
    })
    seen: list[tuple] = []
    cases, traces = [_case(_qa_turn())], [_trace(_kb_turn())]
    planned = judge.plan_judge_calls(cases, traces)
    await judge.score_judge(cases, traces, progress=lambda *a: seen.append(a))
    assert [s[0] for s in seen] == list(range(1, planned + 1)), "done phải tăng đều 1..planned"
    assert all(s[1] == planned for s in seen), "planned phải là hằng số"
    assert [s[2] for s in seen] == ["correctness", "groundedness"]
    assert all(s[4] is False for s in seen), "cache đã tắt trong test → không được báo cache hit"
