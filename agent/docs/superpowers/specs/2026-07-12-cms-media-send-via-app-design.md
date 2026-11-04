# send_via_app gửi ảnh/video thật từ CMS (hướng A: đọc Mongo trực tiếp)

**Ngày:** 2026-07-12
**Branch:** `fix/agent-improvements`
**Trạng thái:** Design (chờ review → implementation plan)

## 1. Bối cảnh & vấn đề

Tool `send_via_app` (agent/tools/support_ops.py) hiện là **stub**: nó chỉ log + trả một
JSON ack chữ (`"Em đã gửi thông tin cho anh/chị ạ."`), **không** có `items[]`, **không**
gọi CMS. Vì thế khi Luna nói "em gửi hình dự án qua app cho mình xem nha" thì thực tế
không có ảnh nào được gửi.

Trong khi đó cả hai đầu còn lại đã sẵn sàng:

- **Kho ảnh/video** nằm ở service `santa-agent-cms` (`../santa-agent-cms`, port 8767):
  collection Mongo `project_media` (metadata; bytes ở S3/MinIO), có REST + endpoint
  download/thumbnail **public** (không cần token), thiết kế sẵn cho thẻ `<img>`.
- **Chặng cuối phía client + transport đã có sẵn:**
  - `static/chat.html` + `static/livekit.html` render `items[]` (carousel ảnh + lightbox
    + video card YouTube) khi một `tool_done.result` có mảng `items[]`.
  - Chat WS (`server/text_chat.py`) forward `tool_done` nguyên văn; voice LiveKit
    (`transport/livekit/room_session.py`) `publish_data` tool events qua data channel.
    → Cả hai kênh tới NobleX app đều ăn `items[]` **miễn phí**, không cần sửa transport.

**Mắt xích thiếu duy nhất:** `send_via_app` chưa lấy media thật từ CMS và chưa trả về
`items[]`.

## 2. Mục tiêu / Ngoài phạm vi

**Mục tiêu:** `send_via_app` trả về `items[]` (ảnh + video YouTube) thật, lấy từ
`project_media`, để chat + voice hiển thị được ảnh/video kèm câu trả lời của Luna khi
stream sang NobleX app. Nhanh (không tải byte qua hotline) và đúng cho ảnh + YouTube.

**Ngoài phạm vi (v1):**

- Không presign S3 ở phía hotline (dùng URL redirect public của CMS).
- Không render mp4 (file video S3) / PDF (brochure) / link Google Drive — **client hiện
  chưa có player/card cho các loại này** → bỏ qua + log. Tương lai: thẻ `<video>` +
  card link tài liệu.
- Không gọi REST CMS (đọc Mongo trực tiếp — hướng A, nhất quán với cách hotline đã đọc
  `project_du_an`/`project_can_ho`).
- Không đụng transport (chat + voice đã forward `tool_done`/`publish_data` sẵn).

## 3. Cơ chế URL (làm rõ: KHÔNG tải byte để tạo link)

"Link noble.vn" chỉ là một URL cố định ghép `media_id` — **không server nào tải ảnh về
để tạo link**:

1. **Hotline** chỉ đọc metadata Mongo rồi ghép chuỗi
   `f"{CMS_BASE}/api/v1/projects/media/{id}/download?inline=true"`. Không đụng byte,
   không presign. Vì thế lượt agent nhanh.
2. Khi **app render `<img src=url>`** mới có request thật: app → CMS
   `GET /media/{id}/download` → CMS `find_one` (1 query) + `presigned_get` (ký URL S3 tại
   chỗ bằng HMAC, **không** network) → trả `302` tới URL S3 đã ký (hết hạn 1h) → app tải
   byte **thẳng từ S3/MinIO**. CMS không proxy byte.
3. Dùng URL redirect của CMS (không phải link S3 trực tiếp) vì nó **ổn định, không hết
   hạn** (chỉ chứa `id`); mỗi lần tải CMS ký lại presigned mới. Link S3 trực tiếp sẽ chết
   sau 1h.
