/**
 * Hàng nút dán đáy ở BA form còn lại — spec 2026-08-21 issue 7, đợt 3.
 *
 * Đợt 2 dán được đáy cho ba tab của HÀNG DỰ ÁN (Tổng quan · Vị trí · Ảnh 360).
 * Phân khu · Tài liệu · Quỹ căn còn để nút chạy theo cuối trang, và chúng là ba
 * form DÀI NHẤT — form căn có 19 ô. Người nhập cuộn xuống cuối để bấm Lưu rồi
 * cuộn lên để sửa tiếp, mỗi lượt hai bước phí.
 *
 * Từ 2026-10-08 chỉ form TẠO còn hàng dán đáy. Bản xem của một hàng đã có dùng
 * nút Sửa ở khối đỉnh, cũng dán.
 */
import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

const DAN = (el: HTMLElement) => {
  expect(el.className).toMatch(/\bsticky\b/)
  expect(el.className).toMatch(/\bbottom-0\b/)
}

async function suaODinh(testId: string) {
  const dinh = screen.getByTestId(testId)
  expect(dinh.className).toMatch(/\bsticky\b/)
  expect(dinh).toContainElement(await screen.findByRole('button', { name: 'Sửa' }))
}

describe('tab Phân khu', () => {
  it('form tạo dán đáy', async () => {
    datApiDoc({ zones: trang([]) })
    boot('/pform?code=VHOP2&tab=phan-khu')
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm phân khu' }))
    DAN(await screen.findByTestId('pform-day'))
  })

  it('bản xem: nút Sửa ở khối đỉnh, không có hàng dán đáy', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=phan-khu')
    await userEvent.click(await screen.findByText('Zurich'))
    await screen.findByText('Thông tin phân khu')
    await suaODinh('pform-dinh')
    expect(screen.queryByTestId('pform-day')).not.toBeInTheDocument()
  })
})

describe('tab Tài liệu', () => {
  it('form tạo dán đáy', async () => {
    datApiDoc({ documents: trang([]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm tài liệu' }))
    DAN(await screen.findByTestId('pform-day'))
  })

  it('bản xem: nút Sửa ở khối đỉnh, không có hàng dán đáy', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await userEvent.click(await screen.findByText('Chính sách bán hàng Q3'))
    await screen.findByText('Nội dung tài liệu')
    await suaODinh('pform-dinh')
    expect(screen.queryByTestId('pform-day')).not.toBeInTheDocument()
  })
})

describe('form căn (/uform)', () => {
  it('form tạo dán đáy', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2')
    await screen.findByRole('option', { name: /Zurich/ })
    DAN(screen.getByTestId('uform-day'))
  })

  it('một căn đã có: nút Sửa ở khối đỉnh, không có hàng dán đáy', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2&unit=100')
    await screen.findByText('Thông tin căn')
    await suaODinh('uform-dinh')
    expect(screen.queryByTestId('uform-day')).not.toBeInTheDocument()
  })
})
