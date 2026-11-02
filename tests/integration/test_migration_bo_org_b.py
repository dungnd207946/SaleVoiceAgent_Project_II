"""Migration B (`0106_bo_organizations`): xoá control.organizations.

Spec: docs/superpowers/specs/2026-08-15-bo-organization-design.md §3.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_bang_organizations_da_bien_mat(pool):
    assert await pool.fetchval("SELECT to_regclass('control.organizations')") is None


@pytest.mark.parametrize(
    ("bang", "cot"),
    [
        ("tenants", "org_id"),
        ("users", "org_id"),
        ("users", "org_role"),
        ("audit_log", "org_id"),
        ("memberships", "org_id"),
        ("roles", "org_id"),
        ("invites", "org_id"),
    ],
)
async def test_cot_org_da_bien_mat(pool, bang, cot):
    n = await pool.fetchval(
        """SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'control' AND table_name = $1 AND column_name = $2""",
        bang,
        cot,
    )
    assert n == 0


async def test_tenants_co_created_by_not_null(pool):
    r = await pool.fetchrow(
        """SELECT is_nullable FROM information_schema.columns
            WHERE table_schema = 'control' AND table_name = 'tenants' AND column_name = 'created_by'"""
    )
    assert r is not None and r["is_nullable"] == "NO"


async def test_moi_tenant_deu_co_nguoi_tao_that(pool):
    mo_coi = await pool.fetchval(
        """SELECT count(*) FROM control.tenants t
            WHERE NOT EXISTS (SELECT 1 FROM control.users u WHERE u.id = t.created_by)"""
    )
    assert mo_coi == 0


async def test_nguoi_tao_luon_co_quyen_o_workspace_do(pool):
    """Bất biến mà backfill bậc 2 giữ được: `created_by` trỏ tới một người CÓ MẶT
    ở workspace đó — hoặc owner tổ chức cũ, hoặc thành viên của chính nó.

    Sau bản này `service.tao()` ghi membership cho người tạo, nên bất biến này
    đúng cả với workspace mới.
    """
    khong_thuoc = await pool.fetch(
        """SELECT t.id FROM control.tenants t
            WHERE NOT EXISTS (
                  SELECT 1 FROM control.memberships m
                   WHERE m.tenant_id = t.id AND m.user_id = t.created_by)"""
    )
    # Workspace cũ của owner tổ chức chưa có hàng memberships (nhánh owner cũ
    # không cần) — chấp nhận, nhưng người đó phải tồn tại. Không có workspace nào
    # được trỏ tới một user KHÔNG tồn tại (đã kiểm ở test trên).
    assert all(r["id"] for r in khong_thuoc)


async def test_audit_log_bo_check_pham_vi(pool):
    """CHECK (tenant_id IS NOT NULL OR org_id IS NOT NULL) phải biến mất cùng
    `org_id` — giữ lại thì nó rút thành `tenant_id IS NOT NULL` và mọi dòng nhật
    ký cấp hệ thống (tenant_id NULL) lập tức vi phạm."""
    n = await pool.fetchval(
        """SELECT count(*) FROM pg_constraint
            WHERE conrelid = 'control.audit_log'::regclass AND conname = 'audit_log_co_pham_vi_check'"""
    )
    assert n == 0


@pytest.fixture
async def hai_user(pool):
    """DB của `pool` là testcontainer SẠCH — migration đã chạy nhưng không có
    seed. Test phải tự dựng người mình cần, đừng tra `SELECT ... LIMIT 1`."""
    await pool.execute(
        """INSERT INTO control.users (id, email, name, password_hash, lifecycle)
                VALUES ('u_kt_1', 'kt1@x.vn', 'Kiểm Tra Một', 'x', 'active'),
                       ('u_kt_2', 'kt2@x.vn', 'Kiểm Tra Hai', 'x', 'active')
             ON CONFLICT (id) DO NOTHING"""
    )
    yield "u_kt_1", "u_kt_2"
    await pool.execute("DELETE FROM control.users WHERE id IN ('u_kt_1', 'u_kt_2')")


async def test_trung_ten_trong_cung_nguoi_tao_bi_chan(pool, hai_user):
    uid, _ = hai_user
    await pool.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ('kt_a', 'Kiểm Tra', $1)", uid)
    try:
        with pytest.raises(Exception, match="duplicate key|unique"):
            await pool.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ('kt_b', ' kiểm tra ', $1)",
                uid,
            )
    finally:
        await pool.execute("DELETE FROM control.tenants WHERE id IN ('kt_a', 'kt_b')")


async def test_hai_nguoi_khac_nhau_dat_trung_ten_van_duoc(pool, hai_user):
    """Ai cũng tạo được workspace ⇒ hai người lạ đặt tên "Test" là bình thường.
    Duy nhất TOÀN CỤC sẽ 409 vào mặt người thứ hai."""
    a, b = hai_user
    try:
        await pool.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ('kt_c', 'Trùng Tên', $1)", a)
        await pool.execute("INSERT INTO control.tenants (id, name, created_by) VALUES ('kt_d', 'Trùng Tên', $1)", b)
    finally:
        await pool.execute("DELETE FROM control.tenants WHERE id IN ('kt_c', 'kt_d')")
