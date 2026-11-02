# Billing Usage Metering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agent đếm token LLM (4 loại) và thời lượng STT/TTS/VAD/speaker-verify/cuộc gọi mỗi phiên, rồi ghi vào `billing.usage_events` (Postgres do Portal sở hữu) mà không làm tăng độ trễ của đường xử lý.

**Architecture:** Một `UsageMeter` thuần in-memory mỗi phiên (chỉ cộng số, không I/O). `StreamingClient` tự ghi usage vào meter qua một `ContextVar`, nên không đổi chữ ký `stream_completion`. Sau mỗi lượt (`save_all` thành công) và lúc đóng phiên, orchestrator/session gọi `sink.flush` theo kiểu fire-and-forget; sink INSERT một batch với `ON CONFLICT DO NOTHING` và chỉ báo meter "đã ghi" khi INSERT thành công, nên thất bại là tự retry với **đúng `seq` cũ**.

**Tech Stack:** Python 3.11+, asyncpg (qua `storage/postgres_client.pool_for_tenant` + `tenant_conn`), pydantic-settings, pytest (`asyncio_mode=auto`), ruff (line-length 120).

**Spec:** [`docs/superpowers/specs/2026-08-18-billing-usage-metering-design.md`](../specs/2026-08-18-billing-usage-metering-design.md)
**Contract bảng (Portal ship):** [`docs/handoff/agent-postgres-billing-write-contract.md`](../../handoff/agent-postgres-billing-write-contract.md)

## Global Constraints

- **Đường nóng không có I/O.** Trong lúc lượt đang chạy, không lời gọi mạng/đĩa nào phục vụ billing. Task 5 có test giữ điều này.
- **Không ước lượng số liệu.** Thiếu usage từ provider → ghi `exact=False` + token 0. Không đoán, không suy ra từ độ dài text.
- **Không có giá trong agent.** Không cột tiền, không bảng giá, không đọc lại bảng billing.
- **`seq` đơn điệu tăng trong phiên và KHÔNG đổi khi retry.** Nội dung của một `seq` là bất biến sau lần drain đầu tiên.
- **Mọi đường ghi là best-effort:** không exception nào từ billing được phép thoát ra đường gọi.
- **Cờ tắt mặc định:** toàn bộ gated sau `settings.billing_metering_enabled` (`BILLING_METERING_ENABLED`, default `false`).
- **Nhánh làm việc:** `feat/share-agent`. Không tạo nhánh mới, không push, không merge.
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`.

---

### Task 1: `UsageMeter` — bộ đếm in-memory

**Files:**
- Create: `src/noble_agent/billing/__init__.py`
- Create: `src/noble_agent/billing/meter.py`
- Test: `tests/unit/unified/test_billing_meter.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `UsageRow` dataclass với các field: `component: str`, `purpose: str`, `provider: str`, `model: str`, `input_tokens: int`, `output_tokens: int`, `cache_write_tokens: int`, `cache_read_tokens: int`, `audio_sec: float`, `wall_ms: float`, `units: int`, `exact: bool`, `turn_idx: int | None`
  - `UsageMeter(session_id: str, channel: str, max_pending: int = 2000)` với `.turn_idx: int`, `.dropped: int`, `.session_id`, `.channel`
  - `UsageMeter.add_llm(*, purpose, provider, model, input_tokens=0, output_tokens=0, cache_write_tokens=0, cache_read_tokens=0, exact=True) -> None`
  - `UsageMeter.add_audio(component, *, purpose="conversation", audio_sec=0.0, wall_ms=0.0, units=0) -> None`
  - `UsageMeter.drain() -> tuple[int, list[UsageRow]] | None`
  - `UsageMeter.commit(seq: int) -> None`
  - `UsageMeter.pending_count -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_billing_meter.py`:

```python
"""UsageMeter — số học thuần, không I/O. Đây là lớp duy nhất chạm đường nóng."""

from noble_agent.billing.meter import UsageMeter


def _meter() -> UsageMeter:
    return UsageMeter(session_id="s1", channel="voice")


def test_llm_calls_aggregate_into_one_row_per_provider_model():
    """5 vòng tool trong một lượt phải gộp thành MỘT dòng, units = số lời gọi.

    Khoá UNIQUE của bảng là (tenant, session, seq, component, purpose, provider,
    model) — ghi từng lời gọi riêng sẽ đụng khoá và bị DO NOTHING nuốt mất.
    """
    m = _meter()
    for _ in range(5):
        m.add_llm(
            purpose="conversation", provider="anthropic", model="claude-x",
            input_tokens=100, output_tokens=10, cache_read_tokens=1000,
        )
    seq, rows = m.drain()
    assert seq == 0
    assert len(rows) == 1
    row = rows[0]
    assert row.component == "llm"
    assert row.units == 5
    assert row.input_tokens == 500
    assert row.output_tokens == 50
    assert row.cache_read_tokens == 5000


def test_different_purpose_stays_a_separate_row():
    m = _meter()
    m.add_llm(purpose="conversation", provider="anthropic", model="claude-x", input_tokens=10)
    m.add_llm(purpose="summary", provider="anthropic", model="claude-x", input_tokens=20)
    _seq, rows = m.drain()
    purposes = sorted(r.purpose for r in rows)
    assert purposes == ["conversation", "summary"]


def test_inexact_call_does_not_contaminate_the_exact_row():
    """Một lời gọi thiếu usage không được làm cả dòng thành exact=False khi
    những lời gọi khác vẫn đo được — chúng tách dòng."""
    m = _meter()
    m.add_llm(purpose="conversation", provider="anthropic", model="claude-x", input_tokens=10, exact=True)
    m.add_llm(purpose="conversation", provider="anthropic", model="claude-x", input_tokens=20, exact=False)
    _seq, rows = m.drain()
    assert len(rows) == 2
    assert sorted(r.exact for r in rows) == [False, True]


def test_audio_counter_emits_only_the_delta():
    """VAD chạy liên tục nên meter giữ số tích luỹ; mỗi lần rút chỉ ghi phần
    tăng thêm. Ghi thẳng tích luỹ = tính tiền hai lần cùng một quãng audio."""
    m = _meter()
    m.add_audio("vad", audio_sec=12.4, wall_ms=41, units=380)
    seq, rows = m.drain()
    assert rows[0].audio_sec == 12.4
    m.commit(seq)

    m.add_audio("vad", audio_sec=11.0, wall_ms=36, units=340)
    seq2, rows2 = m.drain()
    assert seq2 == 1
    assert rows2[0].audio_sec == 11.0   # delta, KHÔNG phải 23.4
    assert rows2[0].units == 340


def test_drain_returns_none_when_nothing_to_write():
    m = _meter()
    assert m.drain() is None


def test_uncommitted_drain_replays_identical_rows_with_the_same_seq():
    """INSERT hỏng → lượt sau phải gửi lại ĐÚNG seq cũ với ĐÚNG nội dung cũ.

    Nội dung của một seq phải bất biến: nếu lần ghi trước thực ra đã landed,
    ON CONFLICT DO NOTHING giữ bản đầu — gộp thêm dữ liệu mới vào cùng seq sẽ
    làm dữ liệu mới biến mất im lặng.
    """
    m = _meter()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    seq, rows = m.drain()

    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=999)  # lượt sau
    seq_retry, rows_retry = m.drain()

    assert seq_retry == seq
    assert [r.input_tokens for r in rows_retry] == [r.input_tokens for r in rows] == [10]


def test_new_data_lands_on_the_next_seq_after_commit():
    m = _meter()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    seq, _rows = m.drain()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=999)
    m.commit(seq)

    seq2, rows2 = m.drain()
    assert seq2 == seq + 1
    assert rows2[0].input_tokens == 999


def test_commit_with_a_stale_seq_is_ignored():
    m = _meter()
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    seq, _ = m.drain()
    m.commit(seq + 7)
    seq_again, _ = m.drain()
    assert seq_again == seq


def test_pending_events_are_capped_and_drop_the_oldest():
    """PG chết suốt một cuộc gọi dài không được phép làm phình RAM vô hạn."""
    m = UsageMeter(session_id="s1", channel="voice", max_pending=3)
    for i in range(5):
        m.add_llm(purpose="conversation", provider="p", model=f"m{i}", input_tokens=1)
    assert m.pending_count == 3
    assert m.dropped == 2
    _seq, rows = m.drain()
    assert sorted(r.model for r in rows) == ["m2", "m3", "m4"]


def test_turn_idx_is_stamped_on_llm_rows():
    m = _meter()
    m.turn_idx = 4
    m.add_llm(purpose="conversation", provider="p", model="m", input_tokens=1)
    _seq, rows = m.drain()
    assert rows[0].turn_idx == 4


def test_session_level_component_has_no_turn_idx():
    """VAD và call chạy ngoài phạm vi lượt → turn_idx NULL trong bảng."""
    m = _meter()
    m.turn_idx = 4
    m.add_audio("call", purpose="session", audio_sec=38.6, units=1)
    _seq, rows = m.drain()
    assert rows[0].turn_idx is None
    assert rows[0].component == "call"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_billing_meter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.billing'`

- [ ] **Step 3: Write minimal implementation**

Create `src/noble_agent/billing/__init__.py`:

```python
"""Đo tiêu thụ để tính tiền — agent chỉ thống kê, Portal quy đổi ra tiền.

Xem docs/superpowers/specs/2026-08-18-billing-usage-metering-design.md.
"""
```

Create `src/noble_agent/billing/meter.py`:

