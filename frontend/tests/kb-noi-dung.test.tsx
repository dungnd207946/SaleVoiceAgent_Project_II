/**
 * Xem lại nội dung ĐÃ NẠP (Task 15) — `GET /kb/files/:id/noi-dung` từ màn Tài
 * liệu chung.
 *
 * Markdown ở đây là NỘI DUNG KHÁCH TẢI LÊN, tức không tin được — phần lớn bài
 * dưới canh đúng chỗ đó: ảnh phải hiện thật, còn HTML/link độc hại thì không
 * được chạy hay bấm được.
 */
import { describe, expect, it } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'
import { Markdown } from '../src/features/kb/markdown'

const SAN_SANG = {
  id: 1,
  tenFile: 'so-tay.md',
  loai: 'md',
  kichThuoc: 10240,
  state: 'san_sang',
  chunkCount: 3,
  loiMessage: '',
  uploadedAt: '2026-07-31T09:00:00Z',
  uploadedBy: 'u_dang',
}

/** Đoạn máy chủ trả về — luôn có `overlapsPrev` từ Task 16. */
function doan(idx: number, text: string, sectionPath = '', overlapsPrev = false) {
  return { idx, text, sectionPath, overlapsPrev }
}

function datDanhSach(ds: unknown[]) {
  server.use(http.get('/api/v1/kb/files', () => HttpResponse.json(ds)))
}

function datNoiDung(id: number, doan: unknown[]) {
  server.use(http.get(`/api/v1/kb/files/${id}/noi-dung`, () => HttpResponse.json(doan)))
}

function boot() {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/kb'] }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

function renderMd(text: string) {
  return render(<Markdown text={text} />)
}

describe('Markdown — ảnh hiện thật', () => {
  it('`![alt](url)` render thành phần tử <img> thật, không phải link', () => {
    renderMd('Xem ảnh: ![Sơ đồ](https://portal.test/anh.png) hết.')
    const anh = screen.getByRole('img', { name: 'Sơ đồ' })
    expect(anh.tagName).toBe('IMG')
    expect(anh).toHaveAttribute('src', 'https://portal.test/anh.png')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('ảnh 404 không vỡ bố cục — chuyển sang chú thích thay vì icon vỡ để mặc định', () => {
    renderMd('![Sơ đồ](https://portal.test/mat.png)')
    const anh = screen.getByRole('img', { name: 'Sơ đồ' })
    fireEvent.error(anh)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText(/không tải được/i)).toBeInTheDocument()
  })
})

describe('Markdown — nội dung độc hại không chạy được', () => {
  it('thẻ HTML thô gõ tay chỉ là VĂN BẢN, không dựng thành DOM element', () => {
    const { container } = renderMd('Xem: <img src=x onerror=alert(1)> hết.')
    // Không dựng bất kỳ dangerouslySetInnerHTML nào — chuỗi bị coi là literal
    // text, browser sẽ không parse "<img...>" gõ tay thành phần tử thật.
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByText(/onerror=alert\(1\)/)).toBeInTheDocument()
  })

  it('`[bấm](javascript:...)` không ra một link bấm được', () => {
    renderMd('[bấm vào đây](javascript:alert(1))')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getByText('bấm vào đây')).toBeInTheDocument()
  })

  it('link http(s) hợp lệ vẫn bấm được bình thường', () => {
    renderMd('[trang chủ](https://portal.test/)')
    const a = screen.getByRole('link', { name: 'trang chủ' })
    expect(a).toHaveAttribute('href', 'https://portal.test/')
  })
})

describe('Markdown — ảnh cũng qua đúng bộ lọc scheme của link', () => {
  it('`![x](javascript:...)` không dựng thành <img src=javascript:...>', () => {
    renderMd('![x](javascript:alert(1))')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    // Không được biến mất im lặng — người xem phải thấy có gì đó bị chặn.
    expect(screen.getByText(/bị chặn/i)).toBeInTheDocument()
  })

  it('`![x](data:text/html;...)` không dựng thành <img>', () => {
    renderMd('![x](data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==)')
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
    expect(screen.getByText(/bị chặn/i)).toBeInTheDocument()
  })

  it('đường dẫn tương đối vẫn render <img> bình thường', () => {
    renderMd('![x](/files/anh.png)')
    const anh = screen.getByRole('img', { name: 'x' })
    expect(anh).toHaveAttribute('src', '/files/anh.png')
  })

  it('URL file công khai của chính portal (`/api/v1/public/files/...`) vẫn render được', () => {
    renderMd('![x](/api/v1/public/files/tenants/a1/anh.png)')
    const anh = screen.getByRole('img', { name: 'x' })
    expect(anh).toHaveAttribute('src', '/api/v1/public/files/tenants/a1/anh.png')
  })

  it('host ngoài hợp lệ (https) vẫn render được, kèm referrerPolicy để không lộ Referer', () => {
    renderMd('![x](https://cdn-cua-khach.example/anh.png)')
    const anh = screen.getByRole('img', { name: 'x' })
    expect(anh).toHaveAttribute('src', 'https://cdn-cua-khach.example/anh.png')
    expect(anh).toHaveAttribute('referrerpolicy', 'no-referrer')
  })
})

