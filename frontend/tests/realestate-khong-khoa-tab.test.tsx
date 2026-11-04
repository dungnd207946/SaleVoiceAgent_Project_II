/**
 * `/pform` không khoá tab nào — spec 2026-08-21 issue 1 + 2.
 *
 * Bản trước khoá 8/9 tab khi chưa có `?code=`. Không tab nào bị khoá nữa: chưa có
 * dự án thì MỌI tab — kể cả Tổng quan — hiện đúng một ô hỏi tên, chứ không phải
 * một tab xám hay một tab trắng.
 *
 * ⚠️ Bản 2026-08-21 đầu cho Vị trí và Ảnh 360 nhập ngay lúc tạo (gom vào một POST
 * 19 ô). Tự-lưu-từng-ô xoá lý do đó: không còn POST lớn nào, nên mỗi ô về đúng
 * tab của nó và tạo mới chỉ hỏi tên.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

const TAB_CAN_DU_AN = ['Mặt bằng', 'Phân khu', 'Quỹ căn', 'Tiến độ', 'Media', 'Tài liệu']
const TAB_LA_COT_DU_AN = ['Tổng quan', 'Vị trí', 'Ảnh 360']

function batPost() {
  const than: unknown[] = []
  server.use(
    http.post('/api/v1/projects', async ({ request }) => {
      than.push(await request.json())
      // Trả VHOP2 vì `datApiDoc` chỉ phục vụ `GET /projects/VHOP2` — mã khác 404,
      // và bài này kiểm điều hướng sau khi tạo, không kiểm phép sinh mã (đã có test riêng).
      return HttpResponse.json(DU_AN, { status: 201 })
    }),
  )
  return than
}

describe('hàng tab lúc tạo mới', () => {
  it('cả chín tab đều bấm được, không tab nào bị khoá', async () => {
    datApiDoc()
    boot('/pform')
    for (const nhan of [...TAB_LA_COT_DU_AN, ...TAB_CAN_DU_AN]) {
      const nut = await screen.findByRole('tab', { name: nhan })
      expect(nut).toBeEnabled()
      expect(nut).not.toHaveAttribute('aria-disabled', 'true')
    }
  })

  it('không còn câu bảo tạo dự án trước rồi tab mới mở ra', async () => {
    datApiDoc()
    boot('/pform')
    await screen.findByRole('tab', { name: 'Tổng quan' })
    expect(screen.queryByText(/mở ra sau đó/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Tạo dự án trước/)).not.toBeInTheDocument()
  })
})

describe('chưa có dự án thì mọi tab hỏi tên — không tab trắng', () => {
  it.each([...TAB_LA_COT_DU_AN, ...TAB_CAN_DU_AN])(
    'tab %s hỏi tên dự án thay vì để trống',
    async (nhan) => {
      datApiDoc()
      boot('/pform')
      await userEvent.click(await screen.findByRole('tab', { name: nhan }))
      expect(await screen.findByText(/Dự án này tên gì/)).toBeInTheDocument()
      expect(screen.getByRole('textbox', { name: /Tên thương mại/ })).toBeInTheDocument()
    },
  )

  it('ô của tab khác KHÔNG lẫn vào đường tạo', async () => {
    datApiDoc()
    boot('/pform?tab=vi-tri')
    await screen.findByRole('textbox', { name: /Tên thương mại/ })
    expect(screen.queryByRole('textbox', { name: /Khu vực/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Link tham quan 360/ })).not.toBeInTheDocument()
  })

  it('POST mang ĐÚNG tên — không có ô nào khác để mang', async () => {
    datApiDoc()
    const than = batPost()
    boot('/pform?tab=vi-tri')

    await userEvent.type(
      await screen.findByRole('textbox', { name: /Tên thương mại/ }),
      'Vinhomes Ocean Park 2',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))

    await waitFor(() => expect(than).toEqual([{ name: 'Vinhomes Ocean Park 2' }]))
  })
})

describe('tạo xong thì ở lại đúng tab', () => {
  it.each(TAB_CAN_DU_AN)('tab %s hiện nội dung thật sau khi đặt tên', async (nhan) => {
    datApiDoc()
    batPost()
    boot('/pform')
    await userEvent.click(await screen.findByRole('tab', { name: nhan }))
    await userEvent.type(
      screen.getByRole('textbox', { name: /Tên thương mại/ }),
      'Vinhomes Ocean Park 2',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))
    await waitFor(() =>
      expect(screen.queryByText(/Dự án này tên gì/)).not.toBeInTheDocument(),
    )
  })

  it('đặt tên rồi Tiếp thì tạo dự án và ở lại ĐÚNG tab đang mở', async () => {
    datApiDoc()
    const than = batPost()
    boot('/pform')
    await userEvent.click(await screen.findByRole('tab', { name: 'Phân khu' }))

    await userEvent.type(
      screen.getByRole('textbox', { name: /Tên thương mại/ }),
      'Vinhomes Ocean Park 2',
    )
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))

    await waitFor(() => expect(than).toEqual([{ name: 'Vinhomes Ocean Park 2' }]))
    expect(await screen.findByRole('button', { name: /Thêm phân khu/ })).toBeInTheDocument()
  })

  it('tên trống thì không gửi gì — backend sẽ 422 và đó là một vòng vô ích', async () => {
    datApiDoc()
    const than = batPost()
    boot('/pform')
    await userEvent.click(await screen.findByRole('tab', { name: 'Media' }))
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))
    expect(than).toEqual([])
  })
})

describe('ô Mã dự án biến mất khỏi form', () => {
  it('tạo mới không có ô nhập mã', async () => {
    datApiDoc()
    boot('/pform')
    await screen.findByRole('textbox', { name: /Tên thương mại/ })
    expect(screen.queryByRole('textbox', { name: /Mã dự án/ })).not.toBeInTheDocument()
  })

  it('dự án đã có thì mã hiện thành chữ dưới tên, kể cả khi sửa cũng không phải ô nhập', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2')
    // Khoanh vùng vào đầu trang: mã còn hiện ở thẻ Thông tin chung nữa.
    const dinh = await screen.findByTestId('pform-dinh')
    expect(await within(dinh).findByText('VHOP2')).toBeInTheDocument()
    await moSuaDuAn()
    expect(screen.queryByRole('textbox', { name: /Mã dự án/ })).not.toBeInTheDocument()
  })
})
