"""Fixture dùng chung cho test M10.

`get_settings()` dựng `Settings()` MỚI mỗi lần gọi (không lru_cache), nên
`monkeypatch.setenv` là đủ — không có cache nào phải clear. Nếu ai đó thêm cache
vào đó, mọi test ở đây sẽ đọc cấu hình của test chạy trước và đỏ theo kiểu khó
hiểu; lúc ấy `fixture moi_truong` là chỗ thêm `cache_clear()`.
"""

import httpx
import pytest

from tests.conftest import MINIO_BUCKET, MINIO_PASSWORD, MINIO_USER, dsn_as

MASTER_KEY = "khoa-goc-test-du-32-byte-cho-hmac-sha256"
ADMIN_TOKEN = "token-quan-tri-test-du-32-ky-tu-tro-len"

TENANT_A = "anphu"
TENANT_B = "bcland"

MAT_KHAU = "MatKhauDaiVaManh!1"
EMAIL_ADMIN = "ak_admin@anphuland.vn"
EMAIL_THUONG = "ak_thuong@anphuland.vn"


@pytest.fixture
def moi_truong(monkeypatch, pg_dsn: str, minio_endpoint: str, redis_url: str):
    """Cấu hình runtime cho test gọi service trực tiếp (không qua app_client).

    DSN là `portal_api` — đúng role production dùng, nên test chịu đúng ràng buộc
    quyền. Nếu để `portal_migrator` thì `dat_mat_khau_agent()` chạy được vì owner
    có CREATEROLE, và ta sẽ không phát hiện ra runtime thật KHÔNG có nó.
    """
    from tests.conftest import API_PASSWORD

    monkeypatch.setenv("DATABASE_URL", dsn_as(pg_dsn, "portal_api", API_PASSWORD))
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("S3_ENDPOINT_URL", minio_endpoint)
    monkeypatch.setenv("S3_BUCKET", MINIO_BUCKET)
    monkeypatch.setenv("S3_ACCESS_KEY", MINIO_USER)
    monkeypatch.setenv("S3_SECRET_KEY", MINIO_PASSWORD)
    monkeypatch.setenv("AGENT_MASTER_KEY", MASTER_KEY)
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", ADMIN_TOKEN)


@pytest.fixture
def ha_tang(moi_truong):
    from portal.modules.enrollment.ha_tang import HaTang

    return HaTang.tu_cai_dat()


@pytest.fixture
async def api_pool(moi_truong, api_dsn: str):
    """Pool bằng `portal_api` — role thật của API. Dùng cho mọi test nghiệp vụ."""
    from portal.core.db.pool import create_pool

    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


@pytest.fixture
async def hai_tenant(pool):
    """Hai workspace có thật, mỗi bên một dự án `published`.

    Seed bằng `pool` (owner) vì nó phải ghi cho HAI tenant; `tenant_conn` đặt
    SET LOCAL từng tenant để qua FORCE RLS.

    ⚠ RESET `agent_keys` và `agent_credentials` ở ĐẦU mỗi test. `pg_dsn` là
    fixture scope session — một container Postgres cho cả lượt chạy — nên
    `secret_version` tích luỹ qua các test và mọi assert kiểu "version == 2" hay
    "dan_xuat(..., 1, ...)" sẽ xanh hoặc đỏ TUỲ THỨ TỰ CHẠY. Đó là loại test tệ
    nhất: nó đỏ ở CI và xanh khi chạy một mình.

    Không xoá `control.tenants`: `lifecycle` bị test suspended đổi, nên dùng
    ON CONFLICT DO UPDATE đưa nó về 'active' thay vì xoá cả cây con.
    """
    from portal.core.db.session import tenant_conn

    # `agent_keys` PHẢI xoá TƯỜNG MINH từ `0940`: trước đó nó treo vào
    # `deployments` nên câu DELETE cho bảng kia cuốn theo bằng cascade. Giờ khoá treo
    # thẳng vào `tenant_id` (không xoá) — thiếu dòng này thì khoá tích luỹ qua các test
    # trên cùng container `pg_dsn` scope session, và mọi assert đếm khoá sẽ xanh hay đỏ
    # TUỲ THỨ TỰ CHẠY. (`control.deployments` đã bỏ ở `0941`.)
    await pool.execute(
        "DELETE FROM control.agent_keys WHERE tenant_id = ANY($1::text[])",
        [TENANT_A, TENANT_B],
    )
    # Nhịp tim khoá theo `tenant_id` từ `0941` — một hàng sót lại làm bài đếm hàng của
    # `test_bo_deployments.py` đỏ tuỳ thứ tự chạy, cùng lý lẽ hai câu trên.
    await pool.execute(
        "DELETE FROM control.agent_heartbeats WHERE tenant_id = ANY($1::text[])",
        [TENANT_A, TENANT_B],
    )
    await pool.execute(
        "DELETE FROM control.agent_credentials WHERE tenant_id = ANY($1::text[])",
        [TENANT_A, TENANT_B],
    )
    for tid, ten in ((TENANT_A, "An Phú Land"), (TENANT_B, "BC Land")):
        await pool.execute(
            """INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')
               ON CONFLICT (id) DO UPDATE SET lifecycle = 'active'""",
            tid,
            ten,
        )
        async with tenant_conn(pool, tid) as conn:
            await conn.execute(
                """INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)
                   VALUES ($1, $2, $3, 'published') ON CONFLICT DO NOTHING""",
                tid,
                f"DA-{tid}",
                f"Dự án {tid}",
            )
            # `pg_dsn` scope session — feedback của test trước tích luỹ nếu không dọn,
            # và assert `total`/phân trang sẽ đỏ hoặc xanh TUỲ THỨ TỰ CHẠY (cùng lý lẽ
            # agent_keys/agent_credentials ở trên).
            await conn.execute("DELETE FROM tenant_data.agent_feedback WHERE tenant_id = $1", tid)
    return TENANT_A, TENANT_B


