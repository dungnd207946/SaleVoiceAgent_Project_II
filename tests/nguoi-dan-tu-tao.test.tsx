import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../vitest.setup'
import { urlAvatar } from '@/features/platform/avatarLipSync'
import { NguoiDanDialog } from '@/features/platform/components/NguoiDanDialog'
import { KhungNguoiDan } from '@/features/platform/components/NutNguoiDan'
import { RESET_NHAN_VAT_GIA } from '@/features/platform/mswNhanVat'
import type { NhanVat } from '@/features/platform/nhanVat'

// Upload thật dùng XHR + FormData mang `File` (để có tiến độ gửi). Trên Node 22 (image
// CI `node:22-alpine`) interceptor XHR của MSW không bao giờ gửi xong body chứa `File`
// của jsdom ⇒ request treo, không về `onload` (Node 24 thì chạy — vì thế máy dev xanh).
// Thay bằng `fetch` chỉ mang trường chữ: fake `/nhan-vat` vẫn nhận và dựng như thật.
vi.mock('@/features/platform/nhanVat', async (goc) => ({
  ...(await goc<object>()),
  taoNhanVat: async (dl: { ten: string; nguon: string }, onTienDo?: (p: number) => void) => {
    const f = new FormData()
    f.append('ten', dl.ten)
    f.append('nguon', dl.nguon)
    const r = await fetch('/api/v1/nhan-vat', { method: 'POST', body: f })
    onTienDo?.(1)
    return r.json()
  },
}))

/**
 * Người dẫn tự tạo (tab Voice): danh sách + chọn, wizard tạo (video | ảnh→AI), theo dõi
 * tiến độ, lỗi có hướng dẫn, và nhân vật đang dùng đi vào URL WebSocket lip sync.
 * Fake `/nhan-vat` CÓ TRẠNG THÁI (`mswNhanVat.ts`) — mỗi lần đọc một nhân vật đang dựng
 * là tiến độ lên một nấc.
 */

const SAN_SANG: NhanVat = {
  id: 'nv-a',
  ten: 'Chị Lan',
  nguon: 'video',
  trangThai: 'san_sang',
  buoc: null,
  tienDo: 1,
  loi: null,
  dangDung: false,
  avatarId: 'nv-aaaa',
  posterUrl: '/poster-lan.png',
  xemTruoc: [{ cau: 'Xin chào', url: '/api/v1/nhan-vat/nv-a/xem-truoc/0' }],
  taoLuc: '2026-10-07T00:00:00Z',
}

function boot(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => RESET_NHAN_VAT_GIA([]))
afterEach(() => {
  vi.useRealTimers()
  vi.stubEnv('VITE_AVATAR_WS_URL', '')
})

describe('URL lip sync theo nhân vật', () => {
  it('có avatarId ⇒ ?avatar=<id>; vắng ⇒ người dẫn mặc định; nối đúng dấu ?/&', () => {
    vi.stubEnv('VITE_AVATAR_WS_URL', 'ws://localhost:8020/avatar')
    expect(urlAvatar()).toBe('ws://localhost:8020/avatar')
    expect(urlAvatar(null)).toBe('ws://localhost:8020/avatar')
    expect(urlAvatar('nv-ab12')).toBe('ws://localhost:8020/avatar?avatar=nv-ab12')
    vi.stubEnv('VITE_AVATAR_WS_URL', 'ws://h/avatar?token=x')
    expect(urlAvatar('nv-ab12')).toBe('ws://h/avatar?token=x&avatar=nv-ab12')
  })

  it('lip sync tắt ⇒ không có nút Người dẫn, không gọi API', () => {
    let goi = 0
    server.use(http.get('/api/v1/nhan-vat/dang-dung', () => (goi++, HttpResponse.json({}))))
    boot(
      <KhungNguoiDan>
        <div>san khau</div>
      </KhungNguoiDan>,
    )
    expect(screen.queryByRole('button', { name: /Người dẫn/ })).toBeNull()
    expect(goi).toBe(0)
  })

  it('lip sync bật ⇒ nút mang tên nhân vật đang dùng, bấm mở hộp thoại', async () => {
    vi.stubEnv('VITE_AVATAR_WS_URL', 'ws://localhost:8020/avatar')
    RESET_NHAN_VAT_GIA([{ ...SAN_SANG, dangDung: true }])
    boot(
      <KhungNguoiDan>
        <div>san khau</div>
      </KhungNguoiDan>,
    )
    const nut = await screen.findByRole('button', { name: /Chị Lan/ })
    await userEvent.click(nut)
    expect(await screen.findByRole('heading', { name: 'Người dẫn' })).toBeInTheDocument()
  })
})

