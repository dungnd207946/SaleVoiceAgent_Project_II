/**
 * Xoá ảnh phải THẤY ĐƯỢC — spec 2026-08-21 issue 4.
 *
 * Bản trước: mỗi ảnh có đúng một nút `✎ Sửa` mang `opacity-0
 * group-hover:opacity-100`, và Xoá nằm trong hộp thoại sau nó. Bốn bước, bước
 * đầu vô hình cho tới khi đưa chuột lên — trên cảm ứng thì không có bước đầu.
 *
 * `opacity-0` KHÔNG phải `display:none`, nên jsdom vẫn tìm thấy nút và một bài
 * test dùng `getByRole` sẽ xanh dù người dùng thật không thấy gì. Vì vậy bài
 * dưới đây canh THẲNG danh sách lớp — đó là chỗ duy nhất sự thật nằm.
 *
 * Từ 2026-10-08, ở Vị trí và Mặt bằng các nút này chỉ có sau khi bấm Sửa và nằm dưới ảnh.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { MEDIA, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

const ANH = { ...MEDIA, id: 95, category: 'mat_bang', caption: 'Mặt bằng tầng 1' }

async function moTabMatBang(anh = [ANH]) {
  datApiDoc({ media: trang(anh) })
  boot('/pform?code=VHOP2&tab=mat-bang')
  await moSuaDuAn()
}

describe('nút trên ảnh không núp sau hover', () => {
  it('chưa bấm Sửa thì không có nút sửa hay xoá ảnh', async () => {
    datApiDoc({ media: trang([ANH]) })
    boot('/pform?code=VHOP2&tab=mat-bang')
    await screen.findByRole('button', { name: /Phóng to/ })
    expect(screen.queryByRole('button', { name: /Sửa mô tả/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Xoá ảnh/ })).not.toBeInTheDocument()
  })

  it('nút sửa hiện thường trực — không mang opacity-0/group-hover', async () => {
    await moTabMatBang()
    const nut = await screen.findByRole('button', { name: /Sửa mô tả/ })
    expect(nut.className).not.toMatch(/\bopacity-0\b/)
    expect(nut.className).not.toMatch(/group-hover:/)
  })

  it('có nút xoá riêng ngay dưới ảnh, cũng hiện thường trực', async () => {
    await moTabMatBang()
    const nut = await screen.findByRole('button', { name: /Xoá ảnh/ })
    expect(nut.className).not.toMatch(/\bopacity-0\b/)
    expect(nut.className).not.toMatch(/group-hover:/)
  })

  it('bố cục lưới: mỗi ảnh có cặp nút của riêng nó', async () => {
    const anh = (id: number, caption: string) => ({ ...MEDIA, id, category: 'tien_do', caption })
    datApiDoc({ media: trang([anh(97, 'Tháng 6'), anh(98, 'Tháng 7')]) })
    boot('/pform?code=VHOP2&tab=tien-do')

    expect(await screen.findAllByRole('button', { name: /Xoá ảnh/ })).toHaveLength(2)
    expect(await screen.findAllByRole('button', { name: /Sửa ảnh/ })).toHaveLength(2)
  })

  /**
   * Bố cục `gallery` (Vị trí · Mặt bằng) cố ý chỉ đặt nút dưới ẢNH ĐANG CHỌN —
   * thumbnail không đủ chỗ cho hai nút bấm được. Xoá một ảnh khác thì bấm
   * thumbnail của nó trước, và thấy rõ mình đang xoá cái gì.
   */
  it('bố cục gallery: nút chỉ nằm dưới ảnh đang chọn', async () => {
    await moTabMatBang([ANH, { ...ANH, id: 96, caption: 'Mặt bằng tầng 2' }])
    expect(await screen.findAllByRole('button', { name: /Xoá ảnh/ })).toHaveLength(1)
    expect(screen.getByRole('button', { name: /Xoá ảnh — Mặt bằng tầng 1/ })).toBeInTheDocument()
  })
})

describe('xoá đi từ hai cú bấm, không phải bốn', () => {
  it('bấm Xoá ảnh rồi xác nhận là DELETE — không mở hộp thoại sửa', async () => {
    const daXoa: string[] = []
    await moTabMatBang()
    server.use(
      http.delete('/api/v1/projects/:code/media/:id', ({ params }) => {
        daXoa.push(String(params.id))
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await userEvent.click(await screen.findByRole('button', { name: /Xoá ảnh/ }))
    // Xác nhận tại chỗ, không phải form sửa: chú thích không được hiện ra.
    expect(screen.queryByRole('textbox', { name: /Chú thích/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Xoá hẳn' }))

    await waitFor(() => expect(daXoa).toEqual(['95']))
  })

  it('bỏ xác nhận thì không gọi DELETE', async () => {
    let goi = 0
    await moTabMatBang()
    server.use(
      http.delete('/api/v1/projects/:code/media/:id', () => {
        goi += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )

    await userEvent.click(await screen.findByRole('button', { name: /Xoá ảnh/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Thôi' }))

    expect(goi).toBe(0)
    expect(screen.queryByRole('button', { name: 'Xoá hẳn' })).not.toBeInTheDocument()
  })
})
