/**
 * Chữ hiển thị cho mã của API — người dùng không thấy `nightly`/`needs_browser`/`kbweb_run`.
 * Quy ước mockup đã duyệt: «mỗi» không «hằng», không thuật ngữ nội bộ.
 */
import type { Mode, TinhTrangNguon, Viec } from './api'

export const NHAN_MODE: Record<Mode, string> = {
  nightly: 'Cập nhật mỗi đêm',
  weekly: 'Cập nhật mỗi tuần',
  rebuild: 'Viết lại toàn bộ hồ sơ',
}

export const MO_TA_MODE: Record<Mode, string> = {
  nightly: 'Thu bài mới của 2 ngày gần nhất, viết bản tin thị trường, cập nhật hồ sơ các dự án khách đang hỏi.',
  weekly: 'Tìm thêm bài cho từng dự án theo các chủ đề đang bật.',
  rebuild: 'Viết lại hồ sơ của mọi dự án từ đầu, dựa trên các bài đã thu.',
}

export const THU_TRONG_TUAN = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN'] as const

export const NHAN_TINH_TRANG: Record<TinhTrangNguon, string> = {
  ok: 'Hoạt động',
  blocked: 'Bị chặn',
  no_feed: 'Trang tĩnh',
  timeout: 'Không phản hồi',
  private: 'Không công khai',
}

export const MAU_TINH_TRANG: Record<TinhTrangNguon, string> = {
  ok: 'bg-acs text-acd',
  blocked: 'bg-badge-warn-bg text-badge-warn-fg',
  no_feed: 'bg-acs text-acd',
  timeout: 'bg-badge-warn-bg text-badge-warn-fg',
  private: 'bg-badge-alert-bg text-badge-alert-fg',
}

const PILL_OK = 'bg-acs text-acd'
const PILL_LOI = 'bg-badge-alert-bg text-badge-alert-fg'
const PILL_CHO = 'bg-badge-neutral-bg text-badge-neutral-fg'

/** Cột «Kết quả»: nhãn + câu giải thích, không bày thông điệp nội bộ (`SRC rebuild: 18 mục`, `ConnectError`). */
export function ketQuaViec(v: Viec): { nhan: string; mau: string; chiTiet: string } {
  if (v.trangThai === 'queued') return { nhan: 'Đang chờ', mau: PILL_CHO, chiTiet: '' }
  if (v.trangThai === 'running') return { nhan: 'Đang chạy', mau: PILL_CHO, chiTiet: '' }
  if (v.trangThai === 'failed') return { nhan: 'Lỗi', mau: PILL_LOI, chiTiet: loiDeDoc(v.thongDiep) }
  if (v.loai === 'kbweb_probe') {
    const t = v.tinhTrangNguon ?? 'ok'
    return { nhan: NHAN_TINH_TRANG[t], mau: MAU_TINH_TRANG[t], chiTiet: t === 'ok' && v.soLuong > 0 ? `${v.soLuong} bài trong 2 ngày gần nhất` : '' }
  }
  if (v.loai === 'kbweb_project') {
    if (v.thongDiep.includes('giữ hồ sơ cũ')) return { nhan: 'Giữ hồ sơ cũ', mau: PILL_CHO, chiTiet: 'Lần viết này không đạt, hồ sơ trước được giữ nguyên' }
    if (v.thongDiep.includes('bỏ qua')) return { nhan: 'Bỏ qua', mau: PILL_CHO, chiTiet: 'Dự án chưa công bố' }
    return { nhan: 'Thành công', mau: PILL_OK, chiTiet: v.soLuong > 0 ? `${v.soLuong} mục hồ sơ` : 'Không có bài mới' }
  }
  return { nhan: 'Thành công', mau: PILL_OK, chiTiet: '' }
}

function loiDeDoc(thongDiep: string): string {
  const m = thongDiep.toLowerCase()
  if (m.includes('connect') || m.includes('connection')) return 'Không kết nối được dịch vụ xử lý, thử lại sau'
  if (m.includes('timeout') || m.includes('timed out')) return 'Quá thời gian chờ, thử lại sau'
  return 'Không hoàn tất, thử lại sau'
}

/** Cột «Việc» của bảng nhật ký / đang chạy. */
export function tenViec(v: Viec): string {
  if (v.loai === 'kbweb_probe') return 'Kiểm tra nguồn'
  if (v.loai === 'kbweb_run') return NHAN_MODE[v.mode as Mode] ?? v.mode
  if (v.mode === 'rebuild') return 'Viết lại hồ sơ'
  if (v.mode === 'init') return 'Tạo hồ sơ'
  return 'Cập nhật hồ sơ'
}

/** Cột «Phạm vi»: tên dự án, tên miền của nguồn, hoặc «Mọi dự án» cho lượt theo lịch. */
export function phamViViec(v: Viec): string {
  if (v.loai === 'kbweb_probe') return (v.url ?? '').replace(/^https?:\/\//, '').replace(/\/$/, '')
  return v.duAnTen ?? v.duAn ?? 'Mọi dự án'
}

export function nguoiViec(v: Viec): string {
  return v.nguoiTen ?? 'Hệ thống'
}

/** Khoá «cùng một việc» — lượt lỗi đã có lượt sau cùng khoá thì không cần nút Chạy lại. */
function khoaViec(v: Viec): string {
  return `${v.loai}|${v.loai === 'kbweb_run' ? v.mode : (v.duAn ?? v.url ?? '')}`
}

/** id các lượt lỗi đã được chạy lại (có lượt mới hơn cùng việc). `ds` mới nhất trước. */
export function daChayLai(ds: readonly Viec[]): Set<number> {
  const thay = new Set<string>()
  const out = new Set<number>()
  for (const v of ds) {
    const k = khoaViec(v)
    if (v.trangThai === 'failed' && thay.has(k)) out.add(v.id)
    thay.add(k)
  }
  return out
}