describe('hộp thoại Người dẫn', () => {
  it('danh sách có người dẫn mặc định + nhân vật đã tạo; chọn nhân vật ⇒ PUT đúng id', async () => {
    RESET_NHAN_VAT_GIA([SAN_SANG])
    const gui: unknown[] = []
    server.use(
      http.put('/api/v1/nhan-vat/dang-dung', async ({ request }) => {
        const body = (await request.json()) as { id: string | null }
        gui.push(body)
        return HttpResponse.json({
          id: body.id,
          ten: 'Chị Lan',
          avatarId: 'nv-aaaa',
          posterUrl: '/poster-lan.png',
        })
      }),
    )
    boot(<NguoiDanDialog onDong={() => {}} />)
    const ds = await screen.findByRole('list', { name: 'Danh sách người dẫn' })
    expect(within(ds).getByText('Người dẫn mặc định')).toBeInTheDocument()
    expect(within(ds).getByText('Đang dùng')).toBeInTheDocument() // mặc định đang dùng
    await userEvent.click(await within(ds).findByRole('button', { name: 'Dùng' }))
    await waitFor(() => expect(gui).toEqual([{ id: 'nv-a' }]))
  })

  it('tạo từ video: nút Tạo chỉ mở khi đủ tên + tệp + đồng ý, xong chuyển sang theo dõi tiến độ tới sẵn sàng', async () => {
    // Poll thật 3s/lần × 3 lần ≈ 9s — trên CI tải nặng vượt timeout. Đồng hồ giả từ đầu
    // test (để interval của react-query dùng timer giả) rồi tua; shouldAdvanceTime giữ
    // cho userEvent/MSW/waitFor vẫn chạy như thật.
    vi.useFakeTimers({ shouldAdvanceTime: true })
    boot(<NguoiDanDialog onDong={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: /Tạo người dẫn/ }))
    const tao = screen.getByRole('button', { name: 'Tạo người dẫn' })
    expect(tao).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Tên người dẫn'), 'Anh Minh')
    // Mặc định là «Tạo từ ảnh» khi dịch vụ AI có cấu hình ⇒ chọn nguồn video trước.
    expect(screen.getByRole('radio', { name: /Tạo từ ảnh bằng AI/ })).toBeChecked()
    await userEvent.click(screen.getByRole('radio', { name: /Tải video lên/ }))
    await userEvent.upload(
      screen.getByLabelText('Video chính'),
      new File(['v'], 'minh.mp4', { type: 'video/mp4' }),
    )
    expect(tao).toBeDisabled() // chưa đồng ý dùng hình ảnh
    await userEvent.click(screen.getByRole('checkbox'))
    expect(tao).toBeEnabled()
    await userEvent.click(tao)
    // Màn theo dõi: tiến độ chạy (fake đẩy 25%/lần đọc) tới khi sẵn sàng ⇒ có nút Dùng.
    expect(await screen.findByRole('status')).toBeInTheDocument()
    // Tua MỘT nhịp poll rồi chờ response của nhịp đó VỀ XONG mới tua tiếp. Tua dồn khi
    // request còn bay (CI tải nặng) thì react-query gộp các lần refetch lại — tiến độ
    // không lên mà vòng lặp đã hết. Không tua trong waitFor: tua luôn timeout của nó.
    const NUT = { name: 'Dùng nhân vật này' }
    let soLanDoc = 0
    const demDoc = ({ request }: { request: Request }) => {
      if (request.method === 'GET' && /\/api\/v1\/nhan-vat\/gia-/.test(request.url)) soLanDoc++
    }
    server.events.on('response:mocked', demDoc)
    try {
      for (let i = 0; i < 10 && !screen.queryByRole('button', NUT); i++) {
        const truoc = soLanDoc
        await act(() => vi.advanceTimersByTimeAsync(3000))
        await waitFor(
          () => {
            if (!screen.queryByRole('button', NUT)) expect(soLanDoc).toBeGreaterThan(truoc)
          },
          { timeout: 10000 },
        )
      }
    } finally {
      server.events.removeListener('response:mocked', demDoc)
    }
    expect(await screen.findByRole('button', NUT, { timeout: 10000 })).toBeInTheDocument()
  })

  it('chưa cấu hình AI ⇒ lựa chọn «Tạo từ ảnh» bị khoá', async () => {
    server.use(
      http.get('/api/v1/nhan-vat', () =>
        HttpResponse.json({
          nhanVat: [],
          dangDung: null,
          taoTuAnh: false,
          nhaCungCap: null,
          toiDa: 10,
          cauDemo: [],
        }),
      ),
    )
    boot(<NguoiDanDialog onDong={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: /Tạo người dẫn/ }))
    await waitFor(() =>
      expect(screen.getByRole('radio', { name: /Tạo từ ảnh bằng AI/ })).toBeDisabled(),
    )
    expect(screen.getByText('Chưa cấu hình dịch vụ AI tạo video.')).toBeInTheDocument()
  })

  it('dựng lỗi ⇒ hiện hướng dẫn sửa + Thử lại gọi đúng endpoint', async () => {
    RESET_NHAN_VAT_GIA([
      {
        ...SAN_SANG,
        id: 'nv-loi',
        ten: 'Video mờ',
        trangThai: 'loi',
        avatarId: null,
        posterUrl: null,
        xemTruoc: [],
        loi: { ma: 'KHONG_THAY_MAT', huongDan: 'Có đoạn không thấy rõ mặt.', chiTiet: '12 frame' },
      },
    ])
    let thuLai = 0
    server.use(
      http.post('/api/v1/nhan-vat/:id/thu-lai', ({ params }) => {
        thuLai++
        expect(params['id']).toBe('nv-loi')
        return HttpResponse.json({
          ...SAN_SANG,
          id: 'nv-loi',
          trangThai: 'dung',
          tienDo: 0.3,
          avatarId: null,
        })
      }),
    )
    boot(<NguoiDanDialog onDong={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Xem Video mờ' }))
    const loi = await screen.findByRole('alert')
    expect(loi).toHaveTextContent('Có đoạn không thấy rõ mặt.')
    expect(loi).toHaveTextContent('12 frame')
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    await waitFor(() => expect(thuLai).toBe(1))
  })

  it('nhân vật sẵn sàng ⇒ có video nói thử của câu demo', async () => {
    RESET_NHAN_VAT_GIA([SAN_SANG])
    const { container } = boot(<NguoiDanDialog onDong={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Xem Chị Lan' }))
    await screen.findByText('«Xin chào»')
    expect(container.ownerDocument.querySelector('video')?.getAttribute('src')).toBe(
      '/api/v1/nhan-vat/nv-a/xem-truoc/0',
    )
  })
})

describe('video gốc', () => {
  it('nhân vật có video nguồn ⇒ xem + tải về được, kể cả lúc đang dựng', async () => {
    RESET_NHAN_VAT_GIA([
      {
        ...SAN_SANG,
        id: 'nv-dang',
        ten: 'Đang dựng',
        nguon: 'anh',
        trangThai: 'dung',
        avatarId: null,
        xemTruoc: [],
        videoUrl: '/api/v1/nhan-vat/nv-dang/video/chinh',
      },
    ])
    const { container } = boot(<NguoiDanDialog onDong={() => {}} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Xem Đang dựng' }))
    await screen.findByText(/Video gốc/)
    expect(screen.getByText('Video AI tạo')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Tải về' })).toHaveAttribute(
      'href',
      '/api/v1/nhan-vat/nv-dang/video/chinh',
    )
    expect(container.ownerDocument.querySelector('details video')?.getAttribute('src')).toBe(
      '/api/v1/nhan-vat/nv-dang/video/chinh',
    )
  })
})
