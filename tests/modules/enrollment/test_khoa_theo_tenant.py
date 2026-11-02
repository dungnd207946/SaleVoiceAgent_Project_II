"""Khoá treo THẲNG vào tenant — `agent_keys.deployment_id` đã bỏ (`0940`).

Trước `0940`, tenant của một khoá suy qua `JOIN control.deployments`. Mô hình mà
tầng trung gian đó phục vụ ("1 tenant → N pod, mỗi pod bộ khoá riêng") đã rỗng
nghĩa từ `0917` (xoá `agent_api`, mất view `tenant_keys`) và `0919` (bỏ cột
`kind`, một khoá dùng chung cho cả chat lẫn voice).

CỔNG THẬT Ở ĐÂY là bài `khoa_cua_A_khong_lot_sang_B`: bỏ JOIN nghĩa là bỏ luôn
`WHERE d.tenant_id = $1` — nếu ai đó viết lại câu SELECT mà quên `WHERE`, mọi
bài khác trong file này vẫn xanh.
"""

import asyncpg
import pytest

from portal.modules.enrollment import contracts, repo

_BOI = "u_seed_test"


async def _them(pool, tenant_id: str, sha: str, label: str = "") -> int:
    return await repo.them_khoa(pool, tenant_id, sha, f"raw-{sha}", sha[:8], label, _BOI)


# ─── Hình dạng bảng ──────────────────────────────────────────────────────────


async def test_agent_keys_treo_vao_tenant_chu_khong_vao_deployment(pool):
    cot = {
        r["column_name"]: r["is_nullable"]
        for r in await pool.fetch(
            """SELECT column_name, is_nullable FROM information_schema.columns
                WHERE table_schema = 'control' AND table_name = 'agent_keys'"""
        )
    }
    assert cot.get("tenant_id") == "NO", "tenant_id phải tồn tại và NOT NULL"
    assert "deployment_id" not in cot


async def test_xoa_tenant_van_keo_theo_khoa(pool, hai_tenant):
    """`ON DELETE CASCADE` giữ đúng ngữ nghĩa cũ. Trước `0940` chuỗi cascade đi
    hai chặng (tenant → deployment → khoá); giờ một chặng. Mất nó là để lại khoá
    mồ côi trỏ vào workspace không còn tồn tại."""
    await pool.execute(
        "INSERT INTO control.tenants (id, name, created_by) VALUES ('akxoa', 'Xoá thử', $1)",
        _BOI,
    )
    await _them(pool, "akxoa", "sha-cascade")
    await pool.execute("DELETE FROM control.tenants WHERE id = 'akxoa'")

    assert await pool.fetchval("SELECT count(*) FROM control.agent_keys WHERE key_sha256 = 'sha-cascade'") == 0


async def test_tenant_khong_ton_tai_thi_khong_chen_duoc_khoa(pool, hai_tenant):
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await _them(pool, "ak_khong_co_that", "sha-fk")


# ─── Đường tra khoá ──────────────────────────────────────────────────────────


async def test_tra_khoa_ra_dung_tenant(pool, hai_tenant):
    """Tenant đến TỪ CHÍNH hàng khoá.

    Bản `0940` của bài này còn khẳng định `count(*) FROM control.deployments = 0` để
    chứng minh tenant không thể đến từ đường JOIN cũ. `0941` bỏ hẳn bảng đó, nên phép
    khẳng định ấy hết ý nghĩa — không còn nguồn thứ hai nào để loại trừ.
    """
    a, _ = hai_tenant
    key_id = await _them(pool, a, "sha-tra")

    khoa = await repo.tra_khoa(pool, "sha-tra")
    assert khoa is not None
    assert khoa.tenant_id == a
    assert khoa.key_id == key_id


async def test_tra_khoa_da_thu_hoi_van_tra_None(pool, hai_tenant):
    a, _ = hai_tenant
    key_id = await _them(pool, a, "sha-thu-hoi")
    await repo.thu_hoi_khoa(pool, key_id)

    assert await repo.tra_khoa(pool, "sha-thu-hoi") is None


async def test_tenant_cua_khoa_khong_can_deployment(pool, hai_tenant):
    a, _ = hai_tenant
    key_id = await _them(pool, a, "sha-chu")

    assert await repo.tenant_cua_khoa(pool, key_id) == a


# ─── Cách ly ─────────────────────────────────────────────────────────────────


async def test_khoa_cua_A_khong_lot_sang_B(pool, hai_tenant):
    a, b = hai_tenant
    await _them(pool, a, "sha-cua-a", label="cua-a")
    await _them(pool, b, "sha-cua-b", label="cua-b")

    nhan_a = {k["label"] for k in await repo.liet_ke_khoa_cua_tenant(pool, a)}
    nhan_b = {k["label"] for k in await repo.liet_ke_khoa_cua_tenant(pool, b)}

    assert "cua-a" in nhan_a, "phải thấy khoá của chính mình — nếu không, cổng này vô nghĩa"
    assert "cua-b" in nhan_b
    assert "cua-b" not in nhan_a
    assert "cua-a" not in nhan_b


# ─── Contract: `deployment_id` biến mất khỏi response ────────────────────────


def test_runtime_credentials_khong_con_deployment_id():
    """Agent nhận `deployment_id` là `int | None` ở mọi chỗ và không assert nó có
    giá trị (`gateway/credentials.py:60`, `chat_proxy.py:32`), nên bỏ field này
    không làm pod vỡ — chỉ làm heartbeat ngừng ghi. Đánh đổi đã chốt; xem spec
    `docs/superpowers/specs/2026-08-19-agent-keys-tenant-id-design.md`."""
    assert "deployment_id" not in contracts.RuntimeCredentialsOut.model_fields
    assert "tenant_id" in contracts.RuntimeCredentialsOut.model_fields


def test_khoa_moi_out_khong_con_deployment_id():
    assert "deployment_id" not in contracts.KhoaMoiOut.model_fields
