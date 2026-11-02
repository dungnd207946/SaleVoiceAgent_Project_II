# Unified Evals Harness (`evals/`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Xây harness đánh giá thống nhất `evals/` (quality per-turn/multi-turn + RAG component + latency per-component + CCU load) với registry JSONL tracked trong git, thay thế `tests/eval` cũ.

**Architecture:** Package top-level `evals/` đứng ngoài `src/`, import chỉ các seam public (`NobleAgent` facade, `noble_kb`, `SileroVAD`, `StreamingLLM`) và gọi service remote qua network. Port nguyên phần đã proven từ `tests/eval` (case schema, trace, 3 scorer, scorecard) và `scripts/load_test/v2` (ramp engine), bổ sung judge / latency aggregation / RAG scorer / registry. Mọi run append 1 dòng vào `evals/registry.jsonl` (tracked); chi tiết per-run vào `evals/reports/<run_id>/` (gitignored).

**Tech Stack:** Python 3.11–3.13, asyncio, pydantic-settings (không bắt buộc — env đọc trực tiếp), websockets, httpx, openai (judge), qdrant-client (read-only), pytest (`asyncio_mode=auto`).

**Spec:** `docs/superpowers/specs/2026-08-24-unified-evals-harness-design.md`

## Global Constraints

- **KHÔNG sửa bất kỳ file nào trong `src/`.** (Spec §2)
- **Không ghi PG/Qdrant ngoài hành vi core của agent**; session dùng prefix `eval:<run_id>:<case_id>`; `BILLING_METERING_ENABLED=false` bị ép trong CLI trước khi import `noble_agent`. (Spec §2, §5.3)
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Chạy `make lint` trước mỗi commit.
- Pytest: `asyncio_mode=auto` (async test không cần decorator).
- Unit test KHÔNG cần infra sống (Redis/PG/service) — mọi I/O có seam để fake.
- Branch hiện tại: `feat/share-agent`. KHÔNG động `develop`, không push, không tạo branch mới.
- `tests/eval/` GIỮ NGUYÊN cho đến Task 19 (chạy song song đối chiếu rồi mới xoá).
- Commit message kết thúc bằng `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

**Chạy test:** luôn từ repo root: `python -m pytest tests/unit/evals/ -q`.

---

### Task 1: Package skeleton + `evals/common.py`

**Files:**
- Create: `evals/__init__.py` (rỗng), `evals/common.py`
- Create: `tests/unit/evals/__init__.py` (rỗng), `tests/unit/evals/test_common.py`

**Interfaces:**
- Produces: `new_run_id(kind: str) -> str` (dạng `YYYYMMDD-HHMMSS-<kind>-<hex6>`), `git_sha() -> str`, `percentiles_ms(samples: list[float], ps=(50,95,99)) -> dict[str, float]` (key `p50/p95/p99/max`, `{}` nếu rỗng), `load_repo_dotenv() -> None`, `REPO_ROOT: Path`, `REPORTS_DIR: Path` (= `evals/reports`).

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/evals/test_common.py
import re

from evals.common import REPORTS_DIR, new_run_id, percentiles_ms


def test_new_run_id_format():
    rid = new_run_id("quality")
    assert re.fullmatch(r"\d{8}-\d{6}-quality-[0-9a-f]{6}", rid)


def test_percentiles_ms_known_values():
    out = percentiles_ms([10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0])
    assert out["p50"] == 50.0
    assert out["p95"] == 100.0
    assert out["max"] == 100.0


def test_percentiles_ms_empty():
    assert percentiles_ms([]) == {}


def test_reports_dir_inside_evals():
    assert REPORTS_DIR.name == "reports" and REPORTS_DIR.parent.name == "evals"
```

- [ ] **Step 2: Chạy để thấy fail**

Run: `python -m pytest tests/unit/evals/test_common.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'evals'`

- [ ] **Step 3: Implement**

```python
# evals/common.py
"""Shared helpers cho evals harness. Pure — KHÔNG import noble_agent."""

from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def new_run_id(kind: str) -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{kind}-{uuid.uuid4().hex[:6]}"


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False, cwd=REPO_ROOT,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 — thiếu git không phải lý do fail một run eval
        return ""


def percentiles_ms(samples: list[float], ps: tuple[int, ...] = (50, 95, 99)) -> dict[str, float]:
    """Nearest-rank percentiles + max. {} nếu rỗng. (Cùng công thức scripts/load_test/v2/common.py.)"""
    if not samples:
        return {}
    ordered = sorted(samples)
    n = len(ordered)
    out: dict[str, float] = {}
    for p in ps:
        k = max(0, min(n - 1, (p * n + 99) // 100 - 1))
        out[f"p{p}"] = ordered[k]
    out["max"] = ordered[-1]
    return out


def load_repo_dotenv() -> None:
    """Nạp .env repo-root vào os.environ (override=False) — port từ tests/eval/__main__._load_dotenv.

    pydantic-settings đọc .env vào Settings, KHÔNG vào os.environ; nhưng vài module trên
    RUN path đọc os.getenv trực tiếp (storage/redis_client.py). Thiếu bước này không lỗi —
    nó im lặng trỏ RUN vào sai infra.
    """
    try:
        from dotenv import load_dotenv as _ld
    except ImportError:
        return
    candidate = REPO_ROOT / ".env"
    if candidate.is_file():
        _ld(candidate, override=False)
```

Và `evals/__init__.py`, `tests/unit/evals/__init__.py` rỗng.

- [ ] **Step 4: Test pass + lint**

Run: `python -m pytest tests/unit/evals/test_common.py -q && ruff check evals/ tests/unit/evals/`
Expected: PASS, no findings

- [ ] **Step 5: Commit**

```bash
git add evals/ tests/unit/evals/
git commit -m "feat(evals): package skeleton + common helpers (run_id, git_sha, percentiles)"
```

---

### Task 2: `evals/registry.py` — registry JSONL tracked

**Files:**
- Create: `evals/registry.py`, `evals/registry.jsonl` (file rỗng, tracked)
- Test: `tests/unit/evals/test_registry.py`

**Interfaces:**
- Consumes: `evals.common.git_sha`
- Produces:
  - `REGISTRY_PATH: Path` (= `evals/registry.jsonl`)
  - `@dataclass(frozen=True) RegistryEntry(run_id: str, ts: str, kind: str, git_sha: str, config: dict, metrics: dict, gates: dict, verdict: str, report_dir: str)`
  - `make_entry(*, run_id: str, kind: str, config: dict, metrics: dict, gates: dict, verdict: str, report_dir: str) -> RegistryEntry` — tự đóng dấu `ts` (ISO UTC) + `git_sha`; raise `ValueError` nếu `verdict` ngoài `{"pass","fail","error"}` hoặc `kind` ngoài `{"quality","rag","bench","load"}`
  - `append_entry(entry: RegistryEntry, path: Path = REGISTRY_PATH) -> None` — append 1 dòng JSON (`ensure_ascii=False`)
  - `read_entries(path: Path = REGISTRY_PATH) -> list[dict]` — bỏ dòng trắng, raise nếu JSON hỏng (kèm số dòng)

- [ ] **Step 1: Viết test fail**

```python
# tests/unit/evals/test_registry.py
import json

import pytest

from evals.registry import append_entry, make_entry, read_entries


def test_roundtrip(tmp_path):
    p = tmp_path / "registry.jsonl"
    e = make_entry(run_id="r1", kind="quality", config={"model": "m"},
                   metrics={"x": 1.0}, gates={"g": "pass"}, verdict="pass", report_dir="evals/reports/r1/")
    append_entry(e, path=p)
    append_entry(e, path=p)
    rows = read_entries(p)
    assert len(rows) == 2
    assert rows[0]["run_id"] == "r1" and rows[0]["kind"] == "quality"
    assert rows[0]["ts"] and "git_sha" in rows[0]


def test_bad_verdict_rejected():
    with pytest.raises(ValueError):
        make_entry(run_id="r", kind="quality", config={}, metrics={}, gates={}, verdict="ok", report_dir="")


def test_bad_kind_rejected():
    with pytest.raises(ValueError):
        make_entry(run_id="r", kind="latency", config={}, metrics={}, gates={}, verdict="pass", report_dir="")


def test_read_broken_line_names_lineno(tmp_path):
    p = tmp_path / "registry.jsonl"
    p.write_text('{"run_id": "a"}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError, match="line 2"):
        read_entries(p)


def test_read_missing_file_is_empty(tmp_path):
    assert read_entries(tmp_path / "nope.jsonl") == []
```

- [ ] **Step 2: Chạy fail** — `python -m pytest tests/unit/evals/test_registry.py -q` → FAIL (module thiếu)

- [ ] **Step 3: Implement**

```python
# evals/registry.py
"""Registry — MỘT dòng JSON tổng hợp mỗi run, append-only, tracked trong git.

Chi tiết per-case nằm ở evals/reports/<run_id>/ (gitignored); dòng registry chỉ mang
metric tổng hợp để diff qua git và vẽ trend.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from evals.common import git_sha

REGISTRY_PATH = Path(__file__).resolve().parent / "registry.jsonl"

_KINDS = frozenset({"quality", "rag", "bench", "load"})
_VERDICTS = frozenset({"pass", "fail", "error"})


@dataclass(frozen=True)
class RegistryEntry:
    run_id: str
    ts: str
    kind: str
    git_sha: str
    config: dict
    metrics: dict
    gates: dict
    verdict: str
    report_dir: str


def make_entry(*, run_id: str, kind: str, config: dict, metrics: dict, gates: dict,
               verdict: str, report_dir: str) -> RegistryEntry:
    if kind not in _KINDS:
        raise ValueError(f"unknown kind {kind!r}; allowed {sorted(_KINDS)}")
    if verdict not in _VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}; allowed {sorted(_VERDICTS)}")
    return RegistryEntry(
        run_id=run_id, ts=datetime.now(UTC).isoformat(), kind=kind, git_sha=git_sha(),
        config=dict(config), metrics=dict(metrics), gates=dict(gates),
        verdict=verdict, report_dir=report_dir,
    )


def append_entry(entry: RegistryEntry, path: Path = REGISTRY_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")


def read_entries(path: Path = REGISTRY_PATH) -> list[dict]:
    if not path.is_file():
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise ValueError(f"{path}: line {lineno}: not valid JSON — {e}") from e
    return out
```

Tạo file rỗng tracked: `touch evals/registry.jsonl`

- [ ] **Step 4: Pass + lint** — `python -m pytest tests/unit/evals/test_registry.py -q && ruff check evals/`

- [ ] **Step 5: Commit**

```bash
git add evals/registry.py evals/registry.jsonl tests/unit/evals/test_registry.py
git commit -m "feat(evals): registry.jsonl writer/reader (1 line per run, tracked)"
```

---

### Task 3: Port quality core (cases / trace / 3 scorers / scorecard) + tests

**Files:**
- Create: `evals/quality/__init__.py`, `evals/quality/cases.py`, `evals/quality/trace.py`, `evals/quality/scorecard.py`, `evals/quality/scorers/{__init__.py,policy.py,tool_traj.py,run_integrity.py}` — copy từ `tests/eval/` cùng tên
- Test: `tests/unit/evals/quality/{__init__.py,test_cases.py,test_trace.py,test_scorecard.py,test_scorer_policy.py,test_scorer_tool_traj.py,test_scorer_run_integrity.py,test_shipped_cases.py}` — copy từ `tests/eval/tests/`

**Interfaces:**
- Produces (giữ NGUYÊN chữ ký cũ, chỉ đổi module path):
  - `evals.quality.cases`: `EvalCase`, `EvalTurn`, `Golden`, `parse_case`, `load_cases`, `load_case_dir`, `AXES`, `CHANNELS`
  - `evals.quality.trace`: `TraceCase`, `TraceTurn`, `TracedToolCall`, `TraceHeader`, `write_traces`, `read_traces`
  - `evals.quality.scorers`: `AxisScore(axis, checks, failures, findings, metrics)`, `Finding(case_id, turn, kind, detail)`
  - `evals.quality.scorers.policy.score_policy(cases, traces) -> AxisScore`; `...tool_traj.score_tool_trajectory(...)`; `...run_integrity.score_run_integrity(...)`
  - `evals.quality.scorecard`: `Scorecard`, `GateResult`, `load_thresholds(path) -> dict`, `build_scorecard(run_id, config, axes, thresholds) -> Scorecard`, `render_markdown(card) -> str`
- Consumes: `tests.e2e_scenarios.assertions.KNOWN_KEYS` (GIỮ import này — vocabulary dùng chung, e2e_scenarios không bị xoá)

- [ ] **Step 1: Copy source + tests**

```bash
mkdir -p evals/quality/scorers tests/unit/evals/quality
cp tests/eval/cases.py tests/eval/trace.py tests/eval/scorecard.py evals/quality/
cp tests/eval/scorers/__init__.py tests/eval/scorers/policy.py tests/eval/scorers/tool_traj.py \
   tests/eval/scorers/run_integrity.py evals/quality/scorers/
touch evals/quality/__init__.py tests/unit/evals/quality/__init__.py
cp tests/eval/tests/test_cases.py tests/eval/tests/test_trace.py tests/eval/tests/test_scorecard.py \
   tests/eval/tests/test_scorer_policy.py tests/eval/tests/test_scorer_tool_traj.py \
   tests/eval/tests/test_scorer_run_integrity.py tests/eval/tests/test_shipped_cases.py \
   tests/unit/evals/quality/
```

- [ ] **Step 2: Đổi import path trong TẤT CẢ file vừa copy**

Trong `evals/quality/**/*.py` và `tests/unit/evals/quality/*.py`, thay MỌI chuỗi
`from tests.eval.` → `from evals.quality.` và `tests.eval.` → `evals.quality.` (kể cả trong docstring/comment nói về đường dẫn module). GIỮ NGUYÊN `from tests.e2e_scenarios.assertions import KNOWN_KEYS`.

```bash
grep -rl "tests\.eval" evals/quality tests/unit/evals/quality | xargs sed -i 's/tests\.eval/evals.quality/g'
grep -rn "tests\.eval" evals/quality tests/unit/evals/quality   # phải ra RỖNG
```

