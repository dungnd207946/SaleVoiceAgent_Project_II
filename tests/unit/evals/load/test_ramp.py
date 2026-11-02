import asyncio

import pytest
from evals.load import ramp as common


def test_ramp_schedule_doubles_and_includes_cap():
    assert common.ramp_schedule(1, 2, 16) == [1, 2, 4, 8, 16]
    assert common.ramp_schedule(1, 2, 10) == [1, 2, 4, 8, 10]


def test_percentiles_nearest_rank():
    s = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    out = common.percentiles(s, (50, 95, 99))
    assert out["p50"] == 5
    assert out["p95"] == 10
    assert out["p99"] == 10
    assert out["max"] == 10


def test_percentiles_empty():
    assert common.percentiles([]) == {}


def test_is_broken_on_error_rate():
    step = common.StepResult(concurrency=4, duration_s=1.0, total=100, ok=98,
                             failed=2, latency={"p95": 0.1}, err_rate=0.02)
    assert common.is_broken(step, baseline_p95=0.1) is True


def test_is_broken_on_latency_blowup():
    step = common.StepResult(concurrency=4, duration_s=1.0, total=100, ok=100,
                             failed=0, latency={"p95": 0.5}, err_rate=0.0)
    assert common.is_broken(step, baseline_p95=0.2) is True   # 0.5 > 2*0.2
    assert common.is_broken(step, baseline_p95=0.3) is False  # 0.5 < 2*0.3


@pytest.mark.asyncio
async def test_run_step_counts_ok():
    async def fake():
        await asyncio.sleep(0.005)
        return 0.005
    step = await common.run_step(fake, concurrency=4, hold_s=0.2)
    assert step.concurrency == 4
    assert step.ok > 0
    assert step.failed == 0
    assert step.err_rate == 0.0
    assert "p95" in step.latency


@pytest.mark.asyncio
async def test_run_step_counts_failures():
    async def boom():
        raise RuntimeError("nope")
    step = await common.run_step(boom, concurrency=2, hold_s=0.1)
    assert step.ok == 0
    assert step.failed > 0
    assert step.err_rate == 1.0


def test_write_results_md(tmp_path):
    step = common.StepResult(concurrency=2, duration_s=1.0, total=10, ok=10,
                             failed=0, latency={"p50": 0.1, "p95": 0.2, "p99": 0.3, "max": 0.3},
                             err_rate=0.0)
    result = common.CampaignResult(label="unit", baseline_p95=0.1, steps=[step], knee=2)
    out = tmp_path / "RESULTS.md"
    common.write_results_md(result, out)
    text = out.read_text()
    assert "knee" in text.lower()
    assert "| 2 |" in text  # concurrency row


def _step(c, ok, dur=60.0, failed=0, p95=0.1):
    total = ok + failed
    return common.StepResult(concurrency=c, duration_s=dur, total=total, ok=ok,
                             failed=failed, latency={"p95": p95},
                             err_rate=(failed / total) if total else 0.0)


def test_knee_by_plateau_serial_stays_at_one():
    # flat throughput (serial GPU) → knee = 1
    steps = [_step(1, 78), _step(2, 78)]
    assert common.knee_by_plateau(steps) == 1


def test_knee_by_plateau_scaling_then_plateau():
    steps = [_step(1, 10, dur=1.0), _step(2, 20, dur=1.0), _step(4, 22, dur=1.0)]
    # gain 1→2 = 1.0 (keep), gain 2→4 = 0.1 < 0.15 (plateau) → knee = 2
    assert common.knee_by_plateau(steps) == 2


def test_knee_by_plateau_stops_on_errors():
    steps = [_step(1, 100, dur=1.0), _step(2, 98, dur=1.0, failed=2)]  # err 2% at c=2
    assert common.knee_by_plateau(steps) == 1


@pytest.mark.asyncio
async def test_run_campaign_full_ramp_runs_all_steps():
    async def fast():
        await asyncio.sleep(0.001)
        return 0.001
    res = await common.run_campaign(fast, label="x", ramp=[1, 2, 4], hold_s=0.05,
                                    warmup_n=0, full_ramp=True)
    assert [s.concurrency for s in res.steps] == [1, 2, 4]
    assert res.knee in (1, 2, 4)
