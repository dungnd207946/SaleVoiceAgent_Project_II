"""Phase C — end-to-end voice load over the aiortc transport (:8766).

Each virtual call: WS-signals an RTC offer with a synthetic caller audio track,
receives the agent audio track (drained), then drives scripted turns. Per turn we
publish one utterance (speech + trailing silence → server VAD endpoints → STT →
LLM → TTS) and measure, from WS pipeline events:
  - ttfr  = emit → first `agent_speaking`   (time-to-first-response: STT+LLM+first token)
  - total = emit → `agent_done`             (full turn incl. TTS playback)
A turn that doesn't reach agent_done within TURN_TIMEOUT is a failed turn.

Ramp of concurrent CALLS (1,2,4,6,8,10,12,16). Voice "break" = ttfr p95 > 2x the
c=1 baseline, or failed-turn rate > 1%. Reuses common.percentiles/knee.

Run the LLM stub first (see README) so ttfr reflects infra, not gemini latency.
"""
from __future__ import annotations

import argparse
import asyncio
import fractions
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import websockets
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame
from dotenv import dotenv_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ENV = dotenv_values(ROOT / ".env")
HOST = "10.50.12.70"
PORT = ENV.get("WS_PORT", "8766")
SR = 48000
FRAME_SAMPLES = 960  # 20 ms @ 48 kHz
TURN_TIMEOUT = 45.0
RAMP = [1, 2, 4, 6, 8, 10, 12, 16]


def _load_utterance_48k() -> np.ndarray:
    """16 kHz fixture (speech + ~3 s trailing silence) → 48 kHz mono int16."""
    pcm = (Path(__file__).parent / "fixture_16k.pcm").read_bytes()
    x16 = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    n48 = int(len(x16) * SR / 16000)
    x48 = np.interp(np.linspace(0, len(x16) - 1, n48), np.arange(len(x16)), x16)
    return x48.astype(np.int16)


class CallerTrack(MediaStreamTrack):
    """Emits silence by default; emit_utterance() plays the fixture once (speech +
    trailing silence), which triggers exactly one STT endpoint on the server."""

    kind = "audio"

    def __init__(self, utterance: np.ndarray) -> None:
        super().__init__()
        self._utt = utterance
        self._pos: int | None = None  # None = silence
        self._pts = 0
        self._start: float | None = None

    def emit_utterance(self) -> None:
        self._pos = 0

    async def recv(self) -> AudioFrame:
        if self._start is None:
            self._start = time.time()
        if self._pos is not None and self._pos < len(self._utt):
            chunk = self._utt[self._pos : self._pos + FRAME_SAMPLES]
            self._pos += FRAME_SAMPLES
            if len(chunk) < FRAME_SAMPLES:
                chunk = np.pad(chunk, (0, FRAME_SAMPLES - len(chunk)))
            if self._pos >= len(self._utt):
                self._pos = None
        else:
            chunk = np.zeros(FRAME_SAMPLES, dtype=np.int16)
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME_SAMPLES)
        frame.sample_rate = SR
        frame.pts = self._pts
        frame.time_base = fractions.Fraction(1, SR)
        frame.planes[0].update(chunk.astype(np.int16).tobytes())
        self._pts += FRAME_SAMPLES
        target = self._start + self._pts / SR
        wait = target - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        return frame


async def _wait_ice(pc: RTCPeerConnection) -> None:
    if pc.iceGatheringState == "complete":
        return
    done = asyncio.get_event_loop().create_future()

    @pc.on("icegatheringstatechange")
    def _on_change() -> None:
        if pc.iceGatheringState == "complete" and not done.done():
            done.set_result(None)

    if pc.iceGatheringState == "complete" and not done.done():
        done.set_result(None)
    await done


