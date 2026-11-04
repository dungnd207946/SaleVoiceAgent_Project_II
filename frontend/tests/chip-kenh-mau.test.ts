/**
 * Cổng MÀU cho `components/ui/ChipKenh` — thuần văn bản, không render.
 *
 * VÌ SAO CẦN CỔNG NÀY: bản đầu (2026-08-13) chọn hai tint nhạt (#e8f0fb /
 * #f0ecfa) và ĐO ĐÚNG phần chữ-trên-nền-chip (5.93 / 6.32, đạt AA) — nhưng
 * KHÔNG đo nền chip với NỀN NÓ ĐỨNG LÊN. Ở `/convos/$phone`, hàng phiên đang
 * chọn có nền `acs` (#e7f2ee): tỉ lệ nền-chip/nền-hàng ra **1.00**, tức hai
 * màu sáng bằng nhau và chip biến mất. Người dùng báo "hầu như không thấy
 * được bằng mắt thường" — jsdom không vẽ nên không bài render nào bắt được,
 * chỉ số học mới bắt được.
 *
 * Cùng lối `tests/o-chon.test.ts`: quét văn bản nguồn cho một lớp lỗi mà
 * engine render giả không có cách nào phát hiện.
 */
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const THEME = path.join(path.dirname(fileURLToPath(import.meta.url)), '../src/styles/theme.css')

/** Độ sáng tương đối WCAG 2.x. */
function doSang(hex: string): number {
  const h = hex.replace('#', '')
  const kenh = [0, 2, 4]
    .map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4))
  return 0.2126 * (kenh[0] as number) + 0.7152 * (kenh[1] as number) + 0.0722 * (kenh[2] as number)
}

function tuongPhan(a: string, b: string): number {
  const [x, y] = [doSang(a), doSang(b)]
  const [cao, thap] = [Math.max(x, y), Math.min(x, y)]
  return (cao + 0.05) / (thap + 0.05)
}

async function docToken(): Promise<Record<string, string>> {
  const css = await readFile(THEME, 'utf8')
  const ra: Record<string, string> = {}
  for (const [, ten, gt] of css.matchAll(/(--color-[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    ra[ten as string] = (gt as string).toLowerCase()
  }
  return ra
}

const KENH = ['chat', 'voice'] as const

describe('ChipKenh — màu phải nổi trên MỌI nền nó đứng lên', () => {
  it('chữ trên nền chip đạt WCAG AA (4.5)', async () => {
    const t = await docToken()
    for (const k of KENH) {
      const bg = t[`--color-badge-kenh-${k}-bg`] as string
      const fg = t[`--color-badge-kenh-${k}-fg`] as string
      expect(tuongPhan(fg, bg), `chữ/nền chip ${k}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  /**
   * Người dùng chốt giữ NỀN NHẠT (2026-08-13, sau khi thử bản đặc: "đậm quá,
   * màu cũ đẹp hơn"). Nền nhạt thì tự nó không tách khỏi `acs` được — nên thứ
   * phải tách là **VIỀN**, và đó cũng đúng là chủ thể của WCAG 1.4.11: ranh
   * giới của một thành phần giao diện, không phải mảng nền của nó.
   */
  it('VIỀN chip tách được khỏi nền hàng ĐANG CHỌN (`acs`) — chỗ bản nền-nhạt-không-viền tàng hình', async () => {
    const t = await docToken()
    const acs = t['--color-acs'] as string
    for (const k of KENH) {
      const vien = t[`--color-badge-kenh-${k}-vien`] as string
      expect(tuongPhan(vien, acs), `viền chip ${k} vs acs`).toBeGreaterThanOrEqual(3)
    }
  })

  it('VIỀN chip tách được khỏi nền thẻ trắng (hàng KHÔNG chọn, card feedback)', async () => {
    const t = await docToken()
    for (const k of KENH) {
      const vien = t[`--color-badge-kenh-${k}-vien`] as string
      expect(tuongPhan(vien, '#ffffff'), `viền chip ${k} vs trắng`).toBeGreaterThanOrEqual(3)
    }
  })

  it('viền phải ĐẬM HƠN nền chip, không phải một sắc nhạt thứ hai', async () => {
    const t = await docToken()
    for (const k of KENH) {
      const vien = t[`--color-badge-kenh-${k}-vien`] as string
      const bg = t[`--color-badge-kenh-${k}-bg`] as string
      expect(tuongPhan(vien, bg), `viền vs nền chip ${k}`).toBeGreaterThanOrEqual(3)
    }
  })

  it('hai kênh khác nhau đủ xa để phân biệt, không phải hai sắc cùng họ', async () => {
    const t = await docToken()
    const chat = t['--color-badge-kenh-chat-bg'] as string
    const voice = t['--color-badge-kenh-voice-bg'] as string
    expect(chat).not.toBe(voice)
    // Không đòi tỉ lệ lớn giữa hai chip: chúng KHÔNG bao giờ chồng lên nhau,
    // và mỗi chip còn mang icon + nhãn chữ nên không phụ thuộc mỗi màu (WCAG
    // 1.4.1). Chỉ chặn ca hai token trỏ cùng một giá trị.
  })
})