Lưu ý: `test_shipped_cases.py` trỏ tới thư mục case data (`tests/eval/data/cases`) — data chưa port (Task 7). Sửa đường dẫn trong test đó thành `evals/quality/data/cases` và tạm skip nếu thư mục chưa tồn tại:

```python
# đầu file tests/unit/evals/quality/test_shipped_cases.py — thay hằng đường dẫn cũ bằng:
import pytest
from pathlib import Path

_CASES = Path(__file__).resolve().parents[3] / "evals" / "quality" / "data" / "cases"
pytestmark = pytest.mark.skipif(not _CASES.is_dir(), reason="case data ported in a later task")
```

(Giữ nguyên phần thân test, chỉ thay biến đường dẫn nó dùng thành `_CASES`.)

- [ ] **Step 3: Chạy test**

Run: `python -m pytest tests/unit/evals/quality/ -q`
Expected: PASS (test_shipped_cases SKIP)

- [ ] **Step 4: Lint + commit**

```bash
ruff check evals/ tests/unit/evals/
git add evals/quality tests/unit/evals/quality
git commit -m "feat(evals): port quality core from tests/eval (cases/trace/scorers/scorecard)"
```

---

### Task 4: `evals/quality/latency.py` — aggregate TTFT/total per-turn

**Files:**
- Create: `evals/quality/latency.py`
- Test: `tests/unit/evals/quality/test_latency.py`

**Interfaces:**
- Consumes: `evals.quality.scorers.AxisScore`, `evals.quality.trace.TraceCase/TraceTurn`, `evals.common.percentiles_ms`
- Produces: `score_latency(cases, traces) -> AxisScore` — axis `"latency"`, `checks=0, failures=0`, metrics: `ttft_p50_ms`, `ttft_p95_ms`, `turn_total_p50_ms`, `turn_total_p95_ms` (`None` khi mẫu rỗng). KHÔNG có gate latency (spec §5.2a — chờ baseline).

- [ ] **Step 1: Test fail**

```python
# tests/unit/evals/quality/test_latency.py
from evals.quality.latency import score_latency
from evals.quality.trace import TraceCase, TraceTurn


def _case(turns):
    return TraceCase(case_id="c1", axis="tool", tenant="noble", channel="chat", reviewed=True, turns=tuple(turns))


def test_aggregates_percentiles():
    traces = [_case([TraceTurn(user="u", reply="r", ttft_ms=100.0, total_ms=200.0),
                     TraceTurn(user="u", reply="r", ttft_ms=300.0, total_ms=400.0)])]
    score = score_latency([], traces)
    assert score.axis == "latency"
    assert score.metrics["ttft_p50_ms"] == 100.0
    assert score.metrics["turn_total_p95_ms"] == 400.0


def test_empty_sample_is_none():
    traces = [_case([TraceTurn(user="u", reply="r", ttft_ms=None, total_ms=0.0)])]
    score = score_latency([], traces)
    assert score.metrics["ttft_p50_ms"] is None
    assert score.metrics["turn_total_p50_ms"] is None
```

- [ ] **Step 2: Chạy fail** — `python -m pytest tests/unit/evals/quality/test_latency.py -q`

- [ ] **Step 3: Implement**

```python
# evals/quality/latency.py
"""Aggregate per-turn ttft_ms/total_ms từ trace thành percentiles cho scorecard/registry.

Trace đã LUÔN capture hai số này (runner.py) — trước đây không ai aggregate. Không gate:
chỉ báo cáo để theo dõi trend (spec §5.2a); gate latency thêm sau khi có baseline.
"""

from __future__ import annotations

from evals.common import percentiles_ms
from evals.quality.scorers import AxisScore
from evals.quality.trace import TraceCase


def score_latency(cases: list, traces: list[TraceCase]) -> AxisScore:  # noqa: ARG001 — chữ ký scorer chung
    ttft = [t.ttft_ms for c in traces for t in c.turns if t.ttft_ms is not None]
    total = [t.total_ms for c in traces for t in c.turns if t.total_ms > 0]
    metrics: dict[str, float | None] = {}
    for name, samples in (("ttft", ttft), ("turn_total", total)):
        pcts = percentiles_ms(samples)
        metrics[f"{name}_p50_ms"] = pcts.get("p50")
        metrics[f"{name}_p95_ms"] = pcts.get("p95")
    return AxisScore(axis="latency", checks=0, failures=0, metrics=metrics)
```

- [ ] **Step 4: Pass + lint** — `python -m pytest tests/unit/evals/quality/test_latency.py -q && ruff check evals/`

- [ ] **Step 5: Commit** — `git add evals/quality/latency.py tests/unit/evals/quality/test_latency.py && git commit -m "feat(evals): latency aggregation axis (ttft/turn_total p50/p95)"`

---

### Task 5: `evals/quality/scorers/rag.py` — grounding scorer full-pipeline

**Files:**
- Create: `evals/quality/scorers/rag.py`
- Test: `tests/unit/evals/quality/test_scorer_rag.py`

**Interfaces:**
- Consumes: `EvalCase` (axis `grounding`/`retrieval`, `EvalTurn.golden.evidence`), `TraceCase` (tool_calls `kb_search` raw_result, reply)
- Produces: `score_rag(cases, traces) -> AxisScore` — axis `"rag"`, metrics `retrieval_hit_rate` + `evidence_in_reply_rate` (`None` khi không có mẫu). Check đếm trên turn có golden.evidence; fail khi evidence (normalized) KHÔNG nằm trong kết quả `kb_search` agent nhìn thấy.
- **Quy ước authoring case (ghi vào docstring):** `golden.evidence` phải là câu TRÍCH NGUYÊN VĂN từ corpus — matcher là normalized-substring (lowercase + collapse whitespace), deterministic, không fuzzy.

- [ ] **Step 1: Test fail**

```python
# tests/unit/evals/quality/test_scorer_rag.py
from evals.quality.cases import EvalCase, EvalTurn, Golden
from evals.quality.scorers.rag import score_rag
from evals.quality.trace import TraceCase, TracedToolCall, TraceTurn


def _case(cid, evidence):
    return EvalCase(id=cid, axis="grounding", origin="kb", tenant="noble", channel="chat", reviewed=True,
                    turns=(EvalTurn(user="hỏi", expect={},
                                    golden=Golden(answer="đáp", evidence=evidence)),))


def _trace(cid, kb_result, reply):
    return TraceCase(case_id=cid, axis="grounding", tenant="noble", channel="chat", reviewed=True,
                     turns=(TraceTurn(user="hỏi", reply=reply,
                                      tool_calls=(TracedToolCall(name="kb_search", args={}, raw_result=kb_result),)),))


def test_hit_when_evidence_in_kb_result_and_reply():
    score = score_rag([_case("c1", "Giá từ 3 tỷ")], [_trace("c1", "…  giá TỪ 3   tỷ …", "Dạ giá từ 3 tỷ ạ")])
    assert score.failures == 0
    assert score.metrics["retrieval_hit_rate"] == 1.0
    assert score.metrics["evidence_in_reply_rate"] == 1.0


def test_miss_when_kb_search_never_saw_evidence():
    score = score_rag([_case("c1", "Giá từ 3 tỷ")], [_trace("c1", "nội dung khác hẳn", "trả lời gì đó")])
    assert score.failures == 1
    assert score.metrics["retrieval_hit_rate"] == 0.0


def test_no_golden_cases_metrics_none():
    score = score_rag([], [])
    assert score.metrics["retrieval_hit_rate"] is None
```

- [ ] **Step 2: Chạy fail** — `python -m pytest tests/unit/evals/quality/test_scorer_rag.py -q`

- [ ] **Step 3: Implement**

```python
# evals/quality/scorers/rag.py
"""RAG-grounding trong ngữ cảnh full-pipeline: chunk vàng có tới được mắt agent không.

Matcher deterministic: normalized substring (lowercase + collapse whitespace). Vì thế
`golden.evidence` PHẢI là câu trích NGUYÊN VĂN từ corpus — không paraphrase.
`retrieval_hit_rate` đo kết quả kb_search agent thực sự nhận; `evidence_in_reply_rate`
đo câu trả lời cuối. Tách hai số để phân biệt "retrieval trượt" với "agent bỏ qua context".
"""

from __future__ import annotations

from evals.quality.cases import EvalCase
from evals.quality.scorers import AxisScore, Finding
from evals.quality.trace import TraceCase

_RAG_AXES = ("grounding", "retrieval")


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def score_rag(cases: list[EvalCase], traces: list[TraceCase]) -> AxisScore:
    trace_by_id = {t.case_id: t for t in traces}
    checks = failures = 0
    findings: list[Finding] = []
    retrieval_hits: list[float] = []
    reply_hits: list[float] = []
    for case in cases:
        if case.axis not in _RAG_AXES:
            continue
        trace = trace_by_id.get(case.id)
        if trace is None or trace.error:
            continue  # run_integrity đã tính case crash/thiếu trace
        for i, (case_turn, trace_turn) in enumerate(zip(case.turns, trace.turns)):
            if not case_turn.golden or not case_turn.golden.evidence:
                continue
            evidence = _norm(case_turn.golden.evidence)
            kb_seen = " ".join(
                _norm(tc.raw_result or "") for tc in trace_turn.tool_calls if tc.name == "kb_search"
            )
            checks += 1
            hit = evidence in kb_seen
            retrieval_hits.append(1.0 if hit else 0.0)
            reply_hits.append(1.0 if evidence in _norm(trace_turn.reply) else 0.0)
            if not hit:
                failures += 1
                findings.append(Finding(case.id, i, "retrieval_miss",
                                        f"evidence không có trong kết quả kb_search: {case_turn.golden.evidence[:80]}"))
    return AxisScore(
        axis="rag", checks=checks, failures=failures, findings=tuple(findings),
        metrics={
            "retrieval_hit_rate": (sum(retrieval_hits) / len(retrieval_hits)) if retrieval_hits else None,
            "evidence_in_reply_rate": (sum(reply_hits) / len(reply_hits)) if reply_hits else None,
        },
    )
```

- [ ] **Step 4: Pass + lint**, **Step 5: Commit** — `git commit -m "feat(evals): rag grounding scorer (retrieval_hit_rate, evidence_in_reply_rate)"`

---

### Task 6: Port `evals/quality/runner.py` — session prefix mới

**Files:**
- Create: `evals/quality/runner.py` (copy `tests/eval/runner.py` rồi sửa)
- Test: `tests/unit/evals/quality/test_runner.py` (copy `tests/eval/tests/test_runner.py` rồi sửa)

**Interfaces:**
- Produces: `run_case(case: EvalCase, *, run_id: str, agent_factory: AgentFactory | None = None) -> TraceCase` (THÊM tham số bắt buộc `run_id`), `build_config_header() -> dict` (giữ nguyên).
- Session id đổi thành: `f"eval:{run_id}:{case.id}:{uuid.uuid4().hex[:6]}"` (spec §2 — lọc/xoá được theo prefix trong Redis lẫn PG `conversation_messages`).

- [ ] **Step 1: Copy + đổi import**

```bash
cp tests/eval/runner.py evals/quality/runner.py
cp tests/eval/tests/test_runner.py tests/unit/evals/quality/test_runner.py
sed -i 's/tests\.eval/evals.quality/g' evals/quality/runner.py tests/unit/evals/quality/test_runner.py
```

- [ ] **Step 2: Sửa runner — 2 chỗ**

Trong `evals/quality/runner.py`:

1. Chữ ký: `async def run_case(case: EvalCase, *, agent_factory: AgentFactory | None = None) -> TraceCase:` → `async def run_case(case: EvalCase, *, run_id: str, agent_factory: AgentFactory | None = None) -> TraceCase:`
2. Dòng `session_id = f"eval-{case.id}-{uuid.uuid4().hex[:8]}"` → `session_id = f"eval:{run_id}:{case.id}:{uuid.uuid4().hex[:6]}"`

- [ ] **Step 3: Cập nhật test_runner**

Mọi call `run_case(case, agent_factory=...)` trong test → `run_case(case, run_id="testrun", agent_factory=...)`. Thêm một test mới xác nhận prefix:

```python
async def test_session_id_carries_eval_prefix():
    seen: dict = {}

    async def factory(*, session_id, channel, tenant_id):
        seen["sid"] = session_id
        raise RuntimeError("stop early")  # không cần agent thật

    case = _make_case()  # helper sẵn có trong file test đã port
    await run_case(case, run_id="20260824-abc", agent_factory=factory)
    assert seen["sid"].startswith(f"eval:20260824-abc:{case.id}:")
```

(Nếu helper tạo case trong file cũ tên khác, dùng đúng tên đó — giữ nguyên phần còn lại của file.)

- [ ] **Step 4: Chạy** — `python -m pytest tests/unit/evals/quality/test_runner.py -q` → PASS

- [ ] **Step 5: Lint + commit** — `git commit -m "feat(evals): port quality runner with eval:<run_id>:<case_id> session prefix"`

---

### Task 7: CLI quality (`evals/__main__.py`) + port case data + preflight + registry append

**Files:**
- Create: `evals/__main__.py` (base từ `tests/eval/__main__.py`), `evals/preflight.py`
- Create: `evals/quality/data/` (copy toàn bộ `tests/eval/data/`)
- Test: `tests/unit/evals/quality/test_cli.py` (copy + sửa từ `tests/eval/tests/test_cli.py`), `tests/unit/evals/test_preflight.py`
- Modify: `.gitignore` — thêm dòng `evals/reports/`

**Interfaces:**
- Produces: `python -m evals list|run|score` với semantics y hệt `python -m tests.eval` cũ, KHÁC:
  - run/score dir: `evals/reports/<run_id>/` (`RUN_ID` từ `evals.common.new_run_id("quality")`; `--run-id` vẫn override được)
  - `_CASES_ROOT = evals/quality/data/cases`, `_THRESHOLDS = evals/quality/data/thresholds.toml`
  - Axes khi score: `[score_policy, score_tool_trajectory, score_run_integrity, score_rag, score_latency]`
  - Trước khi import bất kỳ `noble_agent.*` nào trong `_cmd_run`: `os.environ["BILLING_METERING_ENABLED"] = "false"` (ép, không setdefault — spec §5.3)
  - Sau khi score xong: append registry entry `kind="quality"`; `verdict = "error"` nếu `cases_errored == cases_scored` (cả run không đo được gì), ngược lại `"pass"/"fail"` theo `card.ok`; `gates = {g.metric: "pass" if g.ok else "fail"}`
