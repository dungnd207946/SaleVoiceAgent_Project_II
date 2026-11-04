/**
 * Dự án chưa có toà nào thì không hiện cột hay ô Toà (người dùng chốt 2026-10-09).
 *
 * Căn cứ là dữ liệu chứ không phải loại hình dự án: một dự án ghi loại hình biệt thự vẫn có thể
 * có toà condotel. Căn chỉ gắn được với toà có thật của dự án (khoá ngoại phía backend), nên
 * «dự án chưa có toà» đồng nghĩa «không căn nào có toà».
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { CAN, boot, datApiDoc, giaTriXem, moSuaCan, trang } from './re-fixture'

const KHONG_TOA = { items: [], total: 0 }

/** Mỗi hàng dữ liệu phải có đúng bằng số ô tiêu đề — thiếu một ô là cả hàng lệch cột. */
function khongLechCot() {
  const soCot = screen.getAllByRole('columnheader').length
  for (const hang of screen.getAllByRole('row').slice(1)) {
    expect(hang.querySelectorAll('td')).toHaveLength(soCot)
  }
}

describe('tab Quỹ căn', () => {
  it('dự án chưa có toà: không có cột Toà, hàng không lệch cột', async () => {
    datApiDoc({ buildings: KHONG_TOA, units: trang([{ ...CAN, block: null }]) })
    boot('/pform?code=VHOP2&tab=quy-can')
    await screen.findByText(CAN.unitCode)

    expect(screen.queryByRole('columnheader', { name: 'Toà' })).not.toBeInTheDocument()
    khongLechCot()
  })

  it('dự án có toà: giữ cột Toà, hàng không lệch cột', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=quy-can')
    await screen.findByText(CAN.unitCode)

    expect(screen.getByRole('columnheader', { name: 'Toà' })).toBeInTheDocument()
    khongLechCot()
  })
})

describe('tab Phân khu', () => {
  it('dự án chưa có toà: không có cột Toà, hàng không lệch cột', async () => {
    datApiDoc({ buildings: KHONG_TOA })
    boot('/pform?code=VHOP2&tab=phan-khu')
    await screen.findByText('Zurich')

    expect(screen.queryByRole('columnheader', { name: 'Toà' })).not.toBeInTheDocument()
    khongLechCot()
  })

  it('dự án có toà: cột Toà liệt kê toà của phân khu', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=phan-khu')
    await screen.findByText('Zurich')

    expect(screen.getByRole('columnheader', { name: 'Toà' })).toBeInTheDocument()
    expect(screen.getByText('Toà A')).toBeInTheDocument()
    khongLechCot()
  })
})

describe('màn một căn', () => {
  it('căn cao tầng trong dự án chưa có toà: không có ô Toà, cả khi xem lẫn khi sửa', async () => {
    datApiDoc({ buildings: KHONG_TOA })
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({ ...CAN, block: null }),
      ),
    )
    boot(`/uform?code=VHOP2&unit=${CAN.id}`)
    await waitFor(() => expect(giaTriXem('Mã căn')).toHaveTextContent(CAN.unitCode))

    expect(screen.queryByText('Toà / block')).not.toBeInTheDocument()
    await moSuaCan()
    expect(screen.queryByRole('combobox', { name: /Toà/ })).not.toBeInTheDocument()
  })

  it('dự án có toà: ô Toà hiện tên toà của căn', async () => {
    datApiDoc()
    boot(`/uform?code=VHOP2&unit=${CAN.id}`)

    await waitFor(() => expect(giaTriXem('Toà / block')).toHaveTextContent('Toà A'))
  })
})
