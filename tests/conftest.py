"""Harness test: một container Postgres cho cả session, migration chạy một lần."""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from redis.asyncio import Redis
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from portal.api.app import create_app
from portal.core.config import to_alembic_url
from portal.core.db.pool import create_pool
from portal.core.redis import create_redis


def liet_ke_route(app: FastAPI) -> list[tuple[str, APIRoute]]:
    """MỌI route của app kèm đường đầy đủ — nguồn duy nhất cho các cổng route.

    ⚠ ĐỪNG THAY BẰNG `[r for r in app.routes if isinstance(r, APIRoute)]`.
    Đã xác minh trên FastAPI 0.141.1: `include_router()` KHÔNG duỗi phẳng route vào
    `app.routes` — nó đặt vào đó một `_IncludedRouter`, và object đó KHÔNG có thuộc
    tính `path`. Nên phép quét kia chỉ thấy route khai TRỰC TIẾP trên app, còn route
    của các module thì vô hình. Nó không nổ, nó trả tập rỗng — Cổng 1 dựng trên đó sẽ
    xanh vĩnh viễn. `tests/api/test_registry.py` neo lại đúng điều này.

    ⚠ VÀ ĐỪNG THAY BẰNG `app.openapi()["paths"]`. Nó duỗi phẳng đúng, nhưng bỏ hẳn
    route `include_in_schema=False` — biến "ẩn khỏi /docs" thành đường lách cổng
    quyền. Nó cũng không cho tới `route.dependant`, thứ Cổng 1 cần.

    `iter_route_contexts` là API của fastapi.routing làm đúng cả hai: duỗi phẳng
    router lồng nhau, và không bỏ route ẩn.
    """
    return [
        (ctx.path, ctx.route)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute) and ctx.path is not None
    ]


# Đường dẫn TUYỆT ĐỐI: Config("alembic.ini") tương đối làm `cd tests && pytest`
# ném CommandError. Đã kiểm chứng cả hai chiều.
BACKEND_ROOT = Path(__file__).resolve().parent.parent

MIGRATOR_USER = "portal_migrator"
MIGRATOR_PASSWORD = "dev"

# Mật khẩu của portal_api dùng trong test — NGUỒN DUY NHẤT.
# Migration 0003 cố tình tạo portal_api ở dạng NOLOGIN KHÔNG MẬT KHẨU (xem lý do
# ở đó: một mật khẩu trong git là quyền đọc-ghi mọi tenant cho bất kỳ ai chạm tới
# cổng Postgres). Nên chính harness test là chỗ cấp quyền đăng nhập, sau khi
# migration chạy xong — nó nối bằng bootstrap superuser của container nên làm được.
API_PASSWORD = "apidev"

# Mật khẩu của odyssey_agent dùng trong test — cùng lý lẽ, cùng khuôn với API_PASSWORD.
# Migration 0901 cũng tạo role này NOLOGIN không mật khẩu, và ở đây thì lý do fail-closed
# còn nặng hơn portal_api: đây là MỘT credential cho MỌI tenant (agent-postgres-read §0),
# nên một mật khẩu trong git là quyền đọc toàn bộ khách hàng.
ODYSSEY_AGENT_PASSWORD = "odysseydev"


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    """Container Postgres đã chạy migration xong. Trả DSN của **portal_migrator** (owner).

    Đây là DSN CHỈ-DDL/seed, không phải DSN runtime: fixture `pool` bên dưới dùng nó
    để seed dữ liệu (cần quyền owner vì FORCE RLS) và để tạo/xoá role trong test.
    Mọi pool mô phỏng runtime phải đi qua `api_dsn` — xem docstring của nó.
    """
    with PostgresContainer(
        # Cùng tag với docker-compose.local.yml (hai chỗ, đổi thì đổi cả hai).
        # KHÔNG khớp major Aurora ở production — khoảng hở đã biết, CI không bắt
        # được. Xem deploy/README.md §6.1.
        "postgres:18-alpine",
        username=MIGRATOR_USER,
        password=MIGRATOR_PASSWORD,
        dbname="portal",
    ) as pg:
        dsn = (
            f"postgresql://{MIGRATOR_USER}:{MIGRATOR_PASSWORD}"
            f"@{pg.get_container_host_ip()}:{pg.get_exposed_port(5432)}/portal"
        )
        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        # Alembic dùng DSN MIGRATOR — đây là đúng một nửa của luật "hai credential"
        # (Settings.alembic_url cũng suy từ migrator_url, không từ database_url).
        cfg.set_main_option("sqlalchemy.url", to_alembic_url(dsn))
        command.upgrade(cfg, "head")

        # Cấp quyền đăng nhập cho portal_api SAU migration. Migration không đặt mật
        # khẩu nào (fail-closed), nên nếu bỏ bước này thì mọi test dùng api_pool sẽ
        # đỏ với "role portal_api is not permitted to log in" — một lỗi TO, đúng như
        # thiết kế, thay vì một mật khẩu published âm thầm dùng được ở production.
        # `dsn` thô, KHÔNG phải to_alembic_url(dsn): "postgresql+psycopg://" là URL
        # của SQLAlchemy, libpq không hiểu tiền tố đó.
        with psycopg.connect(dsn, autocommit=True) as pgconn:
            pgconn.execute(f"ALTER ROLE portal_api LOGIN PASSWORD '{API_PASSWORD}'")
            pgconn.execute(f"ALTER ROLE odyssey_agent LOGIN PASSWORD '{ODYSSEY_AGENT_PASSWORD}'")

        yield dsn


