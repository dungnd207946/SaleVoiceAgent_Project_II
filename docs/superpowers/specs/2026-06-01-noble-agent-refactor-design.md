# Noble Agent Core Refactor — Design Spec

**Date:** 2026-06-01
**Status:** Draft (post-brainstorm)
**Source requirement:** [docs/refactor/plan-1.md](../../refactor/plan-1.md)
**Target package:** `src/noble_agent_refactor/`
**Out of scope:** `server/`, `voice/`, `services/`, `metrics/`, transport, audio I/O (giữ nguyên).

## 1. Context

Codebase hiện tại (`src/noble_agent/agent/`) đang chạy ổn nhưng `llm/streaming.py` đã phình lên 1036 dòng với multi-agent switching, V5/V6/V7/V9/V10 RAG-inject patches xen kẽ tool loop, router LLM, và outbound flow. Logic "router phân loại lại từng message" gây mất context khi user trả lời tiếp nối trong cùng skill — đây là lỗi cốt lõi plan-1.md yêu cầu khắc phục.

Refactor này viết lại phần lõi multi-agent theo kiến trúc:

- **Shared session state** (một nguồn sự thật) lưu trong Redis với 3 key.
- **Active-agent stickiness** — định tuyến theo trạng thái, không theo message.
- **Structured handoff** — bỏ anti-pattern "fallback về Manager để hỏi hộ"; agent tự hỏi user.
- **Per-agent thread** với async summary khi handoff + thread dài.

Code mới chạy ở chế độ `general` (đã đơn giản hóa) và **bỏ outbound**. Transport layers (`text_chat.py`, voice pipeline) giữ nguyên qua một facade tương thích.

## 2. Goals

1. Loại bỏ hoàn toàn lỗi mất context khi user trả lời slot trong cùng skill.
2. Tách core thành các module nhỏ, có ranh giới rõ — file lõi không quá ~300 dòng.
3. Cho phép thêm/sửa prompt/rule/tool của từng agent qua `definitions/<agent>/` không cần đụng code.
4. Drop-in tương thích: `text_chat.py` và voice pipeline chỉ đổi 1 import (qua facade `NobleAgent`).
5. Giữ nguyên FastTalker (cache-aware noble_search) + SlowThinker (background prefetch).

## 3. Non-goals

- Không refactor `server/`, `voice/`, `services/`, `metrics/`, `storage/` cũ (vẫn dùng song song cho admin/list_sessions/booking persistence).
- Không thay vector store, không đụng FlatStore artifact.
- Không support outbound callback agent (tạm gác).
- Không inject FAQ tĩnh (V5) hoặc inject semantic FAQ tự động mỗi turn (V10) vào system prompt — RAG chỉ chạy khi LLM gọi `noble_search`.

## 4. Module layout

```
src/noble_agent_refactor/
├── __init__.py                # export NobleAgent facade
├── config.py                  # RefactorSettings (pydantic BaseSettings)
├── orchestrator.py            # TurnRunner — entry point xử lý 1 lượt user
│
├── storage/
│   ├── __init__.py
│   ├── models.py              # Pydantic models (SessionMeta, Customer, SessionState, ...)
│   └── repo.py                # StateRepo — 3-key Redis API + atomic patch_summary
│
├── agents/
│   ├── __init__.py
│   ├── base.py                # AgentDef dataclass
│   ├── registry.py            # load definitions/, dựng AgentDef instances
│   └── runner.py              # run_agent_turn — vòng lặp tool cho 1 agent
│
├── definitions/
│   ├── shared/
│   │   ├── RULES.md           # rule chung (an toàn, ngôn ngữ, format)
│   │   ├── HANDOFF.md         # quy tắc viết briefing khi switch_agent
│   │   └── CUSTOMER_PROFILE.md# template inject customer profile
│   ├── manager/
│   │   ├── SOUL.md            # cốt cách: tên, vai trò, văn phong
│   │   ├── RULES.md           # rule riêng MA (chitchat + khi nào switch)
│   │   ├── PROMPT_TEMPLATE.md # jinja template render system prompt
│   │   └── config.json        # {code, model, temperature, max_tokens, tools[]}
│   ├── consultant/
│   │   ├── SOUL.md
│   │   ├── RULES.md
│   │   ├── PROMPT_TEMPLATE.md
│   │   └── config.json
│   └── support/
│       ├── SOUL.md
│       ├── RULES.md
│       ├── PROMPT_TEMPLATE.md
│       └── config.json
│
├── prompts/
│   └── builder.py             # đọc definitions/, render template
│
├── llm/
│   └── client.py              # streaming client + provider fallback (gemini ↔ openai)
│
├── handoff/
│   ├── briefing.py            # auto_generate_briefing — fallback khi agent ko viết
│   └── summary.py             # summarize_and_persist — async task
│
├── tools/
│   ├── __init__.py
│   ├── schemas.py             # OpenAI tool schemas
│   ├── dispatcher.py          # ToolDispatcher
│   ├── switch_agent.py        # chỉ export schema (runner capture trực tiếp)
│   ├── update_customer.py
│   ├── noble_search.py        # V7 auto-set project_filter → customer.project_interest
│   └── booking.py             # copy từ noble_agent/agent/tools/booking.py
│
└── rag/
    └── adapter.py             # RagAdapter — wrap FastTalker + SlowThinker hiện có
```

