# Tool schema + prompt operational-protocol refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bỏ tên/SĐT khỏi booking, rút booking từ 6 action → 4 action, và viết lại toàn bộ tool description theo operational-protocol (rõ, có ví dụ, không dài dòng, không xung đột system prompt).

**Architecture:** `booking` là router theo `action`; impl nằm ở `availability.py` (stub ngày/giờ) + `schedule_viewing.py` (chốt/liệt kê/đổi lịch). Bỏ `booking_state.py` (chỉ để gom dần tên/SĐT). Description sống trong `schemas.py`; rule vận hành sống trong `RULES.md` — hai nơi không lặp nhau.

**Tech Stack:** Python 3.11+, pytest (asyncio_mode=auto), ruff (line-length 120), jinja2 prompt compose.

## Global Constraints

- Branch làm việc: `feat/connect-db`. TUYỆT ĐỐI không đụng `develop`, không tạo branch mới, không push/PR.
- Không đụng: `config.json` tools list (giữ đúng 10 tool), 3 schema post-sale (`crm_lookup`/`verify_identity`/`support_ticket`) + branch dispatcher của chúng, logic `escalate`/`send_via_app` (chỉ đổi description), `availability.py`, model/RAG/transport/storage schema.
- Description: mỗi tool trả lời KHI NÀO gọi + LÀM GÌ + 1 ví dụ câu khách nói; không nêu lịch sử refactor, không lặp rule vận hành, không liệt kê cứng vùng miền, không cross-reference tool khác.
- Booking chỉ cần dự án + ngày + giờ; KHÔNG thu thập/validate tên hay SĐT.
- Chạy `make test-unit` + `make lint` xanh trước khi coi là xong.
- Bench/snapshot ngoài phạm vi (KHÔNG sửa, chỉ ghi chú): `tests/prompt_versions/*`, `tests/bench/`, `tests/bench_llm.py`, `tests/bench_prompt.py`, `tests/bench_rag/`, `tests/interactive/test_all_tools.py`, `scripts/gen_responses/scenarios.py`, và default string `config.py` `tool_ack_fast_tools` (chứa tên tool đã chết `get_booking_state`/`update_booking_info`/`switch_agent`/`validate_phone` — vô hại vì không khớp tool nào).

---

### Task 1: `schedule_viewing` bỏ tên + SĐT

**Files:**
- Modify: `src/noble_agent/agent/tools/schedule_viewing.py`
- Test: `tests/unit/test_booking_tools.py`

**Interfaces:**
- Produces: `schedule_viewing(state, customer, args: dict, session_id: str) -> str` — không còn đọc/ghi `customer_name`/`phone`; validate chỉ project + ngày; record không có 2 field đó; vẫn set `customer.project_interest`.
- `_normalize_and_validate(project: str, preferred_date: str) -> tuple[str, list[str]]` (đổi chữ ký, bỏ name/phone).

- [ ] **Step 1: Viết lại các test trong `tests/unit/test_booking_tools.py`**

Thay toàn bộ class `TestScheduleViewing` bằng:

