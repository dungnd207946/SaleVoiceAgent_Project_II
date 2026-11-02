"""Hợp đồng WS `remote` của stt (docs/remote_stt_tts_spect.md): handler thật, recognizer giả,
client websockets thật. `sherpa_onnx` chỉ có trong image stt nên được stub."""

import asyncio
import importlib.util
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest
import websockets

STT_SERVER = Path(__file__).resolve().parents[1] / "stt" / "stt_server.py"


class FakeStream:
    # accept_waveform nằm trên STREAM (khớp API thật của sherpa).
    def __init__(self, script):
        self.script = script
        self.i = -1

    def accept_waveform(self, sr, samples):
        self.i += 1


class FakeRecognizer:
    """script: (text, is_endpoint) theo lần accept_waveform thứ i."""

    def __init__(self, script):
        self.script = script

    def create_stream(self, **_):
        return FakeStream(self.script)

    def is_ready(self, s):
        return False

    def decode_stream(self, s):
        pass

    def get_result(self, s):
        return s.script[s.i][0] if 0 <= s.i < len(s.script) else ""

    def is_endpoint(self, s):
        return s.script[s.i][1] if 0 <= s.i < len(s.script) else False

    def reset(self, s):
        pass


@pytest.fixture
def stt(monkeypatch):
    monkeypatch.setitem(sys.modules, "sherpa_onnx", types.ModuleType("sherpa_onnx"))
    spec = importlib.util.spec_from_file_location("stt_server_protocol_undertest", STT_SERVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._recognizer = FakeRecognizer([("xin chao", False), ("xin chao anh", True)])
    module.TOKEN = ""
    return module


@pytest.fixture
async def url(stt):
    server = await websockets.serve(stt.handler, "127.0.0.1", 0, max_size=None)
    yield f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/stt"
    server.close()
    await server.wait_closed()


async def test_partial_roi_final_da_hau_xu_ly(url):
    async with websockets.connect(url) as ws:
        pcm = np.zeros(160, dtype=np.int16).tobytes()
        await ws.send(pcm)
        await asyncio.sleep(0.25)
        await ws.send(pcm)
        await asyncio.sleep(0.25)
        await ws.send(json.dumps({"type": "eos"}))
        msgs = []
        try:
            while True:
                msgs.append(json.loads(await asyncio.wait_for(ws.recv(), timeout=2)))
        except (TimeoutError, websockets.exceptions.ConnectionClosed):
            pass
    assert "partial" in [m["type"] for m in msgs], msgs
    assert all(m.get("text") for m in msgs), msgs
    assert [m["text"] for m in msgs if m["type"] == "final"] == ["Xin chao anh"]


async def test_eos_thi_server_dong_ws(url):
    async with websockets.connect(url) as ws:
        await ws.send(json.dumps({"type": "eos"}))
        with pytest.raises(websockets.exceptions.ConnectionClosed):
            await asyncio.wait_for(ws.recv(), timeout=3)


async def test_sai_token_dong_1008(stt, url):
    stt.TOKEN = "secret"
    with pytest.raises(websockets.exceptions.ConnectionClosed) as exc:
        async with websockets.connect(url, additional_headers={"Authorization": "Bearer nope"}) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
    assert exc.value.rcvd.code == 1008
