# Addressee Gate (chống nói leo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agent voice vừa interrupt được vừa không "nói leo": tiếng người kéo dài đè lên agent → soft-pause → phán đoán DIRECTED/SIDE_TALK → commit interrupt hoặc phát ack "Em xin phép được nói tiếp ạ" rồi phát lại clause đang dở.

**Architecture:** Classifier 2 tầng (heuristic thuần + LLM one-shot qua `StreamingClient.complete_once`, chọn qua `ADDRESSEE_GATE_MODE`) trong file mới `voice/addressee_gate.py`; pacer của `VoiceAgent` thêm soft-pause/resume (KHÔNG cancel task); `BaseSession` tổng quát hóa pattern interrupt-episode sẵn có của multi-speaker; telephony dùng chung `EpisodeTracker`. Spec: [docs/superpowers/specs/2026-08-12-addressee-gate-design.md](../specs/2026-08-12-addressee-gate-design.md).

**Tech Stack:** Python 3.11+, asyncio, pydantic-settings, pytest (`asyncio_mode=auto`), ruff (line-length 120).

## Global Constraints

- Branch: `feat/share-agent` — KHÔNG đụng `develop`, không push, không tạo branch mới.
- `git commit <path>` (pathspec) cho MỌI commit — index đang giữ sẵn phần tách persona `chat/`/`voice/` của user, tuyệt đối không cuốn vào.
- Fail-open toàn tuyến: mọi exception/timeout trong gate → DIRECTED (behavior cũ). Agent không bao giờ được "điếc".
- `ADDRESSEE_GATE_MODE=off` (default trong config.py) phải giữ behavior hiện tại y nguyên từng đường.
- Soft-pause KHÔNG set `VoiceAgent._interrupted`, KHÔNG cancel `_agent_task`.
- Mode multi-speaker: SpeakerFloor xử lý INTERRUPTED trước, addressee gate không tham gia nhánh đó (v1, documented).
- Task nền phải vào `self._bg_tasks` (strong ref) — asyncio chỉ giữ weakref.
- Ruff: line-length 120, rules E,F,W,I,UP,B,SIM. Test đặt tại `tests/unit/`.
- Sau khi xong toàn bộ: chạy checklist `src/noble_agent/SMOKE.md` (đổi turn loop + transport boundary).

---

### Task 1: Config settings + .env

**Files:**
- Modify: `src/noble_agent/config.py` (sau block `# ── Tool-call bridge phrase` ~line 649)
- Modify: `.env` (sau block SPEAKER_MODE ~line 195-211)
- Test: `tests/unit/test_addressee_gate.py` (file mới, phần config)

**Interfaces:**
- Produces: 6 settings fields đọc qua `from noble_agent.config import settings`: `addressee_gate_mode: str`, `addressee_min_speech_ms: int`, `addressee_llm_model: str`, `addressee_llm_timeout_ms: int`, `addressee_gate_when_idle: bool`, `addressee_resume_ack_text: str`. Env name = field name viết hoa (pydantic-settings mặc định).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_addressee_gate.py
"""Unit tests for the addressee gate (chống nói leo) — config, heuristic, dispatch."""

from __future__ import annotations


class TestConfigDefaults:
    def test_addressee_settings_exist_with_safe_defaults(self) -> None:
        from noble_agent.config import UnifiedSettings

        s = UnifiedSettings(_env_file=None)
        assert s.addressee_gate_mode == "off"
        assert s.addressee_min_speech_ms == 400
        assert s.addressee_llm_model == ""
        assert s.addressee_llm_timeout_ms == 600
        assert s.addressee_gate_when_idle is False
        assert s.addressee_resume_ack_text == "Em xin phép được nói tiếp ạ."
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_addressee_gate.py -v`
Expected: FAIL — `AttributeError: 'UnifiedSettings' object has no attribute 'addressee_gate_mode'`

- [ ] **Step 3: Add settings block to config.py**

Chèn sau block `tool_ack_cooldown_s: float = 30.0` (trước `# ── Smart Turn v3`):

```python
    # ── Addressee gate (chống nói leo) ───────────────────────────────────────
    # Phân biệt "khách ngắt lời agent" vs "khách nói chuyện với người bên cạnh".
    # off = behavior cũ (VAD interrupt ngay). Spec:
    # docs/superpowers/specs/2026-08-12-addressee-gate-design.md
    addressee_gate_mode: str = "off"  # off | heuristic | llm | hybrid
    addressee_min_speech_ms: int = 400  # speech liên tục tối thiểu mới soft-pause
    addressee_llm_model: str = ""  # pin model verdict; rỗng → chain mặc định
    addressee_llm_timeout_ms: int = 600  # quá hạn → DIRECTED (fail-open)
    addressee_gate_when_idle: bool = False  # áp gate cả khi agent không nói
    addressee_resume_ack_text: str = "Em xin phép được nói tiếp ạ."
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_addressee_gate.py -v`
Expected: PASS

- [ ] **Step 5: Add the vars to .env**

Chèn vào `.env` (sau block SPEAKER, giữ style comment của file — user yêu cầu giá trị nằm trong .env; mode đặt `hybrid` để user test luôn, default trong code vẫn `off`):

```bash
# ── Addressee gate (chống nói leo) ──────────────────────────────────────────
# off | heuristic | llm | hybrid — phân biệt khách ngắt lời vs nói với người khác
ADDRESSEE_GATE_MODE=hybrid
ADDRESSEE_MIN_SPEECH_MS=400
ADDRESSEE_LLM_MODEL=
ADDRESSEE_LLM_TIMEOUT_MS=600
ADDRESSEE_GATE_WHEN_IDLE=false
ADDRESSEE_RESUME_ACK_TEXT=Em xin phép được nói tiếp ạ.
```

- [ ] **Step 6: Lint + commit (pathspec!)**

```bash
ruff check src/noble_agent/config.py tests/unit/test_addressee_gate.py
git commit src/noble_agent/config.py .env tests/unit/test_addressee_gate.py \
  -m "feat(voice): addressee gate settings (ADDRESSEE_*)"
```

(Nếu `.env` nằm trong `.gitignore` thì bỏ nó khỏi lệnh commit — sửa file vẫn giữ, chỉ không track.)

---

### Task 2: Heuristic classifier + EpisodeTracker (`voice/addressee_gate.py`)

**Files:**
- Create: `src/noble_agent/voice/addressee_gate.py`
- Test: `tests/unit/test_addressee_gate.py` (append)

**Interfaces:**
- Produces:
  - `Verdict` (str Enum): `Verdict.DIRECTED`, `Verdict.SIDE_TALK`, `Verdict.UNSURE` (values `"directed"|"side_talk"|"unsure"`).
  - `classify_heuristic(text: str, *, agent_name: str = "") -> Verdict` — pure, không I/O.
  - `EpisodeTracker(min_speech_ms: int, chunk_ms: int, silence_reset_ms: int = 320)` với method `feed(is_speech: bool) -> str | None` trả `"pause"` (đủ ngưỡng speech), `"reset"` (blip ngắn đã tắt), hoặc `None`; method `reset() -> None`. Dùng bởi Task 5 (BaseSession) và Task 6 (telephony).

- [ ] **Step 1: Write the failing tests**

Append vào `tests/unit/test_addressee_gate.py`:

```python
import pytest

from noble_agent.voice.addressee_gate import EpisodeTracker, Verdict, classify_heuristic


class TestClassifyHeuristic:
    @pytest.mark.parametrize(
        "text",
        ["ừ", "Dạ", "vâng ạ", "ờ ờ", "ok", "à vâng", "dạ dạ"],
    )
    def test_backchannel_is_side_talk(self, text: str) -> None:
        assert classify_heuristic(text) is Verdict.SIDE_TALK

    @pytest.mark.parametrize(
        "text",
        ["em ơi cho anh hỏi", "alo alo", "Luna ơi", "này em, giá căn 2 ngủ sao"],
    )
    def test_calling_agent_is_directed(self, text: str) -> None:
        assert classify_heuristic(text, agent_name="Luna") is Verdict.DIRECTED

    @pytest.mark.parametrize(
        "text",
        ["anh ơi con khóc kìa", "mẹ ơi ra ăn cơm", "bà ơi cầm hộ cái túi"],
    )
    def test_calling_someone_else_is_side_talk(self, text: str) -> None:
        assert classify_heuristic(text, agent_name="Luna") is Verdict.SIDE_TALK

    @pytest.mark.parametrize(
        "text",
        ["thế dự án đó bao nhiêu tiền", "cái căn hai phòng ngủ ấy", "tôi thấy cũng được đấy"],
    )
    def test_plain_sentence_is_unsure(self, text: str) -> None:
        assert classify_heuristic(text, agent_name="Luna") is Verdict.UNSURE

    def test_empty_text_is_unsure(self) -> None:
        assert classify_heuristic("   ") is Verdict.UNSURE


class TestEpisodeTracker:
    def test_sustained_speech_crosses_threshold(self) -> None:
        t = EpisodeTracker(min_speech_ms=400, chunk_ms=32)
        results = [t.feed(True) for _ in range(13)]  # 13 × 32ms = 416ms
        assert results[-1] == "pause"
        assert all(r is None for r in results[:-1])

    def test_short_blip_then_silence_resets(self) -> None:
        t = EpisodeTracker(min_speech_ms=400, chunk_ms=32, silence_reset_ms=320)
        for _ in range(5):  # 160ms speech — dưới ngưỡng
            assert t.feed(True) is None
        results = [t.feed(False) for _ in range(10)]  # 320ms silence
        assert results[-1] == "reset"

    def test_pause_fires_once(self) -> None:
        t = EpisodeTracker(min_speech_ms=64, chunk_ms=32)
        assert t.feed(True) is None
        assert t.feed(True) == "pause"
        assert t.feed(True) is None  # đã pause — không bắn lại

    def test_reset_allows_new_episode(self) -> None:
        t = EpisodeTracker(min_speech_ms=64, chunk_ms=32)
        t.feed(True)
        assert t.feed(True) == "pause"
        t.reset()
        t.feed(True)
        assert t.feed(True) == "pause"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_addressee_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'noble_agent.voice.addressee_gate'`

- [ ] **Step 3: Implement the module**

```python
# src/noble_agent/voice/addressee_gate.py
"""Addressee gate — quyết định câu nói của khách có hướng tới agent hay không.

Chống "nói leo": khách quay sang nói chuyện với người bên cạnh trong lúc agent
đang nói thì KHÔNG được tính là barge-in. Hai tầng: heuristic thuần (0ms) và
LLM one-shot (chỉ ca mơ hồ). Fail-open: mọi đường lỗi đều trả DIRECTED ở tầng
dispatch (classify) — thà ngắt oan còn hơn làm agent điếc.

Spec: docs/superpowers/specs/2026-08-12-addressee-gate-design.md
"""

from __future__ import annotations

import logging
import re
from enum import Enum

logger = logging.getLogger("addressee")


class Verdict(str, Enum):
    DIRECTED = "directed"
    SIDE_TALK = "side_talk"
    UNSURE = "unsure"


# Backchannel: câu chỉ gồm các token đệm — khách đang "ừ hử" theo, không phải
# ngắt lời. So khớp token-set sau khi bỏ dấu câu, nên "dạ dạ" / "à vâng" đều dính.
_BACKCHANNEL_TOKENS = {
    "ừ", "ừm", "ờ", "à", "ạ", "dạ", "vâng", "vầng", "ok", "okay", "oke", "uh", "ừa", "ha", "hử", "hả",
}

# Gọi đích danh agent → DIRECTED. agent_name (lowercase) được thêm lúc runtime.
_AGENT_CALL_PATTERNS = ("em ơi", "em à", "này em", "alo", "a lô")

# Gọi đích danh người khác (xưng hô gia đình/đồng hành) → SIDE_TALK.
_OTHER_CALL_PATTERNS = (
    "anh ơi", "chị ơi", "con ơi", "mẹ ơi", "bố ơi", "ba ơi", "ông ơi", "bà ơi",
    "cưng ơi", "bé ơi", "vợ ơi", "chồng ơi",
)

_PUNCT_RE = re.compile(r"[.,!?;:…\"'()\-]+")


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub(" ", text.lower()).strip()


def classify_heuristic(text: str, *, agent_name: str = "") -> Verdict:
    """Tầng 1 — thuần chuỗi, 0ms, 0 chi phí. UNSURE nghĩa là 'để tầng sau quyết'."""
    norm = _normalize(text)
    if not norm:
        return Verdict.UNSURE

    tokens = norm.split()
    if tokens and all(t in _BACKCHANNEL_TOKENS for t in tokens):
        return Verdict.SIDE_TALK

    if agent_name and agent_name.lower() in norm:
        return Verdict.DIRECTED
    if any(p in norm for p in _AGENT_CALL_PATTERNS):
        return Verdict.DIRECTED
    if any(p in norm for p in _OTHER_CALL_PATTERNS):
        return Verdict.SIDE_TALK
    return Verdict.UNSURE


class EpisodeTracker:
    """Đếm speech-ms cho một 'interrupt episode' — pure logic, dùng chung
    BaseSession + telephony. feed() mỗi VAD chunk; trả 'pause' đúng MỘT lần
    khi speech tích lũy đủ ngưỡng, 'reset' khi im lặng đủ lâu trước khi đạt
    ngưỡng (blip: ho, 'ừ' ngắn), None cho mọi chunk còn lại."""

    def __init__(self, min_speech_ms: int, chunk_ms: int, silence_reset_ms: int = 320) -> None:
        self._min_speech_ms = min_speech_ms
        self._chunk_ms = chunk_ms
        self._silence_reset_ms = silence_reset_ms
        self._speech_ms = 0
        self._silence_ms = 0
        self._fired = False

    def feed(self, is_speech: bool) -> str | None:
        if self._fired:
            return None
        if is_speech:
            self._speech_ms += self._chunk_ms
            self._silence_ms = 0
            if self._speech_ms >= self._min_speech_ms:
                self._fired = True
                return "pause"
            return None
        self._silence_ms += self._chunk_ms
        if self._silence_ms >= self._silence_reset_ms:
            self.reset()
            return "reset"
        return None

    def reset(self) -> None:
        self._speech_ms = 0
        self._silence_ms = 0
        self._fired = False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_addressee_gate.py -v`
Expected: PASS (tất cả)

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/voice/addressee_gate.py tests/unit/test_addressee_gate.py
git commit src/noble_agent/voice/addressee_gate.py tests/unit/test_addressee_gate.py \
  -m "feat(voice): addressee heuristic classifier + EpisodeTracker"
