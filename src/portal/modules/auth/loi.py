"""Mã lỗi RIÊNG của module auth — bảy mã của M2b.

`api/loi.py` ghi: *"Module sau thêm hằng số của nó vào file của nó, không vào
đây."* Bốn mã dùng chung (NO_SESSION · INVALID_CREDENTIALS · FORBIDDEN ·
NO_WORKSPACE) vẫn ở `api/loi.py` vì chúng là hình dạng lỗi của cả API.

HAI MÃ CỐ Ý NHẬP NHẰNG — và đó là điểm chính của file này:

  · `USER_NOT_FOUND` trả cho cả không có id đó lẫn id đó ở tổ chức khác.
    403 cho trường hợp sau là xác nhận id này tồn tại, chỉ không phải của bạn
    — đủ để dò danh sách user của mọi khách hàng. Cùng lý lẽ `doi_workspace()`
    đã dùng khi trả `khong_du_quyen()` thay vì 404.

  · `INVITE_INVALID` trả cho cả ba: token sai · đã dùng · hết hạn. Phân biệt
    hết hạn với không tồn tại cho một máy dò biết token nào đã từng có thật.

Cùng khuôn với `sai_dang_nhap()` ở `api/loi.py`: một mã cho nhiều tình huống là
một QUYẾT ĐỊNH, không phải sự lười.
"""

from portal.api.loi import LoiPortal


def email_da_ton_tai() -> LoiPortal:
    """409, không 422: dữ liệu gửi lên đúng dạng, chỉ là thế giới đã thay đổi.

    UNIQUE trên `users.email` là TOÀN CỤC (migration 0100) — email là khoá đăng
    nhập, và `tim_user_theo_email` không nhận tham số phạm vi nào.

    Dùng cho CẢ đường quản trị lẫn `POST /auth/register`. FE đường đăng ký bắt mã
    này để gợi ý "đăng nhập thay vì đăng ký".
    """
    return LoiPortal("EMAIL_TAKEN", 409, "Email này đã được dùng cho một tài khoản khác")


def user_khong_ton_tai() -> LoiPortal:
    """Xem docstring module — cố ý gộp với "ở tổ chức khác"."""
    return LoiPortal("USER_NOT_FOUND", 404, "Không tìm thấy người dùng này")


def workspace_khong_ton_tai() -> LoiPortal:
    """422 vì đây LÀ lỗi dữ liệu gửi lên: FE gửi một workspaceId không tồn tại.

    THAY `workspace_khong_thuoc_to_chuc()` (mã cũ `WORKSPACE_NOT_IN_ORG`): không
    còn tổ chức thì "thuộc tổ chức của bạn" không còn nghĩa, và câu hỏi duy nhất
    còn lại là "có tồn tại không".

    FK cũng chặn, nhưng bằng ForeignKeyViolationError -> 500. Kiểm trước biến
    cùng một sự thật thành một câu người đọc được.
    """
    return LoiPortal("WORKSPACE_NOT_FOUND", 422, "Workspace được chọn không tồn tại")


def vai_tro_khong_ton_tai_trong_yeu_cau() -> LoiPortal:
    """422 — cùng lý lẽ `workspace_khong_ton_tai()`, cho `roleId`.

    THAY `vai_tro_khong_thuoc_to_chuc()` (mã cũ `ROLE_NOT_IN_ORG`): vai trò đã
    TOÀN CỤC từ 2026-08-15 (migration 0105) nên mọi `role_id` tồn tại đều hợp lệ.

    ⚠ DÙNG CHUNG MÃ `ROLE_NOT_FOUND` với `vai_tro_khong_ton_tai()` bên dưới, khác
    HTTP status. Cố ý: cùng một sự thật ("vai trò này không có"), khác chỗ đứng —
    404 khi `role_id` là PATH PARAM (`GET/PATCH/DELETE /roles/{id}`, tài nguyên
    không tồn tại), 422 khi nó là MỘT TRƯỜNG trong thân request của đường khác
    (thân sai, tài nguyên đích mới là thứ không tồn tại). Tách thành hai mã sẽ
    bắt FE phân biệt một khác biệt nó không dùng tới.
    """
    return LoiPortal("ROLE_NOT_FOUND", 422, "Vai trò được chọn không tồn tại")


