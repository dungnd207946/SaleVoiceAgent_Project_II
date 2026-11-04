# Load / Capacity Stress Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build reusable load tooling and run a stress-to-break campaign against the live santa-hotline-agent stack (Phase A per-service + Phase B chat), producing a capacity report that names each channel's knee and its binding resource.

**Architecture:** A pure-Python core (`common.py`: ramp schedule, async step driver, percentiles, break-detection, report writer) is TDD'd offline. Thin asyncio network clients (embed HTTP, TTS/STT WebSocket, chat WebSocket) reuse the core and are smoke-verified against the live server over LAN. A server-side sampler (`nvidia-smi` + `docker stats` over SSH) captures resource saturation. A single-file OpenAI-compatible LLM stub isolates infra for Phase B.

**Tech Stack:** Python 3.11+ (asyncio, `websockets`, `httpx`, `aiohttp` for the stub), pytest (`asyncio_mode=auto`), `expect` SSH helper for server-side sampling, MongoDB `session_metrics` + Phoenix for agent-side latency.

## Global Constraints

- Python **3.11+**; ruff line-length **120**, rules `E,F,W,I,UP,B,SIM`; pytest `asyncio_mode=auto`.
- **Never touch `develop`.** All work on branch **`test/load-capacity`** (already created + checked out). Local commits only; no push/PR without explicit approval.
- Load is generated **from the Mac over LAN** to `10.50.12.70`. Server-side commands run via the expect helper at `$CLAUDE_JOB_DIR/tmp/rsh.exp` (`ssh thebc@thebc-server.local`).
- New tooling lives under **`scripts/load_test/v2/`**. The sipp-era `scripts/load_test/*.py` + `scripts/load_test/docs/` stay **untouched** (dead, kept for reference).
- The **only** production mutation is the reversible Phase-B LLM stub. **Back up the server `.env` before editing; revert + verify `/api/config` after.**
- **Breaking-point criteria (default):** hold each concurrency step ~90 s; a step "breaks" when p95 latency > **2×** warm-baseline p95, **or** error/timeout rate > **1%**, **or** a server resource is pinned (GPU ~100% + growing backlog / CPU saturated / RAM exhausted).
- No real traffic in the test window (confirmed). Co-tenant `santa-chat-agent` shares the same 20 threads — note cross-impact in the report.
- Confirmed endpoints (from repo `.env`, verified reachable): TTS `ws://10.50.12.70:8011/tts`, STT `ws://10.50.12.70:8012/stt`, embed `http://10.50.12.70:8013/embed` (Bearer `EMBED_REMOTE_TOKEN`), chat `ws://10.50.12.70:8766/chat`, Mongo `:27017`, Phoenix `:6006`.
- Server baseline: i5-14600KF (20 threads), 30 GiB RAM, 1× RTX 5060 Ti 16 GB (7.2 GB resident at idle). TTS is the sole GPU tenant and synthesizes serially (`threading.Lock`) — the prime bottleneck hypothesis.

---

### Task 1: `common.py` — pure helpers (ramp, percentiles, break-detection)

**Files:**
- Create: `scripts/load_test/v2/common.py`
- Test: `scripts/load_test/v2/test_common.py`

**Interfaces:**
- Produces: `ramp_schedule(start=1, factor=2, max_concurrency=256) -> list[int]`; `percentiles(samples: list[float], ps=(50,95,99)) -> dict[str,float]` (keys `"p50"/"p95"/"p99"/"max"`, seconds; `{}` if empty); `is_broken(step: StepResult, baseline_p95: float, err_thresh=0.01, factor=2.0) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# scripts/load_test/v2/test_common.py
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts/load_test/v2 && python -m pytest test_common.py -q`
Expected: FAIL — `ModuleNotFoundError` / `AttributeError: module 'common' has no attribute 'ramp_schedule'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/load_test/v2/common.py
"""Shared load-test primitives: ramp schedule, async step driver, percentiles, report writer.

Pure helpers (ramp_schedule/percentiles/is_broken/write_results_md) are unit-tested offline;
run_step/run_campaign are exercised with a fake make_request (no network).
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

# One request: returns latency in seconds, or raises on failure.
MakeRequest = Callable[[], Awaitable[float]]


def ramp_schedule(start: int = 1, factor: int = 2, max_concurrency: int = 256) -> list[int]:
    """[start, start*factor, ...] up to and including max_concurrency."""
    steps: list[int] = []
    c = start
    while c < max_concurrency:
        steps.append(c)
        c *= factor
    steps.append(max_concurrency)
    return steps


def percentiles(samples: list[float], ps: tuple[int, ...] = (50, 95, 99)) -> dict[str, float]:
    """Nearest-rank percentiles + max over samples (seconds). {} if empty."""
    if not samples:
        return {}
    ordered = sorted(samples)
    n = len(ordered)
    out: dict[str, float] = {}
    for p in ps:
        k = max(0, min(n - 1, (p * n + 99) // 100 - 1))  # ceil(p/100 * n) - 1
        out[f"p{p}"] = ordered[k]
    out["max"] = ordered[-1]
    return out


@dataclass
class StepResult:
    concurrency: int
    duration_s: float
    total: int
    ok: int
    failed: int
    latency: dict[str, float]
    err_rate: float

    @property
    def throughput(self) -> float:
        return self.ok / self.duration_s if self.duration_s else 0.0


def is_broken(step: StepResult, baseline_p95: float, err_thresh: float = 0.01, factor: float = 2.0) -> bool:
    if step.err_rate > err_thresh:
        return True
    p95 = step.latency.get("p95")
    return p95 is not None and baseline_p95 > 0 and p95 > factor * baseline_p95
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts/load_test/v2 && python -m pytest test_common.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/load_test/v2/common.py scripts/load_test/v2/test_common.py
git commit -m "test: load-test pure helpers (ramp/percentiles/break-detection)"
```

