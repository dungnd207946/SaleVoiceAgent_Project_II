# `send_media` Media Search Service — API Contract (updated: tenant isolation)

> **Mục đích:** Quy chuẩn input/output cho **service tìm media hybrid visual** (E5-large
> text + SigLIP2 visual, Qdrant RRF) mà tool `send_media` của agent gọi để lấy ảnh/video
> gửi cho khách. Agent là **client**; service do **team backend media** phát triển/vận hành.
>
> **THAY ĐỔI LẦN NÀY (2026-08-03):** request thêm trường **`tenant_id`** (BẮT BUỘC) để
> service **cách ly kết quả theo tenant** — hiện API chưa cách ly, đây là điểm cần team
> backend sửa. Mọi phần khác của contract giữ nguyên (backward-compatible với client:
> client đã bắt đầu gửi `tenant_id`; response không đổi).
>
> Tham chiếu: `docs/BA-docs/visual_search.md` (thiết kế hybrid visual-search hiện tại).
> Ngữ cảnh cách ly tenant: `docs/BA-docs/db-design/db-design/02-knowledge-base.md` §5
> (Qdrant `<slug>_media` collection riêng mỗi workspace).

---

## 1. Tổng quan

- **Client:** agent, tool `send_media` → `data/media_data.py::search_media` (HTTP client).
- **Service:** team backend media. Nhận `{tenant_id, query, project_code, category, …}` →
  tìm hybrid trên media của **đúng tenant** → trả `hits`. Agent map `hits` → ảnh/video hiển thị.
- **Ranh giới:** service tự sở hữu cơ chế embed/lưu/tìm; agent chỉ gửi tham số + đọc `hits`.

```
LLM tool send_media(query, project_code, category)
   │  agent thêm tenant_id = current_tenant()
   ▼
POST {media_search_url}  ──►  Media service  ──►  Qdrant (media của tenant, RRF text+visual)
   ◄── { hits: [ {media_url, caption, thumb_url, content_type} ] }
   │  agent map → ≤6 ảnh + ≤1 video YouTube → gửi client
```

---

## 2. Transport & Auth

| Mục | Giá trị |
|---|---|
| Protocol | HTTP REST |
| Endpoint | `POST {media_search_url}` (agent config `MEDIA_SEARCH_URL`, hiện `…:8015/search`) |
| Content-Type | `application/json` (request & response) |
| Auth | `Authorization: Bearer <token>` — agent lấy token từ env `SANTA_MODELS_TOKEN`; rỗng → không gửi header |
| Tính chất | stateless · read-only |

---

## 3. Request

### 3.1 Body schema

| Field | Kiểu | Bắt buộc | Ý nghĩa | Δ |
|---|---|:--:|---|:--:|
| `tenant_id` | string | ✅ | Định danh workspace (vd `"noble"`). **Service PHẢI dùng để cách ly** — chỉ tìm trong media của tenant này. | 🆕 |
| `query` | string | ✅ | Câu mô tả ảnh cần tìm (agent tự sinh từ category nếu khách không nêu). | |
| `project_code` | string | ✅ | Mã dự án cần lấy media. | |
| `category` | string | ✅ | Loại media: `tong_quan·ngoai_that·noi_that·tien_ich·mat_bang·vi_tri·tien_do`. | |
| `top_k` | int | ❌ | Số hit tối đa (agent gửi mặc định 10). | |
| `threshold` | float | ❌ | Ngưỡng điểm tối thiểu (agent gửi mặc định 0.4). | |

Ví dụ body:
```json
{
  "tenant_id": "noble",
  "query": "phối cảnh hồ bơi",
  "project_code": "NPLB",
  "category": "tien_ich",
  "top_k": 10,
  "threshold": 0.4
}
```

### 3.2 Cách ly theo `tenant_id` — YÊU CẦU CHÍNH cần team backend sửa

