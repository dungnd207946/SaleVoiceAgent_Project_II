"""Logic tạo · sửa · mời user — M2b.

VÌ SAO FILE RIÊNG, KHÔNG NHÉT VÀO `service.py`: `service.py` sở hữu đúng một
việc — "ai đang đăng nhập và phiên của họ trông thế nào". Việc ở đây là "user và
membership được nhập/sửa thế nào". Hai việc dùng chung `repo.py` nhưng không gọi
nhau, và gộp chúng thành một file 400 dòng thì mỗi lần sửa luồng đăng nhập lại
phải đọc qua bảy hàm không liên quan.

═══════════════════════════════════════════════════════════════════════════════
 KHỐI NÀY MẤT CHỦ VÀ ĐANG TẮT — ĐỌC TRƯỚC KHI BẬT
═══════════════════════════════════════════════════════════════════════════════
Cửa thật của sáu đường `/users*` từng là `users.org_role = 'owner'` (`_lay_owner()`,
đã xoá). Cột đó biến mất cùng tầng tổ chức ở migration 0106, và KHÔNG có gì thay
thế: không còn admin hệ thống nào trong mô hình mới.

Các hàm repo bên dưới vì thế không còn tự giới hạn phạm vi — `liet_ke_user()` trả
MỌI user của hệ thống, `sua_ho_so()` sửa được bất kỳ ai. Nên toàn khối đóng bằng
cờ `USERS_ADMIN_ENABLED` (mặc định `False`) qua `_cong_users_admin()`. Code, test
và route giữ nguyên để bật lại khi có mô hình admin thật.

Hai việc khối này từng gánh đã có đường khác:
  · tạo tài khoản  → `POST /auth/register` (tự đăng ký)
  · quản lý người trong MỘT workspace → `/members`, gate `WORKSPACE_ADMIN`

Hai đường CÔNG KHAI ở cuối file (`xem_loi_moi`, `nhan_loi_moi`) KHÔNG bị cờ chặn:
chúng là đường người được mời đặt mật khẩu, không phải đường quản trị.
"""

import hashlib
import re
import secrets
from datetime import UTC, datetime, timedelta

import asyncpg

from portal.api import loi as loi_chung
from portal.core import nhat_ky
from portal.core.auth import password as pw
from portal.core.config import get_settings
from portal.modules.auth import loi, repo
from portal.modules.auth.contracts import (
    LoiMoiOut,
    NhanLoiMoiIn,
    SuaUserIn,
    TaoUserIn,
    TaoUserRaOut,
    UserDetailOut,
    UserListItemOut,
)

HAN_MOI = timedelta(days=7)
"""Đủ dài để qua một kỳ nghỉ, đủ ngắn để một link rơi ra ngoài không sống mãi.

Bản dùng thật ở đây, không đọc từ migration 0103: không có đường nào cho code
import hằng số của một revision, và hai bản có thể lệch — nên hằng số ở migration
chỉ để đọc, và nó ghi rõ điều đó.
"""

_SO_BYTE_TOKEN = 32
"""256 bit ngẫu nhiên từ `secrets`. Đây là toàn bộ chứng cứ của một đường công
khai đặt được mật khẩu, nên nó không được đoán được — và không có rate limit ở
đường đó (M8)."""

_TIEN_TO_ID = "u_"
_DAI_ID_TOI_DA = 40
"""`users_id_check` ở migration 0100: `^u_[a-z0-9_]{1,40}$`."""


def bam_token(token: str) -> str:
    """sha256 hex — CHỈ giá trị này vào DB (migration 0103 CHECK `^[0-9a-f]{64}$`).

    Không dùng Argon2: token là 256 bit ngẫu nhiên, không phải mật khẩu người
    chọn. Argon2 tốn CPU để chống dò từ điển — với 256 bit ngẫu nhiên thì không
    có từ điển nào để dò, và cái giá đó rơi vào mỗi lần MỞ link mời.
    """
    return hashlib.sha256(token.encode()).hexdigest()


def duong_dan_moi(token: str) -> str:
    """TƯƠNG ĐỐI. FE ghép `location.origin` — xem docstring `TaoUserRaOut.invitePath`."""
    return f"/invite/{token}"


