/**
 * Bóc thông điệp lỗi để hiện cho người dùng — MỘT chỗ duy nhất cho cả module
 * `billing`. Trước review 2026-08-20, ba component (`BangGiaScreen`,
 * `PanelGanWorkspace`, `PanelBoGia`) tự khai ba bản COPY giống hệt 3 dòng này —
 * đổi cách bóc lỗi (vd thêm một nhánh mã lỗi mới) phải nhớ sửa cả ba.
 *
 * `LoiApi` ưu tiên `message` (đã dịch từ mã lỗi BE, xem `api.ts`); `Error`
 * thường thì lấy `message` gốc; còn lại (không phải `Error`) thì dùng
 * `macDinh` — KHÔNG bao giờ hiện `String(err)` trần cho một giá trị lạ.
 */
import { LoiApi } from '@/lib/http'

export function thongDiep(err: unknown, macDinh: string): string {
  if (err instanceof LoiApi) return err.message
  return err instanceof Error ? err.message : macDinh
}
