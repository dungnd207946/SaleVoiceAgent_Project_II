"""Cổng HTTP của M7 — quyền, hình dạng trả về, 404, cách ly tenant."""

import asyncpg
import httpx
import pytest

from portal.core.avatar import avatar_data_uri

from .conftest import TENANT_KHAC, them_luot, them_phien

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def du_lieu(pool: asyncpg.Pool, workspace_ops):
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "s-anh", phone="0912448111", ten="Minh Anh", chuyen=True)
        await them_phien(conn, "s-an", phone=None, ten=None)
        await them_phien(conn, "s-ho", tenant=TENANT_KHAC, phone="0999999999")
        await them_luot(conn, "s-anh", 0, role="user", content="Còn căn 3PN nào không em?")
        await them_luot(conn, "s-anh", 1, role="assistant", content="Dạ còn 4 căn ạ.")


async def test_danh_sach_khach_nhom_theo_so(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach", params={"tu_ngay": "all"})

    assert r.status_code == 200
    body = r.json()
    assert body["tongKhach"] == 2
    assert body["tongPhien"] == 2
    phones = {k["phone"] for k in body["items"]}
    assert phones == {"0912448111", ""}


async def test_khach_mang_du_truong_man_can(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach", params={"tu_ngay": "all"})
    anh = next(k for k in r.json()["items"] if k["phone"] == "0912448111")

    assert anh["ten"] == "Minh Anh"
    assert anh["soPhien"] == 1
    assert anh["daChuyen"] is True
    assert anh["duAn"] == "Ocean Park 2"
    assert anh["summaryCuoi"] == "Hỏi căn 3PN"


async def test_khach_co_ten_mang_avatar_khach_khuyet_ten_thi_null(client_ops: httpx.AsyncClient, du_lieu):
    """`avatar` = data URI DiceBear seed bằng TÊN; chưa có tên thì NULL — FE giữ
    icon người trung tính, không đoán một avatar không có căn cứ (cùng luật
    `noiDungAvatar(null)` bên FE)."""
    r = await client_ops.get("/api/v1/convos/khach", params={"tu_ngay": "all"})

    items = r.json()["items"]
    anh = next(k for k in items if k["phone"] == "0912448111")
    an = next(k for k in items if k["phone"] == "")
    assert anh["avatar"] == avatar_data_uri("Minh Anh")
    assert an["avatar"] is None


async def test_phien_mang_avatar_cung_nguon_voi_khach(client_ops: httpx.AsyncClient, du_lieu):
    """Cùng một khách phải ra CÙNG một avatar ở mọi màn — cùng seed, cùng hàm."""
    r = await client_ops.get("/api/v1/convos/khach/0912448111/phien")

    assert r.json()[0]["avatar"] == avatar_data_uri("Minh Anh")


async def test_phien_cua_khach_khong_mang_noi_dung_luot(client_ops: httpx.AsyncClient, du_lieu):
    """`content` là phần nặng nhất. Endpoint này KHÔNG được kéo nó về."""
    r = await client_ops.get("/api/v1/convos/khach/0912448111/phien")

    assert r.status_code == 200
    assert r.json()[0]["soLuot"] == 2
    assert "content" not in r.text


async def test_nhom_chua_co_so_di_bang_gach_duoi(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach/_/phien")

    assert r.status_code == 200
    assert [p["sessionId"] for p in r.json()] == ["s-an"]


async def test_nhom_chua_co_so_khong_mang_ten_du_phien_co_ghi(
    client_ops: httpx.AsyncClient, pool: asyncpg.Pool, workspace_ops
):
    """Nhóm «Chưa có số» gộp NHIỀU người ẩn danh — gán một cái tên cho nó là nói sai.

    Ca chốt phải có `customer_name` KHÁC NULL trên một phiên `phone IS NULL`. Nếu
    fixture để `ten=None` thì `r["ten"]` vốn đã là None, và xoá hẳn mặt nạ
    `ten=None if r["phone"] == ""` cũng không test nào đỏ — cổng thành đồ trang trí.
    """
    async with pool.acquire() as conn, conn.transaction():
        await them_phien(conn, "s-an-co-ten", phone=None, ten="Ai Đó")

    r = await client_ops.get("/api/v1/convos/khach", params={"tu_ngay": "all"})

    nhom_an = next(k for k in r.json()["items"] if k["phone"] == "")
    assert nhom_an["ten"] is None


async def test_so_khong_co_phien_tra_mang_rong_khong_phai_404(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach/0900000000/phien")

    assert r.status_code == 200
    assert r.json() == []


async def test_chi_tiet_phien_tra_luot_theo_thu_tu(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/phien/s-anh")

    assert r.status_code == 200
    body = r.json()
    assert body["phien"]["sessionId"] == "s-anh"
    assert [luot["seq"] for luot in body["luot"]] == [0, 1]
    assert [luot["role"] for luot in body["luot"]] == ["user", "assistant"]


async def test_chi_tiet_phien_tra_phone(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/phien/s-anh")

    assert r.status_code == 200
    assert r.json()["phien"]["phone"] == "0912448111"


async def test_chi_tiet_phien_khong_so_thi_phone_null(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/phien/s-an")

    assert r.status_code == 200
    assert r.json()["phien"]["phone"] is None


async def test_liet_ke_phien_tra_phone(client_ops: httpx.AsyncClient, du_lieu):
    r = await client_ops.get("/api/v1/convos/khach/0912448111/phien")

    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["phone"] == "0912448111"


async def test_phien_cua_tenant_khac_tra_404(client_ops: httpx.AsyncClient, du_lieu):
    """404 chứ KHÔNG 403: 403 nói cho người ngoài biết session ấy có tồn tại ở đâu đó."""
    r = await client_ops.get("/api/v1/convos/phien/s-ho")

    assert r.status_code == 404


async def test_chua_dang_nhap_bi_chan(app_client: httpx.AsyncClient, workspace_ops):
    r = await app_client.get("/api/v1/convos/khach")

    assert r.status_code == 401


async def test_khong_co_endpoint_ghi_nao(client_ops: httpx.AsyncClient, du_lieu):
    """Màn này chỉ xem. Cổng canh để không ai thêm đường ghi mà không sửa spec.

    Assert đúng `405`, KHÔNG phải `in (404, 405)`: cả hai đường dưới đây đã có route
    GET đăng ký, nên Starlette luôn trả 405 cho sai method. Nhận cả 404 là để ngỏ
    cửa cho ca "route không tồn tại" — tức test vẫn xanh cả khi router chưa lên,
    và nó chứng minh được ít hơn nhiều so với vẻ ngoài.
    """
    for goi in (
        client_ops.post("/api/v1/convos/khach", json={}),
        client_ops.delete("/api/v1/convos/phien/s-anh"),
    ):
        assert (await goi).status_code == 405


async def test_phien_chua_co_luot_nao_tra_mang_rong_khong_404(client_ops: httpx.AsyncClient, du_lieu):
    """Phiên có thật nhưng chưa có lượt nào ⇒ 200 + `luot: []`. Nó chưa có nội dung,
    không phải nó không tồn tại."""
    r = await client_ops.get("/api/v1/convos/phien/s-an")

    assert r.status_code == 200
    assert r.json()["luot"] == []
    assert r.json()["phien"]["soLuot"] == 0