describe('màn Tài liệu — xem nội dung đã nạp', () => {
  it('mở được từ hàng san_sang, đoạn hiện ĐÚNG THỨ TỰ với mép rõ giữa các đoạn', async () => {
    datDanhSach([SAN_SANG])
    datNoiDung(1, [
      doan(0, '# so-tay.md\n\nĐoạn mở đầu.'),
      doan(1, 'Nội dung mục 1 kèm ![Ảnh 1](https://portal.test/a1.png).', 'Mục 1'),
      doan(2, 'Nội dung mục 2.', 'Mục 2'),
    ])
    boot()
    await screen.findByText('so-tay.md')

    await userEvent.click(screen.getByRole('button', { name: /xem nội dung/i }))

    const hopThoai = await screen.findByRole('dialog', { name: /so-tay\.md/i })
    const doanEls = within(hopThoai).getAllByTestId('doan')
    expect(doanEls).toHaveLength(3)

    // Đúng thứ tự: đoạn 0 trước đoạn 1 trước đoạn 2.
    expect(within(doanEls[0]!).getByText('Đoạn mở đầu.')).toBeInTheDocument()
    expect(within(doanEls[1]!).getByText('Mục 1')).toBeInTheDocument()
    expect(within(doanEls[2]!).getByText('Mục 2')).toBeInTheDocument()

    // Ảnh của đoạn giữa hiện THẬT.
    expect(within(doanEls[1]!).getByRole('img', { name: 'Ảnh 1' })).toBeInTheDocument()

    // Mép giữa các đoạn NHÌN THẤY ĐƯỢC, nhưng SUBTLE: mỗi đoạn từ đoạn thứ hai
    // trở đi có đường viền phân cách riêng — không phải một khối liền không
    // ranh giới, và cũng không phải khối tách bạch nặng nề.
    expect(doanEls[1]!.className).toMatch(/border-t/)
    expect(doanEls[2]!.className).toMatch(/border-t/)
  })

  it('đóng được bằng nút Đóng', async () => {
    datDanhSach([SAN_SANG])
    datNoiDung(1, [doan(0, 'Đoạn 0.')])
    boot()
    await screen.findByText('so-tay.md')
    await userEvent.click(screen.getByRole('button', { name: /xem nội dung/i }))
    await screen.findByRole('dialog', { name: /so-tay\.md/i })

    await userEvent.click(screen.getByRole('button', { name: /đóng/i }))

    expect(screen.queryByRole('dialog', { name: /so-tay\.md/i })).not.toBeInTheDocument()
  })

  it('đoạn trùng dòng đầu với đoạn trước được báo, không lặp lại y nguyên như một đoạn mới', async () => {
    datDanhSach([SAN_SANG])
    datNoiDung(1, [
      doan(0, 'Một câu văn khá dài để mượn lại ở đoạn kế tiếp.'),
      doan(
        1,
        'Một câu văn khá dài để mượn lại ở đoạn kế tiếp.\n\n![Ảnh](https://portal.test/a.png)',
        '',
        true,
      ),
      doan(2, 'Nội dung khác hẳn.'),
    ])
    boot()
    await screen.findByText('so-tay.md')
    await userEvent.click(screen.getByRole('button', { name: /xem nội dung/i }))
    const hopThoai = await screen.findByRole('dialog', { name: /so-tay\.md/i })

    const doanEls = within(hopThoai).getAllByTestId('doan')
    // Đoạn đầu không có dấu hiệu trùng lặp nào.
    expect(within(doanEls[0]!).queryByText(/trùng/i)).not.toBeInTheDocument()
    // Đoạn 1 tự báo phần mở đầu là lặp lại — không âm thầm hiện y như đoạn thường.
    expect(within(doanEls[1]!).getByText(/trùng/i)).toBeInTheDocument()
    // Đoạn không trùng gì thì không bị gắn nhãn.
    expect(within(doanEls[2]!).queryByText(/trùng/i)).not.toBeInTheDocument()
  })

  it('tài liệu chưa nạp xong (đang xử lý) không có nút xem', async () => {
    datDanhSach([{ ...SAN_SANG, state: 'dang_xu_ly', chunkCount: 0 }])
    boot()
    await screen.findByText('so-tay.md')

    expect(screen.queryByRole('button', { name: /xem nội dung/i })).not.toBeInTheDocument()
  })
})
