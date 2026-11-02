"""kb_search scope: only scope to a project when the LLM passes project_filter
explicitly; an omitted filter searches ALL projects (so comparison / multi-project
queries are not silently narrowed to customer.project_interest)."""

from __future__ import annotations

from noble_agent.agent.tools import noble_search


class _Customer:
    def __init__(self, project_interest=""):
        self.project_interest = project_interest


class _Dispatcher:
    def __init__(self, project_interest=""):
        self.customer = _Customer(project_interest)
        self.dirty = False

    def mark_customer_dirty(self):
        self.dirty = True


class _RAG:
    def __init__(self):
        self.called_with = None

    async def search(self, query, project_filter):
        self.called_with = project_filter
        return "CTX"


async def _run(monkeypatch, dispatcher, args):
    from noble_agent.config import get_settings

    monkeypatch.setattr(get_settings(), "search_backend", "rag", raising=False)
    rag = _RAG()
    out = await noble_search.run(rag, dispatcher, args)
    return rag, out


async def test_omitted_filter_searches_all_even_with_sticky_project(monkeypatch):
    # customer already pinned to VRI, but the LLM omits project_filter
    disp = _Dispatcher(project_interest="VRI")
    rag, out = await _run(monkeypatch, disp, {"query": "So sánh VRI và VOP2"})
    assert rag.called_with is None  # NOT scoped to VRI → searches all projects
    assert out == "CTX"
    assert disp.customer.project_interest == "VRI"  # sticky value untouched


async def test_explicit_filter_scopes_and_sets_interest(monkeypatch):
    # Use a canonical catalog code so catalog.normalize() validates it without a
    # warmed DB roster (pg_kb carries no bundled fallback in unit tests).
    disp = _Dispatcher(project_interest="")
    rag, _ = await _run(monkeypatch, disp, {"query": "giá", "project_filter": "NCLB"})
    assert rag.called_with == "NCLB"  # explicit scope honoured
    assert disp.customer.project_interest == "NCLB"  # remembered for later turns
    assert disp.dirty is True


async def test_empty_string_filter_is_treated_as_omitted(monkeypatch):
    disp = _Dispatcher(project_interest="VRI")
    rag, _ = await _run(monkeypatch, disp, {"query": "q", "project_filter": ""})
    assert rag.called_with is None  # "" is falsy → searches all, not scoped to VRI


# ─── Sticky project suy TỪ KẾT QUẢ khi LLM không truyền filter ────────────────
#
# `e21c2d9` cho kb_search đi thẳng không cần find_project (tiết kiệm ~1.3s) và vô
# tình cắt đường lấy project_code: nhánh sticky cũ chỉ chạy khi CÓ project_filter,
# nên "vị trí ocean park 3" trả lời đúng mà project_interest rỗng, rồi send_media
# trả missing_project_code và mô hình đi hỏi khách thay vì gửi ảnh. Đo được với cả
# Gemini 2.5 Flash và qwen3.7-flash — lỗi cấu trúc, không phải mô hình.


class _RAGDuAn:
    """RAG nhận `du_an` — bồn chứa mã dự án suy từ hits."""

    def __init__(self, tra_ve=()):
        self.tra_ve = list(tra_ve)
        self.called_with = None

    async def search(self, query, project_filter, dinh_kem=None, du_an=None):
        self.called_with = project_filter
        if du_an is not None:
            du_an.extend(self.tra_ve)
        return "CTX"


async def _run_du_an(monkeypatch, dispatcher, args, tra_ve=()):
    from noble_agent.config import get_settings

    monkeypatch.setattr(get_settings(), "search_backend", "rag", raising=False)
    rag = _RAGDuAn(tra_ve)
    out = await noble_search.run(rag, dispatcher, args)
    return rag, out


async def test_khong_filter_ma_ket_qua_mot_du_an_thi_ghim_sticky(monkeypatch):
    disp = _Dispatcher()
    await _run_du_an(monkeypatch, disp, {"query": "vị trí ocean park 3"}, tra_ve=["VINHOMES_OCEAN_PARK_3"])

    assert disp.customer.project_interest == "VINHOMES_OCEAN_PARK_3"
    assert disp.dirty is True


async def test_ket_qua_nhieu_du_an_thi_KHONG_ghim(monkeypatch):
    """Adapter trả rỗng khi hits không đồng nhất; ghim theo cái nào cũng là đoán."""
    disp = _Dispatcher()
    await _run_du_an(monkeypatch, disp, {"query": "so sánh VRI và VOP2"}, tra_ve=[])

    assert disp.customer.project_interest == ""
    assert disp.dirty is False


