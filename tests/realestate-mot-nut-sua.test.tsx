/**
 * MỘT nút Sửa cho cả hồ sơ dự án, không phải mỗi tab một nút.
 *
 * Người dùng chốt 2026-08-21: nút Sửa mở khoá mọi tab — bấm Sửa ở Tổng quan rồi sang Vị trí thì
 * vẫn đang sửa. Từ 2026-10-08 (mockup đã duyệt): chế độ xem hiện giá trị dạng chữ, không còn ô
 * nhập bị khoá; nút Sửa/Xong nằm cuối hàng tab; màn chi tiết phân khu, toà, căn (`/uform`) dùng
 * chung cờ đó. Trong chế độ sửa vẫn tự lưu từng ô; nút Xong chỉ đóng chế độ sửa, không gửi gì.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { DU_AN, boot, datApiDoc, giaTriXem, trang } from './re-fixture'
import { server } from '../vitest.setup'

function dat() {
  datApiDoc({ media: trang([]), zones: trang([]), documents: trang([]) })
}

function batPatch() {
  const than: Record<string, unknown>[] = []
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(DU_AN)
    }),
  )
  return than
}

const nutSua = () => screen.findByRole('button', { name: 'Sửa' })

describe('mở ra là bản xem dạng chữ', () => {
  it('chưa bấm Sửa thì không có ô nhập nào, giá trị hiện thành chữ', async () => {
    dat()
    boot('/pform?code=VHOP2')

    await waitFor(() => expect(giaTriXem('Chủ đầu tư')).toHaveTextContent(DU_AN.investor))
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()

    await userEvent.click(await nutSua())
    expect(screen.getByRole('textbox', { name: /Chủ đầu tư/ })).toBeEnabled()
  })

  it('nút Sửa nằm cùng hàng tab, ở đầu trang', async () => {
    dat()
    boot('/pform?code=VHOP2')
    const dinh = await screen.findByTestId('pform-dinh')
    expect(dinh).toContainElement(await nutSua())
    expect(within(dinh).getByRole('tablist')).toBeInTheDocument()
    expect(screen.queryByTestId('pform-day')).not.toBeInTheDocument()
  })

  it('bấm Sửa thì nút đổi thành Xong và hiện dải báo đang sửa', async () => {
    dat()
    boot('/pform?code=VHOP2')
    expect(screen.queryByTestId('dai-dang-sua')).not.toBeInTheDocument()
    await userEvent.click(await nutSua())

    expect(screen.getByRole('button', { name: 'Xong' })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Sửa' })).not.toBeInTheDocument()
    expect(screen.getByTestId('dai-dang-sua')).toBeInTheDocument()
  })

  it('bấm Xong thì về bản xem', async () => {
    dat()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nutSua())
    await userEvent.click(screen.getByRole('button', { name: 'Xong' }))

    expect(screen.queryByRole('textbox', { name: /Chủ đầu tư/ })).not.toBeInTheDocument()
    expect(screen.queryByTestId('dai-dang-sua')).not.toBeInTheDocument()
  })
})

describe('MỘT công tắc cho cả mười tab', () => {
  it('bấm Sửa ở Tổng quan rồi sang Vị trí thì vẫn đang sửa', async () => {
    dat()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nutSua())

    await userEvent.click(screen.getByRole('tab', { name: 'Vị trí' }))

    expect(await screen.findByRole('textbox', { name: /Khu vực/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Xong' })).toBeInTheDocument()
  })

  it('chưa bấm Sửa thì tab Vị trí cũng chỉ hiện chữ', async () => {
    dat()
    boot('/pform?code=VHOP2&tab=vi-tri')
    await waitFor(() => expect(giaTriXem('Khu vực')).toHaveTextContent('Hà Nội'))
    expect(screen.queryByRole('textbox', { name: /Khu vực/ })).not.toBeInTheDocument()
  })

  it('tab Ảnh 360 theo cùng công tắc', async () => {
    dat()
    boot('/pform?code=VHOP2&tab=anh-360')
    await screen.findByRole('link', { name: 'Mở ở tab mới' })
    expect(screen.queryByRole('textbox', { name: /Link tham quan 360/ })).not.toBeInTheDocument()
    await userEvent.click(await nutSua())
    expect(screen.getByRole('textbox', { name: /Link tham quan 360/ })).toBeEnabled()
  })
})

describe('trong chế độ sửa vẫn tự lưu', () => {
  it('rời ô là PATCH; Xong không gửi thêm gì', async () => {
    dat()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nutSua())

    const o = screen.getByRole('textbox', { name: /Chủ đầu tư/ })
    await userEvent.clear(o)
    await userEvent.type(o, 'Ecopark')
    await userEvent.tab()

    await waitFor(() => expect(than).toEqual([{ investor: 'Ecopark' }]))
    await userEvent.click(screen.getByRole('button', { name: 'Xong' }))
    expect(than).toEqual([{ investor: 'Ecopark' }])
  })

  it('lưu xong thì đầu trang báo giờ lưu', async () => {
    dat()
    batPatch()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nutSua())

    await userEvent.type(screen.getByRole('textbox', { name: /Chủ đầu tư/ }), ' thêm')
    await userEvent.tab()

    expect(await screen.findByText(/Đã lưu lúc \d{2}:\d{2}/)).toBeInTheDocument()
  })

  it('gõ dở rồi nhảy tab: không hộp nào, và đã lưu', async () => {
    dat()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nutSua())

    await userEvent.type(screen.getByRole('textbox', { name: /Chủ đầu tư/ }), ' thêm')
    await userEvent.click(screen.getByRole('tab', { name: 'Vị trí' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() => expect(than).toHaveLength(1))
  })
})

describe('màn chi tiết theo cùng công tắc', () => {
  it('mở một phân khu: chỉ hiện chữ cho tới khi bấm Sửa', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=phan-khu')
    await userEvent.click(await screen.findByText('Zurich'))

    await waitFor(() => expect(giaTriXem('Tên phân khu')).toHaveTextContent('Zurich'))
    expect(screen.queryByRole('textbox', { name: /Tên phân khu/ })).not.toBeInTheDocument()
    await userEvent.click(await nutSua())
    expect(screen.getByRole('textbox', { name: /Tên phân khu/ })).toBeEnabled()
  })

  it('đang sửa thì mở phân khu ra là sửa được ngay', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=phan-khu')
    await screen.findByText('Zurich')
    await userEvent.click(await nutSua())
    await userEvent.click(screen.getByRole('button', { name: 'Zurich' }))

    expect(await screen.findByRole('textbox', { name: /Tên phân khu/ })).toBeEnabled()
  })

  it('mở một tài liệu: chỉ hiện chữ cho tới khi bấm Sửa', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await userEvent.click(await screen.findByText('Chính sách bán hàng Q3'))

    await waitFor(() => expect(giaTriXem('Tiêu đề')).toHaveTextContent('Chính sách bán hàng Q3'))
    expect(screen.queryByRole('textbox', { name: /Tiêu đề/ })).not.toBeInTheDocument()
    await userEvent.click(await nutSua())
    expect(screen.getByRole('textbox', { name: /Tiêu đề/ })).toBeEnabled()
  })

  it('nút thêm hàng chỉ có khi đang sửa; form TẠO hàng mới nhập được ngay', async () => {
    datApiDoc({ zones: trang([]) })
    boot('/pform?code=VHOP2&tab=phan-khu')
    await screen.findByText('Dự án này chưa có phân khu nào.')
    expect(screen.queryByRole('button', { name: 'Thêm phân khu' })).not.toBeInTheDocument()

    await userEvent.click(await nutSua())
    await userEvent.click(screen.getByRole('button', { name: 'Thêm phân khu' }))
    expect(screen.getByRole('textbox', { name: /Tên phân khu/ })).toBeEnabled()
  })
})

describe('/uform dùng chung công tắc với hồ sơ dự án', () => {
  it('một căn đã có: chỉ hiện chữ cho tới khi bấm Sửa', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=41')

    await screen.findByText('Thông tin căn')
    expect(screen.queryByRole('spinbutton', { name: /Giá bán/ })).not.toBeInTheDocument()
    await userEvent.click(await nutSua())
    expect(screen.getByRole('spinbutton', { name: /Giá bán/ })).toBeEnabled()
  })

  it('đang sửa ở hồ sơ dự án thì mở một căn ra là sửa được ngay', async () => {
    datApiDoc()
    const router = boot('/pform?code=VHOP2&tab=quy-can')
    await userEvent.click(await nutSua())
    await router.navigate({ to: '/uform', search: { code: 'VHOP2', unit: 41 } })

    expect(await screen.findByRole('spinbutton', { name: /Giá bán/ })).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Xong' })).toBeInTheDocument()
  })

  it('TẠO căn mới thì không khoá và không có nút Sửa — nút Tạo căn là công tắc của nó', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2')
    await screen.findByRole('option', { name: /Zurich/ })

    expect(screen.getByRole('textbox', { name: /Mã căn/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Sửa' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Xong' })).not.toBeInTheDocument()
  })
})

describe('đường TẠO không bị khoá', () => {
  it('chưa có dự án thì ô tên nhập được ngay, không cần bấm Sửa', async () => {
    dat()
    boot('/pform')
    expect(await screen.findByRole('textbox', { name: /Tên thương mại/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Sửa' })).not.toBeInTheDocument()
  })
})
