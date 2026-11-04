# `service_customer` (CSBH) Tool — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm custom tenant tool `service_customer` cho noble — trả lời chính sách bán hàng/khuyến mãi/vay vốn của một dự án từ các point `category=csbh` trong Qdrant `media_v3`, đưa caption vào context LLM + gửi media cho app; gỡ `get_project_financial` khỏi offered list.

**Architecture:** Tool nằm ở `tenants/noble/tools/service_customer.py`, tự đăng ký qua `@tool(tenant="noble")`. Truy vấn Qdrant bằng `scroll` (filter `project_id`+`category=csbh`, không vector), tái dùng client KB + `media_data._map_items` cho `items[]`. `caption` vào `context` (giữ trong history); `items[]` bị strip khỏi history qua `_DISPLAY_ITEMS_TOOLS` → caption không lặp. Không có csbh/lỗi → payload chứa `ESCALATE_SIGNAL` để dispatcher auto-escalate.

**Tech Stack:** Python 3.11+, qdrant-client (import-lazy), pytest (asyncio_mode=auto), pydantic-settings.

## Global Constraints

- Branch: `feat/refactor2`. KHÔNG đụng `develop`. Không push/PR khi chưa được yêu cầu.
- Tool phải theo kiến trúc SaaS: file nằm trong `src/noble_agent/tenants/noble/tools/`, đăng ký bằng decorator `@tool(...)`. Không sửa `tenant/loader.py`.
- Tool **không bao giờ raise** ra ngoài (quy ước tool-boundary).
- `ESCALATE_SIGNAL` = `"Thông tin đã được chuyển đến chuyên viên tư vấn"` (import từ `noble_agent.data.providers.base`, không hard-code chuỗi).
- Câu handoff trả cho khách phải đúng nguyên văn: `"Thông tin câu hỏi của anh chị đã được gửi cho bên sale ạ"`.
- BẤT BIẾN: caption chỉ xuất hiện **đúng 1 lần** trong `state.history` (trường `context`); `items[]` bị strip.
- Ruff: line-length 120, target py311. Chạy `make lint` trên file đã sửa.
- KHÔNG xoá code `get_project_financial` (chỉ gỡ khỏi `manifest.enabled`).
- Spec: `docs/superpowers/specs/2026-07-27-service-customer-csbh-tool-design.md`.

---

### Task 1: `build_schemas` cấp schema cho custom tenant tool

Hiện `build_schemas` chỉ dựng từ dict `SCHEMAS` tĩnh → custom tool đăng ký được để dispatch nhưng schema không tới LLM. Sửa để, với mỗi tên được enable không có trong `SCHEMAS`, lấy schema từ registry của tenant hiện tại.

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py` (hàm `build_schemas`, quanh dòng 626–634)
- Test: `tests/unit/unified/test_build_schemas.py`

**Interfaces:**
- Consumes: `registry.resolve(tenant, name) -> ToolSpec | None` (đã có, `agent/tools/registry.py`); `ToolSpec.schema: dict`; `get_tenant_context().tenant_id: str`.
- Produces: `build_schemas(names)` nay bao gồm schema của custom tool khi tenant hiện tại có đăng ký tool đó; thứ tự output khớp `names`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào cuối `tests/unit/unified/test_build_schemas.py`:

```python
from noble_agent.agent.tools import registry as _reg


