"""ROUTER của module auth.

MỌI endpoint khai `action` của nó — cổng 1 quét và làm CI đỏ nếu thiếu. Ba đường
dưới đây công khai hoặc chỉ-cần-phiên, và cả ba khai TƯỜNG MINH lý do: "công
khai có chủ ý" phải phân biệt được với "quên khai".

Đường ở đây viết TƯƠNG ĐỐI ('/auth/login', không phải '/api/v1/auth/login') —
tiền tố do api/app.py gắn, một chỗ duy nhất.
"""

import secrets
from typing import TYPE_CHECKING

import asyncpg
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from redis.asyncio import Redis

if TYPE_CHECKING:
    from portal.core.config import Settings

from portal.api import loi
from portal.core import mailer
from portal.core.auth import oauth_google
from portal.core.auth import repo as core_repo  # doc_quyen — seam cách ly
from portal.core.auth import session as ss
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_ban_ghi_phien, lay_pool, lay_redis, require
from portal.core.avatar import TEN_STYLES_GOI_Y, sinh_avatar_data_uri
from portal.modules.auth import dang_nhap_google, quan_tri_user, quan_tri_vai_tro, repo, service, thanh_vien, thu
from portal.modules.auth.contracts import (
    ActionOut,
    DangKyRaOut,
    DoiMatKhauIn,
    DoiVaiTroThanhVienIn,
    GoiYAvatarOut,
    LoiMoiOut,
    MemberOut,
    MoiLaiRaOut,
    MoiThanhVienIn,
    MoiThanhVienRaOut,
    NhanLoiMoiIn,
    SessionOut,
    SuaHoSoIn,
    SuaUserIn,
    SuaVaiTroIn,
    TaoUserIn,
    TaoUserRaOut,
    TaoVaiTroIn,
    UserDetailOut,
    UserListItemOut,
    VaiTroChiTietOut,
    VaiTroOut,
    VaoDangKy,
)

ROUTER = APIRouter()


class VaoDangNhap(BaseModel):
    email: str
    password: str


class VaoDoiWorkspace(BaseModel):
    workspaceId: str


def _secure() -> bool:
    """Cờ Secure — đọc cấu hình MỖI lần, mặc định True (core/config.py).

    Import trong hàm chứ không ở đầu file, theo lối core/storage.py đang dùng:
    giữ cấu hình ra ngoài thời điểm import module, nên test đổi được nó mà không
    phải nạp lại router.

    Đặt/xoá cookie phải dùng CHUNG hàm này. Lệch nhau một cờ là tắt Secure xong
    đăng nhập chạy còn đăng xuất hỏng — xem `_xoa_cookie`.
    """
    from portal.core.config import get_settings

    return get_settings().cookie_secure


def _dat_cookie(res: Response, session_id: str) -> None:
    """HttpOnly: JS không đọc được, nên một lỗ XSS không tự động thành mất phiên.

    Secure: trình duyệt miễn trừ `http://localhost` nên dev vẫn chạy, còn production
    thì cookie không bao giờ đi qua đường không mã hoá. Tắt được qua COOKIE_SECURE
    cho một kịch bản dev duy nhất — mở portal từ máy khác trong LAN bằng IP, nơi
    miễn trừ localhost không áp dụng. Lý do đầy đủ ở `Settings.cookie_secure`.

    SameSite=Lax đủ vì FE và API cùng gốc (vite proxy '^/api/'). Tách domain thì
    phải đổi sang None + Secure + token CSRF — xem spec §2.4, và đừng quên nửa sau.
    """
    res.set_cookie(
        ss.TEN_COOKIE,
        session_id,
        max_age=ss.TTL_GIAY,
        httponly=True,
        secure=_secure(),
        samesite="lax",
        path="/",
    )


def _xoa_cookie(res: Response) -> None:
    """Cặp đôi của `_dat_cookie` — mọi thuộc tính phải khớp lúc đặt.

    `path` khớp vì nếu không trình duyệt coi là cookie khác và giữ nguyên cái cũ.
    `secure` khớp vì delete_cookie cũng chỉ là một Set-Cookie: gắn Secure lên nó
    rồi gửi qua http là trình duyệt vứt luôn lệnh xoá — phiên bị thu hồi ở Redis
    nhưng cookie chết vẫn đi kèm mọi request tới khi hết hạn.
    """
    res.delete_cookie(ss.TEN_COOKIE, path="/", httponly=True, secure=_secure(), samesite="lax")


