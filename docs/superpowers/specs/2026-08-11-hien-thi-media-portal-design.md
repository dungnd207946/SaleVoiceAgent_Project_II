# Hiển thị media trên Portal — thiết kế

Ngày: 2026-08-11 · Hai repo: `odyssey-portal-frontend` (A–C, F) và `odyssey-portal-backend` (D–E)

## Vấn đề

Portal đang giữ đủ dữ liệu media nhưng không cho người dùng **xem** nó:

- Ảnh render ở đúng 112×80px, không bấm được, dùng chung một cỡ cho cả bốn tab.
- Link 360 chỉ là một thẻ `<a>`; muốn xem phải rời portal.
- `projects.region` mang giá trị máy (`mien_nam`) hiện thẳng ra màn hình.
- 34 ảnh `category = 'csbh'` tồn tại trong DB nhưng **không hiện ở tab nào** — FE không biết danh mục thứ 8.
- 262 ảnh có caption do pipeline KB sinh, nằm trong payload point Qdrant, chưa bao giờ chảy ngược về Postgres.

## Hiện trạng đo được

| Sự thật | Đo ở đâu |
|---|---|
`VungMedia` ghim cứng `h-20 w-28` cho mọi thumbnail, dùng chung cho 4 tab | `components/VungMedia.tsx:64-70` |
`Anh360Tab` chỉ render `<a>` | `components/Anh360Tab.tsx:56-63` |
`projects.region` ở nguồn có đúng 3 giá trị: `mien_bac` (22) · `mien_nam` (15) · `mien_trung` (4) | `odyssey-mockdb`, `tenant_data.projects` |
`media.category` ở nguồn có 8 giá trị, trong đó `csbh` = 34 ảnh | `odyssey-mockdb`, `tenant_data.media` |
CHECK `media_category_hop_le` trên DB dev **đã có 8 giá trị**, nhưng migration `0400_kb_real_estate.py:106` chỉ khai 7 — DB bị sửa tay, lệch dòng migration | `\d tenant_data.media` vs `migrations/versions/` |
`_MediaCategory` ở `modules/realestate/router.py:511` có 7 giá trị → API **từ chối** ghi `csbh` dù DB nhận | `router.py` |
`QdrantStore.scroll_points()` đã đọc sẵn `caption` từ payload; `state/repo.cache_caption()` đã ghi sẵn vào `media.caption` với luật chỉ-ghi-khi-rỗng | `kb/index/store.py:111-144`, `kb/state/repo.py:98-105` |
Job `kb_reclaim_caption` được thiết kế ở Task 11 plan ingest nhưng **chưa viết** | `docs/superpowers/plans/2026-08-10-ingest-qdrant.md` |
Collection media = `<tenant_id>_media`; `workspace_slug` chính là `tenant_id` | `kb/jobs.py:87-89`, `kb/clients/media.py:20-21` |

**Quét toàn bộ cột text của `tenant_data` tìm giá trị dạng slug** — chỉ `projects.region` là chưa có nhãn. `status` · `sale_phase` · `product_type` · `direction` · `sale_status` · `content_type` đã có trong `enums.ts`; `conversations.source` được `PhienKhach.tsx` dịch tay.

## A. Bố cục ảnh — `VungMedia` nhận prop `boCuc`

Một component, hai bố cục:

| Tab | `boCuc` | Hình dạng |
|---|---|---|
Vị trí · Mặt bằng | `gallery` | 1 ảnh lớn `max-h-[60vh]` **`object-contain`** + dải thumbnail bấm để đổi ảnh |
Tiến độ · Media (bên trong folder) | `luoi` | Lưới 2→4 cột co giãn, thẻ ~260×180 `object-cover`, nút Xoá hiện khi hover |

**`object-contain` cho gallery, không phải `object-cover`:** mặt bằng là bản vẽ kỹ thuật — `object-cover` cắt rìa, mà rìa là chỗ ghi ký hiệu và tỉ lệ. Lưới thì ngược lại: ảnh phối cảnh cắt được, và một lưới ảnh lệch tỉ lệ đọc như lỗi bố cục.

**Nút Xoá hiện khi hover, không hiện thường trực:** ảnh là nhân vật chính của vùng này; ba nút xám nằm dưới ba ảnh 112px là lý do vùng cũ trông như một bảng biểu.

