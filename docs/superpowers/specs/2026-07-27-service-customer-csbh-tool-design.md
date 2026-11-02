# Thiết kế: tool `service_customer` (chăm sóc khách hàng — chính sách CSBH)

**Ngày:** 2026-07-27
**Branch:** `feat/refactor2`
**Trạng thái:** đã duyệt thiết kế, chờ viết plan

## 1. Mục tiêu

Thêm tool `service_customer` cho tenant **noble** để trả lời các câu hỏi về
**chính sách bán hàng / chính sách khuyến mãi / chính sách vay vốn** của một dự án
cụ thể. Nguồn dữ liệu là các point trong collection Qdrant `media_v3` có
`category == "csbh"`.

Tool:

1. Nhận tham số `project_code`.
2. Đưa nội dung `caption` (của các point csbh thuộc dự án đó) vào **context của
   LLM** để Luna trả lời đúng câu hỏi cụ thể.
3. Gửi **media** (ảnh + tối đa 1 video) cho app y hệt cách `send_media` đang làm —
   **nếu có** media render được; nếu không thì thôi (vẫn trả lời bằng caption).
4. Nếu dự án **không có** point `category=csbh` → trả câu
   `"Thông tin câu hỏi của anh chị đã được gửi cho bên sale ạ"` **và** thực sự
   escalate sang CVTV/sale.

Đồng thời **bỏ tool `get_project_financial`** khỏi danh sách offered của noble
(trùng lặp nội dung — chính sách tài chính/vay vốn nay do `service_customer` phụ
trách). Code `get_project_financial` **giữ nguyên** đăng ký built-in để rollback,
chỉ gỡ khỏi `manifest.enabled`.

## 2. Bối cảnh đã xác minh

- Collection `media_v3` tồn tại trên Qdrant KB live (`10.50.13.220:6333`, cùng
  `QDRANT_URL`/`QDRANT_API_KEY` với KB). Payload mỗi point:
  `project_id`, `category`, `content_type`, `caption`, `media_url`, `thumb_url`,
  `content_hash`.
- Một dự án có thể có ≥1 point `csbh`.
- Custom tenant tool tự đăng ký qua `@tool(...)` + `tenant/loader.py::_import_tenant_tools`
  (pkgutil walk `tenants/<id>/tools/`). Noble hiện **chưa** có package `tools/`.
- **Lỗ hổng phát hiện được:** `agent/tools/schemas.py::build_schemas` chỉ dựng
  schema từ dict `SCHEMAS` tĩnh → custom tool tuy dispatch được (qua registry)
  nhưng **schema không bao giờ được cấp cho LLM**. Tool `check_loan` của
  `demo_acme` cũng dính lỗi tiềm ẩn này. Thiết kế phải vá `build_schemas`, nếu
  không `service_customer` đăng ký được nhưng Luna không gọi được.
- Cơ chế hiển thị media: `dispatcher.on_tool_done` gửi **full result (kèm
  `items[]`)** cho client; `_strip_display_items` (allowlist `_DISPLAY_ITEMS_TOOLS`)
  loại `items[]` khỏi bản copy ghi vào `state.history`. Client render bất kỳ tool
  nào trả `items[]`.
- Cơ chế escalate: data tool trả chuỗi `ESCALATE_SIGNAL`
  (`"Thông tin đã được chuyển đến chuyên viên tư vấn"`, từ
  `data/providers/base.py`); `dispatcher.dispatch` thấy substring này trong
  result (và `name != "escalate"`) → tự gọi `support_ops.escalate(action=transfer,
  department=CVTV)`. Result trả cho LLM giữ nguyên.

## 3. Vị trí & đăng ký (kiến trúc SaaS)

- `src/noble_agent/tenants/noble/tools/__init__.py` — rỗng.
- `src/noble_agent/tenants/noble/tools/service_customer.py` — executor +
  `@tool(name="service_customer", schema=_SCHEMA, tenant="noble", read_only=True,
  dirties_customer=False)`.
- Loader vốn đã gọi `_import_tenant_tools("noble")` cho mọi lần load tenant → tool
  tự đăng ký khi boot. Không cần sửa loader.

