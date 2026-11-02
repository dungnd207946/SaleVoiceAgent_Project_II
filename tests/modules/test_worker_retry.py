"""Retry theo loại việc và thu hồi việc kẹt `running`.

Hai thứ này tồn tại vì chỉ báo mới của tab kiến thức suy "đang nạp" từ đúng những hàng
`queued|running`. Không có chúng thì một việc bị giết giữa đường (deploy gửi SIGTERM trong
lúc handler đang chặn) làm dấu quay "Đang nạp kiến thức cho agent" XOAY VĨNH VIỄN, và người
dùng không có nút nào bấm — nút Thử lại chỉ hiện ở nhánh lỗi.
"""

import asyncpg
import pytest

from portal.core.db.session import tenant_conn
from portal.core.jobs import enqueue, register, retries_of, run_once, thu_hoi_viec_ket

pytestmark = pytest.mark.integration


@pytest.fixture
async def api_pool(api_dsn):
    """Pool runtime (`portal_api`) — worker thật nối bằng đúng role này, không phải owner.
    Cùng khuôn `api_pool_jobs` ở `test_worker.py`."""
    from portal.core.db.pool import create_pool

    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


@pytest.fixture
async def TENANT(pool):
    """Tenant riêng cho file này: `control.jobs` có FK tới `control.tenants`."""
    ten = "jt_retry"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, 'RetryTenant', 'u_seed_test') "
            "ON CONFLICT (id) DO NOTHING",
            ten,
        )
    yield ten
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM control.tenants WHERE id = $1", ten)


async def _hang(pool, tenant: str, job_id: int) -> asyncpg.Record:
    async with tenant_conn(pool, tenant) as conn:
        return await conn.fetchrow(
            "SELECT state, attempts, run_after, message, started_at FROM control.jobs WHERE id = $1", job_id
        )


async def _xep(pool, tenant: str, kind: str) -> int:
    async with tenant_conn(pool, tenant) as conn:
        return await enqueue(conn, tenant_id=tenant, kind=kind, actor="test", payload={})


# ── khai báo retry ───────────────────────────────────────────────────────────


def test_mac_dinh_khong_retry():
    """Loại việc NGOÀI phạm vi KB (xuất bản cấu hình agent) chạy đúng một lượt từ trước tới
    giờ. Bật retry cho nó là đổi hành vi của một đường không ai yêu cầu."""
    assert retries_of("kind_chua_dang_ky_bao_gio") == 0
    assert retries_of("publish") == 0


def test_moi_loai_viec_kb_deu_co_retry():
    import portal.modules.kb.jobs  # noqa: F401 — import để register() chạy
    from portal.modules.kb.contracts import RETRY_VIEC_KB

    for kind in ("kb_index", "kb_delete", "kb_enrich", "kb_sync_project", "kb_caption_preview"):
        assert retries_of(kind) == RETRY_VIEC_KB, kind


def test_retries_am_thi_no():
    with pytest.raises(ValueError, match="retries âm"):
        register("kind_retries_am", lambda conn, payload: None, retries=-1)


# ── retry khi handler nổ ─────────────────────────────────────────────────────


async def test_hai_luot_dau_xep_lai_luot_ba_that_bai(api_pool, TENANT):
    so_lan = {"n": 0}

    async def _no(conn, payload):
        so_lan["n"] += 1
        raise RuntimeError("hỏng")

    register("test_no_ba_lan", _no, retries=2)
    job_id = await _xep(api_pool, TENANT, "test_no_ba_lan")

    # Lượt 1 → xếp lại, `run_after` đẩy về tương lai nên lượt sau KHÔNG nhặt được ngay.
    await run_once(api_pool)
    r = await _hang(api_pool, TENANT, job_id)
    assert (r["state"], r["attempts"]) == ("queued", 1)
    assert r["started_at"] is None, "xếp lại phải xoá started_at, không thì thu hồi tính sai tuổi"
    assert "hỏng" in r["message"]
    assert await run_once(api_pool) is None, "việc chưa tới lúc chạy mà vẫn bị nhặt"

    # Kéo `run_after` về quá khứ để không phải chờ 30 giây thật.
    for luot in (2, 3):
        async with tenant_conn(api_pool, TENANT) as conn:
            await conn.execute("UPDATE control.jobs SET run_after = now() - interval '1 min' WHERE id = $1", job_id)
        await run_once(api_pool)
        r = await _hang(api_pool, TENANT, job_id)
        if luot < 3:
            assert (r["state"], r["attempts"]) == ("queued", luot)

    assert r["state"] == "failed", "hết lượt phải thành failed, không được xếp lại mãi"
    assert so_lan["n"] == 3, f"chạy {so_lan['n']} lượt, phải là 3 (1 lần đầu + 2 lượt thử lại)"


