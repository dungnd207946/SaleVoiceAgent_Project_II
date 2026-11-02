import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { FeedbackReviewCard } from '@/features/quality/components/FeedbackReviewCard'
import type { Feedback } from '@/features/quality/api'

function dung(feedback: Feedback) {
  const rootRoute = createRootRoute({
    component: () => <FeedbackReviewCard feedback={feedback} />,
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

const CO_DU: Feedback = {
  id: 1,
  sessionId: 'sess_1',
  rating: 2,
  comment: 'Trả lời chậm.',
  createdAt: '2026-08-12T09:00:00+07:00',
  customerName: 'Trần Văn A',
  phone: '0912345678',
  source: 'chat',
}

describe('FeedbackReviewCard', () => {
  // Lưu ý: `RouterProvider` render lần đầu ở trạng thái "pending" rồi mới
  // khớp route (microtask) — mọi test file khác trong repo dùng khuôn này
  // (`convos-phien.test.tsx`, `convos-list.test.tsx`) đều `await
  // screen.findByText(...)` cho truy vấn ĐẦU TIÊN sau mỗi lần `dung()`, các
  // truy vấn sau đó trong cùng test mới dùng `getByText`/`queryByText` đồng
  // bộ vì DOM đã ổn định.

  it('hiện đầy đủ tên + sđt, KHÔNG che', async () => {
    dung(CO_DU)
    expect(await screen.findByText('Trần Văn A')).toBeInTheDocument()
    expect(screen.getByText('0912345678')).toBeInTheDocument()
  })

  it('rating <= 2 hiện badge "Cần chú ý", rating > 2 thì không', async () => {
    // `render()` không tự unmount cây trước khi gọi lại trong CÙNG một test
    // (auto-cleanup của testing-library chỉ chạy GIỮA các `it`, không phải
    // giữa hai lần `render` trong một `it`) — không `unmount()` cây đầu thì
    // "Cần chú ý" của lần render rating=2 vẫn còn trong `document.body` khi
    // kiểm lần render rating=5, làm bài test luôn xanh giả (không bắt được
    // điều kiện lật ngược).
    const lanDau = dung(CO_DU)
    expect(await screen.findByText('Cần chú ý')).toBeInTheDocument()
    lanDau.unmount()

    dung({ ...CO_DU, rating: 5 })
    await screen.findByText('Trần Văn A')
    expect(screen.queryByText('Cần chú ý')).not.toBeInTheDocument()
  })

  it('không có tên/sđt hiện "Khách ẩn danh", không link sang Hội thoại', async () => {
    dung({ ...CO_DU, customerName: null, phone: null })
    expect(await screen.findByText('Khách ẩn danh')).toBeInTheDocument()
    expect(screen.queryByText(/Xem phiên trò chuyện/i)).not.toBeInTheDocument()
  })

  it('comment rỗng hiện chữ thay thế', async () => {
    dung({ ...CO_DU, comment: '' })
    expect(await screen.findByText('(không để lại nhận xét)')).toBeInTheDocument()
  })

  it('hiện chip kênh của phiên (Chat / Voice), đứng trước link sang Hội thoại', async () => {
    const lanDau = dung(CO_DU)
    expect(await screen.findByText('Chat')).toBeInTheDocument()
    lanDau.unmount()

    dung({ ...CO_DU, source: 'voice' })
    expect(await screen.findByText('Voice')).toBeInTheDocument()
    expect(screen.queryByText('Chat')).not.toBeInTheDocument()
  })

  it('chip Chat và Voice mang HAI sắc khác nhau, không cùng một màu xám', async () => {
    // jsdom không tính CSS thật nên chỉ khoá được lớp token (cùng lối
    // `tests/o-chon.test.ts`). Điều đang bảo vệ: hai kênh phải phân biệt được
    // bằng MÀU, không chỉ bằng chữ — người dùng quét danh sách bằng mắt trước
    // khi đọc nhãn.
    const lanDau = dung(CO_DU)
    const chat = await screen.findByText('Chat')
    expect(chat).toHaveClass('bg-badge-kenh-chat-bg', 'text-badge-kenh-chat-fg')
    lanDau.unmount()

    dung({ ...CO_DU, source: 'voice' })
    const voice = await screen.findByText('Voice')
    expect(voice).toHaveClass('bg-badge-kenh-voice-bg', 'text-badge-kenh-voice-fg')
  })

  it('KHÔNG biết kênh (agent bản cũ / chưa có hàng conversations) ⇒ không vẽ chip bịa', async () => {
    dung({ ...CO_DU, source: null })
    await screen.findByText('Trần Văn A')
    expect(screen.queryByText('Chat')).not.toBeInTheDocument()
    expect(screen.queryByText('Voice')).not.toBeInTheDocument()
  })

  it('kênh lạ (backend thêm kênh mới) ⇒ vẫn hiện NGUYÊN VĂN, không nuốt mất', async () => {
    // `conversations.source` là `text` không CHECK có chủ ý — ngày agent gửi
    // `zalo` thì màn này phải nói được "zalo", không phải im lặng bỏ qua.
    dung({ ...CO_DU, source: 'zalo' })
    expect(await screen.findByText('zalo')).toBeInTheDocument()
  })

  it('có phone thì link kèm đúng session_id qua search param', async () => {
    dung(CO_DU)
    const link = (await screen.findByText(/Xem phiên trò chuyện/i)).closest('a')
    expect(link).toHaveAttribute('href', expect.stringContaining('session=sess_1'))
  })
})