Executor nhận kwargs bag của dispatcher; chỉ dùng `args`, `customer`,
`session_id` (chữ ký `async def service_customer(args, *, customer, session_id,
**_) -> str`).

## 4. Truy cập dữ liệu

- Tái dùng singleton client Qdrant của KB: `agent/rag/qdrant_store._get_client()`
  (cùng server/api-key). Không tạo client thứ hai.
- Tên collection: đọc env `CSBH_MEDIA_COLLECTION` (mặc định `media_v3`) ngay trong
  tool (self-contained, giống `support_ops` đọc `SANTA_MODELS_TOKEN` trực tiếp từ
  `os.environ`). Không thêm field vào `config.py`.
- Truy vấn = `client.scroll(collection, scroll_filter=Filter(must=[project_id==code,
  category=="csbh"]), with_payload=True, with_vectors=False, limit=N)` — **không**
  cần query vector. Lấy toàn bộ point csbh của dự án (limit an toàn, ví dụ 16).

## 5. Tham số

- `project_code` (string, optional). Rỗng → mặc định lấy
  `customer.project_interest`. Chuẩn hoá `.strip().upper()`.
- Schema:

```json
{
  "type": "function",
  "function": {
    "name": "service_customer",
    "description": "<mô tả KHI NÀO gọi: khách hỏi chính sách bán hàng / khuyến mãi / vay vốn của một dự án cụ thể + 1 ví dụ>",
    "parameters": {
      "type": "object",
      "properties": {
        "project_code": {"type": "string", "description": "Mã dự án khách muốn hỏi chính sách. Để trống nếu đã biết dự án khách quan tâm."}
      },
      "required": []
    }
  }
}
```

## 6. Định dạng kết quả

### 6.1 Có point csbh

```json
{
  "ok": true,
  "project_name": "<tên dự án>",
  "context": "<nối tất cả caption, phân tách rõ ràng>",
  "items": [ ...≤6 ảnh + ≤1 video... ],
  "count": <số item>,
  "message": "Dạ em gửi thông tin chính sách qua app cho anh/chị rồi ạ."
}
```

- `context` = nối các `caption` gốc của các point csbh (bằng `"\n\n---\n\n"` hoặc
  tương tự). Đây là **nguồn duy nhất** để LLM trả lời.
- `items` dựng bằng cách **tái dùng `media_data._map_items(payloads)`** (payload
  media_v3 khớp đúng shape hit mà `_map_items`/`_hit_to_item` mong đợi:
  `media_url`, `thumb_url`, `caption`, `content_type`) → render trên app giống hệt
  `send_media` (≤6 ảnh + ≤1 video, hỗ trợ `thumb`).
- Nếu có caption nhưng **không** map được item nào (không có media render được) →
  vẫn trả `context`, `items: []`, `count: 0`, `message` đổi thành câu chỉ có nội
  dung chính sách (không nhắc "gửi hình"). Trả lời vẫn hoạt động.

### 6.2 BẤT BIẾN chống trùng lặp context (yêu cầu của người dùng)

`media_data._map_items` gán caption vào `label` (ảnh) / `title` (video) của item.
Nếu cả `items` lẫn `context` cùng vào history thì caption bị lặp 2 lần trong
context của LLM. **Giải quyết:** thêm `service_customer` vào `_DISPLAY_ITEMS_TOOLS`
→ `items[]` bị strip khỏi bản ghi history. Kết quả: trong `state.history` chỉ còn
`context` (caption xuất hiện **đúng 1 lần**); `items` (kèm caption) chỉ tới app.
Đây là lý do caption phải nằm ở `context` riêng — nếu chỉ để trong items thì sau
strip LLM không còn chữ để trả lời.

Test phải khẳng định: bản history sau `_strip_display_items` **không** chứa `items`,
và caption chỉ xuất hiện một lần.

### 6.3 Không có csbh / thiếu mã / lỗi Qdrant

```json
{
  "ok": false,
  "note": "no_csbh",
  "message": "Thông tin câu hỏi của anh chị đã được gửi cho bên sale ạ",
  "signal": "Thông tin đã được chuyển đến chuyên viên tư vấn"
}
```

