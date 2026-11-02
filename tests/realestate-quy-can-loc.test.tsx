/**
 * Tab «Quỹ căn» — tìm mã căn · lọc hướng · sắp xếp · mục lọc theo dữ liệu thật.
 *
 * MỘT ĐIỀU DUY NHẤT CẦN CANH Ở ĐÂY, và mọi bài dưới đây là một mặt của nó:
 * **bảng phân trang phía server, nên cả bốn thứ phải đi qua server**. Lọc hay
 * sắp xếp mảng đã tải cho ra một câu trả lời trông đúng mà sai — "căn đắt nhất"
 * hoá ra là căn đắt nhất trong 20 hàng đang xem, và không có gì trên màn hình
 * nói ra điều đó. Nên bài nào cũng đọc THAM SỐ CỦA REQUEST, không đọc thứ tự
 * hàng trong DOM: thứ tự hàng chỉ chứng minh handler giả sắp đúng.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { CAN, boot, datApiDoc, trang } from './re-fixture'

/** Ghi lại mọi request tới danh sách căn, để đọc tham số lần gọi CUỐI. */
function batTruyVan() {
  const goi: URL[] = []
  server.use(
    http.get('/api/v1/projects/:code/units', ({ request }) => {
      goi.push(new URL(request.url))
      return HttpResponse.json(trang([CAN]))
    }),
  )
  return goi
}

async function moTab() {
  boot('/pform?code=VHOP2&tab=quy-can')
  await screen.findByText('ZR-A-1203')
}

describe('tìm theo mã căn', () => {
  it('gửi `unit_code` lên server và về trang 1', async () => {
    datApiDoc()
    const goi = batTruyVan()
    await moTab()

    await userEvent.type(screen.getByLabelText('Tìm theo mã căn'), 'ZR-A')

    // Đợi request CUỐI: mỗi ký tự gõ sinh một query mới, nên assert ngay sau
    // `type()` là đọc một request giữa chuỗi gõ.
    await waitFor(() => expect(goi.at(-1)?.searchParams.get('unit_code')).toBe('ZR-A'))
    expect(goi.at(-1)?.searchParams.get('offset')).toBe('0')
    // Nếu tìm kiếm chạy ở client thì chỉ có đúng MỘT lần gọi và không lần nào
    // mang tham số — đó là thứ vế này loại trừ.
    expect(goi.length).toBeGreaterThan(1)
  })
})

describe('lọc theo hướng', () => {
  it('gửi `direction` lên server', async () => {
    datApiDoc()
    const goi = batTruyVan()
    await moTab()

    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: 'Lọc theo hướng' }),
      'dong_nam',
    )

    await waitFor(() => expect(goi.at(-1)?.searchParams.get('direction')).toBe('dong_nam'))
  })

  it('không căn nào có hướng thì KHÔNG hiện ô lọc rỗng', async () => {
    // Một dropdown chỉ có mục «Mọi hướng» là một điều khiển không làm được gì —
    // nó hứa một bộ lọc rồi không lọc được gì cả.
    datApiDoc({ facets: { productType: ['chung_cu'], direction: [] } })
    await moTab()

    expect(screen.queryByRole('combobox', { name: 'Lọc theo hướng' })).not.toBeInTheDocument()
  })
})

describe('ô lọc chỉ liệt kê giá trị CÓ THẬT trong quỹ căn', () => {
  it('loại sản phẩm: 12 mục của enum rút còn 2 mục dữ liệu đang có', async () => {
    datApiDoc({ facets: { productType: ['chung_cu', 'penthouse'], direction: ['bac'] } })
    await moTab()

    const o = screen.getByRole('combobox', { name: 'Lọc theo loại sản phẩm' })
    await waitFor(() =>
      expect(
        within(o)
          .getAllByRole('option')
          .map((x) => x.textContent),
      ).toEqual(['Mọi loại sản phẩm', 'Chung cư', 'Penthouse']),
    )
    // Chọn một loại không có căn nào chắc chắn ra bảng rỗng — đó là lý do nó
    // không được có mặt.
    expect(within(o).queryByRole('option', { name: 'Shophouse' })).not.toBeInTheDocument()
  })

  it('facet lỗi thì rơi về enum ĐẦY ĐỦ, không để lại ô lọc trống', async () => {
    // Thà thừa mục còn hơn một ô lọc chỉ có mục «Mọi …» mà không giải thích
    // được vì sao — người dùng đọc ra "dự án này không có loại nào".
    datApiDoc()
    server.use(
      http.get(
        '/api/v1/projects/:code/units/facets',
        () => new HttpResponse(null, { status: 500 }),
      ),
    )
    await moTab()

    const o = screen.getByRole('combobox', { name: 'Lọc theo loại sản phẩm' })
    expect(within(o).getByRole('option', { name: 'Shophouse' })).toBeInTheDocument()
  })

  it('đổi bộ lọc KHÔNG làm mục của dropdown hẹp lại', async () => {
    // Facet không mang bộ lọc trong `queryKey`. Nếu nó mang, chọn «Chung cư»
    // xong là «Penthouse» biến mất khỏi danh sách và không còn đường quay lại.
    datApiDoc({ facets: { productType: ['chung_cu', 'penthouse'], direction: ['bac'] } })
    await moTab()
    const o = screen.getByRole('combobox', { name: 'Lọc theo loại sản phẩm' })
    await waitFor(() => expect(within(o).getAllByRole('option')).toHaveLength(3))

    await userEvent.selectOptions(o, 'chung_cu')

    expect(within(o).getAllByRole('option')).toHaveLength(3)
  })
})

