"""Nhãn danh mục là chuyện của vector, không phải chuyện của người dùng portal."""

import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


async def test_caption_auto_co_nhan_thi_api_tra_ban_sach(client_re, workspace_re, pool):
    r = await client_re.post("/api/v1/projects", json={"projectCode": "capt1", "name": "Dự án capt1"})
    assert r.status_code == 201, r.text
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.media (tenant_id, project_code, content_type, category, media_url, caption_auto) "
            "VALUES (portal.current_tenant(), 'capt1', 'image', 'tong_quan', 'https://x/a.jpg', $1)",
            "Phòng ngủ hiện đại.\nDanh mục: nội thất",
        )

    ds = (await client_re.get("/api/v1/projects/capt1/media")).json()["items"]
    assert ds[0]["caption"] == "Phòng ngủ hiện đại."


async def test_khong_cat_mo_ta_nguoi_go_tay(client_re, workspace_re, pool):
    """Khách gõ đúng chữ đó trong mô tả tay thì KHÔNG được cắt — strip chỉ áp cho caption_auto."""
    r = await client_re.post("/api/v1/projects", json={"projectCode": "capt2", "name": "Dự án capt2"})
    assert r.status_code == 201, r.text
    goc = "Ảnh.\nDanh mục: nội thất"
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.media (tenant_id, project_code, content_type, category, media_url, caption) "
            "VALUES (portal.current_tenant(), 'capt2', 'image', 'tong_quan', 'https://x/b.jpg', $1)",
            goc,
        )

    ds = (await client_re.get("/api/v1/projects/capt2/media")).json()["items"]
    assert ds[0]["caption"] == goc
