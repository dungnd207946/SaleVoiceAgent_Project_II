# Lightbox xem ảnh cho card media — màn Thử agent

**Ngày:** 2026-08-11
**Phạm vi:** component `TheMedia` trong `src/features/platform/components/ThuAgentScreen.tsx` — dùng chung cho cả tab Chat (`BongBong`) và tab Voice (`BongBongGiongNoi`).
**Không đụng tới:** `chatGateway.ts`, `giongNoi.ts` — dữ liệu media (`Media`/`MucMedia`, `docMediaTuKetQua`) đã đúng từ trước (xem spec/Change Log 2026-08-11 "Tab Chat render card ảnh/video").

## Vấn đề

Card media hiện hiện ảnh quá lớn: card rộng theo bong bóng chat (`max-w-[80%]`), lưới 3 cột, mỗi ảnh gần bằng 1/3 bong bóng. Bấm vào ảnh mở `url` gốc (có thể vài MB) ở tab trình duyệt mới — rời khỏi màn thử để xem một tấm ảnh.

Demo tương tác đã duyệt với người dùng: https://claude.ai/code/artifact/97cd7e67-0722-4358-b4c5-4e3b9cc133a1

## Thiết kế

### 1. Lưới ảnh thu nhỏ

- Card: `max-w-[80%]` → `max-w-[280px]` cố định.
- Lưới: `grid-cols-3` → **`grid-cols-2`** (chốt sau khi xem demo — 2 ảnh/hàng, không phải 3).
- Với card 280px, 2 cột, gap 8px: mỗi ô ~136×136px. Tối đa 6 ảnh ⇒ 3 hàng.
- Video **không đổi vị trí trong lưới** — vẫn nằm chung lưới 2 cột với ảnh, đúng thứ tự `items[]` (doc §4.3: "Duyệt hết `items`, đừng lấy phần tử đầu").

### 2. Ảnh: bấm mở lightbox thay vì tab mới

- Đổi phần tử bọc ảnh từ `<a href={it.url} target="_blank">` sang `<button type="button" onClick={...}>` — không còn điều hướng, chỉ mở lightbox tại chỗ.
- Lightbox hiện **đúng một ảnh vừa bấm**, KHÔNG điều hướng sang ảnh khác trong cùng card (đã hỏi người dùng — chốt không cần mũi tên trái/phải).
- **Tải nâng cấp**: lightbox mở ra hiện `thumb` trước (đã có sẵn trong lưới), đồng thời tải ngầm `url` gốc; tải xong thì thay `src` — đúng gợi ý doc §4.3 ("mở lightbox hiện `thumb` trước rồi nâng cấp `url` chạy nền"). Nếu `thumb` vắng hoặc trùng `url` thì bỏ qua bước nâng cấp (không có gì để tải thêm).
- Đóng bằng: bấm nút × (góc trên-phải, nổi trên ảnh), bấm ra ngoài (backdrop), hoặc phím Esc.
- Đóng xong trả focus lại đúng ảnh vừa mở nó (`button.media-cell`), không rơi về `<body>`.

### 3. Video: giữ nguyên

- Vẫn `<a href="https://www.youtube.com/watch?v=..." target="_blank">`, không đổi hành vi. Không có yêu cầu nào cần lightbox cho video (đã hỏi, người dùng chọn giữ nguyên).

### 4. Style — theo đúng khuôn dialog đã có trong repo

Tham chiếu `TaoKhoaDialog.tsx` (khuôn dialog chuẩn của portal):

| Phần | Class |
|---|---|
| Wrapper | `fixed inset-0 z-70 grid place-items-center px-4` |
| Backdrop | `<button>` phủ `absolute inset-0`, `bg-panel/90` (đậm hơn dialog thường — 45% — vì ảnh cần nổi trên nền tối) |
| Khung ảnh | `relative max-h-full max-w-full` |
| Nút đóng | vòng tròn nổi góc trên-phải, `bg-surface`, icon X (tự vẽ SVG, stroke theo quy ước `1.92` của `icons.tsx`) |
| Ảnh | `max-h-[85vh] max-w-[90vw] rounded-lg object-contain` |
| Caption | `text-white` (nền tối), chỉ hiện khi `it.label` có giá trị |

Không thêm mã màu nào ngoài `theme.css` — `bg-panel` đã có sẵn (`#1a1c20`), chỉ đổi độ mờ.

### 5. Accessibility

- `role="dialog"` + `aria-modal="true"` + `aria-label` (lấy `it.label`, fallback "Xem ảnh").
- Nút đóng có `aria-label` ("Đóng").
- Esc đóng được (đăng ký/gỡ listener theo lifecycle mở/đóng, cùng khuôn `TaoKhoaDialog.tsx`).
- Ảnh trong lưới đổi từ `<a>` sang `<button>` vẫn giữ `aria-label` mô tả ("Xem ảnh: {label}") để không mất ngữ nghĩa khi mất `alt` ẩn trong `<a>`.

### 6. State & lifecycle

State cục bộ trong `TheMedia` (không lift lên `BongBong`/`BongBongGiongNoi`, không đổi props của `TheMedia`):

```ts
const [anhMo, setAnhMo] = useState<MedItemAnh | null>(null)
const [srcHienThi, setSrcHienThi] = useState<string | null>(null)
```

- Bấm ảnh → `setAnhMo(it)`, `setSrcHienThi(it.thumb ?? it.url)`.
- `useEffect` theo `anhMo`: nếu có `thumb` khác `url` thì tạo `new Image()`, gán `src = anhMo.url`, `onload` → `setSrcHienThi(anhMo.url)` (chỉ set nếu `anhMo` vẫn là ảnh đang mở — tránh race khi người dùng đổi ảnh nhanh, dù ca này hiếm vì không có điều hướng trong lightbox).
- Đóng → `setAnhMo(null)`.

### 7. Test

Thêm vào `tests/thu-agent.test.tsx` (cả hai khối Chat và Voice đã có sẵn test cho card media — bổ sung, không thay):

1. Bấm một ảnh trong card → lightbox hiện, `src` ban đầu là `thumb`.
2. (nếu giả lập `Image.onload` được trong jsdom) sau khi "tải" xong, `src` đổi sang `url` gốc.
3. Bấm nút × → lightbox đóng, focus trả về đúng nút ảnh vừa mở.
4. Phím Esc → lightbox đóng.
5. Bấm backdrop → lightbox đóng.
6. Ảnh không có `thumb` (chỉ có `url`) → lightbox hiện thẳng `url`, không có bước nâng cấp.

## Ngoài phạm vi

- Điều hướng ảnh trong lightbox (trái/phải) — chốt không làm.
- Lightbox cho video — chốt giữ nguyên mở tab YouTube.
- Card `booking`/`escalate` — vẫn "còn treo" theo CLAUDE.md, không thuộc spec này.
