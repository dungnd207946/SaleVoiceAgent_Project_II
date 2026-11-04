"""CLI: PYTHONPATH=src python -m eval run|score ...

run   — teacher forcing: write data/eval_results/<slug>/predictions.jsonl
score — metrics: write details.jsonl + report.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from eval.config import EvalSettings
from eval.data import enumerate_turns, load_eval_file
from eval.report import build_report
from eval.runner import existing_keys, sample_from_row, score_prediction_row, write_manifest


def _run_dir(cfg: EvalSettings, slug: str) -> Path:
    d = Path(cfg.results_dir) / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


async def _cmd_run(args) -> int:
    from eval.predict import build_predictor, predict_turn

    cfg = EvalSettings()
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    slug = f"{stamp}_{args.slug}"
    out_dir = _run_dir(cfg, slug)
    pred_path = out_dir / "predictions.jsonl"

    records = load_eval_file(args.eval_file or cfg.eval_file)
    samples = [s for rec in records for s in enumerate_turns(rec)]
    if args.limit:
        samples = samples[: args.limit]

    done = existing_keys(pred_path)
    todo = [s for s in samples if s.dedup_key() not in done]

    if not todo:
        print(f"[run] nothing to do — all {len(samples)} samples already in {pred_path}")
        return 0

    client, model, primary = build_predictor()
    temperature = args.temperature if args.temperature is not None else cfg.temperature
    workers = args.workers or cfg.workers
    sem = asyncio.Semaphore(workers)
    lock = asyncio.Lock()
    counter = {"ok": 0, "fail": 0}

    async def _one(sample) -> None:
        async with sem:
            try:
                predicted = await predict_turn(
                    client,
                    sample,
                    model=model,
                    primary=primary,
                    temperature=temperature,
                    max_tokens=cfg.max_tokens,
                )
            except Exception as e:  # noqa: BLE001
                counter["fail"] += 1
                print(f"[run] FAIL {sample.dedup_key()}: {e}")
                return
            row = {
                "conversation_id": sample.conversation_id,
                "turn_idx": sample.turn_idx,
                "step_idx_in_turn": sample.step_idx_in_turn,
                "is_first_assistant": sample.is_first_assistant,
                "is_final_assistant": sample.is_final_assistant,
                "user_message": sample.user_message,
                "prefix": sample.prefix,
                "reference_response": sample.reference_response,
                "predicted_response": predicted,
                "tools": sample.tools,
            }
            line = json.dumps(row, ensure_ascii=False) + "\n"
            async with lock:
                with open(pred_path, "a", encoding="utf-8") as f:
                    f.write(line)
                counter["ok"] += 1

    await asyncio.gather(*(_one(s) for s in todo))

    from noble_agent.config import get_settings

    write_manifest(
        out_dir / "eval_manifest.json",
        {
            "started_at": stamp,
            "slug": slug,
            "eval_file": args.eval_file or cfg.eval_file,
            "agent_model": get_settings().agent_model,
            "primary_provider": primary,
            "n_conv": len(records),
            "n_samples": len(samples),
            "resume_skipped": len(samples) - len(todo),
            "temperature": temperature,
            "workers": workers,
        },
    )
    print(f"[run] done slug={slug} ok={counter['ok']} fail={counter['fail']} skipped={len(samples) - len(todo)}")
    print(f"[run] -> {pred_path}")
    return 0


async def _cmd_score(args) -> int:
    cfg = EvalSettings()
    out_dir = Path(cfg.results_dir) / args.slug
    pred_path = out_dir / "predictions.jsonl"
    if not pred_path.exists():
        print(f"[score] missing {pred_path} -- run the `run` phase first")
        return 1

    pred_rows = load_eval_file(pred_path)
    if args.limit:
        pred_rows = pred_rows[: args.limit]

    threshold = args.tfidf_threshold if args.tfidf_threshold is not None else cfg.tfidf_threshold
    mode = args.response_eval
    workers = args.workers or cfg.workers

    judge_lookup = None
    if mode in ("llm", "both"):
        from eval.response_llm import build_critic, judge_turn

        critic, critic_model = build_critic()
        if args.critic_model:
            critic_model = args.critic_model
        jsem = asyncio.Semaphore(workers)

        async def _judge(row):
            async with jsem:
                try:
                    return await judge_turn(critic, sample_from_row(row), row["predicted_response"], model=critic_model)
                except Exception as e:  # noqa: BLE001
                    print(f"[score] judge FAIL {row.get('conversation_id')} t{row.get('turn_idx')}: {e}")
                    return None

        results = await asyncio.gather(*(_judge(r) for r in pred_rows))
        cache = {
            (r["conversation_id"], r["turn_idx"], r["step_idx_in_turn"]): res
            for r, res in zip(pred_rows, results, strict=True)
        }

        def judge_lookup(sample, _predicted):  # noqa: F811
            return cache.get(sample.dedup_key())

    details = [
        score_prediction_row(r, response_eval_mode=mode, tfidf_threshold=threshold, judge=judge_lookup)
        for r in pred_rows
    ]

    with open(out_dir / "details.jsonl", "w", encoding="utf-8") as f:
        for row in details:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    report = build_report(
        details, slug=args.slug, eval_file=cfg.eval_file, response_eval_mode=mode, tfidf_threshold=threshold
    )
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[score] slug={args.slug} turns={report['summary']['n_total_turns']} mode={mode}")
    print(f"[score] fc={report['summary']['fc_metrics']}")
    print(f"[score] -> {out_dir / 'report.json'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="eval", description="Teacher-forcing eval for synthetic SFT data")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("run", help="generate predictions via teacher forcing")
    pr.add_argument("--slug", required=True)
    pr.add_argument("--eval-file", default=None)
    pr.add_argument("--temperature", type=float, default=None)
    pr.add_argument("--workers", type=int, default=None)
    pr.add_argument("--limit", type=int, default=None)

    ps = sub.add_parser("score", help="score predictions")
    ps.add_argument("--slug", required=True)
    ps.add_argument("--response-eval", choices=["rule", "llm", "both"], default="both")
    ps.add_argument("--critic-model", default=None)
    ps.add_argument("--tfidf-threshold", type=float, default=None)
    ps.add_argument("--workers", type=int, default=None)
    ps.add_argument("--limit", type=int, default=None)

    args = parser.parse_args()
    if args.cmd == "run":
        return asyncio.run(_cmd_run(args))
    return asyncio.run(_cmd_score(args))


if __name__ == "__main__":
    raise SystemExit(main())