```python
class TestScheduleViewing:
    @pytest.mark.asyncio
    async def test_unconfirmed_rejected(self):
        raw = await schedule_viewing(
            State(),
            Customer(),
            {"project": "NCLB", "preferred_date": "01/01/2027", "preferred_time": "10:00", "confirmed": False},
            session_id="test",
        )
        result = json.loads(raw)
        assert result["success"] is False
        assert "xác nhận" in result["error"]

    @pytest.mark.asyncio
    async def test_confirmed_syncs_project_no_name_phone(self):
        state = State()
        customer = Customer()
        with patch("noble_agent.storage.mongo_client.get_db", new_callable=AsyncMock, return_value=None):
            raw = await schedule_viewing(
                state,
                customer,
                {"project": "NCLB", "preferred_date": "01/01/2027", "preferred_time": "10:00", "confirmed": True},
                session_id="s1",
            )
        result = json.loads(raw)
        assert result["success"] is True
        assert result["appointment_id"].startswith("APT")
        # Project vẫn được sync (dirty-signal), tên/SĐT thì không.
        assert customer.project_interest == "NCLB"
        stored = json.loads(state.scratchpad["bookings"])
        assert len(stored) == 1
        assert stored[0]["project"] == "NCLB"
        assert "phone" not in stored[0]
        assert "customer_name" not in stored[0]

    @pytest.mark.asyncio
    async def test_project_pulled_from_customer_interest(self):
        state = State()
        customer = Customer()
        customer.project_interest = "SLC"
        with patch("noble_agent.storage.mongo_client.get_db", new_callable=AsyncMock, return_value=None):
            raw = await schedule_viewing(
                state,
                customer,
                {"preferred_date": "01/01/2027", "preferred_time": "10:00", "confirmed": True},
                session_id="s2",
            )
        result = json.loads(raw)
        assert result["success"] is True
        assert result["project"] == "SLC"

    @pytest.mark.asyncio
    async def test_missing_project_errors(self):
        raw = await schedule_viewing(
            State(),
            Customer(),
            {"preferred_date": "01/01/2027", "preferred_time": "10:00", "confirmed": True},
            session_id="s3",
        )
        result = json.loads(raw)
        assert result["success"] is False
        blob = (result.get("message", "") + " ".join(result.get("errors", []))).lower()
        assert "dự án" in blob
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/unit/test_booking_tools.py -v`
Expected: FAIL — `test_confirmed_syncs_project_no_name_phone` vẫn thấy `phone`/`customer_name` trong record; `test_missing_project_errors` hiện chưa có validate riêng (báo cả lỗi phone).

- [ ] **Step 3: Sửa `schedule_viewing.py`**

Bỏ import/const phone regex — xoá 2 dòng:

```python
import re
```
và
```python
_PHONE_REGEX = re.compile(r"^(0[35789])\d{8}$")
```

Thay `_normalize_and_validate` bằng:

```python
def _normalize_and_validate(project: str, preferred_date: str) -> tuple[str, list[str]]:
    from noble_agent.agent import catalog

    errors: list[str] = []
    norm_project = catalog.normalize(project)
    if not norm_project:
        errors.append(f"Dự án '{project}' không hợp lệ hoặc chưa được cung cấp")
    try:
        d = datetime.strptime((preferred_date or "").strip(), "%d/%m/%Y").date()
        if d < dt_date.today():
            errors.append("Ngày tham quan không được là ngày trong quá khứ")
    except ValueError:
        errors.append("Định dạng ngày không hợp lệ (dùng DD/MM/YYYY)")
    return norm_project, errors
```

Thay `schedule_viewing` (từ `async def schedule_viewing` tới hết `return` thành công) bằng:

```python
async def schedule_viewing(state, customer, args: dict, session_id: str) -> str:
    project = args.get("project") or customer.project_interest or ""
    preferred_date = args.get("preferred_date", "")
    preferred_time = args.get("preferred_time", "")
    notes = args.get("notes", "")
    confirmed = bool(args.get("confirmed", False))

    if not confirmed:
        return json.dumps(
            {
                "ok": False,
                "success": False,
                "error": "Chưa có xác nhận từ khách hàng. Vui lòng xác nhận thông tin trước.",
            },
            ensure_ascii=False,
        )

    norm_project, errors = _normalize_and_validate(project, preferred_date)
    if errors:
        return json.dumps(
            {"ok": False, "success": False, "errors": errors, "message": "; ".join(errors)},
            ensure_ascii=False,
        )

    bookings = _load_bookings(state)
    for b in bookings:
        if (
            b.get("project", "").upper() == norm_project.upper()
            and b.get("preferred_date") == preferred_date
            and b.get("preferred_time") == preferred_time
        ):
            return json.dumps(
                {
                    "ok": False,
                    "success": False,
                    "duplicate": True,
                    "error": (
                        f"Đã có lịch xem {norm_project} vào {preferred_time} "
                        f"ngày {preferred_date}. Vui lòng chọn thời gian khác."
                    ),
                },
                ensure_ascii=False,
            )

    appt_id = f"APT{random.randint(10000, 99999)}"
    booking = {
        "appointment_id": appt_id,
        "session_id": session_id,
        "project": norm_project,
        "preferred_date": preferred_date,
        "preferred_time": preferred_time,
        "notes": notes,
        "created_at": datetime.utcnow().isoformat(),
        "status": "confirmed",
    }
    bookings.append(booking)
    _save_bookings(state, bookings)

    try:
        from noble_agent.storage.mongo_client import get_db

        db = await get_db()
        if db is not None:
            await db.bookings_flat.update_one(
                {"appointment_id": appt_id},
                {"$set": booking},
                upsert=True,
            )
    except Exception as exc:
        logger.warning("schedule_viewing: Mongo write failed (%s) — continuing", exc)

    customer.project_interest = norm_project

    return json.dumps(
        {
            "ok": True,
            "success": True,
            "appointment_id": appt_id,
            "project": norm_project,
            "preferred_date": preferred_date,
            "preferred_time": preferred_time,
            "notes": notes,
            "message": "Đặt lịch thành công.",
        },
        ensure_ascii=False,
        default=str,
    )
```

