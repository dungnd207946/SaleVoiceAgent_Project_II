# 09 — API Contracts: AudioSocket Binary + Tool Schemas

> The two protocols that don't fit on the WebSocket. **AudioSocket** is the binary TCP wire format between Asterisk and the agent (TLV frames, slin 8 kHz). **Tool schemas** are the JSON-Schema function definitions the LLM sees — they govern tool selection, argument shapes, and what tools each agent persona can use.

Read [`07-freepbx-asterisk-bridge.md`](07-freepbx-asterisk-bridge.md) for the AudioSocket flow and [`02-llm-and-agents.md`](02-llm-and-agents.md) for how tools fit into a turn.

---

## 1. AudioSocket — TCP wire format

### 1.1 Listener

Agent listens on TCP `8090`. One connection per call. No TLS (firewall the port; never expose publicly).

```
struct.pack(">BH", type, length) + payload
big-endian, 1 byte type + 2 bytes length + payload
```

### 1.2 Frame types

| Hex | Name | Payload size | Direction | Meaning |
|---|---|---:|---|---|
| `0x00` | `HANGUP` | 0 | Either | Close connection |
| `0x01` | `UUID` | 16 | Asterisk → Agent | Call ID (raw 16-byte UUID, hyphens stripped). MUST be the first frame |
| `0x02` | `SILENCE` | 0 | Either | Optional comfort silence — we don't emit |
| `0x10` | `AUDIO` | 320 | Either | One 20 ms PCM16 LE 8 kHz mono frame |
| `0xFF` | `ERROR` | 1 | Either | Error code byte; receiver SHOULD bail |

### 1.3 Connection lifecycle

```
[Asterisk]                                   [Agent :8090]
    │   TCP SYN                                   │
    │   ─────────────────────────────────────►    │
    │   ◄─────── TCP SYN/ACK ──────────────────   │  set TCP_NODELAY
    │   ─────────── TCP ACK ─────────────────►    │
    │                                             │
    │   TYPE_UUID (0x01) + len(16) + uuid_bytes   │
    │   ─────────────────────────────────────►    │  parse → call_id
    │                                             │
    │   TYPE_AUDIO (0x10) + len(320) + 20ms       │
    │   ─────────────────────────────────────►    │  resample 8→16, VAD,
    │                                             │  STT, LLM, …
    │   TYPE_AUDIO (0x10) + len(320) + 20ms       │
    │   ─────────────────────────────────────►    │
    │                  …                          │
    │                                             │
    │   ◄────  TYPE_AUDIO (0x10) + 20ms TTS  ─    │  resample 24→8 +
    │   ◄────  TYPE_AUDIO (0x10) + 20ms TTS  ─    │  bandpass + pacing
    │                                             │
    │   TYPE_HANGUP (0x00) + len(0)               │
    │   ─────────────────────────────────────►    │  end session
    │   ◄────  FIN  ─────────────────────────     │
```

### 1.4 Invariants the agent enforces

1. **First frame must be `TYPE_UUID`.** Anything else: log + close.
2. **Audio frames must be exactly 320 bytes.** Asterisk will only send 320; agent only emits 320. Anything else: log + drop frame.
3. **TCP_NODELAY is on.** Without it Nagle batches frames into ~40 ms blocks (audio sounds underwater). Set on `accept()`.
4. **Comfort noise during silence.** When agent isn't speaking but call is active, send 320-byte frames at 20 ms cadence with `np.random.normal(0, 32)` PCM16. Asterisk drops idle TCP after ~5 s otherwise.
5. **One call per connection.** Don't multiplex; spawn a new connection task for each `accept()`.

### 1.5 Reading a frame (Python)

```python
async def _read_one_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    head = await reader.readexactly(3)
    frame_type = head[0]
    length = struct.unpack(">H", head[1:3])[0]
    payload = await reader.readexactly(length) if length else b""
    return frame_type, payload
```

