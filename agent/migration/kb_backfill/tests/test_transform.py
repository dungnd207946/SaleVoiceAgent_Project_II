from kb_backfill import transform as t


def test_price_ty_to_vnd():
    assert t._to_vnd(5.62) == 5_620_000_000
    assert t._to_vnd(None) is None
    assert t._to_vnd("") is None


def test_bedrooms():
    assert t._bedrooms("2PN") == 2
    assert t._bedrooms("STUDIO") == 0
    assert t._bedrooms("") is None


def test_direction_fold():
    st = {}
    assert t._fold_direction("Đông Nam", st) == "dong_nam"
    assert t._fold_direction("tay-bac", st) == "tay_bac"
    assert t._fold_direction("Đông", st) == "dong"
    assert t._fold_direction("xyz", st) is None
    assert st["direction_unmapped"] == 1  # only the junk value counted


def test_direction_fold_strips_scraped_area_suffix():
    # live nbx_units concatenates a scraped "Thông thủy <area> m² -->" tail onto some
    # direction values — the direction prefix is real and should still resolve.
    st = {}
    assert t._fold_direction("Đông Nam Thông thủy 54.4 m² -->", st) == "dong_nam"
    assert t._fold_direction("Tây Bắc Thông thủy 0 m² -->", st) == "tay_bac"
    assert st.get("direction_unmapped", 0) == 0


def test_direction_fold_garbage_only_and_dual_direction_stay_unmapped():
    # "Thông thủy ... -->" with no leading direction token carries no direction info;
    # a hyphenated dual-facing value ("Tây Bắc-Đông Bắc") can't be forced into the
    # single-value enum — both are honestly left unmapped (-> NULL), not guessed.
    st = {}
    assert t._fold_direction("Thông thủy 104.39 m² -->", st) is None
    assert t._fold_direction("Tây Bắc-Đông Bắc", st) is None
    assert t._fold_direction("Tây Nam-Đông Bắc", st) is None
    assert st["direction_unmapped"] == 3


def test_sale_status():
    st = {}
    assert t._sale_status("available", st) == "available"
    assert t._sale_status("ready", st) == "available"
    assert t._sale_status("sold", st) == "sold"
    assert t._sale_status("locked", st) == "booked"
    assert t._sale_status("hidden", st) == "available"  # fallback
    assert st["sale_status_fallback"] == 1


def test_product_type():
    st = {}
    assert t._product_type("STUDIO", "cao_tang", st) == "studio"
    assert t._product_type("STU", "cao_tang", st) == "studio"  # live abbreviated unitType code
    assert t._product_type("2PN", "cao_tang", st) == "chung_cu"
    assert t._product_type("", "thap_tang", st) == "biet_thu"
    assert t._product_type("", "hon_hop", st) == "chung_cu"
    assert t._product_type("", "", st) is None
    assert st["product_type_null"] == 1


def test_unit_row_maps_and_derives_price_per_m2():
    st = {}
    u = {"code": "S3.06.08", "unitType": {"name": "2PN", "group": "g"},
         "area": "78.4", "areaBuild": "85.2", "price": 5.62, "priceTts": 5.5,
         "direction": "Đông Nam", "status": "available", "image": "http://x/a.jpg"}
    row = t.unit_row(u, "NPLB", "cao_tang", st)
    assert row["unit_code"] == "S3.06.08"
    assert row["product_type"] == "chung_cu"
    assert row["bedrooms"] == 2
    assert row["direction"] == "dong_nam"
    assert row["area_built_m2"] == 78.4 and row["area_wall_m2"] == 85.2
    assert row["price_vnd"] == 5_620_000_000
    assert row["price_per_m2_vnd"] == round(5_620_000_000 / 78.4)
    assert row["sale_status"] == "available"
    assert row["image_url"] == "http://x/a.jpg"


