import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import type { ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { LocKhach } from '@/features/ops/api'
import { KhachList } from '@/features/ops/components/KhachList'
import { server } from '../vitest.setup'

/**
 * `KhachRow` bấm được bằng `<Link>` của tanstack-router — nó cần một
 * `RouterProvider` làm tổ tiên, nếu không `useRouter()` trả `null` và render
 * nổ (`Cannot read properties of null (reading 'isServer')`). Màn thật luôn có
 * `RouterProvider` ở gốc app; ở đây dựng một router tối giản chỉ để render
 * đúng `ui` được đưa vào — KHÔNG đi qua `routeTree.gen.ts` thật, vì test này
 * kiểm `<KhachList/>` độc lập với props tự tay, không qua `/convos` thật.
 */
function dungTrongRouter(ui: ReactElement) {
  const rootRoute = createRootRoute({ component: () => ui })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

function dung() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return dungTrongRouter(
    <QueryClientProvider client={qc}>
      <KhachList />
    </QueryClientProvider>,
  )
}

describe('màn danh sách khách', () => {
  it('hiện tên, số điện thoại và trích summary của từng khách', async () => {
    dung()
    expect(await screen.findByText('Nguyễn Minh Anh')).toBeInTheDocument()
    expect(screen.getByText(/0912448111/)).toBeInTheDocument()
    expect(screen.getByText(/chốt lịch xem nhà/i)).toBeInTheDocument()
  })

  it('khách không có tên thì hiện số làm tên, KHÔNG hiện «null»', async () => {
    dung()
    await screen.findByText('Nguyễn Minh Anh')
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument()
    expect(screen.getByText('0987112222')).toBeInTheDocument()
  })

  it('nhóm phone rỗng hiện là «Chưa có số», không phải một cái tên', async () => {
    dung()
    expect(await screen.findByText('Chưa có số')).toBeInTheDocument()
  })

  it('badge «Đã chuyển» chỉ ở khách có daChuyen', async () => {
    dung()
    await screen.findByText('Nguyễn Minh Anh')
    expect(screen.getAllByText(/đã chuyển/i)).toHaveLength(1)
  })

  it('hiện hai con số tổng cạnh thanh lọc', async () => {
    dung()
    expect(await screen.findByText(/3 khách/)).toBeInTheDocument()
    expect(screen.getByText(/5 phiên/)).toBeInTheDocument()
  })

  // ── Phân trang ──────────────────────────────────────────────────────────
  // Trước đây chỉ trang đầu (50 khách) tới được màn, và góc phải tự nói «Đang
  // xem 50 / 132 khách» để khỏi cắt cụt im lặng (FINDING 2, review cuối nhánh
  // M7). Nay các trang còn lại tới được qua `ThanhTrang`.

  function motKhach(phone: string) {
    return {
      phone,
      ten: `Khách ${phone}`,
      soPhien: 1,
      ganNhat: '2026-07-27T14:22:00+07:00',
      dauTien: '2026-07-14T16:40:00+07:00',
      daChuyen: false,
      summaryCuoi: null,
      duAn: null,
      tenDuAn: null,
    }
  }

  function dungVoi(loc: LocKhach, datLoc = vi.fn()) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    dungTrongRouter(
      <QueryClientProvider client={qc}>
        <KhachList loc={loc} datLoc={datLoc} />
      </QueryClientProvider>,
    )
    return datLoc
  }

  it('nhiều hơn một trang ⇒ thanh phân trang, bấm trang cuối báo lên route', async () => {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ items: [motKhach('0900000001')], tongKhach: 132, tongPhien: 140 }),
      ),
    )
    const datLoc = dungVoi({ tuNgay: '30' })
    const nav = await screen.findByRole('navigation', { name: 'Phân trang' })
    expect(screen.getByText('Hiện 1–10 / 132')).toBeInTheDocument()
    // Góc phải nói TỔNG, không còn «đang xem» — phần đó thuộc về thanh phân trang.
    expect(screen.getByText(/132 khách/)).toBeInTheDocument()
    expect(screen.queryByText(/đang xem/i)).not.toBeInTheDocument()

    // 132 khách / 10 mỗi trang = 14 trang ⇒ dãy «1 2 … 14».
    await userEvent.click(within(nav).getByRole('button', { name: '14' }))
    expect(datLoc).toHaveBeenLastCalledWith({ tuNgay: '30', trang: 14 })
  })

  it('loc.trang/soHang ⇒ request mang đúng limit/offset', async () => {
    const daGoi: { limit: string | null; offset: string | null }[] = []
    server.use(
      http.get('/api/v1/convos/khach', ({ request }) => {
        const p = new URL(request.url).searchParams
        daGoi.push({ limit: p.get('limit'), offset: p.get('offset') })
        return HttpResponse.json({
          items: [motKhach('0900000001')],
          tongKhach: 132,
          tongPhien: 140,
        })
      }),
    )
    dungVoi({ trang: 3, soHang: 20 })
    expect(await screen.findByText('Hiện 41–60 / 132')).toBeInTheDocument()
    expect(daGoi).toContainEqual({ limit: '20', offset: '40' })
  })

  it('mặc định (không trang/soHang) ⇒ limit 10 offset 0', async () => {
    let tham: URLSearchParams | undefined
    server.use(
      http.get('/api/v1/convos/khach', ({ request }) => {
        tham = new URL(request.url).searchParams
        return HttpResponse.json({ items: [], tongKhach: 0, tongPhien: 0 })
      }),
    )
    dung()
    await screen.findByText('Chưa có hội thoại nào')
    expect(tham?.get('limit')).toBe('10')
    expect(tham?.get('offset')).toBe('0')
  })

  it('đổi bộ lọc khi đang ở trang 3 ⇒ về trang 1', async () => {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ items: [motKhach('0900000001')], tongKhach: 132, tongPhien: 140 }),
      ),
    )
    const datLoc = dungVoi({ trang: 3 })
    await screen.findByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(screen.getByRole('button', { name: '7 ngày' }))
    expect(datLoc).toHaveBeenLastCalledWith({ trang: 1, tuNgay: '7' })
  })

  it('đổi số hàng mỗi trang ⇒ về trang 1', async () => {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ items: [motKhach('0900000001')], tongKhach: 132, tongPhien: 140 }),
      ),
    )
    const datLoc = dungVoi({ trang: 2 })
    await screen.findByRole('navigation', { name: 'Phân trang' })
    await userEvent.selectOptions(screen.getByRole('combobox'), '100')
    expect(datLoc).toHaveBeenLastCalledWith({ trang: 1, soHang: 100 })
  })

  it('ô «Mỗi trang» có đúng 10 · 20 · 50 · 100, mặc định 10', async () => {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ items: [motKhach('0900000001')], tongKhach: 132, tongPhien: 140 }),
      ),
    )
    dungVoi({})
    const chon = await screen.findByRole('combobox')
    expect([...(chon as HTMLSelectElement).options].map((o) => o.value)).toEqual([
      '10',
      '20',
      '50',
      '100',
    ])
    expect(chon).toHaveValue('10')
  })

  it('trang vượt quá số trang thật ⇒ kéo về trang cuối, không hiện «chưa có hội thoại»', async () => {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ items: [], tongKhach: 132, tongPhien: 140 }),
      ),
    )
    const datLoc = dungVoi({ trang: 99 })
    await waitFor(() => expect(datLoc).toHaveBeenCalledWith({ trang: 14 }))
  })

  it('kho rỗng ⇒ không có thanh phân trang', async () => {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ items: [], tongKhach: 0, tongPhien: 0 }),
      ),
    )
    dung()
    await screen.findByText('Chưa có hội thoại nào')
    expect(screen.queryByRole('navigation', { name: 'Phân trang' })).not.toBeInTheDocument()
  })

  it('items đủ khớp tongKhach ⇒ hiện con số trần như trước, không thêm chữ "đang xem"', async () => {
    dung()
    expect(await screen.findByText(/3 khách/)).toBeInTheDocument()
    expect(screen.queryByText(/đang xem/i)).not.toBeInTheDocument()
  })

  it('gõ vào ô tìm thì gọi lại API kèm q — không phải chỉ đổi giá trị ô', async () => {
    // Assert trên REQUEST, không phải trên ô input. Kiểm `input.value === 'Anh'`
    // chỉ chứng minh React giữ state — nó xanh y hệt khi `datLoc` không nối đi đâu.
    const daGoi: string[] = []
    server.use(
      http.get('/api/v1/convos/khach', ({ request }) => {
        daGoi.push(new URL(request.url).searchParams.get('q') ?? '')
        return HttpResponse.json({ items: [], tongKhach: 0, tongPhien: 0 })
      }),
    )
    const loc: LocKhach = {}
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const datLoc = vi.fn()
    dungTrongRouter(
      <QueryClientProvider client={qc}>
        <KhachList loc={loc} datLoc={datLoc} />
      </QueryClientProvider>,
    )
    await screen.findByText('Chưa có hội thoại nào')
    await userEvent.type(screen.getByPlaceholderText(/tìm tên hoặc số/i), 'Anh')

    // Component KHÔNG tự đổi `loc` — route mới là chủ. Nó phải báo lên qua `datLoc`.
    expect(datLoc).toHaveBeenLastCalledWith(expect.objectContaining({ q: 'Anh' }))

    // Và khi route đẩy `loc` mới xuống thì query phải chạy lại với `q`.
    qc.clear()
    dungTrongRouter(
      <QueryClientProvider client={qc}>
        <KhachList loc={{ q: 'Anh' }} datLoc={datLoc} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(daGoi).toContain('Anh'))
  })

  it('mỗi hàng là một link tới /convos/<phone>, nhóm rỗng đi bằng _', async () => {
    dung()
    await screen.findByText('Nguyễn Minh Anh')
    const links = screen.getAllByRole('link')
    const href = links.map((a) => a.getAttribute('href'))
    expect(href).toContain('/convos/0912448111')
    expect(href).toContain('/convos/_')
  })

  it('danh sách rỗng ⇒ màn rỗng, KHÔNG phải thông báo lỗi', async () => {
    // Kho rỗng là bình thường. Hiện câu lỗi ở đây làm người vận hành đi báo sự cố
    // cho một hệ thống đang chạy đúng.
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ items: [], tongKhach: 0, tongPhien: 0 }),
      ),
    )
    dung()
    expect(await screen.findByText('Chưa có hội thoại nào')).toBeInTheDocument()
    expect(screen.queryByText(/không tải được/i)).not.toBeInTheDocument()
  })

  it('backend chết ⇒ câu lỗi, KHÔNG phải màn rỗng', async () => {
    server.use(http.get('/api/v1/convos/khach', () => new HttpResponse(null, { status: 500 })))
    dung()
    expect(await screen.findByText(/không tải được danh sách hội thoại/i)).toBeInTheDocument()
    expect(screen.queryByText('Chưa có hội thoại nào')).not.toBeInTheDocument()
  })

  // ── Lịch sử hội thoại = CHỮ CÁI mặc định, KHÔNG dùng avatar backend ─────────
  // (2026-08-25, đảo chốt 2026-08-21) Người dùng chốt: khách không «set» avatar
  // nên ảnh DiceBear backend trả là thừa — hàng hội thoại vẽ chữ cái như bảng
  // Thành viên (từ ĐẦU + từ CUỐI của tên). Backend VẪN trả `avatar`, FE chỉ thôi
  // đọc, nên bài đầu canh đúng chiều «CÓ avatar cũng không ra <img>». Ghi đè bằng
  // `server.use` chứ không đọc fake dùng chung: ranh nằm ngay trong bài.

  const AVATAR_THU =
    "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D'http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg'%2F%3E"

  function khachGia(them: { avatar: string | null; phone?: string; ten?: string }) {
    return {
      phone: '0912448111',
      ten: 'Minh Anh',
      soPhien: 1,
      ganNhat: '2026-07-27T14:22:00+07:00',
      dauTien: '2026-07-14T16:40:00+07:00',
      daChuyen: false,
      summaryCuoi: null,
      duAn: null,
      tenDuAn: null,
      ...them,
    }
  }

  it('khách CÓ avatar backend vẫn hiện chữ cái — không <img> nào', async () => {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({
          items: [khachGia({ avatar: AVATAR_THU })],
          tongKhach: 1,
          tongPhien: 1,
        }),
      ),
    )
    const { container } = dung()
    await screen.findByText('Minh Anh')
    expect(screen.getByText('MA')).toBeInTheDocument()
    expect(container.querySelector('img')).not.toBeInTheDocument()
  })

  it('chữ cái ghép từ ĐẦU + từ CUỐI; tên MỘT từ lấy đúng một chữ', async () => {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({
          items: [
            khachGia({ avatar: null, ten: 'Nguyễn Minh Anh' }),
            khachGia({ avatar: null, phone: '0900000012', ten: 'Duy' }),
          ],
          tongKhach: 2,
          tongPhien: 2,
        }),
      ),
    )
    dung()
    await screen.findByText('Nguyễn Minh Anh')
    expect(screen.getByText('NA')).toBeInTheDocument()
    expect(screen.getByText('D')).toBeInTheDocument()
  })

  it('hàng khách có tầng mobile: xuống dòng, cột tên không cố định 186px', async () => {
    dung() // helper sẵn có ở đầu file (dòng ~34)
    const hang = (await screen.findAllByRole('link')).find((a) =>
      a.getAttribute('href')?.startsWith('/convos/'),
    )!
    expect(hang.className).toContain('max-md:flex-wrap')
    expect(hang.querySelector('.w-\\[186px\\]')!.className).toContain('max-md:w-auto')
  })
})