```python
"""Bộ đếm tiêu thụ in-memory — lớp DUY NHẤT của billing chạm đường nóng.

Hai loại phép đo sống ở đây:

* **Sự kiện** (lời gọi LLM) — rời rạc, append khi xảy ra.
* **Đồng hồ đo** (thành phần audio) — liên tục, nên meter giữ số tích luỹ và
  ``drain()`` chỉ phát ra phần tăng thêm kể từ lần drain đã commit. VAD và
  thời lượng cuộc gọi chạy bất kể có lượt nào đang diễn ra hay không; ghi số
  tích luỹ thay vì delta sẽ tính tiền hai lần cùng một quãng âm thanh.

Mọi thứ ở đây là số học O(1): không await, không khoá, không serialize.
"""

from __future__ import annotations

from dataclasses import dataclass

MAX_PENDING = 2000

# Các component chạy ngoài phạm vi một lượt hội thoại → turn_idx NULL.
_SESSION_SCOPED = frozenset({"vad", "call"})


@dataclass
class UsageRow:
    component: str
    purpose: str = "conversation"
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    audio_sec: float = 0.0
    wall_ms: float = 0.0
    units: int = 0
    exact: bool = True
    turn_idx: int | None = None


class UsageMeter:
    """Một instance mỗi phiên. Không async, không I/O."""

    def __init__(self, *, session_id: str, channel: str, max_pending: int = MAX_PENDING) -> None:
        self.session_id = session_id
        self.channel = channel
        self.turn_idx = 0
        self.dropped = 0
        self._max_pending = max_pending
        self._seq = 0
        self._events: list[UsageRow] = []
        # (component, purpose) -> {"audio_sec", "wall_ms", "units"}
        self._totals: dict[tuple[str, str], dict[str, float]] = {}
        self._written: dict[tuple[str, str], dict[str, float]] = {}
        # Lô đã drain nhưng chưa xác nhận ghi thành công.
        self._inflight: tuple[int, list[UsageRow], dict[tuple[str, str], dict[str, float]]] | None = None

    @property
    def pending_count(self) -> int:
        return len(self._events)

    def add_llm(
        self,
        *,
        purpose: str,
        provider: str,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
        exact: bool = True,
    ) -> None:
        self._append(
            UsageRow(
                component="llm",
                purpose=purpose,
                provider=provider or "",
                model=model or "",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_write_tokens=cache_write_tokens,
                cache_read_tokens=cache_read_tokens,
                units=1,
                exact=exact,
                turn_idx=self.turn_idx,
            )
        )

    def add_audio(
        self,
        component: str,
        *,
        purpose: str = "conversation",
        audio_sec: float = 0.0,
        wall_ms: float = 0.0,
        units: int = 0,
    ) -> None:
        t = self._totals.setdefault((component, purpose), {"audio_sec": 0.0, "wall_ms": 0.0, "units": 0.0})
        t["audio_sec"] += audio_sec
        t["wall_ms"] += wall_ms
        t["units"] += units

    def drain(self) -> tuple[int, list[UsageRow]] | None:
        """Lô cần ghi, hoặc None khi không có gì.

        Lô chưa commit được trả lại **nguyên vẹn** (cùng seq, cùng nội dung):
        nếu lần ghi trước thực ra đã landed thì ``ON CONFLICT DO NOTHING`` giữ
        bản đầu, nên gộp thêm dữ liệu mới vào cùng seq sẽ làm dữ liệu mới biến
        mất im lặng. Dữ liệu mới chờ seq kế tiếp.
        """
        if self._inflight is not None:
            seq, rows, _snapshot = self._inflight
            return seq, rows

        rows = self._aggregate_events()
        snapshot: dict[tuple[str, str], dict[str, float]] = {}
        for key, total in self._totals.items():
            written = self._written.get(key, {"audio_sec": 0.0, "wall_ms": 0.0, "units": 0.0})
            d_audio = total["audio_sec"] - written["audio_sec"]
            d_wall = total["wall_ms"] - written["wall_ms"]
            d_units = total["units"] - written["units"]
            if d_audio <= 0 and d_wall <= 0 and d_units <= 0:
                continue
            component, purpose = key
            rows.append(
                UsageRow(
                    component=component,
                    purpose=purpose,
                    audio_sec=round(d_audio, 3),
                    wall_ms=round(d_wall, 1),
                    units=int(d_units),
                    turn_idx=None if component in _SESSION_SCOPED else self.turn_idx,
                )
            )
            snapshot[key] = dict(total)

        if not rows:
            return None

        seq = self._seq
        self._inflight = (seq, rows, snapshot)
        self._events = []
        return seq, rows

    def commit(self, seq: int) -> None:
        """Xác nhận lô ``seq`` đã ghi thành công; mở đường cho seq kế tiếp."""
        if self._inflight is None or self._inflight[0] != seq:
            return
        _seq, _rows, snapshot = self._inflight
        for key, total in snapshot.items():
            self._written[key] = total
        self._seq = seq + 1
        self._inflight = None

    # ── nội bộ ──────────────────────────────────────────────────────────
    def _append(self, row: UsageRow) -> None:
        self._events.append(row)
        while len(self._events) > self._max_pending:
            self._events.pop(0)
            self.dropped += 1

    def _aggregate_events(self) -> list[UsageRow]:
        """Gộp theo (component, purpose, provider, model, exact).

        ``exact`` nằm trong khoá gộp để một lời gọi mất usage không kéo cả dòng
        xuống exact=False — hai loại tách dòng, và Portal thấy đúng phần nào đo
        được phần nào không.
        """
        merged: dict[tuple, UsageRow] = {}
        for e in self._events:
            key = (e.component, e.purpose, e.provider, e.model, e.exact)
            cur = merged.get(key)
            if cur is None:
                merged[key] = UsageRow(**vars(e))
                continue
            cur.input_tokens += e.input_tokens
            cur.output_tokens += e.output_tokens
            cur.cache_write_tokens += e.cache_write_tokens
            cur.cache_read_tokens += e.cache_read_tokens
            cur.audio_sec += e.audio_sec
            cur.wall_ms += e.wall_ms
            cur.units += e.units
        return list(merged.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_billing_meter.py -v`
Expected: PASS (12 tests)

- [ ] **Step 5: Lint**

Run: `ruff check src/noble_agent/billing tests/unit/unified/test_billing_meter.py && ruff format src/noble_agent/billing tests/unit/unified/test_billing_meter.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/billing tests/unit/unified/test_billing_meter.py
git commit -m "feat(billing): UsageMeter — bộ đếm in-memory cho đường nóng"
```

---

### Task 2: Cờ cấu hình + sink ghi Postgres

**Files:**
- Modify: `src/noble_agent/config.py` (thêm 1 field cạnh `postgres_enabled`, ~dòng 456)
- Create: `src/noble_agent/billing/sink.py`
- Test: `tests/unit/unified/test_billing_sink.py`

**Interfaces:**
- Consumes: `UsageMeter.drain() -> tuple[int, list[UsageRow]] | None`, `UsageMeter.commit(seq)` (Task 1)
- Produces:
  - `settings.billing_metering_enabled: bool` (env `BILLING_METERING_ENABLED`)
  - `async flush(meter: UsageMeter, *, tenant_id: str | None = None) -> bool` — drain → INSERT → commit; True khi đã ghi. Không bao giờ raise.
  - `INSERT_SQL: str` (hằng, để test khẳng định câu lệnh)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_billing_sink.py`:

```python
"""Sink billing — best-effort, retry bằng cách giữ nguyên lô chưa commit."""

import pytest

from noble_agent.billing import sink
from noble_agent.billing.meter import UsageMeter


class FakeConn:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.batches: list[list[tuple]] = []
        self.sql: str | None = None

    async def executemany(self, sql, args):
        if self.fail:
            raise RuntimeError("boom")
        self.sql = sql
        self.batches.append(list(args))


class FakeCtx:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def wired(monkeypatch):
    """Thay pool + tenant_conn bằng đồ giả; trả về FakeConn đang dùng."""
    conn = FakeConn()

    async def fake_pool(_tid):
        return object()

    monkeypatch.setattr(sink, "_pool_for_tenant", fake_pool)
    monkeypatch.setattr(sink, "_tenant_conn", lambda _pool, _tid: FakeCtx(conn))
    monkeypatch.setattr(sink, "_tenant_id", lambda: "acme")
    return conn


def _meter_with_one_row() -> UsageMeter:
    m = UsageMeter(session_id="s1", channel="voice")
    m.add_llm(purpose="conversation", provider="anthropic", model="claude-x",
              input_tokens=100, output_tokens=10, cache_read_tokens=900)
    return m


async def test_flush_writes_the_batch_and_commits(wired):
    m = _meter_with_one_row()
    ok = await sink.flush(m)
    assert ok is True
    assert len(wired.batches) == 1
    assert len(wired.batches[0]) == 1
    row = wired.batches[0][0]
    assert row[0] == "acme"        # tenant_id
    assert row[1] == "s1"          # session_id
    assert row[2] == "voice"       # channel
    assert row[3] == 0             # seq
    # Đã commit → không còn gì để ghi lại
    assert m.drain() is None


async def test_flush_uses_on_conflict_do_nothing(wired):
    """Idempotency của toàn hệ thống nằm ở đúng mệnh đề này."""
    await sink.flush(_meter_with_one_row())
    assert "ON CONFLICT ON CONSTRAINT usage_events_idem DO NOTHING" in wired.sql


async def test_flush_failure_keeps_the_batch_for_retry(monkeypatch):
    conn = FakeConn(fail=True)

    async def fake_pool(_tid):
        return object()

    monkeypatch.setattr(sink, "_pool_for_tenant", fake_pool)
    monkeypatch.setattr(sink, "_tenant_conn", lambda _pool, _tid: FakeCtx(conn))
    monkeypatch.setattr(sink, "_tenant_id", lambda: "acme")

    m = _meter_with_one_row()
    ok = await sink.flush(m)
    assert ok is False
    seq, rows = m.drain()          # lô vẫn còn, đúng seq cũ
    assert seq == 0
    assert rows[0].input_tokens == 100


async def test_flush_is_a_noop_without_a_pool(monkeypatch):
    async def no_pool(_tid):
        raise RuntimeError("pg down")

    monkeypatch.setattr(sink, "_pool_for_tenant", no_pool)
    monkeypatch.setattr(sink, "_tenant_id", lambda: "acme")
    m = _meter_with_one_row()
    assert await sink.flush(m) is False


async def test_flush_on_empty_meter_does_not_touch_postgres(monkeypatch):
    called = False

    async def fake_pool(_tid):
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(sink, "_pool_for_tenant", fake_pool)
    m = UsageMeter(session_id="s1", channel="chat")
    assert await sink.flush(m) is False
    assert called is False


async def test_flush_never_raises(monkeypatch):
    """Billing hỏng không được phép làm hỏng cuộc gọi."""
    async def explode(_tid):
        raise ValueError("catastrophe")

    monkeypatch.setattr(sink, "_pool_for_tenant", explode)
    monkeypatch.setattr(sink, "_tenant_id", lambda: "acme")
    assert await sink.flush(_meter_with_one_row()) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_billing_sink.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.billing.sink'`