```

---

### Task 3: LLM classifier + mode dispatch

**Files:**
- Modify: `src/noble_agent/voice/addressee_gate.py` (append)
- Test: `tests/unit/test_addressee_gate.py` (append)

**Interfaces:**
- Consumes: `Verdict`, `classify_heuristic` (Task 2); `StreamingClient.complete_once(messages, model, temperature, max_tokens, primary, request_timeout)` (`agent/llm/client.py:348`); `build_llm_providers` (`agent/facade.py`); `get_settings`, `primary_for`, `provider_model_map` (`config.py`) — pattern y hệt `agent/memory/snapshot.py::_call_merge_llm`.
- Produces: `async classify(text: str, *, agent_line: str = "", last_user_text: str = "", agent_name: str = "") -> Verdict` — KHÔNG bao giờ trả UNSURE, không bao giờ raise. Đây là entrypoint duy nhất Task 5/6 gọi.

- [ ] **Step 1: Write the failing tests**

Append vào `tests/unit/test_addressee_gate.py`:

```python
from unittest.mock import AsyncMock, patch

from noble_agent.voice.addressee_gate import classify


def _mock_settings(mode: str):
    s = type("S", (), {})()
    s.addressee_gate_mode = mode
    s.addressee_llm_model = ""
    s.addressee_llm_timeout_ms = 600
    s.agent_model = ""
    s.summary_model = ""
    s.llm_enable_thinking = False
    s.openai_reasoning_effort = "none"
    return s