- `evals/preflight.py`: `async def check_redis() -> str | None` (None = ok, str = mô tả lỗi) — lazy import `redis.asyncio`, đọc `REDIS_URL` từ env, `ping()` timeout 3s. `_cmd_run` gọi trước khi chạy case; lỗi → in đỏ + return 1 (fail sớm thay vì 30 case timeout — spec §10).

- [ ] **Step 1: Copy data + CLI + test**

```bash
mkdir -p evals/quality/data
cp -r tests/eval/data/cases tests/eval/data/thresholds.toml evals/quality/data/
cp tests/eval/__main__.py evals/__main__.py
cp tests/eval/tests/test_cli.py tests/unit/evals/quality/test_cli.py
sed -i 's/tests\.eval/evals.quality/g' tests/unit/evals/quality/test_cli.py
```

- [ ] **Step 2: Sửa `evals/__main__.py`**

Áp các thay đổi sau lên file vừa copy (giữ nguyên `_select`, `_load`, `_cmd_list`, `_reject_empty_selection`, `_reject_mixed_channels`, `_filter_desc`, màu ANSI):

```python
# — imports: thay khối import tests.eval.* bằng —
from evals.common import REPORTS_DIR, new_run_id
from evals.quality.cases import EvalCase, load_case_dir
from evals.quality.latency import score_latency
from evals.quality.scorecard import build_scorecard, load_thresholds, render_markdown
from evals.quality.scorers.policy import score_policy
from evals.quality.scorers.rag import score_rag
from evals.quality.scorers.run_integrity import score_run_integrity
from evals.quality.scorers.tool_traj import score_tool_trajectory
from evals.quality.trace import TraceHeader, read_traces, write_traces
from evals.registry import append_entry, make_entry

# — paths —
_HERE = Path(__file__).resolve().parent
_CASES_ROOT = _HERE / "quality" / "data" / "cases"
_THRESHOLDS = _HERE / "quality" / "data" / "thresholds.toml"
_RUNS = REPORTS_DIR

# — argparse: prog="python -m evals"; sub-parser giữ list/run/score như cũ —

# — trong _score_and_report: axes = [...] thêm 2 scorer mới —
    axes = [
        score_policy(cases, traces),
        score_tool_trajectory(cases, traces),
        score_run_integrity(cases, traces),
        score_rag(cases, traces),
        score_latency(cases, traces),
    ]

# — cuối _score_and_report, NGAY TRƯỚC `return 0 if card.ok else 1`, thêm —
    _append_registry(card, run_dir)

# — hàm mới (module-level) —
def _append_registry(card, run_dir: Path) -> None:
    """Registry là bản ghi bền — best-effort nhưng lỗi phải HIỆN, không nuốt im."""
    errored = card.metrics.get("cases_errored")
    scored = card.config.get("cases_scored")
    if errored is not None and scored and float(errored) >= float(scored):
        verdict = "error"
    else:
        verdict = "pass" if card.ok else "fail"
    entry = make_entry(
        run_id=card.run_id, kind="quality", config=card.config,
        metrics={k: v for k, v in card.metrics.items()},
        gates={g.metric: ("pass" if g.ok else "fail") for g in card.gates},
        verdict=verdict, report_dir=str(run_dir) + "/",
    )
    append_entry(entry)
    print(f"registry: appended {card.run_id} ({verdict})")

# — trong _cmd_run: 3 thay đổi —
#   (1) dòng đầu hàm, TRƯỚC mọi import noble_agent:
    os.environ["BILLING_METERING_ENABLED"] = "false"
#   (2) preflight sau khi chọn cases, trước _drive():
    from evals.preflight import check_redis
    err = asyncio.run(check_redis())
    if err:
        print(f"{_RED}preflight: {err}{_RESET}")
        return 1
#   (3) run_id + truyền vào run_case:
    run_id = args.run_id or new_run_id("quality")
    ...
    trace = await run_case(case, run_id=run_id)

# — _load_dotenv() cũ xoá; main() gọi `from evals.common import load_repo_dotenv; load_repo_dotenv()` —
```

- [ ] **Step 3: Viết `evals/preflight.py` + test**

```python
# evals/preflight.py
"""Preflight — fail sớm với thông báo rõ thay vì N case timeout (spec §10). Lazy imports."""

from __future__ import annotations

import asyncio
import os


async def check_redis(timeout_s: float = 3.0) -> str | None:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis.asyncio as aioredis  # noqa: PLC0415 — lazy: unit test không cần lib chạy thật

        client = aioredis.from_url(url)
        try:
            await asyncio.wait_for(client.ping(), timeout=timeout_s)
        finally:
            await client.aclose()
    except Exception as e:  # noqa: BLE001 — mọi lỗi đều là "Redis không sẵn sàng"
        return f"Redis không sẵn sàng tại {url}: {type(e).__name__}: {e}"
    return None
```

```python
# tests/unit/evals/test_preflight.py
from evals.preflight import check_redis


async def test_check_redis_unreachable_returns_message(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # port 1: từ chối ngay
    err = await check_redis(timeout_s=0.5)
    assert err is not None and "Redis" in err
```

- [ ] **Step 4: Sửa `tests/unit/evals/quality/test_cli.py`**

File cũ test qua `tests.eval.__main__` — đổi mọi tham chiếu module thành `evals.__main__`, đường dẫn runs thành `evals/reports`. Test nào assert nội dung `_RUNS`/`_CASES_ROOT` thì cập nhật theo path mới. Registry side-effect: monkeypatch `evals.__main__.append_entry` thành no-op trong các test score để không ghi vào registry thật; THÊM một test mới:

```python
async def test_score_appends_registry(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr("evals.__main__.append_entry", lambda e: captured.append(e))
    # dùng đúng fixture trace giả mà file test cũ đã có cho lệnh score, rồi:
    assert len(captured) == 1
    assert captured[0].kind == "quality"
    assert captured[0].verdict in {"pass", "fail", "error"}
```

(Gắn vào test score sẵn có của file — tái dùng fixture trace/case của nó.)

- [ ] **Step 5: Thêm `evals/reports/` vào `.gitignore`** (một dòng, cạnh dòng `tests/eval/runs/` hiện tại — dòng cũ giữ nguyên đến Task 19).

- [ ] **Step 6: Chạy toàn bộ + smoke list**

```bash
python -m pytest tests/unit/evals/ -q          # PASS (test_shipped_cases giờ hết skip vì data đã port)
python -m evals list                            # in 30 case từ evals/quality/data/cases/noble
ruff check evals/ tests/unit/evals/
```

- [ ] **Step 7: Commit**

```bash
git add evals/ tests/unit/evals/ .gitignore
git commit -m "feat(evals): quality CLI (list/run/score) + preflight + registry append + ported case data"
```

---

### Task 8: LLM judge (`evals/quality/judge.py`) + `score --judge`

**Files:**
- Create: `evals/quality/judge.py`
- Modify: `evals/__main__.py` (thêm cờ `--judge`, `--judge-budget-usd`)
- Test: `tests/unit/evals/quality/test_judge.py`

**Interfaces:**
- Consumes: pattern `tests/bench_estate/judge.py` (sqlite cache, budget cap, retry); `TraceCase`; `EvalCase.turns[i].golden.evidence`
- Produces:
  - `JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", os.getenv("ESTATE_JUDGE_MODEL", "gpt-5.4-nano-2026-03-17"))`
  - `@dataclass JudgeVerdict(grounded: bool | None, quality: float, rationale: str, cached: bool = False, error: bool = False)` — `grounded=None` khi turn không có evidence để chấm
  - `async judge_turn(*, case_id: str, user: str, reply: str, evidence: str, model: str = JUDGE_MODEL) -> JudgeVerdict`
  - `set_cache_path(p: Path | None)`, `set_budget(usd: float | None)`, `get_cost_usd() -> float`, `BudgetExceeded(RuntimeError)` — cùng semantics bench_estate
  - `async score_judge(cases, traces, *, model: str = JUDGE_MODEL) -> AxisScore` — axis `"judge"`, chấm mọi turn của case `reviewed`; metrics: `judge_quality_mean` (mean 0..1), `judge_grounded_rate` (trên turn có evidence), `judge_coverage` (tỉ lệ turn chấm được — hết budget/lỗi thì turn đó ungraded, KHÔNG fail gate; spec §10)
- `python -m evals score --run-dir D --judge [--judge-budget-usd 2.0]` và `run --judge ...`: judge chạy ở pha SCORE (đọc trace, không đụng agent). Cache tại `evals/reports/.judge_cache.db`.

- [ ] **Step 1: Test fail**

```python
# tests/unit/evals/quality/test_judge.py
import json

import pytest

import evals.quality.judge as judge
from evals.quality.cases import EvalCase, EvalTurn, Golden
from evals.quality.judge import JudgeVerdict, judge_turn, score_judge, set_budget, set_cache_path
from evals.quality.trace import TraceCase, TraceTurn


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    set_cache_path(tmp_path / "cache.db")
    set_budget(None)
    judge.reset_cost()
    yield
    set_cache_path(None)


def _fake_call(payload: dict):
    async def _call(model, system, user):
        return json.dumps(payload)
    return _call


async def test_judge_turn_parses_json(monkeypatch):
    monkeypatch.setattr(judge, "_call_openai", _fake_call({"grounded": True, "quality": 0.9, "rationale": "ok"}))
    v = await judge_turn(case_id="c1", user="hỏi", reply="đáp", evidence="bằng chứng")
    assert v.grounded is True and v.quality == 0.9 and not v.error


async def test_cache_hit_skips_second_call(monkeypatch):
    calls = []

    async def _call(model, system, user):
        calls.append(1)
        return json.dumps({"grounded": True, "quality": 1.0, "rationale": ""})

    monkeypatch.setattr(judge, "_call_openai", _call)
    await judge_turn(case_id="c1", user="u", reply="r", evidence="e")
    v2 = await judge_turn(case_id="c1", user="u", reply="r", evidence="e")
    assert len(calls) == 1 and v2.cached


async def test_score_judge_coverage_counts_errors(monkeypatch):
    async def _boom(model, system, user):
        raise judge.BudgetExceeded("cap")

    monkeypatch.setattr(judge, "_call_openai", _boom)
    case = EvalCase(id="c1", axis="grounding", origin="kb", tenant="noble", channel="chat", reviewed=True,
                    turns=(EvalTurn(user="u", expect={}, golden=Golden(answer="a", evidence="e")),))
    trace = TraceCase(case_id="c1", axis="grounding", tenant="noble", channel="chat", reviewed=True,
                      turns=(TraceTurn(user="u", reply="r"),))
    score = await score_judge([case], [trace])
    assert score.metrics["judge_coverage"] == 0.0
    assert score.metrics["judge_quality_mean"] is None
```

- [ ] **Step 2: Chạy fail** — `python -m pytest tests/unit/evals/quality/test_judge.py -q`

- [ ] **Step 3: Implement `evals/quality/judge.py`**

Model theo `tests/bench_estate/judge.py` — copy nguyên các khối sau từ file đó rồi đổi tên biến path: `_set_cache_path` (đổi tên public thành `set_cache_path`), `_cache_key/_cache_get/_cache_put`, `_PRICING`, `_COST_USD/_BUDGET_USD/BudgetExceeded/set_budget/reset_cost/get_cost_usd`, `_call_openai`, `_call_with_retry`, cùng hằng `JUDGE_TEMP=0.0, JUDGE_MAX_TOKENS=800, JUDGE_TIMEOUT_S=30, JUDGE_RETRY=2`. Phần mới:

```python
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", os.getenv("ESTATE_JUDGE_MODEL", "gpt-5.4-nano-2026-03-17"))
_RUBRIC_VERSION = "v1"  # đổi khi sửa prompt → invalidate cache

@dataclass
class JudgeVerdict:
    grounded: bool | None
    quality: float
    rationale: str
    cached: bool = False
    error: bool = False


_SYSTEM = """Bạn là giám khảo đánh giá câu trả lời của tư vấn viên BĐS Luna.
Chấm khách quan, trả JSON đúng schema, không thêm prose."""


def _build_user(user: str, reply: str, evidence: str) -> str:
    ev_block = f"[BẰNG CHỨNG TỪ KB]\n{evidence}\n\n" if evidence else ""
    grounded_rule = (
        '"grounded": true nếu MỌI khẳng định factual trong câu trả lời được bằng chứng đỡ, '
        "false nếu có chi tiết bịa ngoài bằng chứng"
        if evidence
        else '"grounded": null (không có bằng chứng để đối chiếu)'
    )
    return (
        f"[KHÁCH HỎI]\n{user}\n\n{ev_block}[TƯ VẤN VIÊN TRẢ LỜI]\n{reply}\n\n"
        "NHIỆM VỤ:\n"
        f"1. {grounded_rule}.\n"
        '2. "quality" 0..1: đúng trọng tâm câu hỏi, tiếng Việt tự nhiên, đúng vai tư vấn viên,'
        " không hứa hẹn/cam kết vượt quyền.\n"
        '3. "rationale": 1-2 câu tiếng Việt.\n\n'
        'OUTPUT JSON: {"grounded": true|false|null, "quality": 0.0..1.0, "rationale": "..."}'
    )


async def judge_turn(*, case_id: str, user: str, reply: str, evidence: str,
                     model: str = JUDGE_MODEL) -> JudgeVerdict:
    key = _cache_key(case_id, f"{user}|{reply}|{evidence}", model, _RUBRIC_VERSION)
    if hit := _cache_get(key):
        return JudgeVerdict(grounded=hit["grounded"], quality=float(hit["quality"]),
                            rationale=hit.get("rationale", ""), cached=True)
    try:
        raw, parsed = await _call_with_retry(model, _SYSTEM, _build_user(user, reply, evidence))
    except BudgetExceeded:
        return JudgeVerdict(grounded=None, quality=0.0, rationale="budget exceeded", error=True)
    if parsed is None:
        return JudgeVerdict(grounded=None, quality=0.0, rationale=f"judge_error: {raw[:200]}", error=True)
    grounded = parsed.get("grounded")
    verdict = JudgeVerdict(
        grounded=None if grounded is None else bool(grounded),
        quality=max(0.0, min(1.0, float(parsed.get("quality", 0.0)))),
        rationale=str(parsed.get("rationale", "")),
    )
    _cache_put(key, {"grounded": verdict.grounded, "quality": verdict.quality, "rationale": verdict.rationale})
    return verdict


async def score_judge(cases, traces, *, model: str = JUDGE_MODEL) -> AxisScore:
    """Judge mọi turn của case reviewed. Ungraded (lỗi/hết budget) trừ vào coverage,
    KHÔNG trừ vào quality/grounded — thiếu mẫu phải hiện ra là thiếu, không phải là điểm 0."""
    trace_by_id = {t.case_id: t for t in traces}
    total = graded = 0
    qualities: list[float] = []
    grounded_flags: list[float] = []
    findings: list[Finding] = []
    for case in cases:
        if not case.reviewed:
            continue
        trace = trace_by_id.get(case.id)
        if trace is None or trace.error:
            continue
        for i, (case_turn, trace_turn) in enumerate(zip(case.turns, trace.turns)):
            total += 1
            evidence = case_turn.golden.evidence if case_turn.golden else ""
            v = await judge_turn(case_id=case.id, user=trace_turn.user, reply=trace_turn.reply,
                                 evidence=evidence, model=model)
            if v.error:
                findings.append(Finding(case.id, i, "judge_ungraded", v.rationale))
                continue
            graded += 1
            qualities.append(v.quality)
            if v.grounded is not None:
                grounded_flags.append(1.0 if v.grounded else 0.0)
                if not v.grounded:
                    findings.append(Finding(case.id, i, "ungrounded", v.rationale))
    return AxisScore(
        axis="judge", checks=graded, failures=sum(1 for f in findings if f.kind == "ungrounded"),
        findings=tuple(findings),
        metrics={
            "judge_quality_mean": (sum(qualities) / len(qualities)) if qualities else None,
            "judge_grounded_rate": (sum(grounded_flags) / len(grounded_flags)) if grounded_flags else None,
            "judge_coverage": (graded / total) if total else None,
        },
    )
```

