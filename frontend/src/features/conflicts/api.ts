/** API cảnh báo mâu thuẫn dữ liệu — router `kb` của backend (`modules/kb/conflicts/router.py`). */
import { goi } from '@/lib/http'

export interface ConflictSide {
  entity: string | null
  recordId: number | null
  field: string | null
  label: string
  quote: string
}

export interface Conflict {
  id: number
  summary: string
  createdAt: string
  left: ConflictSide
  right: ConflictSide
}

export interface ConflictSummary {
  projectCode: string
  name: string
  open: number
  checking: boolean
  failed: boolean
  /** Giờ xong của lượt dò gần nhất (thành công hoặc hỏng); `null` khi chưa có lượt nào. */
  checkedAt: string | null
}

export interface ConflictCheck {
  checking: boolean
  failed: boolean
  checkedAt: string | null
  conflicts: Conflict[]
}

const ma = encodeURIComponent

export function conflictSummary(): Promise<ConflictSummary[]> {
  return goi<ConflictSummary[]>('/api/v1/conflicts/summary')
}

export function projectConflicts(code: string): Promise<Conflict[]> {
  return goi<Conflict[]>(`/api/v1/projects/${ma(code)}/conflicts`)
}

export function checkConflicts(code: string, since: string): Promise<ConflictCheck> {
  return goi<ConflictCheck>(`/api/v1/projects/${ma(code)}/conflicts/check?since=${ma(since)}`)
}

export function scanProject(code: string): Promise<{ jobId: number | null }> {
  return goi(`/api/v1/projects/${ma(code)}/conflicts/scan`, { method: 'POST' })
}

export function scanAll(): Promise<{ queued: number }> {
  return goi('/api/v1/conflicts/scan', { method: 'POST' })
}

export function dismissConflict(id: number): Promise<void> {
  return goi<void>(`/api/v1/conflicts/${id}/dismiss`, { method: 'POST' })
}
