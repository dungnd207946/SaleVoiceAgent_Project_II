"""Migration thêm project_code — cột, CHECK mở rộng, và backfill từ 4 bảng nguồn."""

from portal.core.db.session import tenant_conn

TENANT = "mig_acme"


async def test_cot_project_code_ton_tai_va_state_nhan_skipped(pool):
    async with pool.acquire() as conn:
        cot = await conn.fetchval(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'tenant_data' AND table_name = 'kb_index_state' "
            "  AND column_name = 'project_code'"
        )
        assert cot == "text"

        rang_buoc = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'kb_index_state_state_check'"
        )
        assert "skipped" in rang_buoc


async def test_ghi_duoc_state_skipped(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $1, 'u_seed_test')", TENANT)
    try:
        async with tenant_conn(pool, TENANT) as conn:
            await conn.execute(
                "INSERT INTO tenant_data.projects (tenant_id, project_code, name, status) "
                "VALUES (portal.current_tenant(),'p1','Dự án 1','published')"
            )
            pid = await conn.fetchval("SELECT id FROM tenant_data.projects WHERE tenant_id = portal.current_tenant()")
            await conn.execute(
                "INSERT INTO tenant_data.kb_index_state "
                "  (tenant_id, entity, record_id, doc_type, target, state, project_code) "
                "VALUES (portal.current_tenant(), 'projects', $1, 'tong_quan', 'documents', 'skipped', 'p1')",
                pid,
            )
            state = await conn.fetchval(
                "SELECT state FROM tenant_data.kb_index_state WHERE tenant_id = portal.current_tenant()"
            )
        assert state == "skipped"
    finally:
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute("DELETE FROM control.tenants WHERE id = $1", TENANT)


async def test_index_theo_tenant_va_project_code_ton_tai(pool):
    """Badge lọc theo (tenant_id, project_code) trên mọi lần mở danh sách dự án."""
    async with pool.acquire() as conn:
        co = await conn.fetchval(
            "SELECT count(*) FROM pg_indexes "
            "WHERE schemaname = 'tenant_data' AND indexname = 'kb_index_state_tenant_project_idx'"
        )
    assert co == 1
