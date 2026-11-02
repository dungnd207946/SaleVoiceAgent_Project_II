/**
 * Màn `kb` — Tài liệu (M6). Nguồn nghiệp vụ: KB_01.
 *
 * Bốn thứ màn này phải giữ:
 *   · Trạng thái từng file hiện RÕ (§I.2) — "không để khách tưởng upload xong là
 *     agent biết ngay"
 *   · Lỗi nói LÝ DO VÀ CÁCH SỬA, không chỉ chữ "Lỗi" (§II.3)
 *   · Kho rỗng KHÔNG hiện như lỗi (BR04) — nó là trạng thái bình thường
 *   · Xoá nói rõ agent sẽ thôi dùng, và không có thùng rác (BR07)
 */
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

const SAN_SANG = {
  id: 1,
  tenFile: 'chinh-sach.pdf',
  loai: 'pdf',
  kichThuoc: 10240,
  state: 'san_sang',
  chunkCount: 12,
  loiMessage: '',
  uploadedAt: '2026-07-31T09:00:00Z',
  uploadedBy: 'u_dang',
}
const LOI = {
  ...SAN_SANG,
  id: 2,
  tenFile: 'anh-scan.pdf',
  state: 'loi',
  chunkCount: 0,
  loiMessage: 'File này không có lớp chữ — có thể là ảnh scan. Hãy nạp bản có chữ.',
}
const DANG_XU_LY = { ...SAN_SANG, id: 3, tenFile: 'moi.docx', state: 'dang_xu_ly', chunkCount: 0 }

