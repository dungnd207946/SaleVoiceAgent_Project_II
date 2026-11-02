"""TTS WS server handler — synth request → binary PCM + END (Task 6).

Inject FakeTTS qua monkeypatch → không cần vieneu/GPU.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from noble_agent.voice.service import protocol as p


class FakeWS:
    def __init__(self, incoming, headers=None):
        self._incoming = list(incoming)
        self.sent: list = []
        self.closed_code = None
        self.request = SimpleNamespace(headers=headers or {}, path="/tts")

    async def send(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed_code = code

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self._incoming.pop(0)


class FakeTTS:
    def __init__(self):
        self.voice = None

    def set_voice(self, vid):
        self.voice = vid

    async def stream(self, text, stop_event=None):
        yield b"AAAA"
        yield b"BBBB"


async def test_tts_handler_streams_pcm_then_end(monkeypatch):
    created: list[FakeTTS] = []

    def factory():
        inst = FakeTTS()
        created.append(inst)
        return inst

    monkeypatch.setattr("noble_agent.voice.service.tts_server._make_tts", factory)
    monkeypatch.setattr("noble_agent.voice.service.tts_server.settings.voice_service_auth_token", "", raising=False)
    from noble_agent.voice.service import tts_server

    ws = FakeWS([p.synthesize_msg("xin chào", voice="luna")])
    await tts_server.handler(ws)

    binary = [s for s in ws.sent if isinstance(s, bytes)]
    text = [p.parse(s) for s in ws.sent if isinstance(s, str)]
    assert binary == [b"AAAA", b"BBBB"]
    assert {"type": "end"} in text
    assert created[0].voice == "luna"


async def test_make_tts_selects_engine(monkeypatch):
    """tts_server._make_tts picks the engine by settings.tts_service_engine (drop-in classes)."""
    import noble_agent.voice.tts.vieneu as v
    import noble_agent.voice.tts.vieneu_vllm as vv

    monkeypatch.setattr(v, "AsyncVieNeuTTS", lambda: "VIENEU")
    monkeypatch.setattr(vv, "AsyncVieNeuVLLMTTS", lambda: "VLLM")
    from noble_agent.voice.service import tts_server

    monkeypatch.setattr(tts_server.settings, "tts_service_engine", "vieneu", raising=False)
    assert tts_server._make_tts() == "VIENEU"
    monkeypatch.setattr(tts_server.settings, "tts_service_engine", "vieneu_vllm", raising=False)
    assert tts_server._make_tts() == "VLLM"


async def test_tts_handler_rejects_bad_token(monkeypatch):
    monkeypatch.setattr("noble_agent.voice.service.tts_server._make_tts", FakeTTS)
    monkeypatch.setattr(
        "noble_agent.voice.service.tts_server.settings.voice_service_auth_token", "secret", raising=False
    )
    from noble_agent.voice.service import tts_server

    ws = FakeWS([p.synthesize_msg("hi")], headers={})
    await tts_server.handler(ws)
    assert ws.closed_code == 1008
    assert ws.sent == []


class _Closed(Exception):
    """Stand-in for websockets.ConnectionClosed raised mid-stream."""


class FakeTTSCancelable:
    """Records the stop_event passed into stream; raises on the 2nd send to simulate WS drop."""

    def __init__(self):
        self.voice = None
        self.seen_stop_event = None

    def set_voice(self, vid):
        self.voice = vid

    async def stream(self, text, stop_event=None):
        self.seen_stop_event = stop_event
        yield b"AAAA"
        yield b"BBBB"


async def test_synthesize_cancels_on_disconnect(monkeypatch):
    created: list[FakeTTSCancelable] = []

    def factory():
        inst = FakeTTSCancelable()
        created.append(inst)
        return inst

    monkeypatch.setattr("noble_agent.voice.service.tts_server._make_tts", factory)
    monkeypatch.setattr("noble_agent.voice.service.tts_server.settings.voice_service_auth_token", "", raising=False)
    from noble_agent.voice.service import tts_server

    class DroppingWS(FakeWS):
        async def send(self, data):
            self.sent.append(data)
            if isinstance(data, bytes) and len([s for s in self.sent if isinstance(s, bytes)]) >= 1:
                raise _Closed("client gone")

    ws = DroppingWS([p.synthesize_msg("xin chào", voice="luna")])
    await tts_server.handler(ws)

    inst = created[0]
    # The handler passed a stop_event into stream and set it when the send blew up.
    assert inst.seen_stop_event is not None
    assert inst.seen_stop_event.is_set()


async def test_tts_handler_ignores_binary_frames(monkeypatch):
    created: list[FakeTTS] = []

    def factory():
        inst = FakeTTS()
        created.append(inst)
        return inst

    monkeypatch.setattr("noble_agent.voice.service.tts_server._make_tts", factory)
    monkeypatch.setattr("noble_agent.voice.service.tts_server.settings.voice_service_auth_token", "", raising=False)
    from noble_agent.voice.service import tts_server

    ws = FakeWS([b"noise", p.synthesize_msg("hello")])
    await tts_server.handler(ws)

    binary = [s for s in ws.sent if isinstance(s, bytes)]
    text = [p.parse(s) for s in ws.sent if isinstance(s, str)]
    assert binary == [b"AAAA", b"BBBB"]
    assert {"type": "end"} in text