async def sinh_user_id(conn: asyncpg.Connection, email: str) -> str:
    """`dang.tran@anphuland.vn` -> `u_dang_tran`, trùng thì `u_dang_tran_2`.

    Vì sao suy từ email chứ không dùng uuid: `users.id` là `text` có CHECK ký tự
    (0100) chính vì nó đọc được bằng mắt — nó xuất hiện trong `audit_log.actor` và
    trong mọi thông điệp lỗi. `u_a3f9c1b2` ở đó không nói gì cho người đang đọc log.

    Vòng lặp có TRẦN: 50 lần rồi rơi về hậu tố ngẫu nhiên. Một vòng `while True`
    tra DB ở đường tạo user là một cách để một email lạ làm treo request.
    """
    goc = re.sub(r"[^a-z0-9]+", "_", email.split("@")[0].lower()).strip("_")
    goc = goc[:_DAI_ID_TOI_DA] or "user"

    for n in range(1, 51):
        hau_to = "" if n == 1 else f"_{n}"
        ung_vien = f"{_TIEN_TO_ID}{goc[: _DAI_ID_TOI_DA - len(hau_to)]}{hau_to}"
        if not await repo.id_da_dung(conn, ung_vien):
            return ung_vien

    return f"{_TIEN_TO_ID}{goc[:32]}_{secrets.token_hex(3)}"


async def _cong_users_admin(conn: asyncpg.Connection, user_id: str) -> repo.HangUser:
    """Chặn khi cờ tắt, rồi đọc admin đang thao tác. Xem docstring module.

    Vẫn TRẢ CẢ HÀNG: ba luật chống tự khoá cửa cần `id` của người đang gọi để so
    với mục tiêu. Đọc lại ở mỗi hàm là hai truy vấn cho một sự thật.
    """
    if not get_settings().users_admin_enabled:
        raise loi_chung.tinh_nang_dang_tat("quản trị người dùng")
    u = await repo.tim_user_theo_id(conn, user_id)
    if u is None:
        # Phiên đã xác thực tới được đây thì user luôn tồn tại, nên `None` chỉ có
        # thể là một cuộc đua với xoá user — câu trả lời đúng cũng là "không được".
        raise loi_chung.khong_du_quyen()
    return u


async def liet_ke(conn: asyncpg.Connection, actor_id: str) -> list[UserListItemOut]:
    await _cong_users_admin(conn, actor_id)
    return await repo.liet_ke_user(conn)


async def doc_chi_tiet(conn: asyncpg.Connection, actor_id: str, user_id: str) -> UserDetailOut:
    await _cong_users_admin(conn, actor_id)
    ct = await repo.doc_chi_tiet_user(conn, user_id)
    if ct is None:
        raise loi.user_khong_ton_tai()
    return ct


async def _kiem_workspace_ton_tai(conn: asyncpg.Connection, vao: TaoUserIn | SuaUserIn) -> None:
    """GỌI TRƯỚC MỌI INSERT. Xem `repo.loc_workspace_khong_ton_tai`."""
    thieu = await repo.loc_workspace_khong_ton_tai(conn, [m.workspaceId for m in vao.memberships])
    if thieu:
        raise loi.workspace_khong_ton_tai()


async def _kiem_role_ton_tai(conn: asyncpg.Connection, vao: TaoUserIn | SuaUserIn) -> None:
    """GỌI TRƯỚC MỌI INSERT, cùng giao dịch với `_kiem_workspace_ton_tai`.

    Vai trò đã TOÀN CỤC (0105) nên phép kiểm còn lại là "có tồn tại không" —
    trước đây là "có thuộc tổ chức của admin không". Mã lỗi đổi theo:
    `ROLE_NOT_IN_ORG` -> `ROLE_NOT_FOUND`. Vẫn kiểm TRƯỚC INSERT để ra 422 có tên
    field thay vì `ForeignKeyViolationError` -> 500.
    """
    thieu = await repo.loc_role_khong_ton_tai(conn, [m.role_id for m in vao.memberships])
    if thieu:
        raise loi.vai_tro_khong_ton_tai_trong_yeu_cau()


