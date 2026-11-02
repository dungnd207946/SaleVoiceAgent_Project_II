/**
 * Màn `/uform` — form căn, và tab Căn của form dự án (M4).
 *
 * Bốn thứ phải giữ:
 *   · TẠO CĂN MỚI mà dự án 0 phân khu thì chặn form, chỉ đường sang tab Phân
 *     khu — chỉ nhánh TẠO MỚI, vì `OChon zoneCode` ở đó `batBuoc` cần ít nhất
 *     một mục để chọn. SỬA/XEM một căn ĐÃ CÓ (`?unit=`) KHÔNG bị chặn theo số
 *     phân khu — từ migration `0902_noi_zone_code_nullable` (2026-08-15),
 *     `units.zone_code` đã nullable và dữ liệu ingest thường có unit không
 *     zone; chặn cả nhánh xem là bug đã sửa (xem docstring `CanTab.tsx`).
 *   · Dropdown phân khu lấy từ zones của ĐÚNG dự án đang mở.
 *   · Bộ lọc quỹ căn đi qua SERVER (quỹ căn hàng nghìn dòng — lọc client trên
 *     trang đầu trả lời sai câu "còn căn 3PN nào không").
 *   · `?unit=` là `id`, không phải `unit_code` (mã căn không unique, `02a §4.3`).
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import {
  CAN,
  DU_AN,
  PHAN_KHU,
  boot,
  datApiDoc,
  giaTriXem,
  moSuaCan,
  moSuaDuAn,
  trang,
} from './re-fixture'

describe('màn căn — phân khu là bắt buộc', () => {
  it('dự án chưa có phân khu thì chặn và chỉ đường, không hiện form', async () => {
    datApiDoc({ zones: trang([]) })
    boot('/uform?code=VHOP2')

    expect(
      await screen.findByText('Chưa thêm căn được — dự án chưa có phân khu nào.'),
    ).toBeInTheDocument()
    expect(screen.getByText(/ràng buộc ở cơ sở dữ liệu/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tạo căn' })).not.toBeInTheDocument()
  })

  it('tab Căn KHÔNG chặn khi chưa có phân khu — danh sách căn vẫn hiện', async () => {
    datApiDoc({ zones: trang([]) })
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Quỹ căn' }))

    expect(
      screen.queryByText('Chưa thêm căn được — dự án chưa có phân khu nào.'),
    ).not.toBeInTheDocument()
    expect(await screen.findByText(CAN.unitCode)).toBeInTheDocument()
  })

  it('sửa/xem một căn đã có KHÔNG chặn khi dự án chưa có phân khu', async () => {
    datApiDoc({ zones: trang([]) })
    boot(`/uform?code=VHOP2&unit=${CAN.id}`)

    expect(
      screen.queryByText('Chưa thêm căn được — dự án chưa có phân khu nào.'),
    ).not.toBeInTheDocument()
    await waitFor(() => expect(giaTriXem('Mã căn')).toHaveTextContent(CAN.unitCode))
  })

  it('dropdown phân khu lấy từ zones của đúng dự án', async () => {
    datApiDoc({
      zones: trang([PHAN_KHU, { ...PHAN_KHU, id: 11, zoneCode: 'PARIS', name: 'Paris' }]),
    })
    boot('/uform?code=VHOP2')

    // Nhãn là TÊN, `value` vẫn là mã — mã của tenant thật là UUID, không ai đọc được.
    const muc = await screen.findByRole('option', { name: 'Zurich' })
    expect(muc).toHaveValue('ZURICH')
    const o = screen.getByRole('combobox', { name: /Phân khu/ })
    expect(within(o).getByRole('option', { name: 'Paris' })).toHaveValue('PARIS')
    // Có lựa chọn rỗng để buộc người dùng CHỌN, nhưng nhãn nói rõ phải chọn —
    // không phải (không phân khu) như mockup vẽ.
    expect(within(o).getByRole('option', { name: '— chọn phân khu —' })).toBeInTheDocument()
    expect(within(o).queryByRole('option', { name: /không phân khu/ })).not.toBeInTheDocument()
  })

  it('thiếu `?code` thì nói thiếu mã dự án, không render form', async () => {
    boot('/uform')

    expect(await screen.findByText(/Thiếu mã dự án trong đường dẫn/)).toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: /Phân khu/ })).not.toBeInTheDocument()
  })
})

describe('màn căn — tạo mới', () => {
  it('gửi đúng alias, số nguyên đúng kiểu, số rỗng gửi `null`', async () => {
    datApiDoc()
    const than: Record<string, unknown>[] = []
    server.use(
      http.post('/api/v1/projects/:code/units', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(CAN, { status: 201 })
      }),
    )
    boot('/uform?code=VHOP2')
    await screen.findByRole('option', { name: /Zurich/ })

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Phân khu/ }), 'ZURICH')
    await userEvent.type(screen.getByRole('textbox', { name: /Mã căn/ }), 'ZR-A-1203')
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /Loại sản phẩm/ }),
      'chung_cu',
    )
    await userEvent.type(screen.getByRole('spinbutton', { name: /Số phòng ngủ/ }), '3')
    await userEvent.type(screen.getByRole('spinbutton', { name: /DT thông thuỷ/ }), '78.5')
    await userEvent.type(screen.getByRole('spinbutton', { name: /Giá bán/ }), '5600000000')
    await userEvent.click(screen.getByRole('button', { name: 'Tạo căn' }))

    await waitFor(() => expect(than).toHaveLength(1))
    const b = than[0]!
    expect(b.zoneCode).toBe('ZURICH')
    expect(b.unitCode).toBe('ZR-A-1203')
    expect(b.productType).toBe('chung_cu')
    expect(b.bedrooms).toBe(3)
    expect(b.areaBuiltM2).toBe(78.5)
    expect(b.priceVnd).toBe(5600000000)
    // Không nhập ⇒ `null`, KHÔNG `""` (cột numeric/text nullable).
    expect(b.areaLandM2).toBeNull()
    expect(b.direction).toBeNull()
    expect(b.block).toBeNull()
    // `projectCode` kế thừa từ path — không có trong thân.
    expect(Object.keys(b)).not.toContain('projectCode')
  })

  it('hai ô tầng là hai field khác nhau, NHÃN tự phân biệt', async () => {
    // Hai câu gợi ý dưới ô đã bỏ (2026-08-25) và việc phân biệt chuyển hẳn lên
    // nhãn: «Căn nằm ở tầng» vs «Số tầng của căn».
    datApiDoc()
    boot('/uform?code=VHOP2')
    await screen.findByRole('option', { name: /Zurich/ })

    const oTangCua = await screen.findByRole('spinbutton', { name: /Căn nằm ở tầng/ })
    const oSoTang = screen.getByRole('spinbutton', { name: /Số tầng của căn/ })
    expect(oTangCua).not.toBe(oSoTang)
    expect(oTangCua).not.toHaveAccessibleDescription()
    expect(oSoTang).not.toHaveAccessibleDescription()
  })

  it('thiếu giá / diện tích KHÔNG chặn tạo căn, và không câu cảnh báo nào', async () => {
    // `status` SUY RA từ completeness (xem `trangThai.ts`), không có ô Trạng thái
    // để chọn — thiếu trường chỉ đổi `status` gửi lên thành `draft`.
    //
    // Câu «Agent chưa đọc dữ liệu này — còn thiếu …» đã BỎ (2026-08-21, cùng lượt
    // với dòng của dự án): ba ô cổng mang dấu `*` ngay tại ô.
    datApiDoc()
    boot('/uform?code=VHOP2')
    await screen.findByRole('option', { name: /Zurich/ })

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Phân khu/ }), 'ZURICH')
    await userEvent.type(screen.getByRole('textbox', { name: /Mã căn/ }), 'A1')

    expect(screen.queryByText(/Agent chưa đọc dữ liệu này/)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tạo căn' })).not.toBeDisabled()
  })
})

describe('màn căn — đang sửa', () => {
  it('`?unit` là id: nạp căn theo id và khoá ba khoá nghiệp vụ', async () => {
    const xin: string[] = []
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', ({ params }) => {
        xin.push(String(params.id))
        return HttpResponse.json(CAN)
      }),
    )
    boot('/uform?code=VHOP2&unit=41')

    await waitFor(() => expect(xin).toEqual(['41']))
    await moSuaCan()
    // Ba khoá nghiệp vụ vẫn là chữ khi đang sửa — `UnitPatch` không có ô nào trong số đó.
    expect(screen.queryByRole('textbox', { name: /^Phân khu/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Mã căn/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Loại sản phẩm/ })).not.toBeInTheDocument()
    expect(giaTriXem('Phân khu')).toHaveTextContent('Zurich')
    expect(giaTriXem('Mã căn')).toHaveTextContent(CAN.unitCode)
    expect(screen.getByRole('spinbutton', { name: /Giá bán/ })).toHaveValue(5600000000)
  })

  it('`?unit=abc` bỏ qua và mở chế độ tạo mới, không gọi `/units/NaN`', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=abc')

    // Không đỏ vì request `/units/NaN` — nó không được gửi.
    expect(await screen.findByRole('button', { name: 'Tạo căn' })).toBeInTheDocument()
  })

  it('căn vừa bị xoá thì chỉ đường về quỹ căn, không mời thử lại', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json(
          { error: { code: 'UNIT_NOT_FOUND', message: 'Không tìm thấy căn' } },
          { status: 404 },
        ),
      ),
    )
    boot('/uform?code=VHOP2&unit=41')

    expect(await screen.findByText(/Căn này không còn tồn tại/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Thử lại' })).not.toBeInTheDocument()
  })
})

describe('tab Căn — bảng quỹ căn', () => {
  it('ba bộ lọc gửi lên server, không lọc mảng đã tải', async () => {
    const xin: string[] = []
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units', ({ request }) => {
        const u = new URL(request.url)
        xin.push(
          [
            u.searchParams.get('zone_code') ?? '',
            u.searchParams.get('product_type') ?? '',
            u.searchParams.get('sale_status') ?? '',
          ].join('|'),
        )
        return HttpResponse.json(trang([CAN]))
      }),
    )
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Quỹ căn' }))
    await screen.findByText('ZR-A-1203')

    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /Lọc theo phân khu/ }),
      'ZURICH',
    )
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /Lọc theo loại sản phẩm/ }),
      'chung_cu',
    )
    await userEvent.selectOptions(
      screen.getByRole('combobox', { name: /Lọc theo trạng thái bán/ }),
      'sold',
    )

    await waitFor(() => expect(xin.at(-1)).toBe('ZURICH|chung_cu|sold'))
  })

  it('giá hiện dạng đọc được, không hiện số nguyên đồng trần', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Quỹ căn' }))

    expect(await screen.findByText('5,6 tỷ')).toBeInTheDocument()
    expect(screen.queryByText('5600000000')).not.toBeInTheDocument()

    // Số `<th>` phải bằng số `<td>` một hàng — bỏ một mục COT mà quên `<td>`
    // (hoặc ngược lại) làm mọi cột sau nó lệch nhãn, im lặng.
    const soTh = screen.getAllByRole('columnheader').length
    const soTd = screen.getAllByRole('row')[1]!.querySelectorAll('td').length
    expect(soTd).toBe(soTh)
  })

  it('bảng quỹ căn có cột Hướng, hiện nhãn tiếng Việt', async () => {
    datApiDoc({ units: trang([{ ...CAN, direction: 'dong_nam' }]) })
    boot('/pform?code=VHOP2&tab=quy-can')

    expect(await screen.findByRole('columnheader', { name: 'Hướng' })).toBeInTheDocument()
    // Tra TRONG BẢNG: «Đông Nam» cũng là một `<option>` của ô lọc hướng, nên
    // `screen.getByText` toàn màn trúng hai chỗ và báo "nhiều phần tử".
    expect(within(screen.getByRole('table')).getByText('Đông Nam')).toBeInTheDocument()
    expect(screen.queryByText('dong_nam')).not.toBeInTheDocument()
  })

  it('căn chưa có hướng hiện gạch ngang, không hiện chuỗi rỗng', async () => {
    datApiDoc({ units: trang([{ ...CAN, direction: null }]) })
    boot('/pform?code=VHOP2&tab=quy-can')

    const hang = (await screen.findByText(CAN.unitCode)).closest('tr')!
    expect(within(hang).getByText('—')).toBeInTheDocument()
  })

  it('hộp xoá căn nêu cả phân khu vì mã căn không unique', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Quỹ căn' }))
    await screen.findByText('ZR-A-1203')
    await moSuaDuAn()

    await userEvent.click(screen.getByRole('button', { name: 'Xoá' }))
    expect(screen.getByRole('alertdialog')).toHaveTextContent('phân khu Zurich')
  })
})

describe('bấm cả dòng trong quỹ căn', () => {
  it('bấm một ô trơn của dòng căn thì mở màn căn', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Quỹ căn' }))
    await screen.findByText('ZR-A-1203')

    // Ô Loại — chữ trơn giữa dòng. Tra bằng ô của BẢNG, không bằng chữ:
    // 'Chung cư' cũng là một <option> của bộ lọc loại sản phẩm.
    await userEvent.click(screen.getByRole('table').querySelector('tbody td:nth-child(3)')!)

    expect(await screen.findByRole('heading', { name: `Căn ${CAN.unitCode}` })).toBeInTheDocument()
  })

  it('bấm Xoá trong dòng căn không điều hướng đi', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Quỹ căn' }))
    await screen.findByText('ZR-A-1203')
    await moSuaDuAn()

    await userEvent.click(screen.getByRole('button', { name: 'Xoá' }))

    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
  })
})

describe('màn một căn vẫn nằm trong ngữ cảnh dự án', () => {
  it('giữ hàng tab với Căn đang mở — không mất như bản trước', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=41')
    await screen.findByText('Thông tin căn')

    // Đúng thứ đã sai: mở một căn làm hàng tab biến mất, nên người dùng tưởng
    // mình đã rời khỏi dự án — khác hẳn mở một phân khu.
    for (const ten of [
      'Tổng quan',
      'Vị trí',
      'Ảnh 360',
      'Mặt bằng',
      'Phân khu',
      'Quỹ căn',
      'Tiến độ',
      'Media',
      'Tài liệu',
    ]) {
      expect(screen.getByRole('tab', { name: ten })).toBeInTheDocument()
    }
    expect(screen.getByRole('tab', { name: 'Quỹ căn' })).toHaveAttribute('aria-selected', 'true')
    // Và tiêu đề vẫn nói đang ở dự án nào.
    expect(screen.getByRole('heading', { name: DU_AN.name })).toBeInTheDocument()
  })

  it('có đường về quỹ căn, và nó trả về ĐÚNG tab Căn', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=41')
    await screen.findByText('Thông tin căn')

    await userEvent.click(screen.getByRole('button', { name: '‹ Quỹ căn' }))

    // Về `/pform?tab=quy-can` chứ không phải tab Tổng quan.
    expect(await screen.findByRole('columnheader', { name: 'Trạng thái bán' })).toBeInTheDocument()
    expect(screen.queryByText('Thông tin căn')).not.toBeInTheDocument()
  })

  it('bấm một tab khác ở màn căn cũng là một đường về dự án', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=41')
    await screen.findByText('Thông tin căn')

    await userEvent.click(screen.getByRole('tab', { name: 'Phân khu' }))

    expect(await screen.findByRole('columnheader', { name: 'Căn đã nhập' })).toBeInTheDocument()
  })
})

describe('ô khoá vẫn là ô người dùng đọc', () => {
  it('Loại sản phẩm khoá hiện NHÃN tiếng Việt, không phải giá trị máy', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    // `chung_cu` là tên máy — nó rò ra giao diện đúng cái `enums.ts` tồn tại để chặn.
    expect(giaTriXem('Loại sản phẩm')).toHaveTextContent('Chung cư')
    expect(giaTriXem('Loại sản phẩm')).not.toHaveTextContent('chung_cu')
  })
})
