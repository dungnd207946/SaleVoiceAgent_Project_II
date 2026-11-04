"""SonioxSTT must hold its WebSocket open through silence.

Soniox terminates a real-time stream with error 408 after ~20s without audio
frames or `{"type": "keepalive"}` messages. With STT_INPUT_GATE_MODE=vad the
input gate sends nothing during silence, so the adapter itself must emit the
protocol keepalive — otherwise the connection dies mid-call and every later
utterance is silently dropped (send() no-ops on a closed socket).
"""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.protocol import State as WsState

from noble_agent.voice.stt import soniox as soniox_mod
from noble_agent.voice.stt.soniox import SonioxSTT


class FakeWs:
    """Minimal stand-in for a websockets client connection."""

    def __init__(self):
        self.sent: list[str | bytes] = []
        self.state = WsState.OPEN

    async def send(self, data):
        self.sent.append(data)

    async def close(self):
        self.state = WsState.CLOSED

    def __aiter__(self):
        return self

    async def __anext__(self):
        # Never yields — keeps _receive_loop parked like a silent server.
        await asyncio.Future()


@pytest.fixture
def fake_ws(monkeypatch):
    ws = FakeWs()

    async def _connect(*args, **kwargs):
        return ws

    monkeypatch.setattr(soniox_mod.websockets, "connect", _connect)
    monkeypatch.setattr(soniox_mod, "KEEPALIVE_INTERVAL_S", 0.05)
    monkeypatch.setattr(soniox_mod, "_load_hotwords", lambda: [])
    return ws


def _keepalives(ws: FakeWs) -> list[str]:
    out = []
    for msg in ws.sent[1:]:  # sent[0] is the config frame
        if isinstance(msg, str) and msg and json.loads(msg).get("type") == "keepalive":
            out.append(msg)
    return out


async def test_keepalive_sent_during_silence(fake_ws):
    stt = SonioxSTT()
    await stt.start()
    try:
        await asyncio.sleep(0.2)
        assert _keepalives(fake_ws), "no keepalive sent while idle — Soniox will 408 after 20s"
    finally:
        await stt.stop()


async def test_audio_resets_keepalive_timer(fake_ws):
    stt = SonioxSTT()
    await stt.start()
    try:
        # Stream audio more often than the interval: no keepalive should fire.
        for _ in range(6):
            await stt.send(b"\x00\x00" * 160)
            await asyncio.sleep(0.02)
        assert not _keepalives(fake_ws)
    finally:
        await stt.stop()


async def test_stop_cancels_keepalive(fake_ws):
    stt = SonioxSTT()
    await stt.start()
    await stt.stop()
    sent_after_stop = len(fake_ws.sent)
    await asyncio.sleep(0.15)
    assert len(fake_ws.sent) == sent_after_stop
