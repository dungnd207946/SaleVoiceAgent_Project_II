# VLM đoán danh mục ảnh + agent tìm hai lượt

**Ngày:** 2026-08-25 · **Trạng thái:** thiết kế, chờ duyệt
**Hai repo:** `odyssey-portal-backend` (§1–§3) · `odyssey-agent` (§4)

## 1. Vấn đề, đo được

Khách đẩy gần như mọi ảnh vào một danh mục. Đo trên prod `10.50.99.104`:

| Tenant | `tong_quan` | `mat_bang` | 5 danh mục còn lại |
|---|---|---|---|
`aina_prod` | **630 ảnh (96%)** + 19 tour | 29 | **0** |
`aina` | 24 | 8 | **0** |

`send_media(category=…)` là exact match AND vào filter Qdrant, nên
`ngoai_that`/`noi_that`/`tien_ich`/`vi_tri`/`tien_do` **luôn trả rỗng** — agent có ảnh
phòng ngủ, bể bơi, sảnh nhưng không tìm ra.

Thông tin phân loại thì **đã có sẵn trong caption**: mô tả do VLM sinh nói rõ "Phòng ngủ
hiện đại…", "Tòa nhà… tầng trệt có các cửa hàng". Nó chỉ bị một filter chặn trước khi tới
tầng vector.

## 2. Nhãn sinh ở đâu, nằm ở đâu

VLM trả nhãn trong **cùng một lời gọi** với caption, ở dòng cuối:

```
Phòng ngủ hiện đại với cửa kính lớn nhìn ra sông, sàn gỗ và đèn LED trần.
Danh mục: nội thất
```

Portal ghi **cả cụm** vào `media.caption_auto`. Không cột mới, không migration.

- **≤ 2 nhãn**, cho phép **0** — model không chắc thì im, không bịa.
- Parse hỏng ⇒ 0 nhãn, giữ nguyên caption thô. Một dòng sai format không được làm mất mô tả.
- Chỉ đoán khi `category = 'tong_quan'`. Khách đã gán `mat_bang` thì tin họ.

Ba lý do chọn `caption_auto` thay vì một cột riêng:

1. `content_hash = sha256(media_url ␟ caption)` (`clients/media.py:27`). Caption đổi ⇒ hash
   đổi ⇒ **re-index tự chạy**. Nhãn nằm ngoài caption thì delta thấy hash không đổi và nhãn
   không bao giờ lên Qdrant.
2. Nhãn chỉ ảnh hưởng **thứ hạng**, không ảnh hưởng filter — filter vẫn chạy trên cột
   `media.category` của khách. Đoán sai **không thể giấu mất ảnh**, khác hẳn phương án ghi
   đè `category`.
3. Cột hợp đồng `caption` không bị đụng, nên latest-wins của cổng nạp không xoá mất nhãn.

## 3. Nhãn vào vector, và strip khỏi mọi chỗ người đọc

`_text_and_hash` hiện dựng `f"{category} {caption}"` — nhét mã thô `tong_quan` vào chuỗi
embed. Model dense là `intfloat/multilingual-e5-large` và truy vấn của agent là tiếng Việt
có dấu, nên mã không dấu viết liền embed kém. Đổi sang nhãn tiếng Việt:

```
"tổng quan · Phòng ngủ hiện đại… Danh mục: nội thất"
```

Sổ `NHAN_DANH_MUC: dict[str, str]` (`tong_quan → "tổng quan"`, …) trong `kb/contracts.py`,
dùng chung cho prompt và text embed — một nguồn, không hai bản chép.

`split_caption(text) -> tuple[str, list[str]]` cũng ở `kb/contracts.py`, gọi ở **đúng hai
chỗ người đọc**:

| Chỗ | Vì sao |
|---|---|
`realestate/router.py:583` | `caption=r["caption"] or split_caption(r["caption_auto"])[0]` — portal UI chỉ thấy mô tả |
`MediaClient.index` payload | `payload["caption"]` là thứ agent gửi cho khách, phải sạch. `text` để embed giữ nguyên cả cụm |

⚠️ Strip **chỉ áp cho `caption_auto`**, không áp cho `caption`: khách gõ tay chữ
"Danh mục:" trong mô tả của họ thì không được cắt.

