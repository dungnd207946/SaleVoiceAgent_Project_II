# M7 — Màn Hội thoại: khách → phiên → transcript

Ngày: 2026-08-06 · Module: M7 (Vận hành) · Màn: `convos` · Trạng thái: thiết kế đã duyệt

---

## 1. Vấn đề

Màn `convos` hiện là `ScreenStub`. Dữ liệu thì đã có: agent ghi thẳng vào
`tenant_data.conversations` (migration 0903), mỗi hàng là **một phiên**. Nhưng
một người khách thường có nhiều phiên — hỏi giá tuần trước, hỏi vay tuần này,
chốt lịch hôm nay. Bày phẳng theo phiên thì cùng một người hiện thành 6 dòng rời
rạc, và câu hỏi thật của người vận hành ("khách này đã hỏi những gì rồi?") không
trả lời được nếu không tự ghép trong đầu.

Màn này nhóm theo **số điện thoại**: ngoài là danh sách khách, bấm vào một khách
mới ra các phiên của người đó.

**Phạm vi: CHỈ XEM.** Không sửa, không xoá, không tiếp quản hội thoại, không đặt
lịch. Ảnh tham chiếu của prototype có ô nhập tin và hai nút «Tiếp quản» / «Mở
lịch hẹn» — spec này **cố ý bỏ cả ba**. Chúng thuộc `convos.handle`, một action
đã có trong catalog quyền nhưng không có đường ghi nào phía sau; dựng nút cho
một hành động chưa tồn tại là hứa với người dùng một thứ không bấm được.

---

## 2. Dữ liệu

Hai bảng: `tenant_data.conversations` (0903) cho **phiên**, và
`tenant_data.conversation_messages` (0915) cho **từng lượt nói**. Không view,
không bảng phụ nào khác.

> **Đổi hướng 06/08:** bản đầu của spec này để cả transcript trong một cột `jsonb`
> `conversations.full_conversation` (`0912`). Chủ sản phẩm đổi sang một bảng
> riêng, mỗi lượt một hàng. `0915` tạo bảng mới **và gỡ luôn cột cũ** — nó chưa
> mang dữ liệu ở bất kỳ môi trường nào (đã đo: 0 hàng). Đừng đi tìm cột đó.

| Cột | Dùng ở đâu |
|---|---|
| `session_id` | Khoá của một phiên — đường dẫn màn chi tiết |
| `phone` | **Khoá nhóm.** Nullable |
| `customer_name` | Tên hiện ở danh sách + header. Nullable |
| `project` | Chip dự án. Là TÊN tự do, không phải mã — không JOIN đi đâu cả |
| `transferred_to_sales` | Badge «Đã chuyển sales» + bộ lọc |
| `running_version` | Dải meta của phiên (`config v12`) |
| `summary` | Trích đoạn ở danh sách + dải tóm tắt đầu transcript |
| `skill_calls` | Dòng công cụ trong transcript |
| `started_at` · `ended_at` | Thời điểm + thời lượng |
| `created_at` | Dự phòng khi `started_at` NULL |

### 2.1 `tenant_data.conversation_messages` — transcript

| Cột | Dùng ở đâu |
|---|---|
| `tenant_id` · `session_id` · `seq` | PK. `seq` 0-based là **thứ tự đọc duy nhất** |
| `role` | `user` = khách (phải) · `assistant` = agent (trái) · `tool` = dòng hệ thống |
| `content` | Nội dung bong bóng. `NOT NULL DEFAULT ''` |
| `created_at` | Mốc giờ của lượt — thứ hiện ra khi rê chuột (§5.3) |
| `meta` | `tool_calls` · `latency` · `interrupted` · `cached` · `source`… |

**Sắp xếp bằng `seq`, KHÔNG bằng `created_at`.** Hai lượt trong cùng một giây có
thứ tự xác định theo `seq`; theo `created_at` thì không, và transcript sẽ đảo lượt
một cách ngẫu nhiên giữa hai lần tải. `created_at` chỉ để **hiển thị**.

**Không có CHECK trên `role`** (quyết định của `0915`: một `role` thứ tư từ phía
agent không được làm vỡ đường ghi của họ). Nên FE phải coi `role` là mở: mọi giá
trị ngoài `user`/`assistant` render thành dòng hệ thống xám ở giữa màn — hiện ra,
không bỏ đi.

