"""Cổng HTTP của hộp thư sale — hình dạng trả về, phân trang, 404, đường GHI."""

import asyncpg
import httpx
import pytest

from portal.core.avatar import avatar_data_uri

from .conftest import TENANT_KHAC, luc, them_ca, them_du_an, them_luot, them_phien

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def du_lieu(pool: asyncpg.Pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        await them_du_an(conn, "SGI", "Sunshine Green Iconic")
        await them_phien(conn, "s-anh", phone="0912448111", ten="Minh Anh")
        await them_luot(conn, "s-anh", 0)
        await them_ca(conn, "s-anh", du_an="SGI", tao_luc=luc(27))
        await them_ca(conn, "s-bi", tool_thieu="search_units", summary_luc=luc(26), tao_luc=luc(26))
        await them_ca(conn, "s-xong", trang_thai="done", tao_luc=luc(20))
        await them_ca(conn, "s-ho", tenant=TENANT_KHAC)


async def test_danh_sach_mang_du_truong_man_can(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/escalations")

    assert r.status_code == 200
    ca = r.json()["items"][0]
    assert ca["sessionId"] == "s-anh"
    assert ca["phone"] == "0912448111"
    assert ca["ten"] == "Minh Anh"
    assert ca["tenDuAn"] == "Sunshine Green Iconic"
    assert ca["kenh"] is None  # them_phien không đặt source
    assert ca["soLuot"] == 1
    assert ca["trangThai"] == "new"
    assert ca["toolThieuDuLieu"] is None
    # Cùng seed = TÊN với KhachOut/PhienOut — một khách một avatar ở mọi màn.
    assert ca["avatar"] == avatar_data_uri("Minh Anh")


async def test_ca_he_thong_bi_du_lieu_mang_ten_tool(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/escalations")
    bi = next(c for c in r.json()["items"] if c["sessionId"] == "s-bi")

    assert bi["toolThieuDuLieu"] == "search_units"
    assert bi["summaryLuc"] is not None  # bản LLM đã về


async def test_summary_con_ban_tam_thi_summary_luc_rong(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/escalations")
    anh = next(c for c in r.json()["items"] if c["sessionId"] == "s-anh")

    assert anh["summaryLuc"] is None
    assert anh["summary"].startswith("Khách:")


async def test_khong_thay_ca_tenant_khac(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/escalations")

    assert "s-ho" not in r.text
    assert r.json()["tongCa"] == 3


async def test_loc_trang_thai_doi_ca_con_so_dem(client_ops: httpx.AsyncClient, du_lieu):
    """Con số cạnh thanh lọc phải tính trên tập ĐÃ LỌC — nếu không, lọc xong nó
    không đổi và người dùng tưởng bộ lọc hỏng."""
    r = await client_ops.get("/api/v1/escalations", params={"trang_thai": "new"})

    assert r.json()["tongCa"] == 2
    assert len(r.json()["items"]) == 2


async def test_trang_thai_la_thi_400(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/escalations", params={"trang_thai": "linh_tinh"})

    assert r.status_code == 422


async def test_trang_mac_dinh_muoi_dong(client_ops: httpx.AsyncClient, pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        for i in range(12):
            await them_ca(conn, f"s{i}", tao_luc=luc(10 + i))

    r = await client_ops.get("/api/v1/escalations")

    assert len(r.json()["items"]) == 10
    assert r.json()["tongCa"] == 12


async def test_nhan_ca_ghi_nguoi_va_thoi_diem(client_ops: httpx.AsyncClient, pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        eid = await them_ca(conn, "s1")

    r = await client_ops.patch(f"/api/v1/escalations/{eid}", json={"trangThai": "done", "ghiChu": "đã gọi, hẹn thứ 5"})

    assert r.status_code == 200
    ca = r.json()
    assert ca["trangThai"] == "done"
    assert ca["nguoiXuLy"] == "Đăng"  # TÊN người, không phải user_id
    assert ca["xuLyLuc"] is not None
    assert ca["ghiChu"] == "đã gọi, hẹn thứ 5"


async def test_nhan_ca_khong_ton_tai_ra_404(client_ops: httpx.AsyncClient, workspace_ops):
    r = await client_ops.patch("/api/v1/escalations/999999", json={"trangThai": "done"})

    assert r.status_code == 404


async def test_nhan_ca_tenant_khac_ra_404_khong_phai_403(client_ops: httpx.AsyncClient, pool, workspace_ops):
    """403 nói cho người ngoài biết ca ấy có tồn tại ở tenant khác hay không."""
    async with pool.acquire() as conn, conn.transaction():
        eid = await them_ca(conn, "s-ho", tenant=TENANT_KHAC)

    r = await client_ops.patch(f"/api/v1/escalations/{eid}", json={"trangThai": "done"})

    assert r.status_code == 404


async def test_trang_thai_la_khi_ghi_bi_chan_o_cong(client_ops: httpx.AsyncClient, pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        eid = await them_ca(conn, "s1")

    r = await client_ops.patch(f"/api/v1/escalations/{eid}", json={"trangThai": "linh_tinh"})

    assert r.status_code == 422


async def test_lich_su_ghi_chu_cu_truoc_moi_sau(client_ops: httpx.AsyncClient, du_lieu):
    ca_id = (await client_ops.get("/api/v1/escalations")).json()["items"][0]["id"]
    await client_ops.patch(f"/api/v1/escalations/{ca_id}", json={"trangThai": "contacted", "ghiChu": "gọi lần 1"})
    await client_ops.patch(f"/api/v1/escalations/{ca_id}", json={"trangThai": "done", "ghiChu": "khách hẹn thứ 5"})

    r = await client_ops.get(f"/api/v1/escalations/{ca_id}/notes")

    assert r.status_code == 200
    assert [g["noiDung"] for g in r.json()] == ["gọi lần 1", "khách hẹn thứ 5"]
    assert r.json()[0]["nguoi"] == "Đăng"
    assert r.json()[0]["luc"]


async def test_ca_chua_ai_ghi_chu_ra_mang_rong(client_ops: httpx.AsyncClient, du_lieu):
    ca_id = (await client_ops.get("/api/v1/escalations")).json()["items"][0]["id"]

    r = await client_ops.get(f"/api/v1/escalations/{ca_id}/notes")

    assert r.status_code == 200
    assert r.json() == []


async def test_lich_su_ghi_chu_ca_khong_ton_tai_ra_404(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/escalations/999999/notes")

    assert r.status_code == 404


async def test_tab_dang_xu_ly_va_xong_tach_nhau(client_ops: httpx.AsyncClient, du_lieu):
    xong = await client_ops.get("/api/v1/escalations", params={"trang_thai": "done"})

    assert xong.status_code == 200
    assert [c["sessionId"] for c in xong.json()["items"]] == ["s-xong"]


async def test_sap_xep_cu_truoc_va_loc_du_an(client_ops: httpx.AsyncClient, du_lieu):
    cu = await client_ops.get("/api/v1/escalations", params={"sap_xep": "cu"})
    assert [c["sessionId"] for c in cu.json()["items"]][0] == "s-xong"

    sgi = await client_ops.get("/api/v1/escalations", params={"du_an": "SGI"})
    assert [c["sessionId"] for c in sgi.json()["items"]] == ["s-anh"]
    assert sgi.json()["tongCa"] == 1


async def test_danh_sach_du_an_khong_theo_bo_loc(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/escalations", params={"du_an": "SGI"})

    assert r.json()["duAnCo"] == [{"ma": "SGI", "ten": "Sunshine Green Iconic"}]


async def test_sap_xep_la_thi_400(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/escalations", params={"sap_xep": "linh_tinh"})

    assert r.status_code == 422
