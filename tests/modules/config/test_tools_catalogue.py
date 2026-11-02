"""Sổ kỹ năng phải khớp tập tool agent THỰC SỰ có schema.

`get_project_financial` từng nằm ở đây nhưng agent không có schema nào cho nó —
bật nó là dạy LLM gọi một tool không tồn tại. `get_document` thì ngược lại.
"""

from portal.modules.config.tools import MUOI_HAI_KY_NANG, PHU_THUOC, TEN_KY_NANG

LOI = frozenset({"update_customer", "kb_search", "find_project", "escalate"})
TUY_CHON = frozenset(
    {
        "discover_projects",
        "get_document",
        "search_units",
        "booking",
        "send_media",
        "analyze_projects",
        "tinh_tra_gop",
    }
)


def test_dung_11_ten_va_khop_agent():
    assert TEN_KY_NANG == LOI | TUY_CHON
    assert len(MUOI_HAI_KY_NANG) == 11


def test_get_project_financial_da_bi_bo():
    assert "get_project_financial" not in TEN_KY_NANG
    assert "get_project_financial" not in PHU_THUOC


def test_get_document_phu_thuoc_find_project():
    # schema của nó nhận `project_code` — luật ở docstring PHU_THUOC.
    assert PHU_THUOC["get_document"] == ("find_project",)