**`meta` không có hợp đồng hình dạng tổng quát, nhưng MỘT hình dạng đã xác nhận
với dữ liệu thật của team agent (chốt 07/08):** một cuộc gọi tool KHÔNG nằm trên
một hàng — nó là HAI hàng, ghép bằng `tool_call_id`:

1. Hàng `role: "assistant"`, `content: ""`, `meta.tool_calls` là một mảng
   `[{id, type: "function", function: {name, arguments}}]` — đây là YÊU CẦU gọi
   tool. `content` rỗng ở đây KHÔNG phải một lời nói rỗng của agent; không được
   render bong bóng trống cho hàng này.
2. Hàng `role: "tool"`, `content` là CHUỖI JSON kết quả (có thể rất dài — ví dụ
   `discover_projects` trả nguyên một trang danh mục), `meta: {name,
   tool_call_id}` với `tool_call_id` khớp `id` ở hàng (1).

FE ghép hai hàng này thành MỘT khối — đóng theo mặc định (chỉ hiện tên hàm),
bấm để xem tham số/kết quả dạng JSON canh dòng trong khung cuộn riêng. Ghép bằng
`tool_call_id`, KHÔNG bằng vị trí kề nhau: lịch sử bị cắt hoặc hai luồng chèn lẫn
vẫn phải ra đúng. Một hàng `tool` không có hàng `assistant` nào khai (mồ côi)
vẫn phải hiện — dùng `meta.name`, không im lặng bỏ. Khoá khác trong `meta`
**không đọc**; đoán thêm khoá là xây trên một hợp đồng chưa ai ký.

`conversations.skill_calls` (0903) vẫn còn và vẫn không có hợp đồng hình dạng.
Nó là **nguồn dự phòng**: chỉ dùng khi không lượt nào của phiên mang
`meta.tool_calls`, và khi đó dồn xuống cuối phiên thành một khối «Công cụ agent đã
gọi» — vì cột đó ở mức phiên, không biết nó thuộc lượt nào. Hai nguồn cho cùng một
thứ là nợ kỹ thuật đã biết; ghi ở đây để lần sau ai chốt được hợp đồng thì xoá
nhánh dự phòng, đừng thêm nhánh thứ ba.

---

## 3. Backend — module `ops`

Thư mục mới `src/portal/modules/ops/` với `contracts.py` · `repo.py` ·
`router.py`, đúng khuôn `realestate`. Router tự lên nhờ `api/registry.py` —
không sửa `app.py`, không sửa `registry.py`.

### 3.1 Ba endpoint, tất cả GET

| Đường dẫn | Quyền | Trả về |
|---|---|---|
| `GET /api/v1/convos/khach` | `convos.read` | Danh sách khách đã nhóm |
| `GET /api/v1/convos/khach/{phone}/phien` | `convos.read` | Các phiên của một khách, **không** kèm transcript |
| `GET /api/v1/convos/phien/{session_id}` | `convos.read` | Một phiên đầy đủ, kèm transcript |

Không có POST/PATCH/DELETE. Phạm vi là xem.

**Vì sao tách endpoint thứ 3** dù nó cùng quyền với hai cái kia: transcript là
phần nặng nhất của một hàng. Nhét nó vào danh sách phiên nghĩa là mở một khách
có 6 phiên thì kéo về 6 transcript trong khi người dùng đọc 1.

**Nhưng endpoint 2 VẪN phải trả số lượt** — cột phiên hiện «6 lượt» (§5.2):

```sql
SELECT c.session_id, c.started_at, c.ended_at, c.summary, c.project,
       c.transferred_to_sales, c.running_version,
       count(m.seq) AS so_luot
  FROM tenant_data.conversations c
  LEFT JOIN tenant_data.conversation_messages m
         ON m.tenant_id = c.tenant_id AND m.session_id = c.session_id
 WHERE c.tenant_id = portal.current_tenant() AND <khoá nhóm phone>
 GROUP BY c.session_id, c.started_at, c.ended_at, c.summary, c.project,
          c.transferred_to_sales, c.running_version
 ORDER BY COALESCE(c.started_at, c.created_at) DESC
```

