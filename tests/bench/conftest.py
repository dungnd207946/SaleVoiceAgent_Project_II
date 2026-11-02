"""Bench-suite fixtures and pytest config."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

# Make sure src/ is on sys.path even when bench runs standalone (it relies on
# the top-level tests/conftest.py for that, but be defensive).
import sys

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# Auto-load .env so REDIS_URL etc. are visible without `export`.
def _load_dotenv() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        # Expand `~` so paths like FASTEMBED_CACHE_PATH=~/.cache/fastembed
        # become absolute — onnxruntime / many libs don't expand on open().
        if v.startswith("~"):
            v = os.path.expanduser(v)
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()


# ─── Tunables (env-driven) ───────────────────────────────────────────────
# BENCH_N_RUNS: per-bench operation count (default 50). Lower for smoke,
#   higher for stable percentiles.
# BENCH_WARMUP: drop first N samples to avoid cold-cache noise (default 3).


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@pytest.fixture(scope="session")
def n_runs() -> int:
    return _int_env("BENCH_N_RUNS", 50)


@pytest.fixture(scope="session")
def warmup() -> int:
    return _int_env("BENCH_WARMUP", 3)


@pytest.fixture(scope="session")
def bench_session_id() -> str:
    """Unique session id per pytest run — used by tools that touch Redis
    so we never collide with real production sessions."""
    return f"bench-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
async def _connect_storage():
    """Function-scoped + idempotent: ensure the Redis singleton is connected for
    EACH test (session-scoped async autouse fixtures are flaky under
    pytest-asyncio 1.x). Redis is a hard gate for many tools (update_customer,
    session_store reads) — without it the storage layer no-ops silently
    (cm.redis is None → return). `connect_redis()` is cheap after the first call.
    """
    from noble_agent.storage.connection import get_connection_manager

    cm = get_connection_manager()
    if os.environ.get("REDIS_URL") and cm.redis is None:
        try:
            await cm.connect_redis()
        except Exception as e:
            print(f"  [bench] redis connect failed: {e}")
    yield


@pytest.fixture(scope="session")
def bench_phone() -> str:
    """Throwaway VN phone (10 digits, prefix 09 — passes the project regex)."""
    # Last 8 digits derived from a random uuid hex slice → stable per session
    suffix = uuid.uuid4().hex[:8]
    digits = "".join(c if c.isdigit() else str(ord(c) % 10) for c in suffix)
    return "09" + digits


# ─── Skip markers ────────────────────────────────────────────────────────


def pytest_collection_modifyitems(config, items):
    """If env not configured for cloud tests, mark them skipped at collection
    time so the report shows them as deselected instead of erroring.
    """
    has_redis = bool(os.environ.get("REDIS_URL"))

    skip_redis = pytest.mark.skip(reason="REDIS_URL not set")

    for item in items:
        if "needs_redis" in item.keywords and not has_redis:
            item.add_marker(skip_redis)