## 5. Data model (`storage/models.py`)

```python
class SessionMeta(BaseModel):
    session_id: str
    started_at: datetime
    last_active: datetime
    phone: str | None = None
    active_agent: Literal["MA", "CA", "SA"]  # default lấy từ settings.default_agent

class Customer(BaseModel):
    name: str | None = None
    gender: str | None = None
    phone: str | None = None
    project_interest: str | None = None     # canonical 4-char code qua project_catalog
    budget: str | None = None
    preferred_area: str | None = None
    bedroom_count: str | None = None
    is_noble_customer: bool = False
    noble_info: dict | None = None
    full_name: str | None = None

class ThreadMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[dict] | None = None    # OpenAI tool_calls format khi role=assistant
    tool_call_id: str | None = None          # khi role=tool
    name: str | None = None                   # khi role=tool

    def to_openai(self) -> dict: ...

class Briefing(BaseModel):
    from_agent: str        # "CA"
    reason: str
    text: str              # nội dung — agent tự viết hoặc auto-gen
    created_at: datetime

class ThreadSummary(BaseModel):
    agent: str
    upto_message_count: int
    text: str
    created_at: datetime

class SessionState(BaseModel):
    threads: dict[str, list[ThreadMessage]] = Field(
        default_factory=lambda: {"MA": [], "CA": [], "SA": []}
    )
    briefings: dict[str, Briefing] = {}      # key = target agent code
    summaries: dict[str, ThreadSummary] = {} # key = agent code
    scratchpad: dict[str, str] = {}          # agent-private (hiếm dùng)
```

## 6. Storage (`storage/repo.py`)

### Redis key layout (giữ tương thích key cũ)

| Key | Nội dung |
|---|---|
| `session:{sid}:meta` | JSON `SessionMeta` |
| `session:{sid}:customer` | JSON `Customer` |
| `session:{sid}:state` | JSON `SessionState` |

TTL từ `settings.session_ttl_seconds` (kế thừa giá trị store cũ).

### API

```python
class StateRepo:
    def __init__(self, redis_client, default_agent: str, ttl: int):
        ...

    async def load(self, sid) -> tuple[SessionMeta, Customer, SessionState]:
        """Một Redis MGET → parse 3 key. Nếu meta thiếu, khởi tạo với default_agent."""

    async def save_all(self, sid, meta, customer, state) -> None:
        """Pipeline 3 SET cùng TTL."""

    async def save_meta(self, sid, meta) -> None: ...
    async def save_customer(self, sid, customer) -> None: ...
    async def save_state(self, sid, state) -> None: ...

    async def patch_summary(self, sid, agent_code: str, summary: ThreadSummary) -> None:
        """Read state → merge state.summaries[agent_code] = summary → write.
        Dùng cho async summary task, tránh đè field khác."""
```