**`LEFT JOIN`, không `JOIN`.** Một phiên chưa có lượt nào vẫn phải hiện với
`so_luot = 0`; `JOIN` trần làm nó biến mất khỏi cột phiên và không ai biết là mất.
**`count(m.seq)`, không `count(*)`** — `count(*)` đếm cả hàng NULL do LEFT JOIN
sinh ra và trả `1` cho một phiên rỗng.

Đây là chỗ dễ sai theo hai hướng: bỏ luôn `so_luot` (cột phiên mất một nửa thông
tin), hoặc `SELECT` cả `content` về chỉ để đếm.

`GET /khach/{phone}/phien` của một số không còn phiên nào trả **mảng rỗng**,
không phải 404: một URL đã gửi cho đồng nghiệp vẫn phải mở được, và màn hiện
«Khách này không còn phiên nào».

**Endpoint 3** đọc `conversation_messages` của đúng một phiên:

```sql
SELECT seq, role, content, created_at, meta
  FROM tenant_data.conversation_messages
 WHERE tenant_id = portal.current_tenant() AND session_id = $1
 ORDER BY seq          -- KHÔNG ORDER BY created_at, xem §2.1
```

Kèm meta của phiên lấy từ `conversations` (dải đầu transcript: `session_id` ·
giờ · thời lượng · `running_version` · `summary`). Một phiên có hàng trong
`conversations` nhưng chưa có lượt nào ⇒ `200` + mảng rỗng, **không** 404 — phiên
đó có thật, nó chỉ chưa có nội dung.

**Vì sao KHÔNG dùng `convos.transcript.read`:** action đó có trong catalog
(migration 0104) nhưng spec này cố ý không gắn nó vào endpoint nào — quyết định
của chủ sản phẩm ngày 06/08: ai xem được hội thoại thì xem được cả nội dung. Ghi
lại ở đây để lần sau ai thấy action lơ lửng thì biết là chủ ý, không phải bỏ sót.

### 3.2 Nhóm theo số điện thoại

```sql
SELECT COALESCE(phone, '')                                   AS phone,
       count(*)                                              AS so_phien,
       max(COALESCE(started_at, created_at))                 AS gan_nhat,
       min(COALESCE(started_at, created_at))                 AS dau_tien,
       bool_or(transferred_to_sales)                         AS da_chuyen,
       (array_agg(customer_name ORDER BY COALESCE(started_at, created_at) DESC)
          FILTER (WHERE customer_name IS NOT NULL))[1]       AS ten,
       (array_agg(summary ORDER BY COALESCE(started_at, created_at) DESC)
          FILTER (WHERE summary IS NOT NULL AND summary <> ''))[1] AS summary_cuoi,
       (array_agg(project ORDER BY COALESCE(started_at, created_at) DESC)
          FILTER (WHERE project IS NOT NULL))[1]             AS du_an
  FROM tenant_data.conversations
 WHERE tenant_id = portal.current_tenant()
   AND (<lọc thời gian>) AND (<lọc đã chuyển>) AND (<tìm kiếm>)
 GROUP BY 1
 ORDER BY gan_nhat DESC
 LIMIT $n OFFSET $m
```

Bốn điểm không được đổi khi ai đó "dọn lại cho gọn":

1. **`array_agg(... ORDER BY ...)[1]`, KHÔNG phải `max()`.** Cần *giá trị của
   phiên mới nhất*, không phải giá trị lớn nhất theo thứ tự chữ cái.
   `max(customer_name)` chạy được, không báo lỗi, và trả tên sai.
2. **`FILTER (WHERE ... IS NOT NULL)`** để một phiên không ghi tên không đẩy
   `NULL` lên vị trí đầu mảng và xoá mất tên đã biết từ phiên trước.
3. **`COALESCE(started_at, created_at)`** ở mọi chỗ sắp xếp: `started_at`
   nullable, và một phiên không có nó vẫn phải nằm đúng chỗ trên trục thời gian.
4. **`WHERE tenant_id = portal.current_tenant()`.** Migration 0909 đã **bỏ RLS
   toàn bộ** — không còn lưới an toàn nào ở tầng DB. Quên vị này là rò dữ liệu
   xuyên tenant, và nó không có triệu chứng gì cho tới khi có tenant thứ hai.
   Tenant hiệu lực do `tenant_conn()` đặt từ membership đã xác thực, KHÔNG BAO
   GIỜ từ path/query.

