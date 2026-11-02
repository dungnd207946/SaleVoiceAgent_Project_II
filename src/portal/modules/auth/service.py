"""Logic đăng nhập, đăng ký và dựng SessionOut."""

import secrets
from datetime import UTC, datetime

import asyncpg
from redis.asyncio import Redis

from portal.api import loi
from portal.core import nhat_ky
from portal.core.auth import password as pw
from portal.core.auth import repo as core_repo
from portal.core.auth import session as ss
from portal.core.avatar import avatar_data_uri, chu_cai_dau
from portal.modules.auth import loi as loi_auth
from portal.modules.auth import repo
from portal.modules.auth.contracts import SessionOut, SuaHoSoIn, UserOut
from portal.modules.auth.quan_tri_user import _SO_BYTE_TOKEN, HAN_MOI, bam_token, sinh_user_id

# service CẦN core/auth/repo — không phải để CƯỠNG CHẾ (require() vẫn làm việc
# đó, seam không đổi), mà để BÁO CÁO đúng quyền hiệu lực vào `SessionOut.actions`.
# M2a để service trả cả 13 vì lúc đó require() cũng cấp cả 13 — hai chỗ khớp
# NHỜ TRÙNG HỢP. M2b đổi require() sang tra ma trận nhưng đây là chỗ THỨ HAI của
# "M2b đổi hai chỗ trong cùng một PR" (xem docstring SessionOut.actions): quên
# nó thì FE vẫn hiện mọi nút — đúng cái nút-xám-vô-nghĩa design này tồn tại để
# tránh, chỉ là ở hướng ngược lại (hiện nút mà API chặn, không phải ẩn nút mà
# API cho).


def chuan_hoa_email(email: str) -> str:
    """Chuẩn hoá ở BIÊN NHẬP — một chỗ duy nhất.

    CHECK `email = lower(email)` ở DB (migration 0100) là lưới thứ hai: nếu một
    đường ghi nào quên gọi hàm này thì INSERT nổ, không phải một hàng lệch phát
    hiện sáu tháng sau.
    """
    return email.strip().lower()


def suy_initials(name: str) -> str:
    """Chữ trên avatar vuông ở chân sidebar — UỶ QUYỀN về `core.avatar.chu_cai_dau`.

    SUY chứ không lưu: một cột chứa thông tin đã có trong `name` là một bug đang
    chờ lệch. Một nguồn cho CẢ chữ fallback lẫn chữ trong ảnh DiceBear — hai bản
    của luật này từng lệch thật: bản cũ ở đây lấy HAI ký tự đầu cho tên một từ
    ("Hùng" → "HÙ") trong khi ảnh phải là "H".
    """
    return chu_cai_dau(name)


def _dung_session_out(u: repo.HangUser, ws: list, tenant_id: str | None, actions: frozenset[str]) -> SessionOut:
    """Một chỗ dựng payload, hai đường gọi (login và /me).

    Dựng riêng ở hai chỗ là cách chắc chắn để hai đường lệch nhau một trường, và
    lệch đó chỉ lộ ra sau khi người dùng tải lại trang.
    `test_login_va_me_tra_body_giong_het_nhau` canh đúng điều này.

    `actions` PHẢI đến từ `doc_quyen` của người gọi — không tự tính lại ở đây.
    Một hàm dựng payload không phải chỗ để tra ma trận lần hai.
    """
    return SessionOut(
        user=UserOut(
            id=u.id,
            name=u.name,
            email=u.email,
            initials=suy_initials(u.name),
            # Seed user tự chọn thắng; chưa chọn thì suy từ tên như trước 0952.
            avatar=avatar_data_uri(u.avatar_seed or u.name),
            coMatKhau=u.password_hash is not None,
            phone=u.phone,
            jobTitle=u.job_title,
        ),
        workspaces=ws,
        currentWorkspaceId=tenant_id,
        actions=sorted(actions),
    )


async def dung_session_out(conn: asyncpg.Connection, ban_ghi: ss.BanGhiPhien) -> SessionOut:
    """Dựng payload cho FE từ bản ghi phiên.

    Đọc workspace và user từ DB MỖI lần, không cache vào phiên: xem BR-Q04 ở
    docstring của core/auth/session.py.
    """
    u = await repo.tim_user_theo_id(conn, ban_ghi.user_id)
    if u is None:
        raise loi.khong_co_phien()
    ws = await repo.liet_ke_workspace(conn, ban_ghi.user_id)
    # KHÔNG raise khi `ws` rỗng. Từ 2026-08-15 phiên không workspace là trạng thái
    # HỢP LỆ (spec bo-organization §5.0) — người vừa tự đăng ký đi qua đúng nhánh
    # này, và 409 cũ sẽ là ngõ cụt: không có đường nào tới màn tạo workspace.
    #
    # `doc_quyen` chỉ trả None khi user vừa bị xoá GIỮA hai câu SELECT ở trên và
    # đây — một cuộc đua, không phải đường thường. `frozenset()` (fail closed)
    # là câu trả lời đúng, cùng lý lẽ require() dùng khi mất kết nối: mất thông
    # tin thì từ chối, không phải cấp bừa.
    q = await core_repo.doc_quyen(conn, ban_ghi.user_id, ban_ghi.tenant_id) if ban_ghi.tenant_id is not None else None
    return _dung_session_out(u, ws, ban_ghi.tenant_id, q.actions if q else frozenset())


