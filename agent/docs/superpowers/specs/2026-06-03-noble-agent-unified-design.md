# Noble Agent Unified — Design Spec

**Status**: draft — development only, no production rollout planned in this spec.
**Author**: Du Tran (`dutn@noblex.vn`)
**Date**: 2026-06-03
**Branch**: `refactor/unify-agent`
**Supersedes (scope)**: parts of `2026-06-01-noble-agent-refactor-design.md` (multi-agent router/consultant/support architecture)
**Related**: `docs/refactor/plan-1.md` (Plan-1 — shared session state principle)

---

## 1. Motivation

The current production system (`src/noble_agent/`) and the in-progress refactor (`src/noble_agent_refactor/`) both implement a **3-agent architecture**: a Manager (MA, lễ tân/router), a Consultant (CA, pre-sale), and a Support agent (SA, post-sale). The agents talk to each other through a structured `switch_agent` handoff, with per-agent threads, briefings, and async summaries to preserve context across handoffs.

In practice, all three agents share the same domain (Noble Real Estate), the same voice/tone style, and the same backing tools. The handoff machinery exists mostly to keep prompts small per agent — not because the domain is genuinely heterogeneous. The split has costs:

- **Routing failure modes**: even with active-agent stickiness (Plan-1 §2), bouncing between agents creates edge cases (e.g. CA → MA → CA for a single slot collection) that complicate the orchestrator.
- **Prompt drift**: shared RULES.md vs per-agent RULES.md often duplicate or contradict each other — the LLM gets mixed signals.
- **Per-agent threads + briefings**: each handoff costs an extra LLM call to generate a briefing summary; transient briefing failures degrade context.
- **Tool fragmentation**: the same `noble_search` tool exists for CA and SA, but with different surrounding context — fixes have to land twice.

This spec describes a **unified single-agent architecture** where one agent (persona: **Luna**) owns the entire conversation end-to-end, with the full tool set of CA+SA available at all times, driven by a single **operational protocol prompt** that replaces three separate per-agent RULES files.

The new code lives in a new package, `src/noble_agent/`, structured as a self-contained replacement for both `noble_agent/` and `noble_agent_refactor/`. It includes its own service layer (voice, transport, telephony, server) so the package can run standalone behind a feature flag.

---

## 2. Scope

### 2.1 In scope (this spec)

- New package `src/noble_agent/` with:
  - **Agent core** under `agent/` (definitions, prompts, tools, llm, rag, orchestrator, summary, facade).
  - **Service layer** under `server/`, `voice/`, `telephony/`, `transport/`, `services/`, `storage/`, `metrics/` — copied 1-1 from `noble_agent/`, only import paths rewritten.
- Unified operational-protocol prompt (5 sections: Identity / Operational Protocol / Tool Catalog / Style / Guardrails).
- Single shared state in Redis (Plan-1 §1), with state schema simplified to one history list + one summary.
- Feature flag `USE_UNIFIED_AGENT` so the unified package runs alongside legacy/refactor without conflict.
- Unit + integration tests sufficient for the user to verify the unified path in development.

### 2.2 Out of scope (explicitly deferred)

- Production rollout, canary, A/B metrics, success criteria. The user will evaluate quality manually in development before deciding on production.
- Cleanup of `noble_agent/` and `noble_agent_refactor/` — both stay until the user signs off on unified. Cleanup will get a separate spec.
- Semantic response cache (`semcache/`). The current implementation in refactor depends on per-agent threads + briefings; redesigning it for the unified single-thread model is a separate effort. The relevant settings stay but default to disabled.
- Session migration between legacy/refactor and unified state schemas. Sessions started on one path do not survive a flag flip — acceptable in dev.
- New features beyond what's in legacy/refactor today. This is a refactor, not a feature release.

---

## 3. Design principles

These are preserved from Plan-1 and applied to the single-agent architecture:

1. **Shared session state, one source of truth (Plan-1 §1)** — all conversation state lives in 3 Redis keys per session. No process-local memory survives across turns.
2. **State drives behavior, not message classification (Plan-1 §2, adapted)** — in the multi-agent model this meant "active-agent stickiness". With one agent, this principle reduces to: the agent always sees the full prior state (customer profile + history + summary) before deciding what to do.
3. **Agent collects what it needs itself (Plan-1 §3, adapted)** — there is no other agent to hand off to. When information is missing, the agent asks the user directly. When the request exceeds the agent's scope (e.g. customer wants to speak with a human), the agent calls `escalate`, which is now the only "handoff" tool.
4. **No round-trip summarization at every turn** — per-turn summarization adds LLM cost without benefit. Summary fires only when history grows past a threshold, runs asynchronously, and only the overflow tail gets summarized.

The unified architecture inherits these principles wholesale. The thing it discards is the **per-agent thread + briefing chain**, which was a workaround for keeping per-agent prompts small.

---

## 4. Architecture

### 4.1 Package layout

