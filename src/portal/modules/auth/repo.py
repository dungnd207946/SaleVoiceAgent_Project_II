"""SQL nghiệp vụ của module auth: đọc user và workspace của họ.

KHÔNG chứa `doc_quyen` — truy vấn đó ở `portal/core/auth/repo.py`, vì `require()`
(ở core) cần nó và core không được phụ thuộc modules. Chia theo AI CẦN, không
theo bảng nào.

Mọi hàm nhận `conn` từ caller, không tự lấy kết nối: caller quyết định giao dịch.

Không dùng tenant_conn() ở đây — `users`/`memberships` là control-plane, và muốn
đọc membership để BIẾT tenant thì đã phải biết tenant trước (vòng tròn).
"""

from dataclasses import dataclass
from datetime import datetime

import asyncpg

from portal.core.avatar import avatar_data_uri
from portal.modules.auth.contracts import (
    MemberOut,
    MembershipIn,
    MembershipOut,
    UserDetailOut,
    UserListItemOut,
    WorkspaceOut,
)

# Vị từ "membership còn hiệu lực" — MỘT chỗ, ba truy vấn dùng.
# Viết lại bằng tay ở mỗi truy vấn là ba cơ hội quên `expires_at`, và quên nó thì
# một vé hỗ trợ đã hết hạn vẫn hiện trên switcher (hoặc vẫn cho vào). Cùng vị từ
# này có ở core/auth/repo.doc_quyen (trong `ON`, không `WHERE` — xem docstring
# của nó) — hai file, vì core không import modules.
_CON_HIEU_LUC = "(m.expires_at IS NULL OR m.expires_at > now())"


@dataclass(frozen=True, slots=True)
class HangUser:
    id: str
    email: str
    password_hash: str | None
    """NULL đúng khi `lifecycle = 'pending'` — CHECK song điều kiện ở migration 0103.

    M2a khai `str` vì lúc đó user chỉ sinh ra từ seed script và seed luôn có mật
    khẩu. Thư mời đảo điều đó: hàng users tồn tại TRƯỚC khi có mật khẩu. Mọi
    người gọi `pw.kiem()` phải kiểm None trước — xem `service.dang_nhap`.
    """
    name: str
    lifecycle: str
    phone: str | None
    job_title: str | None
    avatar_seed: str | None
    """Seed avatar user TỰ CHỌN (màn Hồ sơ, migration 0952). NULL = suy từ `name`."""


# Hai truy vấn user đọc cùng một tập cột — khai một chỗ để chúng không lệch nhau
# lúc thêm cột, vì HangUser dựng bằng **dict(r) và thiếu cột là TypeError lúc chạy.
_COT_USER = "id, email, password_hash, name, lifecycle, phone, job_title, avatar_seed"


async def tim_user_theo_email(conn: asyncpg.Connection, email: str) -> HangUser | None:
    """`email` phải đã được chuẩn hoá lower(trim()) bởi service — xem spec §3.3.

    Không tự `lower()` ở đây: cột có CHECK `email = lower(email)`, nên chuẩn hoá
    hai lần ở hai tầng là hai chỗ phải giữ đồng bộ. Biên nhập là service.
    """
    r = await conn.fetchrow(
        f"SELECT {_COT_USER} FROM control.users WHERE email = $1",
        email,
    )
    return HangUser(**dict(r)) if r else None


async def tim_user_theo_id(conn: asyncpg.Connection, user_id: str) -> HangUser | None:
    """Dùng bởi `/me`: phiên chỉ giữ user_id, hồ sơ đọc lại từ DB mỗi request.

    Không cache tên/email vào bản ghi phiên — cùng lý lẽ với việc không cache
    quyền (xem core/auth/session.py): một bản sao trong Redis là một bản sao có
    ngày lệch, và người dùng đổi tên xong vẫn thấy tên cũ tới khi hết phiên.
    """
    r = await conn.fetchrow(
        f"SELECT {_COT_USER} FROM control.users WHERE id = $1",
        user_id,
    )
    return HangUser(**dict(r)) if r else None


async def liet_ke_workspace(conn: asyncpg.Connection, user_id: str) -> list[WorkspaceOut]:
    """Workspace user thấy được. Sắp theo tên để sidebar ổn định.

    MỘT ĐƯỜNG DUY NHẤT: membership còn hiệu lực. Trước 2026-08-15 có nhánh thứ
    hai — `org_role = 'owner'` thấy MỌI workspace trong tổ chức mà không cần một
    dòng memberships nào, để tránh quả trứng-và-gà "người cấp membership phải tự
    cấp cho mình trước". Tầng tổ chức đã bị bỏ và quả trứng-và-gà được giải ở chỗ
    khác: `workspace.service.tao()` ghi luôn membership 'Quản trị' cho người tạo.

    Rỗng là HỢP LỆ — user vừa tự đăng ký chưa thuộc workspace nào. Chỗ gọi không
    được raise vì điều đó (xem `service.dung_session_out`).

    `lifecycle <> 'closed'` KHÔNG phải cho đường xoá workspace — đường đó XOÁ CỨNG
    (`DELETE FROM control.tenants`) nên hàng `memberships` biến mất theo cascade và
    câu `JOIN` này tự nhiên không thấy gì. Vị từ ở đây phục vụ ca ĐÌNH CHỈ/ĐÓNG BẰNG
    TAY: `tenants.lifecycle` nhận `'suspended'|'closed'` (CHECK của 0002) và không
    đường code nào sinh ra hai giá trị đó — chỉ một câu `UPDATE` của ops. Thiếu vị từ
    thì một workspace bị đóng tay vẫn nằm trên switcher, bấm vào thì `require()` đáp
    403 `WORKSPACE_DA_DONG`, và người dùng thấy một mục nav dẫn tới một bức tường.

    ⚠ `modules/workspace/repo.workspace_dau_tien_con_lai` PHẢI khớp cả hai vị từ
    này — nó trả lời "còn workspace nào khác không" cho đường xoá, và lệch một vế
    nghĩa là người dùng xoá được workspace cuối cùng qua đúng cái cửa dựng ra để chặn.
    """
    rows = await conn.fetch(
        f"""SELECT t.id, t.name
              FROM control.memberships m
              JOIN control.tenants t ON t.id = m.tenant_id
             WHERE m.user_id = $1 AND {_CON_HIEU_LUC}
               AND t.lifecycle <> 'closed'
             ORDER BY 2""",
        user_id,
    )
    # slug = id: xem docstring WorkspaceOut.slug. plan = None: xem WorkspaceOut.plan.
    return [WorkspaceOut(id=r["id"], slug=r["id"], name=r["name"], plan=None) for r in rows]