# ─── Sesion HTTP qua app THẬT — dùng chung cho test_router_tenant.py và
# test_feedback.py. Ở CONFTEST (không phải import chéo giữa hai file test): mọi
# fixture pytest-discover được cho CẢ CÂY test dưới thư mục này, nên đây là chỗ
# một fixture ĐÚNG NGHĨA "dùng chung" phải nằm — import một fixture từ file test
# khác vào tên tham số cùng tên bị ruff coi là redefine (F811), và tệ hơn: hai
# file rồi sẽ tự nhân đôi fixture của nhau nếu ai đó quên import.
#
# TIỀN TỐ `u_ak_` cho mọi user fixture dựng: câu dọn cuối dùng `LIKE 'u\\_ak\\_%'`.


@pytest.fixture
async def nguoi_dung(pool, hai_tenant):
    """Hai user với vai trò KHÁC NHAU ở workspace — và đó là cả điểm.

    `ak_admin` được cấp vai trò "Quản trị" ở CẢ HAI workspace — đủ danh mục action
    ở mỗi nơi. Đúng thứ test cách ly cần: cùng một người, hai workspace, vẫn
    không được thò tay sang bên kia.

    `ak_thuong` chỉ có membership ở TENANT_A với `vai_tro_hep` (vai trò 0 quyền),
    ra một người đăng nhập được, thuộc workspace, mà thiếu action thứ 13.

    ⚠ TRƯỚC 2026-08-15 `ak_admin` là `org_role='owner'` và KHÔNG có membership nào:
    nhánh owner của `doc_quyen()` cấp đủ 13 action ở mọi workspace cùng tổ chức.
    Nhánh đó đã bỏ, nên membership tường minh là bắt buộc — thiếu nó thì `ak_admin`
    có 0 action và mọi test ở đây đỏ ở bước đầu tiên.
    """
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        for uid, email in (
            ("u_ak_admin", EMAIL_ADMIN),
            ("u_ak_thuong", EMAIL_THUONG),
        ):
            await conn.execute(
                "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
                uid,
                email.split("@")[0],
                email,
                bam(MAT_KHAU),
            )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.executemany(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)",
            [("u_ak_admin", TENANT_A, r_admin), ("u_ak_admin", TENANT_B, r_admin)],
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.users WHERE id LIKE 'u\\_ak\\_%' AND id <> 'u_seed_test'")


@pytest.fixture
async def vai_tro_hep(pool, nguoi_dung):
    """Vai trò 0 quyền gắn cho `ak_thuong` (member) ở TENANT_A.

    Vai trò không có hàng `role_actions` nào là trạng thái HỢP LỆ theo spec §2.1
    ("đã tạo, chưa cấu hình") — đúng thứ cần để chứng minh cổng action chặn thật.

    Membership này cũng là điều kiện để `ak_thuong` ĐĂNG NHẬP ĐƯỢC:
    `liet_ke_workspace()` trả rỗng cho member không membership và `dang_nhap()`
    raise 409 NO_WORKSPACE. Nên fixture này phục vụ hai việc, và bỏ nó đi thì test
    403 đỏ ở bước đăng nhập với một thông điệp không dẫn tới nguyên nhân.
    """
    async with pool.acquire() as conn, conn.transaction():
        rid = await conn.fetchval(
            "INSERT INTO control.roles (id, name, description) VALUES ('r_ak_hep', 'AK Vai Hẹp', 'test') RETURNING id"
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_ak_thuong', $1, $2)",
            TENANT_A,
            rid,
        )
    yield
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.memberships WHERE user_id = 'u_ak_thuong'")
        await conn.execute("DELETE FROM control.roles WHERE id = 'r_ak_hep'")


async def _vao(client: httpx.AsyncClient, email: str, tenant: str) -> None:
    """Đăng nhập rồi ĐẶT workspace hiện tại — hai bước, không gộp.

    `login` chọn workspace nào là chi tiết của M2a; test này cần biết CHẮC nó đang
    ở tenant nào, vì toàn bộ ý nghĩa của cách ly nằm ở đó.
    """
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r = await client.post("/api/v1/me/workspace", json={"workspaceId": tenant})
    assert r.status_code == 200, r.text


@pytest.fixture
async def client(app_client, monkeypatch, nguoi_dung):
    monkeypatch.setenv("AGENT_MASTER_KEY", MASTER_KEY)
    return app_client


@pytest.fixture
async def client_admin(client):
    await _vao(client, EMAIL_ADMIN, TENANT_A)
    return client
