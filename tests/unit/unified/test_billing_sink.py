"""Sink billing — best-effort, retry bằng cách giữ nguyên lô chưa commit."""

import json

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
    m.add_llm(
        purpose="conversation",
        provider="anthropic",
        model="claude-x",
        input_tokens=100,
        output_tokens=10,
        cache_read_tokens=900,
    )
    return m


async def test_flush_writes_the_batch_and_commits(wired):
    m = _meter_with_one_row()
    ok = await sink.flush(m)
    assert ok is True
    assert len(wired.batches) == 1
    assert len(wired.batches[0]) == 1
    row = wired.batches[0][0]
    assert row[0] == "acme"  # tenant_id
    assert row[1] == "s1"  # session_id
    assert row[2] == "voice"  # channel
    assert row[3] == 0  # seq
    # Đã commit → không còn gì để ghi lại
    assert m.drain() is None


async def test_occurred_at_is_the_time_the_usage_happened_not_the_insert_time(wired):
    """Contract §8: dòng đến muộn vẫn phải mang đúng thời điểm phát sinh.

    Để DB default `now()` thì một lô bị PG chết chặn qua nửa đêm cuối tháng rơi
    sang kỳ hoá đơn sau (Portal rollup gộp theo occurred_at).
    """
    from datetime import UTC, datetime

    m = _meter_with_one_row()
    stamped = m.drain()[1][0].occurred_at
    await sink.flush(m)
    row = wired.batches[0][0]
    assert "occurred_at" in wired.sql
    assert row[-1] == stamped  # occurred_at luôn là param cuối của INSERT
    assert stamped.tzinfo is not None
    assert (datetime.now(UTC) - stamped).total_seconds() < 60


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
    seq, rows = m.drain()  # lô vẫn còn, đúng seq cũ
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


async def test_final_flush_failure_dumps_the_payload_as_json(monkeypatch, caplog):
    """Spec §6: lần rút CUỐI hỏng thì phải dump payload JSON mức error.

    `_log_once` chỉ ồn ào lần đầu mỗi phiên, nên PG chết suốt một cuộc gọi 12
    phút sẽ log ở flush giữa cuộc rồi IM LẶNG ở flush cuối — đúng lần mang dòng
    `call` (toàn bộ thời lượng) cộng mọi lượt chưa commit. Vừa không cứu được
    vừa không thấy được.
    """
    conn = FakeConn(fail=True)

    async def fake_pool(_tid):
        return object()

    monkeypatch.setattr(sink, "_pool_for_tenant", fake_pool)
    monkeypatch.setattr(sink, "_tenant_conn", lambda _pool, _tid: FakeCtx(conn))
    monkeypatch.setattr(sink, "_tenant_id", lambda: "acme")

    m = _meter_with_one_row()
    m.add_audio("call", purpose="session", audio_sec=720.0, units=1)
    sink._logged.add(m.session_id)  # flush giữa cuộc đã log rồi → _log_once im lặng

    with caplog.at_level("ERROR", logger="noble_agent.billing.sink"):
        assert await sink.flush(m, final=True) is False

    dumps = [r.getMessage() for r in caplog.records if "payload" in r.getMessage()]
    assert len(dumps) == 1
    payload = json.loads(dumps[0].split("payload: ", 1)[1])
    assert payload["session_id"] == "s1"
    assert payload["seq"] == 0
    components = {r["component"] for r in payload["rows"]}
    assert components == {"llm", "call"}
    assert any(r["audio_sec"] == 720.0 for r in payload["rows"])
    sink.forget_session(m.session_id)


async def test_non_final_flush_failure_does_not_dump(monkeypatch, caplog):
    """Flush giữa cuộc KHÔNG dump: lô còn được thử lại, và dump mỗi lượt sẽ
    biến log thành bãi rác đúng lúc PG đang chết."""
    conn = FakeConn(fail=True)

    async def fake_pool(_tid):
        return object()

    monkeypatch.setattr(sink, "_pool_for_tenant", fake_pool)
    monkeypatch.setattr(sink, "_tenant_conn", lambda _pool, _tid: FakeCtx(conn))
    monkeypatch.setattr(sink, "_tenant_id", lambda: "acme")

    m = _meter_with_one_row()
    sink._logged.add(m.session_id)
    with caplog.at_level("ERROR", logger="noble_agent.billing.sink"):
        assert await sink.flush(m) is False
    assert not [r for r in caplog.records if "payload" in r.getMessage()]
    sink.forget_session(m.session_id)


async def test_flush_never_raises(monkeypatch):
    """Billing hỏng không được phép làm hỏng cuộc gọi."""

    async def explode(_tid):
        raise ValueError("catastrophe")

    monkeypatch.setattr(sink, "_pool_for_tenant", explode)
    monkeypatch.setattr(sink, "_tenant_id", lambda: "acme")
    assert await sink.flush(_meter_with_one_row()) is False