- [ ] **Step 3: Add the setting**

In `src/noble_agent/config.py`, ngay dưới dòng `postgres_enabled: bool = Field(False, alias="POSTGRES_ENABLED")`:

```python
    # Billing metering (SP-BILL). Mặc định TẮT: bảng billing.usage_events do
    # Portal ship, bật trước khi họ tạo bảng + cấp GRANT thì mọi phiên log
    # error liên tục. Bật sau khi Portal tick xong §11 của
    # docs/handoff/agent-postgres-billing-write-contract.md.
    billing_metering_enabled: bool = Field(False, alias="BILLING_METERING_ENABLED")
```

- [ ] **Step 4: Write the sink**

Create `src/noble_agent/billing/sink.py`:

```python
"""Ghi lô usage xuống billing.usage_events — chạy NGOÀI đường nóng.

Bảng do Portal sở hữu; agent chỉ có INSERT (không UPDATE/DELETE/SELECT). Vì
vậy toàn bộ tính idempotent nằm ở ``ON CONFLICT ON CONSTRAINT usage_events_idem
DO NOTHING``: lô thất bại được meter giữ nguyên và gửi lại với ĐÚNG seq cũ, nên
nếu lần trước thực ra đã landed thì lần này không nhân dòng.

Hợp đồng bảng + GRANT: docs/handoff/agent-postgres-billing-write-contract.md.
"""

from __future__ import annotations

import logging

from noble_agent.billing.meter import UsageMeter, UsageRow

logger = logging.getLogger("noble_agent.billing.sink")

INSERT_SQL = (
    "INSERT INTO billing.usage_events "
    "(tenant_id, session_id, channel, seq, turn_idx, component, purpose, provider, model, "
    " input_tokens, output_tokens, cache_write_tokens, cache_read_tokens, "
    " audio_sec, wall_ms, units, exact) "
    "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17) "
    "ON CONFLICT ON CONSTRAINT usage_events_idem DO NOTHING"
)

# Đã log lỗi cho phiên nào rồi — chỉ ồn ào lần đầu mỗi phiên.
_logged: set[str] = set()


def _tenant_id() -> str:
    from noble_agent.tenant.current import current_tenant

    return current_tenant()


async def _pool_for_tenant(tenant_id: str):
    from noble_agent.storage.postgres_client import pool_for_tenant

    return await pool_for_tenant(tenant_id)


def _tenant_conn(pool, tenant_id: str):
    from noble_agent.storage.postgres_client import tenant_conn

    return tenant_conn(pool, tenant_id)


def _params(tenant_id: str, meter: UsageMeter, seq: int, row: UsageRow) -> tuple:
    return (
        tenant_id,
        meter.session_id,
        meter.channel,
        seq,
        row.turn_idx,
        row.component,
        row.purpose,
        row.provider,
        row.model,
        int(row.input_tokens),
        int(row.output_tokens),
        int(row.cache_write_tokens),
        int(row.cache_read_tokens),
        float(row.audio_sec),
        float(row.wall_ms),
        int(row.units),
        bool(row.exact),
    )


async def flush(meter: UsageMeter, *, tenant_id: str | None = None) -> bool:
    """Rút meter và ghi một lô. True khi đã ghi (meter đã commit).

    Không bao giờ raise: mọi lỗi được nuốt và log, lô ở lại meter chờ lượt sau.
    """
    try:
        batch = meter.drain()
        if batch is None:
            return False
        seq, rows = batch
        tid = tenant_id or _tenant_id()
        pool = await _pool_for_tenant(tid)
        if pool is None:
            _log_once(meter, "pool_for_tenant trả None")
            return False
        args = [_params(tid, meter, seq, r) for r in rows]
        async with _tenant_conn(pool, tid) as conn:
            await conn.executemany(INSERT_SQL, args)
        meter.commit(seq)
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort, không được nổ ra hot path
        _log_once(meter, repr(exc))
        return False


def _log_once(meter: UsageMeter, detail: str) -> None:
    """Log ở mức error đúng MỘT lần mỗi phiên.

    Ba nguyên nhân nhìn giống hệt nhau và cần phân biệt được từ log:
    chưa cấp INSERT (SQLSTATE 42501), credential hết hạn (28P01), PG không tới
    được. Vì vậy log kèm nguyên repr của exception.
    """
    if meter.session_id in _logged:
        return
    _logged.add(meter.session_id)
    logger.error(
        "billing: ghi usage thất bại (session=%s, tenant=%s): %s — lô giữ lại, thử lại lượt sau",
        meter.session_id,
        _safe_tenant(),
        detail,
    )


def _safe_tenant() -> str:
    try:
        return _tenant_id()
    except Exception:  # noqa: BLE001
        return "?"


def forget_session(session_id: str) -> None:
    """Quên trạng thái log của một phiên đã đóng (tránh set phình vô hạn)."""
    _logged.discard(session_id)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_billing_sink.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/noble_agent/billing src/noble_agent/config.py tests/unit/unified/test_billing_sink.py
ruff format src/noble_agent/billing tests/unit/unified/test_billing_sink.py
git add src/noble_agent/billing/sink.py src/noble_agent/config.py tests/unit/unified/test_billing_sink.py
git commit -m "feat(billing): sink ghi billing.usage_events + cờ BILLING_METERING_ENABLED"
```

---

### Task 3: ContextVar + chuẩn hoá usage + registry theo phiên

**Files:**
- Create: `src/noble_agent/billing/context.py`
- Create: `src/noble_agent/billing/capture.py`
- Test: `tests/unit/unified/test_billing_capture.py`

**Interfaces:**
- Consumes: `UsageMeter` (Task 1)
- Produces:
  - `context.set_meter(m) -> Token`, `context.reset_meter(token)`, `context.current_meter() -> UsageMeter | None`, `context.use_meter(m)` (contextmanager)
  - `context.get_session_meter(session_id: str, channel: str) -> UsageMeter` — registry theo phiên
  - `context.pop_session_meter(session_id: str) -> UsageMeter | None`
  - `capture.normalize_usage(usage) -> dict | None` — trả `{"input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens", "exact"}`
  - `capture.record(provider: str, model: str, usage, *, purpose: str) -> None` — ghi vào meter hiện hành nếu có

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_billing_capture.py`:

```python
"""Chuẩn hoá usage của provider + đường ghi qua ContextVar."""

from types import SimpleNamespace

from noble_agent.billing import capture, context
from noble_agent.billing.meter import UsageMeter


def test_anthropic_usage_maps_to_four_disjoint_buckets():
    u = SimpleNamespace(
        input_tokens=2140,
        output_tokens=214,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=11800,
    )
    got = capture.normalize_usage(u)
    assert got == {
        "input_tokens": 2140,
        "output_tokens": 214,
        "cache_write_tokens": 0,
        "cache_read_tokens": 11800,
        "exact": True,
    }


def test_anthropic_usage_without_output_is_inexact():
    """Khách ngắt lời → message_delta chưa về → không biết output token.

    Input vẫn chính xác vì nó đến từ message_start. KHÔNG được đoán output.
    """
    u = SimpleNamespace(
        input_tokens=1460,
        output_tokens=None,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=14100,
    )
    got = capture.normalize_usage(u)
    assert got["input_tokens"] == 1460
    assert got["output_tokens"] == 0
    assert got["exact"] is False


def test_openai_usage_subtracts_cached_from_prompt_tokens():
    """OpenAI tính prompt_tokens ĐÃ BAO GỒM phần cached; bốn cột của ta rời
    nhau nên phải trừ ra, nếu không phần cached bị đếm hai lần."""
    u = SimpleNamespace(
        prompt_tokens=5000,
        completion_tokens=120,
        prompt_tokens_details=SimpleNamespace(cached_tokens=4000),
    )
    got = capture.normalize_usage(u)
    assert got["input_tokens"] == 1000
    assert got["cache_read_tokens"] == 4000
    assert got["cache_write_tokens"] == 0
    assert got["output_tokens"] == 120
    assert got["exact"] is True


def test_openai_usage_without_cache_details():
    u = SimpleNamespace(prompt_tokens=300, completion_tokens=40)
    got = capture.normalize_usage(u)
    assert got["input_tokens"] == 300
    assert got["cache_read_tokens"] == 0


def test_normalize_returns_none_for_nothing():
    assert capture.normalize_usage(None) is None
    assert capture.normalize_usage(SimpleNamespace()) is None


def test_record_writes_into_the_current_meter():
    m = UsageMeter(session_id="s1", channel="chat")
    with context.use_meter(m):
        capture.record(
            "anthropic", "claude-x",
            SimpleNamespace(input_tokens=10, output_tokens=2,
                            cache_creation_input_tokens=0, cache_read_input_tokens=5),
            purpose="summary",
        )
    _seq, rows = m.drain()
    assert rows[0].purpose == "summary"
    assert rows[0].provider == "anthropic"
    assert rows[0].input_tokens == 10


def test_record_without_usage_still_logs_an_inexact_call():
    """Lời gọi có xảy ra là một sự thật cần ghi, kể cả khi không đo được."""
    m = UsageMeter(session_id="s1", channel="chat")
    with context.use_meter(m):
        capture.record("vllm", "qwen", None, purpose="conversation")
    _seq, rows = m.drain()
    assert rows[0].exact is False
    assert rows[0].units == 1
    assert rows[0].input_tokens == 0


def test_record_without_a_meter_is_a_noop():
    capture.record("anthropic", "claude-x", None, purpose="conversation")  # không raise


def test_session_registry_returns_the_same_meter_per_session():
    a = context.get_session_meter("sess-A", "voice")
    b = context.get_session_meter("sess-A", "voice")
    assert a is b
    assert context.pop_session_meter("sess-A") is a
    assert context.pop_session_meter("sess-A") is None