Race: async summary task chạy song song với turn kế tiếp. `patch_summary` chỉ động vào `state.summaries[agent_code]`, đọc-merge-ghi. Acceptable risk — collision rất hiếm vì K threshold đảm bảo summary chỉ chạy sau handoff dài.

## 7. Orchestrator (`orchestrator.py`)

```python
class TurnRunner:
    def __init__(self, repo, registry, llm, rag, settings):
        self.repo = repo
        self.registry = registry
        self.llm = llm
        self.rag = rag
        self.settings = settings

    async def handle_turn(self, sid: str, user_text: str, callbacks: TurnCallbacks):
        meta, customer, state = await self.repo.load(sid)

        active = meta.active_agent  # luôn có nhờ default trong repo.load
        state.threads[active].append(ThreadMessage(role="user", content=user_text))

        # SlowThinker prefetch fire-and-forget
        if self.settings.enable_slow_thinker:
            asyncio.create_task(self.rag.prefetch(sid, user_text, customer))

        await self._run_with_handoffs(sid, active, meta, customer, state, callbacks, depth=0)

        meta.last_active = utcnow()
        await self.repo.save_all(sid, meta, customer, state)
        await callbacks.on_done()

    async def _run_with_handoffs(self, sid, agent_code, meta, customer, state, callbacks, depth):
        if depth > self.settings.max_handoff_chain:
            # Bảo hiểm: chain quá sâu → dừng, set active = agent hiện tại (đã nói rồi)
            meta.active_agent = agent_code
            return

        briefing = state.briefings.get(agent_code)
        prior_summary = state.summaries.get(agent_code)
        agent = self.registry.get(agent_code)

        dispatcher = ToolDispatcher(state=state, customer=customer, rag=self.rag, callbacks=callbacks)

        handoff = await run_agent_turn(
            agent=agent,
            thread=state.threads[agent_code],
            customer=customer,
            briefing=briefing,
            prior_summary=prior_summary,
            llm=self.llm,
            dispatcher=dispatcher,
            callbacks=callbacks,
        )

        if handoff is None:
            meta.active_agent = agent_code
            return

        # Auto-briefing fallback
        briefing_text = handoff.briefing
        if not briefing_text:
            briefing_text = await auto_generate_briefing(
                state.threads[agent_code], customer, handoff.reason, self.llm,
                lookback=self.settings.auto_briefing_lookback,
            )

        state.briefings[handoff.target] = Briefing(
            from_agent=agent_code,
            reason=handoff.reason,
            text=briefing_text,
            created_at=utcnow(),
        )

        # Async summary nếu thread đủ dài
        if len(state.threads[agent_code]) > self.settings.summary_threshold_K:
            snapshot = list(state.threads[agent_code])
            asyncio.create_task(
                summarize_and_persist(sid, agent_code, snapshot, self.llm, self.repo, self.settings)
            )

        await callbacks.on_agent_switch(from_=agent_code, to=handoff.target, reason=handoff.reason)

        meta.active_agent = handoff.target
        await self._run_with_handoffs(sid, handoff.target, meta, customer, state, callbacks, depth + 1)
```

### `TurnCallbacks` interface

Mirror tập callback `streaming.py` cũ để facade dễ map:

```python
class TurnCallbacks(Protocol):
    async def on_token(self, token: str) -> None: ...
    async def on_tool_start(self, name: str, args: dict) -> None: ...
    async def on_tool_done(self, name: str, result_summary: str) -> None: ...
    async def on_agent_switch(self, from_: str, to: str, reason: str) -> None: ...
    async def on_done(self) -> None: ...
```

## 8. Agent runner (`agents/runner.py`)

