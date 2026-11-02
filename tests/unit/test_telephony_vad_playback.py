"""`TelephonySession._send_audio` must flag the VAD that agent audio is really
playing (`vad.playback_active`), so the barge-in RMS floor only applies while
echo is possible. Built via `__new__` like test_telephony_billing.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from noble_agent.config import settings
from noble_agent.telephony.session import TelephonySession


def _session() -> TelephonySession:
    s = TelephonySession.__new__(TelephonySession)
    s._running = True
    s._tts_active = False
    s._writer = MagicMock()
    s._writer.drain = AsyncMock()
    s.vad = MagicMock()
    s.vad.playback_active = False
    return s


@pytest.mark.asyncio
async def test_send_audio_marks_vad_playback_active() -> None:
    s = _session()
    pcm_20ms = np.zeros(int(settings.tts_sample_rate * 0.02), dtype=np.int16).tobytes()
    with patch("noble_agent.telephony.session.AudioSocketServer.write_audio_frame"):
        await s._send_audio(pcm_20ms)
    assert s.vad.playback_active is True


@pytest.mark.asyncio
async def test_send_audio_not_running_leaves_flag() -> None:
    s = _session()
    s._running = False
    await s._send_audio(b"\x00\x00" * 480)
    assert s.vad.playback_active is False
