"""Chú giải scorecard (metric / trục / finding) — phủ đủ và render ra đúng chỗ."""

import asyncio

from evals.quality import report_docs
from evals.quality.judge import score_judge
from evals.quality.latency import score_latency
from evals.quality.scorecard import Scorecard, build_scorecard, evaluate_gates, render_markdown
from evals.quality.scorers import AxisScore, Finding
from evals.quality.scorers.policy import score_policy
from evals.quality.scorers.run_integrity import score_run_integrity
from evals.quality.scorers.style import score_style
from evals.quality.scorers.tool_selection import score_tool_selection
from evals.quality.scorers.trajectory import score_trajectory


def _all_shipped_metric_names() -> set[str]:
    """Tên metric của MỌI scorer đang ship.

    Gọi với input rỗng: scorer nào cũng dựng đủ khoá metric (giá trị None) nên lấy được
    vocabulary mà không cần Redis/LLM/trace thật.
    """
    axes = [
        score_policy([], []),
        score_tool_selection([], []),
        score_trajectory([], []),
        score_run_integrity([], []),
        score_style([], []),
        score_latency([], []),
        *asyncio.run(score_judge([], [])),
    ]
    return {name for axis in axes for name in axis.metrics}


def test_moi_metric_dang_ship_deu_co_mo_ta():
    """Thêm metric ở scorer mà quên khai mô tả ⇒ đỏ ở đây, không lọt im lặng ra report."""
    missing = sorted(_all_shipped_metric_names() - set(report_docs.METRIC_DOCS))
    assert not missing, f"thiếu mô tả cho: {missing} (bổ sung vào evals/quality/report_docs.py)"


def test_khong_mo_ta_thua():
    """Mô tả cho metric không còn tồn tại = tài liệu chết, dễ gây hiểu nhầm khi đọc report."""
    stale = sorted(set(report_docs.METRIC_DOCS) - _all_shipped_metric_names())
    assert not stale, f"mô tả thừa (metric đã bị xoá?): {stale}"


def test_describe_metric_la_raise():
    assert report_docs.describe("khong_ton_tai") == ""


def _card(metrics: dict, thresholds: dict) -> Scorecard:
    axis = AxisScore(axis="x", checks=1, failures=0, metrics=metrics)
    return build_scorecard("run-1", {}, [axis], thresholds)


def test_render_in_cot_y_nghia_va_gate():
    th = {"gates": [{"name": "g", "metric": "arg_accuracy", "op": ">=", "limit": 1.0}]}
    md = render_markdown(_card({"arg_accuracy": 0.99, "cases_gated": 95.0}, th))
    assert "| metric | value | gate | ý nghĩa |" in md
    assert report_docs.LEGEND in md
    # metric bị gate: in kèm ngưỡng, lấy từ card.gates chứ không hard-code
    assert "| `arg_accuracy` | 0.99 | `>= 1` |" in md
    # metric không bị gate: cột gate là gạch ngang
    assert "| `cases_gated` | 95 | — |" in md
    # mô tả thật sự xuất hiện, không phải ô rỗng
    assert report_docs.describe("arg_accuracy") in md


def test_render_khong_vo_bang_khi_metric_chua_co_mo_ta():
    """Metric lạ vẫn render được (ô ý nghĩa rỗng) — report không được sập vì thiếu doc."""
    md = render_markdown(_card({"metric_moi_toanh": 1.0}, {"gates": []}))
    assert "| `metric_moi_toanh` | 1 | — |  |" in md


def test_gate_missing_hien_ro_trong_bang_metric():
    th = {"gates": [{"name": "g", "metric": "policy_violations", "op": "<=", "limit": 0.0}]}
    card = _card({"policy_violations": None}, th)
    md = render_markdown(card)
    assert "| `policy_violations` | missing | `<= 0` |" in md
    assert evaluate_gates(card.metrics, th)[0].ok is False


# ── trục + loại finding ───────────────────────────────────────────────────────


def _all_shipped_axis_names() -> set[str]:
    axes = [
        score_policy([], []), score_tool_selection([], []), score_trajectory([], []),
        score_run_integrity([], []), score_latency([], []), *asyncio.run(score_judge([], [])),
    ]
    return {a.axis for a in axes}


def test_moi_truc_deu_co_mo_ta():
    missing = sorted(_all_shipped_axis_names() - set(report_docs.AXIS_DOCS))
    assert not missing, f"thiếu mô tả trục: {missing}"


def test_moi_kind_finding_deu_co_mo_ta():
    """Vocabulary kind lấy từ CHÍNH mã nguồn, không chép tay — thêm kind mới là đỏ ở đây."""
    import re
    from pathlib import Path

    kinds: set[str] = set()
    for path in Path("evals/quality").rglob("*.py"):
        for m in re.finditer(r'Finding\([^)]*?"([a-z_]+)"', path.read_text(encoding="utf-8")):
            kinds.add(m.group(1))
    # policy mượn vocabulary assertion của e2e_scenarios
    from tests.e2e_scenarios.assertions import KNOWN_KEYS

    kinds |= {k for k in KNOWN_KEYS if not k.startswith("tool_")}
    missing = sorted(kinds - set(report_docs.FINDING_DOCS))
    assert not missing, f"thiếu mô tả finding kind: {missing}"


def test_render_chu_giai_cho_moi_section():
    th = {"gates": [{"name": "g", "metric": "policy_violations", "op": "<=", "limit": 0.0}]}
    axis = AxisScore(axis="policy", checks=2, failures=1, metrics={"policy_violations": 1.0},
                     findings=(Finding("C1", 0, "reply_not_contains", "x"),))
    md = render_markdown(build_scorecard("r", {"model": "m"}, [axis], th))
    assert report_docs.CONFIG_LEGEND in md
    assert report_docs.GATES_LEGEND in md
    assert report_docs.AXES_LEGEND in md
    assert report_docs.FINDINGS_LEGEND in md
    assert "| axis | checks | failures | pass rate | chấm gì |" in md
    assert report_docs.describe_axis("policy") in md
    # chú giải kind: chỉ kind CÓ trong report
    assert "| reply_not_contains | " in md
    assert "hallucination" not in md, "không được liệt kê kind không xuất hiện trong report"