(Kèm import: `os`, `dataclass`, `AxisScore`/`Finding` từ `evals.quality.scorers`.)

- [ ] **Step 4: Nối vào CLI**

Trong `evals/__main__.py`:
- Thêm vào cả 2 sub-parser `run` và `score`: `sp.add_argument("--judge", action="store_true")`, `sp.add_argument("--judge-budget-usd", type=float, default=None)`.
- `_score_and_report(run_dir, cases, *, case_filter="", judge=False, judge_budget=None)`: khi `judge=True`, sau khi build axes deterministic:

```python
    if judge:
        from evals.quality.judge import score_judge, set_budget, set_cache_path

        set_cache_path(_RUNS / ".judge_cache.db")
        set_budget(judge_budget)
        axes.append(asyncio.run(score_judge(cases, traces)))
```

- `_cmd_score` / `_cmd_run` truyền `judge=args.judge, judge_budget=args.judge_budget_usd` xuống.

- [ ] **Step 5: Pass + lint** — `python -m pytest tests/unit/evals/quality/ -q && ruff check evals/`

- [ ] **Step 6: Commit** — `git commit -m "feat(evals): LLM judge axis (grounding + quality, sqlite cache, budget cap)"`

---

### Task 9: RAG component — golden schema + metrics thuần

**Files:**
- Create: `evals/rag/__init__.py`, `evals/rag/golden.py`, `evals/rag/metrics.py`
- Create: `evals/rag/data/golden/.gitkeep`
- Test: `tests/unit/evals/rag/{__init__.py,test_golden.py,test_metrics.py}`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) GoldenCase(id: str, tenant: str, query: str, evidence: str, golden_chunk_id: str = "", project_code: str = "", status: str = "draft")`
  - `parse_golden(data: dict, *, source: str) -> GoldenCase` — strict (unknown keys raise), `id/tenant/query/evidence` bắt buộc non-empty
  - `load_golden(path: Path) -> list[GoldenCase]` — JSONL; **raise `ValueError` nếu file còn BẤT KỲ dòng `status != "approved"`** (spec §6: runner từ chối draft)
  - `rank_of(golden: GoldenCase, hits: list[dict]) -> int | None` — index 0-based của hit đầu tiên khớp (`hit["id"] == golden.golden_chunk_id` khi golden có id, HOẶC normalized-substring `golden.evidence` trong `hit["text"]`); `None` nếu không hit nào khớp
  - `aggregate(ranks: list[int | None], latencies_ms: list[float], *, ks: tuple[int, ...] = (1, 3, 5)) -> dict` — `recall_at_1/3/5`, `mrr`, `empty_rate` KHÔNG tính ở đây (runner tính vì cần biết hits rỗng), latency percentiles qua `percentiles_ms` với key `retrieval_p50_ms/p95_ms`

- [ ] **Step 1: Test fail**

```python
# tests/unit/evals/rag/test_golden.py
import pytest

from evals.rag.golden import load_golden, parse_golden


def test_parse_ok():
    g = parse_golden({"id": "g1", "tenant": "noble", "query": "giá NCLB?",
                      "evidence": "Giá từ 3 tỷ", "status": "approved"}, source="t:1")
    assert g.id == "g1" and g.status == "approved"


def test_unknown_key_rejected():
    with pytest.raises(ValueError, match="unknown"):
        parse_golden({"id": "g", "tenant": "t", "query": "q", "evidence": "e", "bonus": 1}, source="t:1")


def test_loader_rejects_draft(tmp_path):
    p = tmp_path / "g.jsonl"
    p.write_text('{"id":"g1","tenant":"noble","query":"q","evidence":"e","status":"draft"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="draft"):
        load_golden(p)
```

```python
# tests/unit/evals/rag/test_metrics.py
from evals.rag.golden import GoldenCase, rank_of
from evals.rag.metrics import aggregate


def test_rank_by_id_then_evidence():
    g_id = GoldenCase(id="g", tenant="t", query="q", evidence="xx", golden_chunk_id="abc", status="approved")
    hits = [{"id": "zzz", "text": "khác"}, {"id": "abc", "text": "khác nữa"}]
    assert rank_of(g_id, hits) == 1
    g_ev = GoldenCase(id="g", tenant="t", query="q", evidence="Giá TỪ 3 tỷ", status="approved")
    hits = [{"id": "1", "text": "… giá từ   3 tỷ …"}]
    assert rank_of(g_ev, hits) == 0
    assert rank_of(g_ev, [{"id": "1", "text": "khác"}]) is None


def test_aggregate_recall_mrr():
    out = aggregate([0, 2, None, 4], [10.0, 20.0, 30.0, 40.0])
    assert out["recall_at_1"] == 0.25
    assert out["recall_at_3"] == 0.5
    assert out["recall_at_5"] == 0.75
    assert abs(out["mrr"] - (1 / 1 + 1 / 3 + 0 + 1 / 5) / 4) < 1e-9
    assert out["retrieval_p50_ms"] == 20.0
```

- [ ] **Step 2: Chạy fail**, **Step 3: Implement**

```python
# evals/rag/golden.py
"""Golden set retrieval: schema strict + loader từ chối draft (spec §6).

`evidence` phải là câu trích NGUYÊN VĂN từ chunk — matcher là normalized substring.
`golden_chunk_id` (Qdrant point id) ưu tiên hơn khi backend trả id.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_KEYS = {"id", "tenant", "query", "evidence", "golden_chunk_id", "project_code", "status"}


@dataclass(frozen=True)
class GoldenCase:
    id: str
    tenant: str
    query: str
    evidence: str
    golden_chunk_id: str = ""
    project_code: str = ""
    status: str = "draft"


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


def parse_golden(data: dict, *, source: str) -> GoldenCase:
    if not isinstance(data, dict):
        raise ValueError(f"{source}: golden case must be a mapping")
    unknown = set(data) - _KEYS
    if unknown:
        raise ValueError(f"{source}: unknown golden keys {sorted(unknown)}")
    for key in ("id", "tenant", "query", "evidence"):
        if not data.get(key) or not isinstance(data[key], str):
            raise ValueError(f"{source}: needs a non-empty string {key!r}")
    return GoldenCase(
        id=data["id"], tenant=data["tenant"], query=data["query"], evidence=data["evidence"],
        golden_chunk_id=str(data.get("golden_chunk_id", "") or ""),
        project_code=str(data.get("project_code", "") or ""),
        status=str(data.get("status", "draft") or "draft"),
    )


def load_golden(path: Path) -> list[GoldenCase]:
    out: list[GoldenCase] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            case = parse_golden(json.loads(line), source=f"{path.name}:{lineno}")
            if case.status != "approved":
                raise ValueError(
                    f"{path.name}:{lineno}: case {case.id!r} has status {case.status!r} — "
                    "runner chỉ nhận file toàn 'approved' (duyệt tay draft trước, spec §6)"
                )
            out.append(case)
    return out


def rank_of(golden: GoldenCase, hits: list[dict]) -> int | None:
    evidence = _norm(golden.evidence)
    for i, hit in enumerate(hits):
        if golden.golden_chunk_id and str(hit.get("id", "")) == golden.golden_chunk_id:
            return i
        if evidence and evidence in _norm(str(hit.get("text", ""))):
            return i
    return None
```

```python
# evals/rag/metrics.py
"""Aggregate retrieval metrics — thuần, test được không cần Qdrant."""

from __future__ import annotations

from evals.common import percentiles_ms


def aggregate(ranks: list[int | None], latencies_ms: list[float], *, ks: tuple[int, ...] = (1, 3, 5)) -> dict:
    n = len(ranks)
    out: dict[str, float | None] = {}
    for k in ks:
        out[f"recall_at_{k}"] = (sum(1 for r in ranks if r is not None and r < k) / n) if n else None
    out["mrr"] = (sum(1.0 / (r + 1) for r in ranks if r is not None) / n) if n else None
    pcts = percentiles_ms(latencies_ms)
    out["retrieval_p50_ms"] = pcts.get("p50")
    out["retrieval_p95_ms"] = pcts.get("p95")
    return out
```

- [ ] **Step 4: Pass + lint**, **Step 5: Commit** — `git commit -m "feat(evals): rag golden schema (reject-draft loader) + recall/mrr metrics"`

---

### Task 10: RAG runner + CLI `python -m evals rag`

**Files:**
- Create: `evals/rag/runner.py`
- Modify: `evals/__main__.py` (thêm subcommand `rag`)
- Test: `tests/unit/evals/rag/test_runner.py`

**Interfaces:**
- Consumes: `load_golden`, `rank_of`, `aggregate`, `evals.registry`, seams `noble_agent`: `data.embed_client`, `data.qdrant_search`, `agent.rag.noble_kb.query_noble_kb`, `tenant.current.set_current_tenant/reset_current_tenant`
- Produces:
  - `SearchFn = Callable[[str, str], Awaitable[list[dict]]]` — (query, project_code) → hits `[{"id","text",...}]`
  - `async run_rag(golden: list[GoldenCase], *, search: SearchFn, top_k: int = 5) -> dict` — trả `{"rows": [...per-case...], "metrics": {recall/mrr/latency + "empty_rate"}}`; per-row: `{id, rank, hit, latency_ms, n_hits}`. Đo latency quanh mỗi call `search`. `empty_rate` = tỉ lệ case `n_hits == 0` (bắt degrade-im-lặng, spec §6). Nếu `empty_rate > 0.5` in cảnh báo `"backend degrade im lặng?"` (spec §10).
  - `async search_structured(query: str, project_code: str, *, top_k: int = 5) -> list[dict]` — mode mặc định: mirror `kb_service_adapter` nhưng TRẢ HITS THÔ (id/text) thay vì string. KHÔNG truyền project filter vào Qdrant (RAG component eval đo khả năng tìm đúng chunk trên toàn corpus tenant). Set tenant contextvar quanh call.
  - `async search_agent_string(query: str, project_code: str, *, top_k: int = 5) -> list[dict]` — mode `--mode agent-string`: gọi `query_noble_kb(query, project_code)` (backend theo `NOBLE_RAG_BACKEND`), wrap string kết quả thành 1 hit `[{"id": "", "text": context}]` (chỉ evidence-match được, không id) — cho A/B backend không phải kb_service.
- CLI: `python -m evals rag --golden <file.jsonl> --tenant noble [--top-k 5] [--mode structured|agent-string]` → ghi `evals/reports/<run_id>/rag.json` (rows + metrics + config) + registry entry `kind="rag"`, verdict: `error` nếu `empty_rate == 1.0` (không đo được gì), ngược lại `pass`.

- [ ] **Step 1: Test fail (fake search)**

```python
# tests/unit/evals/rag/test_runner.py
from evals.rag.golden import GoldenCase
from evals.rag.runner import run_rag


def _g(i, ev, cid=""):
    return GoldenCase(id=f"g{i}", tenant="noble", query=f"q{i}", evidence=ev,
                      golden_chunk_id=cid, status="approved")


async def test_run_rag_ranks_and_aggregates():
    async def search(query, project_code):
        if query == "q1":
            return [{"id": "a", "text": "có Giá từ 3 tỷ ở đây"}]
        return []

    out = await run_rag([_g(1, "giá từ 3 tỷ"), _g(2, "không thấy")], search=search)
    assert out["metrics"]["recall_at_1"] == 0.5
    assert out["metrics"]["empty_rate"] == 0.5
    rows = {r["id"]: r for r in out["rows"]}
    assert rows["g1"]["hit"] is True and rows["g2"]["n_hits"] == 0


async def test_search_error_counts_as_empty_not_crash():
    async def search(query, project_code):
        raise ConnectionError("qdrant down")

    out = await run_rag([_g(1, "x")], search=search)
    assert out["metrics"]["empty_rate"] == 1.0
    assert out["rows"][0]["error"].startswith("ConnectionError")
```

- [ ] **Step 2: Chạy fail**, **Step 3: Implement**

```python
# evals/rag/runner.py
"""RAG component eval — retrieval TÁCH KHỎI agent (spec §6).

Chỉ module này (trong evals/rag) import noble_agent. Mode `structured` mirror
kb_service_adapter nhưng trả hits thô (id/text) để chấm recall@k theo chunk id;
mode `agent-string` gọi query_noble_kb cho backend bất kỳ (evidence-match only).
KHÔNG truyền project filter ở structured: component eval đo tìm-đúng-chunk trên
toàn corpus tenant, khó hơn và có nghĩa hơn.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from evals.rag.golden import GoldenCase, rank_of
from evals.rag.metrics import aggregate

SearchFn = Callable[[str, str], Awaitable[list[dict]]]


async def run_rag(golden: list[GoldenCase], *, search: SearchFn, top_k: int = 5) -> dict:
    rows: list[dict] = []
    ranks: list[int | None] = []
    latencies: list[float] = []
    empty = 0
    for case in golden:
        t0 = time.perf_counter()
        error = ""
        try:
            hits = (await search(case.query, case.project_code))[:top_k]
        except Exception as exc:  # noqa: BLE001 — backend chết = case không đo được, không phải harness crash
            hits = []
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - t0) * 1000.0
        rank = rank_of(case, hits) if hits else None
        if not hits:
            empty += 1
        ranks.append(rank)
        latencies.append(latency_ms)
        rows.append({"id": case.id, "rank": rank, "hit": rank is not None,
                     "latency_ms": latency_ms, "n_hits": len(hits), "error": error})
    metrics = aggregate(ranks, latencies)
    metrics["empty_rate"] = (empty / len(golden)) if golden else None
    if golden and empty / len(golden) > 0.5:
        print(f"CẢNH BÁO: {empty}/{len(golden)} case trả rỗng — backend degrade im lặng? "
              "(kiểm tra tunnel/collection/EMBED_BACKEND, xem CLAUDE.md gotchas)")
    return {"rows": rows, "metrics": metrics}


