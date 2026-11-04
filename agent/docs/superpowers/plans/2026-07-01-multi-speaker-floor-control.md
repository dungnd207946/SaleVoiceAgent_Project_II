# Multi-Speaker Floor Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `multi` speaker policy where multiple people take turns with the agent, but only the current asker may interrupt the agent's TTS; the floor reopens when the agent finishes.

**Architecture:** A `SPEAKER_MODE` selector (`off`/`single`/`multi`) replaces the shipped bool. `multi` adds a pure `SpeakerFloor` (per-turn asker embedding) plus a deferred-interrupt state machine in `BaseSession`: identity is decided by our `SpeakerEmbedder` on the per-utterance PCM buffer (`_utterance_pcm`) — never STT diarization — so it is backend-agnostic (sherpa + Soniox). Lives in `base_session`, shared by browser (aiortc) and LiveKit.

**Tech Stack:** Python 3.11–3.13, numpy, `sherpa-onnx`/httpx (function-local), pytest (`asyncio_mode=auto`), ruff.

## Global Constraints

- Work only in `src/noble_agent/` (+ named test/env/doc files). Active package `noble_agent`.
- Branch `feat/seperate-service`. Local commits only; never touch `develop`; no push/PR/new branch.
- Ruff: line-length 120, target py311, rules `E,F,W,I,UP,B,SIM`. Run `make lint` + `make format` on changed files (the branch has ~pre-existing lint issues on OTHER files — only changed files must be clean).
- Pytest `asyncio_mode=auto`; use `.venv/bin/pytest`. No NEW test failures (branch has ~5 pre-existing failures in `test_base_session.py` + others; report before/after deltas). Unit tests must NOT need a model/network — stub/inject.
- Identity is ALWAYS via `SpeakerEmbedder` on raw PCM (`_utterance_pcm`); NO branch on the STT backend or the STT `speaker` label. Backend-agnostic is a hard requirement.
- Heavy imports stay function-local. Embedding ALWAYS via `asyncio.to_thread` (never block the event loop).
- Audio: PCM int16, 16 kHz, mono; `settings.stt_sample_rate == 16000`.
- `off` and `single` behavior MUST be unchanged (regression guard).
- Scope: `BaseSession` only (browser + LiveKit). Do NOT touch `telephony/`.
- Run `src/noble_agent/SMOKE.md` after the interrupt-path task.

**Current-code anchors (verified):**
- `BaseSession.__init__` builds `self._speaker_verifier` at `server/base_session.py:123-131` (gated on `settings.speaker_verification_enabled`).
- `process_audio_frame` VAD loop + interrupt at `:376-406`; `_utterance_pcm` accumulation at `:395-403`.
- `_handle_interrupt` at `:408-438` (guards `if not self._agent_task or self._agent_task.done(): return`).
- `_on_final` at `:447-498`; existing speaker block at `:465-469`.
- `_trigger_agent_for_text` at `:500-522`; agent turn runs in `_run_agent` at `:658-678`, whose `finally` (`:670-672`) sets `vad.set_idle()` — the agent-done point.
- `_verify_speaker` (single) at `:625-651`; embeds `bytes(self._utterance_pcm)`.

---

### Task 1: `SpeakerFloor` pure class

**Files:**
- Modify: `src/noble_agent/voice/speaker_verifier.py` (append; do not touch `SpeakerVerifier`/`SpeakerEmbedder`)
- Test: `tests/unit/test_speaker_floor.py`

**Interfaces:**
- Consumes: `_normalize`, `_cosine` (already in the file, from the shipped speaker feature).
- Produces:
  - `class SpeakerFloor`
    - `set_asker(emb: np.ndarray) -> None`
    - `clear_asker() -> None`
    - property `has_asker: bool`
    - `matches_asker(emb: np.ndarray, threshold: float) -> bool` (returns `False` when no asker)

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_speaker_floor.py
import numpy as np

from noble_agent.voice.speaker_verifier import SpeakerFloor


