"""Ma trận vai trò × hành động — cổng 2·3·8·10 của spec §7."""

import pytest

from portal.core.auth import repo
from portal.core.auth.actions import ACTIONS, ALL_ACTIONS

pytestmark = pytest.mark.integration


async def test_owner_du_13_quyen_du_khong_co_membership(pool, du_lieu_quyen):
    """Cổng 3 §7. Owner không đi qua ma trận — §3.3.

    Đây là thứ làm cho sửa vai trò không khoá cửa được thành thật: owner bỏ
    tích cả 13 ô của mọi vai trò thì chính họ vẫn vào được và sửa lại.
    """
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, du_lieu_quyen.owner_id, du_lieu_quyen.tenant_id)
    assert q is not None
    assert q.role_name == "Quản trị"
    assert q.actions == ALL_ACTIONS


async def test_nguoi_xem_khong_co_quyen_ghi(pool, du_lieu_quyen):
    """Cổng 2 §7."""
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, du_lieu_quyen.viewer_id, du_lieu_quyen.tenant_id)
    assert q is not None
    assert ACTIONS.CATALOG_READ in q.actions
    assert ACTIONS.CATALOG_WRITE not in q.actions
    assert q.role_name == "Người xem"


async def test_khong_membership_tra_actions_rong(pool, du_lieu_quyen):
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, du_lieu_quyen.nguoi_la_id, du_lieu_quyen.tenant_id)
    assert q is not None
    assert q.actions == frozenset()
    assert q.role_name is None


async def test_user_khong_ton_tai_tra_none(pool, du_lieu_quyen):
    async with pool.acquire() as conn:
        assert await repo.doc_quyen(conn, "u_khong_co", du_lieu_quyen.tenant_id) is None


async def test_membership_het_han_khong_cho_quyen(pool, du_lieu_quyen):
    """Vị từ expires_at phải nằm trong ON, không phải WHERE — §3.2.

    Ở WHERE nó biến LEFT JOIN thành INNER JOIN âm thầm: user không membership mất
    luôn hàng, và nhánh owner không bao giờ chạy tới.
    """
    async with pool.acquire() as conn:
        q = await repo.doc_quyen(conn, du_lieu_quyen.het_han_id, du_lieu_quyen.tenant_id)
    assert q is not None, "user vẫn tồn tại — chỉ vé của họ hết hạn"
    assert q.actions == frozenset()


async def test_bo_tich_mot_o_chan_ngay_lan_doc_ke_tiep(pool, du_lieu_quyen):
    """Cổng 8 §7 — chứng minh KHÔNG cache. Cổng khó viết nhất và quan trọng nhất."""
    async with pool.acquire() as conn:
        truoc = await repo.doc_quyen(conn, du_lieu_quyen.editor_id, du_lieu_quyen.tenant_id)
        assert ACTIONS.CATALOG_WRITE in truoc.actions

        await conn.execute(
            """DELETE FROM control.role_actions
                WHERE role_id = (SELECT role_id FROM control.memberships
                                  WHERE user_id = $1 AND tenant_id = $2)
                  AND action_code = $3""",
            du_lieu_quyen.editor_id,
            du_lieu_quyen.tenant_id,
            ACTIONS.CATALOG_WRITE,
        )

        sau = await repo.doc_quyen(conn, du_lieu_quyen.editor_id, du_lieu_quyen.tenant_id)
    assert ACTIONS.CATALOG_WRITE not in sau.actions


async def test_viewer_goi_endpoint_ghi_nhan_403(client_viewer):
    """Cổng 2 §7 ở tầng HTTP — không chỉ ở repo.

    Endpoint thật là `POST /api/v1/projects` (require(ACTIONS.CATALOG_WRITE)) —
    brief gọi nó "/du-an" nhưng route thật ở `modules/realestate/router.py` đặt
    tên tiếng Anh. `projectCode` phải có trong thân, không thì 422 (thiếu field)
    che mất 403 đang muốn kiểm — `require()` chạy trước khi thân được xác thực,
    nhưng gửi thân hợp lệ loại bỏ hẳn nghi vấn đó khỏi test.
    """
    r = await client_viewer.post("/api/v1/projects", json={"projectCode": "P_THU", "name": "Thử"})
    assert r.status_code == 403
    than = r.json()["error"]
    assert than["code"] == "FORBIDDEN"
    # Cổng của §3.4: thông điệp phải nói LÝ DO, không phải một câu chung chung.
    assert "Người xem" in than["message"]
    assert "Thêm · sửa" in than["message"]


