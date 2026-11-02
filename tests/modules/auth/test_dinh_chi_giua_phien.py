"""CỔNG 11 — đình chỉ user giữa phiên: 401 VÀ bản ghi phiên bị xoá.

401 chứ không 403 (spec §4.4): đình chỉ là chuyện DANH TÍNH, không phải của một
workspace cụ thể. 403 sẽ làm FE hiện màn "không có quyền" trong khi đúng ra phải
đẩy về /login.

Xoá bản ghi chứ không chỉ trả 401: một người bị đình chỉ không được còn phiên sống.
"""

import pytest

from portal.core.auth.session import TEN_COOKIE

pytestmark = pytest.mark.integration


async def test_dinh_chi_giua_phien_tra_401_va_xoa_phien(dang_nhap_san, pool, redis_client):
    c = dang_nhap_san
    sid = c.cookies[TEN_COOKIE]
    assert await redis_client.exists(f"sess:{sid}") == 1

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("UPDATE control.users SET lifecycle='suspended' WHERE id='u_dang'")

    r = await c.get("/api/v1/members")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "NO_SESSION"

    # Và phiên đã bị thu hồi, không chỉ bị từ chối một lần.
    assert await redis_client.exists(f"sess:{sid}") == 0
