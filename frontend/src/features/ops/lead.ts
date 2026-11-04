/**
 * Lead của khách — bậc phễu, nhãn và đối tượng. MỘT chỗ cho cả chip, bộ lọc và route.
 *
 * Nguồn: `tenant_data.escalations` (migration backend `0968`), agent ghi. Tập bậc do
 * người dùng chốt 2026-09-30 (spec `2026-09-30-lead-tren-convos-design.md`). Bậc LẠ agent
 * ghi thêm vẫn tới được FE: nó hiện nguyên văn bằng chip trung tính, không vào bộ lọc.
 */
export const BAC_LEAD = ['lead', 'mql', 'sql', 'hen_gap'] as const
export type BacLead = (typeof BAC_LEAD)[number]

export const NHAN_BAC: Record<BacLead, string> = {
  lead: 'Lead',
  mql: 'MQL',
  sql: 'SQL',
  hen_gap: 'Hẹn gặp',
}

/**
 * Nghĩa của từng bậc cho người đọc — MQL/SQL là thuật ngữ phễu, sale mới vào không
 * tự biết (audit 05/10). Lấy NGUYÊN từ quy trình 9 bước bên agent (`odyssey-agent`
 * changelog 2026-09-29: lead = tiềm năng, mql = quan tâm, sql = đủ điều kiện,
 * hen_gap = có lịch hẹn) — đổi tiêu chí ở đó thì đổi chữ ở đây, đừng tự đặt nghĩa.
 */
export const NGHIA_BAC: Record<BacLead, string> = {
  lead: 'khách tiềm năng',
  mql: 'đã quan tâm',
  sql: 'đủ điều kiện mua',
  hen_gap: 'đã có lịch hẹn',
}

export function laBacLead(v: unknown): v is BacLead {
  return typeof v === 'string' && (BAC_LEAD as readonly string[]).includes(v)
}

/** Giá trị bộ lọc `?stage=` / `lead_stage`: bốn bậc + `none` (khách chưa có lead). */
export type LocStage = BacLead | 'none'

export function laLocStage(v: unknown): v is LocStage {
  return v === 'none' || laBacLead(v)
}

const DOI_TUONG: Record<string, string> = { end_user: 'Khách mua', broker: 'Môi giới' }

/** Mã lạ hiện NGUYÊN VĂN — đoán một nhãn tiếng Việt cho mã không biết là nói sai. */
export function nhanDoiTuong(a: string): string {
  return DOI_TUONG[a] ?? a
}
