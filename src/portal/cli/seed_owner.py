"""Bootstrap owner đầu tiên của một môi trường. Vai `seed-owner` của entrypoint.

VÌ SAO CẦN FILE NÀY. Luồng nhập người dùng là MỜI, không tự đăng ký: `POST /users`
tạo hàng `lifecycle='pending'` rồi người được mời tự đặt mật khẩu ở
`POST /invites/accept`. Nhưng `POST /users` đòi một owner ĐANG ĐĂNG NHẬP
(`_lay_owner()` trong modules/auth/quan_tri_user.py), và `dang_nhap()` còn raise
`khong_co_workspace()` nếu người đó chưa thấy workspace nào. Nên một môi trường
vừa `alembic upgrade head` xong là một môi trường KHÔNG AI VÀO ĐƯỢC: schema đủ,
`/healthz` xanh, và không có đường nào tạo ra người đầu tiên. Đây là đường đó.

VÌ SAO KHÔNG PHẢI `dev_seed.py`. `dev_seed` ghi mật khẩu nằm trong repo vào
`control.users` và `kiem_localhost()` chặn nó ở máy dev — đúng như vậy. File này
ngược lại: nó KHÔNG BAO GIỜ ghi mật khẩu. Nó phát một token mời 256 bit và mật
khẩu do chính owner đặt qua đường công khai `/invite/<token>`. Không ai khác —
kể cả người chạy lệnh này — biết mật khẩu đó.

VÌ SAO CHẶN KHI ĐÃ CÓ USER `active`. Có một người đăng nhập được nghĩa là đường
UI đã mở, và `POST /auth/register` là công cụ đúng cho mọi người tiếp theo. Để file này
chạy được trên hệ đang sống là để lại một đường tạo owner không qua phép kiểm
phép kiểm quyền nào — nó chỉ cần quyền `DATABASE_URL`. Vòng chặn dưới đây là thứ
giữ nó ở đúng nghĩa "bootstrap".

VÌ SAO Ở `portal/cli/` CHỨ KHÔNG `scripts/`: Dockerfile không COPY `scripts/` vào
image. Xem docstring `portal/cli/__init__.py`.

Chạy: docker compose -f docker-compose.dev.yml run --rm seed-owner
"""

import asyncio
import os
import secrets
import sys
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

from portal.core import nhat_ky
from portal.core.config import get_settings
from portal.modules.auth import repo as auth_repo

# `_SO_BYTE_TOKEN` là private nhưng nhập có chủ đích: nó là nguồn duy nhất của
# "token mời dài bao nhiêu". Gõ lại 32 ở đây là để hai đường phát token lệch nhau
# khi ai đó siết một chỗ.
from portal.modules.auth.quan_tri_user import (
    _SO_BYTE_TOKEN,
    HAN_MOI,
    bam_token,
    duong_dan_moi,
    sinh_user_id,
)
from portal.modules.auth.service import chuan_hoa_email
from portal.modules.workspace import service as ws_service
from portal.modules.workspace.contracts import TaoWorkspaceIn

TEN_WORKSPACE_MAC_DINH = "Workspace đầu tiên"


class LoiBootstrap(Exception):
    """Sai cấu hình hoặc sai thời điểm. `main()` biến nó thành exit 1 + một dòng lỗi."""


@dataclass(frozen=True)
class CauHinh:
    email: str
    ten_nguoi: str
    ten_workspace: str
    goc_url: str
    """`https://portal.example.vn` hoặc rỗng. Chỉ để in link đầy đủ cho tiện."""


def doc_cau_hinh(env: dict[str, str]) -> CauHinh:
    """Đọc + validate env. HÀM THUẦN — test được không cần Postgres.

    `SEED_OWNER_EMAIL` bắt buộc, không có mặc định: nó là hộp thư nhận link mời,
    và đoán hộ một địa chỉ là gửi quyền quản trị đầu tiên tới chỗ không ai đọc.

    `SEED_ORG_ID` / `SEED_ORG_NAME` ĐÃ BỎ 2026-08-15 cùng tầng tổ chức. Nếu chúng
    còn trong file env của bạn thì chúng bị bỏ qua — vô hại.
    """
    email = chuan_hoa_email(env.get("SEED_OWNER_EMAIL", ""))
    if "@" not in email:
        raise LoiBootstrap(
            "thiếu hoặc sai SEED_OWNER_EMAIL — email của người dùng đầu tiên.\n"
            "  Đây là địa chỉ nhận link mời, nên nó phải là hộp thư người đó mở được."
        )

    return CauHinh(
        email=email,
        # Mặc định lấy phần trước @: owner sửa tên của mình trong UI được, và bắt
        # devops nghĩ ra một cái tên hiển thị là bắt họ đoán.
        ten_nguoi=env.get("SEED_OWNER_NAME", "").strip() or email.split("@")[0],
        ten_workspace=env.get("SEED_WORKSPACE_NAME", "").strip() or TEN_WORKSPACE_MAC_DINH,
        goc_url=env.get("SEED_PORTAL_URL", "").strip().rstrip("/"),
    )


