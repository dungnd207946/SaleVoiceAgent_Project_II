"""require(action) — CHỖ CẮM QUYỀN. Viết một lần, đổi ruột sau.

═══════════════════════════════════════════════════════════════════════════════
 ĐỌC TRƯỚC KHI SỬA
═══════════════════════════════════════════════════════════════════════════════
Spec tổng §3.5 buộc: "M2a ship require(action) làm FastAPI dependency, và MỌI
endpoint khai action của nó TỪ NGÀY ĐẦU." Lý do: nếu M2a ship endpoint không có
chỗ khai quyền thì M2b thành "rà toàn bộ endpoint và thêm kiểm tra" — kiểu
retrofit đau nhất, và bỏ sót một endpoint là một lỗ hổng không ai thấy.

MA TRẬN VAI TRÒ ĐÃ BẬT. Thân hàm tra `doc_quyen()` mỗi request và so `action` với
tập action hiệu lực. Ba comment cũ trong repo (file này, `modules/auth/router.py`,
`modules/auth/quan_tri_user.py`) từng nói "M2a chỉ kiểm thành viên, M2b sẽ bật ma
trận sau" — đã lỗi thời từ lâu và gỡ 2026-08-15. Chúng nguy hiểm theo kiểu khó
thấy nhất: người đọc kết luận hệ thống đang hở và đi vá một lỗ không tồn tại.

ĐÂY LÀ CỔNG DUY NHẤT. Trước 2026-08-15 các đường quản trị còn một "cửa thật" thứ
hai là `users.org_role = 'owner'`; tầng tổ chức đã bị bỏ nên không còn cửa nào
khác.

VÌ SAO ĐỌC MEMBERSHIP MỖI REQUEST (PQ_01 §BR-Q04 · YC03): CMS cũ nhét vai trò
vào phiếu đăng nhập hạn 15 phút, nên "sa thải một người xong, 15 phút nữa họ vẫn
sửa được dữ liệu". Ràng buộc cách ly đã buộc mọi request nằm trong một giao dịch,
nên đọc thêm một hàng đi cùng chuyến.
"""

from collections.abc import Callable
from typing import Any

import asyncpg
from fastapi import Depends, Request
from redis.asyncio import Redis

from portal.api import loi
from portal.core.auth import repo
from portal.core.auth import session as ss
from portal.core.auth.actions import ALL_ACTIONS
from portal.core.auth.principal import Principal

# `repo` ở đây là `core/auth/repo.py` — ĐÚNG một truy vấn của seam này
# (doc_quyen). Core KHÔNG import modules nào: SQL nghiệp vụ của users/workspace
# ở `modules/auth/repo.py`, và require() không cần tới nó.


class KhaiQuyen:
    """Marker cổng 1 đọc. Có mặt = "đã khai"; vắng = "quên khai"."""

    __slots__ = ("action", "ly_do")

    def __init__(self, action: str | None, ly_do: str | None) -> None:
        self.action = action
        self.ly_do = ly_do


def lay_pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


def lay_redis(request: Request) -> Redis:
    return request.app.state.redis


