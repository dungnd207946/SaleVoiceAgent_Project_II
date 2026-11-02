"""Cột máy sinh phải RA được tới người đọc: `media.caption_auto` (`0936`) và
`documents.body_auto` (`0937`).

Đo được trên prod 2026-08-19: 30/31 media của tenant `aina_2` có `caption_auto` thật,
`caption` rỗng, và giao diện dự án hiện dãy UUID của tên tệp — chữ nằm trong Postgres
lẫn Qdrant nhưng `MediaOut`/`TaiLieuOut` chưa bao giờ trả nó ra.

Thứ tự ưu tiên đúng như hai migration đã khai: chữ của khách thắng chữ máy sinh.
"""

import asyncpg
import httpx
import pytest

pytestmark = pytest.mark.integration


def _url(path: str) -> str:
    return f"/api/v1{path}"


async def _ghi_cot_may(pool: asyncpg.Pool, tenant: str, bang: str, cot: str, id_: int, gia_tri: str) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
        await conn.execute(f"UPDATE tenant_data.{bang} SET {cot} = $2 WHERE id = $1", id_, gia_tri)


async def _tao_media(client: httpx.AsyncClient, project_code: str, **kw) -> int:
    r = await client.post(
        _url(f"/projects/{project_code}/media"),
        json={"contentType": "image", "category": "tong_quan", "mediaUrl": "https://x/ca.webp", **kw},
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


async def test_caption_auto_ra_o_chi_tiet_va_danh_sach(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    r = await client_re.post(_url("/projects"), json={"projectCode": "CA1", "name": "Dự án CA1"})
    assert r.status_code == 201, r.text
    id_ = await _tao_media(client_re, "CA1")
    await _ghi_cot_may(pool, workspace_re, "media", "caption_auto", id_, "Phối cảnh toà tháp nhìn từ hồ.")

    doc = await client_re.get(_url(f"/projects/CA1/media/{id_}"))
    assert doc.status_code == 200 and doc.json()["caption"] == "Phối cảnh toà tháp nhìn từ hồ."

    ds = await client_re.get(_url("/projects/CA1/media"))
    assert ds.status_code == 200
    hang = next(m for m in ds.json()["items"] if m["id"] == id_)
    assert hang["caption"] == "Phối cảnh toà tháp nhìn từ hồ."


async def test_caption_cua_khach_thang_caption_auto(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    r = await client_re.post(_url("/projects"), json={"projectCode": "CA2", "name": "Dự án CA2"})
    assert r.status_code == 201, r.text
    id_ = await _tao_media(client_re, "CA2", caption="Mô tả của khách")
    await _ghi_cot_may(pool, workspace_re, "media", "caption_auto", id_, "Mô tả của máy")

    doc = await client_re.get(_url(f"/projects/CA2/media/{id_}"))
    assert doc.status_code == 200 and doc.json()["caption"] == "Mô tả của khách"


async def test_body_auto_ra_o_chi_tiet_va_danh_sach(
    client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str
):
    r = await client_re.post(_url("/projects"), json={"projectCode": "CA3", "name": "Dự án CA3"})
    assert r.status_code == 201, r.text
    tao = await client_re.post(_url("/projects/CA3/documents"), json={"loai": "csbh", "title": "Bảng giá"})
    assert tao.status_code == 201, tao.text
    id_ = int(tao.json()["id"])
    await _ghi_cot_may(pool, workspace_re, "documents", "body_auto", id_, "Chữ bóc từ tệp scan.")

    doc = await client_re.get(_url(f"/projects/CA3/documents/{id_}"))
    assert doc.status_code == 200 and doc.json()["body"] == "Chữ bóc từ tệp scan."

    ds = await client_re.get(_url("/projects/CA3/documents"))
    assert ds.status_code == 200
    hang = next(d for d in ds.json()["items"] if d["id"] == id_)
    assert hang["body"] == "Chữ bóc từ tệp scan."


async def test_body_cua_khach_thang_body_auto(client_re: httpx.AsyncClient, pool: asyncpg.Pool, workspace_re: str):
    r = await client_re.post(_url("/projects"), json={"projectCode": "CA4", "name": "Dự án CA4"})
    assert r.status_code == 201, r.text
    tao = await client_re.post(
        _url("/projects/CA4/documents"), json={"loai": "csbh", "title": "Bảng giá", "body": "Chữ của khách"}
    )
    assert tao.status_code == 201, tao.text
    id_ = int(tao.json()["id"])
    await _ghi_cot_may(pool, workspace_re, "documents", "body_auto", id_, "Chữ của máy")

    doc = await client_re.get(_url(f"/projects/CA4/documents/{id_}"))
    assert doc.status_code == 200 and doc.json()["body"] == "Chữ của khách"
