# STT Gate ↔ Endpoint Keepalive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `rms`/`vad` STT input-gate modes usable by feeding synthetic silence to STT while the gate is closed, so sherpa's endpoint detector still fires a `final` at its normal timing.

**Architecture:** All keepalive state lives in the pure `SttInputGate`; `BaseSession.process_audio_frame` forwards a gate-provided zero-PCM frame to STT whenever the gate withholds real audio and an utterance is still pending. `_on_final` tells the gate to stop. No `STTBase`/protocol change; backend-agnostic (zeros are just PCM bytes).

**Tech Stack:** Python 3.11–3.13, pytest (`asyncio_mode=auto`), ruff (line-length 120), sherpa-onnx STT, `SttInputGate` (`voice/stt_input_gate.py`), `BaseSession` (`server/base_session.py`).

## Global Constraints

- `off` gate mode behavior MUST be byte-for-byte unchanged (keepalive never invoked in `off`).
- Finalization timing MUST NOT change: keepalive feeds one silence frame per incoming frame at real-time rate; sherpa's endpoint fires at its normal ~1.2s.
- Injected silence MUST NOT enter `_utterance_pcm` (the speaker-embedding buffer) or touch `_stt_audio_start`.
- No new `STTBase` method, no new WS protocol control message.
- New config: `STT_GATE_KEEPALIVE_MAX_SEC` (env) / `stt_gate_keepalive_max_sec: float = 2.0` (`config.py`). Safety cap = `int(stt_gate_keepalive_max_sec * stt_sample_rate * 2)` bytes; `0` disables keepalive.
- Ruff must pass (`make lint`). Match existing style.
- Do not touch `develop`. Local commits on the current branch (`feat/seperate-service`) only.

---

### Task 1: `SttInputGate` keepalive + config field

**Files:**
- Modify: `src/noble_agent/config.py` (add field after line 387 `stt_vad_gate_hangover_ms`)
- Modify: `src/noble_agent/voice/stt_input_gate.py` (add state, `keepalive`, `notify_final`, `from_settings` param, set `_pending` in `gate`)
- Test: `tests/unit/test_stt_input_gate.py` (add keepalive tests; update `test_from_settings_maps_mode_and_hangover`)
- Test: `tests/unit/test_config_gate_speaker.py` (add default assertion)

**Interfaces:**
- Consumes: existing `SttInputGate.__init__(*, mode, preroll_chunks, min_rms, required_consecutive, barge_in_rms, vad_hangover_chunks)`; existing `gate(data: bytes) -> list[bytes]`; `settings.stt_sample_rate` (int, 16000).
- Produces (used by Task 2):
  - `SttInputGate.__init__` gains `keepalive_max_bytes: int = 0`.
  - `SttInputGate.keepalive(frame_len: int) -> bytes | None` — a zero-filled frame of `frame_len` bytes while an utterance is pending and under the cap; else `None`.
  - `SttInputGate.notify_final() -> None` — clears the pending state.
  - `SttInputGate.from_settings(settings)` also reads `settings.stt_gate_keepalive_max_sec: float`.
  - `config.UnifiedSettings.stt_gate_keepalive_max_sec: float = 2.0`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_stt_input_gate.py` (the file already defines `FRAME = 640` and `_f(amp)`; `struct` and `SimpleNamespace` are already imported):

```python
def test_keepalive_emits_silence_while_pending():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=0, keepalive_max_bytes=1920)
    data = _f(1000)
    g.feed_vad(True)
    assert g.gate(data) == [data]  # active → utterance pending
    g.feed_vad(False)
    assert g.gate(data) == []  # gate closed → withheld
    assert g.keepalive(FRAME) == b"\x00" * FRAME


def test_keepalive_none_when_not_pending():
    g = SttInputGate(mode="vad", keepalive_max_bytes=1920)
    assert g.keepalive(FRAME) is None


def test_keepalive_stops_after_notify_final():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=0, keepalive_max_bytes=1920)
    data = _f(1000)
    g.feed_vad(True)
    g.gate(data)  # pending
    g.notify_final()
    assert g.keepalive(FRAME) is None


def test_keepalive_respects_cap():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=0, keepalive_max_bytes=FRAME)
    data = _f(1000)
    g.feed_vad(True)
    g.gate(data)  # pending, keepalive counter reset to 0
    assert g.keepalive(FRAME) == b"\x00" * FRAME  # 0 < FRAME → emit (now == FRAME)
    assert g.keepalive(FRAME) is None  # FRAME >= FRAME → stop


