"""Session facts — bộ nhớ XÁC ĐỊNH do code ghi từ kết quả tool (không phải LLM tóm tắt):
căn đã giới thiệu, tài liệu / ảnh đã gửi, lịch đã chốt, đã chuyển chuyên viên; render
thành khối ngữ cảnh ephemeral cùng hồ sơ hiện tại."""

from __future__ import annotations

import json

from noble_agent.agent import session_facts
from noble_agent.storage.models import Customer, State

_UNITS = {
    "units": [
        {
            "unit_code": "A-1203",
            "bedrooms": 2,
            "price_vnd": 3200000000,
            "project_name": "Noble Crystal",
            "project_code": "NCR",
        },
        {
            "unit_code": "B-0805",
            "bedrooms": 3,
            "price_vnd": 4500000000,
            "project_name": "Noble Crystal",
            "project_code": "NCR",
        },
    ]
}


def test_units_from_recommend_and_search_are_remembered_and_rendered():
    st = State()
    session_facts.record(st, "search_units", {}, json.dumps(_UNITS))
    session_facts.record(
        st,
        "search_units",
        {},
        json.dumps(
            {
                "units": [
                    {
                        "unit_code": "C-1501",
                        "bedrooms": 2,
                        "price_vnd": 0,
                        "project_name": "Sunshine Legend",
                        "project_code": "SLC",
                    }
                ]
            }
        ),
    )
    out = session_facts.render(st, Customer())
    assert "A-1203 (2PN, 3,2 tỷ, Noble Crystal)" in out
    assert "B-0805 (3PN, 4,5 tỷ, Noble Crystal)" in out
    assert "C-1501 (2PN, chưa có giá, Sunshine Legend)" in out
    assert json.dumps(st.scratchpad)  # scratchpad phải serialize được (persist Redis)


def test_units_capped_and_deduped_most_recent_first():
    st = State()
    for i in range(12):
        session_facts.record(
            st,
            "search_units",
            {},
            json.dumps(
                {"units": [{"unit_code": f"U-{i}", "bedrooms": 1, "price_vnd": 1000000000, "project_name": "P"}]}
            ),
        )
    session_facts.record(
        st,
        "search_units",
        {},
        json.dumps({"units": [{"unit_code": "U-11", "bedrooms": 1, "price_vnd": 1000000000, "project_name": "P"}]}),
    )
    out = session_facts.render(st, Customer())
    assert out.count("U-") == 8 and "U-11" in out and "U-0" not in out


def test_documents_media_booking_escalate_are_remembered():
    st = State()
    session_facts.record(
        st,
        "get_document",
        {},
        json.dumps(
            {
                "count": 1,
                "documents": [{"title": "CSBH Noble Crystal T8", "body": "...", "file_url": "https://x/y.pdf"}],
            }
        ),
    )
    session_facts.record(
        st,
        "send_media",
        {"category": "tong_quan"},
        json.dumps(
            {
                "ok": True,
                "project_name": "Noble Crystal",
                "caption": "Hình ảnh dự án Noble Crystal",
                "items": [{}, {}],
                "count": 2,
            }
        ),
    )
    session_facts.record(
        st,
        "booking",
        {"action": "schedule"},
        json.dumps(
            {
                "ok": True,
                "appointment_id": "APT12345",
                "project": "NCR",
                "preferred_date": "30/08/2026",
                "preferred_time": "09:00 - 10:00",
            }
        ),
    )
    session_facts.record(
        st, "escalate", {"action": "transfer"}, json.dumps({"status": "transfer_completed", "department": "CVTV"})
    )
    out = session_facts.render(st, Customer())
    assert "CSBH Noble Crystal T8" in out
    assert "Hình ảnh dự án Noble Crystal" in out
    assert "APT12345" in out and "30/08/2026" in out and "09:00 - 10:00" in out
    assert "chuyển chuyên viên" in out.lower()


def test_failed_or_non_json_results_are_ignored():
    st = State()
    session_facts.record(st, "send_media", {}, json.dumps({"ok": False, "items": [], "note": "no_media"}))
    session_facts.record(st, "get_document", {}, "Thông tin đã được chuyển đến chuyên viên tư vấn")
    session_facts.record(st, "booking", {"action": "schedule"}, json.dumps({"ok": False, "needs_info": True}))
    session_facts.record(st, "kb_search", {}, "not json at all")
    assert session_facts.render(st, Customer()) == ""


def test_render_includes_current_profile_and_skips_empty():
    c = Customer(
        name="Hùng",
        gender="M",
        budget="3 tỷ",
        project_interest="NCR",
        preferred_area="Tây Hồ",
        bedroom_count="2PN",
        purpose="ở",
        notes="làm ở Long Biên",
    )
    out = session_facts.render(State(), c)
    assert out.startswith("[Ngữ cảnh hiện tại")
    assert "anh Hùng" in out and "3 tỷ" in out and "NCR" in out and "Tây Hồ" in out and "2PN" in out
    assert "làm ở Long Biên" in out
    assert session_facts.render(State(), Customer()) == ""
    assert "SĐT" not in out  # không lộ trường rỗng


def test_render_shows_project_name_next_to_code_when_index_available(monkeypatch):
    from noble_agent.agent.tools import find_project

    class _Idx:
        def lookup(self, code):
            return (
                type("C", (), {"code": code, "name": "Noble Crystal", "region": "Tây Hồ"})() if code == "NCR" else None
            )

    monkeypatch.setattr(find_project, "get_index", lambda **_: _Idx())
    out = session_facts.render(State(), Customer(project_interest="NCR"))
    assert "Noble Crystal (NCR)" in out
