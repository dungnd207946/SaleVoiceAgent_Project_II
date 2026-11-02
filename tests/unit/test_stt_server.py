"""STT WS server handler — forward audio to SherpaSTT, push transcripts (Task 5).

Inject FakeSherpaSTT qua monkeypatch → không cần sherpa-onnx.
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
        self.request = SimpleNamespace(headers=headers or {}, path="/stt")

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


class FakeSherpaSTT:
    """Khi nhận audio → phát ngay một final qua callback (coroutine)."""

    def __init__(self, on_partial=None, on_final=None):
        self.on_partial = on_partial
        self.on_final = on_final
        self.started = False
        self.stopped = False

    async def start(self):
        self.started = True

    async def send(self, pcm):
        if self.on_partial:
            await self.on_partial("xin")
        if self.on_final:
            await self.on_final("xin chào")

    async def stop(self):
        self.stopped = True


async def test_stt_handler_forwards_transcripts(monkeypatch):
    created: list[FakeSherpaSTT] = []

    def _factory(on_partial=None, on_final=None):
        inst = FakeSherpaSTT(on_partial=on_partial, on_final=on_final)
        created.append(inst)
        return inst

    monkeypatch.setattr("noble_agent.voice.service.stt_server.SherpaSTT", _factory)
    monkeypatch.setattr("noble_agent.voice.service.stt_server.settings.voice_service_auth_token", "", raising=False)
    from noble_agent.voice.service import stt_server

    ws = FakeWS([b"\x00\x01", p.control_msg(p.EOS)])
    await stt_server.handler(ws)

    texts = [p.parse(s) for s in ws.sent if isinstance(s, str)]
    assert {"type": "partial", "text": "xin"} in texts
    assert {"type": "final", "text": "xin chào"} in texts
    assert created[0].started is True
    assert created[0].stopped is True


async def test_stt_handler_rejects_bad_token(monkeypatch):
    monkeypatch.setattr("noble_agent.voice.service.stt_server.SherpaSTT", FakeSherpaSTT)
    monkeypatch.setattr(
        "noble_agent.voice.service.stt_server.settings.voice_service_auth_token", "secret", raising=False
    )
    from noble_agent.voice.service import stt_server

    ws = FakeWS([b"\x00"], headers={})  # thiếu token
    await stt_server.handler(ws)
    assert ws.closed_code == 1008
    assert ws.sent == []  # không xử lý audio


class FailingSherpaSTT:
    """start() raises — used to verify that finally always calls stop()."""

    def __init__(self, on_partial=None, on_final=None):
        self.stopped = False

    async def start(self):
        raise RuntimeError("boom")

    async def send(self, pcm):  # pragma: no cover
        pass

    async def stop(self):
        self.stopped = True


async def test_stt_handler_stops_on_start_failure(monkeypatch):
    created: list[FailingSherpaSTT] = []

    def _factory(on_partial=None, on_final=None):
        inst = FailingSherpaSTT(on_partial=on_partial, on_final=on_final)
        created.append(inst)
        return inst

    monkeypatch.setattr("noble_agent.voice.service.stt_server.SherpaSTT", _factory)
    monkeypatch.setattr("noble_agent.voice.service.stt_server.settings.voice_service_auth_token", "", raising=False)
    from noble_agent.voice.service import stt_server

    ws = FakeWS([], headers={})
    await stt_server.handler(ws)  # must not raise

    assert created[0].stopped is True
