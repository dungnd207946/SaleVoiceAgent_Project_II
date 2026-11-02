# STT/TTS Standalone WebSocket Services — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tách `sherpa` STT và `vieneu` TTS thành hai service thường trú nói chuyện qua WebSocket, để model load đúng một lần (thay vì mỗi LiveKit job-process), tiết kiệm VRAM GPU và bỏ cold-call warmup.

**Architecture:** Hai WS server (`stt_server`, `tts_server`) bọc các singleton sẵn có (`sherpa._get_recognizer()`, `vieneu._load_tts()`) và *tái dùng* lớp session sẵn có (`SherpaSTT`, `AsyncVieNeuTTS`) cho mỗi kết nối. Hai backend client mới (`RemoteSTT`, `RemoteTTS`) mirror pattern `elevenlabs.py`, implement đúng các interface hiện hành (`STTBase` start/send/stop + on_partial/on_final; TTS `async stream(text)`). Agent worker chọn backend `remote` qua env → `prewarm_voice_models()` (đã gate theo tên backend) tự động không load model nặng. URL service cấu hình qua `.env` để deploy tách máy.

**Tech Stack:** Python 3.11+, `websockets>=13` (server dùng `websockets.asyncio.server.serve`; client dùng `websockets.connect` như elevenlabs.py), pydantic-settings, pytest + pytest-asyncio (`asyncio_mode=auto`), ruff (line-length 120).

## Global Constraints

- Python 3.11–3.13; ruff line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`.
- Pytest `asyncio_mode=auto` — async test functions cần KHÔNG decorator; chúng tự chạy.
- Unit test phải collect được **không cần** optional dep (`sherpa-onnx`, `vieneu`): heavy import phải **function-local**, và test inject fake qua monkeypatch — không import model thật.
- Audio format cố định: STT in = PCM int16, 16kHz, mono; TTS out = PCM int16, 24kHz, mono.
- WS quy ước: **binary frame = PCM thô**, **text frame = JSON control**. `websockets` phân biệt str vs bytes khi iterate `async for msg in ws`.
- Backend mới tên `"remote"` cho cả `STT_BACKEND` và `TTS_BACKEND`.
- Spec nguồn: `docs/superpowers/specs/2026-06-26-voice-stt-tts-service-design.md`.
- Nhánh hiện tại: `feat/seperate-service`. KHÔNG đụng `develop`. Commit cục bộ trên nhánh này.

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `src/noble_agent/config.py` | Thêm 7 field config service (URL/host/port/token) | 1 |
| `src/noble_agent/voice/service/__init__.py` | Package marker | 2 |
| `src/noble_agent/voice/service/protocol.py` | Hằng số message + helper encode/decode/auth (dùng chung 2 đầu) | 2 |
| `src/noble_agent/voice/stt/remote.py` | `RemoteSTT` — client STT, implements `STTBase` | 3 |
| `src/noble_agent/voice/tts/remote.py` | `RemoteTTS` — client TTS, implements `stream()`/`set_voice()`/`pause()` | 4 |
| `src/noble_agent/voice/service/stt_server.py` | WS server STT, reuse `SherpaSTT`; `main()` | 5 |
| `src/noble_agent/voice/service/tts_server.py` | WS server TTS, reuse `AsyncVieNeuTTS`; `main()` | 6 |
| `src/noble_agent/voice/fallback.py` | Cập nhật 2 chain để chèn `remote` (cloud trước local) | 7 |
| `src/noble_agent/server/base_session.py` | Đăng ký builder `remote` trong `_init_stt` | 7 |
| `src/noble_agent/voice/voice_agent.py` | Đăng ký builder `remote` trong `_create_tts`; gọi `pause()` hook trong `pause_tts` | 7 |
| `pyproject.toml` | 2 console script `noble-stt-service` / `noble-tts-service` | 8 |
| `docker-compose.deploy.yml`, `.env.example`, `CLAUDE.md` | Service compose + env mẫu + changelog | 9 |

**Lưu ý cancel/barge-in (quan trọng, áp dụng ở Task 4 & 6):** cancel được hiện thực bằng **đóng WS**, không cần message riêng. Khi barge-in, `RemoteTTS.pause()` đóng WS đang synth → `await ws.send(chunk)` phía server raise `ConnectionClosed` → handler thoát → nhả tài nguyên. Vì mỗi lần `stream()` chỉ tổng hợp **một clause** (sentence-buffer đã cắt) nên clause đang chạy trong executor của vieneu sẽ hoàn tất tự nhiên (vài trăm ms) — đúng như hành vi hiện tại (vieneu vốn không ngắt được giữa clause); cancel chỉ chặn các clause **kế tiếp**. Mỗi `stream()` mở WS mới → không có frame thừa từ lần trước lẫn sang lần sau.

---

### Task 1: Config fields cho service STT/TTS

**Files:**
- Modify: `src/noble_agent/config.py` (thêm vào `UnifiedSettings`, sau khối STT/TTS backend selection ~dòng 59)
- Test: `tests/unit/test_config_voice_service.py` (create)

**Interfaces:**
- Produces: `settings.stt_service_url: str`, `settings.tts_service_url: str`, `settings.stt_service_host: str`, `settings.stt_service_port: int`, `settings.tts_service_host: str`, `settings.tts_service_port: int`, `settings.voice_service_auth_token: str`. (Field không alias → env var = TÊN VIẾT HOA, ví dụ `STT_SERVICE_URL`.)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_voice_service.py
"""Defaults for the remote STT/TTS service config (Task 1)."""

from __future__ import annotations


def test_voice_service_defaults():
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings()
    assert s.stt_service_url == "ws://127.0.0.1:8770/stt"
    assert s.tts_service_url == "ws://127.0.0.1:8771/tts"
    assert s.stt_service_host == "0.0.0.0"
    assert s.stt_service_port == 8770
    assert s.tts_service_host == "0.0.0.0"
    assert s.tts_service_port == 8771
    assert s.voice_service_auth_token == ""


def test_voice_service_env_override(monkeypatch):
    monkeypatch.setenv("STT_SERVICE_URL", "ws://10.0.0.5:9000/stt")
    monkeypatch.setenv("TTS_SERVICE_PORT", "9999")
    monkeypatch.setenv("VOICE_SERVICE_AUTH_TOKEN", "secret123")
    from noble_agent.config import UnifiedSettings

    s = UnifiedSettings()
    assert s.stt_service_url == "ws://10.0.0.5:9000/stt"
    assert s.tts_service_port == 9999
    assert s.voice_service_auth_token == "secret123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config_voice_service.py -v`