async def tao(conn: asyncpg.Connection, actor_id: str, vao: TaoUserIn) -> TaoUserRaOut:
    """Mười bước, MỘT giao dịch (spec §4.3). Người gọi mở giao dịch.

    Vì sao cả mười trong một giao dịch: một user `pending` không có thư mời là một
    hàng không đường nào tới được — không link để nhận, và không nút nào trên UI
    nhắc admin rằng nó tồn tại. Nửa vời ở đây tệ hơn thất bại hẳn.

    `vao.email` ĐÃ được chuẩn hoá lower+trim bởi validator của `TaoUserIn`, nên ở
    đây không gọi `chuan_hoa_email` lần nữa: hai chỗ chuẩn hoá là hai chỗ phải
    giữ đồng bộ, và CHECK `email = lower(email)` ở DB là lưới thứ hai.
    """
    admin = await _cong_users_admin(conn, actor_id)

    if await repo.email_da_dung(conn, vao.email):
        raise loi.email_da_ton_tai()

    await _kiem_workspace_ton_tai(conn, vao)
    await _kiem_role_ton_tai(conn, vao)

    user_id = await sinh_user_id(conn, vao.email)
    await repo.tao_user(
        conn,
        user_id=user_id,
        email=vao.email,
        name=vao.name,
        phone=vao.phone,
        job_title=vao.jobTitle,
    )
    await repo.dat_lai_membership(conn, user_id=user_id, danh_sach=vao.memberships)

    token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
    await repo.ghi_loi_moi_dang_ky(
        conn,
        token_hash=bam_token(token),
        user_id=user_id,
        # `TaoUserIn` nhận NHIỀU membership — không có một workspace duy nhất để
        # gắn thư mời này vào. `/users*` cũng đang đóng sau `USERS_ADMIN_ENABLED`
        # nên đường này không chạy từ UI.
        email=vao.email,
        expires_at=datetime.now(UTC) + HAN_MOI,
        created_by=admin.id,
    )

    # SAU KHI việc đã xong, không phải trước — xem docstring core/nhat_ky.ghi().
    # KHÔNG ghi token vào chi_tiet: nhật ký là bảng chỉ-ghi-thêm mà nhiều người
    # đọc được, và một token ở đó là một thư mời dùng được nằm vĩnh viễn trong log.
    await nhat_ky.ghi_he_thong(
        conn,
        "user.tao",
        admin.id,
        {"user_id": user_id, "email": vao.email, "so_workspace": len(vao.memberships)},
    )

    ct = await repo.doc_chi_tiet_user(conn, user_id)
    assert ct is not None, "vừa INSERT trong cùng giao dịch"
    return TaoUserRaOut(user=ct, invitePath=duong_dan_moi(token))


async def sua(conn: asyncpg.Connection, actor_id: str, user_id: str, vao: SuaUserIn) -> UserDetailOut:
    """Sửa hồ sơ + `lifecycle` + THAY THẾ TOÀN BỘ membership.

    Hai luật chống tự khoá cửa (spec §3.2) kiểm ở đây, trước mọi phép ghi.
    """
    admin = await _cong_users_admin(conn, actor_id)

    hien_tai = await repo.doc_chi_tiet_user(conn, user_id)
    if hien_tai is None:
        raise loi.user_khong_ton_tai()

    # Luật "không tự bỏ quyền chủ tổ chức" đã bỏ cùng `orgRole` (2026-08-15).
    # Luật tự-đình-chỉ thì GIỮ: nó không liên quan tới tổ chức, và một người tự
    # khoá tài khoản của mình vẫn là một cửa không mở lại được từ trong.
    la_chinh_minh = user_id == admin.id
    if la_chinh_minh and vao.lifecycle == "suspended":
        raise loi.tu_khoa_cua_minh("Bạn không thể tự đình chỉ tài khoản của mình")

    if vao.lifecycle is not None and hien_tai.lifecycle == "pending":
        # CHECK song điều kiện của 0103 nói lại bằng tiếng Việt: user chưa có mật
        # khẩu không tồn tại ở trạng thái nào khác `pending`. Để UPDATE nổ thì
        # thành 500; kiểm ở đây thì thành 409 có câu giải thích.
        raise loi.user_chua_nhan_moi()

    await _kiem_workspace_ton_tai(conn, vao)
    await _kiem_role_ton_tai(conn, vao)

    await repo.sua_ho_so(
        conn,
        user_id=user_id,
        name=vao.name,
        phone=vao.phone,
        job_title=vao.jobTitle,
        lifecycle=vao.lifecycle,
    )
    await repo.dat_lai_membership(conn, user_id=user_id, danh_sach=vao.memberships)

    await nhat_ky.ghi_he_thong(
        conn,
        "user.sua",
        admin.id,
        {
            "user_id": user_id,
            "lifecycle": vao.lifecycle or hien_tai.lifecycle,
            "so_workspace": len(vao.memberships),
        },
    )

    ct = await repo.doc_chi_tiet_user(conn, user_id)
    assert ct is not None, "vừa UPDATE trong cùng giao dịch"
    return ct


