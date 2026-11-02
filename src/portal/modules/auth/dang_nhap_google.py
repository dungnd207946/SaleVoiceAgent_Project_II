"""Ba nhánh khớp danh tính của cửa Google (spec §7).

Module này KHÔNG biết HTTP. Nó nhận claims đã đọc xong và quyết định: người này
là ai, có được vào không, và phiên nào được tạo.

═══════════════════════════════════════════════════════════════════════════════
 THỨ TỰ TRA CỨU LÀ BẮT BUỘC: (provider, sub) TRƯỚC, EMAIL SAU
═══════════════════════════════════════════════════════════════════════════════
`sub` là định danh bất biến của tài khoản Google; email thì Google cho đổi.

Đảo thứ tự thì người đổi email tài khoản Google rơi xuống nhánh 3 và bị tạo một
user THỨ HAI — workspace, vai trò, lịch sử của họ nằm ở user thứ nhất và không
ai hiểu vì sao. Test `test_nhanh_1_doi_email_google_van_vao_dung_tai_khoan` canh
đúng điều này.

Đây cũng là lý do thiết kế cần bảng `control.identities` chứ không phải một cột
`gmail` trong `users` — xem spec §2.
"""

import asyncpg
from redis.asyncio import Redis

from portal.core import nhat_ky
from portal.core.auth import session as ss
from portal.core.auth.oauth_google import ClaimsGoogle, LoiGoogle
from portal.modules.auth import quan_tri_user, repo

_PROVIDER = "google"


async def dang_nhap(
    conn: asyncpg.Connection, r: Redis, *, claims: ClaimsGoogle, cho_dang_ky_moi: bool
) -> tuple[str, str | None]:
    """Trả `(session_id, tenant_id)`. Người gọi mở giao dịch VÀ đặt cookie.

    `cho_dang_ky_moi` là `signup_enabled` truyền xuống — chặn nhánh 3 mà KHÔNG
    chặn nhánh 1/2: tắt đăng ký nghĩa là "thôi nhận người mới", không phải "khoá
    cửa những người đang dùng".
    """
    # ── ca c: email chưa xác thực ────────────────────────────────────────────
    # Chặn TRƯỚC mọi thứ. Toàn bộ quyết định «tự liên kết» (spec Q1) đứng trên
    # đúng claim này — không có nó thì nhánh 2 là một đường chiếm tài khoản bằng
    # cách khai một email bất kỳ.
    if not claims.email_verified:
        raise LoiGoogle("EMAIL_CHUA_XAC_THUC")

    hang = await repo.tim_identity(conn, provider=_PROVIDER, subject=claims.sub)

    if hang is not None:
        # ── NHÁNH 1 — đã liên kết. ~99% lượt đăng nhập. ──────────────────────
        u = await repo.tim_user_theo_id(conn, hang.user_id)
        if u is None:
            # ON DELETE CASCADE làm ca này bất khả thi. Nếu vẫn xảy ra thì DB đã
            # sai chứ không phải người dùng — từ chối, đừng đoán.
            raise LoiGoogle("GOOGLE_TU_CHOI")
        _kiem_vao_duoc(u)
        await repo.cham_dang_nhap_identity(
            conn, provider=_PROVIDER, subject=claims.sub, email_tai_provider=claims.email
        )
        return await _mo_phien(conn, r, u, "user.dang_nhap_google")

    u = await repo.tim_user_theo_email(conn, claims.email)

    if u is not None:
        # ── NHÁNH 2 — email trùng, tự liên kết (spec Q1) ─────────────────────
        # KHÔNG đụng vào `password_hash`: người này vẫn đăng nhập bằng mật khẩu
        # được, cửa Google chỉ là đường thứ hai.
        _kiem_vao_duoc(u)
        if u.lifecycle == "pending":
            # ── ca a — được mời, chưa đặt mật khẩu, vào thẳng bằng Google ────
            # Hai câu đi CÙNG NHAU. Kích hoạt mà không xoá thư mời là để lại một
            # link đặt mật khẩu còn sống cho một tài khoản đã vào được — một cửa
            # thứ hai không ai theo dõi.
            await repo.kich_hoat_user_pending(conn, user_id=u.id)
            await repo.xoa_loi_moi_cua_user(conn, user_id=u.id)
        await repo.ghi_identity(
            conn,
            provider=_PROVIDER,
            subject=claims.sub,
            user_id=u.id,
            email_tai_provider=claims.email,
        )
        await nhat_ky.ghi_he_thong(conn, "user.lien_ket_google", u.id, {"email": claims.email})
        u = await repo.tim_user_theo_id(conn, u.id)  # đọc lại: lifecycle có thể vừa đổi
        if u is None:
            # Bất khả thi hôm nay: hàng vừa được đọc thấy vài dòng trên, trong
            # CÙNG giao dịch, không ai xoá được nó ở giữa. Nhưng `ruff` không
            # type-check, và `tim_user_theo_id` khai `HangUser | None` — không gì
            # bắt được nếu lần đọc lại này bị chuyển ra ngoài giao dịch sau này.
            # Không có phép kiểm này thì triệu chứng là `AttributeError` trong
            # `_mo_phien`, tức 500 ở đường đăng nhập thay vì một redirect `?loi=`.
            raise LoiGoogle("GOOGLE_TU_CHOI")
        return await _mo_phien(conn, r, u, "user.dang_nhap_google")

    # ── NHÁNH 3 — người hoàn toàn mới ────────────────────────────────────────
    if not cho_dang_ky_moi:
        raise LoiGoogle("DANG_KY_DANG_TAT")

    user_id = await quan_tri_user.sinh_user_id(conn, claims.email)
    u = await repo.tao_user_tu_google(conn, user_id=user_id, email=claims.email, name=claims.name)
    await repo.ghi_identity(
        conn,
        provider=_PROVIDER,
        subject=claims.sub,
        user_id=u.id,
        email_tai_provider=claims.email,
    )
    await nhat_ky.ghi_he_thong(conn, "user.dang_ky_google", u.id, {"email": claims.email})
    return await _mo_phien(conn, r, u, "user.dang_nhap_google")


