import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { urlAvatar, uocLuongGiayNoi } from '@/features/platform/avatarLipSync'
import { SanKhauAgent } from '@/features/platform/components/SanKhauAgent'

/**
 * Công tắc người dẫn: `VITE_AVATAR_WS_URL` có ⇒ người dẫn LIP SYNC (MuseTalk),
 * vắng ⇒ người dẫn Kling cũ. `vitest.setup.ts` đặt biến về rỗng cho mọi tệp;
 * ở đây bật lại cho riêng từng bài rồi trả về.
 */
describe('sân khấu — người dẫn lip sync', () => {
  afterEach(() => {
    vi.stubEnv('VITE_AVATAR_WS_URL', '')
  })

  it('có VITE_AVATAR_WS_URL ⇒ người dẫn lip sync, hiện ảnh chờ đã tách nền', () => {
    vi.stubEnv('VITE_AVATAR_WS_URL', 'ws://localhost:8020/avatar')
    render(<SanKhauAgent />)
    const nguoi = screen.getByTestId('nguoi-dan')
    expect(nguoi).toHaveAttribute('data-lip-sync', '1')
    expect(nguoi.querySelector('img')?.getAttribute('src')).toBe('/nhan-vat-lipsync.png')
    // Không còn hai <video> của clip Kling.
    expect(nguoi.querySelector('video')).toBeNull()
  })

  it('đường dẫn tương đối (bản deploy) ⇒ wss/ws CÙNG ORIGIN qua nginx của portal', () => {
    vi.stubEnv('VITE_AVATAR_WS_URL', '/lipsync/avatar')
    expect(urlAvatar()).toBe(`ws://${window.location.host}/lipsync/avatar`)
    vi.stubEnv('VITE_AVATAR_WS_URL', 'ws://localhost:8020/avatar')
    expect(urlAvatar()).toBe('ws://localhost:8020/avatar') // máy dev: nối thẳng
  })

  it('vắng biến ⇒ giữ người dẫn Kling cũ', () => {
    render(<SanKhauAgent />)
    const nguoi = screen.getByTestId('nguoi-dan')
    expect(nguoi).not.toHaveAttribute('data-lip-sync')
    expect(nguoi.querySelector('img')?.getAttribute('src')).toBe('/nguoi-dan-nghi.webp')
  })
})

describe('ước lượng độ dài câu (không đưa tay sát cuối câu)', () => {
  it('khớp độ dài audio OmniVoice thật trong log TTS (±10%)', () => {
    // [text, giây audio thật] — log tts-omnivoice 2026-10-14
    const mau: [string, number][] = [
      ['Anh Thế muốn em giới thiệu chi tiết dự án nào ạ?', 2.72],
      ['Anh chị còn muốn tìm hiểu thêm gì, hay muốn em đặt lịch xem dự án không ạ?', 4.2],
      ['Em xin phép ngắt máy nhé, khi nào cần anh chị cứ gọi lại bên em.', 3.6],
    ]
    for (const [text, giay] of mau) {
      expect(Math.abs(uocLuongGiayNoi(text) - giay) / giay).toBeLessThan(0.1)
    }
  })

  it('bỏ khoảng trắng đầu/cuối, câu rỗng = 0', () => {
    expect(uocLuongGiayNoi('   ')).toBe(0)
    expect(uocLuongGiayNoi('  abc  ')).toBe(uocLuongGiayNoi('abc'))
  })
})