---

### Task 2: `common.py` — async step driver, campaign runner, report writer

**Files:**
- Modify: `scripts/load_test/v2/common.py` (append)
- Test: `scripts/load_test/v2/test_common.py` (append)

**Interfaces:**
- Consumes: `StepResult`, `percentiles`, `is_broken` (Task 1).
- Produces: `async run_step(make_request: MakeRequest, concurrency: int, hold_s: float) -> StepResult`; `CampaignResult(label, baseline_p95, steps: list[StepResult], knee: int|None)`; `async run_campaign(make_request, *, label, ramp, hold_s, warmup_n=3) -> CampaignResult`; `write_results_md(result: CampaignResult, path: Path) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# append to scripts/load_test/v2/test_common.py
import asyncio
import pytest


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd scripts/load_test/v2 && python -m pytest test_common.py -q`
Expected: FAIL — `AttributeError: module 'common' has no attribute 'run_step'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/load_test/v2/common.py

async def run_step(make_request: MakeRequest, concurrency: int, hold_s: float) -> StepResult:
    """Run `concurrency` asyncio workers issuing requests back-to-back for hold_s seconds."""
    latencies: list[float] = []
    ok = 0
    failed = 0
    deadline = time.monotonic() + hold_s

    async def worker() -> None:
        nonlocal ok, failed  # single-threaded asyncio → counter mutation is safe
        while time.monotonic() < deadline:
            try:
                lat = await make_request()
                latencies.append(lat)
                ok += 1
            except Exception:
                failed += 1

    start = time.monotonic()
    await asyncio.gather(*[worker() for _ in range(concurrency)])
    dur = time.monotonic() - start
    total = ok + failed
    return StepResult(
        concurrency=concurrency,
        duration_s=dur,
        total=total,
        ok=ok,
        failed=failed,
        latency=percentiles(latencies),
        err_rate=(failed / total) if total else 0.0,
    )


@dataclass
class CampaignResult:
    label: str
    baseline_p95: float
    steps: list[StepResult] = field(default_factory=list)
    knee: int | None = None


async def run_campaign(
    make_request: MakeRequest,
    *,
    label: str,
    ramp: list[int],
    hold_s: float,
    warmup_n: int = 3,
) -> CampaignResult:
    for _ in range(warmup_n):
        try:
            await make_request()
        except Exception:
            pass
    baseline = await run_step(make_request, 1, hold_s)
    baseline_p95 = baseline.latency.get("p95", 0.0)
    result = CampaignResult(label=label, baseline_p95=baseline_p95, steps=[baseline])
    knee = 1
    for c in ramp:
        if c <= 1:
            continue
        step = await run_step(make_request, c, hold_s)
        result.steps.append(step)
        if is_broken(step, baseline_p95):
            break
        knee = c
    result.knee = knee
    return result


def _ms(latency: dict[str, float], key: str) -> str:
    v = latency.get(key)
    return f"{v * 1000:.0f}" if v is not None else "-"


def write_results_md(result: CampaignResult, path: Path) -> None:
    lines = [
        f"# Load campaign — {result.label}",
        "",
        f"- warm baseline p95: {result.baseline_p95 * 1000:.0f} ms",
        f"- knee (max sustainable concurrency): **{result.knee}**",
        "",
        "| concurrency | ok | failed | err% | p50 ms | p95 ms | p99 ms | max ms | req/s |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in result.steps:
        lines.append(
            f"| {s.concurrency} | {s.ok} | {s.failed} | {s.err_rate * 100:.1f} | "
            f"{_ms(s.latency, 'p50')} | {_ms(s.latency, 'p95')} | {_ms(s.latency, 'p99')} | "
            f"{_ms(s.latency, 'max')} | {s.throughput:.1f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd scripts/load_test/v2 && python -m pytest test_common.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add scripts/load_test/v2/common.py scripts/load_test/v2/test_common.py
git commit -m "test: load-test step driver + campaign runner + report writer"
```

---

### Task 3: `phase_a_embed.py` — embed service load client (`:8013`)

**Files:**
- Create: `scripts/load_test/v2/phase_a_embed.py`

**Interfaces:**
- Consumes: `common.ramp_schedule`, `common.run_campaign`, `common.write_results_md`.
- Produces: CLI `python phase_a_embed.py [--hold 90] [--max 256] [--out DIR]` → writes `<out>/embed_RESULTS.md`.

- [ ] **Step 1: Write the client**

