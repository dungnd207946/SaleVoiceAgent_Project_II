/**
 * Ghim hành vi mặc định của `WS_URL_CHAT_MAC_DINH`/`WS_URL_VOICE_MAC_DINH`
 * (`features/platform/api.ts`): không đặt `VITE_AGENT_WS_URL_CHAT`/`_VOICE`
 * thì hai hằng CÙNG ORIGIN với trang đang mở (`ws(s)://<host>/v1/{chat,voice}`) —
 * nginx của image chuyển `/v1/` sang gateway của chính môi trường (đổi 2026-10-01;
 * trước đó là hằng `wss://agent-uat.noble.vn` nên dev và uat dùng chung một gateway).
 *
 * Phải `stubEnv` chứ không import thẳng: vitest CÓ nạp `.env` của repo, và
 * `.env.example` còn khuyên dev đặt hai biến này để trỏ về agent chạy local —
 * bài đo giá trị mặc định mà đọc môi trường lập trình viên thì đỏ trên máy họ,
 * xanh trên CI, và không nói gì về thứ nó định canh.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

async function napLai() {
  vi.resetModules()
  return import('../src/features/platform/api')
}

describe('WS URL mặc định — không ghi đè bằng env thì đi theo origin của trang', () => {
  beforeEach(() => {
    vi.stubEnv('VITE_AGENT_WS_URL_CHAT', '')
    vi.stubEnv('VITE_AGENT_WS_URL_VOICE', '')
  })

  it('WS_URL_CHAT_MAC_DINH', async () => {
    const { WS_URL_CHAT_MAC_DINH } = await napLai()
    expect(WS_URL_CHAT_MAC_DINH).toBe(`ws://${window.location.host}/v1/chat`)
  })

  it('WS_URL_VOICE_MAC_DINH', async () => {
    const { WS_URL_VOICE_MAC_DINH } = await napLai()
    expect(WS_URL_VOICE_MAC_DINH).toBe(`ws://${window.location.host}/v1/voice`)
  })

  it('đặt biến thì hằng đi theo biến', async () => {
    vi.stubEnv('VITE_AGENT_WS_URL_CHAT', 'ws://localhost:9200/v1/chat')
    const { WS_URL_CHAT_MAC_DINH } = await napLai()
    expect(WS_URL_CHAT_MAC_DINH).toBe('ws://localhost:9200/v1/chat')
  })
})
