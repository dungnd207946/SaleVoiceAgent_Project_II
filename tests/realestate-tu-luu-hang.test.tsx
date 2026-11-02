/**
 * Tự lưu cho ba form HÀNG — phân khu · tài liệu · căn.
 *
 * Cùng luật với ba tab cột-dự-án: mở một hàng ra là sửa được ngay, mỗi ô tự lưu
 * khi rời ô, không nút Sửa · Huỷ · Lưu.
 *
 * TẠO một hàng mới thì VẪN cần một nút: chưa có hàng thì không có gì để PATCH.
 * Đó là ranh giới duy nhất giữa hai chế độ, và nó là ranh giới kỹ thuật thật.
 *
 * Khoá nghiệp vụ (mã phân khu · mã căn · phân khu của căn · loại sản phẩm) vẫn
 * chỉ-đọc khi sửa — `ZonePatch`/`UnitPatch` không có ô đó.
 *
 * ⚠️ Nút Sửa đã quay lại (2026-08-21) và nó là MỘT công tắc cho cả form — mở một
 * hàng ra vẫn là bản chỉ-đọc cho tới khi bấm nó. Bên trong thì tự lưu từng ô.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { CAN, PHAN_KHU, TAI_LIEU, boot, datApiDoc, giaTriXem, moSuaDuAn, trang } from './re-fixture'
import { server } from '../vitest.setup'

function bat(duong: string, method: 'patch' | 'post', tra: object) {
  const than: Record<string, unknown>[] = []
  server.use(
    http[method](duong, async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(tra, { status: method === 'post' ? 201 : 200 })
    }),
  )
  return than
}

describe('form phân khu', () => {
  async function moHang() {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=phan-khu')
    await userEvent.click(await screen.findByText('Zurich'))
    await moSuaDuAn()
  }

  it('bấm Sửa là nhập được, và không có nút Lưu phân khu', async () => {
    await moHang()
    expect(screen.getByRole('textbox', { name: /Tên phân khu/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: /^Lưu phân khu/ })).not.toBeInTheDocument()
  })

  it('rời ô ⇒ PATCH đúng một trường', async () => {
    const than = bat('/api/v1/projects/:code/zones/:zoneCode', 'patch', PHAN_KHU)
    await moHang()

    const o = screen.getByRole('textbox', { name: /Quy mô phân khu/ })
    await userEvent.clear(o)
    await userEvent.type(o, '3 toà')
    await userEvent.tab()

    await waitFor(() => expect(than).toEqual([{ productScale: '3 toà' }]))
  })

  it('mã phân khu vẫn chỉ-đọc — khoá bất biến', async () => {
    await moHang()
    expect(screen.queryByRole('textbox', { name: /Mã phân khu/ })).not.toBeInTheDocument()
    expect(screen.getByText('ZURICH')).toBeInTheDocument()
  })

  it('TẠO phân khu mới thì vẫn có một nút', async () => {
    const than = bat('/api/v1/projects/:code/zones', 'post', PHAN_KHU)
    datApiDoc({ zones: trang([]) })
    boot('/pform?code=VHOP2&tab=phan-khu')
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm phân khu' }))

    await userEvent.type(screen.getByRole('textbox', { name: /Tên phân khu/ }), 'Sao Biển')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu phân khu' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.name).toBe('Sao Biển')
  })
})

describe('form tài liệu', () => {
  async function moHang() {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await userEvent.click(await screen.findByText('Chính sách bán hàng Q3'))
    await moSuaDuAn()
  }

  it('bấm Sửa là nhập được', async () => {
    await moHang()
    expect(screen.getByRole('textbox', { name: /Tiêu đề/ })).toBeEnabled()
  })

  it('rời ô Tiêu đề ⇒ PATCH — và `loai` đi kèm vì nó nhập vào chính `title`', async () => {
    const than = bat('/api/v1/projects/:code/documents/:id', 'patch', TAI_LIEU)
    await moHang()

    const o = screen.getByRole('textbox', { name: /Tiêu đề/ })
    await userEvent.clear(o)
    await userEvent.type(o, 'CSBH Q4')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.title).toBe('CSBH Q4')
  })

  it('TẠO tài liệu mới thì vẫn có một nút', async () => {
    datApiDoc({ documents: trang([]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm tài liệu' }))
    expect(screen.getByRole('button', { name: /Lưu tài liệu/ })).toBeInTheDocument()
  })
})

describe('form căn', () => {
  async function moCan() {
    datApiDoc()
    server.use(http.get('/api/v1/projects/:code/units/:id', () => HttpResponse.json(CAN)))
    boot('/uform?code=VHOP2&unit=41')
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
  }

  it('bấm Sửa là nhập được', async () => {
    await moCan()
    expect(screen.getByRole('spinbutton', { name: /Giá bán/ })).toBeEnabled()
  })

  it('rời ô ⇒ PATCH đúng một trường', async () => {
    const than = bat('/api/v1/projects/:code/units/:id', 'patch', CAN)
    await moCan()

    const o = screen.getByRole('spinbutton', { name: /Đơn giá/ })
    await userEvent.clear(o)
    await userEvent.type(o, '81000000')
    await userEvent.tab()

    // `status` ĐI KÈM ở form căn, khác dự án: trạng thái của một căn được SUY ra
    // từ dữ liệu (`trangThaiCan`), không ai chọn — không gửi nó thì điền nốt Giá
    // bán mà căn vẫn nằm `draft` và agent không đọc. Dự án thì có chip, và chip
    // là người sở hữu duy nhất nên PATCH ở đó KHÔNG được mang `status`.
    await waitFor(() =>
      expect(than).toEqual([{ pricePerM2Vnd: 81000000, status: CAN.status }]),
    )
  })

  it('ba khoá nghiệp vụ vẫn khoá — hiện thành chữ, kể cả khi đang sửa', async () => {
    await moCan()
    for (const nhan of [/Mã căn/, /Phân khu/, /Loại sản phẩm/]) {
      expect(screen.queryByRole('textbox', { name: nhan })).not.toBeInTheDocument()
      expect(screen.queryByRole('combobox', { name: nhan })).not.toBeInTheDocument()
    }
    expect(giaTriXem('Mã căn')).toHaveTextContent(CAN.unitCode)
  })

  it('TẠO căn mới thì vẫn có một nút', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2')
    await screen.findByRole('option', { name: /Zurich/ })
    expect(screen.getByRole('button', { name: /Tạo căn/ })).toBeInTheDocument()
  })
})