### 1.6 Writing audio (pacing-aware)

```python
def _make_audio_frame(pcm_320b: bytes) -> bytes:
    assert len(pcm_320b) == 320
    return struct.pack(">BH", 0x10, 320) + pcm_320b

# In TX pacing task:
while not stop:
    frame = _make_audio_frame(next_320b)
    writer.write(frame)
    await writer.drain()
    await asyncio.sleep(0.020 - jitter_compensation)
```

Real implementation: `src/noble_agent/telephony/audiosocket.py`.

### 1.7 Errors

`TYPE_ERROR (0xFF)` is informational. The standard says receivers should bail; we close cleanly and let Asterisk redial / hang up. Don't try to recover mid-call from an error frame.

---

## 2. WebRTC media — what's NOT in the WebSocket

A point of confusion: the browser's WebSocket carries JSON only. **Audio flows over the WebRTC peer connection** that the JSON `rtc_offer` / `rtc_answer` exchange establishes.

```
[Browser]                                    [Agent]
   │ WS open /ws                                │
   │ ──────────────────────────────────────►    │
   │ ◄── {"type":"session_id",...}              │
   │                                            │
   │ ─── {"type":"rtc_offer","sdp":"v=0..."} ─► │  aiortc create answer
   │ ◄── {"type":"rtc_answer","sdp":"v=0..."} ─ │
   │                                            │
   │ ICE / DTLS / SRTP handshake (UDP/443)      │
   │                                            │
   │   Opus 48 kHz over SRTP ───────────────►   │  decode → resample 48→16
   │                                            │  → VAD → STT → LLM
   │                                            │
   │   Opus 48 kHz over SRTP ◄──────────────    │  resample 24→48 →
   │                                            │  encode Opus
```

The WS stays open during media flow for control messages (`interrupt`, `set_voice`, etc.). Closing the WS does NOT immediately drop the SRTP channel — the browser keeps playing buffered audio for a few seconds before the peer connection times out.

When `TRANSPORT_BACKEND=livekit`, the WebRTC plumbing is delegated to LiveKit Cloud — the agent connects as a LiveKit "agent" worker. JSON envelopes on the WS look the same; the SRTP path goes through LiveKit's edge servers instead of direct browser ↔ agent.

---

## 3. Tool calling — schemas the LLM sees

File: `src/noble_agent/agent/tools/schemas.py`. These are OpenAI function-calling JSON schemas. The agent passes a filtered slice of `TOOL_DEFINITIONS` to each LLM call based on the active persona's `config.json` whitelist.

### 3.1 The full `TOOL_DEFINITIONS` shape

```jsonc
TOOL_DEFINITIONS = [
  {
    "type": "function",
    "function": {
      "name": "<tool_name>",
      "description": "<Vietnamese description telling the model when to use this tool>",
      "parameters": {
        "type": "object",
        "properties": { ... },
        "required": [ ... ]
      }
    }
  },
  ...
]
```

### 3.2 Tool list (production)

