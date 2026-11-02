/**
 * Tiêu đề mục dùng CHUNG cho `/billing` (Task 4/5) và `/pricing` (Task 8) — NGOÀI
 * thẻ, `16px sans 600` + một dòng phụ `12,5px`. Trước review 2026-08-20, hai
 * màn tự khai hai bản COPY giống hệt 8 dòng này (docstring `BangGiaScreen.tsx`
 * cũ từng ghi lý do KHÔNG tách — "hai component không cùng chỗ dùng, và bản
 * này chỉ 6 dòng" — lý lẽ đó không còn đứng vững khi bản sao đã lên hai nơi và
 * cùng đổi kiểu chữ mỗi lần chỉnh design token).
 *
 * SỐ MỤC LÀ MỘT Ô RIÊNG (`so`), KHÔNG phải ký tự `①` nhét vào đầu chuỗi tiêu đề
 * (2026-08-21). Ba lý do, xếp theo mức độ đo được:
 *  ① `①②③` là ký tự KHÔNG có trong Be Vietnam Pro — trình duyệt rơi về font hệ
 *    thống cho riêng nó, nên số mục hiện ra một kiểu chữ khác hẳn chữ ngay cạnh,
 *    và lệch baseline. Đó chính là thứ trông "xấu" ở bản trước.
 *  ② Chuỗi `'① Kỳ này'` làm số mục thành một phần của TÊN mục: `getByRole
 *    ('heading', {name: 'Kỳ này'})` trượt, và đọc màn hình đọc "vòng tròn số một
 *    Kỳ này".
 *  ③ Dãy `①②③` chỉ tới `⑳`; số mục là dữ liệu, không phải chữ.
 * Hình ô số PORT từ `docs/design/demo-usage-billing.html` § `.muc-so`: 20×20, viền
 * `border-strong`, mono 11px — cùng thang chữ mono của mọi con số trong portal.
 *
 * `phu` NẰM CÙNG HÀNG với tiêu đề (không xuống dòng): xếp hai dòng thì mỗi mục
 * ăn thêm ~18px, ba mục là 54px — đúng khoản đẩy biểu đồ mục ② xuống dưới nếp
 * gấp (đo ở bản demo).
 */
export function TieuDeMuc({
  so,
  tieuDe,
  phu,
}: {
  /** Số thứ tự mục. Bỏ trống ⇒ không có ô số (mục đứng một mình). */
  readonly so?: number | undefined
  readonly tieuDe: string
  readonly phu: string
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 px-0.5 pb-0.5">
      {so !== undefined && (
        <span
          aria-hidden
          className="grid size-5 flex-none place-items-center rounded-sm border border-border-strong font-mono text-nhan font-medium text-muted-2"
        >
          {so}
        </span>
      )}
      <div className="flex min-w-0 flex-wrap items-baseline gap-x-2.5">
        <h2 className="text-muc font-semibold tracking-[-0.012em] text-fg">{tieuDe}</h2>
        <p className="text-phu text-muted">{phu}</p>
      </div>
    </div>
  )
}