def test_no_asker_matches_nothing():
    f = SpeakerFloor()
    assert f.has_asker is False
    assert f.matches_asker(np.array([1.0, 0.0], dtype=np.float32), 0.5) is False


def test_set_asker_then_match_same_and_reject_different():
    f = SpeakerFloor()
    f.set_asker(np.array([1.0, 0.0, 0.0], dtype=np.float32))
    assert f.has_asker is True
    assert f.matches_asker(np.array([0.9, 0.1, 0.0], dtype=np.float32), 0.5) is True
    assert f.matches_asker(np.array([0.0, 1.0, 0.0], dtype=np.float32), 0.5) is False


def test_clear_asker_reopens_floor():
    f = SpeakerFloor()
    f.set_asker(np.array([1.0, 0.0], dtype=np.float32))
    f.clear_asker()
    assert f.has_asker is False
    assert f.matches_asker(np.array([1.0, 0.0], dtype=np.float32), 0.5) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_speaker_floor.py -v`
Expected: FAIL with `ImportError: cannot import name 'SpeakerFloor'`.

- [ ] **Step 3: Append the implementation**

Append to `src/noble_agent/voice/speaker_verifier.py`:

```python
class SpeakerFloor:
    """Per-turn asker identity for multi-speaker mode.

    Holds the embedding of the speaker who owns the current agent turn (the
    "asker"). While an asker is set, only a matching embedding may interrupt;
    clearing it (agent turn done) reopens the floor to any speaker. Pure vector
    logic — no model, no I/O.
    """

    def __init__(self) -> None:
        self._asker: np.ndarray | None = None

    @property
    def has_asker(self) -> bool:
        return self._asker is not None

    def set_asker(self, emb: np.ndarray) -> None:
        self._asker = _normalize(emb)

    def clear_asker(self) -> None:
        self._asker = None

    def matches_asker(self, emb: np.ndarray, threshold: float) -> bool:
        if self._asker is None:
            return False
        return _cosine(self._asker, emb) >= threshold
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_speaker_floor.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Lint + commit**

```bash
make lint && git add src/noble_agent/voice/speaker_verifier.py tests/unit/test_speaker_floor.py
git commit -m "feat(voice): SpeakerFloor — per-turn asker identity for multi-speaker"
```

---

### Task 2: Config `SPEAKER_MODE` + resolver + wire mode into session/prewarm

**Files:**
- Modify: `src/noble_agent/config.py`
- Modify: `src/noble_agent/server/base_session.py:123-131` (`__init__`)
- Modify: `src/noble_agent/voice/prewarm.py` (speaker gate)
- Test: `tests/unit/test_config_gate_speaker.py` (extend), `tests/unit/test_base_session.py` (adapt legacy-flag refs)

**Interfaces:**
- Consumes: `SpeakerFloor` (Task 1), `SpeakerVerifier` (shipped).
- Produces: `settings.speaker_mode: str`, `settings.speaker_interrupt_min_sec: float`, `config.resolve_speaker_mode() -> str`; `self._speaker_mode: str`, `self._speaker_floor: SpeakerFloor | None`, and the dormant multi-state fields `self._interrupt_episode_active: bool`, `self._interrupt_embed_inflight: bool`, `self._suppress_utterance: bool`; helper `self._agent_is_speaking() -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/test_config_gate_speaker.py
from noble_agent import config as cfg


def test_speaker_mode_defaults():
    from noble_agent.config import settings
    assert settings.speaker_mode == "off"
    assert settings.speaker_interrupt_min_sec == 0.8


def test_resolve_speaker_mode_legacy_bool(monkeypatch):
    s = cfg.get_settings()
    monkeypatch.setattr(s, "speaker_mode", "off", raising=False)
    monkeypatch.setattr(s, "speaker_verification_enabled", True, raising=False)
    assert cfg.resolve_speaker_mode() == "single"


def test_resolve_speaker_mode_explicit(monkeypatch):
    s = cfg.get_settings()
    monkeypatch.setattr(s, "speaker_mode", "multi", raising=False)
    monkeypatch.setattr(s, "speaker_verification_enabled", False, raising=False)
    assert cfg.resolve_speaker_mode() == "multi"


def test_resolve_speaker_mode_unknown_falls_off(monkeypatch):
    s = cfg.get_settings()
    monkeypatch.setattr(s, "speaker_mode", "bogus", raising=False)
    monkeypatch.setattr(s, "speaker_verification_enabled", False, raising=False)
    assert cfg.resolve_speaker_mode() == "off"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_config_gate_speaker.py -k "speaker_mode or resolve_speaker" -v`
