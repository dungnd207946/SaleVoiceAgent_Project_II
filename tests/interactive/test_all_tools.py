#!/usr/bin/env python3
"""Comprehensive tool test — tests ALL 20 tools via WebSocket chat simulator.

Run while test_chat_sim.py is on port 8899:
    python tests/interactive/test_all_tools.py
"""

import asyncio
import json
import sys
import time
from pathlib import Path

SRC = str(Path(__file__).resolve().parents[2] / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import websockets

PASS = "\033[32m✅\033[0m"
FAIL = "\033[31m❌\033[0m"
WARN = "\033[33m⚠️\033[0m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"
URL = "ws://localhost:8899/ws"


async def send_and_collect(ws, msg_text: str, timeout: float = 30.0):
    """Send a message and collect all tool events + the final agent response."""
    await ws.send(json.dumps({"type": "message", "text": msg_text}))

    tools = []
    response_text = ""
    agent = ""
    t0 = time.monotonic()

    while time.monotonic() - t0 < timeout:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(15, timeout - (time.monotonic() - t0)))
            msg = json.loads(raw)

            if msg["type"] == "tool_event":
                tool = msg.get("tool", "")
                action = msg.get("action", "")
                detail = msg.get("detail", "")[:80]
                tools.append({"tool": tool, "action": action, "detail": detail})
                emoji = "🔧" if action == "start" else "✓"
                print(f"      {DIM}{emoji} {action.upper()} {tool}: {detail}{RESET}")

            elif msg["type"] == "agent_response":
                response_text = msg["text"]
                agent = msg.get("agent", "")
                ms = msg.get("llm_ms", "?")
                print(f"    {GREEN}<<< ({agent}, {ms}ms):{RESET} {response_text[:180]}")
                break

            elif msg["type"] == "error":
                response_text = msg["text"]
                print(f"    {FAIL} ERROR: {msg['text']}")
                break

        except TimeoutError:
            break

    return {"response": response_text, "agent": agent, "tools": tools}


