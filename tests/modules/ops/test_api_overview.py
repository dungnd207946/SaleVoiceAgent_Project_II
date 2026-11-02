"""Cổng HTTP của màn Tổng quan — quyền, hình dạng, bất biến, cách ly tenant."""

import asyncpg
import httpx
import pytest

from portal.modules.config.contracts import TEN_KY_NANG

from .conftest import TENANT_KHAC, cach_day, them_phien

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def du_lieu(pool: asyncpg.Pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "h1", bat_dau=cach_day(1), source="chat", chuyen=True)
        await them_phien(conn, "h2", bat_dau=cach_day(1), source="voice")
        await them_phien(conn, "h3", bat_dau=cach_day(2), source="zalo_oa")
        await them_phien(conn, "ngoai", tenant=TENANT_KHAC, bat_dau=cach_day(1), source="chat")
        await conn.execute(
            "INSERT INTO tenant_data.agent_feedback (tenant_id, session_id, rating) VALUES ('opsw','h1',5)"
        )
        await conn.execute(
            "INSERT INTO tenant_data.projects (tenant_id, project_code, name, region, overview, status)"
            " VALUES ('opsw','P1','Ocean Park','Hà Nội','Mô tả','published')"
        )


async def test_khong_dang_nhap_thi_401(app_client: httpx.AsyncClient):
    r = await app_client.get("/api/v1/overview")
    assert r.status_code == 401


async def test_tra_du_nam_khoi(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/overview")

    assert r.status_code == 200
    assert set(r.json()) == {"moc", "hoiThoai", "chuyenSale", "danhGia", "kienThuc"}


async def test_theo_ngay_luon_du_bay_phan_tu(client_ops: httpx.AsyncClient, du_lieu):
    body = (await client_ops.get("/api/v1/overview")).json()

    assert len(body["hoiThoai"]["theoNgay"]) == 7
    assert body["hoiThoai"]["theoNgay"][-1]["ngay"] == body["moc"]["tinhDen"]
    # `tong` là computed_field — phải có mặt trong JSON, biểu đồ đọc nó.
    assert "tong" in body["hoiThoai"]["theoNgay"][0]


async def test_theo_kenh_cong_lai_dung_bang_tong(client_ops: httpx.AsyncClient, du_lieu):
    """Bất biến người dùng ĐỌC ĐƯỢC trên màn: dòng chú thích cộng lại phải ra
    con số lớn ngay trên nó."""
    ht = (await client_ops.get("/api/v1/overview")).json()["hoiThoai"]

    assert sum(k["n"] for k in ht["theoKenh"]) == ht["tong"]
    assert sum(n["tong"] for n in ht["theoNgay"]) == ht["tong"]


async def test_chuyen_sale_cong_lai_bang_tong_hoi_thoai(client_ops: httpx.AsyncClient, du_lieu, pool):
    """Bất biến của gauge: hai cung cộng lại phủ đúng số phiên trong kỳ.

    ⚠️ Fixture `du_lieu` KHÔNG có hàng `escalations` nào, nên từ 2026-08-14
    (tử số đổi sang đếm ca) bài này sẽ xanh với `chuyen = 0` mà không kiểm
    được gì. Chèn một ca ngay tại đây để cả hai vế đều khác 0.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tenant_data.escalations (tenant_id, session_id, status) VALUES ('opsw','h2','new')"
        )

    body = (await client_ops.get("/api/v1/overview")).json()
    cs = body["chuyenSale"]

    # `h2` có ca nhưng KHÔNG có cờ `transferred_to_sales`; `h1` thì ngược lại.
    # Bản cũ (đếm cờ) trả 1 vì `h1` — bản đúng trả 1 vì CA của `h2`. Hai vế
    # dưới cùng nhau chốt là ta đang đếm ca: `chuyen` = 1 và nó KHÔNG đổi khi
    # `h1` giữ cờ.
    assert cs["chuyen"] == 1
    assert cs["chuyen"] + cs["tuXuLy"] == body["hoiThoai"]["tong"]


async def test_tu_xu_ly_khong_bao_gio_am(client_ops: httpx.AsyncClient, du_lieu, pool):
    """Tử số (`escalations`) và mẫu số (`conversations`) giờ là HAI bảng, ghi ở
    hai thời điểm khác nhau — bất biến «tử số ≤ mẫu số» không còn tự đúng.

    Ca thật: ca mở cuối kỳ, phiên của nó chốt sang kỳ sau. Ở đây dựng bằng bốn
    ca trên ba phiên. Không kẹp thì `tuXuLy` âm và gauge quay ngược mà không
    lỗi nào nổ.
    """
    async with pool.acquire() as conn, conn.transaction():
        for i in range(4):
            await conn.execute(
                "INSERT INTO tenant_data.escalations (tenant_id, session_id, status) VALUES ('opsw',$1,'new')",
                f"h{i}",
            )

    body = (await client_ops.get("/api/v1/overview")).json()

    assert body["chuyenSale"]["chuyen"] == 4
    assert body["chuyenSale"]["tuXuLy"] == 0


async def test_danh_gia_dem_TOAN_BO_khong_gioi_han_ky(client_ops: httpx.AsyncClient, du_lieu, pool):
    """Ô ③ phải khớp dải thống kê `/quality`, vốn đếm toàn bộ feedback của
    tenant (xem `enrollment/service.py`). Một lượt chấm từ 90 ngày trước nằm
    ngoài mọi cửa sổ của endpoint này — nó vẫn phải được đếm."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO tenant_data.agent_feedback (tenant_id, session_id, rating, created_at)"
            " VALUES ('opsw','rat-cu',1,$1)",
            cach_day(90),
        )

    dg = (await client_ops.get("/api/v1/overview")).json()["danhGia"]

    # 5 sao (fixture, trong kỳ) + 1 sao (90 ngày trước) — bản cũ chỉ thấy lượt
    # đầu và in `tong = 1`, `trungBinh = 5.0`.
    assert dg["tong"] == 2
    assert dg["trungBinh"] == 3.0
    assert dg["theoSao"]["1"] == 1
    assert dg["theoSao"]["5"] == 1


