# STT Noise Gate + Speaker Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the STT path from emitting transcripts for non-speech (noise/silence) and from a non-primary speaker, via a selectable input gate with pre-roll lookback and an opt-in speaker-verification layer.

**Architecture:** Two independent, flag-gated layers in the shared `voice`/`server` layer. (1) A new `SttInputGate` component sits between caller audio and `stt.send()` with three modes (`off`/`rms`/`vad`) and a shared pre-roll deque. (2) A new `SpeakerVerifier` + `SpeakerEmbedder` (sherpa-onnx embeddings, remote-default/local-fallback like `gender_detector`) runs at `_on_final`, enrolls the first valid utterance, and drops mismatched speakers.

**Tech Stack:** Python 3.11–3.13, `sherpa-onnx` (already a dep — reuse `SpeakerEmbeddingExtractor`), `httpx`, `numpy`, pydantic-settings, pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- Work only in `src/noble_agent/`. Active package is `noble_agent`.
- Branch: `feat/seperate-service`. Local commits only; never touch `develop`; no push / PR / new branch without explicit approval.
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `make lint` + `make format`.
- Pytest `asyncio_mode=auto`. Unit tests must NOT require a model download or network — mock/inject. Model-dependent checks use markers and stay out of `make test-unit`.
- No new heavy dependency — reuse `sherpa-onnx`.
- All flags/thresholds live in `config.py` (env-driven) with safe code defaults (`STT_INPUT_GATE_MODE=off`, `SPEAKER_VERIFICATION_ENABLED=false`).
- Heavy imports (`sherpa_onnx`, `huggingface_hub`, `httpx`) stay function-local so `make test-unit` collects without optional deps.
- Audio format on the hot path: PCM int16, 16 kHz, mono. `settings.stt_sample_rate == 16000`.
- Run `src/noble_agent/SMOKE.md` after wiring tasks (turn loop / audio pipeline touched).

---

### Task 1: Config — add all new settings

**Files:**
- Modify: `src/noble_agent/config.py` (add fields near the Audio + STT sections)
- Test: `tests/unit/test_config_gate_speaker.py`

**Interfaces:**
- Produces: `settings.stt_input_gate_mode: str`, `settings.audio_gate_preroll_chunks: int`, `settings.audio_gate_min_rms: float`, `settings.audio_gate_required_consecutive: int`, `settings.audio_gate_barge_in_rms: float`, `settings.stt_vad_gate_hangover_ms: int`, `settings.speaker_verification_enabled: bool`, `settings.speaker_remote_url: str`, `settings.speaker_remote_timeout: float`, `settings.speaker_remote_token: str`, `settings.speaker_model_dir: str`, `settings.speaker_model_name: str`, `settings.speaker_hf_repo: str`, `settings.speaker_hf_revision: str`, `settings.speaker_match_threshold: float`, `settings.speaker_min_enroll_sec: float`, `settings.speaker_embed_window_sec: float`, `settings.speaker_adapt_enabled: bool`, `settings.speaker_adapt_weight: float`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_gate_speaker.py
from noble_agent.config import settings


def test_input_gate_defaults():
    assert settings.stt_input_gate_mode == "off"
    assert settings.audio_gate_preroll_chunks == 3
    assert settings.audio_gate_min_rms == 160.0
    assert settings.audio_gate_required_consecutive == 3
    assert settings.audio_gate_barge_in_rms == 2400.0
    assert settings.stt_vad_gate_hangover_ms == 300


def test_speaker_defaults():
    assert settings.speaker_verification_enabled is False
    assert settings.speaker_remote_timeout == 3.0
    assert settings.speaker_model_name == "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
    assert settings.speaker_hf_repo == "csukuangfj/speaker-embedding-models"
    assert settings.speaker_hf_revision == "prod"
    assert settings.speaker_match_threshold == 0.5
    assert settings.speaker_min_enroll_sec == 1.0
    assert settings.speaker_embed_window_sec == 3.0
    assert settings.speaker_adapt_enabled is False
    assert settings.speaker_adapt_weight == 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_config_gate_speaker.py -v`
Expected: FAIL with `AttributeError` (fields not defined).

- [ ] **Step 3: Add the fields**

In `config.py`, in the `# ── Audio ──` section replace the line
`audio_guard_frames_gate_enabled: bool = False` with:

```python
    # Input gate to STT: "off" (passthrough) | "rms" (energy) | "vad" (Silero is_speech).
    stt_input_gate_mode: str = "off"
    audio_gate_preroll_chunks: int = 3  # K chunk lookback to recover clipped lead-in (all modes); 0 = off
    audio_gate_min_rms: float = 160.0  # (rms) per-frame energy threshold
    audio_gate_required_consecutive: int = 3  # (rms) consecutive frames to confirm speech
    audio_gate_barge_in_rms: float = 2400.0  # (rms) high-energy barge-in threshold
    stt_vad_gate_hangover_ms: int = 300  # (vad) keep gate open this long after speech ends
```

Then add a new block after the STT settings (near the sherpa block):

