"""`finish_turn`: trả nợ media cuối lượt.

Hai đường đều phụ thuộc việc mô hình chịu gọi tool, mà repo này ghi lại năm lần
rằng nó làm không đều (`MAX_CALLS_PER_TOOL`, `_TOOL_CAP_OVERRIDES`, vòng chốt
`tools=[]`, `MarkdownStripper`, `_auto_escalate`). Cùng lý lẽ `_auto_escalate`:
"prompt nhờ Luna tự gọi, nhưng nó làm không đều".
"""

from __future__ import annotations

import json

import pytest

from noble_agent.agent.tools.dispatcher import ToolDispatcher


class _Callbacks:
    def __init__(self):
        self.done: list[tuple[str, str]] = []

    async def on_tool_start(self, name, args):
        pass

    async def on_tool_done(self, name, result):
        self.done.append((name, result))

    async def on_token(self, tok):
        pass

    async def on_agent_switch(self, agent):
        pass


class _Customer:
    def __init__(self, project_interest=""):
        self.project_interest = project_interest


def _disp(project_interest="", sandbox=False):
    cb = _Callbacks()
    d = ToolDispatcher(
        state=type("S", (), {"history": [], "scratchpad": {}})(),
        customer=_Customer(project_interest),
        rag=None,
        callbacks=cb,
        session_id="sid",
        sandbox=sandbox,
    )
    return d, cb


def _bat_gui(monkeypatch, d, tra_ve='{"ok": true, "items": [{"kind": "image"}], "count": 1}'):
    """Chặn `_exec` để không chạm Qdrant; ghi lại args mà lưới đỡ gửi đi."""
    goi: list[tuple[str, dict]] = []

    async def fake_exec(name, args):
        goi.append((name, dict(args)))
        return tra_ve

    monkeypatch.setattr(d, "_exec", fake_exec)
    return goi


# ─── Suy ý định hình ảnh ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("q", "mong_doi"),
    [
        ("vị trí ocean park 3", "vi_tri"),
        ("dự án nằm ở đâu", "vi_tri"),
        ("cho xem bản đồ", "vi_tri"),
        ("mặt bằng căn 2 ngủ", "mat_bang"),
        # KHÔNG phải yêu cầu xem ảnh — "mặt bằng giá" là mức giá.
        ("mặt bằng giá khu này bao nhiêu", ""),
        ("mặt bằng chung của thị trường", ""),
        # Danh mục mơ hồ cố ý đứng ngoài: "tiến độ thanh toán" rất phổ biến.
        ("tiến độ thanh toán thế nào", ""),
        ("nội thất có sẵn không", ""),
        ("", ""),
    ],
)
def test_suy_y_dinh(q, mong_doi):
    d, _ = _disp()
    assert d._suy_y_dinh_hinh_anh(q) == mong_doi


# ─── Nhánh ①: candidates chưa được chốt ──────────────────────────────────────


async def test_candidates_khong_duoc_chot_thi_gui_ca_ro(monkeypatch):
    """Không có vế này thì mọi yêu cầu ảnh rơi vào fallback kết thúc bằng màn
    hình TRỐNG — tệ hơn hẳn cái luồng hai bước đang sửa."""
    d, cb = _disp(project_interest="VOP3")
    d._ghi_nhan_media("send_media", {"category": "noi_that"}, json.dumps({"note": "category_fallback"}))
    goi = _bat_gui(monkeypatch, d)

    await d.finish_turn()

    assert goi[0][0] == "send_media"
    assert goi[0][1]["_gui_het"] is True
    assert goi[0][1]["category"] == "noi_that"
    assert cb.done[-1][0] == "send_media"


async def test_da_chot_ids_roi_thi_khong_gui_lai(monkeypatch):
    """Lượt gửi thành công phải xoá nợ, không thì khách nhận ảnh hai lần."""
    d, cb = _disp(project_interest="VOP3")
    d._ghi_nhan_media("send_media", {"category": "noi_that"}, json.dumps({"note": "category_fallback"}))
    d._ghi_nhan_media("send_media", {"ids": ["pt-1"]}, json.dumps({"ok": True, "items": [{"kind": "image"}]}))
    goi = _bat_gui(monkeypatch, d)

    await d.finish_turn()

    assert goi == []
    assert cb.done == []


# ─── Nhánh ②: có ý định mà mô hình không gọi ─────────────────────────────────


async def test_y_dinh_vi_tri_ma_khong_goi_send_media_thi_tu_gui(monkeypatch):
    d, cb = _disp(project_interest="VINHOMES_OCEAN_PARK_3")
    d._ghi_nhan_media("kb_search", {"query": "vị trí ocean park 3"}, "ngữ cảnh")
    goi = _bat_gui(monkeypatch, d)

    await d.finish_turn()

    assert goi[0][1]["category"] == "vi_tri"
    assert goi[0][1]["project_code"] == "VINHOMES_OCEAN_PARK_3"


async def test_khong_biet_du_an_thi_khong_gui(monkeypatch):
    """`send_media` cần project_code; không có thì lưới đỡ cũng không đoán."""
    d, cb = _disp(project_interest="")
    d._ghi_nhan_media("kb_search", {"query": "vị trí ocean park 3"}, "ngữ cảnh")
    goi = _bat_gui(monkeypatch, d)

    await d.finish_turn()

    assert goi == []


async def test_mo_hinh_da_gui_roi_thi_luoi_do_im_lang(monkeypatch):
    """Đường chính vẫn là mô hình tự gọi. Bắn thêm ở đây là khách nhận hai thẻ."""
    d, cb = _disp(project_interest="VOP3")
    d._ghi_nhan_media("kb_search", {"query": "vị trí"}, "ngữ cảnh")
    d._ghi_nhan_media("send_media", {"category": "vi_tri"}, json.dumps({"ok": True, "items": [{"kind": "image"}]}))
    goi = _bat_gui(monkeypatch, d)

    await d.finish_turn()

    assert goi == []


async def test_cau_hoi_khong_co_y_dinh_thi_khong_gui(monkeypatch):
    d, cb = _disp(project_interest="VOP3")
    d._ghi_nhan_media("kb_search", {"query": "chính sách thanh toán ra sao"}, "ngữ cảnh")
    goi = _bat_gui(monkeypatch, d)

    await d.finish_turn()

    assert goi == []


# ─── Ranh giới ───────────────────────────────────────────────────────────────


async def test_sandbox_khong_gui_gi(monkeypatch):
    """Lượt ghost của semcache dùng chung session_id thật — gửi ảnh ở đó là gửi
    cho khách một cách ngoài đời, cùng lý lẽ `_auto_escalate` gác `sandbox`."""
    d, cb = _disp(project_interest="VOP3", sandbox=True)
    d._ghi_nhan_media("kb_search", {"query": "vị trí"}, "ngữ cảnh")
    goi = _bat_gui(monkeypatch, d)

    await d.finish_turn()

    assert goi == []


async def test_loi_khi_gui_bu_khong_lam_vo_luot(monkeypatch):
    """Lượt đã trả lời xong; một lưới đỡ hỏng không được biến nó thành lỗi."""
    d, cb = _disp(project_interest="VOP3")
    d._ghi_nhan_media("kb_search", {"query": "vị trí"}, "ngữ cảnh")

    async def no(name, args):
        raise RuntimeError("qdrant chết")

    monkeypatch.setattr(d, "_exec", no)

    await d.finish_turn()  # không được ném

    assert cb.done == []
