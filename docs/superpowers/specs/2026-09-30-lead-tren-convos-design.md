# Lead stage · điểm · đối tượng trên `/convos` — thiết kế

Ngày: 2026-09-30 · Phạm vi: `odyssey-portal-backend` (module `ops`) + `odyssey-portal-frontend` (module `ops`)
Bản vẽ: [`public/demo-lead-convos.html`](../../../public/demo-lead-convos.html) (mở `http://localhost:5273/demo-lead-convos.html`)

## 1. Mục tiêu

Người vận hành nhìn `/convos` là biết khách nào đang ở bậc nào của phễu bán hàng, và lọc được ra
một nhóm, ví dụ «mọi khách SQL». Vào một khách thì thấy được stage của từng phiên, tức thấy khách
đi lên hay đi lùi qua các lần nói chuyện.

**Người dùng chốt:**
- `lead_stage` là phễu TĂNG DẦN: `lead` → `mql` → `sql` → `hen_gap`.
- Danh sách khách: hiện stage mới nhất + **lọc** theo stage (không sắp theo điểm).
- `lead_score` hiện **số thô**, không thang, không tô nấc nóng/lạnh. Dữ liệu thật chạy 30–120 và
  KHÔNG gắn chặt với stage (một `lead` được 100, một `sql` chỉ 70), nên không suy được thang nào.
- UI phải đẹp — bản vẽ ở trên là chuẩn hình.

**Ngoài phạm vi:** `reason_kind` · `lead_signals` · sắp theo điểm · số đếm trên từng chip lọc ·
sửa stage bằng tay.

## 2. Luật dữ liệu

Nguồn: năm cột thêm ở `tenant_data.escalations` (migration `0968`). Agent ghi; Portal chỉ đọc.
Chỉ đọc ba cột `lead_stage` · `lead_score` · `audience`.

- **Lead của một PHIÊN** = hàng `escalations` MỚI NHẤT (`created_at DESC, id DESC`) của phiên đó mà
  `lead_stage IS NOT NULL`. Phiên không có hàng nào như vậy ⇒ không có lead. Lấy CẢ BA trường từ
  CÙNG một hàng — không ghép stage của hàng này với điểm của hàng khác.
- **Lead của một KHÁCH** = lead của PHIÊN mới nhất (theo `COALESCE(started_at, created_at) DESC` — đúng
  thứ tự cột phiên đang hiện) mà CÓ lead. Định nghĩa theo phiên chứ không theo `escalations.created_at`
  trên mọi phiên, để lead ở danh sách, ô «Lead hiện tại» và phiên trên cùng có chip ở trang chi tiết
  LUÔN là cùng một hàng — theo cách dựng, không nhờ may mắn. Khách nối với escalation qua `escalations.session_id = conversations.session_id`, rồi gom
  theo `COALESCE(conversations.phone, '')` — đúng khoá gom nhóm `/convos` đang dùng.
  **Không** dùng `escalations.phone` (đó là ảnh chụp lúc chuyển, có thể lệch).
- «Mới nhất» là THEO THỜI GIAN, không phải bậc cao nhất từng đạt: khách SQL rồi sau đó lại hỏi
  kiểu Lead thì hiện Lead. Phiên mới nhất của khách không chuyển sale ⇒ vẫn hiện lead gần nhất.
- `audience` hoặc `lead_score` có thể NULL dù `lead_stage` có — hiện phần có, bỏ phần thiếu.
- Giá trị stage LẠ (agent thêm bậc mới) vẫn đi qua API nguyên văn; FE hiện nó bằng chip trung tính
  (sắc `badge-neutral`), và nó không có trong bộ lọc.

## 3. API (backend, module `ops`)

JSON camelCase như phần còn lại của `ops`.

### `GET /api/v1/convos/khach`
- `KhachOut` thêm `leadStage: str | None`, `leadScore: int | None`, `audience: str | None` (lead của KHÁCH).
- Tham số mới `lead_stage`: `lead | mql | sql | hen_gap | none` (vắng = không lọc). `none` = khách
  không có lead nào. Giá trị khác ⇒ **422** (khai `Literal`, không lọc im lặng).
- Lọc ÁP TRƯỚC `LIMIT/OFFSET`, và `dem_tong` áp CÙNG điều kiện — `tongKhach`/`tongPhien` và thanh
  phân trang phải nói về tập đã lọc.