def user_chua_nhan_moi() -> LoiPortal:
    """Chặn đổi `lifecycle` của user còn `pending`.

    Không phải một luật nghiệp vụ tự đặt ra — nó là CHECK song điều kiện ở
    migration 0103 nói lại bằng tiếng Việt: user chưa có mật khẩu thì không tồn
    tại ở trạng thái `active` hay `suspended` nào. Đình chỉ họ = xoá thư mời.
    """
    return LoiPortal(
        "USER_PENDING",
        409,
        "Người này chưa đặt mật khẩu nên chưa có trạng thái để đổi — huỷ lời mời nếu muốn thu hồi",
    )


def user_da_nhan_moi() -> LoiPortal:
    """Chặn xoá / mời lại một user đã đặt mật khẩu.

    Xoá một user đã hoạt động là xoá cả membership và mọi thứ trỏ tới họ qua
    CASCADE — một nút không hoàn tác được, và spec này cố ý không có nó. Thu hồi
    quyền của người đang hoạt động = đình chỉ (`lifecycle = 'suspended'`), việc
    này giữ lại dấu vết còn xoá thì không.
    """
    return LoiPortal("USER_NOT_PENDING", 409, "Người này đã đặt mật khẩu — dùng Đình chỉ thay vì xoá")


def tu_khoa_cua_minh(chi_tiet: str) -> LoiPortal:
    """Ba luật §3.2 của spec, một mã.

    VÌ SAO CHẶN Ở SERVER chứ không chỉ ẩn nút: `owner` là con đường DUY NHẤT vào
    màn quản trị tổ chức, và không có console Nền tảng để cứu (M2a §10.1). Mất
    owner cuối cùng nghĩa là sửa DB bằng tay trên production.
    """
    return LoiPortal("SELF_LOCKOUT", 409, chi_tiet)


def loi_moi_khong_hop_le() -> LoiPortal:
    """Xem docstring module — một mã cho ba tình huống."""
    return LoiPortal("INVITE_INVALID", 404, "Lời mời không hợp lệ hoặc đã hết hiệu lực")


def loi_moi_khong_ton_tai() -> LoiPortal:
    """404 — ADMIN hỏi, không phải người nhận hỏi.

    KHÁC `loi_moi_khong_hop_le()` (`INVITE_INVALID`) dù cùng 404. Mã kia trả lời
    "token bạn cầm đã chết" cho một người vừa bấm link; mã này trả lời "email này
    không có lời mời đang treo nào ở workspace của bạn" cho một Quản trị vừa bấm
    Thu hồi hai lần. Gộp làm một là bắt FE hiện câu "hãy xin link mới" cho admin.
    """
    return LoiPortal("INVITE_NOT_FOUND", 404, "Không có lời mời đang chờ cho địa chỉ này")


def email_da_co_tai_khoan() -> LoiPortal:
    """409 — ca đua ở `POST /invites/accept`, nhánh `invite_new` (spec §5.6).

    Lời mời phát cho một email CHƯA có tài khoản, nhưng tới lúc người ta bấm nút
    thì email đó đã có tài khoản (ai đó — kể cả chính họ — vừa `POST /auth/register`).

    KHÔNG tự nối lời mời vào tài khoản vừa có: đường này CÔNG KHAI và không kiểm
    mật khẩu nào, nên làm thế là cho bất kỳ ai giữ link cấp quyền workspace cho một
    tài khoản không phải của mình.
    """
    return LoiPortal(
        "EMAIL_DA_CO_TAI_KHOAN",
        409,
        "Địa chỉ này giờ đã có tài khoản. Hãy đăng nhập rồi đề nghị Quản trị mời lại.",
    )


def can_mat_khau() -> LoiPortal:
    """422 — token `signup`/`invite_new` mà thân request không có `password`."""
    return LoiPortal("INVITE_PASSWORD_REQUIRED", 422, "Lời mời này cần bạn đặt mật khẩu")


def khong_nhan_mat_khau() -> LoiPortal:
    """422 — token `invite_existing` mà thân request CÓ `password`.

    KHÔNG bỏ qua im lặng: một `password` thừa nghĩa là FE đang hiển thị một ô nhập
    không có tác dụng gì, và người dùng vừa gõ một mật khẩu mới rồi tưởng nó đã đổi.
    """
    return LoiPortal(
        "INVITE_PASSWORD_NOT_ALLOWED",
        422,
        "Tài khoản này đã có mật khẩu — lời mời này không đặt lại mật khẩu",
    )


def vai_tro_khong_ton_tai() -> LoiPortal:
    """404 cả khi vai trò thuộc tổ chức khác — cùng lý lẽ `user_khong_ton_tai()`.

    403 xác nhận id này tồn tại, chỉ không phải của bạn — đủ để dò cấu hình
    quyền của mọi khách hàng.
    """
    return LoiPortal("ROLE_NOT_FOUND", 404, "Không tìm thấy vai trò này")


