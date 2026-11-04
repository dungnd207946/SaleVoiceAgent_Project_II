/**
 * Theo dõi mâu thuẫn mới của một dự án trong lúc màn dự án đang mở.
 *
 * Hỏi `check` định kỳ (3 giây khi còn job nạp/dò chưa xong, 15 giây khi rảnh; React Query
 * dừng khi tab bị ẩn) thay vì móc vào từng nút Lưu: phần lớn tab của màn dự án tự lưu bằng
 * lời gọi API trực tiếp, không qua `useMutation`, nên không có chỗ chung nào để móc.
 * Cách này cũng bắt được mâu thuẫn do người khác hay cổng nạp tạo ra.
 */
import { useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { checkConflicts, type Conflict } from './api'
import { SUMMARY_KEY } from './keys'

const BUSY_MS = 3_000
const IDLE_MS = 15_000

export function useConflictWatch(code: string | undefined) {
  const qc = useQueryClient()
  const [since, setSince] = useState(() => new Date(Date.now() - 5_000).toISOString())
  const [fresh, setFresh] = useState<Conflict[]>([])
  const check = useQuery({
    queryKey: ['conflicts', 'check', code, since],
    queryFn: () => checkConflicts(code!, since),
    enabled: Boolean(code),
    refetchInterval: (q) => (q.state.data?.checking ? BUSY_MS : IDLE_MS),
  })
  const found = check.data?.conflicts
  useEffect(() => {
    if (!found?.length) return
    setFresh(found)
    setSince(found.reduce((m, c) => (c.createdAt > m ? c.createdAt : m), found[0]!.createdAt))
    void qc.invalidateQueries({ queryKey: SUMMARY_KEY })
  }, [found, qc])
  return {
    checking: check.data?.checking ?? false,
    failed: check.data?.failed ?? false,
    fresh,
    clear: () => setFresh([]),
  }
}