def test_background_task_inherits_the_meter():
    """Task summary/warm sinh ra trong lượt phải ghi vào ĐÚNG meter — nếu
    không, chi phí nền bị mất mà không ai biết."""
    import asyncio

    async def main():
        m = UsageMeter(session_id="s1", channel="voice")
        with context.use_meter(m):
            async def bg():
                capture.record("anthropic", "claude-x", None, purpose="summary")

            await asyncio.create_task(bg())
        return m

    m = asyncio.run(main())
    _seq, rows = m.drain()
    assert rows[0].purpose == "summary"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_billing_capture.py -v`
Expected: FAIL — `ImportError: cannot import name 'capture' from 'noble_agent.billing'`

- [ ] **Step 3: Write `context.py`**

Create `src/noble_agent/billing/context.py`:

```python
"""Meter của lượt hiện hành qua ContextVar + registry theo phiên.

Dùng ContextVar (đúng khuôn ``tenant/current.py``) để ``StreamingClient`` ghi
được usage mà KHÔNG phải đổi chữ ký ``stream_completion`` xuyên 5 tầng. Lợi ích
kèm theo: ``asyncio.create_task`` sao chép context, nên task summary/warm-cache
sinh ra trong lượt tự động ghi vào đúng meter.

Registry theo phiên tồn tại vì ``TurnRunner`` được cache theo
(tenant, version, channel) — nó phục vụ nhiều phiên, nên không thể giữ meter
làm thuộc tính instance.
"""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar, Token

from noble_agent.billing.meter import UsageMeter

_meter: ContextVar[UsageMeter | None] = ContextVar("noble_usage_meter", default=None)

# Chặn trên: phiên không được dọn (transport crash) không được phép làm phình
# bộ nhớ vô hạn. Vượt trần thì bỏ phiên cũ nhất.
MAX_SESSIONS = 500
_sessions: OrderedDict[str, UsageMeter] = OrderedDict()


def set_meter(meter: UsageMeter | None) -> Token:
    return _meter.set(meter)


def reset_meter(token: Token) -> None:
    _meter.reset(token)


def current_meter() -> UsageMeter | None:
    return _meter.get()


@contextmanager
def use_meter(meter: UsageMeter | None):
    token = _meter.set(meter)
    try:
        yield meter
    finally:
        _meter.reset(token)


def get_session_meter(session_id: str, channel: str) -> UsageMeter:
    m = _sessions.get(session_id)
    if m is None:
        m = UsageMeter(session_id=session_id, channel=channel)
        _sessions[session_id] = m
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
    _sessions.move_to_end(session_id)
    return m


def pop_session_meter(session_id: str) -> UsageMeter | None:
    return _sessions.pop(session_id, None)
