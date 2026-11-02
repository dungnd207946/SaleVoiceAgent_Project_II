/**
 * Tooltip PRIMITIVE dùng chung trong `features/ops` — tách khỏi `BieuDoNgay.tsx`
 * khi `TheKienThuc.tsx` (ô ⑤) trở thành người dùng THỨ HAI (2026-08-14, sửa
 * lỗi ô ⑤ không có tooltip khi rê chuột vào từng hàng, đợt review tooltip ô ①
 * trước đó đã bỏ sót ô này).
 *
 * Đặt ở `features/ops/components/`, KHÔNG phải `components/ui/`: luật ranh
 * giới của repo dành `components/ui/` cho thứ HAI MODULE KHÁC NHAU dùng chung
 * (xem docstring `components/ui/ChipKenh.tsx`) — ở đây mới có một module
 * (`ops`) dùng. Đưa lên `ui/` đúng ngày có người dùng thứ hai THẬT (module
 * khác `ops`).
 *
 * Hành vi/hình thức PORT NGUYÊN từ bản gốc trong `BieuDoNgay.tsx` (chính nó
 * PORT từ demo `moTip`/`dongTip`/`gan`):
 *   · `position: fixed` (không `absolute`): ô gọi tooltip nằm trong thẻ lưới
 *     `overflow-hidden`, `fixed` không bị cắt bởi `overflow` của tổ tiên.
 *   · kẹp theo bề rộng TRẦN (`RONG_TIP`), không đo DOM — jsdom luôn trả 0.
 *   · dưới `NGUONG_LAT` thì lật tooltip xuống DƯỚI con trỏ/tiêu điểm.
 *
 * ⚠️ **PORTAL RA `document.body` (round fix 2026-08-14, lần hai) — KHÔNG gỡ.**
 * `position: fixed` chỉ neo vào VIEWPORT khi không tổ tiên nào có `transform`/
 * `filter`/`contain`/`backdrop-filter`. Bốn ô bấm được của màn Tổng quan mang
 * `O_BAM_DUOC` (`TongQuanScreen.tsx`), trong đó có **`hover:-translate-y-0.5`**
 * — tức ĐÚNG lúc người dùng rê chuột vào để đọc tooltip thì thẻ cha mọc một
 * `transform`. Ba hậu quả cùng lúc, và cả ba đều đã đo được trên trình duyệt:
 *   · thẻ thành CONTAINING BLOCK mới ⇒ `left`/`top` (đang là toạ độ VIEWPORT
 *     từ `clientX`/`clientY`) bị đọc lại thành toạ độ so với góc thẻ ⇒ tooltip
 *     nhảy đi xa con trỏ đúng bằng khoảng cách từ mép màn tới góc thẻ;
 *   · thẻ thành STACKING CONTEXT mới ⇒ `z-index` của tooltip chỉ còn so bì
 *     TRONG thẻ, nên các ô lưới đứng sau trong DOM vẽ ĐÈ lên nó;
 *   · thẻ mang `overflow-hidden` (bắt buộc, xem `TongQuanScreen`) và tooltip
 *     giờ là con của một containing block bên trong thẻ ⇒ bị CẮT. Ở ô ⑤ một
 *     hàng chỉ cao ~35px còn tooltip cao ~100px, nên nó bị cắt SẠCH — đó là
 *     lý do ô ⑤ "đã sửa rồi mà vẫn không thấy tooltip".
 * Portal ra `<body>` gỡ cả ba: tooltip lại là con của root stacking context,
 * `fixed` lại neo vào viewport, và không tổ tiên nào cắt nó nữa. Docstring cũ
 * ở `BieuDoNgay.tsx` từng khẳng định "không tổ tiên nào của ô này có
 * `transform`" — câu đó ĐÚNG cho tới khi `O_BAM_DUOC` ra đời cùng ngày.
 *
 * State (`useTip`) đứng ở file riêng `./useTip.ts` — `react-refresh/
 * only-export-components` không cho file này export vừa component vừa hook.
 */
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** Bề rộng TRẦN của tooltip (`max-w`) — dùng để kẹp vào viewport mà không
 *  phải đo DOM. Kẹp theo trần nên ở sát mép màn hình tooltip lùi vào xa hơn
 *  mức cần thiết một chút; đổi lại nó KHÔNG BAO GIỜ tràn ra ngoài, kể cả
 *  trong jsdom nơi mọi phép đo đều trả 0. */