## 4. Agent tìm hai lượt (`odyssey-agent`)

`search_media` giữ chữ ký, đổi phần giữa: **embed một lần, search hai lần** — một lượt có
filter `category`, một lượt không; lượt lọc rỗng thì lấy kết quả lượt kia.

Bốn điều kiện để nó đúng:

1. **Vector dùng chung.** Phần đắt là hai lời gọi HTTP tới embed service, không phải Qdrant.
   Giá thật của lượt thứ hai là một round-trip Qdrant (~5–20ms trên prod).
2. **Chỉ chạy hai lượt khi `category` khác rỗng.** Không truyền category thì vốn đã không lọc.
3. **"Rỗng" xét trên `items`, không trên `points`.** `_map_items` loại hit client không render
   được; xét `points` thì ba hit vô dụng sẽ chặn fallback và khách vẫn không nhận được gì.
4. **Cache chỉ ôm kết quả CUỐI**, key giữ nguyên (đã gồm `category`).

Thêm một dòng `logger.info` khi fallback được dùng — đó là thước đo duy nhất cho biết nhãn
có đang dọn được vấn đề không, và khi nào fallback thôi cần thiết.

## 5. Rủi ro

| Rủi ro | Chặn |
|---|---|
Model nhét nhãn vào giữa câu | Chỉ nhận dòng **CUỐI** khớp `^Danh mục:\s*`; không khớp ⇒ 0 nhãn |
Khách tự gõ "Danh mục:" trong mô tả tay ⇒ cắt nhầm | Strip chỉ áp cho `caption_auto` |
Nhãn sai làm nhiễu vector | Trần 2 nhãn; nhãn không phải filter nên chỉ đổi thứ hạng |
Ảnh có mô tả tay không bao giờ có nhãn | Đúng thiết kế — `caption` của người thắng `caption_auto` |

## 6. Kiểm chứng

**Unit (portal):** parse 7 ca — 0/1/2 nhãn · nhãn lạ ngoài sổ · thiếu dòng · nhãn giữa câu ·
caption rỗng. Text embed chứa nhãn tiếng Việt chứ không phải mã. `payload.caption` sạch.
`router` trả sạch. `split_caption` không đụng `caption` của người.

**Unit (agent):** ba ca — lọc có kết quả ⇒ không fallback · lọc rỗng ⇒ fallback · không
truyền category ⇒ đúng một lượt search. Cộng một bài canh embed chỉ được gọi MỘT lần.

## 7. Ranh giới

- **Không backfill.** 630 ảnh `tong_quan` của `aina_prod` đã có caption nên `handle_caption`
  bỏ qua — chúng sẽ **không** có nhãn. Phần được cải thiện ngay là 159 ảnh đang caption rỗng
  (nếu chạy lại đợt nạp) và mọi ảnh đẩy lên từ nay. Với 630 ảnh cũ, thứ cứu chúng là §4.
- **Không ghi đè `media.category`.** Nhãn đoán không bao giờ thành dữ liệu của khách.
- **Không hiện nhãn trên giao diện portal** — người dùng chỉ thấy mô tả.
- **Không có thứ tự triển khai bắt buộc** giữa hai repo: §1–§3 chỉ thêm chữ vào một cột và
  vào text embed (agent bản cũ không đọc gì khác đi); §4 độc lập hoàn toàn với §1–§3 và tự
  nó đã cứu được dữ liệu cũ.

## 8. Trạng thái thi công (2026-08-25)

Đã ship: 4 commit ở `odyssey-portal-backend`, 1 commit ở `odyssey-agent`, cùng nhánh
`feat/kb-ingest-speedup`.

**Thử prompt trên ảnh thật của `aina_prod` (4 ảnh, không ghi gì):** model tuân đúng định
dạng dòng cuối **4/4**, độ trễ 2,0–2,7s — không đắt hơn prompt cũ.

| Ảnh | Nhãn model gắn | Nhận xét |
|---|---|---|
`media#712` nhà phố + đường phố | ngoại thất, tiện ích | đúng |
`media#711` toà nhà mặt tiền | ngoại thất, tổng quan | đúng |
`media#710` phòng ngủ | nội thất, tiện ích | đúng, `tiện ích` hơi rộng |
`media#709` **mặt bằng tầng** | mặt bằng | **đúng ca cần cứu** — nó đang nằm trong `tong_quan` |

