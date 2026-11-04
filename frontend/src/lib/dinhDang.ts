/**
 * Định dạng SỐ (và ngày giờ, cuối tệp) dùng chung mọi module (chuyển từ `features/ops/` 2026-10-05: `/quality`
 * in số thô «4.33» vì luật ranh giới cấm nó import ruột `ops`). Hàm THUẦN.
 * Tiền/token/giây của `billing` có formatter riêng (`billing/dinh-dang.ts`) — số
 * lớn dạng `1.20M` ở đó là chốt có chủ ý, đừng gộp về đây.
 *
 * Vì sao gom: trước round fix 2026-08-13 hàm `so()` được CHÉP NGUYÊN VĂN ở
 * năm chỗ (`TongQuanScreen` · `TheKienThuc` · `TheDanhGia` · `GaugeNuaCung` ·
 * `BieuDoNgay`) và `new Intl.NumberFormat('vi-VN', { maximumFractionDigits:
 * 1 })` ở ba chỗ. Tám bản sao là tám chỗ phải sửa vào ngày quy ước nhóm hàng
 * nghìn đổi — và bảy chỗ để quên một cái.
 *
 * `toLocaleString` vs `Intl.NumberFormat`: cùng một engine, `so()` giữ dạng
 * ngắn vì nó không cần tuỳ chọn nào. Hai hàm `soLe*` khai `Intl` tường minh
 * vì chúng CÓ tuỳ chọn, và số chữ số lẻ nằm trong tên hàm để chỗ gọi không
 * phải mở file này ra tra.
 */

/** Số nguyên có nhóm hàng nghìn: `1203` → `1.203`. */
export function so(n: number): string {
  return n.toLocaleString('vi-VN')
}

/** Tối đa MỘT chữ số lẻ — phần trăm (`13,5%`), tỉ lệ gauge. */
export function soLe1(n: number): string {
  return new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(n)
}

/**
 * ĐÚNG hai chữ số lẻ — điểm hài lòng trên thang 5 (`4,33`, `4,30`).
 * `minimumFractionDigits` bằng `maximum` có chủ ý: `4,3` và `4,33` đứng cạnh
 * nhau trong cùng một cột số làm dấu phẩy lệch hàng.
 */
export function soLe2(n: number): string {
  return new Intl.NumberFormat('vi-VN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

// ─── Thời gian — giờ máy người dùng ──────────────────────────────────────────
// Chỉ hai khuôn mà Intl `vi-VN` ra ĐÚNG chữ đang hiện: `dd/mm/yyyy` và `HH:mm`.
// Gộp hai thứ đó trong MỘT `Intl` thì nó đặt giờ TRƯỚC ngày («14:32 05/08/2026»),
// còn `{day, month}` trần ra `05-08` — nên khuôn ghép tự nối các mảnh dưới đây.

const NGAY = new Intl.DateTimeFormat('vi-VN', { day: '2-digit', month: '2-digit', year: 'numeric' })
const GIO = new Intl.DateTimeFormat('vi-VN', {
  hour: '2-digit',
  minute: '2-digit',
  hourCycle: 'h23',
})

/** `05/08/2026`. */
export function ngayThangNam(d: Date): string {
  return NGAY.format(d)
}

/** `05/08` — năm ký tự đầu của `ngayThangNam` (Intl `{day, month}` ra `05-08`). */
export function ngayThang(d: Date): string {
  return NGAY.format(d).slice(0, 5)
}

/** `14:32`. */
export function gioPhut(d: Date): string {
  return GIO.format(d)
}

const TUONG_DOI = new Intl.RelativeTimeFormat('vi', { numeric: 'always' })

/**
 * `giay` đã trôi qua → «vừa xong» · «5 phút trước» · «3 giờ trước» · «2 ngày trước».
 * `numeric: 'always'` có chủ ý: `'auto'` ra «Hôm qua»/«Hôm kia» thay cho «1/2 ngày trước».
 */
export function truoc(giay: number): string {
  if (giay < 60) return 'vừa xong'
  const phut = Math.floor(giay / 60)
  if (phut < 60) return TUONG_DOI.format(-phut, 'minute')
  const gio = Math.floor(phut / 60)
  if (gio < 24) return TUONG_DOI.format(-gio, 'hour')
  return TUONG_DOI.format(-Math.floor(gio / 24), 'day')
}