def ten_vai_tro_da_ton_tai() -> LoiPortal:
    """409, không 422: dữ liệu gửi lên đúng dạng, chỉ là thế giới đã thay đổi.

    `UNIQUE (name)` từ migration 0105 — TOÀN CỤC, không còn theo tổ chức. Thông
    điệp vì thế KHÔNG được nói "trong tổ chức này" nữa: người dùng sẽ đi tìm một
    tổ chức không tồn tại để giải thích vì sao tên bị từ chối.
    """
    return LoiPortal("ROLE_NAME_TAKEN", 409, "Đã có một vai trò tên này")


def vai_tro_dang_dung(so_nguoi: int, so_loi_moi: int = 0) -> LoiPortal:
    """FK RESTRICT trên `memberships` cũng chặn `so_nguoi`, nhưng bằng
    ForeignKeyViolationError → 500. `invites.role_id` (migration 0952) thì
    KHÔNG có `ON DELETE` nào — `so_loi_moi` (từ `repo.dem_loi_moi_dang_treo_vai_tro`)
    là vế thứ hai, thêm sau review round 2: một vai trò có thể có 0 người ĐANG
    GIỮ (`so_nguoi=0`, cổng cũ cho qua) nhưng vẫn có lời mời CÒN SỐNG đang hứa nó
    — xoá lúc đó vỡ ở `ForeignKeyViolationError` khi `DELETE` chạm `invites`.

    Con số trong thông điệp là thứ biến một lời từ chối thành một việc làm được
    — và HAI con số phải TÁCH RIÊNG, không cộng gộp: một Quản trị nhìn bảng
    thành viên thấy 0 người mang vai trò này rồi đọc "N người đang dùng" (N từ
    lời mời) sẽ kết luận cổng này báo sai, vì bảng đó không hiện lời mời chưa ai
    nhận.
    """
    phan = []
    if so_nguoi:
        phan.append(f"{so_nguoi} người đang dùng")
    if so_loi_moi:
        phan.append(f"{so_loi_moi} lời mời đang hứa")
    ly_do = " và ".join(phan) if phan else "0 người đang dùng"
    return LoiPortal(
        "ROLE_IN_USE",
        409,
        f"Vai trò này đang gán cho {ly_do} — chuyển sang vai trò khác hoặc thu hồi lời mời trước khi xoá",
    )


def action_khong_hop_le(ma: str) -> LoiPortal:
    """422 vì đây LÀ lỗi dữ liệu gửi lên. FK tới control.actions cũng chặn, nhưng
    kiểm trước biến cùng một sự thật thành một câu người đọc được."""
    return LoiPortal("UNKNOWN_ACTION", 422, f"Quyền {ma} không tồn tại")


# ═══════════════════════════════════════════════════════════════════════════════
#  M2c — seam `/members` GHI
# ═══════════════════════════════════════════════════════════════════════════════
#
# ⚠ LỆCH BRIEF, CÓ CHỦ Ý: task-4-brief.md §Step 5 xin một hàm MỚI tên
# `vai_tro_khong_ton_tai()` trả 422 ROLE_NOT_FOUND. Tên đó ĐÃ CÓ trong file này
# (định nghĩa phía trên, dòng ~110) — 404, dùng bởi `quan_tri_vai_tro.py` (3 chỗ,
# cho `GET/PATCH/DELETE /roles/{id}`) và neo bởi
# `tests/modules/auth/test_vai_tro.py::test_vai_tro_khong_ton_tai_tra_404`. Định
# nghĩa lại cùng tên trong CÙNG module sẽ ÂM THẦM ghi đè hàm cũ (Python chỉ giữ
# định nghĩa sau cùng) — ba chỗ gọi ở `quan_tri_vai_tro.py` sẽ đổi 404 -> 422 và
# bài test trên đỏ. Đây chính là kiểu brief lệch code thật mà task yêu cầu tự kiểm.
#
# Hàm đáp ứng ĐÚNG yêu cầu (422, mã `ROLE_NOT_FOUND`, cho `role_id` là một TRƯỜNG
# trong thân request chứ không phải path param) ĐÃ TỒN TẠI SẴN ở trên:
# `vai_tro_khong_ton_tai_trong_yeu_cau()`. Service/router của seam `/members`
# (task sau) phải gọi hàm ĐÓ, không phải một `vai_tro_khong_ton_tai()` mới.
# Không thêm hàm nào ở đây cho mục này.