```python
    # ── Speaker verification (opt-in; remote-default like gender_detector) ──────
    speaker_verification_enabled: bool = False
    speaker_remote_url: str = ""  # non-empty → remote embedder (default); empty → local sherpa
    speaker_remote_timeout: float = 3.0
    speaker_remote_token: str = ""  # optional bearer for the remote embedder
    speaker_model_dir: str = "models/speaker"  # (local) ONNX dir
    speaker_model_name: str = "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"  # (local) ONNX file
    speaker_hf_repo: str = "csukuangfj/speaker-embedding-models"  # (local) single-file provision source
    speaker_hf_revision: str = "prod"
    speaker_match_threshold: float = 0.5  # min cosine to accept as the same speaker
    speaker_min_enroll_sec: float = 1.0  # min utterance length to enroll
    speaker_embed_window_sec: float = 3.0  # trailing audio from _audio_ring to embed
    speaker_adapt_enabled: bool = False  # running-mean centroid update
    speaker_adapt_weight: float = 0.1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_config_gate_speaker.py -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
make lint && git add src/noble_agent/config.py tests/unit/test_config_gate_speaker.py
git commit -m "feat(config): add input-gate + speaker-verification settings"
```

---

### Task 2: Parameterize `ConsecutiveFramesGate`

**Files:**
- Modify: `src/noble_agent/voice/audio_guard.py` (the `ConsecutiveFramesGate.__init__` already accepts these args — verify and keep; this task only confirms defaults are overridable and adds a test).
- Test: `tests/unit/test_consecutive_frames_gate.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ConsecutiveFramesGate(min_rms, barge_in_rms, required_consecutive, frame_bytes)` — already exists; this locks its contract for `SttInputGate`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_consecutive_frames_gate.py
import struct

from noble_agent.voice.audio_guard import ConsecutiveFramesGate

FRAME = 640  # 20ms @ 16kHz int16