- Cài: truy vấn gom khách hiện tại thành CTE; lead của khách lấy bằng `LEFT JOIN LATERAL`
  (`escalations e JOIN conversations c ON c.tenant_id = e.tenant_id AND c.session_id = e.session_id
  WHERE COALESCE(c.phone,'') = t.phone AND e.lead_stage IS NOT NULL
  ORDER BY COALESCE(c.started_at, c.created_at) DESC, e.created_at DESC, e.id DESC LIMIT 1`) — khoá sắp
  đầu là thời điểm PHIÊN, khoá sau chọn hàng mới nhất TRONG phiên (§2).
  Lọc bằng `WHERE` trên kết quả lateral. Một hàm dựng SQL dùng chung cho `liet_ke_khach` và `dem_tong`
  để hai chỗ không lệch điều kiện.

### `GET /api/v1/convos/khach/{phone}/phien`
- `PhienOut` thêm ba trường cùng tên — lead của PHIÊN (lateral theo `session_id`).

### `GET /api/v1/convos/phien/{session_id}`
- Dùng lại `PhienOut` nên tự có ba trường; `doc_phien` thêm cùng lateral.

## 4. Giao diện (frontend)

### 4.1 Chip stage — component dùng chung `ChipStage`

`features/ops/components/ChipStage.tsx`. Pill cao 22px, `rounded-full`, viền 1px, 11.5px/600,
**chỉ nhãn** (người dùng chốt: bỏ chấm phễu). Nhãn tự nói bậc; màu ấm dần theo bậc củng cố.

| stage | nhãn | nền | chữ | viền |
|---|---|---|---|---|
| `lead` | Lead | `#f0efec` | `#5f656e` | `#8a857b` |
| `mql` | MQL | `#fbf1dc` | `#7a5410` | `#a57c2c` |
| `sql` | SQL | `#fde6d4` | `#9a3f0c` | `#c46a33` |
| `hen_gap` | Hẹn gặp | `#b4501a` (đặc) | `#ffffff` | `#b4501a` |

- Token mới ở `theme.css`: `--color-lead-{1..4}-{bg,fg,vien}` (luật 1: không mã màu ngoài `theme.css`).
- **Họ màu ẤM** có chủ ý: trên cùng màn teal đã là «Đã chuyển sales», xanh dương là Chat, tím là Voice.
- Đã đo: chữ/nền ≥ 5.11 · viền/surface ≥ 3.64 · **viền/`acs` ≥ 3.20** (nền hàng phiên đang chọn —
  đúng chỗ chip kênh từng tàng hình, CLAUDE.md 2026-08-13) · viền/nền chip ≥ 3.19. Có cổng test
  số học như `chip-kenh-mau.test.ts`.
- Nhãn + thứ tự + bậc nằm MỘT chỗ: `features/ops/lead.ts` (`BAC_LEAD`, `nhanDoiTuong`).
- Đối tượng: `end_user` → «Khách mua», `broker` → «Môi giới», giá trị lạ hiện nguyên văn.
- Điểm: font mono 12.5px `text-fg` + chữ «điểm» 11.5px `muted-2`.

### 4.2 `/convos` — danh sách khách

- **Cột Lead RIÊNG** rộng 158px, giữa cột tóm tắt và cột thời gian, cùng kẻ dọc `border-border-soft`
  như hai cột kia. Dòng 1: `ChipStage`. Dòng 2: `90 điểm · Khách mua`. Cột riêng vì việc chính là
  DÒ MẮT DỌC «ai đang nóng» — chen chip vào hàng chip dự án thì mỗi hàng nằm một chỗ khác nhau.
- Khách không có lead: chữ mờ «Chưa phân loại» 12px `muted-2`, không chip.
- Mobile (<768): cột Lead rơi xuống cùng hàng chip dưới tóm tắt (`max-md:` thêm vào, desktop không
  đổi class nào — luật shell responsive).
- **Bộ lọc stage = MỘT ô 36px, bấm mới mở menu** (người dùng chốt: bày sáu nút ra thì chiếm chỗ).
  Ô: nhãn «Stage» `muted-2` + giá trị đang chọn + mũi tên `moXuong` (xoay 180° khi mở). Chưa lọc ⇒
  giá trị là chữ «Tất cả»; đang lọc ⇒ giá trị là CHÍNH `ChipStage` của stage đó (hoặc chữ «Chưa phân
  loại»), và ô đổi viền `ac` + nền `surface` — nhìn thanh lọc là biết danh sách đang bị lọc.
  Mở: viền `ac` + vòng `acs` 3px.