@pytest.fixture
async def pool(pg_dsn: str) -> AsyncIterator[asyncpg.Pool]:
    """Pool bằng portal_migrator — dùng để seed dữ liệu test và quét catalog.

    CỐ Ý là owner: seed phải ghi cho nhiều tenant (bằng SET LOCAL từng tenant, vì
    FORCE RLS áp cả cho owner), và catalog test cần đọc pg_class. Nhưng owner vẫn có
    toàn quyền DDL, nên nó KHÔNG mô phỏng đúng runtime: test nào kiểm hành vi của
    tiến trình thật phải nối bằng `portal_api` qua fixture `api_dsn`.
    """
    p = await create_pool(pg_dsn, min_size=1, max_size=4)
    await _bao_dam_user_seed(p)
    yield p
    await p.close()


USER_SEED_TEST = "u_seed_test"
"""Người tạo mặc định cho mọi workspace dựng trong test.

Có từ 2026-08-15: `tenants.created_by` là NOT NULL REFERENCES users(id) — nó thay
`org_id` làm phạm vi cho ràng buộc tên workspace (migration 0106). Trước đó test
chèn `org_id = 'noble'` và không cần user nào tồn tại.

MỘT user dùng chung chứ không mỗi test một user: phần lớn test ở đây đo cách ly
tenant hoặc lược đồ, và ai tạo workspace không phải điều chúng nói về. Test nào
CÓ quan tâm (`tests/modules/workspace/`, `tests/integration/test_migration_bo_org_b.py`)
tự dựng người của nó và không dùng hằng này.

⚠ Vì dùng chung, ràng buộc `UNIQUE (created_by, lower(btrim(name)))` áp cho MỌI
workspace test tạo qua đường SQL trực tiếp — hai test đặt cùng một tên workspace
sẽ đụng nhau. `pg_dsn` là scope SESSION (một container cho cả lượt chạy) nên hàng
của test trước sống tới test sau và va vào nó.

Đó là lý do `dọn_workspace_seed` bên dưới chạy sau MỖI test. Không có nó, bộ test
đỏ theo kiểu tệ nhất: xanh khi chạy một mình, đỏ khi chạy cả bộ, và thông điệp
lỗi (`duplicate key`) không chỉ về test đã để lại rác.
"""


async def _bao_dam_user_seed(p: asyncpg.Pool) -> None:
    await p.execute(
        """INSERT INTO control.users (id, email, name, password_hash, lifecycle)
                VALUES ($1, 'seed.test@noblex.local', 'Seed Test', 'x', 'active')
             ON CONFLICT (id) DO NOTHING""",
        USER_SEED_TEST,
    )


@pytest.fixture(autouse=True)
async def don_workspace_seed(pg_dsn: str):
    """Xoá mọi workspace do `USER_SEED_TEST` tạo, SAU mỗi test.

    CHỈ của user seed: workspace do fixture riêng của module dựng (`u_ws_owner`,
    `u_ak_admin`, …) có vòng đời riêng và dọn ở fixture đó — quét sạch
    `control.tenants` ở đây sẽ giật thảm dưới chân chúng.

    CASCADE gỡ luôn memberships, audit_log và dữ liệu tenant_data của workspace đó.

    ⚠ Fixture của module thường dọn user bằng `DELETE ... WHERE id LIKE 'u\\_%'`.
    Câu đó KHỚP CẢ `u_seed_test`, và vì user này còn workspace nên FK chặn → chính
    teardown ném lỗi → user của test (`u_dang`, …) không được dọn → mọi test sau
    đỏ với `duplicate key`. Mọi câu dọn kiểu đó đã thêm `AND id <> 'u_seed_test'`.
    """
    yield
    p = await create_pool(pg_dsn, min_size=1, max_size=1)
    try:
        await p.execute("DELETE FROM control.tenants WHERE created_by = $1", USER_SEED_TEST)
    finally:
        await p.close()


