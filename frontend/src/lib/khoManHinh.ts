import { useSyncExternalStore } from 'react'

/**
 * Ba tầng màn hình của portal (spec 2026-09-28-responsive-mobile).
 *
 * `BP` PHẢI khớp breakpoint mặc định của Tailwind (`md` = 48rem, `lg` = 64rem):
 * class `max-md:`/`max-lg:` và hook này phải đổi tầng ở CÙNG một pixel, nếu
 * không sẽ có dải vài px mà CSS nói mobile còn JS nói tablet.
 *
 * `.02` trừ đi = cách Tailwind v4 viết `width < 48rem` bằng `max-width`.
 *
 * Không có `window.matchMedia` (jsdom) ⇒ `desktop`: test cũ dựng đúng layout cũ.
 */
export const BP = { md: 768, lg: 1024 } as const

export type KhoManHinh = 'mobile' | 'tablet' | 'desktop'

const Q_MOBILE = `(max-width: ${BP.md - 0.02}px)`
const Q_TABLET = `(max-width: ${BP.lg - 0.02}px)`

const coMatchMedia = () => typeof window !== 'undefined' && typeof window.matchMedia === 'function'

function doc(): KhoManHinh {
  if (!coMatchMedia()) return 'desktop'
  if (window.matchMedia(Q_MOBILE).matches) return 'mobile'
  if (window.matchMedia(Q_TABLET).matches) return 'tablet'
  return 'desktop'
}

function dangKy(bao: () => void): () => void {
  if (!coMatchMedia()) return () => {}
  const ds = [Q_MOBILE, Q_TABLET].map((q) => window.matchMedia(q))
  for (const m of ds) m.addEventListener('change', bao)
  return () => {
    for (const m of ds) m.removeEventListener('change', bao)
  }
}

export function useKhoManHinh(): KhoManHinh {
  return useSyncExternalStore(dangKy, doc, () => 'desktop')
}