Expected: FAIL — `AttributeError: 'UnifiedSettings' object has no attribute 'stt_service_url'`

- [ ] **Step 3: Add the config fields**

Trong `src/noble_agent/config.py`, ngay sau dòng `tts_backend: str = "vieneu"  # ...` (≈ dòng 59), thêm:

```python
    # ── Remote STT/TTS services (backend "remote") ─────────────────────────────
    # Client: agent worker đặt STT_BACKEND/TTS_BACKEND=remote và trỏ *_SERVICE_URL
    # tới service WS thường trú (cùng host hoặc máy GPU khác). URL đầy đủ, không
    # giả định localhost → tách máy chỉ là đổi .env.
    stt_service_url: str = "ws://127.0.0.1:8770/stt"
    tts_service_url: str = "ws://127.0.0.1:8771/tts"
    # Server bind (dùng bởi stt_server/tts_server main()). 0.0.0.0 cho máy khác kết nối.
    stt_service_host: str = "0.0.0.0"
    stt_service_port: int = 8770
    tts_service_host: str = "0.0.0.0"
    tts_service_port: int = 8771
    # Tùy chọn (rỗng = tắt xác thực). Khi đặt: client gửi header
    # `Authorization: Bearer <token>`; server từ chối kết nối thiếu/sai token.
    voice_service_auth_token: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config_voice_service.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/config.py tests/unit/test_config_voice_service.py
git commit -m "feat(config): add remote STT/TTS service URL/host/port/token settings"
```

---

### Task 2: Wire protocol module

**Files:**
- Create: `src/noble_agent/voice/service/__init__.py`
- Create: `src/noble_agent/voice/service/protocol.py`
- Test: `tests/unit/test_voice_service_protocol.py` (create)

**Interfaces:**
- Produces (tất cả thuần Python, không import nặng):
  - Hằng số: `PARTIAL="partial"`, `FINAL="final"`, `EOS="eos"`, `SYNTHESIZE="synthesize"`, `END="end"`, `AUTH_HEADER="Authorization"`.
  - `transcript_msg(kind: str, text: str) -> str`
  - `synthesize_msg(text: str, voice: str | None = None) -> str`
  - `control_msg(kind: str) -> str`
  - `parse(raw: str) -> dict`
  - `auth_headers(token: str) -> dict[str, str]`
  - `token_from_headers(headers) -> str`
  - `check_token(headers, expected: str) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_voice_service_protocol.py
"""Pure framing/auth helpers for the voice service WS protocol (Task 2)."""

from __future__ import annotations

from noble_agent.voice.service import protocol as p


def test_transcript_msg_roundtrip():
    raw = p.transcript_msg(p.FINAL, "xin chào")
    assert p.parse(raw) == {"type": "final", "text": "xin chào"}


def test_synthesize_msg_with_voice():
    assert p.parse(p.synthesize_msg("a", voice="luna")) == {
        "type": "synthesize",
        "text": "a",
        "voice": "luna",
    }


def test_synthesize_msg_without_voice_omits_key():
    assert p.parse(p.synthesize_msg("a")) == {"type": "synthesize", "text": "a"}


def test_control_msg():
    assert p.parse(p.control_msg(p.END)) == {"type": "end"}


def test_auth_headers_empty_token_is_empty_dict():
    assert p.auth_headers("") == {}


def test_auth_headers_sets_bearer():
    assert p.auth_headers("tok") == {"Authorization": "Bearer tok"}


def test_token_from_headers():
    assert p.token_from_headers({"Authorization": "Bearer tok"}) == "tok"
    assert p.token_from_headers({}) == ""
    assert p.token_from_headers({"Authorization": "Basic xyz"}) == ""


def test_check_token_disabled_when_expected_empty():
    assert p.check_token({}, "") is True


def test_check_token_match_and_mismatch():
    assert p.check_token({"Authorization": "Bearer tok"}, "tok") is True
    assert p.check_token({"Authorization": "Bearer nope"}, "tok") is False
    assert p.check_token({}, "tok") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_voice_service_protocol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.voice.service'`

- [ ] **Step 3: Create the package + protocol module**

```python
# src/noble_agent/voice/service/__init__.py
"""Standalone WebSocket services that host the heavy STT/TTS models once."""
```

```python
# src/noble_agent/voice/service/protocol.py
"""Wire protocol for the STT/TTS WebSocket services.

Quy ước: binary frame = PCM int16 thô; text frame = JSON control. Module thuần
Python (chỉ json) nên dùng được ở cả client lẫn server và test không cần dep nặng.
"""

from __future__ import annotations

import json

# Message types (giá trị khóa "type" trong JSON control frame)
PARTIAL = "partial"
FINAL = "final"
EOS = "eos"
SYNTHESIZE = "synthesize"
END = "end"

AUTH_HEADER = "Authorization"
_BEARER = "Bearer "


def transcript_msg(kind: str, text: str) -> str:
    """STT server → client: {"type": "partial"|"final", "text": ...}."""
    return json.dumps({"type": kind, "text": text})


def synthesize_msg(text: str, voice: str | None = None) -> str:
    """TTS client → server: {"type": "synthesize", "text": ..., "voice"?: ...}."""
    msg: dict = {"type": SYNTHESIZE, "text": text}
    if voice:
        msg["voice"] = voice
    return json.dumps(msg)


def control_msg(kind: str) -> str:
    """Control frame mang đúng một khóa "type" (eos / end)."""
    return json.dumps({"type": kind})


def parse(raw: str) -> dict:
    """Decode một text frame JSON thành dict."""
    return json.loads(raw)


def auth_headers(token: str) -> dict[str, str]:
    """Header client gửi kèm; rỗng khi token tắt."""
    return {AUTH_HEADER: f"{_BEARER}{token}"} if token else {}


def token_from_headers(headers) -> str:
    """Trích bearer token từ headers (mapping-like .get); "" nếu không có/không hợp lệ."""
    val = ""
    try:
        val = headers.get(AUTH_HEADER, "") or ""
    except AttributeError:
        val = ""
    return val[len(_BEARER) :] if val.startswith(_BEARER) else ""


def check_token(headers, expected: str) -> bool:
    """True nếu auth tắt (expected rỗng) hoặc token khớp."""
    if not expected:
        return True
    return token_from_headers(headers) == expected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_voice_service_protocol.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/voice/service/__init__.py src/noble_agent/voice/service/protocol.py tests/unit/test_voice_service_protocol.py
git commit -m "feat(voice): add WS protocol helpers for STT/TTS services"
```

