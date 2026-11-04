from dataclasses import FrozenInstanceError

import pytest

from noble_agent.data.providers import base


def test_escalate_signal_value():
    assert base.ESCALATE_SIGNAL == "Thông tin đã được chuyển đến chuyên viên tư vấn"


def test_capability_members():
    # recommend/inventory gộp vào unit_search / analyze_projects (merge 2026-09-07)
    assert {c.value for c in base.Capability} == {"listing", "overview", "unit_search"}


def test_no_extras_or_pricing_plumbing():
    assert not hasattr(base, "ExtraFieldSpec")
    assert not hasattr(base, "ToolParamSpec")
    assert not hasattr(base, "EXTRA_UNIT_SUFFIX")
    assert not hasattr(base, "UnitTypePricing")
    assert not hasattr(base, "PricingTable")


_MINIMAL_UNIT = dict(
    project_code="MCP", project_name="Masteri Centre Point", zone_code=None, unit_code="A-1",
    product_type="2PN", bedrooms=2, block="S3", floor=6, num_floors=None, direction="Đông",
    area_built_m2=75.0, area_wall_m2=80.0, area_land_m2=None, price_vnd=5_000_000_000,
    price_per_m2_vnd=None, sale_status="available", image_url=None,
)


def test_unit_dto_is_frozen_and_typed():
    u = base.Unit(**_MINIMAL_UNIT)
    assert u.price_vnd == 5_000_000_000
    with pytest.raises(FrozenInstanceError):
        u.price_vnd = 1  # type: ignore[misc]


def test_query_defaults():
    q = base.UnitQuery(project_code="MCP")
    assert q.sale_status == "available" and q.max_price_vnd == 0
    # union recommend → search (merge 2026-09-07): mặc định không lọc
    assert q.bedrooms == 0 and q.region == ""
    assert not hasattr(base, "RecommendQuery")
    assert not hasattr(base, "UnitRecommendation")


class FakeProvider:
    """Minimal in-memory provider for tool tests. Declares all capabilities."""

    name = "fake"
    capabilities = frozenset(base.Capability)

    def __init__(self, *, projects=None, units=None):
        self._projects = projects or []   # list[ProjectRegistryRow]
        self._units = units or []         # list[base.Unit]

    async def list_projects(self, *, region: str = ""):
        subs = [base.ProjectSummary(p.code, p.name, p.region, (p.type,)) for p in self._projects]
        if region:
            subs = [s for s in subs if region == s.region]
            if not subs:
                return base.ProjectList(0, [], region=region, note="none")
            return base.ProjectList(len(subs), subs, region=region)
        return base.ProjectList(len(subs), subs)

    async def get_overview(self, project_code):
        for p in self._projects:
            if p.code == project_code:
                return base.ProjectOverview(code=p.code, name=p.name, region=p.region)
        return None

    async def search_units(self, query):
        # project_code rỗng = xuyên tất cả dự án (contract thật của pg_kb)
        hits = [u for u in self._units if not query.project_code or u.project_code == query.project_code]
        if query.bedrooms:
            hits = [u for u in hits if u.bedrooms == query.bedrooms]
        return hits or None

    async def discover_projects(self, query):
        subs = list(self._projects)
        if query.region:
            subs = [p for p in subs if query.region == p.region]
        total = len(subs)
        sliced = subs[query.offset : query.offset + query.limit]
        return base.ProjectDiscovery(
            total=total,
            projects=[base.ProjectSummary(p.code, p.name, p.region, (p.type,)) for p in sliced]
        )

    async def get_document(self, project_code, query=""):
        return None

    async def warm(self): ...
    async def warm_if_stale(self, ttl_sec): ...
    def registry_rows(self): return list(self._projects)
    def cached_codes(self): return [p.code for p in self._projects]
    def code_to_name(self): return {p.code: p.name for p in self._projects}


def test_fake_provider_satisfies_protocol():
    assert isinstance(FakeProvider(), base.DataProvider)


def test_inventory_dtos_removed():
    # check_inventory gộp vào analyze_projects (merge 2026-09-07) — DTO đi theo.
    for gone in ("InventorySummary", "InventoryByType", "InventoryByDirection"):
        assert not hasattr(base, gone), gone


def test_project_overview_optional_fields_default_none():
    ov = base.ProjectOverview(code="MCP", name="X")
    assert ov.investor is None and ov.sale_phase is None and ov.link_360 is None


def test_document_dto():
    d = base.Document(project_code="NPLB", title="CSBH Q3", body="Tiến độ...", file_url="acme/csbh.pdf")
    assert d.file_url == "acme/csbh.pdf"
    d2 = base.Document(project_code="NPLB", title="X", body="Y")
    assert d2.file_url is None


def test_project_summary_has_optional_discovery_fields():
    s = base.ProjectSummary("NCLB", "Noble Crystal", "Long Biên", ("chung_cu",))
    assert s.investor == ""
    assert s.price_from_vnd is None
    assert s.sale_phase == ""
    s2 = base.ProjectSummary(
        "X", "Y", "Z", ("chung_cu",), investor="CĐT", price_from_vnd=5_000_000_000, sale_phase="dang_ban"
    )
    assert (s2.investor, s2.price_from_vnd, s2.sale_phase) == ("CĐT", 5_000_000_000, "dang_ban")


def test_discover_dtos():
    q = base.DiscoverQuery(region="Hà Nội", product_type="chung_cu", sale_phase="dang_ban", offset=5, limit=5)
    assert (q.region, q.product_type, q.sale_phase, q.offset, q.limit) == ("Hà Nội", "chung_cu", "dang_ban", 5, 5)
    d = base.ProjectDiscovery(total=213, projects=[])
    assert d.total == 213 and d.projects == []


def test_unit_query_new_fields_and_defaults():
    q = base.UnitQuery(project_code="MCP")
    assert q.product_type == "" and q.block == "" and q.min_area_built_m2 == 0.0
    assert not hasattr(q, "custom_params")
    q2 = base.UnitQuery(project_code="MCP", product_type="2PN", block="S3", min_area_built_m2=70.0)
    assert (q2.product_type, q2.block, q2.min_area_built_m2) == ("2PN", "S3", 70.0)
    # union recommend → search (merge 2026-09-07)
    q3 = base.UnitQuery(project_code="", bedrooms=2, region="Tây Hồ")
    assert (q3.bedrooms, q3.region) == (2, "Tây Hồ")
