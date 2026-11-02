# Báo cáo — Ô Tổng quan bấm được + hiệu ứng rê chuột

## Đã làm

Bốn ô ①②③⑤ của màn `/dashboard` giờ bấm được, đi đúng bốn đích đã chốt:
Hội thoại → `/convos` (link «Xem tất cả →» đã có sẵn, thêm stretched-link vào
chính nó) · Chuyển sale → `/chuyen-sale` («Xem phiên →») · Khách đánh giá →
`/quality` («Xem đánh giá →») · Kiến thức → `/projects` («Quản lý →», đúng
chữ demo `public/demo-tong-quan.html` khối ⑤). Ô ⑥ Usage & Billing giữ
nguyên, không bấm được, không hiệu ứng — vì `/usage`/`/billing` là
`mvp: 'deferred'`.

Kỹ thuật: **stretched-link**, không bọc `<Link>` quanh cả ô (tránh `<a>` lồng
`<a>` ở ô ①, và tránh nuốt mất phần tử tương tác bên trong). Mỗi ô mang
`O_BAM_DUOC` (`relative` + bốn lớp hiệu ứng), link «đầu ô» mang
`after:absolute after:inset-0` để vùng bấm nở ra trọn ô. Phần tử cần giữ
tương tác riêng được nâng `relative z-10` để vẽ TRÊN lớp phủ:

- Ô ①: vùng vẽ biểu đồ (`bieu-do-ve`, thêm `data-testid` để test/kiểm được)
  + hàng nhãn ngày, trong `BieuDoNgay.tsx` — bấm vào đó để XEM một ngày,
  KHÔNG điều hướng.
- Ô ⑤: sáu hàng của `TheKienThuc.tsx` đổi hẳn thành `<Link to="/projects">`
  (bỏ `tabIndex={0}` viết tay — `<Link>` tự tabbable), giữ nguyên
  `onMouseMove`/`onFocus`/`onBlur` cho tooltip.

Bốn lớp hiệu ứng (`O_BAM_DUOC` trong `TongQuanScreen.tsx`): nâng + viền
(`hover:-translate-y-0.5` + `border-strong` + `shadow-noi-nhe`, token mới) ·
nhấn xuống (`active:` trả lại) · bàn phím (`focus-within:border-ac`) ·
`select-none` (chống bôi đen chữ khi kéo chuột qua ô-là-nút) + `motion-reduce:`
tắt transform/transition. Mũi tên `MuiTen` trượt vào bằng `group-hover`.

Token mới `--shadow-noi-nhe: 0 2px 10px rgba(20, 22, 26, 0.1)` trong
`src/styles/theme.css`, kèm comment phân biệt với `--shadow-noi` (nổi hẳn vs
nhấc lên).

## TDD / Test

- `tests/overview-kien-thuc.test.tsx`: viết lại để boot qua router tối thiểu
  (`createRootRoute` + `createMemoryHistory`, khuôn `quality-review-card.test.tsx`)
  vì `Hang` giờ là `<Link>`, cần router context. Thêm 1 test mới: hàng là
  link thật trỏ `/projects`. Bỏ assertion `tabIndex` cũ (không còn viết tay),
  thay bằng kiểm `tagName === 'A'` + `href`.
- `tests/overview-man.test.tsx`: thêm 5 test — ba ô ②③⑤ có link đúng đích,
  ô ⑥ KHÔNG có link nào và không mang lớp hiệu ứng hover, và một test hồi quy
  cấu trúc: vùng vẽ biểu đồ (`bieu-do-ve`) + hàng nhãn ngày (`nhan-ngay-0`)
  KHÔNG có `<a>` tổ tiên nào (`closest('a')` === null) — bấm vào đó không
  ném lỗi. jsdom không tính layout/z-index nên không mô phỏng được "bấm
  xuyên qua lớp phủ" bằng toạ độ thật; phép kiểm cấu trúc này là bằng chứng
  thật hơn — không có `<a>` bao ngoài thì không cách nào điều hướng được, bất
  kể CSS đúng hay sai.

## Ba cổng

- `npm test`: **50 file · 647 passed · 6 skipped · 0 failed** (baseline 641 +
  6 test mới = 647, khớp).
- `npm run build` (`tsc -b && vite build`, typecheck THẬT của repo): xanh.
- `npm run lint`: xanh, không cảnh báo.
- `npx prettier --check` trên các file đã sửa: xanh.

## Kiểm bằng mắt