| Tool | Args (required first) | Returns |
|---|---|---|
| `noble_search` | `query`, `project_filter` (NCLB/NPLB/NCTH/NTTL/SSLC/'') | text block from FlatStore RAG |
| `list_projects` | `region` (Long Biên / Tây Hồ / Tây Thăng Long / '') | list of project codes + names |
| `get_project_overview` | `project_code` OR `project_name` | location, type, scale, highlights |
| `get_project_financial` | `project_code` | price table, payment terms, financing, fees |
| `match_projects` | `criteria` (object: budget, area, region, beds) | top-3 matching projects |
| `search_units` | `project_code`, `bedrooms`, `min_area`, `max_area`, `floor` | unit list with availability |
| `check_availability` | `project_code`, `unit_id` | bool + asking price |
| `schedule_viewing` | `customer_name`, `phone`, `project_code`, `preferred_date`, `preferred_time` | booking_id |
| `list_bookings` | `phone` (optional) | bookings array |
| `modify_booking` | `booking_id`, `new_preferred_date`, `new_preferred_time` | status |
| `validate_phone` | `phone` (Vietnamese mobile/landline) | bool + canonical form |
| `update_customer` | `name` / `full_name` / `phone` / `project_interest` / others | persists to Redis |
| `crm_lookup` | `phone` | existing customer record (or null) |
| `verify_identity` | `phone`, `full_name` | match score + booking history |
| `support_ticket` | `category`, `summary`, `severity` | ticket_id |
| `get_certificate_status` | `phone` OR `booking_id` | ownership cert state |
| `escalate` | `reason`, `summary` | hand-off URL or operator extension |
| `get_booking_state` | (uses session) | what fields still need filling |
| `update_booking_info` | `customer_name`, `phone`, `project_code`, ... | partial booking update |
| `send_media` | `phone`, `payload` | push notification ack |
| `switch_agent` | `target` (router/consultant/support) | switches persona for next turn |

### 3.3 Example — `noble_search` schema (verbatim)

```jsonc
{
  "type": "function",
  "function": {
    "name": "noble_search",
    "description": "Tìm kiếm thông tin chi tiết về dự án Noble Real Estate từ knowledge base. Dùng khi khách hỏi về tiện ích, vị trí chi tiết, thiết kế, vật liệu, công nghệ, giao thông, so sánh dự án, hoặc bất kỳ thông tin cụ thể nào.",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Câu hỏi tìm kiếm bằng tiếng Việt, rõ ràng và cụ thể"
        },
        "project_filter": {
          "type": "string",
          "description": "Mã dự án để lọc (NCLB, NPLB, NCTH, NTTL, SSLC). Để trống nếu tìm tất cả.",
          "enum": ["", "NCLB", "NPLB", "NCTH", "NTTL", "SSLC"]
        }
      },
      "required": ["query"]
    }
  }
}
```

`description` matters more than developer instinct expects — the model uses it to decide **when** to call the tool. Vietnamese descriptions give the model the right register; mixing with English degrades selection quality.

### 3.4 Tool-call wire format (from the LLM)

When the LLM decides to call a tool, the streaming delta contains:

```jsonc
{
  "tool_calls": [{
    "id": "call_abc123",
    "type": "function",
    "function": {
      "name": "noble_search",
      "arguments": "{\"query\": \"thanh toán Lakeside\", \"project_filter\": \"NCLB\"}"
    }
  }]
}
```

`arguments` is a **JSON string**, not an object. The agent parses it (`json.loads(call.arguments)`) and dispatches to `execute_tool(name, args, session_id)`.

Multiple tool calls may appear in one delta — the loop handles each before re-calling the LLM. Tool replies are appended as `role: "tool"` messages with the same `tool_call_id`.

### 3.5 Tool reply wire format (from the agent)

```jsonc
{
  "role": "tool",
  "tool_call_id": "call_abc123",
  "content": "Noble Crystal Long Biên..."   // ALWAYS a string; if dict, JSON-stringify
}
```

The string `content` field is what the model sees for the next turn. Keep it under ~2 k tokens; truncate long FlatStore hits if needed.

### 3.6 V7 auto-side-effect

`agent/tools/__init__.py:_v7_auto_set_project_interest` watches every tool call's args. If it sees `project_filter="NCLB"` (or any valid code) on `noble_search` / `match_projects` / etc., it writes `customer.project_interest = "NCLB"` to Redis even though the model didn't explicitly call `update_customer`. The write goes through `project_catalog.normalize()` so aliases work.

This is **observable behavior** for tests — bench harnesses verify the auto-side-effect fires. Detail: [`02-llm-and-agents.md`](02-llm-and-agents.md) §4.2.

### 3.7 Per-agent tool whitelisting

Each persona's `config.json`:

```jsonc
// agent/definitions/agents/router/config.json (excerpt)
{
  "tools": [
    "noble_search",
    "switch_agent",
    "update_customer",
    "validate_phone",
    "crm_lookup"
  ]
}
```

`agent/registry.py` filters `TOOL_DEFINITIONS` to only this whitelist before passing to the LLM. Adding a tool to the global definitions does NOT make it visible to existing agents — you must add the name to each agent's `tools` array that should use it.

### 3.8 Adding a new tool

Detail in [`02-llm-and-agents.md`](02-llm-and-agents.md) §8. Summary:

1. Append to `TOOL_DEFINITIONS` in `schemas.py` with full Vietnamese description + JSON Schema parameters.
2. Add `_handle_<name>` in `agent/tools/__init__.py:execute_tool`.
3. Add to relevant agents' `config.json:tools`.
4. Unit-test under `tests/unit/agent/tools/test_<name>.py`.
5. If long-running, add a deferred-narration entry in `agent/prompts/`.
6. Bench it via `tests/bench_llm.py --case <new>` to confirm the model picks it up.

---

## 4. Tool-call timing budget

| Tool | Target p95 |
|---|---:|
| `validate_phone` | 5 ms (regex only) |
| `update_customer` | 25 ms (Redis hot) |
| `noble_search` (warm) | 50 ms (FlatStore) |
| `noble_search` (cold) | 200 ms (FlatStore + SemanticCache miss) |
| `crm_lookup` | 800 ms (HTTP to Noble Profile API; cache 1 h positive, 5 min negative) |
| `schedule_viewing` | 150 ms (Mongo write) |
| `send_media` | 100 ms (HTTP to Outreach API) |
| `escalate` | 50 ms (Redis pub-sub, async push) |

Anything >150 ms triggers the deferred-narration ack so the user hears speech instead of silence. Tune the threshold via `DEFERRED_ACK_DELAY_MS` (default 250 ms — fast enough that <150 ms tools never hit it).

Bench: `tests/bench_rag/tool_timing.py --threshold-ms 150`.

---

## 5. Common debugging

| Symptom | Likely cause | Fix |
|---|---|---|
| Audio "underwater" / muffled | TCP_NODELAY off | Set on accept; verify `getsockopt` shows TCP_NODELAY=1 |
| First AudioSocket frame is `TYPE_AUDIO` | Asterisk dialplan missing `Stasis` (or AudioSocket arg malformed) | Re-check dialplan; UUID slice must be 8-4-4-4-12 hex |
| LLM never calls a defined tool | Description in English / vague | Rewrite in Vietnamese matching how callers actually speak |
| LLM calls `update_customer` with `project_interest="Lakeside"` (not canonical) | Description doesn't say "use code" | Add explicit `enum` constraint as in `noble_search` |
| Tool returns dict, model sees stringified JSON | Forgot to wrap in `str(json.dumps(...))` | Always JSON-stringify dict tool returns |
| Bench shows tool latency spike post-deploy | New tool added without timing budget | Add to `tool_timing.py` thresholds |
| `_v7_auto_set_project_interest` not firing | Tool args don't have `project_filter` key | The auto-set checks specific arg names; rename args or extend `_v7_auto_set_project_interest` |
| LLM calls `switch_agent` repeatedly | Agent SOUL/SKILL not specific enough → model bounces | Tighten prompts; switch_agent should be terminal |

---

## 6. References

- AudioSocket spec: https://wiki.asterisk.org/wiki/display/AST/AudioSocket
- OpenAI function calling: https://platform.openai.com/docs/guides/function-calling
- LiveKit agents: https://docs.livekit.io/agents
- aiortc: https://aiortc.readthedocs.io
- `src/noble_agent/agent/tools/schemas.py` — full tool definitions (the source of truth)
- `src/noble_agent/agent/definitions/agents/<persona>/config.json` — per-persona whitelist