USER_PENDING_SIGNUP = "USER_PENDING_SIGNUP"
"""Mã lỗi TỪNG DÒNG của `POST /members` — không phải một `LoiPortal`.

Người này đã tự đăng ký và đang chờ đặt mật khẩu. Phát token mời cho họ sẽ GIẾT
token đăng ký của họ (`invites.user_id` UNIQUE + DO UPDATE): họ bấm link trong
hộp thư và nhận `INVITE_INVALID` mà không hiểu vì sao.
"""

USER_SUSPENDED = "USER_SUSPENDED"
"""Mã lỗi TỪNG DÒNG của `POST /members` — không phải một `LoiPortal` (⑤c, review
cuối trước merge).

Người này `lifecycle='suspended'` (đã bị đình chỉ). KHÔNG nối vào workspace:
đình chỉ nghĩa là thu hồi quyền, nên mời họ vào một workspace MỚI qua seam này
sẽ hoàn tác chính việc đình chỉ đó ở phạm vi workspace kia — cấp quyền cho một
tài khoản đang bị khoá là một cửa sau không ai xin phép.
"""


def email_dang_tu_dang_ky() -> LoiPortal:
    """409 — `POST /members/invites/{email}/resend` cho một email nay đang TỰ
    ĐĂNG KÝ dở (`lifecycle='pending'`). Xem `thanh_vien.gui_lai_loi_moi` (phát
    hiện F, review round 2): mang `user_id` cũ đi tiếp ở ca này sẽ hoặc phát một
    token invite_new (`user_id=NULL`) mà `email_da_dung` sẽ luôn thấy đúng —
    409 `EMAIL_DA_CO_TAI_KHOAN` vĩnh viễn — hoặc một token mang `user_id` của
    một user `pending` mà `doc_loi_moi_con_hieu_luc` không nhận nhánh nào — chết
    hẳn, kể cả ở `GET /invites/{token}`. Cùng lý lẽ `USER_PENDING_SIGNUP` ở
    `thanh_vien.moi`: từ chối tường minh, không phát token.
    """
    return LoiPortal(
        "USER_PENDING_SIGNUP",
        409,
        "Địa chỉ này đang tự đăng ký, chưa đặt mật khẩu — gửi lại lời mời sau khi họ hoàn tất, "
        "hoặc thu hồi lời mời này",
    )


def email_bi_dinh_chi() -> LoiPortal:
    """409 — `POST /members/invites/{email}/resend` cho một email nay thuộc
    một tài khoản `suspended`. Cùng lý lẽ `USER_SUSPENDED` ở `thanh_vien.moi`:
    đình chỉ nghĩa là thu hồi quyền, phát lại một lời mời workspace là mở lại
    đúng cửa đó qua một hình dạng khác.
    """
    return LoiPortal(
        "USER_SUSPENDED",
        409,
        "Tài khoản của địa chỉ này đang bị đình chỉ — không thể gửi lại lời mời",
    )


USER_ALREADY_MEMBER = "USER_ALREADY_MEMBER"
"""Mã lỗi TỪNG DÒNG của `POST /members` — không phải một `LoiPortal`.

Người này đã là thành viên của workspace đang mở. Trước 2026-08-22 ca này đi qua
`them_membership` (UPSERT) và im lặng thành công — nghĩa là mời lại một người đã
ở trong nhà cũng trả `daCo=true`, và Quản trị không có cách nào biết mình vừa
không làm gì cả.

Từ 2026-08-22 mọi lời mời đều phải được NGƯỜI NHẬN xác nhận, nên "im lặng thành
công" còn tệ hơn: nó sẽ gửi cho người ta một lá thư mời vào chỗ họ đã ở.
"""


def mat_khau_hien_tai_sai() -> LoiPortal:
    """400 chứ KHÔNG 401: 401 ở FE là dấu hiệu «phiên chết» (SessionProvider
    điều hướng /login) — người đang gõ nhầm mật khẩu CŨ trong màn Hồ sơ không
    đáng bị đá khỏi phiên đang sống."""
    return LoiPortal("MAT_KHAU_HIEN_TAI_SAI", 400, "Mật khẩu hiện tại không đúng")


def khong_co_mat_khau() -> LoiPortal:
    """Tài khoản Google-only (`password_hash IS NULL`, 0108) — không có mật khẩu
    hiện tại để so, và ĐẶT mật khẩu đầu tiên là một luồng khác (xác minh email),
    không phải luồng đổi."""
    return LoiPortal("KHONG_CO_MAT_KHAU", 409, "Tài khoản đăng nhập bằng Google — không có mật khẩu để đổi")