4. **YouTube** không dính CMS: hotline tách `video_id` từ `external_url` → app tự dựng
   `youtube.com/embed/{video_id}` + thumbnail `img.youtube.com`.

## 4. Luồng dữ liệu

```
agent → send_via_app(query, project_code[], category?)
  → support_ops.send_via_app(customer, args, session_id)
  → data/media_data.list_project_media(code, category, query, limit)
       • db = get_db()
       • doc = structured_data._fetch_project_doc(db, code)   (reuse; alias-aware ma_du_an regex)
       • du_an_id     = str(doc["_id"])
       • project_name = doc.get("ten_thuong_mai") or code
       • docs = db.project_media.find({"du_an_id": du_an_id}).sort("ngay_tao", -1).limit(200)
       • CHỌN LỌC hybrid (§6) → MAP loai_media→kind (§7) → items[]
  → payload {project_name, caption, items[], count, message}  (§8)
  → tool_done → chat forward / livekit publish_data → app render items[]
```

Chi phí trong lượt agent: **1 read Mongo có index** (`project_media.du_an_id` đã có
`create_index`) + build chuỗi. Không tải byte, không presign, không HTTP sang CMS.

## 5. Thay đổi schema tool (agent/tools/schemas.py)

Thêm **1 param tùy chọn** `category`:

```
send_via_app(
  query:        str        # bắt buộc — câu hỏi/yêu cầu nguyên văn của khách
  project_code: string[]   # mã dự án (enum theo DB, như hiện tại)
  category?:    str        # CHỮ TỰ DO (không enum) — hint loại media
)
```

- `category` là **chữ tự do**, KHÔNG enum: `danh_muc` trong CMS là **đường dẫn thư mục
  tự do** (`"Mặt bằng"`, `"Phối cảnh"`, `"Phối cảnh/Brochure"`, `"Pháp lý"`…), người dùng
  CMS tự tạo cây và khác nhau theo dự án — không thể đóng enum.
- Description cập nhật: agent truyền `category` khi khách hỏi loại cụ thể ("mặt bằng",
  "phối cảnh", "brochure", "video"); để rỗng nếu chung chung.
- `send_via_app` vẫn nằm trong `_ENUM_TOOLS` (enum `project_code` theo mã DB) — không đổi.

## 6. Chọn lọc media (hybrid, trong media_data)

Trên tập docs đã fetch (mới nhất trước):

1. **Category** (nếu `category` không rỗng): giữ doc mà `danh_muc` **chứa** token
   category, so khớp **không dấu + lowercase** (`_norm()`). → "mặt bằng" khớp cả
   `"Mặt bằng"`; "phối cảnh" khớp `"Phối cảnh/Brochure"`.
2. **Query keyword** (nếu không có category, HOẶC category ra 0 kết quả) & `query` không
   rỗng: chấm điểm mỗi doc = số token `_norm(query)` xuất hiện trong
   `_norm(ten_file + " " + mo_ta + " " + danh_muc)`; giữ doc điểm > 0, sort theo điểm.
3. **Fallback top-N**: nếu vẫn rỗng → lấy đại diện mới nhất (không lọc).
4. Luôn: chia kết quả thành **ảnh** (cap `MAX_IMAGES = 6`) + tối đa **1 video YouTube**
   (video đầu tiên khớp).

`_norm(s)`: NFD + bỏ dấu combining + lowercase + strip.

## 7. Map `loai_media` → `kind` client

| Nguồn CMS (`loai_media` + dữ liệu) | → item |
|---|---|
| `anh` (file S3) | `{"kind":"image","url":"{CMS_BASE}/api/v1/projects/media/{id}/download?inline=true","label": ten_file or mo_ta}` |
| `link` + `external_url` là YouTube | `{"kind":"video","video_id": <parse>, "title": ten_file}` |
| `link` + `external_url` là URL ảnh (đuôi `.jpg/.jpeg/.png/.webp/.gif`) | `{"kind":"image","url": external_url, "label": ten_file}` |
| `video` (mp4 S3) / `link` Google Drive / `file` (PDF/brochure) | **bỏ qua + log** (client chưa render được) |

