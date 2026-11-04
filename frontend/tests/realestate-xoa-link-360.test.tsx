/**
 * Tab Ảnh 360 phải có đường bỏ link — spec 2026-08-21 issue 4.
 *
 * Trước đợt này, cách duy nhất để bỏ một link 360 là bấm Sửa, xoá trắng ô, rồi
 * Lưu. Không có nút nào nói rằng việc đó làm được, nên với người dùng thì nó
 * không tồn tại.
 *
 * Từ 2026-10-08 nút Xoá link chỉ có khi đang sửa, cạnh ô link.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, boot, datApiDoc, moSuaDuAn } from './re-fixture'

function batPatch() {
  const than: unknown[] = []
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      than.push(await request.json())
      return HttpResponse.json(DU_AN)
    }),
  )
  return than
}

describe('bỏ link tham quan 360', () => {
  it('dự án có link thì bấm Sửa sẽ thấy nút Xoá link', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=anh-360')
    await screen.findByRole('link', { name: 'Mở ở tab mới' })
    expect(screen.queryByRole('button', { name: 'Xoá link' })).not.toBeInTheDocument()
    await moSuaDuAn()
    expect(await screen.findByRole('button', { name: 'Xoá link' })).toBeInTheDocument()
  })

  it('chưa có link thì không hiện nút — không có gì để xoá', async () => {
    datApiDoc({ project: { ...DU_AN, link360: '' } })
    boot('/pform?code=VHOP2&tab=anh-360')
    await screen.findByText(/Chưa có link tham quan 360/)
    await moSuaDuAn()
    expect(screen.queryByRole('button', { name: 'Xoá link' })).not.toBeInTheDocument()
  })

  it('xoá gửi PATCH link360 rỗng, không kéo theo trường nào khác', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=anh-360')
    await moSuaDuAn()

    await userEvent.click(await screen.findByRole('button', { name: 'Xoá link' }))
    await userEvent.click(screen.getByRole('button', { name: 'Xoá hẳn' }))

    await waitFor(() => expect(than).toEqual([{ link360: '' }]))
  })

  it('bỏ xác nhận thì không gửi gì', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=anh-360')
    await moSuaDuAn()

    await userEvent.click(await screen.findByRole('button', { name: 'Xoá link' }))
    await userEvent.click(screen.getByRole('button', { name: 'Thôi' }))

    expect(than).toEqual([])
  })
})