class TestClassifyDispatch:
    async def test_mode_off_always_directed(self) -> None:
        with patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("off")):
            assert await classify("anh ơi con khóc kìa") is Verdict.DIRECTED

    async def test_mode_heuristic_unsure_fails_open_to_directed(self) -> None:
        with patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("heuristic")):
            assert await classify("thế giá bao nhiêu nhỉ") is Verdict.DIRECTED

    async def test_mode_heuristic_side_talk_detected(self) -> None:
        with patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("heuristic")):
            assert await classify("anh ơi con khóc kìa") is Verdict.SIDE_TALK

    async def test_mode_hybrid_unsure_falls_to_llm(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("hybrid")),
            patch(
                "noble_agent.voice.addressee_gate._classify_llm",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ) as mock_llm,
        ):
            assert await classify("thế giá bao nhiêu nhỉ") is Verdict.SIDE_TALK
            mock_llm.assert_awaited_once()

    async def test_mode_hybrid_heuristic_hit_skips_llm(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("hybrid")),
            patch("noble_agent.voice.addressee_gate._classify_llm", new=AsyncMock()) as mock_llm,
        ):
            assert await classify("em ơi") is Verdict.DIRECTED
            mock_llm.assert_not_awaited()

    async def test_llm_exception_fails_open_to_directed(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("llm")),
            patch(
                "noble_agent.voice.addressee_gate._classify_llm",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            assert await classify("bất kỳ câu gì") is Verdict.DIRECTED

    async def test_llm_unsure_fails_open_to_directed(self) -> None:
        with (
            patch("noble_agent.voice.addressee_gate.get_settings", return_value=_mock_settings("llm")),
            patch(
                "noble_agent.voice.addressee_gate._classify_llm",
                new=AsyncMock(return_value=Verdict.UNSURE),
            ),
        ):
            assert await classify("câu mơ hồ") is Verdict.DIRECTED


class TestParseLlmVerdict:
    def test_parse_variants(self) -> None:
        from noble_agent.voice.addressee_gate import _parse_verdict

        assert _parse_verdict("SIDE_TALK") is Verdict.SIDE_TALK
        assert _parse_verdict("side talk.") is Verdict.SIDE_TALK
        assert _parse_verdict("DIRECTED") is Verdict.DIRECTED
        assert _parse_verdict(" directed\n") is Verdict.DIRECTED
        assert _parse_verdict("không rõ") is Verdict.UNSURE
        assert _parse_verdict("") is Verdict.UNSURE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_addressee_gate.py -v -k "Dispatch or ParseLlm"`
Expected: FAIL — `ImportError: cannot import name 'classify'`

- [ ] **Step 3: Implement LLM tier + dispatch**

Append vào `src/noble_agent/voice/addressee_gate.py`:

```python
# Import mức module để test patch được noble_agent.voice.addressee_gate.get_settings.
from noble_agent.config import get_settings  # noqa: E402

_LLM_PROMPT = """Bạn là bộ lọc hội thoại của tổng đài viên tên {agent_name} (nữ, xưng "em").
Bối cảnh cuộc gọi tư vấn bất động sản đang diễn ra:
- Câu {agent_name} đang nói dở: "{agent_line}"
- Câu ngay trước đó của khách: "{last_user_text}"
- Khách vừa nói: "{text}"

Câu khách vừa nói là nói VỚI {agent_name}, hay khách đang nói với người khác bên cạnh
(ví dụ người nhà, đồng nghiệp)? Trả lời đúng MỘT từ:
DIRECTED (nói với {agent_name}) hoặc SIDE_TALK (nói với người khác)."""


def _parse_verdict(raw: str) -> Verdict:
    up = (raw or "").strip().upper()
    if "SIDE" in up:
        return Verdict.SIDE_TALK
    if "DIRECT" in up:
        return Verdict.DIRECTED
    return Verdict.UNSURE


async def _classify_llm(text: str, *, agent_line: str, last_user_text: str, agent_name: str) -> Verdict:
    """Tầng 2 — one-shot LLM, provider chain dùng chung (pattern snapshot._call_merge_llm).
    Trả UNSURE khi không có provider / lỗi / câu trả lời không parse được."""
    from noble_agent.agent.facade import build_llm_providers
    from noble_agent.agent.llm.client import StreamingClient
    from noble_agent.config import primary_for, provider_model_map

    settings = get_settings()
    providers = build_llm_providers()
    if not providers:
        logger.warning("[Addressee] no LLM providers configured")
        return Verdict.UNSURE
    client = StreamingClient(
        providers=providers,
        enable_thinking=False,
        openai_reasoning_effort=settings.openai_reasoning_effort,
    )
    primary = primary_for(settings, settings.addressee_llm_model or settings.agent_model)
    prompt = _LLM_PROMPT.format(
        agent_name=agent_name or "Luna",
        agent_line=(agent_line or "")[:200],
        last_user_text=(last_user_text or "")[:200],
        text=text[:300],
    )
    raw = await client.complete_once(
        messages=[{"role": "user", "content": prompt}],
        model=provider_model_map(settings),
        temperature=0.0,
        max_tokens=8,
        primary=primary,
        request_timeout=settings.addressee_llm_timeout_ms / 1000,
    )
    return _parse_verdict(raw)


async def classify(
    text: str,
    *,
    agent_line: str = "",
    last_user_text: str = "",
    agent_name: str = "",
) -> Verdict:
    """Entrypoint duy nhất cho session code. KHÔNG raise, KHÔNG trả UNSURE —
    mọi đường mơ hồ/lỗi đều fail-open thành DIRECTED (giữ behavior cũ)."""
    try:
        mode = get_settings().addressee_gate_mode
        if mode == "off":
            return Verdict.DIRECTED
        if mode in ("heuristic", "hybrid"):
            v = classify_heuristic(text, agent_name=agent_name)
            if v is not Verdict.UNSURE:
                return v
            if mode == "heuristic":
                return Verdict.DIRECTED
        v = await _classify_llm(
            text, agent_line=agent_line, last_user_text=last_user_text, agent_name=agent_name
        )
        logger.info("[Addressee] LLM verdict=%s for %r", v.value, text[:80])
        return Verdict.DIRECTED if v is Verdict.UNSURE else v
    except Exception as exc:  # noqa: BLE001 — fail-open là invariant
        logger.warning("[Addressee] classify failed (%s) — fail-open DIRECTED", exc)
        return Verdict.DIRECTED
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_addressee_gate.py -v`
Expected: PASS (tất cả)

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/voice/addressee_gate.py tests/unit/test_addressee_gate.py
git commit src/noble_agent/voice/addressee_gate.py tests/unit/test_addressee_gate.py \
  -m "feat(voice): addressee LLM classifier + mode dispatch (fail-open DIRECTED)"
```

---

### Task 4: VoiceAgent soft-pause / resume + resume ack

**Files:**
- Modify: `src/noble_agent/voice/voice_agent.py` (`__init__` ~line 144, `interrupt`/`pause_tts` ~246-266, `speak_text` ~274, `handle_utterance` reset ~346, pacer inner loop ~618-654)
- Modify: `scripts/gen_ack_assets.py` (thêm generate resume-ack asset)
- Test: `tests/unit/test_voice_agent_pause.py` (mới)

**Interfaces:**
- Consumes: `settings.addressee_resume_ack_text`, `settings.tts_sample_rate`, `settings.tool_ack_assets_dir`.
- Produces (Task 5/6 gọi):
  - `VoiceAgent.pause_playback() -> None` (sync) — soft-pause: pacer nín, KHÔNG set `_interrupted`.
  - `VoiceAgent.resume_playback() -> None` (sync) — hẹn phát ack rồi replay clause; pacer tự thực hiện.
  - `VoiceAgent.current_clause_text: str` (property) — text clause đang phát (context cho classifier).
  - Invariant: `interrupt()` / `pause_tts()` tự giải phóng pause (pacer không bao giờ kẹt).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_voice_agent_pause.py
"""Soft-pause/resume của VoiceAgent pacer (addressee gate) — không cần TTS/LLM thật.

Construct qua __new__ (pattern sẵn có trong codebase — xem comment
voice_agent.py ~line 700) và test trực tiếp helper `_wait_if_paused` +
`_play_resume_ack` + invariant interrupt-giải-phóng-pause.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from noble_agent.voice.voice_agent import VoiceAgent


def _bare_agent(sent: list[bytes]):
    a = VoiceAgent.__new__(VoiceAgent)
    a._interrupted = False
    a._playback_paused = False
    a._resume_event = asyncio.Event()
    a._resume_event.set()
    a._resume_with_ack = False
    a._current_clause_text = ""
    a._resume_ack_pcm = b""

    async def _send(chunk: bytes) -> None:
        sent.append(chunk)

    a._send_audio = _send
    return a


class TestWaitIfPaused:
    async def test_not_paused_returns_false_immediately(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        assert await a._wait_if_paused([b"f0"]) is False
        assert sent == []

    async def test_resume_replays_clause_frames_after_ack(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a._resume_ack_pcm = b"ACK!" * 400  # pre-synth asset path (không cần TTS)
        a.pause_playback()

        async def _resume_soon():
            await asyncio.sleep(0.01)
            a.resume_playback()

        task = asyncio.ensure_future(_resume_soon())
        committed = await a._wait_if_paused([b"f0", b"f1"])
        await task
        assert committed is False
        # ack frames trước, rồi replay đúng thứ tự clause frames
        assert sent[-2:] == [b"f0", b"f1"]
        assert len(sent) > 2  # có ack đứng trước

    async def test_commit_interrupt_while_paused_returns_true(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a.pause_playback()

        async def _interrupt_soon():
            await asyncio.sleep(0.01)
            a.interrupt()  # commit — phải tự giải phóng pause

        task = asyncio.ensure_future(_interrupt_soon())
        committed = await a._wait_if_paused([b"f0"])
        await task
        assert committed is True
        assert sent == []  # không replay gì khi commit

    async def test_pause_tts_also_releases_pause(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        a._tts = type("T", (), {})()  # không có .pause — nhánh getattr None
        a.pause_playback()

        async def _hard_pause_soon():
            await asyncio.sleep(0.01)
            await a.pause_tts()

        task = asyncio.ensure_future(_hard_pause_soon())
        committed = await a._wait_if_paused([])
        await task
        assert committed is True


class TestPlayResumeAck:
    async def test_asset_pcm_streamed_in_frames(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        with patch("noble_agent.voice.voice_agent.settings") as s:
            s.tts_sample_rate = 24000
            s.addressee_resume_ack_text = "Em xin phép được nói tiếp ạ."
            frame_bytes = int(24000 * 0.04) * 2
            a._resume_ack_pcm = b"\x01\x02" * frame_bytes  # 2 frames worth
            await a._play_resume_ack()
        assert len(sent) >= 2
        assert b"".join(sent) == a._resume_ack_pcm

    async def test_no_asset_no_text_is_noop(self) -> None:
        sent: list[bytes] = []
        a = _bare_agent(sent)
        with patch("noble_agent.voice.voice_agent.settings") as s:
            s.addressee_resume_ack_text = ""
            a._resume_ack_pcm = b""
            await a._play_resume_ack()
        assert sent == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_voice_agent_pause.py -v`
Expected: FAIL — `AttributeError: 'VoiceAgent' object has no attribute '_wait_if_paused'` (hoặc `pause_playback`)

- [ ] **Step 3: Implement soft-pause in VoiceAgent**

3a. `__init__` (sau `self._last_stt_ms: float | None = None` ~line 166) thêm:

```python
        # Addressee-gate soft-pause: pacer nín khi _playback_paused, KHÔNG cancel
        # turn. _resume_event set = được chạy. Xem _wait_if_paused.
        self._playback_paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._resume_with_ack = False
        self._current_clause_text = ""
        self._resume_ack_pcm: bytes = _load_resume_ack_asset()
```

3b. Module-level loader (cạnh `_load_ack_assets`):

```python
def _load_resume_ack_asset() -> bytes:
    """PCM pre-synth cho câu resume-ack (gen_ack_assets.py --resume-ack).
    Nằm CẠNH assets dir tool-ack nhưng là file riêng `resume_ack.pcm` —
    KHÔNG nằm trong pool random tool-ack. Thiếu file → b"" (live TTS fallback)."""
    dir_str = getattr(settings, "tool_ack_assets_dir", "") or ""
    if not dir_str:
        return b""
    path = Path(dir_str)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent.parent.parent / dir_str
    f = path / "resume_ack.pcm"
    try:
        return f.read_bytes() if f.is_file() else b""
    except Exception as exc:  # noqa: BLE001
        logger.warning("[RESUME-ACK] failed to read %s: %s", f, exc)
        return b""
```

3c. API methods (cạnh `interrupt()` ~line 246):

```python
    def pause_playback(self) -> None:
        """Soft-pause (addressee gate): pacer ngừng gửi frame; turn vẫn sống.
        KHÔNG set _interrupted — llm_producer + synth-ahead chạy tiếp."""
        self._playback_paused = True
        self._resume_event.clear()

    def resume_playback(self) -> None:
        """Side-talk verdict: phát ack xin phép rồi phát lại clause đang dở.
        Ack + replay do pacer thực hiện (single writer tới _send_audio)."""
        self._resume_with_ack = True
        self._playback_paused = False
        self._resume_event.set()

    def _release_pause(self) -> None:
        """Commit interrupt trong lúc đang soft-pause: mở khoá để pacer thấy
        _interrupted và thoát — pacer không bao giờ kẹt trên _resume_event."""
        self._playback_paused = False
        self._resume_event.set()

    @property
    def current_clause_text(self) -> str:
        """Text clause đang phát — context cho addressee classifier."""
        return self._current_clause_text
```

Sửa `interrupt()` và `pause_tts()` gọi `self._release_pause()` ngay sau `self._interrupted = True`. Lưu ý test cũ construct qua `__new__` — dùng `getattr` guard trong `interrupt()`/`pause_tts()`:

```python
    def interrupt(self):
        self._interrupted = True
        if getattr(self, "_resume_event", None) is not None:
            self._release_pause()
```

(tương tự đầu `pause_tts`).

3d. Helper pause + ack (cạnh `_iter_clause_audio`):

```python
    async def _wait_if_paused(self, clause_frames: list[bytes]) -> bool:
        """Chặn khi đang soft-pause. Trả True nếu bị commit-interrupt trong lúc
        chờ (caller break). Khi resume: phát ack xin phép rồi replay các frame
        đã gửi của clause hiện tại (transport buffer đã bị clear lúc pause)."""
        if not self._playback_paused:
            return False
        await self._resume_event.wait()
        if self._interrupted:
            return True
        if self._resume_with_ack:
            self._resume_with_ack = False
            await self._play_resume_ack()
        for f in clause_frames:
            if self._interrupted:
                return True
            await self._send_audio(f)
        return False

    async def _play_resume_ack(self) -> None:
        """Ack 'Em xin phép được nói tiếp ạ' — ưu tiên PCM pre-synth, fallback
        live TTS; cả hai đều best-effort (lỗi thì resume thẳng)."""
        pcm = getattr(self, "_resume_ack_pcm", b"")
        if pcm:
            frame_bytes = int(settings.tts_sample_rate * 0.04) * 2
            for i in range(0, len(pcm), frame_bytes):
                if self._interrupted:
                    return
                await self._send_audio(pcm[i : i + frame_bytes])
            return
        text = (getattr(settings, "addressee_resume_ack_text", "") or "").strip()
        if not text:
            return
        try:
            async with contextlib.aclosing(self._tts.stream(normalize_for_voice(text))) as stream:
                async for chunk in stream:
                    if self._interrupted:
                        return
                    await self._send_audio(chunk)
        except Exception as exc:  # noqa: BLE001 — ack là best-effort
            logger.warning("[RESUME-ACK] live TTS failed: %s — resuming without ack", exc)
```

3e. Pacer inner loop (voice_agent.py ~618-654) — thay đoạn:

```python
                    tts_first_chunk = True
                    sent_speaking = False
                    interrupted_mid_tts = False

                    while True:
                        if self._interrupted and settings.interrupt_mode == "immediate":
```

bằng:

```python
                    tts_first_chunk = True
                    sent_speaking = False
                    interrupted_mid_tts = False
                    clause_frames: list[bytes] = []
                    self._current_clause_text = sc.text

                    while True:
                        if self._interrupted and settings.interrupt_mode == "immediate":
```

và ngay sau dòng `if chunk is None:  # clause-complete sentinel` / `break`, TRƯỚC khối `if tts_first_chunk:` thêm gate + tích lũy, rồi thay `await self._send_audio(chunk)` cuối vòng:

```python
                        if await self._wait_if_paused(clause_frames):
                            interrupted_mid_tts = True
                            break
```

(đặt ngay sau `chunk = await frame_q.get()` + sentinel check), và:

```python
                        clause_frames.append(chunk)
                        await self._send_audio(chunk)
```

3f. `handle_utterance` reset đầu turn (sau `self._interrupted = False` ~line 346):

```python
        self._playback_paused = False
        self._resume_event.set()
        self._resume_with_ack = False
        self._current_clause_text = ""
```

3g. `speak_text` (greeting — không có clause buffer, chỉ chờ):

```python
    async def speak_text(self, text: str) -> None:
        self._interrupted = False
        async for chunk in self._tts.stream(normalize_for_voice(text)):
            if self._interrupted:
                break
            await self._resume_event.wait()
            if self._interrupted:
                break
            await self._send_audio(chunk)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_voice_agent_pause.py -v`
Expected: PASS. Rồi chạy regression: `pytest tests/unit/test_interrupt.py tests/unit/test_ack_manifest.py tests/unit/test_voice_media_forwarding.py -v` — PASS (không phá pacer cũ).

- [ ] **Step 5: gen_ack_assets.py — resume ack asset**

Thêm flag `--resume-ack`: synth `settings.addressee_resume_ack_text` ra `<assets_dir>/resume_ack.pcm` (dùng đúng TTS setup sẵn có của script; KHÔNG thêm vào manifest phrases pool — file đứng riêng). Đọc script trước khi sửa; giữ nguyên cách nó synth từng phrase, chỉ thêm một nhánh ghi ra tên file cố định `resume_ack.pcm`.

- [ ] **Step 6: Lint + commit**

```bash
ruff check src/noble_agent/voice/voice_agent.py scripts/gen_ack_assets.py tests/unit/test_voice_agent_pause.py
git commit src/noble_agent/voice/voice_agent.py scripts/gen_ack_assets.py tests/unit/test_voice_agent_pause.py \
  -m "feat(voice): pacer soft-pause/resume + resume ack (addressee gate)"
```

---

### Task 5: BaseSession — episode + verdict + final gate

**Files:**
- Modify: `src/noble_agent/server/base_session.py` (`__init__` ~121-172, `process_audio_frame` ~444-495, `_on_partial` ~569, `_on_final` ~572-639, `stop()`)
- Test: `tests/unit/test_base_session.py` (append class mới)

**Interfaces:**
- Consumes: `addressee_gate.classify`, `addressee_gate.Verdict`, `addressee_gate.EpisodeTracker` (Task 2/3); `agent.pause_playback()`, `agent.resume_playback()`, `agent.current_clause_text` (Task 4); settings Task 1.
- Produces: hành vi session — không API mới cho tầng khác. Telephony (Task 6) copy cùng pattern.

- [ ] **Step 1: Write the failing tests**

Append vào `tests/unit/test_base_session.py` (dùng `_patched_collaborators` sẵn có; NHỚ thêm vào mock_settings trong fixture: `mock_settings.addressee_gate_mode = "off"`, `mock_settings.addressee_min_speech_ms = 400`, `mock_settings.addressee_llm_timeout_ms = 600`, `mock_settings.addressee_gate_when_idle = False`, `mock_settings.vad_chunk_ms = 32` — đã có, `mock_settings.agent_name = "Luna"`):

```python
# ----------------------------------------------------------------------
# Addressee gate (chống nói leo)
# ----------------------------------------------------------------------


def _speech_chunk_result(is_speech: bool = True, state="speaking"):
    return {"state": state, "is_speech": is_speech, "speech_prob": 0.9, "state_changed": False}


class TestAddresseeGate:
    async def test_gate_off_interrupts_immediately(self) -> None:
        """Mode off: VAD INTERRUPTED → _handle_interrupt như cũ, không episode."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession, VADState

            cols["settings"].addressee_gate_mode = "off"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            cols["vad"].process_chunk.return_value = {
                "state": VADState.INTERRUPTED, "is_speech": True, "speech_prob": 0.9, "state_changed": True,
            }
            await s.process_audio_frame(b"\x00" * 1024)
            cols["agent"].pause_playback.assert_not_called()
            assert s._agent_task.cancelled() or s._agent_task.done()

    async def test_sustained_speech_soft_pauses(self) -> None:
        """Gate on: INTERRUPTED mở episode; speech đủ 400ms → pause_playback,
        KHÔNG cancel agent task."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession, VADState

            cols["settings"].addressee_gate_mode = "hybrid"
            cols["settings"].addressee_min_speech_ms = 400
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            fake_out = _FakeAudioOutput()
            s._audio_output = fake_out
            # 1 chunk INTERRUPTED mở episode + ~13 chunk speech (416ms)
            cols["vad"].process_chunk.return_value = {
                "state": VADState.INTERRUPTED, "is_speech": True, "speech_prob": 0.9, "state_changed": True,
            }
            await s.process_audio_frame(b"\x00" * 1024)
            cols["vad"].process_chunk.return_value = _speech_chunk_result(True)
            for _ in range(13):
                await s.process_audio_frame(b"\x00" * 1024)
            cols["agent"].pause_playback.assert_called_once()
            assert fake_out.clears >= 1
            assert not s._agent_task.done()  # soft — turn còn sống
            s._agent_task.cancel()

    async def test_side_talk_verdict_resumes(self) -> None:
        """Verdict SIDE_TALK trên partial → resume_playback, episode đóng."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            s._addr_paused = True
            s._addr_episode_active = True
            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ):
                await s._classify_addressee("anh ơi con khóc kìa")
            cols["agent"].resume_playback.assert_called_once()
            assert s._addr_episode_verdict == Verdict.SIDE_TALK
            assert not s._agent_task.done()
            s._agent_task.cancel()

    async def test_directed_verdict_commits_interrupt(self) -> None:
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            s._addr_paused = True
            s._addr_episode_active = True
            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.DIRECTED),
            ):
                await s._classify_addressee("em ơi cho anh hỏi giá")
            cols["agent"].pause_tts.assert_awaited()  # _handle_interrupt đường cũ
            assert s._agent_task.cancelled() or s._agent_task.done()

    async def test_final_dropped_after_side_talk_verdict(self) -> None:
        """Final thuộc episode đã verdict SIDE_TALK → drop, không trigger agent."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._addr_episode_verdict = Verdict.SIDE_TALK
            await s._on_final("anh ơi con khóc kìa")
            assert s._agent_task is None  # không trigger
            assert s._addr_episode_verdict is None  # consume-once

    async def test_final_while_speaking_no_verdict_classifies_inline(self) -> None:
        """Final đến khi agent đang nói mà chưa có verdict (câu ngắn dưới
        duration gate) → classify tại chỗ; SIDE_TALK → drop + agent nói tiếp."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession
            from noble_agent.voice.addressee_gate import Verdict

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            with patch(
                "noble_agent.server.base_session.addressee_gate.classify",
                new=AsyncMock(return_value=Verdict.SIDE_TALK),
            ):
                await s._on_final("ừ đúng đấy")
            cols["vad"].set_speaking.assert_called()
            assert not s._agent_task.done()  # agent không bị cancel
            s._agent_task.cancel()

    async def test_deadline_fail_open_commits_interrupt(self) -> None:
        """Không có text trong hạn → DIRECTED fail-open (commit interrupt)."""
        async with _patched_collaborators() as cols:
            from noble_agent.server.base_session import BaseSession

            cols["settings"].addressee_gate_mode = "hybrid"
            s = BaseSession("sid")
            s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
            s._addr_paused = True
            s._addr_episode_active = True
            await s._addressee_deadline()
            cols["agent"].pause_tts.assert_awaited()
            assert s._agent_task.cancelled() or s._agent_task.done()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_base_session.py -k Addressee -v`
Expected: FAIL — `AttributeError` (`_classify_addressee` / `_addr_paused` chưa tồn tại)

- [ ] **Step 3: Implement BaseSession integration**

3a. Import đầu file: `from noble_agent.voice import addressee_gate` và `from noble_agent.voice.addressee_gate import EpisodeTracker, Verdict`.

3b. `__init__` (cạnh block multi-mode deferred-interrupt state ~line 149):

```python
        # Addressee gate (chống nói leo) — spec 2026-08-12. Episode đo speech-ms
        # khi có tiếng đè lên agent; đủ ngưỡng → soft-pause + classify.
        # _classify_addressee / _addressee_deadline là background writers cùng
        # kiểu _evaluate_interrupt_candidate (xem safety comment phía trên).
        self._addr_gate_enabled = settings.addressee_gate_mode != "off"
        self._addr_tracker = EpisodeTracker(
            min_speech_ms=settings.addressee_min_speech_ms,
            chunk_ms=settings.vad_chunk_ms,
        )
        self._addr_episode_active = False
        self._addr_paused = False
        self._addr_verdict_inflight = False
        self._addr_episode_verdict: Verdict | None = None
        self._addr_deadline_handle: asyncio.TimerHandle | None = None
        self._last_user_text = ""
