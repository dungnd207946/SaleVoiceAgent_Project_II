/**
 * Thêm · đổi tên · xoá role người dùng agent (backend `0967`, `/config/roles`).
 *
 * ÁP DỤNG NGAY, KHÔNG CHỜ «Lưu và áp dụng»: ba thao tác này đổi TẬP role chứ không đổi nội
 * dung cấu hình — và `PUT /config` đòi tập khoá trùng đúng tập role đang có, nên để chúng
 * chờ chung một lần Lưu là trộn hai loại thay đổi vào một giao dịch mà backend không có.
 * Xong thì bỏ cache `['config']`; `useBanNhap` ghép tập role mới vào form mà không mất
 * phần người dùng đang gõ dở (xem `ghepTapRole`).
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { LoiApi } from '@/lib/http'
import { suaRole, taoRole, xoaRole, type VaiTro } from './api'

/** Câu lỗi đọc được: `LoiApi` mang câu tiếng Việt của backend, lỗi khác thì câu chung. */
export function cauLoi(e: unknown): string | null {
  if (!e) return null
  return e instanceof LoiApi ? e.message : 'Chưa thực hiện được — thử lại lần nữa.'
}

export function useVaiTro() {
  const qc = useQueryClient()
  const lamMoi = () => qc.invalidateQueries({ queryKey: ['config'] })

  const mTao = useMutation({
    mutationFn: (v: { ten: string; saoChepTu: VaiTro | null; icon: string }) =>
      taoRole(v.ten, v.saoChepTu, v.icon),
    onSuccess: lamMoi,
  })
  const mSua = useMutation({
    mutationFn: ({ key, ...thay }: { key: VaiTro; ten?: string; icon?: string }) =>
      suaRole(key, thay),
    onSuccess: lamMoi,
  })
  const mXoa = useMutation({
    mutationFn: (key: VaiTro) => xoaRole(key),
    onSuccess: lamMoi,
  })

  return { mTao, mSua, mXoa }
}
