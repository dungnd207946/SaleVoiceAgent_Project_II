"""search_units HỢP NHẤT (nuốt recommend_units, merge 2026-09-07) — tool layer.

Một tool căn duy nhất: ``scope='in_project'`` tra trong MỘT dự án (adapter điền
project_code từ hồ sơ; vẫn rỗng → needs_info), ``scope='all_projects'`` gợi ý
xuyên dự án. Envelope hội tụ về dạng NHÓM của recommend cũ:
``units`` (đúng ngân sách) + ``upsell_units`` (vượt-trong-biên, group pitch) +
``counts``/``index``/``has_more``/``next_index``. Giữ nguyên các hành vi đã
eval-tune: dải diện tích ±20% quanh "tầm X" + fallback off-target, headroom
ngân sách, căn chưa-có-giá xếp cuối/loại khi lọc giá, phong thủy soft-rank +
guard con giáp, paging 6 căn, pitch sống ở MỌI lần gọi.

Provider được fake theo đúng contract pg_kb sau merge: MỘT method
``search_units(UnitQuery)`` áp hard filter rồi trả RAW units, rỗng → None.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from noble_agent.agent.tools import projects_info as pi
from noble_agent.data.providers import base

_REGIONS = {"NPTTL": "Hà Nội", "NCR": "Hưng Yên", "SLC": "Hà Nội"}


def _unit(
    code: str,
    area: float | None = 75.0,
    price: int | None = 3_000_000_000,
    *,
    project: str = "SLC",
    bedrooms: int | None = None,
    direction: str = "Đông Nam",
    amenities: str | None = None,
) -> base.Unit:
    return base.Unit(
        project_code=project,
        project_name=_REGIONS.get(project, ""),
        zone_code=None,
        unit_code=code,
        product_type="chung_cu",
        bedrooms=bedrooms,
        block="CT02",
        floor=10,
        num_floors=None,
        direction=direction,
        area_built_m2=area,
        area_wall_m2=None,
        area_land_m2=None,
        price_vnd=price,
        price_per_m2_vnd=None,
        sale_status="available",
        image_url=None,
        amenities=amenities,
    )


_AREA_UNITS = [
    _unit("U-46", 46.0),
    _unit("U-75", 75.0),
    _unit("U-98", 98.0),
    _unit("U-118", 118.0),
    _unit("U-125", 125.0),
    _unit("U-150", 150.0),
    _unit("U-300", 300.0),
]

_BED_UNITS = [
    _unit("A-01", project="NPTTL", bedrooms=2, price=3_000_000_000, direction="Đông Nam"),
    _unit("A-02", project="NPTTL", bedrooms=2, price=4_500_000_000, direction="Tây Bắc"),
    _unit("A-03", project="NPTTL", bedrooms=3, price=6_000_000_000, direction="Nam"),
    _unit("B-01", project="NCR", bedrooms=2, price=2_500_000_000, direction="Tây"),
]


class _FakeProvider:
    """Áp đúng các hard filter mà pg_kb sau merge sẽ áp (project/bedrooms/region/
    giá/diện tích) rồi trả RAW units; RỖNG → None (như SQL không có row).
    ``down=True`` giả backend chết."""

    def __init__(self, units, *, down=False):
        self._units = units
        self._down = down
        self.queries: list[base.UnitQuery] = []

    @property
    def last_query(self):
        return self.queries[-1] if self.queries else None

    async def search_units(self, query: base.UnitQuery):
        self.queries.append(query)
        if self._down:
            return None
        units = list(self._units)
        if query.project_code:
            units = [u for u in units if u.project_code == query.project_code]
        if query.bedrooms:
            units = [u for u in units if u.bedrooms == query.bedrooms]
        if query.region:
            units = [u for u in units if query.region.lower() in _REGIONS.get(u.project_code, "").lower()]
        if query.min_area_built_m2 > 0:
            units = [u for u in units if (u.area_built_m2 or 0) >= query.min_area_built_m2]
        if query.max_area_built_m2 > 0:
            units = [u for u in units if (u.area_built_m2 or 0) <= query.max_area_built_m2]
        if query.max_price_vnd:
            units = [u for u in units if (u.price_vnd or 0) <= query.max_price_vnd]
        return units or None


def _install(monkeypatch, units, **kw) -> _FakeProvider:
    fake = _FakeProvider(units, **kw)
    monkeypatch.setattr(pi.providers, "get_provider", lambda _s: fake)
    return fake


@pytest.fixture
def area_provider(monkeypatch):
    return _install(monkeypatch, _AREA_UNITS)


@pytest.fixture
def feng_shui_on(monkeypatch):
    """Ranker phong thủy BẬT, độc lập .env (AGENT_CONFIG_SOURCE=db trả ctx rỗng
    làm fixture patch-dict cũ trượt im lặng)."""
    from noble_agent.tenant import loader

    monkeypatch.setattr(loader, "get_tenant_context", lambda: SimpleNamespace(rankers=frozenset({"feng_shui"})))


def _state():
    return SimpleNamespace(scratchpad={})


def _customer(gender=None):
    return SimpleNamespace(gender=gender, project_interest="")


async def _run(args: dict, *, state=None, customer=None) -> dict | str:
    out = await pi.search_units(args, state=state, customer=customer)
    return out if out == base.ESCALATE_SIGNAL else json.loads(out)


# ── scope ────────────────────────────────────────────────────────────────────


async def test_in_project_without_code_returns_needs_info(area_provider):
    # Adapter đã thử điền từ hồ sơ mà vẫn rỗng → nhắc find_project, KHÔNG xổ
    # xuyên dự án oan (nghĩa cũ của search) và KHÔNG escalate.
    out = await _run({"scope": "in_project"})
    assert out["needs_info"] is True and "find_project" in out["message"]
    assert area_provider.queries == []  # chưa đụng provider


async def test_all_projects_queries_cross_project(monkeypatch):
    prov = _install(monkeypatch, _BED_UNITS)
    out = await _run({"scope": "all_projects", "bedrooms": 2}, state=_state(), customer=_customer())
    assert prov.queries[0].project_code == ""
    codes = {u["project_code"] for u in out["units"]}
    assert codes == {"NPTTL", "NCR"}


async def test_missing_scope_falls_back_on_project_code_presence(monkeypatch):
    # Model quên scope (dù schema required): có mã → in-project, không mã →
    # xuyên dự án (nghĩa recommend cũ) — không được needs_info oan.
    prov = _install(monkeypatch, _BED_UNITS)
    out = await _run({"project_code": "NPTTL"})
    assert prov.queries[0].project_code == "NPTTL"
    assert all(u["project_code"] == "NPTTL" for u in out["units"])
    out2 = await _run({"bedrooms": 2})
    assert isinstance(out2, dict) and out2["counts"]["total"] == 3


async def test_region_dropped_when_in_project(monkeypatch):
    # Dự án đã chốt thì khu vực do dự án quyết định — giữ region chỉ tạo cơ hội
    # 0-row oan (dự án ghi region khác lời khách nói).
    prov = _install(monkeypatch, _BED_UNITS)
    await _run({"scope": "in_project", "project_code": "NPTTL", "region": "Đà Nẵng"})
    assert prov.queries[0].region == ""
    prov2 = _install(monkeypatch, _BED_UNITS)
    await _run({"scope": "all_projects", "region": "Hưng Yên"})
    assert prov2.queries[0].region == "Hưng Yên"


# ── instruction chốt lượt ────────────────────────────────────────────────────


async def test_in_project_payload_carries_next_step_instruction(area_provider):
    # Bug thật (PK-05 2026-09-04): thiếu instruction tổng nên model tự chốt bằng
    # "muốn xem thêm hình ảnh hoặc mặt bằng không ạ?" — hỏi xin phép, và chào mời
    # thứ dữ liệu căn không có.
    out = await _run({"scope": "in_project", "project_code": "SLC"})
    ins = out["instruction"]
    assert "đặt lịch" in ins
    assert "hình ảnh" in ins and "KHÔNG" in ins
    assert not ins.rstrip().endswith("?")


async def test_all_projects_instruction_presents_without_permission_asking(monkeypatch):
    _install(monkeypatch, _BED_UNITS)
    out = await _run({"scope": "all_projects", "bedrooms": 2}, state=_state(), customer=_customer())
    assert "KHÔNG hỏi xin phép" in out["instruction"]
    assert not out["instruction"].rstrip().endswith("?")


# ── max_price headroom + nhóm upsell (grouped envelope cả hai scope) ─────────

_PRICED = [
    _unit("A-01", 75.0, 2_900_000_000),
    _unit("A-02", 75.0, 3_200_000_000),
    _unit("A-03", 75.0, 4_000_000_000),
]


async def test_max_price_headroom_widens_filter_and_groups_over_budget(monkeypatch):
    prov = _install(monkeypatch, _PRICED)
    # Khách đưa 3 tỷ → filter nới 3.5 tỷ: A-01 trong ngân sách, A-02 vượt nhưng
    # trong khoảng nới → sang NHÓM upsell_units, A-03 vượt khoảng nới → loại.
    out = await _run({"scope": "in_project", "project_code": "SLC", "max_price": 3_000_000_000})
    # 12% của 3 tỷ = 360tr < sàn 500tr → biên nới giữ 500tr ở dải này.
    assert prov.queries[0].max_price_vnd == 3_000_000_000 + 500_000_000
    assert [u["unit_code"] for u in out["units"]] == ["A-01"]
    assert "over_budget" not in out["units"][0]
    assert [u["unit_code"] for u in out["upsell_units"]] == ["A-02"]
    up = out["upsell_units"][0]
    assert up["over_budget"] is True
    assert up["price_delta_pct"] == 7  # (3.2-3.0)/3.0 ≈ 6.7 → 7
    assert "instruction" not in up  # pitch nằm ở mức nhóm, không lặp từng căn
    assert "nâng ngân sách" in out["upsell_instruction"] and "~7%" in out["upsell_instruction"]
    assert not out["upsell_instruction"].rstrip().endswith("?")


async def test_budget_max_accepted_as_max_price_alias(monkeypatch):
    # Tên cũ của recommend_units — config/eval cũ còn chở nó; nhận im lặng.
    prov = _install(monkeypatch, _PRICED)
    await _run({"scope": "in_project", "project_code": "SLC", "budget_max": 3_000_000_000})
    assert prov.queries[0].max_price_vnd == 3_500_000_000


async def test_pct_headroom_on_large_budget(area_provider):
    # Ngân sách lớn: biên nới theo 12%, không kẹt ở 500tr tuyệt đối.
    await _run({"scope": "in_project", "project_code": "SLC", "max_price": 10_000_000_000})
    assert area_provider.queries[0].max_price_vnd == 11_200_000_000


async def test_upsell_pitch_persists_across_calls(monkeypatch):
    _install(monkeypatch, _PRICED)
    st = _state()
    args = {"scope": "in_project", "project_code": "SLC", "max_price": 3_000_000_000}
    first = await _run(args, state=st)
    # 2026-09-04: khách "có căn khác không" → gọi lại tool; guard một-lần cũ làm
    # lời chèo kéo biến mất đúng lượt cần nó — pitch sống ở MỌI lần gọi.
    second = await _run(args, state=st)
    assert "nâng ngân sách" in first["upsell_instruction"]
    assert second["upsell_units"][0]["over_budget"] is True
    assert "nâng ngân sách" in second["upsell_instruction"]


async def test_over_budget_unit_carries_highlights_from_amenities(monkeypatch):
    rich = _unit("A-02", 75.0, 3_200_000_000, amenities="Bể bơi vô cực; Gym; Công viên 5ha; Trường học")
    _install(monkeypatch, [_unit("A-01", 75.0, 2_900_000_000), rich])
    out = await _run({"scope": "in_project", "project_code": "SLC", "max_price": 3_000_000_000})
    up = out["upsell_units"][0]
    assert up["highlights"] == ["Bể bơi vô cực", "Gym", "Công viên 5ha"]
    assert "highlights" not in out["units"][0]


async def test_upsell_group_split_when_within_budget_fills_six(monkeypatch):
    # Bug thật (VINHOMES_GLOBAL_GATE 2026-09-03): kho có ≥6 căn dưới ngân sách
    # → sort trong-ngân-sách-trước + slice [:6] cắt rơi MỌI căn vượt-trong-biên.
    units = [_unit(f"W-{i:02d}", 75.0, 11_900_000_000 - i * 10_000_000, project="NPTTL", bedrooms=2) for i in range(8)]
    units += [
        _unit("U-HI", 75.0, 13_300_000_000, project="NPTTL", bedrooms=2),  # vượt xa hơn
        _unit("U-LO", 75.0, 12_400_000_000, project="NPTTL", bedrooms=2),  # sát ngân sách nhất
    ]
    _install(monkeypatch, units)
    out = await _run(
        {"scope": "all_projects", "bedrooms": 2, "max_price": 12_000_000_000}, state=_state(), customer=_customer()
    )
    assert [u["unit_code"] for u in out["units"]] == ["W-00", "W-01", "W-02", "W-03", "W-04"]
    assert [u["unit_code"] for u in out["upsell_units"]] == ["U-LO"]  # sát ngân sách nhất
    assert "~3%" in out["upsell_instruction"] and "U-LO" in out["upsell_instruction"]
    # counts.total = TỔNG căn khớp thật, không phải số đang hiển thị.
    assert out["counts"]["total"] == 10 and out["counts"]["shown"] == 6


async def test_no_upsell_group_when_no_over_budget_candidates(monkeypatch):
    units = [_unit(f"W-{i:02d}", 75.0, 11_000_000_000 - i * 10_000_000, project="NPTTL", bedrooms=2) for i in range(8)]
    _install(monkeypatch, units)
    out = await _run(
        {"scope": "all_projects", "bedrooms": 2, "max_price": 12_000_000_000}, state=_state(), customer=_customer()
    )
    assert [u["unit_code"] for u in out["units"]] == [f"W-{i:02d}" for i in range(6)]
    assert "upsell_units" not in out and "upsell_instruction" not in out


async def test_far_below_budget_within_capped_at_two_rest_upsell(monkeypatch):
    # Khách hỏi 10 tỷ mà kho within toàn căn 4-5 tỷ (xa tầm — dưới 75% ngân
    # sách): chỉ giữ 2 căn within sát giá nhất, slot còn lại nhường upsell.
    units = [_unit(f"F-{i:02d}", 75.0, 5_000_000_000 - i * 100_000_000, project="NPTTL", bedrooms=2) for i in range(8)]
    units += [
        _unit(f"U-{i:02d}", 75.0, 10_200_000_000 + i * 200_000_000, project="NPTTL", bedrooms=2) for i in range(4)
    ]
    _install(monkeypatch, units)
    out = await _run(
        {"scope": "all_projects", "bedrooms": 2, "max_price": 10_000_000_000}, state=_state(), customer=_customer()
    )
    assert [u["unit_code"] for u in out["units"]] == ["F-00", "F-01"]
    assert [u["unit_code"] for u in out["upsell_units"]] == ["U-00", "U-01", "U-02", "U-03"]
    assert "nâng ngân sách" in out["upsell_instruction"]


async def test_units_near_budget_outrank_much_cheaper_ones(monkeypatch):
    # Bug thật (2026-09-04, dungnd): căn sát ngân sách (vượt nhẹ trong biên)
    # không bao giờ bị căn rẻ-xa-tầm đè khỏi top-6.
    cheap = [_unit(f"CHEAP-{i}", 75.0, 3_000_000_000 + i * 200_000_000, project="NPTTL", bedrooms=2) for i in range(6)]
    near = [
        _unit("NEAR-01", 75.0, 9_600_000_000, project="NPTTL", bedrooms=2),
        _unit("NEAR-02", 75.0, 9_900_000_000, project="NPTTL", bedrooms=2),
    ]
    _install(monkeypatch, near + cheap)
    out = await _run({"scope": "all_projects", "max_price": 9_500_000_000}, state=_state(), customer=_customer())
    assert [u["unit_code"] for u in out["upsell_units"]] == ["NEAR-01", "NEAR-02"]
    codes = [u["unit_code"] for u in out["units"]]
    assert codes == ["CHEAP-5", "CHEAP-4"] and "CHEAP-0" not in codes


async def test_no_units_in_budget_instruction_presents_upsell(monkeypatch):
    _install(monkeypatch, [_unit("A-02", 75.0, 3_200_000_000)])
    out = await _run({"scope": "in_project", "project_code": "SLC", "max_price": 3_000_000_000})
    assert out["units"] == [] and [u["unit_code"] for u in out["upsell_units"]] == ["A-02"]
    assert "vượt nhẹ" in out["instruction"] and "KHÔNG hỏi xin phép" in out["instruction"]


# ── paging (index/has_more/next_index) ───────────────────────────────────────


async def test_paging_envelope_and_second_page(area_provider):
    # 7 căn, trang 6 → trang đầu 6 căn + has_more, trang 2 là căn còn lại.
    first = await _run({"scope": "in_project", "project_code": "SLC"})
    assert first["counts"]["shown"] == 6 and first["counts"]["total"] == 7
    assert first["index"] == 0 and first["has_more"] is True and first["next_index"] == 6
    assert "index" in first["instruction"]  # instruction chở cần gạt lật trang
    second = await _run({"scope": "in_project", "project_code": "SLC", "index": 6})
    assert second["counts"]["shown"] == 1 and second["counts"]["total"] == 7 and second["has_more"] is False
    assert "next_index" not in second
    codes1 = {u["unit_code"] for u in first["units"]}
    codes2 = {u["unit_code"] for u in second["units"]}
    assert not codes1 & codes2 and len(codes1 | codes2) == 7


async def test_paging_past_end_reports_exhausted_not_escalate(area_provider):
    out = await _run({"scope": "in_project", "project_code": "SLC", "index": 20})
    assert out != base.ESCALATE_SIGNAL
    assert out["counts"]["shown"] == 0 and out["counts"]["total"] == 7 and out["has_more"] is False
    assert "hết" in out["instruction"] and "nới" in out["instruction"]
    assert not out["instruction"].rstrip().endswith("?")


async def test_paging_second_page_returns_next_units_with_upsell(monkeypatch):
    units = [_unit(f"W-{i:02d}", 75.0, 11_900_000_000 - i * 10_000_000, project="NPTTL", bedrooms=2) for i in range(8)]
    units += [
        _unit("U-HI", 75.0, 13_300_000_000, project="NPTTL", bedrooms=2),
        _unit("U-LO", 75.0, 12_400_000_000, project="NPTTL", bedrooms=2),
    ]
    _install(monkeypatch, units)
    st = _state()
    args = {"scope": "all_projects", "bedrooms": 2, "max_price": 12_000_000_000}
    first = await _run(args, state=st, customer=_customer())
    assert first["index"] == 0 and first["has_more"] is True and first["next_index"] == 6
    second = await _run({**args, "index": 6}, state=st, customer=_customer())
    assert [u["unit_code"] for u in second["units"]] == ["W-05", "W-06", "W-07"]
    assert [u["unit_code"] for u in second["upsell_units"]] == ["U-HI"]
    assert second["has_more"] is False and "next_index" not in second
    # Trang 2 vẫn chèo kéo — khách lật trang là lúc cần pitch nhất.
    assert "nâng ngân sách" in second["upsell_instruction"]
    page1 = {u["unit_code"] for u in first["units"] + first["upsell_units"]}
    page2 = {u["unit_code"] for u in second["units"] + second["upsell_units"]}
    assert not page1 & page2


# ── diện tích: "tầm X" = dải ±20% + fallback off-target ─────────────────────


async def test_area_m2_becomes_a_band_around_target(area_provider):
    out = await _run({"scope": "in_project", "project_code": "SLC", "area_m2": 120})
    q = area_provider.queries[0]
    assert (q.min_area_built_m2, q.max_area_built_m2) == (96.0, 144.0)
    # nearest to 120 first: 118 (2), 125 (5), 98 (22)
    assert [u["unit_code"] for u in out["units"]] == ["U-118", "U-125", "U-98"]
    assert out["counts"]["shown"] == 3
    assert "note" not in out
    assert all("instruction" not in u for u in out["units"])


async def test_explicit_min_or_max_overrides_band_edge(area_provider):
    await _run({"scope": "in_project", "project_code": "SLC", "area_m2": 120, "min_area": 110})
    q = area_provider.queries[0]
    assert (q.min_area_built_m2, q.max_area_built_m2) == (110.0, 144.0)


async def test_min_area_alone_is_an_open_ended_floor(area_provider):
    out = await _run({"scope": "in_project", "project_code": "SLC", "min_area": 120})
    q = area_provider.queries[0]
    assert (q.min_area_built_m2, q.max_area_built_m2) == (120.0, 0.0)
    assert {u["unit_code"] for u in out["units"]} == {"U-125", "U-150", "U-300"}


async def test_max_area_alone_is_a_ceiling(area_provider):
    out = await _run({"scope": "in_project", "project_code": "SLC", "max_area": 80})
    q = area_provider.queries[0]
    assert (q.min_area_built_m2, q.max_area_built_m2) == (0.0, 80.0)
    assert {u["unit_code"] for u in out["units"]} == {"U-46", "U-75"}


async def test_empty_band_falls_back_to_nearest_units_with_note(monkeypatch):
    fake = _install(monkeypatch, [_unit("U-46", 46.0), _unit("U-300", 300.0), _unit("U-200", 200.0)])
    out = await _run({"scope": "in_project", "project_code": "SLC", "area_m2": 120})
    # 1st query = band, 2nd = same query with the area bounds dropped
    assert len(fake.queries) == 2
    assert (fake.queries[0].min_area_built_m2, fake.queries[0].max_area_built_m2) == (96.0, 144.0)
    assert (fake.queries[1].min_area_built_m2, fake.queries[1].max_area_built_m2) == (0.0, 0.0)
    assert fake.queries[1].project_code == "SLC"
    assert out["note"] == "no_units_in_area_band"
    assert out["area_band"] == {"target_m2": 120.0, "min_m2": 96.0, "max_m2": 144.0}
    # nearest first: 46 (74 away), 200 (80 away), 300 (180 away); all labelled off-target
    assert [u["unit_code"] for u in out["units"]] == ["U-46", "U-200", "U-300"]
    assert all(u["instruction"] == pi._OFF_AREA_UNIT_INSTRUCTION for u in out["units"])


async def test_fallback_caps_to_nearest_few(monkeypatch):
    many = [_unit(f"U-{a}", float(a)) for a in (10, 20, 30, 40, 50, 60, 70, 80, 400)]
    _install(monkeypatch, many)
    out = await _run({"scope": "in_project", "project_code": "SLC", "area_m2": 120})
    assert out["counts"]["shown"] == pi._MAX_OFF_AREA_UNITS
    assert [u["unit_code"] for u in out["units"]][:3] == ["U-80", "U-70", "U-60"]


async def test_empty_band_and_empty_fallback_escalates(monkeypatch):
    _install(monkeypatch, [], down=True)
    assert await _run({"scope": "in_project", "project_code": "SLC", "area_m2": 120}) == base.ESCALATE_SIGNAL


async def test_explicit_floor_with_no_match_still_escalates(area_provider):
    # Only the "tầm X" band gets the nearest-units fallback; an explicit
    # "từ 500 m² trở lên" with nothing above it is a genuine miss.
    assert await _run({"scope": "in_project", "project_code": "SLC", "min_area": 500}) == base.ESCALATE_SIGNAL
    assert len(area_provider.queries) == 1


async def test_area_args_tolerate_strings_and_garbage(area_provider):
    await _run({"scope": "in_project", "project_code": "SLC", "area_m2": "120", "min_area": "abc"})
    q = area_provider.queries[0]
    assert (q.min_area_built_m2, q.max_area_built_m2) == (96.0, 144.0)


# ── phong thủy (soft rank, cả hai scope) ─────────────────────────────────────


async def test_no_feng_shui_signal_ranks_by_price_desc(monkeypatch, feng_shui_on):
    _install(monkeypatch, _BED_UNITS)
    out = await _run({"scope": "all_projects", "bedrooms": 2}, state=_state(), customer=_customer())
    assert "feng_shui" not in out
    prices = [u["price_vnd"] for u in out["units"]]
    assert prices == sorted(prices, reverse=True)  # giá GIẢM dần khi không có tín hiệu
    assert out["counts"]["feng_shui_match"] == 0


async def test_birth_year_with_profile_gender_bat_trach(monkeypatch, feng_shui_on):
    _install(monkeypatch, _BED_UNITS)
    # 1990 male -> Khảm (Đông Tứ Mệnh): {Bắc, Nam, Đông, Đông Nam}
    out = await _run(
        {"scope": "all_projects", "bedrooms": 2, "birth_year": 1990}, state=_state(), customer=_customer("M")
    )
    assert out["feng_shui"]["method"] == "bat_trach"
    assert out["feng_shui"]["cung_phi"] == "Khảm"
    # A-01 (Đông Nam) matches -> ranked FIRST, labelled
    assert out["units"][0]["unit_code"] == "A-01"
    assert out["units"][0]["feng_shui_match"] is True
    assert out["counts"]["feng_shui_match"] == 1


async def test_feng_shui_ranks_inside_a_project_too(monkeypatch, feng_shui_on):
    # Hành vi MỚI của merge: "căn 2 ngủ nào hợp tuổi em trong dự án X" — trước
    # đây search_units không có phong thủy, khách bị ép đi đường xuyên dự án.
    _install(monkeypatch, _BED_UNITS)
    out = await _run(
        {"scope": "in_project", "project_code": "NPTTL", "bedrooms": 2, "birth_year": 1990},
        state=_state(),
        customer=_customer("M"),
    )
    assert out["feng_shui"]["cung_phi"] == "Khảm"
    # A-01 (Đông Nam, hợp hướng) đứng trước A-02 (Tây Bắc) dù giá thấp hơn.
    assert [u["unit_code"] for u in out["units"]] == ["A-01", "A-02"]
    assert out["units"][0]["feng_shui_match"] is True


async def test_zodiac_only_guard_asks_twice_then_falls_back(monkeypatch, feng_shui_on):
    _install(monkeypatch, _BED_UNITS)
    st = _state()
    for _ in range(2):
        out = await _run({"scope": "all_projects", "zodiac": "ti"}, state=st, customer=_customer())
        assert out["needs_info"] is True and "năm sinh" in out["message"]
    assert st.scratchpad["fengshui_guard_attempts"] == 2
    # 3rd call: guard exhausted -> địa chi estimate applied (Tị -> Hỏa), computes
    out = await _run({"scope": "all_projects", "zodiac": "ti"}, state=st, customer=_customer())
    assert "needs_info" not in out
    assert out["feng_shui"]["method"] == "dia_chi" and out["feng_shui"]["menh"] == "Hỏa"


async def test_birth_year_resets_guard_counter(monkeypatch, feng_shui_on):
    _install(monkeypatch, _BED_UNITS)
    st = _state()
    st.scratchpad["fengshui_guard_attempts"] = 1
    await _run({"scope": "all_projects", "birth_year": 1990}, state=st, customer=_customer("M"))
    assert st.scratchpad["fengshui_guard_attempts"] == 0


async def test_note_when_feng_shui_applied_but_zero_match(monkeypatch, feng_shui_on):
    _install(monkeypatch, _BED_UNITS)
    # menh Kim -> {Tây, Tây Bắc, Tây Nam, Đông Bắc}. 3PN: chỉ A-03 (Nam) -> no match.
    out = await _run({"scope": "all_projects", "bedrooms": 3, "menh": "kim"}, state=_state(), customer=_customer())
    assert out["counts"]["feng_shui_match"] == 0
    assert "note" in out and "hợp hướng" in out["note"]


async def test_feng_shui_params_ignored_when_ranker_disabled(monkeypatch):
    from noble_agent.tenant import loader

    monkeypatch.setattr(loader, "get_tenant_context", lambda: SimpleNamespace(rankers=frozenset()))
    _install(monkeypatch, _BED_UNITS)
    out = await _run(
        {"scope": "all_projects", "bedrooms": 2, "birth_year": 1990}, state=_state(), customer=_customer("M")
    )
    assert "feng_shui" not in out  # tenant tắt ranker → tín hiệu bị bỏ qua


# ── giá thiếu / chuẩn hoá đơn vị / escalate / state ──────────────────────────


async def test_budget_in_ty_units_normalized_to_vnd(monkeypatch):
    prov = _install(monkeypatch, _BED_UNITS)
    # LLM lỡ truyền đơn vị tỷ (schema yêu cầu VNĐ thực) → normalizer quy đổi.
    out = await _run({"scope": "all_projects", "bedrooms": 2, "max_price": 2.8}, state=_state(), customer=_customer())
    assert prov.last_query.max_price_vnd == 2_800_000_000 + 500_000_000
    assert out["criteria"]["budget_max_vnd"] == 2_800_000_000


async def test_no_budget_no_per_unit_instruction(monkeypatch):
    _install(monkeypatch, _BED_UNITS)
    out = await _run({"scope": "all_projects", "bedrooms": 2}, state=_state(), customer=_customer())
    assert all("instruction" not in u for u in out["units"])


async def test_zero_price_units_excluded_under_budget_filter(monkeypatch):
    # Căn price_vnd=0 (chưa có giá) KHÔNG được coi là "rẻ nhất trong ngân sách"
    # — bug thật trên tenant eco_green: 6 slot toàn căn giá 0.
    units = _BED_UNITS + [
        _unit("Z-01", 75.0, 0, project="NPTTL", bedrooms=2),
        _unit("Z-02", 75.0, None, project="NPTTL", bedrooms=2),
    ]
    _install(monkeypatch, units)
    out = await _run({"scope": "all_projects", "bedrooms": 2, "max_price": 20}, state=_state(), customer=_customer())
    codes = [u["unit_code"] for u in out["units"]]
    assert "Z-01" not in codes and "Z-02" not in codes
    assert codes == ["A-02", "A-01", "B-01"]  # còn lại sort giá giảm dần


async def test_zero_price_units_last_with_note_when_no_budget(monkeypatch):
    units = [_unit("Z-01", 75.0, 0, project="NPTTL", bedrooms=2)] + _BED_UNITS
    _install(monkeypatch, units)
    out = await _run({"scope": "all_projects", "bedrooms": 2}, state=_state(), customer=_customer())
    last = out["units"][-1]
    assert last["unit_code"] == "Z-01"
    assert last["price_vnd"] is None
    assert "chưa có giá" in last["instruction"]


async def test_backend_down_escalates(monkeypatch):
    _install(monkeypatch, [], down=True)
    out = await _run({"scope": "all_projects", "bedrooms": 2}, state=_state(), customer=_customer())
    assert out == base.ESCALATE_SIGNAL


async def test_records_listed_project_codes_as_find_project_prior(monkeypatch):
    _install(monkeypatch, _BED_UNITS)
    st = _state()
    await _run({"scope": "all_projects", "bedrooms": 2}, state=st, customer=_customer())
    # distinct codes in the order the units were presented (price desc)
    assert st.scratchpad["recent_projects"] == ["NPTTL", "NCR"]