def test_keepalive_disabled_when_max_zero():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=0, keepalive_max_bytes=0)
    data = _f(1000)
    g.feed_vad(True)
    g.gate(data)
    assert g.keepalive(FRAME) is None
```

Replace the existing `test_from_settings_maps_mode_and_hangover` with a version that supplies the two new attributes and asserts the derived cap:

```python
def test_from_settings_maps_mode_and_hangover():
    s = SimpleNamespace(
        stt_input_gate_mode="vad",
        audio_gate_preroll_chunks=4,
        audio_gate_min_rms=160.0,
        audio_gate_required_consecutive=3,
        audio_gate_barge_in_rms=2400.0,
        stt_vad_gate_hangover_ms=300,
        vad_chunk_ms=32,
        stt_gate_keepalive_max_sec=2.0,
        stt_sample_rate=16000,
    )
    g = SttInputGate.from_settings(s)
    assert g.mode == "vad"
    assert g._preroll.maxlen == 4
    assert g._vad_hangover_chunks == 10  # ceil(300/32)
    assert g.keepalive_max_bytes == 64000  # int(2.0 * 16000 * 2)
```

Add to `tests/unit/test_config_gate_speaker.py` (inside `test_input_gate_defaults`, append one assertion):

```python
    assert _default("stt_gate_keepalive_max_sec") == 2.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_stt_input_gate.py tests/unit/test_config_gate_speaker.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'keepalive_max_bytes'` and `AttributeError`/`KeyError` for `stt_gate_keepalive_max_sec`.

- [ ] **Step 3: Add the config field**

In `src/noble_agent/config.py`, immediately after line 387 (`stt_vad_gate_hangover_ms: int = 300 ...`), add:

```python
    stt_gate_keepalive_max_sec: float = 2.0  # (rms/vad) max synthetic silence fed to STT after a pending utterance so its endpoint fires; 0 = off
```

- [ ] **Step 4: Implement the gate changes**

In `src/noble_agent/voice/stt_input_gate.py`, add `keepalive_max_bytes` to `__init__` (new keyword after `vad_hangover_chunks`) and initialize the pending state at the end of `__init__`:

```python
    def __init__(
        self,
        *,
        mode: str = "off",
        preroll_chunks: int = 3,
        min_rms: float = 160.0,
        required_consecutive: int = 3,
        barge_in_rms: float = 2400.0,
        vad_hangover_chunks: int = 0,
        keepalive_max_bytes: int = 0,
    ) -> None:
```

At the end of `__init__` (after `self._vad_active = False`):

```python
        # Keepalive: feed synthetic silence to STT while the gate is closed and
        # an utterance is still pending, so the recognizer's trailing-silence
        # endpoint can fire. 0 → disabled.
        self.keepalive_max_bytes = max(0, int(keepalive_max_bytes))
        self._pending = False
        self._keepalive_bytes = 0
```

In `gate`, inside the `if active:` block (after `out.append(data)`), mark the utterance pending and reset the keepalive counter:

```python
    def gate(self, data: bytes) -> list[bytes]:
        """Return the chunks to forward to STT for this incoming chunk."""
        active = self._active(data)
        out: list[bytes] = []
        if active:
            if not self._was_active:  # rising edge → flush withheld lead-in
                out.extend(self._preroll)
                self._preroll.clear()
            out.append(data)
            self._pending = True  # real audio forwarded → an utterance is in progress
            self._keepalive_bytes = 0
        elif self._preroll.maxlen:
            self._preroll.append(data)
        self._was_active = active
        return out
```

Add the two new methods after `gate` (before `from_settings`):

```python
    def keepalive(self, frame_len: int) -> bytes | None:
        """Silence to feed STT while the gate is closed, so the recognizer's
        endpoint fires on a pending utterance. Returns a zero-filled frame while
        pending and under the cap, else None."""
        if not self._pending or self._keepalive_bytes >= self.keepalive_max_bytes:
            return None
        self._keepalive_bytes += frame_len
        return bytes(frame_len)

    def notify_final(self) -> None:
        """Called when STT emits a final — the utterance ended, stop keepalive."""
        self._pending = False
        self._keepalive_bytes = 0
```

In `from_settings`, add the derived cap to the `cls(...)` call (after `vad_hangover_chunks=hangover,`):

```python
            keepalive_max_bytes=int(settings.stt_gate_keepalive_max_sec * settings.stt_sample_rate * 2),
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_stt_input_gate.py tests/unit/test_config_gate_speaker.py -v`
Expected: PASS (all tests, including the pre-existing gate tests).

- [ ] **Step 6: Lint**

Run: `ruff check src/noble_agent/voice/stt_input_gate.py src/noble_agent/config.py tests/unit/test_stt_input_gate.py tests/unit/test_config_gate_speaker.py`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/config.py src/noble_agent/voice/stt_input_gate.py tests/unit/test_stt_input_gate.py tests/unit/test_config_gate_speaker.py
git commit -m "feat(stt): SttInputGate silence keepalive + STT_GATE_KEEPALIVE_MAX_SEC"
```

