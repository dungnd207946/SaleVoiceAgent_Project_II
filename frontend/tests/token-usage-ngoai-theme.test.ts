/**
 * CỔNG: 21 token màu của `/usage` phải khai ở `:root`, KHÔNG ở `@theme`.
 *
 * Lớp lỗi này đã sập thật (2026-08-25) và nó IM LẶNG hoàn toàn:
 * Tailwind v4 chỉ phát ra biến `@theme` nào **scanner nhìn thấy** trong mã
 * nguồn. Bộ `--color-u-*`/`--color-ua-*`/`--color-ub-*` chỉ được tham chiếu
 * bằng template string ĐỘNG (`var(--color-u-${ma})` trong `truc-usage.ts`), nên
 * scanner không thấy và Tailwind cắt sạch. Đo được lúc đó: sau `vite build`,
 * bundle CSS có `--color-comp-1` (được một class nhắc tới) nhưng **0 lần** có
 * `--color-u-llm`.
 *
 * Hệ quả KHÔNG phải «mất màu» — nó tệ hơn thế: `var(--a)` thành vô nghĩa ⇒
 * `stop-color` của gradient hỏng ⇒ SVG rơi về mặc định và **mọi đường kẻ thành
 * ĐEN**. Không lỗi, không cảnh báo, `tsc`/`eslint`/toàn bộ test đều xanh — chỉ
 * có người dùng mở màn ra và thấy bảy biểu đồ đen như nhau.
 *
 * Bài này quét VĂN BẢN vì đó là tầng duy nhất bắt được: jsdom không nạp CSS,
 * nên không bài render nào phân biệt được `stroke` giải được với `stroke` hỏng.
 * Cùng lý do `o-chon.test.ts` và `vien-tran.test.ts` tồn tại.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// `import.meta.dirname` + `join`, KHÔNG `new URL(..., import.meta.url)`: dưới
// môi trường jsdom của vitest, `import.meta.url` không phải scheme `file:` nên
// `readFileSync(URL)` ném «The URL must be of scheme file». Cùng lối
// `o-chon.test.ts`/`vien-tran.test.ts` — hai cổng quét văn bản có sẵn.
const CSS = readFileSync(join(import.meta.dirname, '../src/styles/theme.css'), 'utf8')

/** Bảy mã component của `/usage` — cùng danh sách với `so-tab-usage.ts`. */
const MA = ['llm', 'stt', 'tts', 'vad', 'call', 'embed', 'speaker_verify']

/** Token của ĐƯỜNG THỨ HAI. Đọc qua `bienMauPhu()` — cũng bằng template string
 *  động (`var(--color-u-${ma}2)`), tức cùng đúng lớp lỗi Tailwind cắt. */
const MA_PHU = ['stt']

/** Thân khối `@theme { … }` (khối đầu tiên, và là khối duy nhất của tệp). */
function thanTheme(): string {
  const i = CSS.indexOf('@theme {')
  expect(i, '`theme.css` không còn khối `@theme` — bài này mất đối tượng đo').toBeGreaterThan(-1)
  let sau = 0
  for (let k = i; k < CSS.length; k++) {
    if (CSS[k] === '{') sau++
    else if (CSS[k] === '}' && --sau === 0) return CSS.slice(i, k)
  }
  throw new Error('`@theme {` không đóng')
}

describe('token màu `/usage` nằm ngoài `@theme`', () => {
  it('cả 21 token đều được khai', () => {
    for (const ma of MA) {
      for (const tien of ['u', 'ua', 'ub']) {
        expect(CSS, `thiếu --color-${tien}-${ma}`).toContain(`--color-${tien}-${ma}:`)
      }
    }
  })

  it('KHÔNG token nào nằm trong `@theme` — Tailwind sẽ cắt và line thành đen', () => {
    const trong = thanTheme()
    const lot = MA.flatMap((ma) =>
      ['u', 'ua', 'ub'].map((t) => `--color-${t}-${ma}:`).filter((khoa) => trong.includes(khoa)),
    )
    expect(
      lot,
      'token này nằm trong `@theme` nên Tailwind v4 sẽ cắt nó (chỉ được tham ' +
        'chiếu bằng template string động) — chuyển xuống khối `:root` ngay dưới',
    ).toEqual([])
  })

  it('token đường 2 cũng đủ, và cũng NGOÀI `@theme`', () => {
    const trong = thanTheme()
    for (const ma of MA_PHU) {
      for (const tien of ['u', 'ua']) {
        const khoa = `--color-${tien}-${ma}2:`
        expect(CSS, `thiếu ${khoa}`).toContain(khoa)
        expect(
          trong.includes(khoa),
          `${khoa} nằm trong \`@theme\` — Tailwind sẽ cắt và đường 2 mất màu`,
        ).toBe(false)
      }
    }
  })

  it('khai trong một khối `:root`', () => {
    const khoi = [...CSS.matchAll(/:root\s*\{([^}]*)\}/g)].map((m) => m[1] ?? '')
    for (const ma of MA) {
      expect(
        khoi.some((k) => k.includes(`--color-u-${ma}:`)),
        `--color-u-${ma} không nằm trong khối \`:root\` nào`,
      ).toBe(true)
    }
  })
})