async def test_loai_viec_khong_khai_retry_that_bai_ngay(api_pool, TENANT):
    async def _no(conn, payload):
        raise RuntimeError("hỏng")

    register("test_no_mot_lan", _no)
    job_id = await _xep(api_pool, TENANT, "test_no_mot_lan")
    await run_once(api_pool)
    r = await _hang(api_pool, TENANT, job_id)
    assert (r["state"], r["attempts"]) == ("failed", 0)


async def test_thanh_cong_khong_xep_lai(api_pool, TENANT):
    from portal.core.jobs import JobResult

    async def _ok(conn, payload):
        return JobResult(count=1, message="xong")

    register("test_ok", _ok, retries=2)
    job_id = await _xep(api_pool, TENANT, "test_ok")
    await run_once(api_pool)
    r = await _hang(api_pool, TENANT, job_id)
    assert r["state"] == "success"


# ── thu hồi việc kẹt ─────────────────────────────────────────────────────────


async def _dat_running_cu(pool, tenant: str, job_id: int, phut: int) -> None:
    async with tenant_conn(pool, tenant) as conn:
        await conn.execute(
            "UPDATE control.jobs SET state = 'running', started_at = now() - make_interval(mins => $2) WHERE id = $1",
            job_id,
            phut,
        )


async def test_viec_ket_con_luot_thi_ve_queued(api_pool, TENANT):
    """Đây là ca chính: tiến trình bị giết giữa việc, hàng nằm `running` và KHÔNG AI DỌN.

    Khung nhìn `control.jobs_stuck` đã liệt kê việc treo từ migration 0006 nhưng không có gì
    đọc nó — đó là lý do việc kẹt sống mãi.
    """

    async def _ok(conn, payload):
        from portal.core.jobs import JobResult

        return JobResult()

    register("test_ket", _ok, retries=2)
    job_id = await _xep(api_pool, TENANT, "test_ket")
    await _dat_running_cu(api_pool, TENANT, job_id, 20)

    da_thu_hoi = await thu_hoi_viec_ket(api_pool)
    assert job_id in da_thu_hoi
    r = await _hang(api_pool, TENANT, job_id)
    assert (r["state"], r["attempts"]) == ("queued", 1)
    assert "thu hồi" in r["message"]


async def test_viec_ket_het_luot_thi_that_bai(api_pool, TENANT):
    async def _ok(conn, payload):
        from portal.core.jobs import JobResult

        return JobResult()

    register("test_ket_het", _ok, retries=0)
    job_id = await _xep(api_pool, TENANT, "test_ket_het")
    await _dat_running_cu(api_pool, TENANT, job_id, 20)

    await thu_hoi_viec_ket(api_pool)
    r = await _hang(api_pool, TENANT, job_id)
    assert r["state"] == "failed", "hết lượt mà vẫn về queued là thu hồi vô hạn"


async def test_viec_running_CHUA_qua_han_khong_bi_thu_hoi(api_pool, TENANT):
    """Phép đo phải phân biệt "treo" với "đang chạy bình thường" — không thì thu hồi sẽ giật
    việc khỏi một worker đang làm, và hai worker cùng chạy một việc."""

    async def _ok(conn, payload):
        from portal.core.jobs import JobResult

        return JobResult()

    register("test_dang_chay", _ok, retries=2)
    job_id = await _xep(api_pool, TENANT, "test_dang_chay")
    await _dat_running_cu(api_pool, TENANT, job_id, 1)

    assert job_id not in await thu_hoi_viec_ket(api_pool)
    assert (await _hang(api_pool, TENANT, job_id))["state"] == "running"


