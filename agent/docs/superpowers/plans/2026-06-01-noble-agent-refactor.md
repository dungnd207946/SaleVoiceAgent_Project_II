# Noble Agent Core Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor noble agent core (multi-agent loop, prompts, tools, storage) thành `src/noble_agent_refactor/` theo spec [2026-06-01-noble-agent-refactor-design.md](../specs/2026-06-01-noble-agent-refactor-design.md), giữ transport/voice/services/metrics nguyên.

**Architecture:** Active-agent stickiness (state-based routing, no LLM router), 3-key Redis storage (meta/customer/state) với per-agent threads, structured handoff với async summary, definitions/ markdown files cho prompt + rule + config từng agent, drop-in facade `NobleAgent` thay thế `StreamingLLM`.

**Tech Stack:** Python 3.11+, pydantic v2, redis.asyncio, jinja2, OpenAI Chat Completions API (streaming + tools), pytest + fakeredis, ruff (line-length 120).

**Source spec:** `docs/superpowers/specs/2026-06-01-noble-agent-refactor-design.md`
**Reuses from existing code:** `noble_agent.agent.project_catalog`, `noble_agent.agent.rag.fast_talker.FastTalker`, `noble_agent.agent.rag.slow_thinker.SlowThinker`, `noble_agent.agent.rag.conversation_stream`, parts of `noble_agent.agent.tools.booking`.

---

## Task 1: Skeleton + config

**Files:**
- Create: `src/noble_agent_refactor/__init__.py`
- Create: `src/noble_agent_refactor/config.py`
- Create: `src/noble_agent_refactor/storage/__init__.py`
- Create: `src/noble_agent_refactor/agents/__init__.py`
- Create: `src/noble_agent_refactor/llm/__init__.py`
- Create: `src/noble_agent_refactor/tools/__init__.py`
- Create: `src/noble_agent_refactor/prompts/__init__.py`
- Create: `src/noble_agent_refactor/handoff/__init__.py`
- Create: `src/noble_agent_refactor/rag/__init__.py`
- Test: `tests/unit/refactor/test_config.py`

- [ ] **Step 1: Tạo các package __init__.py rỗng**

```bash
mkdir -p src/noble_agent_refactor/{storage,agents,llm,tools,prompts,handoff,rag,definitions/{shared,manager,consultant,support}}
mkdir -p tests/unit/refactor
touch src/noble_agent_refactor/{storage,agents,llm,tools,prompts,handoff,rag}/__init__.py
touch tests/unit/refactor/__init__.py
```

- [ ] **Step 2: Viết test cho RefactorSettings**

Create `tests/unit/refactor/test_config.py`:

```python
import os
import pytest


def test_default_values(monkeypatch):
    # Clear any pre-existing env so test sees defaults
    for key in [
        "NOBLE_DEFAULT_AGENT",
        "NOBLE_SUMMARY_K",
        "NOBLE_MAX_HANDOFF_CHAIN",
        "NOBLE_AUTO_BRIEFING_TURNS",
        "NOBLE_SUMMARY_MODEL",
        "NOBLE_BRIEFING_MODEL",
        "NOBLE_ENABLE_SLOW_THINKER",
        "NOBLE_SESSION_TTL",
        "USE_REFACTOR_CORE",
    ]:
        monkeypatch.delenv(key, raising=False)
    from noble_agent_refactor.config import RefactorSettings

    s = RefactorSettings()
    assert s.default_agent == "MA"
    assert s.summary_threshold_K == 8
    assert s.max_handoff_chain == 2
    assert s.auto_briefing_lookback == 6
    assert s.summary_model == "gpt-4o-mini"
    assert s.briefing_model is None
    assert s.enable_slow_thinker is True
    assert s.session_ttl_seconds == 86400
    assert s.use_refactor_core is False


def test_env_override(monkeypatch):
    monkeypatch.setenv("NOBLE_DEFAULT_AGENT", "CA")
    monkeypatch.setenv("NOBLE_SUMMARY_K", "12")
    monkeypatch.setenv("USE_REFACTOR_CORE", "true")
    from noble_agent_refactor.config import RefactorSettings

    s = RefactorSettings()
    assert s.default_agent == "CA"
    assert s.summary_threshold_K == 12
    assert s.use_refactor_core is True


def test_invalid_default_agent(monkeypatch):
    monkeypatch.setenv("NOBLE_DEFAULT_AGENT", "XX")
    from noble_agent_refactor.config import RefactorSettings

    with pytest.raises(ValueError):
        RefactorSettings()
```

- [ ] **Step 3: Run test — expect ImportError**

```bash
pytest tests/unit/refactor/test_config.py -v
```
Expected: ImportError / ModuleNotFoundError.

- [ ] **Step 4: Implement RefactorSettings**

Create `src/noble_agent_refactor/config.py`:

```python
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RefactorSettings(BaseSettings):
    """Settings cho noble_agent_refactor core. Đọc từ .env và environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    default_agent: Literal["MA", "CA", "SA"] = Field("MA", alias="NOBLE_DEFAULT_AGENT")
    summary_threshold_K: int = Field(8, alias="NOBLE_SUMMARY_K")
    max_handoff_chain: int = Field(2, alias="NOBLE_MAX_HANDOFF_CHAIN")
    auto_briefing_lookback: int = Field(6, alias="NOBLE_AUTO_BRIEFING_TURNS")
    summary_model: str = Field("gpt-4o-mini", alias="NOBLE_SUMMARY_MODEL")
    briefing_model: str | None = Field(None, alias="NOBLE_BRIEFING_MODEL")
    enable_slow_thinker: bool = Field(True, alias="NOBLE_ENABLE_SLOW_THINKER")
    session_ttl_seconds: int = Field(86400, alias="NOBLE_SESSION_TTL")
    use_refactor_core: bool = Field(False, alias="USE_REFACTOR_CORE")


_settings: RefactorSettings | None = None


def get_settings() -> RefactorSettings:
    global _settings
    if _settings is None:
        _settings = RefactorSettings()
    return _settings


def reset_settings_for_tests() -> None:
    """Test-only helper: clear cached settings."""
    global _settings
    _settings = None
```

Create `src/noble_agent_refactor/__init__.py`:

```python
"""Noble Agent core refactor (rev 2). See docs/superpowers/specs/2026-06-01-noble-agent-refactor-design.md."""

__all__ = ["get_settings"]

from noble_agent_refactor.config import get_settings
```

- [ ] **Step 5: Run test — expect pass**

The test imports `RefactorSettings` directly; cached `_settings` instance is not used here, so per-test monkeypatched env is read each time.

```bash
pytest tests/unit/refactor/test_config.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent_refactor tests/unit/refactor
git commit -m "feat(refactor): skeleton package + RefactorSettings"
```

---

## Task 2: Storage models

**Files:**
- Create: `src/noble_agent_refactor/storage/models.py`
- Test: `tests/unit/refactor/test_storage_models.py`

- [ ] **Step 1: Viết test cho models**

Create `tests/unit/refactor/test_storage_models.py`:

```python
from datetime import datetime, UTC

from noble_agent_refactor.storage.models import (
    SessionMeta,
    Customer,
    ThreadMessage,
    Briefing,
    ThreadSummary,
    SessionState,
)


def test_session_meta_defaults():
    m = SessionMeta(session_id="s1", started_at=datetime.now(UTC), last_active=datetime.now(UTC))
    assert m.active_agent == "MA"
    assert m.phone is None


def test_customer_defaults():
    c = Customer()
    assert c.name is None
    assert c.is_noble_customer is False
    assert c.noble_info is None


def test_thread_message_to_openai_user():
    m = ThreadMessage(role="user", content="hello")
    assert m.to_openai() == {"role": "user", "content": "hello"}


def test_thread_message_to_openai_assistant_with_tool_calls():
    tc = [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]
    m = ThreadMessage(role="assistant", content="", tool_calls=tc)
    assert m.to_openai() == {"role": "assistant", "content": "", "tool_calls": tc}


def test_thread_message_to_openai_tool():
    m = ThreadMessage(role="tool", tool_call_id="c1", name="x", content='{"ok":true}')
    assert m.to_openai() == {
        "role": "tool",
        "tool_call_id": "c1",
        "name": "x",
        "content": '{"ok":true}',
    }


def test_session_state_default_threads():
    s = SessionState()
    assert set(s.threads.keys()) == {"MA", "CA", "SA"}
    assert s.threads["MA"] == []
    assert s.briefings == {}
    assert s.summaries == {}


def test_session_state_roundtrip_json():
    s = SessionState()
    s.threads["CA"].append(ThreadMessage(role="user", content="hi"))
    s.briefings["SA"] = Briefing(
        from_agent="CA", reason="check docs", text="customer An...", created_at=datetime.now(UTC)
    )
    s.summaries["MA"] = ThreadSummary(
        agent="MA", upto_message_count=10, text="...", created_at=datetime.now(UTC)
    )
    blob = s.model_dump_json()
    restored = SessionState.model_validate_json(blob)
    assert restored.threads["CA"][0].content == "hi"
    assert restored.briefings["SA"].from_agent == "CA"
    assert restored.summaries["MA"].upto_message_count == 10
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest tests/unit/refactor/test_storage_models.py -v
```
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement models**

Create `src/noble_agent_refactor/storage/models.py`:

```python
"""Pydantic models lưu trong Redis cho noble_agent_refactor."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AgentCode = Literal["MA", "CA", "SA"]


class SessionMeta(BaseModel):
    session_id: str
    started_at: datetime
    last_active: datetime
    phone: str | None = None
    active_agent: AgentCode = "MA"


class Customer(BaseModel):
    name: str | None = None
    gender: str | None = None
    phone: str | None = None
    project_interest: str | None = None
    budget: str | None = None
    preferred_area: str | None = None
    bedroom_count: str | None = None
    is_noble_customer: bool = False
    noble_info: dict | None = None
    full_name: str | None = None


class ThreadMessage(BaseModel):
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai(self) -> dict:
        if self.role == "user":
            return {"role": "user", "content": self.content}
        if self.role == "assistant":
            d: dict = {"role": "assistant", "content": self.content}
            if self.tool_calls:
                d["tool_calls"] = self.tool_calls
            return d
        # tool
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "content": self.content,
        }


class Briefing(BaseModel):
    from_agent: str
    reason: str
    text: str
    created_at: datetime


class ThreadSummary(BaseModel):
    agent: str
    upto_message_count: int
    text: str
    created_at: datetime


def _default_threads() -> dict[str, list[ThreadMessage]]:
    return {"MA": [], "CA": [], "SA": []}


class SessionState(BaseModel):
    threads: dict[str, list[ThreadMessage]] = Field(default_factory=_default_threads)
    briefings: dict[str, Briefing] = Field(default_factory=dict)
    summaries: dict[str, ThreadSummary] = Field(default_factory=dict)
    scratchpad: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/unit/refactor/test_storage_models.py -v
```
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/storage/models.py tests/unit/refactor/test_storage_models.py
git commit -m "feat(refactor): pydantic storage models (SessionMeta/Customer/State)"
```

---

## Task 3: StateRepo with fakeredis

**Files:**
- Create: `src/noble_agent_refactor/storage/repo.py`
- Test: `tests/unit/refactor/test_storage_repo.py`
- Modify: `pyproject.toml` (add fakeredis dev dep if missing)

- [ ] **Step 1: Kiểm tra fakeredis trong pyproject.toml**

```bash
grep -E "fakeredis" pyproject.toml
```

Nếu chưa có, thêm vào dev extras (`[project.optional-dependencies] dev`):

```
"fakeredis>=2.20.0",
```

Cài: `pip install fakeredis`.

- [ ] **Step 2: Viết test cho StateRepo**

Create `tests/unit/refactor/test_storage_repo.py`:

```python
import json

import pytest
from fakeredis.aioredis import FakeRedis

from noble_agent_refactor.storage.models import (
    Briefing,
    Customer,
    SessionMeta,
    SessionState,
    ThreadMessage,
    ThreadSummary,
)
from noble_agent_refactor.storage.repo import StateRepo
from datetime import datetime, UTC


@pytest.fixture
async def repo():
    r = FakeRedis(decode_responses=False)
    return StateRepo(redis_client=r, default_agent="MA", ttl_seconds=3600)


async def test_load_returns_defaults_when_empty(repo):
    meta, customer, state = await repo.load("new_sid")
    assert meta.session_id == "new_sid"
    assert meta.active_agent == "MA"
    assert customer.name is None
    assert set(state.threads.keys()) == {"MA", "CA", "SA"}


async def test_default_agent_from_config(repo):
    repo._default_agent = "CA"
    meta, _, _ = await repo.load("sid2")
    assert meta.active_agent == "CA"


async def test_save_all_and_reload_roundtrip(repo):
    meta, customer, state = await repo.load("sid3")
    customer.name = "An"
    state.threads["CA"].append(ThreadMessage(role="user", content="3 tỉ"))
    await repo.save_all("sid3", meta, customer, state)

    meta2, customer2, state2 = await repo.load("sid3")
    assert customer2.name == "An"
    assert state2.threads["CA"][0].content == "3 tỉ"


async def test_save_all_writes_ttl(repo):
    meta, customer, state = await repo.load("sid4")
    await repo.save_all("sid4", meta, customer, state)
    ttl = await repo._redis.ttl("session:sid4:meta")
    assert 3590 < ttl <= 3600


async def test_patch_summary_does_not_overwrite_threads(repo):
    meta, customer, state = await repo.load("sid5")
    state.threads["CA"].append(ThreadMessage(role="user", content="hi"))
    await repo.save_all("sid5", meta, customer, state)

    # Concurrent: another writer appends a new message
    _, _, state_b = await repo.load("sid5")
    state_b.threads["CA"].append(ThreadMessage(role="assistant", content="hello"))
    await repo.save_state("sid5", state_b)

    # patch_summary should only touch summaries
    summary = ThreadSummary(
        agent="CA", upto_message_count=2, text="user hỏi giá", created_at=datetime.now(UTC)
    )
    await repo.patch_summary("sid5", "CA", summary)

    _, _, state_after = await repo.load("sid5")
    assert len(state_after.threads["CA"]) == 2          # not lost
    assert state_after.summaries["CA"].text == "user hỏi giá"