---

### Task 3: `RemoteSTT` client backend

**Files:**
- Create: `src/noble_agent/voice/stt/remote.py`
- Test: `tests/unit/test_remote_stt.py` (create)

**Interfaces:**
- Consumes: `protocol` (Task 2); `settings.stt_service_url`, `settings.voice_service_auth_token` (Task 1).
- Produces: `class RemoteSTT` implements `STTBase` — `__init__(on_partial=None, on_final=None)`, async `start()`, async `send(pcm_bytes: bytes)`, async `stop()`. Nhận text frame `partial`/`final` từ server → gọi callback.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_remote_stt.py
"""RemoteSTT client — demux server text frames to callbacks (Task 3).

Mock websockets.connect; không mở socket thật.
"""

from __future__ import annotations

import asyncio

from noble_agent.voice.service import protocol as p


class FakeServerWS:
    """Giả websocket: phát sẵn frame cho client recv-loop, ghi lại frame client gửi."""

    def __init__(self, incoming):
        self._incoming = list(incoming)
        self.sent: list = []
        self.closed = False

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_remote_stt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.voice.stt.remote'`

- [ ] **Step 3: Implement RemoteSTT**

```python
# src/noble_agent/voice/stt/remote.py
"""Streaming STT client cho service `stt_server` qua WebSocket.

Drop-in của SherpaSTT/SonioxSTT (interface STTBase):
    stt = RemoteSTT(on_partial=..., on_final=...)
    await stt.start(); await stt.send(pcm); await stt.stop()

Gửi PCM int16 16kHz mono dưới dạng binary frame; nhận text frame
{"type":"partial"|"final","text":...} và gọi callback tương ứng. Mirror
voice/stt/elevenlabs.py.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import websockets
from websockets.protocol import State as WsState

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p

logger = logging.getLogger(__name__)


class RemoteSTT:
    """Một phiên STT nối tới service sherpa từ xa."""

    def __init__(
        self,
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
    ):
        self.on_partial = on_partial
        self.on_final = on_final
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._recv_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._ws = await websockets.connect(
            settings.stt_service_url,
            additional_headers=p.auth_headers(settings.voice_service_auth_token),
            max_size=10 * 1024 * 1024,
            ping_interval=20,
        )
        self._recv_task = asyncio.create_task(self._receive_loop())
        logger.info("RemoteSTT connected: %s", settings.stt_service_url)

    async def send(self, pcm_bytes: bytes) -> None:
        if self._ws and self._ws.state == WsState.OPEN:
            try:
                await self._ws.send(pcm_bytes)  # binary frame
            except Exception:
                pass

    async def stop(self) -> None:
        if self._ws and self._ws.state == WsState.OPEN:
            try:
                await self._ws.send(p.control_msg(p.EOS))
                await self._ws.close()
            except Exception:
                pass
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        self._ws = None
        self._recv_task = None
        logger.info("RemoteSTT stopped.")

    async def _receive_loop(self) -> None:
        try:
            async for raw in self._ws:
                if isinstance(raw, bytes):
                    continue  # STT server chỉ gửi text
                msg = p.parse(raw)
                kind = msg.get("type")
                text = msg.get("text", "")
                if not text:
                    continue
                if kind == p.PARTIAL and self.on_partial:
                    await _safe_call(self.on_partial, text)
                elif kind == p.FINAL and self.on_final:
                    await _safe_call(self.on_final, text)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("RemoteSTT receive error: %s", exc)


async def _safe_call(fn: Callable, text: str) -> None:
    try:
        result = fn(text)
        if asyncio.iscoroutine(result):
            await result
    except Exception as exc:
        logger.error("STT callback error: %s", exc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_remote_stt.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/voice/stt/remote.py tests/unit/test_remote_stt.py
git commit -m "feat(stt): add RemoteSTT WebSocket client backend"
```

---

### Task 4: `RemoteTTS` client backend

**Files:**
- Create: `src/noble_agent/voice/tts/remote.py`
- Test: `tests/unit/test_remote_tts.py` (create)

**Interfaces:**
- Consumes: `protocol` (Task 2); `settings.tts_service_url`, `settings.voice_service_auth_token` (Task 1).
- Produces: `class RemoteTTS` — `__init__()`, `set_voice(voice_id: str)`, async generator `stream(text: str) -> AsyncIterator[bytes]` (yield PCM int16 24kHz), async `pause()` (đóng WS đang synth để hủy). Mở **WS mới mỗi lần `stream()`**; lưu `self._active_ws` để `pause()` đóng.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_remote_tts.py
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
    # frame thứ 2 chờ mãi → mô phỏng stream đang chạy khi bị pause
    started = asyncio.Event()

    class SlowWS(FakeServerWS):
        async def __anext__(self):
            started.set()
            await asyncio.sleep(10)  # treo cho tới khi bị cancel/close

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
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_remote_tts_set_voice():
    from noble_agent.voice.tts.remote import RemoteTTS

    tts = RemoteTTS()
    tts.set_voice("luna")
    assert tts._voice_id == "luna"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_remote_tts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.voice.tts.remote'`

- [ ] **Step 3: Implement RemoteTTS**

