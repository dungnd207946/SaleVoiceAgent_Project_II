"""CỔNG 4 — gỡ một người khỏi workspace có hiệu lực Ở REQUEST KẾ TIẾP.

Đây là YC03 và PQ_01 §BR-Q04, và là lý do phiên KHÔNG chứa quyền. CMS cũ nhét vai
trò vào phiếu đăng nhập hạn 15 phút, nên "sa thải một người xong, 15 phút nữa họ
vẫn sửa được dữ liệu".

Nếu test này đỏ vì có ai nhét `role`/`actions` vào bản ghi Redis cho nhanh — đừng
sửa test. Sửa chỗ đó.
"""

import pytest

pytestmark = pytest.mark.integration


async def test_go_membership_thi_request_ke_tiep_403(dang_nhap_san, pool):
    c = dang_nhap_san

    # Trước khi gỡ: vào được.
    assert (await c.get("/api/v1/members")).status_code == 200

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.memberships WHERE user_id='u_dang' AND tenant_id='cs_anphu'")

    # KHÔNG đăng nhập lại, KHÔNG đợi TTL. Ngay request sau.
    r = await c.get("/api/v1/members")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "FORBIDDEN"


async def test_go_khoi_mot_ws_khong_anh_huong_ws_con_lai(dang_nhap_san, pool):
    """Thu hồi phải đúng phạm vi: gỡ khỏi cs_anphu không được đá người ta ra khỏi
    cs_sunrise. Một phép thu hồi quá tay cũng là một bug, chỉ theo chiều ngược lại.

    Xác nhận "vẫn ở trong workspace" bằng `GET /me`, KHÔNG bằng `GET /members`:
    `/members` cần `ACTIONS.WORKSPACE_ADMIN`, còn vai trò của `u_dang` ở
    `cs_sunrise` là CSKH (cố tình ÍT quyền hơn Quản trị ở `cs_anphu` — xem
    docstring `ba_workspace`). Dùng một đường cần quyền cụ thể để hỏi một câu
    không liên quan tới quyền cụ thể là tự trộn hai câu hỏi khác nhau.
    """
    c = dang_nhap_san

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.memberships WHERE user_id='u_dang' AND tenant_id='cs_anphu'")

    # Phiên vẫn sống, vẫn đổi sang workspace còn lại được.
    r = await c.post("/api/v1/me/workspace", json={"workspaceId": "cs_sunrise"})
    assert r.status_code == 200
    assert (await c.get("/api/v1/me")).status_code == 200
