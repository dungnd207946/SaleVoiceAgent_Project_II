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
    """Nạp .env repo-root vào os.environ (override=False) — port từ `_load_dotenv` của harness eval cũ (đã xoá).

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