describe('cột Lead trên danh sách khách', () => {
  function trangCo(items: object[]) {
    server.use(
      http.get('/api/v1/convos/khach', () =>
        HttpResponse.json({ tongKhach: items.length, tongPhien: items.length, items }),
      ),
    )
  }
  const goc = {
    soPhien: 1,
    ganNhat: '2026-07-27T14:22:00+07:00',
    dauTien: '2026-07-27T14:22:00+07:00',
    daChuyen: false,
    summaryCuoi: null,
    duAn: null,
    tenDuAn: null,
  }

  it('hiện chip + điểm + đối tượng trong cột riêng của hàng', async () => {
    trangCo([
      { ...goc, phone: '0911', ten: 'An', leadStage: 'sql', leadScore: 120, audience: 'broker' },
    ])
    dung()
    const cot = await screen.findByTestId('cot-lead')
    expect(within(cot).getByText('SQL')).toBeInTheDocument()
    expect(cot.textContent).toContain('120điểm')
    expect(cot.textContent).toContain('Môi giới')
  })

  it('khách chưa có lead ⇒ «Chưa phân loại» mờ, không chip', async () => {
    trangCo([
      { ...goc, phone: '0912', ten: 'Bình', leadStage: null, leadScore: null, audience: null },
    ])
    dung()
    const cot = await screen.findByTestId('cot-lead')
    expect(cot.textContent).toBe('Chưa phân loại')
  })

  it('backend cũ chưa trả khoá lead ⇒ vẫn «Chưa phân loại», không «undefined»', async () => {
    trangCo([{ ...goc, phone: '0913', ten: 'Chi' }])
    dung()
    const cot = await screen.findByTestId('cot-lead')
    expect(cot.textContent).toBe('Chưa phân loại')
  })

  it('stage lạ hiện nguyên văn', async () => {
    trangCo([
      { ...goc, phone: '0914', ten: 'Dũng', leadStage: 'chot', leadScore: 50, audience: null },
    ])
    dung()
    expect(await screen.findByText('chot')).toBeInTheDocument()
  })

  it('chọn stage trong menu ⇒ `datLoc` nhận `stage` và về trang 1', async () => {
    const datLoc = vi.fn()
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    dungTrongRouter(
      <QueryClientProvider client={qc}>
        <KhachList loc={{ tuNgay: '30', trang: 3 }} datLoc={datLoc} />
      </QueryClientProvider>,
    )
    await userEvent.click(await screen.findByRole('button', { name: /stage/i }))
    await userEvent.click(screen.getByRole('menuitemradio', { name: /^SQL/ }))
    expect(datLoc).toHaveBeenCalledWith(expect.objectContaining({ stage: 'sql', trang: 1 }))
  })

  it('loc.stage được gửi lên API thành `lead_stage`', async () => {
    let thamSo: string | null = null
    server.use(
      http.get('/api/v1/convos/khach', ({ request }) => {
        thamSo = new URL(request.url).searchParams.get('lead_stage')
        return HttpResponse.json({ tongKhach: 0, tongPhien: 0, items: [] })
      }),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    dungTrongRouter(
      <QueryClientProvider client={qc}>
        <KhachList loc={{ tuNgay: '30', stage: 'none' }} datLoc={() => {}} />
      </QueryClientProvider>,
    )
    await waitFor(() => expect(thamSo).toBe('none'))
  })

  it('nhóm «Chưa có số» (nhiều người ẩn danh) ⇒ cột Lead là «—», không phải «Chưa phân loại»', async () => {
    trangCo([{ ...goc, phone: '', ten: null, leadStage: null, leadScore: null, audience: null }])
    dung()
    const cot = await screen.findByTestId('cot-lead')
    expect(cot.textContent).toBe('—')
  })
})