async def chay(conn: asyncpg.Connection, c: CauHinh) -> str | None:
    """Tạo (hoặc mời lại) owner. Trả token mời, hoặc None nếu không cần làm gì.

    NGƯỜI GỌI MỞ GIAO DỊCH — khuôn `repo.py` của cả repo. Ba việc dưới đây phải
    cùng sống hoặc cùng chết: một tài khoản không có workspace, hay một workspace
    không ai vào được, đều là trạng thái mà chính script này tồn tại để tránh.

    BƯỚC "TỔ CHỨC" ĐÃ BỎ 2026-08-15 — `control.organizations` không còn.
    """
    # ── Vòng chặn: có ai đăng nhập được chưa? ────────────────────────────────
    # Đếm `active`, KHÔNG đếm tổng: một lần chạy trước hỏng nửa đường (mạng đứt
    # sau commit, trước khi token kịp in ra) để lại đúng một owner `pending` —
    # và mời lại người đó là việc đúng, không phải một lỗi cần người can thiệp.
    active = await conn.fetchval("SELECT count(*) FROM control.users WHERE lifecycle = 'active'")
    if active:
        raise LoiBootstrap(
            f"TỪ CHỐI: DB đã có {active} tài khoản dùng được.\n"
            "  Vai này chỉ dành cho môi trường chưa ai vào được. Người tiếp theo tự\n"
            "  đăng ký qua `POST /auth/register`, hoặc được Quản trị của một workspace\n"
            "  mời qua `POST /members`.\n"
            "  Mất mật khẩu owner duy nhất? Đó là việc khác: mời lại từ UI, hoặc\n"
            "  `UPDATE control.users SET lifecycle='pending', password_hash=NULL` cho\n"
            "  đúng hàng đó rồi chạy lại lệnh này."
        )

    hien_co = await conn.fetchrow("SELECT id FROM control.users WHERE email = $1", c.email)

    # ── ① Tài khoản đầu tiên, `pending` + `password_hash = NULL`.
    # CHECK `users_co_duong_dang_nhap_check` (0103, đổi tên + nới MỘT CHIỀU ở
    # 0108 để user Google-only khỏi cần mật khẩu — chiều `active ⇒ có mật khẩu`
    # đã bỏ, nhưng chiều `pending ⇒ password_hash IS NULL` vẫn còn) vẫn buộc
    # `pending` đi cùng NULL, nên không có cách nào tạo ra một owner "pending
    # mà đã có mật khẩu".
    if hien_co is None:
        user_id = await sinh_user_id(conn, c.email)
        await conn.execute(
            """INSERT INTO control.users (id, email, password_hash, name, lifecycle)
               VALUES ($1, $2, NULL, $3, 'pending')""",
            user_id,
            c.email,
            c.ten_nguoi,
        )
        await nhat_ky.ghi_he_thong(conn, "owner.bootstrap", user_id, {"email": c.email})
    else:
        # Email đã có nhưng chưa `active` (vòng chặn ở trên đã lo phần còn lại).
        user_id = hien_co["id"]

    # ── ② Workspace. Dùng lại `ws_service.tao()` chứ không INSERT tay: nó ghi cả
    # `tenant_verticals` VÀ hàng `memberships` vai trò "Quản trị" cho người tạo —
    # thiếu hàng đó thì `doc_quyen()` trả 0 action và họ không vào được chính
    # workspace vừa dựng (nhánh owner đã bỏ 2026-08-15).
    #
    # `dang_nhap()` KHÔNG còn raise khi 0 workspace (phiên không workspace là hợp
    # lệ từ 2026-08-15), nên bước này không còn là điều kiện để đăng nhập được —
    # nó chỉ để người vừa bootstrap có sẵn một chỗ làm việc.
    #
    # Chỉ tạo khi DB chưa có workspace nào: chạy lại lệnh này để lấy token mới
    # không được sinh thêm "Workspace đầu tiên (2)".
    da_co_ws = await conn.fetchval("SELECT count(*) FROM control.tenants")
    if not da_co_ws:
        ws = await ws_service.tao(conn, user_id, TaoWorkspaceIn(name=c.ten_workspace))
        tenant_id = ws.id
    else:
        # Nhánh dở dang: chạy lại lệnh này sau một lần trước đã tạo workspace
        # (crash trước khi in được token) — không có `ws.id` vì không tạo mới.
        # Bất biến của NHÁNH NÀY (không phải của user_id) là "tổ chức đã có
        # workspace", nên câu hỏi đúng là tra thẳng `control.tenants`, KHÔNG
        # phải tra `memberships` của riêng `user_id` — hẹp hơn câu cần hỏi, và
        # nếu chạy lại với một `SEED_OWNER_EMAIL` khác (user mới, chưa có
        # membership nào) thì câu hỏi hẹp đó âm thầm trả `NULL`.
        #
        # KHÔNG để `NULL` đi tiếp: dù lời mời ở ④ nay LUÔN là token đăng ký
        # (`ghi_loi_moi_dang_ky`, không mang `tenant_id`), workspace vẫn phải có
        # thật để nhánh này đúng bất biến của nó — một owner không có workspace
        # nào để vào là trạng thái script này tồn tại để tránh.
        # Không tìm được tenant nào ở đây là một trạng thái không có câu trả
        # lời đúng (đếm `tenants` > 0 nhưng SELECT lại rỗng — đua với xoá tenant
        # giữa hai câu lệnh), nên dừng lại và nói rõ, cùng giọng với các
        # `LoiBootstrap` khác trong file này.
        tenant_id = await conn.fetchval("SELECT id FROM control.tenants ORDER BY created_at LIMIT 1")
        if tenant_id is None:
            raise LoiBootstrap(
                "TỪ CHỐI: control.tenants báo có workspace nhưng không tra được hàng nào.\n"
                "  Có thể một tenant vừa bị xoá giữa lúc lệnh này chạy. Chạy lại lệnh — nếu\n"
                "  vẫn gặp lỗi này, kiểm tra trực tiếp `SELECT * FROM control.tenants` trước khi thử tiếp."
            )

    # ── ④ Lời mời — CHỈ để đặt mật khẩu, không phải để cấp quyền vào workspace:
    # ② đã ghi membership 'Quản trị' cho chính user_id này qua `ws_service.tao()`
    # (2026-08-15) rồi, nên token ở đây không "mở cửa" gì thêm cả. `email` mới —
    # trước 0952 token này mang `tenant_id` thật, nhưng vị từ mới của
    # `doc_loi_moi_con_hieu_luc` đòi `invite_existing` phải có user `active`, mà
    # owner vừa tạo còn `pending` (chưa có mật khẩu) — mang `tenant_id` vào đây
    # sẽ sinh một token CHẾT NGAY LÚC SINH. `ghi_loi_moi_dang_ky` đúng hình dạng
    # thật của việc này: một người `pending` cần đặt mật khẩu, đúng nhánh `signup`.
    token_tho = secrets.token_urlsafe(_SO_BYTE_TOKEN)
    await auth_repo.ghi_loi_moi_dang_ky(
        conn,
        token_hash=bam_token(token_tho),
        user_id=user_id,
        email=c.email,
        expires_at=datetime.now(UTC) + HAN_MOI,
        # `created_by` trỏ vào chính họ: hàng này không do ai khác tạo, và
        # `audit_log.actor` ở ② cũng ghi vậy. NULL thì đọc log không biết vì sao có.
        created_by=user_id,
    )
    return token_tho