Cả hai bố cục: bấm ảnh mở **lightbox** — component mới `components/AnhLon.tsx`, dialog toàn màn hình theo đúng nếp `TaoWorkspaceDialog.tsx` (Esc đóng qua listener trên `document`, focus trap, `role="dialog"`). Lightbox nhận **cả bộ ảnh + chỉ số đang xem**, không nhận một ảnh: `‹ ›` đi trong bộ là lý do chính người ta mở nó.

Ô video hiện là một ô xám câm ghi "Video" — cho nó bấm được để mở link ở tab mới. Không nhúng player: `media_url` của video ở nguồn là YouTube embed lẫn `.mp4` trực tiếp, hai thứ cần hai cách nhúng khác nhau và không ai yêu cầu.

## B. Tab Ảnh 360 — nhúng thật

Khi `link360` không rỗng: `<iframe>` tỉ lệ 16:9, `allowfullscreen`, `loading="lazy"`, **kèm dòng link mở tab mới ngay dưới**.

Dòng link đó không phải trang trí. Kuula/Matterport có thể trả `X-Frame-Options: DENY`, và khi đó iframe trắng trơn mà **không phát ra sự kiện nào** để JS biết mà báo — không có `onerror`, không có cách đọc trạng thái khung khác origin. Link là đường thoát duy nhất, nên nó luôn hiện chứ không phải hiện khi lỗi.

Chỉ nhúng khi URL bắt đầu `https://`. `http://` chỉ hiện link: portal chạy https, trình duyệt chặn mixed content **im lặng** và người dùng lại thấy một khung trắng không giải thích được.

**Không whitelist domain nhà cung cấp.** Link do chính người trong tenant nhập, và whitelist sẽ chặn nhầm dịch vụ thứ tư mà không ai đoán trước. Đánh đổi được chấp nhận: một link độc hại nhúng được vào trang portal — khác origin nên không đọc được cookie phiên.

## C. Nhãn tiếng Việt cho `region`

Thêm vào `features/realestate/enums.ts`:

```ts
export const KHU_VUC = chon([
  { value: 'mien_bac', nhan: 'Miền Bắc' },
  { value: 'mien_trung', nhan: 'Miền Trung' },
  { value: 'mien_nam', nhan: 'Miền Nam' },
])
```

Gọi `nhanCua(KHU_VUC, …)` ở mọi chỗ **hiển thị** `region`: `ViTriTab.tsx:105` (DongXem), `DuAnList.tsx:213` (cột bảng), và nhãn của bộ lọc khu vực.

**Chỉ đổi lúc hiển thị, không đụng DB.** `nhanCua()` trả lại chính giá trị khi không khớp, nên `Quận 7, TP.HCM` hiện nguyên vẹn — hai kiểu dữ liệu sống chung được. Chuẩn hoá trong DB thì mất giá trị máy để lọc, và lần nạp sau từ nguồn lại sinh slug mới.

Ô **nhập** `region` vẫn là text tự do, không đổi thành dropdown: `region` là trường bắt buộc của completeness, và biến nó thành enum buộc phải quyết định dữ liệu tự do hiện có đi đâu — việc đó không thuộc phạm vi này.

## D. `csbh` thành danh mục media thứ 8

Ba chỗ, thiếu chỗ nào cũng hỏng theo kiểu khác nhau:

1. **Migration `0918_media_category_csbh`** — `DROP CONSTRAINT IF EXISTS media_category_hop_le` rồi `ADD` lại với 8 giá trị. Phải idempotent theo cả hai chiều vì **DB dev đã có 8** (sửa tay) còn DB dựng mới từ migration chỉ có 7. `downgrade` trả về 7 và sẽ nổ nếu đang tồn tại hàng `csbh` — đó là hành vi đúng, ghi rõ trong docstring.
2. **`_MediaCategory` ở `router.py:511`** thêm `"csbh"`. `_LocMediaCategory` suy từ nó nên bộ lọc tự có.
3. **`MEDIA_CATEGORY` ở `enums.ts`** thêm `{ value: 'csbh', nhan: 'Chính sách bán hàng' }` — nhãn khớp `LOAI_TAI_LIEU.csbh` đã có. `csbh` không nằm trong `MEDIA_CATEGORY_TAB_RIENG` nên tab Media tự có folder thứ 5, không phải sửa `MediaTab.tsx`.

## E. Script thu hồi caption từ Qdrant

