"""Worker dừng giữa việc (deploy) và worker chết (mất nhịp tim) — spec 2026-10-07-worker-tra-viec-khi-dung.

Đo trên dev 07/10: deploy thay `crawl-worker` lúc 10:06, ba lượt «Cập nhật mỗi đêm» bắt đầu 08:32 nằm `running`
tới 14:32 dù không tiến trình nào chạy chúng.
"""

import asyncio

import asyncpg
import pytest

from portal.core import jobs
from portal.core.db.session import tenant_conn
from portal.core.jobs import JobResult, enqueue, register, run_once, thu_hoi_viec_ket, tra_lai_viec_dang_giu
from portal.worker.__main__ import chay_toi_khi_dung

pytestmark = pytest.mark.integration


@pytest.fixture
async def api_pool(api_dsn):
    from portal.core.db.pool import create_pool

    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


@pytest.fixture
async def TENANT(pool):
    ten = "jt_dung"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, 'DungTenant', 'u_seed_test') "
            "ON CONFLICT (id) DO NOTHING",
            ten,
        )
    yield ten
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", ten)


async def _hang(pool, tenant: str, job_id: int) -> asyncpg.Record:
    async with tenant_conn(pool, tenant) as conn:
        return await conn.fetchrow(
            "SELECT state, attempts, started_at, heartbeat_at, message FROM control.jobs WHERE id = $1", job_id
        )


async def _xep(pool, tenant: str, kind: str) -> int:
    async with tenant_conn(pool, tenant) as conn:
        return await enqueue(conn, tenant_id=tenant, kind=kind, actor="test", payload={})


async def _dat_running(pool, tenant: str, job_id: int, *, bat_dau_phut: int, nhip_phut: int | None) -> None:
    async with tenant_conn(pool, tenant) as conn:
        await conn.execute(
            """UPDATE control.jobs SET state = 'running',
                      started_at = now() - make_interval(mins => $2),
                      heartbeat_at = CASE WHEN $3::int IS NULL THEN NULL ELSE now() - make_interval(mins => $3) END
                WHERE id = $1""",
            job_id,
            bat_dau_phut,
            nhip_phut,
        )


async def _ok(conn, payload):
    return JobResult()


def _cho_mai():
    """Handler chặn tới khi bị huỷ; `bat_dau` báo nó đã chạy."""
    bat_dau = asyncio.Event()

    async def handle(conn, payload):
        bat_dau.set()
        await asyncio.Event().wait()

    return handle, bat_dau


# ── dừng giữa việc ───────────────────────────────────────────────────────────


async def test_dung_giua_viec_thi_tra_ve_hang_doi_khong_mat_luot(api_pool, TENANT):
    handle, bat_dau = _cho_mai()
    register("test_dung_giua", handle, retries=0)
    job_id = await _xep(api_pool, TENANT, "test_dung_giua")

    dung = asyncio.Event()
    worker = asyncio.create_task(chay_toi_khi_dung(api_pool, [run_once(api_pool, kinds=["test_dung_giua"])], dung))
    await asyncio.wait_for(bat_dau.wait(), 5)
    dung.set()
    await asyncio.wait_for(worker, 10)

    r = await _hang(api_pool, TENANT, job_id)
    assert (r["state"], r["attempts"]) == ("queued", 0), "dừng do deploy không được tính là một lượt hỏng"
    assert r["started_at"] is None and r["heartbeat_at"] is None
    assert "worker dừng" in r["message"]


async def test_viec_da_xong_khong_bi_dua_lai_hang_doi(api_pool, TENANT):
    """Bị huỷ đúng lúc vừa ghi xong thì id còn trong sổ nhưng hàng đã `success` — giữ nguyên kết quả."""
    register("test_xong_roi", _ok)
    job_id = await _xep(api_pool, TENANT, "test_xong_roi")
    assert await run_once(api_pool, kinds=["test_xong_roi"]) == job_id

    jobs._DANG_GIU[job_id] = TENANT
    assert await tra_lai_viec_dang_giu(api_pool) == []
    assert (await _hang(api_pool, TENANT, job_id))["state"] == "success"


