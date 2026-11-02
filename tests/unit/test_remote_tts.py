"""RemoteTTS client — synth request → binary PCM chunks (Task 4).

Mock websockets.connect; không mở socket thật.
"""

from __future__ import annotations

import asyncio

from noble_agent.voice.service import protocol as p


class FakeServerWS:
    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent: list = []
        self.closed = False

    @property
    def state(self):
        from websockets.protocol import State

        return State.CLOSED if self.closed else State.OPEN

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        item = self._incoming.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


async def test_remote_tts_streams_pcm_until_end(monkeypatch):
    frames = [b"PCMA", b"PCMB", p.control_msg(p.END), b"IGNORED_AFTER_END"]
    fake = FakeServerWS(frames)

    async def fake_connect(url, **kwargs):
        return fake

    monkeypatch.setattr("noble_agent.voice.tts.remote.websockets.connect", fake_connect)

    from noble_agent.voice.tts.remote import RemoteTTS

    tts = RemoteTTS()
    out = [chunk async for chunk in tts.stream("xin chào")]

    assert out == [b"PCMA", b"PCMB"]  # dừng ở END, bỏ frame sau
    # synthesize request đã được gửi dưới dạng text JSON
    assert any(p.parse(s).get("type") == p.SYNTHESIZE for s in fake.sent if isinstance(s, str))
    assert fake.closed is True  # WS đóng sau khi stream xong


async def test_remote_tts_pause_closes_active_ws(monkeypatch):
    # Simulate a slow stream: once the ws is closed, raise ConnectionClosedOK so the
    # async-for terminates and the generator self-exits without any external cancel.
    from websockets.exceptions import ConnectionClosedOK

    started = asyncio.Event()

    class SlowWS(FakeServerWS):
        async def __anext__(self):
            started.set()
            # Spin until pause() closes the ws, then simulate the real library.
            while not self.closed:
                await asyncio.sleep(0)
            raise ConnectionClosedOK(None, None)

    fake = SlowWS([])

    async def fake_connect(url, **kwargs):
        return fake

    monkeypatch.setattr("noble_agent.voice.tts.remote.websockets.connect", fake_connect)

    from noble_agent.voice.tts.remote import RemoteTTS

    tts = RemoteTTS()

    async def consume():
        async for _ in tts.stream("dài"):
            pass

    task = asyncio.create_task(consume())
    await started.wait()
    await tts.pause()  # phải đóng active ws
    assert fake.closed is True
    # Generator must self-terminate (no external cancel needed).
    await asyncio.wait_for(task, timeout=2)


def test_remote_tts_set_voice():
    from noble_agent.voice.tts.remote import RemoteTTS

    tts = RemoteTTS()
    tts.set_voice("luna")
    assert tts._voice_id == "luna"