async def liet_ke_thanh_vien(conn: asyncpg.Connection, tenant_id: str) -> list[MemberOut]:
    """HAI LOẠI HÀNG trong một danh sách: thành viên thật, và lời mời đang treo.

    VÌ SAO GỘP (spec §5.2 + quyết định người yêu cầu 2026-08-22). Sau thay đổi này
    một email chưa có tài khoản KHÔNG còn hàng `users` nào — nên nếu bảng chỉ đọc
    `memberships` thì một Quản trị vừa mời 10 người sẽ thấy một bảng không đổi, và
    không có chỗ nào để bấm "gửi lại". Một bảng thứ hai bên dưới là thứ docstring
    `UserAdmin.tsx` ghi là đã cố ý cắt bỏ 2026-08-10.

    `UNION ALL` chứ không `UNION`: không có hàng nào trùng nhau để khử, và `UNION`
    trần bắt Postgres sort/hash toàn bộ kết quả cho một phép khử không có việc.

    ⚠ MỘT NGƯỜI CÓ THỂ HIỆN HAI LẦN nếu vừa là thành viên vừa có lời mời treo.
    Đường mời chặn ca đó bằng `USER_ALREADY_MEMBER`, nhưng chặn ở cửa không phải
    là bất biến của bảng — ai đó được thêm bằng đường khác trong lúc lời mời còn
    treo thì hai hàng cùng hiện. Chấp nhận: hiện hai hàng là NÓI THẬT về hai sự
    thật đang có, còn khử một hàng ở đây là giấu mất cái link đang lưu hành.
    """
    rows = await conn.fetch(
        f"""SELECT 'member' AS kind, u.id AS user_id, u.name, u.email, m.role_id, r.name AS role,
                   u.lifecycle, NULL::timestamptz AS invited_at, NULL::timestamptz AS expires_at,
                   u.avatar_seed
              FROM control.memberships m
              JOIN control.users u ON u.id = m.user_id
              JOIN control.roles r ON r.id = m.role_id
             WHERE m.tenant_id = $1 AND {_CON_HIEU_LUC}
            UNION ALL
            SELECT 'invite', i.user_id, u.name, i.email, i.role_id, r.name,
                   u.lifecycle, i.created_at, i.expires_at,
                   NULL::text
              FROM control.invites i
              JOIN control.roles r ON r.id = i.role_id
              LEFT JOIN control.users u ON u.id = i.user_id
             WHERE i.tenant_id = $1 AND i.used_at IS NULL AND i.expires_at > now()
             ORDER BY kind DESC, name NULLS LAST, email""",
        tenant_id,
    )
    return [
        MemberOut(
            kind=r["kind"],
            userId=r["user_id"],
            name=r["name"],
            email=r["email"],
            roleId=r["role_id"],
            role=r["role"],
            lifecycle=r["lifecycle"],
            invitedAt=r["invited_at"].isoformat() if r["invited_at"] else None,
            expiresAt=r["expires_at"].isoformat() if r["expires_at"] else None,
            # Cùng công thức với `/me` (service.py) — bảng phải hiện ĐÚNG avatar
            # người đó đã set, không phải một bản FE tự vẽ. Hàng `invite` = None
            # (FE hiện phong bì, xem docstring `MemberOut.avatar`).
            avatar=avatar_data_uri(r["avatar_seed"] or r["name"]) if r["kind"] == "member" else None,
        )
        for r in rows
    ]


# ═══════════════════════════════════════════════════════════════════════════════
#  M2c — seam `/members` GHI (mời · đổi vai trò · gỡ) — chỉ contract + repo ở đây,
#  route/service dựng ở task sau trên nền các hàm dưới đây.
# ═══════════════════════════════════════════════════════════════════════════════


async def role_ton_tai(conn: asyncpg.Connection, role_id: str) -> bool:
    """Vai trò TOÀN CỤC từ 0105 — không còn phạm vi tổ chức để kiểm.

    Vẫn phải kiểm tồn tại: FK sẽ chặn, nhưng bằng `ForeignKeyViolationError` -> 500
    thay vì 422 có tên field. Cùng lý lẽ `loc_role_khong_ton_tai` đã ghi.
    """
    return await conn.fetchval("SELECT 1 FROM control.roles WHERE id = $1", role_id) is not None


async def them_membership(conn: asyncpg.Connection, *, user_id: str, tenant_id: str, role_id: str) -> None:
    """MỘT hàng. KHÔNG dùng `dat_lai_membership` — hàm đó THAY THẾ TOÀN BỘ.

    `ON CONFLICT DO UPDATE`: mời lại một người đã ở trong workspace là đổi vai trò
    của họ, không phải một lỗi. PK là (user_id, tenant_id).
    """
    await conn.execute(
        """INSERT INTO control.memberships (user_id, tenant_id, role_id)
           VALUES ($1, $2, $3)
           ON CONFLICT (user_id, tenant_id) DO UPDATE SET role_id = EXCLUDED.role_id""",
        user_id,
        tenant_id,
        role_id,
    )


async def doi_vai_tro_thanh_vien(conn: asyncpg.Connection, *, user_id: str, tenant_id: str, role_id: str) -> bool:
    """False = không có hàng nào khớp (không phải thành viên workspace này).

    Vị từ `tenant_id` là thứ giữ đường này chỉ chạm ĐÚNG một workspace — KHÔNG
    được thay bằng `dat_lai_membership` (hàm đó DELETE/INSERT lại TOÀN BỘ hàng
    của user, xoá sạch vai trò ở mọi workspace khác — bug mất dữ liệu 2026-08-06).
    Xem `tests/modules/auth/test_repo_thanh_vien.py::test_doi_vai_tro_chi_cham_MOT_workspace`.
    """
    r = await conn.execute(
        "UPDATE control.memberships SET role_id = $3 WHERE user_id = $1 AND tenant_id = $2",
        user_id,
        tenant_id,
        role_id,
    )
    return r != "UPDATE 0"