async def test_viec_chay_xong_thi_roi_so_dang_giu(api_pool, TENANT):
    register("test_roi_so", _ok)
    job_id = await _xep(api_pool, TENANT, "test_roi_so")
    await run_once(api_pool, kinds=["test_roi_so"])
    assert job_id not in jobs._DANG_GIU


async def test_mot_vong_chet_thi_worker_no_ra(api_pool):
    async def chet():
        raise RuntimeError("vòng chết")

    with pytest.raises(RuntimeError, match="vòng chết"):
        await asyncio.wait_for(chay_toi_khi_dung(api_pool, [chet()], asyncio.Event()), 10)


# ── nhịp tim ─────────────────────────────────────────────────────────────────


async def test_nhip_tim_duoc_ghi_trong_luc_chay(api_pool, TENANT, monkeypatch):
    monkeypatch.setattr(jobs, "NHIP_TIM_GIAY", 0.05)
    handle, bat_dau = _cho_mai()
    register("test_nhip", handle)
    job_id = await _xep(api_pool, TENANT, "test_nhip")

    chay = asyncio.create_task(run_once(api_pool, kinds=["test_nhip"]))
    await asyncio.wait_for(bat_dau.wait(), 5)
    await asyncio.sleep(0.3)
    r = await _hang(api_pool, TENANT, job_id)
    chay.cancel()
    await asyncio.gather(chay, return_exceptions=True)
    await tra_lai_viec_dang_giu(api_pool)

    assert r["heartbeat_at"] > r["started_at"], "nhịp tim không được ghi trong lúc handler chạy"


async def test_mat_nhip_tim_thi_thu_hoi_du_chua_toi_nguong_ket(api_pool, TENANT):
    """Worker chết (OOM, máy khởi động lại) — không chờ ngưỡng kẹt 6 giờ của loại việc chạy dài."""
    register("test_mat_nhip", _ok, retries=1, stuck_minutes=360)
    job_id = await _xep(api_pool, TENANT, "test_mat_nhip")
    await _dat_running(api_pool, TENANT, job_id, bat_dau_phut=20, nhip_phut=jobs.MAT_NHIP_PHUT + 1)

    assert job_id in await thu_hoi_viec_ket(api_pool)
    r = await _hang(api_pool, TENANT, job_id)
    assert (r["state"], r["attempts"]) == ("queued", 1), "chết đột ngột phải tính lượt, không thì nhặt lại vô hạn"
    assert "mất nhịp tim" in r["message"] and r["heartbeat_at"] is None


async def test_mat_nhip_tim_het_luot_thi_that_bai(api_pool, TENANT):
    register("test_mat_nhip_het", _ok, retries=0, stuck_minutes=360)
    job_id = await _xep(api_pool, TENANT, "test_mat_nhip_het")
    await _dat_running(api_pool, TENANT, job_id, bat_dau_phut=20, nhip_phut=jobs.MAT_NHIP_PHUT + 1)

    await thu_hoi_viec_ket(api_pool)
    assert (await _hang(api_pool, TENANT, job_id))["state"] == "failed"


async def test_nhip_tim_con_moi_thi_khong_thu_hoi(api_pool, TENANT):
    register("test_nhip_moi", _ok, retries=1, stuck_minutes=360)
    job_id = await _xep(api_pool, TENANT, "test_nhip_moi")
    await _dat_running(api_pool, TENANT, job_id, bat_dau_phut=30, nhip_phut=0)

    assert job_id not in await thu_hoi_viec_ket(api_pool)
    assert (await _hang(api_pool, TENANT, job_id))["state"] == "running"


async def test_khong_co_nhip_tim_thi_chi_theo_nguong_ket(api_pool, TENANT):
    """`heartbeat_at` NULL = việc nhận bởi bản worker cũ: không suy ra nó đã chết."""
    register("test_ban_cu", _ok, retries=1, stuck_minutes=360)
    job_id = await _xep(api_pool, TENANT, "test_ban_cu")
    await _dat_running(api_pool, TENANT, job_id, bat_dau_phut=30, nhip_phut=None)

    assert job_id not in await thu_hoi_viec_ket(api_pool)
    assert (await _hang(api_pool, TENANT, job_id))["state"] == "running"