@pytest.fixture
def api_dsn(pg_dsn: str) -> str:
    """DSN RUNTIME — role `portal_api`. Mọi pool mô phỏng API/worker dùng cái này."""
    return dsn_as(pg_dsn, "portal_api", API_PASSWORD)


def dsn_as(dsn: str, user: str, password: str) -> str:
    """Đổi thông tin đăng nhập trong DSN, giữ nguyên host/port/db.

    Dùng để nối bằng portal_api hoặc agent_<tenant> trong test cách ly.
    """
    tail = dsn.split("@", 1)[1]
    return f"postgresql://{user}:{password}@{tail}"


# ─── Redis (M2a — phiên đăng nhập) ──────────────────────────────────────────


@pytest.fixture(scope="session")
def redis_url() -> Iterator[str]:
    """Redis THẬT trong container, KHÔNG fakeredis.

    Vì sao container: phiên dựa vào TTL và vào lệnh EXPIRE gia hạn. fakeredis mô
    phỏng TTL bằng đồng hồ của tiến trình test, nên một bug kiểu "quên EXPIRE" sẽ
    xanh ở fakeredis và đỏ ở production. Cùng lý lẽ với việc M1 dùng Postgres thật
    thay vì sqlite.

    Cùng tag với docker-compose.local.yml (hai chỗ, đổi thì đổi cả hai).
    """
    with RedisContainer("redis:7-alpine") as c:
        yield f"redis://{c.get_container_host_ip()}:{c.get_exposed_port(6379)}/0"


# ─── Kho tri thức (M6 — một collection mỗi tenant) ──────────────────────────


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    """Qdrant THẬT trong container, KHÔNG client giả.

    Cổng 1 của M6 là cách ly BẰNG CẤU TRÚC: mỗi tenant một collection. Một client
    giả nhận mọi tên collection và trả mọi thứ ta bảo nó trả — nó xanh cho đúng
    cái lỗi cổng này tồn tại để bắt. Cùng lý lẽ với Postgres thật ở M1, Redis
    thật ở M2a, MinIO thật ở M3.
    """
    from testcontainers.community.qdrant import QdrantContainer

    with QdrantContainer("qdrant/qdrant:latest") as c:
        yield f"http://{c.get_container_host_ip()}:{c.get_exposed_port(6333)}"


# ─── Kho tệp (M3 — bundle + con trỏ LIVE) ───────────────────────────────────


@pytest.fixture(scope="session")
def minio_endpoint() -> Iterator[str]:
    """MinIO THẬT trong container, KHÔNG mock S3.

    Vì sao container: cổng 2 của M3 là **thứ tự ghi** — bundle trước, con trỏ
    `LIVE` cuối cùng — và cổng 5 là **policy theo tiền tố**. Một mock S3 nhận mọi
    thứ tự ghi và không có khái niệm policy, nên nó xanh cho đúng những lỗi hai
    cổng đó tồn tại để bắt. Cùng lý lẽ với việc M1 dùng Postgres thật thay sqlite
    và M2a dùng Redis thật thay fakeredis.

    Cùng image với docker-compose.local.yml (hai chỗ, đổi thì đổi cả hai).
    """
    from testcontainers.community.minio import MinioContainer

    with MinioContainer("minio/minio:latest") as c:
        cfg = c.get_config()
        yield f"http://{cfg['endpoint']}"


@pytest.fixture
async def kho_tep(minio_endpoint: str, monkeypatch):
    """Kho tệp rỗng ở đầu mỗi test, bucket đã tạo sẵn.

    Rỗng lại mỗi test chứ không mỗi session: container là scope session nên
    bundle của test trước sống sang test sau, và một test "chưa publish thì LIVE
    không tồn tại" sẽ xanh hoặc đỏ tuỳ thứ tự chạy.

    ⚠ Đặt luôn 4 biến môi trường S3_* — KHÔNG chỉ trả về instance. Lý do: tầng
    service (`service.publish`, `service.tro_lai`) không nhận kho tệp qua tham số,
    nó gọi `kho_tep_tu_cai_dat()` → `get_settings()`. Nên một test khai `kho_tep`
    rồi gọi service trực tiếp (không qua `app_client`) sẽ nhận instance này mà
    service vẫn ghi vào MẶC ĐỊNH của Settings: `http://localhost:9002` bucket
    `odyssey` — tức MinIO dev của docker-compose.local.yml. Trên máy dev thì cổng
    đó CÓ người nghe nên test xanh (mà bundle rơi vào bucket dev thật, không phải
    container throwaway); trên runner CI không có gì ở 9002 nên đỏ với
    EndpointConnectionError, ở một dòng trông chẳng liên quan tới kho tệp.
    Cùng 4 biến này `app_client` cũng đặt — trùng giá trị nên hai fixture đi
    chung thứ tự nào cũng như nhau.
    """
    from portal.core.storage import KhoTep

    monkeypatch.setenv("S3_ENDPOINT_URL", minio_endpoint)
    monkeypatch.setenv("S3_BUCKET", MINIO_BUCKET)
    monkeypatch.setenv("S3_ACCESS_KEY", MINIO_USER)
    monkeypatch.setenv("S3_SECRET_KEY", MINIO_PASSWORD)

    kho = KhoTep(
        endpoint_url=minio_endpoint,
        bucket=MINIO_BUCKET,
        access_key=MINIO_USER,
        secret_key=MINIO_PASSWORD,
    )
    await kho.tao_bucket_neu_chua_co()
    await kho.xoa_sach()
    return kho