```python
# scripts/load_test/v2/phase_a_embed.py
"""Load client for the embed service (:8013). POST /embed {"texts","is_query"} + Bearer."""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ENV = dotenv_values(ROOT / ".env")
URL = ENV["EMBED_REMOTE_URL"].rstrip("/") + "/embed"
TOKEN = (ENV.get("EMBED_REMOTE_TOKEN") or "").strip()
QUERY = "bảng giá và chính sách thanh toán căn hộ dự án Noble"


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=256)
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()

    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        async def make_request() -> float:
            t = time.monotonic()
            r = await client.post(URL, json={"texts": [QUERY], "is_query": True})
            r.raise_for_status()
            if not r.json().get("embeddings"):
                raise ValueError("no embeddings in response")
            return time.monotonic() - t

        print(f"embed load → {URL} (token={'yes' if TOKEN else 'no'})")
        result = await common.run_campaign(
            make_request, label="embed :8013",
            ramp=common.ramp_schedule(max_concurrency=args.max), hold_s=args.hold,
        )
    args.out.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, args.out / "embed_RESULTS.md")
    print(f"knee={result.knee}  → {args.out / 'embed_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
```

- [ ] **Step 2: Smoke-verify against the live service (concurrency ramps automatically; short hold)**

Run: `cd scripts/load_test/v2 && python phase_a_embed.py --hold 3 --max 4 --out /tmp/embed_smoke`
Expected: prints `knee=...`; `/tmp/embed_smoke/embed_RESULTS.md` exists with a table, `err%` = 0 at low concurrency, non-zero `req/s`. (If it fails to connect, confirm `EMBED_REMOTE_URL`/token in `.env` and that `:8013` is reachable via `nc -z 10.50.12.70 8013`.)

- [ ] **Step 3: Commit**

```bash
git add scripts/load_test/v2/phase_a_embed.py
git commit -m "feat: embed-service load client (phase A)"
```

---

### Task 4: `phase_a_tts.py` — TTS service load client (`:8011`, GPU)

**Files:**
- Create: `scripts/load_test/v2/phase_a_tts.py`

**Interfaces:**
- Consumes: `common.ramp_schedule`, `common.run_campaign`, `common.write_results_md`.
- Produces: CLI `python phase_a_tts.py [--hold 90] [--max 64] [--out DIR]` → `<out>/tts_RESULTS.md`. Latency metric = **full synthesis time** (open WS → last PCM before `{"type":"end"}`), the GPU-saturation signal.

- [ ] **Step 1: Write the client**

```python
# scripts/load_test/v2/phase_a_tts.py
"""Load client for the TTS service (:8011). WS: send {"type":"synthesize",...}, drain
binary PCM until {"type":"end"}. Protocol inlined (3 keys) to keep this dependency-light."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import websockets
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ENV = dotenv_values(ROOT / ".env")
URL = ENV["TTS_SERVICE_URL"]
TOKEN = (ENV.get("VOICE_SERVICE_AUTH_TOKEN") or "").strip()
VOICE = (ENV.get("VIENEU_VOICE_ID") or "").strip() or None
TEXT = "Dạ em xin phép giới thiệu về dự án của Noble, đây là một dự án căn hộ cao cấp rất đáng để anh chị tham khảo ạ."


async def _synth_once() -> float:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    t0 = time.monotonic()
    msg = {"type": "synthesize", "text": TEXT}
    if VOICE:
        msg["voice"] = VOICE
    async with websockets.connect(URL, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(msg))
        got_audio = False
        async for raw in ws:
            if isinstance(raw, bytes):
                got_audio = got_audio or bool(raw)
            elif json.loads(raw).get("type") == "end":
                break
    if not got_audio:
        raise ValueError("no PCM received")
    return time.monotonic() - t0


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=64)
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()
    print(f"TTS load → {URL} (GPU-bound, serial synth expected)")
    result = await common.run_campaign(
        _synth_once, label="tts :8011",
        ramp=common.ramp_schedule(max_concurrency=args.max), hold_s=args.hold,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, args.out / "tts_RESULTS.md")
    print(f"knee={result.knee}  → {args.out / 'tts_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
```

- [ ] **Step 2: Smoke-verify against the live service**

Run: `cd scripts/load_test/v2 && python phase_a_tts.py --hold 4 --max 2 --out /tmp/tts_smoke`
Expected: `knee=...`; `/tmp/tts_smoke/tts_RESULTS.md` shows non-zero p50/p95 (hundreds of ms to a few s), `err%` = 0 at concurrency 1. (Warm baseline TTFB is ~300 ms per CLAUDE.md; full synth of this sentence is longer.)

- [ ] **Step 3: Commit**

```bash
git add scripts/load_test/v2/phase_a_tts.py
git commit -m "feat: TTS-service load client (phase A)"
```

---

### Task 5: `phase_a_stt.py` — STT service load client (`:8012`, CPU)

**Files:**
- Create: `scripts/load_test/v2/phase_a_stt.py`

**Interfaces:**
- Consumes: `common.*`.
- Produces: CLI `python phase_a_stt.py [--hold 90] [--max 64] [--out DIR]` → `<out>/stt_RESULTS.md`. Fixture = a synthetic 3 s PCM16 16 kHz mono tone (deterministic, no external file); frames blasted as fast as possible, then `{"type":"eos"}`; latency = start → `{"type":"final"}`. (Content is irrelevant for CPU-cost measurement; `eos` forces finalization.)

- [ ] **Step 1: Write the client**

