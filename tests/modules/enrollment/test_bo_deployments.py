"""`control.deployments` đã bỏ hẳn — khái niệm "pod" không còn trong lược đồ (`0941`).

`0940` đã cắt `agent_keys` khỏi bảng đó. Còn lại đúng hai người dùng: `agent_heartbeats`
(FK + nửa khoá chính) và màn liệt kê của admin nền tảng. Đợt này dọn cả hai.

CỔNG THẬT của file: `test_heartbeat_mot_hang_moi_tenant`. Bỏ `deployment_id` khỏi khoá
chính nghĩa là hai pod của cùng một tenant nay ĐÈ lên nhau thay vì nằm hai hàng — đó là
thay đổi ngữ nghĩa, không phải dọn dẹp, và nó phải được khẳng định chứ không suy ra.
"""

import asyncpg
import pytest

from portal.modules.enrollment import contracts

_BOI = "u_seed_test"


async def _cot(pool, bang: str) -> set[str]:
    return {
        r["column_name"]
        for r in await pool.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'control' AND table_name = $1",
            bang,
        )
    }


# ─── Lược đồ ─────────────────────────────────────────────────────────────────


async def test_bang_deployments_khong_con_ton_tai(pool):
    con = await pool.fetchval(
        "SELECT to_regclass('control.deployments') IS NOT NULL",
    )
    assert con is False


async def test_agent_heartbeats_khoa_theo_tenant(pool):
    assert "deployment_id" not in await _cot(pool, "agent_heartbeats")

    khoa = await pool.fetch(
        """
        SELECT a.attname
          FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
         WHERE i.indrelid = 'control.agent_heartbeats'::regclass AND i.indisprimary
        """
    )
    assert {r["attname"] for r in khoa} == {"tenant_id"}


# ─── Ngữ nghĩa mới của nhịp tim ──────────────────────────────────────────────


async def test_heartbeat_mot_hang_moi_tenant(pool, hai_tenant):
    """Hai lượt beat của CÙNG tenant đè lên nhau, không nằm hai hàng.

    Trước `0941` hai pod (`chat`/`voice`) có `deployment_id` khác nhau ⇒ hai hàng, và
    `config/repo.lay_heartbeat` lấy hàng `last_seen_at` mới nhất. Giờ đúng một hàng —
    cùng kết quả cho người đọc, nhưng bảng không còn phân biệt được pod nào.
    """
    a, _ = hai_tenant
    for ver in (1, 2):
        await pool.execute(
            """INSERT INTO control.agent_heartbeats (tenant_id, running_version, agent_version)
               VALUES ($1, $2, 'test')
               ON CONFLICT (tenant_id) DO UPDATE SET running_version = excluded.running_version,
                                                    last_seen_at = now()""",
            a,
            ver,
        )

    hang = await pool.fetch("SELECT running_version FROM control.agent_heartbeats WHERE tenant_id = $1", a)
    assert len(hang) == 1
    assert hang[0]["running_version"] == 2


async def test_heartbeat_van_can_tenant_co_that(pool, hai_tenant):
    """FK về `control.tenants` (từ `0007`) KHÔNG được rơi cùng FK về `deployments`."""
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await pool.execute(
            "INSERT INTO control.agent_heartbeats (tenant_id, agent_version) VALUES ('ak_khong_co', 'test')"
        )


# ─── Contract ────────────────────────────────────────────────────────────────


def test_khong_con_contract_nao_ten_deployment():
    assert not hasattr(contracts, "DeploymentIn")
    assert not hasattr(contracts, "DeploymentOut")


def test_tenant_van_hanh_out_khong_mang_id_pod():
    """Màn chẩn đoán giữ nguyên giá trị (`so_khoa_con_song`, `san_sang_du_lieu`), chỉ bỏ
    ba trường vốn thuộc về hàng deployment: `id`, `endpoint`, `provisioned_at`."""
    truong = set(contracts.TenantVanHanhOut.model_fields)
    assert {"tenant_id", "so_khoa_con_song", "san_sang_du_lieu"} <= truong
    assert truong.isdisjoint({"id", "endpoint", "provisioned_at", "deployment_id"})
