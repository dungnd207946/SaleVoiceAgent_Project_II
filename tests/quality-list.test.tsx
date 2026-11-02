import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { FeedbackList } from '@/features/quality/components/FeedbackList'
import { TONG_DANH_GIA_GIA } from '@/lib/msw/danhGiaGia'
import type { LocFeedback } from '@/features/quality/api'
import { server } from '../vitest.setup'

// Cùng khuôn `convos-phien.test.tsx`/`quality-review-card.test.tsx`: `RouterProvider`
// render "pending" trước rồi mới khớp route (microtask) — luôn `await
// screen.findByText(...)` cho truy vấn ĐẦU TIÊN sau mỗi lần `dung()`.
function dung(loc: LocFeedback = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const datLoc = vi.fn()
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={qc}>
        <FeedbackList loc={loc} datLoc={datLoc} />
      </QueryClientProvider>
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  const utils = render(<RouterProvider router={router} />)
  return { ...utils, datLoc }
}

describe('FeedbackList', () => {
  it('hiện dải thống kê và danh sách từ fake MSW', async () => {
    dung()
    expect(await screen.findByText('Nguyễn Minh Anh')).toBeInTheDocument()
    // `items` là 5 hàng mẫu, nhưng `total` KHÔNG suy từ chúng: backend tính
    // thống kê trên toàn bộ feedback của tenant bất kể phân trang/bộ lọc, và
    // fake đã theo đúng chiều đó từ 2026-08-14 (`lib/msw/danhGiaGia.ts`, dùng
    // chung với fake `/overview` để ô ③ Tổng quan và màn này không in hai con
    // số khác nhau). Đọc từ hằng, KHÔNG gõ lại `190` — gõ tay ở đây là dựng
    // lại đúng bản sao thứ hai vừa dọn đi.
    expect(screen.getByText(new RegExp(`${TONG_DANH_GIA_GIA} lượt đánh giá`))).toBeInTheDocument()
  })

  it('bấm chip sao gọi datLoc với rating tương ứng', async () => {
    const { datLoc } = dung()
    await screen.findByText('Nguyễn Minh Anh')
    await userEvent.click(screen.getByRole('button', { name: '5 sao' }))
    expect(datLoc).toHaveBeenCalledWith(expect.objectContaining({ ratings: [5] }))
  })

  it('bấm sao ĐANG chọn thì bỏ nó khỏi bộ lọc (multi-select), không thay thế', async () => {
    // loc.ratings = [5, 2] mô phỏng đang chọn hai sao — bấm lại 5 phải chỉ
    // bỏ 5, giữ 2. Nếu component lỡ coi chip là single-select (thay thế thay
    // vì gạn bớt), datLoc sẽ nhận [5] hoặc [] chứ không phải [2].
    const { datLoc } = dung({ ratings: [5, 2] })
    await screen.findByText('Nguyễn Minh Anh')
    await userEvent.click(screen.getByRole('button', { name: '5 sao' }))
    expect(datLoc).toHaveBeenCalledWith(expect.objectContaining({ ratings: [2] }))
  })

  it('bấm sao chưa chọn thì THÊM vào bộ lọc đang có, không xoá phần cũ', async () => {
    // ratings=[2] lọc MSW chỉ còn feedback của "Trần Quang" (rating 2 trong
    // fixture msw.ts) — không dùng "Nguyễn Minh Anh" (rating 5) làm mốc chờ
    // vì nó không có trong tập đã lọc.
    const { datLoc } = dung({ ratings: [2] })
    await screen.findByText('Trần Quang')
    await userEvent.click(screen.getByRole('button', { name: '5 sao' }))
    expect(datLoc).toHaveBeenCalledWith(expect.objectContaining({ ratings: [2, 5] }))
  })

  it('bấm "Tất cả" xoá hết bộ lọc sao', async () => {
    const { datLoc } = dung({ ratings: [5, 2] })
    await screen.findByText('Nguyễn Minh Anh')
    await userEvent.click(screen.getByRole('button', { name: 'Tất cả' }))
    // KHÔNG dùng `objectContaining({ ratings: undefined })`: component bỏ hẳn
    // khoá `ratings` (đúng luật `exactOptionalPropertyTypes`, xem `boSao()`),
    // và vitest — khác Jest — coi khoá vắng mặt và khoá mang `undefined` là
    // HAI THỨ KHÁC NHAU trong `objectContaining`. Đọc trực tiếp giá trị field
    // mới đúng ý "đã xoá bộ lọc" mà không phụ thuộc khoá có tồn tại hay không.
    expect(datLoc).toHaveBeenCalledTimes(1)
    expect(datLoc.mock.calls[0]![0].ratings).toBeUndefined()
  })

  it('lọc hết feedback (theoSao khác 0) thì hiện thông báo rỗng, không phải trắng trơn', async () => {
    // rating=6 không khớp fixture nào (msw.ts chỉ có 1-5) — mô phỏng ca đã lọc
    // về 0 kết quả mà KHÔNG phải backend lỗi, để chắc trạng thái rỗng khác
    // hẳn trạng thái lỗi (câu chữ khác nhau, xem component).
    dung({ ratings: [6] })
    expect(await screen.findByText('Chưa có feedback nào.')).toBeInTheDocument()
    expect(screen.queryByText('Không tải được feedback.')).not.toBeInTheDocument()
  })

  // Finding 4 (review cuối nhánh): fake MSW mặc định (msw.ts) LUÔN trả
  // `next_before_id: null`, nên trước bài này không test nào từng chạm nhánh
  // "còn trang sau" — cả nút VÀ hành vi cursor ở Finding 1/3 chưa ai canh.
  // Ghi đè `server.use(...)` (cùng khuôn `convos-phien.test.tsx`) để bật
  // đúng nhánh đó.
  function daiNextBeforeId(id: number) {
    server.use(
      http.get('/api/v1/agent/feedback', () =>
        HttpResponse.json({
          items: [
            {
              id: 5,
              session_id: 's-anh-1',
              rating: 5,
              comment: 'Trả lời nhanh, đúng ý.',
              created_at: '2026-08-12T09:00:00+07:00',
              customer_name: 'Nguyễn Minh Anh',
              phone: '0912448111',
            },
          ],
          next_before_id: id,
          total: 5,
          theo_sao: { '1': 1, '2': 1, '3': 1, '4': 1, '5': 1 },
          diem_trung_binh: 3,
        }),
      ),
    )
  }

  it('còn trang sau (next_before_id khác null) thì hiện nút, bấm gọi datLoc kèm beforeId mới', async () => {
    daiNextBeforeId(5)
    const { datLoc } = dung()
    await screen.findByText('Nguyễn Minh Anh')

    const nut = screen.getByRole('button', { name: 'Trang sau' })
    expect(nut).toBeInTheDocument()

    await userEvent.click(nut)
    expect(datLoc).toHaveBeenCalledWith(expect.objectContaining({ beforeId: 5 }))
  })

  it('đổi bộ lọc sao lúc cursor (beforeId) đang mở thì datLoc KHÔNG mang beforeId — không hỏi "N sao cũ hơn id X" một cách âm thầm (Finding 1)', async () => {
    // `loc.beforeId` đang set mô phỏng người dùng vừa bấm "Trang sau" một
    // lần rồi mới đổi lọc — đúng chuỗi hành động mô tả ở Finding 1.
    daiNextBeforeId(5)
    const { datLoc } = dung({ beforeId: 5 })
    await screen.findByText('Nguyễn Minh Anh')

    await userEvent.click(screen.getByRole('button', { name: '5 sao' }))

    expect(datLoc).toHaveBeenCalledTimes(1)
    const goiDau = datLoc.mock.calls[0]![0] as LocFeedback
    expect(goiDau.beforeId).toBeUndefined()
    expect(goiDau.ratings).toEqual([5])
  })
})