(Chú ý: `_normalize_and_validate` không còn tham số `name`/`phone`; hàm `schedule_viewing` không còn biến `name`/`phone`/`phone_clean`.)

- [ ] **Step 4: Chạy test, xác nhận PASS**

Run: `pytest tests/unit/test_booking_tools.py -v`
Expected: PASS (4 test).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/schedule_viewing.py tests/unit/test_booking_tools.py
git commit -m "feat(booking): drop name/phone from schedule_viewing

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Booking router → 4 action, xoá `booking_state.py`

**Files:**
- Modify: `src/noble_agent/agent/tools/booking.py`
- Delete: `src/noble_agent/agent/tools/booking_state.py`
- Test: `tests/unit/unified/test_dispatcher.py`, `tests/integration/unified/test_booking_flow.py`

**Interfaces:**
- Consumes: `schedule_viewing.schedule_viewing` (Task 1), `availability.check_availability`, `schedule_viewing.list_bookings`, `schedule_viewing.modify_booking`.
- Produces: `booking.run(state, customer, args, session_id)` chỉ nhận `action ∈ {check_availability, schedule, list, modify}`; action khác → JSON `{"ok": False, "error": "Unknown booking action: ..."}`.

- [ ] **Step 1: Cập nhật `tests/unit/unified/test_dispatcher.py`**

Sửa `test_booking_read_actions_do_not_mark_customer_dirty` — bỏ `get_state`, dùng action còn tồn tại:

```python
async def test_booking_read_actions_do_not_mark_customer_dirty(dispatcher_ctx):
    """check_availability / list don't mutate Customer; the dispatcher must
    NOT force a system-prompt rebuild on every booking turn."""
    d, _, _ = dispatcher_ctx
    for action in ("check_availability", "list"):
        await d.dispatch(_tc("booking", {"action": action}))
        assert d.consume_customer_dirty() is False, f"action={action} should not dirty"
```

(`test_booking_schedule_marks_customer_dirty` giữ nguyên — action `schedule` vẫn nằm trong `_BOOKING_DIRTYING_ACTIONS`.)

- [ ] **Step 2: Cập nhật `tests/integration/unified/test_booking_flow.py`**

Sửa docstring module (2 dòng đầu mô tả get_state/update_info) → mô tả check_availability/schedule. Đổi `test_booking_turn1_get_state` thành:

```python
@pytest.mark.asyncio
async def test_booking_turn1_check_availability(runner, stub_responses):
    """Turn 1: customer asks to book → LLM calls booking(action=check_availability)."""
    stub_responses.append(
        ("tool_then_text", "booking", {"action": "check_availability", "project_code": "NCLB"}, "dạ các ngày trống ạ")
    )

    agent = NobleAgent(session_id=SESSION, runner=runner)
    events, send = make_collector()
    await run_text_turn(agent, send, "anh muốn đặt lịch xem NCLB")

    types = [e["type"] for e in events]
    assert "tool_start" in types
    assert "tool_done" in types
    assert types[-1] == "done"

    tool_start = next(e for e in events if e["type"] == "tool_start")
    assert tool_start["tool"] == "booking"
    assert tool_start["args"].get("action") == "check_availability"

    tool_done = next(e for e in events if e["type"] == "tool_done")
    result = json.loads(tool_done["result"])
    assert "available_dates" in result
    assert "slots" in result
```

Xoá hẳn hàm `test_booking_turn2_update_info` (action `update_info` không còn). Giữ nguyên `test_booking_turn3_schedule` và `test_booking_state_persists_across_turns`.

- [ ] **Step 3: Chạy test, xác nhận FAIL**

