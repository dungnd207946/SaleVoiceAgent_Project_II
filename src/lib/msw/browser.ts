/**
 * Bật MSW ở trình duyệt. Chỉ chạy khi `VITE_MSW !== '0'` — build production
 * không bao giờ nạp file này (xem `main.tsx`, import động).
 */
import { setupWorker } from 'msw/browser'
import { HANDLERS } from './handlers'

export const worker = setupWorker(...HANDLERS)

export async function startMsw(): Promise<void> {
  await worker.start({
    // Request nào không có handler thì đi thẳng ra mạng — nhờ vậy khi M2a-BE
    // có endpoint thật, bật/tắt từng seam được mà không phải tắt cả MSW.
    onUnhandledRequest: 'bypass',
    quiet: true,
  })
}
