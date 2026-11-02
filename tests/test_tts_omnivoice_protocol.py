"""Protocol-level tests for tts_omnivoice/tts_server.py using a stub model —
no GPU, no torch model download."""
from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

_SPEC = importlib.util.spec_from_file_location(
    "omnivoice_tts_server", str(Path(__file__).resolve().parent.parent / "tts_omnivoice" / "tts_server.py")
)
omnivoice_server = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(omnivoice_server)


class _FakeClonePrompt:
    """Stands in for omnivoice.models.omnivoice.VoiceClonePrompt — only the
    two things tts_server.py touches: construction inputs and .save(path)."""

    def __init__(self, ref_audio, ref_text):
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        self.saved_to: str | None = None

    def save(self, path):
        self.saved_to = path


class _StubModel:
    def generate(
        self, text, language, voice_clone_prompt, num_step, guidance_scale, pad_duration, fade_duration
    ):
        assert text and text[0]
        return [np.linspace(-0.2, 0.2, 48000, dtype=np.float32)]  # 2s @ 24kHz

    def create_voice_clone_prompt(self, ref_audio, ref_text):
        assert Path(ref_audio).is_file()  # _enroll_voice must write the decoded bytes to a real file
        assert ref_text  # required — no ASR auto-transcribe wired up
        return _FakeClonePrompt(ref_audio, ref_text)


class _FakeWebSocket:
    def __init__(self, inbound: list[str]):
        self._inbound = inbound
        self.sent: list[bytes | str] = []
        self.request = SimpleNamespace(headers={})

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._inbound:
            raise StopAsyncIteration
        return self._inbound.pop(0)

    async def send(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        pass


@pytest.fixture(autouse=True)
def _inject_stub_model(monkeypatch):
    monkeypatch.setattr(omnivoice_server, "MODEL", _StubModel())
    monkeypatch.setattr(omnivoice_server, "TOKEN", "")
    yield


@pytest.mark.asyncio
async def test_handler_sends_pcm_then_end():
    ws = _FakeWebSocket([json.dumps({"type": "synthesize", "text": "Xin chào 5 giờ"})])
    await omnivoice_server.handler(ws)
    assert any(isinstance(f, bytes) for f in ws.sent)
    assert json.loads(ws.sent[-1]) == {"type": "end"}


@pytest.mark.asyncio
async def test_chunking_splits_long_audio_into_multiple_frames():
    """2s of PCM16@24kHz = 96000 bytes; chunk size is SR*2=48000 bytes/chunk —
    expect exactly 2 binary frames plus the trailing {"type":"end"}."""
    ws = _FakeWebSocket([json.dumps({"type": "synthesize", "text": "câu dài"})])
    await omnivoice_server.handler(ws)
    binary_frames = [f for f in ws.sent if isinstance(f, bytes)]
    assert len(binary_frames) == 2
    assert sum(len(f) for f in binary_frames) == 96000


@pytest.mark.asyncio
async def test_unknown_voice_field_falls_back_to_default_speaker():
    ws = _FakeWebSocket([json.dumps({"type": "synthesize", "text": "xin chào", "voice": "someone-else"})])
    await omnivoice_server.handler(ws)
    assert json.loads(ws.sent[-1]) == {"type": "end"}  # didn't error out on an unknown/unenrolled voice


@pytest.mark.asyncio
async def test_empty_text_sends_end_immediately_no_audio():
    ws = _FakeWebSocket([json.dumps({"type": "synthesize", "text": ""})])
    await omnivoice_server.handler(ws)
    assert ws.sent == [json.dumps({"type": "end"})]


@pytest.mark.asyncio
async def test_enroll_voice_success_registers_and_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(omnivoice_server, "CUSTOM_VOICES_DIR", tmp_path)
    ref_audio_b64 = base64.b64encode(b"not-really-a-wav-but-stub-doesnt-care").decode()
    ws = _FakeWebSocket([json.dumps({
        "type": "enroll_voice", "voice_id": "khach_a", "ref_audio_b64": ref_audio_b64, "ref_text": "Xin chào",
    })])
    await omnivoice_server.handler(ws)
    assert json.loads(ws.sent[-1]) == {"type": "enrolled", "voice_id": "khach_a"}
    prompt = omnivoice_server._CUSTOM_VOICES["khach_a"]
    assert isinstance(prompt, _FakeClonePrompt)
    assert prompt.saved_to == str(tmp_path / "khach_a.pt")


@pytest.mark.asyncio
async def test_enroll_voice_synth_uses_the_cloned_prompt(monkeypatch, tmp_path):
    prompt = _FakeClonePrompt("dummy.wav", "Xin chào")
    monkeypatch.setitem(omnivoice_server._CUSTOM_VOICES, "khach_b", prompt)
    seen = {}
    real_generate = omnivoice_server.MODEL.generate

    def _spy_generate(*args, **kwargs):
        seen["voice_clone_prompt"] = kwargs.get("voice_clone_prompt")
        return real_generate(*args, **kwargs)

    monkeypatch.setattr(omnivoice_server.MODEL, "generate", _spy_generate)
    ws = _FakeWebSocket([json.dumps({"type": "synthesize", "text": "xin chào", "voice": "khach_b"})])
    await omnivoice_server.handler(ws)
    assert seen["voice_clone_prompt"] is prompt


@pytest.mark.asyncio
async def test_enroll_voice_missing_ref_text_returns_error():
    ref_audio_b64 = base64.b64encode(b"whatever").decode()
    req = {"type": "enroll_voice", "voice_id": "x", "ref_audio_b64": ref_audio_b64}
    ws = _FakeWebSocket([json.dumps(req)])
    await omnivoice_server.handler(ws)
    reply = json.loads(ws.sent[-1])
    assert reply["type"] == "error"


@pytest.mark.asyncio
async def test_enroll_voice_bad_base64_returns_error():
    ws = _FakeWebSocket([json.dumps({
        "type": "enroll_voice", "voice_id": "x", "ref_audio_b64": "not-base64!!", "ref_text": "hi",
    })])
    await omnivoice_server.handler(ws)
    reply = json.loads(ws.sent[-1])
    assert reply["type"] == "error"


@pytest.mark.asyncio
async def test_synth_error_still_sends_end_no_audio(monkeypatch):
    def _boom(**_):
        raise RuntimeError("cuda oom")

    monkeypatch.setattr(omnivoice_server.MODEL, "generate", _boom)
    ws = _FakeWebSocket([json.dumps({"type": "synthesize", "text": "xin chào"})])
    await omnivoice_server.handler(ws)
    assert ws.sent == [json.dumps({"type": "end"})]
