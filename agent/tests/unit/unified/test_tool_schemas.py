from noble_agent.agent.tools.schemas import SCHEMAS, SEND_MEDIA_CONTENT_TYPES, schemas_for


def test_switch_agent_is_absent():
    assert "switch_agent" not in SCHEMAS


def test_escalate_description_is_only_human_handoff():
    desc = SCHEMAS["escalate"]["function"]["description"]
    assert "người thật" in desc
    assert "duy nhất" in desc


def test_booking_has_four_actions_no_slot():
    params = SCHEMAS["booking"]["function"]["parameters"]["properties"]
    assert params["action"]["enum"] == ["check_availability", "schedule", "list", "modify"]
    assert "preferred_slot" not in params


def test_schemas_for_returns_in_order():
    out = schemas_for(["update_customer", "kb_search"])
    assert [s["function"]["name"] for s in out] == ["update_customer", "kb_search"]


def test_noble_search_renamed_to_kb_search():
    assert "kb_search" in SCHEMAS
    assert "noble_search" not in SCHEMAS
    assert SCHEMAS["kb_search"]["function"]["name"] == "kb_search"


def test_schemas_for_skips_unknown():
    out = schemas_for(["nonexistent_tool", "kb_search"])
    assert [s["function"]["name"] for s in out] == ["kb_search"]


def test_merged_catalog_present():
    expected = {
        "update_customer",
        "kb_search",
        "discover_projects",
        "get_document",
        "search_units",
        "booking",
        "escalate",
        "send_media",
        "analyze_projects",
    }
    assert expected.issubset(SCHEMAS.keys())
    assert "get_project_financial" not in SCHEMAS
    # Post-sale CRM tools were removed — no tenant could ever offer them.
    assert not ({"crm_lookup", "verify_identity", "support_ticket"} & SCHEMAS.keys())
    # Merge 2026-09-07: 3 tool bị nuốt — schema phải biến mất hẳn.
    assert not ({"recommend_units", "get_project_overview", "check_inventory"} & SCHEMAS.keys())


def test_get_document_schema():
    fn = SCHEMAS["get_document"]["function"]
    props = fn["parameters"]["properties"]
    assert set(props) == {"project_code", "query"}
    # empty project_code is valid — the executor defaults it via
    # dispatcher.default_project_code / the provider's __ALL__ sentinel,
    # consistent with get_project_overview's required=[].
    assert fn["parameters"]["required"] == []


def test_search_units_uses_new_field_names():
    props = SCHEMAS["search_units"]["function"]["parameters"]["properties"]
    for new in ("product_type", "block", "sale_status"):
        assert new in props
    for old in ("unit_type", "tower", "status", "budget_max"):
        assert old not in props
    assert props["sale_status"]["enum"] == ["available", "booked", "sold"]


def test_search_units_merged_scope_and_union_params():
    # Merge 2026-09-07: search_units nuốt recommend_units — scope bắt buộc phân
    # đôi nghĩa của project_code rỗng; union filter hai phía.
    fn = SCHEMAS["search_units"]["function"]
    props = fn["parameters"]["properties"]
    assert props["scope"]["enum"] == ["in_project", "all_projects"]
    assert fn["parameters"]["required"] == ["scope"]  # project_code KHÔNG còn required
    for p in ("bedrooms", "region", "max_price", "purpose", "index"):
        assert p in props, p


def test_project_code_params_have_no_enum():
    """Project-code params are free-text now — the LLM resolves a code via
    find_project instead of picking from a per-session DB-code enum."""
    out = {
        s["function"]["name"]: s
        for s in schemas_for(
            ["booking", "discover_projects", "get_document", "search_units", "kb_search", "send_media"]
        )
    }
    for name in ("booking", "discover_projects", "get_document", "search_units", "send_media"):
        assert "enum" not in out[name]["function"]["parameters"]["properties"]["project_code"]
    assert "enum" not in out["kb_search"]["function"]["parameters"]["properties"]["project_filter"]