def _frame(amp: int) -> bytes:
    return struct.pack(f"<{FRAME // 2}h", *([amp] * (FRAME // 2)))


def test_requires_n_consecutive_loud_frames():
    gate = ConsecutiveFramesGate(min_rms=160, required_consecutive=3)
    loud = _frame(1000)
    assert gate.feed(loud) is False  # 1
    assert gate.feed(loud) is False  # 2
    assert gate.feed(loud) is True   # 3 → confirmed
    assert gate.confirmed is True


def test_silence_resets_immediately():
    gate = ConsecutiveFramesGate(min_rms=160, required_consecutive=3)
    loud = _frame(1000)
    for _ in range(3):
        gate.feed(loud)
    assert gate.confirmed is True
    gate.feed(_frame(0))  # one silent frame
    assert gate.confirmed is False
```

- [ ] **Step 2: Run test to verify it passes or fails**

Run: `pytest tests/unit/test_consecutive_frames_gate.py -v`
Expected: PASS (the class already supports these params). If FAIL, adjust `__init__` to accept `min_rms`, `barge_in_rms`, `required_consecutive`, `frame_bytes` as keyword args defaulting to the current module constants.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_consecutive_frames_gate.py
git commit -m "test(audio-guard): lock ConsecutiveFramesGate parameter contract"
```

---

### Task 3: `SttInputGate` component (Problem 1 core)

**Files:**
- Create: `src/noble_agent/voice/stt_input_gate.py`
- Test: `tests/unit/test_stt_input_gate.py`

**Interfaces:**
- Consumes: `ConsecutiveFramesGate(min_rms, barge_in_rms, required_consecutive)` (Task 2); `settings` (Task 1).
- Produces:
  - `class SttInputGate` with:
    - `__init__(self, *, mode, preroll_chunks, min_rms, required_consecutive, barge_in_rms, vad_hangover_chunks)`
    - `feed_vad(self, is_speech: bool) -> None`
    - `gate(self, data: bytes) -> list[bytes]` — chunks to forward to STT for this input chunk (`[]`, `[data]`, or `preroll… + [data]`)
    - `classmethod from_settings(cls, settings) -> SttInputGate`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_stt_input_gate.py
import struct

from noble_agent.voice.stt_input_gate import SttInputGate

FRAME = 640


def _f(amp: int) -> bytes:
    return struct.pack(f"<{FRAME // 2}h", *([amp] * (FRAME // 2)))


def test_off_mode_passes_everything():
    g = SttInputGate(mode="off", preroll_chunks=3)
    assert g.gate(_f(0)) == [_f(0)]
    assert g.gate(_f(1000)) == [_f(1000)]


def test_rms_mode_withholds_then_flushes_preroll_on_rising_edge():
    g = SttInputGate(mode="rms", preroll_chunks=2, min_rms=160, required_consecutive=3)
    loud = _f(1000)
    out1 = g.gate(loud)  # frame 1 — not confirmed, withheld
    out2 = g.gate(loud)  # frame 2 — not confirmed, withheld
    assert out1 == [] and out2 == []
    out3 = g.gate(loud)  # frame 3 — rising edge: flush 2 preroll + current
    assert out3 == [loud, loud, loud]
    out4 = g.gate(loud)  # already active — passthrough
    assert out4 == [loud]


def test_preroll_respects_maxlen():
    g = SttInputGate(mode="rms", preroll_chunks=1, min_rms=160, required_consecutive=3)
    loud = _f(1000)
    g.gate(loud)  # withheld (deque holds last 1)
    g.gate(loud)  # withheld (deque still holds only last 1)
    out = g.gate(loud)  # rising edge → only 1 preroll + current
    assert out == [loud, loud]


def test_vad_mode_gates_on_is_speech_with_hangover():
    g = SttInputGate(mode="vad", preroll_chunks=0, vad_hangover_chunks=2)
    data = _f(1000)
    assert g.gate(data) == []        # vad not active yet
    g.feed_vad(True)
    assert g.gate(data) == [data]    # active
    g.feed_vad(False)                # hangover 2 → still active
    assert g.gate(data) == [data]
    g.feed_vad(False)                # hangover 1
    g.feed_vad(False)                # hangover 0 → inactive
    assert g.gate(data) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_stt_input_gate.py -v`
Expected: FAIL with `ModuleNotFoundError: noble_agent.voice.stt_input_gate`.

- [ ] **Step 3: Write the implementation**

```python
# src/noble_agent/voice/stt_input_gate.py
"""Selectable input gate between caller audio and STT.

Modes: "off" (passthrough), "rms" (energy gate via ConsecutiveFramesGate),
"vad" (Silero is_speech + hangover). A pre-roll deque recovers the lead-in
clipped while the gate was inactive: on the rising edge (inactive -> active)
the withheld chunks are emitted before the current chunk so the recognizer
sees the start of the utterance.
"""

from __future__ import annotations

from collections import deque

from noble_agent.voice.audio_guard import ConsecutiveFramesGate


class SttInputGate:
    def __init__(
        self,
        *,
        mode: str = "off",
        preroll_chunks: int = 3,
        min_rms: float = 160.0,
        required_consecutive: int = 3,
        barge_in_rms: float = 2400.0,
        vad_hangover_chunks: int = 0,
    ) -> None:
        self.mode = mode
        self._preroll: deque[bytes] = deque(maxlen=max(0, int(preroll_chunks)))
        self._was_active = False
        self._frames_gate = (
            ConsecutiveFramesGate(
                min_rms=min_rms,
                barge_in_rms=barge_in_rms,
                required_consecutive=required_consecutive,
            )
            if mode == "rms"
            else None
        )
        self._vad_hangover_chunks = max(0, int(vad_hangover_chunks))
        self._vad_hangover_left = 0
        self._vad_active = False

    def feed_vad(self, is_speech: bool) -> None:
        """Update the vad-gate flag from one Silero is_speech decision."""
        if is_speech:
            self._vad_active = True
            self._vad_hangover_left = self._vad_hangover_chunks
        elif self._vad_hangover_left > 0:
            self._vad_hangover_left -= 1
        else:
            self._vad_active = False

    def _active(self, data: bytes) -> bool:
        if self.mode == "rms" and self._frames_gate is not None:
            self._frames_gate.feed(data)
            return self._frames_gate.confirmed
        if self.mode == "vad":
            return self._vad_active
        return True  # "off" or unknown → fail open

    def gate(self, data: bytes) -> list[bytes]:
        """Return the chunks to forward to STT for this incoming chunk."""
        active = self._active(data)
        out: list[bytes] = []
        if active:
            if not self._was_active:  # rising edge → flush withheld lead-in
                out.extend(self._preroll)
                self._preroll.clear()
            out.append(data)
        elif self._preroll.maxlen:
            self._preroll.append(data)
        self._was_active = active
        return out

    @classmethod
    def from_settings(cls, settings) -> "SttInputGate":
        import math

        hangover = math.ceil(settings.stt_vad_gate_hangover_ms / max(1, settings.vad_chunk_ms))
        return cls(
            mode=settings.stt_input_gate_mode,
            preroll_chunks=settings.audio_gate_preroll_chunks,
            min_rms=settings.audio_gate_min_rms,
            required_consecutive=settings.audio_gate_required_consecutive,
            barge_in_rms=settings.audio_gate_barge_in_rms,
            vad_hangover_chunks=hangover,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_stt_input_gate.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

```bash
make lint && git add src/noble_agent/voice/stt_input_gate.py tests/unit/test_stt_input_gate.py
git commit -m "feat(voice): SttInputGate — selectable off/rms/vad gate + pre-roll"
```

---

### Task 4: Wire `SttInputGate` into `process_audio_frame`

**Files:**
- Modify: `src/noble_agent/server/base_session.py` (imports, `__init__`, `process_audio_frame`)
- Test: `tests/unit/test_stt_input_gate.py` (add a `from_settings` factory test)

**Interfaces:**
- Consumes: `SttInputGate.from_settings` (Task 3); `settings` (Task 1).
- Produces: `self._input_gate: SttInputGate` on the session; `process_audio_frame` forwards only gated chunks to `stt.send`.

- [ ] **Step 1: Write the failing test (factory mapping)**

```python
# append to tests/unit/test_stt_input_gate.py
from types import SimpleNamespace

from noble_agent.voice.stt_input_gate import SttInputGate


def test_from_settings_maps_mode_and_hangover():
    s = SimpleNamespace(
        stt_input_gate_mode="vad",
        audio_gate_preroll_chunks=4,
        audio_gate_min_rms=160.0,
        audio_gate_required_consecutive=3,
        audio_gate_barge_in_rms=2400.0,
        stt_vad_gate_hangover_ms=300,
        vad_chunk_ms=32,
    )
    g = SttInputGate.from_settings(s)
    assert g.mode == "vad"
    assert g._preroll.maxlen == 4
    assert g._vad_hangover_chunks == 10  # ceil(300/32)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_stt_input_gate.py::test_from_settings_maps_mode_and_hangover -v`
Expected: FAIL only if `from_settings` math is wrong; if Task 3 is correct this passes — then this step documents the contract. Proceed either way.

- [ ] **Step 3: Wire into base_session**

In `base_session.py` imports add:

```python
from noble_agent.voice.stt_input_gate import SttInputGate
```

In `__init__`, replace the `_frames_gate` construction:

```python
        self._frames_gate: ConsecutiveFramesGate | None = (
            ConsecutiveFramesGate() if settings.audio_guard_frames_gate_enabled else None
        )
```

with:

```python
        self._input_gate = SttInputGate.from_settings(settings)
```

Remove the now-unused `ConsecutiveFramesGate` import if nothing else uses it.

Replace the body of `process_audio_frame` (the STT-send block + VAD block) so VAD runs first and STT is gated:

```python
    async def process_audio_frame(self, data: bytes) -> None:
        """Feed one caller-audio frame through VAD + the STT input gate."""
        # VAD first: it drives BOTH interrupt detection and the vad-gate flag.
        self._vad_buf += data
        while len(self._vad_buf) >= VAD_CHUNK_BYTES:
            chunk = self._vad_buf[:VAD_CHUNK_BYTES]
            self._vad_buf = self._vad_buf[VAD_CHUNK_BYTES:]
            result = self.vad.process_chunk(chunk)
            if self._input_gate.mode == "vad":
                self._input_gate.feed_vad(result["is_speech"])
            if result["state"] == VADState.INTERRUPTED:
                await self._handle_interrupt()

        # Gate STT input (off/rms/vad) with shared pre-roll.
        if self.stt:
            chunks = self._input_gate.gate(data)
            if not chunks:
                self.metrics.record_latency("guard", "frames_gated_bytes", len(data))
            for chunk in chunks:
                if self._stt_audio_start == 0.0:
                    self._stt_audio_start = time.monotonic()
                await self.stt.send(chunk)

        self._audio_ring_append(data)
```

- [ ] **Step 4: Run the unit suite + lint**

Run: `pytest tests/unit/test_stt_input_gate.py -v && make test-unit`
Expected: PASS; no import errors from the removed `audio_guard_frames_gate_enabled`. If any test referenced that flag, update it to set `stt_input_gate_mode`.

- [ ] **Step 5: Manual smoke + commit**

Follow `src/noble_agent/SMOKE.md` text-chat/voice path with `STT_INPUT_GATE_MODE=off` (must behave exactly as before), then `=rms` and `=vad`.

```bash
make lint && git add src/noble_agent/server/base_session.py tests/unit/test_stt_input_gate.py
git commit -m "feat(session): gate STT input via SttInputGate (off/rms/vad + pre-roll)"
```

---

### Task 5: `SpeakerVerifier` (Problem 2 core logic)

**Files:**
- Create: `src/noble_agent/voice/speaker_verifier.py` (logic only this task; embedder added in Task 6)
- Test: `tests/unit/test_speaker_verifier.py`

**Interfaces:**
- Produces:
  - `class SpeakerVerifier(*, match_threshold, adapt_enabled, adapt_weight)`
    - property `enrolled: bool`
    - `enroll(emb: np.ndarray) -> None`
    - `verify(emb: np.ndarray) -> tuple[bool, float]`
    - `maybe_adapt(emb: np.ndarray) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_speaker_verifier.py
import numpy as np

from noble_agent.voice.speaker_verifier import SpeakerVerifier


def test_first_verify_passes_before_enroll():
    v = SpeakerVerifier(match_threshold=0.5)
    ok, sim = v.verify(np.array([1.0, 0.0, 0.0], dtype=np.float32))
    assert ok is True and sim == 1.0


def test_same_speaker_accepted_different_rejected():
    v = SpeakerVerifier(match_threshold=0.5)
    v.enroll(np.array([1.0, 0.0, 0.0], dtype=np.float32))
    ok_same, sim_same = v.verify(np.array([0.9, 0.1, 0.0], dtype=np.float32))
    ok_diff, sim_diff = v.verify(np.array([0.0, 1.0, 0.0], dtype=np.float32))
    assert ok_same is True and sim_same > 0.5
    assert ok_diff is False and sim_diff < 0.5


def test_adapt_moves_centroid_toward_new_embedding():
    v = SpeakerVerifier(match_threshold=0.5, adapt_enabled=True, adapt_weight=0.5)
    v.enroll(np.array([1.0, 0.0], dtype=np.float32))
    v.maybe_adapt(np.array([0.0, 1.0], dtype=np.float32))
    _, sim = v.verify(np.array([0.0, 1.0], dtype=np.float32))
    assert sim > 0.5  # centroid moved toward [0,1]


def test_adapt_noop_when_disabled():
    v = SpeakerVerifier(match_threshold=0.5, adapt_enabled=False)
    v.enroll(np.array([1.0, 0.0], dtype=np.float32))
    v.maybe_adapt(np.array([0.0, 1.0], dtype=np.float32))
    _, sim = v.verify(np.array([1.0, 0.0], dtype=np.float32))
    assert sim == 1.0  # unchanged
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_speaker_verifier.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# src/noble_agent/voice/speaker_verifier.py
"""Per-session speaker verification.

Enrolls the primary caller's voice embedding from the first valid utterance,
then rejects later utterances whose embedding does not match (cosine) the
enrolled centroid. Embedding extraction lives in SpeakerEmbedder (added
separately); this class is pure vector logic and is unit-tested without a model.
"""

from __future__ import annotations

import numpy as np


def _normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class SpeakerVerifier:
    def __init__(self, *, match_threshold: float = 0.5, adapt_enabled: bool = False, adapt_weight: float = 0.1) -> None:
        self._threshold = match_threshold
        self._adapt_enabled = adapt_enabled
        self._adapt_weight = adapt_weight
        self._centroid: np.ndarray | None = None

    @property
    def enrolled(self) -> bool:
        return self._centroid is not None

    def enroll(self, emb: np.ndarray) -> None:
        self._centroid = _normalize(emb)

    def verify(self, emb: np.ndarray) -> tuple[bool, float]:
        if self._centroid is None:
            return True, 1.0
        sim = _cosine(self._centroid, emb)
        return sim >= self._threshold, sim

    def maybe_adapt(self, emb: np.ndarray) -> None:
        if not self._adapt_enabled or self._centroid is None:
            return
        w = self._adapt_weight
        self._centroid = _normalize((1.0 - w) * self._centroid + w * _normalize(emb))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_speaker_verifier.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint + commit**

```bash
make lint && git add src/noble_agent/voice/speaker_verifier.py tests/unit/test_speaker_verifier.py
git commit -m "feat(voice): SpeakerVerifier — enroll/verify/adapt cosine logic"
```

---

### Task 6: `SpeakerEmbedder` — local sherpa + remote client + provisioning

**Files:**
- Modify: `src/noble_agent/voice/speaker_verifier.py` (add `SpeakerEmbedder` + provisioning helpers)
- Test: `tests/unit/test_speaker_embedder.py`

**Interfaces:**
- Consumes: `settings` (Task 1); `sherpa_onnx.SpeakerEmbeddingExtractor`; `huggingface_hub.hf_hub_download`; `httpx`.
- Produces:
  - `class SpeakerEmbedder` singleton: `get_instance() -> SpeakerEmbedder`, `embed(pcm16: bytes) -> np.ndarray | None`
  - module fn `_ensure_speaker_model_present(model_dir, model_name, repo_id, token, revision) -> str` (returns abs path)
  - module fn `_get_extractor()` (cached local extractor)

- [ ] **Step 1: Write the failing test (remote path, mocked httpx)**

```python
# tests/unit/test_speaker_embedder.py
import base64

import numpy as np

import noble_agent.voice.speaker_verifier as sv


class _FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"embedding": [0.1, 0.2, 0.3]}


class _FakeClient:
    def __init__(self, *a, **k):
        self.posted = None

    def post(self, url, json=None):
        self.posted = (url, json)
        return _FakeResp()


def test_remote_embed_posts_base64_and_parses(monkeypatch):
    emb = sv.SpeakerEmbedder.__new__(sv.SpeakerEmbedder)  # bypass __init__/_load
    emb._extractor = None
    emb._remote_url = "http://svc:9000"
    emb._remote_client = _FakeClient()
    out = emb.embed(b"\x01\x00\x02\x00")
    assert isinstance(out, np.ndarray)
    np.testing.assert_allclose(out, np.array([0.1, 0.2, 0.3], dtype=np.float32), rtol=1e-6)
    url, payload = emb._remote_client.posted
    assert url == "http://svc:9000/embed"
    assert base64.b64decode(payload["audio_b64"]) == b"\x01\x00\x02\x00"


def test_embed_empty_returns_none():
    emb = sv.SpeakerEmbedder.__new__(sv.SpeakerEmbedder)
    emb._extractor = None
    emb._remote_client = None
    assert emb.embed(b"") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_speaker_embedder.py -v`
Expected: FAIL with `AttributeError: SpeakerEmbedder` (not defined yet).

- [ ] **Step 3: Add embedder + provisioning to `speaker_verifier.py`**

Append to `src/noble_agent/voice/speaker_verifier.py`:

```python
import logging
import os

logger = logging.getLogger(__name__)

_extractor = None


def _ensure_speaker_model_present(model_dir: str, model_name: str, repo_id: str, token: str, revision: str) -> str:
    """Return the local ONNX path, pulling the single file from HF if absent."""
    path = os.path.join(model_dir, model_name)
    if os.path.exists(path):
        return path
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:  # part of the stt-sherpa extra
        raise ImportError('huggingface_hub not installed. Run: pip install -e ".[stt-sherpa]"') from exc
    os.makedirs(model_dir, exist_ok=True)
    logger.info("Speaker model missing — pulling %s/%s@%s ...", repo_id, model_name, revision)
    downloaded = hf_hub_download(
        repo_id=repo_id, filename=model_name, local_dir=model_dir, token=token or None, revision=revision
    )
    return downloaded


def _get_extractor():
    """Load or return the cached sherpa SpeakerEmbeddingExtractor (local mode)."""
    global _extractor
    if _extractor is not None:
        return _extractor
    import sherpa_onnx

    from noble_agent.config import settings

    model_path = _ensure_speaker_model_present(
        settings.speaker_model_dir,
        settings.speaker_model_name,
        settings.speaker_hf_repo,
        settings.hf_token,
        settings.speaker_hf_revision,
    )
    config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model_path, num_threads=settings.sherpa_num_threads)
    _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
    logger.info("Speaker embedding extractor ready (dim=%d).", _extractor.dim)
    return _extractor


class SpeakerEmbedder:
    """Singleton embedder: remote (default when SPEAKER_REMOTE_URL set) or local sherpa."""

    _instance: "SpeakerEmbedder | None" = None

    @classmethod
    def get_instance(cls) -> "SpeakerEmbedder":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self) -> None:
        self._extractor = None
        self._remote_client = None
        self._remote_url = ""
        self._load()

    def _load(self) -> None:
        from noble_agent.config import settings

        if settings.speaker_remote_url:
            import httpx

            self._remote_url = settings.speaker_remote_url.rstrip("/")
            headers = {}
            if settings.speaker_remote_token:
                headers["Authorization"] = f"Bearer {settings.speaker_remote_token}"
            self._remote_client = httpx.Client(timeout=settings.speaker_remote_timeout, headers=headers or None)
            logger.info("Speaker verification: remote mode → %s", self._remote_url)
            return
        self._extractor = _get_extractor()

    def embed(self, pcm16: bytes) -> np.ndarray | None:
        if not pcm16:
            return None
        if self._remote_client is not None:
            return self._embed_remote(pcm16)
        return self._embed_local(pcm16)

    def _embed_remote(self, pcm16: bytes) -> np.ndarray | None:
        import base64

        try:
            resp = self._remote_client.post(
                f"{self._remote_url}/embed",
                json={"audio_b64": base64.b64encode(pcm16).decode("ascii")},
            )
            resp.raise_for_status()
            return np.array(resp.json()["embedding"], dtype=np.float32)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Speaker] remote embed failed: %s", exc)
            return None

    def _embed_local(self, pcm16: bytes) -> np.ndarray | None:
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        stream = self._extractor.create_stream()
        stream.accept_waveform(16000, samples)
        stream.input_finished()
        if not self._extractor.is_ready(stream):
            return None
        return np.array(self._extractor.compute(stream), dtype=np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_speaker_embedder.py -v && make test-unit`
Expected: PASS. (`make test-unit` must still collect without `sherpa_onnx`/`httpx` installed because those imports are function-local.)

- [ ] **Step 5: Lint + commit**

```bash
make lint && git add src/noble_agent/voice/speaker_verifier.py tests/unit/test_speaker_embedder.py
git commit -m "feat(voice): SpeakerEmbedder — local sherpa + remote client + HF provision"
```

---

### Task 7: Wire speaker verification into `_on_final`

**Files:**
- Modify: `src/noble_agent/server/base_session.py` (`__init__`, `_on_final`, add `_utterance_duration` helper)
- Test: `tests/unit/test_speaker_gate_helpers.py`

**Interfaces:**
- Consumes: `SpeakerVerifier` (Task 5), `SpeakerEmbedder` (Task 6), `settings` (Task 1).
- Produces: `self._speaker_verifier: SpeakerVerifier | None`; verification step in `_on_final` between echo-cooldown and smart-turn that drops mismatched speakers.

- [ ] **Step 1: Write the failing test (helper window math)**

```python
# tests/unit/test_speaker_gate_helpers.py
import math


def test_embed_window_bytes():
    # window seconds → bytes (int16 @ 16kHz). 3.0s → 96000 bytes.
    sample_rate = 16000
    window_sec = 3.0
    assert int(window_sec * sample_rate) * 2 == 96000


def test_hangover_chunk_math():
    assert math.ceil(300 / 32) == 10
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/unit/test_speaker_gate_helpers.py -v`
Expected: PASS (documents the byte/chunk math used in wiring).

- [ ] **Step 3: Wire into base_session**

In `base_session.py` imports add:

```python
from noble_agent.voice.speaker_verifier import SpeakerEmbedder, SpeakerVerifier
```

In `__init__` add (after `_input_gate`):

```python
        self._speaker_verifier = (
            SpeakerVerifier(
                match_threshold=settings.speaker_match_threshold,
                adapt_enabled=settings.speaker_adapt_enabled,
                adapt_weight=settings.speaker_adapt_weight,
            )
            if settings.speaker_verification_enabled
            else None
        )
```

In `_on_final`, immediately AFTER the echo-cooldown block (`if not self._echo_cooldown.allow_stt(): return`) and BEFORE the speaker/gender/smart-turn logic, insert:

```python
        if self._speaker_verifier is not None:
            verdict = await self._verify_speaker()
            if verdict is False:
                logger.info("[Speaker] Rejected non-primary speaker: %r", text)
                return
```

Add these helpers to the session class:

```python
    def _utterance_window_bytes(self) -> int:
        return int(settings.speaker_embed_window_sec * settings.stt_sample_rate) * 2

    async def _verify_speaker(self) -> bool | None:
        """Embed the recent utterance and verify against the enrolled centroid.

        Returns True (accept), False (reject), or None (could not decide → accept).
        Enrolls on the first valid utterance.
        """
        seg = bytes(self._audio_ring[-self._utterance_window_bytes() :])
        min_bytes = int(settings.speaker_min_enroll_sec * settings.stt_sample_rate) * 2
        try:
            embedder = SpeakerEmbedder.get_instance()
            emb = await asyncio.to_thread(embedder.embed, seg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Speaker] embed error: %s", exc)
            return None
        if emb is None:
            return None
        if not self._speaker_verifier.enrolled:
            if len(seg) >= min_bytes:
                self._speaker_verifier.enroll(emb)
            return True  # first utterance always passes
        ok, sim = self._speaker_verifier.verify(emb)
        logger.info("[Speaker] sim=%.3f thr=%.2f ok=%s", sim, settings.speaker_match_threshold, ok)
        if ok:
            self._speaker_verifier.maybe_adapt(emb)
        return ok
```

- [ ] **Step 4: Run the unit suite + lint**

Run: `pytest tests/unit/test_speaker_gate_helpers.py -v && make test-unit`
Expected: PASS; no collection errors.

- [ ] **Step 5: Manual smoke + commit**

With `SPEAKER_VERIFICATION_ENABLED=false` confirm zero behavior change (text-chat + voice). With `=true` (remote service up, or local model present) confirm a second voice is dropped per logs. Follow `src/noble_agent/SMOKE.md`.

```bash
make lint && git add src/noble_agent/server/base_session.py tests/unit/test_speaker_gate_helpers.py
git commit -m "feat(session): speaker verification gate in _on_final (opt-in)"
```

---

### Task 8: Remote speaker service + console script

**Files:**
- Create: `src/noble_agent/voice/service/speaker_server.py`
- Modify: `pyproject.toml` (`[project.scripts]` add `noble-speaker-service`)
- Test: `tests/unit/test_speaker_server.py`

**Interfaces:**
- Consumes: `SpeakerEmbedder` local singleton (Task 6).
- Produces: an HTTP endpoint `POST /embed {"audio_b64": ...} -> {"embedding": [...]}`; console entrypoint `noble-speaker-service`.

- [ ] **Step 1: Write the failing test (handler logic, no server)**

```python
# tests/unit/test_speaker_server.py
import base64

import numpy as np

import noble_agent.voice.service.speaker_server as srv


def test_embed_payload_roundtrip(monkeypatch):
    class _FakeEmbedder:
        def embed(self, pcm16):
            assert pcm16 == b"\x01\x00"
            return np.array([0.5, 0.5], dtype=np.float32)

    monkeypatch.setattr(srv, "_embedder", _FakeEmbedder())
    out = srv._handle_embed({"audio_b64": base64.b64encode(b"\x01\x00").decode("ascii")})
    assert out == {"embedding": [0.5, 0.5]}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_speaker_server.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write the service**

```python
# src/noble_agent/voice/service/speaker_server.py
"""Resident speaker-embedding HTTP service.

Mirrors the remote STT/TTS service pattern: wraps the local SpeakerEmbedder
singleton so the GPU/CPU model loads once and the worker talks to it over HTTP
(SPEAKER_REMOTE_URL). Contract: POST /embed {"audio_b64": ...} -> {"embedding": [...]}.
"""

from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)

_embedder = None


def _get_embedder():
    global _embedder
    if _embedder is None:
        from noble_agent.voice.speaker_verifier import SpeakerEmbedder

        # Force LOCAL mode in the service even if SPEAKER_REMOTE_URL is set for workers.
        emb = SpeakerEmbedder.__new__(SpeakerEmbedder)
        emb._remote_client = None
        emb._remote_url = ""
        from noble_agent.voice.speaker_verifier import _get_extractor

        emb._extractor = _get_extractor()
        _embedder = emb
    return _embedder


def _handle_embed(payload: dict) -> dict:
    pcm16 = base64.b64decode(payload["audio_b64"])
    emb = _embedder.embed(pcm16)
    return {"embedding": [] if emb is None else [float(x) for x in emb]}


def run_server() -> None:
    import uvicorn
    from fastapi import FastAPI

    app = FastAPI()
    _get_embedder()  # warm at boot

    @app.post("/embed")
    async def embed(payload: dict):  # noqa: ANN001
        return _handle_embed(payload)

    from noble_agent.config import settings

    host = getattr(settings, "speaker_service_host", "0.0.0.0")
    port = int(getattr(settings, "speaker_service_port", 9100))
    logger.info("Speaker service on %s:%d", host, port)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    run_server()
```

Add to `pyproject.toml` under `[project.scripts]`:

```toml
noble-speaker-service = "noble_agent.voice.service.speaker_server:run_server"
```

Add to `config.py` (Audio/service area):

```python
    speaker_service_host: str = "0.0.0.0"
    speaker_service_port: int = 9100
```

- [ ] **Step 4: Run test + lint**

Run: `pytest tests/unit/test_speaker_server.py -v && make test-unit`
Expected: PASS; `_handle_embed` works with the injected fake.

- [ ] **Step 5: Commit**

```bash
make lint && git add src/noble_agent/voice/service/speaker_server.py src/noble_agent/config.py pyproject.toml tests/unit/test_speaker_server.py
git commit -m "feat(service): noble-speaker-service remote embedding endpoint"
```

---

### Task 9: Prewarm the local speaker model at boot

**Files:**
- Modify: `src/noble_agent/voice/prewarm.py`
- Test: `tests/unit/test_speaker_prewarm.py`

**Interfaces:**
- Consumes: `settings`; `_get_extractor` (Task 6).
- Produces: a guarded eager load inside `prewarm_voice_models()` (gated on `speaker_verification_enabled and not speaker_remote_url`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_speaker_prewarm.py
import noble_agent.voice.prewarm as pw


def test_speaker_prewarm_skipped_in_remote_mode(monkeypatch):
    monkeypatch.setattr(pw.settings, "speaker_verification_enabled", True, raising=False)
    monkeypatch.setattr(pw.settings, "speaker_remote_url", "http://svc", raising=False)
    called = {"n": 0}
    # If prewarm tries to load the local extractor in remote mode, this would bump.
    import noble_agent.voice.speaker_verifier as sv

    monkeypatch.setattr(sv, "_get_extractor", lambda: called.__setitem__("n", called["n"] + 1))
    pw.prewarm_voice_models()
    assert called["n"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_speaker_prewarm.py -v`
Expected: FAIL if prewarm has no speaker guard yet (or PASS trivially if the existing function never touches speaker — in that case the test still guards against a future regression once Step 3 adds the block; proceed).

- [ ] **Step 3: Add the guarded warm**

In `prewarm.py::prewarm_voice_models()`, after the existing STT/TTS warm blocks, add:

```python
    if settings.speaker_verification_enabled and not settings.speaker_remote_url:
        try:
            from noble_agent.voice.speaker_verifier import _get_extractor

            _get_extractor()
            logger.info("[prewarm] speaker embedding model ready")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[prewarm] speaker model load failed (continuing): %s", exc)
```

- [ ] **Step 4: Run test + lint**

Run: `pytest tests/unit/test_speaker_prewarm.py -v && make test-unit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
make lint && git add src/noble_agent/voice/prewarm.py tests/unit/test_speaker_prewarm.py
git commit -m "feat(prewarm): eager-load local speaker model when enabled"
```

---

### Task 10: `.env` / `.env.example` + CLAUDE.md + Change Log

**Files:**
- Modify: `.env`, `.env.example`, `CLAUDE.md`

**Interfaces:** none (docs/config only).

- [ ] **Step 1: Add the vars to `.env.example`**

Append a documented block:

```bash
# ── STT input gate (Problem: noise → garbage text) ────────────────────────────
STT_INPUT_GATE_MODE=off          # off | rms | vad
AUDIO_GATE_PREROLL_CHUNKS=3       # K-chunk lead-in lookback (all modes)
AUDIO_GATE_MIN_RMS=160           # (rms) per-frame energy threshold
AUDIO_GATE_REQUIRED_CONSECUTIVE=3 # (rms) consecutive frames to confirm speech
AUDIO_GATE_BARGE_IN_RMS=2400     # (rms) high-energy barge-in threshold
STT_VAD_GATE_HANGOVER_MS=300     # (vad) keep gate open after speech ends

# ── Speaker verification (Problem: other speakers) ────────────────────────────
SPEAKER_VERIFICATION_ENABLED=false
SPEAKER_REMOTE_URL=               # set → remote (default); empty → local sherpa
SPEAKER_REMOTE_TIMEOUT=3.0
SPEAKER_REMOTE_TOKEN=
SPEAKER_MODEL_DIR=models/speaker
SPEAKER_MODEL_NAME=3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx
SPEAKER_HF_REPO=csukuangfj/speaker-embedding-models
SPEAKER_HF_REVISION=prod
SPEAKER_MATCH_THRESHOLD=0.5
SPEAKER_MIN_ENROLL_SEC=1.0
SPEAKER_EMBED_WINDOW_SEC=3.0
SPEAKER_ADAPT_ENABLED=false
SPEAKER_ADAPT_WEIGHT=0.1
```

- [ ] **Step 2: Mirror into `.env`** with the operator's chosen values (set `STT_INPUT_GATE_MODE` and `SPEAKER_*` to whatever is being tuned; default `SPEAKER_REMOTE_URL` to the running service URL if remote-default is desired). Confirm no inline `KEY=  # comment` traps (python-dotenv parses the comment as the value — put comments on their own line).

- [ ] **Step 3: Update CLAUDE.md**

- In the STT backends paragraph, document that the Silero VAD now optionally gates STT input (`STT_INPUT_GATE_MODE=vad`) in addition to driving interrupts, and that `rms` mode replaces the removed `AUDIO_GUARD_FRAMES_GATE_ENABLED` flag; mention the pre-roll lookback.
- Add a short "Speaker verification" subsection under pluggable backends: opt-in `SPEAKER_VERIFICATION_ENABLED`, remote-default/local-fallback (sherpa `SpeakerEmbeddingExtractor`), enroll-once on first valid utterance, drop on cosine mismatch, runs at `_on_final` off the event loop.
- Add the new env vars to the Key configuration table.
- Append a Change Log row dated `2026-06-30` summarizing both layers and the branch `feat/seperate-service`.

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md && git commit -m "docs: document STT input gate + speaker verification"
# .env is gitignored — do not add it.
```

---

## Self-Review

**Spec coverage:**
- Part 1 input gate (off/rms/vad) → Tasks 1,2,3,4. ✓
- Pre-roll lookback → Task 3 (logic + tests) + Task 4 (wiring). ✓
- Remove `audio_guard_frames_gate_enabled` → Task 1 (replaced) + Task 4 (wiring). ✓
- Part 2 SpeakerVerifier enroll/verify/adapt → Task 5. ✓
- SpeakerEmbedder remote-default/local + HF provision → Task 6. ✓
- Wire verify at `_on_final` after echo-cooldown, before smart-turn, thread-offloaded → Task 7. ✓
- Remote service + console script → Task 8. ✓
- Prewarm guarded on enabled+local → Task 9. ✓
- All env vars + CLAUDE.md + Change Log → Tasks 1 & 10. ✓
- Tests without model/network → Tasks 2,3,5,6,7,8,9 use injection/mocks/pure logic. ✓

**Placeholder scan:** No TBD/TODO; concrete model name, repo, contract, and code in every step. ✓

**Type consistency:** `SttInputGate.gate -> list[bytes]`, `feed_vad(bool)`, `from_settings(settings)`; `SpeakerVerifier.verify -> tuple[bool, float]`, `enroll/maybe_adapt(np.ndarray)`; `SpeakerEmbedder.embed(bytes) -> np.ndarray | None`; service `_handle_embed(dict) -> dict`. Names match across Tasks 3–9. ✓

**Open item (flagged in spec):** `SPEAKER_HF_REPO`/`SPEAKER_MODEL_NAME` default to the public sherpa CAM++ model. If the operator wants it mirrored under `NobleX-AI/`, change only those two env values — no code change.