MINIO_USER = "minioadmin"
MINIO_PASSWORD = "minioadmin"
MINIO_BUCKET = "odyssey-test"


@pytest.fixture
async def redis_client(redis_url: str) -> AsyncIterator[Redis]:
    """Client Redis, store rỗng ở đầu mỗi test.

    `flushdb` chứ không phải xoá theo tiền tố: container là scope session nên phiên
    của test trước sống sang test sau, và một test "đọc id rác trả None" sẽ xanh
    hoặc đỏ tuỳ thứ tự chạy.
    """
    r = create_redis(redis_url)
    await r.flushdb()
    yield r
    await r.aclose()


# ─── App thật, nói chuyện qua ASGI ──────────────────────────────────────────


@pytest.fixture
async def app_client(
    pg_dsn: str, redis_url: str, redis_client: Redis, minio_endpoint: str, monkeypatch
) -> AsyncIterator[httpx.AsyncClient]:
    """App THẬT với lifespan THẬT (pool + redis), nói chuyện qua ASGI.

    ⚠ Nhận `redis_client` dù không dùng tới nó: đó là cách BUỘC THỨ TỰ. `redis_client`
    chạy `flushdb` lúc setup, nên nếu một test khai `(dang_nhap_san, pool, redis_client)`
    thì pytest dựng fixture theo thứ tự tham số — đăng nhập xong mới flush, và bản
    ghi phiên vừa tạo bị xoá ngay. Test đỏ ở một dòng assert trông chẳng liên quan.
    Khai phụ thuộc ở đây đưa việc đó về đồ thị phụ thuộc, không còn phụ thuộc thứ tự
    tham số mà người viết test sau này không có lý do gì để biết.

    ⚠ `httpx.ASGITransport` KHÔNG chạy lifespan — đã kiểm chứng: app.state trống
    trơn nếu chỉ bọc transport. Nên phải mở `app.router.lifespan_context(app)`
    bằng tay. Bỏ bước này thì mọi test endpoint đỏ với AttributeError trên
    `app.state.pool`, và người đọc tưởng lỗi ở code chứ không phải ở fixture.

    ⚠ `base_url` là **https**, không phải http. Cookie phiên đặt `Secure` (spec
    §2.4), và http.cookiejar không gửi cookie Secure qua http:// — đã kiểm: server
    nhận `<KHÔNG CÓ>` với http, nhận đúng giá trị với https. Dùng http ở đây thì
    mọi test có phiên trả 401 và trông như lỗi xác thực.
    Ở dev thật không vướng: trình duyệt miễn trừ `http://localhost` cho cookie Secure.

    DSN runtime là `portal_api` (KHÔNG phải migrator) — đúng role mà production
    dùng, nên test cũng chịu đúng ràng buộc RLS/quyền như production.
    """
    monkeypatch.setenv("DATABASE_URL", dsn_as(pg_dsn, "portal_api", API_PASSWORD))
    monkeypatch.setenv("REDIS_URL", redis_url)
    # Kho tệp đặt qua BIẾN MÔI TRƯỜNG, không tiêm vào app.state: handler job
    # `publish` chạy trong tiến trình worker, nơi không có app nào cả. Cả hai
    # đường phải nhìn thấy cùng một kho, và `Settings` là chỗ duy nhất cả hai đọc.
    monkeypatch.setenv("S3_ENDPOINT_URL", minio_endpoint)
    monkeypatch.setenv("S3_BUCKET", MINIO_BUCKET)
    monkeypatch.setenv("S3_ACCESS_KEY", MINIO_USER)
    monkeypatch.setenv("S3_SECRET_KEY", MINIO_PASSWORD)

    app = create_app()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as c:
            yield c