- `video_id` parse (regex, các dạng chuẩn): `youtube.com/watch?v=<id>`, `youtu.be/<id>`,
  `youtube.com/embed/<id>`, `youtube.com/shorts/<id>`. Trượt → bỏ item + log.
- `CMS_BASE` = `settings.cms_media_base_url` (§9).

## 8. Payload trả về

```json
{
  "ok": true,
  "project_name": "Alluvia Sunshine Marina",
  "caption": "Hình ảnh dự án Alluvia Sunshine Marina",
  "items": [
    {"kind": "image", "url": "https://agent-cms.noble.vn/api/v1/projects/media/<id>/download?inline=true", "label": "Mặt bằng tầng 5"},
    {"kind": "video", "video_id": "abc123", "title": "Phối cảnh dự án"}
  ],
  "count": 2,
  "message": "Dạ em gửi hình dự án qua app cho anh/chị rồi ạ."
}
```

Superset hợp lệ của tool result: client render `items[]`; agent đọc `message`. Bỏ các
field placeholder cũ (`channel`/`phone`/`status:queued`) — vô nghĩa với mô hình mới.

`caption` = `f"Hình ảnh dự án {project_name}"` (mặc định). `message` là câu Luna đọc/nói,
số lượng theo `count`.

## 9. Suy biến (không crash, không escalate)

- Không resolve được dự án / 0 media / tất cả bị bỏ qua →
  `{"ok": false, "items": [], "count": 0, "note": "no_media", "message": "Dạ hình dự án này em chưa có sẵn, em mô tả giúp anh/chị nhé ạ"}`
  → agent mô tả bằng lời (KHÔNG escalate).
- Lỗi Mongo → như trên + `logger.warning`. Không bao giờ ném exception ra khỏi tool.
- `CMS_BASE` chưa cấu hình → không dựng được URL ảnh → ảnh coi như no_media (log);
  **nhưng YouTube vẫn chạy** (video_id độc lập với CMS_BASE).

## 10. Config

Env mới trong `config.py` (UnifiedSettings) + `.env.example`:

| Env | Default | Vai trò |
|---|---|---|
| `CMS_MEDIA_BASE_URL` | `https://agent-cms.noble.vn` | Base URL public của CMS để dựng URL ảnh redirect. Chỉ dùng cho item `kind=image` nguồn S3. |

## 11. File đụng tới

- **MỚI** `src/noble_agent/data/media_data.py` — `list_project_media(code, category, query, limit)`
  (đọc Mongo + chọn lọc §6) + helpers `_norm`, `_parse_youtube_id`, `_is_image_url`.
  Reuse `structured_data._fetch_project_doc` cho resolve code→(du_an_id, name).
- `src/noble_agent/agent/tools/support_ops.py` — `send_via_app` nối vào media_data, map →
  items[] (§7), payload (§8), suy biến (§9). Giữ signature
  `(customer, args, session_id)`. Bỏ placeholder sms/channel.
- `src/noble_agent/agent/tools/schemas.py` — thêm param `category` + refresh description.
- `src/noble_agent/config.py` — `cms_media_base_url`.
- `.env.example` — document `CMS_MEDIA_BASE_URL`.
- `src/noble_agent/agent/definitions/RULES.md` — tool-catalog `send_via_app`: khi nào
  truyền `category`; ảnh/video được gửi qua app hiển thị ngay.

## 12. Kiểm thử

`tests/unit/unified/test_send_via_app_media.py` — fake in-memory Mongo db (theo mẫu
`tests/unit/unified/test_project_financial_mongo.py`), async:

1. Resolve code → du_an_id + project_name (alias-aware).
2. Category filter không dấu: `category="mặt bằng"` khớp doc `danh_muc="Mặt bằng"` và
   `"Phối cảnh/Brochure"` KHÔNG lọt.
3. Query keyword fallback khi category rỗng.
4. Top-N fallback khi cả hai rỗng; cap `MAX_IMAGES`.
5. Mapping: `anh` → image url đúng mẫu CMS_BASE; YouTube link → `video_id`; bỏ qua mp4 /
   Drive / PDF.
