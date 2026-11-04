"""Billing usage_events — bốn khẳng định về ràng buộc DB (spec §9).

Bảng do Portal sở hữu. Trên DB `portal` thật nó **đã tồn tại** từ 2026-08-18
(contract §14) và cả 4 khẳng định dưới đây **đã được kiểm tay ở đó**; bộ test này
là bản tự động hoá để hồi quy trên DB test. Cần ``SPE_PG_ADMIN_DSN`` *và*
``billing.usage_events`` có thật, nếu không thì skip sạch.

⚠️ **Đừng trỏ ``SPE_PG_ADMIN_DSN`` vào DB `portal` production.** Fixture gọi
``apply_schema`` + ``provision``/``deprovision``, tức chạy DDL và tạo/xoá role —
side effect trên DB của team khác. Dùng DB test (hoặc replica) có sẵn
``agent_all`` và ``portal.current_tenant()``, vì policy của bảng keyed theo hai
thứ đó.

Bốn khẳng định — mỗi cái canh một cách hoá đơn sai khác nhau:

1. Ràng buộc ``usage_events_idem`` tồn tại đúng 7 cột. Thiếu nó thì mỗi lần
   retry sinh một dòng mới và **khách bị tính tiền hai lần** (contract §4 —
   "điểm quan trọng nhất trong toàn bộ tài liệu").
2. INSERT lại cùng ``seq`` bị ``DO NOTHING`` nuốt, KHÔNG nhân dòng. Đây chính là
   test bắt được lỗi đã sập trong `_aggregate_events` (khoá gộp từng có thêm
   ``exact``, sinh hai dòng cùng 7 cột khoá trong một lô → dòng mang token thật
   bị bỏ im lặng).
3. ``UPDATE`` bị từ chối — append-only phải do GRANT cưỡng chế, không do kỷ luật
   code (contract §0).
4. Ghi ``tenant_id`` của tenant khác bị ``WITH CHECK`` chặn — một bug phía agent
   không được ghi tiêu thụ của A vào sổ của B (contract §6).

    SPE_PG_ADMIN_DSN=postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey \
      pytest tests/integration/tenant/test_billing_usage_events_live.py -q
"""

from __future__ import annotations

import os

import pytest

ADMIN = os.getenv("SPE_PG_ADMIN_DSN")

pytestmark = [
    pytest.mark.needs_postgres,
    pytest.mark.skipif(not ADMIN, reason="set SPE_PG_ADMIN_DSN to run"),
]

TA, TB = "spe_bill_a", "spe_bill_b"

INSERT_SQL = (
    "INSERT INTO billing.usage_events "
    "(tenant_id, session_id, channel, seq, turn_idx, component, purpose, provider, model, "
    " input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, "
    " audio_sec, wall_ms, units, exact, occurred_at) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18) "
    "ON CONFLICT ON CONSTRAINT usage_events_idem DO NOTHING"
)


def _row(tenant: str, session: str, seq: int, *, input_tokens: int = 100):
    from datetime import UTC, datetime

    return (
        tenant,
        session,
        "chat",
        seq,
        0,
        "llm",
        "conversation",
        "anthropic",
        "claude-x",
        input_tokens,
        10,
        0,
        900,
        0.0,
        0.0,
        1,
        True,
        datetime.now(UTC),
    )


