"""Scorecard tests — thresholds → verdict → markdown. Pure."""

from __future__ import annotations

import pytest
from evals.quality.scorecard import build_scorecard, evaluate_gates, load_thresholds, render_markdown
from evals.quality.scorers import AxisScore, Finding

_THRESHOLDS = {
    "gates": [
        {"name": "Vi phạm policy", "metric": "policy_violations", "op": "<=", "limit": 0.0},
        {"name": "Tool arg accuracy", "metric": "arg_accuracy", "op": ">=", "limit": 1.0},
    ]
}


def test_gate_passes_when_within_limit():
    gates = evaluate_gates({"policy_violations": 0.0, "arg_accuracy": 1.0}, _THRESHOLDS)
    assert [g.ok for g in gates] == [True, True]


def test_gate_fails_and_keeps_actual_value():
    gates = evaluate_gates({"policy_violations": 3.0, "arg_accuracy": 0.5}, _THRESHOLDS)
    assert [g.ok for g in gates] == [False, False]
    assert gates[0].actual == 3.0
    assert gates[0].limit == 0.0


def test_missing_metric_fails_closed():
    gates = evaluate_gates({}, _THRESHOLDS)
    assert all(not g.ok for g in gates)
    assert "missing" in render_markdown(build_scorecard("r1", {}, [], _THRESHOLDS)).lower()


def test_present_but_none_metric_fails_closed_like_an_absent_one():
    """C2's other half. A scorer that measured nothing emits `None` rather than a
    vacuous pass value. `evaluate_gates` used to do `float(metrics[metric])`
    after an `in` check, which would raise TypeError on that None; it must be
    treated exactly like an absent key — actual=None, ok=False, renders
    "missing".
    """
    gates = evaluate_gates({"policy_violations": 0.0, "arg_accuracy": None}, _THRESHOLDS)
    assert [g.ok for g in gates] == [True, False]
    assert gates[1].actual is None

    axis = AxisScore(axis="tool", checks=0, failures=0, metrics={"policy_violations": 0.0, "arg_accuracy": None})
    card = build_scorecard("r1", {}, [axis], _THRESHOLDS)
    assert card.ok is False
    md = render_markdown(card)
    assert "missing" in md
    # The Metrics table must not crash on a None either.
    assert "`arg_accuracy` | missing" in md


@pytest.mark.parametrize(
    ("op", "limit", "actual", "expected"),
    [
        ("<", 1.0, 0.5, True),
        ("<", 1.0, 1.0, False),
        (">", 0.0, 0.5, True),
        (">", 0.0, 0.0, False),
        ("==", 3.0, 3.0, True),
        ("==", 3.0, 2.0, False),
    ],
)
def test_every_comparator_is_exercised(op, limit, actual, expected):
    gates = evaluate_gates({"m": actual}, {"gates": [{"name": "n", "metric": "m", "op": op, "limit": limit}]})
    assert gates[0].ok is expected


def test_markdown_escapes_pipes_and_strips_newlines_in_finding_details():
    """A finding detail carrying a literal `|` would break the Markdown table it
    renders into, and a literal newline would split one row into two. Both occur
    in practice: POL-004's own regex contains `(?:em|mình)` and
    `reply_not_matches` details interpolate the pattern verbatim.
    """
    axis = AxisScore(
        axis="policy",
        checks=1,
        failures=1,
        findings=(Finding("POL-004", 0, "reply_not_matches", "matched r'(?:em|mình)'\nsecond line"),),
        metrics={"policy_violations": 1.0, "arg_accuracy": 1.0},
    )
    md = render_markdown(build_scorecard("r1", {}, [axis], _THRESHOLDS))
    row = next(line for line in md.splitlines() if "POL-004" in line)
    assert r"(?:em\|mình)" in row
    assert "second line" in row  # newline collapsed into the SAME row
    assert "\n" not in row


def test_duplicate_metric_name_across_axes_is_rejected():
    """`build_scorecard` merges every axis's metrics into one dict. A duplicate
    name used to silently shadow — the last scorer wins and the gate reads a
    number from a scorer nobody expected. This file's whole job is not lying.
    """
    a = AxisScore(axis="policy", checks=1, failures=0, metrics={"policy_violations": 0.0})
    b = AxisScore(axis="tool", checks=1, failures=0, metrics={"policy_violations": 99.0})
    with pytest.raises(ValueError, match="duplicate metric"):
        build_scorecard("r1", {}, [a, b], _THRESHOLDS)


