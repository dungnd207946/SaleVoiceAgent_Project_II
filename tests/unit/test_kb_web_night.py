from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from portal.cli import kb_web_night as cli
from portal.modules.kb.web import pipeline
from portal.modules.kb.web.contracts import MODE_REBUILD, MODE_WEEKLY

# 2026-09-30 00:30 giờ VN = 2026-09-29 17:30 UTC — ngày UTC và ngày VN lệch nhau.
NOW = datetime(2026, 9, 29, 17, 30, tzinfo=UTC)
T = ["--tenant", "anphu"]


# ─── tham số ─────────────────────────────────────────────────────────────────


def test_mac_dinh_la_luot_dem():
    a = cli.parse_args(T)
    assert (a.tenant, a.weekly, a.rebuild, a.backfill, a.discover_only, a.day) == (
        "anphu",
        False,
        False,
        None,
        False,
        None,
    )


@pytest.mark.parametrize(
    ("argv", "attr", "value"),
    [
        (["--weekly"], "weekly", True),
        (["--weekly", "--slices", "3"], "slices", 3),
        (["--rebuild"], "rebuild", True),
        (["--backfill", "2024-10-01", "2024-10-03"], "backfill", [date(2024, 10, 1), date(2024, 10, 3)]),
        (["--discover-only"], "discover_only", True),
        (["--discover-only", "--day", "2026-09-29"], "day", date(2026, 9, 29)),
        (["--day", "2026-09-29"], "day", date(2026, 9, 29)),
    ],
)
def test_tham_so_hop_le(argv, attr, value):
    assert getattr(cli.parse_args([*T, *argv]), attr) == value


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--weekly"],
        [*T, "--weekly", "--rebuild"],
        [*T, "--weekly", "--discover-only"],
        [*T, "--rebuild", "--backfill", "2024-10-01", "2024-10-02"],
        [*T, "--discover-only", "--backfill", "2024-10-01", "2024-10-02"],
        [*T, "--weekly", "--day", "2026-09-29"],
        [*T, "--rebuild", "--day", "2026-09-29"],
        [*T, "--backfill", "2024-10-01", "2024-10-02", "--day", "2026-09-29"],
        [*T, "--backfill", "2024-10-05", "2024-10-01"],
        [*T, "--backfill", "2024-10-01"],
        [*T, "--day", "hôm-qua"],
        [*T, "--slices", "2"],
        [*T, "--weekly", "--slices", "0"],
    ],
)
def test_tham_so_sai_thi_thoat(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.parse_args(argv)
    assert e.value.code == 2


# ─── chuỗi đêm ───────────────────────────────────────────────────────────────


class _Log(list):
    pass


class _Pool:
    def __init__(self, calls):
        self.calls = calls

    async def close(self):
        self.calls.append(("close_pool",))


@pytest.fixture
def calls(monkeypatch):
    log = _Log()
    deps = SimpleNamespace(tenant="anphu", pool=_Pool(log))

    class Runtime:
        async def for_tenant(self, tenant):
            log.append(("for_tenant", tenant))
            return deps

    @asynccontextmanager
    async def open_deps():
        log.append(("open",))
        yield Runtime()
        log.append(("close",))

    async def crawl_day(d, day):
        assert d is deps
        log.append(("crawl", day))
        return 1

    async def run_nightly(d, now, *, target=None, queue=True):
        assert d is deps
        log.append(("nightly", now, target, queue))
        return [pipeline.Step("crawl", 1), pipeline.Step("bản tin", 2)]

    async def queue_projects(pool, mode, *, today=None, tenant_id=None, slices=None):
        log.append(("queue", mode, today, tenant_id, slices))
        return 5

    async def create_pool(dsn, **kw):
        log.append(("create_pool",))
        return _Pool(log)

    monkeypatch.setattr(pipeline, "open_deps", open_deps)
    monkeypatch.setattr(pipeline, "crawl_day", crawl_day)
    monkeypatch.setattr(pipeline, "run_nightly", run_nightly)
    monkeypatch.setattr(cli, "queue_projects", queue_projects)
    monkeypatch.setattr(cli, "create_pool", create_pool)
    return log


async def test_luot_dem_mo_runtime_cho_dung_tenant_va_chay_chuoi(calls, capsys):
    assert await cli.main_async(T, now=NOW) == 0
    assert calls == [("open",), ("for_tenant", "anphu"), ("nightly", NOW, date(2026, 9, 29), True), ("close",)]
    assert "bản tin: 2" in capsys.readouterr().out


async def test_luot_dem_theo_ngay_chi_dinh(calls):
    await cli.main_async([*T, "--day", "2026-09-10"], now=NOW)
    assert [c[2] for c in calls if c[0] == "nightly"] == [date(2026, 9, 10)]


async def test_mot_buoc_hong_thi_ma_thoat_1(calls, monkeypatch, capsys):
    async def run_nightly(d, now, *, target=None, queue=True):
        return [pipeline.Step("crawl", 1), pipeline.Step("bản tin", 0, "RuntimeError: bug"), pipeline.Step("dọn", 3)]

    monkeypatch.setattr(pipeline, "run_nightly", run_nightly)
    assert await cli.main_async(T, now=NOW) == 1
    assert "bản tin: RuntimeError: bug" in capsys.readouterr().out


async def test_tuan_chi_xep_viec_theo_ngay_vn_cho_dung_tenant(calls):
    assert await cli.main_async([*T, "--weekly", "--slices", "3"], now=NOW) == 0
    assert calls == [("create_pool",), ("queue", MODE_WEEKLY, date(2026, 9, 30), "anphu", 3), ("close_pool",)]


async def test_dung_lai_chi_xep_viec(calls):
    assert await cli.main_async([*T, "--rebuild"], now=NOW) == 0
    assert calls == [("create_pool",), ("queue", MODE_REBUILD, None, "anphu", None), ("close_pool",)]


async def test_backfill_tung_ngay_khong_xep_viec(calls):
    assert await cli.main_async([*T, "--backfill", "2024-10-01", "2024-10-03"], now=NOW) == 0
    assert calls == [
        ("open",),
        ("for_tenant", "anphu"),
        ("crawl", date(2024, 10, 1)),
        ("crawl", date(2024, 10, 2)),
        ("crawl", date(2024, 10, 3)),
        ("close",),
    ]


async def test_backfill_ngay_hong_thi_ngay_sau_van_chay(calls, monkeypatch):
    async def crawl_day(d, day):
        calls.append(("crawl", day))
        if day == date(2024, 10, 1):
            raise RuntimeError("503")
        return 0

    monkeypatch.setattr(pipeline, "crawl_day", crawl_day)
    assert await cli.main_async([*T, "--backfill", "2024-10-01", "2024-10-02"], now=NOW) == 1
    assert [c[1] for c in calls if c[0] == "crawl"] == [date(2024, 10, 1), date(2024, 10, 2)]


@pytest.fixture
def discover_only(calls, monkeypatch):
    class FakeDiscoverer:
        def __init__(self, http):
            calls.append(("discoverer", type(http).__name__))

        async def day_entries(self, source, day, keywords):
            calls.append(("discover", source.domain, day, keywords))
            return [1, 2]

    cfg = SimpleNamespace(
        sources=(SimpleNamespace(domain="a.vn"), SimpleNamespace(domain="b.vn")), bds_keywords=("bđs",)
    )

    @asynccontextmanager
    async def tenant_conn(pool, tenant):
        calls.append(("tenant_conn", tenant))
        yield "CONN"

    async def load_for_tenant(conn):
        return cfg

    monkeypatch.setattr(cli, "Discoverer", FakeDiscoverer)
    monkeypatch.setattr(cli, "tenant_conn", tenant_conn)
    monkeypatch.setattr(cli.config, "load_for_tenant", load_for_tenant)
    return calls


async def test_chi_tim_bai_khong_mo_deps_khong_xep_viec(discover_only, capsys):
    """Không open_deps: nó mở Qdrant và TẠO collection — lượt chỉ-đọc không được ghi gì."""
    assert await cli.main_async([*T, "--discover-only"], now=NOW) == 0
    assert discover_only == [
        ("create_pool",),
        ("tenant_conn", "anphu"),
        ("close_pool",),
        ("discoverer", "AsyncClient"),
        ("discover", "a.vn", date(2026, 9, 29), ("bđs",)),
        ("discover", "b.vn", date(2026, 9, 29), ("bđs",)),
    ]
    assert "a.vn: 2 bài ngày 2026-09-29" in capsys.readouterr().out


async def test_chi_tim_bai_theo_ngay_chi_dinh(discover_only):
    await cli.main_async([*T, "--discover-only", "--day", "2026-09-10"], now=NOW)
    assert {c[2] for c in discover_only if c[0] == "discover"} == {date(2026, 9, 10)}
