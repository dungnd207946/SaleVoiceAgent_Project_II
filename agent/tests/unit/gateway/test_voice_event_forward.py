"""Voice bridge: forward worker UI events (LiveKit data channel) to the provider ws.

`_bridge_voice` itself is integration-level (needs a live LiveKit room); these
tests cover the pure pieces it delegates to: the packet filter/enqueue and the
event pump that turns queued JSON into ws TEXT frames.
"""

import asyncio

from noble_agent.gateway import server as s


class _FakeWS:
    def __init__(self):
        self.sent: list = []

    async def send(self, msg):
        self.sent.append(msg)


# ---------------------------------------------------------------- enqueue_event


def test_enqueue_accepts_agent_events_topic():
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    payload = '{"type": "transcript", "text": "xin chào"}'
    assert s.enqueue_event(q, "agent-events", payload.encode("utf-8")) is True
    assert q.get_nowait() == payload


def test_enqueue_accepts_untopiced_greeting_packets():
    # Greeting events are published with NO topic (room_session._send_livekit_event).
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    assert s.enqueue_event(q, "", b'{"type": "agent_speaking", "turn_id": "greeting"}') is True
    assert s.enqueue_event(q, None, b'{"type": "agent_done", "turn_id": "greeting"}') is True
    assert q.qsize() == 2


def test_enqueue_rejects_foreign_topic():
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    assert s.enqueue_event(q, "other-topic", b'{"type": "x"}') is False
    assert q.empty()


def test_enqueue_drops_when_queue_full_without_raising():
    # UI events are best-effort: a slow provider must never block/burst the bridge.
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    assert s.enqueue_event(q, "agent-events", b"first") is True
    assert s.enqueue_event(q, "agent-events", b"second") is False
    assert q.get_nowait() == "first"


def test_enqueue_drops_undecodable_payload():
    q: asyncio.Queue = asyncio.Queue(maxsize=4)
    assert s.enqueue_event(q, "agent-events", b"\xff\xfe\xfa") is False
    assert q.empty()


# ------------------------------------------------------------ _pump_agent_events


async def test_pump_sends_queued_events_as_text_frames_in_order():
    q: asyncio.Queue = asyncio.Queue()
    ws = _FakeWS()
    q.put_nowait('{"type": "transcript"}')
    q.put_nowait('{"type": "agent_speaking"}')

    task = asyncio.create_task(s._pump_agent_events(q, ws))
    await asyncio.wait_for(q.join(), timeout=1.0)
    task.cancel()

    # str (not bytes) → the websockets lib emits TEXT frames, so the provider
    # can tell events apart from binary PCM audio.
    assert ws.sent == ['{"type": "transcript"}', '{"type": "agent_speaking"}']
    assert all(isinstance(m, str) for m in ws.sent)


async def test_pump_swallows_send_errors():
    # Provider ws closed mid-call: the pump must end quietly, not crash the bridge.
    q: asyncio.Queue = asyncio.Queue()

    class _DeadWS:
        async def send(self, msg):
            raise ConnectionError("ws closed")

    q.put_nowait('{"type": "transcript"}')
    await asyncio.wait_for(s._pump_agent_events(q, _DeadWS()), timeout=1.0)