Run: `pytest tests/unit/unified/test_dispatcher.py tests/integration/unified/test_booking_flow.py -v`
Expected: FAIL — router hiện vẫn còn nhánh cũ / vẫn import `booking_state`; test mới `available_dates` chưa chắc pass tuỳ stub, nhưng mục tiêu là chứng minh trạng thái trước khi sửa router. (Nếu môi trường thiếu Redis cho integration, chạy riêng unit trước.)

- [ ] **Step 4: Viết lại `src/noble_agent/agent/tools/booking.py`**

```python
"""Unified booking tool — dispatches by `action` field.

Router mỏng: check_availability / schedule / list / modify. Impl nằm ở
availability.py (ngày+giờ trống) và schedule_viewing.py (chốt/liệt kê/đổi lịch).
Booking chỉ cần dự án + ngày + giờ — không thu thập tên hay số điện thoại.
"""

from __future__ import annotations

import json

from noble_agent.agent.tools import availability, schedule_viewing


async def run(state, customer, args: dict, session_id: str) -> str:
    action = (args.get("action") or "").strip()

    if action == "check_availability":
        project = args.get("project_code") or customer.project_interest or ""
        return await availability.check_availability(
            {
                "project_code": project,
                "preferred_date": args.get("preferred_date", ""),
                "preferred_time": args.get("preferred_time", ""),
            }
        )
    if action == "schedule":
        forward = {
            "preferred_date": args.get("preferred_date", ""),
            "preferred_time": args.get("preferred_time", ""),
            "notes": args.get("notes", ""),
            "confirmed": args.get("confirmed", False),
            "project": args.get("project_code", ""),
        }
        return await schedule_viewing.schedule_viewing(state, customer, forward, session_id=session_id)
    if action == "list":
        return await schedule_viewing.list_bookings(state)
    if action == "modify":
        return await schedule_viewing.modify_booking(state, args)

    return json.dumps(
        {"ok": False, "error": f"Unknown booking action: {action!r}"},
        ensure_ascii=False,
    )
```

- [ ] **Step 5: Xoá file `booking_state.py`**

```bash
git rm src/noble_agent/agent/tools/booking_state.py
```

- [ ] **Step 6: Chạy test, xác nhận PASS**

Run: `pytest tests/unit/unified/test_dispatcher.py tests/integration/unified/test_booking_flow.py -v`
Expected: PASS. Nếu integration cần Redis mà môi trường không có → xác nhận ít nhất unit dispatcher PASS và integration được skip/pass với fake_redis fixture.

- [ ] **Step 7: Commit**

```bash
git add src/noble_agent/agent/tools/booking.py tests/unit/unified/test_dispatcher.py tests/integration/unified/test_booking_flow.py
git rm src/noble_agent/agent/tools/booking_state.py
git commit -m "refactor(booking): 6 actions -> 4, drop get_state/update_info

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Description v3 + booking schema params

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py`
- Test: `tests/unit/unified/test_tool_schemas.py`

**Interfaces:**
- Produces: `SCHEMAS["booking"]` với `action` enum = `["check_availability", "schedule", "list", "modify"]`, không còn param `preferred_slot`. Description 10 tool offered viết lại theo v3. `escalate.description` chứa cụm "người thật" và "duy nhất".

- [ ] **Step 1: Cập nhật `tests/unit/unified/test_tool_schemas.py`**

Thay `test_escalate_description_mentions_no_agent_handoff` bằng:

```python
def test_escalate_description_is_only_human_handoff():
    desc = SCHEMAS["escalate"]["function"]["description"]
    assert "người thật" in desc
    assert "duy nhất" in desc
```

Thêm test cho booking schema mới:

```python
def test_booking_has_four_actions_no_slot():
    params = SCHEMAS["booking"]["function"]["parameters"]["properties"]
    assert params["action"]["enum"] == ["check_availability", "schedule", "list", "modify"]
    assert "preferred_slot" not in params
```

- [ ] **Step 2: Chạy test, xác nhận FAIL**

Run: `pytest tests/unit/unified/test_tool_schemas.py::test_escalate_description_is_only_human_handoff tests/unit/unified/test_tool_schemas.py::test_booking_has_four_actions_no_slot -v`
Expected: FAIL — description escalate hiện chưa có "duy nhất"/"người thật" đúng cụm; booking vẫn còn 6 action + `preferred_slot`.

- [ ] **Step 3: Sửa `schemas.py`**

