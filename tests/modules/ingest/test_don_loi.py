"""Dọn `ingest_errors` — §8 mục 4.

Bảng lỗi CHỈ LỚN LÊN nếu không ai dọn: mỗi bản ghi bị từ chối là một dòng, và một
adapter hỏng đẩy toàn payload sai sinh ra chúng ở nhịp tối đa.

Hai vế cắt, và bộ bài này canh đúng chỗ mỗi vế MỘT MÌNH thì hở.
"""

import pytest

from portal.core.db.session import tenant_conn
from portal.modules.ingest import fanout, jobs, repo

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _don_job(pool):
    xoa = "DELETE FROM control.jobs WHERE kind = ANY($1::text[])"
    kinds = [jobs.KIND_IM_LANG, jobs.KIND_DON_LOI]
    await pool.execute(xoa, kinds)
    yield
    await pool.execute(xoa, kinds)


async def _chen(api_pool, tenant_id: str, so: int, *, tuoi_ngay: int = 0) -> None:
    async with tenant_conn(api_pool, tenant_id) as conn:
        for i in range(so):
            await repo.ghi_loi(conn, tenant_id=tenant_id, entity="unit", external_id=f"U{i}", field="x", reason="sai")
    if tuoi_ngay:
        # `pool` không dùng được ở đây (fixture khác), nên lùi tuổi bằng chính
        # kết nối tenant — RLS vẫn áp, đúng như runtime.
        async with tenant_conn(api_pool, tenant_id) as conn:
            await conn.execute(
                "UPDATE tenant_data.ingest_errors SET received_at = now() - ($1 || ' days')::interval "
                "WHERE tenant_id = portal.current_tenant()",
                str(tuoi_ngay),
            )


async def _dem(api_pool, tenant_id: str) -> int:
    async with tenant_conn(api_pool, tenant_id) as conn:
        return await conn.fetchval("SELECT count(*) FROM tenant_data.ingest_errors WHERE tenant_id = $1", tenant_id)


async def _chay(api_pool, tenant_id: str):
    async with tenant_conn(api_pool, tenant_id) as conn:
        return await jobs.handle_don_loi(conn, {})


async def test_cat_theo_tuoi(api_pool, hai_tenant, monkeypatch):
    monkeypatch.setenv("INGEST_LOI_GIU_NGAY", "30")
    a, _ = hai_tenant
    await _chen(api_pool, a, 3, tuoi_ngay=40)
    await _chen(api_pool, a, 2)

    ra = await _chay(api_pool, a)
    assert ra.count == 3
    assert await _dem(api_pool, a) == 2, "dòng mới phải còn"


async def test_cat_theo_tran_dong_khi_dong_con_MOI(api_pool, hai_tenant, monkeypatch):
    """⚠️ Vế bắt buộc thứ hai: cắt theo tuổi MỘT MÌNH không chặn được đợt bùng.

    Adapter hỏng sinh hàng chục nghìn dòng trong một đêm; chúng đều mới tinh nên
    phép cắt theo tuổi không đụng tới, và chúng nằm đó trọn kỳ lưu.
    """
    monkeypatch.setenv("INGEST_LOI_GIU_NGAY", "30")
    monkeypatch.setenv("INGEST_LOI_TRAN_HANG", "5")
    a, _ = hai_tenant
    await _chen(api_pool, a, 20)

    assert (await _chay(api_pool, a)).count == 15
    assert await _dem(api_pool, a) == 5


async def test_cat_theo_ID_chu_khong_theo_received_at(api_pool, hai_tenant, monkeypatch):
    """`received_at` mặc định `now()` = GIỜ GIAO DỊCH, nên cả một lô mang ĐÚNG một
    mốc. Cắt theo `min(received_at)` thì với một lô duy nhất, mốc nhỏ nhất chính là
    mốc của mọi dòng và phép cắt xoá được KHÔNG GÌ.

    `_chen` ghi 20 dòng trong MỘT `tenant_conn` ⇒ một giao dịch ⇒ một mốc. Bài này
    đỏ ngay nếu ai đó đổi `id` thành `received_at` cho «nhất quán».
    """
    monkeypatch.setenv("INGEST_LOI_TRAN_HANG", "5")
    a, _ = hai_tenant
    await _chen(api_pool, a, 20)

    async with tenant_conn(api_pool, a) as conn:
        moc = await conn.fetch("SELECT DISTINCT received_at FROM tenant_data.ingest_errors WHERE tenant_id = $1", a)
    assert len(moc) == 1, "tiền đề của bài: cả lô cùng một mốc"

    assert (await _chay(api_pool, a)).count == 15


async def test_duoi_tran_thi_khong_xoa_gi(api_pool, hai_tenant, monkeypatch):
    """Một kênh dọn xoá nhầm là một kênh không ai dám bật."""
    monkeypatch.setenv("INGEST_LOI_TRAN_HANG", "100")
    monkeypatch.setenv("INGEST_LOI_GIU_NGAY", "30")
    a, _ = hai_tenant
    await _chen(api_pool, a, 4)

    ra = await _chay(api_pool, a)
    assert ra.count == 0
    assert "không có gì" in ra.message
    assert await _dem(api_pool, a) == 4


async def test_bang_rong_khong_no(api_pool, hai_tenant):
    """`min(id)` trên tập rỗng là NULL, và `id < NULL` không khớp gì — nhưng đó là
    thứ phải KIỂM, không phải thứ để suy."""
    a, _ = hai_tenant
    assert (await _chay(api_pool, a)).count == 0


async def test_don_cua_A_khong_dung_vao_B(api_pool, hai_tenant, monkeypatch):
    monkeypatch.setenv("INGEST_LOI_TRAN_HANG", "2")
    a, b = hai_tenant
    await _chen(api_pool, a, 10)
    await _chen(api_pool, b, 10)

    await _chay(api_pool, a)
    assert await _dem(api_pool, a) == 2
    assert await _dem(api_pool, b) == 10, "dọn của A không được chạm dữ liệu B"


async def test_fanout_xep_dung_kind(pool, hai_tenant):
    a, b = hai_tenant
    so = await fanout.xep_moi_tenant(pool, kind=jobs.KIND_DON_LOI)
    assert so >= 2

    tt = {
        r["tenant_id"]
        for r in await pool.fetch("SELECT tenant_id FROM control.jobs WHERE kind = $1", jobs.KIND_DON_LOI)
    }
    assert {a, b} <= tt
    assert await pool.fetchval("SELECT count(*) FROM control.jobs WHERE kind = $1", jobs.KIND_IM_LANG) == 0