function datApi(ds: unknown[]) {
  server.use(http.get('/api/v1/kb/files', () => HttpResponse.json(ds)))
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

describe('màn Tài liệu — danh sách và trạng thái', () => {
  it('hiện tên file và ba trạng thái bằng nhãn tiếng Việt', async () => {
    datApi([SAN_SANG, LOI, DANG_XU_LY])
    boot()

    expect(await screen.findByText('chinh-sach.pdf')).toBeInTheDocument()
    expect(screen.getByText('Sẵn sàng')).toBeInTheDocument()
    expect(screen.getByText('Lỗi')).toBeInTheDocument()
    expect(screen.getByText('Đang xử lý')).toBeInTheDocument()
    // Tên kỹ thuật không lộ ra giao diện.
    expect(screen.queryByText('san_sang')).not.toBeInTheDocument()
  })

  it('lỗi hiện LÝ DO, không chỉ chữ "Lỗi"', async () => {
    // KB_01 §II.3: "Lỗi phải kèm lý do và cách sửa". Đây là chỗ khách tự sửa
    // được hoặc phải gọi hỗ trợ — chênh nhau đúng một câu.
    datApi([LOI])
    boot()

    expect(await screen.findByText(/không có lớp chữ/)).toBeInTheDocument()
    expect(screen.getByText(/nạp bản có chữ/)).toBeInTheDocument()
  })

  it('Đang xử lý nói rõ agent CHƯA dùng được tài liệu này', async () => {
    // §I.2: "không để khách tưởng upload xong là agent biết ngay".
    datApi([DANG_XU_LY])
    boot()

    expect(await screen.findByText(/agent chưa dùng/i)).toBeInTheDocument()
  })
})

describe('màn Tài liệu — kho rỗng', () => {
  it('kho rỗng hiện HƯỚNG DẪN, không hiện như lỗi', async () => {
    // BR04. Một thông báo đỏ ở lần mở đầu tiên là sai — mọi workspace mới đều
    // gặp trạng thái này.
    datApi([])
    boot()

    expect(await screen.findByText(/chưa có tài liệu nào/i)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('lỗi hạ tầng nói KHÁC kho rỗng', async () => {
    // Backend chết mà UI hiện "chưa có tài liệu nào" thì khách đi nạp lại tài
    // liệu họ đã nạp rồi, và không ai báo sự cố.
    server.use(http.get('/api/v1/kb/files', () => new HttpResponse(null, { status: 500 })))
    boot()

    expect(await screen.findByText(/không tải được danh sách tài liệu/i)).toBeInTheDocument()
  })
})

describe('màn Tài liệu — xoá', () => {
  it('xoá phải xác nhận, và popup nói rõ agent sẽ thôi dùng', async () => {
    // BR07: không thùng rác, không hoàn tác. Người dùng phải biết điều đó TRƯỚC
    // khi bấm, không phải sau.
    datApi([SAN_SANG])
    boot()
    await screen.findByText('chinh-sach.pdf')

    await userEvent.click(screen.getByRole('button', { name: /xoá/i }))

    expect(await screen.findByText(/agent sẽ thôi dùng/i)).toBeInTheDocument()
    expect(screen.getByText(/không hoàn tác/i)).toBeInTheDocument()
  })

  it('huỷ trong popup thì KHÔNG gọi API xoá', async () => {
    let daGoi = false
    datApi([SAN_SANG])
    server.use(
      http.delete('/api/v1/kb/files/:id', () => {
        daGoi = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot()
    await screen.findByText('chinh-sach.pdf')
    await userEvent.click(screen.getByRole('button', { name: /xoá/i }))

    await userEvent.click(screen.getByRole('button', { name: /huỷ/i }))

    expect(daGoi).toBe(false)
  })
})

/**
 * ĐƯỜNG TẢI LÊN TRƯỚC ĐÂY KHÔNG CÓ BÀI NÀO — cả đường thành công lẫn đường
 * hỏng. Nên lỗi dưới đây sống được: ô kéo thả nhận `multiple`, mỗi tệp `mutate`
 * riêng trên CÙNG một mutation, mà `onSuccess` lại đặt câu báo hỏng về rỗng —
 * một tệp bất kỳ xong sau một tệp hỏng là câu báo hỏng biến mất.
 */
describe('màn Tài liệu — tải lên nhiều tệp', () => {
  function tep(ten: string) {
    return new File(['x'], ten, { type: 'application/pdf' })
  }

  it('một tệp hỏng giữa lô KHÔNG bị tệp thành công xoá mất câu báo', async () => {
    // PHÂN BIỆT HAI TỆP BẰNG THỨ TỰ GỌI, không đọc `request.formData()`: trong
    // jsdom, body multipart do `fetch` sinh ra không kèm `Content-Type` mà
    // undici chấp nhận, nên `formData()` NÉM. Bản đầu của bài này đọc form và vì
    // thế cả hai request cùng hỏng — bài xanh, nhưng xanh vì mọi thứ đều lỗi chứ
    // không vì lỗi được giữ lại. Một bài xanh sai lý do tệ hơn không có bài.
    let ds: (typeof SAN_SANG)[] = []
    let lan = 0
    server.use(
      http.get('/api/v1/kb/files', () => HttpResponse.json(ds)),
      http.post('/api/v1/kb/files', async () => {
        lan += 1
        // Tệp thứ nhất hỏng NGAY, tệp thứ hai xong SAU — đúng thứ tự khiến
        // `onSuccess` xoá mất câu báo hỏng ở bản trước.
        if (lan === 1)
          return HttpResponse.json(
            { error: { code: 'UNPROCESSABLE', message: 'Tệp vượt quá dung lượng cho phép.' } },
            { status: 422 },
          )
        await new Promise((r) => setTimeout(r, 30))
        ds = [{ ...SAN_SANG, id: 9, tenFile: 'lanh.pdf' }]
        return HttpResponse.json(ds[0])
      }),
    )
    boot()
    await screen.findByText(/Chưa có tài liệu nào/i)

    await userEvent.upload(screen.getByLabelText(/kéo thả/i), [tep('hong.pdf'), tep('lanh.pdf')])

    // ① Tệp lành lên xong THẬT — hàng của nó có mặt. Thiếu phép kiểm này thì
    //    phép kiểm ② thành rỗng nghĩa: lỗi còn đó chỉ vì chưa có gì xoá nó.
    expect(await screen.findByText('lanh.pdf')).toBeInTheDocument()
    // ② …mà câu báo hỏng VẪN còn, và nó mang tên tệp: một lô ba tệp thì «lỗi»
    //    trần không nói được tệp nào đã rơi.
    expect(screen.getByText(/hong\.pdf/)).toBeInTheDocument()
  })
})

/**
 * Ghim danh sách loại tệp — phải khớp `LOAI_HO_TRO` bên backend
 * (`modules/kb/contracts.py`). Thêm loại mới bên backend mà quên sửa đây thì
 * ô kéo thả nói dối và bộ lọc của trình chọn tệp ẨN loại mới khỏi người dùng.
 */
describe('màn Tài liệu — loại tệp được chấp nhận', () => {
  it('chữ hướng dẫn và bộ lọc trình chọn tệp cùng liệt kê .md', async () => {
    datApi([])
    boot()
    await screen.findByText(/chưa có tài liệu nào/i)

    expect(screen.getByText('Kéo thả hoặc chọn tệp .pdf, .docx, .xlsx, .md')).toBeInTheDocument()
    expect(screen.getByLabelText(/kéo thả/i)).toHaveAttribute(
      'accept',
      '.pdf,.docx,.xlsx,.md',
    )
  })
})