```
src/noble_agent/
├── __init__.py
├── __main__.py                # CLI entry; dispatches to legacy if flag off
├── _runner.py
├── config.py                  # UnifiedSettings — merges legacy + refactor settings
├── agent/                     # ← agent core
│   ├── __init__.py
│   ├── facade.py              # NobleAgent: drop-in for transport
│   ├── orchestrator.py        # TurnRunner: single turn, no handoff chain
│   ├── runner.py              # run_turn: LLM stream + tool loop
│   ├── definitions/
│   │   ├── SOUL.md            # Luna identity
│   │   ├── RULES.md           # Operational Protocol + Tool Catalog + Style + Guardrails
│   │   ├── PROMPT_TEMPLATE.md # Jinja composer
│   │   ├── CUSTOMER_PROFILE.md
│   │   └── config.json        # model / temperature / max_tokens / tools list
│   ├── prompts/
│   │   └── builder.py         # build_system_prompt
│   ├── tools/                 # 12 tools (CA+SA union, no switch_agent)
│   │   ├── __init__.py
│   │   ├── schemas.py
│   │   ├── dispatcher.py
│   │   ├── update_customer.py
│   │   ├── noble_search.py
│   │   ├── projects_info.py   # list_projects + get_project_overview
│   │   ├── project_financial.py
│   │   ├── search_units.py
│   │   ├── match_projects.py
│   │   ├── booking.py
│   │   ├── booking_state.py
│   │   ├── availability.py
│   │   ├── schedule_viewing.py
│   │   ├── support_ops.py     # crm_lookup, verify_identity, support_ticket, escalate
│   │   └── send_via_app.py
│   ├── llm/
│   │   ├── client.py
│   │   └── anthropic_provider.py
│   ├── rag/                   # FlatStore + faq_searcher
│   ├── summary/
│   │   └── summarizer.py      # async summary when history > K
│   ├── catalog.py             # project code normalize (NCLB/NCTH/NPLB/NTTL/SSLC)
│   └── qwen_transcript.py     # training-log writer (optional)
├── storage/                   # ← copied from legacy noble_agent/storage/
│   ├── connection.py
│   ├── session_store.py
│   ├── redis_client.py
│   ├── mongo_client.py
│   ├── models.py              # Meta / Customer / State (simplified)
│   └── repo.py
├── server/                    # ← copied from legacy noble_agent/server/
│   ├── http.py
│   ├── ws_handler.py
│   ├── session.py
│   ├── text_chat.py
│   ├── base_session.py
│   ├── outbound_endpoints.py
│   ├── rate_limit.py
│   ├── csv_export.py
│   ├── logging_config.py
│   └── _websockets_post_patch.py
├── voice/                     # ← copied from legacy noble_agent/voice/
│   ├── stt/{soniox,sherpa,elevenlabs,qwen3asr}.py
│   ├── tts/{vieneu,elevenlabs}.py
│   ├── vad/silero.py
│   ├── turn_detection/smart_turn.py
│   ├── audio/
│   ├── sentence_buffer.py     # moved from legacy noble_agent/agent/
│   └── voice_agent.py         # moved from legacy noble_agent/agent/voice.py
├── telephony/                 # ← copied from legacy noble_agent/telephony/
├── transport/                 # ← copied from legacy noble_agent/transport/ (incl. livekit/)
├── services/                  # ← copied from legacy noble_agent/services/
└── metrics/                   # ← copied from legacy noble_agent/metrics/
```

### 4.2 Module boundaries

- **`agent/`** owns: prompt, tool schemas + execution, LLM streaming, conversation orchestration, summary. Knows nothing about WebSockets, audio, telephony.
- **`server/`** owns: HTTP/WS endpoints, session lifecycle, request routing. Imports `agent.facade.NobleAgent` to get a per-session agent instance.
- **`voice/`** owns: audio I/O backends (STT/TTS/VAD/turn detection/audio resampling), the voice loop (`voice_agent.py`), and sentence buffering.
- **`telephony/`** owns: SIP/PSTN provider abstractions.
- **`transport/`** owns: WebRTC + LiveKit transport layer.
- **`services/`** owns: external integrations (CRM, structured data).
- **`storage/`** owns: Redis + MongoDB clients, session state repository.
- **`metrics/`** owns: MongoDB `session_metrics` collection writer.

The only direction `agent/` is imported is **downward into `server/`** (and `voice/voice_agent.py`, which is the voice-mode driver). It does not import from `server/` or `voice/` — strict one-way dependency.

---

## 5. State model

### 5.1 Redis schema (3 keys per session, TTL = `NOBLE_SESSION_TTL`, default 86400s)

| Key | Pydantic model | Update cadence |
|---|---|---|
| `session:{sid}:meta` | `Meta` | every turn (writes `last_active`) |
| `session:{sid}:customer` | `Customer` | when `update_customer` runs, or when a tool auto-sets a field (e.g. `noble_search` setting `project_interest`) |
| `session:{sid}:state` | `State` | every turn (history append) + async when summary is rewritten |

### 5.2 Models

```python
# storage/models.py

class Meta(BaseModel):
    session_id: str
    started_at: datetime
    last_active: datetime
    phone: str | None = None
    # No active_agent field — single agent, no need to track

class Customer(BaseModel):
    name: str | None = None
    full_name: str | None = None
    gender: Literal["M", "F"] | None = None
    phone: str | None = None
    project_interest: str | None = None      # canonical 4-char code
    purpose: str | None = None
    budget: str | None = None
    preferred_area: str | None = None
    bedroom_count: str | None = None
    is_buyer: bool | None = None
    is_noble_customer: bool | None = None
    noble_info: str | None = None

class ThreadMessage(BaseModel):
    role: Literal["user", "assistant", "tool", "system"]
    content: str = ""
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None

class ThreadSummary(BaseModel):
    text: str
    covers_turns: int                        # how many history messages are folded into this summary
    updated_at: datetime

class State(BaseModel):
    history: list[ThreadMessage] = []        # single thread
    summary: ThreadSummary | None = None     # async-generated when history > K
    scratchpad: str = ""                     # Plan-1 §1 — agent-writable scratch
```

