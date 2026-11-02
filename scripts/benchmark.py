"""Latency Benchmark Harness — measure P50/P95/P99 per component.

Measures:
  1. STT: time from audio send → on_final callback
  2. LLM TTFT: time from prompt → first token
  3. TTS TTFB: time from text → first audio chunk
  4. E2E Pipeline: STT final → LLM → TTS → first audio byte

Usage (from repo root, after pip install -e ".[dev]"):
    python scripts/benchmark.py [--runs 5] [--stt soniox] [--tts elevenlabs]
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parent.parent
_SRC = _ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

load_dotenv()

# ── Helpers ──────────────────────────────────────────────────────────────────

def _percentile(data: list[float], p: int) -> float:
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def _print_stats(name: str, latencies: list[float]):
    if not latencies:
        print(f"  {name}: NO DATA")
        return
    print(f"  {name}:")
    print(f"    Min:  {min(latencies):>7.0f}ms")
    print(f"    P50:  {_percentile(latencies, 50):>7.0f}ms")
    print(f"    P95:  {_percentile(latencies, 95):>7.0f}ms")
    print(f"    P99:  {_percentile(latencies, 99):>7.0f}ms")
    print(f"    Max:  {max(latencies):>7.0f}ms")
    print(f"    Mean: {statistics.mean(latencies):>7.0f}ms  (n={len(latencies)})")


def _generate_speech_audio(duration_s: float = 2.0, sample_rate: int = 16000) -> bytes:
    """Generate fake speech-like audio (sine wave + noise) for STT testing."""
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), dtype=np.float32)
    # Mix of frequencies to simulate speech
    audio = 0.3 * np.sin(2 * np.pi * 200 * t) + 0.2 * np.sin(2 * np.pi * 400 * t)
    audio += 0.05 * np.random.randn(len(t)).astype(np.float32)
    return (audio * 32767).astype(np.int16).tobytes()


# ── STT Benchmark ────────────────────────────────────────────────────────────

async def benchmark_stt(backend: str, n_runs: int, audio_file: str | None) -> list[float]:
    """Measure STT latency: audio send → on_final callback."""
    print(f"\n{'='*60}")
    print(f"STT Benchmark: {backend} ({n_runs} runs)")
    print(f"{'='*60}")

    if audio_file and Path(audio_file).exists():
        with open(audio_file, "rb") as f:
            audio_bytes = f.read()
        print(f"  Audio: {audio_file} ({len(audio_bytes)} bytes)")
    else:
        audio_bytes = _generate_speech_audio(2.0)
        print(f"  Audio: synthetic 2s sine wave ({len(audio_bytes)} bytes)")

    latencies: list[float] = []

    if backend == "soniox":
        from noble_agent.voice.stt.soniox import SonioxSTT

        for i in range(n_runs):
            result_event = asyncio.Event()
            transcript_text = [""]
            t0 = time.perf_counter()

            async def on_final(text: str, _box=transcript_text, _ev=result_event):
                _box[0] = text
                _ev.set()

            stt = SonioxSTT(on_final=on_final)
            await stt.start()

            # Send audio in 20ms chunks
            chunk_size = 16000 * 2 * 20 // 1000  # 640 bytes per 20ms
            for j in range(0, len(audio_bytes), chunk_size):
                chunk = audio_bytes[j:j + chunk_size]
                await stt.send(chunk)
                await asyncio.sleep(0.005)  # slight pacing

            # Wait for final (timeout 10s)
            try:
                await asyncio.wait_for(result_event.wait(), timeout=10.0)
                elapsed = (time.perf_counter() - t0) * 1000
                latencies.append(elapsed)
                print(f"  Run {i+1}: {elapsed:.0f}ms → '{transcript_text[0][:50]}'")
            except TimeoutError:
                print(f"  Run {i+1}: TIMEOUT (no on_final received)")

            await stt.stop()
            await asyncio.sleep(0.5)  # cooldown between runs

    _print_stats("STT Latency", latencies)
    return latencies


# ── LLM Benchmark ────────────────────────────────────────────────────────────

async def benchmark_llm(n_runs: int) -> list[float]:
    """Measure LLM TTFT: prompt → first token."""
    print(f"\n{'='*60}")
    print(f"LLM TTFT Benchmark ({n_runs} runs)")
    print(f"{'='*60}")

    from openai import AsyncOpenAI

    from noble_agent.config import settings

    if not settings.openai_api_key:
        print("  No OPENAI_API_KEY — skipping LLM benchmark")
        return []

    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=settings.llm_timeout,
    )
    model = settings.openai_model
    print(f"  Model: {model}")

    prompt = "Noble Crystal Long Biên có bao nhiêu căn hộ và diện tích bao nhiêu?"
    messages = [
        {"role": "system", "content": "You are a helpful real estate assistant."},
        {"role": "user", "content": prompt},
    ]

    latencies: list[float] = []

    for i in range(n_runs):
        t0 = time.perf_counter()
        first_token_time = None

        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            max_tokens=100,
            temperature=0.7,
        )

        full_text = ""
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                full_text += chunk.choices[0].delta.content

        if first_token_time:
            ttft = (first_token_time - t0) * 1000
            total = (time.perf_counter() - t0) * 1000
            latencies.append(ttft)
            print(f"  Run {i+1}: TTFT={ttft:.0f}ms total={total:.0f}ms tokens={len(full_text)}")
        else:
            print(f"  Run {i+1}: NO TOKENS")

    _print_stats("LLM TTFT", latencies)
    return latencies


# ── TTS Benchmark ────────────────────────────────────────────────────────────

async def benchmark_tts(backend: str, n_runs: int) -> list[float]:
    """Measure TTS TTFB: text → first audio chunk."""
    print(f"\n{'='*60}")
    print(f"TTS TTFB Benchmark: {backend} ({n_runs} runs)")
    print(f"{'='*60}")

    text = (
        "Dạ, Noble Crystal Long Biên có tổng cộng một nghìn hai trăm căn hộ, "
        "diện tích từ tám mươi lăm đến một trăm hai mươi mét vuông."
    )
    latencies: list[float] = []
    totals: list[float] = []

    if backend == "elevenlabs":
        from noble_agent.voice.tts.elevenlabs import AsyncElevenLabsTTS

        tts = AsyncElevenLabsTTS()

        for i in range(n_runs):
            t0 = time.perf_counter()
            first_chunk = True
            total_bytes = 0

            async for chunk in tts.stream(text):
                if first_chunk:
                    ttfb = (time.perf_counter() - t0) * 1000
                    latencies.append(ttfb)
                    first_chunk = False
                total_bytes += len(chunk)

            total = (time.perf_counter() - t0) * 1000
            if not first_chunk:
                totals.append(total)
                print(f"  Run {i+1}: TTFB={latencies[-1]:.0f}ms total={total:.0f}ms bytes={total_bytes}")
            else:
                print(f"  Run {i+1}: NO AUDIO")

            await asyncio.sleep(0.3)

    elif backend == "vieneu":
        from noble_agent.voice.tts.vieneu import AsyncVieNeuTTS

        tts = AsyncVieNeuTTS()

        for i in range(n_runs):
            t0 = time.perf_counter()
            first_chunk = True
            total_bytes = 0

            async for chunk in tts.stream(text):
                if first_chunk:
                    ttfb = (time.perf_counter() - t0) * 1000
                    latencies.append(ttfb)
                    first_chunk = False
                total_bytes += len(chunk)

            total = (time.perf_counter() - t0) * 1000
            if not first_chunk:
                totals.append(total)
                print(f"  Run {i+1}: TTFB={latencies[-1]:.0f}ms total={total:.0f}ms bytes={total_bytes}")
            else:
                print(f"  Run {i+1}: NO AUDIO")

    _print_stats("TTS TTFB", latencies)
    # Streaming wins by diverging TTFB from total (TTFB << total). Print both so the
    # before/after (NOBLE_TTS_STREAMING off vs on) divergence is visible in the report.
    _print_stats("TTS total", totals)
    return latencies


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Voice Agent Latency Benchmark")
    parser.add_argument("--runs", type=int, default=5, help="Number of runs per benchmark")
    parser.add_argument("--stt", default="soniox", choices=["soniox", "skip"], help="STT backend")
    parser.add_argument("--tts", default="elevenlabs", choices=["elevenlabs", "vieneu", "skip"], help="TTS backend")
    parser.add_argument("--llm", default="run", choices=["run", "skip"], help="LLM benchmark")
    parser.add_argument("--audio", default=None, help="WAV/PCM file for STT test")
    args = parser.parse_args()

    print("=" * 60)
    print("Voice Agent Latency Benchmark")
    print("=" * 60)

    results = {}

    if args.stt != "skip":
        results["stt"] = await benchmark_stt(args.stt, args.runs, args.audio)

    if args.llm != "skip":
        results["llm"] = await benchmark_llm(args.runs)

    if args.tts != "skip":
        results["tts"] = await benchmark_tts(args.tts, args.runs)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for name, lats in results.items():
        if lats:
            p50, p95 = _percentile(lats, 50), _percentile(lats, 95)
            mn, mx = min(lats), max(lats)
            print(f"  {name.upper():>5s}:  P50={p50:.0f}ms  P95={p95:.0f}ms  Min={mn:.0f}ms  Max={mx:.0f}ms")

    if all(k in results and results[k] for k in ["stt", "llm", "tts"]):
        pipeline_p50 = sum(_percentile(results[k], 50) for k in ["stt", "llm", "tts"])
        print(f"\n  E2E Pipeline (sum P50): {pipeline_p50:.0f}ms")
        print("  (With streaming overlap, actual E2E ~60-70% of sum)")


if __name__ == "__main__":
    asyncio.run(main())
