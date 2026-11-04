"""Bất biến quan trọng nhất của tính năng: đường nóng không chạm I/O.

Test này tồn tại để một thay đổi tương lai không âm thầm kéo lệnh ghi billing
vào giữa lượt.
"""

import asyncio
from unittest.mock import AsyncMock

import fakeredis.aioredis
import pytest

from noble_agent.agent.base import load_agent_def
from noble_agent.agent.orchestrator import TurnRunner
from noble_agent.billing import context
from noble_agent.billing import sink as billing_sink
from noble_agent.billing.meter import UsageMeter
from noble_agent.config import UnifiedSettings
from noble_agent.storage import persist
from noble_agent.storage import pg_data_plane as DP
from noble_agent.storage.repo import StateRepo
from tests.unit.unified._persona import NOBLE_TOOLS, PERSONA_DIR


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
            during.append(len(calls))  # chụp số lần flush GIỮA lượt
        await sink.flush(meter)  # chỉ sau khi lượt xong

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

    await asyncio.wait_for(started.wait(), timeout=1)  # đã chạy nền
    assert not task.done()  # và caller không bị chặn
    released.set()
    await task


# ── orchestrator wiring: drive real handle_turn, not just the modules it calls ──
#
# The three tests above pin billing.context/meter/sink in isolation — they would
# stay green even if `handle_turn` swapped the flush/increment order, moved the
# flush outside `if saved:`, or dropped the `meter is not None` gate. These two
# tests construct a real TurnRunner (same fixture shape as
# test_pg_conversation_seed.py, which already exercises handle_turn against a
# fakeredis-backed StateRepo) so the ordering is proven by actually running the
# turn loop, not restated against already-merged modules.


class _Sink:
    async def on_token(self, t): ...
    async def on_tool_start(self, name, args): ...
    async def on_tool_done(self, name, result): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


@pytest.fixture
def agent():
    return load_agent_def(PERSONA_DIR, tool_names=NOBLE_TOOLS)


@pytest.fixture
async def redis():
    r = fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def repo(redis):
    return StateRepo(redis_client=redis, ttl_seconds=3600)


@pytest.fixture
def settings_billing_on():
    return UnifiedSettings(USE_UNIFIED_AGENT=True, NOBLE_SUMMARY_K=99, BILLING_METERING_ENABLED=True)


@pytest.fixture
def quiet_pg(monkeypatch):
    """Silence the OTHER fire-and-forget writes in `if saved:` (Task 5's
    seed_conversation / persist_turn_messages / insert_messages) so draining
    background tasks after a turn only has the billing flush to contend with.
    """
    monkeypatch.setattr(DP, "persist_turn_messages", AsyncMock())
    monkeypatch.setattr(DP, "seed_conversation", AsyncMock())


def _llm():
    llm = AsyncMock()
    llm.stream_completion = AsyncMock(return_value=("chào anh!", []))
    return llm


async def _drain():
    await asyncio.sleep(0)
    tasks = [t for t in persist._bg_tasks if not t.done()]
    if tasks:
        await asyncio.gather(*tasks)


async def test_billing_flush_call_time_turn_idx_precedes_increment(
    agent, repo, settings_billing_on, quiet_pg, monkeypatch
):
    """Pins `meter.turn_idx += 1` running AFTER `fire_and_forget(billing_sink.flush(meter))`.

    `fire_and_forget` only SCHEDULES the coroutine — its body would run later,
    asynchronously, well after any synchronous statement that follows in
    `handle_turn`. Capturing `meter.turn_idx` at that later point would not
    distinguish the two orderings. Instead this spy captures `meter.turn_idx`
    the moment `billing_sink.flush(meter)` is CALLED (synchronously, as part
    of evaluating the `fire_and_forget(...)` argument) — the value it sees is
    exactly whatever the source code order produces, with no asyncio
    scheduling ambiguity: a reversal (`turn_idx += 1` moved before the flush
    call) would make this observe the POST-increment value instead.
    """
    observed_turn_idx: list[int] = []

    def spy_flush(meter, **_kw):
        observed_turn_idx.append(meter.turn_idx)

        async def _ok():
            return True

        return _ok()

    monkeypatch.setattr(billing_sink, "flush", spy_flush)

    runner = TurnRunner(repo=repo, agent_def=agent, llm=_llm(), rag=None, settings=settings_billing_on, channel="chat")

    await runner.handle_turn("sid-BILL1", "câu 1", _Sink())
    await _drain()
    await runner.handle_turn("sid-BILL1", "câu 2", _Sink())
    await _drain()

    # Each turn's flush call observed turn_idx BEFORE that turn's own
    # increment. Had the two lines been swapped, this would read [1, 2].
    assert observed_turn_idx == [0, 1]

    meter = context.get_session_meter("sid-BILL1", "chat")
    assert meter.turn_idx == 2