Model hơi hào phóng với `tiện ích`. Vô hại: nhãn chỉ đổi thứ hạng, không lọc.

**Test:** backend `make check` — 28 dòng đỏ, **trùng khít từng tên với `origin/develop`**,
không hồi quy. Agent `tests/unit` — 44 đỏ, cũng trùng baseline; khác biệt duy nhất nằm
trong `test_tool_ack.py`, file mà CLAUDE.md đã ghi là flaky theo thời gian (chạy riêng:
6/6 xanh).

⚠️ Tám bài trong `tests/unit/unified/test_send_media.py` **đếm số lượt gọi Qdrant** nên
đỏ khi tìm hai lượt — con số đó đổi có chủ ý. Đã viết lại theo hằng `GOI_MOI_LUOT = 2`
thay vì sửa số trần, để lần sau ai đọc còn biết vì sao.

## 9. Cần thêm vào CLAUDE.md (người dùng tự dán)

| Ngày | Thay đổi |
|---|---|
| 2026-08-25 | **VLM đoán danh mục cho ảnh khách để `tong_quan`, và agent tìm media hai lượt.** Đo trên prod: **96% ảnh của `aina_prod` (630/659) nằm trong `tong_quan`**, 5 danh mục còn lại RỖNG — nên `send_media(category='noi_that'|…)` luôn trả rỗng dù ảnh có thật. Hai bản vá độc lập nhau, không có thứ tự deploy bắt buộc. **① Portal**: profile prompt MỚI `caption_danh_muc` (`prompts.yaml`) bảo VLM ghi thêm dòng cuối `Danh mục: <≤2 nhãn>`; `_profile_caption()` chỉ dùng nó khi `media.category = 'tong_quan'`, ảnh khách đã phân loại thì tin khách. ⚠️ **PHẢI là profile riêng, đừng sửa prompt `caption` chung** — `handle_caption_preview` dùng chung nó và trả chữ THẲNG vào ô mô tả của form upload, nên nhãn sẽ hiện trong ô nhập của người dùng. Nhãn ghi vào `media.caption_auto` cùng caption, KHÔNG cột mới: `content_hash = sha256(media_url ␟ caption)` nên caption đổi ⇒ hash đổi ⇒ **re-index tự chạy**; để nhãn ngoài caption thì delta thấy hash không đổi và nhãn không bao giờ lên Qdrant. ⚠️ **Nhãn KHÔNG bao giờ ghi đè `media.category`** — filter vẫn chạy trên cột của khách, nhãn chỉ nằm trong text vector, nên đoán sai chỉ đổi thứ hạng chứ không giấu mất ảnh. `split_caption()`/`normalize_caption()` ở `kb/contracts.py`; nhãn là **tiếng Việt có dấu** (`NHAN_DANH_MUC`) chứ không phải mã snake_case — model dense là `multilingual-e5-large` còn truy vấn của agent là tiếng Việt, `noi_that` embed kém hẳn; `_text_and_hash` cũng đổi theo, nó vốn nhét mã thô `tong_quan` vào chuỗi embed. ⚠️ **Strip ở ĐÚNG HAI CHỖ người đọc**: `realestate/router.py` (`caption or split_caption(caption_auto)[0]`) và `payload["caption"]` của `MediaClient` — và strip **chỉ áp cho `caption_auto`**, vì khách gõ tay chữ "Danh mục:" trong mô tả của họ thì không được cắt. **② Agent** (`media_data.search_media`): embed MỘT lần, search HAI lượt (có filter category + không filter), lượt lọc rỗng thì rơi về lượt kia. Phần đắt là embed nên lượt hai chỉ tốn một round-trip Qdrant. Xét trên `items` chứ không `points` — hit client không render được thì khách vẫn trắng tay. ⚠️ Tám bài `test_send_media.py` đếm số lượt Qdrant nay tính theo `GOI_MOI_LUOT = 2`. **Chưa backfill**: 630 ảnh cũ đã có caption nên `handle_caption` bỏ qua, chúng KHÔNG có nhãn — thứ cứu chúng là ② chứ không phải ①. Spec: `docs/superpowers/specs/2026-08-25-doan-danh-muc-anh-design.md`. |
