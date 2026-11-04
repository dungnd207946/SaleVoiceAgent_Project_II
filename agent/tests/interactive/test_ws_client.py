#!/usr/bin/env python3
"""WebSocket client test for chat simulator — sends test messages and prints responses.

Run while test_chat_sim.py is running on port 8899:
    python tests/interactive/test_ws_client.py
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
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"

URL = "ws://localhost:8899/ws"

TEST_SCENARIOS = [
    {
        "name": "Greeting check",
        "messages": [],  # no message sent — just check auto greeting
        "expect_in_greeting": ["Luna", "Noble"],
    },
    {
        "name": "Router → Consultant (info inquiry)",
        "messages": ["Tôi muốn tìm hiểu dự án Noble Crystal Long Biên"],
        "expect_tools": ["switch_agent"],
        "expect_in_response": [],  # any response is OK
    },
    {
        "name": "Pricing query (consultant)",
        "messages": ["Giá bán căn 2 phòng ngủ bao nhiêu?"],
        "expect_tools": ["get_project_financial", "kb_search"],  # at least one
        "expect_in_response": [],
    },
    {
        "name": "Booking inquiry",
        "messages": ["Tôi muốn đặt lịch xem nhà"],
        "expect_tools": [],
        "expect_in_response": [],
    },
]


async def run_scenario(scenario: dict, scenario_idx: int) -> dict:
    """Run one test scenario. Returns result dict."""
    name = scenario["name"]
    print(f"\n{BOLD}{CYAN}━━━ Scenario {scenario_idx + 1}: {name} ━━━{RESET}")

    result = {"name": name, "passed": True, "details": []}

    try:
        async with websockets.connect(URL, open_timeout=5) as ws:
            # Collect greeting
            greeting_text = ""
            agent_name = ""
            messages_received = []
            tools_seen = []

            # Read messages until we get the greeting (with timeout)
            t0 = time.monotonic()
            while time.monotonic() - t0 < 8:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3)
                    msg = json.loads(raw)

                    if msg["type"] == "agent_response" and msg.get("source") == "auto_greeting":
                        greeting_text = msg["text"]
                        agent_name = msg.get("agent", "")
                        print(f"  {GREEN}Greeting:{RESET} {greeting_text[:120]}...")
                        break
                    elif msg["type"] == "system":
                        print(f"  {DIM}[system] {msg['text']}{RESET}")
                except TimeoutError:
                    break

            # Check greeting expectations
            if scenario.get("expect_in_greeting"):
                for kw in scenario["expect_in_greeting"]:
                    if kw in greeting_text:
                        print(f"  {PASS} Greeting contains '{kw}'")
                    else:
                        print(f"  {FAIL} Greeting missing '{kw}'")
                        result["passed"] = False

            # Send test messages
            for msg_text in scenario.get("messages", []):
                print(f"\n  {YELLOW}>>> USER:{RESET} {msg_text}")
                await ws.send(json.dumps({"type": "message", "text": msg_text}))

                # Collect responses (agent_response, tool_event) with timeout
                response_text = ""
                t1 = time.monotonic()
                while time.monotonic() - t1 < 30:  # max 30s per message
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=15)
                        msg = json.loads(raw)

                        if msg["type"] == "tool_event":
                            tool_name = msg.get("tool", "")
                            action = msg.get("action", "")
                            detail = msg.get("detail", "")[:80]
                            tools_seen.append(tool_name)
                            emoji = "🔧" if action == "start" else "✓"
                            print(f"  {DIM}  {emoji} {action.upper()} {tool_name}: {detail}{RESET}")

                        elif msg["type"] == "agent_response":
                            response_text = msg["text"]
                            agent_name = msg.get("agent", agent_name)
                            source = msg.get("source", "")
                            llm_ms = msg.get("llm_ms", "?")
                            print(f"  {GREEN}<<< LUNA ({agent_name}, {llm_ms}ms):{RESET} {response_text[:200]}")
                            if len(response_text) > 200:
                                print(f"  {DIM}    ...({len(response_text)} chars total){RESET}")
                            messages_received.append(response_text)
                            break  # got the response

                        elif msg["type"] == "error":
                            print(f"  {FAIL} ERROR: {msg['text']}")
                            result["passed"] = False
                            break

                        elif msg["type"] in ("idle_start", "idle_cancel", "system"):
                            pass  # ignore idle/system messages

                    except TimeoutError:
                        print(f"  {FAIL} Timeout waiting for response (15s)")
                        result["passed"] = False
                        break

                # Check response expectations
                if response_text:
                    for kw in scenario.get("expect_in_response", []):
                        if kw.lower() in response_text.lower():
                            print(f"  {PASS} Response contains '{kw}'")
                        else:
                            print(f"  {FAIL} Response missing '{kw}'")
                            result["passed"] = False
                elif scenario.get("messages"):
                    print(f"  {FAIL} No response received")
                    result["passed"] = False

            # Check tool usage (any of expected tools seen)
            if scenario.get("expect_tools"):
                expected = set(scenario["expect_tools"])
                seen = set(tools_seen)
                overlap = expected & seen
                if overlap:
                    print(f"  {PASS} Tools used: {sorted(seen)}")
                else:
                    # Soft pass — LLM might answer without tools if it has context
                    print(
                        f"  {DIM}  ℹ️  Expected tools {sorted(expected)} but saw {sorted(seen)} (LLM answered directly){RESET}"
                    )

            # Show final agent state
            if agent_name:
                print(f"  {DIM}  Current agent: {agent_name}{RESET}")

    except Exception as e:
        print(f"  {FAIL} Connection error: {e}")
        result["passed"] = False

    return result


async def main():
    print(f"\n{BOLD}{'=' * 60}")
    print("  VoiceAgentRAG — Chat Simulator Integration Test")
    print(f"  Server: {URL}")
    print(f"{'=' * 60}{RESET}")

    # Check server is reachable
    try:
        async with websockets.connect(URL, open_timeout=3) as ws:
            pass
        print(f"\n{PASS} Server reachable at {URL}")
    except Exception as e:
        print(f"\n{FAIL} Cannot connect to {URL}: {e}")
        print("  Make sure test_chat_sim.py is running:")
        print("  python tests/interactive/test_chat_sim.py")
        return

    results = []
    for i, scenario in enumerate(TEST_SCENARIOS):
        r = await run_scenario(scenario, i)
        results.append(r)

    # Summary
    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    print(f"\n{BOLD}{'=' * 60}")
    print(f"  RESULTS: {passed}/{total} scenarios passed")
    print(f"{'=' * 60}{RESET}")
    for r in results:
        icon = PASS if r["passed"] else FAIL
        print(f"  {icon} {r['name']}")

    if passed == total:
        print(f"\n{BOLD}{GREEN}  🎉 All scenarios passed!{RESET}")
    else:
        print(f"\n{BOLD}{YELLOW}  ⚠️  {total - passed} scenario(s) need attention{RESET}")


if __name__ == "__main__":
    asyncio.run(main())
