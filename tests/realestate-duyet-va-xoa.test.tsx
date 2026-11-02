/**
 * Ba mảnh giao diện của đợt bỏ nút nạp:
 *   · Nút Duyệt cho chữ do OCR đọc — hai nút DUY NHẤT còn cần người bấm là nó và Thử lại.
 *   · Không tả nháp cho ảnh Vị trí / Mặt bằng (bản đồ và bản vẽ).
 *   · Xoá dự án là POPUP, không phải khối dưới đáy danh sách.
 */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, TAI_LIEU, boot, datApiDoc, giaTriXem, moSuaDuAn, trang } from './re-fixture'

describe('duyệt chữ đọc từ ảnh', () => {
  const CHO_DUYET = { ...TAI_LIEU, bodyChoDuyet: true }

  it('tài liệu chờ duyệt hiện nhãn và nút Duyệt', async () => {
    datApiDoc({ documents: trang([CHO_DUYET]) })
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
    await userEvent.click(await screen.findByText(CHO_DUYET.title))

    expect(await screen.findByText(/Nội dung đọc từ ảnh — bấm Duyệt để agent dùng/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Duyệt$/ })).toBeInTheDocument()
  })

  it('tài liệu KHÔNG chờ duyệt thì không hiện gì thêm', async () => {
    datApiDoc({ documents: trang([TAI_LIEU]) })
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
    await userEvent.click(await screen.findByText(TAI_LIEU.title))

    await waitFor(() => expect(giaTriXem('Nội dung')).toHaveTextContent(TAI_LIEU.body))
    expect(screen.queryByText(/bấm Duyệt để agent dùng/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Duyệt$/ })).not.toBeInTheDocument()
  })

  it('bấm Duyệt gọi đúng endpoint của tài liệu đó', async () => {
    const goi = vi.fn()
    datApiDoc({ documents: trang([CHO_DUYET]) })
    server.use(
      http.post('/api/v1/projects/:code/documents/:id/approve', ({ params }) => {
        goi(params.id)
        return HttpResponse.json({ approved: true }, { status: 202 })
      }),
    )
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
    await userEvent.click(await screen.findByText(CHO_DUYET.title))
    await userEvent.click(await screen.findByRole('button', { name: /^Duyệt$/ }))

    await waitFor(() => expect(goi).toHaveBeenCalledWith(String(CHO_DUYET.id)))
  })

  it('duyệt xong thì nhãn biến mất mà không phải tải lại màn', async () => {
    datApiDoc({ documents: trang([CHO_DUYET]) })
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
    await userEvent.click(await screen.findByText(CHO_DUYET.title))
    await userEvent.click(await screen.findByRole('button', { name: /^Duyệt$/ }))

    await waitFor(() =>
      expect(screen.queryByText(/bấm Duyệt để agent dùng/)).not.toBeInTheDocument(),
    )
  })
})

describe('mô tả nháp cho ảnh', () => {
  /** Tải một ảnh vào vùng media của một tab, trả về số lần gọi sinh mô tả. */
  async function taiAnhVaoTab(tab: string) {
    const goi = vi.fn()
    datApiDoc({ media: trang([]) })
    server.use(
      http.post('/api/v1/realestate/uploads', () =>
        HttpResponse.json(
          { key: 'tenants/rew/kb-bds/x/a.webp', contentHash: 'h', contentType: 'image/webp' },
          { status: 201 },
        ),
      ),
      http.post('/api/v1/media/draft-caption', () => {
        goi()
        return HttpResponse.json({ jobId: 3, state: 'queued' }, { status: 202 })
      }),
    )
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: tab }))
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: /Thêm ảnh/ }))
    fireEvent.change(await screen.findByLabelText(/Kéo thả hoặc chọn tệp — Ảnh mới/), {
      target: { files: [new File([new Uint8Array([1])], 'a.webp', { type: 'image/webp' })] },
    })
    // Chờ hết lượt tải lên rồi mới khẳng định: khẳng định ngay là khẳng định TRƯỚC khi
    // nhánh sinh mô tả có cơ hội chạy, và test sẽ xanh cả khi nhánh đó vẫn còn.
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Thêm vào danh mục/ })).toBeEnabled(),
    )
    return goi
  }

  it('ảnh Mặt bằng KHÔNG gọi sinh mô tả — bản vẽ tả ra chữ vô nghĩa', async () => {
    expect(await taiAnhVaoTab('Mặt bằng')).not.toHaveBeenCalled()
  })

  it('ảnh Vị trí KHÔNG gọi sinh mô tả — bản đồ cũng vậy', async () => {
    expect(await taiAnhVaoTab('Vị trí')).not.toHaveBeenCalled()
  })

  it('ảnh Tiến độ VẪN gọi sinh mô tả — cổng canh việc tắt nhầm cả lượt', async () => {
    const goi = await taiAnhVaoTab('Tiến độ')
    await waitFor(() => expect(goi).toHaveBeenCalled())
  })
})

describe('xoá dự án', () => {
  it('là popup: có role dialog và lớp mờ phía sau', async () => {
    datApiDoc({ projects: trang([DU_AN]) })
    boot('/projects')
    await screen.findByText('Vinhomes Ocean Park 2')

    await userEvent.click(screen.getByRole('button', { name: /Xoá/ }))

    const hop = await screen.findByRole('alertdialog')
    expect(hop).toHaveAttribute('aria-modal', 'true')
    expect(hop).toHaveTextContent(/Xoá dự án VHOP2/)
  })

  it('tiêu điểm vào Huỷ — hành động này không hoàn tác được', async () => {
    datApiDoc({ projects: trang([DU_AN]) })
    boot('/projects')
    await screen.findByText('Vinhomes Ocean Park 2')
    await userEvent.click(screen.getByRole('button', { name: /Xoá/ }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Huỷ' })).toHaveFocus())
  })

  it('Esc đóng popup mà không xoá gì', async () => {
    const goi = vi.fn()
    datApiDoc({ projects: trang([DU_AN]) })
    server.use(
      http.delete('/api/v1/projects/:code', () => {
        goi()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot('/projects')
    await screen.findByText('Vinhomes Ocean Park 2')
    await userEvent.click(screen.getByRole('button', { name: /Xoá/ }))
    await screen.findByRole('alertdialog')

    await userEvent.keyboard('{Escape}')

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(goi).not.toHaveBeenCalled()
  })

  it('bấm Xoá trong popup thì gọi DELETE', async () => {
    const goi = vi.fn()
    datApiDoc({ projects: trang([DU_AN]) })
    server.use(
      http.delete('/api/v1/projects/:code', ({ params }) => {
        goi(params.code)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot('/projects')
    await screen.findByText('Vinhomes Ocean Park 2')
    await userEvent.click(screen.getByRole('button', { name: /Xoá/ }))

    const hop = await screen.findByRole('alertdialog')
    await userEvent.click(within(hop).getByRole('button', { name: /^Xoá$/ }))

    await waitFor(() => expect(goi).toHaveBeenCalledWith('VHOP2'))
  })
})
