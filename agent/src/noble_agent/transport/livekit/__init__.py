"""LiveKit RTC transport — Phase 1+ of LIVEKIT_MIGRATION.md.

Public surface (grows with each phase):
- `AgentAudioIO` — wraps a LiveKit `Room` + caller audio track, exposes a
  PCM16 input stream and a PCM16 output sink with fast interrupt via
  `clear_output_queue()`.
- `codec_utils` — ulaw ↔ pcm16 helpers for telephony (8 kHz mono).
"""

from __future__ import annotations

from noble_agent.transport.livekit.agent_audio_io import AgentAudioIO, AudioIOConfig
from noble_agent.transport.livekit.codec_utils import pcm16_to_ulaw, ulaw_to_pcm16
from noble_agent.transport.livekit.room_session import RoomSession
from noble_agent.transport.livekit.worker import entrypoint, run_worker

__all__ = [
    "AgentAudioIO",
    "AudioIOConfig",
    "RoomSession",
    "entrypoint",
    "pcm16_to_ulaw",
    "run_worker",
    "ulaw_to_pcm16",
]