async def test_load_handles_corrupt_json(repo):
    await repo._redis.set("session:bad:meta", b"not json")
    meta, _, _ = await repo.load("bad")
    # Falls back to defaults instead of crashing
    assert meta.session_id == "bad"
    assert meta.active_agent == "MA"
```

- [ ] **Step 3: Run test — expect ImportError**

```bash
pytest tests/unit/refactor/test_storage_repo.py -v
```
Expected: ImportError.

- [ ] **Step 4: Implement StateRepo**

Create `src/noble_agent_refactor/storage/repo.py`:

```python
"""3-key Redis state repository cho noble_agent_refactor."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Protocol

from noble_agent_refactor.storage.models import (
    AgentCode,
    Customer,
    SessionMeta,
    SessionState,
    ThreadSummary,
)

logger = logging.getLogger("noble_agent_refactor.repo")


class _RedisAsync(Protocol):
    async def get(self, key: str): ...
    async def set(self, key: str, value, ex: int | None = None): ...
    async def mget(self, keys: list[str]): ...
    async def ttl(self, key: str): ...
    def pipeline(self): ...


def _meta_key(sid: str) -> str:
    return f"session:{sid}:meta"


def _customer_key(sid: str) -> str:
    return f"session:{sid}:customer"


def _state_key(sid: str) -> str:
    return f"session:{sid}:state"


def _safe_loads(raw) -> dict | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("repo: corrupt JSON, falling back to default: %s", e)
        return None


class StateRepo:
    def __init__(self, redis_client: _RedisAsync, default_agent: AgentCode, ttl_seconds: int):
        self._redis = redis_client
        self._default_agent: AgentCode = default_agent
        self._ttl = ttl_seconds

    async def load(self, sid: str) -> tuple[SessionMeta, Customer, SessionState]:
        keys = [_meta_key(sid), _customer_key(sid), _state_key(sid)]
        raw_values = await self._redis.mget(keys)

        meta_d = _safe_loads(raw_values[0])
        customer_d = _safe_loads(raw_values[1])
        state_d = _safe_loads(raw_values[2])

        if meta_d:
            try:
                meta = SessionMeta.model_validate(meta_d)
            except Exception as e:
                logger.warning("repo: meta validation failed (%s), using default", e)
                meta = self._default_meta(sid)
        else:
            meta = self._default_meta(sid)

        customer = Customer.model_validate(customer_d) if customer_d else Customer()
        state = SessionState.model_validate(state_d) if state_d else SessionState()

        return meta, customer, state

    def _default_meta(self, sid: str) -> SessionMeta:
        now = datetime.now(UTC)
        return SessionMeta(
            session_id=sid,
            started_at=now,
            last_active=now,
            active_agent=self._default_agent,
        )

    async def save_meta(self, sid: str, meta: SessionMeta) -> None:
        await self._redis.set(_meta_key(sid), meta.model_dump_json(), ex=self._ttl)

    async def save_customer(self, sid: str, customer: Customer) -> None:
        await self._redis.set(_customer_key(sid), customer.model_dump_json(), ex=self._ttl)

    async def save_state(self, sid: str, state: SessionState) -> None:
        await self._redis.set(_state_key(sid), state.model_dump_json(), ex=self._ttl)

    async def save_all(
        self, sid: str, meta: SessionMeta, customer: Customer, state: SessionState
    ) -> None:
        pipe = self._redis.pipeline()
        pipe.set(_meta_key(sid), meta.model_dump_json(), ex=self._ttl)
        pipe.set(_customer_key(sid), customer.model_dump_json(), ex=self._ttl)
        pipe.set(_state_key(sid), state.model_dump_json(), ex=self._ttl)
        await pipe.execute()

    async def patch_summary(self, sid: str, agent_code: str, summary: ThreadSummary) -> None:
        """Read-modify-write chỉ trường summaries[agent_code]."""
        raw = await self._redis.get(_state_key(sid))
        state_d = _safe_loads(raw) or {}
        try:
            state = SessionState.model_validate(state_d) if state_d else SessionState()
        except Exception as e:
            logger.warning("repo.patch_summary: invalid state, rebuilding: %s", e)
            state = SessionState()
        state.summaries[agent_code] = summary
        await self._redis.set(_state_key(sid), state.model_dump_json(), ex=self._ttl)
```

- [ ] **Step 5: Run test — expect pass**

```bash
pytest tests/unit/refactor/test_storage_repo.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent_refactor/storage/repo.py tests/unit/refactor/test_storage_repo.py pyproject.toml
git commit -m "feat(refactor): StateRepo with 3-key Redis layout + patch_summary"
```

---

## Task 4: Tool schemas

**Files:**
- Create: `src/noble_agent_refactor/tools/schemas.py`
- Test: `tests/unit/refactor/test_tool_schemas.py`

- [ ] **Step 1: Viết test schemas**

Create `tests/unit/refactor/test_tool_schemas.py`:

```python
from noble_agent_refactor.tools.schemas import SCHEMAS, schemas_for


def test_all_four_tools_present():
    assert set(SCHEMAS.keys()) == {
        "switch_agent",
        "update_customer",
        "noble_search",
        "book_consultation",
    }


def test_switch_agent_schema_shape():
    sch = SCHEMAS["switch_agent"]
    assert sch["type"] == "function"
    fn = sch["function"]
    assert fn["name"] == "switch_agent"
    params = fn["parameters"]
    assert "target" in params["properties"]
    assert params["properties"]["target"]["enum"] == ["MA", "CA", "SA"]
    assert "reason" in params["required"]
    assert "briefing" not in params["required"]  # optional


def test_update_customer_field_enum():
    fn = SCHEMAS["update_customer"]["function"]
    field = fn["parameters"]["properties"]["field"]
    # Must enumerate Customer fields exactly
    assert set(field["enum"]) == {
        "name",
        "gender",
        "phone",
        "project_interest",
        "budget",
        "preferred_area",
        "bedroom_count",
        "full_name",
    }


def test_schemas_for_filters_by_name():
    out = schemas_for(["switch_agent", "noble_search"])
    names = [s["function"]["name"] for s in out]
    assert names == ["switch_agent", "noble_search"]


def test_schemas_for_unknown_raises():
    import pytest

    with pytest.raises(KeyError):
        schemas_for(["nope"])
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
pytest tests/unit/refactor/test_tool_schemas.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement schemas**

Create `src/noble_agent_refactor/tools/schemas.py`:

```python
"""OpenAI tool schemas cho refactor agents."""
from __future__ import annotations

CUSTOMER_FIELDS = [
    "name",
    "gender",
    "phone",
    "project_interest",
    "budget",
    "preferred_area",
    "bedroom_count",
    "full_name",
]

SCHEMAS: dict[str, dict] = {
    "switch_agent": {
        "type": "function",
        "function": {
            "name": "switch_agent",
            "description": (
                "Bàn giao cuộc hội thoại sang agent khác khi request ngoài phạm vi của agent hiện tại. "
                "KHÔNG dùng để 'nhờ Manager hỏi thông tin user' — agent phải tự hỏi user."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "enum": ["MA", "CA", "SA"]},
                    "reason": {"type": "string", "description": "Lý do bàn giao."},
                    "briefing": {
                        "type": "string",
                        "description": (
                            "Tóm tắt context để agent kế tiếp tiếp tục liền mạch. "
                            "Tùy chọn — nếu bỏ trống hệ thống auto-generate."
                        ),
                    },
                },
                "required": ["target", "reason"],
            },
        },
    },
    "update_customer": {
        "type": "function",
        "function": {
            "name": "update_customer",
            "description": "Cập nhật một trường thông tin khách hàng vào shared state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "field": {"type": "string", "enum": CUSTOMER_FIELDS},
                    "value": {"type": "string"},
                },
                "required": ["field", "value"],
            },
        },
    },
    "noble_search": {
        "type": "function",
        "function": {
            "name": "noble_search",
            "description": (
                "Tra cứu knowledge base Noble (giá, tiện ích, pháp lý...) theo query tự nhiên. "
                "Truyền project_filter là mã canonical (NCLB/NCTH/NPLB/NTTL/SSLC) nếu biết."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "project_filter": {
                        "type": "string",
                        "enum": ["NCLB", "NCTH", "NPLB", "NTTL", "SSLC"],
                    },
                },
                "required": ["query"],
            },
        },
    },
    "book_consultation": {
        "type": "function",
        "function": {
            "name": "book_consultation",
            "description": "Đặt lịch tham quan dự án với khách. Phải xác nhận thông tin trước.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "phone": {"type": "string"},
                    "project": {"type": "string"},
                    "preferred_date": {"type": "string", "description": "DD/MM/YYYY"},
                    "preferred_time": {"type": "string", "description": "HH:MM"},
                    "notes": {"type": "string"},
                },
                "required": ["customer_name", "phone", "project", "preferred_date", "preferred_time"],
            },
        },
    },
}


def schemas_for(names: list[str]) -> list[dict]:
    """Trả về schemas đã filter theo danh sách tên (giữ thứ tự)."""
    return [SCHEMAS[name] for name in names]
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/unit/refactor/test_tool_schemas.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/tools/schemas.py tests/unit/refactor/test_tool_schemas.py
git commit -m "feat(refactor): tool schemas (switch_agent, update_customer, noble_search, book_consultation)"
```

---

## Task 5: Tool — update_customer

**Files:**
- Create: `src/noble_agent_refactor/tools/update_customer.py`
- Test: `tests/unit/refactor/test_tool_update_customer.py`

- [ ] **Step 1: Viết test**

Create `tests/unit/refactor/test_tool_update_customer.py`:

```python
import json

import pytest

from noble_agent_refactor.storage.models import Customer
from noble_agent_refactor.tools import update_customer as tool


async def test_updates_simple_field():
    c = Customer()
    out = await tool.run(c, {"field": "name", "value": "An"})
    data = json.loads(out)
    assert data["ok"] is True
    assert c.name == "An"


async def test_normalizes_project_interest():
    c = Customer()
    out = await tool.run(c, {"field": "project_interest", "value": "Noble Crystal Long Biên"})
    data = json.loads(out)
    assert data["ok"] is True
    assert c.project_interest == "NCLB"


async def test_rejects_unknown_field():
    c = Customer()
    out = await tool.run(c, {"field": "favorite_color", "value": "blue"})
    data = json.loads(out)
    assert data["ok"] is False
    assert "field" in data["error"].lower()


async def test_phone_passthrough():
    c = Customer()
    out = await tool.run(c, {"field": "phone", "value": "0901234567"})
    data = json.loads(out)
    assert data["ok"] is True
    assert c.phone == "0901234567"


async def test_unknown_project_keeps_raw():
    c = Customer()
    out = await tool.run(c, {"field": "project_interest", "value": "UNKNOWN_X"})
    data = json.loads(out)
    # Refuse to set unknown project — keep None and signal warn
    assert c.project_interest is None
    assert data["ok"] is False
```

- [ ] **Step 2: Run test — expect ModuleNotFoundError**

```bash
pytest tests/unit/refactor/test_tool_update_customer.py -v
```

- [ ] **Step 3: Implement**

Create `src/noble_agent_refactor/tools/update_customer.py`:

```python
"""Tool: update one field on the shared Customer object."""
from __future__ import annotations

import json
import logging

from noble_agent_refactor.tools.schemas import CUSTOMER_FIELDS

logger = logging.getLogger("noble_agent_refactor.tools.update_customer")


async def run(customer, args: dict) -> str:
    field = args.get("field", "")
    value = args.get("value", "")

    if field not in CUSTOMER_FIELDS:
        return json.dumps({"ok": False, "error": f"Unknown field '{field}'"})

    if field == "project_interest":
        from noble_agent.agent import project_catalog as catalog

        canonical = catalog.normalize(value)
        if not canonical:
            return json.dumps({"ok": False, "error": f"Unknown project '{value}'"})
        customer.project_interest = canonical
        return json.dumps({"ok": True, "field": field, "value": canonical})

    setattr(customer, field, value)
    return json.dumps({"ok": True, "field": field, "value": value})
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/unit/refactor/test_tool_update_customer.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/tools/update_customer.py tests/unit/refactor/test_tool_update_customer.py
git commit -m "feat(refactor): update_customer tool with project_interest normalize"
```

---

## Task 6: Tool — noble_search (V7 auto-set)

**Files:**
- Create: `src/noble_agent_refactor/tools/noble_search.py`
- Test: `tests/unit/refactor/test_tool_noble_search.py`

- [ ] **Step 1: Viết test với fake RAG + dispatcher**

Create `tests/unit/refactor/test_tool_noble_search.py`:

```python
from dataclasses import dataclass, field

import pytest

from noble_agent_refactor.storage.models import Customer
from noble_agent_refactor.tools import noble_search


class FakeRag:
    def __init__(self):
        self.calls = []

    async def search(self, query: str, project_filter):
        self.calls.append((query, project_filter))
        return f"hits for {query}/{project_filter}"


@dataclass
class FakeDispatcher:
    customer: Customer
    dirty: bool = False

    def mark_customer_dirty(self):
        self.dirty = True


async def test_uses_customer_filter_when_arg_missing():
    c = Customer(project_interest="NCLB")
    d = FakeDispatcher(customer=c)
    rag = FakeRag()
    out = await noble_search.run(rag, d, {"query": "giá"})
    assert rag.calls == [("giá", "NCLB")]
    assert d.dirty is False
    assert "hits for" in out


async def test_auto_sets_project_interest_when_arg_normalizes():
    c = Customer(project_interest=None)
    d = FakeDispatcher(customer=c)
    rag = FakeRag()
    out = await noble_search.run(
        rag, d, {"query": "tiện ích", "project_filter": "Noble Crystal Long Biên"}
    )
    assert c.project_interest == "NCLB"
    assert d.dirty is True
    assert rag.calls == [("tiện ích", "NCLB")]


async def test_does_not_dirty_when_already_canonical():
    c = Customer(project_interest="NCLB")
    d = FakeDispatcher(customer=c)
    rag = FakeRag()
    await noble_search.run(rag, d, {"query": "giá", "project_filter": "NCLB"})
    assert d.dirty is False


async def test_unknown_project_filter_falls_back_to_raw():
    c = Customer()
    d = FakeDispatcher(customer=c)
    rag = FakeRag()
    await noble_search.run(rag, d, {"query": "giá", "project_filter": "ZZZZ"})
    # No canonical → customer unchanged, search still runs with raw filter
    assert c.project_interest is None
    assert d.dirty is False
    assert rag.calls == [("giá", "ZZZZ")]
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_tool_noble_search.py -v
```

- [ ] **Step 3: Implement**

Create `src/noble_agent_refactor/tools/noble_search.py`:

```python
"""Tool: noble_search with V7 auto-set of customer.project_interest."""
from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("noble_agent_refactor.tools.noble_search")


class _DispatcherCtx(Protocol):
    customer: object
    def mark_customer_dirty(self) -> None: ...


async def run(rag, dispatcher: _DispatcherCtx, args: dict) -> str:
    query = args.get("query", "")
    raw_filter = args.get("project_filter") or None

    project_for_search: str | None = None
    if raw_filter:
        from noble_agent.agent import project_catalog as catalog

        canonical = catalog.normalize(raw_filter)
        if canonical and canonical != getattr(dispatcher.customer, "project_interest", None):
            dispatcher.customer.project_interest = canonical
            dispatcher.mark_customer_dirty()
        project_for_search = canonical or raw_filter
    else:
        project_for_search = getattr(dispatcher.customer, "project_interest", None)

    result = await rag.search(query=query, project_filter=project_for_search)
    return result if isinstance(result, str) else str(result)
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_tool_noble_search.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/tools/noble_search.py tests/unit/refactor/test_tool_noble_search.py
git commit -m "feat(refactor): noble_search tool with V7 project_filter auto-set"
```

---

## Task 7: Tool — book_consultation (wrap legacy)

**Files:**
- Create: `src/noble_agent_refactor/tools/booking.py`
- Test: `tests/unit/refactor/test_tool_booking.py`

- [ ] **Step 1: Viết test**

Create `tests/unit/refactor/test_tool_booking.py`:

```python
import json
from datetime import date, timedelta
from unittest.mock import patch, AsyncMock

import pytest

from noble_agent_refactor.storage.models import Customer
from noble_agent_refactor.tools import booking


async def test_validates_phone_format():
    c = Customer()
    args = {
        "customer_name": "An",
        "phone": "abc",
        "project": "NCLB",
        "preferred_date": (date.today() + timedelta(days=2)).strftime("%d/%m/%Y"),
        "preferred_time": "10:00",
    }
    out = await booking.run(c, args, session_id="s1")
    data = json.loads(out)
    assert data["ok"] is False
    assert any("điện thoại" in e.lower() or "phone" in e.lower() for e in data["errors"])


async def test_delegates_to_schedule_viewing_on_valid_args():
    c = Customer()
    args = {
        "customer_name": "An",
        "phone": "0901234567",
        "project": "Noble Crystal Long Biên",
        "preferred_date": (date.today() + timedelta(days=2)).strftime("%d/%m/%Y"),
        "preferred_time": "10:00",
        "notes": "khách quan tâm 2PN",
    }
    with patch(
        "noble_agent.agent.tools.booking.schedule_viewing",
        new=AsyncMock(return_value={"ok": True, "booking_id": "B123"}),
    ) as mocked:
        out = await booking.run(c, args, session_id="s1")
    data = json.loads(out)
    assert data["ok"] is True
    assert data["booking_id"] == "B123"
    mocked.assert_awaited_once()
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_tool_booking.py -v
```

- [ ] **Step 3: Implement (thin wrapper)**

Create `src/noble_agent_refactor/tools/booking.py`:

```python
"""Tool: book_consultation — delegates to legacy schedule_viewing."""
from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime

logger = logging.getLogger("noble_agent_refactor.tools.booking")


async def run(customer, args: dict, session_id: str) -> str:
    from noble_agent.agent.tools import booking as legacy

    name = args.get("customer_name") or customer.full_name or customer.name or ""
    phone = args.get("phone") or customer.phone or ""
    project = args.get("project") or customer.project_interest or ""
    preferred_date = args.get("preferred_date", "")
    preferred_time = args.get("preferred_time", "")
    notes = args.get("notes", "")

    # Run legacy schedule_viewing — handles validation + persistence
    result = await legacy.schedule_viewing(
        session_id=session_id,
        customer_name=name,
        phone=phone,
        project=project,
        preferred_date=preferred_date,
        preferred_time=preferred_time,
        confirmed=True,
        notes=notes,
    )

    if not isinstance(result, dict):
        return json.dumps({"ok": False, "error": "legacy schedule_viewing returned non-dict"})

    return json.dumps(result, ensure_ascii=False, default=str)
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_tool_booking.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/tools/booking.py tests/unit/refactor/test_tool_booking.py
git commit -m "feat(refactor): book_consultation thin wrapper over legacy schedule_viewing"
```

---

## Task 8: switch_agent placeholder + dispatcher

**Files:**
- Create: `src/noble_agent_refactor/tools/switch_agent.py`
- Create: `src/noble_agent_refactor/tools/dispatcher.py`
- Test: `tests/unit/refactor/test_tool_dispatcher.py`

- [ ] **Step 1: Tạo placeholder switch_agent.py**

Create `src/noble_agent_refactor/tools/switch_agent.py`:

```python
"""switch_agent tool — schema in tools/schemas.py.

