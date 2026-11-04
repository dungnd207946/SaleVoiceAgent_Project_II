/**
 * Phân trang CÓ SỐ cho bốn bảng (spec vòng 2 §4.8).
 *
 * Canh đúng thứ cursor không làm được: nhảy thẳng tới trang n. Và canh rằng số
 * trang suy từ `total` của SERVER, không từ `items.length` — suy từ `items` cho
 * đúng 1 trang mãi mãi.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { CAN, TAI_LIEU, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

function batTruyVan() {
  const goi: URL[] = []
  server.use(
    http.get('/api/v1/projects/:code/units', ({ request }) => {
      const u = new URL(request.url)
      goi.push(u)
      const offset = Number(u.searchParams.get('offset') ?? 0)
      return HttpResponse.json(
        trang([{ ...CAN, id: 1000 + offset, unitCode: `U-${offset}` }], null, 47),
      )
    }),
  )
  return goi
}

describe('thanh phân trang bảng quỹ căn', () => {
  it('số trang suy từ total của server, không từ số hàng đang có', async () => {
    datApiDoc()
    batTruyVan()
    boot('/pform?code=VHOP2&tab=quy-can')

    // 47 hàng, 20 hàng/trang ⇒ 3 trang.
    const thanh = await screen.findByRole('navigation', { name: 'Phân trang' })
    expect(await within(thanh).findByRole('button', { name: '3' })).toBeInTheDocument()
    expect(within(thanh).queryByRole('button', { name: '4' })).not.toBeInTheDocument()
  })

  it('bấm trang 3 gửi offset đúng, không đi qua trang 2', async () => {
    datApiDoc()
    const goi = batTruyVan()
    boot('/pform?code=VHOP2&tab=quy-can')

    const thanh = await screen.findByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: '3' }))

    await screen.findByText('U-40')
    expect(goi.map((u) => u.searchParams.get('offset'))).toContain('40')
    // KHÔNG có request nào cho trang 2 — đó là điểm của phân trang có số.
    expect(goi.map((u) => u.searchParams.get('offset'))).not.toContain('20')
  })

  it('đổi số hàng mỗi trang thì về trang 1', async () => {
    datApiDoc()
    const goi = batTruyVan()
    boot('/pform?code=VHOP2&tab=quy-can')

    const thanh = await screen.findByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: '3' }))
    await screen.findByText('U-40')

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Mỗi trang/ }), '50')

    // Về trang 1: ở trang 3 với 50 hàng/trang thì offset 100 > total 47 ⇒ bảng
    // rỗng, và người dùng không hiểu vì sao dữ liệu biến mất.
    const cuoi = goi[goi.length - 1]!
    expect(cuoi.searchParams.get('offset')).toBe('0')
    expect(cuoi.searchParams.get('limit')).toBe('50')
  })
})

describe('đổi bộ lọc reset về trang 1 (M-2)', () => {
  it('quỹ căn: sang trang 3 rồi đổi lọc phân khu → request kế tiếp offset=0', async () => {
    datApiDoc()
    const goi = batTruyVan()
    boot('/pform?code=VHOP2&tab=quy-can')

    const thanh = await screen.findByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: '3' }))
    await screen.findByText('U-40')

    // Nghiệm thu: bỏ `ds.doiTrang(1)` khỏi `CanTab.doiLoc` phải làm bài này đỏ
    // — trước bản vá này không bài nào canh chuyện đó dù code đã gọi đúng.
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Lọc theo phân khu' }),
      'ZURICH',
    )

    await waitFor(() => expect(goi.at(-1)?.searchParams.get('offset')).toBe('0'))
  })
})

describe('kẹp trang khi total tụt xuống dưới trang đang xem (I-3)', () => {
  it('21 tài liệu, sang trang 2, xoá hàng duy nhất → không hiện "kho rỗng", thanh trang không nói "21–20"', async () => {
    // Kịch bản đúng cái reviewer tháo ra: 21 hàng (2 trang, 20 hàng/trang),
    // sang trang 2 (còn đúng 1 hàng), xoá nó — `total` tụt về 20 NGAY LẬP TỨC.
    // Trước bản vá `useTrangSo` (I-3), `trang` không kẹp theo `total` mới, nên
    // bảng hiện "Chưa có tài liệu nào." (dữ liệu vẫn còn 20 hàng) và thanh
    // trang hiện "Hiện 21–20 / 20" (vô nghĩa).
    let ds = Array.from({ length: 21 }, (_, i) => ({
      ...TAI_LIEU,
      id: 900 + i,
      title: `Tài liệu ${i + 1}`,
    }))
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/documents', ({ request }) => {
        const u = new URL(request.url)
        const offset = Number(u.searchParams.get('offset') ?? 0)
        const limit = Number(u.searchParams.get('limit') ?? 20)
        return HttpResponse.json(trang(ds.slice(offset, offset + limit), null, ds.length))
      }),
      http.delete('/api/v1/projects/:code/documents/:id', ({ params }) => {
        ds = ds.filter((d) => d.id !== Number(params.id))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot('/pform?code=VHOP2&tab=tai-lieu')

    // `findByRole`, không `getByRole`: nút «2» chỉ mọc SAU khi `total` (21) về —
    // khác `CanTab` (có cổng chờ `dsZone` phía trước), `TaiLieuTab` render thanh
    // phân trang NGAY từ lượt đầu, trước khi request tài liệu kịp trả lời.
    const thanh = await screen.findByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(await within(thanh).findByRole('button', { name: '2' }))
    await screen.findByText('Tài liệu 21')
    await moSuaDuAn()

    await userEvent.click(screen.getByRole('button', { name: 'Xoá' }))
    const hop = screen.getByRole('alertdialog')
    await userEvent.click(within(hop).getByRole('button', { name: 'Xoá' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())

    // Kẹp về trang 1 — 20 hàng còn lại vừa đúng một trang, không phải kho rỗng.
    await screen.findByText('Tài liệu 1')
    expect(screen.queryByText('Chưa có tài liệu nào.')).not.toBeInTheDocument()
    expect(screen.getByText(/Hiện 1–20 \/ 20/)).toBeInTheDocument()
  })
})
