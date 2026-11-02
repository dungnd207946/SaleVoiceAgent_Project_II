import pytest


@pytest.mark.anyio
async def test_invites_co_cot_tenant_id_nullable(pool):
    r = await pool.fetchrow(
        """SELECT is_nullable, data_type FROM information_schema.columns
            WHERE table_schema='control' AND table_name='invites' AND column_name='tenant_id'"""
    )
    assert r is not None, "chưa chạy migration invites.tenant_id"
    assert r["is_nullable"] == "YES", "NULL = token tự đăng ký; NOT NULL khoá chết luồng đó"
    assert r["data_type"] == "text"


@pytest.mark.anyio
async def test_xoa_workspace_thi_loi_moi_vao_no_cung_rung(pool):
    """ON DELETE CASCADE: lời mời vào một workspace đã xoá không còn nghĩa gì."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle) VALUES ('u_cas','cas@x.vn','Cas','pending')"
        )
        await conn.execute("""INSERT INTO control.tenants (id, name, created_by) VALUES ('t_cas','Cas WS','u_cas')""")
        # CHECK invites_vai_tro_theo_pham_vi (0952): tenant_id NOT NULL đòi role_id
        # NOT NULL đi kèm — một lời mời vào workspace luôn hứa một vai trò.
        r_id = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        await conn.execute(
            """INSERT INTO control.invites (token_hash, user_id, email, tenant_id, role_id, expires_at, created_by)
               VALUES (repeat('a',64), 'u_cas', 'cas@x.vn', 't_cas', $1, now() + interval '7 day', 'u_cas')""",
            r_id,
        )
        await conn.execute("DELETE FROM control.tenants WHERE id = 't_cas'")
        con = await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_cas'")
        assert con == 0
        await conn.execute("DELETE FROM control.users WHERE id = 'u_cas'")
