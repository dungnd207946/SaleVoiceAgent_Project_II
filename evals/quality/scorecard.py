"""Scorecard — thresholds + axis scores → PASS/FAIL verdict + Markdown report.

Gates fail CLOSED: a metric that no scorer produced is a FAIL, not a skip. A
release gate that silently passes when its input is missing is worse than no
gate, because it reads as evidence.

Pure: takes data, returns strings. The CLI does the file I/O.
"""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from evals.quality import report_docs
from evals.quality.scorers import AxisScore

_OPS = {"<=", ">=", "<", ">", "=="}


@dataclass(frozen=True)
class GateResult:
    name: str
    metric: str
    actual: float | None
    limit: float
    op: str
    ok: bool
    # Gate `judge = true` trong một run KHÔNG chạy judge: không đo được thì không kết
    # luận — không phải FAIL (khác `missing`: metric đáng lẽ phải có mà không có).
    skipped: bool = False


@dataclass(frozen=True)
class Scorecard:
    run_id: str
    config: dict
    axes: tuple[AxisScore, ...] = ()
    gates: tuple[GateResult, ...] = ()
    metrics: dict[str, float | None] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(g.ok for g in self.gates)


def load_thresholds(path: Path) -> dict:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    gates = data.get("gates")
    if not isinstance(gates, list) or not gates:
        raise ValueError(f"{path}: needs a non-empty [[gates]] array")
    for i, gate in enumerate(gates):
        if not gate.get("metric"):
            raise ValueError(f"{path}: gate {i} needs 'metric'")
        if not gate.get("name"):
            raise ValueError(f"{path}: gate {i} needs 'name'")
        if gate.get("op") not in _OPS:
            raise ValueError(f"{path}: gate {i} unknown op {gate.get('op')!r}; allowed {sorted(_OPS)}")
        if not isinstance(gate.get("limit"), (int, float)):
            raise ValueError(f"{path}: gate {i} needs a numeric 'limit'")
        if "judge" in gate and not isinstance(gate["judge"], bool):
            raise ValueError(f"{path}: gate {i} 'judge' must be a boolean")
    return data


def _compare(actual: float, op: str, limit: float) -> bool:
    if op == "<=":
        return actual <= limit
    if op == ">=":
        return actual >= limit
    if op == "<":
        return actual < limit
    if op == ">":
        return actual > limit
    return actual == limit


def evaluate_gates(
    metrics: dict[str, float | None], thresholds: dict, *, judge_ran: bool = False
) -> list[GateResult]:
    """A metric that is ABSENT and a metric that is present-but-`None` are the
    same statement: no scorer measured this, so the gate cannot certify it. Both
    fail closed. `None` is how a scorer says "my sample was empty" instead of
    emitting the value that happens to pass (see scorers/tool_selection.py::_gated_rate).

    Gate khai `judge = true` đọc metric chỉ sinh ra khi chạy `--judge`. Run không
    judge thì gate đó `skipped` (ok, không có actual) — cố ý không đo khác với đo
    mà không ra số. Judge đã chạy mà metric vẫn thiếu → fail-closed như mọi gate.
    """
    out: list[GateResult] = []
    for gate in thresholds["gates"]:
        metric = gate["metric"]
        limit = float(gate["limit"])
        op = gate["op"]
        if gate.get("judge") and not judge_ran:
            out.append(GateResult(gate["name"], metric, None, limit, op, True, skipped=True))
            continue
        raw = metrics.get(metric)
        if raw is None:
            out.append(GateResult(gate["name"], metric, None, limit, op, False))
            continue
        actual = float(raw)
        out.append(GateResult(gate["name"], metric, actual, limit, op, _compare(actual, op, limit)))
    return out


def build_scorecard(
    run_id: str, config: dict, axes: Sequence[AxisScore], thresholds: dict, *, judge_ran: bool = False
) -> Scorecard:
    merged: dict[str, float | None] = {}
    for axis in axes:
        # A duplicate metric name would silently shadow: the last scorer wins and a
        # gate then reads a number produced by a scorer nobody expected. Raise —
        # this module's entire job is to not lie about what was measured.
        clash = sorted(set(axis.metrics) & set(merged))
        if clash:
            raise ValueError(f"duplicate metric name(s) {clash} — axis {axis.axis!r} collides with an earlier axis")
        merged.update(axis.metrics)
    return Scorecard(
        run_id=run_id,
        config=dict(config),
        axes=tuple(axes),
        gates=tuple(evaluate_gates(merged, thresholds, judge_ran=judge_ran)),
        metrics=merged,
    )