async def test_khong_lay_du_lieu_tenant_khac(client_ops: httpx.AsyncClient, du_lieu):
    """`ngoai` thuộc TENANT_KHAC — 3 phiên, không phải 4."""
    body = (await client_ops.get("/api/v1/overview")).json()

    assert body["hoiThoai"]["tong"] == 3


async def test_workspace_rong_tra_200_khong_500(client_ops: httpx.AsyncClient, workspace_ops):
    """Không fixture `du_lieu` — workspace mới toanh. `avg()` trên tập rỗng trả
    NULL; ép float thẳng là 500 ngay lần mở màn đầu tiên."""
    r = await client_ops.get("/api/v1/overview")

    assert r.status_code == 200
    body = r.json()
    assert body["danhGia"]["tong"] == 0
    assert body["danhGia"]["trungBinh"] == 0.0
    assert body["danhGia"]["truoc"] is None
    assert len(body["hoiThoai"]["theoNgay"]) == 7
    assert [m["khoa"] for m in body["kienThuc"]["muc"]] == [
        "duAn",
        "phanKhu",
        "can",
        "taiLieuTraCuu",
        "kyNang",
    ]


async def test_ky_nang_tong_la_so_ky_nang_trong_so_backend(client_ops: httpx.AsyncClient, workspace_ops):
    """Mẫu số của hàng «Kỹ năng agent» phải đọc từ SỔ kỹ năng
    (`config/tools.py::TEN_KY_NANG`, qua mặt tiền `config.contracts`), không
    phải hằng `12` chép tay.

    Chép tay thì ngày thêm kỹ năng thứ 13, thước vẽ 12/12 «đã đủ» trong khi
    còn một kỹ năng chưa ai bật — con số nói dối đúng kiểu ô này sinh ra để
    tránh, và không test nào đỏ.
    """
    body = (await client_ops.get("/api/v1/overview")).json()
    ky_nang = next(m for m in body["kienThuc"]["muc"] if m["khoa"] == "kyNang")

    assert ky_nang["tong"] == len(TEN_KY_NANG)
    # Workspace chưa publish lần nào ⇒ chưa bật kỹ năng nào.
    assert ky_nang["thay"] == 0