---

### Task 2: Wire keepalive into `BaseSession` + docs

**Files:**
- Modify: `src/noble_agent/server/base_session.py` (`process_audio_frame` empty-chunk branch ~lines 416-420; `_on_final` top ~line 520)
- Modify: `tests/unit/test_base_session.py` (add `stt_gate_keepalive_max_sec` to the harness; fix one existing test; add a `TestGateKeepalive` class)
- Modify: `.env.example` (document `STT_GATE_KEEPALIVE_MAX_SEC` near the `STT_INPUT_GATE_*` block)
- Modify: `CLAUDE.md` (STT backends prose + key-configuration table + one Change Log row)

**Interfaces:**
- Consumes (from Task 1): `SttInputGate.keepalive(frame_len: int) -> bytes | None`, `SttInputGate.notify_final() -> None`, `settings.stt_gate_keepalive_max_sec`.
- Produces: no new public interface.

- [ ] **Step 1: Write the failing tests**

First, add the new setting to the shared harness so `SttInputGate.from_settings` works. In `tests/unit/test_base_session.py`, in `_patched_collaborators`, after the line `mock_settings.stt_vad_gate_hangover_ms = 300` (line 54), add:

```python
        mock_settings.stt_gate_keepalive_max_sec = 2.0
```

Update the existing `test_gate_rms_mode_drops_unconfirmed_frames` (the gate now asks for keepalive when it withholds — the stub must return `None` to keep `send` un-awaited). After `gate_stub.gate.return_value = []` (line 941), add:

```python
            gate_stub.keepalive.return_value = None
```

Append a new test class at the end of `tests/unit/test_base_session.py` (`asyncio`, `AsyncMock`, `MagicMock`, `_patched_collaborators`, `_FakeAudioOutput` are already imported/defined in the file):

```python
class TestGateKeepalive:
    """Silence keepalive: gate-closed frames feed STT so the endpoint fires."""

    async def test_keepalive_silence_sent_when_gate_closed(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-ka1")
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()
            gate = MagicMock(spec=SttInputGate)
            gate.mode = "vad"
            gate.gate.return_value = []  # withheld
            gate.keepalive.return_value = b"\x00" * 320
            s._input_gate = gate

            await s.process_audio_frame(b"\x00" * 320)

            gate.keepalive.assert_called_once_with(320)
            s.stt.send.assert_awaited_once_with(b"\x00" * 320)

    async def test_no_send_when_keepalive_returns_none(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-ka2")
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()
            gate = MagicMock(spec=SttInputGate)
            gate.mode = "vad"
            gate.gate.return_value = []
            gate.keepalive.return_value = None
            s._input_gate = gate

            await s.process_audio_frame(b"\x00" * 320)

            s.stt.send.assert_not_awaited()

    async def test_keepalive_silence_excluded_from_utterance_pcm(self) -> None:
        async with _patched_collaborators() as cols:
            cols["settings"].speaker_mode = "multi"
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-ka3")
            s.stt = AsyncMock()
            s._audio_output = _FakeAudioOutput()
            gate = MagicMock(spec=SttInputGate)
            gate.mode = "vad"
            real = b"\x11\x11" * 160
            gate.gate.side_effect = [[real], []]  # frame 1 real, frame 2 withheld
            gate.keepalive.return_value = b"\x00" * 320
            s._input_gate = gate

            await s.process_audio_frame(real)  # real audio → into _utterance_pcm
            await s.process_audio_frame(b"\x00" * 320)  # withheld → keepalive silence

            assert bytes(s._utterance_pcm) == real

    async def test_on_final_calls_notify_final(self) -> None:
        async with _patched_collaborators():
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.stt_input_gate import SttInputGate

            s = BaseSession("sid-ka4")
            gate = MagicMock(spec=SttInputGate)
            s._input_gate = gate

            async def _fake_trigger(t: str) -> None:
                return None

            s._trigger_agent_for_text = _fake_trigger  # type: ignore[method-assign]

            await s._on_final("hello there")

            gate.notify_final.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_base_session.py::TestGateKeepalive -v`
Expected: FAIL — `test_keepalive_silence_sent_when_gate_closed` fails (`send` not awaited / `keepalive` not called) and `test_on_final_calls_notify_final` fails (`notify_final` not called), because `base_session` does not call these yet.

