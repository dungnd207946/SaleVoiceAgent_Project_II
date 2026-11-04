/**
 * Poll trong lúc còn job tạo mô tả, DỪNG ngay khi hết, rồi làm mới danh sách để
 * chữ vừa sinh hiện vào ô mà không phải tải lại trang.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'

import { fetchEnrichStatus, type EnrichItem } from './api'

const POLL_MS = 3_000
const PENDING = new Set(['queued', 'running'])

function _asList(data: unknown): EnrichItem[] {
  return Array.isArray(data) ? (data as EnrichItem[]) : []
}

export function useEnrichStatus(projectCode: string) {
  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['re', projectCode, 'enrich-status'],
    queryFn: () => fetchEnrichStatus(projectCode),
    refetchInterval: (query) =>
      _asList(query.state.data).some((m) => PENDING.has(m.state)) ? POLL_MS : false,
  })

  const pendingCount = _asList(q.data).filter((m) => PENDING.has(m.state)).length
  const prev = useRef(pendingCount)
  useEffect(() => {
    if (prev.current > 0 && pendingCount === 0) {
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })
      void qc.invalidateQueries({ queryKey: ['re', projectCode, 'documents'] })
    }
    prev.current = pendingCount
  }, [pendingCount, projectCode, qc])

  return {
    running: new Set(
      _asList(q.data)
        .filter((m) => PENDING.has(m.state))
        .map((m) => m.recordId),
    ),
  }
}
