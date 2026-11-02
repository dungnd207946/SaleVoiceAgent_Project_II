# `send_media`: thêm `content_type`, `category` thành optional

**Ngày:** 2026-08-06
**Trạng thái:** đã chốt design, chờ implementation plan
**Nhánh:** `develop` (sẽ tách nhánh feature trước khi sửa)

## 1. Vấn đề

Khách xin video dự án ("cho xem video dự án MEL", "có clip nào không") thì `send_media`
hầu như không bao giờ trả về video, dù dữ liệu có video.

Hai nguyên nhân, cả hai đo được trên Qdrant thật (`127.0.0.1:16433` qua SSM tunnel):

**(a) Không có cách nào diễn đạt "tôi muốn video".** Tool chỉ nhận `query` /
`category` / `project_code`; `content_type` chỉ tồn tại như payload field trong
Qdrant và được `_hit_to_item` đọc để *render*, chưa bao giờ là filter. Video vì thế
chỉ lọt kết quả một cách tình cờ: phải vừa trùng `category` vừa thắng 85 ảnh trong
top_k=10 sau RRF.

**(b) `category` đang BẮT BUỘC và là hard filter AND.** LLM buộc phải điền nên nó
điền `tong_quan` theo hướng dẫn mặc định trong RULES.md, và thế là chặn sạch video.

Dữ liệu video thật, 4 collection:

| Collection | image | video | video nằm ở category |
|---|---|---|---|
| `an-phu-land_q8w2_retail_media` | 85 | 2 | `tien_do` (chỉ mình nó) |
| `noble-homes_k3n7_retail_media` | 33 | 4 | `ngoai_that`, `mat_bang`, `noi_that`, `tien_ich` |
| `noble-homes_k3n7_wholesale_media` | 30 | 1 | `tong_quan` |
| `an-phu-land_z5r1_retail_media` | 77 | 1 | `tong_quan` |

`content_type` **trực giao** với `category`: video rải rác, mỗi tenant một kiểu.
Ví dụ cụ thể của failure: MEL *có* video, nhưng nó nằm ở `tien_do`; khách xin
"video dự án MEL" → LLM truyền `category=tong_quan` → `0 hit` → khách nhận
"Dạ hình dự án này em chưa có sẵn".

**(c) Cap `≤1 video`.** `_map_items` giới hạn 1 video/lượt và luôn xếp ảnh trước.
VRI có 3 video nhưng khách chỉ nhận được 1.

## 2. Vì sao `category` từng bắt buộc (ràng buộc phải giữ)

Không có tài liệu — nó vào repo qua commit import `03ed43e "upcode"`. Nhưng
[RULES.md](../../../src/noble_agent/persona/RULES.md) rule 12 cho thấy ý định:
`send_media` được gọi ở **hai chế độ**, và ở chế độ CHỦ ĐỘNG (Luna tự gửi ảnh khi
giới thiệu dự án) `category=tong_quan` đang làm việc **curation**, không chỉ lọc
chủ đề.

Bằng chứng từ tên file thật: `tong_quan` = `__cover`/`__overview`/`__intro`/`__default`;
`mat_bang` = `__map`; `vi_tri` = `__location`. Và kích thước theo category
(`an-phu-land_q8w2_retail`, đo qua CloudFront):

| category | n | median | max |
|---|---|---|---|
| `mat_bang` | 14 | **4.12 MB** | **32.51 MB** |
| `tong_quan` | 56 | 0.43 MB | 23.56 MB |
| `vi_tri` | 14 | 0.38 MB | 0.96 MB |

Bỏ category ở nhánh chủ động → Luna giới thiệu dự án bằng bản vẽ mặt bằng, và nặng
gấp ~10 lần. **Đây là hồi quy phải chống**, không phải suy đoán.

## 3. Quyết định

`category` và `content_type` **đều optional** ở schema, nhưng **không được rỗng cả
hai** — rỗng cả hai thì tool trả `retry` dạy LLM điền ít nhất một chiều.

Lý do chọn hướng này thay vì soft-boost (2 prefetch branch với filter riêng, RRF tự
cộng điểm cho item khớp cả hai — đã verify chạy được trên Qdrant thật): gốc của việc
hard-AND giết recall **chính là category đang bắt buộc**. Cho optional thì LLM không
điền bừa nữa, gốc mất, và hard filter là đủ. Soft boost giữ lại làm phương án dự
phòng nếu đo thấy 0-hit thật (mục 8).

Cơ chế chống LLM bỏ trống cả hai: hướng dẫn đặt **trong `description` của chính
param**, không chỉ trong RULES.md. Đây là bài học đã ghi trong CLAUDE.md
(2026-07-11): rule trong RULES.md một mình không đủ với gemini-2.5-flash, phải nhét
signal vào đúng chỗ model đang điền arg.

