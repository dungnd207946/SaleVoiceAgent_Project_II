"""HotlineWsTTS client — `{"cmd":"synth"}` → binary PCM chunks → `{"event":"end"}`.

Mock websockets.connect; không mở socket thật. Fake-WS pattern lấy từ
`test_remote_tts.py` (FakeServerWS / SlowWS) — dùng nguyên vẹn.
"""

from __future__ import annotations

import asyncio
import json


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


def _patch_connect(monkeypatch, fake):
    async def fake_connect(url, **kwargs):
        return fake

    monkeypatch.setattr("noble_agent.voice.tts.hotline_ws.websockets.connect", fake_connect)


async def test_hotline_ws_streams_pcm_until_end(monkeypatch):
    incoming = [
        json.dumps({"event": "start", "sr": 24000, "id": "1"}),
        b"PCMA",
        b"PCMB",
        json.dumps({"event": "end", "id": "1", "reason": "complete"}),
        b"AFTER_END",
    ]
    fake = FakeServerWS(incoming)
    _patch_connect(monkeypatch, fake)

    from noble_agent.voice.tts.hotline_ws import HotlineWsTTS

    tts = HotlineWsTTS()
    out = [chunk async for chunk in tts.stream("xin chào")]

    # start skipped, binaries yielded, end terminates, post-end ignored.
    assert out == [b"PCMA", b"PCMB"]
    assert fake.closed is True

    # sent frame parses to {"cmd":"synth"} with text + id.
    synth = [json.loads(s) for s in fake.sent if isinstance(s, str) and json.loads(s).get("cmd") == "synth"]
    assert len(synth) == 1
    assert synth[0]["text"] == "xin chào"
    assert synth[0]["id"] == "1"


async def test_hotline_ws_end_reason_error_terminates(monkeypatch):
    incoming = [
        b"PCMA",
        json.dumps({"event": "end", "reason": "error", "error": "synth fail"}),
        b"AFTER",
    ]
    fake = FakeServerWS(incoming)
    _patch_connect(monkeypatch, fake)

    from noble_agent.voice.tts.hotline_ws import HotlineWsTTS

    tts = HotlineWsTTS()
    out = [chunk async for chunk in tts.stream("hi")]

    assert out == [b"PCMA"]  # yields what came before, then stops cleanly
    assert fake.closed is True


async def test_hotline_ws_error_event_terminates(monkeypatch):
    incoming = [
        b"PCMA",
        json.dumps({"event": "error", "error": "bad json"}),
        b"AFTER",
    ]
    fake = FakeServerWS(incoming)
    _patch_connect(monkeypatch, fake)

    from noble_agent.voice.tts.hotline_ws import HotlineWsTTS

    tts = HotlineWsTTS()
    out = [chunk async for chunk in tts.stream("hi")]

    assert out == [b"PCMA"]  # no raise, stops cleanly
    assert fake.closed is True


async def test_hotline_ws_pause_sends_stop_and_closes(monkeypatch):
    from websockets.exceptions import ConnectionClosedOK

    started = asyncio.Event()

    class SlowWS(FakeServerWS):
        async def __anext__(self):
            started.set()
            while not self.closed:
                await asyncio.sleep(0)
            raise ConnectionClosedOK(None, None)

    fake = SlowWS([])
    _patch_connect(monkeypatch, fake)

    from noble_agent.voice.tts.hotline_ws import HotlineWsTTS

    tts = HotlineWsTTS()

    async def consume():
        async for _ in tts.stream("dài"):
            pass

    task = asyncio.create_task(consume())
    await started.wait()
    await tts.pause()

    assert fake.closed is True
    # A {"cmd":"stop"} frame was sent before close.
    assert any(isinstance(s, str) and json.loads(s).get("cmd") == "stop" for s in fake.sent)
    # Generator self-terminates (no external cancel needed).
    await asyncio.wait_for(task, timeout=2)


async def test_hotline_ws_strips_emoji_from_sent_text(monkeypatch):
    incoming = [json.dumps({"event": "end", "reason": "complete"})]
    fake = FakeServerWS(incoming)
    _patch_connect(monkeypatch, fake)

    from noble_agent.voice.tts.hotline_ws import HotlineWsTTS

    tts = HotlineWsTTS()
    _ = [chunk async for chunk in tts.stream("chào bạn 😀🎉")]

    synth = [json.loads(s) for s in fake.sent if isinstance(s, str) and json.loads(s).get("cmd") == "synth"]
    assert len(synth) == 1
    # Vietnamese preserved, emoji removed.
    assert "😀" not in synth[0]["text"]
    assert "🎉" not in synth[0]["text"]
    assert "chào bạn" in synth[0]["text"]


async def test_hotline_ws_empty_after_emoji_strip_no_connect(monkeypatch):
    connected = {"n": 0}

    async def fake_connect(url, **kwargs):
        connected["n"] += 1
        return FakeServerWS([])

    monkeypatch.setattr("noble_agent.voice.tts.hotline_ws.websockets.connect", fake_connect)

    from noble_agent.voice.tts.hotline_ws import HotlineWsTTS

    tts = HotlineWsTTS()
    out = [chunk async for chunk in tts.stream("😀🎉")]

    assert out == []
    assert connected["n"] == 0  # returned early, no WS opened


def test_hotline_ws_set_voice_stores():
    from noble_agent.voice.tts.hotline_ws import HotlineWsTTS

    tts = HotlineWsTTS()
    tts.set_voice("luna")
    assert tts._voice_id == "luna"