async def search_structured(query: str, project_code: str, *, top_k: int = 5) -> list[dict]:
    """Qdrant hybrid như kb_service_adapter nhưng trả hits thô. Read-only."""
    from noble_agent.config import settings
    from noble_agent.data import embed_client
    from noble_agent.data import qdrant_search as qdrant_client
    from noble_agent.tenant.current import current_tenant

    collection = qdrant_client.collection_name(current_tenant(), "documents")
    if not await qdrant_client.collection_exists(settings.qdrant_url, settings.qdrant_api_key, collection):
        return []
    import asyncio

    dense_vecs, sparse_vecs = await asyncio.gather(
        embed_client.embed_dense([query], side="query"),
        embed_client.embed_sparse([query], side="query"),
    )
    if not dense_vecs or not sparse_vecs:
        return []
    # Mirror đúng cách kb_service_adapter dựng prefetch (đọc file đó khi implement —
    # DENSE_VECTOR="dense", SPARSE_VECTOR="bm25"); KHÔNG truyền filter_.
    return await qdrant_client.search_hybrid(
        base_url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        collection=collection,
        prefetches=[
            qdrant_client.DensePrefetch(vector=dense_vecs[0], using="dense"),
            qdrant_client.SparsePrefetch(indices=sparse_vecs[0].indices, values=sparse_vecs[0].values, using="bm25"),
        ],
        limit=top_k,
    )


async def search_agent_string(query: str, project_code: str, *, top_k: int = 5) -> list[dict]:  # noqa: ARG001
    from noble_agent.agent.rag.noble_kb import query_noble_kb

    context = await query_noble_kb(query, project_code)
    return [{"id": "", "text": context}] if context else []
```

**Lưu ý cho executor:** trước khi hoàn thiện `search_structured`, ĐỌC `src/noble_agent/agent/rag/kb_service_adapter.py` (đoạn dựng prefetch, ~dòng 130–160) và `src/noble_agent/data/qdrant_search.py` (chữ ký `DensePrefetch`/`SparsePrefetch`, kiểu trả về của `embed_sparse`) rồi chỉnh cho khớp chữ ký THẬT — khối trên viết theo schema đã đọc ngày 2026-08-24, nếu lệch thì source là chân lý. `search_hybrid` trả `[{**payload, "id": str, "score": float}]`, payload có `text`.

- [ ] **Step 4: Nối CLI**

Trong `evals/__main__.py` thêm sub-parser:

```python
    sp = sub.add_parser("rag")
    sp.add_argument("--golden", required=True, help="Đường dẫn file golden JSONL (toàn status approved)")
    sp.add_argument("--tenant", default="noble")
    sp.add_argument("--top-k", type=int, default=5)
    sp.add_argument("--mode", choices=("structured", "agent-string"), default="structured")
```

và handler:

```python
def _cmd_rag(args: argparse.Namespace) -> int:
    os.environ["BILLING_METERING_ENABLED"] = "false"
    from evals.rag.golden import load_golden
    from evals.rag.runner import run_rag, search_agent_string, search_structured

    golden = load_golden(Path(args.golden))
    run_id = new_run_id("rag")
    run_dir = _RUNS / run_id

    async def _drive():
        from noble_agent.tenant.current import reset_current_tenant, set_current_tenant

        token = set_current_tenant(args.tenant)
        try:
            search = search_structured if args.mode == "structured" else search_agent_string
            return await run_rag(golden, search=lambda q, p: search(q, p, top_k=args.top_k), top_k=args.top_k)
        finally:
            reset_current_tenant(token)

    out = asyncio.run(_drive())
    run_dir.mkdir(parents=True, exist_ok=True)
    config = {"tenant": args.tenant, "mode": args.mode, "top_k": args.top_k,
              "golden_file": args.golden, "cases": len(golden),
              "rag_backend": os.getenv("NOBLE_RAG_BACKEND", "flat_store")}
    (run_dir / "rag.json").write_text(
        json.dumps({"run_id": run_id, "config": config, **out}, ensure_ascii=False, indent=2), encoding="utf-8")
    verdict = "error" if out["metrics"].get("empty_rate") == 1.0 else "pass"
    append_entry(make_entry(run_id=run_id, kind="rag", config=config, metrics=out["metrics"],
                            gates={}, verdict=verdict, report_dir=str(run_dir) + "/"))
    for key in ("recall_at_1", "recall_at_5", "mrr", "empty_rate", "retrieval_p95_ms"):
        print(f"{key:<20} {out['metrics'].get(key)}")
    print(f"\nrag.json: {run_dir / 'rag.json'}")
    return 0 if verdict == "pass" else 1
```

(+ nhánh `if args.cmd == "rag": return _cmd_rag(args)` trong `main()`.)

- [ ] **Step 5: Pass + lint** — `python -m pytest tests/unit/evals/rag/ -q && ruff check evals/`

- [ ] **Step 6: Commit** — `git commit -m "feat(evals): rag component runner + CLI (recall@k/mrr/empty_rate vs Qdrant)"`

---

### Task 11: `gen-golden` — sinh golden set draft từ corpus (read-only)

**Files:**
- Create: `evals/rag/golden_gen.py`
- Modify: `evals/__main__.py` (subcommand `gen-golden`)
- Test: `tests/unit/evals/rag/test_golden_gen.py`

**Interfaces:**
- Produces:
  - `async fetch_chunks(*, tenant: str, limit: int) -> list[dict]` — scroll Qdrant collection `<tenant>_documents` READ-ONLY qua `qdrant_client.AsyncQdrantClient.scroll` (lazy import; `with_payload=True`, `with_vectors=False`), trả `[{"id": str, "text": str, "project_code": str}]` (payload key project: đọc `project_id`)
  - `async gen_questions(chunk: dict, *, model: str, n: int = 2) -> list[dict]` — 1 call LLM (AsyncOpenAI, JSON mode, temp 0) sinh tối đa `n` cặp `{query, evidence}`; **evidence PHẢI là câu trích nguyên văn trong `chunk["text"]`** — hàm VALIDATE bằng normalized-substring và bỏ cặp không đạt (LLM bịa evidence = case rác)
  - `write_draft(cases: list[dict], path: Path) -> None` — JSONL, mỗi dòng đủ schema `GoldenCase` với `status: "draft"`, id dạng `gg-<chunkid8>-<i>`
- CLI: `python -m evals gen-golden --tenant noble --limit 50 [--per-chunk 2] [--model ...]` → `evals/rag/data/golden/<tenant>/draft-<YYYYMMDD-HHMMSS>.jsonl`; in hướng dẫn: duyệt tay, sửa `status` → `approved`, rồi chạy `python -m evals rag --golden <file>`.
- Model env: `EVAL_GOLDEN_MODEL` default = `JUDGE_MODEL` của Task 8.

- [ ] **Step 1: Test fail**

```python
# tests/unit/evals/rag/test_golden_gen.py
import json

import evals.rag.golden_gen as gg
from evals.rag.golden_gen import gen_questions, write_draft


async def test_gen_questions_validates_evidence_verbatim(monkeypatch):
    async def fake_llm(model, system, user):
        return json.dumps({"pairs": [
            {"query": "giá bao nhiêu?", "evidence": "Giá từ 3 tỷ"},
            {"query": "bịa", "evidence": "câu này không có trong chunk"},
        ]})

    monkeypatch.setattr(gg, "_call_llm", fake_llm)
    chunk = {"id": "abc123", "text": "Dự án X. Giá từ 3 tỷ. Bàn giao 2027.", "project_code": "NCLB"}
    pairs = await gen_questions(chunk, model="m")
    assert len(pairs) == 1
    assert pairs[0]["evidence"] == "Giá từ 3 tỷ"


def test_write_draft_schema(tmp_path):
    p = tmp_path / "draft.jsonl"
    write_draft([{"id": "gg-abc-0", "tenant": "noble", "query": "q", "evidence": "e",
                  "golden_chunk_id": "abc", "project_code": "NCLB"}], p)
    row = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert row["status"] == "draft" and row["golden_chunk_id"] == "abc"
```

- [ ] **Step 2: Chạy fail**, **Step 3: Implement**

```python
# evals/rag/golden_gen.py
"""Sinh golden set DRAFT từ corpus Qdrant (read-only) — user duyệt tay rồi mới approved (spec §6)."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

_SYSTEM = """Bạn tạo bộ câu hỏi kiểm thử retrieval cho trợ lý BĐS tiếng Việt.
Với đoạn văn cho trước, sinh câu hỏi tự nhiên mà đoạn đó là câu trả lời đúng.
'evidence' PHẢI là một câu TRÍCH NGUYÊN VĂN (copy đúng từng ký tự) từ đoạn văn.
Trả JSON đúng schema."""


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


async def _call_llm(model: str, system: str, user: str) -> str:
    """Patched in tests."""
    from openai import AsyncOpenAI  # noqa: PLC0415

    client = AsyncOpenAI()
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0, max_completion_tokens=600, response_format={"type": "json_object"},
    )
    return resp.choices[0].message.content or ""


async def gen_questions(chunk: dict, *, model: str, n: int = 2) -> list[dict]:
    user = (
        f"[ĐOẠN VĂN]\n{chunk['text']}\n\n"
        f"Sinh tối đa {n} cặp câu hỏi. "
        'OUTPUT JSON: {"pairs": [{"query": "...", "evidence": "..."}]}'
    )
    raw = await _call_llm(model, _SYSTEM, user)
    try:
        pairs = json.loads(raw).get("pairs") or []
    except ValueError:
        return []
    text_norm = _norm(chunk["text"])
    # LLM bịa evidence = case rác: chỉ giữ cặp evidence nằm nguyên văn trong chunk.
    return [p for p in pairs[:n]
            if isinstance(p, dict) and p.get("query") and p.get("evidence")
            and _norm(p["evidence"]) in text_norm]


async def fetch_chunks(*, tenant: str, limit: int) -> list[dict]:
    from noble_agent.config import settings  # noqa: PLC0415
    from qdrant_client import AsyncQdrantClient  # noqa: PLC0415

    client = AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None)
    points, _next = await client.scroll(
        collection_name=f"{tenant}_documents", limit=limit, with_payload=True, with_vectors=False)
    out = []
    for pt in points:
        payload = pt.payload or {}
        text = (payload.get("text") or "").strip()
        if text:
            out.append({"id": str(pt.id), "text": text, "project_code": str(payload.get("project_id", "") or "")})
    return out


def write_draft(cases: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps({**c, "status": "draft"}, ensure_ascii=False) + "\n")


def draft_path(tenant: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path(__file__).resolve().parent / "data" / "golden" / tenant / f"draft-{stamp}.jsonl"


def default_model() -> str:
    return os.getenv("EVAL_GOLDEN_MODEL",
                     os.getenv("EVAL_JUDGE_MODEL", os.getenv("ESTATE_JUDGE_MODEL", "gpt-5.4-nano-2026-03-17")))
```

- [ ] **Step 4: Nối CLI** — sub-parser `gen-golden` (`--tenant`, `--limit` default 50, `--per-chunk` default 2, `--model` default `default_model()`); handler:

```python
def _cmd_gen_golden(args: argparse.Namespace) -> int:
    from evals.rag.golden_gen import draft_path, fetch_chunks, gen_questions, write_draft

    async def _drive():
        chunks = await fetch_chunks(tenant=args.tenant, limit=args.limit)
        cases = []
        for chunk in chunks:
            for i, pair in enumerate(await gen_questions(chunk, model=args.model, n=args.per_chunk)):
                cases.append({"id": f"gg-{chunk['id'][:8]}-{i}", "tenant": args.tenant,
                              "query": pair["query"], "evidence": pair["evidence"],
                              "golden_chunk_id": chunk["id"], "project_code": chunk["project_code"]})
        return cases

    cases = asyncio.run(_drive())
    out = draft_path(args.tenant)
    write_draft(cases, out)
    print(f"{len(cases)} draft case → {out}")
    print("Duyệt tay: sửa/xoá câu kém, đổi status → \"approved\", rồi: python -m evals rag --golden", out)
    return 0
```

- [ ] **Step 5: Pass + lint + commit** — `git commit -m "feat(evals): gen-golden draft generator (Qdrant read-only scroll + verbatim-evidence validation)"`

---

### Task 12: Bench service — STT / TTS / speaker

**Files:**
- Create: `evals/bench/__init__.py`, `evals/bench/results.py`, `evals/bench/stt.py`, `evals/bench/tts.py`, `evals/bench/speaker.py`
- Create: `evals/bench/fixtures/fixture_16k.pcm` (copy từ `scripts/load_test/v2/fixture_16k.pcm`)
- Test: `tests/unit/evals/bench/{__init__.py,test_results.py}`

**Interfaces:**
- `evals/bench/results.py` (thuần):
  - `@dataclass ComponentResult(component: str, runs: int, errors: int, stats: dict[str, dict[str, float]])` — `stats` = `{metric_name: {p50, p95, p99, max}}`
  - `aggregate_runs(component: str, samples: list[dict[str, float]], errors: int) -> ComponentResult` — samples per-run `{"ttfb_ms": x, "total_ms": y}` → percentiles từng metric qua `percentiles_ms`
  - `flatten(results: list[ComponentResult]) -> dict[str, float]` — `{"stt_ttfb_p50_ms": ..., "stt_error_rate": ...}` cho registry
- `evals/bench/stt.py`: `async measure_stt(*, url: str, token: str, pcm: bytes, runs: int = 10) -> ComponentResult` — mỗi run: mở WS, blast frame 640 bytes (20ms@16k, KHÔNG gửi `eos` — xem docstring `scripts/load_test/v2/phase_a_stt.py`), `ttfb_ms` = tới message JSON đầu tiên (`partial` hoặc `final`), `total_ms` = tới `{"type":"final"}`; run đầu là warm-up bị loại; lỗi/timeout 20s → đếm `errors`, không crash.
- `evals/bench/tts.py`: `async measure_tts(*, url: str, token: str, text: str, voice: str | None, runs: int = 10) -> ComponentResult` — gửi `{"type":"synthesize","text":...,["voice":...]}`, `ttfb_ms` = binary chunk đầu, `total_ms` = tới `{"type":"end"}`; thêm metric `audio_bytes` (tổng byte PCM để tính RTF ngoài band).
- `evals/bench/speaker.py`: `async measure_speaker(*, url: str, pcm: bytes, runs: int = 10) -> ComponentResult` — httpx POST `{url}/embed` body `{"audio_b64": base64(pcm)}`, `total_ms` = round-trip, validate response có key `embedding`.
- Env nguồn endpoint (đọc trong CLI Task 13, không hardcode trong module): `STT_SERVICE_URL` (default `ws://127.0.0.1:8770/stt`), `TTS_SERVICE_URL` (`ws://127.0.0.1:8771/tts`), `SPEAKER_REMOTE_URL`, `VOICE_SERVICE_AUTH_TOKEN`, `VIENEU_VOICE_ID`.

- [ ] **Step 1: Test fail (chỉ phần thuần)**

```python
# tests/unit/evals/bench/test_results.py
from evals.bench.results import aggregate_runs, flatten


def test_aggregate_and_flatten():
    samples = [{"ttfb_ms": 100.0, "total_ms": 500.0}, {"ttfb_ms": 200.0, "total_ms": 600.0}]
    res = aggregate_runs("stt", samples, errors=1)
    assert res.stats["ttfb_ms"]["p50"] == 100.0
    assert res.runs == 2 and res.errors == 1
    flat = flatten([res])
    assert flat["stt_ttfb_p50_ms"] == 100.0
    assert flat["stt_total_p95_ms"] == 600.0
    assert abs(flat["stt_error_rate"] - 1 / 3) < 1e-9  # errors / (runs + errors)


def test_aggregate_empty():
    res = aggregate_runs("tts", [], errors=3)
    assert res.stats == {} and flatten([res])["tts_error_rate"] == 1.0
```

- [ ] **Step 2: Chạy fail**, **Step 3: Implement `results.py`**

```python
# evals/bench/results.py
"""Aggregate kết quả bench per-component — thuần."""

from __future__ import annotations

from dataclasses import dataclass, field

from evals.common import percentiles_ms


@dataclass
class ComponentResult:
    component: str
    runs: int
    errors: int
    stats: dict[str, dict[str, float]] = field(default_factory=dict)


def aggregate_runs(component: str, samples: list[dict[str, float]], errors: int) -> ComponentResult:
    metrics: dict[str, list[float]] = {}
    for sample in samples:
        for key, value in sample.items():
            metrics.setdefault(key, []).append(value)
    return ComponentResult(
        component=component, runs=len(samples), errors=errors,
        stats={k: percentiles_ms(v) for k, v in metrics.items()},
    )


def flatten(results: list[ComponentResult]) -> dict[str, float]:
    out: dict[str, float] = {}
    for res in results:
        for metric, pcts in res.stats.items():
            for pname in ("p50", "p95"):
                if pname in pcts:
                    out[f"{res.component}_{metric.removesuffix('_ms')}_{pname}_ms"] = pcts[pname]
        attempts = res.runs + res.errors
        out[f"{res.component}_error_rate"] = (res.errors / attempts) if attempts else 0.0
    return out
```

- [ ] **Step 4: Implement 3 module service** (network — không unit test, smoke qua CLI Task 13):

```python
# evals/bench/stt.py
"""Bench STT service remote (WS). Protocol + no-eos rationale: scripts/load_test/v2/phase_a_stt.py."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time

