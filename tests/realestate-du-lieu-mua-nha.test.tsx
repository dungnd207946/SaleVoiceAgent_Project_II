/**
 * Trường mua nhà mới (backend migration 0978): tab Toà, bộ nhập hạng mục bàn giao, nhóm ô riêng
 * của căn cao tầng / thấp tầng.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { CAN, DU_AN, TOA, boot, datApiDoc, moSuaDuAn, moSuaCan } from './re-fixture'

describe('tab Toà', () => {
  it('liệt kê toà kèm phân khu, thang máy và số căn', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=toa')

    const hang = (await screen.findByText('Toà A')).closest('tr')!
    expect(await within(hang).findByText('Zurich')).toBeInTheDocument()
    expect(within(hang).getByText('4 khách · 1 hàng')).toBeInTheDocument()
    expect(within(hang).getByText('120')).toBeInTheDocument()
  })

  it('thêm toà gửi mã toà và thông số', async () => {
    datApiDoc()
    const than: Record<string, unknown>[] = []
    server.use(
      http.post('/api/v1/projects/:code/buildings', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json({}, { status: 201 })
      }),
    )
    boot('/pform?code=VHOP2&tab=toa')

    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm toà' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Mã toà/ }), 'B2')
    await userEvent.type(screen.getByRole('spinbutton', { name: 'Số tầng nổi' }), '25')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu toà' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toMatchObject({ buildingCode: 'B2', numFloors: 25 })
  })

  it('toà còn căn không xoá được: hộp xác nhận báo số căn và tắt nút Xoá', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=toa')

    const hang = (await screen.findByText('Toà A')).closest('tr')!
    await moSuaDuAn()
    await userEvent.click(within(hang).getByRole('button', { name: 'Xoá' }))

    const hop = screen.getByRole('alertdialog')
    expect(within(hop).getByText(/Toà còn 120 căn/)).toBeInTheDocument()
    expect(within(hop).getByRole('button', { name: 'Xoá' })).toBeDisabled()
  })

  it('toà không còn căn thì xoá được', async () => {
    datApiDoc({ buildings: { items: [{ ...TOA, unitCount: 0 }], total: 1 } })
    let xoa = 0
    server.use(
      http.delete('/api/v1/projects/:code/buildings/:toa', () => {
        xoa += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot('/pform?code=VHOP2&tab=toa')

    const hang = (await screen.findByText('Toà A')).closest('tr')!
    await moSuaDuAn()
    await userEvent.click(within(hang).getByRole('button', { name: 'Xoá' }))
    await userEvent.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Xoá' }),
    )

    await waitFor(() => expect(xoa).toBe(1))
  })
})

describe('tiêu chuẩn bàn giao', () => {
  it('chế độ xem là bảng: hạng mục, vật liệu, thương hiệu kèm xuất xứ', async () => {
    datApiDoc({
      project: {
        ...DU_AN,
        handoverStandard: [
          { item: 'Thiết bị vệ sinh', material: '', brand: 'TOTO', origin: 'Nhật Bản', note: '' },
        ],
      },
    })
    boot('/pform?code=VHOP2')

    const o = (await screen.findByText('Thiết bị vệ sinh')).closest('tr')!
    expect(within(o).getByText('TOTO')).toBeInTheDocument()
    expect(within(o).getByText('Nhật Bản')).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Thương hiệu' })).toBeInTheDocument()
  })

  it('thêm hạng mục rồi rời ô thì lưu danh sách, bỏ dòng chưa có tên', async () => {
    datApiDoc({ project: { ...DU_AN, handoverStandard: [] } })
    const than: Record<string, unknown>[] = []
    server.use(
      http.patch('/api/v1/projects/:code', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(DU_AN)
      }),
    )
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.click(screen.getByRole('button', { name: 'Thêm hạng mục' }))
    await userEvent.click(screen.getByRole('button', { name: 'Thêm hạng mục' }))
    await userEvent.type(screen.getByRole('combobox', { name: 'Hạng mục — dòng 1' }), 'Điều hoà')
    await userEvent.type(screen.getByRole('textbox', { name: 'Hãng — dòng 1' }), 'Daikin')
    await userEvent.tab()

    await waitFor(() => expect(than.at(-1)).toBeDefined())
    expect(than.at(-1)).toEqual({
      handoverStandard: [{ item: 'Điều hoà', material: '', brand: 'Daikin', origin: '', note: '' }],
    })
  })
})

describe('căn — nhóm ô theo loại sản phẩm', () => {
  it('căn chung cư có ô ban công, không có ô mặt tiền', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    expect(screen.getByRole('spinbutton', { name: 'DT ban công' })).toBeInTheDocument()
    expect(screen.queryByRole('spinbutton', { name: 'Mặt tiền' })).not.toBeInTheDocument()
  })

  it('căn liền kề có ô mặt tiền, không có ô ban công', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({ ...CAN, productType: 'lien_ke', areaBuiltM2: null, areaLandM2: 96 }),
      ),
    )
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    expect(screen.getByRole('spinbutton', { name: 'Mặt tiền' })).toBeInTheDocument()
    expect(screen.queryByRole('spinbutton', { name: 'DT ban công' })).not.toBeInTheDocument()
  })

  it('căn chung cư không có ô DT đất khi trống', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    expect(screen.getByRole('combobox', { name: /Toà \/ block/ })).toBeInTheDocument()
    expect(screen.queryByRole('spinbutton', { name: /DT đất/ })).not.toBeInTheDocument()
  })

  it('căn liền kề ẩn ô toà khi trống nhưng vẫn hiện ô tầng đã có giá trị', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({
          ...CAN,
          productType: 'lien_ke',
          block: null,
          floor: 3,
          areaLandM2: 96,
        }),
      ),
    )
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    expect(screen.queryByRole('combobox', { name: /Toà \/ block/ })).not.toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: /Căn nằm ở tầng/ })).toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: /DT đất/ })).toBeInTheDocument()
  })

  it('đất nền ẩn diện tích sàn và tình trạng bàn giao khi trống', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({
          ...CAN,
          productType: 'dat_nen',
          block: null,
          floor: null,
          areaBuiltM2: null,
          areaWallM2: null,
          areaLandM2: 120,
        }),
      ),
    )
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    expect(screen.queryByRole('spinbutton', { name: /DT thông thuỷ/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton', { name: /DT tim tường/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: /Tình trạng bàn giao/ })).not.toBeInTheDocument()
    expect(screen.getByRole('spinbutton', { name: /DT đất/ })).toBeInTheDocument()
  })
})

describe('căn — chọn toà', () => {
  const TOA_B = { ...TOA, id: 8, buildingCode: 'B', name: 'Toà B' }
  const TOA_KHU_KHAC = { ...TOA, id: 9, buildingCode: 'C', name: 'Toà C', zoneCode: 'GENEVA' }

  it('ô toà liệt kê toà cùng phân khu, chọn thì lưu mã toà', async () => {
    datApiDoc({ buildings: { items: [TOA, TOA_B, TOA_KHU_KHAC], total: 3 } })
    const than: Record<string, unknown>[] = []
    server.use(
      http.patch('/api/v1/projects/:code/units/:id', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(CAN)
      }),
    )
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    const o = screen.getByRole('combobox', { name: /Toà \/ block/ })
    expect(await within(o).findByRole('option', { name: 'Toà B' })).toBeInTheDocument()
    expect(within(o).queryByRole('option', { name: 'Toà C' })).not.toBeInTheDocument()
    await userEvent.selectOptions(o, 'B')

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toMatchObject({ block: 'B' })
  })

  it('ô toà giữ mã toà đang lưu dù toà đó không có trong danh sách', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({ ...CAN, block: 'X9' }),
      ),
    )
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    expect(screen.getByRole('combobox', { name: /Toà \/ block/ })).toHaveValue('X9')
  })
})