**Chỉ mục:** `conversations_tenant_phone_idx (tenant_id, phone)` đã có từ 0903 —
đủ. Không thêm migration.

### 3.3 Tham số

| Tham số | Kiểu | Mặc định | Ghi chú |
|---|---|---|---|
| `q` | str | `""` | ILIKE trên `phone` và `customer_name` |
| `tu_ngay` | `7` \| `30` \| `all` | `30` | Theo `gan_nhat` |
| `da_chuyen` | bool | `false` | `true` ⇒ chỉ khách có `bool_or(transferred_to_sales)` |
| `limit` | int | 50 | Trần 200 — dùng lại `TRANG_MAC_DINH`/`GIOI_HAN_TRANG` của `realestate` |
| `offset` | int | 0 | |

`q` đi vào `ILIKE '%' || $1 || '%'` bằng **tham số bind**, không nối chuỗi. Hai ký
tự `%` và `_` người dùng gõ được escape trước khi bind (`ESCAPE '\'`) — nếu
không, gõ `%` khớp toàn bộ dữ liệu và gõ `_` khớp mọi ký tự đơn, người dùng chỉ
thấy "bộ lọc hỏng".

### 3.4 Khoá nhóm «Chưa có số»

`COALESCE(phone, '')` — mọi phiên `phone IS NULL` gộp thành một nhóm khoá rỗng.
Trên đường dẫn, nhóm này đi bằng **`_`** (`/convos/_`): chuỗi rỗng không đi qua
được path param, và `_` không thể là số điện thoại thật nên không đụng nhóm nào.

Nhóm này **không phải một người**. UI phải nói rõ điều đó (§5.1, §5.2), và
endpoint không được trả `ten` cho nó dù có phiên nào ghi `customer_name`.

### 3.5 Lỗi

Theo khuôn `api/loi.py` đang có: `{error: {code, message}}`. `404` khi
`session_id` không thuộc tenant hiệu lực — **không** `403`, vì phân biệt hai mã
đó cho người ngoài biết session ấy có tồn tại ở tenant khác hay không.

---

## 4. Frontend — routes và tệp

### 4.1 Route

```
src/routes/_app/convos.tsx          →  /convos          · danh sách khách
src/routes/_app/convos.$phone.tsx   →  /convos/$phone   · phiên + transcript
```

Ba bộ lọc nằm trong **search param** (`?q=&tu=&chuyen=`) chứ không phải
`useState`: F5 hoặc gửi link cho đồng nghiệp thì vẫn ra đúng danh sách đang xem.
Phiên đang chọn cũng vậy: `/convos/0912448xxx?sess=sess-a91f3c`.

### 4.2 Tệp mới trong `src/features/ops/`

| Tệp | Việc |
|---|---|
| `api.ts` | 3 hàm gọi + kiểu, chép tay từ `contracts.py` (cùng khoảng hở đã ghi ở `realestate/api.ts`) |
| `components/KhachList.tsx` | Thanh lọc + danh sách + rỗng/lỗi/đang tải |
| `components/KhachRow.tsx` | Một hàng khách |
| `components/PhienKhach.tsx` | Màn chi tiết: header + cột phiên + transcript |
| `components/Transcript.tsx` | Render các lượt nói (theo `seq`) + ghép cặp `assistant`(rỗng)/`tool` thành khối gọi tool (§2.1) |
| `thoiGian.ts` | «14:22» · «hôm qua» · «3 ngày trước» · thời lượng `m:ss`. Hàm thuần, không React |

Dữ liệu qua React Query, khoá `['convos','khach',...]` / `['convos','phien',...]`.
Thêm handler MSW cho cả 3 endpoint để màn chạy được trước khi backend lên.

---

## 5. Thiết kế thị giác

Token lấy từ `styles/theme.css`, không mã màu tự nghĩ. Số liệu dùng
`--font-mono` như mọi màn khác.

### 5.1 Danh sách khách — dòng rộng

Mỗi khách một dải ngang trọn chiều rộng, KHÔNG phải bảng:

```
┌──────────────────────────────────────────────────────────────────────────┐
│ (MA)  Nguyễn Minh Anh    Hỏi căn 3PN dưới 6 tỷ ở Ocean Park 2.      14:22 │
│       0912 448 ***       Agent đã gửi mặt bằng và chốt lịch xem…  6 phiên │
│                          [Ocean Park 2] [• Đã chuyển sales]            ›  │
└──────────────────────────────────────────────────────────────────────────┘
```

Bốn thứ tách nó khỏi hình dạng "table list":

- **Hàng cao, summary giữ 2 dòng** (`-webkit-line-clamp: 2`) — một dòng thì mọi
  khách trông giống nhau.
- **Chip nằm DƯỚI summary**, không chen ngang hàng meta: tên dự án dài không
  được bóp chữ của cột khác.
- **Vạch accent 3px dọc mép trái khi hover** + mũi `›` sáng lên. Một hàng bấm
  được phải nói ra rằng nó bấm được.
- **Mốc ngày chia nhóm** (Hôm nay · Hôm qua · Tuần trước) — 32 hàng phẳng không
  có nhịp nào cho mắt bám.

Avatar là chữ cái đầu của tên, màu nền chọn tất định từ `phone` (cùng số ⇒ cùng
màu qua mọi lần tải). Không có tên ⇒ dùng `?`.

Hàng **«Chưa có số»**: viền đứt, chữ xám, phụ đề «— ẩn danh». Nó không được
trông giống một người thật.

**Thanh lọc** đầu trang: ô tìm · nhóm nút `7 ngày / 30 ngày / Tất cả` · toạc «Chỉ
khách đã chuyển sales» · số tổng canh phải (`32 khách · 86 phiên`).

**Màn rỗng**: khung viền đứt, «Chưa có hội thoại nào» + một câu giải thích khi
nào thì có. Không phải thông báo lỗi, không màu đỏ — kho rỗng là bình thường
(cùng lý lẽ BR04 của `TaiLieuList`).

### 5.2 Màn chi tiết

```
← Tất cả khách
(MA)  Nguyễn Minh Anh                                [Ocean Park 2] [• Đã chuyển]
      0912 448 *** · 6 phiên · từ 14/07 đến 27/07
┌───────────────────┬────────────────────────────────────────────────────────┐
│ 6 PHIÊN           │ sess-a91f3c · 27/07 14:22 → 14:24 (1:48) · 6 lượt  v12 │
│ ▍27/07 · 14:22    ├────────────────────────────────────────────────────────┤
│   Hỏi căn 3PN…    │  ┃ TÓM TẮT CỦA AGENT                                   │
│   6 lượt · 1:48   │  ┃ Khách hỏi căn 3PN dưới 6 tỷ…                        │
│  21/07 · 09:10    │                                                         │
│   Hỏi giá…        │              Còn căn nào 3PN dưới 6 tỷ không em? ◀──── │
│   4 lượt · 2:31   │  ────▶ Dạ hiện còn 4 căn ạ. NT2-1408, 5,62 tỷ.         │
│                   │  search_units(project=VOP2, …) → 4 · 128ms              │
└───────────────────┴────────────────────────────────────────────────────────┘
```

- **Khách bên phải** (nền trắng, viền xám), **agent bên trái** (nền `--color-acs`).
  Ngược nhẹ so với ảnh prototype, nhưng khớp thói quen "mình bên phải" của mọi
  app chat — người vận hành đọc màn này là đọc thay cho agent.
- **Tóm tắt ở ĐẦU** transcript, dải màu ấm. Người mở một phiên ra thường muốn
  biết ngay chuyện gì đã xảy ra, rồi mới đọc chi tiết.
- **Một cuộc gọi tool** (§2.1) hiện thành MỘT khối riêng, KHÔNG phải bong bóng
  chat: không mỏ, không viền đứt (viền đứt đã mang nghĩa "chưa có gì" ở màn danh
  sách — dùng lại đây sẽ đá nghĩa), nền `--color-acs` — CÙNG MÀU bong bóng
  agent, vì đây là hành động của agent, không phải của khách — chỉ khác ở HÌNH
  (hộp chữ nhật bo đều, không mỏ bong bóng). Đóng theo mặc định, chỉ hiện tên hàm (`Agent đã dùng
  tool · <tên>`); bấm để mở «Tham số» (ẩn nếu trống) và «Kết quả», cả hai dạng
  JSON canh dòng trong khung cuộn riêng — không cắt cụt dữ liệu, chỉ không tràn
  màn. `skill_calls` mức phiên (0903) vẫn là nguồn DỰ PHÒNG như cũ: chỉ dùng khi
  không lượt nào của phiên mang một cuộc gọi tool nào, dồn xuống cuối phiên.
