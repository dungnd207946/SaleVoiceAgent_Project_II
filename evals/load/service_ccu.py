"""Ramp riêng từng service STT/TTS/speaker — trả lời "component nào nghẽn trước" (spec §8)."""

from __future__ import annotations

import os
from pathlib import Path

from evals.load import ramp


async def run_service_ccu(component: str, *, max_concurrency: int, hold_s: float) -> ramp.CampaignResult:
    pcm = (Path(__file__).resolve().parents[1] / "bench" / "fixtures" / "fixture_16k.pcm").read_bytes()
    token = os.getenv("VOICE_SERVICE_AUTH_TOKEN", "").strip()
    if component == "stt":
        from evals.bench.stt import _once

        url = os.getenv("STT_SERVICE_URL", "ws://127.0.0.1:8770/stt")

        async def make_request() -> float:
            return (await _once(url, token, pcm))["total_ms"] / 1000.0
    elif component == "tts":
        from evals.bench.tts import _once

        url = os.getenv("TTS_SERVICE_URL", "ws://127.0.0.1:8771/tts")
        text = "Dạ em xin phép giới thiệu về dự án của Noble ạ."

        async def make_request() -> float:
            voice = os.getenv("VIENEU_VOICE_ID", "").strip() or None
            return (await _once(url, token, text, voice))["total_ms"] / 1000.0
    elif component == "speaker":
        from evals.bench.speaker import _once

        url = os.getenv("SPEAKER_REMOTE_URL", "")
        if not url:
            raise ValueError("SPEAKER_REMOTE_URL rỗng")

        async def make_request() -> float:
            return (await _once(url, pcm))["total_ms"] / 1000.0
    else:
        raise ValueError(f"unknown component {component!r}; allowed stt|tts|speaker")
    return await ramp.run_campaign(
        make_request, label=f"{component} {url}",
        ramp=ramp.ramp_schedule(max_concurrency=max_concurrency),
        hold_s=hold_s, full_ramp=True,
    )
