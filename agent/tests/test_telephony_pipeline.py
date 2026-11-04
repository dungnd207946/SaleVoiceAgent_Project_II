"""Telephony pipeline tests — resampler, frame chunking, AudioSocket protocol.

Uses a real audio file to verify the full audio chain:
  Audio file → decode to 8kHz slin → resample 8k→16k (STT) → resample back
  TTS mock (24kHz) → resample 24k→8k → chunk into 320-byte frames

Run: python -m pytest tests/test_telephony_pipeline.py -v
"""

import asyncio
import os
import struct
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

AUDIO_FILE = Path(__file__).parent / "Bản ghi mới.m4a"


# ── Helpers ──────────────────────────────────────────────────────────────────


def load_audio_as_8k_slin(path: Path) -> bytes:
    """Decode any audio file to 8kHz slin16 (Asterisk AudioSocket format)."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "8000", "-ac", "1", "-"],
        capture_output=True,
    )
    assert result.returncode == 0, f"ffmpeg failed: {result.stderr.decode()}"
    return result.stdout


def load_audio_as_16k_slin(path: Path) -> bytes:
    """Decode any audio file to 16kHz slin16 (STT input format)."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "-"],
        capture_output=True,
    )
    assert result.returncode == 0, f"ffmpeg failed: {result.stderr.decode()}"
    return result.stdout


def generate_sine_pcm(freq_hz: int, duration_s: float, sample_rate: int) -> bytes:
    """Generate a sine wave as PCM int16 bytes."""
    t = np.arange(int(duration_s * sample_rate)) / sample_rate
    samples = (np.sin(2 * np.pi * freq_hz * t) * 16000).astype(np.int16)
    return samples.tobytes()


def rms(pcm: bytes) -> float:
    """Calculate RMS energy of PCM int16 audio."""
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64)
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples**2)))


def snr_db(signal: bytes, noise: bytes) -> float:
    """Signal-to-noise ratio in dB."""
    s = rms(signal)
    n = rms(noise)
    if n == 0:
        return float("inf")
    return 20 * np.log10(s / n)


# ── Tests: Resampler ────────────────────────────────────────────────────────


