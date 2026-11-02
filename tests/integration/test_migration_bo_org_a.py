"""Migration A (`0105_roles_thoat_org`): control.roles thoát khỏi organization.

Đo trên DB thật ở HEAD. Spec: docs/superpowers/specs/2026-08-15-bo-organization-design.md §3.
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_roles_khong_con_cot_org_id(pool):
    n = await pool.fetchval(
        """SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'control' AND table_name = 'roles' AND column_name = 'org_id'"""
    )
    assert n == 0


async def test_invites_khong_con_cot_org_id(pool):
    n = await pool.fetchval(
        """SELECT count(*) FROM information_schema.columns
            WHERE table_schema = 'control' AND table_name = 'invites' AND column_name = 'org_id'"""
    )
    assert n == 0


async def test_roles_unique_theo_name(pool):
    ten = await pool.fetchval(
        """SELECT c.conname FROM pg_constraint c
            WHERE c.conrelid = 'control.roles'::regclass AND c.contype = 'u'
              AND pg_get_constraintdef(c.oid) = 'UNIQUE (name)'"""
    )
    assert ten is not None


async def test_bon_vai_tro_mau_con_dung_mot_ban(pool):
    """dev_seed dựng HAI tổ chức ⇒ 8 hàng, 4 cặp trùng tên. Dedup phải đã chạy."""
    hang = await pool.fetch("SELECT name, count(*) AS n FROM control.roles GROUP BY name")
    assert {r["name"] for r in hang} == {"Quản trị", "CSKH", "Biên tập", "Người xem"}
    assert all(r["n"] == 1 for r in hang), "dedup chưa chạy: còn vai trò trùng tên"


@pytest.mark.parametrize(
    ("conname", "mong_doi"),
    [
        ("memberships_role_id_fkey", "FOREIGN KEY (role_id) REFERENCES control.roles(id) ON DELETE RESTRICT"),
        ("memberships_tenant_id_fkey", "FOREIGN KEY (tenant_id) REFERENCES control.tenants(id) ON DELETE CASCADE"),
        ("memberships_user_id_fkey", "FOREIGN KEY (user_id) REFERENCES control.users(id) ON DELETE CASCADE"),
    ],
)
async def test_memberships_fk_don_cot(pool, conname, mong_doi):
    """BA FK ghép, không phải một — bỏ sót thì DROP COLUMN org_id ở migration B nổ.

    FK vai trò giữ ON DELETE RESTRICT: xoá vai trò đang có người giữ bị chặn ở
    tầng DB, làm lưới thứ hai sau `dem_nguoi_dung_vai_tro()`.
    """
    dinh_nghia = await pool.fetchval("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = $1", conname)
    assert dinh_nghia == mong_doi


async def test_khong_con_fk_ghep_nao_tren_memberships(pool):
    ghep = await pool.fetch(
        """SELECT conname FROM pg_constraint
            WHERE conrelid = 'control.memberships'::regclass AND contype = 'f'
              AND pg_get_constraintdef(oid) LIKE '%org_id%'"""
    )
    assert ghep == []


async def test_trigger_seed_theo_org_da_bien_mat(pool):
    assert await pool.fetchval("SELECT to_regproc('control.seed_vai_tro_mau(text)')") is None


async def test_moi_membership_van_tro_toi_mot_vai_tro_that(pool):
    mo_coi = await pool.fetchval(
        """SELECT count(*) FROM control.memberships m
            WHERE NOT EXISTS (SELECT 1 FROM control.roles r WHERE r.id = m.role_id)"""
    )
    assert mo_coi == 0
