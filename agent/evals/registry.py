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
