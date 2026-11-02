# Hợp đồng: đọc mặt bằng dự án

**Ngày:** 2026-08-10 · **Hướng:** `odyssey-portal-backend` → `odyssey-agent` · **Trạng thái:** chờ repo agent áp

> **⚠️ Đọc trước khi động code:** hợp đồng này **ban đầu** viết cho `agent_api.media` —
> schema đó đã bị xoá hoàn toàn (migration `0917_bo_agent_api`, cùng ngày). Bản này đã sửa
> lại theo hiện trạng: đọc thẳng `tenant_data.media`, tự lọc `status = 'published'` tường
> minh (không còn view lo hộ), và role `odyssey_agent` **không còn `search_path`** trỏ
> `agent_api` — mọi câu SQL phải schema-qualify. Xem `docs/contracts/dau-noi-agent.md` §G-6
> để biết đầy đủ bối cảnh đổi Postgres seam.

## 1. Thay đổi

⚠️ **Sửa lại (review vòng cuối, I-3):** bản trước của mục này nói *"Portal thôi ghi
`map_media_id`"* — SAI. Backend (API) **vẫn nhận `mapMedia` và vẫn ghi** cột đó y nguyên
(`router.py` — alias `mapMedia`/`map_media`, gán `payload["map_media_id"]` sau khi tạo
media; `tests/modules/realestate/test_crud.py::test_du_an_cover_map_media_mot_giao_dich`
canh việc này, xem §6). Cái đã đổi là **frontend** — từ vòng 2 của màn dự án, tab Mặt bằng
gộp còn một vùng ảnh duy nhất nên FE **thôi gửi** `mapMedia` cấp dự án lên API.

Hệ quả: với dự án **tạo/sửa qua Portal UI** (đường FE), cột `map_media_id` **luôn `NULL`**
— không phải vì Portal cấm ghi, mà vì không còn ai gửi giá trị để ghi. Một dự án ghi qua
đường khác (script, API gọi thẳng) vẫn có thể có `map_media_id` khác `NULL`.

## 2. Agent phải đổi sang

```sql
SELECT id, public_url, public_thumb_url, coalesce(nullif(caption, ''), caption_auto) AS caption
  FROM tenant_data.media
 WHERE project_code = $1
   AND zone_code IS NULL AND unit_code IS NULL
   AND category = 'mat_bang'
   AND status = 'published'
 ORDER BY created_at
```

⚠️ **`public_url`/`public_thumb_url`, KHÔNG phải `media_url`/`thumb_url`** (thêm 2026-08-12,
migration `0921_media_public_url`). Hai cột cũ lưu **khoá kho tệp**, và bucket chặn công
khai hoàn toàn — gửi giá trị đó vào `items[].url` là khách nhận một chuỗi không mở được.
Hai cột mới là dạng phát-được của cùng giá trị: ảnh trong kho ta thành URL công khai của
Portal, ảnh dán từ CDN ngoài giữ nguyên văn, nên agent không phải phân biệt hai nguồn.

⚠️ **`caption` một mình là RỖNG với ảnh về bằng cổng nạp** (migration `0936`): mô tả do
model sinh nằm ở `caption_auto`, tách ra vì cổng nạp là latest-wins và sẽ xoá trắng `caption`
ở lần đồng bộ kế tiếp. Đo trên prod 2026-08-19: 30/31 ảnh của một tenant có `caption_auto`
thật và `caption = ''`. Thứ tự đúng là chữ của khách thắng chữ máy sinh — chính là
`coalesce(nullif(caption, ''), caption_auto)` ở câu trên; bỏ vế sau là nhãn ảnh gửi cho
khách thành chuỗi rỗng. Portal đã gộp đúng thứ tự này trong `MediaOut.caption`.

`public_url = ''` nghĩa là hàng chưa được backfill — coi như **không có ảnh**, đừng đẩy
chuỗi rỗng vào `items[].url`.

`tenant_data.media` đã có đủ cột. **Không cần migration.**

Ba điểm khác với bản đọc qua view cũ (`agent_api.media`, nay không còn tồn tại):