### 5.3 Schema deltas vs. `noble_agent_refactor`

| Field | Refactor | Unified |
|---|---|---|
| `Meta.active_agent` | `"MA" \| "CA" \| "SA"` | removed |
| `State.threads` | `dict[str, list[ThreadMessage]]` per agent | removed — replaced by flat `history` |
| `State.briefings` | `dict[str, Briefing]` per agent | removed |
| `State.summaries` | `dict[str, ThreadSummary]` per agent | replaced by single `State.summary` |
| `State.history` | (did not exist as flat list) | new — single thread |

### 5.4 History/summary lifecycle

1. Each turn: append user message, assistant message(s), and tool result message(s) into `state.history`.
2. After the user-facing turn completes (after `on_done` fires): compute `pending_count = len(history) - summary.covers_turns`.
3. If `pending_count > K` (default `K=8`, env `NOBLE_SUMMARY_K`): fire `asyncio.create_task(summarize_and_persist(...))`. The summarizer summarizes the head (`pending_count - K_KEEP_TAIL` messages), updates `state.summary.text` and `state.summary.covers_turns`, writes via `StateRepo` with optimistic concurrency.
4. Each subsequent turn rebuilds prompt with: system prompt (including summary if present) + `history[summary.covers_turns:]` tail.

`K_KEEP_TAIL` (default 4, env `NOBLE_SUMMARY_KEEP_TAIL`) is the number of recent messages always kept un-summarized so the LLM sees fresh, verbatim context.

### 5.5 Concurrency

The summary task runs concurrently with the next user turn. If the user sends a new turn before the summary task completes:

- The new turn loads state with the **old** `summary` (smaller `covers_turns`). It rebuilds prompt with more verbatim history. This is correct, just slightly more expensive.
- When the summary task finishes, it writes `summary` with optimistic concurrency — `StateRepo.update_summary` uses Redis `WATCH` on `session:{sid}:state` and retries once on conflict. If conflict happens twice in a row, the summary is dropped (it will be re-triggered on the next overflow check).
- History and customer mutations from the live turn are independent of summary writes — they touch different conceptual fields, and `StateRepo.save_all` writes the entire State object. Summary writes from the background task therefore go through a narrow `update_summary(sid, summary)` path that only touches the `summary` field, implemented as `WATCH state → read → modify summary → MULTI/EXEC`.

---

## 6. Tool set

The unified agent exposes 12 tools — the union of the consultant and support tools, minus `switch_agent`.

| Tool | Purpose |
|---|---|
| `update_customer` | Save any customer field that surfaces in conversation (name, phone, budget, project_interest, area, bedrooms, ...). Each field one call; multiple fields can be parallel. |
| `noble_search` | Knowledge-base search across amenities, location, legal status, materials, design, comparisons. Backend selected via `NOBLE_SEARCH_BACKEND`. |
| `list_projects` | List Noble projects by region. |
| `get_project_overview` | High-level info on one project. |
| `get_project_financial` | Pricing, payment plans, loan policies, promotions, fees. |
| `search_units` | Find specific units by criteria (bedrooms, price, direction, floor, tower, unit code). |
| `match_projects` | Suggest projects matching budget / region / bedrooms / purpose. |
| `booking` | 6-action tool for scheduling visits (`get_state`, `update_info`, `check_availability`, `schedule`, `list`, `modify`). |
| `crm_lookup` | Post-sale CRM lookup (contract, payments, certificate status, ticket history). |
| `verify_identity` | Verify customer with CCCD before disclosing private records. |
| `support_ticket` | Create or list customer-service tickets. |
| `escalate` | Transfer to a human specialist by department/priority. This is now the **only** "handoff" tool — it's not an agent switch, it's a real-world handoff. |
| `send_via_app` | Send brochure/image/map via the NobleX app when voice can't convey it. |

### 6.1 Tool reuse vs. unified-specific changes

- Implementation files (`tools/*.py`) are copied verbatim from `noble_agent_refactor/tools/`. They are pure functions over `(state, customer, args)`, so they don't depend on the multi-agent context.
- `tools/schemas.py`: drop the `switch_agent` schema. Touch up `escalate` description so the LLM knows it's the only handoff path (the refactor description still reads as if it complements `switch_agent`).
- `tools/dispatcher.py`: simpler than refactor — no need to detect `switch_agent` and raise `HandoffRequest`. The dispatcher's interface stays the same; only the special case disappears.

### 6.2 `noble_search` backend

The backend selection (`NOBLE_SEARCH_BACKEND`: `rag` | `grep` | `empty`) is preserved from refactor. `flat_store` (e5-large + BM25 hybrid) remains the default for `rag` mode. The deprecated stubs (`embeddings.py`, `faq_lookup.py`, `vector_store.py`) in legacy `agent/rag/` are **not** copied to unified.

---

## 7. Unified prompt

### 7.1 Persona

**Luna** — the same persona name used by MA and CA in the multi-agent system, now with an expanded role:

```
Bạn là Luna — chuyên viên Noble Real Estate. Em phụ trách toàn bộ cuộc gọi:
chào khách, tư vấn dự án và căn hộ, đặt lịch tham quan, hỗ trợ khách đã mua
(hợp đồng / thanh toán / sổ hồng / bảo hành), và chuyển khách sang chuyên
viên phụ trách khi cần.
```

This goes into `agent/definitions/SOUL.md`.

### 7.2 Five-section operational prompt