Handoff requests are captured directly in agents/runner.py (not via dispatcher),
so no dispatch function lives here. File exists so module path is stable.
"""
TOOL_NAME = "switch_agent"
```

- [ ] **Step 2: Viết test dispatcher**

Create `tests/unit/refactor/test_tool_dispatcher.py`:

```python
import json
from dataclasses import dataclass, field

import pytest

from noble_agent_refactor.storage.models import Customer, SessionState
from noble_agent_refactor.tools.dispatcher import ToolDispatcher


class FakeRag:
    async def search(self, query, project_filter):
        return f"rag:{query}:{project_filter}"


class FakeCallbacks:
    def __init__(self):
        self.events = []

    async def on_tool_start(self, name, args):
        self.events.append(("start", name, args))

    async def on_tool_done(self, name, result):
        self.events.append(("done", name, result))

    async def on_token(self, token): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


def _call(name: str, args: dict, tc_id: str = "tc1") -> dict:
    return {
        "id": tc_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


async def test_dispatch_update_customer_marks_dirty():
    c = Customer()
    d = ToolDispatcher(state=SessionState(), customer=c, rag=FakeRag(),
                       callbacks=FakeCallbacks(), session_id="s1")
    out = await d.dispatch(_call("update_customer", {"field": "name", "value": "An"}))
    assert c.name == "An"
    assert d.consume_customer_dirty() is True
    # consumed → next call returns False
    assert d.consume_customer_dirty() is False
    assert json.loads(out)["ok"] is True


async def test_dispatch_noble_search_uses_rag():
    c = Customer(project_interest="NCLB")
    d = ToolDispatcher(state=SessionState(), customer=c, rag=FakeRag(),
                       callbacks=FakeCallbacks(), session_id="s1")
    out = await d.dispatch(_call("noble_search", {"query": "giá"}))
    assert "rag:giá:NCLB" in out


async def test_unknown_tool_returns_error():
    d = ToolDispatcher(state=SessionState(), customer=Customer(), rag=FakeRag(),
                       callbacks=FakeCallbacks(), session_id="s1")
    out = await d.dispatch(_call("nope", {}))
    assert json.loads(out)["error"].startswith("unknown tool")


async def test_callbacks_fired():
    cb = FakeCallbacks()
    d = ToolDispatcher(state=SessionState(), customer=Customer(), rag=FakeRag(),
                       callbacks=cb, session_id="s1")
    await d.dispatch(_call("update_customer", {"field": "name", "value": "B"}))
    assert cb.events[0][0] == "start"
    assert cb.events[0][1] == "update_customer"
    assert cb.events[-1][0] == "done"


async def test_dispatch_does_not_handle_switch_agent():
    """Dispatcher should NOT dispatch switch_agent — runner captures it."""
    d = ToolDispatcher(state=SessionState(), customer=Customer(), rag=FakeRag(),
                       callbacks=FakeCallbacks(), session_id="s1")
    out = await d.dispatch(_call("switch_agent", {"target": "CA", "reason": "x"}))
    # Returns unknown tool — runner is responsible for special-case capture
    assert "unknown tool" in json.loads(out)["error"]
```

- [ ] **Step 3: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_tool_dispatcher.py -v
```

- [ ] **Step 4: Implement dispatcher**

Create `src/noble_agent_refactor/tools/dispatcher.py`:

```python
"""Tool dispatcher — pure function dispatch + customer_dirty signal."""
from __future__ import annotations

import json
import logging

from noble_agent_refactor.tools import booking, noble_search, update_customer

logger = logging.getLogger("noble_agent_refactor.tools.dispatcher")


class ToolDispatcher:
    def __init__(self, state, customer, rag, callbacks, session_id: str):
        self.state = state
        self.customer = customer
        self.rag = rag
        self.callbacks = callbacks
        self.session_id = session_id
        self._customer_dirty = False

    def mark_customer_dirty(self) -> None:
        self._customer_dirty = True

    def consume_customer_dirty(self) -> bool:
        v, self._customer_dirty = self._customer_dirty, False
        return v

    async def dispatch(self, tool_call: dict) -> str:
        name = tool_call["function"]["name"]
        try:
            args = json.loads(tool_call["function"]["arguments"] or "{}")
        except json.JSONDecodeError as e:
            logger.warning("dispatcher: bad args for %s: %s", name, e)
            return json.dumps({"ok": False, "error": f"bad args: {e}"})

        await self.callbacks.on_tool_start(name, args)
        try:
            if name == "update_customer":
                result = await update_customer.run(self.customer, args)
                self._customer_dirty = True
            elif name == "noble_search":
                result = await noble_search.run(self.rag, self, args)
            elif name == "book_consultation":
                result = await booking.run(self.customer, args, session_id=self.session_id)
            else:
                result = json.dumps({"error": f"unknown tool {name}"})
        except Exception as e:
            logger.exception("dispatcher: tool %s crashed", name)
            result = json.dumps({"error": f"tool {name} crashed: {e}"})

        await self.callbacks.on_tool_done(name, result)
        return result
```

- [ ] **Step 5: Run — expect pass**

```bash
pytest tests/unit/refactor/test_tool_dispatcher.py -v
```
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent_refactor/tools/switch_agent.py src/noble_agent_refactor/tools/dispatcher.py tests/unit/refactor/test_tool_dispatcher.py
git commit -m "feat(refactor): ToolDispatcher with customer_dirty signal"
```

---

## Task 9: Definitions — shared files

**Files:**
- Create: `src/noble_agent_refactor/definitions/shared/RULES.md`
- Create: `src/noble_agent_refactor/definitions/shared/HANDOFF.md`
- Create: `src/noble_agent_refactor/definitions/shared/CUSTOMER_PROFILE.md`

- [ ] **Step 1: shared/RULES.md**

```markdown
# Quy tắc chung cho mọi agent

- Trả lời bằng tiếng Việt tự nhiên, ngắn gọn, không markdown trừ khi cần.
- KHÔNG bịa thông tin về dự án, giá, pháp lý. Dữ liệu phải lấy qua tool `noble_search`.
- Khi user cung cấp thông tin cá nhân (tên, số điện thoại, ngân sách, dự án quan tâm...), gọi tool `update_customer` để lưu vào hồ sơ. Mỗi field một call.
- Không lặp lại nguyên văn câu hỏi của user. Trả lời thẳng.
- Nếu user nói tiếng nước ngoài, vẫn trả lời bằng tiếng Việt.
- Không tự tiết lộ rằng bạn là LLM/AI; nếu bị hỏi, nói rằng bạn là chuyên viên Noble.
```

- [ ] **Step 2: shared/HANDOFF.md**

```markdown
# Quy tắc bàn giao agent (switch_agent)

- Chỉ gọi `switch_agent` khi request của user thực sự ngoài phạm vi của bạn.
- KHÔNG dùng `switch_agent` để "nhờ agent khác hỏi user thông tin còn thiếu". Nếu thiếu thông tin, bạn TỰ hỏi user trực tiếp.
- Khi gọi `switch_agent`:
  - `target`: mã agent đích (`MA` / `CA` / `SA`).
  - `reason`: 1 câu lý do.
  - `briefing` (khuyến nghị): 2–4 câu tóm tắt cho agent đích — họ là ai, đã cung cấp gì, vướng ở đâu, agent đích cần làm gì tiếp.
- Trước khi gọi switch_agent, bạn có thể nói 1 câu ngắn với user ("Em chuyển anh sang phòng hỗ trợ nhé.") rồi mới phát lệnh.
```

- [ ] **Step 3: shared/CUSTOMER_PROFILE.md**

Format template cho customer block (jinja2):

```markdown
## Hồ sơ khách hàng (đã có)

{%- if customer.name or customer.full_name %}
- Tên: {{ customer.full_name or customer.name }}
{%- endif %}
{%- if customer.gender %}
- Giới tính: {{ customer.gender }}
{%- endif %}
{%- if customer.phone %}
- Điện thoại: {{ customer.phone }}
{%- endif %}
{%- if customer.project_interest %}
- Dự án quan tâm: {{ customer.project_interest }}
{%- endif %}
{%- if customer.budget %}
- Ngân sách: {{ customer.budget }}
{%- endif %}
{%- if customer.preferred_area %}
- Diện tích/khu vực mong muốn: {{ customer.preferred_area }}
{%- endif %}
{%- if customer.bedroom_count %}
- Số phòng ngủ: {{ customer.bedroom_count }}
{%- endif %}
{%- if customer.is_noble_customer %}
- Đã là khách Noble: có{% if customer.noble_info %} — {{ customer.noble_info }}{% endif %}
{%- endif %}

Nếu phần trên còn thiếu trường nào mà user vừa cung cấp, hãy gọi `update_customer` ngay.
```

- [ ] **Step 4: Commit**

```bash
git add src/noble_agent_refactor/definitions/shared/
git commit -m "feat(refactor): shared definitions (rules, handoff, customer profile template)"
```

---

## Task 10: Definitions — manager (MA)

**Files:**
- Create: `src/noble_agent_refactor/definitions/manager/SOUL.md`
- Create: `src/noble_agent_refactor/definitions/manager/RULES.md`
- Create: `src/noble_agent_refactor/definitions/manager/PROMPT_TEMPLATE.md`
- Create: `src/noble_agent_refactor/definitions/manager/config.json`

- [ ] **Step 1: manager/SOUL.md**

```markdown
Bạn là Linh — lễ tân trung tâm của Noble Real Estate. Em đón cuộc gọi, chitchat ngắn với khách, và điều hướng sang chuyên viên tư vấn hoặc bộ phận hỗ trợ đúng nhu cầu của khách.
```

- [ ] **Step 2: manager/RULES.md**

```markdown
# Rule riêng cho Manager (MA)

- Vai trò của em là lễ tân/điều phối. Em KHÔNG tự tư vấn sâu về sản phẩm, KHÔNG tự xử lý hồ sơ — em điều hướng.
- Khi khách hỏi tư vấn mua, giá, dự án, đặt lịch tham quan → gọi `switch_agent(target="CA", ...)` với briefing.
- Khi khách hỏi hồ sơ, giấy phép, thủ tục, sổ hồng, hỗ trợ sau bán → gọi `switch_agent(target="SA", ...)`.
- Khi khách chỉ chào hỏi/chitchat, em trả lời 1–2 câu thân thiện rồi hỏi nhu cầu.
- Nếu chưa biết tên khách, hỏi tên trước khi điều hướng.
- KHÔNG hỏi quá nhiều thông tin trước khi route — CA/SA sẽ tự hỏi chi tiết.
```

- [ ] **Step 3: manager/PROMPT_TEMPLATE.md**

```markdown
{{ soul }}

## Quy tắc chung
{{ shared_rules }}

## Quy tắc riêng (Manager)
{{ rules }}

{{ customer_block }}

{% if briefing %}
## Briefing bàn giao từ {{ briefing.from_agent }}
Lý do: {{ briefing.reason }}
{{ briefing.text }}
{% endif %}

{% if prior_summary %}
## Tóm tắt phiên trước (Manager đã làm)
{{ prior_summary.text }}
{% endif %}

## Bàn giao agent
{{ shared_handoff }}
```

- [ ] **Step 4: manager/config.json**

```json
{
  "code": "MA",
  "name": "manager",
  "model": "gemini-2.5-flash",
  "temperature": 0.6,
  "max_tokens": 400,
  "tools": ["switch_agent", "update_customer"]
}
```

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/definitions/manager/
git commit -m "feat(refactor): manager agent definition"
```

---

## Task 11: Definitions — consultant (CA) + support (SA)

**Files:**
- Create: `src/noble_agent_refactor/definitions/consultant/{SOUL,RULES,PROMPT_TEMPLATE}.md`, `config.json`
- Create: `src/noble_agent_refactor/definitions/support/{SOUL,RULES,PROMPT_TEMPLATE}.md`, `config.json`

- [ ] **Step 1: consultant/SOUL.md**

```markdown
Bạn là Luna — chuyên viên tư vấn bán hàng Noble Real Estate. Em làm việc trực tiếp với khách về thông tin dự án, giá, ngân sách, và đặt lịch tham quan.
```

- [ ] **Step 2: consultant/RULES.md**

```markdown
# Rule riêng cho Consultant (CA)

- Em là chuyên viên tư vấn — KHÔNG nhờ Manager hỏi hộ thông tin gì cả. Thiếu thông tin → tự hỏi user trực tiếp.
- Trước khi tư vấn cụ thể, cần ít nhất: tên khách, dự án quan tâm (hoặc tiêu chí), ngân sách.
- Khi cần tra cứu giá/tiện ích/pháp lý/diện tích → gọi `noble_search(query, project_filter)`. Truyền project_filter là mã canonical (NCLB/NCTH/NPLB/NTTL/SSLC) nếu biết.
- Khi user gật đầu đặt lịch tham quan, xác nhận lại tên + số điện thoại + ngày giờ rồi gọi `book_consultation`.
- Chỉ gọi `switch_agent` trong các trường hợp:
  1. Khách hỏi sang thủ tục hồ sơ/sổ hồng/pháp lý chi tiết → `switch_agent(target="SA", ...)`.
  2. Khách kết thúc tư vấn và quay sang chitchat → `switch_agent(target="MA", ...)`.
- Khi nhận briefing từ MA/SA, đọc kỹ và tiếp tục liền mạch — KHÔNG hỏi lại thông tin đã có trong briefing/hồ sơ.
```

- [ ] **Step 3: consultant/PROMPT_TEMPLATE.md** (giống manager nhưng đổi label section)

```markdown
{{ soul }}

## Quy tắc chung
{{ shared_rules }}

## Quy tắc riêng (Consultant)
{{ rules }}

{{ customer_block }}

{% if briefing %}
## Briefing bàn giao từ {{ briefing.from_agent }}
Lý do: {{ briefing.reason }}
{{ briefing.text }}
{% endif %}

{% if prior_summary %}
## Tóm tắt phiên tư vấn trước
{{ prior_summary.text }}
{% endif %}

## Bàn giao agent
{{ shared_handoff }}
```

- [ ] **Step 4: consultant/config.json**

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

- [ ] **Step 5: support/SOUL.md**

```markdown
Bạn là Hân — chuyên viên hỗ trợ khách hàng Noble Real Estate. Em xử lý câu hỏi về hồ sơ, giấy phép, sổ hồng, thủ tục thanh toán, và các vấn đề sau bán.
```

- [ ] **Step 6: support/RULES.md**

```markdown
# Rule riêng cho Support (SA)

- Em là hỗ trợ — KHÔNG nhờ Manager hỏi user. Thiếu thông tin → tự hỏi trực tiếp.
- Cần xác thực khách bằng số điện thoại trước khi tra cứu hồ sơ cá nhân.
- Khi cần tra cứu thông tin dự án (pháp lý, sổ hồng, tiến độ bàn giao) → gọi `noble_search`.
- Chỉ `switch_agent` khi:
  1. Khách quay lại quan tâm mua/giá → `switch_agent(target="CA", ...)`.
  2. Khách hết yêu cầu hỗ trợ và chỉ chitchat → `switch_agent(target="MA", ...)`.
- Khi nhận briefing, đọc kỹ và tiếp tục liền mạch.
```

- [ ] **Step 7: support/PROMPT_TEMPLATE.md** (giống template trên)

```markdown
{{ soul }}

## Quy tắc chung
{{ shared_rules }}

## Quy tắc riêng (Support)
{{ rules }}

{{ customer_block }}

{% if briefing %}
## Briefing bàn giao từ {{ briefing.from_agent }}
Lý do: {{ briefing.reason }}
{{ briefing.text }}
{% endif %}

{% if prior_summary %}
## Tóm tắt phiên hỗ trợ trước
{{ prior_summary.text }}
{% endif %}

## Bàn giao agent
{{ shared_handoff }}
```

- [ ] **Step 8: support/config.json**

```json
{
  "code": "SA",
  "name": "support",
  "model": "gemini-2.5-flash",
  "temperature": 0.6,
  "max_tokens": 600,
  "tools": ["switch_agent", "update_customer", "noble_search"]
}
```

- [ ] **Step 9: Commit**

```bash
git add src/noble_agent_refactor/definitions/consultant/ src/noble_agent_refactor/definitions/support/
git commit -m "feat(refactor): consultant + support agent definitions"
```

---

## Task 12: AgentDef + AgentRegistry

**Files:**
- Create: `src/noble_agent_refactor/agents/base.py`
- Create: `src/noble_agent_refactor/agents/registry.py`
- Test: `tests/unit/refactor/test_agents_registry.py`

- [ ] **Step 1: Đảm bảo jinja2 trong dependencies**

```bash
grep -E "jinja2" pyproject.toml
```

Nếu chưa, thêm vào main dependencies: `"jinja2>=3.1"` và `pip install jinja2`.

- [ ] **Step 2: Viết test**

Create `tests/unit/refactor/test_agents_registry.py`:

```python
from pathlib import Path

import pytest

from noble_agent_refactor.agents.registry import AgentRegistry


@pytest.fixture
def real_registry():
    defs = Path(__file__).resolve().parents[3] / "src" / "noble_agent_refactor" / "definitions"
    return AgentRegistry(defs)


def test_registers_three_agents(real_registry):
    codes = {a.code for a in real_registry.list()}
    assert codes == {"MA", "CA", "SA"}


def test_get_by_code(real_registry):
    ca = real_registry.get("CA")
    assert ca.code == "CA"
    assert ca.name == "consultant"
    assert "noble_search" in ca.tool_names
    assert ca.temperature == 0.7


def test_tool_schemas_match_tool_names(real_registry):
    sa = real_registry.get("SA")
    schema_names = [s["function"]["name"] for s in sa.tool_schemas]
    assert schema_names == sa.tool_names


def test_sections_loaded(real_registry):
    ma = real_registry.get("MA")
    assert "lễ tân" in ma.sections["soul"].lower() or "manager" in ma.sections["soul"].lower()
    assert ma.sections["shared_rules"]
    assert ma.sections["shared_handoff"]
    assert ma.sections["customer_format"]


def test_prompt_template_renders_with_minimal_context(real_registry):
    from noble_agent_refactor.storage.models import Customer

    ma = real_registry.get("MA")
    out = ma.prompt_template.render(
        soul=ma.sections["soul"],
        shared_rules=ma.sections["shared_rules"],
        shared_handoff=ma.sections["shared_handoff"],
        rules=ma.sections["rules"],
        customer_block="",
        briefing=None,
        prior_summary=None,
    )
    assert "Manager" in out or "lễ tân" in out


def test_get_unknown_raises(real_registry):
    with pytest.raises(KeyError):
        real_registry.get("ZZ")
```

- [ ] **Step 3: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_agents_registry.py -v
```

- [ ] **Step 4: Implement AgentDef + AgentRegistry**

Create `src/noble_agent_refactor/agents/base.py`:

```python
"""AgentDef — immutable per-agent configuration loaded from definitions/<agent>/."""
from __future__ import annotations

from dataclasses import dataclass

import jinja2


@dataclass(frozen=True)
class AgentDef:
    code: str               # "MA" | "CA" | "SA"
    name: str               # "manager" | "consultant" | "support"
    model: str
    temperature: float
    max_tokens: int
    prompt_template: jinja2.Template
    sections: dict          # {soul, rules, shared_rules, shared_handoff, customer_format}
    tool_names: list
    tool_schemas: list
```

Create `src/noble_agent_refactor/agents/registry.py`:

```python
"""Load definitions/ → AgentDef instances."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import jinja2