# --- review round 2 -----------------------------------------------------------
# §3.6 (SessionOut.actions phải khớp require()) và §3.7 (co_membership tách khỏi
# actions cho doi_workspace).


async def test_session_actions_nguoi_xem_hep_hon_owner(client_viewer):
    """§3.6 — `SessionOut.actions` phải là tập THẬT, không phải hằng số.

    `_dung_session_out` từng luôn trả `sorted(ALL_ACTIONS)` — đúng M2a, sai từ
    khi M2b bật ma trận: FE hiện mọi nút cho một Người xem, và API chặn hết,
    tức đúng "nút xám vô nghĩa" mà thiết kế này tồn tại để tránh (chỉ lệch
    hướng: hiện nút mà API chặn, không phải ẩn nút mà API cho).

    ⚠ KHÔNG gộp với test owner dưới vào cùng một hàm: `client_viewer` và
    `owner_dang_nhap` cùng mượn `u_dang`/`dang_nhap_san` phía dưới — yêu cầu cả
    hai trong một test khiến CẢ HAI phép mutate (role_id -> Người xem, vai trò
    -> owner) áp lên CÙNG một hàng, và owner luôn thắng (bỏ qua ma trận, §3.3).
    """
    r = await client_viewer.get("/api/v1/me")
    assert r.status_code == 200, r.text
    cua_viewer = set(r.json()["actions"])
    assert ACTIONS.CATALOG_READ in cua_viewer
    assert ACTIONS.CATALOG_WRITE not in cua_viewer
    assert cua_viewer != ALL_ACTIONS, "Người xem không được thấy nút mà API sẽ chặn"


async def test_session_actions_owner_du_13(owner_dang_nhap):
    """Mặt còn lại — owner không đi qua ma trận (§3.3), `SessionOut.actions` của
    họ vẫn phải là đủ 13, không phải một tập suy từ vai trò (họ có thể chẳng có
    vai trò nào — `role_name is None`)."""
    r = await owner_dang_nhap.get("/api/v1/me")
    assert r.status_code == 200, r.text
    assert set(r.json()["actions"]) == ALL_ACTIONS


async def test_vai_tro_0_quyen_van_doi_workspace_duoc_nhung_actions_rong(pool, dang_nhap_san):
    """§3.7 — `co_membership`, KHÔNG PHẢI `actions`, là cửa của `doi_workspace`.

    Một vai trò 0 quyền là trạng thái HỢP LỆ (§2.1 "đã tạo, chưa cấu hình"), và
    §3.3 buộc sửa vai trò không được khoá cửa AI — kể cả người GIỮ vai trò đó,
    không chỉ owner. Trước bản sửa này, `doi_workspace` dùng `not q.actions` làm
    phép kiểm — coi một membership có thật nhưng 0 quyền như "không phải thành
    viên", nên người này thấy workspace trên switcher (`liet_ke_workspace` chỉ
    cần một hàng `memberships`) rồi ăn 403 khi bấm vào — đúng phân kỳ mà
    `test_to_chuc.py` cảnh báo trong docstring của nó.
    """
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.roles (id, name) VALUES ('r_rong_ttq', 'Rỗng TTQ')")
        await conn.execute(
            "UPDATE control.memberships SET role_id = 'r_rong_ttq'"
            " WHERE user_id = 'u_dang' AND tenant_id = 'cs_sunrise'"
        )

    try:
        c = dang_nhap_san
        r = await c.post("/api/v1/me/workspace", json={"workspaceId": "cs_sunrise"})
        assert r.status_code == 200, r.text
        assert r.json()["actions"] == [], "chuyển được, nhưng đúng KHÔNG quyền nào"

        r = await c.get("/api/v1/me")
        assert r.status_code == 200, r.text
        assert r.json()["currentWorkspaceId"] == "cs_sunrise"
        assert r.json()["actions"] == []
    finally:
        # FK RESTRICT trên `role_id`: xoá role trong khi membership còn trỏ vào
        # nó sẽ nổ ForeignKeyViolationError. Gỡ đúng hàng membership của test
        # này trước — `ba_workspace` teardown xoá cả user `u_dang` ngay sau đây
        # nên không cần đặt role_id về lại giá trị cũ.
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM control.memberships WHERE user_id = 'u_dang' AND tenant_id = 'cs_sunrise'")
            await conn.execute("DELETE FROM control.roles WHERE id = 'r_rong_ttq'")