Expected: FAIL (`AttributeError` / no `resolve_speaker_mode`).

- [ ] **Step 3: Config changes**

In `config.py`, KEEP the existing `speaker_verification_enabled: bool = False` (now deprecated — read only by the resolver) and add next to it:

```python
    # Speaker policy. "off" | "single" | "multi". Replaces speaker_verification_enabled
    # (legacy true → resolved to "single" by config.resolve_speaker_mode()).
    speaker_mode: str = "off"
    speaker_interrupt_min_sec: float = 0.8  # (multi) interrupter audio to collect before embed/decide
```

At module level in `config.py`, add (NOTE: `config.py` exposes settings via a lazy singleton `get_settings()` + a module `__getattr__`, NOT a static module `settings` variable — the resolver MUST call `get_settings()`):

```python
def resolve_speaker_mode() -> str:
    """Effective speaker policy: SPEAKER_MODE, with legacy SPEAKER_VERIFICATION_ENABLED=true → 'single'."""
    s = get_settings()
    mode = (s.speaker_mode or "off").strip().lower()
    if mode not in ("off", "single", "multi"):
        mode = "off"
    if mode == "off" and s.speaker_verification_enabled:
        mode = "single"
    return mode
```

- [ ] **Step 4: Wire mode into `base_session.__init__`**

Replace `server/base_session.py:123-131` (the `self._speaker_verifier = (...)` block) with:

```python
        self._speaker_mode = resolve_speaker_mode()
        if self._speaker_mode == "off" and settings.speaker_verification_enabled:
            logger.warning("SPEAKER_VERIFICATION_ENABLED is deprecated — use SPEAKER_MODE=single.")
        self._speaker_verifier = (
            SpeakerVerifier(
                match_threshold=settings.speaker_match_threshold,
                adapt_enabled=settings.speaker_adapt_enabled,
                adapt_weight=settings.speaker_adapt_weight,
            )
            if self._speaker_mode == "single"
            else None
        )
        self._speaker_floor = SpeakerFloor() if self._speaker_mode == "multi" else None
        # Multi-mode deferred-interrupt state (single-writer: pipeline loop).
        self._interrupt_episode_active = False
        self._interrupt_embed_inflight = False
        self._suppress_utterance = False
```

Add imports at the top of `base_session.py` (with the other voice imports):

```python
from noble_agent.config import resolve_speaker_mode
from noble_agent.voice.speaker_verifier import SpeakerEmbedder, SpeakerFloor, SpeakerVerifier
```

(The `SpeakerEmbedder, SpeakerVerifier` import already exists — extend it to include `SpeakerFloor`; add the `resolve_speaker_mode` import. `settings` is already imported.)

IMPORTANT — `_utterance_pcm` accumulation currently gates on `self._speaker_verifier is not None` (`:397,399`). Change BOTH those conditions to also cover multi mode: `if self._speaker_verifier is not None or self._speaker_floor is not None:` (multi needs the buffer too). Do this in `process_audio_frame` at `:397` and `:399`.

Add the helper method (near `_handle_interrupt`):

```python
    def _agent_is_speaking(self) -> bool:
        return self._agent_task is not None and not self._agent_task.done()
```

- [ ] **Step 5: Wire mode into `prewarm.py`**