Service **PHẢI** giới hạn kết quả trong media của đúng `tenant_id`. Cách hiện thực tùy team
(khuyến nghị theo thiết kế): **collection Qdrant riêng mỗi workspace** `<slug>_media`
(service map `tenant_id` → `<slug>`), hoặc một **payload filter `tenant_id`** cứng trên
collection dùng chung. Ràng buộc bắt buộc:
- Tenant A **không bao giờ** nhận được media của tenant B.
- **Fail-closed:** `tenant_id` thiếu / rỗng / không tồn tại → trả `200` với `"hits": []`
  (KHÔNG trả media của tenant khác, KHÔNG lỗi 500).
- `project_code` được diễn giải **trong phạm vi tenant** (cùng mã ở 2 tenant là 2 dự án khác nhau).

---

## 4. Response — `200 OK`

### 4.1 Envelope
```jsonc
{ "hits": [ /* HitObject[], đã xếp theo điểm giảm dần */ ] }
```

### 4.2 `HitObject` (giữ nguyên — agent đang đọc các field này)

| Field | Kiểu | Bắt buộc | Ý nghĩa |
|---|---|:--:|---|
| `media_url` | string | ✅ | URL file media: link ảnh S3/MinIO **hoặc** URL YouTube. Agent hiển thị trực tiếp. |
| `content_type` | string | ❌ | `image` \| `video`. Agent cũng tự suy từ đuôi file/host YouTube nếu vắng. |
| `caption` | string | ❌ | Mô tả (agent dùng làm label ảnh / title video). |
| `thumb_url` | string | ❌ | URL thumbnail (WebP) — agent dùng cho ảnh khi có. |
| `id` | string | ❌ | ID nội bộ (agent chỉ log, không hiển thị). |

> Agent map hits → **≤6 ảnh** (content_type=`image` hoặc URL có đuôi ảnh) **+ ≤1 video YouTube**
> (URL host YouTube). Các loại khác (mp4/PDF/file client không render được) bị bỏ qua.

### 4.3 Ngữ nghĩa & lỗi

- **Không có kết quả** = `200` với `"hits": []`. Agent trả payload `no_media` nhã nhặn cho khách.
- **Thứ tự `hits`** = thứ hạng (agent lấy theo thứ tự, cắt ≤6 ảnh + ≤1 video).
- **Lỗi non-2xx / timeout** → agent bắt, trả `no_media`, **không vỡ lượt**. Timeout phía agent ~10s.
- Agent **không** gửi `"__ALL__"` cho media (media luôn gắn dự án cụ thể; khác `kb_search`).

---

## 5. Ví dụ

**Request**
```json
POST {media_search_url}
Authorization: Bearer <token>
{ "tenant_id": "noble", "query": "phối cảnh hồ bơi", "project_code": "NPLB",
  "category": "tien_ich", "top_k": 10, "threshold": 0.4 }
```

**Response**
```json
{
  "hits": [
    { "media_url": "https://minio/noble/NPLB/pool.webp", "content_type": "image",
      "caption": "Bể bơi vô cực", "thumb_url": "https://minio/noble/NPLB/pool.thumb.webp" },
    { "media_url": "https://youtu.be/dQw4w9WgXcQ", "content_type": "video", "caption": "Video tổng quan" }
  ]
}
```
Agent → gửi 1 ảnh (bể bơi) + 1 video YouTube cho khách.

---

## 6. Tóm tắt thay đổi cho team backend

1. **Đọc thêm `tenant_id`** trong request body (bắt buộc).
2. **Cách ly kết quả theo `tenant_id`** — chỉ trả media của tenant đó (collection/filter theo workspace).
3. **Fail-closed** khi `tenant_id` thiếu/không hợp lệ → `hits: []`.
4. Response shape **không đổi** — không cần sửa gì phía output.

Phía agent đã cập nhật (commit `6e8a8d5`): `search_media` thêm tham số bắt buộc `tenant_id`
(keyword-only), `send_media` truyền `tenant_id=current_tenant()`, request body thêm `tenant_id`
ở đầu. Backward-compatible: tới khi service hỗ trợ, request vẫn hoạt động (service chỉ bỏ qua
field mới) nhưng **chưa cách ly** — nên cần team backend sửa để đóng lỗ hổng.