async def dang_nhap(conn: asyncpg.Connection, r: Redis, *, email: str, mat_khau: str) -> tuple[str, SessionOut]:
    """Trả (session_id, SessionOut). Raise LoiPortal nếu không vào được.

    Thứ tự ba phép kiểm là cố ý: tìm user -> kiểm mật khẩu -> kiểm lifecycle. Kiểm
    lifecycle TRƯỚC mật khẩu sẽ trả lời nhanh cho tài khoản bị đình chỉ, và đồng hồ
    lại tố ra email đó có thật.
    """
    u = await repo.tim_user_theo_email(conn, chuan_hoa_email(email))

    if u is None:
        # Verify vào hash mồi để đường này tốn cùng thời gian với đường sai mật
        # khẩu — nếu không, đồng hồ tự tố ra email nào có thật. Xem core/auth/password.py.
        pw.kiem_gia()
        raise loi.sai_dang_nhap()

    if u.password_hash is None:
        # NULL nghĩa là "không có mật khẩu để so" — KHÔNG chỉ nghĩa `pending`.
        # Trước migration 0108, đúng là chỉ có `pending` (CHECK song điều kiện của
        # 0103 buộc `pending ⇔ NULL` cả hai chiều). 0108 đã BỎ đúng chiều đó: một
        # user Google-only là `active` (hoặc `suspended`) mà `password_hash` vẫn
        # NULL — họ chưa từng đặt mật khẩu, chỉ đăng nhập qua Google. Nhánh này
        # đúng cho CẢ HAI ca vì nó không cần phân biệt: ai không có hash để so đều
        # nhận cùng câu trả lời "sai email/mật khẩu" ở cửa NÀY (cửa mật khẩu) —
        # cửa Google của họ (nếu có) nằm ở `dang_nhap_google.py`, không ở đây.
        #
        # Vì thế phép chặn `None` PHẢI Ở ĐÂY vô điều kiện, không được thu hẹp lại
        # theo `u.lifecycle == "pending"`: một user Google-only gõ email của họ
        # vào form mật khẩu vẫn phải rơi qua đúng nhánh này.
        #
        # `kiem_gia()` chứ không return thẳng: nhánh này KHÔNG được nhanh hơn nhánh
        # sai mật khẩu, nếu không đồng hồ tố ra email nào không có mật khẩu để so
        # (đang chờ mời, HOẶC chỉ đăng nhập bằng Google) — đúng loại rò rỉ mà
        # `kiem_gia()` sinh ra để bịt. Và không được có mã lỗi riêng, cùng lý lẽ
        # với `sai_dang_nhap()` gộp ba tình huống.
        #
        # ⚠ Phải nằm TRƯỚC `pw.kiem()`: Argon2 verify nhận None là TypeError, tức
        # một 500 ở đúng đường đăng nhập.
        pw.kiem_gia()
        raise loi.sai_dang_nhap()

    if not pw.kiem(u.password_hash, mat_khau):
        raise loi.sai_dang_nhap()

    # Đình chỉ dùng CÙNG mã với sai mật khẩu: "tài khoản này bị đình chỉ" cũng là
    # một câu trả lời cho máy dò rằng email đó có thật.
    if u.lifecycle != "active":
        raise loi.sai_dang_nhap()

    ws = await repo.liet_ke_workspace(conn, u.id)
    # 0 workspace KHÔNG còn là lỗi (spec bo-organization §5.0) — phiên mang
    # `tenant_id=None` và FE đưa người dùng tới màn tạo workspace đầu tiên.
    tenant_id = ws[0].id if ws else None

    session_id = await ss.tao(r, user_id=u.id, tenant_id=tenant_id)
    # Cùng lý lẽ `dung_session_out`: actions của SessionOut phải khớp CHÍNH XÁC
    # cái `require()` sẽ thực thi ở request kế tiếp, không phải một hằng số.
    q = await core_repo.doc_quyen(conn, u.id, tenant_id) if tenant_id is not None else None
    return session_id, _dung_session_out(u, ws, tenant_id, q.actions if q else frozenset())