```

3c. `process_audio_frame` — nhánh INTERRUPTED (line ~454) thành:

```python
            if result["state"] == VADState.INTERRUPTED:
                if self._speaker_floor is not None:  # multi: defer until asker is identified
                    self._begin_interrupt_episode()
                elif self._addr_gate_enabled:
                    self._begin_addressee_episode()
                else:
                    await self._handle_interrupt()
            elif self._addr_episode_active and not self._addr_paused:
                # Đang đo episode: tích lũy speech tới ngưỡng soft-pause.
                action = self._addr_tracker.feed(result["is_speech"])
                if action == "pause":
                    await self._addressee_soft_pause()
                elif action == "reset":
                    self._addr_episode_active = False
                    self.vad.set_speaking()  # tiếp tục nghe barge-in mới
```

3d. Methods mới (đặt cạnh `_begin_interrupt_episode` ~line 532):

```python
    def _begin_addressee_episode(self) -> None:
        """Gate on: tiếng người đè lên agent — đo trước, quyết sau (KHÔNG cancel)."""
        if not self._agent_is_speaking() or self._addr_episode_active:
            return
        self._addr_episode_active = True
        self._addr_episode_verdict = None
        self._addr_tracker.reset()
        # VAD confirm chunks đã là speech — nạp trước vào tracker.
        for _ in range(settings.vad_interrupt_confirm_chunks):
            self._addr_tracker.feed(True)
        self.vad.set_speaking()  # giữ máy trạng thái VAD sống cho episode kế

    async def _addressee_soft_pause(self) -> None:
        """Speech đủ ngưỡng: agent im (soft), chờ STT text để phán đoán."""
        self._addr_paused = True
        self.agent.pause_playback()
        if self._audio_output is not None:
            self._audio_output.clear()
        loop = asyncio.get_running_loop()
        # Hạn chờ text + verdict: llm_timeout + 1s grace cho STT partial.
        deadline_s = settings.addressee_llm_timeout_ms / 1000 + 1.0
        self._addr_deadline_handle = loop.call_later(
            deadline_s, lambda: asyncio.ensure_future(self._addressee_deadline())
        )
        logger.info("[Addressee] soft-pause — waiting for STT text (%.1fs)", deadline_s)

    async def _addressee_deadline(self) -> None:
        """Hết hạn mà chưa có verdict → DIRECTED fail-open (behavior cũ)."""
        if not self._addr_paused:
            return
        logger.info("[Addressee] decision deadline — fail-open DIRECTED")
        await self._addressee_commit_interrupt()

    def _addr_reset_episode(self) -> None:
        if self._addr_deadline_handle is not None:
            self._addr_deadline_handle.cancel()
            self._addr_deadline_handle = None
        self._addr_episode_active = False
        self._addr_paused = False
        self._addr_verdict_inflight = False
        self._addr_tracker.reset()

    async def _addressee_commit_interrupt(self) -> None:
        self._addr_reset_episode()
        self._addr_episode_verdict = Verdict.DIRECTED
        await self._handle_interrupt()

    async def _classify_addressee(self, text: str) -> None:
        """Background verdict cho episode đang pause (từ partial hoặc final)."""
        try:
            verdict = await addressee_gate.classify(
                text,
                agent_line=getattr(self.agent, "current_clause_text", ""),
                last_user_text=self._last_user_text,
                agent_name=settings.agent_name,
            )
            self._addr_episode_verdict = verdict
            if verdict is Verdict.SIDE_TALK:
                logger.info("[Addressee] SIDE_TALK — resuming agent: %r", text[:80])
                self._addr_reset_episode()
                self.agent.resume_playback()
                self.vad.set_speaking()
            else:
                logger.info("[Addressee] DIRECTED — committing interrupt: %r", text[:80])
                await self._addressee_commit_interrupt()
        finally:
            self._addr_verdict_inflight = False
