from eval.tool_metrics import aggregate_fc, extract_tool_calls, schema_format_bad, score_turn_fc, value_similarity

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_project_financial",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_code": {"type": "string"},
                    "info_type": {"type": "string", "enum": ["pricing", "fees"]},
                },
                "required": ["project_code", "info_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_customer",
            "parameters": {"type": "object", "properties": {"name": {"type": "string"}}},
        },
    },
]


def _asst(*calls):
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": f"c{i}", "type": "function", "function": {"name": n, "arguments": a}}
            for i, (n, a) in enumerate(calls)
        ],
    }


def test_extract_parses_arguments_json():
    msg = _asst(("update_customer", '{"name": "Nam"}'))
    calls = extract_tool_calls(msg)
    assert calls == [{"name": "update_customer", "args": {"name": "Nam"}}]


def test_value_similarity_bounds():
    assert value_similarity("NCTH", "NCTH") == 1.0
    assert value_similarity("NCTH", "SSLC") < 0.7


def test_exact_match_no_errors():
    pred = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    exp = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert out["has_tool_calls"] is True
    assert out["pairs"][0]["errors"] == []


def test_missing_function_call():
    pred = {"role": "assistant", "content": "Dạ", "tool_calls": []}
    exp = _asst(("update_customer", '{"name": "Nam"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert out["pairs"][0]["errors"] == ["missing_function_call"]


def test_unwanted_function_call():
    pred = _asst(("update_customer", '{"name": "Nam"}'))
    exp = {"role": "assistant", "content": "Dạ", "tool_calls": []}
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert out["pairs"][0]["errors"] == ["unwanted_function_call"]


def test_incorrect_format_undeclared_key_and_bad_enum():
    pred = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "weather"}'))
    exp = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert "incorrect_function_format" in out["pairs"][0]["errors"]


def test_missing_argument():
    pred = _asst(("get_project_financial", '{"project_code": "NCTH"}'))
    exp = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert "missing_argument" in out["pairs"][0]["errors"]


def test_wrong_argument_value():
    pred = _asst(("get_project_financial", '{"project_code": "SSLC", "info_type": "pricing"}'))
    exp = _asst(("get_project_financial", '{"project_code": "NCTH", "info_type": "pricing"}'))
    out = score_turn_fc(pred, exp, tools=TOOLS, threshold=0.7)
    assert "wrong_argument_value" in out["pairs"][0]["errors"]


def test_aggregate_rates():
    rows = [
        {
            "fc": {
                "has_tool_calls": True,
                "pairs": [
                    {"predicted": {"name": "x"}, "expected": None, "errors": ["unwanted_function_call"]},
                ],
            }
        },
        {
            "fc": {
                "has_tool_calls": True,
                "pairs": [
                    {"predicted": None, "expected": {"name": "y"}, "errors": ["missing_function_call"]},
                ],
            }
        },
    ]
    agg = aggregate_fc(rows)
    assert agg["n_turns_with_tool_calls"] == 2
    assert agg["n_total_pairs"] == 2
    assert agg["unwanted_function_call_rate"] == 0.5
    assert agg["missing_function_call_rate"] == 0.5


def test_schema_format_bad_detects_undeclared_key_type_enum():
    schema = {
        "type": "object",
        "properties": {
            "project_code": {"type": "string"},
            "info_type": {"type": "string", "enum": ["pricing", "fees"]},
        },
    }
    assert schema_format_bad({"project_code": "NCTH"}, schema) is False
    assert schema_format_bad({"unknown_key": "x"}, schema) is True  # undeclared key
    assert schema_format_bad({"info_type": "weather"}, schema) is True  # bad enum
    assert schema_format_bad({"project_code": 123}, schema) is True  # bad type
    assert schema_format_bad({"anything": "x"}, {}) is False  # no properties → not bad


def test_empty_required_list_is_respected():
    # schema explicitly declares no required fields; predicted omitting an expected key must NOT be "missing_argument"
    tools = [
        {
            "type": "function",
            "function": {
                "name": "f",
                "parameters": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "required": [],
                },
            },
        }
    ]
    pred = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c0", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
    }
    exp = {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "c0", "type": "function", "function": {"name": "f", "arguments": '{"a": "x"}'}}],
    }
    out = score_turn_fc(pred, exp, tools=tools, threshold=0.7)
    assert "missing_argument" not in out["pairs"][0]["errors"]