```

- [ ] **Step 4: Write `capture.py`**

Create `src/noble_agent/billing/capture.py`:

```python
"""Chuẩn hoá object usage của provider về bốn cột rời nhau của ta.

Bốn cột (input / output / cache_write / cache_read) **không giao nhau**, vì đơn
giá của chúng khác nhau. Anthropic vốn đã tách rời. OpenAI thì ``prompt_tokens``
ĐÃ BAO GỒM phần cached, nên phải trừ ra — không trừ là đếm phần cached hai lần
với giá của input thường.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("noble_agent.billing.capture")


def _int(v: Any) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def normalize_usage(usage: Any) -> dict | None:
    """Trả dict bốn cột + cờ ``exact``, hoặc None khi không có gì để đọc."""
    if usage is None:
        return None

    # Anthropic (qua adapter của ta)
    if hasattr(usage, "input_tokens"):
        out = getattr(usage, "output_tokens", None)
        return {
            "input_tokens": _int(usage.input_tokens),
            "output_tokens": _int(out),
            "cache_write_tokens": _int(getattr(usage, "cache_creation_input_tokens", 0)),
            "cache_read_tokens": _int(getattr(usage, "cache_read_input_tokens", 0)),
            "exact": out is not None,
        }

    # OpenAI-compat
    if hasattr(usage, "prompt_tokens"):
        prompt = _int(usage.prompt_tokens)
        details = getattr(usage, "prompt_tokens_details", None)
        cached = _int(getattr(details, "cached_tokens", 0)) if details is not None else 0
        completion = getattr(usage, "completion_tokens", None)
        return {
            "input_tokens": max(0, prompt - cached),
            "output_tokens": _int(completion),
            "cache_write_tokens": 0,
            "cache_read_tokens": cached,
            "exact": completion is not None,
        }

    return None


def record(provider: str, model: str, usage: Any, *, purpose: str) -> None:
    """Ghi usage của MỘT lời gọi LLM vào meter hiện hành. No-op khi không có meter.

    Provider không trả usage ⇒ vẫn ghi một dòng ``exact=False`` với token 0:
    việc lời gọi đã xảy ra là một sự thật cần biết, và tỷ lệ ``exact=False``
    chính là thước đo mức doanh thu đang bị bỏ sót.
    """
    from noble_agent.billing.context import current_meter

    meter = current_meter()
    if meter is None:
        return
    norm = normalize_usage(usage)
    try:
        if norm is None:
            meter.add_llm(purpose=purpose, provider=provider, model=model, exact=False)
        else:
            meter.add_llm(purpose=purpose, provider=provider, model=model, **norm)
    except Exception:  # noqa: BLE001 — đo lường không được làm hỏng lượt
        logger.debug("billing: record usage thất bại", exc_info=True)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_billing_capture.py -v`
Expected: PASS (10 tests)

- [ ] **Step 6: Lint and commit**

```bash
ruff check src/noble_agent/billing tests/unit/unified/test_billing_capture.py
ruff format src/noble_agent/billing tests/unit/unified/test_billing_capture.py
git add src/noble_agent/billing tests/unit/unified/test_billing_capture.py
git commit -m "feat(billing): ContextVar meter + chuẩn hoá usage 4 cột rời nhau"
```

---

### Task 4: Anthropic adapter phát ra usage

**Files:**
- Modify: `src/noble_agent/agent/llm/anthropic_provider.py` (`_openai_chunk` ~dòng 195, `_adapt_stream` ~dòng 228-281)
- Test: `tests/unit/unified/test_anthropic_usage_passthrough.py`

**Interfaces:**
- Consumes: nothing từ task trước.
- Produces: chunk do `_adapt_stream` phát ra có thuộc tính `.usage` (SimpleNamespace với `input_tokens`, `output_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`) trên **mọi** chunk sau `message_start`. `output_tokens` là `None` cho tới khi `message_delta` về.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_anthropic_usage_passthrough.py`:

```python
"""Adapter Anthropic phải chuyển usage ra ngoài — hiện nó bỏ hẳn hai event mang
số token (message_start và message_delta)."""

from types import SimpleNamespace

from noble_agent.agent.llm.anthropic_provider import _adapt_stream


class FakeStream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e

        return gen()


def _start(**usage):
    return SimpleNamespace(type="message_start", message=SimpleNamespace(usage=SimpleNamespace(**usage)))


def _text(t):
    return SimpleNamespace(type="content_block_delta", index=0,
                           delta=SimpleNamespace(type="text_delta", text=t))


async def _collect(events):
    return [c async for c in _adapt_stream(FakeStream(events))]


async def test_usage_appears_on_the_final_chunk():
    chunks = await _collect([
        _start(input_tokens=2140, cache_creation_input_tokens=0, cache_read_input_tokens=11800),
        _text("xin chào"),
        SimpleNamespace(type="message_delta", delta=SimpleNamespace(stop_reason="end_turn"),
                        usage=SimpleNamespace(output_tokens=214)),
        SimpleNamespace(type="message_stop"),
    ])
    last = chunks[-1]
    assert last.usage.input_tokens == 2140
    assert last.usage.cache_read_input_tokens == 11800
    assert last.usage.output_tokens == 214


async def test_text_still_streams_unchanged():
    chunks = await _collect([
        _start(input_tokens=10, cache_creation_input_tokens=0, cache_read_input_tokens=0),
        _text("a"),
        _text("b"),
        SimpleNamespace(type="message_stop"),
    ])
    text = "".join(c.choices[0].delta.content or "" for c in chunks)
    assert text == "ab"


async def test_input_tokens_are_available_before_the_stream_finishes():
    """Khi khách ngắt lời, ta đóng stream giữa chừng nên message_delta không
    bao giờ về. Input token phải đã có sẵn từ message_start, còn output để
    None để tầng trên đánh dấu exact=False."""
    chunks = await _collect([
        _start(input_tokens=1460, cache_creation_input_tokens=0, cache_read_input_tokens=14100),
        _text("đang nói dở"),
    ])
    mid = chunks[-1]
    assert mid.usage.input_tokens == 1460
    assert mid.usage.output_tokens is None


async def test_no_message_start_means_no_usage_attribute_value():
    chunks = await _collect([_text("a"), SimpleNamespace(type="message_stop")])
    assert getattr(chunks[-1], "usage", None) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_anthropic_usage_passthrough.py -v`
Expected: FAIL — `AttributeError: 'types.SimpleNamespace' object has no attribute 'usage'`

- [ ] **Step 3: Modify `_openai_chunk` to carry usage**

In `src/noble_agent/agent/llm/anthropic_provider.py`, thay hàm `_openai_chunk`:

```python
def _openai_chunk(
    *,
    content: str | None = None,
    tool_call: dict | None = None,
    finish_reason: str | None = None,
    usage: Any = None,
) -> SimpleNamespace:
    """Build a chunk that quacks like ``openai.types.chat.ChatCompletionChunk``
    — only the attribute paths ``StreamingClient`` actually touches matter:
    ``chunk.choices[0].delta.content`` and ``...delta.tool_calls[*]``.

    ``usage`` piggybacks on the same shape the OpenAI SDK uses when
    ``stream_options.include_usage`` is on, so ``StreamingClient`` reads one
    attribute path for both provider families.
    """
    delta_kwargs: dict[str, Any] = {"content": content, "tool_calls": None}
    if tool_call is not None:
        delta_kwargs["tool_calls"] = [tool_call]
    delta = SimpleNamespace(**delta_kwargs)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason, index=0)
    return SimpleNamespace(choices=[choice], usage=usage)
```

- [ ] **Step 4: Thread usage through `_adapt_stream`**

Thay thân `_adapt_stream` (giữ nguyên phần tool-call index tracking):

```python
async def _adapt_stream(anth_stream):
    """Iterate Anthropic stream events and yield OpenAI-shaped chunks.

    Tool-call index tracking: Anthropic gives each content block an integer
    index starting at 0. We reuse that as the OpenAI ``tool_calls[*].index``
    so the consumer's accumulator keys line up.

    Usage: ``message_start`` carries input + cache counts, ``message_delta``
    carries output. We attach the running snapshot to EVERY chunk, not just the
    last one, because an interrupted turn closes the stream before
    ``message_delta`` arrives — the consumer still needs the input counts that
    were already billed, with ``output_tokens`` left None so it can mark the
    row inexact instead of guessing.
    """
    tool_block_indices: dict[int, int] = {}  # anthropic block idx → openai tc idx
    next_tc_idx = 0
    finish_reason: str | None = None
    usage: SimpleNamespace | None = None

    async for event in anth_stream:
        etype = getattr(event, "type", None)

        if etype == "message_start":
            src = getattr(getattr(event, "message", None), "usage", None)
            if src is not None:
                usage = SimpleNamespace(
                    input_tokens=getattr(src, "input_tokens", 0) or 0,
                    output_tokens=None,
                    cache_creation_input_tokens=getattr(src, "cache_creation_input_tokens", 0) or 0,
                    cache_read_input_tokens=getattr(src, "cache_read_input_tokens", 0) or 0,
                )
            continue

        if etype == "content_block_start":
            block = getattr(event, "content_block", None)
            block_idx = getattr(event, "index", 0)
            if block is not None and getattr(block, "type", None) == "tool_use":
                tool_id = getattr(block, "id", "") or ""
                tool_name = getattr(block, "name", "") or ""
                tc_idx = next_tc_idx
                next_tc_idx += 1
                tool_block_indices[block_idx] = tc_idx
                yield _openai_chunk(tool_call=_tool_call_open(tc_idx, tool_id, tool_name), usage=usage)
            continue

        if etype == "content_block_delta":
            block_idx = getattr(event, "index", 0)
            delta = getattr(event, "delta", None)
            if delta is None:
                continue
            dtype = getattr(delta, "type", None)
            if dtype == "text_delta":
                text = getattr(delta, "text", "") or ""
                if text:
                    yield _openai_chunk(content=text, usage=usage)
            elif dtype == "input_json_delta":
                partial = getattr(delta, "partial_json", "") or ""
                if partial and block_idx in tool_block_indices:
                    yield _openai_chunk(
                        tool_call=_tool_call_delta(tool_block_indices[block_idx], partial),
                        usage=usage,
                    )
            continue

        if etype == "message_delta":
            delta = getattr(event, "delta", None)
            stop = getattr(delta, "stop_reason", None) if delta else None
            if stop:
                finish_reason = _STOP_REASON_MAP.get(stop, "stop")
            u = getattr(event, "usage", None)
            if u is not None and usage is not None:
                usage.output_tokens = getattr(u, "output_tokens", 0) or 0
            continue

        if etype == "message_stop":
            yield _openai_chunk(finish_reason=finish_reason or "stop", usage=usage)
            return
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_anthropic_usage_passthrough.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Verify nothing else broke**

Run: `pytest tests/unit/unified -k "anthropic or llm or stream" -v`
Expected: PASS — không có test nào của LLM layer đỏ lên

- [ ] **Step 7: Commit**

```bash
ruff check src/noble_agent/agent/llm/anthropic_provider.py tests/unit/unified/test_anthropic_usage_passthrough.py
git add src/noble_agent/agent/llm/anthropic_provider.py tests/unit/unified/test_anthropic_usage_passthrough.py
git commit -m "feat(billing): adapter Anthropic phát ra usage (kể cả khi bị ngắt giữa stream)"
```

---

### Task 5: `StreamingClient` ghi usage + tham số `purpose`

**Files:**
- Modify: `src/noble_agent/agent/llm/client.py` (`stream_completion` ~195, `_stream_once` ~233, `simple_completion` ~329, `complete_once` ~348, `_apply_provider_shaping` ~178)
- Test: `tests/unit/unified/test_billing_llm_client.py`

**Interfaces:**
- Consumes: `capture.record(provider, model, usage, *, purpose)` (Task 3); chunk có `.usage` (Task 4)
- Produces:
  - `StreamingClient.stream_completion(..., purpose: str = "conversation")`
  - `StreamingClient.complete_once(..., purpose: str = "conversation")`
  - `StreamingClient.simple_completion(..., purpose: str = "conversation")`
  - `client._STREAM_USAGE_PROVIDERS: frozenset[str]` — allowlist slot được gửi `stream_options`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_billing_llm_client.py`:

```python
"""StreamingClient ghi usage vào meter hiện hành mà KHÔNG đổi kiểu trả về."""

from types import SimpleNamespace

import pytest

from noble_agent.agent.llm import client as llm_client
from noble_agent.agent.llm.client import StreamingClient
from noble_agent.billing import context
from noble_agent.billing.meter import UsageMeter


def _chunk(text=None, usage=None, finish=None):
    delta = SimpleNamespace(content=text, tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish, index=0)], usage=usage)


class FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()


class FakeProvider:
    """Đủ để quack như openai.AsyncOpenAI trên đúng đường StreamingClient chạm."""

    def __init__(self, chunks, captured: dict):
        self._chunks = chunks
        self._captured = captured
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self._captured.update(kwargs)
        return FakeStream(self._chunks)


def _client(provider) -> StreamingClient:
    # _providers là LIST các tuple (name, client), không phải dict —
    # _ordered_providers trả thẳng list này và caller unpack `for name, p in ...`.
    return StreamingClient(
        providers=[("vllm", provider)],
        enable_thinking=False,
        openai_reasoning_effort="none",
    )


async def _run(client, meter, purpose="conversation"):
    async def on_token(_t):
        return None

    with context.use_meter(meter):
        return await client.stream_completion(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
            model={"vllm": "qwen"},
            temperature=0.7,
            max_tokens=64,
            on_token=on_token,
            purpose=purpose,
        )


async def test_usage_from_the_stream_lands_in_the_meter():
    usage = SimpleNamespace(prompt_tokens=500, completion_tokens=40,
                            prompt_tokens_details=SimpleNamespace(cached_tokens=400))
    provider = FakeProvider([_chunk("xin "), _chunk("chào", usage=usage, finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")

    content, tool_calls = await _run(_client(provider), meter)

    assert content == "xin chào"          # kiểu trả về KHÔNG đổi
    assert tool_calls is None
    _seq, rows = meter.drain()
    assert rows[0].input_tokens == 100    # 500 − 400 cached
    assert rows[0].cache_read_tokens == 400
    assert rows[0].output_tokens == 40
    assert rows[0].exact is True


async def test_missing_usage_is_recorded_as_inexact():
    provider = FakeProvider([_chunk("a", finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")
    await _run(_client(provider), meter)
    _seq, rows = meter.drain()
    assert rows[0].exact is False
    assert rows[0].units == 1


async def test_purpose_label_reaches_the_row():
    provider = FakeProvider([_chunk("a", finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")
    await _run(_client(provider), meter, purpose="addressee_gate")
    _seq, rows = meter.drain()
    assert rows[0].purpose == "addressee_gate"


async def test_provider_and_model_are_stamped():
    provider = FakeProvider([_chunk("a", finish="stop")], {})
    meter = UsageMeter(session_id="s1", channel="chat")
    await _run(_client(provider), meter)
    _seq, rows = meter.drain()
    assert rows[0].provider == "vllm"
    assert rows[0].model == "qwen"


async def test_stream_options_only_for_allowlisted_providers():
    """Provider không hỗ trợ sẽ trả 400 — mà 400 là lỗi non-transient nên
    stream_completion nhảy provider. Bật ẩu một cờ đo lường = làm hỏng cuộc gọi."""
    assert "vllm" in llm_client._STREAM_USAGE_PROVIDERS
    assert "openai" in llm_client._STREAM_USAGE_PROVIDERS
    assert "dashscope" not in llm_client._STREAM_USAGE_PROVIDERS
    assert "gemini" not in llm_client._STREAM_USAGE_PROVIDERS
    assert "anthropic" not in llm_client._STREAM_USAGE_PROVIDERS

    captured: dict = {}
    provider = FakeProvider([_chunk("a", finish="stop")], captured)
    await _run(_client(provider), UsageMeter(session_id="s1", channel="chat"))
    assert captured["stream_options"] == {"include_usage": True}


async def test_no_meter_means_no_crash():
    provider = FakeProvider([_chunk("a", finish="stop")], {})

    async def on_token(_t):
        return None

    content, _ = await _client(provider).stream_completion(
        messages=[{"role": "user", "content": "hi"}], tools=[], model={"vllm": "qwen"},
        temperature=0.7, max_tokens=64, on_token=on_token,
    )
    assert content == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_billing_llm_client.py -v`
Expected: FAIL — `AttributeError: module 'noble_agent.agent.llm.client' has no attribute '_STREAM_USAGE_PROVIDERS'`

- [ ] **Step 3: Add the allowlist and shaping**

In `src/noble_agent/agent/llm/client.py`, thêm hằng ngay dưới các import:

```python
# Slot tương thích OpenAI đã kiểm chứng là chấp nhận `stream_options`.
# CỐ Ý bảo thủ: provider không hỗ trợ trả 400, mà `_is_transient` coi 400 là
# non-transient nên `stream_completion` sẽ nhảy sang provider kế — tức là một
# cờ ĐO LƯỜNG có thể làm hỏng cuộc gọi. Thà thiếu số liệu (exact=False) còn
# hơn rớt cuộc gọi. `anthropic` không nằm đây vì nó đi qua adapter riêng.
_STREAM_USAGE_PROVIDERS = frozenset({"openai", "vllm"})
```

Trong `_apply_provider_shaping`, thêm ở cuối thân hàm:

```python
        if provider_name in _STREAM_USAGE_PROVIDERS and kwargs.get("stream"):
            kwargs["stream_options"] = {"include_usage": True}
```

- [ ] **Step 4: Record usage in `_stream_once`**

Trong `_stream_once`: thêm tham số `purpose="conversation"` vào chữ ký, khai báo biến trước vòng `async for`:

```python
        last_usage = None
```

Trong vòng lặp, ngay sau `async for chunk in stream:` và **trước** `if interrupt_check ...`:

```python
            # Giữ snapshot usage mới nhất. Anthropic gắn nó vào MỌI chunk sau
            # message_start, nên khi bị ngắt giữa chừng ta vẫn còn input token.
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage is not None:
                last_usage = chunk_usage
```

Ngay trước `tcs = [tool_calls[k] for k in order] if tool_calls else None` ở cuối hàm:

```python
        from noble_agent.billing.capture import record as _record_usage

        _record_usage(provider_name, model, last_usage, purpose=purpose)
```

Và trong `stream_completion`, thêm `purpose: str = "conversation"` vào chữ ký rồi truyền xuống `self._stream_once(..., purpose=purpose)`.

- [ ] **Step 5: Record usage in the non-streaming paths**

`complete_once` (dòng ~348): thêm `purpose: str = "conversation"` vào chữ ký, rồi chèn hai dòng
ngay **sau** `resp = await provider.chat.completions.create(**kwargs)` và **trước**
`content = resp.choices[0].message.content or ""`:

```python
                from noble_agent.billing.capture import record as _record_usage

                _record_usage(name, resolved, getattr(resp, "usage", None), purpose=purpose)
```

`simple_completion` (dòng ~329) chỉ uỷ quyền cho `complete_once`, nên chỉ cần thêm
`purpose: str = "conversation"` vào chữ ký và truyền tiếp:

```python
        return await self.complete_once(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            primary=primary,
            purpose=purpose,
        )
```

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_billing_llm_client.py -v`
Expected: PASS (6 tests)

- [ ] **Step 7: Label every non-conversation call site**

Có **9 call-site** ngoài lượt chính. Bỏ sót một chỗ nghĩa là chi phí đó bị gán nhầm vào
`conversation` và Portal tính tiền khách cho việc nội bộ. Danh sách đầy đủ:

| File:dòng | Việc | `purpose` |
|---|---|---|
| `agent/runner.py:53` | lượt hội thoại chính | *(mặc định — không sửa)* |
| `agent/orchestrator.py:395` | `suggest_followups` — gợi ý câu hỏi cho UI chat | `"suggestions"` |
| `agent/orchestrator.py:526` | warm-cache replay sau summary | `"warm_cache"` |
| `agent/summary/summarizer.py:97` | nén lịch sử hội thoại | `"summary"` |
| `agent/summary/generator.py:67` | sinh tóm tắt cuộc gọi lúc kết thúc | `"summary"` |
| `agent/memory/snapshot.py:91` | trộn hồ sơ khách qua các phiên | `"memory"` |
| `voice/addressee_gate.py:182` | phân loại nói-với-ai | `"addressee_gate"` |
| `semcache/predictor.py:115` | dự đoán lượt kế | `"semcache"` |
| `semcache/sandbox.py:139` | chạy thử lượt dự đoán | `"semcache"` |
| `agent/rag/hipporag/builder.py:107` | dựng đồ thị tri thức (offline) | `"rag_build"` |

Danh sách `purpose` này là **đóng** và phải khớp §2.2 của contract — thêm giá trị mới thì
phải cập nhật contract trước, nếu không Portal gặp nhãn lạ trong bảng.

- [ ] **Step 7b: Verify no call site was missed**

Run: `rtk proxy grep -rn "stream_completion(\|complete_once(\|simple_completion(" src/noble_agent --include=*.py | grep -v "def \|llm/client.py"`
Expected: đúng 10 dòng, và mọi dòng **trừ** `agent/runner.py:53` đều có `purpose=` tường minh.

- [ ] **Step 8: Full LLM suite + commit**

Run: `pytest tests/unit/unified -k "llm or client or summary or semcache or addressee" -v`
Expected: PASS

```bash
ruff check src/noble_agent/agent/llm/client.py tests/unit/unified/test_billing_llm_client.py
git add -A src/noble_agent tests/unit/unified/test_billing_llm_client.py
git commit -m "feat(billing): StreamingClient ghi usage + nhãn purpose cho mọi đường LLM"
```

---

### Task 6: Orchestrator — gắn meter vào lượt và flush sau `save_all`

**Files:**
- Modify: `src/noble_agent/agent/orchestrator.py` (quanh `handle_turn`; điểm chèn: dòng 284-313, trong nhánh `if saved:`)
- Test: `tests/unit/unified/test_billing_orchestrator.py`

**Interfaces:**
- Consumes: `context.get_session_meter`, `context.use_meter` (Task 3); `sink.flush` (Task 2)
- Produces: sau mỗi lượt thành công, `sink.flush` được gọi fire-and-forget; `meter.turn_idx` tăng mỗi lượt.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_billing_orchestrator.py`:

```python
"""Bất biến quan trọng nhất của tính năng: đường nóng không chạm I/O.

