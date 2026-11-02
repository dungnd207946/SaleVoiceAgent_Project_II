import json

from eval.runner import existing_keys, sample_from_row, score_prediction_row, write_manifest


def test_sample_from_row_roundtrips_fields():
    row = {
        "conversation_id": "c",
        "turn_idx": 2,
        "step_idx_in_turn": 1,
        "is_first_assistant": False,
        "is_final_assistant": True,
        "user_message": "hi",
        "prefix": [{"role": "user", "content": "hi"}],
        "reference_response": {"role": "assistant", "content": "ref"},
        "tools": [{"type": "function", "function": {"name": "x"}}],
    }
    s = sample_from_row(row)
    assert s.dedup_key() == ("c", 2, 1)
    assert s.is_final_assistant is True
    assert s.tools[0]["function"]["name"] == "x"


def test_score_prediction_row_rule_only():
    pred_row = {
        "conversation_id": "c",
        "turn_idx": 0,
        "step_idx_in_turn": 0,
        "is_first_assistant": True,
        "is_final_assistant": False,
        "user_message": "alo",
        "prefix": [],
        "reference_response": {"role": "assistant", "content": "Dạ chào anh, em là Luna ạ", "tool_calls": []},
        "predicted_response": {"role": "assistant", "content": "Dạ chào anh, em là Luna ạ", "tool_calls": []},
        "tools": [],
    }
    row = score_prediction_row(pred_row, response_eval_mode="rule", tfidf_threshold=0.7, judge=None)
    assert row["fc"]["has_tool_calls"] is False
    assert row["response_rule"]["opening_compliance"] == 1
    assert "response_llm" not in row


def test_score_prediction_row_with_judge():
    pred_row = {
        "conversation_id": "c",
        "turn_idx": 0,
        "step_idx_in_turn": 0,
        "is_first_assistant": False,
        "is_final_assistant": False,
        "user_message": "alo",
        "prefix": [],
        "reference_response": {"role": "assistant", "content": "ref", "tool_calls": []},
        "predicted_response": {"role": "assistant", "content": "pred", "tool_calls": []},
        "tools": [],
    }
    seen = {}

    def fake_judge(sample, predicted):
        seen["key"] = sample.dedup_key()
        return {"aggregate": 4.0, "factual_pass": True, "scores": {"clarity": 4}}

    row = score_prediction_row(pred_row, response_eval_mode="both", tfidf_threshold=0.7, judge=fake_judge)
    assert row["response_llm"]["aggregate"] == 4.0
    assert seen["key"] == ("c", 0, 0)


def test_existing_keys_reads_dedup_keys(tmp_path):
    p = tmp_path / "predictions.jsonl"
    p.write_text(json.dumps({"conversation_id": "c", "turn_idx": 0, "step_idx_in_turn": 0}) + "\n", encoding="utf-8")
    assert existing_keys(p) == {("c", 0, 0)}


def test_existing_keys_missing_file(tmp_path):
    assert existing_keys(tmp_path / "nope.jsonl") == set()


def test_write_manifest_appends(tmp_path):
    mpath = tmp_path / "eval_manifest.json"
    write_manifest(mpath, {"slug": "a"})
    write_manifest(mpath, {"slug": "b"})
    data = json.loads(mpath.read_text(encoding="utf-8"))
    assert [e["slug"] for e in data] == ["a", "b"]
