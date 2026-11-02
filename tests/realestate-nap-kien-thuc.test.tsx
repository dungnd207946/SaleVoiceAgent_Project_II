/**
 * Chỉ báo «nội dung đang trên đường tới agent» — thay cho nút nạp + badge sáu trạng thái.
 *
 * Bốn thứ màn này phải giữ:
 *   · Không còn nút nào để bấm ở đường bình thường. Nhập liệu xong là xong.
 *   · Thanh tiến độ thay dòng chữ tĩnh (2026-08-25): một đợt nạp có thể kéo hàng giờ,
 *     và «đang nạp» không phân biệt được chậm với kẹt. Số nằm ở title, rê mới thấy.
 *   · Chữ không lộ từ kỹ thuật: người đọc là biên tập viên nội dung.
 *   · Poll chỉ chạy khi có dự án đang nạp, và DỪNG khi xong.
 *
 * 2026-08-17: chỉ báo RỜI KHỎI danh sách `/projects` (bỏ cột «Kiến thức agent» theo yêu
 * cầu người dùng). Nó chỉ còn ở header trang chi tiết dự án, nên phần lớn bài dưới đây
 * mở `/pform?code=…` thay vì `/projects`.
 */
import { describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, KB_DA_NAP, boot, datApiDoc, kbDangNap, kbLoi, trang } from './re-fixture'

const TIEN_DO = 'progressbar'
const LOI = /Lỗi nạp kiến thức cho agent/

describe('chỉ báo nạp kiến thức', () => {
  it('nạp đủ thì đầu trang không có thanh, thẻ kiến thức ghi đủ mục', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [KB_DA_NAP] })
    boot('/pform?code=VHOP2')

    const the = await screen.findByRole('group', { name: 'Kiến thức cho agent' })
    await waitFor(() => expect(the).toHaveTextContent(/12\/12\s*mục/))
    expect(screen.queryByRole(TIEN_DO)).not.toBeInTheDocument()
    expect(screen.queryByText(LOI)).not.toBeInTheDocument()
  })

  it('đang chạy thì thanh hiện phần trăm, số đầy đủ nằm ở title', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [kbDangNap()] })
    boot('/pform?code=VHOP2')

    const thanh = await screen.findByRole(TIEN_DO)
    expect(thanh).toHaveAttribute('title', '5/12 mục đã tới agent')
    expect(screen.getByText('42%')).toBeInTheDocument()
  })

  it('lỗi thì đầu trang hiện nhãn lỗi kèm nút Thử lại, thẻ kiến thức không nhắc lại', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [kbLoi()] })
    boot('/pform?code=VHOP2')

    expect(await screen.findByText(LOI)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Thử lại/ })).toBeInTheDocument()
    expect(screen.getByTestId('pform-dinh')).toHaveTextContent(LOI)
  })

  it('không lỗi thì KHÔNG có nút Thử lại', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [kbDangNap()] })
    boot('/pform?code=VHOP2')
    await screen.findByRole(TIEN_DO)

    expect(screen.queryByRole('button', { name: /Thử lại/ })).not.toBeInTheDocument()
  })

  it('không còn nút nạp nào ở đường bình thường', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [KB_DA_NAP] })
    boot('/projects')
    await screen.findByText('Vinhomes Ocean Park 2')

    expect(screen.queryByRole('button', { name: /^Nạp kiến thức cho agent$/ })).not.toBeInTheDocument()
    expect(screen.queryByText(/Nạp lại toàn bộ/)).not.toBeInTheDocument()
  })

  it('không lộ từ kỹ thuật nào ra giao diện', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [kbLoi()] })
    boot('/pform?code=VHOP2')
    await screen.findByText(LOI)

    for (const tu of [/qdrant/i, /kho vector/i, /đồng bộ/i, /\bembed\b/i, /\bindex\b/i]) {
      expect(screen.queryByText(tu)).not.toBeInTheDocument()
    }
  })

  it('danh sách dự án KHÔNG còn cột kiến thức agent', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [kbLoi()] })
    boot('/projects')
    await screen.findByText('Vinhomes Ocean Park 2')

    expect(screen.queryByRole('columnheader', { name: /Kiến thức agent/ })).not.toBeInTheDocument()
    expect(screen.queryByText(LOI)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Thử lại/ })).not.toBeInTheDocument()
  })
})

describe('nút Thử lại', () => {
  it('bấm là gọi nạp lại phần thay đổi', async () => {
    const goi = vi.fn()
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [kbLoi()] })
    server.use(
      http.post('/api/v1/projects/:code/sync-kb', ({ request }) => {
        goi(new URL(request.url).searchParams.get('mode'))
        return HttpResponse.json({ jobId: 1, state: 'queued' }, { status: 202 })
      }),
    )
    boot('/pform?code=VHOP2')
    await screen.findByText(LOI)

    await userEvent.click(screen.getByRole('button', { name: /Thử lại/ }))
    await waitFor(() => expect(goi).toHaveBeenCalledWith('delta'))
  })

})

describe('chỉ báo ở header trang chi tiết', () => {
  it('hiện trạng thái của đúng dự án đang mở', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [kbDangNap()] })
    boot('/pform?code=VHOP2')

    expect(await screen.findByRole(TIEN_DO)).toBeInTheDocument()
  })

  it('màn tạo dự án MỚI không hiện gì — chưa có dự án nào để nạp', async () => {
    datApiDoc({ projects: trang([DU_AN]), kbStatus: [kbDangNap()] })
    boot('/pform')

    await screen.findByText(/Dự án mới/)
    expect(screen.queryByRole(TIEN_DO)).not.toBeInTheDocument()
  })
})

describe('chỉ báo không được làm sập màn', () => {
  it('trạng thái trả về sai hình dạng thì danh sách dự án vẫn hiện', async () => {
    // Xảy ra thật: `kb-status` nằm dưới cùng tiền tố với `GET /projects/{code}`,
    // nên một thứ tự route sai ở bất kỳ tầng nào cũng làm nó nhận về một object
    // dự án. Mất chỉ báo là chấp nhận được; mất cả bảng thì không.
    datApiDoc({ projects: trang([DU_AN]), kbStatus: DU_AN })
    boot('/projects')

    expect(await screen.findByText('Vinhomes Ocean Park 2')).toBeInTheDocument()
  })
})
