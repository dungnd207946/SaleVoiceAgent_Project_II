"""Đồ dùng chung cho test module ingest.

`api_pool` dùng role `portal_api` — ĐÚNG role production chạy, nên test chịu đúng
ràng buộc quyền và đúng RLS FORCE. Fixture `pool` của repo là `portal_migrator`
(superuser trong container test), và superuser BỎ QUA RLS bất kể FORCE — một cổng
cách ly chạy bằng nó là cổng không bao giờ đỏ.
"""

import pytest

from tests.conftest import dsn_as

TENANT_A = "ing_a"
TENANT_B = "ing_b"


@pytest.fixture
def moi_truong(monkeypatch, pg_dsn: str):
    from tests.conftest import API_PASSWORD

    monkeypatch.setenv("DATABASE_URL", dsn_as(pg_dsn, "portal_api", API_PASSWORD))


@pytest.fixture
async def api_pool(moi_truong, api_dsn: str):
    from portal.core.db.pool import create_pool

    p = await create_pool(api_dsn, min_size=1, max_size=4)
    yield p
    await p.close()


@pytest.fixture
async def hai_tenant(pool):
    """Hai workspace sạch. Seed bằng `pool` (owner) vì phải ghi cho CẢ HAI.

    ⚠ DỌN Ở ĐẦU mỗi test, không phải ở cuối. `pg_dsn` là fixture scope session —
    một container Postgres cho cả lượt chạy — nên bản ghi của test trước tích luỹ,
    và mọi assert đếm số sẽ xanh hay đỏ TUỲ THỨ TỰ CHẠY. Đó là loại test tệ nhất:
    đỏ ở CI, xanh khi chạy một mình.
    """
    from portal.core.db.session import tenant_conn

    await pool.execute(
        "DELETE FROM control.ingest_tokens WHERE tenant_id = ANY($1::text[])",
        [TENANT_A, TENANT_B],
    )
    # ⚠️ Nhật ký cũng phải dọn, và nó nằm ở `control` nên không đi cùng vòng
    # `tenant_conn` bên dưới. Cảnh báo «tenant im lặng» chỉ ghi MỘT LẦN mỗi đợt
    # (`jobs._da_bao`), nên một dòng sót lại từ test trước làm test sau đọc ra
    # «đã báo rồi» và không ghi gì — đỏ ở một assert trông chẳng liên quan, và
    # chỉ đỏ tuỳ THỨ TỰ CHẠY. Chỉ xoá hành động của module này, không quét sạch
    # bảng: test module khác có thể đang dựa vào dòng của chúng.
    await pool.execute(
        "DELETE FROM control.audit_log WHERE tenant_id = ANY($1::text[]) AND hanh_dong LIKE 'ingest.%'",
        [TENANT_A, TENANT_B],
    )
    # Test purge của cổng nạp enqueue job THẬT vào `control.jobs` (kind='kb_delete').
    # Không dọn thì `tests/modules/test_worker.py` chạy SAU trong cùng session sẽ
    # nhặt nhầm job cũ toàn cục (`run_once()` không phân biệt tenant) và đỏ TUỲ
    # THỨ TỰ CHẠY — đúng lớp lỗi mà `control.jobs` không nằm trong vòng dọn tenant_data
    # bên dưới từng bỏ sót.
    await pool.execute(
        "DELETE FROM control.jobs WHERE tenant_id = ANY($1::text[])",
        [TENANT_A, TENANT_B],
    )
    # `created_by` thay cho `org_id` từ migration 0106 (develop bỏ tầng tổ chức
    # 2026-08-15) — cùng khuôn với conftest của `kb` và `enrollment`.
    for tid, ten in ((TENANT_A, "Ingest A"), (TENANT_B, "Ingest B")):
        await pool.execute(
            """INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, 'u_seed_test')
               ON CONFLICT (id) DO UPDATE SET lifecycle = 'active'""",
            tid,
            ten,
        )
        async with tenant_conn(pool, tid) as conn:
            # Thứ tự XOÁ theo chiều phụ thuộc: `units` trỏ `zones` trỏ `projects`.
            for bang in (
                "ingest_manifest_runs",
                "ingest_errors",
                "ingest_records",
                "units",
                "zones",
                "media",
                "documents",
                "projects",
            ):
                await conn.execute(f"DELETE FROM tenant_data.{bang} WHERE tenant_id = $1", tid)  # noqa: S608
    return TENANT_A, TENANT_B
