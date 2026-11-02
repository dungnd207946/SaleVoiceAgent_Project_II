/**
 * Cách TRÌNH BÀY một component — nhãn và màu. MỘT nguồn cho cả hai chỗ vẽ nó:
 * thẻ «Theo component» (`TheComponent.tsx`) và tooltip biểu đồ ngày
 * (`BieuDoChiPhi.tsx`).
 *
 * Tách ra file riêng vì hai component đó PHẢI đồng ý với nhau: người dùng rê
 * chuột lên biểu đồ rồi đối chiếu với danh sách ngay bên phải, và một ô vuông
 * xanh đậm ở tooltip mà lại là «TTS» trong khi danh sách nói xanh đậm là «LLM»
 * thì cả hai thẻ cùng mất tin cậy. Hai bảng màu chép tay sẽ lệch nhau đúng vào
 * lần đầu ai đó thêm một component.
 *
 * MÀU THEO THỨ HẠNG, KHÔNG THEO DANH TÍNH. `bangMau()` nhận danh sách đã xếp
 * theo tiền CẢ KỲ (thứ tự BE trả về) và phát màu theo vị trí. Hệ quả cố ý:
 * cùng một component có thể đổi màu giữa hai kỳ nếu thứ hạng chi phí của nó
 * đổi — đúng ý đồ thang đơn sắc (đậm = tốn nhiều), và vì cả hai thẻ đọc chung
 * một bảng nên chúng luôn đổi cùng nhau.
 */
import type { DongComponent } from './kieu'

/** Nhãn người đọc. Component KHÔNG có ở đây hiện nguyên mã — thà thô còn hơn
 *  im lặng bỏ một dòng có tiền. */
const NHAN: Record<string, string> = {
  llm: 'LLM',
  tts: 'TTS',
  stt: 'STT',
  embed: 'Embed',
  search: 'Tra Google',
  speaker_verify: 'Xác thực giọng',
  vad: 'VAD',
  call: 'Cuộc gọi',
}

export function nhanComponent(ma: string): string {
  return NHAN[ma] ?? ma
}

/** Thang đơn sắc nhạt dần, khai ở `theme.css`. Hạng 6 trở đi dùng lại bậc
 *  nhạt nhất — thứ hạng của chúng đã nói bằng vị trí trong danh sách. */
const THANG = [
  'var(--color-comp-1)',
  'var(--color-comp-2)',
  'var(--color-comp-3)',
  'var(--color-comp-4)',
  'var(--color-comp-5)',
] as const

/** Component đo được nhưng KHÔNG tính tiền — xám, cố ý NGOÀI thang accent. */
export const MAU_KHONG_TINH_TIEN = 'var(--color-comp-0)'

export function mauTheoHang(hang: number): string {
  return THANG[Math.min(hang, THANG.length - 1)] ?? MAU_KHONG_TINH_TIEN
}

/**
 * `component → màu`, phát theo thứ tự của `items` (BE đã xếp theo tiền giảm
 * dần). Component không tính tiền lấy màu xám bất kể đứng ở đâu.
 */
export function bangMau(items: readonly DongComponent[]): Record<string, string> {
  const ra: Record<string, string> = {}
  items.forEach((d, i) => {
    ra[d.component] = Number(d.chi_phi) === 0 ? MAU_KHONG_TINH_TIEN : mauTheoHang(i)
  })
  return ra
}
