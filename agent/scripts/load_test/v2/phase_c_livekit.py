"""Phase C — end-to-end voice load over the PRODUCTION LiveKit path.

Each virtual call: mint a join token, connect to a fresh room (the agent-lk worker
auto-dispatches + auto-greets), publish a synthetic caller audio track, and read the
pipeline events the worker publishes on the `agent-events` data channel
(`agent_speaking` / `agent_done`). Per turn: push one utterance (speech + trailing
silence → server VAD endpoint → STT → LLM → TTS) and measure:
  - ttfr  = emit → first agent_speaking
  - total = emit → agent_done
Ramp of concurrent CALLS. Break = ttfr p95 > 2x c=1 baseline, or failed-turn > 1%.

This hits LiveKit Cloud (media plane) + the worker process-pool + shared STT/TTS.
Run the LLM stub first so ttfr reflects infra, not gemini.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from dotenv import dotenv_values
from livekit import api, rtc

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ENV = dotenv_values(ROOT / ".env")
LK_URL = ENV["LIVEKIT_URL"]
LK_KEY = ENV["LIVEKIT_API_KEY"]
LK_SECRET = ENV["LIVEKIT_API_SECRET"]
SR = 16000
CH = 1
FRAME_SAMPLES = 320  # 20 ms @ 16 kHz
TURN_TIMEOUT = 45.0
EVENT_TOPIC = "agent-events"
RAMP = [1, 4, 8, 16, 24, 32, 48]


def _utterance_16k() -> np.ndarray:
    return np.frombuffer((Path(__file__).parent / "fixture_16k.pcm").read_bytes(), dtype=np.int16).copy()


def _mint(room: str, identity: str) -> str:
    grants = api.VideoGrants(
        room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=True
    )
    return api.AccessToken(LK_KEY, LK_SECRET).with_identity(identity).with_name(identity).with_grants(grants).to_jwt()


class LKCall:
    def __init__(self, idx: int, utt: np.ndarray) -> None:
        self.idx = idx
        self.utt = utt
        self.room = rtc.Room()
        self.source = rtc.AudioSource(SR, CH)
        self.events: asyncio.Queue[dict] = asyncio.Queue()
        self._pos: int | None = None
        self._pump: asyncio.Task | None = None

        @self.room.on("data_received")
        def _on_data(pkt) -> None:  # type: ignore[no-untyped-def]
            try:
                raw = getattr(pkt, "data", pkt)
                topic = getattr(pkt, "topic", None)
                if topic not in (None, EVENT_TOPIC):
                    return
                self.events.put_nowait(json.loads(bytes(raw).decode("utf-8")))
            except Exception:
                pass

    async def connect(self) -> None:
        room_name = f"loadlk-{self.idx}-{int(time.time())}"
        token = _mint(room_name, f"caller-{self.idx}")
        await self.room.connect(LK_URL, token)
        track = rtc.LocalAudioTrack.create_audio_track("caller", self.source)
        await self.room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self._pump = asyncio.ensure_future(self._pump_audio())

    async def _pump_audio(self) -> None:
        start = time.monotonic()
        sent = 0
        silence = np.zeros(FRAME_SAMPLES, dtype=np.int16)
        try:
            while True:
                if self._pos is not None and self._pos < len(self.utt):
                    chunk = self.utt[self._pos : self._pos + FRAME_SAMPLES]
                    self._pos += FRAME_SAMPLES
                    if len(chunk) < FRAME_SAMPLES:
                        chunk = np.pad(chunk, (0, FRAME_SAMPLES - len(chunk)))
                    if self._pos >= len(self.utt):
                        self._pos = None
                else:
                    chunk = silence
                await self.source.capture_frame(
                    rtc.AudioFrame(chunk.tobytes(), SR, CH, FRAME_SAMPLES)
                )
                sent += FRAME_SAMPLES
                wait = start + sent / SR - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def emit_utterance(self) -> None:
        self._pos = 0

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
        try:
            t0 = time.monotonic()
            await self.wait_event({"agent_speaking"}, timeout=20.0)
            await self.wait_event({"agent_done"}, timeout=TURN_TIMEOUT)
            return time.monotonic() - t0
        except TimeoutError:
            return None

    async def do_turn(self) -> tuple[float, float]:
        t0 = time.monotonic()
        self.emit_utterance()
        await self.wait_event({"agent_speaking"}, timeout=TURN_TIMEOUT)
        ttfr = time.monotonic() - t0
        await self.wait_event({"agent_done"}, timeout=TURN_TIMEOUT)
        return ttfr, time.monotonic() - t0

    async def close(self) -> None:
        if self._pump:
            self._pump.cancel()
        try:
            await self.source.aclose()
        except Exception:
            pass
        try:
            await self.room.disconnect()
        except Exception:
            pass


async def _call_worker(idx: int, utt: np.ndarray, deadline: float, out: dict) -> None:
    call = LKCall(idx, utt)
    try:
        await asyncio.wait_for(call.connect(), timeout=30.0)
        greet = await call.await_greet()
        if greet is not None:
            out["greet"].append(greet)
        await asyncio.sleep(0.5)
        while time.monotonic() < deadline:
            try:
                ttfr, total = await call.do_turn()
                out["ttfr"].append(ttfr)
                out["total"].append(total)
            except Exception:
                out["failed_turns"] += 1
            await asyncio.sleep(0.4)
    except Exception as exc:
        out["failed_calls"] += 1
        out.setdefault("errs", []).append(f"{type(exc).__name__}: {exc}")
    finally:
        await call.close()


async def _step(concurrency: int, hold_s: float, utt: np.ndarray) -> dict:
    out: dict = {"ttfr": [], "total": [], "greet": [], "failed_turns": 0, "failed_calls": 0}
    deadline = time.monotonic() + hold_s
    await asyncio.gather(*[_call_worker(i, utt, deadline, out) for i in range(concurrency)])
    return out


def _fmt(vals: list[float], key: str) -> str:
    p = common.percentiles(vals)
    return f"{p.get(key, 0) * 1000:.0f}" if p else "-"


def _write_report(rows: list[tuple[int, dict]], path: Path) -> None:
    lines = [
        "# Phase C — E2E voice (LiveKit, production path)",
        "",
        "ttfr = emit → first agent_speaking. total = emit → agent_done. Events read from the "
        "`agent-events` LiveKit data channel. LLM stubbed to isolate infra.",
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
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    utt = _utterance_16k()
    print(f"voice E2E → {LK_URL} (utterance {len(utt)/SR:.1f}s @ 16k)")

    if args.smoke:
        out = await _step(1, args.hold, utt)
        summary = {k: ({"n": len(v), "p50_ms": round(common.percentiles(v).get("p50", 0) * 1000)}
                       if isinstance(v, list) and v and isinstance(v[0], float) else v)
                   for k, v in out.items()}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
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
    _write_report(rows, args.out / "voice_livekit_RESULTS.md")
    print(f"→ {args.out / 'voice_livekit_RESULTS.md'}")


if __name__ == "__main__":
    asyncio.run(_amain())