Dev server chạy tạm với `VITE_MSW=1` (file `.env` của máy để `VITE_MSW=0` —
dùng backend thật, không đăng nhập được trong phiên này nên override qua env
var lúc chạy, KHÔNG sửa `.env`). `chromium-cli` không có sẵn trên máy này nên
dùng trực tiếp Playwright (đã cài, có Chromium) theo đúng hướng dẫn dự phòng
của skill `run`.

Ảnh `docs/superpowers/anh-man-tong-quan/o-hover.png` (1440×900, chuột đang rê
vào ô ② Chuyển sale):

- **Ô ② nhấc lên + viền đậm rõ nhưng không thô** — so trực tiếp cạnh ô ①
  (nghỉ) trong ảnh crop kiểm thêm: viền ô ② rõ hẳn (`border-strong`) trong
  khi viền ô ① gần như vô hình (`border` nhạt mặc định).
- **Mũi tên đã trượt vào** — "Xem phiên →" hiện đủ mũi tên màu accent, không
  bị cắt/ẩn.
- **Ô ⑥ Usage & Billing KHÔNG đổi gì** — vẫn hai badge "Chưa có", không viền
  đậm, không link nào lộ ra khi rê chuột qua vùng đó (chuột đang ở ô ②).
- **Màn KHÔNG cuộn** — `scrollHeight === clientHeight === 900`,
  `scrollWidth === clientWidth === 1440` (đo qua `page.evaluate`).

Kiểm thêm bàn phím (không phải ảnh bắt buộc, chụp thêm để tự tin): Tab focus
vào link «Xem đánh giá» của ô ③ → cả ô lên viền accent đậm
(`focus-within:border-ac`) + link tự có viền `:focus-visible` toàn cục của
repo. Đúng lớp thứ tư của bốn lớp hiệu ứng.

Tắt dev server (`kill` tiến trình lắng nghe cổng) sau khi chụp xong.

## Quyết định tự ra (không có trong sáu quyết định đã chốt)

1. **`data-testid="bieu-do-ve"` mới trên vùng bám chuột của `BieuDoNgay.tsx`.**
   Cần một cách trỏ tới đúng phần tử đó từ test mà không phụ thuộc `role="img"`
   của SVG bên trong — SVG đó chỉ vẽ khi `W > 0 && H > 0` và jsdom không có
   `ResizeObserver` thật nên luôn trả kích thước 0, tức SVG không bao giờ vào
   DOM trong test. Vùng bám chuột (div bọc ngoài) thì luôn render.
2. **Không sửa `.env`** để bật MSW cho lần kiểm bằng mắt — máy dev này đã đặt
   `VITE_MSW=0` (dùng backend thật) từ trước; override qua biến môi trường
   lúc chạy `npm run dev` thay vì đổi file, để không đụng cấu hình cục bộ của
   máy.
3. **Dùng Playwright thay `chromium-cli`** — công cụ đó không có trên máy
   này; đi theo đúng nhánh dự phòng mà skill `run` đã ghi sẵn.

## Fix tiếp — hồi quy màu accent ở sáu hàng ô ⑤ (2026-08-14, vòng 2)

Coordinator mở ảnh `o-hover.png` gốc, phát hiện sáu hàng «Dự án»/«Phân khu»/
«Căn / sản phẩm»/«Tài liệu dự án»/«Tệp tra cứu»/«Hồ sơ đủ trường» đều lên
**xanh accent** — tác dụng phụ của việc đổi hàng thành `<Link>`: luật toàn
cục `a { color: var(--color-ac) }` (`theme.css:290-293`) ăn vào mọi `<a>`,
kể cả hàng dữ liệu này. Trước đó (còn là `<div>`) chữ vẫn trung tính.

**Sửa:** thêm `text-fg` vào `className` của `<Link>` hàng
(`TheKienThuc.tsx::Hang`), cạnh `no-underline` đã có. Bốn link «đầu ô» (Xem
tất cả/Xem phiên/Xem đánh giá/Quản lý) **giữ nguyên accent** — không đụng.

**Kiểm phần tử con:** dùng Playwright đọc `getComputedStyle` thật trên
Chromium (jsdom trong `vitest` không vẽ CSS — cùng lý do `chip-kenh-mau.test.ts`
đã ghi, nên không kiểm màu qua `vitest` được):

```
cột trong hàng «Dự án»: [Icon] "" → rgb(20,22,26)=fg | "Dự án" → rgb(20,22,26)=fg
| "đã phát hành" → rgb(102,108,118)=muted-2 (không đổi) | "8 / 12" → muted-2
(không đổi) | [Thước, không chữ] | "67%" → rgb(20,22,26)=fg | "4 chưa đọc
được" → rgb(138,92,13)=badge-warn-fg (không đổi)
```

