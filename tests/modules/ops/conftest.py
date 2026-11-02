"""Fixture của M7 — cùng nếp tests/modules/realestate/conftest.py.

Không mock `tenant_conn()`: nó là seam của cách ly, mock nó thì test xanh cho cả
một truy vấn quên `WHERE tenant_id`.
"""

import json
from datetime import UTC, datetime, timedelta

import asyncpg
import httpx
import pytest

MAT_KHAU = "MatKhauDaiVaManh!1"
TENANT = "opsw"
TENANT_KHAC = "opsx"


@pytest.fixture
async def workspace_ops(pool: asyncpg.Pool):
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        for t, ten in ((TENANT, "Ops Workspace"), (TENANT_KHAC, "Ops Khac")):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')", t, ten
            )
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
            "u_ops",
            "Đăng",
            "dang@ops.vn",
            bam(MAT_KHAU),
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_ops', $1, $2)",
            TENANT,
            r_admin,
        )
    yield TENANT
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.users WHERE id = 'u_ops'")


@pytest.fixture
async def conn_ops(pool: asyncpg.Pool, workspace_ops: str):
    from portal.core.db.session import tenant_conn

    async with tenant_conn(pool, workspace_ops) as conn:
        yield conn


def luc(ngay: int, gio: int = 10) -> datetime:
    """Mốc thời gian tất định — KHÔNG dùng now() trong test.

    now() làm ca «7 ngày qua» đỏ vào đúng ngày thứ 8 sau khi ai đó viết test, và
    người sửa sẽ nghĩ mình vừa làm hỏng bộ lọc.
    """
    return datetime(2026, 7, ngay, gio, 0, tzinfo=UTC)


def cach_day(so_ngay: float) -> datetime:
    """Mốc TƯƠNG ĐỐI so với `now()` — chỉ dùng cho test bộ lọc thời gian.

    Bộ lọc so với `now()` của Postgres, nên một mốc cố định như `luc(27)` sẽ đổi
    nghĩa mỗi ngày trôi qua: hôm nay nó nằm trong «30 ngày», tháng sau thì không.
    Test viết bằng `luc()` cho bộ lọc thời gian là test tự hỏng theo lịch.
    """
    return datetime.now(UTC) - timedelta(days=so_ngay)


async def them_phien(
    conn: asyncpg.Connection,
    session_id: str,
    *,
    tenant: str = TENANT,
    phone: str | None = "0912448111",
    ten: str | None = "Minh Anh",
    summary: str | None = "Hỏi căn 3PN",
    du_an: str | None = "Ocean Park 2",
    chuyen: bool = False,
    bat_dau: datetime | None = None,
    source: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO tenant_data.conversations
            (tenant_id, session_id, phone, customer_name, summary, project,
             transferred_to_sales, started_at, created_at, source)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8, COALESCE($8, now()), $9)
        """,
        tenant,
        session_id,
        phone,
        ten,
        summary,
        du_an,
        chuyen,
        bat_dau or luc(27),
        source,
    )


async def them_luot(
    conn: asyncpg.Connection,
    session_id: str,
    seq: int,
    *,
    tenant: str = TENANT,
    role: str = "user",
    content: str = "xin chào",
    tao_luc: datetime | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO tenant_data.conversation_messages
            (tenant_id, session_id, seq, role, content, created_at)
        VALUES ($1,$2,$3,$4,$5,$6)
        """,
        tenant,
        session_id,
        seq,
        role,
        content,
        tao_luc or luc(27),
    )


async def them_ca(
    conn: asyncpg.Connection,
    session_id: str,
    *,
    tenant: str = TENANT,
    phone: str | None = "0912448111",
    ten: str | None = "Minh Anh",
    du_an: str | None = None,
    tool_thieu: str | None = None,
    summary: str | None = "Khách: Minh Anh, SĐT: 0912448111. Lý do chuyển: hỏi sổ hồng.",
    summary_luc: datetime | None = None,
    message_seq: int | None = 7,
    trang_thai: str = "new",
    tao_luc: datetime | None = None,
    lead_stage: str | None = None,
    lead_score: int | None = None,
    audience: str | None = None,
    lead_signals: list[str] | None = None,
) -> int:
    return await conn.fetchval(
        """
        INSERT INTO tenant_data.escalations
            (tenant_id, session_id, phone, customer_name, project, missing_data_tool,
             summary, summary_at, message_seq, status, created_at,
             lead_stage, lead_score, audience, lead_signals)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15::jsonb)
        RETURNING id
        """,
        tenant,
        session_id,
        phone,
        ten,
        du_an,
        tool_thieu,
        summary,
        summary_luc,
        message_seq,
        trang_thai,
        tao_luc or luc(27),
        lead_stage,
        lead_score,
        audience,
        None if lead_signals is None else json.dumps(lead_signals),
    )


async def them_du_an(conn: asyncpg.Connection, code: str, name: str, *, tenant: str = TENANT) -> None:
    await conn.execute(
        "INSERT INTO tenant_data.projects (tenant_id, project_code, name) VALUES ($1,$2,$3)",
        tenant,
        code,
        name,
    )


@pytest.fixture
async def client_ops(app_client: httpx.AsyncClient, workspace_ops) -> httpx.AsyncClient:
    """Client đã đăng nhập vào workspace `opsw`."""
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@ops.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r = await app_client.post("/api/v1/me/workspace", json={"workspaceId": TENANT})
    assert r.status_code == 200, r.text
    return app_client
