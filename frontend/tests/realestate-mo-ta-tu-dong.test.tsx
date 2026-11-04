/**
 * Mô tả tự động (job `kb_enrich`) hiện lên màn và SỬA ĐƯỢC.
 *
 * Trước vòng này chú thích trong kho media là chữ CHỈ ĐỌC (`<p>`), nên mô tả do
 * máy sinh hiện ra mà người dùng không sửa được — đúng nửa yêu cầu bị bỏ.
 *
 * Ba thứ màn này phải giữ:
 *   · Đang tạo thì nói rõ, không hiện ô trống (người dùng tưởng job không chạy).
 *   · Sửa xong rời ô là lưu; không đổi chữ thì KHÔNG gọi API.
 *   · Có đường tạo lại mô tả cho một ảnh cụ thể.
 */
import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { MEDIA, boot, datApiDoc, trang } from './re-fixture'

/** Tab Media mở sẵn một danh mục — vùng ảnh nằm trong đó. */
async function moDanhMucTongQuan() {
  await userEvent.click(await screen.findByRole('button', { name: /Tổng quan/ }))
}

describe('kho media — xem tên, sửa qua hộp thoại', () => {
  it('danh sách hiện TÊN TỆP rồi tới mô tả, không hiện ô nhập', async () => {
    // Đảo chiều 2026-08-25: tên tệp lên dòng chính, mô tả xuống dòng phụ. Trước đó
    // mô tả đứng trước và tên tệp chỉ nằm trong `title`.
    datApiDoc({ media: trang([{ ...MEDIA, fileName: 'Phối cảnh tổng thể.jpg', caption: 'Mô tả máy viết' }]) })
    boot('/pform?code=VHOP2&tab=media')
    await moDanhMucTongQuan()

    expect(await screen.findByText('Phối cảnh tổng thể.jpg')).toBeInTheDocument()
    expect(screen.getByText('Mô tả máy viết')).toBeInTheDocument()
    // Sửa vẫn phải đi qua hộp thoại — danh sách không có ô nhập nào.
    expect(screen.queryByDisplayValue('Mô tả máy viết')).not.toBeInTheDocument()
  })

  it('chưa có mô tả thì rơi về tên tệp', async () => {
    datApiDoc({ media: trang([{ ...MEDIA, fileName: 'Phối cảnh tổng thể.jpg', caption: '' }]) })
    boot('/pform?code=VHOP2&tab=media')
    await moDanhMucTongQuan()

    expect(await screen.findByText('Phối cảnh tổng thể.jpg')).toBeInTheDocument()
  })

  it('bấm Sửa mới mở được ô tên và ô mô tả', async () => {
    datApiDoc({ media: trang([{ ...MEDIA, fileName: 'a.jpg', caption: 'Mô tả cũ' }]) })
    boot('/pform?code=VHOP2&tab=media')
    await moDanhMucTongQuan()

    expect(screen.queryByRole('dialog', { name: /Chỉnh sửa/ })).not.toBeInTheDocument()
    await userEvent.click(await screen.findByRole('button', { name: /Sửa ảnh/ }))

    const hop = await screen.findByRole('dialog', { name: /Chỉnh sửa/ })
    expect(within(hop).getByDisplayValue('a.jpg')).toBeInTheDocument()
    expect(within(hop).getByDisplayValue('Mô tả cũ')).toBeInTheDocument()
  })

  it('lưu gửi CẢ tên lẫn mô tả trong một PATCH', async () => {
    const than: unknown[] = []
    datApiDoc({ media: trang([{ ...MEDIA, fileName: 'a.jpg', caption: 'cũ' }]) })
    server.use(
      http.patch('/api/v1/projects/:code/media/:id', async ({ request }) => {
        than.push(await request.json())
        return HttpResponse.json(MEDIA)
      }),
    )
    boot('/pform?code=VHOP2&tab=media')
    await moDanhMucTongQuan()
    await userEvent.click(await screen.findByRole('button', { name: /Sửa ảnh/ }))

    const hop = await screen.findByRole('dialog', { name: /Chỉnh sửa/ })
    await userEvent.clear(within(hop).getByDisplayValue('a.jpg'))
    await userEvent.type(within(hop).getByLabelText(/Tên/), 'Mặt bằng tầng 3.jpg')
    await userEvent.click(within(hop).getByRole('button', { name: 'Lưu' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ fileName: 'Mặt bằng tầng 3.jpg', caption: 'cũ' })
  })

  it('xoá nằm trong hộp sửa và phải xác nhận', async () => {
    const goi = vi.fn()
    datApiDoc({ media: trang([{ ...MEDIA, fileName: 'a.jpg' }]) })
    server.use(
      http.delete('/api/v1/projects/:code/media/:id', () => {
        goi()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot('/pform?code=VHOP2&tab=media')
    await moDanhMucTongQuan()
    await userEvent.click(await screen.findByRole('button', { name: /Sửa ảnh/ }))

    const hop = await screen.findByRole('dialog', { name: /Chỉnh sửa/ })
    await userEvent.click(within(hop).getByRole('button', { name: 'Xoá' }))
    expect(goi).not.toHaveBeenCalled()

    await userEvent.click(await within(hop).findByText(/Xoá hẳn khỏi danh mục/))
    await userEvent.click(within(hop).getAllByRole('button', { name: 'Xoá' })[0]!)
    await waitFor(() => expect(goi).toHaveBeenCalled())
  })

  it('KHÔNG còn nút tạo lại mô tả — VLM chỉ chạy lúc tải ảnh lên', async () => {
    datApiDoc({ media: trang([{ ...MEDIA, fileName: 'a.jpg', caption: 'cũ' }]) })
    boot('/pform?code=VHOP2&tab=media')
    await moDanhMucTongQuan()
    await userEvent.click(await screen.findByRole('button', { name: /Sửa ảnh/ }))

    const hop = await screen.findByRole('dialog', { name: /Chỉnh sửa/ })
    expect(within(hop).queryByRole('button', { name: /Tạo lại mô tả/ })).not.toBeInTheDocument()
  })

  it('đang tạo mô tả thì nói rõ thay cho tên', async () => {
    datApiDoc({
      media: trang([{ ...MEDIA, fileName: 'a.jpg', caption: '' }]),
      enrichStatus: [{ entity: 'media', recordId: MEDIA.id, state: 'running', message: '' }],
    })
    boot('/pform?code=VHOP2&tab=media')
    await moDanhMucTongQuan()

    expect(await screen.findByText(/Đang tạo mô tả/)).toBeInTheDocument()
  })
})

describe('mô tả nháp ngay lúc tải ảnh lên — chưa lưu vào danh mục', () => {
  async function moODuong() {
    await moDanhMucTongQuan()
    await userEvent.click(await screen.findByRole('button', { name: /Thêm ảnh \/ video/ }))
  }

  it('tải tệp xong thì mô tả tự điền vào ô, trước khi bấm Thêm vào danh mục', async () => {
    datApiDoc({ media: trang([]), draftCaption: 'Toà căn hộ ven sông, mặt tiền kính.' })
    boot('/pform?code=VHOP2&tab=media')
    await moODuong()

    const o = screen.getByLabelText(/Kéo thả hoặc chọn tệp/)
    await userEvent.upload(o, new File(['x'], 'a.jpg', { type: 'image/jpeg' }))

    expect(
      await screen.findByDisplayValue('Toà căn hộ ven sông, mặt tiền kính.', undefined, {
        timeout: 6000,
      }),
    ).toBeInTheDocument()
  })

  it('người dùng gõ tay trong lúc chờ thì KHÔNG bị đè', async () => {
    datApiDoc({ media: trang([]), draftCaption: 'Máy viết' })
    boot('/pform?code=VHOP2&tab=media')
    await moODuong()

    await userEvent.upload(
      screen.getByLabelText(/Kéo thả hoặc chọn tệp/),
      new File(['x'], 'a.jpg', { type: 'image/jpeg' }),
    )
    const o = await screen.findByLabelText(/Chú thích/)
    await userEvent.type(o, 'Người gõ')

    await new Promise((r) => setTimeout(r, 3000))
    expect(o).toHaveValue('Người gõ')
  })

  it('job hỏng thì ô vẫn gõ được, không chặn lưu', async () => {
    datApiDoc({ media: trang([]) })
    server.use(
      http.get('/api/v1/media/draft-caption/:jobId', () =>
        HttpResponse.json({ state: 'failed', caption: '' }),
      ),
    )
    boot('/pform?code=VHOP2&tab=media')
    await moODuong()

    await userEvent.upload(
      screen.getByLabelText(/Kéo thả hoặc chọn tệp/),
      new File(['x'], 'a.jpg', { type: 'image/jpeg' }),
    )
    const o = await screen.findByLabelText(/Chú thích/)
    await userEvent.type(o, 'Tự gõ')
    expect(o).toHaveValue('Tự gõ')
  })
})