`scripts/thu_hoi_caption_tu_qdrant.py`, theo nếp `nap_du_lieu_tu_odyssey.py`.

**Luồng:** với mỗi tenant → `scroll` collection `<tenant_id>_media` (`with_payload=True`, `with_vectors=False`) → ghép `payload.record_id` với `media.id` → `UPDATE tenant_data.media SET caption`.

**Nối bằng `portal_api` + `SET LOCAL app.tenant_id` mỗi tenant trong một giao dịch**, không dùng `portal_migrator`. Tôn trọng luật 1 của repo, và không cần superuser cho một việc chỉ ghi một cột.

**Mặc định chỉ ghi khi `caption = ''`** — cùng luật `state/repo.cache_caption()`. `FORCE=1` mới đè caption người dùng đã sửa tay.

**Chỉ ghi, không xoá** → chạy lại vô hại. Khác hẳn `nap_du_lieu_tu_odyssey.py` (mở đầu bằng DELETE), nên không cần cảnh báo tương ứng.

**Env:** `TGT_DSN` · `QDRANT_URL` · `QDRANT_API_KEY` · `TENANTS` (danh sách ngăn bởi dấu phẩy; rỗng hoặc không đặt = mọi tenant trong `control.tenants`) · `FORCE` (`1` = đè, mọi giá trị khác = không).

**In tổng kết mỗi tenant:** point đọc được / point có caption / hàng đã ghi / bỏ qua vì đã có caption / `record_id` không khớp hàng nào. Cột cuối là cột quan trọng nhất — nó phát hiện point mồ côi còn sót từ record đã xoá.

⚠️ **Qdrant trên EC2 không publish port.** Người chạy phải dựng tunnel SSM trước; script chỉ đọc `QDRANT_URL` từ env và không tự làm việc đó. Ghi trong docstring đầu tệp.

**Tách hàm thuần để test:** `ghep_caption(points, caption_hien_co, *, force) -> KetQuaGhep` — `points` là `list[IndexPoint]` scroll về, `caption_hien_co` là `dict[int, str]` map `media.id` → caption đang có trong Postgres. Trả về dataclass gồm `can_ghi: list[tuple[int, str]]`, `bo_qua_da_co: int`, `mo_coi: list[int]` (record_id không có trong `caption_hien_co`). Test unit cho hàm này; vỏ script (đọc env, mở kết nối, in bảng) không test.

## F. Sắp lại tab Media

Mức 1 hiện là 4 thẻ folder, ảnh bìa `h-24`, lưới 4 cột — thẻ nhỏ và ảnh bìa bé đúng bằng thứ người dùng phàn nàn. Đổi thành lưới 2→3 cột, ảnh bìa `h-36`. Thứ tự folder vẫn suy từ `MEDIA_CATEGORY` (không liệt kê tay), nên `csbh` tự vào đúng chỗ.

## Ranh giới và phụ thuộc

- `AnhLon.tsx` không biết gì về media của BĐS: nó nhận `readonly { src: string; caption: string }[]` + chỉ số. Dùng lại được ở form phân khu/căn sau này.
- `VungMedia` giữ nguyên chữ ký hiện có, thêm đúng một prop `boCuc` với mặc định `'luoi'` — bốn nơi gọi hiện tại không nơi nào gãy.
- Cả bốn tab vẫn dùng chung query key `['re', code, 'media']`, không đổi.
- D là thay đổi hợp đồng: `contracts/` không sinh lại (không đụng `actions.py`/`tools.py`), nhưng `docs/contracts/mat-bang-agent.md` phải nhắc danh mục thứ 8.

## Kiểm

**Backend:** test migration `0918` chạy được trên DB đã có `csbh` lẫn DB chưa có · test API nhận `category='csbh'` khi tạo media · test unit `ghep_caption()` bốn nhánh (rỗng→ghi, đã có→bỏ qua, `force`→đè, point mồ côi→đếm riêng).

**Frontend:** test `nhanCua(KHU_VUC, 'mien_nam')` = `'Miền Nam'` và `nhanCua(KHU_VUC, 'Quận 7, TP.HCM')` trả nguyên văn · test lightbox mở khi bấm ảnh, Esc đóng, `‹ ›` đổi ảnh · test `boCuc='gallery'` render đúng một ảnh lớn · test folder `csbh` xuất hiện ở tab Media · test iframe 360 chỉ render với `https://`.