export const RONG_TIP = 240
/** Dưới ngưỡng này thì lật tooltip xuống DƯỚI con trỏ — cùng phép của demo. */
export const NGUONG_LAT = 150

/** Hộp tooltip đã định vị + kẹp/lật — PORT nguyên phần khung từ `Tip` cũ của
 *  `BieuDoNgay.tsx`. Nội dung bên trong do người gọi tự dựng (mỗi người dùng
 *  một hình dạng nội dung khác nhau: ngày/kênh cho ô ①, mục kho cho ô ⑤). */
export function HopTip({
  x,
  y,
  testId = 'tip',
  children,
}: {
  readonly x: number
  readonly y: number
  readonly testId?: string
  readonly children: ReactNode
}) {
  const rong = typeof window === 'undefined' ? RONG_TIP * 3 : window.innerWidth
  const nua = RONG_TIP / 2
  // Kẹp theo bề rộng TRẦN. `Math.max` đứng ngoài để khi viewport hẹp hơn cả
  // tooltip thì nó dính mép trái chứ không nhảy sang phải.
  const trai = Math.max(nua + 8, Math.min(x, rong - nua - 8))
  const lat = y < NGUONG_LAT

  const hop = (
    <div
      data-testid={testId}
      role="status"
      aria-live="off"
      // `z-[99]` là số của demo (`#tip{z-index:99}`), KHÔNG phải `z-50` cũ:
      // sau khi portal ra `<body>` thì tooltip so bì với MỌI lớp nổi của
      // portal, trong đó `z-70` là hộp thoại (`TaoKhoaDialog`) — một tooltip
      // chui xuống dưới hộp thoại là đúng lớp lỗi vừa sửa, chỉ đổi thủ phạm.
      className="pointer-events-none fixed z-[99] max-w-[240px] rounded-md bg-panel px-[11px] py-[9px] text-[12px] leading-[1.45] text-n1 shadow-noi"
      style={{
        left: trai,
        top: lat ? y + 20 : y - 14,
        transform: lat ? 'translate(-50%, 0)' : 'translate(-50%, -100%)',
      }}
    >
      {children}
    </div>
  )

  // `typeof document === 'undefined'` là khiên cho môi trường không có DOM
  // (không phải SSR — repo là SPA thuần — mà là bài test nào render component
  // ngoài jsdom). Trả thẳng hộp thay vì ném: một tooltip render sai chỗ vẫn
  // hơn một màn trắng.
  return typeof document === 'undefined' ? hop : createPortal(hop, document.body)
}

/** Một dòng «nhãn — giá trị» trong tooltip, chấm màu TUỲ CHỌN: ô ① luôn có
 *  (mỗi kênh một sắc), ô ③/⑤ không có (các dòng ở đó không phải một chuỗi
 *  phân loại theo màu).
 *
 *  `gia` là ReactNode ĐÃ ĐỊNH DẠNG, không phải `number` như bản đầu: ô ③ có
 *  một dòng mang PHẦN TRĂM một chữ số thập phân (`57,9%`) chứ không phải một
 *  phép đếm, và `so()` (nhóm hàng nghìn, không lấy phần lẻ) làm tròn nó thành
 *  `58`. Để người gọi tự chọn `so`/`soLe1`/`soLe2` là chỗ duy nhất biết đại
 *  lượng của mình là gì. */
export function DongTip({
  mau,
  ten,
  gia,
}: {
  readonly mau?: string
  readonly ten: string
  readonly gia: ReactNode
}) {
  return (
    <div className="flex items-center gap-2 leading-[1.7] whitespace-nowrap">
      {mau && <i className="size-2 flex-none rounded-full" style={{ background: mau }} />}
      <span className="text-panel-muted">{ten}</span>
      <b className="ml-auto font-mono font-medium">{gia}</b>
    </div>
  )
}

/** Đoạn chú thích chân tooltip — PORT từ `.n` của demo (`#tip .n`): chữ
 *  thường (không nowrap), có kẻ trên tách khỏi các dòng số phía trên. */
export function GhiChuTip({ children }: { readonly children: ReactNode }) {
  return (
    <div className="mt-1.5 border-t border-panel-line pt-1.5 text-nhan text-panel-muted">
      {children}
    </div>
  )
}
