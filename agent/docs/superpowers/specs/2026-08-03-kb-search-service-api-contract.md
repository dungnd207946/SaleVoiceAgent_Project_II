# `kb_search` Retrieval Service — API Contract

> **Mục đích:** Quy chuẩn input/output cho service truy hồi tri thức văn bản
> (`<slug>_documents`) mà **team RAG** phát triển và vận hành riêng. Agent chỉ là
> **client**: gọi tool `kb_search` → gửi request → nhận `hits` có cấu trúc → tự
> format thành ngữ cảnh cho LLM. Đây là **hợp đồng giao diện** để agent-team và
> RAG-team thống nhất; không ràng buộc cách triển khai nội bộ của service.
>
> Phạm vi: **CHỈ `kb_search`** (truy hồi văn bản). `send_media` giữ nguyên service
> hybrid visual hiện tại (`:8015`, collection `media_v2`) — KHÔNG thuộc contract này.
>
> Tham chiếu thiết kế: `docs/BA-docs/db-design/db-design/02-knowledge-base.md` §8,
> `02b-rag-service.md` §4 (pipeline TEXT → `<slug>_documents`, hybrid dense+sparse RRF).

---

## 1. Tổng quan

- **Bên sở hữu service:** RAG-team. Service đọc Postgres KB (`tenant_data.projects`
  / `zones` / `documents`) → embed (e5 dense + BM25 sparse) → Qdrant collection
  `<slug>_documents` mỗi workspace; truy hồi hybrid RRF.
- **Bên client:** agent (`noble_agent`) qua tool `kb_search`.
- **Ranh giới:** agent gửi `query` + `tenant_id` + phạm vi dự án; service trả danh
  sách `hits` đã xếp hạng. Agent **không** biết tên collection, không biết cơ chế
  embed/fusion; service **không** biết format prompt của agent.

```
LLM tool kb_search(query, project_filter)
   │  agent map: project_filter → project_codes ([] hoặc [1 mã])
   ▼
POST /v1/kb_search  ──►  RAG service  ──►  Qdrant <slug>_documents (dense+sparse RRF,
   │                                        filter project_id ∈ {project_codes, "__ALL__"})
   ◄── { hits: [ {text, project_code, project_name, …} ] }
   │
   ▼  agent format hits → block ngữ cảnh → nhét vào prompt LLM
```

---

## 2. Transport & Auth

| Mục | Giá trị |
|---|---|
| Protocol | HTTP REST |
| Endpoint | `POST /v1/kb_search` |
| Content-Type | `application/json` (request & response) |
| Auth | `Authorization: Bearer <token>` — agent giữ token qua config `KB_SEARCH_TOKEN`. Rỗng → không gửi header (chế độ tin-mạng nội bộ). |
| Health probe (khuyến nghị) | `GET /health` → `200` khi service sẵn sàng |
| Tính chất | stateless · read-only · idempotent |

Agent cấu hình endpoint qua `KB_SEARCH_URL` (mặc định gợi ý dạng
`http://<host>:<port>/v1/kb_search`), song song với `MEDIA_SEARCH_URL` hiện có.

---

## 3. Request

### 3.1 Body schema

| Field | Kiểu | Bắt buộc | Mặc định | Ý nghĩa |
|---|---|:--:|---|---|
| `query` | string | ✅ | — | Câu truy vấn của khách (đã là text thuần, không rỗng sau `strip`). |
| `tenant_id` | string | ✅ | — | Định danh workspace (vd `"noble"`). **Service tự map** `tenant_id` → collection `<slug>_documents`. Agent không gửi tên collection. |
| `project_codes` | string[] | ❌ | `[]` | Các mã dự án đang active để thu hẹp. **`[]` = tìm toàn bộ dự án.** Service **LUÔN tự union thêm `"__ALL__"`** (tài liệu chung tenant) — agent không tự thêm. |
| `top_k` | int | ❌ | `5` | Số hit tối đa trả về. |
| `min_score` | float | ❌ | `0.0` | Ngưỡng lọc điểm; `0.0`/bỏ trống = không lọc. |

