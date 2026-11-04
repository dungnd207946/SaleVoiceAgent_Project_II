/**
 * MỌI `<select>` phải mang class `o-chon` (`styles/theme.css`).
 *
 * VÌ SAO CẦN MỘT CỔNG CHO ĐÚNG MỘT CLASS: bug nó chặn là bug VÔ HÌNH với người
 * viết code. `<select>` để `appearance` mặc định thì Chromium tôn trọng
 * `padding` (ra 35px, đứng cạnh ô nhập 36px trông như nhau) còn WebKit bỏ qua
 * và ép metric riêng (~23px + nút mũi tên hệ thống) — nên màn hình hỏng chỉ ở
 * máy người dùng mở bằng Safari, và không một bài test render nào thấy được
 * (jsdom không có engine vẽ). Quét văn bản là cách duy nhất bắt được nó ở CI.
 *
 * Cùng lối với `module-boundaries.test.ts`: luật nào chỉ sống trong tài liệu
 * thì lần thêm `<select>` tiếp theo sẽ phá.
 */
import { describe, expect, it } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const SRC = join(import.meta.dirname, '../src')

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name)
    if (statSync(full).isDirectory()) return walk(full)
    return /\.tsx$/.test(full) ? [full] : []
  })
}

/** Chú thích bị bỏ trước khi quét: repo NÓI VỀ `<select>` nhiều hơn là dùng nó. */
const CHU_THICH = /\/\*[\s\S]*?\*\/|\/\/.*$/gm

/**
 * Thẻ mở `<select …>`, cắt bằng ĐẾM NGOẶC chứ không bằng regex: mọi `<select>`
 * ở đây đều có `onChange={(e) => …}`, và cái `>` của mũi tên nằm TRƯỚC
 * `className`. Một `[^>]*>` dừng ngay ở đó rồi báo cả 9 chỗ là thiếu class —
 * đúng thứ bẫy làm cổng này tự tin sai theo hướng ồn ào (may là ồn, không phải
 * im lặng).
 */
function theMo(ma: string, dau: number): string {
  let sau = 0
  for (let i = dau; i < ma.length; i++) {
    const c = ma[i]
    if (c === '{') sau++
    else if (c === '}') sau--
    else if (c === '>' && sau === 0) return ma.slice(dau, i + 1)
  }
  return ma.slice(dau)
}

describe('mọi <select> mang class o-chon', () => {
  it('không file nào để sót', () => {
    const sot: string[] = []
    for (const file of walk(SRC)) {
      const ma = readFileSync(file, 'utf8').replace(CHU_THICH, '')
      for (const m of ma.matchAll(/<select\b/g)) {
        const the = theMo(ma, m.index)
        if (!the.includes('o-chon')) sot.push(`${relative(SRC, file)}: ${the.replace(/\s+/g, ' ')}`)
      }
    }
    expect(sot).toEqual([])
  })
})