```python
# scripts/load_test/v2/phase_a_stt.py
"""Load client for the STT service (:8012). WS: blast PCM16 16kHz frames, send
{"type":"eos"}, wait for {"type":"final"}. Latency = start → final."""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import struct
import sys
import time
from pathlib import Path

import websockets
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ENV = dotenv_values(ROOT / ".env")
URL = ENV["STT_SERVICE_URL"]
TOKEN = (ENV.get("VOICE_SERVICE_AUTH_TOKEN") or "").strip()

_SR = 16000
_SECS = 3.0
_FRAME = 320  # 20 ms @ 16 kHz


def _pcm_fixture() -> bytes:
    n = int(_SR * _SECS)
    vals = (int(8000 * math.sin(2 * math.pi * 200 * i / _SR)) for i in range(n))
    return struct.pack(f"<{n}h", *vals)


_AUDIO = _pcm_fixture()


async def _transcribe_once() -> float:
    headers = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
    t0 = time.monotonic()
    got_final = asyncio.Event()
    async with websockets.connect(URL, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        async def recv() -> None:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                if json.loads(raw).get("type") == "final":
                    got_final.set()
                    return
        rx = asyncio.create_task(recv())
        for off in range(0, len(_AUDIO), _FRAME * 2):
            await ws.send(_AUDIO[off:off + _FRAME * 2])
        await ws.send(json.dumps({"type": "eos"}))
        try:
            await asyncio.wait_for(got_final.wait(), timeout=15.0)
        finally:
            rx.cancel()
    return time.monotonic() - t0


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=64)
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()
    print(f"STT load → {URL} (CPU-bound, sherpa)")
    result = await common.run_campaign(
        _transcribe_once, label="stt :8012",
        ramp=common.ramp_schedule(max_concurrency=args.max), hold_s=args.hold,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, args.out / "stt_RESULTS.md")
    print(f"knee={result.knee}  → {args.out / 'stt_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
```

- [ ] **Step 2: Smoke-verify against the live service**

Run: `cd scripts/load_test/v2 && python phase_a_stt.py --hold 4 --max 2 --out /tmp/stt_smoke`
Expected: `knee=...`; `/tmp/stt_smoke/stt_RESULTS.md` with non-zero latency, `err%` = 0 at concurrency 1. If every request times out (no `final`), inspect the STT server logs — the `eos` control frame must trigger finalization; adjust the control key only if the live server disagrees with `voice/service/protocol.py`.

- [ ] **Step 3: Commit**

```bash
git add scripts/load_test/v2/phase_a_stt.py
git commit -m "feat: STT-service load client (phase A)"
```

---

### Task 6: `sampler.sh` — server-side resource sampler

**Files:**
- Create: `scripts/load_test/v2/sampler.sh`

**Interfaces:**
- Produces: a bash loop, run **on the server** via SSH, writing `gpu.csv` (ts,util,mem_used_mib,power_w) + `containers.log` (timestamped `docker stats --no-stream` snapshots) into an output dir, every N seconds until killed.

- [ ] **Step 1: Write the sampler**

```bash
#!/usr/bin/env bash
# Usage: sampler.sh <out_dir> [interval_s]
# Run on the server; Ctrl-C / SIGTERM to stop. Samples GPU + container CPU/mem.
set -u
out="${1:?out_dir required}"
iv="${2:-2}"
mkdir -p "$out"
echo "ts,gpu_util,gpu_mem_used_mib,gpu_power_w" > "$out/gpu.csv"
: > "$out/containers.log"
trap 'exit 0' INT TERM
while true; do
  ts=$(date +%s)
  line=$(nvidia-smi --query-gpu=utilization.gpu,memory.used,power.draw \
         --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
  echo "${ts},${line}" >> "$out/gpu.csv"
  {
    echo "=== ${ts} ==="
    docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' 2>/dev/null \
      | grep -E 'hotline|models|infra' || true
  } >> "$out/containers.log"
  sleep "$iv"
done
```

- [ ] **Step 2: Ship + smoke-verify over SSH (5 s sample, then stop)**

```bash
# from the Mac
scp -o StrictHostKeyChecking=no scripts/load_test/v2/sampler.sh thebc@thebc-server.local:/tmp/sampler.sh  # (use the expect helper's password prompt)
"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'bash /tmp/sampler.sh /tmp/samp 2 & p=$!; sleep 5; kill $p; echo "--- gpu.csv ---"; cat /tmp/samp/gpu.csv; echo "--- containers ---"; head -20 /tmp/samp/containers.log'
```
Expected: `gpu.csv` has a header + ≥2 data rows (util 0–100, mem ~7000+ MiB); `containers.log` shows hotline/models/infra container CPU% lines.

- [ ] **Step 3: Commit**

```bash
git add scripts/load_test/v2/sampler.sh
git commit -m "feat: server-side GPU+container resource sampler"
```

---

### Task 7: Run the Phase A campaign + write Phase A results

**Files:**
- Create: `scripts/load_test/v2/out/phaseA/` (artifacts; gitignored — add to `.gitignore` if not already covered by `out/`)
- Create: `docs/load-capacity-report-2026-07-14.md` (Phase A section; completed in Task 11)

**Interfaces:**
- Consumes: Tasks 3–6 tooling.

- [ ] **Step 1: Confirm idle baseline**

Run: `"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'cat /proc/loadavg; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader'`
Expected: loadavg < 0.5; GPU util ~0%. If busy, wait / investigate before loading.

