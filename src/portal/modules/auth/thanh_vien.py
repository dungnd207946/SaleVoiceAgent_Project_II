"""Nghiệp vụ seam `/members` — người trong MỘT workspace.

VÌ SAO KHÔNG NẰM TRONG `quan_tri_user.py`: file đó là khối quản trị TOÀN HỆ THỐNG
và đang bị `USERS_ADMIN_ENABLED` đóng (0106). Khối này thì mở và gate bằng
`WORKSPACE_ADMIN`. Hai vòng đời khác nhau, hai cổng khác nhau — gộp lại thì bật
tắt một cái là chạm cái kia.

MỌI đường ở đây lấy `tenant_id` từ `Principal`, không bao giờ từ body.
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

from portal.core import nhat_ky
from portal.modules.auth import loi, repo
from portal.modules.auth.contracts import (
    KetQuaMoiOut,
    LoiMoiTungDongOut,
    MemberOut,
    MoiThanhVienIn,
    MoiThanhVienRaOut,
)
from portal.modules.auth.quan_tri_user import (
    _SO_BYTE_TOKEN,
    HAN_MOI,
    bam_token,
    duong_dan_moi,
)


@dataclass(frozen=True, slots=True)
class ThuCanGui:
    """Một lá thư mà ROUTER phải gửi SAU commit. Ba giá trị đi cùng nhau vì `router`
    cần cả ba để chọn ĐÚNG một trong hai thư (`thu_loi_moi_moi` / `thu_loi_moi_da_co`).

    `da_co` chứ không phải `user_id`: người gọi không cần biết id, nó cần biết nói
    câu nào. Trả `user_id` rồi để router tự suy `is not None` là chuyển một quyết
    định nghiệp vụ sang tầng HTTP.
    """

    email: str
    token: str
    da_co: bool


async def moi(
    conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, vao: MoiThanhVienIn
) -> tuple[MoiThanhVienRaOut, list[ThuCanGui]]:
    """Trả (kết quả, thư cần gửi). Người gọi mở giao dịch VÀ gửi thư SAU commit.

    ═══════════════════════════════════════════════════════════════════════════
     MỜI = HỎI. Không nhánh nào ghi `memberships` nữa (2026-08-22).
    ═══════════════════════════════════════════════════════════════════════════
    Trước đó hàm này ghi `memberships` ở HAI nhánh — email mới (kèm `tao_user`) và
    email đã `active`. Cả hai là "làm thay vì hỏi": người nhận có một suất trong
    workspace trước khi họ nói đồng ý. Membership giờ sinh ra ở đúng một chỗ,
    `quan_tri_user.nhan_loi_moi`, và chỉ khi người nhận bấm nút.

    Token thô đi ra qua giá trị trả về chứ không đọc lại từ DB: DB chỉ có `sha256`.
    """
    if not await repo.role_ton_tai(conn, vao.roleId):
        # ⚠ Đừng "sửa" thành `loi.vai_tro_khong_ton_tai()`: tên đó ĐÃ có nghĩa
        # khác trong module này (404, dùng cho GET/PATCH/DELETE /roles/{id}, neo
        # bởi test_vai_tro.py). Hàm đúng cho seam này — 422, ROLE_NOT_FOUND, cho
        # role_id là một TRƯỜNG trong thân request — là
        # `vai_tro_khong_ton_tai_trong_yeu_cau()` (xem docstring của nó trong
        # loi.py).
        raise loi.vai_tro_khong_ton_tai_trong_yeu_cau()

    ok: list[KetQuaMoiOut] = []
    hong: list[LoiMoiTungDongOut] = []
    thu: list[ThuCanGui] = []
    han = datetime.now(UTC) + HAN_MOI

    for email in vao.emails:
        u = await repo.tim_user_theo_email(conn, email)

        if u is not None and u.lifecycle == "pending":
            # GIỮ NGUYÊN quyết định cũ (xem lịch sử docstring này): người đang dở
            # tự đăng ký chỉ có MỘT token đăng ký sống, và phát token mời cho họ
            # giết nó — họ bấm link trong hộp thư và ăn `INVITE_INVALID`.
            #
            # 0952 làm ca này KHẢ THI về mặt schema (hai chỉ mục bộ phận cho phép
            # một email có cả token đăng ký lẫn token mời). Vẫn KHÔNG làm: nhận
            # một lời mời `invite_existing` đòi tài khoản `active`, mà tài khoản
            # này chưa có mật khẩu — nên lời mời đó sẽ không nhận được, chỉ là
            # thất bại muộn hơn và khó hiểu hơn.
            #
            # QUYẾT ĐỊNH CÓ CHỦ Ý, GIỮ NGUYÊN (review cuối trước merge): nhánh này
            # KHÔNG ghi bất kỳ membership nào cho email đang `pending` — dù người
            # đó đang dở đăng ký do CHÍNH họ tự khởi (`POST /auth/register`) hay do
            # một admin KHÁC mời trước (admin A mời, giờ admin B mời lại). Cấp
            # quyền workspace cho một tài khoản chưa có mật khẩu là một mùi riêng
            # (ai đó chiếm được token đăng ký coi như chiếm luôn quyền vào
            # workspace B vừa gán) — rẻ hơn nhiều so với vừa dựng nghiệp vụ đó vừa
            # phải nghĩ cho đúng nó.
            #
            # HỆ QUẢ CHO NGƯỜI MỜI (admin B): lời mời này KHÔNG có tác dụng gì
            # ngoài một dòng lỗi — không membership, không token, không thư nào
            # được gửi cho email này ở lượt gọi hiện tại (nhánh này bác BƯỚC ĐẦU
            # TIÊN, trước khi có hàng `invites` nào của workspace này để mà gửi
            # lại). B phải tự nhớ QUAY LẠI mời bằng `POST /members` SAU KHI người
            # kia đặt xong mật khẩu (lifecycle chuyển `active`) — hệ thống không
            # tự làm hộ và không có hàng chờ nào ghi việc "B từng muốn mời". Xem
            # spec §4.4 (mục "Hệ quả mất membership") cho cùng quyết định này từ
            # góc nhìn spec.
            hong.append(LoiMoiTungDongOut(email=email, ma=loi.USER_PENDING_SIGNUP))
            continue

        if u is not None and u.lifecycle == "suspended":
            # ⑤c: KHÔNG nối vào workspace. Trước bản sửa này, `suspended` rơi
            # chung nhánh "đã có tài khoản" bên dưới và ĐƯỢC cấp membership
            # (`daCo=true`) — tức cấp quyền workspace cho một tài khoản đang bị
            # đình chỉ, đúng lúc đình chỉ có nghĩa "thu hồi quyền". Tách riêng,
            # cùng cơ chế `loi[]` từng-dòng với `USER_PENDING_SIGNUP` ở trên.
            hong.append(LoiMoiTungDongOut(email=email, ma=loi.USER_SUSPENDED))
            continue

        if u is not None and await repo.la_thanh_vien(conn, user_id=u.id, tenant_id=tenant_id):
            # MỚI 2026-08-22. Trước đây rơi vào nhánh `active` bên dưới và UPSERT
            # im lặng — tức mời lại người đã ở trong nhà cũng trả `daCo=true`, và
            # nếu `roleId` lượt này khác thì nó ĐỔI VAI TRÒ của họ qua đường mời.
            # Nay đường đổi vai trò là `PATCH /members/{id}`, đúng một chỗ.
            hong.append(LoiMoiTungDongOut(email=email, ma=loi.USER_ALREADY_MEMBER))
            continue

        token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
        await repo.ghi_loi_moi_workspace(
            conn,
            token_hash=bam_token(token),
            email=email,
            user_id=u.id if u is not None else None,
            tenant_id=tenant_id,
            role_id=vao.roleId,
            expires_at=han,
            created_by=actor_id,
        )
        thu.append(ThuCanGui(email=email, token=token, da_co=u is not None))
        ok.append(
            KetQuaMoiOut(
                email=email,
                userId=u.id if u is not None else None,
                invitePath=duong_dan_moi(token),
                daCo=u is not None,
            )
        )

    await nhat_ky.ghi(
        conn,
        tenant_id,
        "thanh_vien.moi",
        actor_id,
        {"so_moi": len(ok), "so_hong": len(hong), "role_id": vao.roleId},
    )
    return MoiThanhVienRaOut(invites=ok, loi=hong), thu


async def doi_vai_tro(
    conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, user_id: str, role_id: str
) -> MemberOut:
    """Chạm ĐÚNG một hàng `memberships`.

    ĐỪNG thay bằng `repo.dat_lai_membership` — hàm đó THAY THẾ TOÀN BỘ membership
    của user, nên gọi nó với một dòng là xoá sạch vai trò của họ ở mọi workspace
    khác (bug mất dữ liệu thật, 2026-08-06).
    """
    if not await repo.role_ton_tai(conn, role_id):
        raise loi.vai_tro_khong_ton_tai_trong_yeu_cau()
    if not await repo.doi_vai_tro_thanh_vien(conn, user_id=user_id, tenant_id=tenant_id, role_id=role_id):
        raise loi.user_khong_ton_tai()

    await nhat_ky.ghi(conn, tenant_id, "thanh_vien.doi_vai_tro", actor_id, {"user_id": user_id, "role_id": role_id})
    m = await repo.doc_thanh_vien(conn, tenant_id=tenant_id, user_id=user_id)
    assert m is not None, "vừa UPDATE trong cùng giao dịch"
    return m


async def go(conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, user_id: str) -> None:
    """Gỡ khỏi WORKSPACE, KHÔNG xoá tài khoản.

    Tự gỡ chính mình bị chặn: một workspace mất Quản trị cuối cùng là một workspace
    không ai mời thêm được ai, và không có admin hệ thống để gỡ (0106).
    """
    if user_id == actor_id:
        raise loi.tu_khoa_cua_minh("Bạn không thể tự gỡ mình khỏi workspace đang mở")
    if not await repo.go_thanh_vien(conn, user_id=user_id, tenant_id=tenant_id):
        raise loi.user_khong_ton_tai()
    await nhat_ky.ghi(conn, tenant_id, "thanh_vien.go", actor_id, {"user_id": user_id})


async def moi_lai(conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, user_id: str) -> str:
    """Trả token THÔ. Token cũ chết tại đây — `repo.ghi_loi_moi_dang_ky` UPSERT vào
    chỉ mục bộ phận `(email) WHERE tenant_id IS NULL` (0952; KHÔNG còn
    `UNIQUE (invites.user_id)` như trước — cột đó đã bỏ ràng buộc unique cùng
    migration tách hai chỉ mục bộ phận).

    Chỉ áp cho người còn `pending`: sinh thư mời cho người đã có mật khẩu là tạo
    một đường đặt lại mật khẩu mà không ai yêu cầu.

    KHÁC `gui_lai_loi_moi` ngay dưới, và không gộp được (ruling 2026-08-22 sau khi
    phát hiện hàm này gọi một `repo.ghi_loi_moi` đã KHÔNG CÒN TỒN TẠI — 0952 xoá
    nó cùng lúc tách thành `ghi_loi_moi_dang_ky`/`ghi_loi_moi_workspace`): hàm này
    phục vụ một hàng THÀNH VIÊN — `user_id` đã có membership ở workspace này từ
    trước (qua `cli/seed_owner.py`, hoặc `/users` admin `tao()` lúc còn bật), chỉ
    thiếu mật khẩu. `gui_lai_loi_moi` phục vụ một hàng LỜI MỜI — không membership
    nào tồn tại, người nhận còn phải nói đồng ý.

    Vì vậy token ở đây là SIGNUP-SHAPED (`tenant_id=NULL`), không workspace-shaped:
    membership ĐÃ CÓ, cái duy nhất còn thiếu là mật khẩu — đúng nghĩa `signup`, và
    `doc_loi_moi_con_hieu_luc` chỉ chấp nhận `tenant_id IS NOT NULL` khi user đã
    `active` (`invite_existing`) hoặc `user_id IS NULL` (`invite_new`); một user
    `pending` (định nghĩa của nhánh này) không khớp cả hai, nên một token mang
    `tenant_id` ở đây sẽ KHÔNG BAO GIỜ redeem được — mint xong, chết ngay, không
    ai báo lỗi. ĐỪNG "khôi phục" `tenant_id` ở đây coi như sửa một thiếu sót.
    """
    m = await repo.doc_thanh_vien(conn, tenant_id=tenant_id, user_id=user_id)
    if m is None:
        raise loi.user_khong_ton_tai()
    u = await repo.tim_user_theo_id(conn, user_id)
    if u is None or u.lifecycle != "pending":
        raise loi.user_da_nhan_moi()

    token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
    await repo.ghi_loi_moi_dang_ky(
        conn,
        token_hash=bam_token(token),
        user_id=user_id,
        email=u.email,
        expires_at=datetime.now(UTC) + HAN_MOI,
        created_by=actor_id,
    )
    await nhat_ky.ghi(conn, tenant_id, "thanh_vien.moi_lai", actor_id, {"user_id": user_id})
    return token


async def gui_lai_loi_moi(conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, email: str) -> ThuCanGui:
    """Cấp token MỚI cho một lời mời đang treo. Token cũ chết tại đây.

    KHÁC `moi_lai(user_id)` ngay bên trên, và hai hàm này KHÔNG gộp được: `moi_lai`
    phục vụ một hàng THÀNH VIÊN còn `lifecycle='pending'` (di sản — sau 2026-08-22
    không sinh thêm ca đó nữa), định danh bằng `user_id`, và nó đặt lại mật khẩu.
    Hàm này phục vụ một hàng LỜI MỜI, định danh bằng `email` vì có thể chẳng có
    `user_id` nào, và nó không chạm mật khẩu của ai.

    ĐỌC LẠI TRẠNG THÁI EMAIL NGAY LÚC PHÁT TOKEN MỚI (finding F, review round 2)
    — `cu["user_id"]` là ảnh chụp lúc lời mời GỐC được phát, có thể đã CŨ. Ca
    thật: lời mời phát khi email chưa có tài khoản (`user_id=NULL`, invite_new);
    admin bấm "Gửi lại" SAU KHI chính email đó đã tự đăng ký và trở thành
    `active`. Mang `user_id=NULL` cũ đi tiếp thì token mới VẪN mang hình
    invite_new — mọi lượt accept sau đó rơi vào nhánh `invite_new` của
    `quan_tri_user.nhan_loi_moi`, thấy `repo.email_da_dung` = True (đúng, tài
    khoản đã có) và 409 `EMAIL_DA_CO_TAI_KHOAN` VĨNH VIỄN: admin không còn cách
    nào sửa ngoài thu hồi rồi mời lại từ đầu — một lời mời "gửi lại" mà không
    ai gửi lại được là một cái tên nói dối. Tra lại bằng `tim_user_theo_email`
    ở ĐÚNG lúc phát token mới khớp cái mà thế giới đang là, không phải cái nó
    đã từng là.

    BA NHÁNH, ĐÚNG lý lẽ `moi()` — không hơn, không kém, không có nhánh thứ tư:
      · KHÔNG có tài khoản (`u is None`) → vẫn `invite_new` (`user_id=None`).
      · `active`                         → `invite_existing` (`user_id=u.id`) —
        đây là ca sửa của finding F.
      · `pending`/`suspended`            → TỪ CHỐI, không phát token mới. Đừng
        "sửa" bằng cách gán `user_id=u.id` cho một user `pending`: đó là HÌNH
        THỨ TƯ mà `doc_loi_moi_con_hieu_luc` không nhận nhánh nào của nó (nó chỉ
        nhận `tenant_id` khớp `user_id IS NULL` HOẶC `user.lifecycle='active'`)
        — một token không BAO GIỜ redeem được, chết ngay ở `GET /invites/{token}`
        (`INVITE_INVALID`), còn tệ hơn 409 hiện tại. Gán `user_id=None` thay vào
        đó thì lại rơi đúng vào cái vòng 409 vĩnh viễn ở trên, chỉ đổi hướng tới.
        Từ chối tường minh — cùng cơ chế `moi()` đã chọn cho chính hai trạng
        thái này (`USER_PENDING_SIGNUP`/`USER_SUSPENDED`).
    """
    cu = await repo.doc_loi_moi_treo(conn, tenant_id=tenant_id, email=email)
    if cu is None:
        raise loi.loi_moi_khong_ton_tai()

    u = await repo.tim_user_theo_email(conn, email)
    if u is not None and u.lifecycle == "pending":
        raise loi.email_dang_tu_dang_ky()
    if u is not None and u.lifecycle == "suspended":
        raise loi.email_bi_dinh_chi()
    user_id_moi = u.id if (u is not None and u.lifecycle == "active") else None

    token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
    await repo.ghi_loi_moi_workspace(
        conn,
        token_hash=bam_token(token),
        email=email,
        user_id=user_id_moi,
        tenant_id=tenant_id,
        role_id=cu["role_id"],
        expires_at=datetime.now(UTC) + HAN_MOI,
        created_by=actor_id,
    )
    await nhat_ky.ghi(conn, tenant_id, "thanh_vien.gui_lai_moi", actor_id, {"email": email})
    return ThuCanGui(email=email, token=token, da_co=user_id_moi is not None)


async def thu_hoi_loi_moi(conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, email: str) -> None:
    """XOÁ hàng lời mời. 404 khi không có gì để thu hồi (bấm hai lần, hoặc người
    kia vừa nhận xong) — im lặng 204 ở đây nói với admin rằng họ vừa rút lại một
    lời mời mà thật ra đã thành một membership."""
    if not await repo.thu_hoi_loi_moi(conn, tenant_id=tenant_id, email=email):
        raise loi.loi_moi_khong_ton_tai()
    await nhat_ky.ghi(conn, tenant_id, "thanh_vien.thu_hoi_moi", actor_id, {"email": email})
