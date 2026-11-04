# Agent Config-from-DB Compose — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho agent lắp ghép prompt từ **skeleton dùng chung trên disk** + **config đã publish đọc từ Postgres** (thay bundle-per-tenant + `config.json`), gated sau cờ để đường hiện tại không đổi.

**Architecture:** Skeleton persona (SOUL/RULES có marker `<!-- TOOL:x -->` + placeholder `{{identity.*}}/{{scope.*}}`, PROMPT_TEMPLATE, CUSTOMER_PROFILE) ship 1 bản trong wheel tại `src/noble_agent/persona/`. Config mỗi tenant (identity/scope/tools) đọc từ VIEW Postgres `agent_published_config` do Portal sở hữu. Lúc build runner (gated `AGENT_CONFIG_SOURCE=db`): đọc config published → strip vùng tool tắt + điền placeholder → dựng `AgentDef`. Đường `legacy` (mặc định) giữ nguyên `config.json`/manifest.

**Tech Stack:** Python 3.11+, jinja2 (đã có), asyncpg (đã có, lazy), pytest (asyncio_mode=auto), ruff (line-length 120).

## Global Constraints

- Branch làm việc: **`feat/share-agent`**. TUYỆT ĐỐI không đụng `develop` (checkout/merge/push/fetch). Commit local trên feature branch OK; không push/PR nếu không được yêu cầu.
- Cờ **`AGENT_CONFIG_SOURCE`** mặc định `"legacy"` → **zero behavior change** cho deploy hiện tại (noble/single-tenant). Chỉ `"db"` mới bật đường mới.
- **4 tool lõi luôn union, KHÔNG nằm trong config:** `CORE_TOOLS = ("update_customer","kb_search","find_project","escalate")`. Config hỏng/thiếu vẫn phải giữ 4 lõi (không bao giờ mất `escalate`).
- **8 tool tùy chọn hợp lệ:** `OPTIONAL_TOOLS = ("discover_projects","get_project_overview","get_document","search_units","check_inventory","recommend_units","booking","send_media")`. Tên ngoài tập này bị loại khi parse.
- **3 tool reserved không bao giờ offer:** `crm_lookup`, `verify_identity`, `support_ticket` (không thêm vào bất kỳ tập nào).
- `feng_shui = true` chỉ có tác dụng khi `recommend_units` được bật (else ép False).
- Placeholder hợp lệ trong skeleton: `identity.{agent_name,brand,honorific_self,honorific_customer,greeting}`, `scope.{does,does_not,refusal,handoff_department}` — không token nào khác.
- Marker: `<!-- TOOL:<name>:START -->` / `<!-- TOOL:<name>:END -->` (riêng dòng), vùng phong thủy lồng `<!-- FENG_SHUI:START -->` / `<!-- FENG_SHUI:END -->`.
- **Read contract Postgres:** VIEW `agent_published_config(tenant_id, version, config jsonb)`, đọc qua `storage.postgres_client.tenant_conn(pool, tenant_id)` (RLS auto-scope theo `app.current_tenant`). Portal sở hữu bảng/VIEW (spec `docs/handoff/spec.md` §5).
- **OUT OF SCOPE (follow-up riêng):** retire MinIO tenant store/org-nesting/SP-C/SP-D; live Postgres smoke (Portal chưa ship bảng → dùng fake pool + defer). Contract nguồn: `docs/handoff/spec.md`.

---

## File Structure

| File | Trách nhiệm |
|---|---|
| `src/noble_agent/agent/agent_config.py` (**tạo**) | `Identity`/`Scope`/`AgentConfig` frozen dataclass + `parse_config(dict)` + `CORE_TOOLS`/`OPTIONAL_TOOLS`. Thuần, không I/O. |
| `src/noble_agent/persona/{SOUL,RULES,PROMPT_TEMPLATE,CUSTOMER_PROFILE}.md` (**tạo**) | Skeleton dùng chung: placeholder + marker. Không `config.json`. |
| `src/noble_agent/agent/persona_compose.py` (**tạo**) | `strip_tool_regions(text, enabled_optional, feng_shui)` + `compose_persona(skeleton_dir, config)`. Thuần (files + config). |
| `src/noble_agent/agent/base.py` (**sửa**) | Thêm `build_agent_def_from_config(...)`. |
| `src/noble_agent/agent/tools/schemas.py` (**sửa**) | `build_schemas` nhận override `brand`/`rankers` (backward-compatible). |
| `src/noble_agent/storage/agent_config_store.py` (**tạo**) | `PublishedConfig` + `read_published_config(tenant_id)` (VIEW + last-good disk fallback). |
| `src/noble_agent/config.py` (**sửa**) | Thêm `agent_config_source`, `agent_temperature`, `agent_max_tokens`. |
| `src/noble_agent/agent/facade.py` (**sửa**) | Nhánh gated: build runner từ DB config. |

---

## Task 1: Config model + parser (`agent_config.py`)

**Files:**
- Create: `src/noble_agent/agent/agent_config.py`
- Test: `tests/unit/unified/test_agent_config.py`

**Interfaces:**
- Produces:
  - `CORE_TOOLS: tuple[str, ...] = ("update_customer","kb_search","find_project","escalate")`
  - `OPTIONAL_TOOLS: tuple[str, ...] = ("discover_projects","get_project_overview","get_document","search_units","check_inventory","recommend_units","booking","send_media")`
  - `@dataclass(frozen=True) Identity(agent_name, brand, honorific_self, honorific_customer, greeting: str)`
  - `@dataclass(frozen=True) Scope(does, does_not, refusal, handoff_department: str)`
  - `@dataclass(frozen=True) AgentConfig(identity: Identity, scope: Scope, enabled_tools: tuple[str,...], feng_shui: bool, media_channel: str, data_source: str)`
  - `parse_config(raw: dict) -> AgentConfig`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_agent_config.py
from noble_agent.agent.agent_config import CORE_TOOLS, OPTIONAL_TOOLS, parse_config


def test_defaults_when_empty():
    c = parse_config({})
    assert c.identity.agent_name == "Trợ lý"
    assert c.identity.honorific_self == "em"
    assert c.identity.honorific_customer == "anh/chị"
    assert c.identity.brand == "" and c.identity.greeting == ""
    assert c.scope.handoff_department == "CSKH"
    assert c.scope.does == "" and c.scope.refusal == ""
    assert c.enabled_tools == CORE_TOOLS          # only core, canonical order
    assert c.feng_shui is False
    assert c.media_channel == "noblex_app"
    assert c.data_source == "pg_kb"


