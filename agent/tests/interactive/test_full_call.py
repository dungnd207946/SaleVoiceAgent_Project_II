#!/usr/bin/env python3
"""End-to-end call driver for the /chat pipeline (text brain + production TTS).

Drives a full, scripted customer call through the LIVE `/chat/ws` endpoint of
the running unified server (noble-hotline on :8766) — the same agent brain,
RAG, tools, normalize + TTS backend the phone path uses. For each customer
turn it streams the agent reply, prints tokens / tool calls / metrics, and (TTS
on) collects the PCM16 audio. At the end it stitches every agent turn into one
WAV — the whole call as a single recording — and prints a transcript.

Run (server must already be up on :8766):
    cd santa-hotline-agent
    .venv/bin/python tests/interactive/test_full_call.py
    .venv/bin/python tests/interactive/test_full_call.py --no-tts   # transcript only, faster
    .venv/bin/python tests/interactive/test_full_call.py --host localhost --port 8766

Output:
    <scratch>/full_call.wav   — concatenated agent audio (PCM16/mono @ tts rate)
    transcript printed to stdout
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
import wave
from pathlib import Path

import websockets

# ── ANSI ───────────────────────────────────────────────────────────────────
CYAN, GREEN, YELLOW, DIM, BOLD, RED, RESET = (
    "\033[36m",
    "\033[32m",
    "\033[33m",
    "\033[2m",
    "\033[1m",
    "\033[31m",
    "\033[0m",
)

# ── The call script: customer turns, start → finish ─────────────────────────
# Covers greeting/opener, project info (slashes + big numbers + units from RAG),
# the 4 sub-zones (X/Y → "X và Y"), a viewing appointment with a dd/mm/yyyy date,
# name + phone capture, and a closing — i.e. the normalize edge cases we fixed.
CALL_SCRIPT: list[str] = [
    "Alo, đây có phải tổng đài Noble Palace không em?",
    "Cho anh hỏi dự án Noble Palace Tây Thăng Long là gì, quy mô bao nhiêu hecta vậy em?",
    "Dự án có mấy phân khu, gồm những phân khu nào?",
    "Một căn diện tích khoảng bao nhiêu m2 và giá tầm bao nhiêu?",
    "Anh muốn đặt lịch tới xem nhà mẫu vào ngày 02/07/2026 có được không?",
    "Anh tên Bình, số điện thoại của anh là 0901234567 nhé.",
    "Ừ vậy thôi, cảm ơn em nhiều, chào em.",
]


def _fmt_metrics(m: dict) -> str:
    parts = []
    if m.get("ttft_ms") is not None:
        parts.append(f"TTFT {m['ttft_ms']}ms")
    if m.get("tokens"):
        parts.append(f"{m['tokens']} tok")
    if m.get("tokens_per_sec"):
        parts.append(f"{m['tokens_per_sec']} tok/s")
    if m.get("total_ms") is not None:
        parts.append(f"total {m['total_ms']}ms")
    return "  ".join(parts)


async def run_call(host: str, port: int, use_tts: bool, out_wav: Path) -> int:
    session = "call-" + uuid.uuid4().hex[:8]
    url = f"ws://{host}:{port}/chat/ws?session={session}"
    print(f"{DIM}connecting {url}{RESET}")

    all_pcm = bytearray()  # whole-call audio (all turns concatenated)
    sample_rate = 24000
    transcript: list[tuple[str, str]] = []

    try:
        ws = await websockets.connect(url, max_size=None, open_timeout=10)
    except Exception as exc:
        print(f"{RED}Cannot connect to {url}: {exc}{RESET}")
        print(f"{YELLOW}Is the server running?  systemctl --user status noble-hotline{RESET}")
        return 1

    async with ws:
        print(f"{BOLD}{'=' * 70}{RESET}")
        print(f"{BOLD}  Noble hotline — full call test   (tts={'on' if use_tts else 'off'}){RESET}")
        print(f"{BOLD}{'=' * 70}{RESET}")

        for i, customer in enumerate(CALL_SCRIPT, 1):
            print(f"\n{CYAN}{BOLD}[{i}] Khách:{RESET} {CYAN}{customer}{RESET}")
            transcript.append(("Khách", customer))
            await ws.send(json.dumps({"type": "user_text", "text": customer, "tts": use_tts}, ensure_ascii=False))

            reply_parts: list[str] = []
            turn_pcm = bytearray()
            done = False
            tts_done = not use_tts  # if no tts, we don't wait for tts_end
            saw_tts_begin = False
            t0 = time.perf_counter()

            # Per-turn read loop: agent tokens (text) + PCM (binary), until done+tts_end.
            while not (done and tts_done):
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=120)
                except asyncio.TimeoutError:
                    print(f"{RED}  timeout waiting for agent{RESET}")
                    break

                if isinstance(msg, (bytes, bytearray)):
                    turn_pcm += msg
                    continue

                ev = json.loads(msg)
                t = ev.get("type")
                if t == "token":
                    sys.stdout.write(ev["text"])
                    sys.stdout.flush()
                    reply_parts.append(ev["text"])
                elif t == "tool_start":
                    print(f"\n  {YELLOW}🔧 {ev['tool']}({json.dumps(ev.get('args', {}), ensure_ascii=False)}){RESET}")
                elif t == "tool_done":
                    res = str(ev.get("result", ""))
                    print(f"  {YELLOW}✓ {ev['tool']} → {res[:120]}{RESET}")
                elif t == "agent_switch":
                    print(f"\n  {DIM}→ switch: {ev.get('agent')}{RESET}")
                elif t == "tts_begin":
                    saw_tts_begin = True
                    sample_rate = ev.get("sample_rate", sample_rate)
                elif t == "tts_end":
                    tts_done = True
                    dur = len(turn_pcm) / 2 / sample_rate if sample_rate else 0
                    print(
                        f"\n  {GREEN}🔊 TTS {ev.get('tts_ms', '?')}ms · {len(turn_pcm) // 1024}KB · ~{dur:.1f}s{RESET}"
                    )
                elif t == "error":
                    print(f"\n  {RED}error: {ev.get('message')}{RESET}")
                elif t == "done":
                    done = True
                    print(f"\n  {DIM}{_fmt_metrics(ev)}{RESET}")
                    # If TTS was requested but the reply was empty/no audio, don't hang.
                    if use_tts and not saw_tts_begin:
                        # give the worker a brief grace, then stop waiting
                        await asyncio.sleep(0.2)
                        tts_done = True

            reply = "".join(reply_parts).strip()
            transcript.append(("Luna", reply))
            all_pcm += turn_pcm
            print(f"  {DIM}(turn {time.perf_counter() - t0:.1f}s){RESET}")

        # ── Write the whole-call recording ──────────────────────────────────
        if use_tts and all_pcm:
            with wave.open(str(out_wav), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sample_rate)
                w.writeframes(bytes(all_pcm))
            total_s = len(all_pcm) / 2 / sample_rate
            print(
                f"\n{GREEN}{BOLD}► Full-call recording:{RESET} {out_wav}  "
                f"({len(all_pcm) // 1024}KB, {total_s:.1f}s @ {sample_rate}Hz)"
            )

        # ── Transcript ──────────────────────────────────────────────────────
        print(f"\n{BOLD}{'=' * 70}{RESET}\n{BOLD}  TRANSCRIPT{RESET}\n{BOLD}{'=' * 70}{RESET}")
        for who, line in transcript:
            color = CYAN if who == "Khách" else GREEN
            print(f"{color}{who:>6}{RESET}: {line}")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Full-call E2E test through /chat/ws")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--no-tts", dest="tts", action="store_false", help="skip TTS (transcript only, faster)")
    ap.add_argument("--out", default=None, help="output WAV path (default: scratchpad/full_call.wav)")
    args = ap.parse_args()

    out_wav = Path(args.out) if args.out else Path(__file__).resolve().parents[2] / "full_call.wav"
    return asyncio.run(run_call(args.host, args.port, args.tts, out_wav))


if __name__ == "__main__":
    sys.exit(main())
