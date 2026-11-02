"""Mọi màn vận hành hiện TÊN dự án, không phải mã.

`conversations.project`/`escalations.project` lưu `project_code`, và với tenant thật
mã đó là một UUID (`DCAC8A12_705D_…`) — bày nguyên cho người trực đọc là bày một khoá
nội bộ. `CaOut` đã có `tenDuAn` từ trước; ba chỗ còn lại chưa.
"""

import asyncpg
import httpx
import pytest

from .conftest import them_ca, them_du_an, them_phien

pytestmark = pytest.mark.asyncio

MA = "DCAC8A12_705D_42C7_BC7C_715DAC569093"
TEN = "Sunshine Crystal River"
MOI_KHACH = {"tu_ngay": "all"}


@pytest.fixture
async def co_du_an(pool: asyncpg.Pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        await them_du_an(conn, MA, TEN)
        await them_phien(conn, "s-td1", phone="0912448111", du_an=MA)
        await them_ca(conn, "s-td1", du_an=MA)


@pytest.fixture
async def du_an_da_xoa(pool: asyncpg.Pool, workspace_ops):
    """Phiên giữ mã của dự án không còn hàng nào — không FK nào chặn chuyện này."""
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "s-td2", phone="0912448222", du_an="DA_DA_XOA")
        await them_ca(conn, "s-td2", du_an="DA_DA_XOA")


async def test_danh_sach_khach_mang_ten_du_an(client_ops: httpx.AsyncClient, co_du_an):
    r = await client_ops.get("/api/v1/convos/khach", params=MOI_KHACH)
    assert r.status_code == 200, r.text

    khach = r.json()["items"][0]
    assert khach["duAn"] == MA
    assert khach["tenDuAn"] == TEN


async def test_danh_sach_phien_mang_ten_du_an(client_ops: httpx.AsyncClient, co_du_an):
    r = await client_ops.get("/api/v1/convos/khach/0912448111/phien")
    assert r.status_code == 200, r.text
    assert r.json()[0]["tenDuAn"] == TEN


async def test_du_an_khong_con_hang_thi_ten_None(client_ops: httpx.AsyncClient, du_an_da_xoa):
    """Hiện lại mã là hành vi ĐÚNG — nói «Chưa rõ» là bỏ mất thông tin duy nhất còn lại."""
    khach = (await client_ops.get("/api/v1/convos/khach", params=MOI_KHACH)).json()["items"][0]
    assert khach["duAn"] == "DA_DA_XOA"
    assert khach["tenDuAn"] is None


async def test_dropdown_ca_mang_ca_ma_va_ten(client_ops: httpx.AsyncClient, co_du_an):
    """Ô lọc dự án ở Hộp thư sale — nhãn phải đọc được, `value` vẫn là mã."""
    r = await client_ops.get("/api/v1/escalations")
    assert r.status_code == 200, r.text
    assert r.json()["duAnCo"] == [{"ma": MA, "ten": TEN}]


async def test_dropdown_du_an_khong_con_hang_van_liet_ke(client_ops: httpx.AsyncClient, du_an_da_xoa):
    duan = (await client_ops.get("/api/v1/escalations")).json()["duAnCo"]
    assert duan == [{"ma": "DA_DA_XOA", "ten": None}]