```
1. SOUL.md             — Identity (Luna là ai, vai trò bao trùm)
2. RULES.md            — Operational Protocol (12 numbered rules covering both mission + decision rules)
                       — Tool Catalog (intent → tool table)
                       — Style (Vietnamese, voice-friendly, no markdown)
                       — Guardrails (no AI disclosure, no out-of-domain answers, etc.)
3. CUSTOMER_PROFILE.md — Jinja template rendering customer state
4. PROMPT_TEMPLATE.md  — top-level composer
```

The original 6-section structure (Identity / Mission / Tools / Decision Protocol / Style / Guardrails) was collapsed to 5 because Mission and Decision Protocol overlapped — the Operational Protocol numbered list now does both jobs: it states what the agent is trying to accomplish on a call **and** the mandatory rules for doing so.

### 7.3 Operational Protocol (RULES.md, first subsection)

```
## Operational Protocol

Mỗi cuộc gọi vận hành theo các quy tắc sau, áp dụng theo thứ tự:

1. Nhận diện khách (nếu chưa có tên) → hỏi tên, lưu bằng update_customer
   trước khi đi sâu vào nội dung khác.

2. Phân loại nhu cầu sớm:
   - Pre-sale (tìm hiểu, mua, xem giá, đặt lịch tham quan) → đi vào nhóm tool
     dự án (list_projects / get_project_overview / get_project_financial /
     search_units / match_projects / noble_search / booking).
   - Post-sale (đã mua, hỏi hợp đồng / thanh toán / sổ hồng / bảo hành /
     thủ tục) → đi vào nhóm tool hỗ trợ (verify_identity → crm_lookup →
     support_ticket).

3. BẮT BUỘC gọi tool trước khi trả lời mọi câu cần dữ liệu thực (danh sách
   dự án, giá, vị trí, tiện ích, pháp lý, lịch, thông tin khách). KHÔNG suy
   đoán, KHÔNG bịa tên dự án / số liệu / khu vực. Đây là nguyên tắc số 1 —
   vi phạm = sai cuộc gọi.

4. Khách cung cấp thông tin cá nhân → update_customer NGAY trong cùng response
   (mỗi field một call, có thể parallel với tool khác). KHÔNG để dồn cuối
   cuộc gọi.

5. Parallel tool khi cần dữ liệu nhiều nguồn: ví dụ user vừa nêu tên vừa hỏi
   danh sách dự án → update_customer + list_projects cùng response.

6. Booking có state machine bắt buộc:
   - Đầu mỗi turn về booking: booking(action="get_state") trước tiên.
   - Mỗi field khách cung cấp (ngày / khung giờ): booking(action="update_info", ...).
   - Trước khi confirm: booking(action="check_availability", ...).
   - booking(action="schedule", confirmed=true) CHỈ khi state==CONFIRM và
     khách đã xác nhận lại bằng lời.

7. Khách Noble đã mua → verify_identity (CCCD) BẮT BUỘC trước khi cho xem
   hợp đồng / thanh toán / sổ hồng. Không có CCCD = không tra cứu.

8. Tool error / empty → nói rõ với khách + đề xuất bước tiếp (vd "Em chưa
   tìm thấy thông tin này, anh/chị có thể nói lại chi tiết hơn?"). KHÔNG
   bịa data thay thế.

9. Mã dự án canonical 4 chữ: NCLB / NCTH / NPLB / NTTL / SSLC. Khi gọi tool
   có project_code, dùng mã canonical — KHÔNG truyền tên đầy đủ.

10. Khi noble_search trả về có project_code rõ → coi như khách đã confirm
    interest dự án đó (system tự set customer.project_interest, không cần
    update_customer thủ công).

11. Khi vượt khả năng tự xử lý (khách yêu cầu gặp người thật, vấn đề pháp
    lý phức tạp, khiếu nại nghiêm trọng) → escalate(action="transfer",
    department=..., priority=...).

12. Voice không diễn đạt được (ảnh, bản đồ, bản vẽ, brochure) →
    send_via_app(query, project_code=[...]) SONG SONG với câu filler
    ("Dạ em gửi anh/chị qua app NobleX, chờ em chút nha").
```

### 7.4 Tool Catalog (RULES.md, second subsection)

```
## Tool catalog

| Khi user nói/hỏi | GỌI TOOL |
|---|---|
| Tên, SĐT, ngân sách, dự án, khu vực, số PN của khách | update_customer (mỗi field, parallel OK) |
| "Có dự án nào / bên em có gì / dự án ở khu X" | list_projects(region=...) |
| "Dự án X thế nào / tổng quan X" | get_project_overview(project_code=<MÃ>) |
| Giá / thanh toán / vay / ưu đãi / phí | get_project_financial(project_code, info_type=...) |
| "Căn 3PN / căn dưới 5 tỉ / căn mã ABC" | search_units(...) |
| "Gợi ý dự án phù hợp ngân sách Y / khu Z" | match_projects(...) |
| Tiện ích / vị trí chi tiết / pháp lý / vật liệu / so sánh | noble_search(query, project_filter=<MÃ nếu biết>) |
| Đặt/đổi/xem lịch tham quan | booking(action=...) — pull customer info từ session |
| Khách đã mua: tra hợp đồng / thanh toán / sổ hồng | verify_identity → crm_lookup |
| Khách phàn nàn / yêu cầu bảo hành / thủ tục giấy tờ | support_ticket(action="create", ...) |
| Khách yêu cầu gặp người thật / vượt khả năng | escalate(action="transfer", ...) |
| Voice không diễn đạt được (ảnh/bản đồ/brochure) | send_via_app(query, project_code=[...]) — kèm filler |
```