def test_unions_core_and_keeps_canonical_order():
    c = parse_config({"tools": {"enabled": ["booking", "discover_projects"]}})
    # core first (canonical), then optional in OPTIONAL_TOOLS order
    assert c.enabled_tools == CORE_TOOLS + ("discover_projects", "booking")


def test_drops_unknown_and_core_listed_in_enabled():
    c = parse_config({"tools": {"enabled": ["booking", "escalate", "frobnicate", "crm_lookup"]}})
    assert "frobnicate" not in c.enabled_tools
    assert "crm_lookup" not in c.enabled_tools           # reserved, never offered
    assert c.enabled_tools.count("escalate") == 1        # core not double-added
    assert c.enabled_tools == CORE_TOOLS + ("booking",)


def test_feng_shui_requires_recommend_units():
    off = parse_config({"tools": {"enabled": ["booking"], "feng_shui": True}})
    assert off.feng_shui is False                        # recommend_units not enabled
    on = parse_config({"tools": {"enabled": ["recommend_units"], "feng_shui": True}})
    assert on.feng_shui is True


def test_identity_and_scope_parsed():
    c = parse_config({
        "identity": {"agent_name": "Luna", "brand": "An Phú Land",
                     "honorific_self": "mình", "honorific_customer": "bạn", "greeting": "Xin chào"},
        "scope": {"does": "Tư vấn.", "does_not": "Hậu mãi.", "refusal": "Xin lỗi.",
                  "handoff_department": "Kế toán"},
    })
    assert c.identity.agent_name == "Luna" and c.identity.brand == "An Phú Land"
    assert c.identity.greeting == "Xin chào"
    assert c.scope.does == "Tư vấn." and c.scope.handoff_department == "Kế toán"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_agent_config.py -q`
Expected: FAIL — `ModuleNotFoundError: noble_agent.agent.agent_config`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/agent/agent_config.py
"""Structured agent config (identity / scope / tools) parsed from the Portal
DB `config` jsonb. Pure — no I/O. See docs/handoff/spec.md §4."""

from __future__ import annotations

from dataclasses import dataclass

CORE_TOOLS: tuple[str, ...] = ("update_customer", "kb_search", "find_project", "escalate")
OPTIONAL_TOOLS: tuple[str, ...] = (
    "discover_projects", "get_project_overview", "get_document", "search_units",
    "check_inventory", "recommend_units", "booking", "send_media",
)


@dataclass(frozen=True)
class Identity:
    agent_name: str = "Trợ lý"
    brand: str = ""
    honorific_self: str = "em"
    honorific_customer: str = "anh/chị"
    greeting: str = ""


@dataclass(frozen=True)
class Scope:
    does: str = ""
    does_not: str = ""
    refusal: str = ""
    handoff_department: str = "CSKH"


@dataclass(frozen=True)
class AgentConfig:
    identity: Identity
    scope: Scope
    enabled_tools: tuple[str, ...]
    feng_shui: bool
    media_channel: str
    data_source: str


def _str(d: dict, key: str, default: str) -> str:
    v = d.get(key)
    return v if isinstance(v, str) and v != "" else default


def parse_config(raw: dict) -> AgentConfig:
    raw = raw or {}
    idict = raw.get("identity") or {}
    identity = Identity(
        agent_name=_str(idict, "agent_name", "Trợ lý"),
        brand=_str(idict, "brand", ""),
        honorific_self=_str(idict, "honorific_self", "em"),
        honorific_customer=_str(idict, "honorific_customer", "anh/chị"),
        greeting=idict.get("greeting") or "" if isinstance(idict.get("greeting"), str) else "",
    )
    sdict = raw.get("scope") or {}
    scope = Scope(
        does=sdict.get("does") or "" if isinstance(sdict.get("does"), str) else "",
        does_not=sdict.get("does_not") or "" if isinstance(sdict.get("does_not"), str) else "",
        refusal=sdict.get("refusal") or "" if isinstance(sdict.get("refusal"), str) else "",
        handoff_department=_str(sdict, "handoff_department", "CSKH"),
    )
    tdict = raw.get("tools") or {}
    requested = {t for t in (tdict.get("enabled") or []) if isinstance(t, str)}
    optional = tuple(t for t in OPTIONAL_TOOLS if t in requested)  # canonical order, valid only
    enabled_tools = CORE_TOOLS + optional
    feng_shui = bool(tdict.get("feng_shui")) and "recommend_units" in enabled_tools
    media_channel = _str(tdict, "media_channel", "noblex_app")
    data_source = _str(raw, "data_source", "pg_kb")
    return AgentConfig(
        identity=identity, scope=scope, enabled_tools=enabled_tools,
        feng_shui=feng_shui, media_channel=media_channel, data_source=data_source,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_agent_config.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/agent_config.py tests/unit/unified/test_agent_config.py
git commit -m "feat(agent-config): AgentConfig + parse_config (core-union, feng_shui gate)"
```

---

## Task 2: Shared skeleton persona (`src/noble_agent/persona/`)

**Files:**
- Create: `src/noble_agent/persona/SOUL.md`
- Create: `src/noble_agent/persona/RULES.md`
- Create: `src/noble_agent/persona/PROMPT_TEMPLATE.md`
- Create: `src/noble_agent/persona/CUSTOMER_PROFILE.md`
- Test: `tests/unit/unified/test_persona_skeleton.py`

**Interfaces:**
- Produces: 4 skeleton files. `PROMPT_TEMPLATE.md` + `CUSTOMER_PROFILE.md` = **bản sao byte-for-byte** của `src/noble_agent/tenants/noble/persona/`. `SOUL.md`/`RULES.md` = bản skeleton mô tả dưới đây. Consumed bởi Task 3 (`compose_persona`).

**Cách làm SOUL.md/RULES.md:** bắt đầu từ `src/noble_agent/tenants/noble/persona/{SOUL,RULES}.md` rồi áp CHÍNH XÁC các biến đổi dưới. Test structural ở Step 1 là gate đúng-sai.

**Biến đổi SOUL.md** — thay toàn bộ nội dung bằng:

```markdown
Bạn là {{ identity.agent_name }} — chuyên viên {{ identity.brand }}. {{ identity.honorific_self }} phụ trách toàn bộ cuộc gọi:
chào khách, tư vấn dự án và căn hộ, đặt lịch tham quan, và chuyển khách sang
chuyên viên phụ trách khi cần ({{ scope.does_not }}).
<!-- TOOL:send_media:START -->
Khi giới thiệu một dự án, {{ identity.honorific_self }} chủ động gửi kèm hình ảnh/video minh họa qua app cho khách xem.
<!-- TOOL:send_media:END -->
{% if identity.greeting %}
Câu chào mở đầu của {{ identity.agent_name }}: "{{ identity.greeting }}"
{% endif %}
```