Test này tồn tại để một thay đổi tương lai không âm thầm kéo lệnh ghi billing
vào giữa lượt.
"""

import asyncio

from noble_agent.billing import context
from noble_agent.billing.meter import UsageMeter


async def test_sink_is_not_called_while_the_turn_is_running(monkeypatch):
    """Trong lúc LLM đang stream, sink phải im lặng tuyệt đối."""
    calls: list[str] = []

    async def spy_flush(meter, **_kw):
        calls.append("flush")
        return True

    from noble_agent.billing import sink

    monkeypatch.setattr(sink, "flush", spy_flush)

    meter = UsageMeter(session_id="s1", channel="chat")
    during: list[int] = []

    async def fake_turn():
        with context.use_meter(meter):
            meter.add_llm(purpose="conversation", provider="p", model="m", input_tokens=5)
            during.append(len(calls))          # chụp số lần flush GIỮA lượt
        await sink.flush(meter)                 # chỉ sau khi lượt xong

    await fake_turn()
    assert during == [0]
    assert calls == ["flush"]


async def test_turn_idx_advances_per_turn():
    meter = UsageMeter(session_id="s1", channel="chat")
    assert meter.turn_idx == 0
    meter.turn_idx += 1
    meter.add_llm(purpose="conversation", provider="p", model="m", input_tokens=1)
    _seq, rows = meter.drain()
    assert rows[0].turn_idx == 1


async def test_flush_runs_as_a_background_task(monkeypatch):
    """Flush không được await trên đường trả lời."""
    started = asyncio.Event()
    released = asyncio.Event()

    async def slow_flush(_meter, **_kw):
        started.set()
        await released.wait()
        return True

    from noble_agent.billing import sink
    from noble_agent.storage.persist import fire_and_forget

    monkeypatch.setattr(sink, "flush", slow_flush)

    meter = UsageMeter(session_id="s1", channel="chat")
    meter.add_llm(purpose="conversation", provider="p", model="m", input_tokens=1)
    task = fire_and_forget(sink.flush(meter))

    await asyncio.wait_for(started.wait(), timeout=1)   # đã chạy nền
    assert not task.done()                              # và caller không bị chặn
    released.set()
    await task
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_billing_orchestrator.py -v`
Expected: FAIL — `ModuleNotFoundError` hoặc `AttributeError` tuỳ task trước đã merge chưa; nếu Task 1-3 đã xong thì test 1 và 2 PASS còn test 3 vẫn phải chạy được — chạy để xác nhận baseline trước khi sửa orchestrator.

- [ ] **Step 3: Wire the meter into `handle_turn`**

Trong `src/noble_agent/agent/orchestrator.py`, ở đầu `handle_turn` (sau khi có `sid`), bọc toàn bộ phần chạy lượt:

```python
        from noble_agent.billing import context as billing_ctx

        billing_on = bool(self._settings.billing_metering_enabled)
        meter = billing_ctx.get_session_meter(sid, self._channel or "chat") if billing_on else None
        meter_token = billing_ctx.set_meter(meter)
```

và trong `finally` của `handle_turn` (chỗ `on_done` đang được bảo đảm gọi):

```python
            billing_ctx.reset_meter(meter_token)
```

Trong nhánh `if saved:`, **ngay sau** dòng neo
`fire_and_forget(pg_data_plane.persist_turn_messages(sid, base_seq=prev, messages=new_msgs))`
— định vị bằng **văn bản neo này**, KHÔNG bằng số dòng: Task 5 đã sửa cùng file
(`orchestrator.py:395` và `:526`) nên số dòng đã lệch:

```python
                # Billing: rút meter và ghi lô — fire-and-forget, đúng khuôn
                # persist_turn_messages ở trên. Đặt SAU save_all vì lô mang
                # seq riêng của nó; ghi trước khi lượt chốt sẽ đóng seq cho một
                # lượt có thể còn hỏng.
                if meter is not None:
                    from noble_agent.billing import sink as billing_sink

                    # THỨ TỰ QUAN TRỌNG: flush TRƯỚC, tăng turn_idx SAU.
                    # add_llm đóng dấu turn_idx lúc gọi (trong lượt, = N), còn các
                    # dòng audio không-session-scoped lấy turn_idx trong drain().
                    # Tăng trước khi flush sẽ cho dòng audio N+1 trong khi dòng llm
                    # là N — cùng một lượt ra hai turn_idx khác nhau.
                    fire_and_forget(billing_sink.flush(meter))
                    meter.turn_idx += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_billing_orchestrator.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Regression — turn loop still intact**

Run: `pytest tests/unit/unified -k "orchestrator or runner or turn" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
ruff check src/noble_agent/agent/orchestrator.py tests/unit/unified/test_billing_orchestrator.py
git add src/noble_agent/agent/orchestrator.py tests/unit/unified/test_billing_orchestrator.py
git commit -m "feat(billing): orchestrator gắn meter theo lượt + flush sau save_all"
```

---

### Task 7: Đo thời lượng voice (VAD / STT / TTS / speaker-verify / cuộc gọi)

**Files:**
- Modify: `src/noble_agent/server/base_session.py` (`__init__` ~101-110, `process_audio_frame` ~522-580, `_embed_current_utterance` ~1065, `stop` ~402-516)
- Modify: `src/noble_agent/voice/voice_agent.py` (`__init__` ~165-186, vùng TTS ~755-775)
- Modify: `src/noble_agent/server/text_chat.py` (`_persist_session_end` ~363, gọi từ dòng 357)
- Test: `tests/unit/unified/test_billing_voice_meters.py`

**Interfaces:**
- Consumes: `UsageMeter.add_audio` (Task 1), `context.get_session_meter` / `pop_session_meter` (Task 3), `sink.flush` (Task 2)
- Produces: `VoiceAgent.__init__(..., usage_meter: UsageMeter | None = None)`; `BaseSession.billing: UsageMeter | None`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/unified/test_billing_voice_meters.py`:

```python
"""Quy tắc đo thời lượng — cái nào vào hoá đơn, cái nào chỉ là giá vốn."""

from noble_agent.billing.meter import UsageMeter


def _rows(m: UsageMeter) -> dict[str, object]:
    _seq, rows = m.drain()
    return {r.component: r for r in rows}


def test_vad_counts_audio_seconds_and_cpu_separately():
    m = UsageMeter(session_id="s1", channel="voice")
    for _ in range(10):                       # 10 chunk × 32 ms
        m.add_audio("vad", audio_sec=0.032, wall_ms=0.4, units=1)
    vad = _rows(m)["vad"]
    assert round(vad.audio_sec, 3) == 0.32
    assert round(vad.wall_ms, 1) == 4.0
    assert vad.units == 10


def test_stt_bills_real_audio_not_synthetic_silence():
    """Im lặng do agent tự bơm vào STT (keepalive) vẫn nằm trong hoá đơn nhà
    cung cấp, nhưng khách KHÔNG nói nó — nên nó thuộc wall_ms (giá vốn), không
    thuộc audio_sec (hoá đơn)."""
    m = UsageMeter(session_id="s1", channel="voice")
    m.add_audio("stt", audio_sec=4.2, wall_ms=12400.0)   # 4,2 s khách nói / 12,4 s stream mở
    stt = _rows(m)["stt"]
    assert stt.audio_sec == 4.2
    assert stt.wall_ms == 12400.0


def test_tts_counts_both_audio_seconds_and_characters():
    """ElevenLabs tính theo ký tự, VieNeu theo giây — ghi cả hai để Portal
    chọn theo hợp đồng của từng backend."""
    m = UsageMeter(session_id="s1", channel="voice")
    m.add_audio("tts", audio_sec=6.1, wall_ms=820.0, units=138)
    tts = _rows(m)["tts"]
    assert tts.audio_sec == 6.1
    assert tts.units == 138


def test_speaker_verify_counts_embeddings():
    m = UsageMeter(session_id="s1", channel="voice")
    m.add_audio("speaker_verify", audio_sec=1.5, wall_ms=95.0, units=1)
    sv = _rows(m)["speaker_verify"]
    assert sv.units == 1


def test_call_row_is_session_scoped():
    m = UsageMeter(session_id="s1", channel="voice")
    m.turn_idx = 7
    m.add_audio("call", purpose="session", audio_sec=38.6, units=1)
    call = _rows(m)["call"]
    assert call.turn_idx is None
    assert call.purpose == "session"
    assert call.audio_sec == 38.6
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_billing_voice_meters.py -v`
Expected: PASS ngay (chúng chỉ khẳng định hợp đồng của `UsageMeter` từ Task 1). Đây là **test đặc tả quy tắc** — chạy để chốt ngữ nghĩa trước khi cắm vào code thật. Nếu FAIL thì Task 1 sai, quay lại sửa.

- [ ] **Step 3: Create the meter in `BaseSession.__init__`**

Trong `src/noble_agent/server/base_session.py::__init__`, cạnh `self.metrics = MetricsCollector()` (dòng ~105):

```python
        from noble_agent.billing import context as _billing_ctx

        # `settings` đã được import ở đầu module — không alias lại.
        self.billing = (
            _billing_ctx.get_session_meter(session_id, "voice")
            if settings.billing_metering_enabled
            else None
        )
```

- [ ] **Step 4: Meter VAD and STT in `process_audio_frame`**

Trong vòng cắt chunk VAD (dòng ~526-530), bọc `self.vad.process_chunk(chunk)`:

```python
            _t0 = time.perf_counter()
            result = self.vad.process_chunk(chunk)
            if self.billing is not None:
                self.billing.add_audio(
                    "vad",
                    audio_sec=settings.vad_chunk_ms / 1000.0,
                    wall_ms=(time.perf_counter() - _t0) * 1000.0,
                    units=1,
                )
```

Trong nhánh gửi STT (dòng ~576), ngay trước `await self.stt.send(chunk)`:

```python
                if self.billing is not None:
                    # CHỈ audio thật của khách. Im lặng keepalive ở nhánh trên
                    # cố ý KHÔNG cộng vào audio_sec — agent tự bơm nó, khách
                    # không nói nó. Nó phản ánh trong wall_ms lúc đóng phiên.
                    self.billing.add_audio("stt", audio_sec=len(chunk) / (settings.stt_sample_rate * 2))
```

- [ ] **Step 5: Meter speaker verification**

Trong `_embed_current_utterance` (dòng ~1065), bọc lời gọi embed:

```python
        _t0 = time.perf_counter()
        _pcm_len = len(self._utterance_pcm)
        # ... lời gọi embed hiện có, giữ nguyên ...
        if self.billing is not None:
            self.billing.add_audio(
                "speaker_verify",
                audio_sec=_pcm_len / (settings.stt_sample_rate * 2),
                wall_ms=(time.perf_counter() - _t0) * 1000.0,
                units=1,
            )
```

- [ ] **Step 6: Meter TTS in `VoiceAgent`**

Thêm tham số vào `VoiceAgent.__init__` (dòng ~170), ngay sau `metrics`:

```python
        usage_meter=None,
```

và gán `self._billing = usage_meter` cạnh `self._metrics = metrics`.

Trong vùng TTS (dòng ~760-773), đếm byte frame và ký tự:

```python
                synth_t0 = time.monotonic()
                synth_first = True
                _tts_bytes = 0
                async with contextlib.aclosing(self._iter_clause_audio(sc)) as clause:
                    async for frame in clause:
                        if self._interrupted and settings.interrupt_mode == "immediate":
                            break
                        if synth_first:
                            ttfb_ms = (time.monotonic() - synth_t0) * 1000
                            self._metrics.record_latency("tts", "ttfb", ttfb_ms)
                            meta["ttfb_ms"] = round(ttfb_ms)
                            synth_first = False
                        _tts_bytes += len(frame)
                        await frame_q.put(frame)
                if not synth_first:
                    _total_ms = (time.monotonic() - synth_t0) * 1000
                    self._metrics.record_latency("tts", "total", _total_ms)
                    if self._billing is not None:
                        self._billing.add_audio(
                            "tts",
                            audio_sec=_tts_bytes / (settings.tts_sample_rate * 2),
                            wall_ms=_total_ms,
                            units=len(getattr(sc, "text", "") or ""),
                        )
```

Trong `BaseSession`, chỗ khởi tạo `VoiceAgent`, truyền `usage_meter=self.billing`.

- [ ] **Step 7: Final flush + call row on session close**

Trong `BaseSession.stop`, thay khối lưu metrics (dòng ~509-514):

```python
        try:
            from noble_agent.metrics.store import save_session_metrics

            await save_session_metrics(self.session_id, self.metrics, session_duration)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to save session metrics: %s", exc)

        if self.billing is not None:
            try:
                from noble_agent.billing import context as _billing_ctx
                from noble_agent.billing import sink as _billing_sink

                self.billing.add_audio("call", purpose="session", audio_sec=session_duration, units=1)
                await _billing_sink.flush(self.billing)
                _billing_ctx.pop_session_meter(self.session_id)
                _billing_sink.forget_session(self.session_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("billing: flush cuối phiên thất bại: %s", exc)
```

Trong `src/noble_agent/server/text_chat.py::_persist_session_end`, thêm ở cuối hàm (chat **không** có dòng `call` — không có thời lượng cuộc gọi để tính):

```python
    try:
        from noble_agent.billing import context as billing_ctx
        from noble_agent.billing import sink as billing_sink

        meter = billing_ctx.pop_session_meter(session_id)
        if meter is not None:
            await billing_sink.flush(meter)
            billing_sink.forget_session(session_id)
    except Exception:  # noqa: BLE001
        logger.warning("billing: flush cuối phiên chat thất bại", exc_info=True)
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/unit/unified/test_billing_voice_meters.py tests/unit/test_base_session.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
ruff check src/noble_agent/server/base_session.py src/noble_agent/voice/voice_agent.py src/noble_agent/server/text_chat.py
git add -A src/noble_agent tests/unit/unified/test_billing_voice_meters.py
git commit -m "feat(billing): đo thời lượng VAD/STT/TTS/speaker-verify + dòng call lúc đóng phiên"
```

---

### Task 8: Integration test với Postgres thật + tài liệu

**Files:**
- Create: `tests/integration/unified/test_billing_usage_events_pg.py`
- Create: `src/noble_agent/storage/sql/billing_reference.sql` (bản DDL **tham khảo** để dựng DB test — KHÔNG áp lên production, Portal sở hữu schema thật)
- Modify: `src/noble_agent/SMOKE.md`
- Modify: `CLAUDE.md` (mục Layout, bảng Key configuration, mục Storage, bảng Change Log)
- Modify: `docs/CHANGELOG-agent.md`

**Interfaces:**
- Consumes: toàn bộ Task 1-7.
- Produces: không có API mới.

- [ ] **Step 1: Write the reference DDL**

Create `src/noble_agent/storage/sql/billing_reference.sql`:

```sql
-- THAM KHẢO — KHÔNG áp lên production.
-- Schema billing do team Portal sở hữu và tạo. File này CHỈ để dựng DB cho
-- integration test. Nguồn sự thật:
-- docs/handoff/agent-postgres-billing-write-contract.md

CREATE SCHEMA IF NOT EXISTS billing;

CREATE TABLE IF NOT EXISTS billing.usage_events (
    event_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id     text NOT NULL,
    session_id    text NOT NULL,
    channel       text NOT NULL,
    seq           integer NOT NULL,
    turn_idx      integer,
    component     text NOT NULL,
    purpose       text NOT NULL DEFAULT 'conversation',
    provider      text NOT NULL DEFAULT '',
    model         text NOT NULL DEFAULT '',
    input_tokens       bigint NOT NULL DEFAULT 0,
    output_tokens      bigint NOT NULL DEFAULT 0,
    cache_write_tokens bigint NOT NULL DEFAULT 0,
    cache_read_tokens  bigint NOT NULL DEFAULT 0,
    audio_sec     double precision NOT NULL DEFAULT 0,
    wall_ms       double precision NOT NULL DEFAULT 0,
    units         bigint NOT NULL DEFAULT 0,
    exact         boolean NOT NULL DEFAULT true,
    occurred_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT usage_events_idem
        UNIQUE (tenant_id, session_id, seq, component, purpose, provider, model)
);

CREATE INDEX IF NOT EXISTS usage_events_tenant_time
    ON billing.usage_events (tenant_id, occurred_at);
CREATE INDEX IF NOT EXISTS usage_events_session
    ON billing.usage_events (tenant_id, session_id);

-- portal.current_tenant() là hàm của Portal. DB test dựng bản tối giản đọc GUC.
CREATE SCHEMA IF NOT EXISTS portal;
CREATE OR REPLACE FUNCTION portal.current_tenant() RETURNS text
    LANGUAGE sql STABLE AS $$ SELECT current_setting('app.tenant_id', true) $$;

ALTER TABLE billing.usage_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_insert ON billing.usage_events;
CREATE POLICY tenant_insert ON billing.usage_events
    FOR INSERT WITH CHECK (tenant_id = portal.current_tenant());

DROP POLICY IF EXISTS tenant_read ON billing.usage_events;
CREATE POLICY tenant_read ON billing.usage_events
    FOR SELECT USING (tenant_id = portal.current_tenant());
```

- [ ] **Step 2: Write the integration test**

Create `tests/integration/unified/test_billing_usage_events_pg.py`:

```python
"""Đối chiếu hợp đồng bảng billing với Postgres thật.

