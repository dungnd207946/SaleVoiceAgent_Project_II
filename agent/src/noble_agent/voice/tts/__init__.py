"""TTS backends — pluggable Text-to-Speech providers.

All backends expose the same async generator interface:
    tts = AsyncElevenLabsTTS()
    async for chunk in tts.stream("Xin chào"):
        send_audio(chunk)  # PCM int16, 24kHz, mono

Switch via .env: TTS_BACKEND=vieneu | elevenlabs
"""