Cập nhật docstring đầu file (bỏ câu "mirror legacy SFT"):

```python
"""OpenAI tool schemas cho unified single-agent (Luna).

Mỗi description theo hướng operational-protocol: nêu KHI NÀO gọi + tool LÀM GÌ
+ 1 ví dụ câu khách nói. Rule vận hành sống ở definitions/RULES.md — không lặp
ở đây. `escalate` là off-ramp duy nhất (không có agent khác để hand off).
"""
```

Thay `description` của từng tool bằng bản v3 (giữ nguyên phần `parameters` trừ `booking`):

- `update_customer`: `"Ghi nhớ thông tin cá nhân của khách vào hồ sơ: tên, giới tính, dự án đang quan tâm, mục đích ở hay đầu tư, ngân sách, khu vực muốn mua, số phòng ngủ. Gọi ngay khi khách vừa cung cấp bất kỳ thông tin nào trong số này. Ví dụ khách nói 'anh tên Hùng, tầm 3 tỷ' thì gọi update_customer(name='Hùng', budget='3 tỷ')."`
- `noble_search`: `"Tra cứu thông tin chi tiết về dự án trong tài liệu: tiện ích, mô tả vị trí, thiết kế, vật liệu, pháp lý, hoặc so sánh giữa các dự án. Dùng cho câu hỏi nội dung cụ thể cần dữ liệu thật. Ví dụ 'dự án đó có bể bơi không', 'pháp lý dự án thế nào'."`
- `list_projects`: `"Liệt kê danh sách các dự án Noble đang mở bán, có thể lọc theo khu vực. Dùng khi khách muốn biết Noble có những dự án nào, hoặc có dự án nào ở một khu vực. Ví dụ 'bên em có dự án nào', 'ở Long Biên có dự án gì'."`
- `get_project_overview`: `"Lấy thông tin tổng quan của một dự án: vị trí, loại hình, quy mô, các điểm nổi bật chính. Dùng khi khách hỏi giới thiệu chung về một dự án cụ thể. Ví dụ 'dự án Noble Crystal thế nào', 'giới thiệu cho em dự án đó'."`
- `get_project_financial`: `"Lấy thông tin tài chính của một dự án: bảng giá, chính sách thanh toán, chính sách vay ngân hàng, ưu đãi, hoặc các loại phí. Dùng khi khách hỏi về giá hoặc điều khoản tài chính. Ví dụ 'dự án đó giá bao nhiêu', 'trả góp thế nào'."`
- `search_units`: `"Tìm các căn hộ cụ thể còn trong một dự án theo tiêu chí: loại căn, mức giá tối đa, hướng, tầng, diện tích, mã căn, tình trạng còn hay đã bán. Dùng khi khách hỏi về căn cụ thể. Ví dụ 'còn căn 3 phòng ngủ dưới 5 tỷ không', 'có căn nào hướng Đông Nam'."`
- `match_projects`: `"Gợi ý những dự án phù hợp với nhu cầu của khách khi khách chưa biết chọn dự án nào, dựa trên ngân sách, khu vực, số phòng ngủ và mục đích. Dùng khi khách muốn được tư vấn nên xem dự án nào. Ví dụ 'tầm 4 tỷ ở Tây Hồ thì nên xem dự án nào'."`
- `escalate`: `"Chuyển cuộc gọi sang chuyên viên là người thật. Dùng khi khách đã mua nhà hỏi về hợp đồng, thanh toán, sổ hồng, bảo hành hoặc thủ tục; khi khách hỏi giá nội bộ; khi khách yêu cầu gặp người thật; hoặc khi một tool khác trả về đúng câu 'Thông tin đã được chuyển đến chuyên viên tư vấn'. Đây là cách duy nhất để đưa cuộc gọi ra khỏi luồng tự động."`
- `send_via_app`: `"Gửi tài liệu cho khách qua ứng dụng NobleX hoặc SMS: hình ảnh, bản đồ, mặt bằng, brochure — những nội dung khó diễn đạt bằng lời nói. Bắt buộc nói một câu filler ('Dạ em gửi qua app cho anh/chị nha, chờ em một chút ạ') cùng lúc khi gọi tool."`

Thay TOÀN BỘ entry `"booking"` trong `SCHEMAS` bằng:

