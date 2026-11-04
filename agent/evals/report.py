"""TREND.md — bề mặt monitoring định kỳ, sinh từ registry.jsonl (spec §9.2). Thuần."""

from __future__ import annotations

_KIND_METRICS: dict[str, tuple[str, ...]] = {
    "quality": (
        "policy_pass_rate",
        "arg_accuracy",
        "tool_selection_accuracy",
        "banned_call_rate",
        "ttft_p95_ms",
        "answer_correctness_mean",
        "grounded_rate",
        "context_retention_score",
    ),
    "rag": (
        "recall_at_1",
        "recall_at_5",
        "context_recall_at_5",
        "mrr",
        "empty_rate",
        "retrieval_p95_ms",
        "faithfulness_rate",
    ),
    "bench": (
        "stt_total_p95_ms",
        "tts_ttfb_p95_ms",
        "speaker_total_p95_ms",
        "vad_chunk_p95_ms",
        "llm_ttft_p95_ms",
    ),
    "load": ("knee_ccu", "p95_at_knee_ms", "err_rate_at_knee"),
}


def _fmt(v) -> str:
    if v is None:
        return "—"
    return f"{v:.4g}" if isinstance(v, (int, float)) else str(v)


def render_trend(entries: list[dict], *, last_n: int = 20) -> str:
    if not entries:
        return "# Evals trend\n\nchưa có run nào trong registry.\n"
    by_kind: dict[str, list[dict]] = {}
    for e in sorted(entries, key=lambda x: x.get("ts", "")):
        by_kind.setdefault(e.get("kind", "?"), []).append(e)

    lines = [
        "# Evals trend",
        "",
        "## Run mới nhất theo kind",
        "",
        "| kind | run_id | ts | verdict | metrics chính |",
        "|---|---|---|---|---|",
    ]
    for kind in ("quality", "rag", "bench", "load"):
        rows = by_kind.get(kind)
        if not rows:
            continue
        latest = rows[-1]
        keys = _KIND_METRICS.get(kind, ())
        summary = ", ".join(
            f"{k}={_fmt(latest['metrics'].get(k))}"
            for k in keys
            if k in latest["metrics"]
        )
        lines.append(
            f"| {kind} | `{latest['run_id']}` | {latest['ts'][:19]} | {latest['verdict']} | {summary} |"
        )

    for kind, rows in by_kind.items():
        keys = _KIND_METRICS.get(kind, ())
        lines += [
            "",
            f"## {kind} — {min(len(rows), last_n)} run gần nhất",
            "",
            "| ts | run_id | git | verdict | " + " | ".join(keys) + " |",
            "|---|---|---|---|" + "---|" * len(keys),
        ]
        for e in rows[-last_n:]:
            vals = " | ".join(_fmt(e["metrics"].get(k)) for k in keys)
            lines.append(
                f"| {e['ts'][:19]} | `{e['run_id']}` | {e.get('git_sha', '')} | {e['verdict']} | {vals} |"
            )

    quality = by_kind.get("quality", [])
    if len(quality) >= 2:
        latest = quality[-1]
        prev_pass = next(
            (e for e in reversed(quality[:-1]) if e["verdict"] == "pass"), None
        )
        if prev_pass:
            lines += [
                "",
                f"## Δ quality: `{latest['run_id']}` vs `{prev_pass['run_id']}` (pass gần nhất)",
                "",
            ]
            for k in sorted(set(latest["metrics"]) & set(prev_pass["metrics"])):
                a, b = prev_pass["metrics"].get(k), latest["metrics"].get(k)
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    lines.append(f"- `{k}`: {_fmt(a)} → {_fmt(b)} (Δ {_fmt(b - a)})")
    return "\n".join(lines) + "\n"