```python
@dataclass
class HandoffRequest:
    target: str
    reason: str
    briefing: str | None

async def run_agent_turn(
    *,
    agent: AgentDef,
    thread: list[ThreadMessage],
    customer: Customer,
    briefing: Briefing | None,
    prior_summary: ThreadSummary | None,
    llm,
    dispatcher: ToolDispatcher,
    callbacks: TurnCallbacks,
) -> HandoffRequest | None:

    system = build_system_prompt(agent, customer, briefing, prior_summary)
    messages = [{"role": "system", "content": system}, *[m.to_openai() for m in thread]]

    while True:
        content, tool_calls = await llm.stream_completion(
            messages=messages,
            tools=agent.tool_schemas,
            model=agent.model,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            on_token=callbacks.on_token,
        )

        assistant_msg = ThreadMessage(role="assistant", content=content, tool_calls=tool_calls)
        thread.append(assistant_msg)
        messages.append(assistant_msg.to_openai())

        if not tool_calls:
            return None  # agent nói xong, không handoff

        # Tách switch_agent ra trước — capture & exit
        for tc in tool_calls:
            if tc["function"]["name"] == "switch_agent":
                args = json.loads(tc["function"]["arguments"])
                # Synthetic tool result để thread consistent với OpenAI history
                thread.append(ThreadMessage(
                    role="tool", tool_call_id=tc["id"], name="switch_agent",
                    content='{"status":"handoff_initiated"}',
                ))
                return HandoffRequest(
                    target=args["target"],
                    reason=args.get("reason", ""),
                    briefing=args.get("briefing"),
                )

        # Dispatch các tool còn lại
        for tc in tool_calls:
            result = await dispatcher.dispatch(tc)
            tool_msg = ThreadMessage(
                role="tool", tool_call_id=tc["id"],
                name=tc["function"]["name"], content=result,
            )
            thread.append(tool_msg)
            messages.append(tool_msg.to_openai())

        # Nếu dispatcher bật cờ customer_dirty (V7 auto-set), rebuild system prompt
        if dispatcher.consume_customer_dirty():
            messages[0] = {"role": "system", "content": build_system_prompt(agent, customer, briefing, prior_summary)}
        # loop tiếp: gửi tool results lại LLM
```

## 9. Agent definitions (`definitions/<agent>/`)

### Files

- **`SOUL.md`** — 2-5 dòng. Tên, vai trò, văn phong. Inject vào đầu prompt.
- **`RULES.md`** — rule riêng agent. CA/SA RULES.md phải ghi rõ: "Thiếu thông tin → tự hỏi user, KHÔNG switch về MA chỉ để hỏi".
- **`PROMPT_TEMPLATE.md`** — jinja2 template với placeholder:
  - `{{soul}}` — nội dung SOUL.md
  - `{{shared_rules}}` — nội dung shared/RULES.md
  - `{{shared_handoff}}` — nội dung shared/HANDOFF.md
  - `{{rules}}` — nội dung RULES.md của agent
  - `{{customer_block}}` — render customer profile theo CUSTOMER_PROFILE.md
  - `{{briefing}}` — `{from_agent, reason, text}` (nếu có)
  - `{{prior_summary}}` — `{text, upto_message_count}` (nếu có)
- **`config.json`**:

```json
{
  "code": "CA",
  "name": "consultant",
  "model": "gemini-2.5-flash",
  "temperature": 0.7,
  "max_tokens": 800,
  "tools": ["switch_agent", "update_customer", "noble_search", "book_consultation"]
}
```

### Tool list per agent (mặc định)

| Agent | tools |
|---|---|
| MA | switch_agent, update_customer |
| CA | switch_agent, update_customer, noble_search, book_consultation |
| SA | switch_agent, update_customer, noble_search |

### `AgentDef` (`agents/base.py`)

```python
@dataclass(frozen=True)
class AgentDef:
    code: str                # "MA" / "CA" / "SA"
    name: str
    model: str
    temperature: float
    max_tokens: int
    prompt_template: jinja2.Template
    sections: dict[str, str] # {soul, rules, shared_rules, shared_handoff, customer_format}
    tool_names: list[str]
    tool_schemas: list[dict] # build từ schemas.SCHEMAS lọc theo tool_names
```

### Registry (`agents/registry.py`)

```python
class AgentRegistry:
    def __init__(self, definitions_dir: Path):
        self._agents: dict[str, AgentDef] = self._load_all(definitions_dir)

    def get(self, code: str) -> AgentDef: ...
    def list(self) -> list[AgentDef]: ...
```

