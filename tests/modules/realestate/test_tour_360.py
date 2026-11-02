"""`projects.link_360` thành một hàng `media` `tour_360`.

Ở collection `documents` link nằm TRONG text nên LLM phải chép lại một URL dài nhiều
tham số để trả cho khách — chép sai là chuyện sẽ xảy ra. Ở `media` link đi trong payload
point và client tự render, LLM không chạm vào chuỗi (D16).
"""

import json

import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration

LINK = "https://kuula.co/share/collection/7l8Rt?logo=1&info=1&fs=1&vr=0&thumbs=1"


async def _jobs(pool, tenant: str, kind: str) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id", tenant, kind
        )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else dict(r["payload"]) for r in rows]


async def _tour(pool, tenant: str, code: str):
    async with tenant_conn(pool, tenant) as conn:
        return await conn.fetchrow(
            "SELECT id, media_url, caption, category, status FROM tenant_data.media "
            "WHERE tenant_id = portal.current_tenant() AND project_code = $1 AND content_type = 'tour_360'",
            code,
        )


async def _tao(client, code: str, **kw) -> None:
    r = await client.post("/api/v1/projects", json={"projectCode": code, "name": f"Dự án {code}", **kw})
    assert r.status_code == 201, r.text


async def test_tao_du_an_co_link_360_sinh_hang_media(client_re, workspace_re, pool):
    await _tao(client_re, "t360a", link360=LINK)

    row = await _tour(pool, workspace_re, "t360a")
    assert row is not None, "có link 360 mà không sinh hàng media"
    assert row["media_url"] == LINK
    assert "360" in row["caption"] and "t360a" in row["caption"], "caption phải mang tên dự án"
    assert row["category"] == "tong_quan", "danh mục ngoài media_visual thì không bao giờ được nạp"


async def test_hang_tour_duoc_dat_viec_nap(client_re, workspace_re, pool):
    await _tao(client_re, "t360b", link360=LINK)
    row = await _tour(pool, workspace_re, "t360b")

    js = await _jobs(pool, workspace_re, "kb_index")
    assert any(j.get("entity") == "media" and j.get("record_id") == int(row["id"]) for j in js)


async def test_them_link_360_sau_thi_sinh_hang(client_re, workspace_re, pool):
    await _tao(client_re, "t360c")
    assert await _tour(pool, workspace_re, "t360c") is None

    r = await client_re.patch("/api/v1/projects/t360c", json={"link360": LINK})
    assert r.status_code == 200, r.text
    assert (await _tour(pool, workspace_re, "t360c"))["media_url"] == LINK


async def test_doi_link_thi_sua_dung_hang_do_khong_sinh_them(client_re, workspace_re, pool):
    await _tao(client_re, "t360d", link360=LINK)
    cu = await _tour(pool, workspace_re, "t360d")

    moi_link = "https://kuula.co/share/collection/KHAC"
    r = await client_re.patch("/api/v1/projects/t360d", json={"link360": moi_link})
    assert r.status_code == 200, r.text

    row = await _tour(pool, workspace_re, "t360d")
    assert row["id"] == cu["id"], "đổi link mà sinh hàng thứ hai — hàng cũ thành point mồ côi"
    assert row["media_url"] == moi_link


async def test_xoa_link_thi_xoa_hang_va_don_point(client_re, workspace_re, pool):
    await _tao(client_re, "t360e", link360=LINK)
    cu = await _tour(pool, workspace_re, "t360e")

    r = await client_re.patch("/api/v1/projects/t360e", json={"link360": ""})
    assert r.status_code == 200, r.text

    assert await _tour(pool, workspace_re, "t360e") is None
    xoa = await _jobs(pool, workspace_re, "kb_delete")
    assert any(j.get("entity") == "media" and j.get("record_id") == int(cu["id"]) for j in xoa)


async def test_doi_ten_du_an_cap_nhat_caption_tour(client_re, workspace_re, pool):
    """Caption mang tên dự án, nên đổi tên mà không chạm là caption nói tên cũ mãi mãi."""
    await _tao(client_re, "t360f", link360=LINK)

    r = await client_re.patch("/api/v1/projects/t360f", json={"name": "Vinhomes Royal Island"})
    assert r.status_code == 200, r.text

    assert "Vinhomes Royal Island" in (await _tour(pool, workspace_re, "t360f"))["caption"]


async def test_khong_co_link_thi_khong_sinh_gi(client_re, workspace_re, pool):
    await _tao(client_re, "t360g")
    r = await client_re.patch("/api/v1/projects/t360g", json={"overview": "nội dung"})
    assert r.status_code == 200, r.text
    assert await _tour(pool, workspace_re, "t360g") is None
