/**
 * Tự lưu từng ô — người dùng chốt 2026-08-21, đảo lại quyết định «giữ nút Sửa».
 *
 * LƯU KHI RỜI Ô, không debounce: bấm sang tab khác thì trình duyệt phát `blur`
 * TRƯỚC `click`, nên phần vừa gõ đã lên đường trước khi tab đổi — đúng chỗ mà
 * hộp «Bỏ thay đổi chưa lưu?» đang chặn. Ô CHỌN thì lưu ngay lúc đổi: chọn một
 * mục đã là một quyết định xong, không có trạng thái «đang gõ dở».
 *
 * PATCH mang ĐÚNG ô vừa đổi, không mang cả form: backend dùng
 * `exclude_unset=True`, nên gửi cả 16 ô là gửi lại 15 giá trị không ai sửa —
 * và một trong số đó có thể vừa bị đổi ở nơi khác.
 *
 * TẠO MỚI không tự lưu được: chưa có hàng nào để PATCH. Đường tạo là một ô tên
 * (`CongDatTen`), và nó là đường DUY NHẤT — nên tab Tổng quan lúc chưa có dự án
 * cũng hiện đúng ô đó.
 *
 * ⚠️ NÚT SỬA ĐÃ QUAY LẠI (người dùng chốt 2026-08-21, lần thứ ba của cùng câu
 * hỏi): form mở ra là bản chỉ-đọc, bấm Sửa mới mở khoá — nhưng bên trong chế độ
 * sửa thì vẫn tự lưu từng ô. Nút Sửa là công tắc XEM/SỬA, không phải nút lưu.
 * Chi tiết công tắc ở `realestate-mot-nut-sua.test.tsx`; ở đây chỉ gọi
 * `moSuaDuAn()` cho xong bước mở.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { DU_AN, boot, datApiDoc, moSuaDuAn } from './re-fixture'
import { server } from '../vitest.setup'

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

const oChu = (re: RegExp) => screen.getByRole('textbox', { name: re })

describe('tab Tổng quan tự lưu', () => {
  it('rời ô Chủ đầu tư ⇒ PATCH mang ĐÚNG một trường', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.clear(oChu(/Chủ đầu tư/))
    await userEvent.type(oChu(/Chủ đầu tư/), 'Ecopark')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ investor: 'Ecopark' })
  })

  it('gõ mà chưa rời ô thì CHƯA gửi gì', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.type(oChu(/Chủ đầu tư/), 'X')
    expect(than).toHaveLength(0)
  })

  it('rời ô mà không đổi gì thì KHÔNG gửi', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.click(oChu(/Chủ đầu tư/))
    await userEvent.tab()
    expect(than).toHaveLength(0)
  })

  it('ô CHỌN lưu ngay lúc đổi, không chờ rời ô', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    const o = screen.getByRole('combobox', { name: /Trạng thái kinh doanh/ })

    await userEvent.selectOptions(o, 'sap_mo_ban')

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ salePhase: 'sap_mo_ban' })
  })

  it('PATCH không bao giờ mang `status` — chip ở hàng tab sở hữu trường đó', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.clear(oChu(/Chủ đầu tư/))
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(Object.keys(than[0]!)).not.toContain('status')
  })
})

describe('nút Huỷ và hộp «chưa lưu» đã biến mất — nút Sửa/Xong thì ở lại', () => {
  it('bấm Sửa là nhập được; không nút Huỷ, và nút Xong KHÔNG gửi gì', async () => {
    // Nút Xong chỉ đóng chế độ sửa — mỗi ô đã tự lưu lúc rời ô. Bài này canh đúng
    // phần đó: bấm nó không sinh request nào ngoài lượt lưu của ô vừa rời.
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    expect(screen.getByRole('textbox', { name: /Chủ đầu tư/ })).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Huỷ' })).not.toBeInTheDocument()

    await userEvent.type(oChu(/Chủ đầu tư/), 'X')
    await userEvent.click(screen.getByRole('button', { name: 'Xong' }))
    await waitFor(() => expect(than).toHaveLength(1))
    expect(Object.keys(than[0]!)).toEqual(['investor'])
  })

  it('gõ dở rồi nhảy tab: KHÔNG hộp xác nhận, và tab đổi thật', async () => {
    datApiDoc()
    batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.type(oChu(/Chủ đầu tư/), ' thêm')
    await userEvent.click(screen.getByRole('tab', { name: 'Vị trí' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Vị trí' })).toHaveAttribute('aria-selected', 'true'),
    )
  })

  it('nhảy tab lưu nốt phần vừa gõ, không mất', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.clear(oChu(/Chủ đầu tư/))
    await userEvent.type(oChu(/Chủ đầu tư/), 'Ecopark')
    await userEvent.click(screen.getByRole('tab', { name: 'Vị trí' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ investor: 'Ecopark' })
  })
})

describe('ô của tab Vị trí về lại tab Vị trí', () => {
  it('tab Tổng quan lúc TẠO MỚI chỉ hỏi tên, không có ô Khu vực', async () => {
    datApiDoc()
    boot('/pform')

    expect(await screen.findByRole('textbox', { name: /Tên thương mại/ })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Khu vực/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Link tham quan 360/ })).not.toBeInTheDocument()
  })

  it('tab Tổng quan của dự án ĐÃ CÓ cũng không mang ô Khu vực', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    expect(screen.queryByRole('textbox', { name: /Khu vực/ })).not.toBeInTheDocument()
  })

  it('ô Khu vực nằm ở tab Vị trí và tự lưu ở đó', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()
    const o = screen.getByRole('textbox', { name: /Khu vực/ })

    await userEvent.clear(o)
    await userEvent.type(o, 'Hưng Yên')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ region: 'Hưng Yên' })
  })
})

describe('câu «Agent chưa đọc dữ liệu này» đã bỏ', () => {
  it('dự án nháp thiếu trường: không còn câu đó ở Tổng quan', async () => {
    datApiDoc({ project: { ...DU_AN, region: '', status: 'draft' } })
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    expect(screen.queryByText(/Agent chưa đọc dữ liệu này/)).not.toBeInTheDocument()
  })

  it('không còn nhãn «cần để phát hành» ở ô nào', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    expect(screen.queryByText('cần để phát hành')).not.toBeInTheDocument()
  })
})
