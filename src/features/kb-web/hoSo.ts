import type { MucHoSo } from './api'

/** Bỏ hai dòng đầu do hệ thống thêm («(Cập nhật …)» và «[tiêu đề]») và nhãn chủ đề mở đầu — xem public-web.md. */
export function thanMuc(m: MucHoSo): string {
  const than = m.noiDung.replace(/^\(Cập nhật \d{2}\/\d{2}\/\d{4}\)\n(?:\[[^\n]*\]\n)?/, '')
  return than.startsWith(`${m.nhan}:`) ? than.slice(m.nhan.length + 1).trim() : than
}
