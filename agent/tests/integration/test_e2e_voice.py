"""Task 3: End-to-end voice flow test — STT→LLM→TTS pipeline.

Tests the full pipeline with audio input or text input,
records traces: STT output, LLM output, TTS audio output.

Usage:
    # Text mode (no audio hardware needed):
    python data/test_e2e/e2e_voice_test.py --mode text --output data/test_e2e/traces/

    # Audio mode (requires audio files):
    python data/test_e2e/e2e_voice_test.py --mode audio --input data/test_e2e/audio/ --output data/test_e2e/traces/
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


# Test conversations — multi-turn scenarios
TEST_CONVERSATIONS = [
    {
        "id": "conv_01_greeting_to_advisor",
        "description": "Greeting → hỏi dự án → advisor tư vấn",
        "turns": [
            {"user": "Xin chào", "expect_agent": "router"},
            {"user": "Tôi muốn tìm hiểu về Noble Crystal Tây Hồ", "expect_agent": "consultant"},
            {
                "user": "Giá căn hai phòng ngủ bao nhiêu?",
                "expect_agent": "consultant",
                "expect_tools": ["kb_search"],
            },
        ],
    },
    {
        "id": "conv_02_booking_flow",
        "description": "Đặt lịch tham quan từ đầu đến cuối",
        "turns": [
            {"user": "Tôi muốn đặt lịch xem nhà Noble Crystal Tây Hồ", "expect_agent": "consultant"},
            {
                "user": ("Tên tôi là Minh, số điện thoại không chín một hai ba bốn năm sáu bảy tám"),
                "expect_tools": ["update_customer"],
            },
            {"user": "Ngày mai lúc chín giờ sáng", "expect_agent": "consultant"},
        ],
    },
    {
        "id": "conv_03_advisor_personalized",
        "description": "Tư vấn cá nhân hoá theo nhu cầu",
        "turns": [
            {"user": "Tôi muốn được tư vấn mua nhà", "expect_agent": "consultant"},
            {"user": "Mục đích để ở, ngân sách khoảng năm tỷ", "expect_tools": ["update_customer"]},
            {"user": "Gia đình tôi bốn người, cần ba phòng ngủ", "expect_tools": ["update_customer"]},
        ],
    },
    {
        "id": "conv_04_support_flow",
        "description": "Khách đã mua → hỏi hợp đồng",
        "turns": [
            {"user": "Tôi đã mua căn hộ Noble Crystal và muốn kiểm tra hợp đồng", "expect_agent": "support"},
            {"user": "Số điện thoại tôi là không chín một hai ba bốn năm sáu bảy tám", "expect_tools": ["crm_lookup"]},
        ],
    },
    {
        "id": "conv_05_transfer",
        "description": "Yêu cầu gặp người thật",
        "turns": [
            {"user": "Cho tôi nói chuyện với nhân viên thật", "expect_agent": "support"},
        ],
    },
    {
        "id": "conv_06_noise",
        "description": "Câu hỏi có nhiễu từ STT",
        "turns": [
            {"user": "Nô bồ Crystal, à Noble Crystal Long Biên giá giá bao nhiêu", "expect_agent": "consultant"},
        ],
    },
]


class E2ETrace:
    """Records a single conversation trace."""

    def __init__(self, conv_id: str):
        self.conv_id = conv_id
        self.turns: list[dict] = []
        self.start_time = time.monotonic()

    def add_turn(
        self,
        user_text: str,
        response: str,
        tools_called: list[str],
        agent: str,
        ttft_ms: float,
        total_ms: float,
        tts_audio_path: str = "",
    ):
        self.turns.append(
            {
                "user_text": user_text,
                "llm_response": response,
                "tools_called": tools_called,
                "agent": agent,
                "ttft_ms": round(ttft_ms, 1),
                "total_ms": round(total_ms, 1),
                "tts_audio_path": tts_audio_path,
                "timestamp": time.monotonic() - self.start_time,
            }
        )

    def to_dict(self) -> dict:
        return {
            "conv_id": self.conv_id,
            "turns": self.turns,
            "total_turns": len(self.turns),
            "total_duration_s": round(time.monotonic() - self.start_time, 2),
        }


async def _run_text_turn(llm, turn: dict):
    """Single user turn → response metrics (no closure over loop vars)."""
    t0 = time.monotonic()
    tokens: list[str] = []
    tools_called: list[str] = []
    ttft = 0.0
    first_token = True

    def on_token(t: str) -> None:
        nonlocal ttft, first_token
        if first_token:
            ttft = (time.monotonic() - t0) * 1000
            first_token = False
        tokens.append(t)

    def on_tool_start(name: str, _args: object) -> None:
        tools_called.append(name)

    try:
        await llm.stream_response(
            user_text=turn["user"],
            on_token=on_token,
            on_tool_start=on_tool_start,
        )
    except Exception as e:
        tokens.append(f"[ERROR: {e}]")

    total_ms = (time.monotonic() - t0) * 1000
    return {
        "response": "".join(tokens),
        "tools_called": tools_called,
        "agent": llm._current_agent,
        "ttft_ms": ttft,
        "total_ms": total_ms,
    }


async def run_text_e2e(output_dir: str):
    """Run E2E test in text mode (no audio)."""
    from noble_agent.agent.llm.streaming import StreamingLLM

    os.makedirs(output_dir, exist_ok=True)
    all_traces = []

    for conv in TEST_CONVERSATIONS:
        print(f"\n{'=' * 60}")
        print(f"Conversation: {conv['id']} — {conv['description']}")
        print(f"{'=' * 60}")

        trace = E2ETrace(conv["id"])
        llm = await StreamingLLM.create("")

        for turn_idx, turn in enumerate(conv["turns"]):
            out = await _run_text_turn(llm, turn)
            response = out["response"]
            tools_called = out["tools_called"]
            agent = out["agent"]
            ttft = out["ttft_ms"]
            total_ms = out["total_ms"]

            trace.add_turn(
                user_text=turn["user"],
                response=response,
                tools_called=tools_called,
                agent=agent,
                ttft_ms=ttft,
                total_ms=total_ms,
            )

            print(f"  Turn {turn_idx + 1}:")
            print(f"    User: {turn['user'][:80]}")
            print(f"    Agent: {agent}")
            print(f"    Tools: {tools_called}")
            print(f"    TTFT: {ttft:.0f}ms  Total: {total_ms:.0f}ms")
            print(f"    Response: {response[:120]}...")

            if turn.get("expect_agent") and agent != turn["expect_agent"]:
                print(f"    ⚠ EXPECTED agent={turn['expect_agent']}, GOT {agent}")
            if turn.get("expect_tools"):
                for et in turn["expect_tools"]:
                    if et not in tools_called:
                        print(f"    ⚠ EXPECTED tool={et} not called")

        all_traces.append(trace.to_dict())

    # Save traces
    traces_path = os.path.join(output_dir, "traces.json")
    with open(traces_path, "w", encoding="utf-8") as f:
        json.dump(all_traces, f, ensure_ascii=False, indent=2)
    print(f"\nTraces saved to {traces_path}")

    # Summary
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for t in all_traces:
        total_ttft = sum(turn["ttft_ms"] for turn in t["turns"] if turn["ttft_ms"])
        avg_ttft = total_ttft / len(t["turns"]) if t["turns"] else 0
        cid, nturn, dur = t["conv_id"], t["total_turns"], t["total_duration_s"]
        print(f"  {cid}: {nturn} turns, avg TTFT={avg_ttft:.0f}ms, duration={dur}s")


async def run_audio_e2e(input_dir: str, output_dir: str):
    """Run E2E test with audio files (requires STT + TTS backends)."""
    print("Audio E2E mode requires running STT and TTS backends.")
    print(f"Looking for audio files in {input_dir}...")

    audio_files = list(Path(input_dir).glob("*.wav")) + list(Path(input_dir).glob("*.pcm"))
    if not audio_files:
        print(f"No audio files found in {input_dir}. Place .wav or .pcm files there.")
        return

    os.makedirs(output_dir, exist_ok=True)

    for audio_file in audio_files:
        print(f"\nProcessing: {audio_file.name}")
        # Read audio and convert to PCM int16 16kHz if needed
        if audio_file.suffix == ".wav":
            import wave

            with wave.open(str(audio_file), "rb") as wf:
                pcm_data = wf.readframes(wf.getnframes())
                sample_rate = wf.getframerate()
                print(f"  Audio: {sample_rate}Hz, {wf.getnframes()} frames, {wf.getnchannels()} channels")
        else:
            pcm_data = audio_file.read_bytes()
            print(f"  Raw PCM: {len(pcm_data)} bytes")

        # TODO: Feed through STT → get transcript → run through LLM → TTS → save output
        # This requires the full server pipeline running.
        # For now, log what would happen:
        trace = {
            "audio_file": audio_file.name,
            "audio_size_bytes": len(pcm_data),
            "status": "pending_stt_backend",
            "note": "Run with live STT/TTS backends for full E2E test",
        }

        trace_path = os.path.join(output_dir, f"{audio_file.stem}_trace.json")
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace, f, ensure_ascii=False, indent=2)
        print(f"  Trace: {trace_path}")


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="E2E voice flow test")
    parser.add_argument("--mode", choices=["text", "audio"], default="text")
    _here = Path(__file__).resolve().parent
    parser.add_argument("--input", default=str(_here / "audio"))
    parser.add_argument("--output", default=str(_here / "traces"))
    args = parser.parse_args()

    if args.mode == "text":
        await run_text_e2e(args.output)
    else:
        await run_audio_e2e(args.input, args.output)


if __name__ == "__main__":
    asyncio.run(main())