from noble_agent_refactor.agents.base import AgentDef
from noble_agent_refactor.tools.schemas import schemas_for

logger = logging.getLogger("noble_agent_refactor.registry")

AGENT_DIRS = {"manager": "MA", "consultant": "CA", "support": "SA"}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class AgentRegistry:
    def __init__(self, definitions_dir: Path):
        self._defs_dir = Path(definitions_dir)
        self._env = jinja2.Environment(
            loader=jinja2.BaseLoader(),
            autoescape=False,
            trim_blocks=False,
            lstrip_blocks=False,
            keep_trailing_newline=True,
        )
        self._shared = self._load_shared()
        self._agents: dict[str, AgentDef] = {}
        for dirname, code in AGENT_DIRS.items():
            self._agents[code] = self._load_agent(dirname, code)

    def _load_shared(self) -> dict:
        shared_dir = self._defs_dir / "shared"
        return {
            "shared_rules": _read(shared_dir / "RULES.md"),
            "shared_handoff": _read(shared_dir / "HANDOFF.md"),
            "customer_format": _read(shared_dir / "CUSTOMER_PROFILE.md"),
        }

    def _load_agent(self, dirname: str, code: str) -> AgentDef:
        agent_dir = self._defs_dir / dirname
        config = json.loads(_read(agent_dir / "config.json"))
        if config["code"] != code:
            raise ValueError(f"definitions/{dirname}/config.json code={config['code']} expected {code}")

        sections = {
            "soul": _read(agent_dir / "SOUL.md"),
            "rules": _read(agent_dir / "RULES.md"),
            **self._shared,
        }
        template_src = _read(agent_dir / "PROMPT_TEMPLATE.md")
        tmpl = self._env.from_string(template_src)
        tool_names = list(config["tools"])
        tool_schemas = schemas_for(tool_names)

        return AgentDef(
            code=code,
            name=config["name"],
            model=config["model"],
            temperature=float(config["temperature"]),
            max_tokens=int(config["max_tokens"]),
            prompt_template=tmpl,
            sections=sections,
            tool_names=tool_names,
            tool_schemas=tool_schemas,
        )

    def get(self, code: str) -> AgentDef:
        if code not in self._agents:
            raise KeyError(f"unknown agent code {code}")
        return self._agents[code]

    def list(self) -> list[AgentDef]:
        return list(self._agents.values())
```

- [ ] **Step 5: Run — expect pass**

```bash
pytest tests/unit/refactor/test_agents_registry.py -v
```
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent_refactor/agents/ tests/unit/refactor/test_agents_registry.py pyproject.toml
git commit -m "feat(refactor): AgentDef + AgentRegistry loading definitions/"
```

---

## Task 13: Prompt builder

**Files:**
- Create: `src/noble_agent_refactor/prompts/builder.py`
- Test: `tests/unit/refactor/test_prompts_builder.py`

- [ ] **Step 1: Viết test**

Create `tests/unit/refactor/test_prompts_builder.py`:

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest

from noble_agent_refactor.agents.registry import AgentRegistry
from noble_agent_refactor.prompts.builder import build_system_prompt
from noble_agent_refactor.storage.models import Briefing, Customer, ThreadSummary


@pytest.fixture
def registry():
    defs = Path(__file__).resolve().parents[3] / "src" / "noble_agent_refactor" / "definitions"
    return AgentRegistry(defs)