- Cột phiên sắp mới nhất trên đầu; phiên đang chọn có nền `--color-acs` + vạch
  accent trái.

### 5.3 Mốc giờ — ẩn, rê chuột mới hiện

Giờ của từng lượt **ẩn mặc định**. Rê chuột vào một lượt thì hiện giờ của **đúng
lượt đó** (không phải cả phiên).

```css
.tt { opacity: 0; transform: translateY(-3px); height: 16px;
      transition: opacity .22s cubic-bezier(.4,0,.2,1),
                  transform .22s cubic-bezier(.4,0,.2,1); }
.msg:hover .tt, .msg:focus-within .tt { opacity: 1; transform: translateY(0); }
```

Bốn ràng buộc, không cái nào là tuỳ chọn:

1. **`opacity: 0`, KHÔNG `display: none`.** Ô giờ phải luôn chiếm chỗ. Nếu nó
   biến mất hẳn thì lúc rê chuột cả cột tin nhắn bị xô xuống 16px — chuyển động
   mượt cỡ nào cũng không cứu được cảm giác đó.
2. **`:focus-within` hiện y như hover.** Người dùng bàn phím không có "rê vào";
   không có dòng này thì mốc giờ là dữ liệu họ không bao giờ tới được.
3. **`@media (hover: none)` ⇒ hiện sẵn.** Trên điện thoại/tablet không có trạng
   thái hover, ẩn đi là giấu mất dữ liệu vĩnh viễn.
4. **`prefers-reduced-motion` ⇒ bỏ phần nhích 3px**, chỉ còn mờ dần.

---

## 6. Trường hợp biên

| Tình huống | Xử lý |
|---|---|
| `phone IS NULL` | Gộp nhóm «Chưa có số», đường dẫn `/convos/_`, viền đứt |
| `customer_name` NULL ở mọi phiên | Hiện số điện thoại làm tên, avatar `?` |
| `customer_name` khác nhau giữa các phiên | Lấy của phiên **mới nhất** (§3.2) |
| `summary` NULL/rỗng | Danh sách: bỏ hẳn dòng trích. Cột phiên: «Chưa có tóm tắt cho phiên này» xám nghiêng |
| Phiên không có hàng nào trong `conversation_messages` | «Phiên này chưa có bản ghi hội thoại» — không phải lỗi |
| `role: "assistant"` với `content = ''` VÀ `meta.tool_calls` hợp lệ | Không render bong bóng — đây là YÊU CẦU gọi tool, render thành khối gọi tool (§2.1) |
| `role: "assistant"` với `content = ''` VÀ không có `tool_calls` (suy biến) | Không render gì — không có gì để hiện |
| `role: "tool"` có `tool_call_id` khớp một `assistant` đã khai | Ghép vào khối gọi tool của hàng `assistant` đó, không render riêng |
| `role: "tool"` KHÔNG khớp hàng `assistant` nào (mồ côi — lịch sử bị cắt) | Vẫn render một khối gọi tool riêng, dùng `meta.name` nếu có |
| `role` lạ khác (không phải `user`/`assistant`/`tool`) | Dòng hệ thống xám giữa màn, không bỏ đi — `0915` cố ý không có CHECK |
| `seq` nhảy cóc (0, 1, 5) | Vẫn render theo thứ tự `seq`, không chèn chỗ trống, không báo lỗi |
| `meta.tool_calls` không phải mảng, hoặc một phần tử thiếu `id`/tên hàm | Bỏ qua đúng phần tử đó; hàng còn lại (bong bóng nếu có `content`) vẫn hiện |
| `arguments`/`content` của `tool` không parse được JSON | Hiện nguyên văn chuỗi thô trong khung cuộn, không vỡ màn |
| Cuộc gọi tool chưa có kết quả (phiên bị cắt giữa lúc gọi) | Khối vẫn hiện tên hàm; mở ra thấy «Phiên bị ngắt trước khi có kết quả» |
| Lượt nói có `session_id` không có hàng trong `conversations` | Không tới được từ UI (luôn vào qua phiên). Không dựng đường riêng cho nó |
| `ended_at` NULL | Không hiện thời lượng. **Không** in `0:00` — nó là một con số sai |
| `started_at` NULL | Dùng `created_at` cho mọi phép sắp xếp và hiển thị |
| `project` NULL | Chip «Chưa rõ dự án» |
| Tenant chưa có hội thoại nào | Màn rỗng §5.1 |
| `session_id` không thuộc tenant | 404 |