Không chỗ nào khác bị ăn theo — mọi span khác đã tự khai `text-muted-2`/
`text-badge-warn-fg` nên có specificity riêng, không bị `color` kế thừa từ
`<a>` đè lên. Kiểm luôn **hover**: `text-fg` không chỉ thắng ở trạng thái
nghỉ mà còn thắng cả `a:hover { color: var(--color-acd) }` — đo được cả rest
lẫn hover cùng trả `rgb(20, 22, 26)` (= `--color-fg`), không lệch sang
`--color-ac`/`--color-acd`. Lý do: Tailwind v4 phát utility trong cascade
layer `utilities`, đứng SAU layer `base` (nơi luật `a`/`a:hover` toàn cục
sống) — layer sau luôn thắng layer trước bất kể specificity, nên `.text-fg`
thắng cả `a` lẫn `a:hover` mà không cần thêm `hover:text-fg`. Đã đo lại hiệu
ứng hover của hàng vẫn còn nguyên: viền lên `border-strong`
(`rgb(222,217,208)`) + nền `acs-manh` (`rgb(220,236,230)`), chỉ có MÀU CHỮ
là khoá lại ở `fg`.

**Test canh mới** (`tests/overview-kien-thuc.test.tsx`): kiểm
`hang.className` khớp `/\btext-fg\b/`. Đây là kiểm CLASS, không phải
computed style — vì jsdom không render CSS thật nên một bài `getComputedStyle`
trong `vitest` sẽ luôn trả giá trị rỗng/mặc định bất kể `text-fg` có mặt hay
không (không bắt được gì, dương tính giả). Bài kiểm class THÌ bắt được thật:
gỡ `text-fg` khỏi `className` là bài này đỏ ngay lập tức — đã tự kiểm ngược
bằng cách bỏ tạm chữ đó và chạy lại, thấy đỏ đúng như kỳ vọng trước khi để
lại bản đã sửa.

### Ba cổng (vòng 2)

- `npm test`: **50 file · 648 passed · 6 skipped · 0 failed** (647 + 1 test
  mới = 648, khớp).
- `npm run build`: xanh.
- `npm run lint`: xanh.
- `npx prettier --check` trên 2 file đã sửa: xanh.

### Ảnh chụp lại

`o-hover.png` chụp lại (chuột vẫn rê vào ô ② Chuyển sale, cùng khuôn ảnh
trước) — xác nhận: sáu hàng ô ⑤ giờ chữ đen trung tính (`fg`), «Quản lý →»
ở đầu ô vẫn xanh accent, hiệu ứng hover ô ② (nhấc lên + viền đậm + mũi tên
trượt vào) không đổi, ô ⑥ không đổi gì, màn không cuộn
(`scrollHeight===clientHeight===900`).

Dev server chạy lại tạm với `VITE_MSW=1` (không sửa `.env`), tắt ngay sau
khi chụp xong.

## Fix tiếp — review round 3 (2026-08-14): test hồi quy ô ① không chứng minh được điều nó tuyên bố

Review trả Approved kèm 1 Important + 4 Minor (2 sửa, 2 bỏ qua theo chỉ đạo
coordinator).

### [Important] Đóng vòng bằng thực nghiệm — ba con số đo được

Vấn đề: bài `'vùng vẽ biểu đồ + hàng nhãn ngày ô ① KHÔNG nằm trong link nào'`
kiểm `closest('a') === null` rồi `userEvent.click` — đây là bằng chứng CẤU
TRÚC, không phải bằng chứng HÀNH VI. `userEvent.click(el)` trong jsdom gọi
THẲNG handler đã gắn trên `el`, không hit-test theo toạ độ như trình duyệt
thật. Nếu `z-10` sai (thiếu, bị ghi đè, hoặc một ancestor vô tình dựng
stacking context mới nhốt nó xuống dưới `::after`) thì trình duyệt thật NUỐT
cú bấm trong khi bài test này vẫn xanh — đúng ca rủi ro trọng tâm của quyết
định #3 (stretched-link).

**Đóng vòng bằng Playwright trên Chromium thật** (script
`click-through.js`, `dev` chạy `VITE_MSW=1`, `page.mouse.click(x, y)` theo
TOẠ ĐỘ — không theo element handle, để đúng là hit-test thật): ba phép đo,
đọc `page.url()` ngay sau mỗi cú bấm.