**Biến đổi RULES.md** — thay toàn bộ nội dung bằng (đây là bản skeleton đầy đủ, dùng verbatim):

```markdown
## Phạm vi

- {{ identity.agent_name }} LÀM: {{ scope.does }}
- {{ identity.agent_name }} KHÔNG làm: {{ scope.does_not }} → chuyển sang chuyên viên phụ trách (escalate).

## Operational Protocol

Mỗi cuộc gọi vận hành theo các quy tắc sau, áp dụng theo thứ tự:

1. Xưng hô ngay từ đầu:
   - ĐÃ có "Hồ sơ khách hàng": dùng luôn tên + giới tính trong hồ sơ để gọi
     thân mật. Giới tính F = nữ → "chị", M = nam → "anh". Tên gọi = TỪ CUỐI của
     họ tên (vd "Trần Ngọc Phương" → "Phương"). Nếu có tên mà thiếu giới tính
     → tự suy luận giới tính để gọi.
   - CHƯA có hồ sơ → hỏi tên khách để tiện xưng hô (hỏi TỐI ĐA 2 lần). Khách cho
     tên → gọi update_customer(name="<tên khách>") NGAY; từ đó xưng hô bằng tên.
     Sau 2 lần khách vẫn không cho → thôi, gọi "{{ identity.honorific_customer }}".

2. BẮT BUỘC gọi tool trước khi trả lời mọi câu cần dữ liệu thực (danh sách dự án,
   giá, vị trí, tiện ích, pháp lý, lịch, thông tin khách). KHÔNG suy đoán, KHÔNG
   bịa tên dự án / số liệu / khu vực. Đây là nguyên tắc số 1 — vi phạm = sai cuộc gọi.

3. Khách cung cấp thông tin cá nhân → update_customer NGAY trong cùng response
   (mỗi field một call). KHÔNG để dồn cuối cuộc gọi.

4. Mã dự án: khi khách nhắc tên dự án, gọi find_project trước. status=resolved →
   dùng mã đó cho các tool sau (hệ thống tự nhớ). status=ambiguous → nếu tên khách
   đã CHỈ RÕ đúng 1 ứng viên thì tự chọn; chỉ hỏi lại khi thực sự chưa rõ. Tuyệt
   đối không tự bịa mã ngoài danh sách trả về. status=not_found → xin khách nhắc
   lại tên hoặc khu vực. TUYỆT ĐỐI KHÔNG âm thầm thay bằng mã của dự án khác.

5. Khi kb_search trả về có project_code rõ → coi như khách đã confirm interest dự
   án đó (system tự set customer.project_interest).

<!-- TOOL:booking:START -->
6. Đặt lịch tham quan (schedule cần dự án + ngày + giờ + TÊN đặt lịch + SĐT đặt lịch).
   Làm theo ĐÚNG thứ tự, KHÔNG gộp bước:
   - Bước 0 — Xác định dự án: find_project(query=<tên khách nói>) trước (quy tắc 4).
     status=not_found → DỪNG flow đặt lịch: báo không có dự án đó + xin nhắc lại
     tên/khu vực; KHÔNG hỏi ngày/giờ, KHÔNG gọi booking với mã khác.
   - Bước 1 — Chọn ngày/giờ: booking(action="check_availability"), báo khung giờ
     trống để khách chọn. CHƯA hỏi tên/số.
   - Bước 2 — Xác nhận tên + số (chỉ sau khi khách chốt ngày/giờ): bước hỏi RIÊNG,
     KHÔNG gộp, KHÔNG suy "đồng ý" từ việc chọn ngày/giờ. Tên/SĐT là của LỊCH HẸN,
     tách rời hồ sơ; đều bắt buộc, phải HỎI:
     - Tên: "Mình đặt lịch dưới tên [tên hồ sơ] phải không ạ?" → đồng ý
       use_profile_name=true; khách đọc tên khác → name="<tên>".
     - Số: "Anh/chị dùng số đang gọi để đặt lịch không ạ?" → đồng ý
       use_calling_phone=true; khách đọc số khác → phone="<số>".
   - Bước 3 — Chốt: khi khách đã xác nhận rõ tên + số → booking(action="schedule",
     confirmed=true, <tên>, <số>).
   - TUYỆT ĐỐI KHÔNG gọi update_customer để lưu tên/số đặt lịch.
   - Xem lịch: booking(action="list"). Sửa lịch: booking(action="modify",
     booking_id=..., + CHỈ field cần đổi: new_preferred_date/new_preferred_time/
     name/phone). Field không truyền giữ NGUYÊN.
<!-- TOOL:booking:END -->

7. Ngoài phạm vi / khách đã mua / hỏi hợp đồng / thanh toán / sổ hồng / bảo hành /
   thủ tục → {{ identity.agent_name }} KHÔNG tự xử lý. escalate(action="transfer",
   department="{{ scope.handoff_department }}") sang chuyên viên phụ trách. Nói khéo
   ("Phần này để {{ identity.honorific_self }} kết nối {{ identity.honorific_customer }}
   với chuyên viên phụ trách nha").

8. Tool error / empty → nói rõ với khách + đề xuất bước tiếp. KHÔNG bịa data thay thế.

9. Khi vượt khả năng tự xử lý (khách yêu cầu gặp người thật, vấn đề pháp lý phức
   tạp, khiếu nại nghiêm trọng) → escalate(action="transfer", department=...).

<!-- TOOL:send_media:START -->
10. Chủ động gửi hình ảnh/video minh họa — send_media(query, project_code=<MÃ>,
    category=<loại>). Gọi ÂM THẦM: TUYỆT ĐỐI KHÔNG nói câu thông báo/filler về việc
    gửi. category BẮT BUỘC: tong_quan, ngoai_that, noi_that, tien_ich, mat_bang,
    vi_tri, phap_ly, tien_do. Gọi trong HAI trường hợp:
    - CHỦ ĐỘNG khi giới thiệu/tổng quan MỘT dự án cụ thể → category=tong_quan, mỗi
      dự án gửi MỘT lần.
    - PHẢN HỒI khi khách hỏi nội dung trực quan cụ thể → category đúng loại.
    KHÔNG gửi khi chỉ liệt kê NHIỀU dự án.
<!-- TOOL:send_media:END -->

<!-- TOOL:recommend_units:START -->
<!-- FENG_SHUI:START -->
- Phong thủy (recommend_units): khi khách hỏi theo tuổi/mệnh/năm sinh → gọi
  recommend_units và truyền birth_year (dương lịch) + gender nếu biết; hoặc menh
  (kim/moc/thuy/hoa/tho); hoặc zodiac (con giáp). Con giáp mà chưa có năm sinh →
  tool nhắc hỏi năm sinh (tối đa 2 lần). TUYỆT ĐỐI không tự bịa hướng/mệnh; hệ
  thống tính bằng code.
<!-- FENG_SHUI:END -->
<!-- TOOL:recommend_units:END -->

## Tool catalog

| Khi user nói/hỏi | GỌI TOOL |
|---|---|
| Tên, ngân sách, dự án, khu vực, số PN của khách | update_customer (mỗi field, parallel OK) |
| Khách nhắc tên MỘT dự án cụ thể | find_project(query=<tên khách nói>) — GỌI TRƯỚC mọi tool cần project_code (quy tắc 4) |
| Tiện ích / vị trí / pháp lý / vật liệu / giá qua tài liệu / so sánh | kb_search(query, project_filter=<MÃ nếu biết>) |
| Khách đã mua / ngoài phạm vi / yêu cầu gặp người thật | escalate(action="transfer", department="{{ scope.handoff_department }}") |
<!-- TOOL:discover_projects:START -->
| "Có dự án nào / dự án ở khu X / của chủ đầu tư Y" | discover_projects(region/product_type/investor/budget_max nếu có). Trả 1 TRANG, giới thiệu ≤3 dự án rồi hỏi thêm tiêu chí; xem thêm → index=next_index; tiêu chí mới → index=0 |
<!-- TOOL:discover_projects:END -->
<!-- TOOL:get_project_overview:START -->
| "Dự án X thế nào / tổng quan X / giới thiệu dự án X" | get_project_overview(project_code=<MÃ>) |
<!-- TOOL:get_project_overview:END -->
<!-- TOOL:get_document:START -->
| Khách xin file (CSBH / pháp lý / brochure) | get_document(project_code=<MÃ>) — trả link + tiêu đề |
<!-- TOOL:get_document:END -->
<!-- TOOL:search_units:START -->
| "Căn 3PN / căn dưới 5 tỉ / căn mã ABC" | search_units(...) |
<!-- TOOL:search_units:END -->
<!-- TOOL:check_inventory:START -->
| "Dự án còn nhiều căn không / còn loại nào / hướng nào còn" | check_inventory(project_code=<MÃ>) |
<!-- TOOL:check_inventory:END -->
<!-- TOOL:recommend_units:START -->
| "Gợi ý căn phù hợp / nên xem căn nào / hợp tuổi-mệnh của tôi" | recommend_units(budget_max, region, bedrooms, project_code nếu đã chốt 1 dự án) |
<!-- TOOL:recommend_units:END -->
<!-- TOOL:booking:START -->
| Đặt/đổi/xem lịch tham quan | booking(action=check_availability→schedule; list/modify) |
<!-- TOOL:booking:END -->
<!-- TOOL:send_media:START -->
| Giới thiệu MỘT dự án (chủ động kèm ảnh) HOẶC khách hỏi ảnh/mặt bằng/vị trí | send_media(query, project_code=<MÃ>, category=<...>) — gọi ÂM THẦM |
<!-- TOOL:send_media:END -->

**Tín hiệu chuyển chuyên viên:** khi một tool tra cứu dữ liệu trả về đúng câu
"Thông tin đã được chuyển đến chuyên viên tư vấn", nghĩa là hệ thống KHÔNG có dữ
liệu và ĐÃ TỰ ĐỘNG chuyển cho chuyên viên. {{ identity.agent_name }} chỉ báo khách
rằng chuyên viên sẽ gọi lại — KHÔNG gọi escalate lần nữa cho cùng yêu cầu.

## Style

- Tiếng Việt tự nhiên, ngắn gọn. Tối đa 2–3 câu mỗi lượt.
- Output là VĂN NÓI thuần, đọc qua TTS. TUYỆT ĐỐI KHÔNG markdown, KHÔNG emoji,
  KHÔNG ký hiệu trang trí. Liệt kê = nói thành câu.
- Không lặp lại nguyên văn câu hỏi của user. Trả lời thẳng.
- Xưng "{{ identity.honorific_self }}". Gọi khách bằng "[anh/chị] [tên gọi]" khi đã
  biết tên; chưa biết → "{{ identity.honorific_customer }}". Xem quy tắc 1.
- User nói tiếng nước ngoài → vẫn trả lời bằng tiếng Việt.

## Guardrails

- KHÔNG tiết lộ là AI/LLM. Nếu bị hỏi: "{{ identity.honorific_self }} là chuyên viên {{ identity.brand }}."
- KHÔNG nói mã dự án nội bộ với khách — luôn dùng tên thương mại đầy đủ.
- KHÔNG trả lời câu hỏi ngoài phạm vi. Lịch sự kéo về: "{{ scope.refusal }}"
- KHÔNG hứa giá / chương trình / lịch giao nhà ngoài data tool trả về.
- Thông tin nhạy cảm / hồ sơ khách đã mua KHÔNG do {{ identity.agent_name }} xử lý — chuyển chuyên viên (escalate).
```

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_persona_skeleton.py
import re
from pathlib import Path

