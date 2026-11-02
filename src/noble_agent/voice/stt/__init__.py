"""STT backends — pluggable Speech-to-Text providers.

All backends implement the same async interface:
    stt = SonioxSTT(on_partial=..., on_final=...)
    await stt.start()
    await stt.send(pcm_bytes)   # PCM int16, 16kHz, mono
    await stt.stop()

Switch via .env: STT_BACKEND=soniox | sherpa | elevenlabs | qwen3asr
"""

from noble_agent.voice.stt.base import STTBase

__all__ = ["STTBase"]
