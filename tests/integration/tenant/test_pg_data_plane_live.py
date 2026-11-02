"""SP-E2 live write-path proof: the 3 DAOs write/read under the tenant role + RLS.

Requires ``SPE_PG_ADMIN_DSN`` (skipped otherwise). Proves each DAO round-trips for
its own tenant AND that a second tenant, using the same DAO on its own role
connection, sees NONE of the first tenant's rows (RLS isolation is inherent to the
write path, not a filter the DAO applies).

    SPE_PG_ADMIN_DSN=postgresql://sp_admin:sp_admin_pw@localhost:5432/odyssey \
      pytest tests/integration/tenant/test_pg_data_plane_live.py -q
"""

from __future__ import annotations

import os

import pytest

from noble_agent.storage import pg_data_plane as DP
from noble_agent.tenant import pg_provisioning as PG

ADMIN = os.getenv("SPE_PG_ADMIN_DSN")
pytestmark = [
    pytest.mark.needs_postgres,
    pytest.mark.skipif(not ADMIN, reason="set SPE_PG_ADMIN_DSN to run"),
]

TA, TB = "spe_dao_a", "spe_dao_b"


def _tenant_dsn(admin: str, role: str, pw: str) -> str:
    scheme, tail = admin.split("://", 1)[0], admin.split("@", 1)[1]
    return f"{scheme}://{role}:{pw}@{tail}"


@pytest.fixture
async def conns():
    import asyncpg

    await PG.apply_schema(ADMIN)
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)
    await PG.provision(ADMIN, TA, "pw_a")
    await PG.provision(ADMIN, TB, "pw_b")
    a = await asyncpg.connect(_tenant_dsn(ADMIN, TA, "pw_a"))
    b = await asyncpg.connect(_tenant_dsn(ADMIN, TB, "pw_b"))
    yield a, b
    await a.close()
    await b.close()
    await PG.deprovision(ADMIN, TA)
    await PG.deprovision(ADMIN, TB)


async def test_contacts_roundtrip_and_isolation(conns):
    a, b = conns
    await DP.upsert_contact(a, tenant_id=TA, phone="0900000001", snapshot="likes district 2")
    await DP.upsert_contact(a, tenant_id=TA, phone="0900000001", snapshot="updated: likes district 7")  # upsert
    got = await DP.get_contact(a, tenant_id=TA, phone="0900000001")
    assert got["snapshot"] == "updated: likes district 7"
    # tenant B, same DAO on its own role conn, sees nothing of A's
    assert await DP.get_contact(b, tenant_id=TB, phone="0900000001") is None


async def test_conversation_upsert_with_skill_calls(conns):
    a, _ = conns
    cid = await DP.record_conversation(
        a,
        tenant_id=TA,
        session_id="sess-1",
        phone="0900000002",
        customer_name="Anh Ba",
        project="VRI",
        transferred_to_sales=True,
        running_version=7,
        summary="quan tâm 2PN",
        skill_calls=[{"name": "find_project", "args": {"q": "royal island"}, "result": "VRI"}],
    )
    assert cid is not None
    # upsert on (tenant, session): a second partial write updates, no dup row
    await DP.record_conversation(
        a, tenant_id=TA, session_id="sess-1", summary="chốt đặt lịch", transferred_to_sales=True
    )
    n = await a.fetchval("SELECT count(*) FROM tenant_data.conversations WHERE session_id = 'sess-1'")
    assert n == 1
    row = await a.fetchrow(
        "SELECT summary, running_version, skill_calls FROM tenant_data.conversations WHERE session_id = 'sess-1'"
    )
    assert row["summary"] == "chốt đặt lịch" and row["running_version"] == 7
    assert "find_project" in row["skill_calls"]  # jsonb preserved across the upsert


async def test_appointments_upsert_update_and_isolation(conns):
    a, b = conns
    aid = await DP.upsert_appointment(
        a, tenant_id=TA, appointment_id="APT00001", session_id="sess-1",
        customer_name="Chị Tư", phone="0900000003",
        project_code="VOP2", preferred_date="2026-08-01", preferred_time="15:00",
    )
    assert aid is not None
    # re-book (modify) with the same appointment_id upserts the SAME row, no dup
    aid2 = await DP.upsert_appointment(
        a, tenant_id=TA, appointment_id="APT00001", preferred_time="16:00", status="confirmed",
    )
    assert aid2 == aid
    assert await a.fetchval("SELECT count(*) FROM tenant_data.appointments") == 1
    row = await a.fetchrow("SELECT preferred_time, project_code FROM tenant_data.appointments WHERE id = $1", aid)
    assert row["preferred_time"] == "16:00"  # updated
    assert row["project_code"] == "VOP2"  # COALESCE preserved on partial upsert
    hint = await DP.get_latest_appointment_by_phone(a, tenant_id=TA, phone="0900000003")
    assert hint == {"customer_name": "Chị Tư", "project_code": "VOP2"}
    assert await DP.update_appointment_status(a, tenant_id=TA, appointment_id=aid, status="done") is True
    # updating a non-existent id → False (no row)
    assert await DP.update_appointment_status(a, tenant_id=TA, appointment_id=999999, status="x") is False
    # B cannot see A's appointment (RLS)
    assert await b.fetchval("SELECT count(*) FROM tenant_data.appointments") == 0