def _fmt(value: float | None) -> str:
    return "missing" if value is None else f"{value:.4g}"


def render_markdown(card: Scorecard) -> str:
    lines: list[str] = []
    verdict = "PASS" if card.ok else "FAIL"
    lines.append(f"# Eval scorecard `{card.run_id}` — **{verdict}**")
    lines.append("")

    lines.append("## Config")
    lines.append("")
    lines.append(f"> {report_docs.CONFIG_LEGEND}")
    lines.append("")
    lines.append("| key | value |")
    lines.append("|---|---|")
    for key in sorted(card.config):
        lines.append(f"| `{key}` | `{card.config[key]}` |")
    lines.append("")

    lines.append("## Gates (loại 1 tuyệt đối + loại 2 theo baseline)")
    lines.append("")
    lines.append(f"> {report_docs.GATES_LEGEND}")
    lines.append("")
    lines.append("| | gate | metric | actual | ngưỡng |")
    lines.append("|---|---|---|---|---|")
    for gate in card.gates:
        mark = "⏭" if gate.skipped else "✅" if gate.ok else "❌"
        actual = "skipped (cần --judge)" if gate.skipped else _fmt(gate.actual)
        lines.append(f"| {mark} | {gate.name} | `{gate.metric}` | {actual} | `{gate.op} {gate.limit:.4g}` |")
    lines.append("")

    lines.append("## Trục")
    lines.append("")
    lines.append(f"> {report_docs.AXES_LEGEND}")
    lines.append("")
    lines.append("| axis | checks | failures | pass rate | chấm gì |")
    lines.append("|---|---|---|---|---|")
    for axis in card.axes:
        doc = report_docs.describe_axis(axis.axis).replace("|", "\\|")
        lines.append(f"| {axis.axis} | {axis.checks} | {axis.failures} | {axis.pass_rate:.1%} | {doc} |")
    lines.append("")

    if card.metrics:
        # Ngưỡng lấy từ chính card.gates — mô tả và ngưỡng KHÔNG được khai hai nơi,
        # nếu không thresholds.toml đổi mà bảng này vẫn in ngưỡng cũ.
        gate_of = {g.metric: f"`{g.op} {g.limit:.4g}`" for g in card.gates}
        lines.append("## Metrics")
        lines.append("")
        lines.append(f"> {report_docs.LEGEND}")
        lines.append("")
        lines.append("| metric | value | gate | ý nghĩa |")
        lines.append("|---|---|---|---|")
        for key in sorted(card.metrics):
            doc = report_docs.describe(key).replace("|", "\\|")
            lines.append(f"| `{key}` | {_fmt(card.metrics[key])} | {gate_of.get(key, '—')} | {doc} |")
        lines.append("")

    findings = [(axis.axis, f) for axis in card.axes for f in axis.findings]
    lines.append(f"## Findings ({len(findings)})")
    lines.append("")
    if not findings:
        lines.append("Không có finding nào.")
    else:
        lines.append(f"> {report_docs.FINDINGS_LEGEND}")
        lines.append("")
        # Chỉ chú giải kind THỰC SỰ xuất hiện — liệt kê cả bảng vocabulary vào mỗi report
        # là nhiễu, người đọc phải tự lọc xem cái nào liên quan.
        kinds = sorted({f.kind for _, f in findings})
        lines.append("| kind | nghĩa |")
        lines.append("|---|---|")
        for kind in kinds:
            lines.append(f"| {kind} | {report_docs.describe_finding(kind).replace('|', chr(92) + '|')} |")
        lines.append("")
        lines.append("| axis | case | turn | kind | detail |")
        lines.append("|---|---|---|---|---|")
        for axis_name, finding in findings:
            detail = finding.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {axis_name} | `{finding.case_id}` | {finding.turn} | {finding.kind} | {detail} |")
    lines.append("")
    return "\n".join(lines)