describe('sắp xếp theo cột số', () => {
  it('bấm tiêu đề Giá gửi `sort=price_vnd`, bấm lại thêm `desc`, bấm nữa thì bỏ hẳn', async () => {
    datApiDoc()
    const goi = batTruyVan()
    await moTab()
    const nut = screen.getByRole('button', { name: /Giá/ })

    await userEvent.click(nut)
    await waitFor(() => expect(goi.at(-1)?.searchParams.get('sort')).toBe('price_vnd'))
    expect(goi.at(-1)?.searchParams.get('desc')).toBeNull()

    await userEvent.click(nut)
    await waitFor(() => expect(goi.at(-1)?.searchParams.get('desc')).toBe('true'))

    // Nhịp thứ ba VỀ MẶC ĐỊNH. Với vòng hai nhịp, đường về thứ tự gốc duy nhất
    // là tải lại trang.
    await userEvent.click(nut)
    await waitFor(() => expect(goi.at(-1)?.searchParams.get('sort')).toBeNull())
  })

  it('ba cột số sắp xếp được, cột chữ thì không', async () => {
    datApiDoc()
    await moTab()

    for (const nhan of ['PN', 'DT thông thuỷ', 'Giá']) {
      expect(screen.getByRole('button', { name: new RegExp(nhan) })).toBeInTheDocument()
    }
    expect(screen.queryByRole('button', { name: /Hướng/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Phân khu/ })).not.toBeInTheDocument()
  })

  it('cột đang sắp mang `aria-sort` — chiều sắp xếp phải tới được trình đọc màn hình', async () => {
    // Mũi tên vẽ ra chỉ có mắt đọc được. `aria-sort` là chỗ DUY NHẤT nói ra
    // chiều đang sắp cho người dùng trình đọc màn hình.
    datApiDoc()
    await moTab()
    const cot = () => screen.getByRole('columnheader', { name: /Giá/ })

    expect(cot()).toHaveAttribute('aria-sort', 'none')
    await userEvent.click(screen.getByRole('button', { name: /Giá/ }))
    expect(cot()).toHaveAttribute('aria-sort', 'ascending')
    await userEvent.click(screen.getByRole('button', { name: /Giá/ }))
    expect(cot()).toHaveAttribute('aria-sort', 'descending')
  })

  it('đổi cột sắp xếp bắt đầu lại từ chiều TĂNG, không giữ chiều của cột cũ', async () => {
    datApiDoc()
    const goi = batTruyVan()
    await moTab()

    await userEvent.click(screen.getByRole('button', { name: /Giá/ }))
    await userEvent.click(screen.getByRole('button', { name: /Giá/ }))
    await waitFor(() => expect(goi.at(-1)?.searchParams.get('desc')).toBe('true'))

    await userEvent.click(screen.getByRole('button', { name: /^PN/ }))

    await waitFor(() => expect(goi.at(-1)?.searchParams.get('sort')).toBe('bedrooms'))
    expect(goi.at(-1)?.searchParams.get('desc')).toBeNull()
  })

  it('sắp xếp về trang 1 — cùng lý do đổi bộ lọc', async () => {
    // Đang ở trang 3 rồi sắp xếp lại thì trang 3 của thứ tự mới là một chỗ khác
    // hẳn, và người dùng đọc ra "dữ liệu nhảy lung tung".
    datApiDoc()
    const goi: URL[] = []
    server.use(
      http.get('/api/v1/projects/:code/units', ({ request }) => {
        goi.push(new URL(request.url))
        return HttpResponse.json(trang([CAN], null, 47))
      }),
    )
    boot('/pform?code=VHOP2&tab=quy-can')
    await screen.findByText('ZR-A-1203')

    const thanh = screen.getByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: '3' }))
    await waitFor(() => expect(goi.at(-1)?.searchParams.get('offset')).toBe('40'))

    await userEvent.click(screen.getByRole('button', { name: /Giá/ }))

    await waitFor(() => expect(goi.at(-1)?.searchParams.get('offset')).toBe('0'))
  })
})

