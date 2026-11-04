/**
 * Khoá gateway dạng RÕ không được nằm lại trong localStorage.
 *
 * Bối cảnh: 2026-08-10 màn «Thử agent» bắt dán khoá thô vào một ô nhập, nên nó
 * lưu khoá xuống localStorage. 2026-08-11 ô dán đổi thành `<select>` chọn theo
 * tên và đường ĐỌC bị bỏ — đường GHI thì không. Từ đó tới 2026-08-27 portal ghi
 * một khoá `ody_ag_…` xuống máy người dùng mỗi lần bấm «Áp dụng» và không bao
 * giờ đọc lại: rủi ro giữ nguyên, lợi ích bằng không. Khoá đó mở được cả
 * `/runtime-credentials` = mật khẩu Postgres của tenant.
 *
 * Hai chiều phải canh, và chiều thứ hai mới là chiều quan trọng: DỌN cái đã có,
 * và KHÔNG GHI thêm nữa.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { donKhoaThoCu } from '../src/lib/donKhoaThoCu'

const KHOA_CHAT = 'thu-agent-gateway:cau-hinh'
const KHOA_VOICE = 'thu-agent-voice:cau-hinh'

function doc(p: string): string {
  return readFileSync(resolve(__dirname, '..', p), 'utf8')
}

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

describe('dọn khoá thô cũ', () => {
  it('xoá cả khoá chat lẫn khoá voice', () => {
    localStorage.setItem(
      KHOA_CHAT,
      JSON.stringify({ wsUrl: 'wss://x/v1/chat', apiKey: 'ody_ag_a' }),
    )
    localStorage.setItem(
      KHOA_VOICE,
      JSON.stringify({ wsUrl: 'wss://x/v1/voice', apiKey: 'ody_ag_b' }),
    )

    donKhoaThoCu()

    expect(localStorage.getItem(KHOA_CHAT)).toBeNull()
    expect(localStorage.getItem(KHOA_VOICE)).toBeNull()
  })

  it('KHÔNG đụng khoá của tính năng khác', () => {
    // `odyssey.lang` là ngôn ngữ người dùng chọn — dọn nhầm nó là đá người dùng
    // về tiếng Việt mỗi lần mở app.
    localStorage.setItem('odyssey.lang', 'en')
    localStorage.setItem(KHOA_CHAT, '{}')

    donKhoaThoCu()

    expect(localStorage.getItem('odyssey.lang')).toBe('en')
  })

  it('localStorage ném thì nuốt, không làm app chết lúc khởi động', () => {
    // Safari chặn site data ⇒ chính phép truy cập đã ném. Hàm này chạy ở
    // `main.tsx` TRƯỚC khi React mount, nên một lỗi ở đây là trang trắng.
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('SecurityError')
    })

    expect(() => donKhoaThoCu()).not.toThrow()
  })

  it('main.tsx gọi hàm dọn', () => {
    // `main.tsx` có side effect (createRoot, MSW) nên không import được trong
    // jsdom — quét văn bản, cùng lối `nap-lai-khi-chunk-hong`.
    expect(doc('src/main.tsx')).toMatch(/donKhoaThoCu\(\)/)
  })
})

describe('cổng: hai tệp gateway KHÔNG được ghi localStorage nữa', () => {
  // Đây là chiều dễ bị nối lại nhất: ai đó thấy `apiKey` phải gõ/chọn lại mỗi
  // lần mở màn và "tiện tay" lưu nó xuống. Bài này để cú đó đỏ ngay.
  it.each([['src/features/platform/chatGateway.ts'], ['src/features/platform/giongNoi.ts']])(
    '%s không gọi localStorage',
    (p) => {
      // Bóc chú thích trước: hai tệp có docstring GIẢI THÍCH vì sao bỏ
      // localStorage, và chữ đó không phải lời gọi.
      const nguon = doc(p)
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .replace(/\/\/.*$/gm, '')
      expect(nguon).not.toMatch(/localStorage/)
    },
  )
})
