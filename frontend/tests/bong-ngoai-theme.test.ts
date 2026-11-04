/**
 * Cổng cấu trúc: KHÔNG có bóng đổ chép tay (`shadow-[…rgba…]`) trong `src/`.
 *
 * Bóng đổ mang MÀU (rgba), nên cùng luật với mã màu: chỉ sống ở `theme.css`
 * (`--shadow-*` ⇒ utility `shadow-chon`, `shadow-menu`…). Trước 2026-10-05 có 18
 * bản chép tay, và cùng một vai trò mang tới bốn con số khác nhau — menu thả
 * xuống ở bốn chỗ là bốn độ đậm (.12 · .14 · .16 · hai lớp). jsdom không nạp CSS
 * nên chỉ quét văn bản mới bắt được, cùng lý do `tests/vien-tran.test.ts`.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

function quet(thuMuc: string): string[] {
  const ra: string[] = []
  for (const ten of readdirSync(thuMuc)) {
    const duongDan = join(thuMuc, ten)
    if (statSync(duongDan).isDirectory()) ra.push(...quet(duongDan))
    else if (/\.tsx?$/.test(ten)) ra.push(duongDan)
  }
  return ra
}

describe('bóng đổ chỉ sống ở theme.css', () => {
  it('không tệp nào trong src/ viết shadow-[…] mang màu', () => {
    const lech = quet('src').flatMap((f) =>
      (readFileSync(f, 'utf8').match(/shadow-\[[^\]]*(rgba?|#[0-9a-f]{3,8})[^\]]*\]/gi) ?? []).map(
        (m) => `${f}: ${m}`,
      ),
    )
    expect(lech, 'thêm/dùng một `--shadow-*` trong theme.css thay vì chép tay').toEqual([])
  })
})