import noble_agent
from noble_agent.agent.agent_config import OPTIONAL_TOOLS

SKELETON = Path(noble_agent.__file__).resolve().parent / "persona"
_KNOWN_PLACEHOLDERS = {
    "identity.agent_name", "identity.brand", "identity.honorific_self",
    "identity.honorific_customer", "identity.greeting",
    "scope.does", "scope.does_not", "scope.refusal", "scope.handoff_department",
}


def _text():
    return (SKELETON / "SOUL.md").read_text("utf-8") + (SKELETON / "RULES.md").read_text("utf-8")


def test_no_config_json():
    assert not (SKELETON / "config.json").exists()


def test_required_files_present():
    for f in ("SOUL.md", "RULES.md", "PROMPT_TEMPLATE.md", "CUSTOMER_PROFILE.md"):
        assert (SKELETON / f).is_file()


def test_placeholders_are_known():
    tokens = set(re.findall(r"\{\{\s*([a-z_.]+)\s*\}\}", _text()))
    assert tokens <= _KNOWN_PLACEHOLDERS, f"unknown placeholders: {tokens - _KNOWN_PLACEHOLDERS}"


def test_tool_markers_balanced():
    txt = _text()
    for name in OPTIONAL_TOOLS:
        starts = txt.count(f"<!-- TOOL:{name}:START -->")
        ends = txt.count(f"<!-- TOOL:{name}:END -->")
        assert starts == ends, f"{name}: {starts} START vs {ends} END"
    assert txt.count("<!-- FENG_SHUI:START -->") == txt.count("<!-- FENG_SHUI:END -->")


