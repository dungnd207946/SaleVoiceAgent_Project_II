/** Màn «Chuyển sale» (`/chuyen-sale`) — hộp thư ca agent đã hứa gọi lại. */
import { StrictMode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { http, HttpResponse } from 'msw'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'
import { boGiaLap, giaLapManHinh } from './man-hinh'

function boot(path = '/chuyen-sale') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(
    <StrictMode>
      <QueryClientProvider client={qc}>
        <LangProvider>
          <RouterProvider router={router} />
        </LangProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
}

/** Cột danh sách bên trái — `screen` bắt cả dropdown lọc lẫn khối chi tiết. */
function cotTrai(): HTMLElement {
  return screen.getByLabelText('Trang sau').closest('div')!.parentElement as HTMLElement
}

const nutSapXep = () => screen.getByRole('button', { name: 'Cũ nhất trước' })

describe('Chuyển sale — chip dự án', () => {
  it('hàng danh sách hiện TÊN dự án, không hiện mã', async () => {
    // Đảo quyết định cũ («chip ngắn nên dùng mã»): mã của tenant thật là một UUID
    // 36 ký tự (`DCAC8A12_705D_…`), dài hơn mọi tên dự án và không nói gì với
    // người trực. Lý do «chật chỗ» chỉ ra đúng chiều ngược lại.
    boot()
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    expect(within(cotTrai()).getAllByText('Sunshine Green Iconic')[0]).toHaveClass('rounded-full')
    expect(within(cotTrai()).queryByText('SGI')).not.toBeInTheDocument()
  })

  it('ca CÓ avatar backend vẫn hiện chữ cái, không <img>', async () => {
    // (2026-08-25, đảo chốt 2026-08-21) Lịch sử hội thoại/ca chuyển sale thôi
    // dùng avatar backend — chữ cái từ ĐẦU + CUỐI của tên, như bảng Thành viên.
    // Backend vẫn trả `avatar`, FE thôi đọc. Ghi đè bằng `server.use`: canh đúng
    // ranh «có avatar cũng không ra ảnh».
    const AVATAR_THU =
      "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D'http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg'%2F%3E"
    server.use(
      http.get('/api/v1/escalations', () =>
        HttpResponse.json({
          items: [
            {
              id: 99,
              sessionId: 's-avatar',
              phone: '0912448111',
              ten: 'Minh Anh',
              avatar: AVATAR_THU,
              duAn: null,
              tenDuAn: null,
              toolThieuDuLieu: null,
              summary: null,
              summaryLuc: null,
              messageSeq: null,
              trangThai: 'new',
              nguoiXuLy: null,
              xuLyLuc: null,
              ghiChu: null,
              kenh: null,
              soLuot: 1,
              taoLuc: '2026-07-27T14:32:11+07:00',
            },
          ],
          tongCa: 1,
          duAnCo: [],
        }),
      ),
    )
    boot()
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    await waitFor(() => expect(within(cotTrai()).getByText('MA')).toBeInTheDocument())
    expect(document.querySelector(`img[src="${AVATAR_THU}"]`)).not.toBeInTheDocument()
  })

  it('dự án chưa có hàng trong KB thì chip rơi về mã, không nói «Chưa rõ»', async () => {
    // `escalations.project` không có FK — mã có thể trỏ vào dự án đã xoá. Nói
    // «Chưa rõ dự án» ở đó là bỏ mất thông tin duy nhất còn lại.
    boot()
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    expect(within(cotTrai()).getAllByText('NCR')[0]).toHaveClass('rounded-full')
  })
})

describe('Chuyển sale — khung và phân trang', () => {
  it('khung chốt chiều cao, không co theo số ca', async () => {
    boot()
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    const khung = screen.getByLabelText('Trang sau').closest('.rounded-xl') as HTMLElement
    expect(khung).toHaveClass('h-[calc(100vh-120px)]', 'flex', 'flex-col')
  })

  it('danh sách ca cuộn trong khung, thanh phân trang không trôi theo', async () => {
    boot()
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    const thanh = screen.getByLabelText('Trang sau').closest('div') as HTMLElement
    expect(thanh).toHaveClass('shrink-0')

    const cot = thanh.parentElement as HTMLElement
    expect(cot).toHaveClass('flex', 'min-h-0', 'flex-col')
    expect(within(cot).getAllByText('Nguyễn Minh Anh')[0]!.closest('.overflow-y-auto')).toBeTruthy()
  })
})

describe('Chuyển sale — lịch sử ghi chú', () => {
  it('khối chi tiết hiện từng lần ghi kèm người và giờ, không chỉ bản cuối', async () => {
    boot()

    await screen.findByText('Gọi lần 1 không nghe, nhắn Zalo rồi.')
    expect(screen.getByText('Khách gọi lại, hẹn gửi mã hợp đồng chiều nay.')).toBeInTheDocument()
    const moc = screen.getAllByRole('listitem')
    expect(moc.length).toBeGreaterThanOrEqual(5)
    expect(screen.getByText('Lê Biên Tập')).toBeInTheDocument()
    expect(screen.getByText('Phạm Thu Hà')).toBeInTheDocument()
  })

  it('hộp đánh dấu xong để ô trống, không đổ sẵn ghi chú của người trước', async () => {
    boot()
    await userEvent.click(await screen.findByText('Khách chưa cho tên'))
    await userEvent.click(await screen.findByRole('button', { name: 'Đánh dấu xong' }))

    const hop = within(screen.getByRole('dialog'))
    expect(hop.getByText('Khách hẹn gọi lại sau 17h.')).toBeInTheDocument()

    expect(hop.getByLabelText('Ghi chú kết quả')).toHaveValue('')
  })
})

describe('Chuyển sale — tab, sắp xếp, lọc dự án', () => {
  it('có bốn tab: Chưa liên hệ · Đang xử lý · Xong · Tất cả', async () => {
    boot()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Xong' })).toBeInTheDocument())

    for (const nhan of ['Chưa liên hệ', 'Đang xử lý', 'Xong', 'Tất cả']) {
      expect(screen.getByRole('button', { name: nhan })).toBeInTheDocument()
    }
  })

  it('tab Xong tách khỏi Đang xử lý', async () => {
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Xong' }))

    await waitFor(() => expect(within(cotTrai()).getByText('Trần Bảo Long')).toBeInTheDocument())
    expect(within(cotTrai()).queryByText('Khách chưa cho tên')).not.toBeInTheDocument()
  })

  it('dropdown dự án hiện TÊN làm nhãn, value vẫn là mã, lọc thì đổi danh sách', async () => {
    boot()
    const o = await screen.findByLabelText('Lọc theo dự án')
    const muc = within(o).getByRole('option', { name: 'Sunshine Green Iconic' })
    expect(muc).toHaveValue('SGI')

    await userEvent.selectOptions(o, 'NCR')

    await waitFor(() =>
      expect(within(cotTrai()).queryByText('Nguyễn Minh Anh')).not.toBeInTheDocument(),
    )
    expect(
      within(screen.getByLabelText('Lọc theo dự án')).getByRole('option', {
        name: 'Sunshine Green Iconic',
      }),
    ).toBeInTheDocument()
  })

  it('nút Cũ nhất trước đảo thứ tự, bấm lại thì thôi', async () => {
    boot()
    await waitFor(() => expect(nutSapXep()).toHaveAttribute('aria-pressed', 'false'))

    await userEvent.click(nutSapXep())
    await waitFor(() => expect(nutSapXep()).toHaveAttribute('aria-pressed', 'true'))

    await userEvent.click(nutSapXep())
    await waitFor(() => expect(nutSapXep()).toHaveAttribute('aria-pressed', 'false'))
  })
})

describe('Chuyển sale — mở transcript', () => {
  it('link mang theo session của ĐÚNG ca, không chỉ số điện thoại', async () => {
    boot()
    const link = await screen.findByRole('link', { name: /Mở transcript/ })

    expect(link).toHaveAttribute('href', expect.stringContaining('session=s-anh-3'))
  })

  it('ca chưa có số vẫn deep-link đúng phiên, không rơi vào nhóm chung', async () => {
    boot()
    await userEvent.click(await screen.findByText('Khách chưa cho tên'))
    const link = await screen.findByRole('link', { name: /Mở transcript/ })

    expect(link).toHaveAttribute('href', expect.stringMatching(/\/convos\/_\?.*session=s-an-1/))
  })
})

describe('Chuyển sale — mobile', () => {
  afterEach(boGiaLap)

  it('không có ?ca= ⇒ CHỈ danh sách (không nhảy vào ca đầu)', async () => {
    giaLapManHinh(375)
    boot()
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '‹ Danh sách' })).not.toBeInTheDocument()
    expect(screen.getByText('Tất cả ca')).toBeInTheDocument()
  })

  it('có ?ca= ⇒ CHỈ chi tiết; «‹ Danh sách» về lại danh sách', async () => {
    giaLapManHinh(375)
    // `?ca=` phải trỏ vào một ca THẬT CÓ trong trang hiện tại (tab mặc định
    // `all` ⇒ mọi id trong `CA_GIA` khớp) — sau khi sửa Important #1, một
    // `?ca=` không khớp không còn rơi về `items[0]` để giả vờ có chi tiết.
    boot('/chuyen-sale?ca=12')
    await screen.findByRole('button', { name: '‹ Danh sách' })
    // T9 (deferred minor): danh sách phải THỰC SỰ ẩn lúc chi tiết đang hiện,
    // không chỉ suy từ việc «‹ Danh sách» có mặt.
    expect(screen.queryByLabelText('Trang sau')).not.toBeInTheDocument()
    expect(screen.queryByText('Tất cả ca')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '‹ Danh sách' }))
    await waitFor(() => expect(screen.getByLabelText('Trang sau')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: '‹ Danh sách' })).not.toBeInTheDocument()
  })

  it('nhận ca xong trên mobile: ĐỨNG LẠI ở ca vừa nhận, không lặng lẽ hiện ca khác', async () => {
    // Repro của final-review.md Important #1: tab «Chưa liên hệ» (?tab=new), mở
    // ca 12 (?ca=12), bấm «Nhận ca này». Ca 12 rời tab `new` nên không còn khớp
    // trang đang lọc. Trước Important #1 `dangMo` rơi về `items[0]` (một ca `new`
    // KHÁC, cùng bộ nút); bản vá đầu đẩy về danh sách — số vừa nhận biến mất
    // đúng lúc cần gọi (critique 05/10). Nay ca vừa nhận được GHIM, ở trạng thái
    // mới, kèm câu báo.
    giaLapManHinh(375)
    boot('/chuyen-sale?tab=new&ca=12')
    expect(await screen.findByText('Nguyễn Minh Anh')).toBeInTheDocument()
    expect(screen.queryByLabelText('Trang sau')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Nhận ca này' }))

    expect(await screen.findByText('Đã nhận ca Nguyễn Minh Anh.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '‹ Danh sách' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Đánh dấu xong' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Nhận ca này' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Trang sau')).not.toBeInTheDocument()

    // Trả về như cũ cho các bài sau trong file (`CA_GIA` là trạng thái module).
    await userEvent.click(screen.getByRole('button', { name: 'Hoàn tác' }))
    expect(await screen.findByRole('button', { name: 'Nhận ca này' })).toBeInTheDocument()
  })
})

describe('Chuyển sale — polish 05/10', () => {
  it('tiêu đề cột danh sách nói đúng tab đang mở', async () => {
    boot('/chuyen-sale?tab=done')
    expect(await screen.findByText('Ca đã xong')).toBeInTheDocument()
    expect(screen.queryByText('Ca cần gọi lại')).not.toBeInTheDocument()
  })

  it('tên đọc được của hàng mở đầu bằng TÊN khách (không phải chữ cái avatar), chip kỹ năng nói «thiếu dữ liệu»', async () => {
    boot('/chuyen-sale?tab=new')
    const hang = await screen.findAllByRole('button', { name: /^Nguyễn Minh Anh/ })
    expect(hang.length).toBeGreaterThan(0)
    expect(hang.some((h) => /Thiếu dữ liệu: Tìm & gợi ý căn/.test(h.textContent ?? ''))).toBe(true)
  })
})
