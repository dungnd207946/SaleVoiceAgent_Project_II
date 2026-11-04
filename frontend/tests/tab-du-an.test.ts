/**
 * `tabHopLe()` là hàm thuần duy nhất trong `tabDuAn.ts` — test nó trực tiếp,
 * không qua router: nó chạy lúc `validateSearch`, trước khi có gì để render.
 */
import { describe, expect, it } from 'vitest'
import { TAB_DU_AN, tabHopLe } from '../src/features/realestate/tabDuAn'

describe('tabHopLe', () => {
  it('id hợp lệ đi qua nguyên vẹn', () => {
    for (const t of TAB_DU_AN) expect(tabHopLe(t.id)).toBe(t.id)
  })

  it('id cũ trong link đã gửi cho đồng nghiệp vẫn mở đúng tab', () => {
    expect(tabHopLe('thong-tin')).toBe('tong-quan')
    expect(tabHopLe('can')).toBe('quy-can')
  })

  it('giá trị lạ về tab đầu chứ không ném lỗi', () => {
    expect(tabHopLe('xyz')).toBe('tong-quan')
    expect(tabHopLe(undefined)).toBe('tong-quan')
    expect(tabHopLe(['can'])).toBe('tong-quan')
  })

  it('id csbh đã bỏ vẫn ánh xạ sang tai-lieu', () => {
    expect(tabHopLe('csbh')).toBe('tai-lieu')
  })
})
