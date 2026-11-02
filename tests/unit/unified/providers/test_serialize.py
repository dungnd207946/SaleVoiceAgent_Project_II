"""Unit tests for the DTO -> LLM-facing JSON serialisers in
``noble_agent.data.providers._serialize``. These freeze the exact standardized
key set the LLM sees (SP1 KB-Postgres schema, Task 5)."""

from noble_agent.data.providers import _serialize as ser
from noble_agent.data.providers import base


def test_project_list_json_keys():
    pl = base.ProjectList(1, [base.ProjectSummary("MCP", "Masteri", "mien_bac", ("can_ho",))])
    out = ser.project_list_json(pl)
    assert out["count"] == 1
    assert set(out["projects"][0]) == {"code", "name", "category", "region"}
    assert out["projects"][0]["category"] == ["can_ho"]
    assert "region" not in out
    assert "note" not in out


def test_project_list_json_includes_region_and_note_when_present():
    pl = base.ProjectList(0, [], region="mien_nam", note="Không tìm thấy khu vực này.")
    out = ser.project_list_json(pl)
    assert out["region"] == "mien_nam"
    assert out["note"] == "Không tìm thấy khu vực này."


def test_discover_project_json_new_keys():
    s = base.ProjectSummary(
        code="NPLB",
        name="Noble Palace",
        region="mien_bac",
        category=("chung_cu", "shophouse"),
        investor="Noble",
        price_from_vnd=3_000_000_000,
        sale_phase="dang_ban",
    )
    out = ser.discover_project_json(s)
    assert set(out) == {"code", "name", "region", "category", "investor", "price_from_vnd", "sale_phase"}
    assert out["category"] == ["chung_cu", "shophouse"]
    assert "hot" not in out and "type" not in out


def test_overview_json_new_keys():
    ov = base.ProjectOverview(
        code="NPLB",
        name="Noble Palace",
        region="mien_bac",
        address="Long Biên, Hà Nội",
        investor="Noble",
        developer="Noble Dev",
        total_land_area_m2=12000.0,
        floor_area_m2=45000.0,
        build_density_pct=35.5,
        product_scale="500 căn",
        amenities="Bể bơi, gym",
        ownership_form="Sở hữu lâu dài",
        handover_standard="Hoàn thiện cơ bản",
        total_investment_vnd=5_000_000_000_000,
        sale_phase="dang_ban",
        overview="Dự án ven sông.",
        link_360="https://example.com/360",
    )
    out = ser.overview_json(ov)
    assert set(out) == {
        "code",
        "name",
        "region",
        "address",
        "investor",
        "developer",
        "total_land_area_m2",
        "floor_area_m2",
        "build_density_pct",
        "product_scale",
        "amenities",
        "ownership_form",
        "handover_standard",
        "total_investment_vnd",
        "sale_phase",
        "overview",
        "link_360",
    }
    assert out["address"] == "Long Biên, Hà Nội"
    assert out["total_land_area_m2"] == 12000.0


def test_overview_json_none_text_fields_become_empty_string_numerics_stay_none():
    ov = base.ProjectOverview(code="NPLB", name="Noble Palace")
    out = ser.overview_json(ov)
    assert out["region"] == ""
    assert out["address"] == ""
    assert out["investor"] == ""
    assert out["developer"] == ""
    assert out["product_scale"] == ""
    assert out["amenities"] == ""
    assert out["ownership_form"] == ""
    assert out["handover_standard"] == ""
    assert out["sale_phase"] == ""
    assert out["overview"] == ""
    assert out["link_360"] == ""
    assert out["total_land_area_m2"] is None
    assert out["floor_area_m2"] is None
    assert out["build_density_pct"] is None
    assert out["total_investment_vnd"] is None


def test_unit_json_new_keys():
    u = base.Unit(
        project_code="NPLB",
        project_name="Noble Palace",
        zone_code="RIVER",
        unit_code="S3.06.08",
        product_type="chung_cu",
        bedrooms=3,
        block="S3",
        floor=6,
        num_floors=None,
        direction="dong_nam",
        area_built_m2=78.4,
        area_wall_m2=85.2,
        area_land_m2=None,
        price_vnd=5_620_000_000,
        price_per_m2_vnd=71_000_000,
        sale_status="available",
        image_url="",
    )
    j = ser.unit_json(u)
    assert j["product_type"] == "chung_cu" and j["area_built_m2"] == 78.4
    assert j["sale_status"] == "available" and j["block"] == "S3"
    assert "clear_area_m2" not in j and "max_discount_pct" not in j
    assert set(j) == {
        "unit_code",
        "product_type",
        "bedrooms",
        "direction",
        "block",
        "floor",
        "num_floors",
        "area_built_m2",
        "area_wall_m2",
        "area_land_m2",
        "price_vnd",
        "price_per_m2_vnd",
        "sale_status",
        "image_url",
        "project_code",
        "project_name",
    }


def test_unit_json_none_optional_fields_become_empty_string():
    u = base.Unit(
        project_code="NPLB",
        project_name="Noble Palace",
        zone_code=None,
        unit_code="S3.06.08",
        product_type="chung_cu",
        bedrooms=None,
        block=None,
        floor=None,
        num_floors=None,
        direction=None,
        area_built_m2=None,
        area_wall_m2=None,
        area_land_m2=None,
        price_vnd=None,
        price_per_m2_vnd=None,
        sale_status="unknown",
        image_url=None,
    )
    j = ser.unit_json(u)
    assert j["direction"] == ""
    assert j["block"] == ""
    assert j["image_url"] == ""
    assert j["floor"] is None
    assert j["area_built_m2"] is None
    assert j["price_vnd"] is None


def test_no_pricing_json_and_no_inventory_json():
    assert not hasattr(ser, "pricing_json")
    assert not hasattr(ser, "_unit_type_pricing_json")
    # check_inventory gộp vào analyze_projects (merge 2026-09-07) — serializer đi theo.
    assert not hasattr(ser, "inventory_json")
