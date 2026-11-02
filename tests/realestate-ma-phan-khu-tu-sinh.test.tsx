/**
 * Ô «Mã phân khu» rời form — backend suy mã từ tên (spec 2026-08-21 §4.3).
 *
 * Cùng lý lẽ với mã dự án: `zone_code` là khoá BẤT BIẾN (`ZonePatch` không có ô
 * đó) nên bắt người nhập đặt nó ở ô đầu tiên là bắt họ ra một quyết định vĩnh
 * viễn trước khi biết mình đang làm gì.
 *
 * Mã KHÔNG biến mất khỏi giao diện — nó còn ở dòng phụ dưới tên trong màn chi tiết; thứ
 * biến mất là cái Ô NHẬP.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { PHAN_KHU, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'
import { server } from '../vitest.setup'

function batThanPost() {
  const than: Record<string, unknown>[] = []
  server.use(
    http.post('/api/v1/projects/:code/zones', async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(PHAN_KHU, { status: 201 })
    }),
  )
  return than
}

async function moFormMoi() {
  await userEvent.click(await screen.findByRole('tab', { name: 'Phân khu' }))
  await moSuaDuAn()
  await userEvent.click(await screen.findByRole('button', { name: 'Thêm phân khu' }))
}

describe('form phân khu không còn ô mã', () => {
  it('tạo mới: không có ô «Mã phân khu»', async () => {
    datApiDoc({ zones: trang([]) })
    boot('/pform?code=VHOP2')
    await moFormMoi()

    expect(await screen.findByRole('textbox', { name: /Tên phân khu/ })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Mã phân khu/ })).not.toBeInTheDocument()
  })

  it('POST không gửi `zoneCode` — backend sinh từ `name`', async () => {
    datApiDoc({ zones: trang([]) })
    const than = batThanPost()
    boot('/pform?code=VHOP2')
    await moFormMoi()

    await userEvent.type(screen.getByRole('textbox', { name: /Tên phân khu/ }), 'Sao Biển')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu phân khu' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(Object.keys(than[0]!)).not.toContain('zoneCode')
    expect(than[0]!.name).toBe('Sao Biển')
  })

  it('sửa: cũng không còn ô mã bị khoá — mã hiện chỉ-đọc', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Phân khu' }))
    await userEvent.click(await screen.findByText('Zurich'))
    await moSuaDuAn()

    expect(screen.getByRole('textbox', { name: /Tên phân khu/ })).toBeEnabled()
    expect(screen.queryByRole('textbox', { name: /Mã phân khu/ })).not.toBeInTheDocument()
  })

  it('form sửa vẫn hiện mã — mã tự sinh thì càng cần chỗ tra', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Phân khu' }))
    await userEvent.click(await screen.findByText('Zurich'))

    expect(await screen.findByText('ZURICH')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Mã phân khu/ })).not.toBeInTheDocument()
  })
})

describe('tên phân khu thay mã làm ô bắt buộc', () => {
  it('«Tên phân khu» được đánh dấu bắt buộc', async () => {
    datApiDoc({ zones: trang([]) })
    boot('/pform?code=VHOP2')
    await moFormMoi()

    expect(await screen.findByRole('textbox', { name: 'Tên phân khu' })).toBeRequired()
  })

  it('để trống tên thì không gửi request nào', async () => {
    datApiDoc({ zones: trang([]) })
    const than = batThanPost()
    boot('/pform?code=VHOP2')
    await moFormMoi()

    await userEvent.click(screen.getByRole('button', { name: 'Lưu phân khu' }))
    expect(than).toHaveLength(0)
  })
})
