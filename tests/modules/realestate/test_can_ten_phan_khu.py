"""`CanOut.zoneName` — bảng quỹ căn hiện TÊN phân khu, không phải mã.

Tên phải tới từ API chứ không map ở giao diện: danh sách phân khu bên đó là một
`useInfiniteQuery` chỉ tải trang đầu, nên dự án nhiều phân khu sẽ có căn hiện ô
trống — hỏng âm thầm, đúng lớp lỗi mà bộ lọc phía server tồn tại để tránh.
"""

import pytest

from portal.core.db.session import tenant_conn

pytestmark = pytest.mark.integration


async def _du_an_co_phan_khu(client, pool, tenant: str) -> None:
    r = await client.post("/api/v1/projects", json={"projectCode": "ztn1", "name": "Dự án ztn1"})
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/projects/ztn1/zones",
        json={"zoneCode": "PK_A", "name": "Tháp Sông Hồng"},
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/projects/ztn1/units",
        json={"zoneCode": "PK_A", "unitCode": "A-01", "productType": "chung_cu"},
    )
    assert r.status_code == 201, r.text


async def test_liet_ke_can_mang_ten_phan_khu(client_re, workspace_re, pool):
    await _du_an_co_phan_khu(client_re, pool, workspace_re)

    r = await client_re.get("/api/v1/projects/ztn1/units")
    assert r.status_code == 200, r.text
    can = r.json()["items"][0]
    assert can["zoneCode"] == "PK_A"
    assert can["zoneName"] == "Tháp Sông Hồng"


async def test_doc_mot_can_cung_mang_ten(client_re, workspace_re, pool):
    await _du_an_co_phan_khu(client_re, pool, workspace_re)
    cid = (await client_re.get("/api/v1/projects/ztn1/units")).json()["items"][0]["id"]

    r = await client_re.get(f"/api/v1/projects/ztn1/units/{cid}")
    assert r.status_code == 200, r.text
    assert r.json()["zoneName"] == "Tháp Sông Hồng"


async def test_phan_khu_chua_dat_ten_thi_ten_rong_khong_phai_loi(client_re, workspace_re, pool):
    """`zones.name` mặc định `''` — giao diện tự rơi về mã, API không đoán hộ."""
    await client_re.post("/api/v1/projects", json={"projectCode": "ztn2", "name": "Dự án ztn2"})
    await client_re.post("/api/v1/projects/ztn2/zones", json={"zoneCode": "PK_B"})
    await client_re.post(
        "/api/v1/projects/ztn2/units",
        json={"zoneCode": "PK_B", "unitCode": "B-01", "productType": "chung_cu"},
    )

    can = (await client_re.get("/api/v1/projects/ztn2/units")).json()["items"][0]
    assert can["zoneName"] == ""


async def test_can_khong_phan_khu_thi_ten_None(client_re, workspace_re, pool):
    """`zone_code` bỏ NOT NULL từ `0902` — 3015/3015 căn của một tenant thật không phân khu."""
    await client_re.post("/api/v1/projects", json={"projectCode": "ztn3", "name": "Dự án ztn3"})
    async with tenant_conn(pool, workspace_re) as conn:
        await conn.execute(
            "INSERT INTO tenant_data.units (tenant_id, project_code, unit_code, product_type) "
            "VALUES (portal.current_tenant(), 'ztn3', 'C-01', 'chung_cu')"
        )

    can = (await client_re.get("/api/v1/projects/ztn3/units")).json()["items"][0]
    assert can["zoneCode"] is None
    assert can["zoneName"] is None
