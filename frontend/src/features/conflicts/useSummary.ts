import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { conflictSummary } from './api'
import { SUMMARY_KEY, projectKey } from './keys'

const BUSY_MS = 3_000
const IDLE_MS = 15_000

/** Hỏi lại 3 giây một lần khi có dự án đang kiểm tra, 15 giây khi rảnh. */
export function useSummary() {
  return useQuery({
    queryKey: SUMMARY_KEY,
    queryFn: conflictSummary,
    refetchInterval: (q) => (q.state.data?.some((r) => r.checking) ? BUSY_MS : IDLE_MS),
  })
}

/** Dự án vừa kiểm tra xong thì tải lại danh sách cảnh báo của nó. */
export function useReloadWhenDone(code: string, checking: boolean) {
  const qc = useQueryClient()
  const was = useRef(checking)
  useEffect(() => {
    if (was.current && !checking) void qc.invalidateQueries({ queryKey: projectKey(code) })
    was.current = checking
  }, [checking, code, qc])
}

/** Số cảnh báo đang mở theo mã dự án — cho chữ «N mâu thuẫn» ở từng dòng của màn Kiến thức. */
export function useConflictCounts(): Map<string, number> {
  const s = useSummary()
  return new Map((s.data ?? []).filter((r) => r.open > 0).map((r) => [r.projectCode, r.open]))
}
