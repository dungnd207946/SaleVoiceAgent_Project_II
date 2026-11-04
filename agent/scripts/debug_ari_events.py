"""Subscribe to ALL ARI events and dump them to stdout — diagnostic tool.

Unlike `run_telephony.py` which only listens for `app=noble-voice-agent`
events (Stasis-only), this uses `subscribeAll=true` to see every channel
lifecycle event: ChannelCreated / ChannelStateChange / Dial / BridgeCreated
/ ChannelHangupRequest / ChannelDestroyed.

Use to diagnose why a trunk call isn't reaching the callee or the agent.

Usage:
  python scripts/debug_ari_events.py              # just watch
  python scripts/debug_ari_events.py --call 0942866939   # originate + watch
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402
import websockets  # noqa: E402

from noble_agent.config import settings  # noqa: E402

WS_URL = (
    f"{'wss' if settings.asterisk_ari_scheme == 'https' else 'ws'}"
    f"://{settings.asterisk_host}:{settings.asterisk_ari_port}"
    f"/ari/events?api_key={settings.asterisk_ari_username}"
    f":{settings.asterisk_ari_password}"
    f"&app={settings.asterisk_ari_app}&subscribeAll=true"
)
HTTP_BASE = (
    f"{settings.asterisk_ari_scheme}://{settings.asterisk_host}"
    f":{settings.asterisk_ari_port}/ari"
)
AUTH = (settings.asterisk_ari_username, settings.asterisk_ari_password)


def _fmt(event: dict) -> str:
    t = event.get("type", "?")
    ch = event.get("channel", {})
    parts = [f"[{t}]"]
    if ch:
        parts.append(f"ch={ch.get('id')}")
        parts.append(f"state={ch.get('state')}")
        parts.append(f"name={ch.get('name')}")
        cid = ch.get("caller", {}).get("number")
        dialed = ch.get("dialplan", {})
        if cid:
            parts.append(f"caller={cid}")
        if dialed:
            parts.append(f"ctx={dialed.get('context')}/exten={dialed.get('exten')}")
    if t == "Dial":
        parts.append(f"dial_status={event.get('dialstatus')}")
        parts.append(f"peer={event.get('peer', {}).get('name')}")
    if t == "ChannelHangupRequest":
        parts.append(f"cause={event.get('cause')} ({event.get('cause_txt')})")
    if t == "ChannelDestroyed":
        parts.append(f"cause={event.get('cause')} ({event.get('cause_txt')})")
    return " ".join(parts)


async def originate(number: str, mode: str) -> None:
    await asyncio.sleep(1.0)  # let WS subscribe first
    print(f"\n>>> ORIGINATE to {number} ({mode} mode) ...\n")
    # `Local/<n>@from-internal` routes through FreePBX Outbound Routes so CID
    # gets substituted properly (direct `PJSIP/.../trunk` with a 1800 CID is
    # rejected by VN mobile carriers with cause=21). Matches voiceagentrag.
    params = {
        "endpoint": f"Local/{number}@from-internal",
        "callerId": f'"Noble Agent" <{settings.asterisk_outbound_callerid}>',
        "timeout": settings.asterisk_outbound_timeout,
    }
    if mode == "app":
        # Put channel directly into our Stasis app so ARI emits ChannelCreated,
        # Dial status, ChannelStateChange, StasisStart events. No dialplan, so
        # the channel will hang up right after StasisStart — that's fine for
        # diagnostics. Agent's existing StasisStart handler will see it.
        params["app"] = settings.asterisk_ari_app
    else:
        # Dialplan-context mode (what make_outbound_call.py uses). Channel
        # events are NOT forwarded to our ARI app unless the dialplan calls
        # `Stasis(noble-voice-agent)` explicitly.
        params["context"] = settings.asterisk_outbound_context
        params["extension"] = "s"
        params["priority"] = 1
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            f"{HTTP_BASE}/channels",
            params=params,
            auth=AUTH,
            timeout=15.0,
        )
        print(f">>> HTTP {resp.status_code}: {resp.text[:300]}\n")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--call", help="Place outbound call to this number 1s after WS subscribe")
    parser.add_argument("--mode", choices=["app", "context"], default="app",
                        help="'app' = originate directly into Stasis app so ALL channel "
                             "events are visible (best for diagnosis). 'context' = dialplan "
                             "mode (same as make_outbound_call.py) — events hidden unless "
                             "dialplan calls Stasis().")
    parser.add_argument("--seconds", type=int, default=60, help="How long to listen")
    args = parser.parse_args()

    if not settings.asterisk_ari_password:
        print("ASTERISK_ARI_PASSWORD not set", file=sys.stderr)
        return 1

    print(f"Connecting to {WS_URL.split('api_key=')[0]}...")
    async with websockets.connect(WS_URL, ping_interval=20) as ws:
        print("Subscribed. Listening for ALL events (Ctrl-C to quit).\n")

        tasks = [asyncio.create_task(_read(ws, args.seconds))]
        if args.call:
            tasks.append(asyncio.create_task(originate(args.call, args.mode)))
        await asyncio.gather(*tasks, return_exceptions=True)
    return 0


async def _read(ws, seconds: int) -> None:
    try:
        async with asyncio.timeout(seconds):
            async for raw in ws:
                try:
                    e = json.loads(raw)
                    print(_fmt(e))
                except Exception as exc:
                    print(f"[parse-err] {exc}: {raw[:200]}")
    except TimeoutError:
        print(f"\n--- {seconds}s watch window ended ---")


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
