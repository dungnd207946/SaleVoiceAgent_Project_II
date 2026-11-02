"""Seed dev: 3 user · 3 workspace. Idempotent.

CHỈ CHẠY TRÊN CONTAINER DEV. Script này ghi mật khẩu đã hash vào control.users;
lỡ tay chạy với DSN production là tạo một tài khoản mà mật khẩu nằm trong Makefile.

VIẾT LẠI 2026-08-15 cùng việc bỏ tầng tổ chức. Bản cũ dựng HAI tổ chức và bất
biến nó dạy là "`haven` thuộc org khác nên không hiện trên switcher của dang".
Bất biến đó biến mất cùng `organizations`. Bất biến THAY THẾ, mạnh tương đương:

    dang@anphuland.vn   -> anphu, sunrise   (membership Quản trị / CSKH)
    haven@haven.vn      -> haven            (membership Quản trị)
    bientap@anphuland.vn-> anphu            (membership Biên tập)

`haven` tồn tại trong DB mà KHÔNG hiện trên switcher của dang — vì dang không có
hàng `memberships` nào ở đó, không phải vì một tổ chức nào ngăn lại. Cách ly giờ
do `memberships` canh, và đó là phép chứng minh bằng mắt vẫn dùng được.

Seed đúng những workspace mỗi user thấy được thì mọi bug lọc đều trông như chạy
đúng, và không ai phát hiện ra.

Ba workspace lấy đúng tên trong MSW của FE (`src/lib/msw/handlers.ts`) để so màn
thật với màn giả được ngay.

Chạy: make dev-seed   (sau make migrate && make grant-api-dev)
"""

import asyncio
import sys
from urllib.parse import urlparse

import asyncpg

from portal.core.auth import password as pw
from portal.core.config import get_settings

# (tenant_id, tên, created_by) — mỗi workspace có một người tạo.
#
# `tenants.created_by` là NOT NULL từ migration 0106; nó vừa thay `org_id` làm
# phạm vi cho ràng buộc tên, vừa trả lời "ai mở workspace này".
WORKSPACE = [
    ("anphu", "An Phú Land", "u_dang"),
    ("sunrise", "Sunrise Land", "u_dang"),
    ("haven", "Havenly Property", "u_haven"),
]

# (user_id, email, mật khẩu, tên)
#
# Mật khẩu "1" là CỐ Ý: tài khoản này chỉ để đối chiếu cách ly bằng mắt trên máy
# dev. kiem_localhost() bên dưới là thứ giữ nó ở đó.
NGUOI_DUNG = [
    ("u_dang", "dang@anphuland.vn", "odyssey-dev", "Trần Hải Đăng"),
    ("u_haven", "haven@haven.vn", "1", "Haven Dev"),
    # u_bt: member có vai trò «Biên tập» ở anphu. Đường `member` cần một người
    # thật để thấy được ma trận đang chặn đúng — owner thì không bao giờ bị chặn.
    # Mật khẩu "2", không "1": test_moi_user_co_mat_khau_rieng_va_khong_rong
    # (tests/unit/test_dev_seed_an_toan.py) đòi mỗi user một mật khẩu riêng, và
    # "1" đã là của u_haven ở trên.
    ("u_bt", "bientap@anphuland.vn", "2", "Lê Biên Tập"),
]

# (user_id, tenant_id, TÊN vai trò) — tra role_id theo `name`.
# Migration 0104 seed 4 vai trò, 0105 gỡ chúng khỏi tổ chức (toàn cục, UNIQUE(name));
# seed chỉ tra, không tạo lại.
#
# MỌI dòng ở đây giờ là BẮT BUỘC: nhánh owner trong `doc_quyen()` đã bỏ, nên
# không có membership là không thấy và không vào được. Không có dòng nào của
# u_dang trỏ tới haven — và đó chính là điều cần thấy trên switcher.
MEMBERSHIP = [
    ("u_dang", "anphu", "Quản trị"),
    ("u_dang", "sunrise", "CSKH"),
    ("u_haven", "haven", "Quản trị"),
    ("u_bt", "anphu", "Biên tập"),
]

HOST_CHO_PHEP = {"localhost", "127.0.0.1", "::1"}


def kiem_localhost(dsn: str) -> None:
    """Chặn chạy ngoài máy dev.

    So khớp CHÍNH XÁC với `urlparse().hostname`, không phải `"localhost" in dsn`:
    phép `in` cho `localhost.evil.vn` đi qua, và cho cả `?host=localhost` trong
    query string trong khi kết nối thật đi tới host khác.
    """
    host = urlparse(dsn).hostname or ""
    if host not in HOST_CHO_PHEP:
        sys.exit(
            f"TỪ CHỐI: dev_seed chỉ chạy trên localhost, DSN đang trỏ {host!r}.\n"
            f"Script này ghi mật khẩu dev vào control.users — chạy trên DB thật là tạo\n"
            f"một tài khoản mà mật khẩu nằm trong repo."
        )