def test_build_schemas_offers_registered_custom_tool(patch_tool_params, monkeypatch):
    patch_tool_params(())
    # tenant hiện tại trong test env = "noble" (TENANT_ID mặc định)
    schema = {
        "type": "function",
        "function": {
            "name": "zzz_demo_tool",
            "description": "demo",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }

    async def _exec(args, **_):
        return "ok"

    _reg.register(_reg.ToolSpec(name="zzz_demo_tool", schema=schema, executor=_exec, tenant="noble"))
    try:
        out = {s["function"]["name"]: s for s in schemas.build_schemas(["booking", "zzz_demo_tool"])}
        assert "zzz_demo_tool" in out
        assert out["zzz_demo_tool"]["function"]["description"] == "demo"
    finally:
        _reg.clear_tenant_for_tests("noble")


def test_build_schemas_skips_unregistered_unknown_name(patch_tool_params):
    patch_tool_params(())
    out = schemas.build_schemas(["booking", "nope_not_a_tool"])
    names = {s["function"]["name"] for s in out}
    assert "nope_not_a_tool" not in names
    assert "booking" in names
```

- [ ] **Step 2: Chạy test xác nhận FAIL**

Run: `.venv/bin/pytest tests/unit/unified/test_build_schemas.py::test_build_schemas_offers_registered_custom_tool -v`
Expected: FAIL (`zzz_demo_tool` không có trong output).

- [ ] **Step 3: Sửa `build_schemas`**

Trong `src/noble_agent/agent/tools/schemas.py`, thay đoạn dựng `out` (dòng ~631–634) bằng loop giữ thứ tự + resolve custom tool. Đoạn hiện tại:

```python
    from noble_agent.agent.tools.custom_params import TYPE_JSON
    from noble_agent.tenant.loader import get_tenant_context

    out = [_copy.deepcopy(SCHEMAS[name]) for name in names if name in SCHEMAS]
```

Đổi thành:

```python
    from noble_agent.agent.tools import registry
    from noble_agent.agent.tools.custom_params import TYPE_JSON
    from noble_agent.tenant.loader import get_tenant_context

    try:
        _tenant_id = get_tenant_context().tenant_id
    except Exception:
        _tenant_id = "noble"

    # Static built-ins come from SCHEMAS; a name NOT in SCHEMAS is a custom
    # tenant tool — pull its schema off the registered ToolSpec so it is
    # actually OFFERED to the LLM (not just dispatchable). Order follows `names`.
    out: list[dict] = []
    for name in names:
        if name in SCHEMAS:
            out.append(_copy.deepcopy(SCHEMAS[name]))
            continue
        spec = registry.resolve(_tenant_id, name)
        if spec is not None and spec.schema:
            out.append(_copy.deepcopy(spec.schema))
```

(Giữ nguyên toàn bộ phần sau: tool_params injection, feng-shui gate, brand render, return.)

- [ ] **Step 4: Chạy test xác nhận PASS**

Run: `.venv/bin/pytest tests/unit/unified/test_build_schemas.py -v`
Expected: tất cả PASS (2 test mới + 4 test cũ).

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/agent/tools/schemas.py
git add src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_build_schemas.py
git commit -m "feat(schemas): build_schemas offers registered custom tenant tools"
```

---

### Task 2: Tool `service_customer` (Qdrant CSBH → context + items)

Đây là deliverable chính. File tool self-contained trong tenant noble.

**Files:**
- Create: `src/noble_agent/tenants/noble/tools/__init__.py` (rỗng)
- Create: `src/noble_agent/tenants/noble/tools/service_customer.py`
- Test: `tests/unit/tenant/test_service_customer.py`

**Interfaces:**
- Consumes: `qdrant_store._get_client()` (`agent/rag/qdrant_store.py`) → async client có `.scroll(collection_name, scroll_filter, with_payload, with_vectors, limit) -> (points, next_offset)`; mỗi point có `.payload: dict`. `media_data._map_items(hits: list[dict]) -> list[dict]`. `db_project_registry.code_to_name() -> dict`. `ESCALATE_SIGNAL`. Kwargs bag dispatcher: `args, customer, session_id`.
- Produces: đăng ký `ToolSpec(name="service_customer", tenant="noble", read_only=True, dirties_customer=False)` với executor trả JSON string.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/unit/tenant/test_service_customer.py`:

```python
import json
import types

import pytest

from noble_agent.data.providers.base import ESCALATE_SIGNAL


class _FakePoint:
    def __init__(self, payload):
        self.payload = payload


def _load_tool():
    # import module → decorator self-registers; return the executor fn
    import importlib
    mod = importlib.import_module("noble_agent.tenants.noble.tools.service_customer")
    return importlib.reload(mod)


def _fake_customer(project_interest=""):
    return types.SimpleNamespace(project_interest=project_interest)


def _patch_scroll(monkeypatch, points, *, raise_exc=None):
    from noble_agent.agent.rag import qdrant_store

    class _Client:
        async def scroll(self, **kwargs):
            if raise_exc:
                raise raise_exc
            return list(points), None

    monkeypatch.setattr(qdrant_store, "_get_client", lambda: _Client())


_CSBH_PAYLOAD = {
    "project_id": "VGRC",
    "category": "csbh",
    "content_type": "image",
    "caption": "Chính sách ưu đãi: thanh toán sớm 7.5%.",
    "media_url": "https://nbx-sales-dev.noble.vn/img/real/proj/qc__csbh.jpg",
    "thumb_url": "https://s3/thumb.webp",
    "content_hash": "abc",
}


async def test_csbh_present_returns_context_and_items(monkeypatch):
    _patch_scroll(monkeypatch, [_FakePoint(_CSBH_PAYLOAD)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is True
    assert "thanh toán sớm 7.5%" in out["context"]
    assert out["count"] == 1
    assert out["items"][0]["kind"] == "image"
    assert out["items"][0]["url"] == _CSBH_PAYLOAD["media_url"]


async def test_no_csbh_returns_handoff_with_escalate_signal(monkeypatch):
    _patch_scroll(monkeypatch, [])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is False
    assert out["message"] == "Thông tin câu hỏi của anh chị đã được gửi cho bên sale ạ"
    assert ESCALATE_SIGNAL in json.dumps(out, ensure_ascii=False)


async def test_qdrant_error_degrades_to_handoff(monkeypatch):
    _patch_scroll(monkeypatch, [], raise_exc=RuntimeError("qdrant down"))
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is False
    assert ESCALATE_SIGNAL in json.dumps(out, ensure_ascii=False)


async def test_missing_code_and_no_interest_is_handoff(monkeypatch):
    _patch_scroll(monkeypatch, [_FakePoint(_CSBH_PAYLOAD)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({}, customer=_fake_customer(project_interest=""), session_id="s1"))
    assert out["ok"] is False


async def test_defaults_to_customer_project_interest(monkeypatch):
    _patch_scroll(monkeypatch, [_FakePoint(_CSBH_PAYLOAD)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({}, customer=_fake_customer(project_interest="VGRC"), session_id="s1"))
    assert out["ok"] is True


async def test_caption_present_but_no_renderable_media(monkeypatch):
    payload = dict(_CSBH_PAYLOAD, media_url="", thumb_url="", content_type="pdf")
    _patch_scroll(monkeypatch, [_FakePoint(payload)])
    mod = _load_tool()
    out = json.loads(await mod.service_customer({"project_code": "VGRC"}, customer=_fake_customer(), session_id="s1"))
    assert out["ok"] is True
    assert out["items"] == []
    assert "Chính sách ưu đãi" in out["context"]
```

- [ ] **Step 2: Chạy test xác nhận FAIL**

Run: `.venv/bin/pytest tests/unit/tenant/test_service_customer.py -v`
Expected: FAIL (ModuleNotFoundError `noble_agent.tenants.noble.tools.service_customer`).

- [ ] **Step 3: Tạo package + tool**

`src/noble_agent/tenants/noble/tools/__init__.py`: file rỗng.

`src/noble_agent/tenants/noble/tools/service_customer.py`:

```python
"""Custom tool (tenant=noble): trả lời chính sách bán hàng/khuyến mãi/vay vốn
(CSBH) của một dự án từ Qdrant collection `media_v3` (category=csbh).

Đưa `caption` vào context LLM (trường `context`) + gửi media (ảnh/video) cho app
qua `items[]` (được dispatcher strip khỏi history → caption không lặp). Không có
csbh / thiếu mã / lỗi Qdrant → payload chứa ESCALATE_SIGNAL để dispatcher
auto-escalate sang CVTV/sale. Không bao giờ raise.
"""

from __future__ import annotations

import json
import logging
import os

from noble_agent.agent.rag import qdrant_store
from noble_agent.agent.tools.registry import tool
from noble_agent.data import media_data
from noble_agent.data.providers.base import ESCALATE_SIGNAL

logger = logging.getLogger("noble_agent.tenants.noble.tools.service_customer")

_COLLECTION = os.environ.get("CSBH_MEDIA_COLLECTION", "media_v3")
_SCROLL_LIMIT = 16
_HANDOFF_MSG = "Thông tin câu hỏi của anh chị đã được gửi cho bên sale ạ"

_SCHEMA = {
    "type": "function",
    "function": {
        "name": "service_customer",
        "description": (
            "Trả lời câu hỏi về CHÍNH SÁCH của một dự án: chính sách bán hàng, "
            "khuyến mãi/ưu đãi, hoặc vay vốn/hỗ trợ lãi suất. Ví dụ: khách hỏi "
            "'dự án X có chính sách vay vốn thế nào', 'ưu đãi thanh toán sớm ra sao'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project_code": {
                    "type": "string",
                    "description": "Mã dự án khách hỏi chính sách. Để trống nếu đã biết dự án khách quan tâm.",
                }
            },
            "required": [],
        },
    },
}


def _handoff() -> str:
    return json.dumps(
        {"ok": False, "note": "no_csbh", "message": _HANDOFF_MSG, "signal": ESCALATE_SIGNAL},
        ensure_ascii=False,
    )


def _scroll_filter(code: str):
    from qdrant_client import models

    return models.Filter(
        must=[
            models.FieldCondition(key="project_id", match=models.MatchValue(value=code)),
            models.FieldCondition(key="category", match=models.MatchValue(value="csbh")),
        ]
    )


@tool(name="service_customer", schema=_SCHEMA, tenant="noble", read_only=True, dirties_customer=False)
async def service_customer(args, *, customer, session_id, **_) -> str:
    code = (args.get("project_code") or "").strip().upper()
    if not code:
        code = (getattr(customer, "project_interest", "") or "").strip().upper()
    if not code:
        logger.info("[service_customer] sid=%s no project code/interest", session_id)
        return _handoff()

    try:
        client = qdrant_store._get_client()
        points, _next = await client.scroll(
            collection_name=_COLLECTION,
            scroll_filter=_scroll_filter(code),
            with_payload=True,
            with_vectors=False,
            limit=_SCROLL_LIMIT,
        )
    except Exception as exc:  # never raise out of a tool
        logger.warning("[service_customer] sid=%s code=%s scroll failed: %s", session_id, code, exc)
        return _handoff()

    payloads = [p.payload or {} for p in points]
    captions = [(pl.get("caption") or "").strip() for pl in payloads]
    captions = [c for c in captions if c]
    if not captions:
        logger.info("[service_customer] sid=%s code=%s no csbh", session_id, code)
        return _handoff()

    items = media_data._map_items(payloads)

    from noble_agent.data import db_project_registry

    project_name = db_project_registry.code_to_name().get(code) or code
    context = "\n\n---\n\n".join(captions)
    message = (
        "Dạ em gửi thông tin chính sách qua app cho anh/chị rồi ạ."
        if items
        else "Dạ em gửi thông tin chính sách cho anh/chị ạ."
    )
    logger.info("[service_customer] sid=%s code=%s captions=%d items=%d", session_id, code, len(captions), len(items))
    return json.dumps(
        {
            "ok": True,
            "project_name": project_name,
            "context": context,
            "items": items,
            "count": len(items),
            "message": message,
        },
        ensure_ascii=False,
    )
```

- [ ] **Step 4: Chạy test xác nhận PASS**

Run: `.venv/bin/pytest tests/unit/tenant/test_service_customer.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/tenants/noble/tools/service_customer.py tests/unit/tenant/test_service_customer.py
git add src/noble_agent/tenants/noble/tools/ tests/unit/tenant/test_service_customer.py
git commit -m "feat(noble): add service_customer CSBH tool (media_v3 policy answers)"
```

---

### Task 3: Strip `items[]` khỏi history cho `service_customer`

Đảm bảo caption không lặp trong context: thêm tool vào allowlist display-items.

**Files:**
- Modify: `src/noble_agent/agent/tools/dispatcher.py:36` (`_DISPLAY_ITEMS_TOOLS`)
- Test: `tests/unit/tools/test_dispatch_registry.py`

**Interfaces:**
- Consumes: `dispatcher._strip_display_items(name, result) -> str` (đã có).
- Produces: `_DISPLAY_ITEMS_TOOLS == {"send_media", "service_customer"}`.

- [ ] **Step 1: Viết test thất bại**

Thêm vào `tests/unit/tools/test_dispatch_registry.py`:

```python
import json

from noble_agent.agent.tools import dispatcher as _disp


def test_service_customer_items_stripped_from_history():
    result = json.dumps(
        {"ok": True, "context": "Chính sách X", "items": [{"kind": "image", "url": "u", "label": "Chính sách X"}], "count": 1},
        ensure_ascii=False,
    )
    stripped = _disp._strip_display_items("service_customer", result)
    data = json.loads(stripped)
    assert "items" not in data
    # caption chỉ còn 1 lần (trong context), không lặp qua item label
    assert stripped.count("Chính sách X") == 1
    assert data["context"] == "Chính sách X"
```

- [ ] **Step 2: Chạy test xác nhận FAIL**

Run: `.venv/bin/pytest tests/unit/tools/test_dispatch_registry.py::test_service_customer_items_stripped_from_history -v`
Expected: FAIL (`items` vẫn còn — `service_customer` chưa trong allowlist).

- [ ] **Step 3: Thêm vào allowlist**

Trong `src/noble_agent/agent/tools/dispatcher.py`, dòng 36:

```python
_DISPLAY_ITEMS_TOOLS = {"send_media"}
```

Đổi thành:

```python
_DISPLAY_ITEMS_TOOLS = {"send_media", "service_customer"}
```

- [ ] **Step 4: Chạy test xác nhận PASS**

Run: `.venv/bin/pytest tests/unit/tools/test_dispatch_registry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/dispatcher.py tests/unit/tools/test_dispatch_registry.py
git commit -m "feat(dispatcher): strip service_customer items[] from LLM history"
```

---

### Task 4: Manifest swap + RULES.md + integration

Gỡ `get_project_financial`, thêm `service_customer` vào offered list; cập nhật RULES; test agent load ra đúng bộ tool.

**Files:**
- Modify: `src/noble_agent/tenants/noble/manifest.toml` (`[tools].enabled`)
- Modify: `src/noble_agent/tenants/noble/persona/RULES.md` (dòng 18, 140, 150–151)
- Test: `tests/unit/tenant/test_service_customer_integration.py`

**Interfaces:**
- Consumes: `load_agent_def(persona_dir, *, tool_names, brand=...)` → `AgentDef.tool_schemas`; `get_tenant_context().enabled_tools`.
- Produces: noble offered set chứa `service_customer`, không chứa `get_project_financial`.

- [ ] **Step 1: Viết test thất bại**

Tạo `tests/unit/tenant/test_service_customer_integration.py`:

```python
import importlib

from noble_agent.tenant.loader import get_tenant_context, reset_tenant_context_for_tests


def test_manifest_offers_service_customer_not_financial():
    reset_tenant_context_for_tests()
    # đảm bảo tool module đã import (decorator self-register)
    importlib.import_module("noble_agent.tenants.noble.tools.service_customer")
    ctx = get_tenant_context()
    assert "service_customer" in ctx.enabled_tools
    assert "get_project_financial" not in ctx.enabled_tools


def test_agent_def_offers_service_customer_schema():
    reset_tenant_context_for_tests()
    importlib.import_module("noble_agent.tenants.noble.tools.service_customer")
    ctx = get_tenant_context()
    from noble_agent.agent.base import load_agent_def

    agent = load_agent_def(ctx.persona_dir, tool_names=list(ctx.enabled_tools), brand=dict(ctx.brand))
    names = {s["function"]["name"] for s in agent.tool_schemas}
    assert "service_customer" in names
    assert "get_project_financial" not in names
```

- [ ] **Step 2: Chạy test xác nhận FAIL**

Run: `.venv/bin/pytest tests/unit/tenant/test_service_customer_integration.py -v`
Expected: FAIL (`get_project_financial` vẫn trong enabled).

- [ ] **Step 3: Sửa manifest**

Trong `src/noble_agent/tenants/noble/manifest.toml`, khối `[tools].enabled`: xoá dòng `"get_project_financial",` và thêm `"service_customer",`. Kết quả:

```toml
enabled = [
    "find_project",
    "update_customer",
    "kb_search",
    "discover_projects",
    "get_project_overview",
    "search_units",
    "recommend_units",
    "booking",
    "escalate",
    "send_media",
    "check_inventory",
    "service_customer",
]
```

- [ ] **Step 4: Sửa RULES.md**

(a) Dòng 140 — thay dòng tool-catalog `get_project_financial`:

```
| Giá / thanh toán / vay / ưu đãi / phí | get_project_financial(project_code, info_type=...) |
```

thành:

```
| Chính sách bán hàng / khuyến mãi / ưu đãi / vay vốn / hỗ trợ lãi suất của một dự án | service_customer(project_code=<MÃ>) |
```

(b) Dòng 18 — bỏ `get_project_financial` khỏi danh sách nhóm tool dự án:

```
     dự án (discover_projects / get_project_overview / get_project_financial /
     search_units / recommend_units / kb_search / booking).
```

thành:

```
     dự án (discover_projects / get_project_overview / service_customer /
     search_units / recommend_units / kb_search / booking).
```

(c) Dòng 150–151 — trong đoạn "Tín hiệu chuyển chuyên viên", thay `get_project_financial` bằng `service_customer`:

```
**Tín hiệu chuyển chuyên viên:** khi get_project_financial, search_units,
get_project_overview, discover_projects, recommend_units hoặc check_inventory trả về đúng câu
```

thành:

```
**Tín hiệu chuyển chuyên viên:** khi service_customer, search_units,
get_project_overview, discover_projects, recommend_units hoặc check_inventory trả về đúng câu
```

- [ ] **Step 5: Chạy test xác nhận PASS**

Run: `.venv/bin/pytest tests/unit/tenant/test_service_customer_integration.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Regression — full unit suite**

Run: `.venv/bin/pytest tests/unit -q`
Expected: không có failure MỚI so với baseline đã biết (8 failed: 2 USD-normalize, 2 qdrant_adapter, 1 qdrant_store, 1 snapshot_short_term, 1 prompt 'Tên:', 1 local-.env media). Ghi lại con số pass/fail.

- [ ] **Step 7: Lint + commit**

```bash
.venv/bin/ruff check src/noble_agent/tenants/noble/
git add src/noble_agent/tenants/noble/manifest.toml src/noble_agent/tenants/noble/persona/RULES.md tests/unit/tenant/test_service_customer_integration.py
git commit -m "feat(noble): offer service_customer, retire get_project_financial from manifest + RULES"
```

---

### Task 5: Smoke live `/chat` (thủ công, theo SMOKE.md)

**Files:** none (kiểm thử vận hành).

- [ ] **Step 1: Chạy dev server**

`scripts/run.sh` (cần `USE_UNIFIED_AGENT=true`, keys trong `.env`). Mở `http://localhost:8766/chat`.

- [ ] **Step 2: Case có csbh**

Hỏi: "Dự án Vinhomes Green City có chính sách vay vốn thế nào?" (hoặc một dự án anh biết có csbh). Kỳ vọng: Luna gọi `find_project` (nếu chưa có mã) rồi `service_customer`; trả lời đúng nội dung caption; app hiển thị ảnh csbh.

- [ ] **Step 3: Case không csbh**

Hỏi chính sách một dự án không có point csbh. Kỳ vọng: Luna đọc câu "Thông tin câu hỏi của anh chị đã được gửi cho bên sale ạ"; Redis scratchpad có `escalation_transferred=1` (auto-escalate đã chạy).

- [ ] **Step 4: Cập nhật CLAUDE.md Change Log + memory nếu cần**

Thêm 1 dòng Change Log (ngày 2026-07-27, tool service_customer + build_schemas custom-tool offering fix + retire get_project_financial). Cân nhắc memory cho collection `media_v3` payload schema nếu hữu ích.

---

## Self-Review

**Spec coverage:**
- §3 vị trí/đăng ký → Task 2 (package + @tool). ✓
- §4 truy cập Qdrant scroll → Task 2. ✓
- §5 param project_code + default project_interest → Task 2 (test_defaults_to_customer_project_interest). ✓
- §6.1 có csbh (context+items) → Task 2. ✓
- §6.2 bất biến chống trùng lặp → Task 3. ✓
- §6.3 handoff + ESCALATE_SIGNAL (3 nhánh) → Task 2 (no_csbh / missing_code / qdrant_error). ✓
- §7.1 dispatcher allowlist → Task 3. ✓
- §7.2 build_schemas fix → Task 1. ✓
- §7.3 manifest swap → Task 4. ✓
- §7.4 RULES.md → Task 4. ✓
- §8 test + smoke → Task 2/3/4 + Task 5. ✓

**Placeholder scan:** không có TBD/TODO; mọi step code đều đầy đủ. ✓

**Type consistency:** `service_customer(args, *, customer, session_id, **_)` khớp giữa Task 2 (định nghĩa) và Task 3/4 (dùng qua dispatcher/registry). `_map_items`/`_get_client`/`code_to_name`/`ESCALATE_SIGNAL` đều là API có thật đã xác minh. `_DISPLAY_ITEMS_TOOLS` set khớp Task 3. ✓