def require(action: str | None, *, ly_do: str | None = None) -> Any:
    """Dùng làm default của tham số endpoint:

        async def liet_ke(p: Principal = require(ACTIONS.WORKSPACE_ADMIN)): ...

    Route công khai:

        async def dang_nhap(_: None = require(None, ly_do="chưa có phiên")): ...
    """
    if action is not None and action not in ALL_ACTIONS:
        raise ValueError(
            f"action {action!r} không thuộc 13 nhóm của PQ_01 §3.1. "
            f"Xem portal/core/auth/actions.py. Có phải gõ sai tên không?"
        )
    if action is None and not ly_do:
        raise ValueError(
            "route công khai phải khai `ly_do` — `require(None)` trần không phân biệt "
            "được với quên khai, và cổng 1 sẽ không đọc được ý định"
        )

    dep: Callable[..., Any]

    if action is None:

        async def _cong_khai() -> None:
            return None

        dep = _cong_khai
    else:

        async def _kiem(
            request: Request,
            pool: asyncpg.Pool = Depends(lay_pool),
            r: Redis = Depends(lay_redis),
        ) -> Principal:
            sid = request.cookies.get(ss.TEN_COOKIE, "")
            ban_ghi = await ss.doc(r, sid)
            if ban_ghi is None:
                raise loi.khong_co_phien()

            async with pool.acquire() as conn, conn.transaction():
                if ban_ghi.tenant_id is None:
                    # Phiên chưa có workspace nào (vừa tự đăng ký). Không có gì để
                    # tra ma trận, nhưng VẪN phải kiểm lifecycle: một tài khoản bị
                    # đình chỉ mà chưa có workspace vẫn phải bị đẩy về /login, chứ
                    # không ngồi nhìn một màn "không đủ quyền" mà đăng xuất rồi vào
                    # lại cũng không sửa được.
                    lifecycle = await conn.fetchval(
                        "SELECT lifecycle FROM control.users WHERE id = $1", ban_ghi.user_id
                    )
                    if lifecycle != "active":
                        await ss.xoa(r, sid)
                        raise loi.khong_co_phien()
                    raise loi.thieu_quyen(action, None)

                q = await repo.doc_quyen(conn, ban_ghi.user_id, ban_ghi.tenant_id)

                # Đình chỉ là chuyện DANH TÍNH, không phải của một workspace: xoá
                # luôn phiên rồi 401. 403 sẽ làm FE hiện màn "không có quyền" trong
                # khi đúng ra phải đẩy về /login. Xem spec §4.4.
                if q is None or q.lifecycle != "active":
                    await ss.xoa(r, sid)
                    raise loi.khong_co_phien()

                # WORKSPACE ĐÃ XOÁ — kiểm SAU lifecycle của user, TRƯỚC ma trận
                # quyền. Thứ tự đó có lý do: một tài khoản bị đình chỉ phải bị đẩy
                # về /login dù workspace của họ còn sống, còn một workspace đã đóng
                # thì mọi vai trò đều vô nghĩa — kiểm ma trận trước chỉ đổi 403 này
                # thành một 403 khác nói sai lý do.
                #
                # KHÔNG xoá phiên như nhánh trên: người dùng vẫn đăng nhập hợp lệ và
                # thường vẫn còn workspace khác. Đá họ về /login là bắt gõ lại mật
                # khẩu vì một workspace mà có khi họ không phải người xoá. `GET /me`
                # (khai `require(None, ...)` nên KHÔNG đi qua nhánh này) tự dời con
                # trỏ phiên sang workspace còn lại — xem `modules/auth/router.phien_hien_tai`.
                #
                # `tenant_lifecycle is None` = workspace bị xoá CỨNG. Gộp vào đây,
                # fail-closed: mất thông tin thì từ chối.
                if q.tenant_lifecycle is None or q.tenant_lifecycle == "closed":
                    raise loi.workspace_da_dong()

            # `actions` là tập hiệu lực đọc từ CSDL mỗi request — không cache vào
            # phiên (PQ_01 §BR-Q04).
            #
            # KHÔNG có nhánh `if not q.actions: raise khong_du_quyen()` riêng ở
            # đây nữa (review đã gỡ nó) — một vai trò 0 quyền là trạng thái HỢP
            # LỆ (§2.1 "đã tạo, chưa cấu hình"; §3.3 sửa vai trò không được khoá
            # cửa AI, kể cả người giữ vai trò đó), nên nó không đáng một mã lỗi
            # riêng. `action not in q.actions` đã ĐÚNG fail-closed cho nó: tập
            # rỗng thì mọi action đều fail, và người dùng nhận `thieu_quyen()` —
            # câu nói LÝ DO (§3.4) — thay vì `khong_du_quyen()` chung. Việc "có
            # phải thành viên không" đã tách khỏi đây, giờ là việc của
            # `HangQuyen.co_membership` (dùng ở `modules/auth/router.doi_workspace`).
            if action not in q.actions:
                raise loi.thieu_quyen(action, q.role_name)

            return Principal(
                user_id=ban_ghi.user_id,
                tenant_id=ban_ghi.tenant_id,
                role=q.role_name or "",
                actions=q.actions,
            )

        dep = _kiem

    dep.khai_quyen = KhaiQuyen(action, ly_do)  # type: ignore[attr-defined]
    return Depends(dep)


async def lay_ban_ghi_phien(
    request: Request,
    r: Redis = Depends(lay_redis),
) -> tuple[str, ss.BanGhiPhien]:
    """Trả (session_id, bản ghi). Raise 401 nếu không có phiên.

    Khác `require(action)`: KHÔNG kiểm membership. Dùng cho đúng hai đường của
    chính module auth — `/me` (chưa biết workspace nào để kiểm) và `/me/workspace`
    (đang đổi workspace, nên workspace cũ không phải điều kiện).

    ⚠ Đây KHÔNG phải cửa sau của require(). Nó không trả `Principal`, nên endpoint
    dùng nó không có `tenant_id` đã xác thực để đưa vào `tenant_conn()`. Module
    khác cần đọc `tenant_data` thì dùng `require(action)` — không có ngoại lệ.
    """
    sid = request.cookies.get(ss.TEN_COOKIE, "")
    ban_ghi = await ss.doc(r, sid)
    if ban_ghi is None:
        raise loi.khong_co_phien()
    return sid, ban_ghi
