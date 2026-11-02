"""Voice CCU — end-to-end voice load over the PRODUCTION LiveKit path.

Ported from `scripts/load_test/v2/phase_c_livekit.py`. Each virtual call: mint a join
token, connect to a fresh room (the agent-lk worker auto-dispatches + auto-greets),
publish a synthetic caller audio track, and read the pipeline events the worker
publishes on the `agent-events` data channel (`agent_speaking` / `agent_done`). Per
turn: push one utterance (speech + trailing silence → server VAD endpoint → STT →
LLM → TTS) and measure:
  - ttfr  = emit → first agent_speaking
  - total = emit → agent_done
Ramp of concurrent CALLS, early-stop on ttfr p95 > 2x c=1 baseline or failed-turn > 1%
(`ramp.is_broken`). `max_concurrency=1` = a single full-pipeline voice call — the
end-to-end pipeline benchmark (spec §7).

This hits LiveKit Cloud (media plane) + the worker process-pool + shared STT/TTS.
Run the LLM stub first so ttfr reflects infra, not gemini.

LiveKit imports are deferred into functions so `import evals.load.voice_ccu` succeeds
even where the `livekit` package (or a working `.env`) is not installed/configured.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path

import numpy as np

from evals.load import ramp as common

ROOT = Path(__file__).resolve().parents[2]
SR = 16000
CH = 1
FRAME_SAMPLES = 320  # 20 ms @ 16 kHz
TURN_TIMEOUT = 45.0
EVENT_TOPIC = "agent-events"


def _fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "fixture_16k.pcm"


def _utterance_16k() -> np.ndarray:
    return np.frombuffer(_fixture_path().read_bytes(), dtype=np.int16).copy()


def _lk_creds() -> tuple[str, str, str]:
    from dotenv import dotenv_values  # noqa: PLC0415

    env = dotenv_values(ROOT / ".env")
    url, key, secret = env.get("LIVEKIT_URL"), env.get("LIVEKIT_API_KEY"), env.get("LIVEKIT_API_SECRET")
    if not (url and key and secret):
        raise RuntimeError("LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET missing from .env")
    return url, key, secret


def _mint(key: str, secret: str, room: str, identity: str) -> str:
    from livekit import api  # noqa: PLC0415

    grants = api.VideoGrants(
        room_join=True, room=room, can_publish=True, can_subscribe=True, can_publish_data=True
    )
    return api.AccessToken(key, secret).with_identity(identity).with_name(identity).with_grants(grants).to_jwt()


class LKCall:
    def __init__(self, idx: int, utt: np.ndarray, lk_url: str, lk_key: str, lk_secret: str) -> None:
        from livekit import rtc  # noqa: PLC0415

        self.idx = idx
        self.utt = utt
        self.lk_url = lk_url
        self.lk_key = lk_key
        self.lk_secret = lk_secret
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
        from livekit import rtc  # noqa: PLC0415

        room_name = f"loadlk-{self.idx}-{int(time.time())}"
        token = _mint(self.lk_key, self.lk_secret, room_name, f"caller-{self.idx}")
        await self.room.connect(self.lk_url, token)
        track = rtc.LocalAudioTrack.create_audio_track("caller", self.source)
        await self.room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        self._pump = asyncio.ensure_future(self._pump_audio())

    async def _pump_audio(self) -> None:
        from livekit import rtc  # noqa: PLC0415

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
        with contextlib.suppress(Exception):
            await self.source.aclose()
        with contextlib.suppress(Exception):
            await self.room.disconnect()


async def _call_worker(idx: int, utt: np.ndarray, deadline: float, out: dict, lk: tuple[str, str, str]) -> None:
    call = LKCall(idx, utt, *lk)
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


async def _step(concurrency: int, hold_s: float, utt: np.ndarray, lk: tuple[str, str, str]) -> dict:
    out: dict = {"ttfr": [], "total": [], "greet": [], "failed_turns": 0, "failed_calls": 0}
    deadline = time.monotonic() + hold_s
    await asyncio.gather(*[_call_worker(i, utt, deadline, out, lk) for i in range(concurrency)])
    return out


async def run_voice_ccu(*, max_concurrency: int, hold_s: float, out_dir: Path) -> common.CampaignResult:
    """Ramp concurrent LiveKit calls; each call loops turns for `hold_s`. Break = ttfr
    p95 > 2x c=1 baseline, or failed-turn rate > 1% (`ramp.is_broken`). Writes
    `voice_ccu.md` under `out_dir` and returns the campaign result (knee = max
    sustainable concurrent calls)."""
    lk = _lk_creds()
    utt = _utterance_16k()
    print(f"voice E2E → {lk[0]} (utterance {len(utt) / SR:.1f}s @ 16k)")

    schedule = common.ramp_schedule(max_concurrency=max_concurrency)
    steps: list[common.StepResult] = []
    baseline_p95 = 0.0
    knee = schedule[0] if schedule else 1
    for c in schedule:
        raw = await _step(c, hold_s, utt, lk)
        ok = len(raw["ttfr"])
        # A call that fails to connect never gets a turn — it must still count as a
        # failure of this step's totals/err_rate, else a fully-unreachable step reports
        # total=0/err_rate=0.0 (looks "clean") instead of err_rate=1.0 (spec §10 all-dead
        # check in _cmd_load_voice relies on err_rate, not on raw["failed_calls"]).
        failed = raw["failed_turns"] + raw["failed_calls"]
        total = ok + failed
        step = common.StepResult(
            concurrency=c, duration_s=hold_s, total=total, ok=ok, failed=failed,
            latency=common.percentiles(raw["ttfr"]), err_rate=(failed / total) if total else 0.0,
        )
        steps.append(step)
        if c == schedule[0]:
            baseline_p95 = step.latency.get("p95", 0.0)
        print(
            f"c={c}: ok={ok} fail_turn={failed} fail_call={raw['failed_calls']} "
            f"ttfr_p95={step.latency.get('p95', 0.0) * 1000:.0f}ms err={step.err_rate * 100:.1f}%"
        )
        if common.is_broken(step, baseline_p95):
            print(f"  → BREAK at c={c}")
            break
        knee = c

    result = common.CampaignResult(
        label=f"voice e2e (LiveKit) {lk[0]}", baseline_p95=baseline_p95, steps=steps, knee=knee,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    common.write_results_md(result, out_dir / "voice_ccu.md")
    print(f"→ {out_dir / 'voice_ccu.md'}")
    return result
