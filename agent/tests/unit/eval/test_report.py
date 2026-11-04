from eval.report import build_report


def _detail(turn_idx, fc, rule=None, llm=None):
    row = {"conversation_id": "c", "turn_idx": turn_idx, "step_idx_in_turn": 0, "fc": fc}
    if rule is not None:
        row["response_rule"] = rule
    if llm is not None:
        row["response_llm"] = llm
    return row


def test_build_report_summary_and_per_turn():
    fc_with_pair = {
        "has_tool_calls": True,
        "pairs": [{"predicted": {"name": "x"}, "expected": {"name": "x"}, "errors": []}],
    }
    details = [
        _detail(0, fc_with_pair, rule={"forbidden_words": 1, "politeness_markers": 1}),
        _detail(1, {"has_tool_calls": False, "pairs": []}, rule={"forbidden_words": 0, "politeness_markers": 1}),
    ]
    report = build_report(
        details, slug="20260604_x", eval_file="f.jsonl", response_eval_mode="rule", tfidf_threshold=0.7
    )
    assert report["n_conversations"] == 1
    assert report["summary"]["n_total_turns"] == 2
    assert report["summary"]["fc_metrics"]["n_turns_with_tool_calls"] == 1
    assert report["summary"]["response_rule"]["forbidden_words"]["pass_rate"] == 0.5
    assert set(report["per_turn"].keys()) == {"0", "1"}
    assert report["max_turns"] == 1


def test_build_report_includes_llm_when_present():
    details = [
        _detail(
            0,
            {"has_tool_calls": False, "pairs": []},
            llm={"aggregate": 4.0, "factual_pass": True, "scores": {"clarity": 4}},
        )
    ]
    report = build_report(details, slug="s", eval_file="f", response_eval_mode="both", tfidf_threshold=0.7)
    assert "response_llm" in report["summary"]
    assert report["summary"]["response_llm"]["factual_pass_rate"] == 1.0
    assert report["summary"]["response_llm"]["aggregate"] == 4.0
