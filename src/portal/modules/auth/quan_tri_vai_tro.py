"""Sáu thao tác vai trò. Mọi thao tác ghi nằm trong MỘT transaction.

⚠ BA THAO TÁC GHI ĐANG TẮT — ĐỌC TRƯỚC KHI BẬT

Vai trò đã TOÀN CỤC từ migration 0105: một bộ 4 dùng chung cho MỌI workspace, vì
không còn tổ chức để mỗi tổ chức giữ một bản riêng. Cùng lúc, cửa thật cũ của
khối này — `users.org_role = 'owner'` — biến mất cùng migration 0106.

Hệ quả: nếu để `POST`/`PATCH`/`DELETE /roles` mở cho `WORKSPACE_ADMIN` thì Quản
trị của MỘT workspace bất kỳ sẽ sửa hoặc xoá được vai trò của TẤT CẢ workspace
khác. Đó không phải là điều `WORKSPACE_ADMIN` hứa.

Nên ba đường ghi đóng bằng cờ `ROLES_CRUD_ENABLED` (mặc định `False`) —
`_cong_ghi_vai_tro()`. Bảng, code và test giữ nguyên để bật lại khi có mô hình
quyền động, và khi bật thì phải kèm một cổng phù hợp, không phải chỉ lật cờ.

BA ĐƯỜNG ĐỌC (`liet_ke_action`, `liet_ke`, `doc`) VẪN MỞ: FE cần `GET /roles` để
dựng dropdown chọn vai trò lúc mời thành viên. Đóng chúng là làm hỏng luồng mời
người — thứ không liên quan gì tới rủi ro ở trên.

Cổng chung của cả sáu vẫn là `require(ACTIONS.WORKSPACE_ADMIN)` khai ở router.
"""

from uuid import uuid4

import asyncpg

from portal.api import loi as loi_chung
from portal.core import nhat_ky
from portal.core.config import get_settings
from portal.modules.auth import loi, repo


def _cong_ghi_vai_tro() -> None:
    """Chặn mọi đường GHI vai trò khi cờ tắt. Xem docstring module."""
    if not get_settings().roles_crud_enabled:
        raise loi_chung.tinh_nang_dang_tat("quản trị vai trò")


async def liet_ke_action(conn: asyncpg.Connection, user_id: str) -> list[asyncpg.Record]:
    return await repo.liet_ke_action(conn)


async def liet_ke(conn: asyncpg.Connection, user_id: str) -> list[asyncpg.Record]:
    return await repo.liet_ke_vai_tro(conn)


async def doc(conn: asyncpg.Connection, user_id: str, role_id: str) -> asyncpg.Record:
    r = await repo.doc_vai_tro(conn, role_id)
    if r is None:
        raise loi.vai_tro_khong_ton_tai()
    return r


async def tao(conn: asyncpg.Connection, user_id: str, name: str, description: str | None, actions: list[str]) -> str:
    """Thứ tự trong MỘT transaction — người gọi mở transaction.

    1. kiểm cờ                         → 403 FEATURE_DISABLED
    2. kiểm action hợp lệ              → 422 UNKNOWN_ACTION
    3. kiểm tên chưa dùng              → 409 ROLE_NAME_TAKEN
    4. INSERT roles
    5. INSERT role_actions

    Bước 2 và 3 TRƯỚC bước 4 là cố ý: FK và UNIQUE cũng chặn, nhưng bằng một
    ngoại lệ asyncpg → 500. Kiểm trước biến cùng một sự thật thành một câu có
    tên field.
    """
    _cong_ghi_vai_tro()

    la = await repo.loc_action_la(conn, actions)
    if la is not None:
        raise loi.action_khong_hop_le(la)

    # `UNIQUE (name)` từ 0105 — toàn cục, không còn theo tổ chức.
    trung = await conn.fetchval("SELECT 1 FROM control.roles WHERE name = $1", name)
    if trung:
        raise loi.ten_vai_tro_da_ton_tai()

    # uuid4, KHÔNG suy từ tên: tên đổi được, id thì phải ổn định (spec §2.1).
    role_id = "r_" + uuid4().hex
    await repo.tao_vai_tro(conn, role_id, name, description)
    await repo.dat_action_cua_vai_tro(conn, role_id, actions)

    # SAU KHI việc đã xong — cùng khuôn quan_tri_user.py. Vai trò không thuộc
    # workspace nào nên `ghi_he_thong` (tenant_id=NULL), không phải `ghi()`.
    await nhat_ky.ghi_he_thong(conn, "role.tao", user_id, {"role_id": role_id, "name": name, "actions": actions})
    return role_id


async def sua(
    conn: asyncpg.Connection,
    user_id: str,
    role_id: str,
    name: str,
    description: str | None,
    actions: list[str],
) -> None:
    _cong_ghi_vai_tro()
    if await repo.doc_vai_tro(conn, role_id) is None:
        raise loi.vai_tro_khong_ton_tai()

    la = await repo.loc_action_la(conn, actions)
    if la is not None:
        raise loi.action_khong_hop_le(la)

    trung = await conn.fetchval(
        "SELECT 1 FROM control.roles WHERE name = $1 AND id <> $2",
        name,
        role_id,
    )
    if trung:
        raise loi.ten_vai_tro_da_ton_tai()

    await repo.doi_ten_vai_tro(conn, role_id, name, description)
    await repo.dat_action_cua_vai_tro(conn, role_id, actions)

    await nhat_ky.ghi_he_thong(conn, "role.sua", user_id, {"role_id": role_id, "name": name, "actions": actions})


async def xoa(conn: asyncpg.Connection, user_id: str, role_id: str) -> None:
    _cong_ghi_vai_tro()
    hien_tai = await repo.doc_vai_tro(conn, role_id)
    if hien_tai is None:
        raise loi.vai_tro_khong_ton_tai()

    n = await repo.dem_nguoi_dung_vai_tro(conn, role_id)
    n_loi_moi = await repo.dem_loi_moi_dang_treo_vai_tro(conn, role_id)
    if n > 0 or n_loi_moi > 0:
        # `n == 0` không có nghĩa "không ai đang giữ vai trò này" theo nghĩa
        # người xoá cần biết — một lời mời còn sống hứa đúng vai trò này cũng
        # chặn DELETE, chỉ là chặn ở FK trần của `invites.role_id` (500) nếu
        # thiếu vế này. Xem docstring `repo.dem_loi_moi_dang_treo_vai_tro`.
        raise loi.vai_tro_dang_dung(n, n_loi_moi)

    await repo.xoa_vai_tro(conn, role_id)

    # `hien_tai` đọc TRƯỚC khi xoá — tên và action của một vai trò đã mất không
    # còn tra được nếu ghi nhật ký sau DELETE mà không giữ lại giá trị cũ.
    await nhat_ky.ghi_he_thong(
        conn,
        "role.xoa",
        user_id,
        {"role_id": role_id, "name": hien_tai["name"], "actions": list(hien_tai["actions"])},
    )