async def test_contact_profile_and_snapshot_coexist(conns):
    import json

    a, b = conns
    # snapshot upsert then profile upsert land on the SAME (tenant, phone) row,
    # neither clobbering the other's column.
    await DP.upsert_contact(a, tenant_id=TA, phone="0900000009", snapshot="likes VRI")
    await DP.upsert_contact_profile(
        a, tenant_id=TA, phone="0900000009", profile={"budget": "3 tỷ"}, insert_default={"name": "No Name"}
    )
    # partial profile update merges (jsonb ||), does not wipe budget, and never
    # re-applies the insert-only default over a real later name.
    await DP.upsert_contact_profile(
        a, tenant_id=TA, phone="0900000009", profile={"name": "Chị Năm"}, insert_default={}
    )
    row = await DP.get_contact(a, tenant_id=TA, phone="0900000009")
    assert row["snapshot"] == "likes VRI"  # profile upserts left snapshot intact
    profile = json.loads(row["profile"]) if isinstance(row["profile"], str) else row["profile"]
    assert profile == {"budget": "3 tỷ", "name": "Chị Năm"}  # merged, No Name overwritten by real name
    # B sees none of A's contact (RLS)
    assert await DP.get_contact(b, tenant_id=TB, phone="0900000009") is None


async def test_escalations_roundtrip_and_isolation(conns):
    a, b = conns
    eid = await DP.insert_escalation(
        a, tenant_id=TA, session_id="sess-esc", phone="0900000011",
        customer_name="Anh Sáu", project="SGI", missing_data_tool="search_units",
        summary="Khách: Anh Sáu, SĐT: 0900000011. Lý do chuyển: hết dữ liệu.", message_seq=7,
    )
    assert eid is not None
    row = await a.fetchrow("SELECT status, summary_at FROM tenant_data.escalations WHERE id = $1", eid)
    assert row["status"] == "new" and row["summary_at"] is None  # bản tạm, Portal chưa đụng

    await DP.update_escalation_summary(a, tenant_id=TA, escalation_id=eid, summary="Khách cần tra tồn kho 3PN.")
    row = await a.fetchrow("SELECT summary, summary_at FROM tenant_data.escalations WHERE id = $1", eid)
    assert row["summary"].startswith("Khách cần tra") and row["summary_at"] is not None

    assert await DP.has_escalation(a, tenant_id=TA, session_id="sess-esc") is True
    assert await DP.has_escalation(a, tenant_id=TA, session_id="khac") is False
    # B dùng cùng DAO trên role của nó: không thấy dòng nào của A
    assert await DP.has_escalation(b, tenant_id=TB, session_id="sess-esc") is False
    assert await b.fetchval("SELECT count(*) FROM tenant_data.escalations") == 0


async def test_apply_schema_regrant_phuc_hoi_quyen_bang_moi(conns):
    """`GRANT ON ALL TABLES` là ảnh chụp — role có trước bảng mới thì không có quyền,
    và wrapper nuốt lỗi nên mất dòng im lặng. Block re-GRANT phải vá được."""
    import asyncpg

    a, _ = conns
    admin = await asyncpg.connect(ADMIN)
    try:
        await admin.execute(f'REVOKE ALL ON tenant_data.escalations FROM "{TA}"')
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await DP.insert_escalation(a, tenant_id=TA, session_id="s", summary="x")
        await PG.apply_schema(ADMIN)  # chạy lại DDL = chạy block re-GRANT
        assert await DP.insert_escalation(a, tenant_id=TA, session_id="s", summary="x") is not None
    finally:
        await admin.close()


async def test_conversation_list_by_phone_newest_first(conns):
    a, _ = conns
    from datetime import UTC, datetime

    await DP.record_conversation(
        a, tenant_id=TA, session_id="c-old", phone="0900000010",
        ended_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    await DP.record_conversation(
        a, tenant_id=TA, session_id="c-new", phone="0900000010",
        ended_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    rows = await DP.list_conversations_by_phone(a, tenant_id=TA, phone="0900000010", limit=5)
    assert [r["session_id"] for r in rows] == ["c-new", "c-old"]