async def xoa(conn: asyncpg.Connection, actor_id: str, user_id: str) -> None:
    """CHỈ xoá được user còn `pending` — thu hồi một lời mời gửi sai địa chỉ.

    Người đã đặt mật khẩu thì không: xoá họ là CASCADE gỡ mọi thứ trỏ tới họ, một
    nút không hoàn tác được. Thu hồi quyền của người đang hoạt động là Đình chỉ,
    việc đó giữ lại dấu vết còn xoá thì không.
    """
    admin = await _cong_users_admin(conn, actor_id)

    hien_tai = await repo.doc_chi_tiet_user(conn, user_id)
    if hien_tai is None:
        raise loi.user_khong_ton_tai()
    if hien_tai.lifecycle != "pending":
        raise loi.user_da_nhan_moi()

    await repo.xoa_user(conn, user_id=user_id)
    await nhat_ky.ghi_he_thong(conn, "user.xoa_loi_moi", admin.id, {"user_id": user_id, "email": hien_tai.email})


async def moi_lai(conn: asyncpg.Connection, actor_id: str, user_id: str) -> str:
    """Trả `invitePath` mới. Token cũ CHẾT — `invites.user_id` UNIQUE + DO UPDATE.

    Chỉ áp cho user còn `pending`: sinh thư mời cho người đã có mật khẩu là tạo ra
    một đường đặt lại mật khẩu mà không ai yêu cầu, và quên mật khẩu là việc của
    M8 với xác minh danh tính của chính người đó, không phải của admin.
    """
    admin = await _cong_users_admin(conn, actor_id)

    hien_tai = await repo.doc_chi_tiet_user(conn, user_id)
    if hien_tai is None:
        raise loi.user_khong_ton_tai()
    if hien_tai.lifecycle != "pending":
        raise loi.user_da_nhan_moi()

    token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
    await repo.ghi_loi_moi_dang_ky(
        conn,
        token_hash=bam_token(token),
        user_id=user_id,
        email=hien_tai.email,  # cùng lý do với `tao()` ở trên
        expires_at=datetime.now(UTC) + HAN_MOI,
        created_by=admin.id,
    )
    await nhat_ky.ghi_he_thong(conn, "user.moi_lai", admin.id, {"user_id": user_id})
    return duong_dan_moi(token)


# --- hai đường CÔNG KHAI -----------------------------------------------------
# Token CHÍNH LÀ chứng cứ. Bắt đăng nhập để đặt mật khẩu lần đầu là một vòng tròn:
# muốn đăng nhập thì phải có mật khẩu, mà mật khẩu đặt ở đây.


def _kind(hang: repo.HangLoiMoi) -> str:
    """Suy `kind` từ HAI cột — MỘT chỗ duy nhất trong cả codebase.

    `xem_loi_moi` và `nhan_loi_moi` đều cần nó, và hai bản chép tay của cùng một
    phép suy là hai bản sẽ lệch: màn hình nói "chỉ cần bấm nút" trong khi đường ghi
    đòi mật khẩu là một lỗi không ai đọc code ra được.

    Ba tổ hợp, không phải bốn: CHECK `invites_dang_ky_co_user` (0952) chặn tổ hợp
    (tenant_id NULL, user_id NULL) ở tầng DB.
    """
    if hang.tenant_id is None:
        return "signup"
    return "invite_new" if hang.user_id is None else "invite_existing"


async def xem_loi_moi(conn: asyncpg.Connection, token: str) -> LoiMoiOut:
    """Cho màn nhận lời mời biết nó đang hỏi về CÁI GÌ và cho tài khoản NÀO.

    KHÔNG kiểm ca đua `EMAIL_DA_CO_TAI_KHOAN` ở đây: trạng thái đổi được giữa lần
    GET này và lần POST sau, nên một phép kiểm ở đây chỉ tạo cảm giác an toàn.
    Phép kiểm thật nằm trong giao dịch của `nhan_loi_moi`.
    """
    hang = await repo.doc_loi_moi_con_hieu_luc(conn, bam_token(token))
    if hang is None:
        raise loi.loi_moi_khong_hop_le()
    return LoiMoiOut(
        email=hang.email,
        name=hang.name,
        kind=_kind(hang),
        workspaceName=hang.ten_workspace,
    )


