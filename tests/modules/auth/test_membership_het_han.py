"""CỔNG 5 — membership có `expires_at` quá hạn TỰ mất hiệu lực.

YC08: "Quyền hỗ trợ tự hết hạn, không ai phải nhớ đi thu hồi." Cột có từ M2a
(migration 0101) chính là để câu đó đúng bằng cơ chế, không bằng một runbook.

Luồng xin/duyệt quyền hỗ trợ là M2b. Cái được kiểm ở đây là VỊ TỪ trong
require(): một hàng quá hạn phải bị bỏ qua như thể không tồn tại.
"""

import pytest

pytestmark = pytest.mark.integration


async def test_membership_qua_han_bi_bo_qua(dang_nhap_san, pool):
    c = dang_nhap_san
    assert (await c.get("/api/v1/members")).status_code == 200

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """UPDATE control.memberships SET expires_at = now() - interval '1 second'
                WHERE user_id='u_dang' AND tenant_id='cs_anphu'"""
        )

    assert (await c.get("/api/v1/members")).status_code == 403


async def test_membership_con_han_van_vao_duoc(dang_nhap_san, pool):
    """Mặt còn lại: vé hỗ trợ CÒN hạn phải vào được, không thì cột này vô dụng."""
    c = dang_nhap_san

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """UPDATE control.memberships SET expires_at = now() + interval '1 hour'
                WHERE user_id='u_dang' AND tenant_id='cs_anphu'"""
        )

    assert (await c.get("/api/v1/members")).status_code == 200


async def test_ws_het_han_bien_khoi_switcher(dang_nhap_san, pool):
    """Cùng vị từ, chỗ khác: hết hạn phải biến khỏi danh sách workspace của /me,
    không chỉ bị chặn ở require(). Nếu không thì người ta thấy workspace trên
    switcher, bấm vào, và ăn 403 — trông như hệ thống hỏng."""
    c = dang_nhap_san

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """UPDATE control.memberships SET expires_at = now() - interval '1 second'
                WHERE user_id='u_dang' AND tenant_id='cs_sunrise'"""
        )

    ws = (await c.get("/api/v1/me")).json()["workspaces"]
    assert [w["id"] for w in ws] == ["cs_anphu"]