---

## 7. Kiểm thử

**Backend** (`tests/modules/ops/`):

- Nhóm theo phone: 3 phiên cùng số ⇒ 1 hàng, `so_phien = 3`.
- `ten`/`summary_cuoi`/`du_an` lấy đúng **phiên mới nhất**, không phải `max()` —
  ca chốt: phiên cũ tên `"Zũng"`, phiên mới tên `"An"` ⇒ phải ra `"An"`.
- Phiên `customer_name` NULL không xoá tên đã biết từ phiên khác.
- `phone IS NULL` gộp một nhóm, khoá rỗng.
- **Cách ly tenant**: tenant A không thấy hàng nào của B qua cả 3 endpoint. Đây
  là cổng quan trọng nhất của module — 0909 đã bỏ RLS, không còn lưới nào khác.
- `q` chứa `%` không khớp toàn bộ bảng; `q` chứa `_` không khớp mọi ký tự đơn.
- Ba bộ lọc kết hợp trả đúng tập.
- `/khach/{phone}/phien` trả `so_luot` đúng bằng số hàng `conversation_messages`,
  và **không** mang `content` của lượt nào trong thân trả về.
- Phiên **0 lượt** vẫn xuất hiện trong danh sách phiên với `so_luot = 0` — cổng
  canh `LEFT JOIN` + `count(m.seq)`, hai lỗi im lặng đã ghi ở §3.1.
- `/khach/<số không có phiên>/phien` trả `200` + mảng rỗng, không phải `404`.
- Transcript trả về **đúng thứ tự `seq`** kể cả khi `created_at` của hai lượt
  bằng nhau — ca chốt: hai hàng cùng `created_at`, `seq` 1 và 0, phải ra 0 trước.
- **Cách ly**: tenant A gọi endpoint 3 với `session_id` của B ⇒ `404`, và bảng
  `conversation_messages` có RLS bật (`0915` gọi `enforce_tenant_isolation`; xác
  minh trên DB dev: 12/12 bảng `tenant_data` có RLS sau `0913` + `0915`).

**Frontend** (`tests/features/ops/`, vitest + MSW):

- Danh sách rỗng ⇒ màn rỗng, không phải thông báo lỗi.
- Bấm một hàng ⇒ điều hướng `/convos/$phone` đúng số.
- Một lượt có `role` lạ hoặc `meta` méo ⇒ các lượt còn lại vẫn render (cổng chống
  vỡ màn vì dữ liệu do hệ khác ghi).
- `ended_at` NULL ⇒ không có chuỗi `0:00` nào trên màn.
- Search param sống sót qua reload — **kiểm tay** (Task 7 điểm 9 của kế hoạch), không
  phải test: nó cần router thật + reload thật, mà `vitest` dựng component ngoài
  router thì không tái hiện được. Ghi rõ ở đây để không ai đi tìm một test không có.

---

## 8. Ngoài phạm vi

- Tiếp quản hội thoại, nhắn cho khách (`convos.handle`) — chưa có đường ghi.
- Tạo/sửa lịch hẹn từ màn này — thuộc màn `appts`.
- Phân biệt kênh chat/voice, đếm "đang chờ người thật", thời lượng cuộc gọi:
  prototype có, **dữ liệu không có**. `conversations` không mang cột kênh nào.
  Dựng chúng bây giờ là bịa số.
- Badge số trên nav `convos` (`badge.count` đang `null`) — cần định nghĩa "cần
  người xử lý", mà định nghĩa đó chưa có dữ liệu đỡ.
- Xuất transcript ra tệp.
