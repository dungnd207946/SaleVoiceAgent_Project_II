/**
 * Một dấu duy nhất cho «bắt buộc»: dấu `*` đỏ.
 *
 * Nhãn phụ «cần để phát hành» đã bỏ (người dùng chốt 2026-08-21), nên năm trường
 * của cổng phát hành không còn dấu gì — và người nhập không biết ô nào đáng điền.
 * Chúng nhận `*` như mọi ô bắt buộc khác: hai bậc dấu là hai bậc phải đi giải
 * thích, mà bậc thứ hai vừa bị bỏ chính vì lý do đó.
 *
 * LUẬT: `*` = ô nằm trong `BAT_BUOC` (cổng phát hành) HOẶC là khoá phải có lúc tạo.
 *
 * ⚠️ MỘT NGOẠI LỆ (2026-08-25): hai ô diện tích nằm trong `BAT_BUOC.unit` nhưng KHÔNG
 * mang `*`, vì cổng chỉ đòi MỘT TRONG HAI. Đánh sao cả hai đọc thành «phải điền cả
 * hai»; đánh sao một ô là nói dối về ô kia. Xem `DIEN_TICH_CAN` ở `completeness.ts`.
 */
import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

/** Nhãn của mỗi ô = `<span>` đầu tiên trong `<label>`; `textContent` của cả label gồm cả `<option>`. */
const coSao = () =>
  Array.from(document.querySelectorAll('label > span:first-child'))
    .map((s) => s.textContent ?? '')
    .filter((t) => t.includes('*'))
    .map((t) => t.replace('*', '').trim())

describe('tab Tổng quan', () => {
  it('chế độ xem không có dấu `*` — dấu thuộc về ô nhập', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await screen.findByRole('group', { name: 'Thông tin chung' })
    expect(screen.queryAllByTitle('Bắt buộc')).toHaveLength(0)
  })

  it('ba trường cổng phát hành thuộc tab này đều mang `*`', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    await screen.findByRole('textbox', { name: /Chủ đầu tư/ })

    // «Quy mô sản phẩm» đã RỜI cổng phát hành (người dùng chốt 2026-08-25): nó là
    // câu mô tả tự do («3 toà · 1.240 căn hộ»), không phải dữ liệu agent tra cứu.
    expect(coSao()).toEqual(['Tên thương mại', 'Chủ đầu tư', 'Giới thiệu dự án'])
  })

  it('dấu `*` là màu đỏ và có tooltip, không chỉ là một ký tự', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    await screen.findByRole('textbox', { name: /Chủ đầu tư/ })

    const sao = screen.getAllByTitle('Bắt buộc')[0]!
    expect(sao.className).toContain('text-badge-alert-fg')
  })
})

describe('tab Vị trí', () => {
  it('Khu vực mang `*`, Địa chỉ thì không', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()
    await screen.findByRole('textbox', { name: /Khu vực/ })

    expect(coSao()).toEqual(['Khu vực'])
  })
})

describe('form căn', () => {
  it('hai khoá lúc tạo + hai trường cổng phát hành mang `*`; diện tích thì KHÔNG', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2')
    await screen.findByRole('option', { name: /Zurich/ })

    expect(coSao()).toEqual(['Phân khu', 'Mã căn', 'Trạng thái bán', 'Giá bán'])
  })
})

describe('không còn nhãn phụ nào', () => {
  it('«cần để phát hành» đã biến mất khỏi mọi form', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    await screen.findByRole('textbox', { name: /Chủ đầu tư/ })
    expect(screen.queryByText('cần để phát hành')).not.toBeInTheDocument()
  })
})

describe('chip thôi kể tên trường còn thiếu', () => {
  it('menu trạng thái thôi liệt kê trường còn thiếu', async () => {
    const { DU_AN } = await import('./re-fixture')
    datApiDoc({ project: { ...DU_AN, status: 'draft', region: '' } })
    boot('/pform?code=VHOP2')

    await userEvent.click(await screen.findByRole('button', { name: /Trạng thái dự án/ }))

    expect(screen.queryByText(/Chưa phát hành được/)).not.toBeInTheDocument()
    // Và thôi CHẶN luôn: một mục xám không kể lý do là một ngõ cụt — 422 của
    // backend mới là chỗ nói trường nào còn thiếu (2026-08-21).
    expect(screen.getByRole('menuitem', { name: 'Đã phát hành' })).toBeEnabled()
  })
})