from evals.bench.results import ComponentResult, aggregate_runs

_FRAME_BYTES = 640  # 20 ms @ 16 kHz PCM16


async def _once(url: str, token: str, pcm: bytes, timeout_s: float = 20.0) -> dict[str, float]:
    import websockets  # noqa: PLC0415

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    t0 = time.perf_counter()
    ttfb: list[float] = []
    done = asyncio.Event()

    async with websockets.connect(url, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        async def recv() -> None:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                if not ttfb:
                    ttfb.append((time.perf_counter() - t0) * 1000.0)
                if json.loads(raw).get("type") == "final":
                    done.set()
                    return

        rx = asyncio.create_task(recv())
        for off in range(0, len(pcm), _FRAME_BYTES):
            await ws.send(pcm[off:off + _FRAME_BYTES])
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout_s)
        finally:
            rx.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await rx
    return {"ttfb_ms": ttfb[0] if ttfb else 0.0, "total_ms": (time.perf_counter() - t0) * 1000.0}


async def measure_stt(*, url: str, token: str, pcm: bytes, runs: int = 10) -> ComponentResult:
    samples: list[dict[str, float]] = []
    errors = 0
    with contextlib.suppress(Exception):
        await _once(url, token, pcm)  # warm-up, bỏ kết quả
    for _ in range(runs):
        try:
            samples.append(await _once(url, token, pcm))
        except Exception:  # noqa: BLE001 — một run lỗi là một điểm error_rate, không crash bench
            errors += 1
    return aggregate_runs("stt", samples, errors)
```

```python
# evals/bench/tts.py
"""Bench TTS service remote (WS). Protocol: scripts/load_test/v2/phase_a_tts.py."""

from __future__ import annotations

import contextlib
import json
import time

from evals.bench.results import ComponentResult, aggregate_runs


async def _once(url: str, token: str, text: str, voice: str | None) -> dict[str, float]:
    import websockets  # noqa: PLC0415

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    msg: dict = {"type": "synthesize", "text": text}
    if voice:
        msg["voice"] = voice
    t0 = time.perf_counter()
    ttfb = 0.0
    audio_bytes = 0
    async with websockets.connect(url, additional_headers=headers, max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps(msg))
        async for raw in ws:
            if isinstance(raw, bytes):
                if not audio_bytes:
                    ttfb = (time.perf_counter() - t0) * 1000.0
                audio_bytes += len(raw)
            elif json.loads(raw).get("type") == "end":
                break
    if not audio_bytes:
        raise ValueError("no PCM received")
    return {"ttfb_ms": ttfb, "total_ms": (time.perf_counter() - t0) * 1000.0, "audio_bytes": float(audio_bytes)}


async def measure_tts(*, url: str, token: str, text: str, voice: str | None, runs: int = 10) -> ComponentResult:
    samples: list[dict[str, float]] = []
    errors = 0
    with contextlib.suppress(Exception):
        await _once(url, token, text, voice)
    for _ in range(runs):
        try:
            samples.append(await _once(url, token, text, voice))
        except Exception:  # noqa: BLE001
            errors += 1
    return aggregate_runs("tts", samples, errors)
```

```python
# evals/bench/speaker.py
"""Bench speaker-embedding service (HTTP). Contract: POST /embed {"audio_b64"} → {"embedding": [...]}
(src/noble_agent/voice/service/speaker_server.py docstring)."""

from __future__ import annotations

import base64
import contextlib
import time

from evals.bench.results import ComponentResult, aggregate_runs


async def _once(url: str, pcm: bytes) -> dict[str, float]:
    import httpx  # noqa: PLC0415

    t0 = time.perf_counter()
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(f"{url.rstrip('/')}/embed", json={"audio_b64": base64.b64encode(pcm).decode()})
        resp.raise_for_status()
        if not resp.json().get("embedding"):
            raise ValueError("no embedding in response")
    return {"total_ms": (time.perf_counter() - t0) * 1000.0}


async def measure_speaker(*, url: str, pcm: bytes, runs: int = 10) -> ComponentResult:
    samples: list[dict[str, float]] = []
    errors = 0
    with contextlib.suppress(Exception):
        await _once(url, pcm)
    for _ in range(runs):
        try:
            samples.append(await _once(url, pcm))
        except Exception:  # noqa: BLE001
            errors += 1
    return aggregate_runs("speaker", samples, errors)
```

Copy fixture: `mkdir -p evals/bench/fixtures && cp scripts/load_test/v2/fixture_16k.pcm evals/bench/fixtures/`

- [ ] **Step 5: Pass + lint + commit** — `git commit -m "feat(evals): service bench stt/tts/speaker + pure result aggregation"`

---

### Task 13: Bench VAD + LLM + CLI `python -m evals bench`

**Files:**
- Create: `evals/bench/vad.py`, `evals/bench/llm.py`
- Modify: `evals/__main__.py` (subcommand `bench`)
- Test: `tests/unit/evals/bench/test_vad.py` (chỉ phần cắt chunk thuần)

**Interfaces:**
- `evals/bench/vad.py`:
  - `iter_chunks(pcm: bytes, chunk_bytes: int) -> list[bytes]` (thuần — chỉ chunk đủ size)
  - `measure_vad(pcm: bytes) -> ComponentResult` — sync; import `SileroVAD, CHUNK_SAMPLES` từ `noble_agent.voice.vad.silero` (Y HỆT worker — cùng model + settings, spec §7), đo `chunk_ms` per-chunk qua `time.perf_counter`, thêm metric tổng `throughput_chunks_per_s` in ra console. Load model 1 lần ngoài vòng đo.
- `evals/bench/llm.py`: `async measure_llm(*, prompt: str, runs: int = 5) -> ComponentResult` — dùng `noble_agent.agent.llm.streaming.StreamingLLM.create(session_id)` + callback `on_token` đo `ttft_ms`/`total_ms`, theo ĐÚNG pattern `tests/bench_estate/runner.py::_create_llm` + `_stream_with_timings` (đọc file đó khi implement để khớp chữ ký `stream_completion`); session_id = `f"eval:bench-llm:{uuid4().hex[:8]}"`; prompt mặc định `"Chào em, cho anh hỏi Noble có những dự án nào?"`.
- CLI: `python -m evals bench [--components stt,tts,speaker,vad,llm] [--runs 10]` — mặc định chạy TẤT CẢ; component nào thiếu env endpoint hoặc lỗi cả (`runs == 0`) chỉ set `verdict` phần đó, KHÔNG chặn phần khác (spec §10). Output: `evals/reports/<run_id>/bench.json` + registry `kind="bench"`, metrics = `flatten(results)`, `verdict = "error"` nếu MỌI component đều 0 run thành công, ngược lại `"pass"`.

- [ ] **Step 1: Test fail**

```python
# tests/unit/evals/bench/test_vad.py
from evals.bench.vad import iter_chunks


def test_iter_chunks_drops_tail():
    chunks = iter_chunks(b"\x00" * 2100, chunk_bytes=1024)
    assert len(chunks) == 2 and all(len(c) == 1024 for c in chunks)
```

- [ ] **Step 2: Chạy fail**, **Step 3: Implement**

```python
# evals/bench/vad.py
"""Bench VAD Silero — import ĐÚNG class worker dùng (cùng model + settings), không sửa src."""

from __future__ import annotations

import os
import time

from evals.bench.results import ComponentResult, aggregate_runs


def iter_chunks(pcm: bytes, chunk_bytes: int) -> list[bytes]:
    return [pcm[off:off + chunk_bytes] for off in range(0, len(pcm) - chunk_bytes + 1, chunk_bytes)]


def measure_vad(pcm: bytes) -> ComponentResult:
    os.environ.setdefault("BILLING_METERING_ENABLED", "false")
    from noble_agent.voice.vad.silero import CHUNK_SAMPLES, SileroVAD  # noqa: PLC0415

    vad = SileroVAD()  # load model 1 lần, ngoài vòng đo
    samples: list[dict[str, float]] = []
    chunks = iter_chunks(pcm, CHUNK_SAMPLES * 2)
    t_all = time.perf_counter()
    for chunk in chunks:
        t0 = time.perf_counter()
        vad.process_chunk(chunk)
        samples.append({"chunk_ms": (time.perf_counter() - t0) * 1000.0})
    wall_s = time.perf_counter() - t_all
    result = aggregate_runs("vad", samples, errors=0)
    if wall_s > 0:
        print(f"vad throughput: {len(chunks) / wall_s:.0f} chunks/s ({len(chunks)} chunks)")
    return result
```

```python
# evals/bench/llm.py
"""Bench LLM TTFT/total qua provider chain đang pin — cùng seam StreamingLLM bench_estate dùng."""

from __future__ import annotations

import time
import uuid

from evals.bench.results import ComponentResult, aggregate_runs

DEFAULT_PROMPT = "Chào em, cho anh hỏi Noble có những dự án nào?"


async def _once(prompt: str) -> dict[str, float]:
    from noble_agent.agent.llm.streaming import StreamingLLM  # noqa: PLC0415

    llm = await StreamingLLM.create(f"eval:bench-llm:{uuid.uuid4().hex[:8]}")
    t0 = time.perf_counter()
    ttft: list[float] = []

    def on_token(_tok: str) -> None:
        if not ttft:
            ttft.append((time.perf_counter() - t0) * 1000.0)

    # Chữ ký stream: theo tests/bench_estate/runner.py::_stream_with_timings — đọc file đó
    # khi implement và gọi đúng method nó gọi (cùng seam, đã proven).
    await llm.stream_response(user_text=prompt, on_token=on_token)
    return {"ttft_ms": ttft[0] if ttft else 0.0, "total_ms": (time.perf_counter() - t0) * 1000.0}