@pytest.fixture
async def conns():
    """Tenant-role connections, hoặc skip khi bảng của Portal chưa có."""
    import asyncpg

    from noble_agent.tenant import pg_provisioning as PG

    try:
        admin = await asyncpg.connect(ADMIN)
    except Exception as exc:  # noqa: BLE001 — DSN đặt sẵn nhưng PG không tới được
        pytest.skip(f"SPE_PG_ADMIN_DSN không kết nối được: {exc!r}")
    try:
        exists = await admin.fetchval("SELECT to_regclass('billing.usage_events') IS NOT NULL")
    finally:
        await admin.close()
    if not exists:
        pytest.skip("billing.usage_events chưa tồn tại — Portal chưa ship (contract §11)")

    def _tenant_dsn(role: str, pw: str) -> str:
        scheme, tail = ADMIN.split("://", 1)[0], ADMIN.split("@", 1)[1]
        return f"{scheme}://{role}:{pw}@{tail}"

    await PG.apply_schema(ADMIN)
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)
    await PG.provision(ADMIN, TA, "pw_a")
    await PG.provision(ADMIN, TB, "pw_b")

    # Policy của bảng billing là `TO agent_all`, và GRANT INSERT/SELECT cũng cấp cho
    # nhóm đó — role per-tenant do `provision` tạo KHÔNG tự là member, nên thiếu bước
    # này thì mọi INSERT dưới đây `42501` và 4 test hoá thành test của GRANT chứ không
    # phải test của idempotency/RLS. Trên DB thật, provisioning của Portal lo việc này.
    admin = await asyncpg.connect(ADMIN)
    try:
        for role in (TA, TB):
            await admin.execute(f'GRANT agent_all TO "{role}"')
    finally:
        await admin.close()

    a = await asyncpg.connect(_tenant_dsn(TA, "pw_a"))
    b = await asyncpg.connect(_tenant_dsn(TB, "pw_b"))
    try:
        yield a, b
    finally:
        await a.close()
        await b.close()
        await PG.deprovision(ADMIN, TA)
        await PG.deprovision(ADMIN, TB)


async def _scoped(conn, tenant: str):
    """SET LOCAL app.tenant_id giống `storage/postgres_client.py::tenant_conn`."""
    tx = conn.transaction()
    await tx.start()
    await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
    await conn.execute("SELECT set_config('app.current_tenant', $1, true)", tenant)
    return tx


async def test_idem_constraint_exists_on_exactly_seven_columns(conns):
    """Cơ chế retry của agent dựa hoàn toàn vào ràng buộc này (contract §4)."""
    import asyncpg

    admin = await asyncpg.connect(ADMIN)
    try:
        cols = await admin.fetch(
            """
            SELECT a.attname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
            WHERE c.conname = 'usage_events_idem'
              AND n.nspname = 'billing' AND t.relname = 'usage_events'
            ORDER BY k.ord
            """
        )
    finally:
        await admin.close()
    assert [r["attname"] for r in cols] == [
        "tenant_id",
        "session_id",
        "seq",
        "component",
        "purpose",
        "provider",
        "model",
    ]


async def test_reinsert_same_seq_does_not_duplicate_the_row(conns):
    """Retry sau lỗi mạng KHÔNG được nhân đôi hoá đơn."""
    a, _b = conns
    tx = await _scoped(a, TA)
    try:
        await a.execute(INSERT_SQL, *_row(TA, "s-idem", 0))
        await a.execute(INSERT_SQL, *_row(TA, "s-idem", 0, input_tokens=999))
        n = await a.fetchval(
            "SELECT count(*) FROM billing.usage_events WHERE session_id = $1 AND seq = 0",
            "s-idem",
        )
        assert n == 1
    finally:
        await tx.rollback()


async def test_update_is_denied(conns):
    """Append-only do GRANT cưỡng chế, không do kỷ luật code (contract §0)."""
    a, _b = conns
    tx = await _scoped(a, TA)
    try:
        await a.execute(INSERT_SQL, *_row(TA, "s-upd", 0))
        with pytest.raises(Exception) as err:  # asyncpg.InsufficientPrivilegeError
            await a.execute("UPDATE billing.usage_events SET input_tokens = 0 WHERE session_id = $1", "s-upd")
        assert "permission denied" in str(err.value).lower()
    finally:
        await tx.rollback()


async def test_writing_another_tenants_id_is_blocked_by_with_check(conns):
    """Một bug phía agent không được ghi tiêu thụ của A vào sổ của B (§6)."""
    a, _b = conns
    tx = await _scoped(a, TA)
    try:
        with pytest.raises(Exception) as err:  # row-level security violation
            await a.execute(INSERT_SQL, *_row(TB, "s-cross", 0))
        assert "row-level security" in str(err.value).lower()
    finally:
        await tx.rollback()