In `voice/prewarm.py`, the speaker warm block currently gates on `settings.speaker_verification_enabled and not settings.speaker_remote_url`. Change the gate to use the resolver:

```python
    from noble_agent.config import resolve_speaker_mode

    if resolve_speaker_mode() in ("single", "multi") and not settings.speaker_remote_url:
        try:
            from noble_agent.voice.speaker_verifier import _get_extractor

            _get_extractor()
            logger.info("[prewarm] speaker embedding model ready")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[prewarm] speaker model load failed (continuing): %s", exc)
```

(Keep the import function-local as shown.)

- [ ] **Step 6: Adapt existing tests that referenced the old bool / verifier gate**

Run `.venv/bin/pytest tests/unit/test_base_session.py -v` and fix any test that set `speaker_verification_enabled` to toggle the verifier: for `single`-mode tests set `mock_settings.speaker_mode = "single"`; for the off default leave `speaker_mode = "off"`. The `mock_settings` SimpleNamespace must now also carry `speaker_mode` and `speaker_interrupt_min_sec` attributes (add them to the fixture with defaults `"off"` / `0.8`). Do NOT delete coverage — re-express intent via `speaker_mode`.

- [ ] **Step 7: Run tests + lint**

Run: `.venv/bin/pytest tests/unit/test_config_gate_speaker.py tests/unit/test_base_session.py -v && make test-unit`
Expected: new config tests pass; `test_base_session.py` shows no NEW failures vs the ~5 pre-existing. Report before/after counts.

- [ ] **Step 8: Commit**

```bash
make lint && git add src/noble_agent/config.py src/noble_agent/server/base_session.py src/noble_agent/voice/prewarm.py tests/unit/test_config_gate_speaker.py tests/unit/test_base_session.py
git commit -m "feat(config): SPEAKER_MODE selector (off/single/multi) + resolver; wire into session/prewarm"
```

---

### Task 3: Asker lifecycle + `_on_final` multi gate

**Files:**
- Modify: `src/noble_agent/server/base_session.py` (`_on_final`, `_run_agent` finally, new `_set_asker_from_utterance` helper)
- Test: `tests/unit/test_base_session.py`

**Interfaces:**
- Consumes: `self._speaker_floor`, `self._agent_is_speaking()`, `self._suppress_utterance`, `self._utterance_pcm`, `SpeakerEmbedder` (Task 2); `SpeakerFloor.set_asker/clear_asker/matches_asker` (Task 1).
- Produces: multi-mode drop-non-asker behavior in `_on_final`; asker set on floor-open accept; asker cleared on agent-done.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/test_base_session.py inside a new TestMultiSpeakerGate class
# (follow the file's existing fixture/patched-collaborators pattern; set
#  cols["settings"].speaker_mode = "multi").
#
# Test A: agent NOT speaking + multi → utterance accepted (agent triggered),
#         and floor.set_asker called with the embedded utterance.
# Test B: agent speaking + non-asker (floor.matches_asker → False) → _on_final
#         returns WITHOUT calling _trigger_agent_for_text.
# Test C: _suppress_utterance=True → _on_final drops (returns) and resets the flag.
# Test D: agent-done (_run_agent finally) calls floor.clear_asker().
#
# Use an injected fake SpeakerEmbedder (monkeypatch SpeakerEmbedder.get_instance
# to return an object whose .embed returns a fixed np.ndarray) and a stub floor
# (monkeypatch session._speaker_floor with a Mock exposing has_asker/
# matches_asker/set_asker/clear_asker). Assert on _trigger_agent_for_text
# (patch it to record calls) and on floor method calls. Do NOT load a model.
```

Write the four tests concretely against the harness (mirror `TestSpeakerVerificationWiring` / `TestUtterancePcmBuffer` already in the file for the exact fixture calls).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_base_session.py -k MultiSpeaker -v`
Expected: FAIL (behavior not implemented).

- [ ] **Step 3: Add the asker-embed helper**

Add to `BaseSession` (near `_verify_speaker`):

