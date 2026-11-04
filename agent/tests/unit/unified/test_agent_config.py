from noble_agent.agent.agent_config import CORE_TOOLS, OPTIONAL_TOOLS, parse_config


def test_defaults_when_empty():
    c = parse_config({})
    assert c.identity.agent_name == "Trợ lý"
    assert c.identity.honorific_self == "em"
    assert c.identity.honorific_customer == "anh/chị"
    assert c.identity.brand == "" and c.identity.greeting == ""
    assert c.scope.handoff_department == "CSKH"
    assert c.scope.does == "" and c.scope.refusal == ""
    assert c.scope.departments == ()
    assert c.style.tone == "than_thien" and c.style.reply_length == "trung_binh"
    assert c.enabled_tools == CORE_TOOLS          # only core, canonical order
    assert c.feng_shui is False
    assert c.media_channel == "noblex_app"
    assert c.data_source == "pg_kb"


def test_no_lookup_gated_off_by_default():
    # no_lookup_needed là van xả CHỈ cho LLM_FORCE_TOOL_FIRST_ROUND — cờ tắt
    # (mặc định) thì đừng chào một tool chết cho LLM mỗi lượt.
    c = parse_config({})
    assert "no_lookup_needed" not in c.enabled_tools
    assert "no_lookup_needed" not in CORE_TOOLS


def test_no_lookup_offered_when_force_tool_first_round():
    c = parse_config({"skills": ["booking"]}, force_tool_first_round=True)
    assert "no_lookup_needed" in c.enabled_tools
    # Van xả đứng cuối nhóm core, trước nhóm optional (giữ thứ tự canonical cũ).
    assert c.enabled_tools == CORE_TOOLS + ("no_lookup_needed", "booking")


def test_unions_core_and_keeps_canonical_order():
    c = parse_config({"skills": ["booking", "discover_projects"]})
    # core first (canonical), then optional in OPTIONAL_TOOLS order
    assert c.enabled_tools == CORE_TOOLS + ("discover_projects", "booking")


def test_drops_unknown_and_core_listed_in_enabled():
    c = parse_config({"skills": ["booking", "escalate", "frobnicate", "recall_memory"]})
    assert "frobnicate" not in c.enabled_tools
    assert "recall_memory" not in c.enabled_tools         # unknown skill → dropped
    assert c.enabled_tools.count("escalate") == 1        # core not double-added
    assert c.enabled_tools == CORE_TOOLS + ("booking",)


def test_feng_shui_derived_from_search_units():
    off = parse_config({"skills": ["booking"]})
    assert off.feng_shui is False                        # search_units not enabled
    on = parse_config({"skills": ["search_units"]})
    assert on.feng_shui is True                          # derived (no feng_shui column yet)


def test_legacy_tool_names_alias_to_merged_tools():
    # Config Portal đã publish TRƯỚC merge 2026-09-07 còn chở tên cũ — phải map
    # sang tool hợp nhất, dedupe, không phụ thuộc thứ tự deploy với Portal.
    c = parse_config({"skills": ["recommend_units", "get_project_overview", "check_inventory", "search_units"]})
    assert "search_units" in c.enabled_tools
    assert "discover_projects" in c.enabled_tools
    assert "analyze_projects" in c.enabled_tools
    for gone in ("recommend_units", "get_project_overview", "check_inventory"):
        assert gone not in c.enabled_tools
    assert c.enabled_tools.count("search_units") == 1    # alias + tên mới không nhân đôi
    assert c.feng_shui is True                           # derive chạy SAU alias


def test_identity_and_scope_parsed():
    c = parse_config({
        "name": "Luna", "brand_name": "An Phú Land",
        "self_pronoun": "mình", "customer_pronoun": "bạn", "greeting": "Xin chào",
        "scope_does": "Tư vấn.", "scope_does_not": "Hậu mãi.", "refusal_line": "Xin lỗi.",
        "departments": [{"ten": "Kế toán", "khi_nao": "hỏi hóa đơn"},
                        {"ten": "CSKH", "khi_nao": "hợp đồng đã ký"}],
    })
    assert c.identity.agent_name == "Luna" and c.identity.brand == "An Phú Land"
    assert c.identity.honorific_self == "mình" and c.identity.honorific_customer == "bạn"
    assert c.identity.greeting == "Xin chào"
    assert c.scope.does == "Tư vấn." and c.scope.does_not == "Hậu mãi." and c.scope.refusal == "Xin lỗi."
    # handoff_department defaults to the first department; the full list is preserved
    assert c.scope.handoff_department == "Kế toán"
    assert [d.ten for d in c.scope.departments] == ["Kế toán", "CSKH"]
    assert c.scope.departments[0].khi_nao == "hỏi hóa đơn"


def test_style_closed_vocab_falls_back_on_invalid():
    c = parse_config({"tone": "than_thien", "reply_length": "ngan"})
    assert c.style.tone == "than_thien" and c.style.reply_length == "ngan"
    bad = parse_config({"tone": "xxx", "reply_length": "yyy"})
    assert bad.style.tone == "than_thien" and bad.style.reply_length == "trung_binh"


def test_departments_drop_blank_and_default_handoff():
    c = parse_config({"departments": [{"khi_nao": "no name"}, {"ten": "  "}]})
    assert c.scope.departments == ()                     # blank/missing `ten` dropped
    assert c.scope.handoff_department == "CSKH"           # no valid dept → default


def test_all_optional_tools_are_enableable():
    """Verify that all optional tools can be enabled and union with core tools."""
    c = parse_config({"skills": list(OPTIONAL_TOOLS)})
    for t in OPTIONAL_TOOLS:
        assert t in c.enabled_tools
    assert set(c.enabled_tools) == set(CORE_TOOLS) | set(OPTIONAL_TOOLS)