```python
    "booking": {
        "type": "function",
        "function": {
            "name": "booking",
            "description": (
                "Đặt lịch cho khách tới tham quan dự án. action='check_availability' để "
                "xem những ngày và khung giờ còn trống, gọi trước để báo khách chọn; "
                "action='schedule' để chốt lịch sau khi khách đã chọn ngày và giờ, đặt "
                "confirmed=true; action='list' để xem các lịch đã đặt; action='modify' để "
                "đổi ngày hoặc giờ của một lịch đã đặt. Chỉ cần dự án, ngày và giờ; không "
                "cần tên hay số điện thoại."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["check_availability", "schedule", "list", "modify"],
                    },
                    "preferred_date": {
                        "type": "string",
                        "description": "Ngày mong muốn DD/MM/YYYY (check_availability để lọc, schedule bắt buộc).",
                    },
                    "preferred_time": {
                        "type": "string",
                        "description": "Khung giờ khách chọn, ví dụ '09:00 - 10:00' (schedule).",
                    },
                    "project_code": {
                        "type": "string",
                        "description": "Mã dự án. Bỏ trống nếu đã có trong hồ sơ khách.",
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "True khi khách đã chốt ngày và giờ (schedule).",
                    },
                    "notes": {"type": "string", "description": "Ghi chú thêm cho lịch (schedule)."},
                    "booking_id": {"type": "string", "description": "Mã lịch APT... cần đổi (modify)."},
                    "new_preferred_date": {"type": "string", "description": "Ngày mới DD/MM/YYYY (modify)."},
                    "new_preferred_time": {
                        "type": "string",
                        "description": "Giờ mới, ví dụ '09:00 - 10:00' (modify).",
                    },
                },
                "required": ["action"],
            },
        },
    },
```

(Description 3 tool post-sale `crm_lookup`/`verify_identity`/`support_ticket` GIỮ NGUYÊN — không đụng.)

- [ ] **Step 4: Chạy test, xác nhận PASS**

Run: `pytest tests/unit/unified/test_tool_schemas.py -v`
Expected: `test_escalate_description_is_only_human_handoff`, `test_booking_has_four_actions_no_slot`, `test_thirteen_tools_present`, `test_schemas_for_returns_in_order` PASS. (`test_schemas_for_skips_unknown` và `test_project_enums_have_15_codes` là PRE-EXISTING FAIL trên branch này — không thuộc phạm vi task, xác nhận chúng fail giống trước, không phải do thay đổi này.)

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_tool_schemas.py
git commit -m "refactor(schemas): operational-protocol descriptions + booking 4-action params

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: RULES.md — rule 6 + tool catalog

**Files:**
- Modify: `src/noble_agent/agent/definitions/RULES.md`
- Test: `tests/unit/unified/test_agent_def.py` (chỉ chạy để xác nhận không vỡ — không sửa)

**Interfaces:**
- Consumes: `load_agent_def` đọc `RULES.md` vào `agent.sections["rules"]`; test hiện chỉ assert chứa "Operational Protocol" (giữ nguyên header).

- [ ] **Step 1: Sửa Rule 6 trong `RULES.md`**

Thay block rule 6 (dòng "6. Booking có state machine bắt buộc:" và 4 gạch đầu dòng dưới nó) bằng:

```markdown
6. Đặt lịch tham quan (chỉ cần dự án + ngày + giờ, KHÔNG hỏi tên hay số
   điện thoại):
   - Gọi booking(action="check_availability") để lấy ngày và khung giờ còn
     trống, rồi báo khách chọn.
   - Khi khách đã chọn ngày và giờ: booking(action="schedule",
     confirmed=true) để chốt.
   - Xem lịch đã đặt: booking(action="list"). Đổi ngày/giờ lịch đã đặt:
     booking(action="modify", booking_id=...).
   - Dự án lấy từ hồ sơ khách (project_interest); nếu chưa rõ thì hỏi khách
     muốn tham quan dự án nào trước khi schedule.
```

- [ ] **Step 2: Sửa dòng booking trong bảng "Tool catalog"**

Thay dòng:

```markdown
| Đặt/đổi/xem lịch tham quan | booking(action=...) — pull customer info từ session |
```

bằng:

```markdown
| Đặt/đổi/xem lịch tham quan | booking(action=check_availability→schedule; list/modify) — chỉ cần dự án + ngày + giờ |
```

- [ ] **Step 3: Chạy test agent def + build prompt**