Cần: POSTGRES_ADMIN_DSN trỏ tới một DB test đã áp billing_reference.sql.
"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("POSTGRES_ADMIN_DSN"), reason="cần POSTGRES_ADMIN_DSN cho integration billing"
)


async def test_insert_then_retry_same_seq_does_not_duplicate(pg_conn):
    """Bất biến quan trọng nhất của hợp đồng: retry không nhân đôi hoá đơn."""
    from noble_agent.billing.sink import INSERT_SQL

    args = (
        "acme", "sess-1", "voice", 0, 0, "llm", "conversation", "anthropic", "claude-x",
        100, 10, 0, 900, 0.0, 1200.0, 1, True,
    )
    await pg_conn.execute("SELECT set_config('app.tenant_id', 'acme', true)")
    await pg_conn.execute(INSERT_SQL, *args)
    await pg_conn.execute(INSERT_SQL, *args)          # retry y hệt
    n = await pg_conn.fetchval(
        "SELECT count(*) FROM billing.usage_events WHERE tenant_id='acme' AND session_id='sess-1'"
    )
    assert n == 1


async def test_wrong_tenant_is_rejected_by_with_check(pg_agent_conn):
    """Bug phía agent không được phép ghi tiêu thụ của tenant khác."""
    from noble_agent.billing.sink import INSERT_SQL

    await pg_agent_conn.execute("SELECT set_config('app.tenant_id', 'acme', true)")
    with pytest.raises(Exception):
        await pg_agent_conn.execute(
            INSERT_SQL,
            "other-tenant", "s", "chat", 0, 0, "llm", "conversation", "p", "m",
            1, 1, 0, 0, 0.0, 0.0, 1, True,
        )


