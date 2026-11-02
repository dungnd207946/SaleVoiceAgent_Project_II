/** Phân trang phía client cho các bảng của màn — API trả trọn danh sách (dự án, bài, nhật ký ≤ 200). */
import { useState } from 'react'

export function usePhanTrang<T>(ds: readonly T[], macDinh = 20) {
  const [trang, setTrang] = useState(1)
  const [soHang, setSoHang] = useState(macDinh)
  const soTrang = Math.max(1, Math.ceil(ds.length / soHang))
  const dang = Math.min(trang, soTrang)
  return {
    hien: ds.slice((dang - 1) * soHang, dang * soHang),
    thanh: {
      trang: dang,
      soTrang,
      total: ds.length,
      soHang,
      doiTrang: setTrang,
      doiSoHang: (n: number) => {
        setSoHang(n)
        setTrang(1)
      },
    },
  }
}