- [ ] **Step 3: Wire keepalive in `process_audio_frame`**

In `src/noble_agent/server/base_session.py`, change the empty-chunk branch (currently lines 418-420) from:

```python
            chunks = self._input_gate.gate(data)
            if not chunks:
                self.metrics.record_latency("guard", "frames_gated_bytes", len(data))
```

to:

```python
            chunks = self._input_gate.gate(data)
            if not chunks:
                self.metrics.record_latency("guard", "frames_gated_bytes", len(data))
                # Gate closed but an utterance may be pending: feed synthetic
                # silence so the STT endpoint fires at its normal timing. Bypasses
                # the real-chunk loop, so it never enters _utterance_pcm.
                silence = self._input_gate.keepalive(len(data))
                if silence is not None:
                    await self.stt.send(silence)
```

- [ ] **Step 4: Wire `notify_final` in `_on_final`**

In `_on_final`, immediately after `self._reset_idle()` (line 520) and before the STT-latency metric block, add:

```python
        self._input_gate.notify_final()  # utterance ended → stop keepalive silence
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_base_session.py -v`
Expected: PASS (the new `TestGateKeepalive` class and all pre-existing tests, including `TestFramesGate`).

- [ ] **Step 6: Update `.env.example`**

In `.env.example`, directly below the `STT_VAD_GATE_HANGOVER_MS=300 ...` line in the `STT_INPUT_GATE_*` block, add:

```bash
STT_GATE_KEEPALIVE_MAX_SEC=2.0        # (rms/vad) max synthetic silence fed to STT after a pending utterance so its endpoint fires; 0 = off
```

- [ ] **Step 7: Update `CLAUDE.md`**

In the STT backends bullet (the `STT_INPUT_GATE_MODE` paragraph), append a sentence:

```
When a gate mode is `rms`/`vad`, closed frames are backfilled with synthetic zero-PCM silence (`STT_GATE_KEEPALIVE_MAX_SEC`, default `2.0`s cap) fed to the STT engine so the recognizer's trailing-silence endpoint still fires — finalization timing is unchanged, real noise stays blocked, and it is backend-agnostic (zeros are plain PCM, no protocol change). The injected silence bypasses `_utterance_pcm`.
```

Add a row to the key-configuration table (after the `STT_VAD_GATE_HANGOVER_MS` row):

```
| `STT_GATE_KEEPALIVE_MAX_SEC` | `2.0` | (rms/vad) max synthetic silence fed to STT after a pending utterance so the endpoint fires; `0` = off. |
```

Add one Change Log row at the top of the Change Log table body:

```
| 2026-07-01 | **STT input gate ↔ endpoint keepalive.** `rms`/`vad` gate modes withheld trailing silence from the STT engine, starving sherpa's `is_endpoint()` → no `final` was ever emitted (partials streamed but nothing submitted). `SttInputGate` now backfills closed frames with synthetic zero-PCM silence (`keepalive()`/`notify_final()`, capped by `STT_GATE_KEEPALIVE_MAX_SEC`, default `2.0`s); `base_session.process_audio_frame` forwards it to `stt.send` (bypassing `_utterance_pcm`), `_on_final` calls `notify_final()`. Timing unchanged (endpoint still fires at ~1.2s), real noise still blocked, backend-agnostic (no protocol change), `off` mode unchanged. Branch `feat/seperate-service`. | Enabling the noise gate silently broke STT finalization because the gate removed exactly the trailing silence the recognizer's endpoint needs. |
```

- [ ] **Step 8: Lint**

Run: `ruff check src/noble_agent/server/base_session.py tests/unit/test_base_session.py`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add src/noble_agent/server/base_session.py tests/unit/test_base_session.py .env.example CLAUDE.md
git commit -m "feat(stt): feed gate keepalive silence to STT so endpoint fires (rms/vad)"
```

---

## Manual verification (after both tasks)

Run the STT-path smoke check with the gate enabled:

1. Set `STT_INPUT_GATE_MODE=vad` in `.env`.
2. Fully restart the LiveKit worker (kill the prewarm process too so the new config loads).
3. Call in, speak one sentence, stop.
4. Confirm in the worker log: `[STT] Final transcript received: ...` appears ~1.2s after you stop, and the agent responds.
5. Confirm the session metrics on disconnect still show `frames_gated_bytes` (silence is blocked from `_utterance_pcm`, real noise still gated) but finals now fire.

Run `src/noble_agent/SMOKE.md` (turn loop + STT path touched).