class Call:
    """One virtual voice call over aiortc."""

    def __init__(self, idx: int, utterance: np.ndarray) -> None:
        self.idx = idx
        self.caller = CallerTrack(utterance)
        self.pc = RTCPeerConnection()
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self.ws = None
        self._reader: asyncio.Task | None = None
        self._drains: list[asyncio.Task] = []

    async def connect(self) -> None:
        sid = f"loadc-{self.idx}-{int(time.time())}"
        self.ws = await websockets.connect(
            f"ws://{HOST}:{PORT}/?session={sid}", max_size=4 * 1024 * 1024
        )
        # session_id greeting (inline, before the event reader starts)
        await asyncio.wait_for(self.ws.recv(), timeout=10.0)

        self.pc.addTrack(self.caller)

        @self.pc.on("track")
        def _on_track(track):  # type: ignore[no-untyped-def]
            if track.kind == "audio":
                self._drains.append(asyncio.ensure_future(self._drain(track)))

        offer = await self.pc.createOffer()
        await self.pc.setLocalDescription(offer)
        await _wait_ice(self.pc)
        await self.ws.send(
            json.dumps(
                {"type": "rtc_offer", "sdp": self.pc.localDescription.sdp, "offer_type": "offer"}
            )
        )
        # read until the answer arrives (nothing else is sent before it)
        while True:
            raw = await asyncio.wait_for(self.ws.recv(), timeout=15.0)
            if isinstance(raw, str) and json.loads(raw).get("type") == "rtc_answer":
                ans = json.loads(raw)
                await self.pc.setRemoteDescription(
                    RTCSessionDescription(sdp=ans["sdp"], type=ans["answer_type"])
                )
                break
        self._reader = asyncio.ensure_future(self._read_events())

    async def _drain(self, track) -> None:
        try:
            while True:
                await track.recv()
        except Exception:
            pass

    async def _read_events(self) -> None:
        try:
            async for raw in self.ws:
                if isinstance(raw, str):
                    with_type = json.loads(raw)
                    await self.events.put(with_type)
        except Exception:
            pass

    async def wait_event(self, types: set[str], timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no {types} within {timeout}s")
            ev = await asyncio.wait_for(self.events.get(), timeout=remaining)
            if ev.get("type") in types:
                return ev

    async def await_greet(self) -> float | None:
        """Wait for the auto-greeting to finish; returns its duration or None."""
        try:
            t0 = time.monotonic()
            await self.wait_event({"agent_speaking"}, timeout=20.0)
            await self.wait_event({"agent_done"}, timeout=TURN_TIMEOUT)
            return time.monotonic() - t0
        except TimeoutError:
            return None

    async def do_turn(self) -> tuple[float, float]:
        t0 = time.monotonic()
        self.caller.emit_utterance()
        await self.wait_event({"agent_speaking"}, timeout=TURN_TIMEOUT)
        ttfr = time.monotonic() - t0
        await self.wait_event({"agent_done"}, timeout=TURN_TIMEOUT)
        return ttfr, time.monotonic() - t0

    async def close(self) -> None:
        for t in self._drains:
            t.cancel()
        if self._reader:
            self._reader.cancel()
        try:
            await self.pc.close()
        except Exception:
            pass
        try:
            if self.ws:
                await self.ws.close()
        except Exception:
            pass


async def _call_worker(idx: int, utt: np.ndarray, deadline: float, out: dict) -> None:
    call = Call(idx, utt)
    try:
        await asyncio.wait_for(call.connect(), timeout=30.0)
        greet = await call.await_greet()
        if greet is not None:
            out["greet"].append(greet)
        # settle so we don't barge into the greeting tail
        await asyncio.sleep(0.5)
        while time.monotonic() < deadline:
            try:
                ttfr, total = await call.do_turn()
                out["ttfr"].append(ttfr)
                out["total"].append(total)
            except Exception:
                out["failed_turns"] += 1
            await asyncio.sleep(0.4)
    except Exception:
        out["failed_calls"] += 1
    finally:
        await call.close()


async def _step(concurrency: int, hold_s: float, utt: np.ndarray) -> dict:
    out = {"ttfr": [], "total": [], "greet": [], "failed_turns": 0, "failed_calls": 0}
    deadline = time.monotonic() + hold_s
    await asyncio.gather(*[_call_worker(i, utt, deadline, out) for i in range(concurrency)])
    return out


def _fmt(vals: list[float], key: str) -> str:
    p = common.percentiles(vals)
    return f"{p.get(key, 0) * 1000:.0f}" if p else "-"


def _write_report(rows: list[tuple[int, dict]], path: Path) -> None:
    lines = [
        "# Phase C — E2E voice (aiortc :8766)",
        "",
        "ttfr = utterance emit → first agent_speaking (STT+LLM+first token). "
        "total = emit → agent_done (full turn incl. TTS playback).",
        "",
        "| calls | turns ok | failed turns | failed calls | ttfr p50 | ttfr p95 | total p50 | total p95 | greet p50 |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c, o in rows:
        lines.append(
            f"| {c} | {len(o['ttfr'])} | {o['failed_turns']} | {o['failed_calls']} | "
            f"{_fmt(o['ttfr'], 'p50')} | {_fmt(o['ttfr'], 'p95')} | "
            f"{_fmt(o['total'], 'p50')} | {_fmt(o['total'], 'p95')} | {_fmt(o['greet'], 'p50')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _amain() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=60.0)
    ap.add_argument("--max", type=int, default=16)
    ap.add_argument("--out", type=Path, default=Path("out/phaseC"))
    ap.add_argument("--smoke", action="store_true", help="one call, one-ish turn, verbose")
    args = ap.parse_args()
    utt = _load_utterance_48k()
    print(f"voice E2E → ws://{HOST}:{PORT}/  (utterance {len(utt)/SR:.1f}s @ 48k)")

    if args.smoke:
        out = await _step(1, args.hold, utt)
        print(json.dumps({k: (v if not isinstance(v, list) else {"n": len(v),
              "p50_ms": round(common.percentiles(v).get("p50", 0) * 1000)}) for k, v in out.items()}, indent=2))
        return

    ramp = [c for c in RAMP if c <= args.max]
    rows: list[tuple[int, dict]] = []
    baseline_p95 = None
    for c in ramp:
        o = await _step(c, args.hold, utt)
        rows.append((c, o))
        p95 = common.percentiles(o["ttfr"]).get("p95", 0)
        total_turns = len(o["ttfr"]) + o["failed_turns"]
        err = o["failed_turns"] / total_turns if total_turns else 0
        if baseline_p95 is None:
            baseline_p95 = p95
        print(f"c={c}: ok={len(o['ttfr'])} fail_turn={o['failed_turns']} fail_call={o['failed_calls']} "
              f"ttfr_p95={p95*1000:.0f}ms err={err*100:.1f}%")
        if err > 0.01 or (baseline_p95 and p95 > 2 * baseline_p95):
            print(f"  → BREAK at c={c}")
            break
    args.out.mkdir(parents=True, exist_ok=True)
    _write_report(rows, args.out / "voice_aiortc_RESULTS.md")
    print(f"→ {args.out / 'voice_aiortc_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