async def test_khong_ghi_de_khi_da_dung_du_an_do(monkeypatch):
    """Không đánh dấu dirty vô ích — mỗi lần dirty là một lượt dựng lại system prompt."""
    disp = _Dispatcher(project_interest="VOP3")
    await _run_du_an(monkeypatch, disp, {"query": "tiện ích"}, tra_ve=["VOP3"])

    assert disp.customer.project_interest == "VOP3"
    assert disp.dirty is False


async def test_co_filter_thi_sticky_theo_FILTER_khong_theo_ket_qua(monkeypatch):
    """Nhánh cũ vẫn thắng: LLM đã nói rõ phạm vi thì kết quả không được ghi đè nó."""
    disp = _Dispatcher()
    rag, _ = await _run_du_an(monkeypatch, disp, {"query": "giá", "project_filter": "VOP3"}, tra_ve=["MOT_DU_AN_KHAC"])

    assert disp.customer.project_interest != "MOT_DU_AN_KHAC"


async def test_rag_cu_khong_nhan_du_an_van_chay(monkeypatch):
    """Nhánh `except TypeError` giữ tương thích: RAG bản cũ chỉ nhận hai tham số."""
    disp = _Dispatcher()
    rag, out = await _run(monkeypatch, disp, {"query": "vị trí ocean park 3"})

    assert out == "CTX"
    assert disp.customer.project_interest == ""


# ─── Kết quả RỖNG → chỉ đạo trung thực, không trả "" trần ─────────────────────
#
# Mọi backend degrade IM LẶNG về rỗng (CLAUDE.md); "" trần nghĩa là model nhận
# con số không và tự ứng biến — đường ngắn nhất tới bịa số liệu. Chuỗi chỉ đạo
# vẫn là CHUỖI TRẦN (không JSON) nên contract hình-dạng-có-cổng của kb_search
# giữ nguyên.


class _RAGRong:
    async def search(self, query, project_filter):
        return "   "  # backend degrade / không có hit — khoảng trắng cũng là rỗng


def _assert_chi_dao_trung_thuc(out: str) -> None:
    assert "trung thực" in out and "không bịa" in out
    assert not out.lstrip().startswith("{")  # vẫn chuỗi trần, không phải JSON


async def test_ket_qua_rong_tra_chi_dao_trung_thuc(monkeypatch):
    from noble_agent.config import get_settings

    monkeypatch.setattr(get_settings(), "search_backend", "rag", raising=False)
    out = await noble_search.run(_RAGRong(), _Dispatcher(), {"query": "giá NCLB"})
    _assert_chi_dao_trung_thuc(out)


async def test_rag_tat_tra_chi_dao_trung_thuc(monkeypatch):
    from noble_agent.config import get_settings

    monkeypatch.setattr(get_settings(), "search_backend", "rag", raising=False)
    out = await noble_search.run(None, _Dispatcher(), {"query": "giá"})
    _assert_chi_dao_trung_thuc(out)


async def test_backend_empty_tra_chi_dao_trung_thuc(monkeypatch):
    from noble_agent.config import get_settings

    monkeypatch.setattr(get_settings(), "search_backend", "empty", raising=False)
    out = await noble_search.run(None, _Dispatcher(), {"query": "giá"})
    _assert_chi_dao_trung_thuc(out)


async def test_grep_rong_tra_chi_dao_trung_thuc(monkeypatch):
    from noble_agent.agent.rag import grep_search
    from noble_agent.config import get_settings

    monkeypatch.setattr(get_settings(), "search_backend", "grep", raising=False)
    monkeypatch.setattr(grep_search, "search", lambda **_kw: "")
    out = await noble_search.run(None, _Dispatcher(), {"query": "giá"})
    _assert_chi_dao_trung_thuc(out)


async def test_grep_co_ket_qua_van_tra_nguyen_van(monkeypatch):
    from noble_agent.agent.rag import grep_search
    from noble_agent.config import get_settings

    monkeypatch.setattr(get_settings(), "search_backend", "grep", raising=False)
    monkeypatch.setattr(grep_search, "search", lambda **_kw: "FAQ...")
    assert await noble_search.run(None, _Dispatcher(), {"query": "giá"}) == "FAQ..."