```python
# src/noble_agent/voice/tts/remote.py
"""Streaming TTS client cho service `tts_server` qua WebSocket.

Drop-in của AsyncVieNeuTTS/AsyncElevenLabsTTS:
    tts = RemoteTTS()
    async for chunk in tts.stream("Xin chào"):
        send_audio(chunk)   # PCM int16 bytes

Mỗi lần stream() mở một WS mới (như elevenlabs), gửi 1 yêu cầu synthesize, nhận
binary PCM chunk tới khi gặp {"type":"end"} rồi đóng. Barge-in: pause() đóng WS
đang synth → server thấy ConnectionClosed và dừng (xem ghi chú cancel trong plan).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import websockets
from websockets.protocol import State as WsState

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p

logger = logging.getLogger("remote_tts")


class RemoteTTS:
    """Client TTS nối tới service vieneu từ xa (một synth/lần)."""

    def __init__(self):
        self._voice_id: str = settings.vieneu_voice_id or ""
        self._active_ws: websockets.WebSocketClientProtocol | None = None

    def set_voice(self, voice_id: str) -> None:
        self._voice_id = voice_id
        logger.info("RemoteTTS voice set to: %s", voice_id)

    async def pause(self) -> None:
        """Barge-in: đóng WS đang synth để hủy lần tổng hợp hiện tại."""
        ws = self._active_ws
        if ws is not None and ws.state == WsState.OPEN:
            try:
                await ws.close()
            except Exception:
                pass

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        ws = await websockets.connect(
            settings.tts_service_url,
            additional_headers=p.auth_headers(settings.voice_service_auth_token),
            max_size=10 * 1024 * 1024,
            ping_interval=20,
        )
        self._active_ws = ws
        try:
            await ws.send(p.synthesize_msg(text, voice=self._voice_id or None))
            async for raw in ws:
                if isinstance(raw, bytes):
                    if raw:
                        yield raw
                else:
                    if p.parse(raw).get("type") == p.END:
                        break
        except Exception as exc:
            logger.error("RemoteTTS stream error: %s", exc)
        finally:
            self._active_ws = None
            if ws.state == WsState.OPEN:
                try:
                    await ws.close()
                except Exception:
                    pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_remote_tts.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/voice/tts/remote.py tests/unit/test_remote_tts.py
git commit -m "feat(tts): add RemoteTTS WebSocket client backend"
```

---

### Task 5: STT WebSocket server

**Files:**
- Create: `src/noble_agent/voice/service/stt_server.py`
- Test: `tests/unit/test_stt_server.py` (create)

