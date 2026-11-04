"""CLI: python -m synthetic --num-conversations N --max-turns M --output PATH

Generates synthetic CA↔Noble conversations and appends them to a JSONL file
matching `data/eval_processed/eval_sft.json`.

Examples:
    # Default: 10 convos × ≤8 turns → data/synthetic_sft/{ts}.jsonl
    python -m synthetic

    # 50 convos, 8-way parallel, persona sampling seeded
    python -m synthetic --num-conversations 50 --concurrency 8 --seed 42

    # Drive CA with a specific persona only (e.g. for debugging)
    python -m synthetic --persona angry_postsale_paperwork --num-conversations 3
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path


def _fmt_dur(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m{s:02d}s"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# Make `src/` importable without `pip install -e .`
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


async def _amain(args: argparse.Namespace) -> int:
    # Imports deferred until after sys.path tweak above.
    from noble_agent.agent.facade import _get_runner
    from noble_agent.tenant.current import current_tenant
    from synthetic.ca_client import CustomerAgentClient
    from synthetic.config import get_synthetic_settings
    from synthetic.personas import PERSONAS, get_persona, sample_persona
    from synthetic.runner import run_conversation

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not args.verbose:
        for noisy in ("httpx", "httpcore", "openai", "anthropic", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.ERROR)

    settings = get_synthetic_settings()
    ca = CustomerAgentClient(settings)

    rng = random.Random(args.seed) if args.seed is not None else random.Random()

    output_path = Path(args.output) if args.output else _default_output()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if args.persona:
        fixed_persona = get_persona(args.persona)
        picker = lambda: fixed_persona  # noqa: E731
    else:
        picker = lambda: sample_persona(rng)  # noqa: E731

    concurrency = max(1, args.concurrency)
    print(
        f"[synthetic] provider={settings.provider} model={settings.model} "
        f"convos={args.num_conversations} max_turns={args.max_turns} "
        f"concurrency={concurrency} output={output_path}",
        flush=True,
    )
    print(f"[synthetic] personas available: {len(PERSONAS)}", flush=True)

    # Warm the Noble runner singleton once before launching workers so all
    # parallel conversations share the same already-built TurnRunner.
    await _get_runner(current_tenant(), "chat")

    semaphore = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()
    counter = {"succeeded": 0, "failed": 0, "completed": 0, "running": 0}
    total = args.num_conversations
    started_at = time.monotonic()

    # Append-mode so re-runs accumulate; output filename has timestamp by
    # default so cross-run mixing only happens when the user opts in.
    f = output_path.open("a", encoding="utf-8")

    async def _heartbeat() -> None:
        """Periodic progress line so the user knows the job is alive + ETA."""
        interval = max(1, args.progress_interval)
        while True:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return
            done = counter["completed"]
            elapsed = time.monotonic() - started_at
            rate = done / elapsed if elapsed > 0 else 0
            remaining = total - done
            eta = remaining / rate if rate > 0 else 0
            pct = (done / total * 100) if total else 100
            print(
                f"[progress] {done}/{total} ({pct:.0f}%) | "
                f"running={counter['running']} ok={counter['succeeded']} "
                f"fail={counter['failed']} | "
                f"elapsed={_fmt_dur(elapsed)} eta={_fmt_dur(eta) if rate > 0 else '?'} | "
                f"rate={rate * 60:.1f}/min",
                flush=True,
            )

    async def _one(idx: int, persona) -> None:
        async with semaphore:
            async with write_lock:
                counter["running"] += 1
            tag = f"[{idx + 1}/{total}] persona={persona.label}"
            try:
                record = await run_conversation(
                    persona=persona,
                    ca=ca,
                    max_turns=args.max_turns,
                )
            except Exception as exc:  # noqa: BLE001
                async with write_lock:
                    counter["failed"] += 1
                    counter["completed"] += 1
                    counter["running"] -= 1
                    print(
                        f"[synthetic] {tag} FAIL ({exc.__class__.__name__}: {exc}) ({counter['completed']}/{total})",
                        flush=True,
                    )
                return

            if record["turns"] == 0:
                async with write_lock:
                    counter["failed"] += 1
                    counter["completed"] += 1
                    counter["running"] -= 1
                    print(
                        f"[synthetic] {tag} skip (0 turns) ({counter['completed']}/{total})",
                        flush=True,
                    )
                return

            line = json.dumps(record, ensure_ascii=False) + "\n"
            async with write_lock:
                f.write(line)
                f.flush()
                counter["succeeded"] += 1
                counter["completed"] += 1
                counter["running"] -= 1
                print(
                    f"[synthetic] {tag} ok turns={record['turns']} "
                    f"msgs={len(record['messages'])} "
                    f"ended_naturally={record['ended_naturally']} "
                    f"({counter['completed']}/{total})",
                    flush=True,
                )

    heartbeat_task = asyncio.create_task(_heartbeat()) if args.progress_interval > 0 else None
    try:
        await asyncio.gather(*(_one(i, picker()) for i in range(total)))
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task
        f.close()

    elapsed = time.monotonic() - started_at
    print(
        f"[synthetic] done — succeeded={counter['succeeded']} "
        f"failed={counter['failed']} elapsed={_fmt_dur(elapsed)} → {output_path}",
        flush=True,
    )
    return 0 if counter["succeeded"] > 0 else 1


def _default_output() -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path("data/synthetic_sft") / f"{ts}.jsonl"


def main() -> None:
    p = argparse.ArgumentParser(description="Synthesize Noble Agent SFT data via Customer Agent")
    p.add_argument("--num-conversations", "-n", type=int, default=10)
    p.add_argument("--max-turns", "-t", type=int, default=8, help="Max user turns per conversation")
    p.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=4,
        help="How many conversations to run in parallel (default: 4)",
    )
    p.add_argument(
        "--output",
        "-o",
        default=None,
        help="Output JSONL path (default: data/synthetic_sft/{timestamp}.jsonl)",
    )
    p.add_argument(
        "--persona",
        default=None,
        help="Pin a single persona label (else random from personas.PERSONAS)",
    )
    p.add_argument("--seed", type=int, default=None, help="Random seed for persona sampling")
    p.add_argument(
        "--progress-interval",
        type=int,
        default=5,
        help="Seconds between [progress] heartbeat lines (0 to disable, default: 5)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    try:
        rc = asyncio.run(_amain(args))
    except KeyboardInterrupt:
        rc = 130
    sys.exit(rc)


if __name__ == "__main__":
    main()