async def test_agent_role_cannot_update_or_delete(pg_agent_conn):
    """Append-only phải do DB cưỡng chế, không do kỷ luật code."""
    with pytest.raises(Exception):
        await pg_agent_conn.execute("UPDATE billing.usage_events SET input_tokens = 0")
    with pytest.raises(Exception):
        await pg_agent_conn.execute("DELETE FROM billing.usage_events")
```

**Repo chưa có fixture Postgres nào** (các `tests/unit/unified/test_pg_*.py` đều dùng đồ
giả), nên phải viết mới. Tạo `tests/integration/unified/conftest_billing.py`:

```python
"""Fixture Postgres cho integration test billing.

Dựng schema từ billing_reference.sql, tạo một role least-privilege đúng như
GRANT mà contract yêu cầu Portal cấp, rồi dọn sạch sau mỗi test.
"""

import os
from pathlib import Path

import pytest

_DDL = Path("src/noble_agent/storage/sql/billing_reference.sql")
_AGENT_ROLE = "billing_test_agent"
_AGENT_PW = "billing_test_pw"


@pytest.fixture
async def pg_owner():
    """Kết nối bằng superuser: dựng schema + role, dọn sau khi xong."""
    import asyncpg

    dsn = os.environ["POSTGRES_ADMIN_DSN"]
    conn = await asyncpg.connect(dsn)
    await conn.execute(_DDL.read_text(encoding="utf-8"))
    await conn.execute(
        f"DO $$ BEGIN "
        f"  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_AGENT_ROLE}') THEN "
        f"    CREATE ROLE {_AGENT_ROLE} LOGIN PASSWORD '{_AGENT_PW}'; "
        f"  END IF; "
        f"END $$;"
    )
    # Đúng bộ quyền contract §5 yêu cầu: USAGE + INSERT, KHÔNG hơn.
    await conn.execute(f"GRANT USAGE ON SCHEMA billing TO {_AGENT_ROLE}")
    await conn.execute(f"GRANT USAGE ON SCHEMA portal TO {_AGENT_ROLE}")
    await conn.execute(f"GRANT INSERT ON billing.usage_events TO {_AGENT_ROLE}")
    await conn.execute(f"REVOKE UPDATE, DELETE ON billing.usage_events FROM {_AGENT_ROLE}")
    await conn.execute("TRUNCATE billing.usage_events")
    try:
        yield conn
    finally:
        await conn.execute("TRUNCATE billing.usage_events")
        await conn.close()


@pytest.fixture
async def pg_conn(pg_owner):
    """Alias cho kết nối owner — dùng khi test không quan tâm phân quyền."""
    return pg_owner


@pytest.fixture
async def pg_agent_conn(pg_owner):
    """Kết nối bằng role least-privilege, đúng như agent chạy production."""
    import asyncpg

    dsn = os.environ["POSTGRES_ADMIN_DSN"]
    # Thay user/password trong DSN bằng role test.
    import urllib.parse as up

    parts = up.urlsplit(dsn)
    netloc = f"{_AGENT_ROLE}:{_AGENT_PW}@{parts.hostname}:{parts.port or 5432}"
    agent_dsn = up.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    conn = await asyncpg.connect(agent_dsn)
    try:
        yield conn
    finally:
        await conn.close()
```

Trong `tests/integration/unified/conftest.py`, thêm ở cuối để pytest thấy các fixture:

```python
from tests.integration.unified.conftest_billing import (  # noqa: F401
    pg_agent_conn,
    pg_conn,
    pg_owner,
)
```

- [ ] **Step 3: Run the integration test**

Run: `POSTGRES_ADMIN_DSN=... pytest tests/integration/unified/test_billing_usage_events_pg.py -v`
Expected: PASS (3 tests). Không có DSN → skip sạch.

- [ ] **Step 4: Add the smoke entry**

Thêm vào `src/noble_agent/SMOKE.md`:

```markdown
### Billing metering (khi BILLING_METERING_ENABLED=true)

1. Gọi/chat một phiên 3 lượt rồi cúp máy.
2. `SELECT seq, turn_idx, component, purpose, units, exact FROM billing.usage_events
   WHERE session_id = '<sid>' ORDER BY seq, component;`
3. Kỳ vọng: có dòng `llm` mỗi lượt; voice thêm `stt`/`tts`/`vad`; đúng **một** dòng
   `component='call'` với `turn_idx IS NULL`; `seq` liên tục từ 0.
4. Kiểm tra log: **không** có dòng `billing: ghi usage thất bại`.
5. Đo TTFA/TTFT trước-sau bằng `make bench` — không được xấu đi.
```

- [ ] **Step 5: Update CLAUDE.md**

- Bảng **Layout**: thêm hàng `` `billing/` `` — "Đo tiêu thụ để tính tiền: `meter.py` (in-memory, hot path), `sink.py` (ghi PG), `capture.py` (chuẩn hoá usage), `context.py` (ContextVar + registry phiên)".
- Bảng **Key configuration**: thêm hàng `BILLING_METERING_ENABLED` | `false` | "Bật đo tiêu thụ để tính tiền. Ghi `billing.usage_events` (Portal sở hữu, agent chỉ INSERT)."
- Mục **Storage**: thêm một đoạn — bề mặt ghi Postgres thứ hai ngoài `tenant_data`, agent chỉ `INSERT`, contract ở `docs/handoff/agent-postgres-billing-write-contract.md`.
- Bảng **Change Log**: thêm entry mới lên đầu, **xoá entry thứ 11**.

- [ ] **Step 6: Update the changelog**

Thêm entry lên ĐẦU bảng trong `docs/CHANGELOG-agent.md`:

```markdown
| 2026-08-18 | Billing usage metering: `billing/` mới (UsageMeter in-memory → sink `billing.usage_events`), bắt token 4 cột từ Anthropic + OpenAI-compat kèm nhãn `purpose`, đo `audio_sec`/`wall_ms` cho STT/TTS/VAD/speaker-verify + dòng `call` mỗi phiên. Gated sau `BILLING_METERING_ENABLED` (mặc định tắt). | Chưa có cơ chế nào đếm token/thời lượng để tính tiền khách; chi phí nền (summary, warm-cache, addressee-gate) hoàn toàn không nhìn thấy được. |
```

- [ ] **Step 7: Full suite**

Run: `make test-unified && make lint`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "feat(billing): integration test PG + smoke + tài liệu"
```

---

## Ghi chú cho người thực thi

**Bốn câu chưa chốt** (spec §11) — nếu chưa có trả lời khi tới Task 8, vẫn implement đủ và để cờ `BILLING_METERING_ENABLED=false`:

1. Tên schema/bảng: `billing.usage_events` hay `control.agent_usage_events`? → nếu đổi, sửa `INSERT_SQL` trong `sink.py` (một hằng, một chỗ).
2. GRANT cấp cho role nào — phải cấp cho **cả** role per-tenant và `odyssey_agent` (đường fallback).
3. `vad` / `speaker_verify` có tính tiền khách không → **không ảnh hưởng code**, agent vẫn đo.
4. `purpose` nào tính tiền → **không ảnh hưởng code**.

**Điều KHÔNG được làm:**
- Không ước lượng token khi provider không trả usage.
- Không thêm cột giá/tiền vào bất kỳ đâu.
- Không cho agent `SELECT`/`UPDATE`/`DELETE` trên bảng billing.
- Không `await` sink trên đường lượt (chỉ `fire_and_forget`), trừ lần flush cuối lúc đóng phiên.
- Không bật `stream_options` cho provider ngoài allowlist.