```

3e. `_on_partial` (line ~569):

```python
    async def _on_partial(self, text: str) -> None:
        await self._send_event({"type": "partial_transcript", "text": text})
        if self._addr_paused and not self._addr_verdict_inflight and len(text.strip()) >= 4:
            self._addr_verdict_inflight = True
            task = asyncio.ensure_future(self._classify_addressee(text))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)
```

3f. `_on_final` — chèn SAU speaker gates (sau block `self._speaker_floor` ~line 610), TRƯỚC block `if speaker:`:

```python
        if self._addr_gate_enabled:
            verdict = self._addr_episode_verdict
            self._addr_episode_verdict = None  # consume-once
            if verdict is Verdict.SIDE_TALK:
                logger.info("[Addressee] Dropped side-talk final: %r", text)
                return
            if verdict is None:
                if self._agent_is_speaking():
                    # Câu ngắn chưa kịp qua duration gate / verdict — quyết tại đây.
                    v = await addressee_gate.classify(
                        text,
                        agent_line=getattr(self.agent, "current_clause_text", ""),
                        last_user_text=self._last_user_text,
                        agent_name=settings.agent_name,
                    )
                    if v is Verdict.SIDE_TALK:
                        logger.info("[Addressee] Dropped side-talk final mid-turn: %r", text)
                        self._addr_reset_episode()
                        self.agent.resume_playback() if self._addr_paused else None
                        self.vad.set_speaking()
                        return
                    await self._addressee_commit_interrupt()
                    self._addr_episode_verdict = None
                elif settings.addressee_gate_when_idle:
                    v = await addressee_gate.classify(
                        text, last_user_text=self._last_user_text, agent_name=settings.agent_name
                    )
                    if v is Verdict.SIDE_TALK:
                        logger.info("[Addressee] Dropped side-talk final (idle): %r", text)
                        return
        self._last_user_text = text
