"""Trần đồng thời khai theo loại việc — core cưỡng chế, module khai."""

import pytest

from portal.core.jobs import JobResult, concurrency_of, register


@pytest.fixture(autouse=True)
def _giu_nguyen_so_handler():
    from portal.core import jobs

    handlers = dict(jobs._HANDLERS)
    concurrency = dict(jobs._CONCURRENCY)
    yield
    jobs._HANDLERS.clear()
    jobs._HANDLERS.update(handlers)
    jobs._CONCURRENCY.clear()
    jobs._CONCURRENCY.update(concurrency)


async def _handler(conn, payload):
    return JobResult()


def test_mac_dinh_mot_luot_mot_lan():
    register("t_default", _handler)
    assert concurrency_of("t_default") == 1


def test_khai_tran_cao_hon():
    register("t_wide", _handler, max_concurrency=6)
    assert concurrency_of("t_wide") == 6


def test_kind_chua_dang_ky_van_tra_mot():
    assert concurrency_of("t_unknown") == 1


def test_tran_duoi_mot_bi_tu_choi():
    with pytest.raises(ValueError, match="max_concurrency"):
        register("t_zero", _handler, max_concurrency=0)


def test_headroom_bo_kind_da_dat_tran():
    from portal.core import jobs

    register("t_busy", _handler, max_concurrency=1)
    register("t_free", _handler, max_concurrency=2)
    jobs._INFLIGHT["t_busy"] = 1
    jobs._INFLIGHT["t_free"] = 1
    try:
        ready = jobs.kinds_with_headroom()
        assert "t_busy" not in ready
        assert "t_free" in ready
    finally:
        jobs._INFLIGHT.clear()