6. `_parse_youtube_id` các dạng URL (watch/youtu.be/embed/shorts) + URL rác → None.
7. Suy biến: no_media (0 doc), Mongo lỗi → `ok:false, note:"no_media"`, không raise.
8. `CMS_BASE` rỗng → ảnh bị loại nhưng YouTube vẫn ra item.

Chạy: `pytest tests/unit/unified/test_send_via_app_media.py -v`. Sau đó `make test-unit`
+ `make lint`. Smoke (SMOKE.md) vì có đụng tool loop + prompt.

## 13. Rủi ro / phụ thuộc

- **Chất lượng data CMS:** độ "đúng cái nào" phụ thuộc `du_an_id` khớp, `loai_media` đúng
  loại, và `danh_muc` được gắn. Media chưa gắn category → agent chỉ gửi được top-N chung.
- **Reachability:** URL ảnh trỏ `agent-cms.noble.vn` (HTTPS công khai) — NobleX app mobile
  phải ra được host này. IP nội bộ `10.50.12.70` sẽ không dùng cho mobile.
- **Reuse `_fetch_project_doc`:** đang là hàm "private" của `structured_data`. Cân nhắc
  thêm một wrapper public nhỏ (`resolve_project_ref(code) -> (du_an_id, name) | None`) để
  không gọi xuyên `_private`. (Quyết định lúc implement — surgical.)
- **Video non-YouTube / PDF:** bỏ qua trong v1 (giới hạn client). Nếu kho có nhiều loại
  này, cần mở rộng client (`<video>` + card link) ở phase sau.

## 14. Ảnh render nhanh — web-thumbnail (bổ sung sau duyệt, 2026-07-12)

**Vấn đề:** CMS phục vụ ảnh **gốc full-res** (jpg/png/webp/gif/heic/RAW), không transcode/
resize, không CDN. `needs_thumbnail` chỉ True cho **PDF + RAW** → ảnh web thường KHÔNG có
thumbnail (`/thumbnail` 404). Grid 6 ô ảnh gốc trên mobile → chậm. Đòn bẩy tốc độ nằm ở
CMS/CDN, không phải hotline.

**Quyết định:** CMS sinh **web-thumbnail cho MỌI ảnh** (luồng riêng, repo santa-agent-cms);
hotline chuẩn bị sẵn để dùng.

### 14a. Luồng hotline (repo này — làm ngay, forward-compatible)
- Item `kind=image` mang thêm field tùy chọn **`thumb`** =
  `f"{cms_base}/api/v1/projects/media/{id}/thumbnail"` — **CHỈ khi** media doc có
  `thumbnail_key` (không rỗng). Chưa có → không phát `thumb`.
- `url` (bản `/download` full) giữ nguyên cho lightbox/xem to.
- Rủi ro zero: hôm nay ảnh chưa có `thumbnail_key` → `thumb` vắng → client dùng `url` (hành
  vi hiện tại). Sau khi CMS backfill → `thumb` tự xuất hiện, không cần sửa/redeploy hotline.
- Client tester (`static/chat.html`/`livekit.html`, repo này): grid tile dùng `thumb` nếu
  có (else `url`); lightbox luôn dùng `url`. Contract item ảnh: `{kind, url, thumb?, label}`
  — ghi lại cho đội NobleX app.
- Test bổ sung: media có `thumbnail_key` → item có `thumb` đúng mẫu; media không có → không
  có `thumb`.

### 14b. Luồng CMS (repo santa-agent-cms — effort riêng, KHÔNG thuộc run này)
- `needs_thumbnail` mở cho mọi `image/*`; thêm bộ resize web (JPEG/WebP ~800px q80) song
  song `_raw_to_jpeg`/`_pdf_to_jpeg`.
- Backfill: script sinh thumbnail cho ảnh `project_media` đang có `thumbnail_key=None`.
- Tuân theo branch/CLAUDE/harness của repo CMS. Sau khi deploy, hotline (14a) tự hưởng.
