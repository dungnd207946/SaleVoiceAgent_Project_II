/**
 * MỘT query cho cả màn. `refetchInterval` là HÀM để TẮT được khi không còn dự án
 * nào đang nạp — số cố định là một request mỗi 3 giây suốt thời gian tab mở.
 */
import { useQuery } from '@tanstack/react-query'

import { fetchKbStatus, type KbStatus } from './api'

export const KB_KEY = ['re', 'kb-status'] as const

const POLL_MS = 3_000

function _asList(data: unknown): KbStatus[] {
  return Array.isArray(data) ? (data as KbStatus[]) : []
}

export function useKbStatus() {
  const q = useQuery({
    queryKey: KB_KEY,
    queryFn: fetchKbStatus,
    refetchInterval: (query) => (_asList(query.state.data).some((t) => t.indexing) ? POLL_MS : false),
  })

  const byCode: Record<string, KbStatus> = {}
  for (const t of _asList(q.data)) {
    if (t?.projectCode) byCode[t.projectCode] = t
  }

  return { byCode, isLoading: q.isPending }
}