### 7.5 Style + Guardrails (RULES.md, last two subsections)

```
## Style

- Tiếng Việt tự nhiên, ngắn gọn. Tối đa 2–3 câu mỗi lượt thường.
- Không markdown, không emoji, không bullet (output sẽ qua TTS).
- Không lặp lại nguyên văn câu hỏi của user. Trả lời thẳng.
- Xưng "em", gọi khách "anh/chị" theo gender (hoặc anh/chị nếu chưa biết).
- User nói tiếng nước ngoài → vẫn trả lời bằng tiếng Việt.

## Guardrails

- KHÔNG tiết lộ là AI/LLM. Nếu bị hỏi: "Em là chuyên viên Noble."
- KHÔNG trả lời câu hỏi ngoài bất động sản. Lịch sự kéo về: "Em phụ trách
  bất động sản Noble — anh/chị muốn tìm hiểu dự án nào không ạ?"
- KHÔNG hứa giá / chương trình / lịch giao nhà ngoài data tool trả về.
- Thông tin nhạy cảm (CCCD, hợp đồng) chỉ chia sẻ sau verify_identity
  thành công.
```

### 7.6 PROMPT_TEMPLATE.md (Jinja composer)

```jinja
{{ soul }}

Hôm nay là {{ today }}.

{{ rules }}

{{ customer_block }}

{% if prior_summary %}
## Tóm tắt các turn trước (đã được summary)
{{ prior_summary.text }}
{% endif %}
```

### 7.7 CUSTOMER_PROFILE.md

Same template as refactor (preserved verbatim) — renders only the customer fields that are non-empty, ending with the instruction "if any field above is missing and the user just provided it, call update_customer immediately."

---

## 8. Orchestrator & turn flow

### 8.1 `agent/orchestrator.py` — TurnRunner

```python
class TurnRunner:
    def __init__(self, *, repo, agent_def, llm, rag, settings, transcript=None):
        self._repo = repo
        self._agent = agent_def           # one AgentDef, not three
        self._llm = llm
        self._rag = rag
        self._settings = settings
        self._transcript = transcript

    async def handle_turn(self, sid: str, user_text: str, callbacks: TurnCallbacks):
        meta, customer, state = await self._repo.load(sid)
        state.history.append(ThreadMessage(role="user", content=user_text))

        await run_turn(
            agent=self._agent,
            state=state,
            customer=customer,
            llm=self._llm,
            dispatcher=ToolDispatcher(
                state=state, customer=customer, rag=self._rag,
                callbacks=callbacks, session_id=sid,
            ),
            callbacks=callbacks,
        )

        meta.last_active = datetime.now(UTC)
        await self._repo.save_all(sid, meta, customer, state)

        pending = len(state.history) - (state.summary.covers_turns if state.summary else 0)
        if pending > self._settings.summary_threshold_K:
            asyncio.create_task(
                summarize_and_persist(
                    sid=sid, history=list(state.history),
                    prior_summary=state.summary, llm=self._llm,
                    repo=self._repo,
                    model=self._settings.summary_model,
                    keep_tail=self._settings.summary_keep_tail,
                )
            )

        if self._transcript is not None:
            await self._transcript.write_session_async(
                session_id=sid, customer=customer, state=state
            )
        await callbacks.on_done()
```

What's gone vs. refactor:

- `_run_with_handoffs`, `_apply_handoff` — no chain to run.
- `_try_cache_hit`, `_replay_cache_hit` — semcache deferred.
- `received: set[str]` — no per-agent threads to propagate the user turn into.
- `depth` parameter, `max_handoff_chain` setting — no chain.

### 8.2 `agent/runner.py` — run_turn

```python
MAX_TOOL_ITERATIONS = 5

async def run_turn(*, agent, state, customer, llm, dispatcher, callbacks):
    system = build_system_prompt(agent, customer, state.summary)
    messages = [{"role": "system", "content": system}]

    start = state.summary.covers_turns if state.summary else 0
    messages.extend(m.to_openai() for m in state.history[start:])

    for _ in range(MAX_TOOL_ITERATIONS):
        content, tool_calls = await llm.stream_completion(
            messages=messages,
            tools=agent.tool_schemas,
            model=agent.model,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            on_token=callbacks.on_token,
        )

        assistant_msg = ThreadMessage(role="assistant", content=content or "", tool_calls=tool_calls)
        state.history.append(assistant_msg)
        messages.append(assistant_msg.to_openai())

        if not tool_calls:
            return

        for tc in tool_calls:
            result = await dispatcher.dispatch(tc)
            tool_msg = ThreadMessage(
                role="tool", tool_call_id=tc["id"],
                name=tc["function"]["name"], content=result,
            )
            state.history.append(tool_msg)
            messages.append(tool_msg.to_openai())

        if dispatcher.consume_customer_dirty():
            messages[0] = {
                "role": "system",
                "content": build_system_prompt(agent, customer, state.summary),
            }

    logger.warning("runner: hit MAX_TOOL_ITERATIONS")
```

Differences from refactor `run_agent_turn`:

- No `switch_agent` detection or `HandoffRequest` return.
- No `resume_pending` (semcache deferred).
- `briefing` and `prior_summary` parameters collapse to a single `state.summary` passed through `build_system_prompt`.
- Single `messages` list, one thread.

### 8.3 `agent/summary/summarizer.py` — async summary

