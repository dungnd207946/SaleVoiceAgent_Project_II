/**
 * Phép chia «tab nào hiện, tab nào vào menu +N» của hàng tab role (`KhoiVaiTro.tsx`) —
 * hàm THUẦN, tách khỏi component để test được mà không cần bố cục (jsdom đo mọi thứ = 0)
 * và vì `react-refresh/only-export-components` không cho tệp component xuất hàm.
 */
import type { VaiTro } from './api'

/** Khoảng giữa hai tab (`gap-1`). */
export const KHE = 4
/** Chỗ dành cho nút «+N» khi phải gom — ước lượng thay vì đo: nút này chỉ tồn tại khi đã
 *  thiếu chỗ, tức đo nó là phải vẽ nó trước. «+10 ▾» ở 12.5px đo được ~52px. */
export const CHO_NUT_THEM_N = 60

/**
 * Bao nhiêu tab đầu tiên vừa hàng. `null` = không đo được (jsdom, lần vẽ đầu) ⇒ hiện hết.
 * Hàm THUẦN để test được phép chia mà không cần bố cục.
 */
export function soTabVua(rongTab: readonly number[], choTrong: number): number | null {
  if (choTrong <= 0 || rongTab.some((w) => w <= 0)) return null
  const tong = rongTab.reduce((a, w) => a + w + KHE, 0)
  if (tong <= choTrong) return rongTab.length
  let dung = 0
  let k = 0
  for (const w of rongTab) {
    if (dung + w + KHE > choTrong - CHO_NUT_THEM_N) break
    dung += w + KHE
    k++
  }
  return Math.max(1, k)
}

/** Dãy tab hiện: `k` tab đầu, nhưng tab ĐANG MỞ luôn có mặt — nó thế chỗ tab cuối. */
export function tabHien(keys: readonly VaiTro[], k: number, dangMo: VaiTro): VaiTro[] {
  const dau = keys.slice(0, k)
  if (dau.includes(dangMo) || !keys.includes(dangMo)) return dau
  return [...dau.slice(0, Math.max(0, k - 1)), dangMo]
}