async def measure_llm(*, prompt: str = DEFAULT_PROMPT, runs: int = 5) -> ComponentResult:
    samples: list[dict[str, float]] = []
    errors = 0
    for _ in range(runs):
        try:
            samples.append(await _once(prompt))
        except Exception:  # noqa: BLE001
            errors += 1
    return aggregate_runs("llm", samples, errors)
```

**Lưu ý executor:** method stream của `StreamingLLM` phải lấy đúng tên từ `tests/bench_estate/runner.py::_stream_with_timings` (file đó đang chạy production hằng ngày) — nếu là `stream_completion(...)` với chữ ký khác thì sửa `_once` theo, KHÔNG sửa src.

- [ ] **Step 4: Nối CLI**

```python
    sp = sub.add_parser("bench")
    sp.add_argument("--components", default="stt,tts,speaker,vad,llm")
    sp.add_argument("--runs", type=int, default=10)
```

```python
def _cmd_bench(args: argparse.Namespace) -> int:
    os.environ["BILLING_METERING_ENABLED"] = "false"
    from evals.bench.results import flatten

    wanted = {x.strip() for x in args.components.split(",") if x.strip()}
    pcm = (Path(__file__).resolve().parent / "bench" / "fixtures" / "fixture_16k.pcm").read_bytes()
    token = os.getenv("VOICE_SERVICE_AUTH_TOKEN", "").strip()
    results = []

    async def _drive():
        if "stt" in wanted:
            from evals.bench.stt import measure_stt
            results.append(await measure_stt(url=os.getenv("STT_SERVICE_URL", "ws://127.0.0.1:8770/stt"),
                                             token=token, pcm=pcm, runs=args.runs))
        if "tts" in wanted:
            from evals.bench.tts import measure_tts
            results.append(await measure_tts(
                url=os.getenv("TTS_SERVICE_URL", "ws://127.0.0.1:8771/tts"), token=token,
                text="Dạ em xin phép giới thiệu về dự án của Noble, đây là một dự án căn hộ cao cấp ạ.",
                voice=os.getenv("VIENEU_VOICE_ID", "").strip() or None, runs=args.runs))
        if "speaker" in wanted:
            url = os.getenv("SPEAKER_REMOTE_URL", "").strip()
            if url:
                from evals.bench.speaker import measure_speaker
                results.append(await measure_speaker(url=url, pcm=pcm, runs=args.runs))
            else:
                print("speaker: SPEAKER_REMOTE_URL rỗng — bỏ qua")
        if "llm" in wanted:
            from evals.bench.llm import measure_llm
            results.append(await measure_llm(runs=min(args.runs, 5)))

    if "vad" in wanted:
        from evals.bench.vad import measure_vad
        results.append(measure_vad(pcm))
    asyncio.run(_drive())

    run_id = new_run_id("bench")
    run_dir = _RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    metrics = flatten(results)
    payload = {"run_id": run_id, "components": [
        {"component": r.component, "runs": r.runs, "errors": r.errors, "stats": r.stats} for r in results]}
    (run_dir / "bench.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    all_dead = bool(results) and all(r.runs == 0 for r in results)
    verdict = "error" if (all_dead or not results) else "pass"
    append_entry(make_entry(run_id=run_id, kind="bench",
                            config={"components": sorted(wanted), "runs": args.runs},
                            metrics=metrics, gates={}, verdict=verdict, report_dir=str(run_dir) + "/"))
    for r in results:
        print(f"{r.component:<8} runs={r.runs} errors={r.errors} "
              + " ".join(f"{m}.p50={p['p50']:.0f}" for m, p in r.stats.items() if "p50" in p))
    print(f"\nbench.json: {run_dir / 'bench.json'}")
    return 0 if verdict == "pass" else 1
```

(+ nhánh dispatch trong `main()`.)

- [ ] **Step 5: Pass + lint + commit** — `git commit -m "feat(evals): vad (in-process Silero) + llm bench + bench CLI with per-component isolation"`

---

### Task 14: Load — port ramp engine

**Files:**
- Create: `evals/load/__init__.py`, `evals/load/ramp.py` (copy `scripts/load_test/v2/common.py`)
- Test: `tests/unit/evals/load/{__init__.py,test_ramp.py}` (copy `scripts/load_test/v2/test_common.py`)

**Interfaces:**
- Produces (giữ nguyên tên hàm cũ, module mới `evals.load.ramp`): `ramp_schedule`, `percentiles`, `StepResult`, `is_broken`, `run_step`, `CampaignResult`, `knee_by_plateau`, `run_campaign`, `write_results_md`, `MakeRequest`

- [ ] **Step 1: Copy + sửa import**

```bash
mkdir -p evals/load tests/unit/evals/load
touch evals/load/__init__.py tests/unit/evals/load/__init__.py
cp scripts/load_test/v2/common.py evals/load/ramp.py
cp scripts/load_test/v2/test_common.py tests/unit/evals/load/test_ramp.py
```

Trong `tests/unit/evals/load/test_ramp.py`: bỏ mọi `sys.path.insert`/`import common`, thay bằng `from evals.load import ramp as common` (giữ alias `common` để thân test không phải đổi).

- [ ] **Step 2: Chạy** — `python -m pytest tests/unit/evals/load/test_ramp.py -q` → PASS

- [ ] **Step 3: Lint + commit** — `git commit -m "feat(evals): port load ramp engine (schedule/knee/percentiles) from load_test v2"`

---

### Task 15: `evals/load/chat_ccu.py` — CCU chat + assert admission

**Files:**
- Create: `evals/load/chat_ccu.py`
- Modify: `evals/__main__.py` (subcommand `load`, target `chat`)
- Test: `tests/unit/evals/load/test_chat_ccu.py`

**Interfaces:**
- Consumes: `evals.load.ramp`, protocol chat WS (mẫu: `scripts/load_test/v2/phase_b_chat.py` — greeting `{"type":"session_id"}`, gửi `{"type":"user_text","text":...}`, đợi `{"type":"done"}`)
- Produces:
  - `TURNS: list[str]` — 4 câu kịch bản (copy từ phase_b_chat.py)
  - `async run_chat_ccu(*, base_ws: str, max_concurrency: int, hold_s: float) -> CampaignResult` — mỗi virtual user giữ 1 session WS (`?session=eval:load:<idx>-<ts>`), loop turns; per-turn latency; step theo `ramp_schedule`; knee `knee_by_plateau`
  - `async assert_admission(*, base_ws: str, base_http: str, cap: int, extra: int = 5) -> dict` — mở `cap + extra` WS idle đồng thời; trả `{"over_cap_closed_4029": int, "ready_503_at_saturation": bool, "ready_200_after_drain": bool}`. Sau khi mở đủ: GET `{base_http}/health/ready` (httpx) kỳ vọng 503; đóng hết; poll ready tới 200 (timeout 30s). Đếm số WS bị close với `code == 4029` (websockets raise `ConnectionClosedError` có `rcvd.code`).
  - `summarize_admission(res: dict, cap: int) -> tuple[dict[str, str], bool]` (THUẦN — test được): map thành gates `{"admission_4029": "pass|fail", "ready_503": ..., "ready_recover": ...}` + ok tổng; `admission_4029` pass khi `over_cap_closed_4029 >= 1`
- CLI: `python -m evals load --target chat [--max 64] [--hold 60] [--host ws://localhost:8766] [--admission-cap N]` — ramp luôn chạy; admission CHỈ chạy khi truyền `--admission-cap` (đắt: mở N+5 socket). Output `evals/reports/<run_id>/chat_ccu.md` (qua `write_results_md`) + registry `kind="load"`, metrics `{"knee_ccu": knee, "p95_at_knee_ms": ..., "err_rate_at_knee": ...}`, gates từ `summarize_admission` (rỗng nếu không chạy admission), verdict: `error` nếu mọi step err_rate 1.0, `fail` nếu admission chạy mà không pass, ngược lại `pass`.

- [ ] **Step 1: Test fail (phần thuần)**

```python
# tests/unit/evals/load/test_chat_ccu.py
from evals.load.chat_ccu import summarize_admission


def test_admission_pass():
    gates, ok = summarize_admission(
        {"over_cap_closed_4029": 3, "ready_503_at_saturation": True, "ready_200_after_drain": True}, cap=10)
    assert ok and gates == {"admission_4029": "pass", "ready_503": "pass", "ready_recover": "pass"}


def test_admission_fail_when_no_4029():
    gates, ok = summarize_admission(
        {"over_cap_closed_4029": 0, "ready_503_at_saturation": True, "ready_200_after_drain": True}, cap=10)
    assert not ok and gates["admission_4029"] == "fail"
```

- [ ] **Step 2: Chạy fail**, **Step 3: Implement**

```python
# evals/load/chat_ccu.py
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
```

- [ ] **Step 4: Nối CLI** — sub-parser `load` (`--target` choices `chat|voice|service` — voice/service ở Task 16, `--max` default 64, `--hold` default 60.0, `--host` default `ws://localhost:8766`, `--admission-cap` type int default None); handler target chat:

```python
def _cmd_load_chat(args: argparse.Namespace) -> int:
    from evals.load.chat_ccu import assert_admission, run_chat_ccu, summarize_admission
    from evals.load.ramp import write_results_md

    base_ws = args.host
    base_http = base_ws.replace("ws://", "http://", 1).replace("wss://", "https://", 1)
    run_id = new_run_id("load")
    run_dir = _RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    result = asyncio.run(run_chat_ccu(base_ws=base_ws, max_concurrency=args.max, hold_s=args.hold))
    write_results_md(result, run_dir / "chat_ccu.md")
    knee_step = next((s for s in result.steps if s.concurrency == result.knee), result.steps[-1])
    metrics = {"knee_ccu": float(result.knee or 0),
               "p95_at_knee_ms": (knee_step.latency.get("p95", 0.0)) * 1000.0,
               "err_rate_at_knee": knee_step.err_rate}
    gates: dict[str, str] = {}
    admission_ok = True
    if args.admission_cap:
        res = asyncio.run(assert_admission(base_ws=base_ws, base_http=base_http, cap=args.admission_cap))
        gates, admission_ok = summarize_admission(res, args.admission_cap)
        (run_dir / "admission.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    all_dead = all(s.err_rate >= 1.0 for s in result.steps)
    verdict = "error" if all_dead else ("pass" if admission_ok else "fail")
    append_entry(make_entry(run_id=run_id, kind="load",
                            config={"target": "chat", "host": base_ws, "max": args.max, "hold_s": args.hold,
                                    "admission_cap": args.admission_cap},
                            metrics=metrics, gates=gates, verdict=verdict, report_dir=str(run_dir) + "/"))
    print(f"knee={result.knee} → {run_dir / 'chat_ccu.md'}")
    return 0 if verdict == "pass" else 1
```

- [ ] **Step 5: Pass + lint + commit** — `git commit -m "feat(evals): chat CCU load (ramp + knee) with admission 4029/503 assertions"`

---

### Task 16: `voice_ccu` + `service_ccu`

**Files:**
- Create: `evals/load/voice_ccu.py` (port `scripts/load_test/v2/phase_c_livekit.py`), `evals/load/service_ccu.py`
- Modify: `evals/__main__.py` (target `voice`, `service`)

**Interfaces:**
- `voice_ccu`: port nguyên `phase_c_livekit.py` thành module (bỏ `sys.path.insert` + `import common` → `from evals.load import ramp as common`; bỏ `argparse`/`__main__` → expose `async def run_voice_ccu(*, max_concurrency: int, hold_s: float, out_dir: Path) -> common.CampaignResult` gói logic `_amain` cũ). Số đo giữ nguyên: `ttfr` (audio-end → agent nói) + `total`. **Đây cũng là số full-pipeline voice: chạy `--max 1` = bench pipeline đơn** (spec §7 dòng cuối).
- `service_ccu`: ramp cho từng service — tái dùng `_once` của Task 12:

```python
# evals/load/service_ccu.py
"""Ramp riêng từng service STT/TTS/speaker — trả lời "component nào nghẽn trước" (spec §8)."""

from __future__ import annotations

import os
from pathlib import Path

from evals.load import ramp


async def run_service_ccu(component: str, *, max_concurrency: int, hold_s: float) -> ramp.CampaignResult:
    pcm = (Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "fixture_16k.pcm").read_bytes()
    token = os.getenv("VOICE_SERVICE_AUTH_TOKEN", "").strip()
    if component == "stt":
        from evals.bench.stt import _once
        url = os.getenv("STT_SERVICE_URL", "ws://127.0.0.1:8770/stt")

        async def make_request() -> float:
            return (await _once(url, token, pcm))["total_ms"] / 1000.0
    elif component == "tts":
        from evals.bench.tts import _once
        url = os.getenv("TTS_SERVICE_URL", "ws://127.0.0.1:8771/tts")
        text = "Dạ em xin phép giới thiệu về dự án của Noble ạ."

        async def make_request() -> float:
            return (await _once(url, token, text, os.getenv("VIENEU_VOICE_ID", "").strip() or None))["total_ms"] / 1000.0
    elif component == "speaker":
        from evals.bench.speaker import _once
        url = os.getenv("SPEAKER_REMOTE_URL", "")
        if not url:
            raise ValueError("SPEAKER_REMOTE_URL rỗng")

        async def make_request() -> float:
            return (await _once(url, pcm))["total_ms"] / 1000.0
    else:
        raise ValueError(f"unknown component {component!r}; allowed stt|tts|speaker")
    return await ramp.run_campaign(make_request, label=f"{component} {url}",
                                   ramp=ramp.ramp_schedule(max_concurrency=max_concurrency),
                                   hold_s=hold_s, full_ramp=True)
```

- CLI: `--target voice` → `run_voice_ccu`, ghi `voice_ccu.md` + registry (metrics `knee_ccu`, `ttfr_p95_at_knee_ms` nếu campaign expose); `--target service --component stt|tts|speaker` → `run_service_ccu`, ghi `<component>_ccu.md` + registry metrics `{f"{component}_knee_ccu": ...}`. Cả hai `kind="load"`, verdict `error` nếu mọi step err 100%, ngược lại `pass`.

- [ ] **Step 1: Port voice_ccu** — `cp scripts/load_test/v2/phase_c_livekit.py evals/load/voice_ccu.py`, sửa import như trên, gói `_amain` thành `run_voice_ccu`. Giữ nguyên phần mint token / synthetic audio / data-channel events.

- [ ] **Step 2: Viết service_ccu** (code trên) + thêm `--component` vào sub-parser `load`, dispatch 2 target mới trong CLI (mẫu handler theo `_cmd_load_chat`, không admission).

- [ ] **Step 3: Verify import-only** (không có LiveKit/service ở CI):

```bash
python -c "import evals.load.voice_ccu, evals.load.service_ccu; print('ok')"
python -m pytest tests/unit/evals/ -q
```

Expected: `ok`, tests PASS. (Nếu `voice_ccu` import LiveKit ở module-level và lib thiếu → chuyển import đó vào trong hàm.)

- [ ] **Step 4: Lint + commit** — `git commit -m "feat(evals): voice CCU (LiveKit port) + per-service ramp (stt/tts/speaker)"`

---

### Task 17: `python -m evals report` — TREND.md

**Files:**
- Create: `evals/report.py`
- Modify: `evals/__main__.py` (subcommand `report`)
- Test: `tests/unit/evals/test_report.py`

**Interfaces:**
- Produces: `render_trend(entries: list[dict], *, last_n: int = 20) -> str` (THUẦN) — Markdown gồm: (1) bảng "run mới nhất theo kind" (kind, run_id, ts, verdict, 3-5 metric chính); (2) mỗi kind một bảng lịch sử `last_n` run (ts, git_sha, verdict + metric chính của kind: quality → `policy_pass_rate, arg_accuracy, ttft_p95_ms`; rag → `recall_at_5, mrr, empty_rate`; bench → `stt_total_p95_ms, tts_ttfb_p95_ms, llm_ttft_p95_ms`; load → `knee_ccu`); (3) khối "Δ vs run pass trước đó" cho run quality mới nhất (delta từng metric số).
- CLI `report`: đọc `read_entries()` → ghi `evals/reports/TREND.md` + in ra stdout.

- [ ] **Step 1: Test fail**

```python
# tests/unit/evals/test_report.py
from evals.report import render_trend


def _e(kind, run_id, verdict, metrics, ts="2026-08-24T10:00:00+00:00"):
    return {"run_id": run_id, "ts": ts, "kind": kind, "git_sha": "abc", "config": {},
            "metrics": metrics, "gates": {}, "verdict": verdict, "report_dir": ""}


def test_latest_per_kind_and_delta():
    entries = [
        _e("quality", "q1", "pass", {"policy_pass_rate": 1.0, "ttft_p95_ms": 800.0}),
        _e("quality", "q2", "pass", {"policy_pass_rate": 0.9, "ttft_p95_ms": 900.0},
           ts="2026-08-25T10:00:00+00:00"),
        _e("bench", "b1", "pass", {"stt_total_p95_ms": 1200.0}),
    ]
    md = render_trend(entries)
    assert "q2" in md and "b1" in md
    assert "Δ" in md and "-0.1" in md  # policy_pass_rate 1.0 → 0.9


def test_empty_registry():
    assert "chưa có run nào" in render_trend([])
```

- [ ] **Step 2: Chạy fail**, **Step 3: Implement**

```python
# evals/report.py
"""TREND.md — bề mặt monitoring định kỳ, sinh từ registry.jsonl (spec §9.2). Thuần."""

from __future__ import annotations

_KIND_METRICS: dict[str, tuple[str, ...]] = {
    "quality": ("policy_pass_rate", "arg_accuracy", "retrieval_hit_rate", "ttft_p95_ms", "judge_quality_mean"),
    "rag": ("recall_at_1", "recall_at_5", "mrr", "empty_rate", "retrieval_p95_ms"),
    "bench": ("stt_total_p95_ms", "tts_ttfb_p95_ms", "speaker_total_p95_ms", "vad_chunk_p95_ms", "llm_ttft_p95_ms"),
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

    lines = ["# Evals trend", "", "## Run mới nhất theo kind", "",
             "| kind | run_id | ts | verdict | metrics chính |", "|---|---|---|---|---|"]
    for kind in ("quality", "rag", "bench", "load"):
        rows = by_kind.get(kind)
        if not rows:
            continue
        latest = rows[-1]
        keys = _KIND_METRICS.get(kind, ())
        summary = ", ".join(f"{k}={_fmt(latest['metrics'].get(k))}" for k in keys if k in latest["metrics"])
        lines.append(f"| {kind} | `{latest['run_id']}` | {latest['ts'][:19]} | {latest['verdict']} | {summary} |")

    for kind, rows in by_kind.items():
        keys = _KIND_METRICS.get(kind, ())
        lines += ["", f"## {kind} — {min(len(rows), last_n)} run gần nhất", "",
                  "| ts | run_id | git | verdict | " + " | ".join(keys) + " |",
                  "|---|---|---|---|" + "---|" * len(keys)]
        for e in rows[-last_n:]:
            vals = " | ".join(_fmt(e["metrics"].get(k)) for k in keys)
            lines.append(f"| {e['ts'][:19]} | `{e['run_id']}` | {e.get('git_sha', '')} | {e['verdict']} | {vals} |")

    quality = by_kind.get("quality", [])
    if len(quality) >= 2:
        latest = quality[-1]
        prev_pass = next((e for e in reversed(quality[:-1]) if e["verdict"] == "pass"), None)
        if prev_pass:
            lines += ["", f"## Δ quality: `{latest['run_id']}` vs `{prev_pass['run_id']}` (pass gần nhất)", ""]
            for k in sorted(set(latest["metrics"]) & set(prev_pass["metrics"])):
                a, b = prev_pass["metrics"].get(k), latest["metrics"].get(k)
                if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                    lines.append(f"- `{k}`: {_fmt(a)} → {_fmt(b)} (Δ {_fmt(b - a)})")
    return "\n".join(lines) + "\n"
```

CLI handler:

```python
def _cmd_report(args: argparse.Namespace) -> int:  # noqa: ARG001
    from evals.report import render_trend
    from evals.registry import read_entries

    md = render_trend(read_entries())
    out = _RUNS / "TREND.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"→ {out}")
    return 0
```

- [ ] **Step 4: Pass + lint + commit** — `git commit -m "feat(evals): TREND.md report from registry"`

---

### Task 18: Make targets + README

**Files:**
- Modify: `Makefile` — THAY khối `# ---- Eval harness (tests/eval)` (các target `eval-list/eval-run/eval-gate/eval-score/eval-test`) bằng khối mới; GIỮ nguyên các target `eval-estate*`
- Create: `evals/README.md`

**Interfaces:** Make targets mới (spec §9.3):

```make
# ---- Evals harness (evals/) ------------------------------------------------
# Spec: docs/superpowers/specs/2026-08-24-unified-evals-harness-design.md
# quality/rag cần Redis + LLM key + RAG backend; bench/load cần service sống;
# report/selftest không cần gì.
eval-list:
	python -m evals list $(ARGS)

eval-quality:
	python -m evals run $(ARGS)

eval-quality-smoke:
	python -m evals run --case pol-001,pol-002,tool-001 $(ARGS)

eval-quality-full:
	python -m evals run --judge $(ARGS)

eval-score:
	python -m evals score --run-dir evals/reports/$(RUN) $(ARGS)

eval-rag:
	python -m evals rag $(ARGS)

eval-bench:
	python -m evals bench $(ARGS)

eval-load:
	python -m evals load --target chat $(ARGS)

eval-report:
	python -m evals report

# Dành cho cron/CI định kỳ: smoke + bench + report; suite lỗi vẫn chạy suite sau.
eval-periodic:
	-python -m evals run --case pol-001,pol-002,tool-001
	-python -m evals bench --runs 5
	python -m evals report

eval-selftest:
	python -m pytest tests/unit/evals/ -q
```

**Lưu ý:** 3 case id trong `eval-quality-smoke` phải là id THẬT — lấy từ `python -m evals list` (3 case đầu, 1 policy + 2 tool hoặc tương tự) và ghi đúng id vào Makefile.

- [ ] **Step 1: Sửa Makefile** như trên (chạy `python -m evals list` trước để lấy 3 id thật cho smoke).

- [ ] **Step 2: Viết `evals/README.md`** — ngắn (~80 dòng): mục đích, sơ đồ 4 suite, bảng lệnh make, quy trình gen-golden → duyệt tay → approved, quy ước `golden.evidence` nguyên văn, cảnh báo load test chỉ chạy staging/dev (LiveKit Cloud dùng chung — gotcha giật cuộc gọi thật), registry schema 1 dòng, cách đặt cron `make eval-periodic`.

- [ ] **Step 3: Verify** — `make eval-selftest && make eval-report && ruff check evals/`

- [ ] **Step 4: Commit** — `git commit -m "feat(evals): make targets (eval-quality/rag/bench/load/report/periodic) + README"`

---

### Task 19: Migration — đối chiếu song song rồi xoá `tests/eval`

**Files:**
- Delete: `tests/eval/` (toàn bộ)
- Modify: `.gitignore` (xoá dòng `tests/eval/runs/`), `CLAUDE.md` (mục Commands + Change Log), `docs/CHANGELOG-agent.md` (entry mới lên đầu), `docs/handoff/2026-08-18-eval-harness-p0-handoff.md` (thêm 1 dòng đầu file: superseded)

**Điều kiện tiên quyết:** cần Redis + LLM key + RAG backend sống (`.env` đầy đủ) — đây là task DUY NHẤT cần infra. Nếu infra không sẵn, DỪNG và báo user thay vì xoá không đối chiếu.

- [ ] **Step 1: Chạy song song đối chiếu (spec §12.2)**

```bash
python -m tests.eval run --case pol-001,pol-002,tool-001 --run-id compare-old
python -m evals run --case pol-001,pol-002,tool-001 --run-id compare-new
```

(Dùng đúng 3 case id đã chọn ở Task 18.) So sánh: mở `tests/eval/runs/compare-old/scores.json` và `evals/reports/compare-new/scores.json` — các metric DETERMINISTIC (`policy_violations`, `tool_selection_accuracy`, `arg_accuracy`, `unnecessary_call_rate`, `cases_errored`, `cases_gated`) phải KHỚP NHAU TUYỆT ĐỐI (LLM non-deterministic giữa 2 run có thể làm lệch — nếu lệch, chạy lại cả hai một lần nữa; lệch lặp lại = bug port, DỪNG và điều tra, không xoá).

Expected: metric deterministic khớp; harness mới có thêm `retrieval_hit_rate`/`ttft_p95_ms` (None/`missing` được — chưa có case grounding).

- [ ] **Step 2: Xoá harness cũ**

```bash
git rm -r tests/eval
```

Xoá dòng `tests/eval/runs/` khỏi `.gitignore`. Kiểm không còn tham chiếu sống:

```bash
grep -rn "tests\.eval\|tests/eval" --include="*.py" --include="Makefile" --include="*.toml" . \
  | grep -v "^\./docs/" | grep -v node_modules
```

Expected: RỖNG (docs cũ được phép còn nhắc tên).

- [ ] **Step 3: Chạy lại toàn bộ kiểm chứng**

```bash
python -m pytest tests/unit/evals/ -q     # PASS
make lint                                  # không finding mới
python -m evals list                       # vẫn 30 case
```

- [ ] **Step 4: Cập nhật docs theo self-maintenance rules**

1. `CLAUDE.md` mục Commands: thay khối lệnh eval cũ (`make eval-run`… nếu có nhắc) bằng `make eval-quality / eval-rag / eval-bench / eval-load / eval-report / eval-periodic`; nhắc registry `evals/registry.jsonl`.
2. `docs/CHANGELOG-agent.md`: thêm entry đầu bảng — "2026-08-24 | Harness evals/ thống nhất thay tests/eval: quality (per-turn/multi-turn + judge + latency + rag-grounding), rag component (recall@k/MRR, golden duyệt tay), bench per-component (STT/TTS/speaker/VAD/LLM), CCU load (chat admission 4029/503, voice LiveKit, per-service) + registry.jsonl tracked. | Cần chuẩn đánh giá model + monitoring định kỳ; tests/eval cũ thiếu RAG scorer/registry/latency aggregation."
3. `CLAUDE.md` bảng Change Log: thêm bản 1–2 câu của entry trên lên đầu, XOÁ entry thứ 11.
4. Đầu `docs/handoff/2026-08-18-eval-harness-p0-handoff.md` thêm: `> **SUPERSEDED 2026-08-24** bởi evals/ — xem docs/superpowers/specs/2026-08-24-unified-evals-harness-design.md`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(evals)!: replace tests/eval with unified evals/ harness

Parallel-run comparison passed (deterministic metrics identical).
Docs updated per CLAUDE.md self-maintenance rules."
```

---

## Self-Review (đã chạy)

- **Spec coverage:** §4 layout → Task 1–17; §5 quality (port + latency + judge + rag scorer + prefix + billing guard) → Task 3–8; §6 rag (+ gen-golden duyệt tay, empty-rate warning) → Task 9–11; §7 bench (STT/TTS/speaker/VAD/LLM; full-pipeline chat = quality ttft, full-pipeline voice = voice_ccu --max 1, ghi rõ ở Task 16) → Task 12–13; §8 load (ramp port, chat admission, voice, per-service) → Task 14–16; §9 registry/report/make → Task 2, 17, 18; §10 error handling (preflight, judge ungraded, rag empty-rate, bench per-component isolation, eval-periodic `-` prefix) → rải trong Task 7/8/10/13/18; §11 testing → mỗi task; §12 migration → Task 19; §13 YAGNI tôn trọng (không gate latency, không HTML).
- **Type consistency:** `AxisScore/Finding` dùng chung mọi scorer mới; `run_case(case, *, run_id, agent_factory)` khớp Task 6→7; `ComponentResult/aggregate_runs/flatten` khớp Task 12→13→16; `make_entry/append_entry` khớp Task 2→7/10/13/15/16; `percentiles_ms` key `p50/p95/p99/max` khớp mọi consumer.
- **Điểm executor phải đối chiếu source (đã ghi chú trong task):** chữ ký `DensePrefetch/SparsePrefetch/embed_sparse` (Task 10), method stream của `StreamingLLM` (Task 13), tên helper trong `test_runner.py` cũ (Task 6).
