"""LLM judge — 3 rubric: correctness / groundedness / multiturn (spec §5.2).

Grader duy nhất trong evals/quality gọi network, chạy ở pha SCORE (đọc trace,
không đụng agent), gated --judge. Hạ tầng (cache sqlite, budget, retry) nằm ở
evals/judge_client.py.

Turn ungraded (lỗi/hết budget) trừ vào *_coverage, KHÔNG trừ vào điểm — thiếu
mẫu phải hiện ra là thiếu, không phải là điểm 0.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from evals import judge_client
from evals.quality.scorers import AxisScore, Finding

logger = logging.getLogger("evals.quality.judge")

_RUBRIC_V = {"correctness": "v1", "groundedness": "v1", "multiturn": "v1"}

# (done, planned, rubric, case_id, cache_hit)
ProgressFn = Callable[[int, int, str, str, bool], None]

_SYSTEMS = {
    "correctness": (
        "Bạn là giám khảo chấm độ ĐÚNG của câu trả lời tư vấn viên BĐS so với đáp án chuẩn.\n"
        "Chấm khách quan, trả JSON đúng schema, không thêm prose."
    ),
    "groundedness": (
        "Bạn là giám khảo kiểm tra câu trả lời của tư vấn viên có được ĐỠ bởi dữ liệu tool trả về không.\n"
        "Chấm khách quan, trả JSON đúng schema, không thêm prose."
    ),
    "multiturn": (
        "Bạn là giám khảo đánh giá CẢ HỘI THOẠI nhiều lượt giữa khách và tư vấn viên BĐS.\n"
        "Chấm khách quan, trả JSON đúng schema, không thêm prose."
    ),
}


def _user_correctness(user: str, golden_answer: str, reply: str) -> str:
    return (
        f"[KHÁCH HỎI]\n{user}\n\n[ĐÁP ÁN CHUẨN]\n{golden_answer}\n\n[TƯ VẤN VIÊN TRẢ LỜI]\n{reply}\n\n"
        "NHIỆM VỤ:\n"
        '1. "correct" 0..1: mức khớp NỘI DUNG với đáp án chuẩn (khác cách diễn đạt không trừ điểm).\n'
        '2. "intent_aligned": true nếu trả lời đúng trọng tâm câu khách hỏi.\n'
        '3. "hallucinated": true nếu có khẳng định factual mâu thuẫn hoặc vượt ra ngoài đáp án chuẩn.\n'
        '4. "rationale": 1-2 câu tiếng Việt.\n\n'
        'OUTPUT JSON: {"correct": 0.0..1.0, "intent_aligned": true|false, '
        '"hallucinated": true|false, "rationale": "..."}'
    )


def _user_groundedness(reply: str, tool_evidence: str) -> str:
    return (
        f"[DỮ LIỆU TOOL TRẢ VỀ]\n{tool_evidence}\n\n[TƯ VẤN VIÊN TRẢ LỜI]\n{reply}\n\n"
        "NHIỆM VỤ:\n"
        '1. "grounded": true nếu MỌI khẳng định factual trong câu trả lời được dữ liệu tool đỡ; '
        "false nếu có chi tiết bịa ngoài dữ liệu.\n"
        '2. "unsupported_claims": list các khẳng định không được đỡ (rỗng nếu grounded).\n'
        '3. "rationale": 1-2 câu tiếng Việt.\n\n'
        'OUTPUT JSON: {"grounded": true|false, "unsupported_claims": ["..."], "rationale": "..."}'
    )


def _user_multiturn(transcript: str, customer: str) -> str:
    return (
        f"[THÔNG TIN KHÁCH BAN ĐẦU]\n{customer or '(trống)'}\n\n[HỘI THOẠI]\n{transcript}\n\n"
        "NHIỆM VỤ:\n"
        '1. "context_retention" 0..1: tư vấn viên có GIỮ và DÙNG thông tin khách đã nói ở các lượt trước không, '
        "có hỏi lại điều đã biết không (hỏi lại = trừ nặng).\n"
        '2. "consistency" 0..1: các lượt có tự mâu thuẫn về fact/cam kết không.\n'
        '3. "issues": list vấn đề cụ thể (rỗng nếu sạch).\n'
        '4. "rationale": 1-2 câu tiếng Việt.\n\n'
        'OUTPUT JSON: {"context_retention": 0.0..1.0, "consistency": 0.0..1.0, "issues": ["..."], "rationale": "..."}'
    )


def _key(rubric: str, case_id: str, payload: str, model: str) -> str:
    return judge_client.cache_key(rubric, _RUBRIC_V[rubric], case_id, payload, model)


async def _graded_call(rubric: str, case_id: str, payload: str, model: str) -> dict | None:
    """Gọi judge có cache; None = ungraded (lỗi/parse fail/budget)."""
    key = _key(rubric, case_id, payload, model)
    if hit := judge_client.cache_get(key):
        return hit
    try:
        _raw, parsed = await judge_client.call_llm_json(model, _SYSTEMS[rubric], payload)
    except judge_client.BudgetExceeded:
        return None
    except Exception as e:  # noqa: BLE001 — lỗi transient judge không được sập cả pha score
        logger.warning("judge %s transient error for %s: %s", rubric, case_id, e)
        return None
    if parsed is None:
        return None
    judge_client.cache_put(key, parsed)
    return parsed


def _clamp(x, default=0.0) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return default


def _mean_or_none(xs: list[float]) -> float | None:
    return (sum(xs) / len(xs)) if xs else None


def plan_judge_calls(cases, traces) -> int:
    """Số lời gọi judge một lượt score SẼ cần (kể cả cái sẽ hit cache). Pure, không network.

    Dùng để in tiến độ: pha judge chạy tuần tự, mỗi call tới 30s + 2 retry, nên một lượt
    100 case im lặng hàng chục phút — không có mẫu số thì người chạy tưởng nó treo và Ctrl-C
    giữa chừng (đã xảy ra thật 2026-08-25).
    """
    trace_by_id = {t.case_id: t for t in traces}
    n = 0
    for case in cases:
        if not case.reviewed:
            continue
        trace = trace_by_id.get(case.id)
        if trace is None or trace.error:
            continue
        for case_turn, trace_turn in zip(case.turns, trace.turns, strict=False):
            if not (case_turn.golden and case_turn.golden.answer):
                continue
            n += 1  # correctness
            if any(tc.raw_result for tc in trace_turn.tool_calls):
                n += 1  # groundedness
        if len(case.turns) >= 2 and len(trace.turns) >= 2:
            n += 1  # multiturn
    return n


async def score_judge(
    cases, traces, *, model: str = judge_client.JUDGE_MODEL, progress: ProgressFn | None = None
) -> list[AxisScore]:
    trace_by_id = {t.case_id: t for t in traces}
    planned = plan_judge_calls(cases, traces) if progress else 0
    done = 0

    async def _call(rubric: str, case_id: str, payload: str) -> dict | None:
        nonlocal done
        cached = judge_client.cache_get(_key(rubric, case_id, payload, model)) is not None
        out = await _graded_call(rubric, case_id, payload, model)
        done += 1
        if progress:
            progress(done, planned, rubric, case_id, cached)
        return out

    c_total = c_graded = 0
    corrects: list[float] = []
    intents: list[float] = []
    hallus: list[float] = []
    c_findings: list[Finding] = []

    g_total = g_graded = 0
    grounded: list[float] = []
    g_findings: list[Finding] = []

    m_total = m_graded = 0
    retention: list[float] = []
    consistency: list[float] = []
    m_findings: list[Finding] = []

    for case in cases:
        if not case.reviewed:
            continue
        trace = trace_by_id.get(case.id)
        if trace is None or trace.error:
            continue

        for i, (case_turn, trace_turn) in enumerate(zip(case.turns, trace.turns, strict=False)):
            golden = case_turn.golden
            if not golden or not golden.answer:
                continue

            c_total += 1
            v = await _call(
                "correctness", case.id, _user_correctness(trace_turn.user, golden.answer, trace_turn.reply)
            )
            if v is None:
                c_findings.append(Finding(case.id, i, "judge_ungraded", "correctness: lỗi judge/budget"))
            else:
                c_graded += 1
                corrects.append(_clamp(v.get("correct")))
                intents.append(1.0 if v.get("intent_aligned") else 0.0)
                hallucinated = bool(v.get("hallucinated"))
                hallus.append(1.0 if hallucinated else 0.0)
                if hallucinated:
                    c_findings.append(Finding(case.id, i, "hallucination", str(v.get("rationale", ""))))

            tool_evidence = "\n---\n".join(
                f"[{tc.name}] {tc.raw_result}" for tc in trace_turn.tool_calls if tc.raw_result
            )
            if tool_evidence:
                g_total += 1
                v = await _call("groundedness", case.id, _user_groundedness(trace_turn.reply, tool_evidence))
                if v is None:
                    g_findings.append(Finding(case.id, i, "judge_ungraded", "groundedness: lỗi judge/budget"))
                else:
                    g_graded += 1
                    is_grounded = bool(v.get("grounded"))
                    grounded.append(1.0 if is_grounded else 0.0)
                    if not is_grounded:
                        claims = "; ".join(str(c) for c in v.get("unsupported_claims") or [])
                        g_findings.append(Finding(case.id, i, "ungrounded", claims or str(v.get("rationale", ""))))

        if len(case.turns) >= 2 and len(trace.turns) >= 2:
            m_total += 1
            transcript = "\n".join(f"KHÁCH: {t.user}\nTƯ VẤN VIÊN: {t.reply}" for t in trace.turns)
            v = await _call("multiturn", case.id, _user_multiturn(transcript, str(case.customer or "")))
            if v is None:
                m_findings.append(Finding(case.id, -1, "judge_ungraded", "multiturn: lỗi judge/budget"))
            else:
                m_graded += 1
                retention.append(_clamp(v.get("context_retention")))
                consistency.append(_clamp(v.get("consistency")))
                for issue in v.get("issues") or []:
                    m_findings.append(Finding(case.id, -1, "multiturn_issue", str(issue)))

    def _cov(graded: int, total: int) -> float | None:
        return None if total <= 0 else graded / total

    return [
        AxisScore(
            axis="correctness", checks=c_graded,
            failures=sum(1 for f in c_findings if f.kind == "hallucination"), findings=tuple(c_findings),
            metrics={
                "answer_correctness_mean": _mean_or_none(corrects),
                "intent_alignment_rate": _mean_or_none(intents),
                "hallucination_rate": _mean_or_none(hallus),
                "correctness_coverage": _cov(c_graded, c_total),
            },
        ),
        AxisScore(
            axis="groundedness", checks=g_graded,
            failures=sum(1 for f in g_findings if f.kind == "ungrounded"), findings=tuple(g_findings),
            metrics={"grounded_rate": _mean_or_none(grounded), "groundedness_coverage": _cov(g_graded, g_total)},
        ),
        AxisScore(
            axis="multiturn", checks=m_graded,
            failures=sum(1 for f in m_findings if f.kind == "multiturn_issue"), findings=tuple(m_findings),
            metrics={
                "context_retention_score": _mean_or_none(retention),
                "consistency_score": _mean_or_none(consistency),
                "multiturn_coverage": _cov(m_graded, m_total),
            },
        ),
    ]