```python
    async def _embed_current_utterance(self) -> "np.ndarray | None":
        """Embed the current per-utterance PCM span off the event loop."""
        seg = bytes(self._utterance_pcm)  # snapshot before await (concurrent clear-safe)
        if not seg:
            return None
        try:
            return await asyncio.to_thread(SpeakerEmbedder.get_instance().embed, seg)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Speaker] embed error: %s", exc)
            return None
```

- [ ] **Step 4: Insert the multi gate into `_on_final`**

In `_on_final`, replace the shipped speaker block at `:465-469`:

```python
        if self._speaker_verifier is not None:
            verdict = await self._verify_speaker()
            if verdict is False:
                logger.info("[Speaker] Rejected non-primary speaker: %r", text)
                return
```

with:

```python
        if self._speaker_verifier is not None:  # single mode
            verdict = await self._verify_speaker()
            if verdict is False:
                logger.info("[Speaker] Rejected non-primary speaker: %r", text)
                return

        if self._speaker_floor is not None:  # multi mode
            if self._suppress_utterance:
                self._suppress_utterance = False
                logger.info("[Speaker] Dropped non-asker (interrupt-rejected) utterance: %r", text)
                return
            if self._agent_is_speaking():
                emb = await self._embed_current_utterance()
                if emb is not None and not self._speaker_floor.matches_asker(
                    emb, settings.speaker_match_threshold
                ):
                    logger.info("[Speaker] Dropped non-asker final mid-turn: %r", text)
                    return
            else:
                emb = await self._embed_current_utterance()
                if emb is not None:
                    self._speaker_floor.set_asker(emb)  # floor open → this speaker owns the new turn
```

- [ ] **Step 5: Clear asker on agent-done**

In `_run_agent`'s `finally` block (`:670-672`), after `self.vad.set_idle()`, add:

```python
            if self._speaker_floor is not None:
                self._speaker_floor.clear_asker()
```

- [ ] **Step 6: Run tests + lint**

Run: `.venv/bin/pytest tests/unit/test_base_session.py -k "MultiSpeaker or SpeakerVerification or UtterancePcm" -v && make test-unit`
Expected: new tests pass; no new failures; single-mode + off-mode tests still green.

- [ ] **Step 7: Commit**

```bash
make lint && git add src/noble_agent/server/base_session.py tests/unit/test_base_session.py
git commit -m "feat(session): multi-speaker asker lifecycle + _on_final non-asker gate"
```

---

### Task 4: Deferred interrupt state machine (multi)

**Files:**
- Modify: `src/noble_agent/server/base_session.py` (`process_audio_frame` interrupt branch + accumulation trigger; new `_begin_interrupt_episode`, `_evaluate_interrupt_candidate`)
- Test: `tests/unit/test_base_session.py`

**Interfaces:**
- Consumes: `self._speaker_floor`, `self._agent_is_speaking()`, `self._interrupt_episode_active`, `self._interrupt_embed_inflight`, `self._suppress_utterance`, `self._utterance_pcm`, `self._embed_current_utterance()` (Task 3), `self._handle_interrupt()`, `self.vad.set_speaking()`.
- Produces: asker-gated barge-in — a matching interrupter triggers `_handle_interrupt`; a non-matching one is suppressed (agent keeps speaking).

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/unit/test_base_session.py (TestMultiSpeakerInterrupt)
# Test A: multi + agent speaking + candidate embedding matches asker →
#         _evaluate_interrupt_candidate calls _handle_interrupt (patch it, assert called);
#         episode + inflight flags reset to False afterward.
# Test B: multi + agent speaking + candidate does NOT match asker →
#         _handle_interrupt NOT called; _suppress_utterance set True; vad.set_speaking called;
#         flags reset.
# Test C: off/single mode → VAD INTERRUPTED still calls _handle_interrupt immediately
#         (regression: _begin_interrupt_episode path not taken).
#
# Drive _evaluate_interrupt_candidate directly with a stubbed floor
# (matches_asker → True / False) and a fake embedder; assert on a patched
# _handle_interrupt and on the flags / vad.set_speaking. No model.
```

Write these concretely against the harness.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_base_session.py -k MultiSpeakerInterrupt -v`
Expected: FAIL.