- [ ] **Step 2: For each service (embed → stt → tts): start sampler, run campaign, stop sampler, pull artifacts**

```bash
# embed
"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'rm -rf /tmp/samp_embed; nohup bash /tmp/sampler.sh /tmp/samp_embed 2 >/tmp/samp_embed.out 2>&1 & echo $! > /tmp/samp_embed.pid'
cd scripts/load_test/v2 && python phase_a_embed.py --hold 90 --max 256 --out out/phaseA/embed
"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'kill $(cat /tmp/samp_embed.pid)'
scp -o StrictHostKeyChecking=no -r thebc@thebc-server.local:/tmp/samp_embed out/phaseA/embed/sampler   # (expect password)

# stt  (repeat with samp_stt / phase_a_stt.py --max 64)
# tts  (repeat with samp_tts / phase_a_tts.py --max 64)  ← watch GPU util pin to 100% at the knee
```
Expected: three `*_RESULTS.md` tables + three sampler dirs. **TTS is expected to knee earliest**, with `gpu.csv` util → ~100% and p95 climbing at/after the knee. Note each service's knee + binding resource (TTS→GPU, STT→CPU threads in `containers.log`, embed→CPU/GPU depending on where the embed model runs).

- [ ] **Step 3: Sanity-check the numbers**