- Menu (`rounded-lg`, viền `border-strong`, bóng nhẹ, rộng 220px): «Tất cả» · kẻ · bốn `ChipStage`
  theo thứ tự phễu · kẻ · «Chưa phân loại». Mục đang chọn nền `acs` + dấu ✓ `ac` ở mép phải.
  `aria-haspopup="menu"` + `aria-expanded` trên nút, mục là `menuitemradio` + `aria-checked`
  (cùng lối menu ngôn ngữ ở `UserMenu`). Đóng bằng: chọn một mục · Esc · bấm ra ngoài; ↑/↓/Enter
  đi được bằng phím. KHÔNG dùng `<select>` gốc: option gốc không vẽ được chip màu, mà chip trong
  menu chính là thứ dạy người dùng màu nào là bậc nào trước khi họ gặp nó trong danh sách.
- Menu render qua **`createPortal` ra `document.body`**, `position: fixed` theo `getBoundingClientRect`
  của nút: tấm nền `KhachList` mang `overflow-hidden`, nên một menu `absolute` bên trong bị CẮT khi danh
  sách ngắn (lọc ra 0 khách ⇒ tấm nền chỉ cao ~200px). Cùng bài học tooltip `HopTip` (CLAUDE.md
  2026-08-14). Menu LẬT LÊN khi phía dưới không đủ chỗ; cuộn trang hoặc đổi cỡ cửa sổ thì đóng menu
  (menu `fixed` không đi theo nút).
- Search param `?stage=lead|mql|sql|hen_gap|none`; mặc định không ghi lên URL. Đổi stage là REPLACE
  + về trang 1 (cùng lệ lọc/cỡ trang hiện có). Giá trị lạ trên URL ⇒ coi như không lọc.
- `LocKhach` thêm `stage`; `danhSachKhach()` gửi `lead_stage`.

### 4.3 `/convos/$phone` — chi tiết khách

- **Ô «Lead hiện tại»** ở mép phải header (nền `n2`, viền `border`, `rounded-lg`): ba ô ngăn bằng
  vạch dọc — «Lead hiện tại» + `ChipStage` · «Điểm» + số mono 20px · «Đối tượng» + chữ 13.5px/500.
  Lấy từ lead của KHÁCH — cùng hàm với danh sách, nên hai màn luôn khớp. Khách không có lead ⇒ không
  hiện ô. Nguồn dữ liệu: lead mới nhất suy từ danh sách phiên đã tải (phiên đầu tiên có `leadStage`
  theo thứ tự mới nhất) — KHÔNG thêm request. Khớp danh sách theo đúng định nghĩa §2, có bài test
  canh hai màn cho cùng một stage.
- **Hàng phiên**: dòng meta cuối (`14 lượt · 6m 12s`) thêm `ChipStage` của CHÍNH phiên đó, căn phải.
  Phiên không có lead ⇒ không chip.
- **Dòng thông tin phiên** (`dong-phien`): sau «N lượt», một vạch ngăn 1×16px rồi `ChipStage` ·
  `90 điểm` · đối tượng của phiên đang xem. Feedback vẫn ở `ml-auto` như cũ.

## 5. Kiểm thử

**Backend** (`tests/modules/ops/`):
- Lead của khách = lead của phiên mới nhất CÓ lead; phiên mới hơn không có lead bị bỏ qua; trong
  một phiên, hàng NULL mới hơn bị bỏ qua.
- Ba trường lấy cùng một hàng.
- `lead_stage=sql` chỉ trả khách có lead mới nhất là SQL (khách từng SQL nay Lead thì KHÔNG trả).
- `lead_stage=none` trả khách không có lead nào.
- `tongKhach`/`tongPhien` khớp tập đã lọc.
- Giá trị lạ ⇒ 422.
- Phiên có nhiều hàng lead ⇒ lấy hàng mới nhất của phiên.
- Cách ly tenant: lead của tenant khác không lọt sang.

**Frontend:**
- `ChipStage`: nhãn + lớp màu theo bậc; stage lạ hiện nguyên văn bằng chip trung tính.
- Cổng số học tương phản bốn bậc (chữ/nền ≥ 4.5, viền/surface, viền/`acs`, viền/nền chip ≥ 3).
- `/convos`: cột Lead hiện đúng; «Chưa phân loại» khi rỗng; mở menu → chọn gửi `lead_stage`, ghi
  `?stage=`, về trang 1, menu đóng, ô hiện chip đã chọn; Esc/bấm ngoài đóng menu; `?stage=xyz` bị bỏ qua.
- `/convos/$phone`: ô Lead hiện tại khớp phiên mới nhất có lead; chip từng phiên; dòng thông tin phiên.
- Fake MSW `ops/msw.ts` phủ đủ bốn bậc + khách không lead + stage lạ, và lọc theo `lead_stage`.