```python
async def summarize_and_persist(*, sid, history, prior_summary, llm, repo, model, keep_tail):
    covered = prior_summary.covers_turns if prior_summary else 0
    new_msgs = history[covered:]
    if len(new_msgs) <= keep_tail:
        return  # nothing to summarize beyond the tail

    to_summarize = new_msgs[:-keep_tail]
    prompt = build_summary_prompt(prior_summary, to_summarize)
    text = await llm.simple_completion(prompt, model=model, max_tokens=400)

    new_summary = ThreadSummary(
        text=text,
        covers_turns=covered + len(to_summarize),
        updated_at=datetime.now(UTC),
    )
    await repo.update_summary(sid, new_summary)
```

`build_summary_prompt` (helper) formats the previous summary + the to-summarize messages into a "rewrite the summary to incorporate these new turns, keep it under 200 words, focus on facts the agent will need: customer profile, requests made, tools called, decisions reached" prompt.

### 8.4 `agent/facade.py` — NobleAgent (drop-in shim)

```python
class NobleAgent:
    def __init__(self, session_id: str, runner: TurnRunner):
        self.session_id = session_id
        self._runner = runner
        self._current_agent: str = "unified"   # legacy attr — constant

    @classmethod
    async def create(cls, session_id: str, customer: dict | None = None) -> "NobleAgent":
        runner = await _get_runner()
        return cls(session_id=session_id, runner=runner)

    async def stream_response(
        self, user_text: str,
        on_token=None, on_tool_start=None, on_tool_done=None,
        interrupt_check=None, on_agent_switch=None,  # ignored
        **_legacy_ignored,
    ) -> str:
        sink: list[str] = []
        cb = _Callbacks(
            on_token=on_token, on_tool_start=on_tool_start,
            on_tool_done=on_tool_done,
            on_agent_switch=on_agent_switch,        # never fired
            interrupt_check=interrupt_check,
            sink=sink, owner=self,
        )
        await self._runner.handle_turn(self.session_id, user_text, cb)
        return "".join(sink)

    async def reset(self) -> None:
        ...   # delete 3 Redis keys, same as refactor.facade

    async def refresh_system_prompt(self) -> None:
        return None  # rebuilt every turn

    def set_interrupt_context(self, **_kwargs) -> None:
        return None  # not ported in phase 1
```

`on_agent_switch` is accepted but never invoked — kept in the signature so transport code can pass it without modification.

### 8.5 Turn flow

```
user_text from transport (text WS / voice)
  ↓
NobleAgent.stream_response(user_text, callbacks)
  ↓
TurnRunner.handle_turn
  ├─ repo.load(sid)                          ← 3 Redis keys
  ├─ state.history.append(user_msg)
  ├─ run_turn
  │   ├─ build_system_prompt (SOUL + RULES + customer + summary)
  │   ├─ LLM stream (1+ iterations)
  │   │   ├─ on_token callback (per chunk)
  │   │   ├─ dispatch tool_calls in batch
  │   │   ├─ on_tool_start / on_tool_done callbacks
  │   │   └─ rebuild prompt if customer_dirty
  │   └─ append assistant + tool messages
  ├─ repo.save_all(meta, customer, state)
  ├─ if history > K → asyncio.create_task(summarize_and_persist)
  ├─ transcript writer (if enabled)
  └─ callbacks.on_done()
```

---

## 9. Service layer migration

### 9.1 Principle

Copy 1-1 from `noble_agent/<module>/` into `noble_agent/<module>/`. The only edit is import-path rewriting (`noble_agent.xxx` → `noble_agent.xxx`). No behavior changes, no refactoring of service code. Bugs discovered during migration are noted but not fixed in this spec's scope.

### 9.2 Module-by-module

| Module | Action | Notes |
|---|---|---|
| `voice/stt/*` | Copy 1-1 | Lazy-import wiring at `server/session.py` updates to point at unified paths. |
| `voice/tts/*` | Copy 1-1 | TTS factory previously lived in legacy `noble_agent/agent/voice.py`. Unified moves the factory into `voice/voice_agent.py`. |
| `voice/vad/silero.py`, `voice/turn_detection/smart_turn.py`, `voice/audio/` | Copy 1-1 | No changes. |
| `voice/sentence_buffer.py` | Move from legacy `noble_agent/agent/sentence_buffer.py` | Logically belongs to voice, not agent. |
| `voice/voice_agent.py` | Move from legacy `noble_agent/agent/voice.py` (+ parts of `agent/app.py`) | Holds the voice loop driver. Calls into `agent.facade.NobleAgent` for the brain. |
| `telephony/` | Copy 1-1 | Provider abstractions unchanged. |
| `transport/` (incl. `livekit/`) | Copy 1-1 | Webhook/event handlers unchanged. |
| `services/crm_service.py`, `services/structured_data_service.py` | Copy 1-1 | Used by tools. |
| `storage/connection.py`, `storage/redis_client.py`, `storage/mongo_client.py` | Copy 1-1 | Connection helpers unchanged. |
| `storage/session_store.py` | Copy 1-1 | Legacy session writer for MongoDB conversation history collection — keep behavior. |
| `storage/models.py` | New (unified schema) | Single source for Meta/Customer/State/ThreadMessage/ThreadSummary. |
| `storage/repo.py` | New | Implements `StateRepo` (load 3 keys, save_all, update_summary with WATCH). |
| `metrics/` | Copy 1-1 | MongoDB `session_metrics` collection unchanged. |
| `server/http.py`, `server/base_session.py`, `server/outbound_endpoints.py`, `server/rate_limit.py`, `server/csv_export.py`, `server/logging_config.py`, `server/_websockets_post_patch.py` | Copy 1-1 | Import paths only. |
| `server/ws_handler.py` | Copy + minor edit | `/chat*` routes to `text_chat.handle_text_session`; other paths to voice `Session`. Same logic as legacy. |
| `server/session.py` | Copy + wire-up edit | Instantiates `NobleAgent` from unified facade instead of legacy `StreamingLLM`. |
| `server/text_chat.py` | Copy + wire-up edit | Same — uses unified `NobleAgent`. |