async def go_thanh_vien(conn: asyncpg.Connection, *, user_id: str, tenant_id: str) -> bool:
    """Gỡ khỏi MỘT workspace. KHÔNG xoá `control.users` — xoá tài khoản là việc
    khác, và hiện không có chủ (khối `/users*` đang tắt sau 0106)."""
    r = await conn.execute("DELETE FROM control.memberships WHERE user_id = $1 AND tenant_id = $2", user_id, tenant_id)
    return r != "DELETE 0"


async def doc_thanh_vien(conn: asyncpg.Connection, *, tenant_id: str, user_id: str) -> MemberOut | None:
    """Cùng cú JOIN với `liet_ke_thanh_vien`, một hàng — cho response của PATCH.

    PHẢI trả CÙNG tập trường với `liet_ke_thanh_vien`: FE nhận response của PATCH
    rồi thay hàng tương ứng trong bảng. Thiếu một trường ở đây thì đúng hàng vừa
    đổi vai trò bị mất cột đó, còn các hàng khác thì không — một lỗi chỉ hiện ở
    một hàng duy nhất, sau một hành động duy nhất.
    """
    r = await conn.fetchrow(
        f"""SELECT u.id, u.name, u.email, u.lifecycle, m.role_id, r.name AS role, u.avatar_seed
              FROM control.memberships m
              JOIN control.users u ON u.id = m.user_id
              JOIN control.roles r ON r.id = m.role_id
             WHERE m.tenant_id = $1 AND m.user_id = $2 AND {_CON_HIEU_LUC}""",
        tenant_id,
        user_id,
    )
    if r is None:
        return None
    return MemberOut(
        kind="member",
        userId=r["id"],
        name=r["name"],
        email=r["email"],
        roleId=r["role_id"],
        role=r["role"],
        lifecycle=r["lifecycle"],
        invitedAt=None,
        expiresAt=None,
        avatar=avatar_data_uri(r["avatar_seed"] or r["name"]),
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  M2b — ghi user · membership · thư mời
# ═══════════════════════════════════════════════════════════════════════════════
#
# PHẠM VI TỔ CHỨC ĐÃ BỎ (2026-08-15). Trước đây mọi hàm dưới đây nhận `org_id` và
# đưa nó vào WHERE hoặc vào giá trị INSERT — đó là cách phạm vi tổ chức được cưỡng
# chế ở tầng SQL. Không còn tổ chức thì không còn phạm vi nào để cưỡng chế: các
# hàm này tra thẳng bằng `id`.
#
# ⚠ HỆ QUẢ: chúng KHÔNG còn tự giới hạn dữ liệu người gọi thấy được. Toàn bộ khối
# này chỉ phục vụ `/users*`, và `/users*` bị đóng bằng cờ `USERS_ADMIN_ENABLED`
# (mặc định False) đúng vì lý do đó — xem `quan_tri_user._cong_users_admin()`.
#
# `MembershipOut.expiresAt` KHÔNG dùng vị từ `_CON_HIEU_LUC`: màn admin phải thấy
# cả dòng đã hết hạn để biết vì sao người đó mất quyền. Ẩn nó đi thì hàng biến
# mất và admin cấp lại một dòng thứ hai đúng như dòng đang có.


async def liet_ke_user(conn: asyncpg.Connection) -> list[UserListItemOut]:
    """Mọi user, kèm SỐ workspace được cấp (không kèm danh sách).

    `LEFT JOIN` + `COUNT(m.tenant_id)`: user chưa có membership nào vẫn phải hiện
    — sau khi mở tự đăng ký, đó là trạng thái của MỌI người vừa tạo tài khoản.
    `INNER JOIN` sẽ làm họ tàng hình.
    """
    rows = await conn.fetch(
        f"""SELECT u.id, u.email, u.name, u.job_title, u.lifecycle,
                   COUNT(m.tenant_id) FILTER (WHERE {_CON_HIEU_LUC}) AS so_ws
              FROM control.users u
              LEFT JOIN control.memberships m ON m.user_id = u.id
             GROUP BY u.id, u.email, u.name, u.job_title, u.lifecycle
             ORDER BY u.name"""
    )
    return [
        UserListItemOut(
            id=r["id"],
            email=r["email"],
            name=r["name"],
            jobTitle=r["job_title"],
            lifecycle=r["lifecycle"],
            workspaceCount=r["so_ws"],
        )
        for r in rows
    ]


async def liet_ke_membership(conn: asyncpg.Connection, user_id: str) -> list[MembershipOut]:
    """Membership của MỘT user, kèm tên workspace. Gồm cả dòng đã hết hạn.

    JOIN `tenants` để lấy tên: FE không đối chiếu id với `session.workspaces` được
    — danh sách đó là workspace của ADMIN đang xem, không phải của user đang sửa.
    """
    rows = await conn.fetch(
        """SELECT m.tenant_id, t.name, m.role_id, r.name AS role, m.expires_at
             FROM control.memberships m
             JOIN control.tenants t ON t.id = m.tenant_id
             JOIN control.roles r ON r.id = m.role_id
            WHERE m.user_id = $1
            ORDER BY t.name""",
        user_id,
    )
    return [
        MembershipOut(
            workspaceId=r["tenant_id"],
            workspaceName=r["name"],
            roleId=r["role_id"],
            role=r["role"],
            expiresAt=r["expires_at"],
        )
        for r in rows
    ]


async def doc_chi_tiet_user(conn: asyncpg.Connection, user_id: str) -> UserDetailOut | None:
    """None = không có user đó.

    Hai truy vấn, không một truy vấn có JOIN: hồ sơ là một hàng còn membership là
    n hàng, và gộp chúng lại nghĩa là mỗi trường hồ sơ lặp n lần rồi phải gỡ ra.
    """
    r = await conn.fetchrow(
        """SELECT id, email, name, phone, job_title, lifecycle, created_at
             FROM control.users WHERE id = $1""",
        user_id,
    )
    if r is None:
        return None
    return UserDetailOut(
        id=r["id"],
        email=r["email"],
        name=r["name"],
        phone=r["phone"],
        jobTitle=r["job_title"],
        lifecycle=r["lifecycle"],
        createdAt=r["created_at"],
        memberships=await liet_ke_membership(conn, r["id"]),
    )


async def email_da_dung(conn: asyncpg.Connection, email: str) -> bool:
    """Kiểm TOÀN CỤC, không theo org — UNIQUE trên `users.email` là toàn cục (0100).

    Email là khoá đăng nhập: `tim_user_theo_email` không có tham số org, nên một
    email ở hai tổ chức là một câu hỏi không có câu trả lời đúng.
    """
    return await conn.fetchval("SELECT 1 FROM control.users WHERE email = $1", email) is not None


async def id_da_dung(conn: asyncpg.Connection, user_id: str) -> bool:
    """`users.id` là PK toàn cục — dùng bởi phép sinh id ở service."""
    return await conn.fetchval("SELECT 1 FROM control.users WHERE id = $1", user_id) is not None


async def loc_workspace_khong_ton_tai(conn: asyncpg.Connection, workspace_ids: list[str]) -> list[str]:
    """Trả những id KHÔNG có trong `control.tenants`. Rỗng = tất cả hợp lệ.

    Thay `loc_workspace_ngoai_to_chuc`: không còn tổ chức thì "ngoài tổ chức"
    không còn nghĩa; câu hỏi duy nhất còn lại là "có tồn tại không".

    GỌI TRƯỚC MỌI INSERT membership. FK cũng chặn, nhưng bằng
    `ForeignKeyViolationError` -> 500; ở đây nó thành 422 có tên workspace cụ thể.

    Trả cái KHÔNG hợp lệ chứ không trả cái hợp lệ: người gọi cần đặt tên thứ sai
    vào thông điệp lỗi, và `set(gửi) - set(hợp lệ)` ở phía gọi là một phép trừ
    nữa để làm sai.
    """
    if not workspace_ids:
        return []
    hop_le = {
        r["id"] for r in await conn.fetch("SELECT id FROM control.tenants WHERE id = ANY($1::text[])", workspace_ids)
    }
    return [w for w in workspace_ids if w not in hop_le]


async def loc_role_khong_ton_tai(conn: asyncpg.Connection, role_ids: list[str]) -> list[str]:
    """Trả những `role_id` KHÔNG có trong `control.roles`. Rỗng = tất cả hợp lệ.

    Thay `loc_role_ngoai_to_chuc`: vai trò đã TOÀN CỤC từ 2026-08-15 (một bộ 4
    dùng chung cho mọi workspace), nên mọi `role_id` tồn tại đều hợp lệ. Mã lỗi
    đi kèm đổi `ROLE_NOT_IN_ORG` -> `ROLE_NOT_FOUND`.

    GỌI TRƯỚC MỌI INSERT membership, cùng giao dịch — xem `dat_lai_membership`.
    """
    if not role_ids:
        return []
    hop_le = {r["id"] for r in await conn.fetch("SELECT id FROM control.roles WHERE id = ANY($1::text[])", role_ids)}
    return [r for r in role_ids if r not in hop_le]


async def tao_user_tu_dang_ky(conn: asyncpg.Connection, *, user_id: str, email: str, name: str) -> HangUser:
    """Tự đăng ký: user ra đời `pending` + `password_hash = NULL`.

    ĐỔI 2026-08-17: trước đây tạo thẳng `active` với mật khẩu từ form. Nay mật
    khẩu đặt qua link trong thư, nên CHECK `users_co_duong_dang_nhap_check`
    (0103, đổi tên + nới MỘT CHIỀU ở 0108 để user Google-only khỏi cần mật khẩu
    — chiều `active ⇒ có mật khẩu` đã bỏ, chiều `pending ⇒ password_hash IS
    NULL` vẫn còn) vẫn buộc `pending` đi cùng NULL — không có cách nào tạo sai.
    """
    r = await conn.fetchrow(
        f"""INSERT INTO control.users (id, email, name, password_hash, lifecycle)
                 VALUES ($1, $2, $3, NULL, 'pending')
              RETURNING {_COT_USER}""",
        user_id,
        email,
        name,
    )
    return HangUser(**dict(r))


async def tao_user(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    email: str,
    name: str,
    phone: str | None,
    job_title: str | None,
) -> None:
    """INSERT một user CHỜ MỜI: `lifecycle = 'pending'`, `password_hash = NULL`.

    Hai giá trị đó khai TƯỜNG MINH ở đây dù cột `lifecycle` có DEFAULT 'active':
    default là 'active', và dựa vào default ở chỗ này sẽ tạo ra một user active
    không mật khẩu. Trước 0108, CHECK song điều kiện của 0103 chặn đúng ca đó —
    nổ ở đây thành 500 chứ không thành một hàng sai. 0108 đã BỎ đúng chiều này
    (`users_co_duong_dang_nhap_check` giờ chỉ còn ép MỘT CHIỀU `pending ⇒ NULL`,
    vì user Google-only là `active` mà không mật khẩu) — CHECK không còn là
    lưới đỡ cho lỗi này nữa, nên khai TƯỜNG MINH ở đây quan trọng hơn trước:
    quên nó giờ lặng lẽ tạo một user active không mật khẩu, không còn nổ ngay.
    """
    await conn.execute(
        """INSERT INTO control.users
               (id, email, name, phone, job_title, lifecycle, password_hash)
           VALUES ($1, $2, $3, $4, $5, 'pending', NULL)""",
        user_id,
        email,
        name,
        phone,
        job_title,
    )


async def sua_ho_so(
    conn: asyncpg.Connection,
    *,
    user_id: str,
    name: str,
    phone: str | None,
    job_title: str | None,
    lifecycle: str | None,
) -> None:
    """`lifecycle = None` -> giữ nguyên (COALESCE). KHÔNG sửa email/id."""
    await conn.execute(
        """UPDATE control.users
              SET name = $2, phone = $3, job_title = $4,
                  lifecycle = COALESCE($5, lifecycle)
            WHERE id = $1""",
        user_id,
        name,
        phone,
        job_title,
        lifecycle,
    )


async def dat_lai_membership(conn: asyncpg.Connection, *, user_id: str, danh_sach: list[MembershipIn]) -> None:
    """THAY THẾ TOÀN BỘ membership của user (spec §4.4).

    GỌI TRONG MỘT GIAO DỊCH với mọi thứ khác — giữa DELETE và INSERT, user không
    có quyền nào, và một request song song lọt vào khoảng đó sẽ thấy họ mất hết
    workspace. `conn.transaction()` ở service đóng khoảng đó lại.

    Vì sao thay thế chứ không patch từng dòng: form là một bảng người dùng sửa
    trực tiếp. Diễn dịch nó thành chuỗi add/remove/update ở FE là đặt logic hoà
    giải vào chỗ không có giao dịch, và hai tab mở cùng lúc trộn ra một tập quyền
    không ai chọn.

    Ghi `role_id` (migration 0104 + quyết định 2026-08-04 spec §4.0), không phải
    tên vai trò — người gọi PHẢI đã chạy `loc_role_khong_ton_tai` trong CÙNG giao
    dịch trước khi gọi hàm này, giống hệt `loc_workspace_khong_ton_tai` cho
    `workspaceId`. Hàm này không tự kiểm lại: FK `role_id -> roles(id)` (0105) là
    lưới cuối, không phải lưới đầu.
    """
    await conn.execute("DELETE FROM control.memberships WHERE user_id = $1", user_id)
    if not danh_sach:
        return
    await conn.executemany(
        """INSERT INTO control.memberships (user_id, tenant_id, role_id, expires_at)
           VALUES ($1, $2, $3, $4)""",
        [(user_id, m.workspaceId, m.role_id, m.expiresAt) for m in danh_sach],
    )


async def xoa_user(conn: asyncpg.Connection, *, user_id: str) -> None:
    """CASCADE gỡ luôn membership và thư mời (0105 dựng lại FK đơn cột, vẫn CASCADE).

    Người gọi đã kiểm `lifecycle = 'pending'` — xem `loi.user_da_nhan_moi()`.
    """
    await conn.execute("DELETE FROM control.users WHERE id = $1", user_id)


# --- thư mời -----------------------------------------------------------------


async def ghi_loi_moi_dang_ky(
    conn: asyncpg.Connection,
    *,
    token_hash: str,
    user_id: str,
    email: str,
    expires_at: datetime,
    created_by: str,
) -> None:
    """Token TỰ ĐĂNG KÝ (`POST /auth/register`) — `tenant_id`/`role_id` đều NULL.

    HAI HÀM CHỨ KHÔNG MỘT. 0952 thay `UNIQUE (user_id)` bằng HAI chỉ mục bộ phận,
    và `ON CONFLICT` phải nêu ĐÚNG chỉ mục nó suy vào — gồm cả vị từ `WHERE`. Một
    hàm với một tham số `tenant_id: str | None` sẽ phải rẽ nhánh chuỗi SQL bên
    trong, tức viết hai câu lệnh rồi giả vờ là một.
    """
    await conn.execute(
        """INSERT INTO control.invites (token_hash, user_id, email, tenant_id, role_id, expires_at, created_by)
           VALUES ($1, $2, $3, NULL, NULL, $4, $5)
           ON CONFLICT (email) WHERE tenant_id IS NULL DO UPDATE
               SET token_hash = EXCLUDED.token_hash,
                   user_id    = EXCLUDED.user_id,
                   expires_at = EXCLUDED.expires_at,
                   created_by = EXCLUDED.created_by,
                   created_at = now(),
                   used_at    = NULL""",
        token_hash,
        user_id,
        email,
        expires_at,
        created_by,
    )


async def ghi_loi_moi_workspace(
    conn: asyncpg.Connection,
    *,
    token_hash: str,
    email: str,
    user_id: str | None,
    tenant_id: str,
    role_id: str,
    expires_at: datetime,
    created_by: str,
) -> None:
    """Token MỜI vào một workspace. `user_id=None` = email chưa có tài khoản.

    `user_id` NULL ĐƯỢC là toàn bộ điểm của 0952: lời mời tồn tại TRƯỚC tài khoản,
    nên nó không thể neo vào tài khoản.

    `role_id` phải lưu ở đây, không suy từ `memberships`: `memberships` là bảng
    lời mời này sẽ GHI VÀO lúc được nhận, không phải bảng nó đọc từ.

    Khoá nghiệp vụ là (email, workspace): mời lại một người ở CÙNG workspace giết
    token cũ (đúng — họ chỉ cần một link), còn mời họ vào workspace KHÁC là một
    hàng khác (`UNIQUE (user_id)` cũ chặn đúng ca này, và đó là lỗi).

    `used_at = NULL` khai TƯỜNG MINH trong DO UPDATE — mời lại một email có hàng cũ
    đã dùng thì token mới sinh ra đã ở trạng thái đã-dùng, và người nhận ăn 404.
    """
    await conn.execute(
        """INSERT INTO control.invites (token_hash, user_id, email, tenant_id, role_id, expires_at, created_by)
           VALUES ($1, $2, $3, $4, $5, $6, $7)
           ON CONFLICT (email, tenant_id) WHERE tenant_id IS NOT NULL DO UPDATE
               SET token_hash = EXCLUDED.token_hash,
                   user_id    = EXCLUDED.user_id,
                   role_id    = EXCLUDED.role_id,
                   expires_at = EXCLUDED.expires_at,
                   created_by = EXCLUDED.created_by,
                   created_at = now(),
                   used_at    = NULL""",
        token_hash,
        user_id,
        email,
        tenant_id,
        role_id,
        expires_at,
        created_by,
    )


@dataclass(frozen=True, slots=True)
class HangLoiMoi:
    user_id: str | None
    """`None` ⇔ `invite_new` — email chưa có tài khoản. Người gọi PHẢI rẽ nhánh:
    ba trong bốn chỗ dùng giá trị này để UPDATE một hàng `users` chưa tồn tại."""
    email: str
    name: str | None
    """`None` cùng lúc với `user_id` — không có hàng `users` nào mang một cái tên."""
    tenant_id: str | None
    role_id: str | None
    """`None` ⇔ `tenant_id is None` (CHECK `invites_vai_tro_theo_pham_vi`)."""
    ten_workspace: str | None


async def doc_loi_moi_con_hieu_luc(conn: asyncpg.Connection, token_hash: str) -> HangLoiMoi | None:
    """None = token sai HOẶC đã dùng HOẶC hết hạn HOẶC sai trạng thái tài khoản.

    Gộp ở TẦNG SQL, không ở tầng service: vị từ nằm trong WHERE thì không có đường
    gọi thứ hai nào bỏ qua nó được.

    BA NHÁNH TRẠNG THÁI TÀI KHOẢN, thay cho một vế `u.lifecycle = 'pending'` duy
    nhất (bản trước 2026-08-22):
      · `signup`          — ĐÒI `pending`. Chiều cũ, vẫn đúng: một hàng invite chưa
        dùng trên một user đã `active` không được phép đặt lại mật khẩu của họ.
      · `invite_new`      — KHÔNG có user để hỏi. Chính là ca mới.
      · `invite_existing` — ĐÒI `active`. Vế cũ loại đúng ca này (user đã active),
        tức trước 0952 nhánh này không thể tồn tại.

    `LEFT JOIN` chứ không `JOIN`: `JOIN` làm mọi hàng `user_id IS NULL` biến mất —
    một `None` im lặng ở đúng nhánh mà cả thay đổi này tồn tại vì nó.
    """
    r = await conn.fetchrow(
        """SELECT i.user_id, i.email, u.name, i.tenant_id, i.role_id, t.name AS ten_workspace
             FROM control.invites i
             LEFT JOIN control.users u   ON u.id = i.user_id
             LEFT JOIN control.tenants t ON t.id = i.tenant_id
            WHERE i.token_hash = $1
              AND i.used_at IS NULL
              AND i.expires_at > now()
              AND (
                    (i.tenant_id IS NULL     AND u.lifecycle = 'pending')
                 OR (i.tenant_id IS NOT NULL AND i.user_id IS NULL)
                 OR (i.tenant_id IS NOT NULL AND u.lifecycle = 'active')
              )""",
        token_hash,
    )
    if r is None:
        return None
    return HangLoiMoi(
        user_id=r["user_id"],
        email=r["email"],
        name=r["name"],
        tenant_id=r["tenant_id"],
        role_id=r["role_id"],
        ten_workspace=r["ten_workspace"],
    )


async def doc_loi_moi_treo(conn: asyncpg.Connection, *, tenant_id: str, email: str) -> asyncpg.Record | None:
    """Lời mời đang treo của một email ở một workspace — cho hai đường ADMIN
    (gửi lại · thu hồi), nơi định danh là email chứ không phải token."""
    return await conn.fetchrow(
        """SELECT token_hash, user_id, email, role_id
             FROM control.invites
            WHERE tenant_id = $1 AND email = $2 AND used_at IS NULL AND expires_at > now()""",
        tenant_id,
        email,
    )


async def thu_hoi_loi_moi(conn: asyncpg.Connection, *, tenant_id: str, email: str) -> bool:
    """XOÁ hàng, không đánh dấu `used_at`. `used_at` nghĩa "đã có người nhận" —
    dùng nó cho việc admin rút lại là ghi một sự thật sai vào bảng.

    `expires_at > now()` khai TƯỜNG MINH ở đây, khớp Y HỆT vị từ của
    `doc_loi_moi_treo` (sibling — "gửi lại"): QUYẾT ĐỊNH có chủ ý, không phải
    sót. Một hàng đã hết hạn không còn là một lời mời ĐANG TREO — `liet_ke_thanh_vien`
    cũng lọc nó ra khỏi `GET /members` bằng đúng vị từ này, nên nó không hiện ở
    đâu để admin bấm "Thu hồi" từ giao diện; để nó SỐNG SÓT một API riêng (không
    vị từ hạn) là hai đường đọc CÙNG một khái niệm ("lời mời đang treo") trả lời
    khác nhau, và admin gọi thẳng API sẽ thấy revoke "thành công" (204) trên một
    hàng mà resend đã 404 `INVITE_NOT_FOUND` — hai kết quả trái nhau cho cùng một
    câu hỏi "hàng này còn treo không". Dọn rác hết hạn là việc của TTL/job khác,
    không phải lý do để endpoint này nhận một hàng đã chết.

    False = không có gì để thu hồi (admin bấm hai lần, lời mời vừa được nhận,
    hoặc lời mời đã hết hạn).
    """
    r = await conn.execute(
        "DELETE FROM control.invites WHERE tenant_id = $1 AND email = $2 AND used_at IS NULL AND expires_at > now()",
        tenant_id,
        email,
    )
    return r != "DELETE 0"


async def la_thanh_vien(conn: asyncpg.Connection, *, user_id: str, tenant_id: str) -> bool:
    """KHÔNG lọc theo `_CON_HIEU_LUC`: một membership hết hạn vẫn là một HÀNG, và
    `them_membership` sẽ UPSERT lên nó. Câu hỏi ở đây là "có hàng không", không
    phải "có quyền không"."""
    return await conn.fetchval(
        "SELECT EXISTS (SELECT 1 FROM control.memberships WHERE user_id = $1 AND tenant_id = $2)",
        user_id,
        tenant_id,
    )


async def doc_ten_workspace(conn: asyncpg.Connection, tenant_id: str) -> str | None:
    return await conn.fetchval("SELECT name FROM control.tenants WHERE id = $1", tenant_id)


async def nhan_loi_moi_dat_mat_khau(
    conn: asyncpg.Connection, *, token_hash: str, user_id: str, password_hash: str
) -> None:
    """`signup` — đặt mật khẩu + `active`, rồi đánh dấu token đã dùng.

    ĐỔI TÊN từ `nhan_loi_moi` (2026-08-22): từ nay có BA cách nhận một lời mời và
    chỉ một trong ba đặt mật khẩu cho một user đã tồn tại. Một cái tên trần
    (`nhan_loi_moi`) ở tầng repo giờ là cái tên của việc mà tầng trên làm, không
    phải việc mà hàm này làm.
    """
    await conn.execute(
        "UPDATE control.users SET password_hash = $2, lifecycle = 'active' WHERE id = $1",
        user_id,
        password_hash,
    )
    await danh_dau_da_dung(conn, token_hash=token_hash)


async def danh_dau_da_dung(conn: asyncpg.Connection, *, token_hash: str) -> None:
    """Thiếu lệnh này là để token sống tiếp sau khi việc đã xong — ai đọc được link
    vẫn dùng lại được. Người gọi mở giao dịch."""
    await conn.execute("UPDATE control.invites SET used_at = now() WHERE token_hash = $1", token_hash)


async def tao_user_da_kich_hoat(
    conn: asyncpg.Connection, *, user_id: str, email: str, name: str, password_hash: str
) -> None:
    """`invite_new` — user ra đời `active` VÀ có mật khẩu, trong cùng một lệnh.

    KHÔNG đi qua `pending`. `lifecycle='pending'` nghĩa "chưa đặt mật khẩu" (CHECK
    `users_co_duong_dang_nhap_check` ép `pending ⇒ password_hash IS NULL`), mà ở
    nhánh này mật khẩu đã có trong tay — tạo `pending` rồi UPDATE ngay sau là hai
    lệnh nói hai điều trái nhau về cùng một hàng.

    KHÁC `tao_user()` (mời kiểu cũ: `pending` + NULL) và khác `tao_user_tu_dang_ky()`
    (`pending` + NULL). Ba hàm vì ba trạng thái ra đời khác nhau, không vì ba chỗ gọi.
    """
    await conn.execute(
        """INSERT INTO control.users (id, email, name, password_hash, lifecycle)
           VALUES ($1, $2, $3, $4, 'active')""",
        user_id,
        email,
        name,
        password_hash,
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  M2b — vai trò (spec §4, quyết định 2026-08-04) — migration 0104
# ═══════════════════════════════════════════════════════════════════════════════


async def liet_ke_action(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT code, group_name, label_vi, label_en, sort_order
             FROM control.actions ORDER BY sort_order"""
    )


# VAI TRÒ ĐÃ TOÀN CỤC (2026-08-15, migration 0105). Trước đây mọi hàm dưới đây
# nhận `org_id` và đưa nó vào WHERE — cách ly tổ chức nằm ở tầng SQL để không phụ
# thuộc việc người gọi nhớ kiểm trước. Không còn tổ chức thì không còn gì để cách
# ly: một bộ 4 vai trò dùng chung cho mọi workspace.
#
# ⚠ HỆ QUẢ: ba hàm GHI dưới đây (`tao_vai_tro`, `doi_ten_vai_tro`,
# `dat_action_cua_vai_tro`, `xoa_vai_tro`) sửa vai trò của TOÀN HỆ THỐNG. Đó
# chính là lý do ba endpoint ghi `/roles` bị đóng bằng cờ `ROLES_CRUD_ENABLED`
# (mặc định False) — xem `quan_tri_vai_tro._cong_ghi_vai_tro()`.


async def liet_ke_vai_tro(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Kèm userCount — đếm bằng LEFT JOIN chứ không subquery-per-row.

    Đếm CẢ membership đã hết hạn: xoá vai trò sẽ vỡ FK vì hàng đó vẫn tồn tại,
    nên báo con số nhỏ hơn thực tế là nói dối theo hướng người dùng phát hiện
    bằng một lỗi 409 khó hiểu.
    """
    return await conn.fetch(
        """SELECT r.id, r.name, r.description, count(m.user_id) AS user_count
             FROM control.roles r
             LEFT JOIN control.memberships m ON m.role_id = r.id
            GROUP BY r.id, r.name, r.description
            ORDER BY r.created_at"""
    )


async def doc_vai_tro(conn: asyncpg.Connection, role_id: str) -> asyncpg.Record | None:
    """None = không có vai trò đó ⇒ router ra 404."""
    return await conn.fetchrow(
        """SELECT r.id, r.name, r.description,
                  coalesce(array_agg(ra.action_code)
                           FILTER (WHERE ra.action_code IS NOT NULL), '{}') AS actions
             FROM control.roles r
             LEFT JOIN control.role_actions ra ON ra.role_id = r.id
            WHERE r.id = $1
            GROUP BY r.id, r.name, r.description""",
        role_id,
    )


async def tao_vai_tro(conn: asyncpg.Connection, role_id: str, name: str, description: str | None) -> None:
    await conn.execute(
        "INSERT INTO control.roles (id, name, description) VALUES ($1,$2,$3)",
        role_id,
        name,
        description,
    )


async def doi_ten_vai_tro(conn: asyncpg.Connection, role_id: str, name: str, description: str | None) -> None:
    await conn.execute(
        "UPDATE control.roles SET name = $2, description = $3 WHERE id = $1",
        role_id,
        name,
        description,
    )


async def dat_action_cua_vai_tro(conn: asyncpg.Connection, role_id: str, codes: list[str]) -> None:
    """THAY THẾ TOÀN BỘ. Người gọi phải đang ở trong conn.transaction() — xoá xong
    mà insert hỏng thì vai trò mất sạch quyền, im lặng.
    """
    await conn.execute("DELETE FROM control.role_actions WHERE role_id = $1", role_id)
    if codes:
        await conn.execute(
            """INSERT INTO control.role_actions (role_id, action_code)
                    SELECT r.id, c
                      FROM control.roles r, unnest($2::text[]) AS c
                     WHERE r.id = $1""",
            role_id,
            codes,
        )


async def dem_nguoi_dung_vai_tro(conn: asyncpg.Connection, role_id: str) -> int:
    return await conn.fetchval("SELECT count(*) FROM control.memberships WHERE role_id = $1", role_id)


async def dem_loi_moi_dang_treo_vai_tro(conn: asyncpg.Connection, role_id: str) -> int:
    """Lời mời CÒN SỐNG (`used_at IS NULL AND expires_at > now()`) đang hứa vai
    trò này — cạnh `dem_nguoi_dung_vai_tro` ở trên, không thay nó.

    `invites.role_id` (migration 0952) là FK trần, KHÔNG `ON DELETE` nào — mời ai
    đó một vai trò rồi xoá vai trò đó trước khi họ nhận là để `DELETE FROM
    control.roles` vỡ ở `ForeignKeyViolationError` → 500 ngay tại `invites`, dù
    `dem_nguoi_dung_vai_tro` báo 0 (không ai CÒN GIỮ vai trò này qua
    `memberships` — đúng, vì chưa ai nhận). Guard ở `quan_tri_vai_tro.xoa` phải
    hỏi cả câu này TRƯỚC khi xoá, cùng lý lẽ `loc_action_la` đã ghi: 422 có tên
    thay vì một 500 vô danh.

    Lời mời đã dùng (`used_at`) hoặc đã hết hạn không hứa gì nữa — không tính,
    và cũng không chặn `DELETE` (FK không còn ai đọc tới hàng đó theo nghĩa
    "đang hứa").
    """
    return await conn.fetchval(
        "SELECT count(*) FROM control.invites WHERE role_id = $1 AND used_at IS NULL AND expires_at > now()",
        role_id,
    )


async def xoa_vai_tro(conn: asyncpg.Connection, role_id: str) -> None:
    await conn.execute("DELETE FROM control.roles WHERE id = $1", role_id)


async def loc_action_la(conn: asyncpg.Connection, codes: list[str]) -> str | None:
    """Trả MỘT mã không có trong danh mục, hoặc None — không cam kết đó là mã
    đầu tiên của danh sách gửi lên (truy vấn không có ORDER BY / WITH
    ORDINALITY). Người gọi chỉ cần một tên cụ thể để đưa vào câu 422, không cần
    đúng cái người dùng gõ trước; dùng để ra 422 có tên thay vì một
    ForeignKeyViolationError → 500."""
    if not codes:
        return None
    return await conn.fetchval(
        """SELECT c FROM unnest($1::text[]) AS c
            WHERE NOT EXISTS (SELECT 1 FROM control.actions a WHERE a.code = c)
            LIMIT 1""",
        codes,
    )


# ─── Danh tính ngoài (migration 0108) ────────────────────────────────────────
#
# Giao dịch do NGƯỜI GỌI mở, như mọi thứ khác trong file này. Nhánh 3 ghi hai
# bảng (users + identities) và cả hai phải cùng sống hoặc cùng chết — router bọc.


@dataclass(frozen=True, slots=True)
class HangIdentity:
    provider: str
    subject: str
    user_id: str
    email_tai_provider: str


async def tim_identity(conn: asyncpg.Connection, *, provider: str, subject: str) -> HangIdentity | None:
    """Đường tra CHÍNH của cửa Google — chạy TRƯỚC mọi phép tra theo email.

    Đổi thứ tự là để người dùng đổi email tài khoản Google mất sạch workspace:
    `sub` bất biến còn email thì không. Xem spec §7.
    """
    r = await conn.fetchrow(
        "SELECT provider, subject, user_id, email_tai_provider "
        "FROM control.identities WHERE provider = $1 AND subject = $2",
        provider,
        subject,
    )
    return HangIdentity(**dict(r)) if r else None


async def ghi_identity(
    conn: asyncpg.Connection, *, provider: str, subject: str, user_id: str, email_tai_provider: str
) -> None:
    """KHÔNG `ON CONFLICT DO NOTHING`: người gọi đã tra `tim_identity` và biết
    hàng chưa có. Nuốt xung đột ở đây là nuốt luôn ca «hai user cùng chiếm một
    tài khoản Google» mà PRIMARY KEY sinh ra để chặn.
    """
    await conn.execute(
        "INSERT INTO control.identities (provider, subject, user_id, email_tai_provider, last_login_at) "
        "VALUES ($1, $2, $3, $4, now())",
        provider,
        subject,
        user_id,
        email_tai_provider,
    )


async def cham_dang_nhap_identity(
    conn: asyncpg.Connection, *, provider: str, subject: str, email_tai_provider: str
) -> None:
    """Cập nhật CẢ email hiển thị, không chỉ mốc thời gian: người đổi email tài
    khoản Google vẫn là nhánh 1, và nếu cột này đứng yên thì audit đọc ra một
    email đã chết.
    """
    await conn.execute(
        "UPDATE control.identities SET last_login_at = now(), email_tai_provider = $3 "
        "WHERE provider = $1 AND subject = $2",
        provider,
        subject,
        email_tai_provider,
    )


async def tao_user_tu_google(conn: asyncpg.Connection, *, user_id: str, email: str, name: str) -> HangUser:
    """`active` NGAY, khác `tao_user_tu_dang_ky` (ra `pending` rồi chờ bấm link).

    Cái link đặt mật khẩu tồn tại để chứng minh hộp thư có thật. Google vừa
    chứng minh xong điều đó (`email_verified`), nên bắt đi lại một vòng nữa là
    thu phí một lời hứa đã được trả.
    """
    r = await conn.fetchrow(
        f"INSERT INTO control.users (id, email, password_hash, name, lifecycle) "
        f"VALUES ($1, $2, NULL, $3, 'active') RETURNING {_COT_USER}",
        user_id,
        email,
        name,
    )
    return HangUser(**dict(r))


async def kich_hoat_user_pending(conn: asyncpg.Connection, *, user_id: str) -> None:
    """Nhánh a — người được mời vào thẳng bằng Google. `WHERE lifecycle =
    'pending'` để câu này không bao giờ hạ cấp một `suspended` thành `active`
    nếu ai đó gọi nhầm chỗ.
    """
    await conn.execute(
        "UPDATE control.users SET lifecycle = 'active' WHERE id = $1 AND lifecycle = 'pending'",
        user_id,
    )


async def xoa_loi_moi_cua_user(conn: asyncpg.Connection, *, user_id: str) -> None:
    """Đi CÙNG `kich_hoat_user_pending`, không tách rời. Người đã vào được rồi
    mà link đặt mật khẩu còn sống là một cửa thứ hai không ai theo dõi.
    """
    await conn.execute("DELETE FROM control.invites WHERE user_id = $1", user_id)


async def sua_ho_so_cua_minh(
    conn: asyncpg.Connection,
    user_id: str,
    cot: dict[str, str | None],
) -> None:
    """UPDATE đúng những cột được đưa vào — vắng khoá = KHÔNG ĐỔI.

    `cot` chỉ nhận bốn tên cột của màn Hồ sơ (service kiểm trước khi gọi);
    dựng SET động nhưng TÊN CỘT lấy từ allowlist, giá trị đi tham số — không
    có đường nào cho chuỗi người dùng chạm vào phần SQL tĩnh.
    """
    hop_le = {"name", "phone", "job_title", "avatar_seed"}
    la = set(cot) - hop_le
    if la:
        raise ValueError(f"cột ngoài allowlist: {la}")
    if not cot:
        return
    ten_cot = sorted(cot)
    dat = ", ".join(f"{c} = ${i + 2}" for i, c in enumerate(ten_cot))
    await conn.execute(
        f"UPDATE control.users SET {dat} WHERE id = $1",
        user_id,
        *[cot[c] for c in ten_cot],
    )


async def doi_password_hash(conn: asyncpg.Connection, user_id: str, hash_moi: str) -> None:
    await conn.execute("UPDATE control.users SET password_hash = $1 WHERE id = $2", hash_moi, user_id)