```

**Chú ý dòng `self.agent.resume_playback() if self._addr_paused else None` — viết thành if thường (ruff SIM):**

```python
                        if self._addr_paused:
                            self.agent.resume_playback()
                        self._addr_reset_episode()
```

(gọi `_addr_reset_episode()` SAU khi đọc `_addr_paused`.)

3g. `stop()`: thêm `self._addr_reset_episode()` cạnh chỗ cancel `_hold_timer`/`_idle_timer`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_base_session.py -v`
Expected: PASS toàn bộ (cả test cũ — fixture đã thêm addressee mock settings; mode mặc định "off" giữ test cũ nguyên hành vi).

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/server/base_session.py tests/unit/test_base_session.py
git commit src/noble_agent/server/base_session.py tests/unit/test_base_session.py \
  -m "feat(voice): addressee gate in BaseSession — episode, soft-pause, verdict, final gate"
```

---

### Task 6: Telephony session integration

**Files:**
- Modify: `src/noble_agent/telephony/session.py` (`__init__`, `_handle_audio` ~161-173, `_on_partial` ~234, `_on_final` ~238)
- Test: `tests/unit/test_telephony_addressee.py` (mới)

**Interfaces:**
- Consumes: `addressee_gate.classify/Verdict/EpisodeTracker`, `agent.pause_playback()/resume_playback()/current_clause_text` — y hệt Task 5. Telephony KHÔNG có `AudioOutput.clear()` (frame ghi thẳng Asterisk, buffer ~20ms) → pause chỉ cần `agent.pause_playback()`.
- Produces: hành vi telephony tương đương BaseSession (subset: không speaker gates, không smart-turn).

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_telephony_addressee.py
"""Addressee gate trên đường telephony — logic subset của BaseSession."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from noble_agent.voice.addressee_gate import Verdict


def _bare_tel_session():
    from noble_agent.telephony.session import TelephonySession

    s = TelephonySession.__new__(TelephonySession)
    s.agent = AsyncMock()
    s.agent.interrupt = MagicMock()
    s.agent.pause_playback = MagicMock()
    s.agent.resume_playback = MagicMock()
    s.agent.current_clause_text = "đang nói dở"
    s.vad = MagicMock()
    s.metrics = MagicMock()
    s._agent_task = None
    s._stt_audio_start = 0.0
    s._addr_gate_enabled = True
    s._addr_episode_verdict = None
    s._addr_paused = False
    s._addr_verdict_inflight = False
    s._addr_episode_active = False
    s._last_user_text = ""
    s._bg_tasks = set()
    from noble_agent.voice.addressee_gate import EpisodeTracker

    s._addr_tracker = EpisodeTracker(min_speech_ms=400, chunk_ms=32)
    s._addr_deadline_handle = None
    return s


class TestTelephonyAddressee:
    async def test_side_talk_final_dropped(self) -> None:
        s = _bare_tel_session()
        s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(return_value=Verdict.SIDE_TALK),
        ):
            await s._on_final("anh ơi ra ăn cơm")
        assert not s._agent_task.done()  # không bị cancel
        s._agent_task.cancel()

    async def test_directed_final_triggers_agent(self) -> None:
        s = _bare_tel_session()
        started: list[str] = []

        async def _fake_trigger(text: str) -> None:
            started.append(text)

        s._trigger_agent = _fake_trigger
        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(return_value=Verdict.DIRECTED),
        ):
            await s._on_final("em ơi giá căn đó bao nhiêu")
        assert started == ["em ơi giá căn đó bao nhiêu"]

    async def test_gate_disabled_passthrough(self) -> None:
        s = _bare_tel_session()
        s._addr_gate_enabled = False
        started: list[str] = []

        async def _fake_trigger(text: str) -> None:
            started.append(text)

        s._trigger_agent = _fake_trigger
        await s._on_final("bất kỳ")
        assert started == ["bất kỳ"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_telephony_addressee.py -v`
Expected: FAIL — telephony `_on_final` chưa có gate (side-talk vẫn trigger) / thiếu field.

