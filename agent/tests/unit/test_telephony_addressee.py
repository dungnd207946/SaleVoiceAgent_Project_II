"""Addressee gate trên đường telephony — logic subset của BaseSession."""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

from noble_agent.voice.addressee_gate import Verdict


def _bare_tel_session():
    from noble_agent.telephony.session import TelephonySession

    s = TelephonySession.__new__(TelephonySession)
    s.agent = AsyncMock()
    s.agent.interrupt = MagicMock()
    s.agent.pause_playback = MagicMock()
    s.agent.resume_playback = MagicMock()
    s.agent.spoken_text_this_turn = "đang nói dở"
    s._dialogue_ring = deque(maxlen=6)
    s.vad = MagicMock()
    s.metrics = MagicMock()
    s._agent_task = None
    s._stt_audio_start = 0.0
    s._addr_gate_enabled = True
    s._addr_episode_verdict = None
    s._addr_paused = False
    s._addr_episode_active = False
    s._last_user_text = ""
    s._bg_tasks = set()
    s._addr_episode_gen = 0
    from noble_agent.voice.addressee_gate import EpisodeTracker

    s._addr_tracker = EpisodeTracker(min_speech_ms=400, chunk_ms=32)
    s._addr_deadline_handle = None
    s.billing = None  # billing metering off by default (fix round 1, Task 7)
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
        assert list(s._dialogue_ring) == []  # dropped final never enters the ring
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

    async def test_paused_final_side_talk_resumes_and_drops(self) -> None:
        """Amendment đêm 2026-08-12: verdict giờ quyết trên FINAL, không còn
        classify trên partial. Paused + final classify → SIDE_TALK → resume,
        final bị drop (agent task vẫn là task đang ngủ ban đầu)."""
        s = _bare_tel_session()
        s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
        original_task = s._agent_task
        s._addr_paused = True
        s._addr_episode_active = True
        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(return_value=Verdict.SIDE_TALK),
        ):
            await s._on_final("con ơi ăn cơm đi")
        s.agent.resume_playback.assert_called_once()
        assert s._agent_task is original_task
        assert not s._agent_task.done()
        assert list(s._dialogue_ring) == []
        assert s._addr_paused is False
        s._agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task

    async def test_paused_final_directed_commits_and_triggers(self) -> None:
        """Paused + final classify → DIRECTED → commit interrupt rồi trigger
        MỘT turn mới với chính final đó."""
        s = _bare_tel_session()
        s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
        s._addr_paused = True
        s._addr_episode_active = True
        started: list[str] = []

        async def _fake_trigger(text: str) -> None:
            started.append(text)

        s._trigger_agent = _fake_trigger
        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(return_value=Verdict.DIRECTED),
        ):
            await s._on_final("em ơi cho anh hỏi giá")

        s.agent.interrupt.assert_called_once()  # commit went through _addressee_commit_interrupt
        assert started == ["em ơi cho anh hỏi giá"]
        assert s._addr_episode_verdict is None

        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task  # drain the cancelled sleep(10) task cleanly

    async def test_paused_final_mixed_sentence_directed(self) -> None:
        """Prompt-rule doc test: câu hỗn hợp (side-talk + nội dung hướng tới
        agent) → DIRECTED. Rule thật nằm trong _LLM_PROMPT; ở mức session
        này chỉ verify plumbing."""
        s = _bare_tel_session()
        s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
        s._addr_paused = True
        s._addr_episode_active = True
        started: list[str] = []

        async def _fake_trigger(text: str) -> None:
            started.append(text)

        s._trigger_agent = _fake_trigger
        mixed_text = "con đi ăn cơm ngay cho bố, bên em giá căn hộ như thế nào"
        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(return_value=Verdict.DIRECTED),
        ):
            await s._on_final(mixed_text)

        s.agent.interrupt.assert_called_once()
        assert started == [mixed_text]
        assert s._addr_episode_verdict is None

        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task

    async def test_deadline_uses_max_pause_ms(self) -> None:
        """`_addr_deadline_s()` giờ đọc trực tiếp ADDRESSEE_MAX_PAUSE_MS."""
        from noble_agent.config import settings

        s = _bare_tel_session()
        original = settings.addressee_max_pause_ms
        settings.addressee_max_pause_ms = 1234
        try:
            assert s._addr_deadline_s() == 1.234
        finally:
            settings.addressee_max_pause_ms = original

    async def test_final_classify_races_live_deadline_falls_through_directed(self) -> None:
        """IMPORTANT-1 regression (review round 1): the deadline can fire
        WHILE the inline classify is in flight (awaiting the LLM) and
        resolve the SAME episode itself (fail-open DIRECTED commit) before
        our verdict lands. The epoch-guard must detect that and NOT take
        the SIDE_TALK arm — the deadline's commit is authoritative; the
        final proceeds as a normal turn instead of being dropped into dead
        air on top of an already-committed interrupt."""
        s = _bare_tel_session()
        s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
        s._addr_paused = True
        s._addr_episode_active = True
        started: list[str] = []

        async def _fake_trigger(text: str) -> None:
            started.append(text)

        s._trigger_agent = _fake_trigger

        async def _classify_races_deadline(*_args, **_kwargs):
            # Simulates the deadline timer firing WHILE this classify call
            # is still in flight — it resolves (and commits) the SAME
            # episode before we return our own (now-stale) verdict.
            await s._addressee_deadline()
            return Verdict.SIDE_TALK

        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(side_effect=_classify_races_deadline),
        ):
            await s._on_final("anh ơi con khóc kìa")

        s.agent.interrupt.assert_called_once()  # committed exactly once (by the deadline)
        assert started == ["anh ơi con khóc kìa"]  # final proceeded, not dropped
        assert s._addr_episode_verdict is None  # not leaked to the next final
        s.agent.resume_playback.assert_not_called()  # SIDE_TALK arm never taken

        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task

    async def test_paused_but_turn_finished_naturally_side_talk_does_not_rearm_vad(self) -> None:
        """MINOR-2 (telephony mirror): when the turn already finished
        naturally (agent not "speaking") and classify still returns
        SIDE_TALK, `vad.set_speaking()` must NOT fire (base_session also
        restarts its idle timer here — telephony has no idle-timer
        mechanism to mirror)."""
        s = _bare_tel_session()

        async def _already_done() -> None:
            return None

        s._agent_task = asyncio.ensure_future(_already_done())
        await s._agent_task
        assert s._agent_task.done()

        s._addr_paused = True
        s._addr_episode_active = True

        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(return_value=Verdict.SIDE_TALK),
        ) as mock_classify:
            await s._on_final("con ơi ăn cơm đi")

        mock_classify.assert_awaited_once()
        s.agent.resume_playback.assert_called_once()
        assert s._addr_paused is False
        s.vad.set_speaking.assert_not_called()