def test_build_minimal(registry):
    out = build_system_prompt(registry.get("MA"), Customer(), briefing=None, prior_summary=None)
    assert "lễ tân" in out.lower() or "manager" in out.lower()
    # No briefing/summary sections rendered
    assert "Briefing bàn giao" not in out
    assert "Tóm tắt phiên" not in out


def test_build_with_customer(registry):
    c = Customer(name="An", project_interest="NCLB", budget="3 tỉ")
    out = build_system_prompt(registry.get("CA"), c, briefing=None, prior_summary=None)
    assert "An" in out
    assert "NCLB" in out
    assert "3 tỉ" in out


def test_build_with_briefing(registry):
    b = Briefing(from_agent="MA", reason="khách muốn tư vấn",
                 text="Khách tên An, ngân sách 3 tỉ, quan tâm NCLB.",
                 created_at=datetime.now(UTC))
    out = build_system_prompt(registry.get("CA"), Customer(), briefing=b, prior_summary=None)
    assert "Briefing bàn giao từ MA" in out
    assert "khách muốn tư vấn" in out
    assert "Khách tên An" in out


def test_build_with_prior_summary(registry):
    s = ThreadSummary(agent="CA", upto_message_count=12, text="đã giới thiệu 3 căn",
                      created_at=datetime.now(UTC))
    out = build_system_prompt(registry.get("CA"), Customer(), briefing=None, prior_summary=s)
    assert "Tóm tắt" in out
    assert "đã giới thiệu" in out
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_prompts_builder.py -v
```

- [ ] **Step 3: Implement builder**

Create `src/noble_agent_refactor/prompts/builder.py`:

```python
"""Compose system prompt for an agent from its AgentDef + runtime context."""
from __future__ import annotations

import jinja2

from noble_agent_refactor.agents.base import AgentDef
from noble_agent_refactor.storage.models import Briefing, Customer, ThreadSummary

_customer_env = jinja2.Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)


def _render_customer(template_src: str, customer: Customer) -> str:
    return _customer_env.from_string(template_src).render(customer=customer)


def build_system_prompt(
    agent: AgentDef,
    customer: Customer,
    briefing: Briefing | None,
    prior_summary: ThreadSummary | None,
) -> str:
    customer_block = _render_customer(agent.sections["customer_format"], customer)
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

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_prompts_builder.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/prompts/builder.py tests/unit/refactor/test_prompts_builder.py
git commit -m "feat(refactor): build_system_prompt composes definitions + runtime context"
```

---

## Task 14: LLM streaming client

**Files:**
- Create: `src/noble_agent_refactor/llm/client.py`
- Test: `tests/unit/refactor/test_llm_client.py`

- [ ] **Step 1: Viết test với mock OpenAI**

Create `tests/unit/refactor/test_llm_client.py`:

```python
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent_refactor.llm.client import StreamingClient


def _fake_stream_chunks(text_pieces, tool_calls=None):
    """Yield chunks mirroring OpenAI streaming SDK shape."""
    chunks = []
    for piece in text_pieces:
        chunks.append(
            MagicMock(choices=[MagicMock(delta=MagicMock(content=piece, tool_calls=None))])
        )
    if tool_calls:
        for tc in tool_calls:
            chunks.append(
                MagicMock(choices=[MagicMock(delta=MagicMock(content=None, tool_calls=[tc]))])
            )
    chunks.append(MagicMock(choices=[MagicMock(delta=MagicMock(content=None, tool_calls=None),
                                               finish_reason="stop")]))
    return chunks


async def test_streams_tokens_and_returns_content():
    mock_create = AsyncMock()
    async def gen():
        for ch in _fake_stream_chunks(["he", "llo"]):
            yield ch
    mock_create.return_value = gen()
    mock_provider = MagicMock(name="provider")
    mock_provider.chat.completions.create = mock_create

    client = StreamingClient(providers=[("openai", mock_provider)])
    tokens = []

    async def on_token(t):
        tokens.append(t)

    content, tool_calls = await client.stream_completion(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        model="gpt-4o-mini",
        temperature=0.5,
        max_tokens=100,
        on_token=on_token,
    )
    assert content == "hello"
    assert tool_calls is None or tool_calls == []
    assert tokens == ["he", "llo"]


async def test_falls_back_to_second_provider_on_failure():
    failing = MagicMock()
    failing.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

    good = MagicMock()
    async def gen():
        for ch in _fake_stream_chunks(["ok"]):
            yield ch
    good.chat.completions.create = AsyncMock(return_value=gen())

    client = StreamingClient(providers=[("p1", failing), ("p2", good)])
    content, _ = await client.stream_completion(
        messages=[{"role": "user", "content": "x"}],
        tools=[], model="m", temperature=0.5, max_tokens=10, on_token=AsyncMock(),
    )
    assert content == "ok"


async def test_complete_once_returns_text():
    mock_create = AsyncMock()
    mock_create.return_value = MagicMock(choices=[MagicMock(message=MagicMock(content="summary text"))])
    provider = MagicMock()
    provider.chat.completions.create = mock_create

    client = StreamingClient(providers=[("openai", provider)])
    out = await client.complete_once(
        messages=[{"role": "user", "content": "summarize"}],
        model="gpt-4o-mini",
        temperature=0.2,
        max_tokens=100,
    )
    assert out == "summary text"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_llm_client.py -v
```

- [ ] **Step 3: Implement client**

Create `src/noble_agent_refactor/llm/client.py`:

```python
"""Streaming LLM client with provider fallback. Provider objects must mirror the OpenAI SDK shape."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable

logger = logging.getLogger("noble_agent_refactor.llm")


class StreamingClient:
    def __init__(self, providers: list[tuple[str, object]]):
        """providers: ordered list of (name, openai_client_like). First success wins."""
        if not providers:
            raise ValueError("StreamingClient requires at least one provider")
        self._providers = providers

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
        last_err: Exception | None = None
        for name, provider in self._providers:
            try:
                return await self._stream_once(
                    provider=provider,
                    messages=messages,
                    tools=tools,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    on_token=on_token,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("llm: provider %s failed (%s), trying next", name, e)
                last_err = e
        raise RuntimeError(f"all LLM providers failed: {last_err}")

    async def _stream_once(self, *, provider, messages, tools, model, temperature,
                            max_tokens, on_token) -> tuple[str, list[dict] | None]:
        kwargs = dict(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )
        if tools:
            kwargs["tools"] = tools

        stream = await provider.chat.completions.create(**kwargs)

        content_parts: list[str] = []
        tool_calls: dict[int, dict] = {}  # by index, accumulating

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                content_parts.append(piece)
                await on_token(piece)
            for tc_delta in getattr(delta, "tool_calls", None) or []:
                idx = getattr(tc_delta, "index", 0)
                cur = tool_calls.setdefault(idx, {"id": "", "type": "function",
                                                   "function": {"name": "", "arguments": ""}})
                if getattr(tc_delta, "id", None):
                    cur["id"] = tc_delta.id
                fn = getattr(tc_delta, "function", None)
                if fn:
                    if getattr(fn, "name", None):
                        cur["function"]["name"] = fn.name
                    if getattr(fn, "arguments", None):
                        cur["function"]["arguments"] += fn.arguments

        tcs = [tool_calls[i] for i in sorted(tool_calls.keys())] if tool_calls else None
        return "".join(content_parts), tcs

    async def complete_once(self, *, messages, model, temperature, max_tokens) -> str:
        last_err: Exception | None = None
        for name, provider in self._providers:
            try:
                resp = await provider.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                )
                return resp.choices[0].message.content or ""
            except Exception as e:  # noqa: BLE001
                logger.warning("llm.complete_once: provider %s failed (%s)", name, e)
                last_err = e
        raise RuntimeError(f"all LLM providers failed: {last_err}")
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_llm_client.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/llm/client.py tests/unit/refactor/test_llm_client.py
git commit -m "feat(refactor): StreamingClient with provider fallback"
```

---

## Task 15: Agent runner (LLM + tool loop)

**Files:**
- Create: `src/noble_agent_refactor/agents/runner.py`
- Test: `tests/unit/refactor/test_agents_runner.py`

- [ ] **Step 1: Viết test với fake LLM**

Create `tests/unit/refactor/test_agents_runner.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from noble_agent_refactor.agents.registry import AgentRegistry
from noble_agent_refactor.agents.runner import HandoffRequest, run_agent_turn
from noble_agent_refactor.storage.models import Customer, SessionState, ThreadMessage
from noble_agent_refactor.tools.dispatcher import ToolDispatcher


@pytest.fixture
def registry():
    defs = Path(__file__).resolve().parents[3] / "src" / "noble_agent_refactor" / "definitions"
    return AgentRegistry(defs)


class FakeRag:
    async def search(self, query, project_filter):
        return f"rag:{query}/{project_filter}"


class NoopCallbacks:
    async def on_token(self, t): ...
    async def on_tool_start(self, n, a): ...
    async def on_tool_done(self, n, r): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


def _make_dispatcher(state, customer):
    return ToolDispatcher(state=state, customer=customer, rag=FakeRag(),
                          callbacks=NoopCallbacks(), session_id="s1")


def _tool_call(name, args, tc_id="tc1"):
    return {"id": tc_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedLLM:
    def __init__(self, scripts):
        # scripts: list of (content, tool_calls) tuples returned in order
        self._scripts = list(scripts)

    async def stream_completion(self, *, messages, tools, model, temperature, max_tokens, on_token):
        content, tcs = self._scripts.pop(0)
        return content, tcs


async def test_no_tool_calls_returns_none(registry):
    llm = ScriptedLLM([("Chào anh, em là Linh.", None)])
    state = SessionState()
    customer = Customer()
    out = await run_agent_turn(
        agent=registry.get("MA"),
        thread=state.threads["MA"],
        customer=customer,
        briefing=None, prior_summary=None,
        llm=llm,
        dispatcher=_make_dispatcher(state, customer),
        callbacks=NoopCallbacks(),
    )
    assert out is None
    # Assistant message appended
    assert state.threads["MA"][-1].role == "assistant"
    assert state.threads["MA"][-1].content == "Chào anh, em là Linh."


async def test_captures_switch_agent(registry):
    llm = ScriptedLLM([
        ("Em chuyển anh sang tư vấn nhé.",
         [_tool_call("switch_agent", {"target": "CA", "reason": "khách muốn tư vấn",
                                       "briefing": "Khách tên An, ngân sách 3 tỉ"})]),
    ])
    state = SessionState()
    customer = Customer()
    out = await run_agent_turn(
        agent=registry.get("MA"),
        thread=state.threads["MA"],
        customer=customer,
        briefing=None, prior_summary=None,
        llm=llm,
        dispatcher=_make_dispatcher(state, customer),
        callbacks=NoopCallbacks(),
    )
    assert isinstance(out, HandoffRequest)
    assert out.target == "CA"
    assert out.briefing == "Khách tên An, ngân sách 3 tỉ"
    # Synthetic tool result appended for thread consistency
    assert state.threads["MA"][-1].role == "tool"
    assert state.threads["MA"][-1].name == "switch_agent"


async def test_runs_tool_then_continues(registry):
    llm = ScriptedLLM([
        ("Để em tra...", [_tool_call("noble_search", {"query": "giá NCLB"})]),
        ("Giá khoảng 5 tỉ.", None),
    ])
    state = SessionState()
    customer = Customer(project_interest="NCLB")
    out = await run_agent_turn(
        agent=registry.get("CA"),
        thread=state.threads["CA"],
        customer=customer,
        briefing=None, prior_summary=None,
        llm=llm,
        dispatcher=_make_dispatcher(state, customer),
        callbacks=NoopCallbacks(),
    )
    assert out is None
    # Thread: assistant(tool_call) + tool + assistant(final)
    roles = [m.role for m in state.threads["CA"]]
    assert roles == ["assistant", "tool", "assistant"]
    assert state.threads["CA"][-1].content == "Giá khoảng 5 tỉ."


async def test_update_customer_then_continue(registry):
    llm = ScriptedLLM([
        ("", [_tool_call("update_customer", {"field": "name", "value": "An"})]),
        ("Cảm ơn anh An.", None),
    ])
    state = SessionState()
    customer = Customer()
    await run_agent_turn(
        agent=registry.get("CA"),
        thread=state.threads["CA"],
        customer=customer,
        briefing=None, prior_summary=None,
        llm=llm,
        dispatcher=_make_dispatcher(state, customer),
        callbacks=NoopCallbacks(),
    )
    assert customer.name == "An"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_agents_runner.py -v
```

- [ ] **Step 3: Implement runner**

Create `src/noble_agent_refactor/agents/runner.py`:

```python
"""Single-agent turn runner — LLM streaming + tool loop, with switch_agent capture."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from noble_agent_refactor.agents.base import AgentDef
from noble_agent_refactor.prompts.builder import build_system_prompt
from noble_agent_refactor.storage.models import Briefing, Customer, ThreadMessage, ThreadSummary

logger = logging.getLogger("noble_agent_refactor.runner")

# Cap to avoid runaway tool loops within a single agent turn
MAX_TOOL_ITERATIONS = 5


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
    dispatcher,
    callbacks,
) -> HandoffRequest | None:
    system = build_system_prompt(agent, customer, briefing, prior_summary)
    messages: list[dict] = [{"role": "system", "content": system}]
    messages.extend(m.to_openai() for m in thread)

    for iteration in range(MAX_TOOL_ITERATIONS):
        content, tool_calls = await llm.stream_completion(
            messages=messages,
            tools=agent.tool_schemas,
            model=agent.model,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            on_token=callbacks.on_token,
        )

        assistant_msg = ThreadMessage(role="assistant", content=content or "", tool_calls=tool_calls)
        thread.append(assistant_msg)
        messages.append(assistant_msg.to_openai())

        if not tool_calls:
            return None

        # Special-case: capture switch_agent immediately, stop tool loop
        for tc in tool_calls:
            if tc["function"]["name"] == "switch_agent":
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                # synthetic tool result so thread is OpenAI-history-consistent
                thread.append(ThreadMessage(
                    role="tool",
                    tool_call_id=tc["id"],
                    name="switch_agent",
                    content='{"status":"handoff_initiated"}',
                ))
                return HandoffRequest(
                    target=args.get("target", "MA"),
                    reason=args.get("reason", ""),
                    briefing=args.get("briefing"),
                )

        # Dispatch remaining tool calls
        for tc in tool_calls:
            result = await dispatcher.dispatch(tc)
            tool_msg = ThreadMessage(
                role="tool",
                tool_call_id=tc["id"],
                name=tc["function"]["name"],
                content=result,
            )
            thread.append(tool_msg)
            messages.append(tool_msg.to_openai())

        # If customer changed via tool (V7/update_customer) rebuild system prompt
        if dispatcher.consume_customer_dirty():
            messages[0] = {
                "role": "system",
                "content": build_system_prompt(agent, customer, briefing, prior_summary),
            }

    logger.warning("runner: hit MAX_TOOL_ITERATIONS for agent %s", agent.code)
    return None
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_agents_runner.py -v
```
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/agents/runner.py tests/unit/refactor/test_agents_runner.py
git commit -m "feat(refactor): run_agent_turn with switch_agent capture + tool loop cap"
```

