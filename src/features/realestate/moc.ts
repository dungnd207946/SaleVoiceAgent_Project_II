/**
 * Nhóm media `tien_do` thành MỐC cho timeline của tab Tiến độ.
 *
 * Media KHÔNG có cột ngày-mốc — hợp đồng cổng nạp chỉ có `caption` (hop_dong.py
 * phía backend), nên ngày đi nhờ trong caption theo khuôn mà cả hai adapter
 * (AINA `noblexsync`/`noblex-agent-adapter`, từ 2026-08-25) cùng phát:
 *
 *     «Tiến độ dd/mm/yyyy — <tiêu đề mốc>[ — <chú thích riêng của ảnh>]»
 *
 * Đổi khuôn này là đổi HỢP ĐỒNG hai phía — sửa cả adapter lẫn regex ở đây.
 *
 * Ảnh không mang tiền tố (upload tay qua portal, hoặc nguồn khác) KHÔNG bị đẩy
 * ra ngoài timeline: nhóm theo NGÀY TẠO (`createdAt`) — ảnh tải cùng ngày là
 * một đợt cập nhật, đúng nghĩa một mốc. Hai loại nhóm sắp chung một trục thời
 * gian, mới nhất trước.
 */
import { ngayThangNam } from '@/lib/dinhDang'
import type { Media } from './api'

export interface NhomMoc {
  /** Khoá nhóm — ổn định để làm `key` React. */
  readonly khoa: string
  /** Ngày mốc hiển thị, `dd/mm/yyyy`. */
  readonly ngay: string
  /** Tiêu đề mốc («05/2026», «Cất nóc toà A»…) — rỗng với nhóm theo ngày tạo. */
  readonly tieuDe: string
  readonly anh: readonly Media[]
}

const KHUON_MOC = /^Tiến độ (\d{2}\/\d{2}\/\d{4}) — (.+)$/

/** `dd/mm/yyyy` → khoá so sánh `yyyymmdd`; chuỗi lạ về '' (xếp cuối). */
function khoaNgay(ngay: string): string {
  const [d, m, y] = ngay.split('/')
  if (!d || !m || !y) return ''
  return `${y}${m}${d}`
}

function ngayTao(m: Media): string {
  const t = new Date(m.createdAt)
  if (Number.isNaN(t.getTime())) return ''
  return ngayThangNam(t)
}

interface Doc {
  ngay: string
  tieuDe: string
  /** Phần chú thích RIÊNG của ảnh, đã bóc tiền tố mốc (nếu có). */
  rieng: string
}

function doc(m: Media): Doc {
  const khop = KHUON_MOC.exec(m.caption)
  if (!khop) return { ngay: ngayTao(m), tieuDe: '', rieng: m.caption }
  const [tieuDe, ...conLai] = khop[2]!.split(' — ')
  return { ngay: khop[1]!, tieuDe: tieuDe ?? '', rieng: conLai.join(' — ') }
}

/**
 * Nhãn của MỘT ảnh khi đứng dưới heading mốc: chỉ phần riêng của nó — lặp lại
 * nguyên caption «Tiến độ dd/mm/yyyy — …» dưới từng ảnh của cùng một mốc là
 * nhiễu. Ảnh không có phần riêng trả '' để chỗ gọi rơi về fileName.
 */
export function nhanTrongMoc(m: Media): string {
  return doc(m).rieng
}

export function nhomTheoMoc(anh: readonly Media[]): NhomMoc[] {
  const nhom = new Map<string, { ngay: string; tieuDe: string; anh: Media[] }>()
  for (const m of anh) {
    const d = doc(m)
    const khoa = `${d.ngay}|${d.tieuDe}`
    const co = nhom.get(khoa)
    if (co) co.anh.push(m)
    else nhom.set(khoa, { ngay: d.ngay, tieuDe: d.tieuDe, anh: [m] })
  }
  return [...nhom.entries()]
    .map(([khoa, g]) => ({ khoa, ngay: g.ngay, tieuDe: g.tieuDe, anh: g.anh }))
    .sort((a, b) => {
      const ka = khoaNgay(a.ngay)
      const kb = khoaNgay(b.ngay)
      if (ka !== kb) return ka < kb ? 1 : -1 // mới nhất trước; ngày hỏng ('') xuống cuối
      return a.tieuDe.localeCompare(b.tieuDe, 'vi')
    })
}
