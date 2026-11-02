/**
 * Cổng token của biểu đồ. Đọc thẳng `theme.css` — không render, không jsdom
 * (jsdom không tính được `var()` lồng nhau nên một test render sẽ xanh cả khi
 * token không tồn tại).
 *
 * Bảo vệ hai điều: token có mặt, và KHÔNG ai chép mã màu ra ngoài file này.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// `new URL('../src/styles/theme.css', import.meta.url)` (bản gốc trong brief) ném
// "The URL must be of scheme file" dưới môi trường test `jsdom` của repo này —
// cùng lý do đã buộc `tests/chip-kenh-mau.test.ts` dùng `fileURLToPath` +
// `path.join` thay vì truyền URL thẳng vào `readFileSync`.
const CSS_PATH = path.join(path.dirname(fileURLToPath(import.meta.url)), '../src/styles/theme.css')
const CSS = readFileSync(CSS_PATH, 'utf8')

const CAN_CO = [
  '--color-ds1',
  '--color-ds2',
  '--color-ds3',
  '--color-ds4',
  '--color-ds-khac',
  '--color-ds1-mo',
  '--color-acs-manh',
  '--radius-mark',
] as const

describe('token chuỗi dữ liệu', () => {
  it.each(CAN_CO)('%s được khai trong @theme', (ten) => {
    expect(CSS).toContain(`${ten}:`)
  })

  it('ds1 và ds2 là hai mã khác nhau', () => {
    const doc = (ten: string) => CSS.match(new RegExp(`${ten}:\\s*(#[0-9a-f]{6})`, 'i'))?.[1]
    expect(doc('--color-ds1')).toBeDefined()
    expect(doc('--color-ds1')).not.toBe(doc('--color-ds2'))
  })

  it('radius-mark là 3px — KHÔNG phải bậc thứ tư của thang UI', () => {
    expect(CSS).toMatch(/--radius-mark:\s*3px/)
  })
})
