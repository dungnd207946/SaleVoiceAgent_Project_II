"""Cắt đoạn hội thoại quanh lúc agent chuyển ca.

Neo của cửa sổ là `escalations.message_seq` — chỉ số tuyệt đối trong
`state.history` phía agent, cùng hệ đánh số với `conversation_messages.seq`.
Spec: docs/superpowers/specs/2026-09-11-trich-hoi-thoai-ca-chuyen-sale-design.md §3
"""

import pytest

from portal.modules.ops import repo

from .conftest import TENANT_KHAC, them_ca, them_luot, them_phien

pytestmark = pytest.mark.asyncio


async def test_lay_dung_cac_luot_truoc_moc_chuyen(conn_ops):
    for i in range(6):
        await them_luot(conn_ops, "s1", i, content=f"lượt {i}")
    await them_ca(conn_ops, "s1", message_seq=4)

    hang = await repo.doc_trich(conn_ops, session_id="s1", truoc_seq=4)

    assert [r["seq"] for r in hang] == [0, 1, 2, 3]


async def test_tra_ve_tang_dan_theo_seq(conn_ops):
    """Câu SQL lấy N lượt CUỐI nên bên trong phải `ORDER BY seq DESC`. Quên đảo
    lại là transcript hiện ngược, và không lỗi nào phát ra."""
    for i in range(4):
        await them_luot(conn_ops, "s1", i, content=f"lượt {i}")

    hang = await repo.doc_trich(conn_ops, session_id="s1", truoc_seq=None)

    assert [r["seq"] for r in hang] == [0, 1, 2, 3]


async def test_chi_lay_sau_luot_cuoi_cua_cua_so(conn_ops):
    """Trần là `TRICH_SO_LUOT`, và phải cắt từ phía GẦN mốc chuyển — sale cần
    bối cảnh ngay trước lúc bí, không phải lời chào đầu cuộc gọi."""
    for i in range(20):
        await them_luot(conn_ops, "s1", i, content=f"lượt {i}")

    hang = await repo.doc_trich(conn_ops, session_id="s1", truoc_seq=15)

    assert [r["seq"] for r in hang] == [9, 10, 11, 12, 13, 14]


async def test_bo_hang_tool_va_assistant_rong(conn_ops):
    """`conversation_messages` giữ cả kết quả tool (JSON) lẫn hàng assistant rỗng
    chỉ mang `tool_calls`. Không lọc thì sale đọc phải tham số của search_units."""
    await them_luot(conn_ops, "s1", 0, role="user", content="còn căn 2PN nào không em")
    await them_luot(conn_ops, "s1", 1, role="assistant", content="")
    await them_luot(conn_ops, "s1", 2, role="tool", content='{"units": []}')
    await them_luot(conn_ops, "s1", 3, role="assistant", content="dạ để em kiểm tra ạ")

    hang = await repo.doc_trich(conn_ops, session_id="s1", truoc_seq=4)

    assert [(r["seq"], r["role"]) for r in hang] == [(0, "user"), (3, "assistant")]


async def test_message_seq_rong_thi_lay_cac_luot_cuoi(conn_ops):
    """Ca cũ không có mốc neo. Có dữ liệu còn hơn một khối rỗng — và với một ca
    ĐÃ chuyển thì mấy lượt cuối gần như luôn là đoạn quanh lúc chuyển."""
    for i in range(9):
        await them_luot(conn_ops, "s1", i, content=f"lượt {i}")
    await them_ca(conn_ops, "s1", message_seq=None)

    hang = await repo.doc_trich(conn_ops, session_id="s1", truoc_seq=None)

    assert [r["seq"] for r in hang] == [3, 4, 5, 6, 7, 8]


async def test_phien_khong_co_luot_nao_tra_mang_rong(conn_ops):
    """Transcript ghi fire-and-forget bên agent: lượt cuối có thể chưa kịp xuống
    Postgres. Rỗng là ca BÌNH THƯỜNG, không phải lỗi."""
    await them_ca(conn_ops, "s-chua-co-luot")

    assert await repo.doc_trich(conn_ops, session_id="s-chua-co-luot", truoc_seq=7) == []


async def test_khong_lay_luot_cua_tenant_khac(conn_ops):
    """Hai tenant có thể trùng `session_id` — nó do bên agent sinh, không có gì
    ép duy nhất toàn hệ."""
    await them_phien(conn_ops, "s1")
    await them_luot(conn_ops, "s1", 0, content="của ta")
    await them_luot(conn_ops, "s1", 1, tenant=TENANT_KHAC, content="của họ")

    hang = await repo.doc_trich(conn_ops, session_id="s1", truoc_seq=None)

    assert [r["content"] for r in hang] == ["của ta"]


async def test_khong_lay_luot_cua_phien_khac(conn_ops):
    await them_luot(conn_ops, "s1", 0, content="phiên một")
    await them_luot(conn_ops, "s2", 0, content="phiên hai")

    hang = await repo.doc_trich(conn_ops, session_id="s1", truoc_seq=None)

    assert [r["content"] for r in hang] == ["phiên một"]


async def test_mang_du_cot_cho_transcript(conn_ops):
    """FE dùng lại `components/Transcript.tsx`, vốn đọc `LuotOut` đầy đủ — thiếu
    một cột là `ValidationError` 500 chứ không phải một ô trống."""
    await them_luot(conn_ops, "s1", 0)

    hang = await repo.doc_trich(conn_ops, session_id="s1", truoc_seq=None)

    # `set(Record)` duyệt GIÁ TRỊ, không phải khoá — phải gọi `.keys()`.
    assert set(hang[0].keys()) >= {"seq", "role", "content", "created_at", "meta"}