def test_scorecard_ok_only_when_every_gate_passes():
    axis = AxisScore(axis="policy", checks=2, failures=0, metrics={"policy_violations": 0.0, "arg_accuracy": 1.0})
    good = build_scorecard("r1", {"git_sha": "abc"}, [axis], _THRESHOLDS)
    assert good.ok is True

    bad_axis = AxisScore(
        axis="policy",
        checks=2,
        failures=1,
        findings=(Finding("POL-1", 0, "escalated", "no escalate"),),
        metrics={"policy_violations": 1.0, "arg_accuracy": 1.0},
    )
    bad = build_scorecard("r1", {}, [bad_axis], _THRESHOLDS)
    assert bad.ok is False


def test_markdown_lists_config_axes_gates_and_findings():
    axis = AxisScore(
        axis="policy",
        checks=3,
        failures=1,
        findings=(Finding("POL-7", 1, "reply_not_matches", "matched '5 tỷ'"),),
        metrics={"policy_violations": 1.0, "arg_accuracy": 1.0},
    )
    md = render_markdown(build_scorecard("20260817-1200", {"git_sha": "abc1234"}, [axis], _THRESHOLDS))
    assert "20260817-1200" in md
    assert "abc1234" in md
    assert "policy" in md
    assert "POL-7" in md
    assert "5 tỷ" in md
    assert "FAIL" in md


def test_load_thresholds_reads_toml(tmp_path):
    p = tmp_path / "t.toml"
    p.write_text(
        '[[gates]]\nname = "Vi phạm policy"\nmetric = "policy_violations"\nop = "<="\nlimit = 0.0\n',
        encoding="utf-8",
    )
    loaded = load_thresholds(p)
    assert loaded["gates"][0]["metric"] == "policy_violations"


def test_load_thresholds_rejects_bad_op(tmp_path):
    p = tmp_path / "t.toml"
    p.write_text('[[gates]]\nname = "x"\nmetric = "m"\nop = "~="\nlimit = 1.0\n', encoding="utf-8")
    with pytest.raises(ValueError, match="unknown op"):
        load_thresholds(p)


def test_load_thresholds_rejects_missing_metric(tmp_path):
    p = tmp_path / "t.toml"
    p.write_text('[[gates]]\nname = "x"\nop = "<="\nlimit = 1.0\n', encoding="utf-8")
    with pytest.raises(ValueError, match="needs 'metric'"):
        load_thresholds(p)


def test_real_thresholds_file_is_valid():
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / "evals" / "quality" / "data" / "thresholds.toml"
    if not path.is_file():
        pytest.skip("data ported in a later task")
    loaded = load_thresholds(path)
    assert loaded["gates"], "shipped thresholds.toml must define at least one gate"


_JUDGE_THRESHOLDS = {
    "gates": [
        {"name": "policy", "metric": "policy_violations", "op": "<=", "limit": 0.0},
        {"name": "bịa", "metric": "hallucination_rate", "op": "<=", "limit": 0.4, "judge": True},
    ]
}


def test_judge_gate_is_skipped_not_failed_when_judge_did_not_run():
    """Gate loại 2 trên metric judge chỉ có nghĩa khi judge chạy; run không `--judge`
    không được FAIL vì thiếu số mà nó cố ý không đo."""
    gates = evaluate_gates({"policy_violations": 0.0}, _JUDGE_THRESHOLDS, judge_ran=False)
    assert [g.ok for g in gates] == [True, True]
    assert gates[1].skipped is True and gates[1].actual is None
    assert gates[0].skipped is False


def test_judge_gate_enforced_when_judge_ran():
    gates = evaluate_gates({"policy_violations": 0.0, "hallucination_rate": 0.5}, _JUDGE_THRESHOLDS, judge_ran=True)
    assert [g.ok for g in gates] == [True, False]
    assert gates[1].skipped is False
    # judge chạy mà metric vẫn thiếu → fail-closed như mọi gate khác
    gates = evaluate_gates({"policy_violations": 0.0}, _JUDGE_THRESHOLDS, judge_ran=True)
    assert gates[1].ok is False and gates[1].skipped is False


def test_skipped_gate_renders_as_skipped_and_card_passes():
    axis = AxisScore(axis="policy", checks=1, failures=0, metrics={"policy_violations": 0.0})
    card = build_scorecard("r1", {}, [axis], _JUDGE_THRESHOLDS, judge_ran=False)
    assert card.ok is True
    md = render_markdown(card)
    assert "skipped" in md.lower()


def test_load_thresholds_rejects_non_bool_judge_flag(tmp_path):
    p = tmp_path / "t.toml"
    p.write_text('[[gates]]\nname="g"\nmetric="m"\nop="<="\nlimit=0.0\njudge="yes"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_thresholds(p)