## 4. Hợp đồng tool

```
send_media(query, project_code?, category?, content_type?)
required: ["query"]
```

| Param | Giá trị | Bỏ trống nghĩa là |
|---|---|---|
| `query` | free text | — (bắt buộc, không đổi) |
| `project_code` | mã canonical | dùng `customer.project_interest` (không đổi) |
| `category` | 8 enum như hiện tại | không lọc theo loại |
| `content_type` | `image` \| `video` | cả hai loại — hành vi hôm nay |

Cột "bỏ trống nghĩa là" mô tả **ngữ nghĩa filter** của từng param xét riêng. Ràng
buộc "không rỗng cả hai" là một tầng khác, nằm ở validation của tool (§5), không ở
schema — nên với LLM thì cả hai param đều thực sự optional.

`SEND_MEDIA_CONTENT_TYPES = ("image", "video")` đặt cạnh `SEND_MEDIA_CATEGORIES`
trong `schemas.py`, làm single source of truth cho enum schema và cho validation ở
`support_ops` (đúng pattern `SEND_MEDIA_CATEGORIES` đang dùng).

Nội dung `description` cần sửa:

- `category`: gỡ "BẮT BUỘC"; thêm *"chủ động giới thiệu tổng quan → `tong_quan`;
  khách xin video chung mà không nói rõ loại → bỏ trống"*
- `content_type` (mới): *"`video` khi khách xin video/clip/quay dự án; `image` khi
  khách xin ảnh/hình; bỏ trống = cả hai"*

## 5. Validation (`support_ops.send_media`)

| Điều kiện | Kết quả |
|---|---|
| `category` rỗng **VÀ** `content_type` rỗng | `retry` **`missing_filter`** (mới) |
| `category` ngoài enum | `invalid_category` (giữ) |
| `content_type` ngoài enum | `invalid_content_type` (mới) |
| không có code và không có `project_interest` | `missing_project_code` (giữ) |

Bỏ retry `missing_category`. Tất cả dùng `_retry_payload` sẵn có — LLM đã được
RULES.md dạy gọi lại theo `message`.

`search_query` fallback hiện là `query or f"hình ảnh {category} dự án"`. Category giờ
có thể rỗng nên phải đổi. Danh từ lấy theo `content_type`: `"video"` khi
`content_type == "video"`, còn lại `"hình ảnh"`. Chuỗi kết quả chính xác:

| `content_type` | `category` | `search_query` khi `query` rỗng |
|---|---|---|
| `video` | `tien_do` | `"video tien_do dự án"` |
| `video` | rỗng | `"video dự án"` |
| rỗng / `image` | `tong_quan` | `"hình ảnh tong_quan dự án"` |
| rỗng / `image` | rỗng | *(không xảy ra — §5 đã chặn rỗng cả hai)* |

Ghép bằng cách nối các phần non-rỗng rồi join một khoảng trắng, để không sinh ra
`"hình ảnh  dự án"` hai khoảng trắng.

## 6. Filter và search

**`qdrant_search.build_scope_filter`** thêm kwarg `content_type: str | None = None`
→ thêm một `FieldCondition(key="content_type", match=MatchValue(value=...))` vào
`must` khi có giá trị. Hard filter. **Không sửa `search_hybrid`** (mọi branch vẫn
dùng cùng một filter). `kb_search` không truyền kwarg mới → không ảnh hưởng.

**`media_data.search_media`** thêm param `content_type: str = ""`, chuyển xuống
`build_scope_filter`, và **đưa vào cache key**. Thiếu chỗ cache key là bug thật:
"xin ảnh" và "xin video" cùng project + cùng query sẽ dùng lẫn kết quả của nhau
trong 300s.

## 7. Cap kết quả

`_map_items(hits, *, max_videos: int = 1)`. `search_media` truyền
`max_videos=MAX_VIDEOS_WHEN_REQUESTED (=3)` khi `content_type == "video"`, còn lại
giữ `1`.

Không cần logic sắp xếp mới: ảnh vẫn xếp trước video như hiện tại, và khi filter là
`video` thì danh sách ảnh rỗng nên video tự lên đầu. Nhánh chủ động (`tong_quan`,
không có `content_type`) giữ nguyên `≤6 ảnh + ≤1 video`.

## 8. Non-goals (cố ý không làm ở slice này)

- **`.mp4`**: giữ drop + log. Client không có player — [chat.html:599-600](../../../static/chat.html)
  chỉ dựng iframe YouTube từ `video_id`, nhánh else là chữ "Video chưa khả dụng", và
  thumbnail lấy từ `img.youtube.com/vi/{video_id}`. Bản mp4 duy nhất trong dữ liệu
  nằm trên `cdn.noblex-demo.local` (không resolve → seed demo). Support nó = sửa
  server + client + nguồn thumbnail để phục vụ 1 record giả.
