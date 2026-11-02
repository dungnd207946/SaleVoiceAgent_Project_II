"""RemoteSTT client — demux server text frames to callbacks (Task 3).

Mock websockets.connect; không mở socket thật.
"""

from __future__ import annotations

import asyncio

from websockets.protocol import State as WsState

from noble_agent.voice.service import protocol as p


class FakeServerWS:
    """Giả websocket: phát sẵn frame cho client recv-loop, ghi lại frame client gửi."""

    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent: list = []
        self.closed = False
        self.state = WsState.OPEN

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.closed = True
        self.state = WsState.CLOSED

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._incoming:
            raise StopAsyncIteration
        await asyncio.sleep(0)
        return self._incoming.pop(0)


async def test_remote_stt_emits_partial_and_final(monkeypatch):
    frames = [
        p.transcript_msg(p.PARTIAL, "xin"),
        p.transcript_msg(p.FINAL, "xin chào"),
    ]
    fake = FakeServerWS(frames)

    async def fake_connect(url, **kwargs):
        return fake

    monkeypatch.setattr("noble_agent.voice.stt.remote.websockets.connect", fake_connect)

    partials: list[str] = []
    finals: list[str] = []

    async def on_partial(t):
        partials.append(t)

    async def on_final(t):
        finals.append(t)

    from noble_agent.voice.stt.remote import RemoteSTT

    stt = RemoteSTT(on_partial=on_partial, on_final=on_final)
    await stt.start()
    # đẩy một chunk audio (binary)
    await stt.send(b"\x00\x01")
    # cho recv-loop tiêu thụ các frame đã phát
    await asyncio.sleep(0.05)
    await stt.stop()

    assert partials == ["xin"]
    assert finals == ["xin chào"]
    assert b"\x00\x01" in fake.sent  # audio đã được forward dưới dạng binary


async def test_remote_stt_send_before_start_is_noop(monkeypatch):
    from noble_agent.voice.stt.remote import RemoteSTT

    stt = RemoteSTT()
    # chưa start → không có ws; send không được ném lỗi
    await stt.send(b"\x00")