async def test_billing_no_flush_when_save_all_fails(agent, repo, settings_billing_on, quiet_pg, monkeypatch):
    """Pins the `if saved:` placement: a turn whose save_all raises must
    dispatch NO flush at all — a batch drained before the turn is durable
    would close a seq for a turn that might still fail.
    """
    flush_calls: list[int] = []

    def spy_flush(meter, **_kw):
        flush_calls.append(1)

        async def _ok():
            return True

        return _ok()

    monkeypatch.setattr(billing_sink, "flush", spy_flush)

    async def _boom(*a, **k):
        raise RuntimeError("redis down")

    monkeypatch.setattr(repo, "save_all", _boom)

    runner = TurnRunner(repo=repo, agent_def=agent, llm=_llm(), rag=None, settings=settings_billing_on, channel="chat")

    await runner.handle_turn("sid-BILL2", "xin chào", _Sink())
    await _drain()

    assert flush_calls == []
    meter = context.get_session_meter("sid-BILL2", "chat")
    assert meter.turn_idx == 0  # never bumped either — the whole block was skipped


async def test_audio_rows_carry_the_same_turn_idx_as_llm_rows_in_one_batch(
    agent, repo, settings_billing_on, quiet_pg, monkeypatch
):
    """Bất biến: trong CÙNG một lô, dòng audio và dòng `llm` phải cùng `turn_idx`.

    Đây là bất biến mà `test_billing_flush_call_time_turn_idx_precedes_increment`
    KHÔNG canh được, và bug đã lọt qua đúng khe đó: test kia đọc
    `meter.turn_idx` tại thời điểm `flush` được GỌI (đồng bộ, pre-increment nên
    luôn đúng), còn dòng audio lại được đóng dấu muộn hơn — bên trong `drain()`,
    tức là trong thân coroutine mà `fire_and_forget` chỉ lên lịch. Khi thân đó
    chạy, `meter.turn_idx += 1` đã thực thi xong.

    Dữ liệu thật đã sập kiểu này: một lô ra `llm turn=0` và `stt turn=1`.

    Spy ở đây CỐ Ý là `async def` để chạy hoãn đúng như thật, và gọi `drain` với
    đúng kwargs nhận được — nếu orchestrator không truyền `turn_idx` tường minh
    thì `drain` rơi về `self.turn_idx` (đã tăng) và test đỏ.
    """
    captured: list = []

    async def spy_flush(meter, **kw):
        batch = meter.drain(turn_idx=kw.get("turn_idx"))
        if batch is not None:
            captured.append(batch[1])
        return True

    monkeypatch.setattr(billing_sink, "flush", spy_flush)

    runner = TurnRunner(repo=repo, agent_def=agent, llm=_llm(), rag=None, settings=settings_billing_on, channel="chat")

    # Bơm tay vào ĐÚNG meter mà orchestrator sẽ dùng. `_llm()` của test là fake
    # không đi qua StreamingClient nên không tự sinh dòng `llm`; thêm tay một
    # dòng để mô phỏng đúng thứ tự đóng dấu của đường thật: `add_llm` đóng dấu
    # NGAY (append-time), `add_audio` để `drain()` đóng dấu SAU.
    meter = context.get_session_meter("sid-BILL-TURNIDX", "chat")
    meter.add_llm(purpose="conversation", provider="p", model="m", input_tokens=10)
    meter.add_audio("stt", audio_sec=1.5)
    meter.add_audio("tts", audio_sec=2.5, units=40)

    await runner.handle_turn("sid-BILL-TURNIDX", "câu 1", _Sink())
    await _drain()

    assert captured, "không có lô nào được flush"
    rows = captured[0]
    llm_turns = {r.turn_idx for r in rows if r.component == "llm"}
    audio_turns = {r.turn_idx for r in rows if r.component in ("stt", "tts")}
    assert llm_turns == {0}, f"dòng llm phải mang turn 0, thực tế {llm_turns}"
    assert audio_turns == {0}, f"dòng audio phải mang turn 0, thực tế {audio_turns}"


async def test_replayed_batch_keeps_its_original_turn_idx(agent, repo, settings_billing_on, quiet_pg):
    """Lô chưa commit phải replay NGUYÊN VẸN — kể cả `turn_idx`.

    `ON CONFLICT DO NOTHING` giữ bản đã landed, nên đóng dấu lại một seq có thể
    đã ghi là làm hai lần ghi cùng seq mang nội dung khác nhau.
    """
    from noble_agent.billing.meter import UsageMeter

    m = UsageMeter(session_id="s-replay", channel="voice")
    m.add_audio("stt", audio_sec=1.0)
    seq, rows = m.drain(turn_idx=3)
    assert [r.turn_idx for r in rows] == [3]

    # Chưa commit → replay, và turn_idx mới bị BỎ QUA.
    seq2, rows2 = m.drain(turn_idx=99)
    assert seq2 == seq
    assert [r.turn_idx for r in rows2] == [3]