---

## Task 16: Handoff briefing (auto-generate)

**Files:**
- Create: `src/noble_agent_refactor/handoff/briefing.py`
- Test: `tests/unit/refactor/test_handoff_briefing.py`

- [ ] **Step 1: Viết test**

Create `tests/unit/refactor/test_handoff_briefing.py`:

```python
from unittest.mock import AsyncMock

import pytest

from noble_agent_refactor.handoff.briefing import auto_generate_briefing
from noble_agent_refactor.storage.models import Customer, ThreadMessage


async def test_calls_llm_with_recent_messages_and_returns_text():
    thread = [
        ThreadMessage(role="user", content="cho em tư vấn nhà 3 tỉ"),
        ThreadMessage(role="assistant", content="dạ anh tên gì ạ"),
        ThreadMessage(role="user", content="anh tên An"),
    ]
    customer = Customer(name="An", budget="3 tỉ")
    llm = AsyncMock()
    llm.complete_once = AsyncMock(return_value="Khách tên An, ngân sách 3 tỉ.")

    out = await auto_generate_briefing(thread, customer, reason="cần hồ sơ",
                                        llm=llm, lookback=6, model="gpt-4o-mini")
    assert out == "Khách tên An, ngân sách 3 tỉ."
    args, kwargs = llm.complete_once.call_args
    prompt_msgs = kwargs["messages"]
    assert prompt_msgs[0]["role"] == "user"
    assert "An" in prompt_msgs[0]["content"]
    assert "3 tỉ" in prompt_msgs[0]["content"]
    assert "cần hồ sơ" in prompt_msgs[0]["content"]


async def test_lookback_limits_messages():
    thread = [ThreadMessage(role="user", content=f"msg{i}") for i in range(20)]
    llm = AsyncMock()
    llm.complete_once = AsyncMock(return_value="x")
    await auto_generate_briefing(thread, Customer(), reason="r", llm=llm, lookback=3, model="m")
    prompt = llm.complete_once.call_args.kwargs["messages"][0]["content"]
    assert "msg19" in prompt
    assert "msg16" not in prompt  # only last 3
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_handoff_briefing.py -v
```

- [ ] **Step 3: Implement**

Create `src/noble_agent_refactor/handoff/briefing.py`:

```python
"""Auto-generate handoff briefing when the source agent didn't supply one."""
from __future__ import annotations

from noble_agent_refactor.storage.models import Customer, ThreadMessage

_BRIEFING_PROMPT = """Bạn là trợ lý ghi briefing cho cuộc hội thoại tư vấn bất động sản.

Bối cảnh: agent hiện tại đang bàn giao cho agent khác. Lý do bàn giao: {reason}.

Hồ sơ khách đã có:
{customer_block}

Đoạn hội thoại gần đây:
{thread_block}

Yêu cầu: viết briefing 2–5 câu cho agent kế tiếp, gồm:
- Khách là ai (tên, dự án quan tâm nếu có).
- Slot đã thu thập + slot còn thiếu.
- Việc đang dở và bước tiếp theo agent kế tiếp cần làm.

Chỉ trả về nội dung briefing, không lời thừa."""


def _format_customer(c: Customer) -> str:
    fields = []
    if c.name or c.full_name:
        fields.append(f"- Tên: {c.full_name or c.name}")
    if c.phone:
        fields.append(f"- SĐT: {c.phone}")
    if c.project_interest:
        fields.append(f"- Dự án: {c.project_interest}")
    if c.budget:
        fields.append(f"- Ngân sách: {c.budget}")
    if c.preferred_area:
        fields.append(f"- Diện tích: {c.preferred_area}")
    if c.bedroom_count:
        fields.append(f"- Phòng ngủ: {c.bedroom_count}")
    return "\n".join(fields) or "(chưa có)"


def _format_thread(thread: list[ThreadMessage]) -> str:
    lines = []
    for m in thread:
        if m.role == "user":
            lines.append(f"User: {m.content}")
        elif m.role == "assistant" and m.content:
            lines.append(f"Agent: {m.content}")
    return "\n".join(lines) or "(trống)"


async def auto_generate_briefing(
    thread: list[ThreadMessage],
    customer: Customer,
    reason: str,
    llm,
    lookback: int,
    model: str,
) -> str:
    recent = thread[-lookback:]
    prompt = _BRIEFING_PROMPT.format(
        reason=reason or "(không nói rõ)",
        customer_block=_format_customer(customer),
        thread_block=_format_thread(recent),
    )
    return await llm.complete_once(
        messages=[{"role": "user", "content": prompt}],
        model=model,
        temperature=0.2,
        max_tokens=300,
    )
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_handoff_briefing.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/handoff/briefing.py tests/unit/refactor/test_handoff_briefing.py
git commit -m "feat(refactor): auto_generate_briefing fallback when agent omits briefing"
```

---

## Task 17: Handoff summary (async task)

**Files:**
- Create: `src/noble_agent_refactor/handoff/summary.py`
- Test: `tests/unit/refactor/test_handoff_summary.py`

- [ ] **Step 1: Viết test**

Create `tests/unit/refactor/test_handoff_summary.py`:

```python
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from noble_agent_refactor.handoff.summary import summarize_and_persist
from noble_agent_refactor.storage.models import SessionState, ThreadMessage
from noble_agent_refactor.storage.repo import StateRepo


async def test_persists_summary_via_patch():
    redis = FakeRedis(decode_responses=False)
    repo = StateRepo(redis_client=redis, default_agent="MA", ttl_seconds=3600)
    # Seed state with some thread already
    meta, customer, state = await repo.load("sid_x")
    state.threads["CA"].append(ThreadMessage(role="user", content="ngân sách 3 tỉ"))
    await repo.save_all("sid_x", meta, customer, state)

    snapshot = list(state.threads["CA"])
    llm = AsyncMock()
    llm.complete_once = AsyncMock(return_value="Khách 3 tỉ, đang tìm 2PN.")

    await summarize_and_persist(sid="sid_x", agent_code="CA",
                                 thread_snapshot=snapshot, llm=llm, repo=repo,
                                 model="gpt-4o-mini")

    _, _, after = await repo.load("sid_x")
    assert after.summaries["CA"].text == "Khách 3 tỉ, đang tìm 2PN."
    assert after.summaries["CA"].upto_message_count == len(snapshot)


async def test_does_not_overwrite_threads_added_meanwhile():
    redis = FakeRedis(decode_responses=False)
    repo = StateRepo(redis_client=redis, default_agent="MA", ttl_seconds=3600)
    meta, customer, state = await repo.load("sid_y")
    state.threads["CA"].append(ThreadMessage(role="user", content="m1"))
    await repo.save_all("sid_y", meta, customer, state)
    snapshot = list(state.threads["CA"])

    # Concurrent writer adds a new message
    _, _, state_b = await repo.load("sid_y")
    state_b.threads["CA"].append(ThreadMessage(role="assistant", content="m2"))
    await repo.save_state("sid_y", state_b)

    llm = AsyncMock()
    llm.complete_once = AsyncMock(return_value="sum")
    await summarize_and_persist("sid_y", "CA", snapshot, llm, repo, model="m")

    _, _, after = await repo.load("sid_y")
    assert len(after.threads["CA"]) == 2  # not lost
    assert after.summaries["CA"].text == "sum"
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_handoff_summary.py -v
```

- [ ] **Step 3: Implement**

Create `src/noble_agent_refactor/handoff/summary.py`:

```python
"""Async per-thread summarizer — fires after handoff when thread length > K."""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from noble_agent_refactor.storage.models import ThreadMessage, ThreadSummary

logger = logging.getLogger("noble_agent_refactor.summary")

_PROMPT = """Tóm tắt đoạn hội thoại sau (góc nhìn agent {agent}) thành 4–6 câu, giữ lại:
- Khách là ai, đã cung cấp slot gì.
- Việc agent đã làm xong và đang dở.
- Quyết định/cam kết với khách nếu có.

Đoạn hội thoại:
{thread}

Chỉ trả về tóm tắt, không lời thừa."""


def _format(thread: list[ThreadMessage]) -> str:
    lines = []
    for m in thread:
        if m.role == "user":
            lines.append(f"User: {m.content}")
        elif m.role == "assistant" and m.content:
            lines.append(f"Agent: {m.content}")
        elif m.role == "tool":
            lines.append(f"[tool {m.name}]: {m.content[:120]}")
    return "\n".join(lines)


async def summarize_and_persist(
    sid: str,
    agent_code: str,
    thread_snapshot: list[ThreadMessage],
    llm,
    repo,
    model: str,
) -> None:
    try:
        text = await llm.complete_once(
            messages=[{"role": "user", "content": _PROMPT.format(
                agent=agent_code, thread=_format(thread_snapshot))}],
            model=model,
            temperature=0.2,
            max_tokens=400,
        )
    except Exception:
        logger.exception("summary: LLM failed for %s/%s", sid, agent_code)
        return

    summary = ThreadSummary(
        agent=agent_code,
        upto_message_count=len(thread_snapshot),
        text=text.strip(),
        created_at=datetime.now(UTC),
    )
    try:
        await repo.patch_summary(sid, agent_code, summary)
    except Exception:
        logger.exception("summary: patch_summary failed for %s/%s", sid, agent_code)
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_handoff_summary.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/handoff/summary.py tests/unit/refactor/test_handoff_summary.py
git commit -m "feat(refactor): async summarize_and_persist with patch_summary"
```

---

## Task 18: RAG adapter

**Files:**
- Create: `src/noble_agent_refactor/rag/adapter.py`
- Test: `tests/unit/refactor/test_rag_adapter.py`

- [ ] **Step 1: Viết test**

Create `tests/unit/refactor/test_rag_adapter.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from noble_agent_refactor.rag.adapter import RagAdapter
from noble_agent_refactor.storage.models import Customer


async def test_search_delegates_to_fast_talker():
    fast = MagicMock()
    fast.get_context = AsyncMock(return_value="ctx-block")
    adapter = RagAdapter(fast_talker=fast, slow_thinker=None)
    out = await adapter.search(query="giá", project_filter="NCLB")
    assert out == "ctx-block"
    fast.get_context.assert_awaited_once_with(query="giá", project_filter="NCLB")


async def test_search_uses_empty_string_when_filter_none():
    fast = MagicMock()
    fast.get_context = AsyncMock(return_value="x")
    adapter = RagAdapter(fast_talker=fast, slow_thinker=None)
    await adapter.search(query="q", project_filter=None)
    fast.get_context.assert_awaited_once_with(query="q", project_filter="")


async def test_prefetch_skipped_when_slow_thinker_none():
    adapter = RagAdapter(fast_talker=MagicMock(), slow_thinker=None)
    # Should not raise
    await adapter.prefetch("sid", "user said something", Customer())


async def test_prefetch_publishes_to_stream():
    slow = MagicMock()
    stream = MagicMock()
    stream.publish_user_utterance = AsyncMock()
    slow.stream = stream
    adapter = RagAdapter(fast_talker=MagicMock(), slow_thinker=slow)
    await adapter.prefetch("sid", "muốn 3 tỉ", Customer(project_interest="NCLB"))
    stream.publish_user_utterance.assert_awaited_once()
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_rag_adapter.py -v
```

- [ ] **Step 3: Implement**

Create `src/noble_agent_refactor/rag/adapter.py`:

```python
"""Thin adapter over noble_agent.agent.rag.FastTalker + SlowThinker."""
from __future__ import annotations

import logging

from noble_agent_refactor.storage.models import Customer

logger = logging.getLogger("noble_agent_refactor.rag")


class RagAdapter:
    def __init__(self, fast_talker, slow_thinker):
        self._fast = fast_talker
        self._slow = slow_thinker

    async def search(self, query: str, project_filter: str | None) -> str:
        try:
            return await self._fast.get_context(query=query, project_filter=project_filter or "")
        except Exception:
            logger.exception("rag.search failed")
            return ""

    async def prefetch(self, sid: str, user_text: str, customer: Customer) -> None:
        if self._slow is None:
            return
        try:
            stream = getattr(self._slow, "stream", None)
            if stream and hasattr(stream, "publish_user_utterance"):
                await stream.publish_user_utterance(
                    session_id=sid,
                    text=user_text,
                    project_filter=customer.project_interest or "",
                )
        except Exception:
            logger.exception("rag.prefetch failed")
```

> Note: `noble_agent.agent.rag.conversation_stream.ConversationStream` exposes
> `publish_user_utterance` (or similar). If the API differs, adjust here only —
> the adapter is the single integration point. See
> `src/noble_agent/agent/rag/conversation_stream.py` for the actual signature.

- [ ] **Step 4: Verify signature against existing code**

```bash
grep -E "def (publish|publish_user)" src/noble_agent/agent/rag/conversation_stream.py
```

If the method has a different name (e.g. `publish` taking an event), update `adapter.py` and the test together to match — keep test + impl in sync.

- [ ] **Step 5: Run — expect pass**

```bash
pytest tests/unit/refactor/test_rag_adapter.py -v
```
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent_refactor/rag/adapter.py tests/unit/refactor/test_rag_adapter.py
git commit -m "feat(refactor): RagAdapter wrapping FastTalker + SlowThinker"
```

---

## Task 19: Orchestrator (TurnRunner)

**Files:**
- Create: `src/noble_agent_refactor/orchestrator.py`
- Test: `tests/unit/refactor/test_orchestrator.py`

- [ ] **Step 1: Viết test integration (fake LLM + fakeredis)**

Create `tests/unit/refactor/test_orchestrator.py`:

```python
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fakeredis.aioredis import FakeRedis

