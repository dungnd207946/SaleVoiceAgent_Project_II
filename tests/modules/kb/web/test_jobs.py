import json
from contextlib import asynccontextmanager
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from portal.core.db.session import tenant_conn
from portal.core.jobs import JobResult, run_once
from portal.modules.kb.contracts import TemporaryError, enqueue_web_project
from portal.modules.kb.web import fanout, jobs, pipeline
from portal.modules.kb.web.compose import dossier_ids
from portal.modules.kb.web.contracts import KIND_PROJECT, KIND_RUN, MODE_INIT, MODE_NIGHTLY, MODE_REBUILD, MODE_WEEKLY
from portal.modules.kb.web.fanout import queue_projects
from portal.modules.kb.web.pipeline import Refreshed

from .conftest import NPTTL, OTHER, TENANT

pytestmark = pytest.mark.integration

_MONDAY = date(2026, 9, 28)


@pytest.fixture(autouse=True)
async def _no_leftover_web_jobs(pool):
    """Fan-out xếp việc cho MỌI tenant active trong DB test; job sót lại sẽ bị
    `tests/modules/test_worker.py` (run_once không lọc kind) nhặt nhầm."""
    await pool.execute("DELETE FROM control.jobs WHERE kind IN ($1, $2)", KIND_PROJECT, KIND_RUN)
    yield
    await pool.execute("DELETE FROM control.jobs WHERE kind IN ($1, $2)", KIND_PROJECT, KIND_RUN)


async def _jobs(pool, tenant):
    rows = await pool.fetch(
        "SELECT payload FROM control.jobs WHERE tenant_id = $1 AND kind = $2 ORDER BY id", tenant, KIND_PROJECT
    )
    return [json.loads(r["payload"]) if isinstance(r["payload"], str) else r["payload"] for r in rows]


async def _add_project(pool, tenant, code, name, status="published") -> int:
    async with tenant_conn(pool, tenant) as c:
        return await c.fetchval(
            """INSERT INTO tenant_data.projects (tenant_id, project_code, name, status)
               VALUES ($1, $2, $3, $4) RETURNING id""",
            tenant,
            code,
            name,
            status,
        )


async def _user_says(pool, tenant, content, *, session="s1", seq=0):
    async with tenant_conn(pool, tenant) as c:
        await c.execute(
            """INSERT INTO tenant_data.conversation_messages
                   (tenant_id, session_id, seq, role, content, created_at, meta)
               VALUES ($1, $2, $3, 'user', $4, now(), '{}'::jsonb)""",
            tenant,
            session,
            seq,
            content,
        )


# ─── enqueue ─────────────────────────────────────────────────────────────────


class _IndexCo:
    """Index giả: chỉ dự án trong `co` đã có hồ sơ."""

    def __init__(self, *co: str) -> None:
        self._first = {dossier_ids(n)[0] for n in co}

    async def get(self, ids):
        return ["mục"] if ids[0] in self._first else []


async def test_du_an_chua_co_ho_so_duoc_xep_init_du_chua_ai_hoi(web_tenant, api_pool, pool):
    await _add_project(api_pool, TENANT, "SRC", "Sunrise City")
    n = await fanout.queue_missing(api_pool, _IndexCo(NPTTL), tenant_id=TENANT)
    assert n == 1
    assert await _jobs(pool, TENANT) == [{"project_code": "SRC", "mode": MODE_INIT}]
    assert await fanout.queue_missing(api_pool, _IndexCo(NPTTL), tenant_id=TENANT) == 0, "gộp vào việc đang chờ"


