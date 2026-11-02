"""Orchestrate a sipp load-test run against the LiveKit SIP → agent worker.

Responsibilities:
1. Ensure the PCMU pcap fixture exists (regenerate if stale).
2. Spawn sipp with `scripts/load_test/docs/scenarios/basic_call.xml`, tee its stdout.
3. Sample RSS of the agent worker PID at 5 s intervals while sipp runs.
4. Write `scripts/load_test/docs/LOAD_TEST_RESULTS.md` summarising:
   - sipp stats (successful / failed calls, INVITE→200 latency)
   - memory trace (RSS samples + peak)

Prereqs (check before running):
- `sipp` on PATH (`brew install sipp`).
- LiveKit + LiveKit-SIP up: `docker compose --profile livekit up -d`.
- Worker running: `uv run python -m noble_agent --transport livekit`.

Usage:
    # 1 call smoke test (default)
    uv run python scripts/load_test/run_load_test.py --concurrent 1 --calls 1

    # 10-concurrent / 30-minute soak
    uv run python scripts/load_test/run_load_test.py \\
        --concurrent 10 --duration 1800

    # Custom target (non-default SIP host/port or trunk number)
    uv run python scripts/load_test/run_load_test.py \\
        --concurrent 50 --duration 3600 \\
        --sip-target 127.0.0.1:5060 --sip-service +84999000001

Safety:
- Defaults to 1 call / 1 concurrent so an accidental `make loadtest` doesn't
  hammer a real env. Scale up explicitly.
- `--dry-run` prints the sipp command without executing it.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCENARIO_DIR = ROOT / "tests" / "load" / "scenarios"
DEFAULT_SCENARIO = SCENARIO_DIR / "basic_call.xml"
PCAP = ROOT / "tests" / "load" / "fixtures" / "utterance_pcmu.pcap"
DEFAULT_ACK_ASSET = ROOT / "assets" / "voice" / "acks" / "01_em_can_kiem_tra_thong_tin_trong_he_thong_quy_khach.pcm"
RESULTS = ROOT / "tests" / "load" / "LOAD_TEST_RESULTS.md"


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class RunConfig:
    concurrent: int
    calls: int              # -m <calls>, 0 means run for --duration
    duration_s: int         # 0 means run until --calls complete
    rate: int               # -r <rate>
    rate_period_ms: int     # -rp <ms>
    sip_target: str         # host[:port]
    sip_service: str        # Request-URI user (trunk number)
    scenario: Path          # sipp scenario XML
    worker_pid: int | None  # for RSS sampling
    dry_run: bool


@dataclass
class SippResult:
    returncode: int
    stdout_path: Path
    stats_path: Path | None
    duration_s: float


@dataclass
class MemSample:
    ts: float
    rss_kb: int


@dataclass
class RunReport:
    started_at: str
    finished_at: str
    config: RunConfig
    sipp: SippResult
    mem_samples: list[MemSample] = field(default_factory=list)
    sipp_stats: dict | None = None


# ── Fixture management ───────────────────────────────────────────────────────

def ensure_pcap() -> None:
    if PCAP.exists():
        return
    print(f"note: {PCAP} missing — regenerating from {DEFAULT_ACK_ASSET.name}")
    if not DEFAULT_ACK_ASSET.exists():
        print(
            "error: default ack asset not found; run `uv run python scripts/gen_ack_assets.py` first",
            file=sys.stderr,
        )
        sys.exit(2)
    gen = ROOT / "scripts" / "load_test" / "gen_pcap.py"
    subprocess.run(
        [
            sys.executable, str(gen),
            "--in", str(DEFAULT_ACK_ASSET),
            "--raw", "--rate", "24000",
            "--out", str(PCAP),
        ],
        check=True,
    )


# ── sipp runner ──────────────────────────────────────────────────────────────

def build_sipp_cmd(cfg: RunConfig, out_dir: Path) -> list[str]:
    stats_csv = out_dir / "sipp_stats.csv"
    cmd: list[str] = [
        "sipp",
        cfg.sip_target,
        "-sf", str(cfg.scenario),
        "-s", cfg.sip_service,
        "-l", str(cfg.concurrent),          # max concurrent calls
        "-r", str(cfg.rate),                # new calls per period
        "-rp", str(cfg.rate_period_ms),
        "-trace_stat", "-stf", str(stats_csv),
        "-trace_err",
        "-error_file", str(out_dir / "sipp_errors.log"),
        "-nostdin",
        "-p", "5061",                        # local SIP port (avoid 5060)
        # Explicit media IP + base port — without these sipp tries to auto-
        # detect via a raw IPv4 socket, which macOS blocks without root
        # (`Can't create raw IPv4 socket: Operation not permitted`).
        "-mi", "127.0.0.1",
        "-mp", "40000",
    ]

    if cfg.calls > 0:
        cmd.extend(["-m", str(cfg.calls)])

    if cfg.duration_s > 0 and cfg.calls == 0:
        # sipp has no native duration flag; we enforce via timeout.
        pass

    return cmd


async def run_sipp(cfg: RunConfig, out_dir: Path) -> SippResult:
    cmd = build_sipp_cmd(cfg, out_dir)
    stdout_path = out_dir / "sipp_stdout.log"
    stats_path = out_dir / "sipp_stats.csv"

    print("sipp cmd:")
    print("  " + " ".join(cmd))
    if cfg.dry_run:
        return SippResult(returncode=0, stdout_path=stdout_path, stats_path=None, duration_s=0.0)

    started = time.monotonic()
    with stdout_path.open("w") as fout:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=fout,
            stderr=asyncio.subprocess.STDOUT,
        )

        timeout = cfg.duration_s if (cfg.duration_s > 0 and cfg.calls == 0) else None
        try:
            rc = await asyncio.wait_for(proc.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            print(f"reached --duration {cfg.duration_s}s — signalling sipp SIGTERM")
            proc.send_signal(signal.SIGTERM)
            try:
                rc = await asyncio.wait_for(proc.wait(), timeout=10)
            except asyncio.TimeoutError:
                proc.kill()
                rc = await proc.wait()
    duration = time.monotonic() - started

    return SippResult(
        returncode=rc,
        stdout_path=stdout_path,
        stats_path=stats_path if stats_path.exists() else None,
        duration_s=duration,
    )


# ── Memory sampler ───────────────────────────────────────────────────────────

async def sample_worker_rss(pid: int, interval_s: float, stop: asyncio.Event) -> list[MemSample]:
    """RSS via `ps -o rss= -p <pid>` every interval_s until stop is set."""
    samples: list[MemSample] = []
    while not stop.is_set():
        try:
            out = subprocess.check_output(["ps", "-o", "rss=", "-p", str(pid)], text=True).strip()
            rss_kb = int(out.split()[0]) if out else 0
            samples.append(MemSample(ts=time.time(), rss_kb=rss_kb))
        except (subprocess.CalledProcessError, ValueError):
            # worker died or bad output — stop sampling
            break
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except asyncio.TimeoutError:
            pass
    return samples


def parse_sipp_stats(stats_path: Path | None) -> dict | None:
    """Extract total successful / failed / response-time stats from sipp csv."""
    if not stats_path or not stats_path.exists():
        return None
    # sipp writes a single-line header then one row per interval; last row
    # has cumulative counters. We grab the last non-empty line.
    last = None
    header = None
    with stats_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if header is None:
                header = line.split(";")
                continue
            last = line
    if not header or not last:
        return None
    cols = last.split(";")
    row = dict(zip(header, cols))
    # Interesting columns from sipp docs:
    keys = [
        "CurrentCall", "TotalCallCreated", "SuccessfulCall(C)", "FailedCall(C)",
        "ResponseTime1", "ResponseTime1StDev", "CallLength", "CallLengthStDev",
        "FailedCallCannotSendMessage(C)", "FailedCallMaxUdpRetrans(C)",
        "FailedCallUnexpectedMessage(C)",
    ]
    return {k: row.get(k, "") for k in keys if k in row}


# ── Report writer ────────────────────────────────────────────────────────────

def _fmt_mem(samples: list[MemSample]) -> str:
    if not samples:
        return "_no samples (worker PID not provided or died early)_"
    peak = max(s.rss_kb for s in samples)
    first = samples[0].rss_kb
    last = samples[-1].rss_kb
    return (
        f"- samples: {len(samples)}  interval: 5s\n"
        f"- first RSS: {first/1024:.1f} MiB\n"
        f"- last  RSS: {last/1024:.1f} MiB\n"
        f"- peak  RSS: {peak/1024:.1f} MiB\n"
        f"- drift (last - first): {(last - first)/1024:+.1f} MiB"
    )


def write_report(report: RunReport, out_path: Path) -> None:
    cfg = report.config
    sipp = report.sipp
    lines = [
        f"# Load Test Run — {report.started_at}",
        "",
        f"- scenario: `{cfg.scenario.relative_to(ROOT)}`",
        f"- concurrent: **{cfg.concurrent}**  calls: {cfg.calls or 'open'}  duration_s: {cfg.duration_s or 'until calls complete'}",
        f"- rate: {cfg.rate}/{cfg.rate_period_ms}ms",
        f"- sip target: `{cfg.sip_target}`  service: `{cfg.sip_service}`",
        f"- worker PID sampled: {cfg.worker_pid or 'n/a'}",
        "",
        "## sipp",
        f"- wall duration: {sipp.duration_s:.1f}s",
        f"- return code: {sipp.returncode}  (0 = all calls accepted)",
        f"- stdout: `{sipp.stdout_path.relative_to(ROOT) if sipp.stdout_path.is_relative_to(ROOT) else sipp.stdout_path}`",
    ]
    if report.sipp_stats:
        lines.append("")
        lines.append("### sipp counters (last row of `-trace_stat` csv)")
        for k, v in report.sipp_stats.items():
            lines.append(f"- {k}: {v}")

    lines += [
        "",
        "## Worker memory (RSS)",
        _fmt_mem(report.mem_samples),
        "",
        "---",
        f"Generated by `scripts/load_test/run_load_test.py` at {report.finished_at}.",
        "",
    ]

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"→ {out_path}")


# ── Main ─────────────────────────────────────────────────────────────────────

def _parse_args() -> RunConfig:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--concurrent", type=int, default=1, help="max concurrent calls (sipp -l)")
    ap.add_argument("--calls", type=int, default=1,
                    help="total calls to complete (sipp -m). 0 = open-ended, use --duration.")
    ap.add_argument("--duration", type=int, default=0,
                    help="seconds to run before terminating sipp (only if --calls=0)")
    ap.add_argument("--rate", type=int, default=1, help="new-call rate (sipp -r)")
    ap.add_argument("--rate-period-ms", type=int, default=1000, help="rate period in ms (sipp -rp)")
    ap.add_argument("--sip-target", default="127.0.0.1:5060",
                    help="LiveKit SIP host:port")
    ap.add_argument("--sip-service", default="+84999000001",
                    help="Request-URI user — must match a trunk number in sip.yaml")
    ap.add_argument("--worker-pid", type=int, default=0,
                    help="agent worker PID for RSS sampling (0 = skip)")
    ap.add_argument("--scenario", type=Path, default=DEFAULT_SCENARIO,
                    help=f"sipp scenario XML (default: {DEFAULT_SCENARIO.relative_to(ROOT)}). "
                         f"Use scenarios/basic_call_audio.xml for the full STT→LLM path "
                         f"(needs sudo on macOS).")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.calls == 0 and args.duration == 0:
        ap.error("either --calls >0 or --duration >0 must be set")

    scenario = args.scenario if args.scenario.is_absolute() else (ROOT / args.scenario)
    if not scenario.exists():
        ap.error(f"scenario not found: {scenario}")

    return RunConfig(
        concurrent=args.concurrent,
        calls=args.calls,
        duration_s=args.duration,
        rate=args.rate,
        rate_period_ms=args.rate_period_ms,
        sip_target=args.sip_target,
        sip_service=args.sip_service,
        scenario=scenario,
        worker_pid=args.worker_pid or None,
        dry_run=args.dry_run,
    )


async def _main_async() -> int:
    if not shutil.which("sipp"):
        print("error: `sipp` not on PATH — install with `brew install sipp`", file=sys.stderr)
        return 2

    cfg = _parse_args()
    # Only regenerate the audio pcap when the audio scenario is in use.
    if "audio" in cfg.scenario.stem:
        ensure_pcap()

    out_dir = ROOT / "tests" / "load" / "out" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)

    stop_mem = asyncio.Event()
    mem_task = None
    if cfg.worker_pid:
        mem_task = asyncio.create_task(sample_worker_rss(cfg.worker_pid, 5.0, stop_mem))

    started_iso = datetime.now(timezone.utc).isoformat()
    sipp_result = await run_sipp(cfg, out_dir)

    if cfg.dry_run:
        print("dry-run: skipping aggregation + report write")
        return 0

    stop_mem.set()
    mem_samples: list[MemSample] = []
    if mem_task:
        mem_samples = await mem_task

    sipp_stats = parse_sipp_stats(sipp_result.stats_path)


    report = RunReport(
        started_at=started_iso,
        finished_at=datetime.now(timezone.utc).isoformat(),
        config=cfg,
        sipp=sipp_result,
        mem_samples=mem_samples,
        sipp_stats=sipp_stats,
    )

    (out_dir / "mem_samples.json").write_text(
        json.dumps([{"ts": s.ts, "rss_kb": s.rss_kb} for s in mem_samples], indent=2),
        encoding="utf-8",
    )
    write_report(report, out_dir / "LOAD_TEST_RESULTS.md")
    # Also update the top-level canonical copy for quick inspection.
    write_report(report, RESULTS)

    return sipp_result.returncode


def main() -> None:
    sys.exit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