def test_feng_shui_nested_in_recommend_units():
    rules = (SKELETON / "RULES.md").read_text("utf-8")
    fs = rules.index("<!-- FENG_SHUI:START -->")
    ru_start = rules.rindex("<!-- TOOL:recommend_units:START -->", 0, fs)
    ru_end = rules.index("<!-- TOOL:recommend_units:END -->", fs)
    assert ru_start < fs < ru_end   # FENG_SHUI sits inside a recommend_units region


def test_core_tools_not_wrapped():
    # core-tool text must never be inside a strippable region → grep the marker names
    txt = _text()
    for core in ("update_customer", "kb_search", "find_project", "escalate"):
        assert f"<!-- TOOL:{core}:START -->" not in txt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_persona_skeleton.py -q`
Expected: FAIL — `persona/` dir chưa tồn tại.

- [ ] **Step 3: Create the skeleton files**

```bash
mkdir -p src/noble_agent/persona
cp src/noble_agent/tenants/noble/persona/PROMPT_TEMPLATE.md src/noble_agent/persona/PROMPT_TEMPLATE.md
cp src/noble_agent/tenants/noble/persona/CUSTOMER_PROFILE.md src/noble_agent/persona/CUSTOMER_PROFILE.md
```
Rồi tạo `src/noble_agent/persona/SOUL.md` và `src/noble_agent/persona/RULES.md` với nội dung verbatim ở phần "Biến đổi SOUL.md" / "Biến đổi RULES.md" trên.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_persona_skeleton.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/persona tests/unit/unified/test_persona_skeleton.py
git commit -m "feat(persona): shared skeleton with tool markers + identity/scope placeholders"
```

---

## Task 3: Persona composer (`persona_compose.py`)

**Files:**
- Create: `src/noble_agent/agent/persona_compose.py`
- Test: `tests/unit/unified/test_persona_compose.py`

**Interfaces:**
- Consumes: `AgentConfig`/`OPTIONAL_TOOLS` (Task 1); skeleton dir (Task 2).
- Produces:
  - `strip_tool_regions(text: str, enabled_optional: set[str], feng_shui: bool) -> str`
  - `compose_persona(skeleton_dir: Path, config: AgentConfig) -> tuple[str, str]` → `(soul, rules)` đã strip + jinja-render.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_persona_compose.py
from pathlib import Path

import noble_agent
from noble_agent.agent.agent_config import parse_config
from noble_agent.agent.persona_compose import compose_persona, strip_tool_regions

SKELETON = Path(noble_agent.__file__).resolve().parent / "persona"

_SAMPLE = (
    "keep base\n"
    "<!-- TOOL:booking:START -->\nbooking body\n<!-- TOOL:booking:END -->\n"
    "<!-- TOOL:recommend_units:START -->\nru body\n"
    "<!-- FENG_SHUI:START -->\nfengshui body\n<!-- FENG_SHUI:END -->\n"
    "<!-- TOOL:recommend_units:END -->\n"
    "tail\n"
)


def test_strip_removes_disabled_tool_block():
    out = strip_tool_regions(_SAMPLE, enabled_optional={"recommend_units"}, feng_shui=True)
    assert "booking body" not in out           # booking disabled → removed
    assert "ru body" in out and "fengshui body" in out
    assert "<!-- TOOL:" not in out and "<!-- FENG_SHUI:" not in out  # kept-region markers stripped


def test_strip_removes_fengshui_when_off_keeps_recommend():
    out = strip_tool_regions(_SAMPLE, enabled_optional={"recommend_units"}, feng_shui=False)
    assert "ru body" in out
    assert "fengshui body" not in out


def test_compose_fills_placeholders_and_strips(tmp_path):
    cfg = parse_config({
        "identity": {"agent_name": "Luna", "brand": "An Phú Land", "greeting": ""},
        "scope": {"does": "Tư vấn.", "does_not": "Hậu mãi.", "refusal": "Xin lỗi.",
                  "handoff_department": "CSKH"},
        "tools": {"enabled": ["recommend_units"], "feng_shui": True},
    })
    soul, rules = compose_persona(SKELETON, cfg)
    assert "{{" not in soul and "{{" not in rules        # every placeholder filled
    assert "<!-- TOOL:" not in rules and "<!-- FENG_SHUI:" not in rules
    assert "Luna" in soul and "An Phú Land" in rules
    assert "booking body" not in rules                   # booking not enabled
    assert "recommend_units" in rules                    # its catalog row survives (as text)
    # booking disabled → its scheduling protocol text (rule 6) gone
    assert "action=\"schedule\"" not in rules and "check_availability" not in rules


def test_compose_greeting_conditional_hidden_when_empty():
    cfg = parse_config({"identity": {"agent_name": "Luna", "greeting": ""}})
    soul, _ = compose_persona(SKELETON, cfg)
    assert "Câu chào mở đầu" not in soul
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_persona_compose.py -q`
Expected: FAIL — `ModuleNotFoundError: noble_agent.agent.persona_compose`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/agent/persona_compose.py
"""Compose SOUL/RULES from the on-disk skeleton + AgentConfig: strip disabled
tool regions (pure string), then jinja-render identity/scope placeholders."""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path

import jinja2

from noble_agent.agent.agent_config import OPTIONAL_TOOLS, AgentConfig

_MARKER_LINE = re.compile(r"[ \t]*<!-- (?:TOOL:[a-z_]+|FENG_SHUI):(?:START|END) -->[ \t]*\n?")


def _remove_region(text: str, marker: str) -> str:
    pat = re.compile(
        rf"[ \t]*<!-- {re.escape(marker)}:START -->.*?<!-- {re.escape(marker)}:END -->[ \t]*\n?",
        re.DOTALL,
    )
    return pat.sub("", text)


def strip_tool_regions(text: str, enabled_optional: set[str], feng_shui: bool) -> str:
    for name in OPTIONAL_TOOLS:
        if name not in enabled_optional:
            text = _remove_region(text, f"TOOL:{name}")
    if not feng_shui:
        text = _remove_region(text, "FENG_SHUI")
    return _MARKER_LINE.sub("", text)  # drop markers of kept regions


_ENV = jinja2.Environment(
    loader=jinja2.BaseLoader(), autoescape=False, keep_trailing_newline=True
)


def _render(text: str, ctx: dict) -> str:
    return _ENV.from_string(text).render(**ctx)


def compose_persona(skeleton_dir: Path, config: AgentConfig) -> tuple[str, str]:
    enabled_optional = {t for t in config.enabled_tools if t in OPTIONAL_TOOLS}
    ctx = {"identity": asdict(config.identity), "scope": asdict(config.scope)}
    soul = _render(
        strip_tool_regions((skeleton_dir / "SOUL.md").read_text("utf-8"), enabled_optional, config.feng_shui), ctx
    )
    rules = _render(
        strip_tool_regions((skeleton_dir / "RULES.md").read_text("utf-8"), enabled_optional, config.feng_shui), ctx
    )
    return soul, rules
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_persona_compose.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/persona_compose.py tests/unit/unified/test_persona_compose.py
git commit -m "feat(persona): compose_persona — strip tool regions + render placeholders"
```