async def main_async() -> int:
    c = doc_cau_hinh(dict(os.environ))
    # `database_url` (role runtime), KHÔNG `migrator_url`: mọi việc ở đây là DML
    # trên schema `control`, mà 0003 đã GRANT đủ cho role runtime. Dùng credential
    # DDL cho một việc không cần DDL là đưa nó ra khỏi hai file env đang tách rời
    # (deploy/README.md §1–§2).
    conn = await asyncpg.connect(get_settings().database_url)
    try:
        async with conn.transaction():
            token = await chay(conn, c)
    finally:
        await conn.close()

    if token is None:
        print("seed-owner: không có gì để làm.")
        return 0

    duong_dan = duong_dan_moi(token)
    print("seed-owner: xong.")
    print(f"  owner     {c.email}")
    print(f"  hạn mời   {HAN_MOI.days} ngày")
    print()
    print("  LINK MỜI — gửi cho owner, họ tự đặt mật khẩu. In MỘT LẦN, không lưu ở đâu:")
    print(f"  {c.goc_url}{duong_dan}" if c.goc_url else f"  <origin của FE>{duong_dan}")
    return 0


def main() -> None:
    try:
        sys.exit(asyncio.run(main_async()))
    except LoiBootstrap as e:
        print(f"seed-owner: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