@ROUTER.post("/auth/login", response_model=SessionOut)
async def dang_nhap(
    vao: VaoDangNhap,
    res: Response,
    _: None = require(None, ly_do="chưa có phiên nên không có gì để kiểm"),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> SessionOut:
    async with pool.acquire() as conn:
        session_id, ra = await service.dang_nhap(conn, r, email=vao.email, mat_khau=vao.password)
    _dat_cookie(res, session_id)
    return ra


@ROUTER.post("/auth/register", response_model=DangKyRaOut)
async def dang_ky(
    vao: VaoDangKy,
    res: Response,
    _: None = require(None, ly_do="chính đường này tạo ra tài khoản đầu tiên — đòi phiên là vòng tròn"),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DangKyRaOut:
    """201 = tài khoản mới · 200 = đã gửi lại thư · 409 = email đã có tài khoản.

    KHÔNG đặt cookie phiên: mật khẩu chưa tồn tại tại thời điểm này. Người dùng
    qua hộp thư -> `/invite/<token>` -> `/login`. Đây là bước LÙI có chủ ý so với
    bản trước (đăng ký xong vào thẳng) — cái giá của xác thực email.
    """
    from portal.core.config import get_settings

    c = get_settings()
    c.kiem_tra_dang_ky_mau_thuan_san_xuat()
    if not c.signup_enabled:
        raise loi.tinh_nang_dang_tat("đăng ký tài khoản")

    async with pool.acquire() as conn, conn.transaction():
        _, token, da_gui_lai = await service.dang_ky(conn, email=vao.email, name=vao.name)

    url = mailer.url_tuyet_doi(quan_tri_user.duong_dan_moi(token)) if mailer.dang_bat() else ""
    # Nội dung dựng ở `thu.py`, KHÔNG nhúng ở đây — xem docstring module đó.
    t = thu.thu_dang_ky(ten=vao.name, email=vao.email, url=url)
    await mailer.gui(
        den=vao.email, tieu_de=t.tieu_de, than_text=t.than_text, than_html=t.than_html, anh_nhung=t.anh_nhung
    )
    res.status_code = 200 if da_gui_lai else 201
    return DangKyRaOut(daGuiLai=da_gui_lai)


@ROUTER.post("/auth/logout", status_code=204)
async def dang_xuat(
    request: Request,
    res: Response,
    _: None = require(None, ly_do="đăng xuất phải chạy được cả khi phiên đã hết hạn"),
    r: Redis = Depends(lay_redis),
) -> None:
    # KHÔNG dùng lay_ban_ghi_phien: đăng xuất trên một phiên đã hết hạn phải trả
    # 204, không phải 401. Người dùng bấm Đăng xuất và nhận lỗi là vô lý — và tệ
    # hơn, FE sẽ không biết có nên xoá state phía client hay không. Luỹ đẳng.
    sid = request.cookies.get(ss.TEN_COOKIE, "")
    if sid:
        await ss.xoa(r, sid)

    # Hai việc, không phải một. Xoá bản ghi Redis là thu hồi THẬT (cổng 10); xoá
    # cookie là để trình duyệt thôi gửi một giá trị đã chết ở mọi request sau đó.
    # Thiếu vế sau thì mỗi lần tải trang là một lượt tra Redis vô ích, và devtool
    # vẫn hiện một cookie phiên như thể còn đăng nhập.
    _xoa_cookie(res)


@ROUTER.get("/me", response_model=SessionOut)
async def phien_hien_tai(
    _: None = require(None, ly_do="chính nó là đường FE hỏi 'tôi đã đăng nhập chưa'"),
    phien: tuple[str, ss.BanGhiPhien] = Depends(lay_ban_ghi_phien),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> SessionOut:
    """Trả phiên, và TỰ CHỮA con trỏ nếu nó chỉ vào workspace không còn thấy được.

    ═══════════════════════════════════════════════════════════════════════════
     VÌ SAO ĐƯỜNG NÀY PHẢI GHI, DÙ NÓ LÀ MỘT `GET`
    ═══════════════════════════════════════════════════════════════════════════
    Xoá workspace là XOÁ CỨNG, nên `control.tenants` không còn hàng nào cho id đó và
    `liet_ke_workspace` thôi trả nó về. Nhưng bản ghi phiên nằm ở REDIS, ngoài mọi
    cascade của Postgres — nên mọi phiên KHÁC vẫn trỏ vào id đã chết: tab thứ hai,
    máy thứ hai, và mọi THÀNH VIÊN đang mở nó lúc Quản trị bấm Xoá — nhận một
    `currentWorkspaceId` không có trong `workspaces`. `SessionReady` của FE
    (lib/session.tsx) ném "Phiên không có workspace nào" cho đúng hình dạng đó:
    một màn trắng cho người chẳng bấm gì cả.

    Endpoint xoá đã dời con trỏ của phiên NGƯỜI XOÁ. Nó không với tới được các
    phiên khác — chúng nằm dưới những khoá Redis mà nó không biết. Nên chỗ chữa
    đúng là ở đây: mỗi phiên tự sửa mình ở lần hỏi kế tiếp.

    KHÔNG chỉ sửa payload trả về mà bỏ qua Redis: bản ghi phiên là NGUỒN SỰ THẬT
    của `require()`, nên một payload "đã sửa" chồng lên một bản ghi chưa sửa
    nghĩa là FE hiện workspace mới trong khi mọi request vẫn 403 theo workspace cũ.

    KHÔNG gộp vào `require()`: nó chạy ở mọi endpoint và phải là một phép ĐỌC.
    Một cổng quyền ghi Redis mỗi request là thứ rất khó suy luận về sau.
    """
    sid, ban_ghi = phien
    async with pool.acquire() as conn:
        ra = await service.dung_session_out(conn, ban_ghi)

        if ra.currentWorkspaceId is not None and all(w.id != ra.currentWorkspaceId for w in ra.workspaces):
            # `workspaces[0]` — danh sách đã `ORDER BY name`, nên phiên nhảy sang
            # đúng mục ĐẦU TIÊN của switcher. `None` khi không còn cái nào: hợp lệ
            # từ 2026-08-15 (spec bo-organization §5.0), cùng trạng thái với người
            # vừa tự đăng ký.
            moi = ra.workspaces[0].id if ra.workspaces else None
            await ss.doi_workspace(r, sid, moi)
            ra = await service.dung_session_out(conn, ss.BanGhiPhien(ban_ghi.user_id, moi))

    return ra


@ROUTER.post("/me/workspace", response_model=SessionOut)
async def doi_workspace(
    vao: VaoDoiWorkspace,
    _: None = require(None, ly_do="đang ĐỔI workspace nên workspace cũ không phải điều kiện"),
    phien: tuple[str, ss.BanGhiPhien] = Depends(lay_ban_ghi_phien),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> SessionOut:
    sid, ban_ghi = phien

    async with pool.acquire() as conn:
        # KIỂM TRƯỚC KHI GHI. Ghi trước rồi kiểm nghĩa là một request 403 vẫn để
        # lại phiên trỏ vào workspace lạ, và mọi request sau 403 mãi mà người dùng
        # không hiểu vì sao. Cổng 9 canh đúng điều này.
        q = await core_repo.doc_quyen(conn, ban_ghi.user_id, vao.workspaceId)
        if q is None or not (q.co_membership or q.actions) or q.tenant_lifecycle != "active":
            # Không phân biệt "không tồn tại" với "không thuộc" — phân biệt là cho
            # không một máy dò danh sách workspace của mọi khách hàng.
            #
            # `q.co_membership` — KHÔNG `q.actions` — là câu hỏi thật ở đây: "có
            # phải thành viên workspace này không". Một member giữ vai trò 0
            # quyền (trạng thái HỢP LỆ — §2.1 "đã tạo, chưa cấu hình") vẫn có
            # `co_membership=True` nên vẫn đổi được — chỉ là sau đó `require()`
            # chặn hết mọi action. Dùng `actions` một mình ở đây từng là bug: nó
            # trả True cho switcher (`liet_ke_workspace` chỉ cần một hàng
            # memberships) rồi 403 lúc bấm vào, đúng thứ dòng comment ở
            # `test_to_chuc.py` cảnh báo.
            #
            # `or q.actions`: owner hợp lệ trong org của mình có `actions` đầy
            # mà KHÔNG CẦN một hàng `memberships` nào (§3.3) — `co_membership`
            # của họ có thể là False, và đó không phải lý do chặn.
            #
            # `tenant_lifecycle != 'active'` CHẶN ĐƯỜNG QUAY LẠI một workspace đã
            # xoá. Đường này khai `require(None, ...)` nên nó KHÔNG đi qua phép
            # kiểm `WORKSPACE_DA_DONG` của `require()` — và membership vẫn còn
            # nguyên sau khi xoá, nên hai vế trên vẫn nói "được vào". Thiếu vế này
            # thì switcher không hiện workspace đã xoá nhưng một request thẳng vào
            # `POST /me/workspace` vẫn ghim phiên vào nó, và mọi màn sau đó 403.
            raise loi.khong_du_quyen()

        await ss.doi_workspace(r, sid, vao.workspaceId)
        return await service.dung_session_out(conn, ss.BanGhiPhien(ban_ghi.user_id, vao.workspaceId))


@ROUTER.patch("/me/ho-so", response_model=SessionOut)
async def sua_ho_so(
    body: SuaHoSoIn,
    _: None = require(None, ly_do="tự sửa hồ sơ CHÍNH MÌNH — không đụng tài nguyên của workspace nào"),
    phien: tuple[str, ss.BanGhiPhien] = Depends(lay_ban_ghi_phien),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> SessionOut:
    """Màn «Hồ sơ & tuỳ chọn». VẮNG KHOÁ = không đổi; `avatarSeed: null` = về
    avatar mặc định suy từ tên. Trả `SessionOut` MỚI để FE ghi thẳng vào cache
    phiên — avatar ở chân sidebar đổi ngay, không chờ refetch `/me`.

    KHÔNG đi qua khối `/users*` (USERS_ADMIN_ENABLED): `sua_ho_so` chỉ nhận
    `user_id` từ CHÍNH bản ghi phiên — không có tham số nào chọn người khác.
    """
    _sid, ban_ghi = phien
    async with pool.acquire() as conn, conn.transaction():
        await service.sua_ho_so(conn, ban_ghi.user_id, body)
        return await service.dung_session_out(conn, ban_ghi)


@ROUTER.get("/me/avatar-goi-y", response_model=list[GoiYAvatarOut])
async def avatar_goi_y(
    _: None = require(None, ly_do="sinh gợi ý cho chính mình — không đọc dữ liệu của ai"),
    __: tuple[str, ss.BanGhiPhien] = Depends(lay_ban_ghi_phien),
) -> list[GoiYAvatarOut]:
    """Lưới «Đổi avatar» — MỖI style trong sổ góp 4 ô (người dùng chốt
    2026-08-22: mặc định nghiêm túc là initials theo tên, còn lưới gợi ý thì
    nhiều kiểu khác nhau cho ai muốn đổi). Muốn bộ khác thì gọi lại.

    Seed mang TIỀN TỐ `style:` (hợp đồng của `core/avatar.py::_tach`) và sinh
    Ở SERVER (`secrets.token_urlsafe`); avatar sinh KHÔNG qua `lru_cache`
    (`sinh_avatar_data_uri`): hàng chục seed dùng-một-lần mỗi lượt bấm sẽ flood
    cache của những seed thật đang sống trong danh sách khách.
    """
    goi_y = []
    for style in TEN_STYLES_GOI_Y:
        for _i in range(4):
            seed = f"{style}:{secrets.token_urlsafe(8)}"
            goi_y.append(GoiYAvatarOut(seed=seed, avatar=sinh_avatar_data_uri(seed)))
    return goi_y


@ROUTER.post("/me/mat-khau", status_code=204)
async def doi_mat_khau(
    body: DoiMatKhauIn,
    _: None = require(None, ly_do="đổi mật khẩu của CHÍNH MÌNH — service xác thực lại bằng mật khẩu hiện tại"),
    phien: tuple[str, ss.BanGhiPhien] = Depends(lay_ban_ghi_phien),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    """Sai mật khẩu hiện tại → 400 (KHÔNG 401 — 401 là «phiên chết» với FE);
    tài khoản Google-only → 409. Không revoke phiên khác — xem docstring service."""
    _sid, ban_ghi = phien
    async with pool.acquire() as conn, conn.transaction():
        await service.doi_mat_khau(
            conn, ban_ghi.user_id, mat_khau_hien_tai=body.matKhauHienTai, mat_khau_moi=body.matKhauMoi
        )


@ROUTER.get("/members", response_model=list[MemberOut])
async def liet_ke_thanh_vien(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[MemberOut]:
    # tenant_id từ Principal (đã xác thực qua membership), KHÔNG từ query param.
    #
    # Cổng thật là `require(ACTIONS.WORKSPACE_ADMIN)` ngay trên — `require()` đã
    # cưỡng chế action từ M2b. Comment cũ ở đây nói nó "chưa chặn ai" đã lỗi thời
    # và gỡ 2026-08-15.
    async with pool.acquire() as conn:
        return await repo.liet_ke_thanh_vien(conn, p.tenant_id)


async def _gui_thu_moi(t: thanh_vien.ThuCanGui, ten_workspace: str) -> bool:
    """True = đã gửi ⇒ `invitePath` về `None`. False ⇒ giữ đường dẫn để admin copy tay.

    Chọn thư theo `t.da_co`, KHÔNG theo một cờ nào ở đây: quyết định "người này đã
    có tài khoản chưa" thuộc về `thanh_vien.moi`, nơi có `repo` trong tay.

    Phục vụ ĐÚNG hai chỗ gọi — `POST /members` và `POST /members/invites/{email}/resend`
    — cả hai đang mời vào một WORKSPACE nên cả hai cần `ten_workspace`.
    `POST /members/{user_id}/invite` (legacy, `moi_lai_thanh_vien` ngay dưới)
    KHÔNG gọi hàm này — xem docstring `thanh_vien.moi_lai` cho lý do.
    """
    url = mailer.url_tuyet_doi(quan_tri_user.duong_dan_moi(t.token)) if mailer.dang_bat() else ""
    dung = thu.thu_loi_moi_da_co if t.da_co else thu.thu_loi_moi_moi
    n = dung(email=t.email, ten_workspace=ten_workspace, url=url)
    return await mailer.gui(
        den=t.email, tieu_de=n.tieu_de, than_text=n.than_text, than_html=n.than_html, anh_nhung=n.anh_nhung
    )


@ROUTER.post("/members", response_model=MoiThanhVienRaOut, status_code=201)
async def moi_thanh_vien(
    vao: MoiThanhVienIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MoiThanhVienRaOut:
    """Mời vào workspace ĐANG MỞ — `tenant_id` từ `Principal`, không từ body.

    Thư gửi SAU commit (spec §5.3): mail không rollback được, và giữ kết nối
    Postgres suốt lúc bắt tay TLS là cách làm cạn pool.

    `ten_workspace` đọc TRONG cùng giao dịch: gửi thư nói tên một workspace vừa bị
    đổi tên là một sự thật cũ, nhưng đọc nó SAU commit là thêm một round-trip cho
    mọi lượt mời để tránh một ca không ai gặp.
    """
    async with pool.acquire() as conn, conn.transaction():
        ra, can_gui = await thanh_vien.moi(conn, actor_id=p.user_id, tenant_id=p.tenant_id, vao=vao)
        ten_ws = await repo.doc_ten_workspace(conn, p.tenant_id) or p.tenant_id

    # Vòng lặp thường, KHÔNG comprehension: mỗi lượt là một lần bắt tay SMTP.
    da_gui: set[str] = set()
    for t in can_gui:
        if await _gui_thu_moi(t, ten_ws):
            da_gui.add(t.email)

    return MoiThanhVienRaOut(
        invites=[i.model_copy(update={"invitePath": None}) if i.email in da_gui else i for i in ra.invites],
        loi=ra.loi,
    )


@ROUTER.patch("/members/{user_id}", response_model=MemberOut)
async def doi_vai_tro_thanh_vien(
    user_id: str,
    vao: DoiVaiTroThanhVienIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MemberOut:
    async with pool.acquire() as conn, conn.transaction():
        return await thanh_vien.doi_vai_tro(
            conn, actor_id=p.user_id, tenant_id=p.tenant_id, user_id=user_id, role_id=vao.roleId
        )


@ROUTER.delete("/members/{user_id}", status_code=204)
async def go_thanh_vien(
    user_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await thanh_vien.go(conn, actor_id=p.user_id, tenant_id=p.tenant_id, user_id=user_id)


@ROUTER.post("/members/{user_id}/invite", response_model=MoiLaiRaOut)
async def moi_lai_thanh_vien(
    user_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MoiLaiRaOut:
    """`invitePath` về `None` khi thư đã gửi — cùng hợp đồng với `POST /members`.

    Thư ở đây là THƯ ĐĂNG KÝ (`thu.thu_dang_ky`), không một trong hai thư mời của
    `_gui_thu_moi` — lý do nằm ở docstring `thanh_vien.moi_lai` (token nó phát ra
    là SIGNUP-shaped, không workspace-shaped). Route này tự xây thư, cùng lối
    `router.dang_ky` ở trên, thay vì gọi `_gui_thu_moi`.
    """
    async with pool.acquire() as conn, conn.transaction():
        token = await thanh_vien.moi_lai(conn, actor_id=p.user_id, tenant_id=p.tenant_id, user_id=user_id)
        u = await conn.fetchrow("SELECT email, name FROM control.users WHERE id = $1", user_id)

    url = mailer.url_tuyet_doi(quan_tri_user.duong_dan_moi(token)) if mailer.dang_bat() else ""
    n = thu.thu_dang_ky(ten=u["name"], email=u["email"], url=url)
    da_gui = await mailer.gui(
        den=u["email"], tieu_de=n.tieu_de, than_text=n.than_text, than_html=n.than_html, anh_nhung=n.anh_nhung
    )
    if da_gui:
        return MoiLaiRaOut(invitePath=None)
    return MoiLaiRaOut(invitePath=quan_tri_user.duong_dan_moi(token))


@ROUTER.post("/members/invites/{email}/resend", response_model=MoiLaiRaOut)
async def gui_lai_loi_moi(
    email: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MoiLaiRaOut:
    """Định danh là EMAIL, không phải một id.

    Hàng lời mời của một email chưa có tài khoản KHÔNG có id nào khác — `token_hash`
    là thứ tuyệt đối không được ra khỏi DB, và thêm một cột id chỉ để làm path param
    là thêm một khoá cho một bảng có hạn 7 ngày.

    KHÁC `POST /members/{user_id}/invite` ngay trên: đường kia phục vụ hàng THÀNH
    VIÊN còn `pending` (di sản) và nó đặt lại mật khẩu; đường này phục vụ hàng LỜI
    MỜI và không chạm mật khẩu của ai.
    """
    async with pool.acquire() as conn, conn.transaction():
        t = await thanh_vien.gui_lai_loi_moi(
            conn, actor_id=p.user_id, tenant_id=p.tenant_id, email=email.strip().lower()
        )
        ten_ws = await repo.doc_ten_workspace(conn, p.tenant_id) or p.tenant_id

    if await _gui_thu_moi(t, ten_ws):
        return MoiLaiRaOut(invitePath=None)
    return MoiLaiRaOut(invitePath=quan_tri_user.duong_dan_moi(t.token))


@ROUTER.delete("/members/invites/{email}", status_code=204)
async def thu_hoi_loi_moi(
    email: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await thanh_vien.thu_hoi_loi_moi(conn, actor_id=p.user_id, tenant_id=p.tenant_id, email=email.strip().lower())


# ═══════════════════════════════════════════════════════════════════════════════
#  M2b — quản trị user cấp TỔ CHỨC
#  spec: docs/superpowers/specs/2026-08-03-m2b-tao-sua-user-design.md
# ═══════════════════════════════════════════════════════════════════════════════
#
# ⚠ SÁU ĐƯỜNG DƯỚI ĐANG TẮT bằng cờ `USERS_ADMIN_ENABLED` (mặc định False) —
# `quan_tri_user._cong_users_admin()`. Cửa thật cũ (`org_role = 'owner'`) biến mất
# cùng tầng tổ chức 2026-08-15 và không có gì thay thế. Route giữ nguyên để bật
# lại khi có mô hình admin thật; xem header `quan_tri_user.py`. Cũ:
# phép khai ở đây là chỗ cắm, chưa phải chặn.
#
# `p.tenant_id` KHÔNG dùng ở đây: đây là hành động cấp tổ chức, và org_id suy từ
# `p.user_id` trong service. Đưa tenant_id vào là thu hẹp sai phạm vi — owner
# quản user của cả org, không của riêng workspace họ đang mở.
#
# MỌI đường GHI bọc `conn.transaction()` ở TẦNG NÀY, không trong service: service
# gọi nhiều hàm repo, và ai mở giao dịch thì người đó quyết định biên của nó —
# cùng lối `repo.py` đã ghi ("caller quyết định giao dịch").


@ROUTER.get("/users", response_model=list[UserListItemOut])
async def liet_ke_user(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[UserListItemOut]:
    async with pool.acquire() as conn:
        return await quan_tri_user.liet_ke(conn, p.user_id)


@ROUTER.get("/users/{user_id}", response_model=UserDetailOut)
async def doc_user(
    user_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> UserDetailOut:
    async with pool.acquire() as conn:
        return await quan_tri_user.doc_chi_tiet(conn, p.user_id, user_id)


@ROUTER.post("/users", response_model=TaoUserRaOut, status_code=201)
async def tao_user(
    vao: TaoUserIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TaoUserRaOut:
    async with pool.acquire() as conn, conn.transaction():
        return await quan_tri_user.tao(conn, p.user_id, vao)


@ROUTER.patch("/users/{user_id}", response_model=UserDetailOut)
async def sua_user(
    user_id: str,
    vao: SuaUserIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> UserDetailOut:
    async with pool.acquire() as conn, conn.transaction():
        return await quan_tri_user.sua(conn, p.user_id, user_id, vao)


@ROUTER.delete("/users/{user_id}", status_code=204)
async def xoa_user(
    user_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    """CHỈ user còn `pending` — thu hồi một lời mời gửi sai địa chỉ. Xem service."""
    async with pool.acquire() as conn, conn.transaction():
        await quan_tri_user.xoa(conn, p.user_id, user_id)


@ROUTER.post("/users/{user_id}/invite", response_model=MoiLaiRaOut)
async def moi_lai(
    user_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MoiLaiRaOut:
    async with pool.acquire() as conn, conn.transaction():
        return MoiLaiRaOut(invitePath=await quan_tri_user.moi_lai(conn, p.user_id, user_id))


# --- hai đường CÔNG KHAI của thư mời ----------------------------------------


@ROUTER.get("/invites/{token}", response_model=LoiMoiOut)
async def xem_loi_moi(
    token: str,
    _: None = require(None, ly_do="người nhận mời chưa có mật khẩu nên chưa thể có phiên"),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> LoiMoiOut:
    """Token trong ĐƯỜNG DẪN, không trong query string.

    Query string bị ghi vào access log của mọi reverse proxy theo mặc định, và
    path cũng vậy — nhưng path là thứ FE phải dùng để làm link bấm được, nên đây
    là một sự đánh đổi đã có, không phải một cái mới. Bù lại bằng hạn 7 ngày +
    dùng một lần: xem `repo.doc_loi_moi_con_hieu_luc`.
    """
    async with pool.acquire() as conn:
        return await quan_tri_user.xem_loi_moi(conn, token)


@ROUTER.post("/invites/accept", status_code=204)
async def nhan_loi_moi(
    vao: NhanLoiMoiIn,
    res: Response,
    _: None = require(None, ly_do="chính đường này tạo ra mật khẩu đầu tiên — đòi phiên là vòng tròn"),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> None:
    """204. Đặt cookie phiên CHỈ khi `quan_tri_user.nhan_loi_moi` trả về một cặp
    (user_id, tenant_id) — tức nhánh `invite_existing` vừa chạy. Hai nhánh còn lại
    (`signup`/`invite_new`) trả `None` và FE vẫn đẩy về `/login` như trước: mật
    khẩu vừa được ĐẶT trong chính request công khai này, tự cấp phiên ở đó là mở
    lại đúng lỗ hổng "ai mở được link mời thì có phiên".

    Tạo phiên SAU KHI giao dịch Postgres đã commit (`async with` transaction đóng
    trước khi khối này chạy) — không cấp phiên cho một lượt nhận mời chưa chắc
    đã ghi xong.

    Token ở THÂN request, không ở đường dẫn như GET ở trên: đây là đường ghi, và
    một POST có token trong path là một URL đầy đủ nằm trong access log cạnh
    chính hành động đổi mật khẩu.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            ket_qua = await quan_tri_user.nhan_loi_moi(conn, vao)
        if ket_qua is not None:
            user_id, tenant_id = ket_qua
            session_id = await ss.tao(r, user_id=user_id, tenant_id=tenant_id)
            _dat_cookie(res, session_id)


# ═══════════════════════════════════════════════════════════════════════════════
#  M2b — vai trò cấp TỔ CHỨC (spec §4, quyết định 2026-08-04) — migration 0104
# ═══════════════════════════════════════════════════════════════════════════════
#
# ⚠ BA ĐƯỜNG GHI `/roles` ĐANG TẮT bằng cờ `ROLES_CRUD_ENABLED` (mặc định False)
# — `quan_tri_vai_tro._cong_ghi_vai_tro()`. Vai trò đã TOÀN CỤC (0105) nên để mở
# thì Quản trị của một workspace sửa được vai trò của mọi workspace khác. BA
# ĐƯỜNG ĐỌC vẫn mở: FE cần `GET /roles` cho dropdown mời thành viên. Cũ:
# qua cổng 1, CỬA THẬT là `org_role = 'owner'` — kiểm trong
# `quan_tri_vai_tro._kiem_owner()`. Xem docstring đầu file đó.


@ROUTER.get("/actions", response_model=list[ActionOut])
async def liet_ke_action(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[ActionOut]:
    async with pool.acquire() as conn:
        rows = await quan_tri_vai_tro.liet_ke_action(conn, p.user_id)
    return [ActionOut(**dict(r)) for r in rows]


@ROUTER.get("/roles", response_model=list[VaiTroOut])
async def liet_ke_vai_tro(
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> list[VaiTroOut]:
    async with pool.acquire() as conn:
        rows = await quan_tri_vai_tro.liet_ke(conn, p.user_id)
    return [VaiTroOut(**dict(r)) for r in rows]


@ROUTER.get("/roles/{role_id}", response_model=VaiTroChiTietOut)
async def doc_vai_tro(
    role_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> VaiTroChiTietOut:
    async with pool.acquire() as conn:
        r = await quan_tri_vai_tro.doc(conn, p.user_id, role_id)
    return VaiTroChiTietOut(id=r["id"], name=r["name"], description=r["description"], actions=sorted(r["actions"]))


@ROUTER.post("/roles", response_model=VaiTroChiTietOut, status_code=201)
async def tao_vai_tro(
    than: TaoVaiTroIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> VaiTroChiTietOut:
    async with pool.acquire() as conn, conn.transaction():
        rid = await quan_tri_vai_tro.tao(conn, p.user_id, than.name, than.description, than.actions)
    return VaiTroChiTietOut(id=rid, name=than.name, description=than.description, actions=sorted(than.actions))


@ROUTER.patch("/roles/{role_id}", response_model=VaiTroChiTietOut)
async def sua_vai_tro(
    role_id: str,
    than: SuaVaiTroIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> VaiTroChiTietOut:
    async with pool.acquire() as conn, conn.transaction():
        await quan_tri_vai_tro.sua(conn, p.user_id, role_id, than.name, than.description, than.actions)
    return VaiTroChiTietOut(id=role_id, name=than.name, description=than.description, actions=sorted(than.actions))


@ROUTER.delete("/roles/{role_id}", status_code=204)
async def xoa_vai_tro(
    role_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await quan_tri_vai_tro.xoa(conn, p.user_id, role_id)


# --- ba đường CÔNG KHAI của cửa Google (spec 2026-08-18) ---------------------
#
# Cả ba là GET. `/auth/google/callback` là GET vì Google điều hướng trình duyệt
# tới nó — ta không chọn được method.

_TIEN_TO_STATE = "oauth:state:"
_HAN_STATE_GIAY = 300

_TEN_COOKIE_STATE = "odyssey_oauth_state"
"""Buộc `state` vào ĐÚNG trình duyệt đã bắt đầu luồng — xem `_dat_cookie_state`.

Hàng `oauth:state:<state>` một mình trong Redis là một TOKEN TOÀN CỤC: bất kỳ
trình duyệt nào cầm được giá trị `state` đều đổi được nó, kể cả một trình duyệt
không phải trình duyệt đã gọi `/start`. Đó là login-CSRF: kẻ tấn công tự lấy
`state` của CHÍNH HỌ, tự đăng nhập Google bằng tài khoản của họ, rồi đưa nạn
nhân URL callback kèm `code`+`state` đó — nạn nhân nhận cookie phiên của TÀI
KHOẢN KẺ TẤN CÔNG. `GETDEL` ở callback chỉ chống REPLAY (dùng lại một `state`
đã tiêu) — nó không nhìn được trình duyệt nào đang gọi, nên không chống được ca
trên. Cookie so khớp với `state` trong query mới là phép buộc-trình-duyệt.
"""


def _dat_cookie_state(res: Response, state: str) -> None:
    """Đặt cookie đối chiếu — cặp với `_xoa_cookie_state`, mọi thuộc tính phải
    khớp lúc xoá (theo đúng lý lẽ `_dat_cookie`/`_xoa_cookie` ở trên).

    `SameSite=Lax`, KHÔNG `Strict`: callback là một điều hướng GET TOP-LEVEL từ
    Google, và cookie `Lax` vẫn được gửi trong ca đó — `Strict` chặn mất chính
    cookie này và giết luôn cả luồng.

    `max_age` bằng đúng `_HAN_STATE_GIAY`: cookie không cần sống lâu hơn hàng
    Redis mà nó đối chiếu.
    """
    res.set_cookie(
        _TEN_COOKIE_STATE,
        state,
        max_age=_HAN_STATE_GIAY,
        httponly=True,
        secure=_secure(),
        samesite="lax",
        path="/",
    )


def _xoa_cookie_state(res: Response) -> None:
    """Xoá cookie state — gọi ở MỌI đường ra của callback, thành công lẫn thất
    bại. Một `state` đã tiêu (dùng rồi, hoặc chưa từng khớp) còn nằm trong
    trình duyệt là rác biết nói: nó sẽ khớp nhầm — hoặc gây khó hiểu — ở lượt
    kế tiếp. `path`/`secure`/`httponly`/`samesite` phải khớp lúc đặt, cùng lý lẽ
    `_xoa_cookie`.
    """
    res.delete_cookie(_TEN_COOKIE_STATE, path="/", httponly=True, secure=_secure(), samesite="lax")


def _dem_cookie_state(request: Request) -> int:
    """Đếm số lần `odyssey_oauth_state` xuất hiện trong header Cookie THÔ.

    `request.cookies` đã gộp trùng lặp thành một giá trị nên nó không thấy được
    đòn này: một subdomain anh em bị chiếm đặt cookie cùng tên với `Domain=.…`,
    trình duyệt gửi CẢ HAI, và parser lấy một cái tuỳ ý — kẻ tấn công cắm được
    `state` của mình vào lượt của nạn nhân. Hai cookie cùng tên không bao giờ là
    một luồng hợp lệ, nên đếm rồi từ chối là đủ và không cần đoán cái nào thật.

    `__Host-` sẽ đóng đòn này gọn hơn nhưng nó ĐÒI `Secure`, và `cookie_secure`
    cố ý tắt được cho một kịch bản dev (xem docstring của nó). Đổi tên cookie
    theo cờ thì set và delete có ngày lệch nhau — chính lỗi `_xoa_cookie` cảnh báo.

    Tách theo `=` RỒI `strip()` phần TÊN, KHÔNG `startswith(f"{TEN}=")`: Starlette
    (`cookie_parser`) tự `key.strip()` trước khi so tên, nên header
    `odyssey_oauth_state =...` (khoảng trắng TRƯỚC dấu `=`) vẫn được NÓ tính là
    cookie của ta — còn `startswith` thì không (chuỗi sau `.strip()` bắt đầu bằng
    `"odyssey_oauth_state "`, không phải `"odyssey_oauth_state="`). Phép đếm phải
    khớp CHÍNH XÁC cách Starlette tách tên; lệch một ký tự khoảng trắng là có một
    dạng header mà Starlette thấy còn ta thì không — đúng kẽ hở phép đếm này sinh
    ra để bịt. (Không khai thác được qua trình duyệt thật — RFC 6265 §5.2 buộc
    trình duyệt cắt khoảng trắng quanh tên cookie — nhưng một phép đếm phòng thủ
    phải đếm đúng thứ parser đếm, không phải thứ trông giống.)

    ⚠ GỘP MỌI dòng header `Cookie`, KHÔNG chỉ đọc dòng ĐẦU: `request.cookies`
    (Starlette) dùng `headers.getlist("cookie")` rồi gộp — nếu phép đếm này chỉ
    `headers.get("cookie")` (một dòng), một request mang HAI dòng `Cookie` (dòng
    đầu giá trị thật, dòng sau giá trị kẻ tấn công) sẽ đếm ra 1 (qua cửa) trong
    khi `request.cookies` đã gộp cả hai và trả giá trị của kẻ tấn công theo luật
    last-wins — đúng lại lớp lỗi "đếm không khớp thứ parser đếm" mà hàm này vừa
    được sửa vì nó, chỉ đổi từ khoảng-trắng-trong-tên sang nhiều-dòng-header.
    HTTP/1.1 (uvicorn hôm nay) và RFC 6265 buộc trình duyệt gộp thành một dòng,
    nên không tới được qua trình duyệt — NHƯNG RFC 9113 §8.2.3 (HTTP/2) cho phép
    tách trường cookie thành nhiều dòng, đúng lý do Starlette phải `getlist` thay
    vì đọc một header. Đừng "tối ưu" ngược về `.get()` — lỗ này mở lại im lặng
    ngay khi deployment đổi ASGI server hỗ trợ HTTP/2, hoặc đứng sau một proxy
    chuyển tiếp dòng đã tách.
    """
    raw = "; ".join(request.headers.getlist("cookie"))
    return sum(1 for phan in raw.split(";") if "=" in phan and phan.split("=", 1)[0].strip() == _TEN_COOKIE_STATE)


def _cau_hinh_google() -> "Settings":
    """Đọc cấu hình MỖI lần, như `_secure()`. Trả `Settings` hoặc ném 403.

    `tinh_nang_dang_tat` trả 403 chứ không 404, và lý lẽ của nó (`api/loi.py`)
    áp đúng ở đây: cửa CÓ tồn tại và sẽ bật lại khi cấu hình đủ. 404 làm FE kết
    luận sai rằng đường đã bị gỡ và đi tìm đường thay thế.

    Gọi `kiem_tra_google_mau_thuan_san_xuat()` ở ĐÂY — tức mọi lượt vào HAI
    đường đi qua hàm này, `/auth/google/start` và `/auth/google/callback` —
    chứ không đợi ai POST `/auth/register`: đường Google không đi qua đó, và
    một production bật `GOOGLE_CLIENT_ID` mà quên `PUBLIC_BASE_URL`, không ai
    đăng ký sau khi deploy, sẽ để người dùng Google ĐẦU TIÊN gặp
    `redirect_uri_mismatch` mù mờ từ Google — đúng thứ phép kiểm này viết ra để
    chặn TRƯỚC.

    `/auth/providers` CỐ Ý KHÔNG đi qua hàm này: nó gọi thẳng `google_bat()` —
    chỉ báo cáo cờ bật/tắt cho FE vẽ nút, không phải một cổng vào cửa Google —
    nên không cần (và không nên) chạy phép kiểm mâu thuẫn sản xuất này.
    """
    from portal.core.config import get_settings

    c = get_settings()
    if not c.google_bat():
        raise loi.tinh_nang_dang_tat("đăng nhập bằng Google")
    c.kiem_tra_google_mau_thuan_san_xuat()
    return c


def _ve_login(ma: str) -> RedirectResponse:
    """Callback là điều hướng trình duyệt nên KHÔNG trả JSON được — envelope
    `{error:{code,message}}` không có chỗ để đi. FE đọc `?loi=` và hiện tại chỗ.

    302 chứ không 307: đây là kết thúc một luồng GET, không phải một lệnh phải
    giữ nguyên method.
    """
    return RedirectResponse(f"/login?loi={ma}", status_code=302)


@ROUTER.get("/auth/providers")
async def nha_cung_cap(
    _: None = require(None, ly_do="màn đăng nhập chưa có phiên nào để đòi"),
) -> dict[str, bool]:
    """CHỈ trả tên nhà cung cấp. Không `client_id`, không URL, không gì khác —
    mỗi trường thêm vào là một thứ nói cho người chưa đăng nhập biết về hệ thống.

    Tồn tại vì FE không có đường nào khác biết tính năng bật hay tắt: `/config/*`
    là agent config và đòi phiên, `/me` cũng vậy. KHÔNG dùng biến build-time của
    Vite thay cho đường này — cờ thật nằm ở `.env` của backend, và một bản FE
    build sẵn đem sang môi trường khác sẽ nói sai.

    ⚠ Đây KHÔNG phải phép chặn. Phép chặn nằm ở `/auth/google/start`.
    """
    from portal.core.config import get_settings

    return {"google": get_settings().google_bat()}


@ROUTER.get("/auth/google/start")
async def bat_dau_google(
    _: None = require(None, ly_do="chính đường này bắt đầu việc tạo phiên — đòi phiên là vòng tròn"),
    r: Redis = Depends(lay_redis),
) -> RedirectResponse:
    """Sinh `state` + `code_verifier`, cất Redis 5 phút, đẩy sang Google.

    Redis chứ không Postgres: dữ liệu này sống 5 phút và chết hẳn. Một bảng cho
    nó là một bảng phải có job dọn rác.
    """
    c = _cau_hinh_google()
    state = secrets.token_urlsafe(32)
    verifier = oauth_google.sinh_verifier()
    await r.set(f"{_TIEN_TO_STATE}{state}", verifier, ex=_HAN_STATE_GIAY)
    ve = RedirectResponse(
        oauth_google.duong_uy_quyen(
            client_id=c.google_client_id,
            redirect_uri=c.google_redirect_uri(),
            state=state,
            challenge=oauth_google.thach_thuc(verifier),
        ),
        status_code=307,
    )
    # Buộc `state` vào trình duyệt này — xem docstring `_TEN_COOKIE_STATE`.
    _dat_cookie_state(ve, state)
    return ve


@ROUTER.get("/auth/google/callback")
async def tro_ve_tu_google(
    request: Request,
    code: str = "",
    state: str = "",
    _: None = require(None, ly_do="chính đường này tạo ra phiên đầu tiên — đòi phiên là vòng tròn"),
    pool: asyncpg.Pool = Depends(lay_pool),
    r: Redis = Depends(lay_redis),
) -> RedirectResponse:
    """Điểm hạ cánh của luồng. Mọi lỗi thành `302 /login?loi=<MA>`.

    `code`/`state` khai mặc định `""` chứ không bắt buộc: Google trả về đây cả
    khi người dùng bấm «Huỷ» (không có `code`), và một 422 của FastAPI ở đúng
    lúc đó là một trang lỗi JSON đập vào mặt người vừa đổi ý.

    Kể cả tính-năng-tắt (`_cau_hinh_google()` ném `FEATURE_DISABLED`) cũng đổ về
    `302` ở ĐÂY — khác `/start`. `/start` là một lời gọi có chủ đích tới một
    đường không tồn tại, 403 JSON là câu trả lời đúng. Callback thì KHÔNG: nó là
    điều hướng top-level từ Google giữa một luồng người dùng đã bắt đầu (cấu
    hình có thể bị tắt SAU khi họ đã qua `/start`), và một 403 JSON đập vào mặt
    trình duyệt ở đúng chỗ này còn để cookie state sống sót suốt 300 giây.
    """

    def _thoat(ve: RedirectResponse) -> RedirectResponse:
        """MỌI đường ra đi qua đây — thành công lẫn thất bại — để cookie state
        luôn được xoá. Xem docstring `_xoa_cookie_state`."""
        _xoa_cookie_state(ve)
        return ve

    try:
        c = _cau_hinh_google()
    except loi.LoiPortal:
        # `_cau_hinh_google()` ném khi tính năng tắt (`FEATURE_DISABLED`, 403) —
        # đúng cho `/start` nhưng KHÔNG đúng ở đây, xem docstring trên. Tái dùng
        # `DANG_KY_DANG_TAT` (mã đã có, `dang_nhap_google` dùng cho nhánh 3 khi
        # `signup_enabled=False`) thay vì thêm một mã mới — FE đã biết xử lý nó,
        # và "đường vào này đang tắt" là cùng một câu cho người dùng dù lý do kỹ
        # thuật khác nhau.
        return _thoat(_ve_login("DANG_KY_DANG_TAT"))

    # Buộc `state` vào ĐÚNG trình duyệt đã bắt đầu luồng, TRƯỚC khi chạm Redis.
    # Hàng Redis một mình là một token TOÀN CỤC — kẻ tấn công đổi `state` của
    # chính họ ở trình duyệt nạn nhân, và nạn nhân nhận cookie phiên của TÀI
    # KHOẢN KẺ TẤN CÔNG (login-CSRF). `GETDEL` ngay dưới chống REPLAY (dùng lại
    # một `state` đã tiêu) — đó là một lỗ KHÁC, phép này không thay được cho nó
    # và ngược lại. Kiểm cả bốn: query rỗng, cookie thiếu, hai bên lệch, hoặc
    # NHIỀU HƠN MỘT cookie cùng tên (một subdomain anh em bị chiếm cắm thêm một
    # `odyssey_oauth_state` khác — xem `_dem_cookie_state`). `request.cookies`
    # không thấy được ca cuối nên phải đếm trên header thô TRƯỚC.
    if _dem_cookie_state(request) > 1:
        return _thoat(_ve_login("STATE_HET_HAN"))
    state_cookie = request.cookies.get(_TEN_COOKIE_STATE)
    if not state or not state_cookie or state_cookie != state:
        return _thoat(_ve_login("STATE_HET_HAN"))

    # GETDEL — dùng MỘT LẦN, atomic. `GET` rồi `DEL` là hai lệnh rời nhau, và
    # khoảng giữa chúng là một cửa sổ replay: ai đó gọi lại đúng callback này
    # với cùng `state` (kể cả từ ĐÚNG trình duyệt, cookie vẫn khớp) trước khi
    # hàng Redis bị xoá sẽ tiêu state đó hai lần. Đây là phép chống REPLAY,
    # KHÔNG phải phép chống CSRF — phép đó đã chạy ở trên.
    verifier = await r.getdel(f"{_TIEN_TO_STATE}{state}")
    if verifier is None:
        return _thoat(_ve_login("STATE_HET_HAN"))
    if not code:
        return _thoat(_ve_login("GOOGLE_TU_CHOI"))

    if isinstance(verifier, bytes):
        verifier = verifier.decode()

    try:
        claims = await oauth_google.doi_code_lay_claims(
            code=code,
            verifier=verifier,
            client_id=c.google_client_id,
            client_secret=c.google_client_secret,
            redirect_uri=c.google_redirect_uri(),
        )
        async with pool.acquire() as conn, conn.transaction():
            session_id, tenant_id = await dang_nhap_google.dang_nhap(
                conn, r, claims=claims, cho_dang_ky_moi=c.signup_enabled
            )
    except oauth_google.LoiGoogle as e:
        return _thoat(_ve_login(e.ma))

    # `_dat_cookie` CỦA CHÍNH FILE NÀY, không một bản thứ hai: `_secure()` lệch
    # nhau một cờ là đăng nhập chạy còn đăng xuất hỏng — xem `_xoa_cookie`.
    #
    # ⚠ HAI CHUỖI DƯỚI PHẢI KHỚP ĐÚNG TÊN ROUTE CỦA FE
    # (`src/routes/_app/dashboard.tsx` và `src/routes/tao-workspace-dau-tien.tsx`).
    # Không compiler nào canh ranh giới này: đường mật khẩu điều hướng bằng
    # `navigate({ to })` của TanStack Router nên gõ sai là lỗi `tsc`, còn ở đây
    # chỉ là một chuỗi Python — gõ sai thì FE rơi vào `notFoundComponent`, tức
    # người dùng mới đăng nhập Google lần đầu nhận màn 404 thay vì màn tạo
    # workspace. Đã từng sai đúng như vậy: `/tao-workspace` (thiếu `-dau-tien`).
    ve = RedirectResponse("/dashboard" if tenant_id else "/tao-workspace-dau-tien", status_code=302)
    _dat_cookie(ve, session_id)
    return _thoat(ve)