### 3.2 Ràng buộc

- `query` rỗng/chỉ khoảng trắng → service trả `400` (agent đã tự chặn trước khi gọi,
  nhưng service vẫn nên phòng thủ).
- `project_codes` chứa mã không tồn tại trong tenant → service **bỏ qua mã đó**
  (không lỗi); nếu sau khi bỏ còn `[]` thì hành xử như "toàn bộ dự án" (+ `"__ALL__"`).
- Phần tử `"__ALL__"` nếu client lỡ gửi → chấp nhận, không nhân đôi.

---

## 4. Response — `200 OK`

### 4.1 Envelope

```jsonc
{
  "hits": [ /* HitObject[], đã xếp hạng giảm dần */ ],
  "query_echo": "…",   // tùy chọn — debug
  "latency_ms": 42     // tùy chọn — debug
}
```

### 4.2 `HitObject`

| Field | Kiểu | Bắt buộc | Ý nghĩa |
|---|---|:--:|---|
| `text` | string | ✅ | Nội dung chunk (đơn vị truy hồi). |
| `project_code` | string | ✅ | Mã dự án của chunk (= `project_id`). `"__ALL__"` cho tài liệu chung tenant. |
| `project_name` | string | ✅ | Tên dự án — agent dùng để trích dẫn với khách. |
| `section` | string | ❌ | Breadcrumb ngữ cảnh, vd `"Noble Crystal › tiện ích"`. |
| `score` | float | ❌ | Điểm RRF. **Vắng → agent dùng thứ tự trả về làm thứ hạng.** |
| `doc_type` | string | ❌ | Loại tài liệu: `thong_tin` / `tong_quan` / `phan_khu` / `tai_lieu` … |
| `source_file_url` | string \| null | ❌ | Link file gốc (PDF) để trích dẫn / gửi khách; `null` khi không có. |
| `updated_at` | string (ISO-8601) | ❌ | Mốc cập nhật nguồn — agent surface "cập nhật lúc {updated_at}" (02b §4). |
| `chunk_index` | int | ❌ | Thứ tự chunk trong nguồn. |

### 4.3 Ngữ nghĩa

- **Thứ tự `hits` là thứ hạng cuối cùng** (đã hybrid RRF + lọc theo filter). Agent có
  thể cắt thêm theo `top_k` / `min_score` phía mình nếu muốn.
- **Không có kết quả** = `200` với `"hits": []`. Đây **KHÔNG phải lỗi** — agent hiểu
  là "không có ngữ cảnh" và tiếp tục lượt bình thường.
- **`"__ALL__"` luôn được gộp** vào phạm vi tìm bởi service → tài liệu chung tenant
  (giới thiệu công ty, quy trình mua, brochure…) luôn khả kiến.
- **Cách ly tenant** do service cưỡng chế theo `tenant_id` (collection riêng
  `<slug>_documents`); một `tenant_id` không bao giờ thấy chunk của tenant khác.

---

## 5. Mã lỗi & hành vi degrade

| HTTP | Khi nào | Body | Agent xử lý |
|---|---|---|---|
| `200` | Thành công (kể cả 0 hit) | `{hits:[…]}` | Dùng `hits` (rỗng = không ngữ cảnh). |
| `400` | Thiếu `query` hoặc `tenant_id` | `{error, message}` | Coi như không ngữ cảnh (không nên xảy ra — agent tự validate trước). |
| `401` | Token sai/thiếu | `{error}` | Log + không ngữ cảnh. |
| `5xx` / timeout | Service lỗi/quá tải | (bất kỳ) | Log + **không ngữ cảnh**. |

