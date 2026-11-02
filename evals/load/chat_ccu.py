"""CCU chat WS :8766/chat + assert hành vi admission (spec §8).

Kịch bản turn + protocol theo scripts/load_test/v2/phase_b_chat.py. Admission check là
kiểm chứng CHƯA TỪNG CÓ: vượt CHAT_MAX_CONCURRENT_SESSIONS phải close 4029 và
/health/ready phải 503 khi bão hoà, hồi phục sau drain. CHẠY TRÊN STAGING/DEV — không
nhắm production đang phục vụ khách."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

from evals.load.ramp import CampaignResult, StepResult, knee_by_plateau, percentiles, ramp_schedule

TURNS = [
    "Chào em, cho anh hỏi Noble có những dự án nào?",
    "Dự án nào ở khu vực trung tâm và tầm giá khoảng 3 tỷ?",
    "Cho anh xin thông tin chi tiết dự án đó với.",
    "Anh muốn đặt lịch tham quan cuối tuần này được không?",
]


async def _run_turn(ws, text: str) -> float:
    t0 = time.monotonic()
    await ws.send(json.dumps({"type": "user_text", "text": text}))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=60.0)
        if isinstance(raw, str) and json.loads(raw).get("type") == "done":
            return time.monotonic() - t0


async def _session_worker(base_ws: str, idx: int, deadline: float, latencies: list[float], counters: dict) -> None:
    import websockets  # noqa: PLC0415

    sid = f"eval:load:{idx}-{int(deadline)}"
    try:
        async with websockets.connect(f"{base_ws}/chat?session={sid}", max_size=10 * 1024 * 1024) as ws:
            await asyncio.wait_for(ws.recv(), timeout=10.0)  # drain greeting {"type":"session_id"}
            i = 0
            while time.monotonic() < deadline:
                try:
                    latencies.append(await _run_turn(ws, TURNS[i % len(TURNS)]))
                    counters["ok"] += 1
                except Exception:  # noqa: BLE001
                    counters["failed"] += 1
                i += 1
    except Exception:  # noqa: BLE001
        counters["failed"] += 1


async def _step(base_ws: str, concurrency: int, hold_s: float) -> StepResult:
    latencies: list[float] = []
    counters = {"ok": 0, "failed": 0}
    start = time.monotonic()
    deadline = start + hold_s
    await asyncio.gather(*[_session_worker(base_ws, i, deadline, latencies, counters) for i in range(concurrency)])
    dur = time.monotonic() - start
    total = counters["ok"] + counters["failed"]
    return StepResult(concurrency=concurrency, duration_s=dur, total=total, ok=counters["ok"],
                       failed=counters["failed"], latency=percentiles(latencies),
                       err_rate=(counters["failed"] / total) if total else 0.0)


async def run_chat_ccu(*, base_ws: str, max_concurrency: int, hold_s: float) -> CampaignResult:
    baseline = await _step(base_ws, 1, hold_s)
    result = CampaignResult(label=f"chat {base_ws}", baseline_p95=baseline.latency.get("p95", 0.0),
                             steps=[baseline])
    for c in ramp_schedule(max_concurrency=max_concurrency):
        if c <= 1:
            continue
        result.steps.append(await _step(base_ws, c, hold_s))
    result.knee = knee_by_plateau(result.steps)
    return result


async def assert_admission(*, base_ws: str, base_http: str, cap: int, extra: int = 5) -> dict:
    import httpx  # noqa: PLC0415
    import websockets  # noqa: PLC0415

    sockets: list = []
    closed_4029 = 0
    try:
        for i in range(cap + extra):
            try:
                ws = await websockets.connect(f"{base_ws}/chat?session=eval:adm:{i}", max_size=1024 * 1024)
                # Greeting HOẶC close-ngay: session bị từ chối close 4029 trước khi kịp greeting.
                await asyncio.wait_for(ws.recv(), timeout=10.0)
                sockets.append(ws)
            except websockets.exceptions.ConnectionClosed as e:
                if getattr(e.rcvd, "code", None) == 4029:
                    closed_4029 += 1
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_http}/health/ready")
            ready_503 = resp.status_code == 503
    finally:
        for ws in sockets:
            with contextlib.suppress(Exception):
                await ws.close()
    ready_200 = False
    async with httpx.AsyncClient(timeout=10.0) as client:
        for _ in range(30):
            with contextlib.suppress(Exception):
                if (await client.get(f"{base_http}/health/ready")).status_code == 200:
                    ready_200 = True
                    break
            await asyncio.sleep(1.0)
    return {"over_cap_closed_4029": closed_4029, "ready_503_at_saturation": ready_503,
            "ready_200_after_drain": ready_200}


def summarize_admission(res: dict, cap: int) -> tuple[dict[str, str], bool]:  # noqa: ARG001 — cap giữ cho message
    gates = {
        "admission_4029": "pass" if res.get("over_cap_closed_4029", 0) >= 1 else "fail",
        "ready_503": "pass" if res.get("ready_503_at_saturation") else "fail",
        "ready_recover": "pass" if res.get("ready_200_after_drain") else "fail",
    }
    return gates, all(v == "pass" for v in gates.values())
