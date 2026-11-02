"""Bất biến: hàng `media` nào có `media_url` thì có `public_url`.

Đó là cột agent gửi cho khách. Một đường ghi quên tính nó thì ảnh đó tới khách dưới
dạng chuỗi rỗng — không lỗi, không log, và chỉ lộ ra khi khách phàn nàn.
"""

import asyncpg
import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def base_url(monkeypatch):
    """Mặc định rỗng = không sinh link; đặt để đo được phép nối."""
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://portal.test")


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _media_cua(pool: asyncpg.Pool, tenant: str, project_code: str) -> list[asyncpg.Record]:
    return await pool.fetch(
        "SELECT media_url, public_url, thumb_url, public_thumb_url FROM tenant_data.media "
        "WHERE tenant_id = $1 AND project_code = $2 ORDER BY id",
        tenant,
        project_code,
    )


async def _du_an(client: httpx.AsyncClient, code: str) -> str:
    r = await client.post(_url("/projects"), json={"projectCode": code, "name": code})
    assert r.status_code == 201, r.text
    return code


async def test_tao_media_qua_tab_media_dien_public_url(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    code = await _du_an(client_re, "PUBURL0")
    r = await client_re.post(
        _url(f"/projects/{code}/media"),
        json={"category": "tong_quan", "contentType": "image", "mediaUrl": "tenants/x/kb-bds/abc/a.jpg"},
    )
    assert r.status_code == 201, r.text
    hang = await _media_cua(pool, workspace_re, code)
    assert hang[-1]["public_url"].endswith("/api/v1/public/files/tenants/x/kb-bds/abc/a.jpg")


async def test_o_cover_cua_form_du_an_cung_dien(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    """Đường ghi thứ hai — `_payload_media_con`, không đi qua router media."""
    r = await client_re.post(
        _url("/projects"),
        json={
            "projectCode": "PUBURL1",
            "name": "Có cover",
            "coverMedia": {"mediaUrl": "tenants/x/kb-bds/def/cover.jpg"},
        },
    )
    assert r.status_code == 201, r.text
    hang = await _media_cua(pool, workspace_re, "PUBURL1")
    assert len(hang) == 1
    assert hang[0]["public_url"].endswith("/api/v1/public/files/tenants/x/kb-bds/def/cover.jpg")


async def test_url_ngoai_giu_nguyen(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    code = await _du_an(client_re, "PUBURL2")
    r = await client_re.post(
        _url(f"/projects/{code}/media"),
        json={"category": "tong_quan", "contentType": "image", "mediaUrl": "https://cdn.khach.vn/a.jpg"},
    )
    assert r.status_code == 201, r.text
    hang = await _media_cua(pool, workspace_re, code)
    assert hang[-1]["public_url"] == "https://cdn.khach.vn/a.jpg"


async def test_sua_media_url_thi_public_url_theo(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    """Đổi ảnh mà quên cập nhật cột dẫn xuất là agent gửi ảnh CŨ cho khách."""
    code = await _du_an(client_re, "PUBURL3")
    tao = await client_re.post(
        _url(f"/projects/{code}/media"),
        json={"category": "tong_quan", "contentType": "image", "mediaUrl": "tenants/x/kb-bds/cu/a.jpg"},
    )
    id_ = tao.json()["id"]
    await client_re.patch(_url(f"/projects/{code}/media/{id_}"), json={"mediaUrl": "tenants/x/kb-bds/moi/b.jpg"})
    hang = await _media_cua(pool, workspace_re, code)
    assert hang[-1]["public_url"].endswith("/kb-bds/moi/b.jpg")


async def test_ten_tep_luu_va_doc_lai_duoc(client_re: httpx.AsyncClient):
    """Tên gốc giữ dấu tiếng Việt; khoá S3 thì không (đã qua `_ten_an_toan`)."""
    code = await _du_an(client_re, "TENANH1")
    r = await client_re.post(
        _url(f"/projects/{code}/media"),
        json={
            "category": "tong_quan",
            "contentType": "image",
            "mediaUrl": "tenants/x/kb-bds/abc/Phoi-canh-toa-A.jpg",
            "fileName": "Phối cảnh tổng thể — toà A.jpg",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["fileName"] == "Phối cảnh tổng thể — toà A.jpg"

    ds = await client_re.get(_url(f"/projects/{code}/media"))
    assert ds.json()["items"][0]["fileName"] == "Phối cảnh tổng thể — toà A.jpg"


async def test_sua_ten_tep(client_re: httpx.AsyncClient):
    code = await _du_an(client_re, "TENANH2")
    tao = await client_re.post(
        _url(f"/projects/{code}/media"),
        json={"category": "tong_quan", "contentType": "image", "mediaUrl": "tenants/x/a.jpg", "fileName": "cũ.jpg"},
    )
    id_ = tao.json()["id"]
    r = await client_re.patch(_url(f"/projects/{code}/media/{id_}"), json={"fileName": "Mặt bằng tầng 3.jpg"})
    assert r.status_code == 200, r.text
    assert r.json()["fileName"] == "Mặt bằng tầng 3.jpg"


async def test_khong_gui_ten_thi_rong_khong_loi(client_re: httpx.AsyncClient):
    """Ảnh cũ tạo trước migration, và ảnh dán URL ngoài không có tên tệp nào."""
    code = await _du_an(client_re, "TENANH3")
    r = await client_re.post(
        _url(f"/projects/{code}/media"),
        json={"category": "tong_quan", "contentType": "image", "mediaUrl": "https://cdn.x/a.jpg"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["fileName"] == ""