### 9.3 Files explicitly NOT migrated

- `noble_agent/agent/registry.py` — multi-agent registry, obsolete in unified.
- `noble_agent/agent/llm/streaming.py` (the old `StreamingLLM` class) — unified uses `agent/llm/client.py` from refactor + `NobleAgent` facade.
- `noble_agent/agent/tools/` (legacy tool implementations) — unified uses refactor tools.
- `noble_agent/agent/rag/embeddings.py`, `faq_lookup.py`, `vector_store.py` — deprecated stubs.
- `noble_agent/agent/prompts/` (legacy prompts directory) — unified has its own `agent/definitions/PROMPT_TEMPLATE.md`.
- `noble_agent/agent/summary/` — unified has new `agent/summary/summarizer.py` written from scratch (single-thread summary, not per-agent).
- `noble_agent/agent/support/` — its logic is collapsed into `tools/support_ops.py`.

### 9.4 Config consolidation

`noble_agent/config.py` defines a single `UnifiedSettings(BaseSettings)` class. It merges:

- Every field from legacy `noble_agent/config.py` (STT/TTS/LLM keys, Mongo/Redis URLs, voice params, metrics, telephony, transport).
- Agent-core fields from refactor (`summary_threshold_K`, `summary_model`, `session_ttl_seconds`, `transcript_log_enabled`, `transcript_log_dir`, `enable_slow_thinker`, `search_backend`).

Field names stay the same as their sources, so existing env vars work unchanged. New fields:

```python
use_unified_agent: bool = Field(False, alias="USE_UNIFIED_AGENT")
summary_keep_tail: int = Field(4, alias="NOBLE_SUMMARY_KEEP_TAIL")
```

Removed (no longer meaningful):

- `default_agent` (single agent now)
- `max_handoff_chain`, `auto_briefing_lookback`, `briefing_model`

Kept but disabled by default:

- All `semcache_*` settings. `semcache_enabled` defaults to `False`. The unified package does not wire a semcache manager in `agent/facade.py` for phase 1.

### 9.5 Storage schema migration

The unified state schema is incompatible with legacy/refactor:

- Legacy: a single Redis list of flat messages + a customer key.
- Refactor: 3 keys (`meta`, `customer`, `state`) with per-agent threads inside `state`.
- Unified: 3 keys with a flat `state.history` and single `state.summary`.

**Decision**: no read-side backward compatibility. Sessions started on legacy/refactor stay on those paths (`USE_UNIFIED_AGENT=false`). Sessions started while `USE_UNIFIED_AGENT=true` use the unified schema. Flipping the flag mid-session loses context — acceptable for dev.

A one-way migration script `scripts/migrate_session_to_unified.py` is **not** included in this spec.

### 9.6 CLI entry

`noble_agent/__main__.py`:

```python
def main():
    from noble_agent.config import get_settings
    if get_settings().use_unified_agent:
        from noble_agent.server.http import run_server
        run_server()
    else:
        from noble_agent.__main__ import main as legacy_main
        legacy_main()

if __name__ == "__main__":
    main()
```

`pyproject.toml`:

```toml
[project.scripts]
noble-agent = "noble_agent.__main__:main"
```

This makes the unified `__main__` the dispatch point. With the flag off, behavior is unchanged from today (legacy boots, and inside legacy `USE_REFACTOR_CORE` still decides legacy-vs-refactor). With the flag on, the unified server boots.

---

## 10. Feature flag & dev workflow

### 10.1 Flag

```bash
USE_UNIFIED_AGENT=false   # default
USE_UNIFIED_AGENT=true    # bật unified
```

### 10.2 Co-existence

Three independent code paths share the repo:

| Flag combination | Active code |
|---|---|
| `USE_UNIFIED_AGENT=true` | `noble_agent/*` |
| `USE_UNIFIED_AGENT=false` + `USE_REFACTOR_CORE=true` | `noble_agent/*` (transport) + `noble_agent_refactor/*` (agent core) |
| `USE_UNIFIED_AGENT=false` + `USE_REFACTOR_CORE=false` | `noble_agent/*` (full legacy) |

There is no shared code or shared state between unified and the other two paths.

### 10.3 Dev workflow

1. Implement `noble_agent/` per this spec.
2. Set `USE_UNIFIED_AGENT=true` in local `.env`.
3. `scripts/run.sh` boots the unified server.
4. Open `http://localhost:8766/chat` and exercise the agent via text chat. Watch the tool trace pane.
5. Smoke-test voice via the existing frontend voice client.
6. Manually evaluate conversation quality, tool calling accuracy, response style, latency.
7. To compare against refactor/legacy: set `USE_UNIFIED_AGENT=false`, restart.

### 10.4 Rollback

Set `USE_UNIFIED_AGENT=false`, restart. Active sessions on the unified path lose context (different state schema). Acceptable in dev.

### 10.5 Out of scope for this spec

- Staging canary, A/B metrics in production, structured success criteria.
- Cleanup of `noble_agent/` and `noble_agent_refactor/` after the user accepts unified.
- Production rollout sequence.