Load 1 lần khi process start. Hot-reload không cần ở giai đoạn này.

## 10. Prompts (`prompts/builder.py`)

```python
def build_system_prompt(
    agent: AgentDef,
    customer: Customer,
    briefing: Briefing | None,
    prior_summary: ThreadSummary | None,
) -> str:
    customer_block = render_customer(agent.sections["customer_format"], customer)
    return agent.prompt_template.render(
        soul=agent.sections["soul"],
        shared_rules=agent.sections["shared_rules"],
        shared_handoff=agent.sections["shared_handoff"],
        rules=agent.sections["rules"],
        customer_block=customer_block,
        briefing=briefing.model_dump() if briefing else None,
        prior_summary=prior_summary.model_dump() if prior_summary else None,
    )
```

Pure function, không I/O. Test bằng snapshot.

## 11. Tools layer

### `tools/schemas.py`

```python
SCHEMAS: dict[str, dict] = {
    "switch_agent": {
        "type": "function",
        "function": {
            "name": "switch_agent",
            "description": "Bàn giao cuộc hội thoại sang agent khác khi gặp request ngoài phạm vi. KHÔNG dùng để 'nhờ MA hỏi user' — agent phải tự hỏi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["MA", "CA", "SA"]},
                    "reason": {"type": "string"},
                    "briefing": {"type": "string", "description": "Tóm tắt context để agent kế tiếp tiếp tục liền mạch. Tùy chọn — nếu bỏ trống hệ thống auto-gen."},
                },
                "required": ["target", "reason"],
            },
        },
    },
    "update_customer": { ... field enum của Customer, value: str ... },
    "noble_search": { ... query, project_filter: enum codes (optional) ... },
    "book_consultation": { ... time, project, contact_name, contact_phone ... },
}
```

### `tools/dispatcher.py`

```python
class ToolDispatcher:
    def __init__(self, state, customer, rag, callbacks):
        self.state = state
        self.customer = customer
        self.rag = rag
        self.callbacks = callbacks
        self._customer_dirty = False

    async def dispatch(self, tool_call) -> str:
        name = tool_call["function"]["name"]
        args = json.loads(tool_call["function"]["arguments"] or "{}")
        await self.callbacks.on_tool_start(name, args)

        if name == "update_customer":
            result = await update_customer.run(self.customer, args)
            self._customer_dirty = True
        elif name == "noble_search":
            result = await noble_search.run(self.rag, self, args)
        elif name == "book_consultation":
            result = await booking.run(self.customer, args)
        else:
            result = json.dumps({"error": f"unknown tool {name}"})

        await self.callbacks.on_tool_done(name, result)
        return result

    def mark_customer_dirty(self) -> None:
        self._customer_dirty = True

    def consume_customer_dirty(self) -> bool:
        v, self._customer_dirty = self._customer_dirty, False
        return v
```

### `tools/noble_search.py` — V7 auto-set

```python
async def run(rag, dispatcher: ToolDispatcher, args: dict) -> str:
    query = args["query"]
    raw_filter = args.get("project_filter")

    if raw_filter:
        canonical = project_catalog.normalize(raw_filter)
        if canonical and canonical != dispatcher.customer.project_interest:
            dispatcher.customer.project_interest = canonical
            dispatcher.mark_customer_dirty()
        project_for_search = canonical or raw_filter
    else:
        project_for_search = dispatcher.customer.project_interest

    return await rag.search(query=query, project_filter=project_for_search)
```

### `tools/switch_agent.py`

Chỉ export schema. Không có hàm dispatch — runner capture trước khi đến dispatcher.

### `tools/update_customer.py`, `tools/booking.py`

`update_customer` mutate `Customer` instance trong place (orchestrator save lại cuối turn). `booking` copy + thu gọn từ `noble_agent/agent/tools/booking.py`.

## 12. LLM client (`llm/client.py`)

