"""discover_projects tool: envelope shaping over a fake provider."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

from noble_agent.agent.tools import projects_info
from noble_agent.data.providers import base


class _FakeProvider:
    def __init__(self, total, page):
        self._total, self._page = total, page
        self.last_query = None

    async def discover_projects(self, query):
        self.last_query = query
        return base.ProjectDiscovery(total=self._total, projects=self._page)


def _install(monkeypatch, provider):
    monkeypatch.setattr(projects_info.providers, "get_provider", lambda _s: provider)


def _summ(code):
    return base.ProjectSummary(
        code, f"Dự án {code}", "Hà Nội", ("chung_cu",), investor="CĐT", sale_phase="dang_ban"
    )


async def test_envelope_has_more_and_suggested_narrow(monkeypatch):
    prov = _FakeProvider(total=213, page=[_summ("A"), _summ("B")])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 2})())

    out = json.loads(await projects_info.discover_projects({"region": "Hà Nội", "index": 0}))
    assert out["total"] == 213
    assert out["index"] == 0
    assert out["count"] == 2
    assert out["has_more"] is True
    assert out["next_index"] == 2
    assert [p["code"] for p in out["projects"]] == ["A", "B"]
    # region given → not suggested; budget/product_type/purpose/investor not given → suggested
    assert "region" not in out["suggested_narrow"]
    assert "budget_max" in out["suggested_narrow"]
    # provider received canonical query with limit = page size and offset = index
    assert prov.last_query.limit == 2 and prov.last_query.offset == 0
    assert prov.last_query.region == "Hà Nội"


async def test_envelope_last_page_no_more(monkeypatch):
    prov = _FakeProvider(total=2, page=[_summ("A"), _summ("B")])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())

    out = json.loads(await projects_info.discover_projects({"index": 0}))
    assert out["has_more"] is False
    assert "next_index" not in out


async def test_budget_normalized_to_vnd_with_headroom(monkeypatch):
    prov = _FakeProvider(total=0, page=[])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())

    # Schema asks for real VNĐ, but the LLM sometimes still sends tỷ (5) —
    # both must normalize to the same VNĐ filter, widened by the pct headroom
    # (12% của 5 tỷ = 600tr > sàn 500tr) so slightly over-budget projects still
    # surface (tagged, not dropped).
    await projects_info.discover_projects({"budget_max": 5})
    assert prov.last_query.budget_max_vnd == 5_000_000_000 + 600_000_000

    await projects_info.discover_projects({"budget_max": 5_000_000_000})
    assert prov.last_query.budget_max_vnd == 5_000_000_000 + 600_000_000


async def test_over_budget_project_tagged_with_instruction(monkeypatch):
    in_budget = replace(_summ("A"), price_from_vnd=4_800_000_000)
    over_budget = replace(_summ("B"), price_from_vnd=5_300_000_000)
    prov = _FakeProvider(total=2, page=[in_budget, over_budget])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())

    out = json.loads(await projects_info.discover_projects({"budget_max": 5}))
    by_code = {p["code"]: p for p in out["projects"]}
    assert "instruction" not in by_code["A"]
    assert "over_budget" not in by_code["A"]
    assert by_code["B"]["over_budget"] is True
    assert by_code["B"]["price_delta_pct"] == 6  # (5.3-5.0)/5.0 = 6%
    assert "GIỚI THIỆU LUÔN" in by_code["B"]["instruction"]
    assert not by_code["B"]["instruction"].rstrip().endswith("?")


async def test_over_budget_project_pitch_once_per_session(monkeypatch):
    over = replace(_summ("B"), price_from_vnd=5_300_000_000)
    prov = _FakeProvider(total=1, page=[over])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())
    state = SimpleNamespace(scratchpad={})

    first = json.loads(await projects_info.discover_projects({"budget_max": 5}, state=state))
    assert "instruction" in first["projects"][0]
    second = json.loads(await projects_info.discover_projects({"budget_max": 5}, state=state))
    # Dữ liệu giữ, lời pitch không lặp trong cùng phiên.
    assert second["projects"][0]["over_budget"] is True
    assert "instruction" not in second["projects"][0]


async def test_instruction_script_total_then_gather_close(monkeypatch):
    # Kịch bản chỉnh 2026-09-04 (vòng 2): (1) mở đầu nói TỔNG số dự án, (2) giới
    # thiệu 4-5 dự án nổi bật, (3) chốt tin bằng ĐÚNG MỘT câu khai thác tiêu chí
    # còn thiếu — user thu hẹp khai thác về MỘT tiêu chí ngân sách (region/
    # purpose bỏ khỏi câu gộp). KHÔNG chèo mời xem căn trong cùng tin — hai lời
    # chốt một tin làm câu trả lời máy móc (feedback thật trên /chat).
    prov = _FakeProvider(total=14, page=[_summ("A"), _summ("B")])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())
    out = json.loads(await projects_info.discover_projects({"index": 0}))
    ins = out["instruction"]
    assert "tổng cộng 14 dự án" in ins
    assert "4-5 dự án" in ins
    assert "ngân sách" in ins and "MỘT câu" in ins and "tư vấn" in ins
    assert "mục đích" not in ins  # khai thác đã thu về mỗi ngân sách
    # Không kèm lời mời xem căn — tin này chỉ có một lời chốt.
    assert "hấp dẫn" not in ins
    assert not ins.rstrip().endswith("?")


async def test_instruction_skips_gathering_when_budget_known(monkeypatch):
    prov = _FakeProvider(total=3, page=[_summ("A")])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())
    out = json.loads(await projects_info.discover_projects({"budget_max": 5}))
    ins = out["instruction"]
    assert "MỘT câu" not in ins  # có ngân sách → không còn bước khai thác
    # Không còn gì để hỏi → lời chốt DUY NHẤT là chèo kéo sang quỹ căn.
    assert "tổng cộng 3 dự án" in ins and "hấp dẫn" in ins


async def test_no_budget_given_no_per_project_instruction(monkeypatch):
    prov = _FakeProvider(total=1, page=[replace(_summ("A"), price_from_vnd=9_000_000_000)])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())

    out = json.loads(await projects_info.discover_projects({}))
    assert prov.last_query.budget_max_vnd == 0
    assert "instruction" not in out["projects"][0]


async def test_envelope_empty_page_past_end_not_introduce_instruction(monkeypatch):
    """Regression: paging past total (count==0, total>0) must NOT tell Luna to
    "introduce these projects" over an empty list."""
    prov = _FakeProvider(total=2, page=[])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())

    out = json.loads(await projects_info.discover_projects({"index": 10}))
    assert out["count"] == 0
    assert out["total"] == 2
    assert out["has_more"] is False
    assert out["instruction"] != "Giới thiệu các dự án này cho khách, dẫn dắt chọn 1 dự án để tìm hiểu sâu."


async def test_escalate_on_none(monkeypatch):
    class _Down:
        async def discover_projects(self, q):
            return None

    _install(monkeypatch, _Down())
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())
    out = await projects_info.discover_projects({})
    assert out == base.ESCALATE_SIGNAL


async def test_records_listed_codes_as_find_project_prior(monkeypatch):
    prov = _FakeProvider(total=2, page=[_summ("A"), _summ("B")])
    _install(monkeypatch, prov)
    monkeypatch.setattr(projects_info, "get_settings", lambda: type("S", (), {"discover_page_size": 5})())
    state = SimpleNamespace(scratchpad={})
    await projects_info.discover_projects({"index": 0}, state=state)
    assert state.scratchpad["recent_projects"] == ["A", "B"]


# ── mode overview (nuốt get_project_overview, merge 2026-09-07) ──────────────


class _OverviewProvider:
    def __init__(self, overview):
        self._ov = overview
        self.last_arg = None

    async def get_overview(self, code):
        self.last_arg = code
        return self._ov

    async def discover_projects(self, query):  # pragma: no cover — không được gọi ở mode overview
        raise AssertionError("mode overview không được rơi vào nhánh khám phá")


async def test_project_code_switches_to_overview_mode(monkeypatch):
    ov = base.ProjectOverview(
        code="NCLB", name="Noble Crystal Long Biên", region="Long Biên",
        investor="Noble", sale_phase="dang_ban", overview="Tổng quan...",
    )
    prov = _OverviewProvider(ov)
    _install(monkeypatch, prov)
    out = json.loads(await projects_info.discover_projects({"project_code": "NCLB"}))
    assert out["code"] == "NCLB"
    assert out["name"] == "Noble Crystal Long Biên"
    assert out["region"] == "Long Biên"
    assert out["investor"] == "Noble"
    assert out["sale_phase"] == "dang_ban"
    assert out["overview"] == "Tổng quan..."
    assert prov.last_arg == "NCLB"


async def test_overview_mode_none_escalates(monkeypatch):
    _install(monkeypatch, _OverviewProvider(None))
    assert await projects_info.discover_projects({"project_code": "ZZZ"}) == base.ESCALATE_SIGNAL


def _overview(code="SBR"):
    return base.ProjectOverview(
        code=code, name=f"Dự án {code}", region="TP.HCM",
        investor="Sunshine", sale_phase="sap_mo_ban", overview="Pháp lý: Sổ hồng lâu dài",
    )


async def test_overview_instruction_sends_media_and_probes_criteria(monkeypatch):
    # Tenant có send_media → instruction lệnh gửi ảnh tổng quan (category=tong_quan)
    # + chốt bằng câu khai thác tiêu chí / ngân sách, KHÔNG hỏi xin phép.
    from noble_agent.tenant import loader

    _install(monkeypatch, _OverviewProvider(_overview()))
    monkeypatch.setattr(
        loader, "get_tenant_context",
        lambda: SimpleNamespace(enabled_tools=("discover_projects", "send_media")),
    )
    out = json.loads(await projects_info.discover_projects({"project_code": "SBR"}))
    inst = out["instruction"]
    assert "send_media" in inst and "tong_quan" in inst
    assert "tiêu chí" in inst and "ngân sách" in inst
    assert "KHÔNG hỏi xin phép" in inst  # chặn kiểu 'có muốn em gửi... không ạ?'
    assert out["code"] == "SBR"  # dữ liệu overview vẫn nguyên


async def test_overview_instruction_omits_send_media_when_not_offered(monkeypatch):
    # Tenant KHÔNG bật send_media → instruction không được nhắc tới tool đó,
    # nhưng câu khai thác tiêu chí / ngân sách vẫn phải còn.
    from noble_agent.tenant import loader

    _install(monkeypatch, _OverviewProvider(_overview()))
    monkeypatch.setattr(
        loader, "get_tenant_context",
        lambda: SimpleNamespace(enabled_tools=("discover_projects",)),
    )
    out = json.loads(await projects_info.discover_projects({"project_code": "SBR"}))
    inst = out["instruction"]
    assert "send_media" not in inst
    assert "tiêu chí" in inst and "ngân sách" in inst
