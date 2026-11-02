/**
 * Hai phép định dạng thời gian của tab «Nguồn dữ liệu» — dùng ở cả bốn khối.
 *
 * TỆP RIÊNG, không nằm cạnh component: eslint `react-refresh/only-export-components`
 * cảnh báo đúng khi một module vừa export component vừa export hàm thuần — Vite
 * không nhận ra nó là module component và nạp lại cả trang mỗi lần sửa. Cùng lý
 * do `tabDuAn.ts` đã tách ra khỏi `KhungDuAn.tsx`.
 */
import { truoc } from '@/lib/dinhDang'

/** Mốc tuyệt đối — dùng ở cột ngày của bảng, chỗ người dùng cần con số chính xác. */
export function luc(iso: string | null): string {
  return iso == null ? '—' : new Date(iso).toLocaleString('vi-VN')
}


export function cachDay(iso: string | null, bayGio: Date): string {
  if (iso == null) return 'chưa nhận lần nào'
  return truoc(Math.floor((bayGio.getTime() - new Date(iso).getTime()) / 1000))
}