Verify: each `err%` is 0 below the knee and rises (or p95 doubles) at the reported knee; the sampler CSV corroborates the binding resource. If a service shows 0 errors and flat p95 all the way to `--max`, re-run with a higher `--max` (it didn't reach saturation).

- [ ] **Step 4: Commit the results tables (not the large sampler dumps)**

```bash
git add scripts/load_test/v2/out/phaseA/embed/embed_RESULTS.md \
        scripts/load_test/v2/out/phaseA/stt/stt_RESULTS.md \
        scripts/load_test/v2/out/phaseA/tts/tts_RESULTS.md
git commit -m "test: phase A per-service load results"
```

---

### Task 8: `llm_stub.py` — OpenAI-compatible streaming fake

**Files:**
- Create: `scripts/load_test/v2/llm_stub.py`

**Interfaces:**
- Produces: `python llm_stub.py [--port 8099] [--tps 50]` → serves `POST /v1/chat/completions` (stream) with a canned Vietnamese reply as OpenAI `chat.completion.chunk` SSE deltas, paced at `--tps` tokens/sec. Text-only (no tool calls) — see caveat in Task 10.

- [ ] **Step 1: Write the stub**

```python
# scripts/load_test/v2/llm_stub.py
"""Minimal OpenAI-compatible streaming chat endpoint for load-test LLM isolation.

Serves POST /v1/chat/completions with stream=true, emitting a canned Vietnamese
answer as chat.completion.chunk SSE deltas at ~--tps tokens/sec. Deterministic,
no external calls. Text-only (does not emit tool_calls)."""
from __future__ import annotations

import argparse
import asyncio
import json
import time

from aiohttp import web

CANNED = (
    "Dạ em xin phép trả lời câu hỏi của anh chị. Noble hiện có nhiều dự án căn hộ "
    "cao cấp với vị trí đẹp, tiện ích đầy đủ và chính sách thanh toán linh hoạt. "
    "Anh chị quan tâm tới dự án nào để em tư vấn chi tiết hơn ạ."
).split()


def _chunk(model: str, created: int, delta: dict, finish=None) -> str:
    payload = {
        "id": "stub", "object": "chat.completion.chunk", "created": created, "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _handler(request: web.Request) -> web.StreamResponse:
    body = await request.json()
    model = body.get("model", "stub")
    tps = request.app["tps"]
    created = int(time.time())
    resp = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
    await resp.prepare(request)
    await resp.write(_chunk(model, created, {"role": "assistant"}).encode())
    for i, w in enumerate(CANNED):
        await resp.write(_chunk(model, created, {"content": (w if i == 0 else " " + w)}).encode())
        await asyncio.sleep(1.0 / tps)
    await resp.write(_chunk(model, created, {}, finish="stop").encode())
    await resp.write(b"data: [DONE]\n\n")
    await resp.write_eof()
    return resp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--tps", type=float, default=50.0)
    args = ap.parse_args()
    app = web.Application()
    app["tps"] = args.tps
    app.router.add_post("/v1/chat/completions", _handler)
    web.run_app(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Local SSE smoke test**

```bash
pip install aiohttp   # if missing in .venv
python scripts/load_test/v2/llm_stub.py --port 8099 &   # background
sleep 1
curl -sN -X POST http://127.0.0.1:8099/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"stub","stream":true,"messages":[{"role":"user","content":"hi"}]}' | head -5
kill %1
```
Expected: several `data: {...delta...}` lines then `data: [DONE]`. Each line is valid JSON with `choices[0].delta`.

- [ ] **Step 3: Commit**

```bash
git add scripts/load_test/v2/llm_stub.py
git commit -m "feat: OpenAI-compatible streaming LLM stub for infra isolation"
```

---

### Task 9: `phase_b_chat.py` — chat WS load client (`:8766`)

**Files:**
- Create: `scripts/load_test/v2/phase_b_chat.py`

**Interfaces:**
- Consumes: `common.percentiles`, `common.StepResult`, `common.CampaignResult`, `common.is_broken`, `common.write_results_md`.
- Produces: CLI `python phase_b_chat.py [--hold 90] [--max 128] [--out DIR]` → `<out>/chat_RESULTS.md`. Uses **persistent WS sessions** (one per concurrency slot), each looping scripted turns; latency = per-turn (send `user_text` → receive `done`). Trailing `suggestions` events are ignored.

- [ ] **Step 1: Write the client**

```python
# scripts/load_test/v2/phase_b_chat.py
"""Chat-WS end-to-end load client (:8766/chat). Each virtual user holds one WS session
and loops scripted turns; per-turn latency = send user_text → receive `done`.
Reuses common.* for percentiles/break-detection/report."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import websockets
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ENV = dotenv_values(ROOT / ".env")
_HOST = "10.50.12.70"
_PORT = ENV.get("WS_PORT", "8766")
BASE = f"ws://{_HOST}:{_PORT}/chat"

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
        if not isinstance(raw, str):
            continue
        if json.loads(raw).get("type") == "done":
            return time.monotonic() - t0


async def _session_worker(idx: int, deadline: float, latencies: list[float], counters: dict) -> None:
    sid = f"load-{idx}-{int(deadline)}"
    try:
        async with websockets.connect(f"{BASE}?session={sid}", max_size=10 * 1024 * 1024) as ws:
            # drain the initial {"type":"session_id"} greeting
            await asyncio.wait_for(ws.recv(), timeout=10.0)
            i = 0
            while time.monotonic() < deadline:
                text = TURNS[i % len(TURNS)]
                i += 1
                try:
                    latencies.append(await _run_turn(ws, text))
                    counters["ok"] += 1
                except Exception:
                    counters["failed"] += 1
    except Exception:
        counters["failed"] += 1


async def _step(concurrency: int, hold_s: float) -> common.StepResult:
    latencies: list[float] = []
    counters = {"ok": 0, "failed": 0}
    start = time.monotonic()
    deadline = start + hold_s
    await asyncio.gather(*[_session_worker(i, deadline, latencies, counters) for i in range(concurrency)])
    dur = time.monotonic() - start
    total = counters["ok"] + counters["failed"]
    return common.StepResult(
        concurrency=concurrency, duration_s=dur, total=total,
        ok=counters["ok"], failed=counters["failed"],
        latency=common.percentiles(latencies),
        err_rate=(counters["failed"] / total) if total else 0.0,
    )


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=128)
    ap.add_argument("--out", type=Path, default=Path("."))
    args = ap.parse_args()
    print(f"chat load → {BASE}")
    baseline = await _step(1, args.hold)
    baseline_p95 = baseline.latency.get("p95", 0.0)
    result = common.CampaignResult(label="chat :8766", baseline_p95=baseline_p95, steps=[baseline])
    knee = 1
    for c in common.ramp_schedule(max_concurrency=args.max):
        if c <= 1:
            continue
        step = await _step(c, args.hold)
        result.steps.append(step)
        if common.is_broken(step, baseline_p95):
            break
        knee = c
    result.knee = knee
    args.out.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, args.out / "chat_RESULTS.md")
    print(f"knee={result.knee}  → {args.out / 'chat_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
```

- [ ] **Step 2: Smoke-verify against the live server (real gemini, 1 session, short hold)**

Run: `cd scripts/load_test/v2 && python phase_b_chat.py --hold 8 --max 2 --out /tmp/chat_smoke`
Expected: `knee=...`; `/tmp/chat_smoke/chat_RESULTS.md` with ≥1 completed turn at concurrency 1, `err%` = 0. (This smoke uses the real gemini still configured — it confirms the WS turn protocol end-to-end before the stub goes in.)

- [ ] **Step 3: Commit**

```bash
git add scripts/load_test/v2/phase_b_chat.py
git commit -m "feat: chat-WS end-to-end load client (phase B)"
```

---

### Task 10: Deploy the LLM stub, run Phase B campaign, revert

**Files:**
- Create: `scripts/load_test/v2/out/phaseB/chat_RESULTS.md` (artifact)
- Temporary: server `.env` backup at `~/deploy/santa-hotline-agent/.env.loadtest-bak`

**Interfaces:**
- Consumes: Task 8 stub, Task 9 client, Task 6 sampler.

**Caveat (record in the report):** the stub is text-only, so Phase B exercises orchestration + Redis + Mongo + LLM-plumbing but **not** the `noble_search` → Qdrant/embed path (no tool calls). RAG-retrieval load is represented by Phase A's embed test. A tool-calling stub variant is a future extension.

- [ ] **Step 1: Confirm server→Mac reachability, then run the stub on the Mac**

```bash
# Mac LAN IP:
ipconfig getifaddr en0    # note it, e.g. 10.50.12.206
python scripts/load_test/v2/llm_stub.py --port 8099 --tps 50 &   # leave running
# from the server, confirm it can reach the Mac stub:
"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'curl -sN -m 5 -X POST http://<MAC_IP>:8099/v1/chat/completions -H "Content-Type: application/json" -d "{\"model\":\"stub\",\"stream\":true,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}" | head -3'
```
Expected: the server prints `data: {...}` lines. **If the server cannot reach the Mac**, instead copy `llm_stub.py` to the server and run it on-box (`http://127.0.0.1:8099`), installing `aiohttp` in whatever Python/venv is available there; use `127.0.0.1` in Step 2.

- [ ] **Step 2: Back up + repoint the agent's LLM to the stub, recreate containers**

```bash
"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'cd ~/deploy/santa-hotline-agent && cp .env .env.loadtest-bak && \
  sed -i "s#^OPENAI_BASE_URL=.*#OPENAI_BASE_URL=http://<MAC_IP>:8099/v1#" .env && \
  sed -i "s#^OPENAI_MODEL=.*#OPENAI_MODEL=stub#" .env && \
  sed -i "s#^NOBLE_AGENT_MODEL=.*#NOBLE_AGENT_MODEL=stub#" .env && \
  sed -i "s#^NOBLE_SUMMARY_MODEL=.*#NOBLE_SUMMARY_MODEL=stub#" .env && \
  sed -i "s#^NOBLE_SUGGESTIONS_MODEL=.*#NOBLE_SUGGESTIONS_MODEL=stub#" .env && \
  grep -qxF "OPENAI_API_KEY=stub" .env || echo "OPENAI_API_KEY=stub" >> .env && \
  docker compose -f docker-compose.local.yml up -d agent agent-lk'
sleep 8
curl -s http://10.50.12.70:8766/api/config
```
Expected: `/api/config` still reports `"model": "gemini-2.5-flash"` in the `llm` block (that field echoes `ANTHROPIC_MODEL`/display config, not the runtime pin) — the real check is that a chat turn now returns the canned stub text. Verify with one turn:
`cd scripts/load_test/v2 && python phase_b_chat.py --hold 6 --max 1 --out /tmp/chat_stub_check` → the turn completes fast (stub ~50 tok/s, no external latency) and `err%` = 0. If turns error, check the stub is reachable from the container and `NOBLE_AGENT_MODEL=stub` resolves to the openai slot.

- [ ] **Step 3: Run the Phase B campaign with the sampler**

```bash
"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'rm -rf /tmp/samp_chat; nohup bash /tmp/sampler.sh /tmp/samp_chat 2 >/tmp/samp_chat.out 2>&1 & echo $! > /tmp/samp_chat.pid'
cd scripts/load_test/v2 && python phase_b_chat.py --hold 90 --max 128 --out out/phaseB
"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'kill $(cat /tmp/samp_chat.pid)'
scp -o StrictHostKeyChecking=no -r thebc@thebc-server.local:/tmp/samp_chat out/phaseB/sampler   # (expect password)
```
Expected: `out/phaseB/chat_RESULTS.md` with a knee; `containers.log` shows `agent`/`agent-lk` CPU% climbing toward saturation of the box's threads at the knee (Redis/Mongo/Qdrant CPU also visible). Binding resource expected = CPU.

- [ ] **Step 4: Revert the stub + verify**

```bash
"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'cd ~/deploy/santa-hotline-agent && mv .env.loadtest-bak .env && \
  docker compose -f docker-compose.local.yml up -d agent agent-lk'
sleep 8
curl -s http://10.50.12.70:8766/api/config
# kill the Mac stub:
kill %1 2>/dev/null || pkill -f llm_stub.py
```
Expected: `.env` restored (diff against git-tracked `.env.example` keys if unsure); a chat turn again produces varied gemini text (not the canned stub sentence). **This revert step is mandatory** — do not leave the server pointed at the stub.

- [ ] **Step 5: Commit the results table**

```bash
git add scripts/load_test/v2/out/phaseB/chat_RESULTS.md
git commit -m "test: phase B chat end-to-end load results (LLM stubbed)"
```

---

### Task 11: Synthesize the capacity report + README + cleanup

**Files:**
- Create: `docs/load-capacity-report-2026-07-14.md`
- Create: `scripts/load_test/v2/README.md`
- Modify: `.gitignore` (add `scripts/load_test/v2/out/**/sampler/` if not covered)

**Interfaces:**
- Consumes: all prior results + sampler CSVs.

- [ ] **Step 1: Write the README (run recipes + revert checklist)**

```markdown
# Load test v2 — santa-hotline-agent

Stress-to-break tooling. Load runs from the Mac over LAN → `10.50.12.70`;
resource sampling runs on the server. Replaces the dead sipp harness in
`scripts/load_test/` (self-hosted LiveKit SIP no longer exists).

## Layout
- `common.py`      — ramp / async step driver / percentiles / break-detection / report writer (unit-tested: `pytest test_common.py`)
- `phase_a_*.py`   — per-service load clients: embed (:8013), tts (:8011), stt (:8012)
- `phase_b_chat.py`— chat-WS end-to-end (:8766), persistent sessions
- `llm_stub.py`    — OpenAI-compatible streaming fake (Phase B infra isolation)
- `sampler.sh`     — server-side nvidia-smi + docker stats sampler (run over SSH)

## Breaking point
Hold each concurrency step ~90 s. Break = p95 > 2× warm baseline, or err > 1%,
or a server resource pinned. Reported "knee" = last healthy step.

## Run
Phase A (no server change):
    python phase_a_embed.py --hold 90 --max 256 --out out/phaseA/embed
    python phase_a_stt.py   --hold 90 --max 64  --out out/phaseA/stt
    python phase_a_tts.py   --hold 90 --max 64  --out out/phaseA/tts
Sampler (on server, per run): `bash /tmp/sampler.sh /tmp/samp 2 &`

Phase B (stub LLM — see the revert checklist!):
    python llm_stub.py --port 8099 &
    # repoint server .env OPENAI_BASE_URL/OPENAI_MODEL + NOBLE_*_MODEL=stub, recreate agent/agent-lk
    python phase_b_chat.py --hold 90 --max 128 --out out/phaseB

## Revert checklist (Phase B) — MANDATORY
1. `mv .env.loadtest-bak .env` on the server, `docker compose -f docker-compose.local.yml up -d agent agent-lk`.
2. Verify a chat turn returns varied gemini text (not the canned stub sentence).
3. Kill the Mac stub (`pkill -f llm_stub.py`).
```

- [ ] **Step 2: Write the capacity report from the collected results**

Assemble `docs/load-capacity-report-2026-07-14.md` with these sections (fill numbers from `out/phaseA/*` + `out/phaseB/chat_RESULTS.md` + the sampler CSVs):

```markdown
# Load / Capacity Report — santa-hotline-agent (2026-07-14)

## Environment
i5-14600KF (20 threads), 30 GiB RAM, 1× RTX 5060 Ti 16 GB. Single box, shared with
santa-chat-agent + CMS + logging + Phoenix. Load from Mac over LAN (~0.6 ms RTT).
Phase B LLM stubbed (text-only) to isolate infra.

## Results (knee = max sustainable concurrency at default break criteria)
| Channel | Warm p95 | Knee | Binding resource | Evidence |
|---|---:|---:|---|---|
| TTS (:8011) | … | … | GPU (serial synth) | gpu.csv util→100% |
| STT (:8012) | … | … | CPU threads | containers.log |
| embed (:8013) | … | … | … | … |
| chat E2E (:8766) | … | … | CPU (agent orchestration) | containers.log |

## Interpretation
- Voice concurrent-call ceiling ≈ TTS knee (TTS is the sole GPU tenant, serial). One
  call ties up the GPU for the synth duration; N concurrent calls serialize.
- STT/embed headroom vs the TTS ceiling.
- Chat ceiling (CPU) vs voice ceiling (GPU) — which binds first for a mixed workload.

## Recommendations
- If TTS-GPU is the ceiling: micro-batching / a second GPU / faster-or-quantized codec /
  a hard cap on concurrent audio sessions with a queue.
- Co-tenancy: heavy hotline load competes with santa-chat-agent for the 20 threads.

## Caveats
- Phase B stub is text-only → Qdrant/embed RAG path not exercised in chat E2E (covered by Phase A embed).
- Phase C (WebRTC + LiveKit-Cloud voice) deferred; voice ceiling inferred from TTS.
```

- [ ] **Step 3: Ensure sampler dumps are gitignored, commit report + README**

```bash
grep -q 'load_test/v2/out' .gitignore || echo 'scripts/load_test/v2/out/**/sampler/' >> .gitignore
git add docs/load-capacity-report-2026-07-14.md scripts/load_test/v2/README.md .gitignore
git commit -m "docs: hotline load/capacity report + load-test v2 README"
```

- [ ] **Step 4: Final cleanup verification**

Run: `curl -s http://10.50.12.70:8766/api/config` and one `phase_b_chat.py --hold 5 --max 1` turn.
Expected: chat returns varied (non-stub) text → server is back to gemini. `pgrep -f llm_stub.py` on the Mac returns nothing. Server `/tmp/samp*` dirs removed: `"$CLAUDE_JOB_DIR/tmp/rsh.exp" 'rm -rf /tmp/samp*'`.

---

## Self-Review

**Spec coverage:**
- §5 Phase A embed/stt/tts → Tasks 3/5/4 + run Task 7. ✓
- §6 Phase B chat → Task 9 + run Task 10. ✓
- §4 observation (sampler + Mongo + Phoenix) → Task 6 sampler; Mongo/Phoenix rollup available (reader confirmed from Mac) and folded into report interpretation (Task 11). Note: the plan leans on the sampler + client-side latency as primary; Mongo `session_metrics` per-stage is an optional deepening in the report, not a separate task.
- §7 LLM stub → Task 8 + Task 10 deploy/revert. ✓
- §3 breaking-point definition → `is_broken` (Task 1) + hold/ramp (Task 2), applied in all campaigns. ✓
- §9 deliverable report → Task 11. ✓
- §10 safety/cleanup → Task 10 Step 4 + Task 11 Step 4. ✓
- §11 Phase C deferred → recorded as a report caveat. ✓
- §12 file layout → matches Tasks 1–8 + README (Task 11). ✓

**Placeholder scan:** report tables in Task 11 use `…` as data-fill markers (numbers come from live runs — legitimately unknowable at plan time), not as un-specified code. `<MAC_IP>` is a runtime value captured in Task 10 Step 1. All code steps contain complete code.

**Type consistency:** `StepResult` / `CampaignResult` fields (`concurrency`, `duration_s`, `total`, `ok`, `failed`, `latency`, `err_rate`, `knee`, `baseline_p95`, `steps`) are used identically across `common.py`, `phase_b_chat.py`, and the tests. `make_request` signature (`() -> Awaitable[float]`) is consistent across `run_step`, `run_campaign`, and all Phase A clients. `write_results_md(result, path)` and `is_broken(step, baseline_p95, …)` signatures match every call site.