- [ ] **Step 3: Gate the interrupt branch in `process_audio_frame`**

Replace `server/base_session.py:386-387`:

```python
            if result["state"] == VADState.INTERRUPTED:
                await self._handle_interrupt()
```

with:

```python
            if result["state"] == VADState.INTERRUPTED:
                if self._speaker_floor is not None:  # multi: defer until asker is identified
                    self._begin_interrupt_episode()
                else:
                    await self._handle_interrupt()
```

After the STT gate/forward block (right before `self._audio_ring_append(data)` at `:406`), add the accumulation trigger:

```python
        # Multi mode: once we have enough of the interrupter's audio, identify them.
        if (
            self._speaker_floor is not None
            and self._interrupt_episode_active
            and not self._interrupt_embed_inflight
        ):
            min_bytes = int(settings.speaker_interrupt_min_sec * settings.stt_sample_rate) * 2
            if len(self._utterance_pcm) >= min_bytes:
                self._interrupt_embed_inflight = True
                asyncio.ensure_future(self._evaluate_interrupt_candidate())
```

- [ ] **Step 4: Add the episode methods**

```python
    def _begin_interrupt_episode(self) -> None:
        """Multi mode: a speaker started over the agent — collect audio, decide later.

        Do NOT cancel the agent yet; only the asker may interrupt, and we cannot
        know who this is until ~speaker_interrupt_min_sec of audio is embedded.
        """
        if not self._agent_is_speaking():
            return
        self._interrupt_episode_active = True

    async def _evaluate_interrupt_candidate(self) -> None:
        """Embed the interrupter and honor the barge-in only if it is the asker."""
        emb = await self._embed_current_utterance()
        try:
            if emb is not None and self._speaker_floor.matches_asker(emb, settings.speaker_match_threshold):
                await self._handle_interrupt()  # asker barge-in honored (delayed by the ID window)
            else:
                self._suppress_utterance = True  # non-asker: drop their final if it lands mid-turn
                self.vad.set_speaking()  # keep the agent-speaking VAD state to watch for the asker
                logger.info("[Speaker] Ignored non-asker interrupt; agent continues.")
        finally:
            self._interrupt_episode_active = False
            self._interrupt_embed_inflight = False
```

- [ ] **Step 5: Run tests + lint**

Run: `.venv/bin/pytest tests/unit/test_base_session.py -k "MultiSpeaker or SpeakerVerification or UtterancePcm" -v && make test-unit`
Expected: new tests pass; off/single interrupt path unchanged; no new failures.

- [ ] **Step 6: Manual smoke + commit**

