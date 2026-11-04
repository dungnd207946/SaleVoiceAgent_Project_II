/**
 * Chip stage phải đọc được và NỔI trên mọi nền nó đứng lên — cùng lý do cổng
 * `chip-kenh-mau`: jsdom không vẽ, chỉ số học bắt được lớp lỗi này. Nền quan trọng
 * nhất là `acs` — hàng phiên ĐANG CHỌN ở `/convos/$phone`, chỗ chip kênh từng tàng hình.
 */
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const THEME = path.join(path.dirname(fileURLToPath(import.meta.url)), '../src/styles/theme.css')

function doSang(hex: string): number {
  const h = hex.replace('#', '')
  const k = [0, 2, 4]
    .map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
  return 0.2126 * (k[0] as number) + 0.7152 * (k[1] as number) + 0.0722 * (k[2] as number)
}

function tuongPhan(a: string, b: string): number {
  const [x, y] = [doSang(a), doSang(b)]
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

async function docToken(): Promise<Record<string, string>> {
  const css = await readFile(THEME, 'utf8')
  const ra: Record<string, string> = {}
  for (const [, ten, gt] of css.matchAll(/(--color-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    ra[ten as string] = (gt as string).toLowerCase()
  }
  return ra
}

const BAC = [1, 2, 3, 4] as const

describe('ChipStage — bốn bậc phễu', () => {
  it('chữ trên nền chip đạt WCAG AA (4.5)', async () => {
    const t = await docToken()
    for (const b of BAC) {
      const bg = t[`--color-lead-${b}-bg`] as string
      const fg = t[`--color-lead-${b}-fg`] as string
      expect(tuongPhan(fg, bg), `chữ/nền bậc ${b}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('RANH GIỚI chip (viền, hoặc chính nền với chip đặc) tách khỏi nền `acs` và nền thẻ ≥ 3', async () => {
    const t = await docToken()
    for (const nen of ['--color-acs', '--color-n1', '--color-n0']) {
      for (const b of BAC) {
        const vien = t[`--color-lead-${b}-vien`] as string
        expect(tuongPhan(vien, t[nen] as string), `viền bậc ${b} vs ${nen}`).toBeGreaterThanOrEqual(
          3,
        )
      }
    }
  })

  it('viền bậc 1–3 tách khỏi chính nền chip ≥ 3 (bậc 4 là chip đặc, viền = nền)', async () => {
    const t = await docToken()
    for (const b of [1, 2, 3] as const) {
      const vien = t[`--color-lead-${b}-vien`] as string
      const bg = t[`--color-lead-${b}-bg`] as string
      expect(tuongPhan(vien, bg), `viền/nền bậc ${b}`).toBeGreaterThanOrEqual(3)
    }
  })
})