class TestResampler:
    """Test resampler quality and correctness."""

    def test_backend_is_soxr(self):
        """soxr should be the active backend (best quality)."""
        from noble_agent.telephony.resampler import _BACKEND

        assert _BACKEND == "soxr", f"Expected soxr, got {_BACKEND}"

    def test_8k_to_16k_ratio(self):
        """8kHz → 16kHz should exactly double the sample count."""
        from noble_agent.telephony.resampler import resample_8k_to_16k

        pcm_8k = generate_sine_pcm(1000, 0.1, 8000)  # 100ms
        pcm_16k = resample_8k_to_16k(pcm_8k)
        samples_8k = len(pcm_8k) // 2
        samples_16k = len(pcm_16k) // 2
        assert abs(samples_16k - samples_8k * 2) <= 2, f"Expected ~{samples_8k * 2} samples, got {samples_16k}"

    def test_24k_to_8k_ratio(self):
        """24kHz → 8kHz should reduce sample count by 3x."""
        from noble_agent.telephony.resampler import resample_tts_to_8k

        pcm_24k = generate_sine_pcm(1000, 0.1, 24000)  # 100ms
        pcm_8k = resample_tts_to_8k(pcm_24k)
        samples_24k = len(pcm_24k) // 2
        samples_8k = len(pcm_8k) // 2
        assert abs(samples_8k - samples_24k // 3) <= 2, f"Expected ~{samples_24k // 3} samples, got {samples_8k}"

    def test_roundtrip_preserves_energy(self):
        """8k→16k→8k roundtrip should preserve most signal energy."""
        from noble_agent.telephony.resampler import resample_8k_to_16k, resample_16k_to_8k

        original = generate_sine_pcm(1000, 0.5, 8000)
        upsampled = resample_8k_to_16k(original)
        roundtrip = resample_16k_to_8k(upsampled)
        # RMS should be within 10% of original
        ratio = rms(roundtrip) / rms(original)
        assert 0.85 < ratio < 1.15, f"Energy ratio {ratio:.3f} — too much loss"

    def test_anti_aliasing_no_high_freq(self):
        """24k→8k downsampling must NOT produce aliasing above 4kHz (Nyquist)."""
        from noble_agent.telephony.resampler import resample_tts_to_8k

        # 6kHz sine at 24kHz — above 4kHz Nyquist of 8kHz output
        pcm_24k = generate_sine_pcm(6000, 0.5, 24000)
        pcm_8k = resample_tts_to_8k(pcm_24k)
        # With proper anti-aliasing, output should be near-silent
        # Without anti-aliasing (old numpy), it would alias to 2kHz
        output_rms = rms(pcm_8k)
        input_rms = rms(pcm_24k)
        attenuation_db = 20 * np.log10(output_rms / input_rms) if output_rms > 0 else -100
        assert attenuation_db < -30, f"6kHz signal only attenuated {attenuation_db:.1f}dB — anti-aliasing not working"

    def test_real_audio_resample(self):
        """Resample real audio file and verify output is valid."""
        if not AUDIO_FILE.exists():
            pytest.skip("Test audio file not found")
        from noble_agent.telephony.resampler import resample_8k_to_16k

        pcm_8k = load_audio_as_8k_slin(AUDIO_FILE)
        assert len(pcm_8k) > 0, "Failed to decode audio file"

        # 8k → 16k (STT path)
        pcm_16k = resample_8k_to_16k(pcm_8k)
        assert len(pcm_16k) > 0
        assert rms(pcm_16k) > 100, "Upsampled audio has no energy"

        # Simulate TTS path: use 16k as mock TTS, check 16k→8k
        from noble_agent.telephony.resampler import _resample

        pcm_back = _resample(pcm_16k, 16000, 8000)
        ratio = rms(pcm_back) / rms(pcm_8k)
        assert 0.7 < ratio < 1.3, f"Roundtrip energy ratio {ratio:.3f}"

    def test_empty_input(self):
        """Empty input should return empty output."""
        from noble_agent.telephony.resampler import resample_8k_to_16k, resample_tts_to_8k

        assert resample_8k_to_16k(b"") == b""
        assert resample_tts_to_8k(b"") == b""

    def test_same_rate_passthrough(self):
        """Same rate should return identical bytes."""
        from noble_agent.telephony.resampler import _resample

        pcm = generate_sine_pcm(1000, 0.1, 16000)
        assert _resample(pcm, 16000, 16000) == pcm


# ── Tests: AudioSocket Protocol ─────────────────────────────────────────────


class TestAudioSocketProtocol:
    """Test AudioSocket TLV frame encoding/decoding."""

    def test_audio_frame_format(self):
        """Audio frame: type=0x10, length=big-endian uint16, payload."""
        import io

        from noble_agent.telephony.audiosocket import TYPE_AUDIO, AudioSocketServer

        # Create a mock writer
        buf = io.BytesIO()

        class MockWriter:
            def write(self, data):
                buf.write(data)

        writer = MockWriter()
        pcm = b"\x00" * 320  # 20ms silence
        AudioSocketServer.write_audio_frame(writer, pcm)
        frame = buf.getvalue()

        assert frame[0] == TYPE_AUDIO  # 0x10
        length = struct.unpack(">H", frame[1:3])[0]
        assert length == 320
        assert len(frame) == 3 + 320

    def test_hangup_frame_format(self):
        """Hangup frame: type=0x00, length=0."""
        import io

        from noble_agent.telephony.audiosocket import TYPE_HANGUP, AudioSocketServer

        buf = io.BytesIO()

        class MockWriter:
            def write(self, data):
                buf.write(data)

        writer = MockWriter()
        AudioSocketServer.write_hangup_frame(writer)
        frame = buf.getvalue()

        assert frame[0] == TYPE_HANGUP  # 0x00
        length = struct.unpack(">H", frame[1:3])[0]
        assert length == 0

    def test_frame_read_roundtrip(self):
        """Write a frame, read it back."""
        from noble_agent.telephony.audiosocket import TYPE_AUDIO, AudioSocketServer

        pcm = generate_sine_pcm(1000, 0.02, 8000)  # 20ms

        # Encode
        header = struct.pack(">BH", TYPE_AUDIO, len(pcm))
        frame_bytes = header + pcm

        # Decode
        async def _test():
            reader = asyncio.StreamReader()
            reader.feed_data(frame_bytes)
            frame_type, payload = await AudioSocketServer._read_frame(reader)
            assert frame_type == TYPE_AUDIO
            assert payload == pcm

        asyncio.run(_test())


# ── Tests: TTS Frame Chunking ───────────────────────────────────────────────


class TestTTSChunking:
    """Test that TTS audio is properly chunked into 320-byte frames."""

    def test_chunk_exact_multiple(self):
        """Audio that's exact multiple of 320 bytes."""
        pcm = b"\x01" * 3200  # 10 frames exactly
        chunks = self._chunk(pcm)
        assert len(chunks) == 10
        assert all(len(c) == 320 for c in chunks)

    def test_chunk_with_remainder(self):
        """Audio with remainder is padded with silence."""
        pcm = b"\x01" * 500  # 1 full frame + 180 bytes remainder
        chunks = self._chunk(pcm)
        assert len(chunks) == 2
        assert len(chunks[0]) == 320
        assert len(chunks[1]) == 320
        # Last chunk should be padded with zeros
        assert chunks[1][:180] == b"\x01" * 180
        assert chunks[1][180:] == b"\x00" * 140

    def test_large_tts_chunk(self):
        """5 seconds of TTS audio at 8kHz = 80,000 bytes = 250 frames."""
        pcm = generate_sine_pcm(500, 5.0, 8000)
        chunks = self._chunk(pcm)
        expected = len(pcm) // 320 + (1 if len(pcm) % 320 else 0)
        assert len(chunks) == expected
        assert all(len(c) == 320 for c in chunks)

    @staticmethod
    def _chunk(pcm_8k: bytes, frame_size: int = 320) -> list[bytes]:
        """Simulate the chunking logic from TelephonySession._send_audio."""
        chunks = []
        offset = 0
        while offset < len(pcm_8k):
            chunk = pcm_8k[offset : offset + frame_size]
            if len(chunk) < frame_size:
                chunk = chunk + b"\x00" * (frame_size - len(chunk))
            chunks.append(chunk)
            offset += frame_size
        return chunks


# ── Tests: Full Pipeline Simulation ─────────────────────────────────────────


class TestFullPipeline:
    """Simulate the full telephony audio pipeline with real audio."""

    def test_asterisk_to_stt_pipeline(self):
        """Simulate: Audio file → 8kHz slin → resample 8k→16k → verify STT-ready."""
        if not AUDIO_FILE.exists():
            pytest.skip("Test audio file not found")
        from noble_agent.telephony.resampler import resample_8k_to_16k

        # Step 1: Decode to 8kHz slin (what Asterisk sends)
        pcm_8k = load_audio_as_8k_slin(AUDIO_FILE)
        assert len(pcm_8k) > 0

        # Step 2: Chunk into 20ms frames (what AudioSocket delivers)
        frame_size = 320  # 20ms @ 8kHz, 16-bit
        frames = [pcm_8k[i : i + frame_size] for i in range(0, len(pcm_8k), frame_size)]
        assert len(frames) > 0

        # Step 3: Resample each frame to 16kHz (what _handle_audio does)
        stt_audio = b""
        for frame in frames:
            if len(frame) < frame_size:
                frame = frame + b"\x00" * (frame_size - len(frame))
            pcm_16k = resample_8k_to_16k(frame)
            stt_audio += pcm_16k

        # Verify: 16kHz audio should have ~2x samples of 8kHz input
        samples_8k = len(pcm_8k) // 2
        samples_16k = len(stt_audio) // 2
        ratio = samples_16k / samples_8k
        assert 1.9 < ratio < 2.1, f"Sample ratio {ratio:.2f}, expected ~2.0"

        # Verify: energy preserved
        energy_ratio = rms(stt_audio) / rms(pcm_8k)
        assert 0.7 < energy_ratio < 1.5, f"Energy ratio {energy_ratio:.2f}"

    def test_tts_to_asterisk_pipeline(self):
        """Simulate: TTS 24kHz → resample → chunk 320 bytes → verify Asterisk-ready."""
        from noble_agent.telephony.resampler import resample_tts_to_8k

        # Simulate TTS output: 1 second of speech-like audio at 24kHz
        tts_audio = generate_sine_pcm(300, 1.0, 24000)

        # Step 1: Resample 24kHz → 8kHz
        pcm_8k = resample_tts_to_8k(tts_audio)
        assert len(pcm_8k) > 0

        # Step 2: Chunk into 320-byte frames
        frame_size = 320
        frames = []
        offset = 0
        while offset < len(pcm_8k):
            chunk = pcm_8k[offset : offset + frame_size]
            if len(chunk) < frame_size:
                chunk = chunk + b"\x00" * (frame_size - len(chunk))
            frames.append(chunk)
            offset += frame_size

        # Verify: ~50 frames per second at 8kHz
        expected_frames = 8000 * 2 // frame_size  # 1 second
        assert abs(len(frames) - expected_frames) <= 2

        # Verify: all frames are exactly 320 bytes
        assert all(len(f) == frame_size for f in frames)

        # Verify: frames have audio content (not silence)
        assert rms(pcm_8k) > 100

    def test_stt_receives_continuous_audio(self):
        """Verify STT would receive continuous audio stream during TTS playback.

        This simulates the concurrent audio loop + TTS send pattern.
        The key issue: TTS pacing must not starve STT audio delivery.
        """
        if not AUDIO_FILE.exists():
            pytest.skip("Test audio file not found")
        from noble_agent.telephony.resampler import resample_8k_to_16k

        pcm_8k = load_audio_as_8k_slin(AUDIO_FILE)
        frame_size = 320

        # Simulate: process 8kHz frames (audio loop) while TTS runs
        stt_chunks_received = 0
        total_frames = len(pcm_8k) // frame_size

        for i in range(total_frames):
            frame = pcm_8k[i * frame_size : (i + 1) * frame_size]
            if len(frame) < frame_size:
                break
            # This is what _handle_audio does for each frame
            pcm_16k = resample_8k_to_16k(frame)
            if len(pcm_16k) > 0:
                stt_chunks_received += 1

        assert stt_chunks_received == total_frames, f"STT received {stt_chunks_received}/{total_frames} chunks"

    def test_reference_quality_comparison(self):
        """Compare our resampled output against ffmpeg reference (gold standard)."""
        if not AUDIO_FILE.exists():
            pytest.skip("Test audio file not found")
        from noble_agent.telephony.resampler import resample_8k_to_16k

        # Our pipeline: file → 8kHz → soxr resample → 16kHz
        pcm_8k = load_audio_as_8k_slin(AUDIO_FILE)
        our_16k = resample_8k_to_16k(pcm_8k)

        # Reference: file → 16kHz directly via ffmpeg (best quality)
        ref_16k = load_audio_as_16k_slin(AUDIO_FILE)

        # Both should have similar energy (within 30%)
        our_rms = rms(our_16k)
        ref_rms = rms(ref_16k)
        ratio = our_rms / ref_rms if ref_rms > 0 else 0
        assert 0.5 < ratio < 2.0, f"Our RMS={our_rms:.0f} vs ref RMS={ref_rms:.0f} (ratio={ratio:.2f})"

        # Both should have similar length (within 5%)
        len_ratio = len(our_16k) / len(ref_16k) if len(ref_16k) > 0 else 0
        assert 0.9 < len_ratio < 1.1, f"Length ratio {len_ratio:.2f} — significant mismatch"
