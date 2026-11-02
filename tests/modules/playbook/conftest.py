"""Fixture của module playbook — chép nếp tests/modules/ops/conftest.py (tenant tường minh, không mock tenant_conn)."""

import json
from datetime import UTC, datetime

import asyncpg
import httpx
import pytest

from portal.modules.playbook import nut as nut_mod

MAT_KHAU = "MatKhauDaiVaManh!1"
TENANT = "pbw"
TENANT_KHAC = "pbx"


@pytest.fixture
async def workspace_pb(pool: asyncpg.Pool):
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        for t, ten in ((TENANT, "Playbook Workspace"), (TENANT_KHAC, "Playbook Khac")):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')", t, ten
            )
        await conn.execute(
            "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
            "u_pb",
            "Đăng",
            "dang@pb.vn",
            bam(MAT_KHAU),
        )
        r_admin = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ('u_pb', $1, $2)",
            TENANT,
            r_admin,
        )
    yield TENANT
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.users WHERE id = 'u_pb'")


@pytest.fixture
async def conn_pb(pool: asyncpg.Pool, workspace_pb: str):
    from portal.core.db.session import tenant_conn

    async with tenant_conn(pool, workspace_pb) as conn:
        yield conn


@pytest.fixture
async def client_pb(app_client: httpx.AsyncClient, workspace_pb) -> httpx.AsyncClient:
    """Client đã đăng nhập vào workspace `pbw`."""
    r = await app_client.post("/api/v1/auth/login", json={"email": "dang@pb.vn", "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r = await app_client.post("/api/v1/me/workspace", json={"workspaceId": TENANT})
    assert r.status_code == 200, r.text
    return app_client


async def them_phien(
    conn: asyncpg.Connection,
    session_id: str,
    *,
    tenant: str = TENANT,
    phone: str | None = "0912448111",
    ten: str | None = "Minh Anh",
    chuyen: bool = False,
    source: str | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO tenant_data.conversations
            (tenant_id, session_id, phone, customer_name, transferred_to_sales, started_at, created_at, source)
        VALUES ($1,$2,$3,$4,$5, now(), now(), $6)
        """,
        tenant,
        session_id,
        phone,
        ten,
        chuyen,
        source,
    )


async def them_nhan(
    conn, sid, seq, playbook, *, created_at=None, user="Căn này đắt quá em", agent="Dạ em hiểu ạ", tenant=TENANT
):
    """Cặp user (seq-1) + assistant (seq) có meta.playbook; `playbook` là dict hoặc chuỗi JSON thô (meta hỏng)."""
    ts = created_at or datetime.now(UTC)
    meta = playbook if isinstance(playbook, str) else json.dumps({"playbook": playbook}, ensure_ascii=False)
    await conn.execute(
        "INSERT INTO tenant_data.conversation_messages (tenant_id, session_id, seq, role, content, created_at, meta)"
        " VALUES ($1, $2, $3, 'user', $4, $5, '{}'::jsonb)",
        tenant,
        sid,
        seq - 1,
        user,
        ts,
    )
    await conn.execute(
        "INSERT INTO tenant_data.conversation_messages (tenant_id, session_id, seq, role, content, created_at, meta)"
        " VALUES ($1, $2, $3, 'assistant', $4, $5, $6::jsonb)",
        tenant,
        sid,
        seq,
        agent,
        ts,
        meta,
    )


_HASH = {n["id"]: n["hash"] for n in nut_mod.doc()["nodes"]}
_MAC_DINH = object()


def nhan(nut="che_dat", *, dat=True, v="v3", h=_MAC_DINH, **kw):
    """`h` mặc định = hash nút trong JSON (nhãn agent đợt 2 ghi); `h=None` = nhãn trước đợt 2 (không có `h`)."""
    d = {"nut": nut, "v": v, **kw}
    h = _HASH.get(nut, "") if h is _MAC_DINH else h
    if h is not None:
        d["h"] = h
    if dat is not None:
        d["dat"] = dat
    return d