| # | Bấm vào đâu | URL trước | URL sau | Kỳ vọng |
|---|---|---|---|---|
| 1 | Toạ độ TRONG vùng vẽ biểu đồ (`bieu-do-ve`, giữa ô) | `/dashboard` | `/dashboard` | KHÔNG đổi — đo ĐÚNG |
| 2 | Toạ độ TRONG hàng nhãn ngày (`nhan-ngay-0`, giữa nút) | `/dashboard` | `/dashboard` | KHÔNG đổi — đo ĐÚNG |
| 3 | **Đối chứng dương** — toạ độ TRỐNG của ô ① (padding góc trên-trái, cách mép 6px, trước hàng tiêu đề — không trúng chữ/link/vùng vẽ/nhãn ngày) | `/dashboard` | **`/convos`** | ĐÃ đổi — đo ĐÚNG |

Ba con số đo được (log thật, không phải suy diễn):
```json
{
  "veBieuDo": "http://localhost:5274/dashboard",
  "nhanNgay": "http://localhost:5274/dashboard",
  "vungTrong": "http://localhost:5274/convos"
}
```

Đối chứng dương (#3) là phần bắt buộc: không có nó thì "#1/#2 không đổi URL"
cũng giải thích được bằng một giả thuyết khác hoàn toàn — "cả ô không bấm
được gì" (ví dụ `after:absolute` thiếu, hoặc link «Xem tất cả» gãy) — và kết
luận "z-10 chặn đúng chỗ" sẽ là một suy luận sai dựa trên bằng chứng đúng
tình cờ. #3 loại trừ giả thuyết đó: ô ① CÓ bấm được (điều hướng đúng
`/convos` khi bấm ngoài hai vùng loại trừ), và #1/#2 không đổi KHÔNG PHẢI vì
cả ô liệt, mà vì đúng hai vùng đó được `z-10` che chắn.

### Bài jsdom bắt được việc GỠ `z-10`

jsdom không hit-test được theo toạ độ (lý do thí nghiệm trên phải làm bằng
Playwright), nhưng kiểm được SỰ HIỆN DIỆN của lớp. Thêm hai assert vào bài
cũ (`ve.classList.contains('z-10')` và `nhanNgay.parentElement?.classList
.contains('z-10')` — lớp `z-10` nằm ở hàng bọc ngoài các nút nhãn ngày, không
phải từng nút). Đã tự kiểm ngược: gỡ tạm `z-10` khỏi `bieu-do-ve`
(`BieuDoNgay.tsx`) → chạy `vitest` → đỏ đúng dòng assert mới → phục hồi →
xanh lại.

**Sửa lại comment cho trung thực** (yêu cầu review): bài test giờ nói rõ nó
chỉ canh được (1) cấu trúc DOM và (2) sự hiện diện của lớp `z-10` — hành vi
"bấm xuyên lớp phủ" CHỈ kiểm được trong trình duyệt thật, và ghi lại chính
xác đã kiểm ngày nào (2026-08-14), bằng công cụ gì (Playwright), và kết quả
ba con số ở trên — để người đọc sau không cần lặp lại thí nghiệm mà vẫn biết
nó đã được làm.

### [Minor] Nhận, đã sửa — bài ô ⑥ so với chính hằng `O_BAM_DUOC`

Bài cũ chỉ soi 2/4 lớp (`hover:-translate-y-0.5`, `hover:shadow-noi-nhe`) —
đổi tên lớp ở component thì bài test vẫn xanh giả. Export `O_BAM_DUOC` từ
`TongQuanScreen.tsx`, import vào test, tách theo khoảng trắng rồi assert
`o.classList.contains(lop)` là `false` cho MỌI lớp trong hằng đó. Đã tự kiểm
ngược: tạm ghép `O_BAM_DUOC` vào `className` của `OUsage` → chạy `vitest` →
đỏ → gỡ lại → xanh.

### Hai Minor BỎ QUA theo chỉ đạo coordinator (không làm)

- Siết regex `\btext-fg\b` thành so khớp danh sách class cứng.
- Mở rộng `aria-label` bốn link đầu ô (chữ hiện tại là chữ demo đã duyệt;
  đổi nhãn khả truy cập là quyết định riêng, không gộp vào việc này).

### Ba cổng (round 3)

- `npm test`: **50 file · 648 passed · 6 skipped · 0 failed** (không đổi số —
  round này sửa/siết assertion trong bài đã có, không thêm bài mới).
- `npm run build`: xanh.
- `npm run lint`: xanh.
- `npx prettier --check` trên 2 file đã sửa: xanh.

Dev server (`VITE_MSW=1`, tạm cho thí nghiệm Playwright) đã tắt ngay sau khi
đo xong ba con số.