describe('kho rỗng phân biệt "chưa có căn" với "không khớp bộ lọc"', () => {
  it('gõ mã căn không khớp thì nói KHÔNG KHỚP BỘ LỌC, không nói chưa có căn nào', async () => {
    // Câu "Chưa có căn nào." khi đang có bộ lọc bật dạy người dùng rằng quỹ căn
    // trống — và họ đi nhập lại thứ đã có.
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units', ({ request }) => {
        const ma = new URL(request.url).searchParams.get('unit_code') ?? ''
        return HttpResponse.json(trang(ma ? [] : [CAN]))
      }),
    )
    await moTab()

    await userEvent.type(screen.getByLabelText('Tìm theo mã căn'), 'KHONG-CO')

    expect(await screen.findByText('Không có căn nào khớp bộ lọc.')).toBeInTheDocument()
    expect(screen.queryByText('Chưa có căn nào.')).not.toBeInTheDocument()
  })
})

describe('cột và bộ lọc trạng thái phát hành', () => {
  it('gửi `status` lên server và về trang 1', async () => {
    datApiDoc()
    const goi = batTruyVan()
    await moTab()

    await userEvent.selectOptions(screen.getByLabelText('Lọc theo trạng thái phát hành'), 'draft')

    await waitFor(() => expect(goi.at(-1)?.searchParams.get('status')).toBe('draft'))
    expect(goi.at(-1)?.searchParams.get('offset')).toBe('0')
  })

  it('bỏ chọn thì thôi gửi `status` — «Mọi trạng thái» không phải một giá trị', async () => {
    datApiDoc()
    const goi = batTruyVan()
    await moTab()
    const o = screen.getByLabelText('Lọc theo trạng thái phát hành')

    await userEvent.selectOptions(o, 'draft')
    await waitFor(() => expect(goi.at(-1)?.searchParams.get('status')).toBe('draft'))
    await userEvent.selectOptions(o, '')

    await waitFor(() => expect(goi.at(-1)?.searchParams.get('status')).toBeNull())
  })

  it('cột Phát hành riêng: chip chỉ ở căn chưa phát hành, căn đã phát hành để trống', async () => {
    datApiDoc({
      units: trang([
        { ...CAN, id: 1, unitCode: 'PUB-1', status: 'published' },
        { ...CAN, id: 2, unitCode: 'NHAP-1', status: 'draft' },
      ]),
    })
    boot('/pform?code=VHOP2&tab=quy-can')
    await screen.findByText('PUB-1')

    const cot = screen.getAllByRole('columnheader').map((th) => th.textContent)
    const oCua = (ma: string, nhan: string) =>
      screen.getByText(ma).closest('tr')!.querySelectorAll('td')[cot.indexOf(nhan)]!
    expect(cot).toContain('Phát hành')
    expect(oCua('NHAP-1', 'Phát hành')).toHaveTextContent('Bản nháp')
    expect(oCua('NHAP-1', 'Mã căn')).not.toHaveTextContent('Bản nháp')
    expect(oCua('PUB-1', 'Phát hành')).toHaveTextContent(/^$/)
  })

  it('căn sản phẩm đất chỉ có DT đất KHÔNG bị gắn cờ thiếu', async () => {
    // 5.133 căn biệt thự/nhà phố/shophouse trên tenant thật không bao giờ có DT
    // thông thuỷ. Cổng cũ gắn cờ hết, kể cả 4.189 căn đang published.
    datApiDoc({
      units: trang([
        {
          ...CAN,
          id: 3,
          unitCode: 'BT-01',
          productType: 'biet_thu',
          areaBuiltM2: null,
          areaLandM2: 180,
          status: 'published',
        },
      ]),
    })
    boot('/pform?code=VHOP2&tab=quy-can')
    await screen.findByText('BT-01')

    expect(screen.queryByText(/⚠ Thiếu/)).not.toBeInTheDocument()
  })

  it('thiếu CẢ HAI diện tích thì mới gắn cờ, và gọi tên là «Diện tích»', async () => {
    datApiDoc({
      units: trang([
        { ...CAN, id: 4, unitCode: 'TRONG', areaBuiltM2: null, areaLandM2: null, status: 'draft' },
      ]),
    })
    boot('/pform?code=VHOP2&tab=quy-can')
    await screen.findByText('TRONG')

    expect(screen.getByText(/⚠ Thiếu: Diện tích/)).toBeInTheDocument()
  })
})