from noble_agent_refactor.agents.registry import AgentRegistry
from noble_agent_refactor.config import RefactorSettings
from noble_agent_refactor.orchestrator import TurnRunner
from noble_agent_refactor.storage.repo import StateRepo


@pytest.fixture
def registry():
    defs = Path(__file__).resolve().parents[3] / "src" / "noble_agent_refactor" / "definitions"
    return AgentRegistry(defs)


def _tc(name, args, tc_id="t1"):
    return {"id": tc_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedLLM:
    """Per-agent-code script of (content, tool_calls) responses, consumed in order."""
    def __init__(self, scripts_by_code):
        self._scripts = {k: list(v) for k, v in scripts_by_code.items()}
        self._current = None

    def set_current_agent(self, code):
        self._current = code

    async def stream_completion(self, *, messages, tools, model, temperature, max_tokens, on_token):
        # Determine current agent from system prompt content
        sys_content = messages[0]["content"]
        if "lễ tân" in sys_content.lower() or "Manager" in sys_content:
            code = "MA"
        elif "tư vấn bán hàng" in sys_content.lower() or "Consultant" in sys_content:
            code = "CA"
        else:
            code = "SA"
        content, tcs = self._scripts[code].pop(0)
        return content, tcs

    async def complete_once(self, *, messages, model, temperature, max_tokens):
        return "auto-briefing text"


class FakeRag:
    async def search(self, query, project_filter):
        return f"rag:{query}/{project_filter}"
    async def get_context(self, query, project_filter):
        return f"ctx:{query}/{project_filter}"


class RecorderCallbacks:
    def __init__(self):
        self.tokens = []
        self.switches = []
        self.tool_starts = []
        self.done = False

    async def on_token(self, t): self.tokens.append(t)
    async def on_tool_start(self, n, a): self.tool_starts.append((n, a))
    async def on_tool_done(self, n, r): ...
    async def on_agent_switch(self, **kw): self.switches.append(kw)
    async def on_done(self): self.done = True


def _make_runner(registry, llm, settings_overrides=None):
    redis = FakeRedis(decode_responses=False)
    settings = RefactorSettings()
    if settings_overrides:
        for k, v in settings_overrides.items():
            setattr(settings, k, v)
    repo = StateRepo(redis_client=redis, default_agent=settings.default_agent,
                     ttl_seconds=settings.session_ttl_seconds)
    rag = FakeRag()
    rag.search = AsyncMock(return_value="rag-hits")
    rag.prefetch = AsyncMock()
    return TurnRunner(repo=repo, registry=registry, llm=llm, rag=rag, settings=settings), repo


async def test_first_turn_uses_default_agent(registry):
    llm = ScriptedLLM({"MA": [("Chào anh!", None)], "CA": [], "SA": []})
    runner, repo = _make_runner(registry, llm)
    cb = RecorderCallbacks()
    await runner.handle_turn("s1", "hello", cb)
    assert cb.tokens == [] or cb.done  # tokens delivered via on_token in real client; ScriptedLLM doesn't stream
    meta, _, state = await repo.load("s1")
    assert meta.active_agent == "MA"
    # User msg + assistant msg
    assert len(state.threads["MA"]) == 2


async def test_same_turn_handoff_chain(registry):
    llm = ScriptedLLM({
        "MA": [("Em chuyển sang tư vấn.",
                [_tc("switch_agent", {"target": "CA", "reason": "khách muốn tư vấn"})])],
        "CA": [("Chào anh, em là Luna.", None)],
        "SA": [],
    })
    runner, repo = _make_runner(registry, llm)
    cb = RecorderCallbacks()
    await runner.handle_turn("s2", "anh muốn tư vấn nhà", cb)
    meta, _, state = await repo.load("s2")
    assert meta.active_agent == "CA"
    assert len(cb.switches) == 1
    assert cb.switches[0]["to"] == "CA"
    # CA thread has user msg propagated? No — user only goes into active thread (MA at turn start)
    assert len(state.threads["MA"]) >= 2   # user + assistant w/ switch_agent tool call + tool result
    assert len(state.threads["CA"]) >= 1   # CA's assistant msg


async def test_stickiness_on_followup_turn(registry):
    # First turn: MA→CA. Second turn: user replies; should stick to CA without re-routing.
    llm = ScriptedLLM({
        "MA": [("ok",
                [_tc("switch_agent", {"target": "CA", "reason": "x", "briefing": "khách muốn 3 tỉ"})])],
        "CA": [
            ("Hi An, anh nói thêm nhu cầu nhé.", None),
            ("Dạ 3 tỉ thì em đề xuất...", None),
        ],
        "SA": [],
    })
    runner, repo = _make_runner(registry, llm)
    await runner.handle_turn("s3", "muốn mua nhà 3 tỉ", RecorderCallbacks())
    await runner.handle_turn("s3", "phòng 2 ngủ", RecorderCallbacks())
    meta, _, state = await repo.load("s3")
    assert meta.active_agent == "CA"
    # User's 2nd message should be in CA thread, not MA
    user_msgs_in_ca = [m for m in state.threads["CA"] if m.role == "user"]
    assert any("phòng 2 ngủ" in m.content for m in user_msgs_in_ca)


async def test_auto_briefing_when_agent_omits(registry):
    llm = ScriptedLLM({
        "MA": [("chuyển nhé",
                [_tc("switch_agent", {"target": "SA", "reason": "hỏi sổ"})])],
        "CA": [],
        "SA": [("Em Hân đây.", None)],
    })
    runner, repo = _make_runner(registry, llm)
    await runner.handle_turn("s4", "em muốn hỏi sổ hồng", RecorderCallbacks())
    _, _, state = await repo.load("s4")
    assert state.briefings["SA"].text == "auto-briefing text"


async def test_chain_depth_cap(registry):
    # MA→CA→SA→… should stop at max_handoff_chain
    llm = ScriptedLLM({
        "MA": [("", [_tc("switch_agent", {"target": "CA", "reason": "x"})])],
        "CA": [("", [_tc("switch_agent", {"target": "SA", "reason": "y"})])],
        "SA": [("", [_tc("switch_agent", {"target": "CA", "reason": "z"})])],
    })
    runner, repo = _make_runner(registry, llm, settings_overrides={"max_handoff_chain": 2})
    cb = RecorderCallbacks()
    await runner.handle_turn("s5", "hi", cb)
    # Should have made at most 2 switches and stopped
    assert len(cb.switches) <= 2
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_orchestrator.py -v
```

- [ ] **Step 3: Implement TurnRunner**

Create `src/noble_agent_refactor/orchestrator.py`:

```python
"""TurnRunner — entry point per user turn. Owns active-agent stickiness + handoff chain."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Protocol

from noble_agent_refactor.agents.runner import HandoffRequest, run_agent_turn
from noble_agent_refactor.handoff.briefing import auto_generate_briefing
from noble_agent_refactor.handoff.summary import summarize_and_persist
from noble_agent_refactor.storage.models import Briefing, ThreadMessage
from noble_agent_refactor.tools.dispatcher import ToolDispatcher

logger = logging.getLogger("noble_agent_refactor.orchestrator")


class TurnCallbacks(Protocol):
    async def on_token(self, token: str) -> None: ...
    async def on_tool_start(self, name: str, args: dict) -> None: ...
    async def on_tool_done(self, name: str, result: str) -> None: ...
    async def on_agent_switch(self, *, from_: str, to: str, reason: str) -> None: ...
    async def on_done(self) -> None: ...


class TurnRunner:
    def __init__(self, *, repo, registry, llm, rag, settings):
        self._repo = repo
        self._registry = registry
        self._llm = llm
        self._rag = rag
        self._settings = settings

    async def handle_turn(self, sid: str, user_text: str, callbacks: TurnCallbacks) -> None:
        meta, customer, state = await self._repo.load(sid)
        active = meta.active_agent

        # Append user message to the active agent's thread
        state.threads[active].append(ThreadMessage(role="user", content=user_text))

        # Fire SlowThinker prefetch (best-effort)
        if self._settings.enable_slow_thinker and self._rag is not None:
            asyncio.create_task(self._rag.prefetch(sid, user_text, customer))

        await self._run_with_handoffs(sid, active, meta, customer, state, callbacks, depth=0)

        meta.last_active = datetime.now(UTC)
        await self._repo.save_all(sid, meta, customer, state)
        await callbacks.on_done()

    async def _run_with_handoffs(self, sid, agent_code, meta, customer, state, callbacks, depth):
        if depth > self._settings.max_handoff_chain:
            logger.warning("orchestrator: max_handoff_chain reached at %s", agent_code)
            meta.active_agent = agent_code
            return

        agent = self._registry.get(agent_code)
        dispatcher = ToolDispatcher(
            state=state, customer=customer, rag=self._rag,
            callbacks=callbacks, session_id=sid,
        )

        handoff = await run_agent_turn(
            agent=agent,
            thread=state.threads[agent_code],
            customer=customer,
            briefing=state.briefings.get(agent_code),
            prior_summary=state.summaries.get(agent_code),
            llm=self._llm,
            dispatcher=dispatcher,
            callbacks=callbacks,
        )

        if handoff is None:
            meta.active_agent = agent_code
            return

        await self._apply_handoff(sid, agent_code, handoff, state, customer, callbacks)
        meta.active_agent = handoff.target
        await self._run_with_handoffs(sid, handoff.target, meta, customer, state, callbacks, depth + 1)

    async def _apply_handoff(self, sid, agent_code, handoff: HandoffRequest, state, customer, callbacks):
        briefing_text = handoff.briefing
        if not briefing_text:
            try:
                briefing_text = await auto_generate_briefing(
                    state.threads[agent_code], customer, handoff.reason, self._llm,
                    lookback=self._settings.auto_briefing_lookback,
                    model=self._settings.briefing_model or self._settings.summary_model,
                )
            except Exception:
                logger.exception("orchestrator: auto_briefing failed")
                briefing_text = f"(auto-briefing failed) reason={handoff.reason}"

        state.briefings[handoff.target] = Briefing(
            from_agent=agent_code,
            reason=handoff.reason,
            text=briefing_text,
            created_at=datetime.now(UTC),
        )

        if len(state.threads[agent_code]) > self._settings.summary_threshold_K:
            snapshot = list(state.threads[agent_code])
            asyncio.create_task(
                summarize_and_persist(
                    sid=sid, agent_code=agent_code, thread_snapshot=snapshot,
                    llm=self._llm, repo=self._repo, model=self._settings.summary_model,
                )
            )

        await callbacks.on_agent_switch(from_=agent_code, to=handoff.target, reason=handoff.reason)
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_orchestrator.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/orchestrator.py tests/unit/refactor/test_orchestrator.py
git commit -m "feat(refactor): TurnRunner — active-agent stickiness + handoff chain"
```

---

## Task 20: Facade NobleAgent

**Files:**
- Modify: `src/noble_agent_refactor/__init__.py`
- Create: `src/noble_agent_refactor/facade.py`
- Test: `tests/unit/refactor/test_facade.py`

- [ ] **Step 1: Viết test**

Create `tests/unit/refactor/test_facade.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


async def test_facade_create_and_stream():
    from noble_agent_refactor.facade import NobleAgent

    # Patch _build_runner to avoid touching real Redis/LLM
    fake_runner = MagicMock()

    async def fake_handle(sid, user_text, cb):
        await cb.on_token("hello")
        await cb.on_done()
    fake_runner.handle_turn = fake_handle

    with patch("noble_agent_refactor.facade._build_runner", return_value=fake_runner):
        agent = await NobleAgent.create("sess-1")
        tokens = []
        async def on_token(t): tokens.append(t)
        full = await agent.stream_response("hi", on_token=on_token)
        assert tokens == ["hello"]
        assert full == "hello"


async def test_facade_callbacks_all_optional():
    from noble_agent_refactor.facade import NobleAgent

    fake_runner = MagicMock()
    async def fake_handle(sid, user_text, cb):
        await cb.on_agent_switch(from_="MA", to="CA", reason="x")
        await cb.on_tool_start("noble_search", {"query": "q"})
        await cb.on_tool_done("noble_search", "result")
        await cb.on_done()
    fake_runner.handle_turn = fake_handle

    with patch("noble_agent_refactor.facade._build_runner", return_value=fake_runner):
        agent = await NobleAgent.create("sess-2")
        # No callbacks supplied — should not crash
        out = await agent.stream_response("hi")
        assert out == ""
```

- [ ] **Step 2: Run — expect ImportError**

```bash
pytest tests/unit/refactor/test_facade.py -v
```

- [ ] **Step 3: Implement facade**

Create `src/noble_agent_refactor/facade.py`:

```python
"""Drop-in facade replacing StreamingLLM in transport (text_chat.py, voice loop)."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

from noble_agent_refactor.agents.registry import AgentRegistry
from noble_agent_refactor.config import get_settings
from noble_agent_refactor.llm.client import StreamingClient
from noble_agent_refactor.orchestrator import TurnRunner
from noble_agent_refactor.rag.adapter import RagAdapter
from noble_agent_refactor.storage.repo import StateRepo

logger = logging.getLogger("noble_agent_refactor.facade")

_runner_singleton: TurnRunner | None = None


def _build_runner() -> TurnRunner:
    """Construct runner singleton — wire registry, llm client, rag adapter, repo."""
    settings = get_settings()

    # Registry
    defs_dir = Path(__file__).resolve().parent / "definitions"
    registry = AgentRegistry(defs_dir)

    # LLM providers — reuse env vars from legacy core (OPENAI_API_KEY, GEMINI_API_KEY)
    providers: list[tuple[str, object]] = []
    try:
        import openai
        if os.getenv("OPENAI_API_KEY"):
            providers.append(("openai",
                              openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))))
        if os.getenv("GEMINI_API_KEY"):
            providers.append(("gemini",
                              openai.AsyncOpenAI(
                                  api_key=os.getenv("GEMINI_API_KEY"),
                                  base_url="https://generativelanguage.googleapis.com/v1beta/openai/")))
    except ImportError:
        logger.error("openai SDK not installed")
    if not providers:
        raise RuntimeError("No LLM providers configured (OPENAI_API_KEY or GEMINI_API_KEY)")

    llm = StreamingClient(providers=providers)

    # RAG: reuse existing FastTalker + SlowThinker constructed by the noble_agent app.
    # FastTalker requires (embeddings, vector_store, cache, stream, metrics, ...) — fetch the
    # already-built instance from the noble_agent app singleton instead of re-constructing.
    # If no singleton accessor exists yet, expose one (e.g. `noble_agent.agent.rag.get_fast_talker()`)
    # — that small addition belongs to this task, not a follow-up.
    from noble_agent.agent.rag import get_fast_talker  # add if missing
    fast = get_fast_talker()
    slow = None  # SlowThinker startup is owned by the existing app; pass None for now (prefetch becomes no-op)
    rag = RagAdapter(fast_talker=fast, slow_thinker=slow)

    # Redis
    from noble_agent.storage.connection import get_connection_manager
    redis_client = get_connection_manager().redis
    repo = StateRepo(
        redis_client=redis_client,
        default_agent=settings.default_agent,
        ttl_seconds=settings.session_ttl_seconds,
    )

    return TurnRunner(repo=repo, registry=registry, llm=llm, rag=rag, settings=settings)