def _kiem_vao_duoc(u: repo.HangUser) -> None:
    """Ca b — CỬA HẬU.

    Cửa mật khẩu đã chặn `suspended` (`service.dang_nhap`). Cửa này mà không chặn
    thì: admin đình chỉ người vừa nghỉ việc, mật khẩu hết tác dụng, và họ bấm nút
    Google vẫn vào được — lệnh đình chỉ thành vô nghĩa mà không ai nhìn thấy.

    Repo đã vấp đúng loại lỗi này một lần ở `thanh_vien.py` (user `suspended` rơi
    chung nhánh "đã có tài khoản" và ĐƯỢC cấp membership).

    ═══════════════════════════════════════════════════════════════════════════
     ALLOWLIST, KHÔNG PHẢI DENYLIST
    ═══════════════════════════════════════════════════════════════════════════
    Cửa mật khẩu (`service.dang_nhap`) viết `if u.lifecycle != "active": raise
    ...` — allowlist, chặn MỌI giá trị không phải `active`. Viết `if u.lifecycle
    == "suspended"` ở đây là denylist: chỉ chặn đúng một giá trị đã biết, và hai
    cửa chỉ trùng kết quả hôm nay vì CHECK của migration 0103 giới hạn cột trong
    đúng ba giá trị. `control.tenants.lifecycle` đã có tiền lệ giá trị thứ tư
    (`closed`) — ngày ai đó thêm một trạng thái mới cho `users` (`closed`,
    `archived`, ...), cửa mật khẩu tự động chặn nó vì là allowlist, còn một
    denylist ở đây sẽ cho đi qua, im lặng, không test nào đỏ. Một cổng sinh ra
    để chống fail-open thì chính nó phải fail-closed — nên allowlist, dù hôm nay
    tập hợp cho phép chỉ có hai giá trị.

    `pending` PHẢI nằm trong allowlist: nhánh a (người được mời, chưa đặt mật
    khẩu) đi qua đúng hàm này trước khi được kích hoạt thành `active` — bỏ nó ra
    là chặn luôn nhánh a (xem `test_bien_a_pending_thanh_active_va_thu_moi_chet`,
    test đó đỏ ngay nếu ai "đơn giản hoá" allowlist này về `("active",)`).

    NÓI THẲNG, không gộp vào `sai_dang_nhap()`: lý lẽ chống dò email không áp
    được ở đây. Muốn thử email X qua cửa này thì phải đăng nhập được vào tài
    khoản Google của X — đã là chủ hộp thư rồi, không còn gì để rò. Và "Email
    hoặc mật khẩu không đúng" là câu vô nghĩa với người không gõ mật khẩu nào.
    """
    if u.lifecycle not in ("active", "pending"):
        raise LoiGoogle("TAI_KHOAN_DINH_CHI")


async def _mo_phien(conn: asyncpg.Connection, r: Redis, u: repo.HangUser, hanh_dong: str) -> tuple[str, str | None]:
    """DÙNG LẠI `ss.tao()` của đường mật khẩu, không viết bản thứ hai.

    Hai đường vào phải sinh ra CÙNG một loại phiên. Lệch nhau ở đây nghĩa là
    `logout`, thu hồi phiên, và TTL trượt chỉ đúng cho một nửa số người dùng.

    KHÔNG dựng `SessionOut` ở đây: callback trả 302, không trả JSON — FE gọi
    `/me` như mọi lần tải trang khác.
    """
    ws = await repo.liet_ke_workspace(conn, u.id)
    tenant_id = ws[0].id if ws else None
    session_id = await ss.tao(r, user_id=u.id, tenant_id=tenant_id)
    await nhat_ky.ghi_he_thong(conn, hanh_dong, u.id, {"email": u.email})
    return session_id, tenant_id
