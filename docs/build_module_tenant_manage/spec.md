# Handoff — Tạo Organization / Tenant & Cấu hình Agent (Portal ↔ Agent)

> **Đối tượng:** team Portal/Dashboard.
> **Mục tiêu:** khi provider tạo workspace tenant (điền form), một agent hội thoại
> được tạo ra ngay. Tài liệu này đặc tả **những gì Portal chịu trách nhiệm**: form
> thu thập, cấu trúc `config`, bảng cấu hình **đánh version**, và **hợp đồng đọc**
> để agent tự lắp ghép prompt lúc chạy.
> **Trạng thái:** contract (chưa implement). Agent-side là một effort song song
> (mục [§8](#8-đổi-kèm-phía-agent-informative-không-phải-việc-của-portal)).

---

## 1. Bức tranh tổng thể

Điểm khác biệt **duy nhất** giữa agent của các tenant là **dữ liệu có cấu trúc**:
danh tính, phạm vi, và tập tool được bật. Phần khung prompt (persona skeleton,
tool schema, luồng hội thoại) là **giống hệt nhau** cho mọi tenant.

Vì vậy kiến trúc tách làm hai:

| Thành phần | Ai sở hữu | Lưu ở đâu |
|---|---|---|
| **Persona skeleton** (SOUL/RULES có marker + placeholder, PROMPT_TEMPLATE, CUSTOMER_PROFILE) | **Agent** | Trên **disk agent** (ship trong wheel), 1 bản dùng chung |
| **Config tenant** (identity / scope / tools) — **đánh version** | **Portal** | **Postgres**, 1..N version/tenant |
| Lắp ghép skeleton + config → prompt | **Agent** | Lúc chạy (request-time) |

```
Request (tenant_id)
  │
  ├─▶ Portal DB   : đọc config version ĐÃ PUBLISH của tenant  ── agent chỉ ĐỌC
  ├─▶ Disk agent  : nạp skeleton SOUL.md / RULES.md
  │
  ├─ strip vùng <!-- TOOL:x --> cho tool KHÔNG bật
  ├─ điền placeholder {{identity.*}} {{scope.*}}
  └─ build tool schema từ tập enabled
        │
        ▼
   prompt hoàn chỉnh
```

> **Không còn** MinIO tenant store cho luồng này. Config sống trong Postgres,
> skeleton sống trên disk agent. (Xem [§8](#8-đổi-kèm-phía-agent-informative-không-phải-việc-của-portal).)

---

## 2. Ranh giới trách nhiệm

**Portal LÀM:**
1. Render form (mục [§3](#3-form-provider-điền)) khi provider tạo/sửa tenant.
2. Map input → object `config` (mục [§4](#4-cấu-trúc-config-jsonb)).
3. Sở hữu bảng cấu hình **đánh version** + logic **draft / publish / rollback**
   + con trỏ `published` (mục [§5](#5-bảng-cấu-hình-versioned--hợp-đồng)).
4. Validate cấu hình **trước khi publish** (mục [§6](#6-validate-trước-khi-publish)).
5. Đảm bảo `tenant_id` đúng định dạng (mục [§7](#7-định-danh-org--tenant)).

**Agent LÀM (không phải việc Portal):**
- Giữ persona skeleton + tool schema.
- Đọc config version đã publish theo `tenant_id`, strip marker, điền placeholder,
  ghép prompt; **pin version theo cuộc gọi** (một cuộc gọi đang chạy giữ nguyên
  version đến hết); refresh định kỳ; fallback last-good.
- Luôn bật 4 **tool lõi** (mục [§4.3](#43-tools)) bất kể config.

Agent **chỉ ĐỌC** bảng config. Portal không cần gọi API nào của agent.

---

## 3. Form provider điền

Hai nhóm (khớp mockup dashboard) + 1 nhóm tool.

### 3.1. Danh tính
| Nhãn form | Key | Bắt buộc | Mặc định | Ghi chú |
|---|---|---|---|---|
| Tên agent | `identity.agent_name` | ✔ | — | vd "Trợ lý", "Luna" |
| Tên thương hiệu | `identity.brand` | ✔ | — | vd "An Phú Land" |
| Xưng hô — agent tự xưng | `identity.honorific_self` | ✔ | `"em"` | vế trái "em ↔ anh/chị" |
| Xưng hô — gọi khách | `identity.honorific_customer` | ✔ | `"anh/chị"` | vế phải |
| Lời chào | `identity.greeting` | ✘ | `""` | câu mở đầu; rỗng → agent dùng mở đầu tự nhiên |

> Gợi ý UI cho "Xưng hô": một control kiểu `em ↔ anh/chị` tách thành 2 giá trị
> `honorific_self` / `honorific_customer`.

### 3.2. Phạm vi
| Nhãn form | Key | Bắt buộc | Mặc định | Ghi chú |
|---|---|---|---|---|
| Agent làm gì | `scope.does` | ✔ | — | vd "Tư vấn dự án và đặt lịch tham quan." |
| Agent không làm gì | `scope.does_not` | ✔ | — | vd "Hậu mãi và giá riêng — chuyển người thật." |
| Câu từ chối ngoài phạm vi | `scope.refusal` | ✘ | (agent có câu mặc định) | câu agent nói khi bị hỏi ngoài phạm vi |
| Phòng ban chuyển tiếp | `scope.handoff_department` | ✔ | `"CSKH"` | phòng ban mặc định khi `escalate` |

### 3.3. Tool
Checklist các capability. **4 tool lõi luôn bật** (hiển thị nhưng **disable
checkbox — không cho bỏ tick**). 8 tool tùy chọn provider tự tick. Chi tiết
mô tả từng tool ở mục [§9](#9-danh-mục-tool). Ngoài ra:
- Sub-toggle **Phong thủy** (`tools.feng_shui`) — chỉ hiện/kích hoạt được khi
  `recommend_units` được bật.
- **Kênh gửi media** (`tools.media_channel`) — chỉ ý nghĩa khi `send_media` bật;
  mặc định `"noblex_app"`.

---

## 4. Cấu trúc `config` (jsonb)

Object Portal ghi vào cột `config` của mỗi version.

```json
{
  "identity": {
    "agent_name": "Trợ lý",
    "brand": "An Phú Land",
    "honorific_self": "em",
    "honorific_customer": "anh/chị",
    "greeting": ""
  },
  "scope": {
    "does": "Tư vấn dự án và đặt lịch tham quan.",
    "does_not": "Hậu mãi và giá riêng — chuyển người thật.",
    "refusal": "Em phụ trách bất động sản An Phú Land — anh/chị muốn tìm hiểu dự án nào không ạ?",
    "handoff_department": "CSKH"
  },
  "tools": {
    "enabled": [
      "discover_projects",
      "get_project_overview",
      "search_units",
      "check_inventory",
      "recommend_units",
      "booking",
      "send_media",
      "get_document"
    ],
    "feng_shui": true,
    "media_channel": "noblex_app"
  },
  "data_source": "pg_kb"
}
```

### 4.1. `identity`
Tất cả là chuỗi. `agent_name` / `brand` / `honorific_self` / `honorific_customer`
bắt buộc non-empty; `greeting` optional (rỗng được).

### 4.2. `scope`
Tất cả là chuỗi. `does` / `does_not` / `handoff_department` bắt buộc non-empty;
`refusal` optional (rỗng → agent dùng câu từ chối mặc định).

### 4.3. `tools`
- `enabled: string[]` — **chỉ các tool TÙY CHỌN** provider tick. **KHÔNG liệt kê
  4 tool lõi** (`escalate`, `update_customer`, `kb_search`, `find_project`) —
  agent **luôn tự union** chúng vào. Kể cả config hỏng/thiếu, 4 lõi vẫn bật ⇒
  không bao giờ mất van an toàn `escalate`.
- Mỗi phần tử phải thuộc tập tool tùy chọn hợp lệ (mục [§9.2](#92-tùy-chọn-provider-tick)).
  Tên lạ → loại (và cảnh báo lúc validate).
- `feng_shui: bool` — bật overlay phong thủy cho `recommend_units`. **Chỉ có tác
  dụng khi `recommend_units` ∈ `enabled`**; nếu `recommend_units` tắt thì bỏ qua.
- `media_channel: string` — mặc định `"noblex_app"`; chỉ ý nghĩa khi
  `send_media` ∈ `enabled`.

### 4.4. `data_source`
Chuỗi, hiện **cố định `"pg_kb"`**. Không phải field provider chọn — Portal set
mặc định `"pg_kb"`. (Để dành cho khả năng đa nguồn dữ liệu sau.)

---

## 5. Bảng cấu hình versioned — hợp đồng

Portal sở hữu bảng + toàn bộ logic version. Dưới đây là **contract** (ngữ nghĩa
bắt buộc); DDL là **tham khảo** — Portal được đặt tên schema/bảng theo quy ước
riêng, miễn giữ đúng ngữ nghĩa + để lộ một **bề mặt đọc ổn định** cho agent
(mục [§5.3](#53-hợp-đồng-đọc-agent)).

Kiến trúc version **soi gương đúng mô hình MinIO hiện tại**: version **bất biến**
sau khi tạo + một **con trỏ published** + `parent_version` để truy vết.

### 5.1. DDL tham khảo

```sql
-- Mỗi version là BẤT BIẾN sau khi ghi. draft là bản làm việc (mutable).
CREATE TABLE agent_config_versions (
    tenant_id       text        NOT NULL,
    version         int         NOT NULL,      -- 1..N, tăng đơn điệu / tenant
    status          text        NOT NULL,      -- 'draft' | 'published' | 'archived'
    config          jsonb       NOT NULL,      -- object ở §4
    parent_version  int         NULL,          -- version nguồn khi dẫn xuất
    created_at      timestamptz NOT NULL DEFAULT now(),
    created_by      text        NULL,
    PRIMARY KEY (tenant_id, version)
);

-- Con trỏ "đang chạy" — publish/rollback = đổi con trỏ này (atomic).
CREATE TABLE agent_config_pointer (
    tenant_id          text        PRIMARY KEY,
    published_version  int         NOT NULL,
    updated_at         timestamptz NOT NULL DEFAULT now()
);
```

### 5.2. Ngữ nghĩa các thao tác
Đối chiếu 1-1 với provisioning MinIO hiện có (SP-C1) để hai team chung từ vựng:

| Thao tác | Ý nghĩa |
|---|---|
| **save-draft** | Ghi (upsert) bản làm việc `status='draft'` cho tenant. **Mutable** — sửa form lưu lại nhiều lần đè lên draft. Chưa ảnh hưởng cuộc gọi đang chạy. |
| **publish** | Snapshot draft → **version mới bất biến** (`version = max+1`, `parent_version = published_version` hiện tại), rồi **dời con trỏ** `published_version` sang version mới. Version cũ giữ nguyên (đánh `archived` tùy chọn). Chỉ publish khi **validate pass** (§6). |
| **rollback** | Dời con trỏ `published_version` về một version cũ đã tồn tại. Không tạo bản ghi mới. |
| **list-versions / diff** | Truy vấn `agent_config_versions` theo `tenant_id`. |

**Bất biến quan trọng:** một hàng version **không bao giờ bị sửa nội dung** sau
khi tạo (trừ nhãn `status`). Điều này đảm bảo cuộc gọi đã pin version N luôn đọc
đúng nội dung N.

### 5.3. Hợp đồng đọc (agent)
Agent, cho `tenant_id` hiện tại, cần lấy **object `config` của version đang
published**. Để agent không phụ thuộc tên bảng nội bộ của Portal, **để lộ một
VIEW ổn định**:

```sql
CREATE VIEW agent_published_config AS
SELECT v.tenant_id, v.version, v.config
FROM   agent_config_versions v
JOIN   agent_config_pointer  p
       ON p.tenant_id = v.tenant_id AND p.published_version = v.version;
```

Agent chỉ truy vấn: `SELECT version, config FROM agent_published_config WHERE tenant_id = <current>`.

**Cách ly tenant:** đặt bảng/VIEW dưới RLS scope theo `tenant_id` **giống hệt
`tenant_data`** (hai policy: `tenant_isolation` @ `current_user` cho Portal +
`agent_runtime` @ `current_setting('app.current_tenant')` cho agent). Agent đọc
dưới role dùng chung + GUC `app.current_tenant` sẵn có ⇒ tự động chỉ thấy config
của đúng tenant. Chi tiết RLS: xem `CLAUDE.md` mục Postgres (SP-E1/Plan 2).

**Chưa có config / chưa publish:** VIEW trả 0 dòng. Agent xử lý fail-closed
(dùng last-good trên đĩa nếu có, hoặc mặc định an toàn) — Portal không cần lo,
nhưng nên đảm bảo **tenant mới được publish v1 ngay khi tạo** để agent có gì mà đọc.

---

## 6. Validate trước khi publish

Portal chặn **publish** nếu cấu hình không hợp lệ (E08 — tương đương gate
`validate_bundle` của MinIO):

1. `config` parse được thành object đúng shape §4.
2. Các field bắt buộc §4.1/§4.2 non-empty.
3. Mọi phần tử `tools.enabled` ∈ tập tool tùy chọn hợp lệ (§9.2). Tên lạ → từ chối
   (hoặc loại + cảnh báo).
4. `tools.enabled` **không được chứa** tool lõi (§9.1) — lõi do agent tự thêm;
   liệt kê lại là thừa/nhầm.
5. Nếu `tools.feng_shui = true` thì `recommend_units` phải ∈ `enabled` (nếu không
   → cảnh báo, và agent sẽ bỏ qua feng_shui).
6. `tenant_id` đúng định dạng §7.
7. `data_source` ∈ {`"pg_kb"`} (hiện tại).

Draft **không** cần pass toàn bộ (đang soạn dở được lưu); chỉ **publish** mới gate.

---

## 7. Định danh org / tenant

Định danh do backend mint (không phải người nhập tự do), khớp code agent hiện có
(`noble_agent.tenant.identity`):

- `org_id` = `org_<rand8>` — `org_` + 8 hex ngẫu nhiên. Vd `org_1d9f1a2f`.
- `tenant_id` = `<org_id>_<slug(tên hiển thị)>` — **tất định, không hậu tố ngẫu
  nhiên**. Vd tên "Demo Sales" trong `org_1d9f1a2f` → `org_1d9f1a2f_demo-sales`.
  - `slug`: fold về `[a-z0-9-]`, cắt tối đa 40 ký tự, không rỗng.
  - `org_id` suy ra từ `tenant_id` bằng cách tách 2 segment đầu — **không cần
    lookup/map**.
- **Ràng buộc:** tên tenant **duy nhất trong một org** (Portal enforce ở tầng
  form). Nhờ `tenant_id` tất định, trùng tên trong cùng org ⇒ trùng `tenant_id`
  ⇒ xung đột — Portal phải chặn từ form. Hai org khác nhau đặt trùng tên thì OK
  (khác prefix `org_`).

Regex tham chiếu: `org_id` `^org_[a-z0-9]{6,32}$`; `tenant_id`
`^org_[a-z0-9]{6,32}_[a-z0-9][a-z0-9_-]*$`.

---

## 8. Đổi kèm phía agent (informative — không phải việc của Portal)

Ghi lại để hai team đồng bộ; đây là effort agent-side, implement riêng:

1. `load_agent_def` **bỏ đọc `config.json`**. `model` / `temperature` /
   `max_tokens` chuyển sang biến `.env` phía agent (runtime knob của ops, không
   phải provider chọn). `agent_name` lấy từ `config.identity.agent_name`.
2. Loader **compose-from-DB**: đọc `config` published (§5.3), nạp skeleton trên
   disk, strip marker theo `enabled`, điền placeholder → prompt. Pin version theo
   cuộc gọi; TTL-refresh; last-good fallback.
3. Skeleton persona (SOUL/RULES gắn marker + placeholder) chuyển từ per-tenant
   thành **1 bản dùng chung** trên disk agent.
4. **Retire** MinIO tenant store + org-nesting `<org_id>/<tenant_id>/` +
   versioning-trên-MinIO (SP-C) + heartbeat-ghi-MinIO **cho luồng config**.

---

## 9. Danh mục tool

Portal render mỗi tool tùy chọn thành 1 checkbox (label + mô tả ngắn dưới đây).
4 tool lõi hiển thị nhưng khóa ON.

### 9.1. Lõi — khóa ON (agent tự thêm, KHÔNG nằm trong `tools.enabled`)
| Tool | Vai trò |
|---|---|
| `escalate` | Chuyển sang người thật (hậu mãi, giá riêng, khiếu nại, vượt phạm vi). Van an toàn — không cho tắt. |
| `update_customer` | Lưu thông tin cá nhân người gọi (tên, giới tính, ngân sách, dự án quan tâm, khu vực, số phòng ngủ). |
| `kb_search` | Tra cứu kho tri thức (tiện ích, vị trí, pháp lý, chính sách, giá qua tài liệu). |
| `find_project` | Giải tên dự án khách nói → mã chuẩn nội bộ (feed mọi tool dự án). |

### 9.2. Tùy chọn — provider tick
| Tool | Mô tả cho form |
|---|---|
| `discover_projects` | Khám phá/liệt kê dự án theo tiêu chí (khu vực, ngân sách, loại hình, chủ đầu tư), có phân trang. |
| `get_project_overview` | Giới thiệu tổng quan một dự án. |
| `get_document` | Gửi link tài liệu (chính sách bán hàng / pháp lý / brochure). |
| `search_units` | Tìm căn theo tiêu chí (số phòng ngủ, khoảng giá, mã căn). |
| `check_inventory` | Tóm tắt tồn kho (còn/hết, đếm theo loại căn/hướng). |
| `recommend_units` | Gợi ý căn phù hợp theo ngân sách/khu vực/số PN. *(bật Phong thủy để gợi ý theo tuổi/mệnh/năm sinh).* |
| `booking` | Đặt / đổi / xem lịch tham quan dự án. |
| `send_media` | Chủ động gửi ảnh/video minh họa dự án qua app. |

Sub-toggle:
| Toggle | Điều kiện | Tác dụng |
|---|---|---|
| `tools.feng_shui` | cần `recommend_units` bật | Bật overlay phong thủy (tham số năm sinh/giới tính/mệnh/con giáp) trong gợi ý căn. |
| `tools.media_channel` | cần `send_media` bật | Kênh gửi media, mặc định `noblex_app`. |

### 9.3. Reserved — ẩn khỏi form
`crm_lookup`, `verify_identity`, `support_ticket` — đã đăng ký builtin nhưng
**không đưa vào form** (thuộc hậu mãi → dùng `escalate`). Dashboard **ẩn** ba tool
này.

---

## 10. Phụ lục — quy ước placeholder & marker trong skeleton (FYI)

Đây là quy ước **agent-owned** trong file skeleton. Portal **không sửa** skeleton;
thông tin này chỉ để Portal hiểu `config` được lắp vào prompt ra sao (và nếu muốn,
dựng live-preview trong dashboard). **Chủ sở hữu chuẩn là agent** — nếu agent đổi
quy ước, agent cập nhật lại phụ lục này.

### 10.1. Placeholder (điền từ `config`)
| Token trong skeleton | Nguồn |
|---|---|
| `{{identity.agent_name}}` | `config.identity.agent_name` |
| `{{identity.brand}}` | `config.identity.brand` |
| `{{identity.honorific_self}}` | `config.identity.honorific_self` |
| `{{identity.honorific_customer}}` | `config.identity.honorific_customer` |
| `{{identity.greeting}}` | `config.identity.greeting` (rỗng → dòng bị bỏ) |
| `{{scope.does}}` | `config.scope.does` |
| `{{scope.does_not}}` | `config.scope.does_not` |
| `{{scope.refusal}}` | `config.scope.refusal` (rỗng → dùng mặc định) |
| `{{scope.handoff_department}}` | `config.scope.handoff_department` |

### 10.2. Marker vùng tool (strip khi tool tắt)
Mỗi tool tùy chọn "sở hữu" một hoặc vài đoạn text (rule protocol + hàng catalog).
Các đoạn đó bọc trong cặp marker riêng dòng:

```
<!-- TOOL:booking:START -->
6. Đặt lịch tham quan: gọi booking(action="check_availability" → "schedule" ...).
| Đặt/đổi/xem lịch tham quan | booking(...) |
<!-- TOOL:booking:END -->
```

Lúc chạy, với mỗi tool **không** thuộc tập enabled (đã union lõi), agent **xóa
nguyên khối** giữa `START` và `END` của tool đó. Vùng **Phong thủy** lồng trong
`recommend_units`, gate thêm bởi `tools.feng_shui`:

```
<!-- TOOL:recommend_units:START -->
| Gợi ý căn phù hợp | recommend_units(...) |
<!-- FENG_SHUI:START -->
- Phong thủy: khi khách hỏi theo tuổi/mệnh/năm sinh → recommend_units(birth_year, gender, menh, zodiac).
<!-- FENG_SHUI:END -->
<!-- TOOL:recommend_units:END -->
```

Các câu trong skeleton mà **lẽ ra liệt kê tên nhiều tool** (phân loại nhu cầu,
"tín hiệu chuyển chuyên viên") được **viết lại generic** để không phụ thuộc tool
cụ thể ⇒ không cần marker lẻ. Base (xưng hô, bắt buộc gọi tool, update_customer,
escalate, find_project, kb_search, style, guardrails, khối `{{scope.*}}`) **không
bao giờ bị strip**.

---

## 11. Ví dụ end-to-end

Provider "An Phú Land" tạo tenant "Demo Sales", **tắt `booking` và `get_document`**,
bật Phong thủy. Backend mint `tenant_id = org_1d9f1a2f_demo-sales`, publish v1 với
`config`:

```json
{
  "identity": { "agent_name": "Trợ lý", "brand": "An Phú Land",
                "honorific_self": "em", "honorific_customer": "anh/chị", "greeting": "" },
  "scope": { "does": "Tư vấn dự án và đặt lịch tham quan.",
             "does_not": "Hậu mãi và giá riêng — chuyển người thật.",
             "refusal": "", "handoff_department": "CSKH" },
  "tools": { "enabled": ["discover_projects","get_project_overview","search_units",
                         "check_inventory","recommend_units","send_media"],
             "feng_shui": true, "media_channel": "noblex_app" },
  "data_source": "pg_kb"
}
```

Lúc có cuộc gọi, agent: đọc v1 → tập tool = 4 lõi ∪ 6 tùy chọn (⇒ **không** có
`booking`, `get_document`) → **xóa** vùng `<!-- TOOL:booking -->` và
`<!-- TOOL:get_document -->` trong RULES → giữ vùng `recommend_units` + `FENG_SHUI`
→ điền `{{identity.*}}`/`{{scope.*}}` → prompt hoàn chỉnh. `booking`/`get_document`
không xuất hiện cả trong luật lẫn trong tool schema ⇒ agent không đề cập, không gọi.
