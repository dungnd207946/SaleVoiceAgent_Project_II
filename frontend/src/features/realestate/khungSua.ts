/**
 * Chế độ Xem / Sửa của form dự án — MỘT cờ cho mọi tab và màn chi tiết (người dùng chốt 2026-08-21).
 * Đi qua context vì nút Sửa và giờ lưu ở đầu trang, còn lượt lưu do từng tab gửi.
 */
import { createContext, useCallback, useContext, useState } from 'react'
import type { DuAn } from './api'

export type SaveEvent = 'start' | 'done' | 'error'

interface KhungSua {
  duAn: DuAn | null
  dangSua: boolean
  doiSua: (v: boolean) => void
  saving: boolean
  savedAt: Date | null
  /** `useLuuTungO` báo mỗi lượt lưu để đầu trang hiện «Đang lưu…» / «Đã lưu lúc …». */
  reportSave: (event: SaveEvent) => void
}

/** Mặc định MỞ: form tạo mới nằm ngoài provider và phải nhập được ngay. */
const Ctx = createContext<KhungSua>({
  duAn: null,
  dangSua: true,
  doiSua: () => {},
  saving: false,
  savedAt: null,
  reportSave: () => {},
})

export const KhungSuaProvider = Ctx.Provider

export function useKhungSua(): KhungSua {
  return useContext(Ctx)
}

export function useSaveStatus(): Pick<KhungSua, 'saving' | 'savedAt' | 'reportSave'> {
  const [pending, setPending] = useState(0)
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const reportSave = useCallback((event: SaveEvent) => {
    if (event === 'start') {
      setPending((n) => n + 1)
      return
    }
    setPending((n) => Math.max(0, n - 1))
    if (event === 'done') setSavedAt(new Date())
  }, [])
  return { saving: pending > 0, savedAt, reportSave }
}