Run: `pytest tests/unit/unified/test_agent_def.py -v`
Expected: PASS (3 test — 10 tool, có "Operational Protocol", có escalate).

- [ ] **Step 4: Commit**

```bash
git add src/noble_agent/agent/definitions/RULES.md
git commit -m "docs(rules): booking rule to 4-action flow, no name/phone

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Verify toàn bộ + cập nhật CLAUDE.md

**Files:**
- Modify: `CLAUDE.md` (mục Layout `agent/tools/` + Change Log)

- [ ] **Step 1: Chạy full unit + lint**

Run: `make test-unit && make lint`
Expected: unit PASS (trừ 2 pre-existing fail đã nêu ở Task 3 Step 4); ruff sạch. Nếu ruff báo import `re`/biến thừa trong `schedule_viewing.py` → dọn.

- [ ] **Step 2: Chạy integration booking (nếu có Redis/fake)**

Run: `pytest tests/integration/unified/test_booking_flow.py -v`
Expected: PASS.

- [ ] **Step 3: Cập nhật CLAUDE.md**

Trong dòng bảng Layout `agent/tools/`, đổi mô tả booking sang "booking gồm 4 action (check_availability / schedule / list / modify), chỉ cần dự án + ngày + giờ (không tên/SĐT)". Thêm 1 row đầu Change Log:

```markdown
| 2026-07-03 | **Tool schema + prompt refactor theo operational-protocol; booking bỏ tên/SĐT, 6→4 action.** Viết lại description 10 tool offered (KHI NÀO + LÀM GÌ + 1 ví dụ, bỏ lịch sử refactor/rule vận hành/liệt kê vùng miền). `booking` rút còn `check_availability/schedule/list/modify` (xoá `get_state`/`update_info` + file `booking_state.py`), bỏ param `preferred_slot`. `schedule_viewing` bỏ validate tên+SĐT (bỏ `_PHONE_REGEX`), record không còn `customer_name`/`phone`, vẫn set `project_interest`. RULES.md rule 6 + tool catalog cập nhật theo flow mới. Spec `docs/superpowers/specs/2026-07-03-tool-schema-prompt-operational-refactor-design.md`. Branch `feat/connect-db`. | Sau khi bỏ mock data, description lủng củng/mô tả theo lịch sử refactor gây confuse model yếu (gemini/qwen-flash); booking không còn cần tên+SĐT (đang mock) — chỉ cần báo ngày/giờ trống cho khách chọn. |
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude): booking 4-action + operational-protocol schema refactor

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Nguyên tắc description → Task 3 (docstring + 10 description). ✓
- Description v3 10 tool → Task 3. ✓
- Booking 6→4 action, xoá get_state/update_info + booking_state.py → Task 2. ✓
- Bỏ tên/SĐT (validate + record + customer sync) → Task 1. ✓
- Bỏ `preferred_slot`, chuẩn hoá `preferred_time` → Task 3 (schema). ✓
- schedule thiếu dự án → error để Luna hỏi → Task 1 (`_normalize_and_validate` báo lỗi khi project rỗng) + `test_missing_project_errors`. ✓
- RULES.md rule 6 + catalog → Task 4. ✓
- Không đụng 3 schema post-sale / config.json tools → Global Constraints + Task 3 note. ✓
- Tác động test (booking_tools, dispatcher, booking_flow, tool_schemas) → Task 1/2/3. ✓
- CLAUDE.md self-maintenance (tool shape đổi) → Task 5. ✓

**Placeholder scan:** Không có TBD/TODO; mọi step có code/command cụ thể. ✓

**Type consistency:** `_normalize_and_validate(project, preferred_date) -> (norm_project, errors)` dùng nhất quán ở Task 1. `booking.run` forward key `project` (từ `project_code`) → `schedule_viewing` đọc `args.get("project")` — khớp. `action` enum 4 giá trị khớp giữa `booking.py` (Task 2) và `schemas.py` (Task 3). Test `available_dates`/`slots` khớp output `availability.check_availability`. ✓

**Pre-existing fails (không do plan này):** `test_tool_schemas.py::test_schemas_for_skips_unknown`, `::test_project_enums_have_15_codes` — đã fail sẵn trên branch (assert enum tĩnh đã bị gỡ / so sánh object copy). Ghi rõ ở Task 3 Step 4.
