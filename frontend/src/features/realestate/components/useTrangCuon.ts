/**
 * Phân trang cursor dùng chung cho cả năm danh sách của M4.
 *
 * MỘT BẪY DUY NHẤT, VÀ NÓ LÀ LÝ DO FILE NÀY TỒN TẠI: điều kiện hết trang là
 * `nextCursor === null`, **không phải** `items.length === 0`. `contracts.py` nói
 * thẳng — trang cuối vừa khớp `limit` hàng vẫn cho `items` đầy. Năm danh sách tự
 * viết vòng lặp là năm cơ hội viết `items.length < limit` và bỏ mất hàng cuối
 * của mỗi dự án, âm thầm.
 *
 * `getNextPageParam` của react-query trả `undefined` để nói "hết" — `null` KHÔNG
 * được coi là hết (v5 phân biệt hai giá trị này), nên phải đổi tường minh.
 */
import { useInfiniteQuery, type QueryKey } from '@tanstack/react-query'
import type { Trang } from '../api'

export function useTrangCuon<T>(
  queryKey: QueryKey,
  nap: (cursor: string | null) => Promise<Trang<T>>,
  batBuoc = true,
) {
  const q = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam }) => nap(pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (trang: Trang<T>) => trang.nextCursor ?? undefined,
    enabled: batBuoc,
  })
  const items: T[] = (q.data?.pages ?? []).flatMap((p) => [...p.items])
  return { ...q, items }
}