class _LatchingFakeVAD:
    """Faithful replica of the REAL SileroVAD's INTERRUPTED-latch semantics
    (`voice/vad/silero.py::_update_state`): once in INTERRUPTED there is NO
    exit transition — every subsequent chunk keeps returning INTERRUPTED
    until `set_speaking()` / `set_idle()` is called explicitly. The plain
    `MagicMock` used by `_bare_tel_session()` does NOT reproduce this — it
    just returns whatever was last configured — which is why the production
    bug this regression covers slipped past the existing addressee tests.

    Starts in SPEAKING (agent is mid-turn); every chunk is speech, matching
    the "khách nói leo liên tục" scenario the gate exists to catch.
    """

    def __init__(self, confirm_chunks: int = 3) -> None:
        from noble_agent.voice.vad import VADState

        self._VADState = VADState
        self._confirm_chunks = confirm_chunks
        self.state = VADState.SPEAKING
        self._interrupt_chunks = 0
        self.speaking_resets = 0

    def process_chunk(self, _chunk: bytes) -> dict:
        is_speech = True
        if self.state == self._VADState.SPEAKING:
            self._interrupt_chunks += 1
            if self._interrupt_chunks >= self._confirm_chunks:
                self.state = self._VADState.INTERRUPTED
                self._interrupt_chunks = 0
        # INTERRUPTED: latched — no exit transition (mirrors the real bug).
        return {"state": self.state, "is_speech": is_speech, "speech_prob": 0.9, "state_changed": False}

    def set_speaking(self) -> None:
        self.state = self._VADState.SPEAKING
        self._interrupt_chunks = 0
        self.speaking_resets += 1

    def set_idle(self) -> None:
        self.state = self._VADState.IDLE
        self._interrupt_chunks = 0


