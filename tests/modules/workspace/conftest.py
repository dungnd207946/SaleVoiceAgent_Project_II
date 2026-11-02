"""Fixture của module workspace.

CỐ Ý KHÔNG dùng `tests/modules/auth/conftest.py` dù nó đã dựng org/tenant/user:
pytest chỉ tự nạp `conftest.py` của cây tổ tiên, nên dùng nó phải import chéo — và
file đó đang được sửa bởi một effort song song (vai trò động). Một fixture 40 dòng
tự chủ rẻ hơn một phụ thuộc vào file đang đổi.

TIỀN TỐ `ws_` cho mọi id fixture dựng ra: câu dọn cuối dùng `LIKE 'ws\\_%'`, và
endpoint đang test thì TỰ SINH id từ tên (không đoán trước được). Nên tên workspace
trong test phải bắt đầu bằng "Ws " để `slug_tenant()` ra id có tiền tố đó — nếu
không, hàng do endpoint tạo sẽ sống sót qua test sau.
"""

import asyncpg
import httpx
import pytest

MAT_KHAU = "MatKhauDaiVaManh!1"


@pytest.fixture
async def to_chuc_ws(pool: asyncpg.Pool):
    """Ba user, hai workspace — không còn tổ chức nào (bỏ 2026-08-15).

    Mật khẩu băm bằng đúng hàm production dùng — hash cứng trong test là thứ hết
    hạn im lặng ngày ai đó đổi tham số Argon2.

    CẢ BA đều có membership. Trước đây `u_ws_owner` cố ý KHÔNG có: nhánh
    `org_role='owner'` trong `liet_ke_workspace()` cho họ thấy mọi workspace của
    tổ chức mà không cần hàng nào. Nhánh đó đã bỏ — không membership giờ nghĩa là
    `workspaces` rỗng và `currentWorkspaceId=None`, tức họ đăng nhập được nhưng
    rơi vào màn "tạo workspace đầu tiên", không phải thứ bộ test này đang đo.

    `u_ws_owner2` giữ tên cũ nhưng nghĩa đã đổi: nó là NGƯỜI TẠO KHÁC, dùng để
    chứng minh "trùng tên workspace giữa hai người tạo thì hợp lệ" — thay cho bất
    biến cũ "trùng tên khác org thì OK" (`UNIQUE (created_by, lower(btrim(name)))`,
    migration 0106).
    """
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        for uid, email in (
            ("u_ws_owner", "owner@anphuland.vn"),
            ("u_ws_member", "member@anphuland.vn"),
            ("u_ws_owner2", "owner2@khac.vn"),
        ):
            await conn.execute(
                "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
                uid,
                email.split("@")[0],
                email,
                bam(MAT_KHAU),
            )
        # Hai workspace SẴN CÓ, hai người tạo khác nhau — cùng TÊN hiển thị để
        # chính cặp này là bằng chứng ràng buộc tên chỉ áp trong phạm vi một người.
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('ws_co_san', 'Ws Có Sẵn', 'u_ws_owner')"
        )
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('ws_co_san2', 'Ws Có Sẵn', 'u_ws_owner2')"
        )
        # Bốn vai trò mẫu là TOÀN CỤC từ 0105. Fixture chỉ TRA id — không tự dựng.
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        assert r_admin, "migration 0104/0105 chưa seed vai trò 'Quản trị' — fixture không dựng thay được"
        await conn.executemany(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)",
            [
                ("u_ws_owner", "ws_co_san", r_admin),
                ("u_ws_member", "ws_co_san", r_admin),
                ("u_ws_owner2", "ws_co_san2", r_admin),
            ],
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        # XOÁ THEO `created_by`, KHÔNG theo tiền tố id.
        #
        # `tenants.created_by` là FK KHÔNG CASCADE (migration 0106) — cố ý: xoá một
        # người không được kéo theo workspace mà cả đội đang dùng. Nên teardown phải
        # dọn workspace TRƯỚC, và phải dọn HẾT: endpoint tự sinh id từ tên, nên một
        # test đặt tên không bắt đầu bằng "Ws" sẽ để lại hàng mà `LIKE 'ws\_%'`
        # không thấy — và teardown ném ForeignKeyViolation, không dọn nổi user, rồi
        # mọi test sau đỏ với `duplicate key`.
        await conn.execute("DELETE FROM control.tenants WHERE created_by LIKE 'u\\_ws\\_%' OR id LIKE 'ws\\_%'")
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_ws\\_%' AND id <> 'u_seed_test'")

        # NHẬT KÝ CẤP HỆ THỐNG KHÔNG CASCADE — đó chính là điểm của nó.
        # `workspace.xoa` ghi bằng `nhat_ky.ghi_he_thong()` (`tenant_id IS NULL`) để
        # dòng đó sống sót câu `DELETE` đã cuốn theo mọi thứ mang tenant_id. Hệ quả ở
        # đây: câu dọn tenant phía trên không với tới nó, nên mỗi lượt chạy bộ test
        # để lại thêm một dòng, và bài canh nó (`test_xoa_ghi_nhat_ky_song_sot_cascade`)
        # dùng `fetchrow` trên một tập ngày càng lớn.
        await conn.execute("DELETE FROM control.audit_log WHERE tenant_id IS NULL AND chi_tiet->>'id' LIKE 'ws\\_%'")
        # Role Postgres cũng là đối tượng cấp CLUSTER, ngoài mọi cascade. Một test
        # xoá-role thất bại giữa đường để lại `agent_ws_*` sống, và nó không thuộc
        # database nào nên `make reset` cũng không dọn.
        for r in await conn.fetch("SELECT rolname FROM pg_roles WHERE rolname LIKE 'agent\\_ws\\_%'"):
            await conn.execute(f'DROP ROLE IF EXISTS "{r["rolname"]}"')


async def dang_nhap(client: httpx.AsyncClient, email: str) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": MAT_KHAU})
    assert r.status_code == 200, r.text


@pytest.fixture
async def client_owner(app_client: httpx.AsyncClient, to_chuc_ws) -> httpx.AsyncClient:
    await dang_nhap(app_client, "owner@anphuland.vn")
    return app_client


@pytest.fixture
async def client_member(app_client: httpx.AsyncClient, to_chuc_ws) -> httpx.AsyncClient:
    await dang_nhap(app_client, "member@anphuland.vn")
    return app_client
