import json

from eval.data import TurnSample, enumerate_turns, load_eval_file


def _record():
    return {
        "conversation_id": "synth-abc",
        "tools": [{"type": "function", "function": {"name": "update_customer", "parameters": {}}}],
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "alo em"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "update_customer", "arguments": '{"name": "Anh Nam"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "update_customer", "content": "{}"},
            {"role": "assistant", "content": "Dạ chào anh Nam, em là Luna ạ"},
            {"role": "user", "content": "giá sao em"},
            {"role": "assistant", "content": "Dạ em kiểm tra giúp anh ạ. Cảm ơn anh đã quan tâm Noble"},
        ],
    }


def test_enumerate_counts_and_flags():
    samples = enumerate_turns(_record())
    assert len(samples) == 3
    assert all(isinstance(s, TurnSample) for s in samples)
    assert samples[0].is_first_assistant is True
    assert samples[0].is_final_assistant is False
    assert samples[-1].is_final_assistant is True


def test_turn_and_step_indices():
    samples = enumerate_turns(_record())
    # turn 0: two assistant steps (tool-call step, then answer step)
    assert (samples[0].turn_idx, samples[0].step_idx_in_turn) == (0, 0)
    assert (samples[1].turn_idx, samples[1].step_idx_in_turn) == (0, 1)
    # turn 1: one assistant step
    assert (samples[2].turn_idx, samples[2].step_idx_in_turn) == (1, 0)


def test_prefix_and_user_message():
    samples = enumerate_turns(_record())
    assert samples[0].user_message == "alo em"
    assert len(samples[0].prefix) == 2  # system + user
    assert samples[1].prefix[-1]["role"] == "tool"
    assert samples[2].user_message == "giá sao em"
    assert samples[0].tools == _record()["tools"]


def test_reference_response_is_the_assistant_message():
    samples = enumerate_turns(_record())
    assert samples[0].reference_response["tool_calls"][0]["function"]["name"] == "update_customer"
    assert "Luna" in samples[1].reference_response["content"]


def test_load_eval_file_skips_blank_lines(tmp_path):
    p = tmp_path / "eval.jsonl"
    p.write_text(
        json.dumps({"conversation_id": "a", "messages": []})
        + "\n"
        + "\n"
        + json.dumps({"conversation_id": "b", "messages": []})
        + "\n",
        encoding="utf-8",
    )
    records = load_eval_file(p)
    assert [r["conversation_id"] for r in records] == ["a", "b"]
