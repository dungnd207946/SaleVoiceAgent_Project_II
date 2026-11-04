/**
 * `status` của DỰ ÁN là thứ người dùng chọn, không suy từ completeness
 * (2026-08-11), và từ 2026-08-21 nó nằm ở CHIP trên hàng tab chứ không trong form.
 *
 * HAI THỨ PHẢI GIỮ:
 *   · Chỉ MỘT chỗ được gửi `status` — nay là chip. Tab Vị trí (và tab Tổng quan)
 *     gửi kèm là ghi đè lựa chọn của người dùng mỗi lần họ sửa một ô khác.
 *   · Chọn «Đã phát hành» khi còn thiếu trường thì GỬI và để backend trả lời.
 *     FE THÔI CHẶN TRƯỚC (người dùng chốt 2026-08-21): phép chặn cũ tồn tại để
 *     thay một 422 mờ mịt bằng một câu nói rõ trường nào thiếu — rồi chính câu đó
 *     bị bỏ khỏi menu, nên còn lại một mục xám không giải thích gì và không đường
 *     nào đi tiếp. 422 của backend qua `cauLoi()` nói đúng thứ đã mất.
 *
 * `status` của CĂN vẫn suy ra — xem `realestate-trang-thai-suy-ra.test.tsx`.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

/** Dự án NHÁP thiếu `region`, giữ mã VHOP2 để handler của `datApiDoc` nhận. */
const NHAP_THIEU = { ...DU_AN, region: '', status: 'draft' }

function batThanPatch() {
  const than: Record<string, unknown>[] = []
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(DU_AN)
    }),
  )
  return than
}

/**
 * ⚠️ Ô CHỌN Trạng thái ĐÃ RỜI tab Tổng quan (spec 2026-08-21 issue 5) — nó là
 * chip ở cột phải hàng tab, chi tiết ở `realestate-chip-trang-thai.test.tsx`.
 *
 * Nhóm dưới đây giữ lại ĐÚNG bất biến mà file chip không phủ: FE KHÔNG chặn
 * trước — mọi lựa chọn trong menu đều gửi được, và trường còn thiếu là câu trả
 * lời của backend chứ không phải một mục bị làm mờ.
 */
describe('không chặn phát hành ở FE — backend là người trả lời', () => {
  it('thiếu trường thì mục Đã phát hành VẪN bấm được', async () => {
    // Mã VHOP2, KHÔNG phải mã của `DU_AN_THIEU`: handler của `datApiDoc` trả 404
    // cho mọi mã khác VHOP2, nên một dự án thiếu trường phải mượn mã đó.
    datApiDoc({ project: NHAP_THIEU })
    boot('/pform?code=VHOP2')

    await userEvent.click(await screen.findByRole('button', { name: /Trạng thái dự án/ }))

    expect(screen.getByRole('menuitem', { name: 'Đã phát hành' })).toBeEnabled()
    expect(screen.queryByText(/Chưa phát hành được/)).not.toBeInTheDocument()
  })

  it('bấm là GỬI — người dùng không bị khoá ngoài một mục xám không lời giải', async () => {
    datApiDoc({ project: NHAP_THIEU })
    const than = batThanPatch()
    boot('/pform?code=VHOP2')

    await userEvent.click(await screen.findByRole('button', { name: /Trạng thái dự án/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Đã phát hành' }))

    await waitFor(() => expect(than).toEqual([{ status: 'published' }]))
  })

  it('đủ trường thì cũng vậy — không còn câu chặn', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    await userEvent.click(await screen.findByRole('button', { name: /Trạng thái dự án/ }))

    expect(screen.getByRole('menuitem', { name: 'Đã phát hành' })).toBeEnabled()
  })

  it('thiếu trường vẫn chuyển về Bản nháp được — chặn chỉ áp cho phát hành', async () => {
    datApiDoc({ project: { ...NHAP_THIEU, status: 'archived' } })
    const than = batThanPatch()
    boot('/pform?code=VHOP2')

    await userEvent.click(await screen.findByRole('button', { name: /Trạng thái dự án/ }))
    await userEvent.click(screen.getByRole('menuitem', { name: 'Bản nháp' }))

    await waitFor(() => expect(than).toEqual([{ status: 'draft' }]))
  })
})

describe('tab Vị trí thôi gửi status', () => {
  it('PATCH chỉ có region và address', async () => {
    datApiDoc({ media: trang([]) })
    const than = batThanPatch()
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()

    const o = screen.getByRole('textbox', { name: /Địa chỉ/ })
    await userEvent.clear(o)
    await userEvent.type(o, 'Văn Giang')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    // Tự lưu từng ô ⇒ đúng MỘT trường; `region` không ai sửa nên không đi kèm.
    expect(than[0]).toEqual({ address: 'Văn Giang' })
  })
})
