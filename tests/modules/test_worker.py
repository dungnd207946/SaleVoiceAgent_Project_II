"""Worker + handler registry. Cơ chế làm module sau thêm loại job mà không sửa file của M1."""

import asyncio

import pytest

from portal.core.db.session import tenant_conn
from portal.core.jobs import JobResult, enqueue, register, run_once

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _giu_nguyen_so_handler():
    """_HANDLERS là dict cấp module, sống suốt tiến trình pytest.

    Test đăng ký một kind rồi để đó thì test/module sau dùng lại một kind chung
    ("cham", "hong") sẽ kế thừa handler cũ và pass/fail vì lý do khác. Chế độ hỏng
    này im lặng theo thiết kế, nên chặn ở đây thay vì để ai đó truy sau.
    """
    from portal.core import jobs

    truoc = dict(jobs._HANDLERS)
    yield
    jobs._HANDLERS.clear()
    jobs._HANDLERS.update(truoc)


@pytest.fixture
async def tenant(pool):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ('jt', 'JobTenant', 'u_seed_test')"
        )
    yield "jt"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("DELETE FROM control.tenants WHERE id = 'jt'")


@pytest.fixture
async def api_pool_jobs(api_dsn):
    """Pool runtime (portal_api) — worker thật nối bằng đúng role này, không phải owner."""
    from portal.core.db.pool import create_pool

    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


async def test_kind_moi_khong_can_migration(tenant, api_pool_jobs):
    """kind là text tự do — module sau thêm loại job không cần đổi schema."""
    seen: list[dict] = []

    async def handle(conn, payload):
        seen.append(payload)
        return JobResult(count=len(payload), message="xong")

    register("kind_hoan_toan_moi", handle)

    async with tenant_conn(api_pool_jobs, tenant) as conn:
        job_id = await enqueue(conn, tenant_id=tenant, kind="kind_hoan_toan_moi", actor="test", payload={"a": 1})

    assert await run_once(api_pool_jobs) == job_id
    assert seen == [{"a": 1}]

    async with tenant_conn(api_pool_jobs, tenant) as conn:
        row = await conn.fetchrow("SELECT state, count, message FROM control.jobs WHERE id = $1", job_id)
    assert row["state"] == "success"
    assert row["count"] == 1
    assert row["message"] == "xong"


async def test_handler_chay_trong_tenant_conn_nen_bi_rls(tenant, api_pool_jobs):
    """Handler thấy đúng tenant của job — không phải thấy tất cả."""
    got: list[str | None] = []

    async def handle(conn, payload):
        got.append(await conn.fetchval("SELECT portal.current_tenant()"))
        return JobResult(count=0, message="")

    register("kiem_tenant", handle)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        await enqueue(conn, tenant_id=tenant, kind="kiem_tenant", actor="test", payload={})
    await run_once(api_pool_jobs)
    assert got == [tenant]


async def test_handler_nem_loi_thi_job_failed_khong_retry(tenant, api_pool_jobs):
    async def handle(conn, payload):
        raise RuntimeError("cố tình vỡ")

    register("hong", handle)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        job_id = await enqueue(conn, tenant_id=tenant, kind="hong", actor="test", payload={})

    assert await run_once(api_pool_jobs) == job_id
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        row = await conn.fetchrow("SELECT state, message FROM control.jobs WHERE id = $1", job_id)
    assert row["state"] == "failed"
    assert "cố tình vỡ" in row["message"]

    assert await run_once(api_pool_jobs) is None, "job failed bị nhặt lại — mặc định KHÔNG retry"


async def test_kind_khong_co_handler_thi_cho_ban_moi(tenant, api_pool_jobs):
    """LẬT hành vi cũ (failed ngay). Kind lạ nghĩa là bản đang chạy chưa biết nó, mà deploy
    chạy `migrate` trước `up -d` — xem `test_worker_retry.py` cho cả hai đầu của luật."""
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        job_id = await enqueue(conn, tenant_id=tenant, kind="khong_ai_khai", actor="t", payload={})
    assert await run_once(api_pool_jobs) == job_id
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        row = await conn.fetchrow("SELECT state, message FROM control.jobs WHERE id = $1", job_id)
    assert row["state"] == "queued"
    assert "chưa có handler" in row["message"]


async def test_job_da_nhan_khong_bi_nhat_lai(tenant, api_pool_jobs):
    """Job đã được nhận thì lượt run_once sau không nhặt lại.

    Cơ chế ở đây là CHUYỂN TRẠNG THÁI, không phải SKIP LOCKED: run_once() commit
    state='running' TRƯỚC khi handler chạy, nên vị từ WHERE state='queued' một mình
    đã đủ loại job đó. SKIP LOCKED được canh riêng ở test dưới.
    """
    started = asyncio.Event()
    release = asyncio.Event()
    lan_chay = 0

    async def handle(conn, payload):
        nonlocal lan_chay
        lan_chay += 1
        started.set()
        await release.wait()
        return JobResult(count=0, message="")

    register("cham", handle)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        await enqueue(conn, tenant_id=tenant, kind="cham", actor="t", payload={})

    task = asyncio.create_task(run_once(api_pool_jobs))
    await asyncio.wait_for(started.wait(), timeout=5)
    assert await run_once(api_pool_jobs) is None, "worker thứ hai nhặt trùng job"
    release.set()
    await task
    assert lan_chay == 1