async def chay(dsn: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            # USERS TRƯỚC TENANTS — thứ tự bắt buộc từ migration 0106:
            # `tenants.created_by` là FK tới `users(id)`, nên người tạo phải tồn tại
            # trước workspace của họ. Bản trước chèn tenants trước vì `org_id` trỏ
            # sang `organizations`, một bảng độc lập với users.
            #
            # Băm lại mỗi lần chạy là đúng: idempotent theo KẾT QUẢ (user tồn tại
            # với mật khẩu này), không theo hash — Argon2 có salt nên hash luôn khác.
            #
            # DO UPDATE cả email: đổi email trong file này rồi chạy lại phải kéo
            # được hàng cũ theo, không thì DB dev giữ email cũ mãi mà không ai biết.
            for uid, email, mat_khau, ten in NGUOI_DUNG:
                await conn.execute(
                    """INSERT INTO control.users (id, email, password_hash, name)
                       VALUES ($1,$2,$3,$4)
                       ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email,
                                                      password_hash = EXCLUDED.password_hash,
                                                      name = EXCLUDED.name""",
                    uid,
                    email,
                    pw.bam(mat_khau),
                    ten,
                )
            # DO UPDATE trên `created_by`: đổi người tạo trong file này rồi chạy lại
            # phải kéo được hàng cũ theo, không thì DB dev vĩnh viễn lệch với file.
            for tid, ten, nguoi_tao in WORKSPACE:
                await conn.execute(
                    """INSERT INTO control.tenants (id, name, created_by) VALUES ($1,$2,$3)
                       ON CONFLICT (id) DO UPDATE SET created_by = EXCLUDED.created_by""",
                    tid,
                    ten,
                    nguoi_tao,
                )
            for uid, tid, ten_vai_tro in MEMBERSHIP:
                # RETURNING + fetchval, KHÔNG chỉ execute(): đây là INSERT duy nhất trong
                # file có JOIN có thể khớp 0 dòng (tên vai trò gõ sai, hoặc user và vai
                # trò lệch tổ chức). Mọi INSERT khác ở trên là VALUES thuần — luôn đúng
                # 1 dòng, nên chưa từng cần kiểm. execute() bỏ command tag, và 0 dòng ghi
                # ra trông y hệt 1 dòng ghi ra trên console — im lặng để lại một DB dev
                # thiếu membership mà không dòng log nào nói vì sao.
                role_id = await conn.fetchval(
                    """INSERT INTO control.memberships (user_id, tenant_id, role_id)
                       SELECT $1, $2, r.id
                         FROM control.users u
                         JOIN control.roles r ON r.name = $3
                        WHERE u.id = $1
                       ON CONFLICT (user_id, tenant_id) DO UPDATE SET role_id = EXCLUDED.role_id
                       RETURNING role_id""",
                    uid,
                    tid,
                    ten_vai_tro,
                )
                if role_id is None:
                    raise RuntimeError(
                        f"MEMBERSHIP tra không ra: user={uid!r} workspace={tid!r} "
                        f"vai_tro={ten_vai_tro!r} — không có user này, hoặc không có vai "
                        f"trò tên đúng vậy. Kiểm lại NGUOI_DUNG và tên vai trò trong "
                        f"MEMBERSHIP (bốn vai trò mẫu là TOÀN CỤC từ migration 0105)."
                    )
    finally:
        await conn.close()

    print("seed xong.")
    for uid, email, mat_khau, _ in NGUOI_DUNG:
        # MỘT nguồn duy nhất cho "thấy gì": bảng MEMBERSHIP. Bản trước có thêm một
        # nhánh cho `org_role='owner'` (thấy mọi workspace cùng org) — nhánh đó đã
        # bỏ khỏi `doc_quyen()`, nên nếu giữ ở đây thì console in ra một danh sách
        # mà portal không hiện, và người dev tưởng mình vừa seed hỏng.
        thay = [t for u, t, _ in MEMBERSHIP if u == uid]
        khong_thay = [t for t, _, _ in WORKSPACE if t not in thay]
        print(f"  {email} / {mat_khau}")
        print(f"      thấy: {', '.join(thay)}")
        print(f"      KHÔNG được hiện trên switcher: {', '.join(khong_thay)}")


def main() -> None:
    dsn = get_settings().database_url
    kiem_localhost(dsn)
    asyncio.run(chay(dsn))


if __name__ == "__main__":
    main()