```python
class StreamingClient:
    def __init__(self, providers: list[ProviderConfig]):
        self.providers = providers  # [{name: openai, base_url, api_key, ...}, ...]

    async def stream_completion(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
        model: str,
        temperature: float,
        max_tokens: int,
        on_token: Callable[[str], Awaitable[None]],
    ) -> tuple[str, list[dict] | None]:
        """Trả về (content_text, tool_calls). Stream token qua callback."""

    async def complete_once(self, *, messages, model, temperature, max_tokens) -> str:
        """Non-streaming, dùng cho auto-briefing + summary."""
```

Giữ logic provider fallback (gemini ↔ openai) + retry/backoff từ `streaming.py` cũ — chỉ tách ra file riêng.

## 13. Handoff helpers

### `handoff/briefing.py`

```python
async def auto_generate_briefing(
    thread: list[ThreadMessage],
    customer: Customer,
    reason: str,
    llm,
    lookback: int = 6,
) -> str:
    recent = thread[-lookback:]
    prompt = render_briefing_prompt(recent, customer, reason)
    return await llm.complete_once(
        messages=[{"role": "user", "content": prompt}],
        model=settings.briefing_model,  # default = settings.summary_model
        temperature=0.2,
        max_tokens=200,
    )
```

Prompt cố định: "Tóm tắt context cuộc hội thoại + slot khách đã cung cấp + việc đang dở, để agent kế tiếp tiếp nhận liền mạch. Tối đa 5 câu."

### `handoff/summary.py`

```python
async def summarize_and_persist(sid, agent_code, thread_snapshot, llm, repo, settings):
    prompt = render_summary_prompt(thread_snapshot, agent_code)
    text = await llm.complete_once(
        messages=[{"role": "user", "content": prompt}],
        model=settings.summary_model,
        temperature=0.2,
        max_tokens=400,
    )
    summary = ThreadSummary(
        agent=agent_code,
        upto_message_count=len(thread_snapshot),
        text=text,
        created_at=utcnow(),
    )
    await repo.patch_summary(sid, agent_code, summary)
```

## 14. RAG adapter (`rag/adapter.py`)

```python
class RagAdapter:
    def __init__(self, fast_talker, slow_thinker):
        self.fast = fast_talker
        self.slow = slow_thinker

    async def search(self, query: str, project_filter: str | None) -> str:
        return await self.fast.query(query=query, project_code=project_filter)

    async def prefetch(self, sid: str, user_text: str, customer: Customer):
        await self.slow.publish(sid=sid, utterance=user_text, customer=customer)
```

Bootstrap delegate cho `noble_agent.agent.rag.noble_kb` factory hiện có — không copy logic.

## 15. Config (`config.py`)

```python
class RefactorSettings(BaseSettings):
    default_agent: Literal["MA", "CA", "SA"] = "MA"   # NOBLE_DEFAULT_AGENT
    summary_threshold_K: int = 8                       # NOBLE_SUMMARY_K
    max_handoff_chain: int = 2                         # NOBLE_MAX_HANDOFF_CHAIN
    auto_briefing_lookback: int = 6                    # NOBLE_AUTO_BRIEFING_TURNS
    summary_model: str = "gpt-4o-mini"                 # NOBLE_SUMMARY_MODEL
    briefing_model: str | None = None                  # NOBLE_BRIEFING_MODEL (fallback summary_model)
    enable_slow_thinker: bool = True                   # NOBLE_ENABLE_SLOW_THINKER
    session_ttl_seconds: int = 86400                   # NOBLE_SESSION_TTL
    use_refactor_core: bool = False                    # USE_REFACTOR_CORE — facade switch

    class Config:
        env_file = ".env"
        env_prefix = ""
```

Per-agent model/temperature lấy từ `definitions/<agent>/config.json`. Có thể override qua env `NOBLE_AGENT_<CODE>_MODEL` nếu cần (giai đoạn 2).

## 16. Facade (`__init__.py`)

