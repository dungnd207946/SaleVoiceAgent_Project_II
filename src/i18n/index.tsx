/**
 * i18n — VI mặc định, EN thứ hai (spec §6.2).
 *
 * VÌ SAO KHÔNG DÙNG i18next: hôm nay toàn bộ chuỗi song ngữ của shell nằm
 * trong cặp `{vi, en}` của nav item — đúng hình dạng prototype dùng (`data-l`).
 * Một provider 40 dòng làm đủ việc đó. Module nào cần số nhiều / nội suy /
 * tách file dịch thì thay `useLang()` bằng i18next mà không đụng nav item:
 * `t()` nhận vào một `Label`, không nhận key chuỗi.
 *
 * Ngôn ngữ giữ ở localStorage — chọn lại mỗi lần mở tab là thứ gây khó chịu
 * ngay lập tức, và nó không phải dữ liệu cần bảo mật.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import type { Label, Lang } from '@/lib/nav-types'

const STORAGE_KEY = 'odyssey.lang'

/**
 * EN đang TẮT (người dùng chốt 2026-10-05, audit impeccable): chỉ khung — rail,
 * panel, palette — có bản dịch, nội dung mọi màn vẫn tiếng Việt, nên bật EN là
 * một giao diện nửa nọ nửa kia. Tắt ở ĐÂY thì mọi chỗ cho chọn ngôn ngữ (menu
 * «Hồ sơ & tuỳ chọn», thẻ «Ngôn ngữ hiển thị» ở `/settings`) biến mất, và ai đã
 * lưu `en` về VI. Cơ chế `t()` và các bản dịch giữ nguyên — dịch xong các màn
 * thì đổi thành `true`, các bài test i18n (`skipIf(!CO_EN)`) tự chạy lại.
 */
export const CO_EN = false

interface LangContextValue {
  readonly lang: Lang
  readonly setLang: (next: Lang) => void
  /** Chọn nhánh ngôn ngữ của một cặp `{vi, en}`. */
  readonly t: (label: Label) => string
}

const LangContext = createContext<LangContextValue | null>(null)

function readStored(): Lang {
  if (typeof window === 'undefined' || !CO_EN) return 'vi'
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'en' ? 'en' : 'vi'
  } catch {
    return 'vi' // localStorage bị chặn (chế độ riêng tư, chính sách trình duyệt)
  }
}

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(readStored)

  const setLang = useCallback((next: Lang) => {
    setLangState(next)
    try {
      window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // không lưu được thì ngôn ngữ chỉ sống trong phiên
    }
  }, [])

  // `<html lang>` cho screen reader và cho `:lang()` trong CSS.
  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const t = useCallback((label: Label) => label[lang], [lang])

  const value = useMemo<LangContextValue>(() => ({ lang, setLang, t }), [lang, setLang, t])
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>
}

export function useLang(): LangContextValue {
  const ctx = useContext(LangContext)
  if (!ctx) throw new Error('useLang() phải nằm trong <LangProvider>')
  return ctx
}