**Quy tắc bất biến phía agent:** mọi lỗi transport / non-2xx / timeout đều được bắt
và **degrade về "không có ngữ cảnh" (trả rỗng cho LLM)** — **không bao giờ làm vỡ
lượt hội thoại**. Timeout mặc định phía agent ~`10s` (tương đương service media hiện tại).

---

## 6. Ví dụ

### 6.1 Một dự án (`kb_search("tiện ích", "NCLB")`)

**Request**
```json
POST /v1/kb_search
Authorization: Bearer <token>
{
  "query": "tiện ích",
  "tenant_id": "noble",
  "project_codes": ["NCLB"],
  "top_k": 5
}
```

**Response**
```json
{
  "hits": [
    {
      "text": "Dự án có bể bơi vô cực tầng 5, phòng gym, khu BBQ ngoài trời...",
      "project_code": "NCLB",
      "project_name": "Noble Crystal Long Biên",
      "section": "Noble Crystal Long Biên › tiện ích",
      "score": 0.87,
      "doc_type": "tong_quan",
      "source_file_url": null,
      "updated_at": "2026-07-29T08:00:00Z",
      "chunk_index": 2
    }
  ],
  "latency_ms": 38
}
```

### 6.2 So sánh 2 dự án — agent phát **2 call song song** (PA1)

Khách: "So sánh tiện ích dự án A và B". LLM gọi tool 2 lần trong cùng lượt; agent
gửi 2 request độc lập:

```json
POST /v1/kb_search   { "query": "tiện ích", "tenant_id": "noble", "project_codes": ["A"], "top_k": 5 }
POST /v1/kb_search   { "query": "tiện ích", "tenant_id": "noble", "project_codes": ["B"], "top_k": 5 }
```

Mỗi response có `top_k` riêng → đảm bảo lấy đủ chunk của **cả hai** dự án (không bị
một dự án lấn hết top-k). Agent gộp 2 kết quả rồi format cho LLM.

### 6.3 Toàn bộ dự án (`kb_search("chính sách thanh toán", "")`)

**Request**
```json
{
  "query": "chính sách thanh toán",
  "tenant_id": "noble",
  "project_codes": [],
  "top_k": 5
}
```
`project_codes: []` → service tìm trên **mọi dự án** của tenant + tài liệu `"__ALL__"`.
Hữu ích cho câu hỏi chung không gắn dự án cụ thể.

---

## 7. Ánh xạ phía agent (tham chiếu — KHÔNG thuộc trách nhiệm RAG-team)

Tool schema giữ **phẳng** cho LLM yếu (gemini-flash) — quyết định PA1:

```
kb_search(query: str, project_filter: str = "")
```

- `project_filter` → `project_codes`: `""` → `[]`, `"NCLB"` → `["NCLB"]`.
- So sánh nhiều dự án = **nhiều tool call song song**, mỗi call 1 mã (không dùng
  nested `[[query, code]]` — nested array dễ khiến LLM yếu điền sai).
- Agent tự chèn `tenant_id` từ `current_tenant()`, không phải tham số LLM.
- Agent nhận `hits` → format thành block ngữ cảnh (một hit / block, kèm
  `project_name` + `section` + freshness) → nhét vào prompt.

---

## 8. Điểm còn mở (chốt khi tích hợp)

1. **Cổng/host cụ thể** của service + có versioning path `/v1/` hay không (contract
   này giả định có).
2. **Định dạng `updated_at`**: ISO-8601 UTC (`Z`) — chốt nếu team muốn epoch/khác.
3. **Rate-limit / batch endpoint** (`POST /v1/kb_search:batch` nhiều query 1 lần) —
   chưa cần cho PA1 (multi-call song song đủ dùng); mở nếu sau này tối ưu round-trip.
4. **`min_score` scale**: RRF score không chuẩn hóa [0,1] cố định giữa các truy vấn —
   nếu dùng `min_score` cần thống nhất thang điểm hoặc để service tự lọc.