async def test_xep_viec_va_gop_viec_trung(web_tenant, api_pool, pool):
    async with tenant_conn(api_pool, TENANT) as c:
        assert isinstance(await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL"), int)
        assert await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL") is None
    assert await _jobs(pool, TENANT) == [{"project_code": "NPTTL", "mode": MODE_INIT}]


async def test_khac_mode_thi_khong_gop(web_tenant, api_pool, pool):
    async with tenant_conn(api_pool, TENANT) as c:
        assert await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL") is not None
        assert (
            await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL", mode=MODE_NIGHTLY)
            is not None
        )
    assert [j["mode"] for j in await _jobs(pool, TENANT)] == [MODE_INIT, MODE_NIGHTLY]


async def test_viec_dang_chay_khong_chan_viec_moi(web_tenant, api_pool, pool):
    """Chỉ gộp với việc CÒN CHỜ: việc đang chạy có thể đã đọc dữ liệu cũ."""
    async with tenant_conn(api_pool, TENANT) as c:
        await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL")
    await pool.execute(
        "UPDATE control.jobs SET state = 'running' WHERE tenant_id = $1 AND kind = $2", TENANT, KIND_PROJECT
    )
    async with tenant_conn(api_pool, TENANT) as c:
        assert await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL") is not None
    assert len(await _jobs(pool, TENANT)) == 2


async def test_viec_dang_cho_thu_lai_khong_nuot_yeu_cau_moi(web_tenant, api_pool, pool):
    """Việc đang lùi sau lỗi (attempts > 0, run_after ở tương lai) không được hút yêu cầu mới."""
    async with tenant_conn(api_pool, TENANT) as c:
        await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL")
    await pool.execute(
        """UPDATE control.jobs SET attempts = 1, run_after = now() + interval '1 hour'
            WHERE tenant_id = $1 AND kind = $2""",
        TENANT,
        KIND_PROJECT,
    )
    async with tenant_conn(api_pool, TENANT) as c:
        assert await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL") is not None
        assert await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL") is None
    assert len(await _jobs(pool, TENANT)) == 2


async def test_gop_chi_trong_cung_tenant(web_tenant, api_pool, pool):
    for tid in (TENANT, OTHER):
        async with tenant_conn(api_pool, tid) as c:
            assert await enqueue_web_project(c, tenant_id=tid, actor="t", project_code="NPTTL") is not None
    assert len(await _jobs(pool, TENANT)) == 1
    assert len(await _jobs(pool, OTHER)) == 1


async def test_mode_sai_thi_nem_va_khong_ghi(web_tenant, api_pool, pool):
    async with tenant_conn(api_pool, TENANT) as c:
        with pytest.raises(ValueError):
            await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL", mode="x")
    assert await _jobs(pool, TENANT) == []


async def test_lech_tenant_thi_core_enqueue_nem(web_tenant, api_pool, pool):
    async with tenant_conn(api_pool, TENANT) as c:
        with pytest.raises(RuntimeError):
            await enqueue_web_project(c, tenant_id=OTHER, actor="t", project_code="NPTTL")
    assert await _jobs(pool, OTHER) == []


# ─── fan-out ─────────────────────────────────────────────────────────────────


async def test_fanout_dung_lai_moi_du_an_cho_tung_tenant(web_tenant, api_pool, pool):
    assert await queue_projects(api_pool, MODE_REBUILD) >= 2
    assert await _jobs(pool, TENANT) == [{"project_code": "NPTTL", "mode": MODE_REBUILD}]
    assert await _jobs(pool, OTHER) == [{"project_code": "NPTTL", "mode": MODE_REBUILD}]
    tenants = await pool.fetch(
        "SELECT DISTINCT tenant_id FROM control.jobs WHERE kind = $1 AND tenant_id = ANY($2::text[])",
        KIND_PROJECT,
        [TENANT, OTHER],
    )
    assert {r["tenant_id"] for r in tenants} == {TENANT, OTHER}


async def test_fanout_chay_lai_khong_xep_trung(web_tenant, api_pool, pool):
    await queue_projects(api_pool, MODE_REBUILD)
    await queue_projects(api_pool, MODE_REBUILD)
    assert len(await _jobs(pool, TENANT)) == 1


async def test_fanout_bo_du_an_nhap_va_tenant_khong_active(web_tenant, api_pool, pool):
    await _add_project(pool, TENANT, "DRAFT1", "Dự án Nháp Một", status="draft")
    await pool.execute("UPDATE control.tenants SET lifecycle = 'suspended' WHERE id = $1", OTHER)
    await queue_projects(api_pool, MODE_REBUILD)
    assert [j["project_code"] for j in await _jobs(pool, TENANT)] == ["NPTTL"]
    assert await _jobs(pool, OTHER) == []


async def test_fanout_mot_tenant_hong_van_xep_tenant_khac_roi_bao_loi(web_tenant, api_pool, pool, monkeypatch):
    real = fanout.load_projects

    async def flaky(conn):
        if await conn.fetchval("SELECT portal.current_tenant()") == TENANT:
            raise RuntimeError("hỏng")
        return await real(conn)

    monkeypatch.setattr(fanout, "load_projects", flaky)
    with pytest.raises(RuntimeError, match=TENANT):
        await queue_projects(api_pool, MODE_REBUILD)
    assert await _jobs(pool, TENANT) == []
    assert await _jobs(pool, OTHER) == [{"project_code": "NPTTL", "mode": MODE_REBUILD}]


async def test_dem_khong_log_thi_xep_moi_du_an(web_tenant, api_pool, pool):
    await _add_project(pool, TENANT, "VHSC", "Vinhomes Smart City")
    await queue_projects(api_pool, MODE_NIGHTLY)
    assert sorted(j["project_code"] for j in await _jobs(pool, TENANT)) == ["NPTTL", "VHSC"]
    assert all(j["mode"] == MODE_NIGHTLY for j in await _jobs(pool, TENANT))


async def test_dem_chi_xep_du_an_duoc_hoi(web_tenant, api_pool, pool):
    await _add_project(pool, TENANT, "VHSC", "Vinhomes Smart City")
    await _user_says(pool, TENANT, "cho mình hỏi giá vinhomes smart city")
    await queue_projects(api_pool, MODE_NIGHTLY)
    assert await _jobs(pool, TENANT) == [{"project_code": "VHSC", "mode": MODE_NIGHTLY}]
    assert await _jobs(pool, OTHER) == [{"project_code": "NPTTL", "mode": MODE_NIGHTLY}]


def _day_with_slot(start: date, slot: int, slices: int) -> date:
    """Ngày >= `start` đầu tiên có `toordinal() % slices == slot`."""
    delta = (slot - start.toordinal()) % slices
    return start + timedelta(days=delta)


def _pin_slices(monkeypatch, n: int) -> None:
    monkeypatch.setattr(fanout, "get_env", lambda: SimpleNamespace(web_deep_slices=n))


async def test_tuan_chi_xep_lat_cat_id_mod_n_cua_hom_nay(web_tenant, api_pool, pool, monkeypatch):
    _pin_slices(monkeypatch, 7)
    async with tenant_conn(pool, TENANT) as c:
        base = await c.fetchval(
            "SELECT id FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = 'NPTTL'"
        )
    other_id = await _add_project(pool, TENANT, "VHSC", "Vinhomes Smart City")
    assert base % 7 != other_id % 7
    today = _day_with_slot(_MONDAY, other_id % 7, 7)
    assert today.toordinal() % 7 == other_id % 7
    await queue_projects(api_pool, MODE_WEEKLY, today=today)
    assert await _jobs(pool, TENANT) == [{"project_code": "VHSC", "mode": MODE_WEEKLY}]


async def test_tuan_van_loc_theo_tin_hieu_duoc_hoi(web_tenant, api_pool, pool, monkeypatch):
    _pin_slices(monkeypatch, 7)
    async with tenant_conn(pool, TENANT) as c:
        pid = await c.fetchval(
            "SELECT id FROM tenant_data.projects WHERE tenant_id = portal.current_tenant() AND project_code = 'NPTTL'"
        )
    await _user_says(pool, TENANT, "xin chào")
    today = _day_with_slot(_MONDAY, pid % 7, 7)
    await queue_projects(api_pool, MODE_WEEKLY, today=today)
    assert await _jobs(pool, TENANT) == []


async def test_tuan_2_lat_cat_phu_het_qua_2_ngay_lien_tiep(web_tenant, api_pool, pool, monkeypatch):
    """`KB_WEB_DEEP_SLICES=2` chia dự án đang được hỏi thành hai nửa rời nhau;
    hai ngày liên tiếp (toordinal lệch nhau đúng 1, đổi tính chẵn lẻ) phủ hết."""
    _pin_slices(monkeypatch, 2)
    vhsc_id = await _add_project(pool, TENANT, "VHSC", "Vinhomes Smart City")
    suna_id = await _add_project(pool, TENANT, "SUNA", "Sun Annora Residence")
    await _user_says(pool, TENANT, "cho mình hỏi giá vinhomes smart city", seq=0)
    await _user_says(pool, TENANT, "cho mình hỏi giá sun annora residence", seq=1)
    assert vhsc_id % 2 != suna_id % 2  # hai id liên tiếp luôn khác tính chẵn lẻ

    day1, day2 = _MONDAY, _MONDAY + timedelta(days=1)
    await queue_projects(api_pool, MODE_WEEKLY, today=day1)
    day1_codes = {j["project_code"] for j in await _jobs(pool, TENANT)}
    await queue_projects(api_pool, MODE_WEEKLY, today=day2)
    day2_codes = {j["project_code"] for j in await _jobs(pool, TENANT)} - day1_codes

    assert day1_codes & day2_codes == set()
    assert day1_codes | day2_codes == {"VHSC", "SUNA"}


async def test_tuan_slices_1_xep_moi_du_an_duoc_hoi_moi_ngay(web_tenant, api_pool, pool, monkeypatch):
    """`KB_WEB_DEEP_SLICES=1` nghĩa là mọi dự án, mọi ngày — không có lát cắt nào."""
    _pin_slices(monkeypatch, 1)
    await _add_project(pool, TENANT, "VHSC", "Vinhomes Smart City")
    await _user_says(pool, TENANT, "cho mình hỏi giá vinhomes smart city")
    for day in (_MONDAY, _MONDAY + timedelta(days=3)):
        await pool.execute("DELETE FROM control.jobs WHERE tenant_id = $1 AND kind = $2", TENANT, KIND_PROJECT)
        await queue_projects(api_pool, MODE_WEEKLY, today=day)
        assert {j["project_code"] for j in await _jobs(pool, TENANT)} == {"VHSC"}


async def test_tuan_7_lat_cat_phu_het_qua_7_ngay_lien_tiep_qua_ranh_gioi_tuan(web_tenant, api_pool, pool, monkeypatch):
    """7 ngày liên tiếp (dù có băng qua ranh giới tuần lịch) không bỏ sót dự án nào."""
    _pin_slices(monkeypatch, 7)
    codes = []
    for i in range(7):
        code = f"P{i}"
        name = f"Du an demo so {i}"
        await _add_project(pool, TENANT, code, name)
        await _user_says(pool, TENANT, f"cho mình hỏi giá {name.lower()}", seq=i)
        codes.append(code)

    start = date(2026, 10, 3)  # thứ Bảy — chuỗi 7 ngày băng qua ranh giới tuần lịch
    seen: set[str] = set()
    for i in range(7):
        day = start + timedelta(days=i)
        await pool.execute("DELETE FROM control.jobs WHERE tenant_id = $1 AND kind = $2", TENANT, KIND_PROJECT)
        await queue_projects(api_pool, MODE_WEEKLY, today=day)
        seen |= {j["project_code"] for j in await _jobs(pool, TENANT)}
    assert seen == set(codes)


async def test_fanout_mode_sai_thi_nem(web_tenant, api_pool):
    with pytest.raises(ValueError):
        await queue_projects(api_pool, "x")


# ─── handler ─────────────────────────────────────────────────────────────────


_THREE = Refreshed(3)


class _Recorder:
    def __init__(self, result=_THREE, exc=None):
        self.calls = []
        self.result = result
        self.exc = exc

    async def __call__(self, deps, project, mode, now):
        self.calls.append((deps, project, mode, now))
        if self.exc:
            raise self.exc
        return self.result


class _Runtime:
    pool = "POOL"

    def __init__(self):
        self.tenants = []

    async def for_tenant(self, tenant):
        self.tenants.append(tenant)
        return "DEPS"


@pytest.fixture
def fake_refresh(monkeypatch):
    rec = _Recorder()
    monkeypatch.setattr(pipeline, "refresh_project", rec)
    monkeypatch.setattr(jobs, "_shared_runtime", _Runtime())
    return rec


async def test_handler_goi_refresh_dung_du_an_va_mode(web_tenant, api_pool, fake_refresh):
    async with tenant_conn(api_pool, TENANT) as c:
        r = await jobs.handle_project(c, {"project_code": "NPTTL", "mode": MODE_REBUILD})
    assert r == JobResult(count=3, message="NPTTL rebuild: 3 mục")
    [(deps, project, mode, now)] = fake_refresh.calls
    assert deps == "DEPS"
    assert jobs._shared_runtime.tenants == [TENANT]
    assert (project.code, project.name, mode) == ("NPTTL", NPTTL, MODE_REBUILD)
    assert now.tzinfo is not None


async def test_handler_thieu_mode_thi_la_init(web_tenant, api_pool, fake_refresh):
    async with tenant_conn(api_pool, TENANT) as c:
        await jobs.handle_project(c, {"project_code": "NPTTL"})
    assert fake_refresh.calls[0][2] == MODE_INIT


@pytest.mark.parametrize("code", ["KHONGCO", "DRAFT1", "__ALL__", ""])
async def test_handler_du_an_khong_co_hoac_chua_published_thi_bo_qua(web_tenant, api_pool, pool, fake_refresh, code):
    await _add_project(pool, TENANT, "DRAFT1", "Dự án Nháp", status="draft")
    async with tenant_conn(api_pool, TENANT) as c:
        r = await jobs.handle_project(c, {"project_code": code, "mode": MODE_INIT})
    assert r.count == 0 and "bỏ qua" in r.message
    assert fake_refresh.calls == []


async def test_handler_khong_thay_du_an_cua_tenant_khac(web_tenant, api_pool, pool, fake_refresh):
    await _add_project(pool, OTHER, "CHIOTHER", "Dự án Riêng")
    async with tenant_conn(api_pool, TENANT) as c:
        r = await jobs.handle_project(c, {"project_code": "CHIOTHER", "mode": MODE_INIT})
    assert r.count == 0
    assert fake_refresh.calls == []


async def test_handler_loi_tam_thoi_lan_ra(web_tenant, api_pool, fake_refresh):
    fake_refresh.exc = TemporaryError("429")
    async with tenant_conn(api_pool, TENANT) as c:
        with pytest.raises(TemporaryError):
            await jobs.handle_project(c, {"project_code": "NPTTL", "mode": MODE_INIT})


async def test_handler_khong_co_deps_chung_thi_tu_mo(web_tenant, api_pool, monkeypatch):
    rec = _Recorder()
    opened = []

    class Own(_Runtime):
        async def for_tenant(self, tenant):
            return "OWN"

    @asynccontextmanager
    async def fake_open():
        opened.append("open")
        yield Own()
        opened.append("close")

    monkeypatch.setattr(pipeline, "refresh_project", rec)
    monkeypatch.setattr(pipeline, "open_deps", fake_open)
    monkeypatch.setattr(jobs, "_shared_runtime", None)
    async with tenant_conn(api_pool, TENANT) as c:
        await jobs.handle_project(c, {"project_code": "NPTTL", "mode": MODE_INIT})
    assert opened == ["open", "close"]
    assert rec.calls[0][0] == "OWN"


async def test_handler_da_dang_ky_voi_retry():
    from portal.core import jobs as core

    assert core.get_handler(KIND_PROJECT).__wrapped__ is jobs.handle_project
    assert core.retries_of(KIND_PROJECT) == 2


async def test_worker_chay_job_that_va_ghi_ket_qua(web_tenant, api_pool, pool, fake_refresh):
    async with tenant_conn(api_pool, TENANT) as c:
        job_id = await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL")
    assert await run_once(api_pool, kinds=[KIND_PROJECT]) == job_id
    row = await pool.fetchrow("SELECT state, count, message FROM control.jobs WHERE id = $1", job_id)
    assert (row["state"], row["count"], row["message"]) == ("success", 3, "NPTTL init: 3 mục")


async def test_worker_loi_tam_thoi_thi_xep_lai(web_tenant, api_pool, pool, fake_refresh):
    fake_refresh.exc = TemporaryError("503")
    async with tenant_conn(api_pool, TENANT) as c:
        job_id = await enqueue_web_project(c, tenant_id=TENANT, actor="t", project_code="NPTTL")
    await run_once(api_pool, kinds=[KIND_PROJECT])
    row = await pool.fetchrow("SELECT state, attempts FROM control.jobs WHERE id = $1", job_id)
    assert (row["state"], row["attempts"]) == ("queued", 1)


@pytest.mark.parametrize(
    ("result", "message"),
    [
        (Refreshed(0, "trả lời LLM bị cắt"), "NPTTL init: giữ hồ sơ cũ — trả lời LLM bị cắt"),
        (Refreshed(4, "trả lời LLM bị cắt"), "NPTTL init: 4 mục, dừng dựng giữa chừng — trả lời LLM bị cắt"),
        (Refreshed(0), "NPTTL init: 0 mục"),
    ],
)
async def test_handler_bao_ro_khi_giu_ho_so_cu(web_tenant, api_pool, fake_refresh, result, message):
    fake_refresh.result = result
    async with tenant_conn(api_pool, TENANT) as c:
        r = await jobs.handle_project(c, {"project_code": "NPTTL", "mode": MODE_INIT})
    assert r == JobResult(count=result.count, message=message)


# ─── kbweb_run ───────────────────────────────────────────────────────────────


@pytest.fixture
def fake_nightly(monkeypatch):
    calls = []

    async def run_nightly(deps, now, *, target=None, queue=True):
        calls.append((deps, now))
        return [pipeline.Step("crawl", 2), pipeline.Step("bản tin", 1)]

    monkeypatch.setattr(pipeline, "run_nightly", run_nightly)
    monkeypatch.setattr(jobs, "_shared_runtime", _Runtime())
    return calls


async def test_run_dem_chay_chuoi_cho_dung_tenant(web_tenant, api_pool, fake_nightly):
    async with tenant_conn(api_pool, TENANT) as c:
        r = await jobs.handle_run(c, {"mode": MODE_NIGHTLY})
    assert r == JobResult(count=3, message="crawl: 2; bản tin: 1")
    assert jobs._shared_runtime.tenants == [TENANT] and fake_nightly[0][0] == "DEPS"


async def test_run_dem_mot_buoc_hong_thi_job_hong(web_tenant, api_pool, monkeypatch):
    async def run_nightly(deps, now, *, target=None, queue=True):
        return [pipeline.Step("crawl", 2), pipeline.Step("dọn", 0, "OSError: pool")]

    monkeypatch.setattr(pipeline, "run_nightly", run_nightly)
    monkeypatch.setattr(jobs, "_shared_runtime", _Runtime())
    async with tenant_conn(api_pool, TENANT) as c:
        with pytest.raises(RuntimeError, match="dọn: OSError: pool"):
            await jobs.handle_run(c, {"mode": MODE_NIGHTLY})


async def test_run_tuan_chi_xep_ho_so_theo_slices_cua_lich(web_tenant, api_pool, pool, monkeypatch):
    monkeypatch.setattr(jobs, "_shared_runtime", _Runtime())
    seen = []

    async def queue_projects(p, mode, **kw):
        seen.append((mode, kw))
        return 4

    monkeypatch.setattr(fanout, "queue_projects", queue_projects)
    async with tenant_conn(api_pool, TENANT) as c:
        r = await jobs.handle_run(c, {"mode": MODE_WEEKLY, "slices": 3})
    assert r == JobResult(count=4, message="weekly: xếp 4 hồ sơ")
    assert seen == [(MODE_WEEKLY, {"tenant_id": TENANT, "slices": 3, "asked_days": 28, "actor": "lich"})]


async def test_run_mode_sai_thi_nem(web_tenant, api_pool):
    async with tenant_conn(api_pool, TENANT) as c:
        with pytest.raises(ValueError):
            await jobs.handle_run(c, {"mode": MODE_INIT})


async def test_run_da_dang_ky_khong_retry():
    from portal.core import jobs as core

    assert core.get_handler(KIND_RUN).__wrapped__ is jobs.handle_run
    assert core.retries_of(KIND_RUN) == 0 and core.stuck_minutes_of(KIND_RUN) == 360