async def nhan_loi_moi(conn: asyncpg.Connection, vao: NhanLoiMoiIn) -> tuple[str, str] | None:
    """BA nhánh, MỘT giao dịch mỗi nhánh. Người gọi mở giao dịch.

    Trả `(user_id, tenant_id)` KHI VÀ CHỈ KHI nhánh `invite_existing` vừa chạy —
    router dùng cặp đó để tự tạo phiên NGAY, không đẩy về `/login`. Chỉ nhánh này
    được phép: người nhận ĐÃ có mật khẩu từ trước, tài khoản KHÔNG sinh ra tại đây
    — token chỉ quyết định họ có vào thêm một workspace hay không, không phải
    "ai được cấp một danh tính mới". Hai nhánh còn lại (`signup`/`invite_new`) vẫn
    trả `None`: mật khẩu được ĐẶT ngay trong chính request này, và tự cấp phiên
    cho một request công khai vừa tạo ra mật khẩu đó là đúng lỗ hổng đã chặn từ
    đầu (ai mở được link mời — bị forward, lộ qua log proxy — thì có phiên).
    """
    token_hash = bam_token(vao.token)
    hang = await repo.doc_loi_moi_con_hieu_luc(conn, token_hash)
    if hang is None:
        raise loi.loi_moi_khong_hop_le()

    kind = _kind(hang)

    if kind == "invite_existing":
        if vao.password is not None:
            raise loi.khong_nhan_mat_khau()
        assert hang.user_id is not None and hang.tenant_id is not None and hang.role_id is not None
        if not await repo.la_thanh_vien(conn, user_id=hang.user_id, tenant_id=hang.tenant_id):
            # CHỈ ghi khi CHƯA có membership. `repo.them_membership` là
            # `ON CONFLICT DO UPDATE SET role_id` — nếu người này đã thành viên
            # qua một đường KHÁC từ SAU lúc lời mời được phát (`ws_service.tao()`,
            # hay khối `/users` admin), chấp nhận token cũ ở đây sẽ ÂM THẦM GHI
            # ĐÈ vai trò họ đang giữ bằng vai trò đã hứa trên token — đúng lớp
            # lỗi "vai trò đổi qua đường mời" mà cả đợt 2026-08-22 dựng ra để
            # chấm dứt (xem `thanh_vien.moi`, nhánh `USER_ALREADY_MEMBER`). Nhận
            # một lời mời mà mình coi như đã nhận rồi phải là một no-op, không
            # phải một phép giáng cấp.
            await repo.them_membership(conn, user_id=hang.user_id, tenant_id=hang.tenant_id, role_id=hang.role_id)
        await repo.danh_dau_da_dung(conn, token_hash=token_hash)
        await nhat_ky.ghi(conn, hang.tenant_id, "user.nhan_moi_ws", hang.user_id, {"user_id": hang.user_id})
        return hang.user_id, hang.tenant_id

    if vao.password is None:
        raise loi.can_mat_khau()

    if kind == "signup":
        assert hang.user_id is not None
        await repo.nhan_loi_moi_dat_mat_khau(
            conn, token_hash=token_hash, user_id=hang.user_id, password_hash=pw.bam(vao.password)
        )
        await nhat_ky.ghi_he_thong(conn, "user.nhan_moi", hang.user_id, {"user_id": hang.user_id})
        return

    # kind == "invite_new" — tài khoản ra đời ĐÚNG TẠI ĐÂY, không sớm hơn một dòng.
    assert hang.tenant_id is not None and hang.role_id is not None
    if await repo.email_da_dung(conn, hang.email):
        # Ca đua spec §5.6, NHÁNH TUẦN TỰ: ai đó đăng ký email này trước khi ta
        # tới được đây. Đây là đường NHANH, không phải đường DUY NHẤT — xem
        # `try` ngay dưới cho ca đua THẬT (commit lọt vào giữa SELECT này và
        # INSERT bên dưới).
        raise loi.email_da_co_tai_khoan()

    user_id = await sinh_user_id(conn, hang.email)
    try:
        # READ COMMITTED không khoá gì giữa lượt SELECT ở `email_da_dung` và
        # INSERT này — một `POST /auth/register` commit lọt vào đúng khe đó
        # (spec §5.6, "ca đua thật") làm câu dưới vỡ ở `users_email_key`
        # (`asyncpg.UniqueViolationError`), và không bọc lại thì FastAPI thấy
        # một exception lạ ⇒ 500. Bọc ở ĐÂY, không ở tầng router: đây là nơi
        # DUY NHẤT biết vì sao INSERT này có thể vỡ theo đúng cách này (một
        # UNIQUE khác vỡ vì lý do khác không được nuốt thành cùng một 409).
        await repo.tao_user_da_kich_hoat(
            conn,
            user_id=user_id,
            email=hang.email,
            name=hang.email.split("@")[0],
            password_hash=pw.bam(vao.password),
        )
    except asyncpg.UniqueViolationError as e:
        if e.constraint_name != "users_email_key":
            raise
        raise loi.email_da_co_tai_khoan() from e
    await repo.them_membership(conn, user_id=user_id, tenant_id=hang.tenant_id, role_id=hang.role_id)
    await repo.danh_dau_da_dung(conn, token_hash=token_hash)
    await nhat_ky.ghi(conn, hang.tenant_id, "user.tao_tu_loi_moi", user_id, {"user_id": user_id})
