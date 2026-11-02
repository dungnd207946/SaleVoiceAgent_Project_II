/**
 * Chip Trạng thái ở cột phải hàng tab — spec 2026-08-21 issue 5.
 *
 * `projects.status` là thông tin của CẢ dự án nhưng trước đợt này chỉ sống trong
 * form của tab Tổng quan: đứng ở tab Quỹ căn thì không biết dự án đang nháp hay
 * đã phát hành, và muốn đổi phải quay về tab đầu.
 *
 * MỘT NGƯỜI SỞ HỮU, KHÔNG HAI. Khi chip đã PATCH `{status}` riêng thì tab Tổng
 * quan phải THÔI gửi `status`, nếu không nó gửi lại giá trị đã đọc lúc mount và
 * hoàn nguyên thứ người dùng vừa đổi — âm thầm, vì response 200 và mọi thứ trông
 * như đã lưu. `exclude_unset=True` của backend làm việc bỏ trường này an toàn:
 * trường vắng mặt KHÔNG được cập nhật (DEFAULT chỉ áp lúc INSERT).
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, boot, datApiDoc, moSuaDuAn } from './re-fixture'

function batPatch() {
  const than: Record<string, unknown>[] = []
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      const b = (await request.json()) as Record<string, unknown>
      than.push(b)
      return HttpResponse.json({ ...DU_AN, ...b })
    }),
  )
  return than
}

/** Bất đồng bộ: dự án nạp qua query, chip chưa có ở lượt render đầu. */
function chip() {
  return screen.findByRole('button', { name: /Trạng thái dự án/ })
}

describe('chip hiện ở mọi tab', () => {
  it.each(['tong-quan', 'quy-can', 'media', 'tai-lieu'])('tab %s vẫn thấy chip', async (tab) => {
    datApiDoc()
    boot(`/pform?code=VHOP2&tab=${tab}`)
    expect(await screen.findByRole('button', { name: /Trạng thái dự án/ })).toBeInTheDocument()
  })

  it('nhãn chip đọc từ bản ghi, không phải hằng', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'archived' } })
    boot('/pform?code=VHOP2')
    expect(await chip()).toHaveTextContent('Lưu trữ')
  })

  it('aria-label nói rõ đây là trạng thái của DỰ ÁN', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=quy-can')
    // Mỗi căn có `status` riêng — chip treo cố định trên hàng tab rất dễ bị đọc
    // thành trạng thái của căn đang xem, nên nó phải tự nói ra.
    expect(await screen.findByRole('button', { name: /Trạng thái dự án/ })).toBeInTheDocument()
  })
})

describe('đổi trạng thái từ chip', () => {
  it('PATCH CHỈ có status, không kéo theo trường nào khác', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'draft' } })
    const than = batPatch()
    boot('/pform?code=VHOP2')

    await userEvent.click(await chip())
    await userEvent.click(screen.getByRole('menuitem', { name: 'Đã phát hành' }))

    await waitFor(() => expect(than).toEqual([{ status: 'published' }]))
  })

  it('có đủ ba lựa chọn', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await chip())
    const menu = screen.getByRole('menu')
    for (const nhan of ['Bản nháp', 'Đã phát hành', 'Lưu trữ']) {
      expect(within(menu).getByRole('menuitem', { name: nhan })).toBeInTheDocument()
    }
  })

  it('422 của backend hiện thành câu đọc được, kể cả khi FE tưởng là đủ', async () => {
    // Dự án FE thấy là ĐỦ (`DU_AN`) nhưng backend vẫn từ chối — hai danh sách
    // `BAT_BUOC` là hai bản chép tay, không cổng CI nào so. Đây là đường duy nhất
    // còn dẫn tới 422 sau khi chip chặn trước mọi ca FE biết được.
    datApiDoc({ project: { ...DU_AN, status: 'draft' } })
    server.use(
      http.patch('/api/v1/projects/:code', () =>
        HttpResponse.json(
          {
            error: {
              code: 'INCOMPLETE_DATA',
              message: 'Thiếu dữ liệu bắt buộc để publish: overview',
            },
          },
          { status: 422 },
        ),
      ),
    )
    boot('/pform?code=VHOP2')

    await userEvent.click(await chip())
    await userEvent.click(screen.getByRole('menuitem', { name: 'Đã phát hành' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/Tổng quan|overview/)
  })
})

describe('một người sở hữu status', () => {
  it('tab Tổng quan THÔI gửi status — nếu không nó hoàn nguyên thứ chip vừa đổi', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'draft' } })
    const than = batPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.clear(screen.getByRole('textbox', { name: /Đơn vị phát triển/ }))
    await userEvent.type(screen.getByRole('textbox', { name: /Đơn vị phát triển/ }), 'X')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(Object.keys(than[0]!)).not.toContain('status')
  })

  it('không còn ô chọn Trạng thái trong form Tổng quan', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    expect(screen.queryByRole('combobox', { name: /^Trạng thái$/ })).not.toBeInTheDocument()
  })

  it('POST tạo mới cũng KHÔNG gửi status — DEFAULT của cột lo phần đó', async () => {
    // Bản trước gửi `status: 'draft'` tường minh vì form tạo mới là chính tab
    // Tổng quan. Đường tạo giờ là `CongDatTen` (một ô tên), và cột `status` có
    // DEFAULT `'draft'` áp lúc INSERT — gửi lại nó không thêm gì.
    const than: Record<string, unknown>[] = []
    datApiDoc()
    server.use(
      http.post('/api/v1/projects', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(DU_AN, { status: 201 })
      }),
    )
    boot('/pform')

    await userEvent.type(await screen.findByRole('textbox', { name: /Tên thương mại/ }), 'X')
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ name: 'X' })
  })
})
