"""Fixture chung.

Postgres là container RIÊNG của testcontainers (một cho cả phiên test) — không bao giờ
nối vào DB dev hay DB của dự án khác trên máy. Migration chạy thật (`alembic upgrade head`).

Hai pool, hai quyền — giống production:
- `admin_pool`: `portal_migrator` (owner) — CHỈ để seed/dọn/đọc kiểm trong test.
- `client`: app thật nối bằng `portal_api` — nếu GRANT thiếu, test đỏ như production đỏ.
"""

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import httpx
import psycopg
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

from portal.api.app import create_app
from portal.core.config import to_alembic_url
from portal.core.db.pool import create_pool

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MIGRATOR_USER = "portal_migrator"
MIGRATOR_PASSWORD = "dev"
API_PASSWORD = "apidev"


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    """DSN owner của container đã migrate xong."""
    with PostgresContainer(
        "postgres:18-alpine", username=MIGRATOR_USER, password=MIGRATOR_PASSWORD, dbname="portal"
    ) as pg:
        dsn = (
            f"postgresql://{MIGRATOR_USER}:{MIGRATOR_PASSWORD}"
            f"@{pg.get_container_host_ip()}:{pg.get_exposed_port(5432)}/portal"
        )
        cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
        cfg.set_main_option("sqlalchemy.url", to_alembic_url(dsn))
        command.upgrade(cfg, "head")
        # Migration tạo portal_api NOLOGIN (không mật khẩu trong git) — harness cấp login.
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f"ALTER ROLE portal_api LOGIN PASSWORD '{API_PASSWORD}'")
        yield dsn


@pytest.fixture(scope="session")
def api_dsn(pg_dsn: str) -> str:
    return pg_dsn.replace(f"{MIGRATOR_USER}:{MIGRATOR_PASSWORD}@", f"portal_api:{API_PASSWORD}@", 1)


def dsn_as(pg_dsn: str, user: str, password: str) -> str:
    return pg_dsn.replace(f"{MIGRATOR_USER}:{MIGRATOR_PASSWORD}@", f"{user}:{password}@", 1)


async def _don_sach(pool: asyncpg.Pool) -> None:
    """TRUNCATE mọi bảng `shop` + reset identity — test sau bắt đầu từ DB rỗng, id từ 1."""
    async with pool.acquire() as conn:
        bang = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'shop'")
        if bang:
            ds = ", ".join(f'shop."{b["tablename"]}"' for b in bang)
            await conn.execute(f"TRUNCATE {ds} RESTART IDENTITY CASCADE")


@pytest.fixture
async def admin_pool(pg_dsn: str) -> AsyncIterator[asyncpg.Pool]:
    p = await create_pool(pg_dsn, min_size=1, max_size=4)
    try:
        yield p
    finally:
        await _don_sach(p)
        await p.close()


@pytest.fixture
async def client(api_dsn: str, admin_pool: asyncpg.Pool) -> AsyncIterator[httpx.AsyncClient]:
    """Client HTTP vào app thật. Pool gắn thẳng vào `app.state` (ASGITransport không chạy lifespan).

    Phụ thuộc `admin_pool` để dữ liệu được dọn sau test.
    """
    app = create_app()
    app.state.pool = await create_pool(api_dsn, min_size=1, max_size=4)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        await app.state.pool.close()
