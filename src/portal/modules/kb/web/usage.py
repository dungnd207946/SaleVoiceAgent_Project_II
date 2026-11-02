"""Đếm chi phí dữ liệu ngoài theo lượt chạy rồi ghi vào `billing.usage_events`.

Mỗi job mang một `UsageMeter` qua `ContextVar`; `WebLlm`, `Grounding`, `WebIndex` tự cộng vào.
Trigger `usage_events_dinh_gia` định giá ngay lúc ghi.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field

import asyncpg

from portal.core.db.session import tenant_conn
from portal.core.jobs import JobResult, current_job
from portal.modules.kb.web.contracts import JOB_SESSION_PREFIX

log = logging.getLogger(__name__)

PURPOSE = "kb_web"
CHANNEL = "kb_web"
DRAFT_SESSION_PREFIX = "kbweb-draft:"

EMBED_PROVIDER = "santa-models"
EMBED_MODEL = "multilingual-e5-large"
GOOGLE = "google"
DASHSCOPE = "dashscope"

TIER_32K = 32_000
TIER_256K = 256_000


def qwen_model(model: str, prompt_tokens: int) -> str:
    """DashScope tính giá theo số token vào của từng lượt gọi; bậc đi vào tên model."""
    if prompt_tokens > TIER_256K:
        return f"{model}>256k"
    if prompt_tokens > TIER_32K:
        return f"{model}>32k"
    return model


@dataclass
class _Tally:
    input_tokens: int = 0
    output_tokens: int = 0
    units: int = 0
    text_units: int = 0


@dataclass
class UsageMeter:
    tallies: dict[tuple[str, str, str], _Tally] = field(default_factory=dict)

    def _at(self, component: str, provider: str, model: str) -> _Tally:
        return self.tallies.setdefault((component, provider, model), _Tally())

    def llm(self, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        t = self._at("llm", provider, model)
        t.input_tokens += max(input_tokens, 0)
        t.output_tokens += max(output_tokens, 0)

    def search(self, model: str) -> None:
        self._at("search", GOOGLE, model).units += 1

    def embed(self, texts: list[str]) -> None:
        self._at("embed", EMBED_PROVIDER, EMBED_MODEL).text_units += sum(len(x) for x in texts)

    def empty(self) -> bool:
        return not any(t.input_tokens or t.output_tokens or t.units or t.text_units for t in self.tallies.values())


_METER: ContextVar[UsageMeter | None] = ContextVar("kbweb_usage_meter", default=None)


def meter() -> UsageMeter | None:
    return _METER.get()


_INSERT = """
INSERT INTO billing.usage_events
       (tenant_id, session_id, channel, seq, component, purpose, provider, model,
        input_tokens, output_tokens, units, text_units, exact)
VALUES (portal.current_tenant(), $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, true)
ON CONFLICT ON CONSTRAINT usage_events_idem DO NOTHING
"""


async def flush(
    pool: asyncpg.Pool,
    tenant: str,
    m: UsageMeter,
    *,
    session_id: str,
    seq: int,
    purpose: str = PURPOSE,
    channel: str = CHANNEL,
) -> None:
    """Ghi trong giao dịch RIÊNG: giao dịch của handler rollback khi job lỗi, mà tiền đã tốn."""
    if m.empty():
        return
    rows = [
        (session_id, channel, seq, comp, purpose, prov, model, t.input_tokens, t.output_tokens, t.units, t.text_units)
        for (comp, prov, model), t in m.tallies.items()
    ]
    try:
        async with tenant_conn(pool, tenant) as conn:
            await conn.executemany(_INSERT, rows)
    except Exception:  # noqa: BLE001 — sổ hỏng không được làm hỏng job
        log.warning("không ghi được usage dữ liệu ngoài %s (tenant %s)", session_id, tenant, exc_info=True)


JobHandler = Callable[[asyncpg.Connection, dict], Awaitable[JobResult]]


def metered(
    handler: JobHandler | None = None,
    *,
    purpose: str = PURPOSE,
    channel: str = CHANNEL,
    session_prefix: str = JOB_SESSION_PREFIX,
) -> JobHandler | Callable[[JobHandler], JobHandler]:
    """Bọc handler: đếm mọi lượt gọi tốn tiền trong job, ghi sổ cả khi job lỗi.

    Dùng trần `metered(h)` cho dữ liệu ngoài, hoặc `metered(h, purpose=...)` cho việc khác.
    """

    def wrap(h: JobHandler) -> JobHandler:
        @functools.wraps(h)
        async def run(conn: asyncpg.Connection, payload: dict) -> JobResult:
            job = current_job()
            tenant = await conn.fetchval("SELECT portal.current_tenant()")
            m = UsageMeter()
            token = _METER.set(m)
            try:
                return await h(conn, payload)
            finally:
                _METER.reset(token)
                if job is not None and tenant:
                    await flush(
                        job.pool,
                        tenant,
                        m,
                        session_id=f"{session_prefix}{job.id}",
                        seq=job.attempt,
                        purpose=purpose,
                        channel=channel,
                    )

        return run

    return wrap(handler) if handler is not None else wrap


class metering:
    """`with metering() as m:` cho lượt gọi ngoài job (soạn câu tìm bài)."""

    def __init__(self) -> None:
        self.meter = UsageMeter()
        self._token = None

    def __enter__(self) -> UsageMeter:
        self._token = _METER.set(self.meter)
        return self.meter

    def __exit__(self, *exc: object) -> None:
        _METER.reset(self._token)