---

## Task 4: `build_agent_def_from_config` + `build_schemas` brand/rankers override

**Files:**
- Modify: `src/noble_agent/agent/tools/schemas.py:631` (`build_schemas`)
- Modify: `src/noble_agent/agent/base.py` (append `build_agent_def_from_config`)
- Test: `tests/unit/unified/test_build_agent_def_from_config.py`

**Interfaces:**
- Consumes: `AgentConfig` (Task 1), `compose_persona` (Task 3).
- Produces:
  - `build_schemas(names, *, brand: dict | None = None, rankers: frozenset | None = None) -> list[dict]` (override tùy chọn; None → hành vi cũ đọc `get_tenant_context()`).
  - `build_agent_def_from_config(skeleton_dir: Path, config: AgentConfig, *, model: str, temperature: float, max_tokens: int) -> AgentDef`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_build_agent_def_from_config.py
from pathlib import Path

import noble_agent
from noble_agent.agent.agent_config import parse_config
from noble_agent.agent.base import build_agent_def_from_config

SKELETON = Path(noble_agent.__file__).resolve().parent / "persona"


def _cfg(**tools):
    return parse_config({
        "identity": {"agent_name": "Luna", "brand": "An Phú Land"},
        "scope": {"does": "Tư vấn.", "does_not": "Hậu mãi.", "refusal": "Xin lỗi.", "handoff_department": "CSKH"},
        "tools": tools,
    })


def test_builds_agentdef_with_enabled_tools():
    cfg = _cfg(enabled=["booking", "recommend_units"], feng_shui=True)
    ad = build_agent_def_from_config(SKELETON, cfg, model="m", temperature=0.5, max_tokens=700)
    assert ad.name == "Luna"
    assert ad.model == "m" and ad.temperature == 0.5 and ad.max_tokens == 700
    names = {s["function"]["name"] for s in ad.tool_schemas}
    assert {"update_customer", "kb_search", "find_project", "escalate", "booking", "recommend_units"} <= names
    assert "discover_projects" not in names          # not enabled


def test_brand_rendered_into_tool_schema():
    cfg = _cfg(enabled=[])
    ad = build_agent_def_from_config(SKELETON, cfg, model="m", temperature=0.7, max_tokens=800)
    blob = str(ad.tool_schemas)
    assert "{{ brand" not in blob and "{{brand" not in blob   # brand tokens rendered
    assert "An Phú Land" in blob                              # rendered from config.identity.brand


def test_feng_shui_off_strips_recommend_params():
    cfg = _cfg(enabled=["recommend_units"], feng_shui=False)
    ad = build_agent_def_from_config(SKELETON, cfg, model="m", temperature=0.7, max_tokens=800)
    ru = next(s for s in ad.tool_schemas if s["function"]["name"] == "recommend_units")
    props = ru["function"]["parameters"]["properties"]
    assert "birth_year" not in props and "menh" not in props   # feng-shui params gated off
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_build_agent_def_from_config.py -q`
Expected: FAIL — `build_agent_def_from_config` chưa tồn tại.

- [ ] **Step 3a: Make `build_schemas` accept overrides**

Trong `src/noble_agent/agent/tools/schemas.py`, đổi chữ ký + 2 chỗ đọc context. Thay dòng `def build_schemas(names: list[str]) -> list[dict]:` thành:

```python
def build_schemas(
    names: list[str], *, brand: dict | None = None, rankers: frozenset | None = None
) -> list[dict]:
```

Trong thân, thay khối rankers (dòng ~656–659):

```python
    # 2) Gate the feng-shui overlay params behind rankers (override or manifest).
    if rankers is None:
        try:
            rankers = get_tenant_context().rankers
        except Exception:
            rankers = frozenset({"feng_shui"})  # default: Noble behaviour
```

và khối brand (dòng ~671–674):

```python
    if brand is None:
        try:
            brand = dict(get_tenant_context().brand)
        except Exception:
            brand = dict(_BRAND_DEFAULTS)