def test_schemas_for_ignores_codes_kwarg_for_backward_compat():
    """`codes=` is accepted (legacy callers) but has no effect on the output."""
    out_with_codes = schemas_for(["booking"], codes=["NCLB", "NPTTL"])
    out_without_codes = schemas_for(["booking"])
    assert out_with_codes == out_without_codes


def test_discover_projects_schema_enums():
    fn = SCHEMAS["discover_projects"]["function"]
    props = fn["parameters"]["properties"]
    assert props["product_type"]["enum"] == [
        "chung_cu", "biet_thu", "lien_ke", "shophouse", "dat_nen", "van_phong",
    ]
    assert props["purpose"]["enum"] == ["live", "invest"]
    assert "index" in props
    assert "list_projects" not in SCHEMAS


def test_discover_projects_has_overview_mode():
    # Merge 2026-09-07: nuốt get_project_overview — có mã → chi tiết một dự án.
    fn = SCHEMAS["discover_projects"]["function"]
    assert "project_code" in fn["parameters"]["properties"]
    assert "tổng quan" in fn["description"] or "chi tiết" in fn["description"]


def test_send_media_requires_only_query():
    params = SCHEMAS["send_media"]["function"]["parameters"]
    assert params["required"] == ["query"]
    # `ids` KHÔNG vào `required`: nó chỉ có ở lượt gửi của luồng hai bước, và bắt
    # buộc nó là chặn luôn lượt đầu.
    assert set(params["properties"]) == {"query", "ids", "project_code", "category", "content_type"}


def test_send_media_content_type_enum_matches_source_of_truth():
    props = SCHEMAS["send_media"]["function"]["parameters"]["properties"]
    # `tour_360` thêm 2026-08-14: Portal ghi link tour vào collection `_media` để LLM không
    # phải chép lại một URL dài nhiều tham số.
    assert SEND_MEDIA_CONTENT_TYPES == ("image", "video", "tour_360")
    assert props["content_type"]["enum"] == list(SEND_MEDIA_CONTENT_TYPES)


def test_send_media_category_copy_no_longer_says_mandatory():
    """category giờ optional — mô tả không được còn ép LLM luôn điền."""
    props = SCHEMAS["send_media"]["function"]["parameters"]["properties"]
    assert "BẮT BUỘC" not in props["category"]["description"]


def test_send_media_description_tells_llm_to_pass_at_least_one():
    desc = SCHEMAS["send_media"]["function"]["description"]
    assert "ÍT NHẤT MỘT" in desc
    assert "content_type=video" in desc


def test_update_customer_description_asks_for_one_batched_call():
    desc = SCHEMAS["update_customer"]["function"]["description"]
    assert "MỘT lời gọi" in desc


# ── Bước 2 review chất lượng: protocol riêng từng tool sống ở description (một nguồn sự thật).
def _desc(name: str) -> str:
    return SCHEMAS[name]["function"]["description"]


def test_booking_description_carries_the_step_protocol():
    d = _desc("booking")
    assert "not_found" in d                                      # bước 0: find_project not_found → dừng
    assert d.index("check_availability") < d.index("schedule")   # thứ tự bước
    assert "riêng" in d.lower()                                  # hỏi tên + số là bước RIÊNG
    assert "update_customer" in d                                # không ghi tên/số đặt lịch vào hồ sơ


def test_send_media_description_carries_the_three_cases_and_fallback():
    d = _desc("send_media")
    assert "tong_quan" in d and "MỘT lần" in d                   # chủ động, mỗi dự án một lần
    assert "category_fallback" in d and "candidates" in d        # luồng hai bước
    assert "nhiều dự án" in d.lower()                            # không gửi khi liệt kê nhiều dự án


def test_search_units_description_explains_band_note_and_both_scopes():
    d = _desc("search_units")
    assert "no_units_in_area_band" in d
    assert "in_project" in d and "all_projects" in d
    assert "recommend_units" not in d  # tool đó đã bị nuốt — không được chỉ LLM gọi tên chết


def test_analyze_projects_description_has_sql_error_fallback():
    d = _desc("analyze_projects")
    assert "sửa" in d and "discover_projects" in d