Run `src/noble_agent/SMOKE.md` interrupt/barge-in path with `SPEAKER_MODE=off` (immediate barge-in, unchanged) and `=multi` (only the asker's barge-in cuts the agent).

```bash
make lint && git add src/noble_agent/server/base_session.py tests/unit/test_base_session.py
git commit -m "feat(session): multi-speaker deferred interrupt — only the asker may barge in"
```

---

### Task 5: `.env` / `.env.example` + CLAUDE.md

**Files:**
- Modify: `.env.example`, `.env` (gitignored — edit, do NOT commit), `CLAUDE.md`

**Interfaces:** none (docs/config only).

- [ ] **Step 1: `.env.example`**

Replace the `SPEAKER_VERIFICATION_ENABLED=false` line in the speaker block with:

```bash
# ── Speaker policy ────────────────────────────────────────────────────────────
# off | single | multi. single = one enrolled primary (drop others).
# multi = turn-taking; only the current asker may interrupt agent TTS.
SPEAKER_MODE=off
SPEAKER_INTERRUPT_MIN_SEC=0.8    # (multi) interrupter audio collected before speaker ID
```

Keep the rest of the `SPEAKER_*` block unchanged. Add a one-line deprecation note above the old var if it is still present, or remove the `SPEAKER_VERIFICATION_ENABLED` line (the resolver still honors it if set, but `SPEAKER_MODE` is authoritative).

- [ ] **Step 2: `.env`** — mirror: add `SPEAKER_MODE=off` and `SPEAKER_INTERRUPT_MIN_SEC=0.8` (safe defaults; comments on their OWN lines — no inline `KEY=  # comment` traps). Remove or comment out the old `SPEAKER_VERIFICATION_ENABLED` line. Do NOT `git add` `.env`.

- [ ] **Step 3: CLAUDE.md**

- In the Speaker verification section: replace `SPEAKER_VERIFICATION_ENABLED` with `SPEAKER_MODE` (`off`/`single`/`multi`); document `multi` (turn-taking, asker-only interrupt while agent speaks, floor reopens on agent-done, identity via `SpeakerEmbedder` on `_utterance_pcm` so it is **backend-agnostic — works with sherpa AND soniox**), the `SPEAKER_INTERRUPT_MIN_SEC` barge-in latency trade-off, and that telephony is out of scope.
- Key configuration table: add `SPEAKER_MODE`, `SPEAKER_INTERRUPT_MIN_SEC`; note `SPEAKER_VERIFICATION_ENABLED` is deprecated (→ `single`).
- Append ONE Change Log row dated 2026-07-01 summarizing multi-speaker floor control + the SPEAKER_MODE migration + branch `feat/seperate-service`.

- [ ] **Step 4: Commit**

```bash
git add .env.example CLAUDE.md && git commit -m "docs: SPEAKER_MODE + multi-speaker floor control"
# .env is gitignored — do not add it.
```

---

## Self-Review

**Spec coverage:**
- `SPEAKER_MODE=off|single|multi` replacing the bool + resolver → Task 2. ✓
- `SpeakerFloor` (per-turn asker) → Task 1. ✓
- Backend-agnostic identity via `SpeakerEmbedder` on `_utterance_pcm`, no STT-label branch → Tasks 3 & 4 (embed helper), Global Constraints. ✓
- `multi`: idle → any speaker accepted + becomes asker → Task 3 (floor-open set_asker). ✓
- `multi`: agent speaking → non-asker `_on_final` dropped → Task 3. ✓
- `multi`: deferred interrupt, asker-only barge-in, agent keeps talking during ID, no match → ignore + suppress → Task 4. ✓
- Floor reopens on agent-done → Task 3 (`_run_agent` finally clear_asker). ✓
- `SPEAKER_INTERRUPT_MIN_SEC` → Tasks 2 & 4. ✓
- Backward-compat legacy bool → `single` + warning → Task 2. ✓
- off/single unchanged → Tasks 3/4 branch on `_speaker_floor`/`_speaker_verifier`; regression tests. ✓
- Scope base_session only; telephony untouched → Global Constraints + no telephony file in any task. ✓
- Docs + Change Log → Task 5. ✓

**Placeholder scan:** No TBD/TODO; complete code for every code step. Task 3 Step 1 / Task 4 Step 1 describe the tests to write against the existing harness rather than pasting harness-specific fixture code the implementer must read anyway — acceptable because the exact assertions and stubs are enumerated and the file already contains mirror examples (`TestSpeakerVerificationWiring`, `TestUtterancePcmBuffer`) to copy the fixture calls from.

**Type consistency:** `SpeakerFloor.set_asker/clear_asker/has_asker/matches_asker(emb, threshold)` identical across Tasks 1/3/4. `_embed_current_utterance() -> np.ndarray | None`, `_agent_is_speaking() -> bool`, and the three `_interrupt_*`/`_suppress_utterance` flags defined in Task 2, used in Tasks 3/4. `resolve_speaker_mode()` defined Task 2, used in base_session + prewarm. ✓
