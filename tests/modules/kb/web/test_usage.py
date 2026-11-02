"""Chi phí dữ liệu ngoài: bộ đếm theo job, bậc giá Qwen, ghi sổ và định giá ngay lúc ghi."""

from decimal import Decimal

import pytest

from portal.core import jobs as core_jobs
from portal.core.jobs import JobRef, JobResult
from portal.modules.kb.web import usage
from portal.modules.kb.web.usage import UsageMeter, metered, qwen_model

from .conftest import OTHER, TENANT

pytestmark = pytest.mark.integration


def test_bac_gia_qwen_theo_token_vao_tung_luot():
    assert qwen_model("qwen3.7-flash", 32_000) == "qwen3.7-flash"
    assert qwen_model("qwen3.7-flash", 32_001) == "qwen3.7-flash>32k"
    assert qwen_model("qwen3.7-flash", 256_001) == "qwen3.7-flash>256k"


def test_bo_dem_cong_don_theo_khoa():
    m = UsageMeter()
    m.llm("dashscope", "qwen3.7-flash", 100, 10)
    m.llm("dashscope", "qwen3.7-flash", 50, 5)
    m.search("gemini-2.5-flash")
    m.search("gemini-2.5-flash")
    m.embed(["abc", "de"])
    assert m.tallies[("llm", "dashscope", "qwen3.7-flash")].input_tokens == 150
    assert m.tallies[("llm", "dashscope", "qwen3.7-flash")].output_tokens == 15
    assert m.tallies[("search", "google", "gemini-2.5-flash")].units == 2
    assert m.tallies[("embed", "santa-models", "multilingual-e5-large")].text_units == 5


@pytest.fixture
async def clean_usage(pool, web_tenant):
    await pool.execute("DELETE FROM billing.usage_events WHERE tenant_id = ANY($1::text[])", [TENANT, OTHER])
    yield
    await pool.execute("DELETE FROM billing.usage_events WHERE tenant_id = ANY($1::text[])", [TENANT, OTHER])


async def _rated(pool, session_id):
    return await pool.fetch(
        """SELECT e.component, e.model, e.seq, e.channel, e.purpose, r.metric, r.amount
             FROM billing.usage_events e JOIN billing.rated_usage r USING (event_id)
            WHERE e.session_id = $1 ORDER BY e.component, e.model, r.metric""",
        session_id,
    )


async def test_flush_ghi_so_va_dinh_gia_bang_gia_rieng(web_pool, pool, clean_usage):
    m = UsageMeter()
    m.llm("dashscope", "qwen3.7-flash", 1_000_000, 1_000_000)
    for _ in range(620):
        m.search("gemini-2.5-flash")
    await usage.flush(web_pool, TENANT, m, session_id="kbweb:1", seq=0)
    rows = {(r["component"], r["metric"]): r for r in await _rated(pool, "kbweb:1")}
    assert rows[("search", "units")]["amount"] == Decimal("225680")
    assert rows[("llm", "input_tokens")]["amount"] == Decimal("780")
    assert rows[("llm", "output_tokens")]["amount"] == Decimal("3380")
    assert {(r["channel"], r["purpose"]) for r in rows.values()} == {("kb_web", "kb_web")}


async def test_llm_hoi_thoai_van_gia_chung(pool, clean_usage):
    await pool.execute(
        """INSERT INTO billing.usage_events (tenant_id, session_id, channel, seq, component, purpose,
                                               provider, model, input_tokens, output_tokens)
           VALUES ($1, 's-hoi-thoai', 'chat', 0, 'llm', 'conversation', 'dashscope', 'qwen3.7-flash',
                   1000000, 1000000)""",
        TENANT,
    )
    rows = {r["metric"]: r["amount"] for r in await _rated(pool, "s-hoi-thoai")}
    assert rows == {"input_tokens": Decimal("19500"), "output_tokens": Decimal("97500")}


async def test_flush_lai_cung_seq_khong_ghi_trung(web_pool, pool, clean_usage):
    m = UsageMeter()
    m.search("gemini-2.5-flash")
    await usage.flush(web_pool, TENANT, m, session_id="kbweb:2", seq=0)
    await usage.flush(web_pool, TENANT, m, session_id="kbweb:2", seq=0)
    await usage.flush(web_pool, TENANT, m, session_id="kbweb:2", seq=1)
    n = await pool.fetchval("SELECT count(*) FROM billing.usage_events WHERE session_id = 'kbweb:2'")
    assert n == 2


async def test_portal_api_khong_ghi_duoc_cho_tenant_khac(web_pool, pool, clean_usage):
    from asyncpg.exceptions import InsufficientPrivilegeError

    from portal.core.db.session import tenant_conn

    async with tenant_conn(web_pool, TENANT) as conn:
        with pytest.raises(InsufficientPrivilegeError):
            await conn.execute(
                """INSERT INTO billing.usage_events (tenant_id, session_id, channel, seq, component)
                   VALUES ($1, 'x', 'kb_web', 0, 'search')""",
                OTHER,
            )


async def test_metered_ghi_so_ca_khi_job_loi(web_pool, pool, clean_usage):
    async def hong(conn, payload):
        usage.meter().search("gemini-2.5-flash")
        raise RuntimeError("hỏng giữa chừng")

    from portal.core.db.session import tenant_conn

    token = core_jobs._CURRENT_JOB.set(JobRef(id=77, attempt=1, pool=web_pool))
    try:
        async with tenant_conn(web_pool, TENANT) as conn:
            with pytest.raises(RuntimeError):
                await metered(hong)(conn, {})
    finally:
        core_jobs._CURRENT_JOB.reset(token)
    rows = await _rated(pool, "kbweb:77")
    assert [(r["component"], r["seq"]) for r in rows] == [("search", 1)]


async def test_metered_khong_co_luot_goi_thi_khong_ghi(web_pool, pool, clean_usage):
    async def rong(conn, payload):
        return JobResult(0, "")

    from portal.core.db.session import tenant_conn

    token = core_jobs._CURRENT_JOB.set(JobRef(id=78, attempt=0, pool=web_pool))
    try:
        async with tenant_conn(web_pool, TENANT) as conn:
            await metered(rong)(conn, {})
    finally:
        core_jobs._CURRENT_JOB.reset(token)
    assert await pool.fetchval("SELECT count(*) FROM billing.usage_events WHERE session_id = 'kbweb:78'") == 0
