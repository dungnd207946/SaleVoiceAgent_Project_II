"""Cổng HTTP của khối trích hội thoại trên một ca chuyển sale.

Spec: docs/superpowers/specs/2026-09-11-trich-hoi-thoai-ca-chuyen-sale-design.md §4
"""

import asyncpg
import httpx
import pytest

from .conftest import TENANT_KHAC, them_ca, them_luot, them_phien

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ca_co_thoai(pool: asyncpg.Pool, workspace_ops) -> int:
    """Một phiên tám lượt, agent chuyển ở lượt thứ 6."""
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "s-anh", phone="0912448111", ten="Minh Anh")
        for i, (role, noi) in enumerate(
            [
                ("user", "alo em ơi"),
                ("assistant", "dạ em Luna đây ạ"),
                ("user", "còn căn 2PN nào tầm 3 tỷ không em"),
                ("assistant", ""),  # hàng tool_calls — không phải lời nói
                ("tool", '{"units": []}'),  # kết quả tool — không phải lời nói
                ("user", "bao giờ thì bàn giao vậy em"),
                ("assistant", "em chuyển cho chuyên viên ngay ạ"),
                ("user", "ok em"),
            ]
        ):
            await them_luot(conn, "s-anh", i, role=role, content=noi)
        return await them_ca(conn, "s-anh", message_seq=6)


async def test_tra_ve_cac_luot_truoc_moc_chuyen(client_ops: httpx.AsyncClient, ca_co_thoai: int):
    r = await client_ops.get(f"/api/v1/escalations/{ca_co_thoai}/trich")

    assert r.status_code == 200
    assert [x["seq"] for x in r.json()] == [0, 1, 2, 5]


async def test_khong_tra_hang_tool_hay_assistant_rong(client_ops: httpx.AsyncClient, ca_co_thoai: int):
    """Hàng `tool` mang JSON thô; assistant rỗng chỉ là yêu cầu gọi tool. Cả hai
    lọt ra là sale đọc phải ruột kỹ thuật của agent."""
    r = await client_ops.get(f"/api/v1/escalations/{ca_co_thoai}/trich")

    vai = {x["role"] for x in r.json()}
    assert vai == {"user", "assistant"}
    assert all(x["content"] for x in r.json())


async def test_khong_lay_luot_sau_moc_chuyen(client_ops: httpx.AsyncClient, ca_co_thoai: int):
    """`message_seq` chụp lúc tool escalate đang chạy, nên lời hứa 'em chuyển cho
    chuyên viên' CHƯA nằm trong history. Trích đoạn phải dừng ở câu hỏi của khách."""
    r = await client_ops.get(f"/api/v1/escalations/{ca_co_thoai}/trich")

    assert r.json()[-1]["content"] == "bao giờ thì bàn giao vậy em"


async def test_mang_du_truong_cho_transcript(client_ops: httpx.AsyncClient, ca_co_thoai: int):
    """FE dùng lại `components/Transcript.tsx` — nó đọc cả `meta` và `taoLuc`."""
    r = await client_ops.get(f"/api/v1/escalations/{ca_co_thoai}/trich")

    assert set(r.json()[0]) == {"seq", "role", "content", "taoLuc", "meta"}


async def test_ca_chua_co_luot_nao_ra_mang_rong(client_ops: httpx.AsyncClient, pool: asyncpg.Pool, workspace_ops):
    """Transcript ghi fire-and-forget bên agent — rỗng là ca bình thường, không 404."""
    async with pool.acquire() as conn, conn.transaction():
        ca_id = await them_ca(conn, "s-chua-co-luot")

    r = await client_ops.get(f"/api/v1/escalations/{ca_id}/trich")

    assert r.status_code == 200
    assert r.json() == []


async def test_ca_khong_ton_tai_ra_404(client_ops: httpx.AsyncClient, ca_co_thoai: int):
    r = await client_ops.get("/api/v1/escalations/999999/trich")

    assert r.status_code == 404


async def test_ca_cua_tenant_khac_ra_404(client_ops: httpx.AsyncClient, pool: asyncpg.Pool, workspace_ops):
    """404 chứ KHÔNG 403 — cùng lý lẽ `doc_phien`: 403 xác nhận id đó có thật."""
    async with pool.acquire() as conn, conn.transaction():
        ca_id = await them_ca(conn, "s-ho", tenant=TENANT_KHAC)

    r = await client_ops.get(f"/api/v1/escalations/{ca_id}/trich")

    assert r.status_code == 404
