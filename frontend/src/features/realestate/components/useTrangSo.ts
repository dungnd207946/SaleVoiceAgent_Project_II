/**
 * Phân trang CÓ SỐ TRANG cho các BẢNG — đứng cạnh `useTrangCuon`, không thay nó.
 *
 * HAI HOOK CHO HAI KIỂU NẠP, cố ý: bảng cần nhảy tới trang n (người dùng biết
 * mình đang ở đâu trong 237 hàng), còn media cần nạp một lần rồi lọc client-side
 * cho bốn folder không lệch số đếm nhau. Gộp thành một hook nhận cờ là một hook
 * làm hai việc và không rõ việc nào đang chạy.
 *
 * `useQuery` chứ `useInfiniteQuery`: mỗi trang là một truy vấn ĐỘC LẬP, không
 * nối dồn — `queryKey` mang `trang`/`soHang` nên react-query cache từng trang
 * riêng và bấm lại trang cũ là tức thời.
 */
import { useLayoutEffect, useState } from 'react'
import { keepPreviousData, useQuery, type QueryKey } from '@tanstack/react-query'
import { SO_HANG_CHON } from '@/components/ui/ThanhTrang'
import type { Trang } from '../api'

export { SO_HANG_CHON }
const SO_HANG_DAU = 20

export function useTrangSo<T>(
  queryKey: QueryKey,
  nap: (p: { limit: number; offset: number }) => Promise<Trang<T>>,
  soHangDau: number = SO_HANG_DAU,
) {
  const [trang, setTrang] = useState(1)
  const [soHang, setSoHang] = useState(soHangDau)

  const q = useQuery({
    queryKey: [...queryKey, 'trang', trang, soHang],
    queryFn: () => nap({ limit: soHang, offset: (trang - 1) * soHang }),
    placeholderData: keepPreviousData,
  })

  const total = q.data?.total ?? 0
  const soTrang = Math.max(1, Math.ceil(total / soHang))

  useLayoutEffect(() => {
    if (q.data && trang > soTrang) setTrang(soTrang)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q.data, soTrang])

  return {
    items: (q.data?.items ?? []) as readonly T[],
    total,
    trang: Math.min(trang, soTrang),
    soHang,
    soTrang,
    doiTrang: setTrang,
    doiSoHang: (n: number) => {
      setSoHang(n)
      setTrang(1)
    },
    isPending: q.isPending,
    error: q.error,
    refetch: q.refetch,
  }
}
