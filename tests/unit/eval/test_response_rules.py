from eval.data import TurnSample
from eval.response_rules import aggregate_rules, extract_customer_name, score_turn_rules


def _sample(*, first=False, final=False, prefix=None):
    return TurnSample(
        conversation_id="c",
        turn_idx=0,
        step_idx_in_turn=0,
        is_first_assistant=first,
        is_final_assistant=final,
        user_message="alo",
        prefix=prefix or [],
        reference_response={},
        tools=[],
    )


def test_opening_compliance_pass_and_fail():
    s = _sample(first=True)
    assert score_turn_rules(s, {"content": "Dạ chào anh, em là Luna ạ"})["opening_compliance"] == 1
    assert score_turn_rules(s, {"content": "Chào anh"})["opening_compliance"] == 0


def test_opening_is_none_when_not_first():
    s = _sample(first=False)
    assert score_turn_rules(s, {"content": "Dạ em là Luna"})["opening_compliance"] is None


def test_closing_compliance():
    s = _sample(final=True)
    assert score_turn_rules(s, {"content": "Cảm ơn anh đã quan tâm Noble ạ"})["closing_compliance"] == 1
    assert score_turn_rules(s, {"content": "Dạ vâng ạ"})["closing_compliance"] == 0


def test_forbidden_words():
    s = _sample()
    assert score_turn_rules(s, {"content": "Dạ vâng ạ"})["forbidden_words"] == 1
    assert score_turn_rules(s, {"content": "Anh chờ chút nhé"})["forbidden_words"] == 0


def test_conciseness_2_to_3_sentences():
    s = _sample()
    assert score_turn_rules(s, {"content": "Dạ vâng ạ"})["conciseness_clarity"] == 1  # 1 sentence ok (max 3)
    assert score_turn_rules(s, {"content": "Câu một. Câu hai."})["conciseness_clarity"] == 1
    assert score_turn_rules(s, {"content": "Một. Hai. Ba. Bốn."})["conciseness_clarity"] == 0


def test_politeness_markers():
    s = _sample()
    assert score_turn_rules(s, {"content": "Dạ được ạ"})["politeness_markers"] == 1
    assert score_turn_rules(s, {"content": "Ok xong"})["politeness_markers"] == 0


def test_tool_only_turn_skips_text_axes():
    s = _sample()
    out = score_turn_rules(s, {"content": ""})
    assert out["forbidden_words"] is None
    assert out["conciseness_clarity"] is None
    assert out["politeness_markers"] is None
    assert out["opening_compliance"] is None
    assert out["closing_compliance"] is None


def test_extract_customer_name_and_name_usage():
    prefix = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "update_customer", "arguments": '{"name": "Nam"}'},
                }
            ],
        },
    ]
    assert extract_customer_name(prefix) == "Nam"
    s = _sample(prefix=prefix)
    assert score_turn_rules(s, {"content": "Dạ cảm ơn anh Nam ạ"})["name_usage"] == 1
    assert score_turn_rules(s, {"content": "Dạ cảm ơn anh ạ"})["name_usage"] == 0


def test_aggregate_rules_pass_rate():
    rows = [
        {"rule": {"forbidden_words": 1, "politeness_markers": 1, "opening_compliance": None}},
        {"rule": {"forbidden_words": 0, "politeness_markers": 1, "opening_compliance": 1}},
    ]
    agg = aggregate_rules(rows)
    assert agg["forbidden_words"]["pass_rate"] == 0.5
    assert agg["forbidden_words"]["n_evaluated"] == 2
    assert agg["opening_compliance"]["n_evaluated"] == 1
    assert 0.0 <= agg["aggregate"] <= 1.0


def test_conciseness_does_not_split_on_decimal_price():
    s = _sample()
    # "Giá 5.5 tỷ anh ạ. Thanh toán 30%." is 2 sentences, not 3.
    assert score_turn_rules(s, {"content": "Giá 5.5 tỷ anh ạ. Thanh toán 30 phần trăm."})["conciseness_clarity"] == 1


def test_name_usage_uses_word_boundary():
    prefix = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "update_customer", "arguments": '{"name": "An"}'}}
            ],
        },
    ]
    s = _sample(prefix=prefix)
    # "An" must NOT match inside "anh"/"quan"
    assert score_turn_rules(s, {"content": "Dạ em tư vấn cho anh ạ"})["name_usage"] == 0
    # but matches when the standalone token "An" is present
    assert score_turn_rules(s, {"content": "Dạ cảm ơn anh An ạ"})["name_usage"] == 1