- Trường `signal` = hằng `ESCALATE_SIGNAL` (import từ
  `data.providers.base`). Vì `dispatch()` kiểm tra `ESCALATE_SIGNAL in result`
  (substring trên chuỗi JSON), việc nhúng vào một field là đủ để dispatcher
  **tự động escalate** sang CVTV/sale. Result trả cho LLM giữ nguyên → Luna đọc
  `message`.
- **Ba nhánh cùng trả payload này** (quyết định mở rộng đã duyệt):
  - dự án không có point csbh nào;
  - `project_code` rỗng và `customer.project_interest` cũng rỗng;
  - Qdrant lỗi / scroll ném exception (bắt trong tool → không raise).
- Tool **không bao giờ raise** ra ngoài (đồng thuận với quy ước tool-boundary).

## 7. Sửa vào core (tối thiểu — 4 chỗ)

1. **`agent/tools/dispatcher.py`** — thêm `"service_customer"` vào
   `_DISPLAY_ITEMS_TOOLS` (comment tại đó đã mời "Add a new media tool here").
2. **`agent/tools/schemas.py::build_schemas`** — sau khi dựng `out` từ `SCHEMAS`
   tĩnh, với mỗi `name` trong `names` **không** có trong `SCHEMAS`: lấy
   `spec = registry.resolve(tenant_id, name)` (tenant_id từ
   `get_tenant_context().tenant_id`, fallback `"noble"` nếu context chưa dựng);
   nếu `spec` và `spec.schema` → append `deepcopy(spec.schema)`. Bảo toàn thứ tự
   theo `names`. Đây là fix biến custom tool thành first-class (được offer, không
   chỉ dispatch được) và tiện thể sửa `check_loan`. Không đụng `schemas_for`
   (giữ injection-free cho caller cũ).
3. **`tenants/noble/manifest.toml`** — bỏ `"get_project_financial"`, thêm
   `"service_customer"` trong `[tools].enabled`.
4. **`tenants/noble/persona/RULES.md`** — thêm dòng tool-catalog cho
   `service_customer` (KHI NÀO gọi: khách hỏi chính sách bán hàng/khuyến mãi/vay
   vốn của một dự án → gọi `service_customer` với `project_code`); gỡ/định tuyến
   lại các tham chiếu `get_project_financial` (các câu hỏi giá/chính sách tài chính
   nay đi qua `service_customer`, phần còn lại escalate).

Không xoá code `get_project_financial` (schema trong `SCHEMAS`, adapter trong
`builtins.py` giữ nguyên) — chỉ gỡ khỏi offered list; rollback = thêm lại 1 dòng
manifest.

## 8. Kiểm thử

Unit test (mock `qdrant_store._get_client()` / hàm scroll):

- **Có csbh:** `context` chứa các caption; `items` map đúng (ảnh + video);
  `ok:true`, `count`, `message`.
- **Chống trùng lặp:** kết quả sau `_strip_display_items("service_customer", ...)`
  không còn `items`; caption chỉ xuất hiện 1 lần trong bản history.
- **Không csbh:** `ok:false`, đúng câu message, `signal == ESCALATE_SIGNAL`.
- **Thiếu mã (project_code rỗng + project_interest rỗng):** → handoff payload.
- **Lỗi Qdrant (scroll raise):** → handoff payload, không raise.
- **Có caption nhưng không media render được:** `context` có chữ, `items:[]`.
- **`build_schemas`:** khi tenant=noble và `service_customer` được enable →
  schema `service_customer` có trong output (được offer); tenant không enable →
  không có. Regression: schema built-in cũ vẫn nguyên, `get_project_financial`
  vẫn build được khi có trong names.
- **Manifest:** `get_project_financial` vắng, `service_customer` có mặt trong
  `enabled` của noble; agent load ra đúng bộ tool.

Sau code: smoke live `/chat` theo `SMOKE.md` — hỏi chính sách một dự án có csbh
(nhận caption + ảnh trên app), và một dự án không có csbh (nhận câu handoff +
escalate ghi nhận).

## 9. Ngoài phạm vi

- Không đổi provider layer / `NOBLE_DATA_SOURCE`.
- Không xoá code `get_project_financial`.
- Không đụng transport/client render (đã generic theo `items[]`).
- Không thêm vector search cho media (chỉ scroll theo filter).