def test_analyze_projects_description_covers_inventory_questions():
    # Merge 2026-09-07: check_inventory bị nuốt — câu tồn kho đi đường SQL,
    # description phải chở ví dụ GROUP BY tồn kho để few-shot.
    d = _desc("analyze_projects")
    assert "tồn kho" in d and "sale_status" in d
    assert "check_inventory" not in d and "recommend_units" not in d


def test_find_project_description_has_confirmation_ladder():
    d = _desc("find_project")
    assert "ambiguous" in d and "best_guess" in d and "recently_listed" in d
    assert "mã của dự án khác" in d                              # không thay mã dự án khác


def test_discover_projects_description_has_widen_on_empty():
    assert "hẹp nhất" in _desc("discover_projects")


def test_escalate_description_says_relay_message_field():
    assert "message" in _desc("escalate")


def test_search_units_feng_shui_guidance_gated_by_rankers():
    from noble_agent.agent.tools.schemas import build_schemas

    on = build_schemas(["search_units"], brand={}, rankers=frozenset({"feng_shui"}))[0]["function"]["description"]
    off = build_schemas(["search_units"], brand={}, rankers=frozenset())[0]["function"]["description"]
    assert "birth_year" in on and "[FENG_SHUI]" not in on
    assert "birth_year" not in off and "FENG_SHUI" not in off


# ── Routing giá căn → search_units (27/08): tài liệu KHÔNG có giá, kho căn mới có.
def _built(names: list[str]) -> dict[str, str]:
    from noble_agent.agent.tools.schemas import build_schemas

    built = build_schemas(names, brand={}, rankers=frozenset())
    return {s["function"]["name"]: s["function"]["description"] for s in built}


def test_price_questions_route_to_search_units_not_kb_search():
    d = _built(["kb_search", "search_units"])
    assert "giá Noble Crystal" not in d["kb_search"]                # ví dụ cũ đẩy giá vào tài liệu
    assert "search_units" in d["kb_search"]                          # kb_search chỉ sang kho căn khi hỏi giá
    assert "giá" in d["search_units"] and "kb_search" in d["search_units"]  # nhận câu hỏi giá, nói rõ không kb_search
    assert "[TOOL:" not in d["kb_search"]                            # marker đã được cắt


def test_kb_search_drops_the_search_units_pointer_when_that_tool_is_off():
    d = _built(["kb_search"])
    assert "search_units" not in d["kb_search"]
    assert "[TOOL:" not in d["kb_search"] and "[/TOOL:" not in d["kb_search"]


# ── Routing bản CSBH → get_document (27/08): "có bản nào / mới nhất / xin file" là danh sách tài liệu,
#    không phải nội dung; kb_search chỉ cho chi tiết bên trong (chiết khấu, vay, tiến độ).
def test_sales_policy_document_requests_route_to_get_document():
    d = _built(["kb_search", "get_document"])
    assert "get_document" in d["kb_search"] and "mới nhất" in d["kb_search"]
    assert "mới nhất" in d["get_document"] and "kb_search" in d["get_document"]
    assert "[TOOL:" not in d["kb_search"]


def test_kb_search_drops_the_get_document_pointer_when_that_tool_is_off():
    d = _built(["kb_search"])
    assert "get_document" not in d["kb_search"]


# ── Escalate theo CHỦ ĐỀ giao dịch của khách, không theo "đã mua hay chưa" (27/08, eval QA-310/403/409, POL-405).
def test_escalate_description_covers_customer_transactions_not_project_legal():
    d = _desc("escalate")
    assert "chuyển nhượng" in d and "CHƯA mua" in d          # bán lại / sang tên, kể cả khách chưa mua
    assert "KHÔNG kb_search" in d                            # không tra cứu trước rồi tự trả lời
    assert "sổ hồng lâu dài" in d                            # pháp lý DỰ ÁN vẫn là kb_search (QA-302)
    assert "người hay máy" in d and "KHÔNG hỏi lại" in d   # POL-507: "em là người hay máy?" → escalate, không hỏi lý do
    assert "theo CSBH" in d                                 # QA-214: chiết khấu theo CSBH ≠ đòi giá riêng → kb_search
    assert "booking" in d and "đặt cọc" in d               # lịch xem → booking; cọc theo CSBH → kb_search