```python
class NobleAgent:
    """Drop-in thay thế StreamingLLM cho transport hiện tại."""

    @classmethod
    async def create(cls, session_id: str, customer: dict | None = None) -> "NobleAgent":
        # Build runner singleton (registry, llm, rag, repo) một lần process-wide
        # Wrap thành instance per session
        ...

    async def stream_response(
        self,
        user_text: str,
        *,
        on_token: Callable | None = None,
        on_tool_start: Callable | None = None,
        on_tool_done: Callable | None = None,
        on_agent_switch: Callable | None = None,
    ) -> str:
        # Wrap callbacks thành TurnCallbacks, gọi runner.handle_turn,
        # accumulate text, trả về full response string (giống streaming cũ).
```

`text_chat.py` và voice loop chỉ cần đổi:

```python
# trước
from noble_agent.agent.llm.streaming import StreamingLLM
llm = await StreamingLLM.create(session_id)

# sau (gated bằng USE_REFACTOR_CORE)
if settings.use_refactor_core:
    from noble_agent_refactor import NobleAgent
    llm = await NobleAgent.create(session_id)
else:
    from noble_agent.agent.llm.streaming import StreamingLLM
    llm = await StreamingLLM.create(session_id)
```

## 17. Mapping cũ → mới

| Code cũ | Thay bằng |
|---|---|
| `agent/llm/streaming.py` (1036 dòng) | `llm/client.py` (~250) + `agents/runner.py` (~150) + `orchestrator.py` (~200) |
| `agent/registry.py` (379 dòng) | `agents/registry.py` (~80) + `definitions/` markdown files |
| `agent/prompts/generator.py` | `prompts/builder.py` (~80, jinja-based) |
| `agent/tools/__init__.py` (33KB dispatcher) | `tools/dispatcher.py` (~80) + tool files riêng |
| `agent/tools/schemas.py` (24KB) | `tools/schemas.py` (chỉ giữ 4 tool) |
| `storage/session_store.py` (14KB) | `storage/repo.py` (~150) — chỉ 3 key, giữ tương thích |
| V5/V10 FAQ inject | **bỏ** |
| LLM router fast_route | **bỏ** (active-agent stickiness thay thế) |
| Outbound agent | **bỏ** |

## 18. Testing plan

| Layer | Test |
|---|---|
| `storage/repo.py` | Unit + integration với fakeredis. Load default khi key thiếu, save_all atomic, patch_summary merge đúng. |
| `prompts/builder.py` | Snapshot test cho 3 agent × {có/không briefing, có/không summary}. |
| `agents/runner.py` | Unit với fake LLM: vòng tool đơn, vòng tool có error, switch_agent capture, customer_dirty rebuild. |
| `orchestrator.py` | Integration với fake LLM + fake redis: cùng-turn handoff A→B, chain depth limit, async summary trigger. |
| `tools/noble_search.py` | V7 auto-set: project_filter normalize, customer_dirty bật, fallback dùng customer.project_interest khi LLM không truyền. |
| `handoff/briefing.py` + `summary.py` | Unit với fake LLM — prompt format ổn định. |
| Facade `NobleAgent` | Smoke test với `text_chat.py` test harness hiện tại. |

Mock LLM dùng pattern hiện có ở [tests/unit/test_text_chat.py](../../../tests/unit/test_text_chat.py).

## 19. Rollout

1. Land toàn bộ `src/noble_agent_refactor/` với feature flag `USE_REFACTOR_CORE=false` (mặc định).
2. Bật flag trong dev, chạy chat tester (`/chat`) song song với voice cũ.
3. So sánh metrics (latency, mất context rate) qua eval harness.
4. Bật flag cho voice khi đã yên tâm.
5. Sau 1 sprint stable → xóa `agent/llm/streaming.py` cũ + LLM router + outbound.

## 20. Open items (parking lot)

- Per-agent env override (`NOBLE_AGENT_CA_MODEL=...`) — giai đoạn 2 nếu cần.
- Hot-reload `definitions/` khi sửa file — không cần ngay.
- Briefing/summary có thể cache theo content hash để rerun không tốn LLM — phase 2.
- Migration `session:{sid}:state` schema cũ (chỉ có `history`, không có `threads`) → schema mới: thêm shim trong `StateRepo.load` mapping legacy `history` → `threads[default_agent]`.