- **2-branch RRF soft boost cho `category`**: đã verify khả thi (per-branch filter +
  RRF cộng điểm cho item khớp cả hai, đo được trên `noble-homes_k3n7_retail_media`:
  video `noi_that` lên #1 score 0.75, 3 video khác vẫn còn trong kết quả thay vì
  0 hit). Để dành; chỉ làm nếu sau khi ship thấy 0-hit thật với category optional.
- **`thumb_url` trỏ IP private `10.50.13.220:9000`** và **thiếu rendition `medium`**
  (client đã có `im.medium || im.url` nhưng pipeline mới không emit `medium` → luôn
  rơi về ảnh gốc, có file 32 MB). Là vấn đề ingest/hạ tầng riêng, không trộn vào đây.

## 9. Phạm vi file

| File | Sửa gì |
|---|---|
| `src/noble_agent/agent/tools/schemas.py` | `SEND_MEDIA_CONTENT_TYPES`; param `content_type`; `required` còn `["query"]`; description `category` |
| `src/noble_agent/agent/tools/support_ops.py` | validation 4 nhánh; `search_query` fallback; truyền `content_type` xuống |
| `src/noble_agent/data/qdrant_search.py` | `build_scope_filter(..., content_type=None)` |
| `src/noble_agent/data/media_data.py` | param `content_type`; cache key; `_map_items(max_videos)`; `MAX_VIDEOS_WHEN_REQUESTED` |
| `src/noble_agent/persona/RULES.md` | rule 12 (~dòng 120) + bảng tool catalog (~dòng 183) — đường **db-mode** |
| `src/noble_agent/tenants/noble/persona/RULES.md` | rule 12 (~dòng 107) + bảng tool catalog (~dòng 150) — đường **legacy** |
| `tests/unit/unified/test_send_media.py` | test mới + sửa test neo `missing_category` |
| `scripts/test_search_tools.py` | `run_media` cases mang thêm `content_type`; nhánh interactive cho nhập được — đây là công cụ live-verify của chính hai tool này (`make test-search`) |

`tenants/demo_acme` không enable `send_media` → không đụng.

Cả hai file persona đều sửa để không lệch: `.env` local không set
`AGENT_CONFIG_SOURCE` → default `legacy` (file sống khi smoke local là
`tenants/noble/`), còn các tenant đã ingest trên Qdrant là db-mode (`persona/`).

## 10. Test

Bổ sung vào `tests/unit/unified/test_send_media.py`:

- schema: `required == ["query"]`; `content_type` enum đúng 2 giá trị; `category`
  description không còn chữ "BẮT BUỘC"
- validation: rỗng cả hai → `missing_filter`; `content_type` sai → `invalid_content_type`;
  chỉ `content_type=video` (không category) → chạy search bình thường; chỉ `category`
  → chạy như cũ
- filter: `content_type` xuất hiện trong filter gửi Qdrant; `kb_search` gọi
  `build_scope_filter` không kwarg mới → filter không đổi
- cache: key đổi theo `content_type` (hai lời gọi khác `content_type` không dùng lẫn
  kết quả)
- `_map_items`: tôn trọng `max_videos`; `content_type=video` → tối đa 3 video
- `support_ops` → `search_media`: `content_type` được truyền xuống nguyên vẹn

Sửa test đang neo hành vi cũ: `test_send_media_missing_category_returns_retry`.

## 11. Verify sau khi code xong

1. `make test-unit` — 0 failure mới so với baseline `git archive HEAD` cùng `.env`
2. `make lint` sạch trên mọi file đã sửa
3. Live qua SSM tunnel, tầng dữ liệu trước: `make test-search ARGS="-i"` — kiểm
   `content_type=video` có thực sự lọc đúng và trả video ở category khác `tong_quan`
   (cases đã biết: MEL/LEP `tien_do`, VRI 3 video ở 3 category). Script này bypass
   cache nên mỗi lần chạy đều đụng backend thật.
4. Live tầng agent: `python scripts/chat_repl.py -t <tenant db-mode>` với
   `NOBLE_RAG_BACKEND=kb_service`, thử 3 câu — "cho xem video dự án MEL" (kỳ vọng ra
   video `tien_do`, đây là ca hôm nay fail), "giới thiệu dự án X" (kỳ vọng vẫn ảnh
   `tong_quan`, không hồi quy), "cho xem mặt bằng X" (kỳ vọng không đổi)
5. `SMOKE.md` không bắt buộc — slice này không đụng turn loop / transport
