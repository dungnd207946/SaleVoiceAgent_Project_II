"""Điều tiết nhịp gọi VLM — logic thuần, không mạng, không chờ thật."""

import asyncio

import pytest

from portal.modules.kb.clients.rate_gate import VlmRateGate


def _gate(**kw) -> VlmRateGate:
    clock_state = {"t": 0.0}
    g = VlmRateGate(ceiling=6, clock=lambda: clock_state["t"], **kw)
    g._clock_state = clock_state  # test dời thời gian qua đây
    return g


def test_bat_dau_o_tran():
    assert _gate().permits == 6


def test_429_giam_mot_nua():
    g = _gate()
    g.penalize()
    assert g.permits == 3
    g.penalize()
    assert g.permits == 1


def test_khong_bao_gio_xuong_duoi_san():
    g = _gate(floor=2)
    for _ in range(5):
        g.penalize()
    assert g.permits == 2


def test_thanh_cong_du_nhieu_thi_hoi_dan():
    g = _gate(recover_after=3)
    g.penalize()
    before = g.permits
    for _ in range(3):
        g.reward()
    assert g.permits == before + 1


def test_khong_vuot_tran_khi_hoi():
    g = _gate(recover_after=1)
    for _ in range(20):
        g.reward()
    assert g.permits == 6


def test_sau_429_phai_nghi_het_cooldown():
    g = _gate(cooldown_sec=30.0)
    g.penalize()
    assert g.paused_for() == pytest.approx(30.0)
    g._clock_state["t"] = 31.0
    assert g.paused_for() == 0.0


async def test_giam_permits_thi_chan_that_su():
    """penalize() phải CHẶN bớt lượt chạy, không chỉ đổi một con số trang trí."""
    g = VlmRateGate(ceiling=4, cooldown_sec=0.0)
    g.penalize()  # còn 2
    running = 0
    peak = 0

    async def one_call() -> None:
        nonlocal running, peak
        async with g:
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.05)
            running -= 1

    await asyncio.gather(*[one_call() for _ in range(4)])
    assert peak == 2