async def test_nguong_ket_mac_dinh_15_phut(api_pool, TENANT):
    async def _ok(conn, payload):
        from portal.core.jobs import JobResult

        return JobResult()

    register("test_ket_mac_dinh", _ok, retries=2)
    job_id = await _xep(api_pool, TENANT, "test_ket_mac_dinh")
    await _dat_running_cu(api_pool, TENANT, job_id, 16)
    assert job_id in await thu_hoi_viec_ket(api_pool)
    assert "15 phút" in (await _hang(api_pool, TENANT, job_id))["message"]


async def test_viec_web_chay_dai_khong_bi_thu_hoi_truoc_120_phut(api_pool, TENANT):
    """Lượt dựng hồ sơ web chạy hàng chục phút; thu hồi ở 15 phút là chạy song song hai lần cùng dự án."""
    import portal.modules.kb.web.jobs  # noqa: F401 — đăng ký kbweb_project
    from portal.modules.kb.web.contracts import KIND_PROJECT

    dang_chay = await _xep(api_pool, TENANT, KIND_PROJECT)
    await _dat_running_cu(api_pool, TENANT, dang_chay, 30)
    treo = await _xep(api_pool, TENANT, KIND_PROJECT)
    await _dat_running_cu(api_pool, TENANT, treo, 130)

    da_thu_hoi = await thu_hoi_viec_ket(api_pool)
    assert dang_chay not in da_thu_hoi
    assert treo in da_thu_hoi
    assert (await _hang(api_pool, TENANT, dang_chay))["state"] == "running"
    r = await _hang(api_pool, TENANT, treo)
    assert r["state"] == "queued" and "120 phút" in r["message"]


def test_nguong_ket_phai_duong():
    with pytest.raises(ValueError):
        register("test_nguong_am", lambda c, p: None, stuck_minutes=0)


async def test_thu_hoi_khong_cham_loai_viec_la(api_pool, TENANT):
    """Một `kind` lạ trong bảng (di sản, hoặc module chưa nạp) không được đụng tới: ta không
    biết luật retry của nó, và đoán là đoán sai."""
    job_id = await _xep(api_pool, TENANT, "kind_la_khong_dang_ky")
    await _dat_running_cu(api_pool, TENANT, job_id, 60)
    await thu_hoi_viec_ket(api_pool)
    assert (await _hang(api_pool, TENANT, job_id))["state"] == "running"


# ── kind chưa có handler ở bản đang chạy ─────────────────────────────────────


async def test_kind_la_thi_xep_lai_cho_ban_moi_chu_khong_giet_ngay(api_pool, TENANT):
    """Deploy chạy `migrate` TRƯỚC `up -d`, nên migration xếp việc cho kind mà worker CŨ
    chưa biết. Giết ngay là mất việc trước khi bản mới lên — 37 job `kb_thumb` chết đúng
    kiểu đó trên dev 2026-08-17, và không gì xếp lại chúng."""
    job_id = await _xep(api_pool, TENANT, "kind_khong_ai_dang_ky")
    assert await run_once(api_pool) == job_id

    h = await _hang(api_pool, TENANT, job_id)
    assert h["state"] == "queued", "kind lạ phải chờ bản mới, không phải failed"
    assert h["attempts"] == 1
    assert h["run_after"] > h["started_at"] if h["started_at"] else True


async def test_kind_la_mai_thi_cuoi_cung_van_that_bai(api_pool, TENANT):
    """Không có trần thì một kind gõ sai nằm trong hàng đợi mãi mãi và chỉ báo quay mãi."""
    from portal.core.jobs import LUOT_CHO_HANDLER

    job_id = await _xep(api_pool, TENANT, "kind_go_sai_that")
    for _ in range(LUOT_CHO_HANDLER + 1):
        async with tenant_conn(api_pool, TENANT) as conn:
            await conn.execute("UPDATE control.jobs SET run_after = now() WHERE id = $1", job_id)
        await run_once(api_pool)

    h = await _hang(api_pool, TENANT, job_id)
    assert h["state"] == "failed"
    assert "không có handler" in h["message"]
