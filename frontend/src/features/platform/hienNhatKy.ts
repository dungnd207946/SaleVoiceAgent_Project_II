/**
 * Cách hiện một hàng nhật ký — người và chi tiết. Tách khỏi component vì
 * `react-refresh/only-export-components` cấm .tsx export hàm thuần.
 */

import type { DongNhatKy } from './nhatKy'

/**
 * `actorId` không phải người — các dạng THẬT BE ghi (docs/contracts/audit.md, kiểm
 * 2026-08-25): `agent` (agent bootstrap) · `platform_admin` (NobleX) · `cron` (job
 * định kỳ) · `ingest` / `ingest_token:<id>` (cổng nạp) · `token:<id>` (importer cũ) · `''`
 * (không ghi được người).
 * Danh sách có thể mọc — dạng lạ hiện NGUYÊN chuỗi, không bao giờ lọc bỏ hàng.
 */
const TEN_DAC_BIET: Readonly<Record<string, string>> = {
  agent: 'Agent',
  platform_admin: 'NobleX',
  cron: 'Hệ thống',
  ingest: 'Cổng nạp',
  '': 'Hệ thống',
}

const TIEN_TO_CONG_NAP = ['ingest_token:', 'token:'] as const

/** Tên người; người đã bị gỡ (tên null, id `u_…`) hiện id thô — vẫn là bằng chứng. */
export function tenNguoi(d: Pick<DongNhatKy, 'actorId' | 'actorTen'>): string {
  if (d.actorTen) return d.actorTen
  if (TIEN_TO_CONG_NAP.some((t) => d.actorId.startsWith(t))) return TEN_DAC_BIET.ingest ?? d.actorId
  return TEN_DAC_BIET[d.actorId] ?? d.actorId
}

const GIOI_HAN_NGAN = 120

function giaTri(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (Array.isArray(v)) return v.map(giaTri).join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/**
 * `khoá: giá trị` nối bằng « · ». Đợt 1 KHÔNG có formatter riêng theo mã —
 * `chiTiet` là jsonb nguyên văn với hình dạng khác nhau mỗi mã (spec §6).
 * `ngan` để hiện trong ô, `dayDu` cho `title`.
 */
export function tomTatChiTiet(ct: Readonly<Record<string, unknown>>): {
  ngan: string
  dayDu: string
} {
  const dayDu = Object.entries(ct)
    .map(([k, v]) => `${k}: ${giaTri(v)}`)
    .join(' · ')
  const ngan = dayDu.length > GIOI_HAN_NGAN ? `${dayDu.slice(0, GIOI_HAN_NGAN - 1)}…` : dayDu
  return { ngan, dayDu }
}
