/**
 * Chữ cái của tên — từ ĐẦU + từ CUỐI («Nguyễn Minh Anh» → «NA»), tên MỘT từ lấy đúng
 * một chữ, rỗng ⇒ `?`. CÙNG luật với `chu_cai_dau` của backend — người dùng chốt
 * 2026-08-25: bảng Thành viên và lịch sử hội thoại phải cùng một khuôn chữ cái.
 */
export function chuCai(ten: string): string {
  const tu = ten.trim().split(/\s+/).filter(Boolean)
  if (tu.length === 0) return '?'
  const dau = tu[0]?.[0] ?? ''
  const cuoi = tu.length > 1 ? (tu[tu.length - 1]?.[0] ?? '') : ''
  return (dau + cuoi).toUpperCase()
}