class TestTelephonyVADLatchRegression:
    async def test_latching_vad_does_not_starve_episode_tracker(self) -> None:
        """CRITICAL-1 (telephony mirror): with the real VAD's INTERRUPTED-latch
        behavior, ~20 consecutive speech chunks over an agent turn must still
        cross the 400ms soft-pause threshold and call `agent.pause_playback()`.
        Pre-fix routing (`if INTERRUPTED: ... elif episode_active: feed
        tracker`) starves the tracker after the first re-arm — see the
        base_session sibling test for the full mechanism."""
        from noble_agent.telephony.session import VAD_CHUNK_BYTES

        s = _bare_tel_session()
        s.vad = _LatchingFakeVAD(confirm_chunks=3)
        s.stt = None
        s._vad_buf = b""
        s._audio_ring = bytearray()
        s._agent_task = asyncio.ensure_future(asyncio.sleep(10))

        for _ in range(20):
            await s._handle_audio(b"\x00" * VAD_CHUNK_BYTES)

        s.agent.pause_playback.assert_called_once()
        assert not s._agent_task.done()  # soft-pause, turn stays alive
        s._agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task


class TestTelephonyDialogueRing:
    """Dialogue ring (2026-08-12 chiều amendment) — telephony mirror of
    tests/unit/test_base_session.py::TestAddresseeDialogueRing."""

    async def test_trigger_agent_appends_prior_agent_text_then_user_text(self) -> None:
        s = _bare_tel_session()
        s.agent.spoken_text_this_turn = "Dạ dự án này ở quận 2 ạ."

        await s._trigger_agent("giá bao nhiêu vậy")

        assert list(s._dialogue_ring) == [
            ("agent", "Dạ dự án này ở quận 2 ạ."),
            ("user", "giá bao nhiêu vậy"),
        ]
        s._agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task

    async def test_trigger_agent_skips_empty_prior_agent_text(self) -> None:
        s = _bare_tel_session()
        s.agent.spoken_text_this_turn = ""

        await s._trigger_agent("chào em")

        assert list(s._dialogue_ring) == [("user", "chào em")]
        s._agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task

    async def test_final_inline_classify_while_paused_passes_recent_dialogue_and_spoken_text(self) -> None:
        """The inline classify branch of `_on_final` also fires while the
        gate is soft-paused (not just while the agent is speaking) — same
        ring + spoken-text context must reach `classify()`."""
        s = _bare_tel_session()
        s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
        s._addr_paused = True
        s._addr_episode_active = True
        s._dialogue_ring.append(("user", "trước đó khách hỏi gì đó"))
        s.agent.spoken_text_this_turn = "em đang nói dở câu này"

        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(return_value=Verdict.SIDE_TALK),
        ) as mock_classify:
            await s._on_final("em ơi cho anh hỏi giá")

        _, kwargs = mock_classify.call_args
        assert kwargs["recent_dialogue"] == (("user", "trước đó khách hỏi gì đó"),)
        assert kwargs["agent_line"] == "em đang nói dở câu này"

        s._agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task

    async def test_on_final_inline_classify_passes_recent_dialogue_and_spoken_text(self) -> None:
        s = _bare_tel_session()
        s._agent_task = asyncio.ensure_future(asyncio.sleep(10))
        s._dialogue_ring.append(("user", "câu trước"))
        s.agent.spoken_text_this_turn = "câu agent đang nói"

        with patch(
            "noble_agent.telephony.session.addressee_gate.classify",
            new=AsyncMock(return_value=Verdict.SIDE_TALK),
        ) as mock_classify:
            await s._on_final("ừ đúng đấy")

        _, kwargs = mock_classify.call_args
        assert kwargs["recent_dialogue"] == (("user", "câu trước"),)
        assert kwargs["agent_line"] == "câu agent đang nói"

        s._agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task


class TestTelephonyStaleDeadlineOnNewTurn:
    async def test_trigger_agent_resets_stale_paused_episode(self) -> None:
        """IMPORTANT-2 (telephony mirror): a paused episode left over from a
        turn that ended naturally must not survive into the NEXT turn —
        `_trigger_agent` must reset the episode (cancelling any armed
        deadline) before starting the new turn."""
        s = _bare_tel_session()
        s._addr_paused = True
        s._addr_episode_active = True
        loop = asyncio.get_running_loop()
        handle = loop.call_later(10, lambda: None)
        s._addr_deadline_handle = handle

        await s._trigger_agent("câu hỏi hợp lệ ở lượt mới")

        assert handle.cancelled()
        assert s._addr_paused is False
        assert s._addr_episode_active is False

        s._agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await s._agent_task