**Interfaces:**
- Consumes: `protocol` (Task 2); `SherpaSTT` (`voice/stt/sherpa.py`); `settings.stt_service_host/port`, `settings.voice_service_auth_token`.
- Produces: async `handler(websocket)` (đăng ký SherpaSTT per-connection, forward binary→`send`, text `eos`→stop), `main()` (warm `_get_recognizer()` rồi `serve`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stt_server.py
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
    monkeypatch.setattr("noble_agent.voice.service.stt_server.SherpaSTT", FakeSherpaSTT)
    monkeypatch.setattr(
        "noble_agent.voice.service.stt_server.settings.voice_service_auth_token", "", raising=False
    )
    from noble_agent.voice.service import stt_server

    ws = FakeWS([b"\x00\x01", p.control_msg(p.EOS)])
    await stt_server.handler(ws)

    texts = [p.parse(s) for s in ws.sent if isinstance(s, str)]
    assert {"type": "partial", "text": "xin"} in texts
    assert {"type": "final", "text": "xin chào"} in texts


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_stt_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.voice.service.stt_server'`

- [ ] **Step 3: Implement the STT server**

```python
# src/noble_agent/voice/service/stt_server.py
"""WebSocket server thường trú cho STT (sherpa).

Load recognizer singleton một lần (warmup), rồi mỗi kết nối tạo một SherpaSTT
(per-session OnlineStream, dùng chung recognizer). Forward binary PCM → SherpaSTT;
callback on_partial/on_final → text frame về client. Đóng/eos → stop().

Chạy: `noble-stt-service` hoặc `python -m noble_agent.voice.service.stt_server`.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p
from noble_agent.voice.stt.sherpa import SherpaSTT

logger = logging.getLogger("stt_server")


async def handler(websocket) -> None:
    """Một kết nối STT. Tạo SherpaSTT riêng; recognizer singleton dùng chung."""
    if not p.check_token(websocket.request.headers, settings.voice_service_auth_token):
        logger.warning("STT connection rejected: bad/missing auth token")
        await websocket.close(1008, "unauthorized")
        return

    async def on_partial(text: str) -> None:
        await websocket.send(p.transcript_msg(p.PARTIAL, text))

    async def on_final(text: str) -> None:
        await websocket.send(p.transcript_msg(p.FINAL, text))

    stt = SherpaSTT(on_partial=on_partial, on_final=on_final)
    await stt.start()
    logger.info("STT session started for %s", getattr(websocket.request, "path", "?"))
    try:
        async for msg in websocket:
            if isinstance(msg, bytes):
                await stt.send(msg)
            else:
                if p.parse(msg).get("type") == p.EOS:
                    break
    except Exception as exc:  # noqa: BLE001 — kết nối rớt là bình thường
        logger.info("STT session ended: %s", exc)
    finally:
        await stt.stop()


async def _run() -> None:
    from websockets.asyncio.server import serve

    from noble_agent.voice.stt import sherpa as sherpa_mod

    logger.info("STT service: warming recognizer ...")
    sherpa_mod._get_recognizer()  # load model một lần
    logger.info("STT service: recognizer ready")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - một số nền tảng
            pass

    async with serve(handler, settings.stt_service_host, settings.stt_service_port, max_size=10 * 1024 * 1024):
        logger.info("STT service listening on %s:%d", settings.stt_service_host, settings.stt_service_port)
        await stop.wait()
    logger.info("STT service stopped.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_stt_server.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/voice/service/stt_server.py tests/unit/test_stt_server.py
git commit -m "feat(voice): add standalone STT WebSocket server"
```

---

### Task 6: TTS WebSocket server

**Files:**
- Create: `src/noble_agent/voice/service/tts_server.py`
- Test: `tests/unit/test_tts_server.py` (create)

**Interfaces:**
- Consumes: `protocol` (Task 2); `AsyncVieNeuTTS` (`voice/tts/vieneu.py`); `settings.tts_service_host/port`, `settings.voice_service_auth_token`.
- Produces: async `handler(websocket)` (nhận `synthesize` → stream binary PCM → `end`), `main()` (warm `_load_tts()` rồi `serve`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_tts_server.py
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

    async def stream(self, text):
        yield b"AAAA"
        yield b"BBBB"


async def test_tts_handler_streams_pcm_then_end(monkeypatch):
    monkeypatch.setattr("noble_agent.voice.service.tts_server.AsyncVieNeuTTS", FakeTTS)
    monkeypatch.setattr(
        "noble_agent.voice.service.tts_server.settings.voice_service_auth_token", "", raising=False
    )
    from noble_agent.voice.service import tts_server

    ws = FakeWS([p.synthesize_msg("xin chào", voice="luna")])
    await tts_server.handler(ws)

    binary = [s for s in ws.sent if isinstance(s, bytes)]
    text = [p.parse(s) for s in ws.sent if isinstance(s, str)]
    assert binary == [b"AAAA", b"BBBB"]
    assert {"type": "end"} in text


async def test_tts_handler_rejects_bad_token(monkeypatch):
    monkeypatch.setattr("noble_agent.voice.service.tts_server.AsyncVieNeuTTS", FakeTTS)
    monkeypatch.setattr(
        "noble_agent.voice.service.tts_server.settings.voice_service_auth_token", "secret", raising=False
    )
    from noble_agent.voice.service import tts_server

    ws = FakeWS([p.synthesize_msg("hi")], headers={})
    await tts_server.handler(ws)
    assert ws.closed_code == 1008
    assert ws.sent == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_tts_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.voice.service.tts_server'`

- [ ] **Step 3: Implement the TTS server**

```python
# src/noble_agent/voice/service/tts_server.py
"""WebSocket server thường trú cho TTS (vieneu).

Load model singleton một lần (warmup) qua AsyncVieNeuTTS/_load_tts. Mỗi kết nối
nhận các yêu cầu {"type":"synthesize","text":...,"voice"?:...}; stream binary PCM
int16 24kHz từng chunk rồi gửi {"type":"end"}. `_inference_lock` toàn cục trong
vieneu.py tuần tự hóa GPU giữa mọi kết nối (đánh đổi đã chọn: 1 model, hàng đợi).

Client đóng WS giữa chừng (barge-in) → ws.send raise ConnectionClosed → handler
thoát. Vì mỗi synthesize chỉ là một clause nên đủ ngắn.

Chạy: `noble-tts-service` hoặc `python -m noble_agent.voice.service.tts_server`.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from noble_agent.config import settings
from noble_agent.voice.service import protocol as p
from noble_agent.voice.tts.vieneu import AsyncVieNeuTTS

logger = logging.getLogger("tts_server")


async def handler(websocket) -> None:
    """Một kết nối TTS; phục vụ nhiều yêu cầu synthesize tuần tự."""
    if not p.check_token(websocket.request.headers, settings.voice_service_auth_token):
        logger.warning("TTS connection rejected: bad/missing auth token")
        await websocket.close(1008, "unauthorized")
        return

    tts = AsyncVieNeuTTS()  # __init__ dùng singleton _load_tts() (đã warm)
    try:
        async for msg in websocket:
            if isinstance(msg, bytes):
                continue  # TTS client chỉ gửi text control
            data = p.parse(msg)
            if data.get("type") != p.SYNTHESIZE:
                continue
            voice = data.get("voice")
            if voice:
                tts.set_voice(voice)
            text = data.get("text", "")
            if not text:
                await websocket.send(p.control_msg(p.END))
                continue
            async for chunk in tts.stream(text):
                if chunk:
                    await websocket.send(chunk)  # binary PCM
            await websocket.send(p.control_msg(p.END))
    except Exception as exc:  # noqa: BLE001 — kết nối rớt/barge-in là bình thường
        logger.info("TTS session ended: %s", exc)


async def _run() -> None:
    from websockets.asyncio.server import serve

    from noble_agent.voice.tts import vieneu as vieneu_mod

    logger.info("TTS service: loading model ...")
    vieneu_mod._load_tts()  # load model một lần
    logger.info("TTS service: model ready")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover
            pass

    async with serve(handler, settings.tts_service_host, settings.tts_service_port, max_size=10 * 1024 * 1024):
        logger.info("TTS service listening on %s:%d", settings.tts_service_host, settings.tts_service_port)
        await stop.wait()
    logger.info("TTS service stopped.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_tts_server.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/voice/service/tts_server.py tests/unit/test_tts_server.py
git commit -m "feat(voice): add standalone TTS WebSocket server"
```

---

### Task 7: Wire `remote` backend + update fallback chains + pause hook

**Files:**
- Modify: `src/noble_agent/voice/fallback.py:24-25` (hai hằng số chain)
- Modify: `src/noble_agent/server/base_session.py` (thêm `_build_remote` + map STT, ~dòng 195-219)
- Modify: `src/noble_agent/voice/voice_agent.py` (thêm builder remote vào `_create_tts` ~dòng 178; gọi pause hook trong `pause_tts` ~dòng 213)
- Modify: `tests/unit/test_voice_fallback.py` (cập nhật 4 assertion chain cũ + thêm remote)
- Test: thêm trong `tests/unit/test_voice_fallback.py`

**Interfaces:**
- Consumes: `RemoteSTT` (Task 3), `RemoteTTS` (Task 4).
- Produces: `STT_FALLBACK_CHAIN == ["remote", "soniox", "sherpa"]`, `TTS_FALLBACK_CHAIN == ["remote", "elevenlabs", "vieneu"]`; builder `"remote"` trong cả hai map; `VoiceAgent.pause_tts` gọi `await self._tts.pause()` nếu có.

- [ ] **Step 1: Update the failing fallback tests first (RED)**

Trong `tests/unit/test_voice_fallback.py`, sửa 4 assertion hiện có cho khớp chain mới và thêm test remote:

```python
def test_resolve_order_primary_head_stt() -> None:
    assert resolve_order("sherpa", STT_FALLBACK_CHAIN) == ["sherpa", "remote", "soniox"]


def test_resolve_order_configured_stays_head() -> None:
    assert resolve_order("soniox", STT_FALLBACK_CHAIN) == ["soniox", "remote", "sherpa"]


def test_resolve_order_tts_chain() -> None:
    assert resolve_order("vieneu", TTS_FALLBACK_CHAIN) == ["vieneu", "remote", "elevenlabs"]


def test_resolve_order_tts_configured_stays_head() -> None:
    assert resolve_order("elevenlabs", TTS_FALLBACK_CHAIN) == ["elevenlabs", "remote", "vieneu"]


def test_resolve_order_remote_head_prefers_cloud_then_local_stt() -> None:
    assert resolve_order("remote", STT_FALLBACK_CHAIN) == ["remote", "soniox", "sherpa"]


def test_resolve_order_remote_head_prefers_cloud_then_local_tts() -> None:
    assert resolve_order("remote", TTS_FALLBACK_CHAIN) == ["remote", "elevenlabs", "vieneu"]
```

- [ ] **Step 2: Run to verify the chain tests fail**

Run: `pytest tests/unit/test_voice_fallback.py -v`
Expected: FAIL trên các assertion chain (giá trị cũ `["sherpa","soniox"]` ...).

- [ ] **Step 3: Update the chains**

Trong `src/noble_agent/voice/fallback.py`, thay 2 dòng hằng số (≈ 24-25):

```python
# Fixed code-constant chains. Service-client backend `remote` đứng đầu; khi nó
# là primary, fallback ưu tiên CLOUD (soniox/elevenlabs) trước rồi mới tới model
# LOCAL (sherpa/vieneu) như last-resort — rớt về local TRONG worker sẽ tái hiện
# đúng vấn đề VRAM/warmup mà service sinh ra để giải. resolve_order giữ nguyên
# ngữ nghĩa: primary cấu hình luôn là head.
STT_FALLBACK_CHAIN: list[str] = ["remote", "soniox", "sherpa"]
TTS_FALLBACK_CHAIN: list[str] = ["remote", "elevenlabs", "vieneu"]
```

- [ ] **Step 4: Run fallback tests to verify pass**

Run: `pytest tests/unit/test_voice_fallback.py -v`
Expected: PASS (toàn bộ, gồm 2 test remote mới)

- [ ] **Step 5: Register the STT `remote` builder**

Trong `src/noble_agent/server/base_session.py`, thêm builder vào `_init_stt` (cạnh `_build_sherpa`, trước `base_builders`):

```python
            def _build_remote():
                from noble_agent.voice.stt.remote import RemoteSTT

                return RemoteSTT(on_partial=self._on_partial, on_final=self._on_final)
```

và thêm vào dict `base_builders`:

```python
            base_builders = {
                "soniox": _build_soniox,
                "qwen3asr": _build_qwen3asr,
                "elevenlabs": _build_elevenlabs,
                "sherpa": _build_sherpa,
                "remote": _build_remote,
            }
```

- [ ] **Step 6: Register the TTS `remote` builder + pause hook**

Trong `src/noble_agent/voice/voice_agent.py::_create_tts`, thêm builder và đưa vào map:

```python
        def _build_remote():
            from noble_agent.voice.tts.remote import RemoteTTS

            return RemoteTTS()

        builders = {"vieneu": _build_vieneu, "elevenlabs": _build_eleven, "remote": _build_remote}
```

và sửa `pause_tts` để hủy synth từ xa khi barge-in (sau `self._interrupted = True`):

```python
    async def pause_tts(self) -> None:
        """... (giữ nguyên docstring) ..."""
        self._interrupted = True
        pause = getattr(self._tts, "pause", None)
        if pause is not None:
            try:
                await pause()
            except Exception as exc:  # noqa: BLE001 — pause là best-effort
                logger.warning("pause_tts hook failed: %s", exc)
```

- [ ] **Step 7: Add a wiring smoke test**

Thêm vào cuối `tests/unit/test_voice_fallback.py`:

```python
async def test_create_tts_builds_remote_backend(monkeypatch):
    """_create_tts với TTS_BACKEND=remote trả về RemoteTTS (không load vieneu)."""
    from noble_agent.config import settings
    from noble_agent.voice.tts.remote import RemoteTTS
    from noble_agent.voice.voice_agent import VoiceAgent

    monkeypatch.setattr(settings, "tts_backend", "remote")
    tts = VoiceAgent._create_tts()
    assert isinstance(tts, RemoteTTS)
```

- [ ] **Step 8: Run the wiring + fallback tests**

Run: `pytest tests/unit/test_voice_fallback.py tests/unit/test_tts_factory.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/noble_agent/voice/fallback.py src/noble_agent/server/base_session.py src/noble_agent/voice/voice_agent.py tests/unit/test_voice_fallback.py
git commit -m "feat(voice): wire remote STT/TTS backends + cloud-first fallback + pause hook"
```

---

### Task 8: Console script entrypoints

**Files:**
- Modify: `pyproject.toml` (`[project.scripts]`, ≈ dòng sau `noble-agent = ...`)
- Test: `tests/unit/test_voice_service_entrypoints.py` (create)

**Interfaces:**
- Consumes: `stt_server.main` (Task 5), `tts_server.main` (Task 6).
- Produces: console script `noble-stt-service`, `noble-tts-service`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_voice_service_entrypoints.py
"""main() của 2 service tồn tại và callable; module __main__ chạy được (Task 8)."""

from __future__ import annotations


def test_stt_server_main_callable():
    from noble_agent.voice.service.stt_server import main

    assert callable(main)


def test_tts_server_main_callable():
    from noble_agent.voice.service.tts_server import main

    assert callable(main)


def test_pyproject_declares_service_scripts():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    data = tomllib.loads((root / "pyproject.toml").read_text())
    scripts = data["project"]["scripts"]
    assert scripts["noble-stt-service"] == "noble_agent.voice.service.stt_server:main"
    assert scripts["noble-tts-service"] == "noble_agent.voice.service.tts_server:main"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_voice_service_entrypoints.py -v`
Expected: FAIL — `KeyError: 'noble-stt-service'`

- [ ] **Step 3: Add the console scripts**

Trong `pyproject.toml`, sửa khối `[project.scripts]`:

```toml
[project.scripts]
noble-agent = "noble_agent.__main__:main"
noble-stt-service = "noble_agent.voice.service.stt_server:main"
noble-tts-service = "noble_agent.voice.service.tts_server:main"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_voice_service_entrypoints.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/unit/test_voice_service_entrypoints.py
git commit -m "build: add noble-stt-service / noble-tts-service console scripts"
```

---

### Task 9: Deploy compose + .env.example + CLAUDE.md

**Files:**
- Modify: `docker-compose.deploy.yml` (thêm 2 service; đặt `agent`/`agent-lk` sang remote, bỏ GPU reservation của chúng)
- Modify: `.env.example` (thêm khối config service)
- Modify: `CLAUDE.md` (cập nhật mục backends + thêm dòng Change Log)

**Interfaces:** không có code interface — đây là config/deploy/docs. Không có test tự động; verify bằng `docker compose config` (lint compose) và đọc lại.

- [ ] **Step 1: Add the two services to `docker-compose.deploy.yml`**

Thêm vào cuối khối `services:` (sau `agent-lk`):

```yaml
  # STT service (sherpa, CPU) — model thường trú, load một lần. agent/agent-lk
  # nối qua STT_SERVICE_URL=ws://127.0.0.1:8770/stt (network_mode: host).
  santa-stt:
    image: 418295696099.dkr.ecr.ap-northeast-2.amazonaws.com/aidc/santa-hotline-agent:${IMAGE_TAG:-dev-latest}
    env_file: .env
    command: ["noble-stt-service"]
    network_mode: host
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
      - ./hf-cache:/root/.cache/huggingface
    restart: unless-stopped

  # TTS service (vieneu/santa-tts, GPU) — model GPU thường trú, load MỘT LẦN cho
  # toàn hệ thống. Đây là service DUY NHẤT reserve GPU; agent/agent-lk dùng remote.
  santa-tts:
    image: 418295696099.dkr.ecr.ap-northeast-2.amazonaws.com/aidc/santa-hotline-agent:${IMAGE_TAG:-dev-latest}
    env_file: .env
    command: ["noble-tts-service"]
    network_mode: host
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
      - ./hf-cache:/root/.cache/huggingface
    restart: unless-stopped
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

- [ ] **Step 2: Point `agent` and `agent-lk` at the remote backends, drop their GPU reservation**

Trong service `agent`, thêm vào `environment:`:

```yaml
      - STT_BACKEND=remote
      - TTS_BACKEND=remote
```

và **xóa** khối `deploy: resources: reservations: devices` của `agent` (GPU giờ chỉ ở `santa-tts`). Làm tương tự cho `agent-lk`: thêm 2 dòng env remote và xóa khối `deploy:` GPU của nó. Thêm `santa-stt`, `santa-tts` vào `depends_on` của `agent-lk`:

```yaml
    depends_on:
      - agent
      - livekit
      - santa-stt
      - santa-tts
```

> Ghi chú: image cho `santa-stt`/`santa-tts` cần cài extra local (`.[stt-sherpa,tts-vieneu]`); image cho `agent`/`agent-lk` thì KHÔNG cần (remote) — nếu cùng một image, các builder local vẫn tồn tại nhưng không bao giờ được gọi vì backend=remote. Nếu sau này tách Dockerfile, bỏ extra local khỏi image agent để chốt chặn cứng (xem spec §6.2).

- [ ] **Step 3: Validate the compose file**

Run: `docker compose -f docker-compose.deploy.yml config >/dev/null && echo OK`
Expected: in ra `OK` (cú pháp compose hợp lệ). Nếu môi trường không có docker, bỏ qua và đọc lại file bằng mắt.

- [ ] **Step 4: Add the env block to `.env.example`**

Thêm khối (cạnh các biến STT/TTS hiện có):

```bash
# ── Remote STT/TTS services (backend "remote") ────────────────────────────────
# Agent worker: đặt remote để KHÔNG load model nặng trong process worker.
# STT_BACKEND=remote
# TTS_BACKEND=remote
# URL đầy đủ client kết nối (đổi sang ws://<gpu-host>:<port>/... khi tách máy GPU,
# hoặc wss://... khi đi qua Internet sau reverse-proxy TLS).
STT_SERVICE_URL=ws://127.0.0.1:8770/stt
TTS_SERVICE_URL=ws://127.0.0.1:8771/tts
# Server bind (dùng bởi noble-stt-service / noble-tts-service).
STT_SERVICE_HOST=0.0.0.0
STT_SERVICE_PORT=8770
TTS_SERVICE_HOST=0.0.0.0
TTS_SERVICE_PORT=8771
# Tùy chọn: bearer token chống truy cập trái phép khi service mở ra mạng. Rỗng = tắt.
VOICE_SERVICE_AUTH_TOKEN=
```

- [ ] **Step 5: Update `CLAUDE.md`**

Trong mục **Pluggable backends → STT**: thêm `remote` vào danh sách `STT_BACKEND` và một câu: "`remote` — client WebSocket tới service `noble-stt-service` thường trú (`voice/stt/remote.py` → `voice/service/stt_server.py`); load model một lần ngoài worker." Tương tự cho **TTS**: thêm `remote` (`voice/tts/remote.py` → `voice/service/tts_server.py`). Cập nhật fallback-chain wording: STT `remote → soniox → sherpa`, TTS `remote → elevenlabs → vieneu` (cloud trước, local last-resort).

Thêm một dòng vào bảng **Change Log** (đầu bảng):

```markdown
| 2026-06-26 | **Tách STT/TTS thành service WebSocket thường trú.** Backend mới `remote` (`voice/stt/remote.py`, `voice/tts/remote.py`) là client WS mirror elevenlabs; server `voice/service/{stt_server,tts_server}.py` bọc singleton `sherpa._get_recognizer()` / `vieneu._load_tts()` và reuse `SherpaSTT`/`AsyncVieNeuTTS` per-connection. Protocol `voice/service/protocol.py` (binary=PCM, text=JSON). Config `STT_SERVICE_URL`/`TTS_SERVICE_URL`/host/port + `VOICE_SERVICE_AUTH_TOKEN`. Fallback chains đổi: STT `remote→soniox→sherpa`, TTS `remote→elevenlabs→vieneu` (cloud trước local-in-worker). Console scripts `noble-stt-service`/`noble-tts-service`; compose thêm `santa-stt`/`santa-tts` (chỉ `santa-tts` giữ GPU). `VoiceAgent.pause_tts` gọi `tts.pause()` (đóng WS) để barge-in hủy synth từ xa. Worker chạy `*_BACKEND=remote` → `prewarm_voice_models()` (đã gate theo tên) tự bỏ qua load model nặng. Branch `feat/seperate-service`. | Mô hình process-pool của LiveKit khiến mỗi job-process load lại model → N bản vieneu trên VRAM + cold-call warmup. Tách service để model GPU load đúng một lần, dùng chung; URL `.env`-driven để deploy máy GPU riêng. |
```

- [ ] **Step 6: Commit**

```bash
git add docker-compose.deploy.yml .env.example CLAUDE.md
git commit -m "deploy: add santa-stt/santa-tts services + remote backend env + docs"
```

---

### Task 10: Full-suite verification

**Files:** none (verification gate).

- [ ] **Step 1: Run the full unit suite + lint**

Run:
```bash
make test-unit
make lint
```
Expected: tất cả PASS; ruff sạch trên file mới. Nếu ruff than về import-order/line-length, chạy `make format` rồi `make lint` lại và commit `style: ruff format`.

- [ ] **Step 2: Manual smoke (tùy môi trường có GPU/model)**

Theo `src/noble_agent/SMOKE.md` cho phần turn-loop/transport. Tối thiểu, nếu có model local:
```bash
# Terminal 1
noble-tts-service
# Terminal 2
noble-stt-service
# Terminal 3 — agent worker dùng remote
STT_BACKEND=remote TTS_BACKEND=remote scripts/run.sh --no-reload
```
Gọi thử qua `/chat` (text, kiểm tra TTS service nhận synth) và một cuộc voice; xác nhận: service chỉ load model một lần (log "model ready" một lần), agent worker KHÔNG log "prewarm: loading TTS (vieneu)".

- [ ] **Step 3: Latency check (skill latency-discipline)**

Run: `make bench` (hoặc `python scripts/benchmark_latency.py`) trước/sau khi bật remote nếu môi trường cho phép; xác nhận TTFA không hồi quy đáng kể (loopback WS thêm low-ms). Ghi lại con số vào PR description.

- [ ] **Step 4: Final commit (nếu có thay đổi format)**

```bash
git add -A && git commit -m "style: ruff format for voice service modules" || echo "nothing to format"
```

---

## Self-Review

**1. Spec coverage:**
- §3 transport WebSocket → Task 3/4/5/6 dùng `websockets`. ✓
- §4.1 cấu trúc file → Task 2/3/4/5/6 tạo đúng các file. ✓
- §4.3 worker tự bỏ qua load → `prewarm_voice_models()` đã gate; xác nhận ở Task 10 smoke. ✓ (không sửa prewarm.py — đúng spec)
- §5 protocol (binary=PCM, text=JSON, partial/final, synthesize/end) → Task 2 helpers + Task 3-6 dùng. ✓
- §5.2 cancel/barge-in → hiện thực bằng WS-close (Task 4 `pause()` + Task 7 hook); ghi chú giải thích lệch so với "message cancel" của spec nhưng giữ đúng intent (nhả tài nguyên). ✓
- §6.1 đăng ký builder remote → Task 7. ✓
- §6.2 fallback cloud-first → Task 7 chains + tests. ✓
- §7 vòng đời/auth → Task 5/6 warm + auth + signal handler; Task 1 token. ✓
- §8 config .env → Task 1 + Task 9 `.env.example`. ✓
- §9 deploy console scripts + compose → Task 8 + Task 9. ✓
- §10 testing/latency → mỗi task có test; Task 10 latency. ✓

**2. Placeholder scan:** Không có TBD/TODO/"handle edge cases"; mọi step code đều đầy đủ. ✓

**3. Type consistency:**
- Protocol hằng số (`PARTIAL/FINAL/EOS/SYNTHESIZE/END`) + hàm (`transcript_msg/synthesize_msg/control_msg/parse/auth_headers/token_from_headers/check_token`) định nghĩa ở Task 2, dùng nhất quán ở Task 3-6. ✓
- `RemoteSTT(on_partial, on_final)` (Task 3) khớp cách `_build_remote` gọi ở Task 7. ✓
- `RemoteTTS()` + `set_voice` + `stream` + `pause` (Task 4) khớp builder + `pause_tts` hook (Task 7). ✓
- `handler`/`main` (Task 5/6) khớp console script string ở Task 8. ✓
- Chain values (Task 7) khớp giữa code và test. ✓

## Notes / Risks

- **websockets API:** server dùng `websockets.asyncio.server.serve` (ổn định từ websockets 13; pyproject pin `>=13.0`) với handler `async def handler(websocket)` và `websocket.request.headers`/`.path`. Client giữ `websockets.connect(..., additional_headers=...)` y như elevenlabs.py. Nếu phiên bản cài đặt khác biệt API, điều chỉnh trong Task 5/6 (chỉ ảnh hưởng 2 file server).
- **vieneu không ngắt giữa clause:** WS-close hủy được các clause *kế tiếp*, clause đang chạy hoàn tất tự nhiên (đúng hành vi hiện tại). Không phải hồi quy.
- **Concurrency TTS serial:** `_inference_lock` + executor 1-worker → các synth tuần tự toàn cục. Đánh đổi đã chọn (spec §3); nâng cấp pool K là việc tương lai, protocol không phải đổi.
- **Cùng image cho agent + service:** builder local vẫn tồn tại trong image agent nhưng không được gọi (backend=remote). Chốt chặn cứng tuyệt đối (bỏ extra local khỏi image agent) để pha tách Dockerfile sau.
