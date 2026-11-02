/**
 * Nút Sửa/Xong ở hàng tab của hồ sơ dự án và dòng giờ lưu cạnh nó.
 *
 * Mockup đã duyệt 2026-10-08: nút ghi «Xong» ở chế độ sửa và luôn bấm được — mỗi ô đã tự lưu
 * khi rời ô nên Xong chỉ đóng chế độ sửa. Kết quả lưu hiện thành «Đã lưu lúc HH:MM» cạnh nút.
 * (Thay quyết định 2026-08-21: nút «Lưu» mờ tới khi có ô đổi.)
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { CAN, DU_AN, boot, datApiDoc, trang } from './re-fixture'

function dat() {
  datApiDoc({ media: trang([]), zones: trang([]), documents: trang([]) })
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      const b = (await request.json()) as Record<string, unknown>
      return HttpResponse.json({ ...DU_AN, ...b })
    }),
  )
}

const nut = (ten: string) => screen.findByRole('button', { name: ten })

describe('nút Sửa/Xong', () => {
  it('chưa bấm Sửa thì nút là «Sửa» và bấm được', async () => {
    dat()
    boot('/pform?code=VHOP2')
    expect(await nut('Sửa')).toBeEnabled()
  })

  it('bấm Sửa thì nút thành «Xong» và bấm được ngay — không có gì phải chờ lưu', async () => {
    dat()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nut('Sửa'))

    expect(await nut('Xong')).toBeEnabled()
    expect(screen.queryByRole('button', { name: 'Lưu' })).not.toBeInTheDocument()
  })

  it('bấm Xong thì về bản xem và nút về «Sửa»', async () => {
    dat()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nut('Sửa'))
    await userEvent.click(await nut('Xong'))

    expect(await nut('Sửa')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Chủ đầu tư/ })).not.toBeInTheDocument()
  })
})

describe('giờ lưu ở đầu trang', () => {
  it('chưa lưu lượt nào thì không có dòng giờ lưu', async () => {
    dat()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nut('Sửa'))

    expect(screen.queryByText(/Đã lưu lúc/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Tự lưu khi rời ô/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Chỉ đọc/)).not.toBeInTheDocument()
  })

  it('lưu một ô thì báo «Đã lưu lúc HH:MM» — đó là kết quả, không phải cơ chế', async () => {
    dat()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nut('Sửa'))
    await userEvent.type(screen.getByRole('textbox', { name: /Đơn vị phát triển/ }), 'X')
    await userEvent.tab()

    expect(await screen.findByText(/^Đã lưu lúc \d{2}:\d{2}$/)).toBeInTheDocument()
  })

  it('giờ lưu là của cả hồ sơ: lưu ở Tổng quan rồi sang Vị trí vẫn thấy', async () => {
    dat()
    boot('/pform?code=VHOP2')
    await userEvent.click(await nut('Sửa'))
    await userEvent.type(screen.getByRole('textbox', { name: /Đơn vị phát triển/ }), 'X')
    await userEvent.tab()
    await screen.findByText(/Đã lưu lúc/)

    await userEvent.click(screen.getByRole('tab', { name: 'Vị trí' }))
    await screen.findByRole('textbox', { name: /Khu vực/ })
    expect(screen.getByText(/Đã lưu lúc/)).toBeInTheDocument()
  })
})

describe('/uform theo cùng luật', () => {
  it('căn đã có: Sửa → Xong, lưu một ô thì báo giờ lưu', async () => {
    datApiDoc({ media: trang([]) })
    server.use(http.patch('/api/v1/projects/:code/units/:id', () => HttpResponse.json(CAN)))
    boot(`/uform?code=VHOP2&unit=${CAN.id}`)
    await userEvent.click(await nut('Sửa'))
    expect(await nut('Xong')).toBeEnabled()

    await userEvent.type(screen.getByRole('spinbutton', { name: /Số phòng ngủ/ }), '1')
    await userEvent.tab()
    await waitFor(() => expect(screen.getByText(/Đã lưu lúc \d{2}:\d{2}/)).toBeInTheDocument())
  })
})
