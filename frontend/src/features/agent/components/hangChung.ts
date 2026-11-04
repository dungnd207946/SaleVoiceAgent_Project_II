/**
 * Hằng nội dung của «Cấu hình chung» — sáu rào chắn, ba giọng điệu, ba độ dài.
 *
 * VÌ SAO TÁCH RA KHỎI `CauHinhChung.tsx` (2026-08-08): từ khi màn có hai chế độ
 * (xem · sửa), CẢ HAI cùng cần ba bảng này — form để dựng chip chọn, bản tóm tắt
 * để dịch mã `than_thien` thành chữ «Thân thiện». Chép sang file thứ hai là mở
 * đúng một lớp lỗi im lặng: thêm một giọng điệu ở form mà quên ở bảng dịch thì
 * màn xem hiện mã thô, không ai thấy cho tới khi có người chọn đúng giọng đó.
 *
 * Đặt ở file riêng chứ không ở file component vì eslint
 * `react-refresh/only-export-components` không cho file component export hằng —
 * cùng lý do `lop.ts` tồn tại.
 */

/** Sáu rào chắn của AG_01 BR08. Bản sao để HIỂN THỊ; nơi cưỡng chế là tầng render
 * của backend (`bundle.RAO_CHAN`). Lệch chữ ở đây không mở được công tắc nào —
 * không có công tắc nào để mở. */
export const RAO_CHAN: readonly string[] = [
  'Không bịa số liệu ngoài dữ liệu được cung cấp.',
  'Không nói mã nội bộ của dự án hay của hệ thống.',
  'Chỉ nói về dữ liệu trong workspace này.',
  'Xin phép trước khi lưu số điện thoại của khách.',
  'Dữ liệu quá hạn thì nói cần xác nhận lại, không khẳng định còn hàng.',
  'Không tư vấn pháp lý hay thuế.',
]

export const GIONG_DIEU = [
  { ma: 'lich_su', nhan: 'Lịch sự' },
  { ma: 'than_thien', nhan: 'Thân thiện' },
  { ma: 'ngan_gon', nhan: 'Ngắn gọn' },
] as const

export const DO_DAI = [
  { ma: 'ngan', nhan: 'Ngắn' },
  { ma: 'trung_binh', nhan: 'Trung bình' },
  { ma: 'chi_tiet', nhan: 'Chi tiết' },
] as const

/** Mã → nhãn tiếng Việt. Trả lại chính mã khi không nhận ra: bản nháp có thể mang
 * một giá trị backend thêm sau, và hiện mã thô vẫn hơn hiện ô trống — người đọc
 * ít ra biết có một giá trị ở đó. */
function nhanTheoMa(bang: readonly { ma: string; nhan: string }[], ma: string): string {
  return bang.find((x) => x.ma === ma)?.nhan ?? ma
}

export const nhanGiongDieu = (ma: string) => nhanTheoMa(GIONG_DIEU, ma)
export const nhanDoDai = (ma: string) => nhanTheoMa(DO_DAI, ma)