```

- [ ] **Step 3b: Add `build_agent_def_from_config` to `base.py`**

Append vào `src/noble_agent/agent/base.py`:

```python
def build_agent_def_from_config(
    skeleton_dir: Path | str,
    config,  # noble_agent.agent.agent_config.AgentConfig
    *,
    model: str,
    temperature: float,
    max_tokens: int,
) -> AgentDef:
    """Build an AgentDef from the shared on-disk skeleton + a parsed AgentConfig
    (DB path). Marker-strips + renders SOUL/RULES, offers config.enabled_tools,
    renders brand from config.identity.brand, gates feng-shui by config.feng_shui."""
    from noble_agent.agent.persona_compose import compose_persona
    from noble_agent.agent.tools.schemas import build_schemas

    d = Path(skeleton_dir)
    env = jinja2.Environment(
        loader=jinja2.BaseLoader(), autoescape=False, keep_trailing_newline=True
    )
    tmpl = env.from_string(_read(d / "PROMPT_TEMPLATE.md"))
    soul, rules = compose_persona(d, config)
    sections = {"soul": soul, "rules": rules, "customer_format": _read(d / "CUSTOMER_PROFILE.md")}

    brand = {"company": config.identity.brand, "app_name": config.identity.brand}
    rankers = frozenset({"feng_shui"}) if config.feng_shui else frozenset()
    tool_names = list(config.enabled_tools)
    tool_schemas = build_schemas(tool_names, brand=brand, rankers=rankers)

    return AgentDef(
        name=config.identity.agent_name,
        model=model,
        temperature=float(temperature),
        max_tokens=int(max_tokens),
        prompt_template=tmpl,
        sections=sections,
        tool_names=tool_names,
        tool_schemas=tool_schemas,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_build_agent_def_from_config.py tests/unit/unified/test_build_schemas.py -q`
Expected: PASS (3 new + `test_build_schemas` regressions still green — override defaults None ⇒ hành vi cũ).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/agent/base.py src/noble_agent/agent/tools/schemas.py tests/unit/unified/test_build_agent_def_from_config.py
git commit -m "feat(agent): build_agent_def_from_config + build_schemas brand/rankers override"
```

---

## Task 5: Postgres config reader (`agent_config_store.py`)

**Files:**
- Create: `src/noble_agent/storage/agent_config_store.py`
- Test: `tests/unit/unified/test_agent_config_store.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) PublishedConfig(version: int, config: dict)`
  - `async read_published_config(tenant_id: str, *, pool=None) -> PublishedConfig | None`
  - Đọc VIEW `agent_published_config(tenant_id, version, config)` qua `tenant_conn`; ghi last-good ra đĩa khi thành công; trả last-good khi DB lỗi; None khi không có gì.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_agent_config_store.py
import pytest

from noble_agent.storage import agent_config_store as acs
from noble_agent.storage.agent_config_store import PublishedConfig, read_published_config


class _FakeTxn:
    async def __aenter__(self): return None
    async def __aexit__(self, *a): return False


class _FakeConn:
    def __init__(self, row): self._row = row
    def transaction(self): return _FakeTxn()
    async def execute(self, *a): return None
    async def fetchrow(self, *a): return self._row


class _FakeAcq:
    def __init__(self, conn): self._c = conn
    async def __aenter__(self): return self._c
    async def __aexit__(self, *a): return False


class _FakePool:
    def __init__(self, row): self._conn = _FakeConn(row)
    def acquire(self): return _FakeAcq(self._conn)


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(acs, "_CACHE_DIR", tmp_path)


async def test_reads_row_and_parses_jsonb_string():
    pool = _FakePool({"version": 3, "config": '{"identity": {"agent_name": "Luna"}}'})
    pc = await read_published_config("org_a1b2c3d4_x", pool=pool)
    assert pc == PublishedConfig(version=3, config={"identity": {"agent_name": "Luna"}})


async def test_none_when_no_row():
    pool = _FakePool(None)
    assert await read_published_config("org_a1b2c3d4_x", pool=pool) is None


async def test_serves_last_good_on_db_error(monkeypatch):
    ok = _FakePool({"version": 5, "config": {"identity": {"agent_name": "Cached"}}})
    assert (await read_published_config("org_a1b2c3d4_x", pool=ok)).version == 5   # writes last-good

    async def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(acs, "_read_from_db", _boom)
    pc = await read_published_config("org_a1b2c3d4_x")     # DB errors → last-good
    assert pc.version == 5 and pc.config["identity"]["agent_name"] == "Cached"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_agent_config_store.py -q`
Expected: FAIL — module chưa tồn tại.

- [ ] **Step 3: Write minimal implementation**

```python
# src/noble_agent/storage/agent_config_store.py
"""Read the tenant's PUBLISHED agent config from Postgres (Portal-owned VIEW
`agent_published_config`) under RLS, with a last-good on-disk fallback (E01).
See docs/handoff/spec.md §5.3."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("noble_agent.storage.agent_config")

_SQL = "SELECT version, config FROM agent_published_config WHERE tenant_id = $1"
_CACHE_DIR = Path("/var/lib/noble/agent_config_cache")


@dataclass(frozen=True)
class PublishedConfig:
    version: int
    config: dict


async def _read_from_db(tenant_id: str, *, pool=None) -> PublishedConfig | None:
    from noble_agent.storage.postgres_client import get_pool, tenant_conn

    pool = pool or await get_pool()
    async with tenant_conn(pool, tenant_id) as conn:
        row = await conn.fetchrow(_SQL, tenant_id)
    if row is None:
        return None
    cfg = row["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    return PublishedConfig(version=int(row["version"]), config=dict(cfg))


def _cache_file(tenant_id: str) -> Path:
    return _CACHE_DIR / f"{tenant_id}.json"


def _write_last_good(tenant_id: str, pc: PublishedConfig) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_file(tenant_id).write_text(
            json.dumps({"version": pc.version, "config": pc.config}, ensure_ascii=False), "utf-8"
        )
    except Exception:
        logger.warning("agent_config: last-good write failed for %s", tenant_id, exc_info=True)


def _read_last_good(tenant_id: str) -> PublishedConfig | None:
    try:
        raw = json.loads(_cache_file(tenant_id).read_text("utf-8"))
        return PublishedConfig(version=int(raw["version"]), config=dict(raw["config"]))
    except Exception:
        return None


async def read_published_config(tenant_id: str, *, pool=None) -> PublishedConfig | None:
    try:
        pc = await _read_from_db(tenant_id, pool=pool)
    except Exception:
        logger.warning("agent_config: DB read failed for %s — serving last-good", tenant_id, exc_info=True)
        return _read_last_good(tenant_id)
    if pc is not None:
        _write_last_good(tenant_id, pc)
    return pc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/unified/test_agent_config_store.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/noble_agent/storage/agent_config_store.py tests/unit/unified/test_agent_config_store.py
git commit -m "feat(agent-config): Postgres reader for published config + last-good fallback"
```

---

## Task 6: Facade wiring behind `AGENT_CONFIG_SOURCE` flag + settings

**Files:**
- Modify: `src/noble_agent/config.py` (thêm 3 settings)
- Modify: `src/noble_agent/agent/facade.py` (nhánh gated trong `_build_runner_from_ctx`)
- Test: `tests/unit/unified/test_facade_db_config.py`

**Interfaces:**
- Consumes: `read_published_config` (Task 5), `parse_config` (Task 1), `build_agent_def_from_config` (Task 4).
- Produces: khi `settings.agent_config_source == "db"`, `_build_runner_from_ctx` dựng `agent_def` từ config DB thay `load_agent_def(config.json)`. `legacy` (mặc định) không đổi.
- `SKELETON_DIR = Path(noble_agent.__file__).resolve().parent / "persona"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/unified/test_facade_db_config.py
import pytest

from noble_agent import config as cfgmod
from noble_agent.agent import facade
from noble_agent.storage.agent_config_store import PublishedConfig


def test_settings_default_is_legacy():
    s = cfgmod.UnifiedSettings(_env_file=None)
    assert s.agent_config_source == "legacy"
    assert s.agent_temperature == 0.7
    assert s.agent_max_tokens == 800


async def test_db_path_builds_agentdef_from_published_config(monkeypatch):
    async def _fake_read(tenant_id, *, pool=None):
        return PublishedConfig(version=2, config={
            "identity": {"agent_name": "Luna", "brand": "An Phú Land"},
            "scope": {"does": "Tư vấn.", "does_not": "Hậu mãi.", "refusal": "Xin lỗi.",
                      "handoff_department": "CSKH"},
            "tools": {"enabled": ["booking"]},
        })

    monkeypatch.setattr(facade, "read_published_config", _fake_read, raising=False)
    ad = await facade._agent_def_from_db("org_a1b2c3d4_x")
    assert ad.name == "Luna"
    names = {s["function"]["name"] for s in ad.tool_schemas}
    assert "booking" in names and "escalate" in names          # optional + core
    assert "discover_projects" not in names


async def test_db_path_none_raises(monkeypatch):
    async def _none(tenant_id, *, pool=None):
        return None

    monkeypatch.setattr(facade, "read_published_config", _none, raising=False)
    with pytest.raises(RuntimeError, match="no published config"):
        await facade._agent_def_from_db("org_a1b2c3d4_x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/unified/test_facade_db_config.py -q`
Expected: FAIL — settings field + `_agent_def_from_db` chưa tồn tại.

- [ ] **Step 3a: Add settings**

Trong `src/noble_agent/config.py`, thêm vào `UnifiedSettings` (cạnh các field agent khác):

```python
    agent_config_source: str = "legacy"   # "legacy" (config.json/manifest) | "db" (Portal Postgres)
    agent_temperature: float = 0.7        # DB path: replaces persona/config.json
    agent_max_tokens: int = 800           # DB path: replaces persona/config.json
```

- [ ] **Step 3b: Wire the gated branch in facade**

Trong `src/noble_agent/agent/facade.py`, thêm import cạnh các import khác:

```python
from noble_agent.storage.agent_config_store import read_published_config
```

Thêm helper (đặt trước `_build_runner_from_ctx`):

```python
def _skeleton_dir():
    import noble_agent

    return Path(noble_agent.__file__).resolve().parent / "persona"


async def _agent_def_from_db(tenant_id: str):
    """Build an AgentDef from the tenant's PUBLISHED Postgres config + on-disk
    skeleton (AGENT_CONFIG_SOURCE=db). Raises if no published config exists."""
    from noble_agent.agent.agent_config import parse_config
    from noble_agent.agent.base import build_agent_def_from_config

    settings = get_settings()
    pc = await read_published_config(tenant_id)
    if pc is None:
        raise RuntimeError(f"no published config for tenant {tenant_id!r}")
    cfg = parse_config(pc.config)
    return build_agent_def_from_config(
        _skeleton_dir(), cfg,
        model=settings.agent_model if getattr(settings, "agent_model", "") else settings.agent_name,
        temperature=settings.agent_temperature,
        max_tokens=settings.agent_max_tokens,
    )
```

> Lưu ý `model`: đường DB không có `config.json`. `agent_def.model` chỉ là fallback
> cho unit test gọi `run_turn` không định tuyến (routing thực đi qua
> `NOBLE_AGENT_MODEL`/`provider_model_map`, xem `_build_runner_from_ctx` chú thích).
> Dùng `settings.agent_model` nếu có, else một chuỗi non-empty an toàn (`agent_name`).
> Không thêm setting `agent_model` mới trong task này — `getattr(..., "")` cho phép
> vắng mặt.

Sửa `_build_runner_from_ctx` để chọn nguồn agent_def theo cờ. Thay khối:

```python
    settings = get_settings()
    agent_def = load_agent_def(
        ctx.persona_dir, tool_names=list(ctx.enabled_tools), agent_name=settings.agent_name, brand=dict(ctx.brand)
    )
```

bằng:

```python
    settings = get_settings()
    if settings.agent_config_source == "db":
        agent_def = await _agent_def_from_db(ctx.tenant_id)
    else:
        agent_def = load_agent_def(
            ctx.persona_dir, tool_names=list(ctx.enabled_tools), agent_name=settings.agent_name, brand=dict(ctx.brand)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/unified/test_facade_db_config.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Full gate + lint**

Run: `make test-unit` — kỳ vọng: tất cả test mới xanh; **0 regression mới** so với baseline red đã ghi trong CLAUDE.md (2 USD-normalize, 2 `test_tool_ack` flaky, vieneu_vllm, 2 qdrant_adapter, qdrant_store, prompt_builder, send_media). Đường `legacy` mặc định ⇒ các test hiện có không đổi.
Run: `make lint` — kỳ vọng: sạch trên mọi file task này chạm (`agent_config.py`, `persona_compose.py`, `agent_config_store.py`, `base.py`, `schemas.py`, `facade.py`, `config.py`).

- [ ] **Step 6: Commit**

```bash
git add src/noble_agent/config.py src/noble_agent/agent/facade.py tests/unit/unified/test_facade_db_config.py
git commit -m "feat(facade): AGENT_CONFIG_SOURCE=db builds agent_def from Postgres config + skeleton"
```

---

## Self-Review (đã chạy)

**1. Spec coverage** (`docs/handoff/spec.md`):
- §4 config shape → Task 1 `parse_config` (identity/scope/tools/feng_shui/media_channel/data_source). ✔
- §4.3 core union + drop unknown/core-listed → Task 1. ✔
- §10 placeholder + marker + strip → Task 2 (skeleton) + Task 3 (compose). ✔
- §9 core khóa / optional / reserved ẩn → Task 1 `CORE_TOOLS`/`OPTIONAL_TOOLS` (reserved không xuất hiện). ✔
- §5.3 read contract VIEW `agent_published_config` + RLS + last-good → Task 5. ✔
- §8 bỏ config.json / model-temp-max_tokens từ .env / compose-from-DB → Task 4 (build_agent_def_from_config) + Task 6 (settings + wiring). ✔
- Version pin theo cuộc gọi (BR05): `read_published_config` trả `version`; NobleAgent đã pin version tại create() (cơ chế hiện có) — Task 6 cung cấp version qua PublishedConfig. Ghép sâu vào `_runners` cache keyed (tenant,version) là **follow-up** khi Portal ship bảng (live smoke) — nằm ngoài scope plan này, đã ghi Global Constraints. ✔ (gap có chủ đích, được nêu)
- §8 retire MinIO / live PG smoke → OUT OF SCOPE (ghi rõ). ✔

**2. Placeholder scan:** không có "TBD/TODO"; mọi code step có code thật; test step có test thật. ✔

**3. Type consistency:** `AgentConfig`/`Identity`/`Scope` (Task 1) dùng nhất quán ở Task 3/4/6; `build_agent_def_from_config(skeleton_dir, config, *, model, temperature, max_tokens)` khớp giữa Task 4 (định nghĩa) và Task 6 (gọi); `read_published_config(tenant_id, *, pool=None) -> PublishedConfig|None` khớp Task 5↔Task 6; `build_schemas(names, *, brand, rankers)` khớp Task 4 định nghĩa ↔ dùng. ✔

**Gap có chủ đích (không phải thiếu sót):** đấu nối per-conversation version cache + retire MinIO + live PG smoke = follow-up sau khi Portal ship VIEW. Plan này giao đường compose-from-DB **gated tắt mặc định**, test bằng fake pool — flip `AGENT_CONFIG_SOURCE=db` + 1 live smoke là bước kế.