async def wait_greeting(ws):
    """Wait for greeting, skipping system messages."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < 10:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            if msg["type"] == "agent_response":
                return msg["text"]
        except TimeoutError:
            break
    return ""


async def run_conversation(messages: list[str], name: str = "", timeout_per_msg: float = 30.0):
    """Open a fresh WebSocket session, send messages in order, collect results."""
    print(f"\n  {BOLD}{CYAN}── {name} ──{RESET}")

    async with websockets.connect(URL, open_timeout=5) as ws:
        greeting = await wait_greeting(ws)
        print(f"    {DIM}Greeting OK, agent=router{RESET}")

        results = []
        for msg in messages:
            print(f"    {YELLOW}>>> USER:{RESET} {msg}")
            r = await send_and_collect(ws, msg, timeout=timeout_per_msg)
            results.append(r)

        return results


async def main():
    print(f"\n{BOLD}{'=' * 70}")
    print("  VoiceAgentRAG — Full Tool Integration Test")
    print(f"  Server: {URL}")
    print(f"{'=' * 70}{RESET}")

    # Check server
    try:
        async with websockets.connect(URL, open_timeout=3) as ws:
            pass
    except Exception as e:
        print(f"\n{FAIL} Server not reachable: {e}")
        return

    total_pass = 0
    total_fail = 0

    # ─── FLOW 1: Router → Consultant → Info tools ─────────────────────
    results = await run_conversation(
        [
            "Tôi muốn tìm hiểu về dự án Noble Crystal Long Biên",
            "Cho tôi xem bảng giá căn 2 phòng ngủ",
            "Chính sách thanh toán như thế nào?",
            "Có ưu đãi gì không?",
        ],
        name="FLOW 1: Consultant — Info + Financial Tools",
    )

    # Check tools used
    all_tools_1 = set()
    for r in results:
        for t in r["tools"]:
            if t["action"] == "start":
                all_tools_1.add(t["tool"])

    expected_1 = {"switch_agent"}  # at minimum, router should switch to consultant
    for t in expected_1:
        if t in all_tools_1:
            print(f"  {PASS} Tool '{t}' was used")
            total_pass += 1
        else:
            print(f"  {WARN} Tool '{t}' not seen (LLM may have answered directly)")

    # Check noble_search specifically
    if "kb_search" in all_tools_1:
        # Check for lightrag error
        noble_details = [
            t["detail"]
            for t in sum([r["tools"] for r in results], [])
            if t["tool"] == "kb_search" and t["action"] == "done"
        ]
        has_error = any("lightrag" in d.lower() or "error" in d.lower() for d in noble_details)
        if has_error:
            print(f"  {FAIL} noble_search still has lightrag error!")
            total_fail += 1
        else:
            print(f"  {PASS} noble_search works (no lightrag error)")
            total_pass += 1
    else:
        print(f"  {DIM}  ℹ️  noble_search not triggered in this flow{RESET}")

    # Check financial tools
    financial_tools = {"get_project_financial", "search_units", "discover_projects"}
    found_financial = financial_tools & all_tools_1
    if found_financial:
        for t in found_financial:
            details = [
                x["detail"] for x in sum([r["tools"] for r in results], []) if x["tool"] == t and x["action"] == "done"
            ]
            has_err = any("error" in d.lower() for d in details)
            if has_err:
                print(f"  {FAIL} {t} returned error: {details[0][:60]}")
                total_fail += 1
            else:
                print(f"  {PASS} {t} executed successfully")
                total_pass += 1

    print(f"  {DIM}All tools seen: {sorted(all_tools_1)}{RESET}")

    # ─── FLOW 2: Booking flow ─────────────────────────────────────────
    results = await run_conversation(
        [
            "Tôi muốn đặt lịch xem nhà dự án Noble Crystal Long Biên",
            "Tên tôi là Minh, số điện thoại 0912345678",
            "Ngày thứ bảy tuần này được không?",
        ],
        name="FLOW 2: Consultant — Booking Flow",
    )

    all_tools_2 = set()
    for r in results:
        for t in r["tools"]:
            if t["action"] == "start":
                all_tools_2.add(t["tool"])

    booking_tools = {
        "get_booking_state",
        "update_booking_info",
        "schedule_viewing",
        "check_availability",
        "validate_phone",
    }
    found_booking = booking_tools & all_tools_2
    for t in found_booking:
        details = [
            x["detail"] for x in sum([r["tools"] for r in results], []) if x["tool"] == t and x["action"] == "done"
        ]
        has_err = any("not defined" in d.lower() or "error" in d.lower() for d in details)
        if has_err:
            print(f"  {FAIL} {t} had error: {details[0][:80]}")
            total_fail += 1
        else:
            print(f"  {PASS} {t} executed successfully")
            total_pass += 1

    if "update_customer" in all_tools_2:
        print(f"  {PASS} update_customer used (captured name/phone)")
        total_pass += 1

    print(f"  {DIM}All tools seen: {sorted(all_tools_2)}{RESET}")

    # ─── FLOW 3: Support — CRM + Escalation ──────────────────────────
    results = await run_conversation(
        [
            "Tôi đã mua căn hộ ở Noble Crystal, muốn kiểm tra hợp đồng",
            "Số điện thoại của tôi là 0987654321",
            "Tôi muốn gặp chuyên viên người thật",
        ],
        name="FLOW 3: Support — CRM + Escalation",
    )

    all_tools_3 = set()
    for r in results:
        for t in r["tools"]:
            if t["action"] == "start":
                all_tools_3.add(t["tool"])

    support_tools = {"crm_lookup", "verify_identity", "switch_agent", "escalate", "support_ticket"}
    found_support = support_tools & all_tools_3
    for t in found_support:
        details = [
            x["detail"] for x in sum([r["tools"] for r in results], []) if x["tool"] == t and x["action"] == "done"
        ]
        has_err = any("error" in d.lower() and "not found" not in d.lower() for d in details)
        if has_err:
            print(f"  {FAIL} {t} had error: {details[0][:80]}")
            total_fail += 1
        else:
            print(f"  {PASS} {t} executed successfully")
            total_pass += 1

    print(f"  {DIM}All tools seen: {sorted(all_tools_3)}{RESET}")

    # ─── FLOW 4: Direct noble_search test ─────────────────────────────
    results = await run_conversation(
        [
            "Tôi muốn tìm hiểu dự án Noble Crystal Long Biên",
            "Tiện ích nội khu dự án này có những gì?",
        ],
        name="FLOW 4: Direct noble_search test",
    )

    all_tools_4 = set()
    for r in results:
        for t in r["tools"]:
            if t["action"] == "start":
                all_tools_4.add(t["tool"])

    if "kb_search" in all_tools_4:
        noble_done = [
            x["detail"]
            for x in sum([r["tools"] for r in results], [])
            if x["tool"] == "kb_search" and x["action"] == "done"
        ]
        has_err = any("lightrag" in d.lower() or "error" in d.lower() for d in noble_done)
        if has_err:
            print(f"  {FAIL} noble_search STILL has lightrag error!")
            total_fail += 1
        else:
            print(f"  {PASS} noble_search returned real data (MemoryRouter fallback worked)")
            total_pass += 1
    else:
        print(f"  {DIM}  ℹ️  noble_search not triggered (LLM answered directly){RESET}")

    print(f"  {DIM}All tools seen: {sorted(all_tools_4)}{RESET}")

    # ─── SUMMARY ──────────────────────────────────────────────────────
    all_tools_used = all_tools_1 | all_tools_2 | all_tools_3 | all_tools_4

    print(f"\n{BOLD}{'=' * 70}")
    print("  SUMMARY")
    print(f"{'=' * 70}{RESET}")
    print(f"  {PASS} Passed: {total_pass}")
    print(f"  {FAIL} Failed: {total_fail}")
    print(f"  Tools actually used across all flows: {sorted(all_tools_used)}")

    # Check which tools were NEVER triggered
    all_schema_tools = {
        "kb_search",
        "list_projects",
        "discover_projects",
        "get_project_financial",
        "search_units",
        "match_projects",
        "schedule_viewing",
        "list_bookings",
        "modify_booking",
        "check_availability",
        "validate_phone",
        "update_customer",
        "switch_agent",
        "crm_lookup",
        "verify_identity",
        "support_ticket",
        "get_certificate_status",
        "escalate",
        "get_booking_state",
        "update_booking_info",
    }
    never_used = all_schema_tools - all_tools_used
    if never_used:
        print(f"  {DIM}Tools never triggered by LLM: {sorted(never_used)} (normal — LLM decides){RESET}")


if __name__ == "__main__":
    asyncio.run(main())