- [ ] **Step 3: Implement telephony integration**

3a. Import: `from noble_agent.voice import addressee_gate` + `from noble_agent.voice.addressee_gate import EpisodeTracker, Verdict`.

3b. `__init__`: thêm cùng bộ field như BaseSession 3b (gate_enabled, tracker, episode_active, paused, verdict_inflight, episode_verdict, deadline_handle, _last_user_text, `_bg_tasks: set = set()` nếu chưa có).

3c. `_handle_audio` — nhánh INTERRUPTED (line ~168) thành:

```python
            if result["state"] == VADState.INTERRUPTED:
                if self._agent_task and not self._agent_task.done():
                    if self._addr_gate_enabled:
                        self._begin_addressee_episode()
                    else:
                        logger.info("[TEL] Interruption detected — cancelling agent task")
                        self.agent.interrupt()
                        self._agent_task.cancel()
                        self.vad.set_idle()
            elif self._addr_episode_active and not self._addr_paused:
                action = self._addr_tracker.feed(result["is_speech"])
                if action == "pause":
                    await self._addressee_soft_pause()
                elif action == "reset":
                    self._addr_episode_active = False
                    self.vad.set_speaking()
```

3d. Copy 5 method từ BaseSession Task 5-3d (`_begin_addressee_episode`, `_addressee_soft_pause` — BỎ nhánh `_audio_output.clear()` vì telephony không có, `_addressee_deadline`, `_addr_reset_episode`, `_addressee_commit_interrupt` — commit dùng trình tự telephony cũ: `self.agent.interrupt(); self._agent_task.cancel(); self.vad.set_idle()`, và `_classify_addressee`). `_agent_is_speaking` helper: `self._agent_task is not None and not self._agent_task.done()`.

3e. `_on_partial`: thêm cùng hook như BaseSession 3e.

3f. `_on_final` — trước `await self._trigger_agent(text)`:

```python
        if self._addr_gate_enabled:
            verdict = self._addr_episode_verdict
            self._addr_episode_verdict = None
            if verdict is Verdict.SIDE_TALK:
                logger.info("[TEL][Addressee] Dropped side-talk final: %r", text)
                return
            if verdict is None and self._agent_task and not self._agent_task.done():
                v = await addressee_gate.classify(
                    text,
                    agent_line=getattr(self.agent, "current_clause_text", ""),
                    last_user_text=self._last_user_text,
                    agent_name=settings.agent_name,
                )
                if v is Verdict.SIDE_TALK:
                    logger.info("[TEL][Addressee] Dropped side-talk final mid-turn: %r", text)
                    self._addr_reset_episode()
                    self.vad.set_speaking()
                    return
        self._last_user_text = text
```

(telephony không có nhánh when_idle — PSTN 1-1, side-talk khi agent im hiếm; giữ subset gọn. Ghi chú comment.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_telephony_addressee.py tests/unit/test_base_session.py -v`
Expected: PASS

- [ ] **Step 5: Lint + commit**

```bash
ruff check src/noble_agent/telephony/session.py tests/unit/test_telephony_addressee.py
git commit src/noble_agent/telephony/session.py tests/unit/test_telephony_addressee.py \
  -m "feat(voice): addressee gate on telephony path"
```

---

### Task 7: Docs + changelog + full test sweep

**Files:**
- Modify: `CLAUDE.md` (bảng Change Log — thêm entry mới, XÓA entry thứ 11; cân nhắc thêm 1 dòng vào bảng Key configuration nếu còn budget ≤45KB)
- Modify: `docs/CHANGELOG-agent.md` (entry đầy đủ lên ĐẦU bảng)
- Modify: `src/noble_agent/SMOKE.md` (thêm mục smoke: bật `ADDRESSEE_GATE_MODE=hybrid`, giả side-talk → agent pause rồi "xin phép nói tiếp"; nói "em ơi" → ngắt thật)

**Interfaces:** — (docs only)

- [ ] **Step 1: Full regression sweep**

Run: `make test-unit`
Expected: PASS (lưu ý memory `unit-suite-env-dependent-failures`: ~30 fail phụ thuộc .env/data — diff với baseline trước khi đổ lỗi cho change; đối chiếu bằng `git stash` KHÔNG được phép — dùng so sánh danh sách fail trước/sau bằng cách chạy trên commit trước qua `git worktree`? KHÔNG — worktree bị cấm. Chạy `pytest tests/unit -q` và so danh sách fail với lần chạy đầu Task 1 Step 2 đã ghi nhận.)

Ghi lại danh sách fail (nếu có) TRƯỚC khi bắt đầu Task 1 để làm baseline: `pytest tests/unit -q 2>&1 | tail -30 > /tmp/claude-1000/.../baseline-unit.txt` (scratchpad).

- [ ] **Step 2: CLAUDE.md changelog (2 chỗ) + SMOKE.md**

Entry 1–2 câu cho bảng `## Change Log` (xóa entry cũ nhất cho đủ 10):

> | 2026-08-12 | Addressee gate chống nói leo (`ADDRESSEE_GATE_MODE=off\|heuristic\|llm\|hybrid`): tiếng đè lên agent ≥400ms → soft-pause pacer (không cancel turn) → classifier heuristic/LLM phán DIRECTED (commit interrupt) hay SIDE_TALK (ack "Em xin phép được nói tiếp ạ" + phát lại clause dở, drop final). Fail-open DIRECTED mọi đường lỗi. | VAD interrupt thuần năng lượng khiến khách nói chuyện với người bên cạnh cũng ngắt + được agent trả lời; tắt interrupt thì agent nói không ngắt được. |

Entry đầy đủ tương ứng vào `docs/CHANGELOG-agent.md` (đầu bảng). SMOKE.md: thêm mục "Addressee gate" với 3 bước thử tay (side-talk → resume + ack; "em ơi" → ngắt; mode off → behavior cũ).

- [ ] **Step 3: Commit docs**

```bash
git commit CLAUDE.md docs/CHANGELOG-agent.md src/noble_agent/SMOKE.md \
  -m "docs: addressee gate changelog + smoke checklist"
```

- [ ] **Step 4: Manual smoke (user-gated)**

Báo user chạy: `scripts/run.sh` + browser voice (memory `voice-startup-recipe`), test 3 kịch bản SMOKE mới. LLM verdict cần key + Redis như thường. Đây là bước user xác nhận hành vi thật — không tự động được.

---

## Self-review đã chạy

- **Spec coverage:** flow soft-pause/verdict/resume-ack/final-gate (Task 4+5), classifier 2 tầng + env (Task 1-3), telephony (Task 6), gen_ack_assets resume ack (Task 4 Step 5), docs (Task 7), when_idle (Task 5 3f). Đủ.
- **Type consistency:** `Verdict` enum dùng xuyên suốt; `classify(text, *, agent_line, last_user_text, agent_name)` thống nhất Task 3/5/6; `EpisodeTracker.feed → "pause"|"reset"|None` thống nhất Task 2/5/6; `current_clause_text` property (Task 4) đọc qua getattr ở Task 5/6.
- **Known trade-offs (chấp nhận, đã ghi):** đuôi clause TRƯỚC đó đã nằm trong transport buffer lúc clear sẽ mất (replay chỉ phủ clause hiện tại); greeting `speak_text` pause được nhưng không replay; mode multi-speaker ưu tiên SpeakerFloor, gate không tham gia nhánh INTERRUPTED của nó.