async def test_skip_locked_khong_cho_hai_worker_tranh_cung_mot_job(tenant, api_pool_jobs):
    """SKIP LOCKED: claimant thứ hai BỎ QUA hàng đang bị khoá, KHÔNG chờ.

    Đây là thứ làm chạy nhiều worker song song thành an toàn mà không tắc. Không có
    nó thì claimant thứ hai chặn ở khoá cho tới khi txn thứ nhất xong — nhiều worker
    thành hàng đợi tuần tự, và một handler chậm giữ khoá là mọi worker khác đứng im.

    TEST CHẠY ĐÚNG CÂU SQL CỦA PRODUCTION, không phải một bản sao.
    Bản trước tự khai lại câu claim thành string literal ngay trong file này. Hệ quả:
    nó chứng minh Postgres có SKIP LOCKED, chứ KHÔNG chứng minh run_once() dùng
    SKIP LOCKED — xoá hai từ đó khỏi jobs.py thì cả bộ test vẫn xanh. Nên ở đây
    import thẳng `_CAU_NHAT_JOB` (hằng số mà run_once() dùng) và chạy chính nó: bỏ
    SKIP LOCKED khỏi production là test này đỏ, ở đúng dòng asyncio.wait_for.
    """
    from portal.core.jobs import _CAU_NHAT_JOB

    async with tenant_conn(api_pool_jobs, tenant) as conn:
        job_id = await enqueue(conn, tenant_id=tenant, kind="tranh_khoa", actor="t", payload={})

    # Kết nối A giữ khoá, KHÔNG commit.
    async with api_pool_jobs.acquire() as ca, ca.transaction():
        await ca.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
        row_a = await ca.fetchrow(_CAU_NHAT_JOB)
        assert row_a is not None and row_a["id"] == job_id

        # Kết nối B chạy đúng câu đó: phải trả RỖNG NGAY, không chờ khoá.
        # asyncio.wait_for là cố ý: KHÔNG có SKIP LOCKED thì lệnh này CHẶN (chờ khoá
        # của A giải phóng), nên timeout biến "nó bị chặn" thành FAIL thay vì treo test.
        async with api_pool_jobs.acquire() as cb, cb.transaction():
            await cb.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
            got = await asyncio.wait_for(cb.fetchrow(_CAU_NHAT_JOB), timeout=3)
        assert got is None, "claimant thứ hai không bỏ qua hàng đang khoá"


async def test_enqueue_tu_choi_xep_job_cho_tenant_khac(tenant, api_pool_jobs):
    """control.jobs KHÔNG có RLS, nên chỉ Python chặn được đường chéo-tenant này.

    Không có guard, `enqueue(conn, tenant_id="tenant_khac", ...)` từ trong giao dịch
    của `tenant` THÀNH CÔNG, và worker về sau chạy job đó bằng ngữ cảnh của tenant kia.
    """
    with pytest.raises(RuntimeError, match="tenant hiệu lực"):
        async with tenant_conn(api_pool_jobs, tenant) as conn:
            await enqueue(conn, tenant_id="tenant_khac", kind="xau", actor="t", payload={})

    # Và KHÔNG có hàng nào lọt vào hàng đợi cho tenant kia. Kiểm cả chuyện này vì
    # "ném lỗi" mà vẫn ghi được hàng thì guard chỉ là trang trí.
    async with api_pool_jobs.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM control.jobs WHERE tenant_id = 'tenant_khac'") == 0

    # Đường bình thường vẫn chạy: guard chặn cái sai, không chặn cái đúng.
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        job_id = await enqueue(conn, tenant_id=tenant, kind="tot", actor="t", payload={})
        assert await conn.fetchval("SELECT tenant_id FROM control.jobs WHERE id = $1", job_id) == tenant


async def test_enqueue_ngoai_tenant_conn_thi_no_ngay(api_pool_jobs):
    """Ngoài tenant_conn(), portal.current_tenant() là NULL — xếp job cho không ai.

    Fail closed: nổ ngay ở lời gọi, không ghi một hàng job mồ côi mà worker sẽ nhặt
    rồi chạy với tenant NULL.
    """
    async with api_pool_jobs.acquire() as conn:
        with pytest.raises(RuntimeError, match="không suy được tenant"):
            await enqueue(conn, tenant_id="bat_ky", kind="xau", actor="t", payload={})


async def test_khong_co_job_thi_tra_none(api_pool_jobs):
    assert await run_once(api_pool_jobs) is None


async def test_nhat_dung_kind_duoc_yeu_cau(tenant, api_pool_jobs):
    """Job cũ hơn thuộc kind khác KHÔNG được nhặt: không có vế này, một hàng đợi
    đầy caption chặn làn index dù làn đó rỗng."""
    ran: list[str] = []

    async def handle(conn, payload):
        ran.append(str(payload["ten"]))
        return JobResult(count=1)

    register("cu", handle)
    register("moi", handle)
    async with tenant_conn(api_pool_jobs, tenant) as conn:
        await enqueue(conn, tenant_id=tenant, kind="cu", actor="t", payload={"ten": "cu"})
        await enqueue(conn, tenant_id=tenant, kind="moi", actor="t", payload={"ten": "moi"})

    assert await run_once(api_pool_jobs, kinds=["moi"]) is not None
    assert ran == ["moi"]