def _get_runner() -> TurnRunner:
    global _runner_singleton
    if _runner_singleton is None:
        _runner_singleton = _build_runner()
    return _runner_singleton


class _Callbacks:
    """Adapter wrapping the loose callback set transport passes in."""
    def __init__(self, *, on_token, on_tool_start, on_tool_done, on_agent_switch, sink):
        self._on_token = on_token
        self._on_tool_start = on_tool_start
        self._on_tool_done = on_tool_done
        self._on_agent_switch = on_agent_switch
        self._sink = sink

    async def on_token(self, token: str):
        self._sink.append(token)
        if self._on_token:
            await self._on_token(token)

    async def on_tool_start(self, name, args):
        if self._on_tool_start:
            await self._on_tool_start(name, args)

    async def on_tool_done(self, name, result):
        if self._on_tool_done:
            await self._on_tool_done(name, result)

    async def on_agent_switch(self, *, from_, to, reason):
        if self._on_agent_switch:
            await self._on_agent_switch(from_=from_, to=to, reason=reason)

    async def on_done(self): ...


class NobleAgent:
    """Drop-in replacement for noble_agent.agent.llm.streaming.StreamingLLM."""

    def __init__(self, session_id: str, runner: TurnRunner):
        self.session_id = session_id
        self._runner = runner

    @classmethod
    async def create(cls, session_id: str, customer: dict | None = None) -> "NobleAgent":
        runner = _get_runner()
        # `customer` arg: legacy StreamingLLM took initial customer for prefilling.
        # In refactor, customer is loaded from Redis; ignore the arg here.
        return cls(session_id=session_id, runner=runner)

    async def stream_response(
        self,
        user_text: str,
        *,
        on_token: Callable[[str], Awaitable[None]] | None = None,
        on_tool_start: Callable[[str, dict], Awaitable[None]] | None = None,
        on_tool_done: Callable[[str, str], Awaitable[None]] | None = None,
        on_agent_switch: Callable | None = None,
    ) -> str:
        sink: list[str] = []
        cb = _Callbacks(
            on_token=on_token,
            on_tool_start=on_tool_start,
            on_tool_done=on_tool_done,
            on_agent_switch=on_agent_switch,
            sink=sink,
        )
        await self._runner.handle_turn(self.session_id, user_text, cb)
        return "".join(sink)


def reset_runner_for_tests() -> None:
    global _runner_singleton
    _runner_singleton = None
```

Modify `src/noble_agent_refactor/__init__.py`:

```python
"""Noble Agent core refactor (rev 2). See docs/superpowers/specs/2026-06-01-noble-agent-refactor-design.md."""

__all__ = ["NobleAgent", "get_settings"]

from noble_agent_refactor.config import get_settings
from noble_agent_refactor.facade import NobleAgent
```

- [ ] **Step 4: Run — expect pass**

```bash
pytest tests/unit/refactor/test_facade.py -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent_refactor/facade.py src/noble_agent_refactor/__init__.py tests/unit/refactor/test_facade.py
git commit -m "feat(refactor): NobleAgent facade drop-in for StreamingLLM"
```

---

## Task 21: Wire facade into text_chat (feature-flagged)

**Files:**
- Modify: `src/noble_agent/server/text_chat.py`
- Test: `tests/unit/test_text_chat.py` (extend existing)

- [ ] **Step 1: Inspect current text_chat.py for the LLM creation site**

```bash
grep -n "StreamingLLM\|stream_response\|llm" src/noble_agent/server/text_chat.py | head -30
```

Note exact line numbers where `StreamingLLM.create(...)` and `llm.stream_response(...)` are called.

- [ ] **Step 2: Add feature-flag-gated import**

Edit `src/noble_agent/server/text_chat.py` at the import section — replace direct import with conditional factory:

```python
# Before (somewhere near top):
# from noble_agent.agent.llm.streaming import StreamingLLM

# After:
async def _create_llm(session_id: str):
    from noble_agent_refactor.config import get_settings
    if get_settings().use_refactor_core:
        from noble_agent_refactor import NobleAgent
        return await NobleAgent.create(session_id)
    from noble_agent.agent.llm.streaming import StreamingLLM
    return await StreamingLLM.create(session_id)
```

Then replace the existing `llm = await StreamingLLM.create(session_id)` line with `llm = await _create_llm(session_id)`.

- [ ] **Step 3: Add test toggling the flag**

Add to `tests/unit/test_text_chat.py`:

```python
async def test_text_chat_uses_refactor_when_flag_on(monkeypatch):
    from unittest.mock import AsyncMock, patch

    monkeypatch.setenv("USE_REFACTOR_CORE", "true")
    from noble_agent_refactor.config import reset_settings_for_tests
    reset_settings_for_tests()

    fake_agent = AsyncMock()
    fake_agent.stream_response = AsyncMock(return_value="hi")

    with patch("noble_agent_refactor.NobleAgent.create",
               new=AsyncMock(return_value=fake_agent)) as mock_create:
        from noble_agent.server import text_chat
        llm = await text_chat._create_llm("s1")
        assert llm is fake_agent
        mock_create.assert_awaited_once()


async def test_text_chat_uses_legacy_when_flag_off(monkeypatch):
    from unittest.mock import AsyncMock, patch

    monkeypatch.setenv("USE_REFACTOR_CORE", "false")
    from noble_agent_refactor.config import reset_settings_for_tests
    reset_settings_for_tests()

    fake = AsyncMock()
    with patch("noble_agent.agent.llm.streaming.StreamingLLM.create",
               new=AsyncMock(return_value=fake)):
        from noble_agent.server import text_chat
        llm = await text_chat._create_llm("s2")
        assert llm is fake
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/unit/test_text_chat.py -v
```
Expected: existing tests still pass + 2 new tests pass.

- [ ] **Step 5: Manual smoke (optional)**

```bash
USE_REFACTOR_CORE=true scripts/run.sh --no-reload &
# open http://localhost:8766/chat in browser, send "muốn mua nhà 3 tỉ"
# expect: response stream + agent_switch event in trace
```

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/server/text_chat.py tests/unit/test_text_chat.py
git commit -m "feat(refactor): wire NobleAgent facade into text_chat behind USE_REFACTOR_CORE flag"
```

---

## Task 22: End-to-end integration test

**Files:**
- Create: `tests/integration/refactor/test_e2e_chat.py`
- Create: `tests/integration/refactor/__init__.py`

- [ ] **Step 1: Viết E2E test (no audio, just chat loop)**

Create `tests/integration/refactor/__init__.py` (empty).

Create `tests/integration/refactor/test_e2e_chat.py`:

```python
"""E2E: orchestrator → repo → registry, with fake LLM + fakeredis.

Reproduces the plan-1.md failure scenario and asserts it does NOT happen.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis

from noble_agent_refactor.agents.registry import AgentRegistry
from noble_agent_refactor.config import RefactorSettings
from noble_agent_refactor.orchestrator import TurnRunner
from noble_agent_refactor.storage.repo import StateRepo


def _tc(name, args, tc_id):
    return {"id": tc_id, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedLLM:
    def __init__(self, by_code):
        self._scripts = {k: list(v) for k, v in by_code.items()}

    async def stream_completion(self, *, messages, tools, model, temperature, max_tokens, on_token):
        sys = messages[0]["content"]
        if "Manager" in sys or "lễ tân" in sys.lower():
            code = "MA"
        elif "Consultant" in sys or "tư vấn bán hàng" in sys.lower():
            code = "CA"
        else:
            code = "SA"
        return self._scripts[code].pop(0)

    async def complete_once(self, *, messages, model, temperature, max_tokens):
        return "(auto)"


class FakeRag:
    async def search(self, query, project_filter): return f"rag:{query}"
    async def prefetch(self, sid, text, customer): ...


class NoopCB:
    async def on_token(self, t): ...
    async def on_tool_start(self, n, a): ...
    async def on_tool_done(self, n, r): ...
    async def on_agent_switch(self, **kw): ...
    async def on_done(self): ...


async def test_plan1_phone_scenario_does_not_lose_context():
    """Plan-1.md scenario:
       1) user: 'muốn mua nhà 3 tỉ cần tư vấn' → MA → CA
       2) CA: 'cho em xin số điện thoại'
       3) user: '0901234567'  ← old router would mis-classify and lose context
       4) CA must receive this user msg + still know about '3 tỉ'
    """
    sid = "plan1"
    registry = AgentRegistry(Path("src/noble_agent_refactor/definitions"))
    redis = FakeRedis(decode_responses=False)
    repo = StateRepo(redis, default_agent="MA", ttl_seconds=3600)
    settings = RefactorSettings()

    llm = ScriptedLLM({
        "MA": [
            ("Để em chuyển sang tư vấn ạ.",
             [_tc("switch_agent", {"target": "CA", "reason": "khách muốn tư vấn",
                                    "briefing": "Khách quan tâm mua nhà ngân sách 3 tỉ"}, "t1")]),
        ],
        "CA": [
            ("Anh cho em xin số điện thoại để tiện liên hệ ạ.", None),
            # Turn 2: receives "0901234567"
            ("",
             [_tc("update_customer", {"field": "phone", "value": "0901234567"}, "t2")]),
            ("Em đã ghi nhận SĐT 0901234567. Em đề xuất căn 3 tỉ phù hợp nhé.", None),
        ],
        "SA": [],
    })

    runner = TurnRunner(repo=repo, registry=registry, llm=llm, rag=FakeRag(), settings=settings)

    # Turn 1
    await runner.handle_turn(sid, "muốn mua nhà 3 tỉ cần tư vấn", NoopCB())
    meta, customer, state = await repo.load(sid)
    assert meta.active_agent == "CA"
    assert state.briefings["CA"].text  # briefing present (3 tỉ context)

    # Turn 2 — user replies with just a phone number
    await runner.handle_turn(sid, "0901234567", NoopCB())
    meta2, customer2, state2 = await repo.load(sid)
    # Stickiness: still on CA, NOT bounced to MA
    assert meta2.active_agent == "CA"
    # Phone captured
    assert customer2.phone == "0901234567"
    # CA's thread retains both user messages + briefing context
    user_msgs = [m.content for m in state2.threads["CA"] if m.role == "user"]
    assert "0901234567" in user_msgs
    # Final assistant message references the 3 tỉ context
    last_assistant = [m for m in state2.threads["CA"] if m.role == "assistant" and m.content][-1]
    assert "3 tỉ" in last_assistant.content
```

- [ ] **Step 2: Run E2E**

```bash
pytest tests/integration/refactor/test_e2e_chat.py -v
```
Expected: 1 passed.

- [ ] **Step 3: Run full refactor test suite**

```bash
pytest tests/unit/refactor tests/integration/refactor -v
```
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/refactor
git commit -m "test(refactor): e2e plan-1 phone-context scenario"
```

---

## Task 23: Lint + ruff sweep

**Files:**
- (all of `src/noble_agent_refactor/`)

- [ ] **Step 1: Run ruff**

```bash
make lint
```

- [ ] **Step 2: Auto-fix what's auto-fixable**

```bash
ruff check --fix src/noble_agent_refactor tests/unit/refactor tests/integration/refactor
ruff format src/noble_agent_refactor tests/unit/refactor tests/integration/refactor
```

- [ ] **Step 3: Re-run lint to confirm clean**

```bash
make lint
```
Expected: no errors.

- [ ] **Step 4: Run full unit suite one more time**

```bash
pytest tests/unit/refactor tests/integration/refactor -v
```
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore(refactor): ruff sweep on noble_agent_refactor"
```

---

## Task 24: Update CLAUDE.md to mention the refactor package

**Files:**
- Modify: `CLAUDE.md` (root)

- [ ] **Step 1: Add a short subsection under Architecture**

Edit `CLAUDE.md` and add (right after the existing "### Layering" table or at the end of the Architecture section):

```markdown
### Refactor package (noble_agent_refactor)

A clean rewrite of the multi-agent core lives in [src/noble_agent_refactor/](src/noble_agent_refactor/). It implements active-agent stickiness, per-agent threads with async summary, and definitions-driven agent prompts. Enable via `USE_REFACTOR_CORE=true` in `.env`. Spec: [docs/superpowers/specs/2026-06-01-noble-agent-refactor-design.md](docs/superpowers/specs/2026-06-01-noble-agent-refactor-design.md). The legacy `agent/` package stays in place until cutover.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: mention noble_agent_refactor + USE_REFACTOR_CORE flag in CLAUDE.md"
```

---

## Done.

When all 24 tasks are checked off, the refactor package is feature-complete behind the `USE_REFACTOR_CORE` flag. Legacy `noble_agent` continues to handle production traffic until the operator flips the flag and validates in `/chat`. After 1 stable sprint, the cleanup pass (delete legacy streaming.py, router, V5/V10 inject, outbound) becomes a separate plan.