def test_unit_row_price_per_m2_none_when_area_missing():
    st = {}
    row = t.unit_row({"code": "U1", "unitType": {"name": "1PN"}, "price": 3.0,
                      "area": None, "status": "available"}, "P", "cao_tang", st)
    assert row["price_per_m2_vnd"] is None


def test_unit_row_handles_string_unit_type():
    # live nbx_units has unitType as a bare code string (e.g. "LK"/"HOT"/"STU"), not a dict.
    st = {}
    row = t.unit_row({"code": "U2", "unitType": "LK", "price": 3.0,
                      "area": "50", "status": "available"}, "P", "cao_tang", st)
    assert row["bedrooms"] is None
    assert row["product_type"] == "chung_cu"  # falls back to project-type default
    assert st["unittype_string_fallback"] == 1


def test_unit_row_abbreviated_studio_code_resolves_studio():
    # unitType as a dict abbreviates the studio name to "STU" (not the full "STUDIO").
    st = {}
    row = t.unit_row({"code": "U3", "unitType": {"name": "STU"}, "price": 2.0,
                      "area": "30", "status": "available"}, "P", "cao_tang", st)
    assert row["bedrooms"] is None
    assert row["product_type"] == "studio"
    assert st.get("unittype_string_fallback", 0) == 0  # unitType was a dict, no fallback counted


def test_unit_row_bare_string_studio_code_resolves_studio():
    # the live/common case: unitType is a BARE string "STU" (no dict wrapper at all) —
    # the raw string itself must still resolve to product_type=studio, and the
    # string-unitType fallback stat still increments since it wasn't a dict.
    st = {}
    row = t.unit_row({"code": "U4", "unitType": "STU", "price": 2.0,
                      "area": "30", "status": "available"}, "P", "cao_tang", st)
    assert row["bedrooms"] is None
    assert row["product_type"] == "studio"
    assert st["unittype_string_fallback"] == 1


def test_project_row_category_derived_from_units():
    doc = {"projectCode": "nplb", "name": "Noble Palace", "areaRegion": "Long Biên",
           "location": "Q. Long Biên", "type": "hon_hop", "investor": "Noble",
           "description": "Đại đô thị", "overview": {"scale": "2400 sp", "ownership": "Lâu dài"}}
    units = [
        {"product_type": "chung_cu"}, {"product_type": "biet_thu"},
        {"product_type": "chung_cu"}, {"product_type": None},
    ]
    row = t.project_row(doc, units)
    assert row["project_code"] == "NPLB"
    assert row["category"] == ["biet_thu", "chung_cu"]  # sorted distinct, None dropped
    assert row["region"] == "Long Biên" and row["address"] == "Q. Long Biên"
    assert row["investor"] == "Noble" and row["product_scale"] == "2400 sp"
    assert row["ownership_form"] == "Lâu dài" and row["overview"] == "Đại đô thị"
    assert row["sale_phase"] == "dang_ban"


def test_project_row_category_fallback_from_type_when_no_units():
    row = t.project_row({"projectCode": "P1", "type": "cao_tang"}, [])
    assert row["category"] == ["chung_cu"]


def test_project_row_category_hon_hop_fallback_is_sorted():
    row = t.project_row({"projectCode": "P1", "type": "hon_hop"}, [])
    assert row["category"] == ["biet_thu", "chung_cu"]  # sorted, not insertion order


def test_project_row_overview_double_encoded_string():
    doc = {"projectCode": "P1", "type": "cao_tang",
           "overview": '{"scale": "100 căn", "ownership": "50 năm"}'}
    row = t.project_row(doc, [])
    assert row["product_scale"] == "100 căn" and row["ownership_form"] == "50 năm"


def test_project_code_of_empty():
    assert t.project_code_of({"projectCode": ""}) == ""
    assert t.project_code_of({"projectCode": " nplb "}) == "NPLB"
    assert t.project_code_of({"projectCode": 123}) == "123"  # non-string guard