async def dang_ky(conn: asyncpg.Connection, *, email: str, name: str) -> tuple[str, str, bool]:
    """Trả (user_id, token_thô, da_gui_lai). Người gọi mở giao dịch VÀ gửi thư sau commit.

    Ba nhánh (spec §4.1):
      · chưa tồn tại        -> tạo `pending`, phát token          -> da_gui_lai=False (201)
      · tồn tại, `pending`  -> phát token MỚI, token cũ chết      -> da_gui_lai=True  (200)
      · tồn tại, có mật khẩu-> ném `email_da_ton_tai()`           ->                 (409)

    Nhánh ba nói THẲNG là trùng — quyết định người yêu cầu 2026-08-17, spec §7.6.
    Nó KHÔNG kéo theo nới lỏng nào ở `dang_nhap`: xem spec §4.2b.

    KHÔNG tạo phiên, KHÔNG đặt cookie: mật khẩu chưa tồn tại tại thời điểm này —
    xem docstring router. KHÔNG xác thực email nào khác ngoài việc gửi thư này:
    chính cái link mới là phép xác thực (bấm được nghĩa là hộp thư có thật).
    """
    email = chuan_hoa_email(email)
    u = await repo.tim_user_theo_email(conn, email)

    if u is not None and u.lifecycle != "pending":
        raise loi_auth.email_da_ton_tai()

    if u is None:
        user_id = await sinh_user_id(conn, email)
        await repo.tao_user_tu_dang_ky(conn, user_id=user_id, email=email, name=name.strip())
        da_gui_lai = False
    else:
        user_id = u.id
        da_gui_lai = True

    token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
    await repo.ghi_loi_moi_dang_ky(
        conn,
        token_hash=bam_token(token),
        user_id=user_id,
        email=email,
        expires_at=datetime.now(UTC) + HAN_MOI,
        created_by=user_id,  # không ai khác tạo hàng này
    )
    await nhat_ky.ghi_he_thong(conn, "user.dang_ky", user_id, {"email": email, "gui_lai": da_gui_lai})
    return user_id, token, da_gui_lai


async def sua_ho_so(conn: asyncpg.Connection, user_id: str, body: SuaHoSoIn) -> None:
    """Ghi đúng những trường CÓ MẶT trong payload — `model_fields_set` là ranh.

    Không trả gì: router dựng lại `SessionOut` qua `dung_session_out` — một
    đường dựng payload duy nhất, đúng lý do `_dung_session_out` tồn tại.
    """
    cot: dict[str, str | None] = {}
    if "name" in body.model_fields_set:
        if body.name is None:
            # `name: null` không có nghĩa nào (tên là NOT NULL) — nói thẳng thay
            # vì im lặng bỏ qua một payload dị dạng.
            raise loi.LoiPortal("NAME_NULL", 422, "Trường name không nhận null — muốn giữ nguyên thì đừng gửi khoá này")
        cot["name"] = body.name
    if "phone" in body.model_fields_set:
        cot["phone"] = body.phone
    if "jobTitle" in body.model_fields_set:
        cot["job_title"] = body.jobTitle
    if "avatarSeed" in body.model_fields_set:
        cot["avatar_seed"] = body.avatarSeed

    if not cot:
        return
    await repo.sua_ho_so_cua_minh(conn, user_id, cot)
    await nhat_ky.ghi_he_thong(conn, "user.sua_ho_so", user_id, {"truong": sorted(cot)})


async def doi_mat_khau(conn: asyncpg.Connection, user_id: str, *, mat_khau_hien_tai: str, mat_khau_moi: str) -> None:
    """Tự đổi mật khẩu của CHÍNH MÌNH — xác thực lại bằng mật khẩu hiện tại.

    Không revoke các phiên khác của user (ngoài phạm vi, ghi nhận có chủ ý):
    phiên sống trong Redis theo TTL, và người đổi mật khẩu vì «máy kia còn đăng
    nhập» sẽ cần một màn quản lý phiên riêng — không phải một side effect ngầm
    ở đây.
    """
    u = await repo.tim_user_theo_id(conn, user_id)
    if u is None:
        raise loi.khong_co_phien()
    if u.password_hash is None:
        raise loi_auth.khong_co_mat_khau()
    if not pw.kiem(u.password_hash, mat_khau_hien_tai):
        raise loi_auth.mat_khau_hien_tai_sai()
    await repo.doi_password_hash(conn, user_id, pw.bam(mat_khau_moi))
    # KHÔNG ghi mật khẩu (kể cả hash) vào chi tiết nhật ký — chỉ ghi sự kiện.
    await nhat_ky.ghi_he_thong(conn, "user.doi_mat_khau", user_id, {})