The user will evaluate unified manually in dev, decide separately whether to promote it, and the promotion will get its own spec.

---

## 11. Test strategy (development)

The goal is enough coverage for the user to trust that the unified code path works — not full production-grade coverage.

### 11.1 Unit tests (`tests/unit/unified/`)

- **`test_state_models.py`** — Meta / Customer / State pydantic schemas, serialize round-trip, default values.
- **`test_repo.py`** — `StateRepo.load`/`save_all` against 3 Redis keys, TTL is set, `update_summary` is atomic under simulated concurrent write.
- **`test_prompt_builder.py`** — `build_system_prompt` renders correctly from SOUL + RULES + customer + summary. Snapshot tests for three cases: empty customer / populated customer / customer + summary.
- **`test_runner.py`** — `run_turn` with a fake LLM:
  - LLM returns no tool_calls → assistant message appended, returns.
  - LLM returns tool_calls → dispatcher invoked, tool messages appended, LLM called again.
  - Customer dirty after tool → system prompt rebuilt for next iteration.
  - Max iterations reached → warning logged, returns gracefully.
- **`test_dispatcher.py`** — each tool dispatched against mock service layer. `customer_dirty` flag set when `noble_search` auto-sets `project_interest`.
- **`test_summarizer.py`** — async summarize with fake LLM. Only overflow head is summarized; the last `keep_tail` messages stay verbatim. Updates `covers_turns` correctly.
- **`test_facade.py`** — `NobleAgent.stream_response` bridges sync callbacks (`on_token`, `on_tool_start`, `on_tool_done`) to the async runner; legacy kwargs (`on_agent_switch`, `interrupt_check`) accepted but inert.

### 11.2 Integration tests (`tests/integration/unified/`)

- **`test_text_chat_e2e.py`** — WS `/chat` connect, send a single text message, assert token stream events and a final `done`. LLM provider is mocked.
- **`test_text_chat_tool_flow.py`** — Scenario: user says "Anh tên Hùng, cho em xin danh sách dự án" → expect parallel `update_customer(name="Hùng")` and `list_projects()` → assistant response references the mock projects.
- **`test_text_chat_booking_flow.py`** — Multi-turn booking happy path: user asks to book → `booking(get_state)` → user provides date → `booking(update_info)` → `booking(check_availability)` → user confirms → `booking(schedule, confirmed=true)`.
- **`test_session_resume.py`** — Two separate WS connections with the same `session=` parameter. The second turn's prompt includes history from the first.

### 11.3 Skipped in dev

- Voice end-to-end automated tests (audio fixtures are heavy). Use the frontend voice client manually.
- Telephony / outbound flow automated tests. Manual exercise when needed.
- Load tests, latency benchmarks. Deferred.

### 11.4 Test infrastructure

- `tests/unit/unified/conftest.py`:
  - `fake_llm` — produces predefined `(content, tool_calls)` tuples per call.
  - `fake_redis` — `fakeredis` async client.
  - `unified_runner` — `TurnRunner` wired with fake providers.
- Reuses `tests/conftest.py` shared fixtures where available.

### 11.5 Makefile

```makefile
test-unified:
	pytest tests/unit/unified tests/integration/unified -v
```

### 11.6 Manual smoke checklist (user-run)

- [ ] `scripts/run.sh` boots cleanly with `USE_UNIFIED_AGENT=true`.
- [ ] `/chat` page loads, sending a message produces a streaming response.
- [ ] Sending "Anh tên Hùng, muốn tìm hiểu Noble Crystal" shows `update_customer` and a project info tool in the trace pane.
- [ ] Reloading the tab with the same `?session=` URL preserves history.
- [ ] A voice call via the frontend voice client receives a spoken response (smoke only).
- [ ] Toggling `USE_UNIFIED_AGENT=false` still boots the server, and the legacy/refactor flow works.

---

## 12. Open questions / known risks

- **Tool overload**: with 12 tools always available, the LLM may pick the wrong tool more often than in the 3-agent system where each agent had a small toolset. Mitigation: the Tool Catalog table in the prompt is intent → tool, very explicit. Test in dev and adjust prompt language if mis-routing shows up.
- **Single thread length**: with one thread per session (no per-agent threads), long calls produce longer histories. Summary mitigates this, but `K_KEEP_TAIL` may need tuning if the agent forgets very recent context after summary fires. Default 4 is a guess; tune in dev.
- **`escalate` semantics**: in the multi-agent world, `switch_agent(target="SA")` was used for support handoffs. `escalate` is now both the post-sale support entry **and** the human transfer path. The prompt distinguishes these (rule 11 = human transfer), but the tool itself doesn't — its `department` enum decides. Worth watching for misuse.
- **Voice loop coupling**: moving `voice_agent.py` from `agent/` to `voice/` is a small refactor on legacy code. Risk of breakage if the legacy `voice.py` has hidden imports from `agent/`. To be checked during implementation.
- **`__main__.py` dispatch**: importing `noble_agent.__main__` from `noble_agent.__main__` couples the two packages. If `noble_agent` is later removed, `__main__` needs updating. Acceptable while both packages co-exist.

---

## 13. Acceptance for this spec

This spec is "done" when:

1. The user agrees on architecture (package layout, state schema, prompt structure, tool set, orchestrator design).
2. The user agrees on what's in vs. out of scope (this is a dev-only refactor; no production rollout in this spec).

Implementation of the spec happens through a separate implementation plan produced by `writing-plans`.