- **Tự lọc `status = 'published'`** — trước đây view lo việc này; đọc bảng gốc nghĩa là
  bạn thấy cả `draft`/`archived` nếu quên mệnh đề này.
- **Cách ly tenant do RLS FORCE** (migration `0913`) cưỡng chế theo credential đang nối,
  bạn **không cần** tự viết `WHERE tenant_id = ...` — nhưng vẫn phải tự lọc `status` như
  trên, RLS không biết gì về published/draft.
- Nếu dự án cha (`tenant_data.projects`, `project_code = $1`) không ở `status =
  'published'`, hàng `media` của nó **không tự động bị ẩn** — muốn giữ hành vi cũ (ẩn mặt
  bằng của dự án nháp), tự `JOIN tenant_data.projects p ON p.project_code = m.project_code
  AND p.status = 'published'`.

Truy vấn trả **nhiều** hàng — agent trả cả bộ mặt bằng, không phải một ảnh.

## 3. Cột `map_media_id` không bị xoá

Giữ lại để dữ liệu cũ không mất và để repo agent đổi theo nhịp riêng. Nhưng **đừng đọc nó
nữa**: một dự án cũ còn `map_media_id` khác `NULL` và một dự án mới có `NULL` sẽ cho hai
hành vi khác nhau cho cùng một câu hỏi — đúng loại lỗi chỉ hiện trên dữ liệu thật.

## 4. Khoảng hồi quy

Từ lúc **frontend** ship (thôi gửi `mapMedia` cấp dự án) tới lúc repo agent áp hợp đồng
này, agent đọc `map_media_id` nhận `NULL` cho MỌI dự án tạo/sửa qua Portal UI sau mốc đó,
và trả lời "chưa có mặt bằng" dù dự án **có** ảnh mặt bằng (nằm trong `tenant_data.media`,
chỉ là không còn ai gán `map_media_id` trỏ tới nó). Dự án ghi qua đường khác (script, API
gọi thẳng còn gửi `mapMedia`) không nằm trong khoảng hồi quy này — `map_media_id` của
chúng vẫn đúng, chỉ là agent không nên dựa vào cột đó nữa dù đúng hay sai (xem §3).

Nếu cần đóng khoảng đó trước: Portal đặt `mapMediaId` = ảnh đầu của danh mục `mat_bang` như
một lưới an toàn, gỡ sau khi repo agent xong.

## 5. Cách kiểm đã áp đúng

Sau khi repo agent đổi, hỏi agent "cho xem mặt bằng dự án <mã>" trên một dự án có ≥2 ảnh
`mat_bang`, `status = 'published'`, và `map_media_id IS NULL`. Đúng: trả đủ số ảnh. Sai: trả
"chưa có mặt bằng".

## 6. Cổng canh

**Cổng canh:** `tests/modules/realestate/test_crud.py::test_du_an_cover_map_media_mot_giao_dich`

Test đó tạo một dự án qua `POST /projects` kèm `mapMedia`, rồi khẳng định
`mapMediaId is not None` trên response VÀ trên hàng `tenant_data.projects` đọc thẳng —
đúng khẳng định mà §1 vừa sửa lại (*"API vẫn nhận và vẫn ghi `map_media_id`"*). Nó KHÔNG
canh được nửa còn lại của §1 (frontend thôi gửi `mapMedia` cấp dự án) — đó là thay đổi ở
repo `odyssey-portal-frontend`, ngoài tầm với của một test ở repo này.

Đây là chỗ I-3 (review vòng cuối) lẽ ra đã bắt được sớm hơn: hợp đồng này từng khẳng định
điều ngược với chính cổng canh của nó (*"Portal thôi ghi `map_media_id`"* trong khi test
trên xanh và khẳng định điều ngược lại) mà không ai phát hiện, vì file này — khác
`docs/contracts/bundle.md` — không neo bằng một cổng nào. Sửa một bên (code hoặc hợp đồng)
mà quên bên kia giờ ít nhất còn một chỗ để `grep` ra trước khi tin nội dung phía trên.
