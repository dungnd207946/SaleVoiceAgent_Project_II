/**
 * Hai primitive của `components/ui/Truong.tsx` sau spec 2026-08-21 (issue 3 + 6).
 *
 * Ví dụ trong ô và dữ liệu thật phải trông KHÁC nhau: cùng cỡ cùng kiểu thì người
 * điền không phân biệt được thứ mình đã gõ với thứ app gợi ý.
 *
 * `batBuoc` (dấu *) và `neededToPublish` (nhãn chữ) là HAI thứ, không phải hai
 * cách vẽ một thứ: một ô chặn lúc LƯU khác một ô chỉ chặn lúc PHÁT HÀNH, và
 * gộp chúng vào một dấu đỏ là nói với người dùng rằng họ không lưu được.
 */
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { OChu } from '../src/components/ui/Truong'

describe('ví dụ trong ô khác dữ liệu thật (issue 3)', () => {
  it('placeholder nghiêng và nhỏ hơn cỡ chữ dữ liệu', () => {
    render(
      <OChu ten="investor" nhan="Chủ đầu tư" giaTri="" doi={() => {}} goiYTrongO="Tên pháp nhân" />,
    )
    const o = screen.getByRole('textbox', { name: 'Chủ đầu tư' })
    expect(o).toHaveClass('placeholder:italic')
    // Ví dụ một bậc thang dưới dữ liệu: `text-than` 13,5px trong ô `text-noi` 14,5px.
    expect(o).toHaveClass('placeholder:text-than')
    expect(o).toHaveClass('text-noi')
  })

  it('sắc RIÊNG, nhạt hơn `muted-3`', () => {
    // Đổi 2026-08-25: ví dụ nay chỉ hiện khi ĐANG SỬA và ô còn rỗng, nên nó là gợi
    // ý tạm thời chứ không phải nội dung — đọc nhầm nó thành dữ liệu đã gõ hại hơn
    // là đọc nó khó. Token riêng để đổi một chỗ, không rải hex khắp component.
    // Từ 2026-10-05 sắc đó là MỘT rule `::placeholder` ở `@layer base` cho cả portal
    // (trước chỉ ô này dùng token, hơn 20 ô khác ra 4 sắc). Canh cả hai vế: rule trỏ
    // vào token, và ô không mang `placeholder:text-*` nào đè lên nó.
    const css = readFileSync('src/styles/theme.css', 'utf8')
    expect(css).toMatch(/::placeholder\s*\{\s*color:\s*var\(--color-placeholder\)/)
    render(<OChu ten="investor" nhan="Chủ đầu tư" giaTri="" doi={() => {}} goiYTrongO="VD" />)
    const o = screen.getByRole('textbox', { name: 'Chủ đầu tư' })
    // (cỡ thì được: `placeholder:text-than` là bậc thang cỡ, không phải màu)
    const CO = /^placeholder:text-(\[|nhan$|phu$|than$|noi$)/
    expect([...o.classList].filter((c) => /^placeholder:text-/.test(c) && !CO.test(c))).toEqual([])
  })

  it('CHẾ ĐỘ XEM không render ví dụ nào — và chữ là màu chữ thường', () => {
    // Người dùng bắt được trên màn thật: ô rỗng ở chế độ xem hiện một câu mờ, đọc
    // ra như dữ liệu đã có. Và chữ ở chế độ xem phải ĐEN — nó là dữ liệu thật, chỉ
    // là chưa mở để sửa.
    // Từ 2026-10-08 chế độ xem là chữ, không còn ô bị khoá; ô rỗng hiện «—».
    render(<OChu ten="investor" nhan="Chủ đầu tư" giaTri="" doi={() => {}} goiYTrongO="VD" khoa />)
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
    expect(screen.queryByText('VD')).not.toBeInTheDocument()
    expect(screen.getByRole('definition')).toHaveTextContent('—')
  })

  it('chế độ xem có dữ liệu: chữ màu chữ thường', () => {
    render(<OChu ten="investor" nhan="Chủ đầu tư" giaTri="Vinhomes" doi={() => {}} khoa />)
    const giaTri = screen.getByRole('definition')
    expect(giaTri).toHaveTextContent('Vinhomes')
    expect(giaTri).toHaveClass('text-fg')
  })
})

/**
 * Nhãn «cần để phát hành» ĐÃ BỎ (người dùng chốt 2026-08-21). Hai bài dưới neo
 * lại phần còn sống: `batBuoc` vẫn vẽ dấu `*`, và ô trơn không mang dấu nào —
 * nếu ai đó dựng lại một nhãn thứ hai thì bài thứ hai đỏ.
 */
describe('dấu bắt buộc là dấu DUY NHẤT trên nhãn ô', () => {
  it('batBuoc vẽ dấu *', () => {
    render(<OChu ten="name" nhan="Tên thương mại" giaTri="" doi={() => {}} batBuoc />)
    expect(screen.getByTitle('Bắt buộc')).toBeInTheDocument()
  })

  it('ô trơn: nhãn đúng bằng tên ô, không thêm chữ nào', () => {
    render(<OChu ten="developer" nhan="Đơn vị phát triển" giaTri="" doi={() => {}} />)
    expect(screen.queryByTitle('Bắt buộc')).not.toBeInTheDocument()
    const nhan = document.querySelector('label > span:first-child')
    expect(nhan?.textContent).toBe('Đơn vị phát triển')
  })
})

/** Audit 05/10: tên ô từng đọc ra «Tên thương mại *» kèm cả câu gợi ý — dấu sao và
 *  gợi ý nằm TRONG `<label>` nên nhập vào tên truy cập. */
describe('tên truy cập của ô', () => {
  it('ô bắt buộc: tên KHÔNG có dấu sao, nghĩa «bắt buộc» đi qua aria-required', () => {
    render(<OChu ten="name" nhan="Tên thương mại" giaTri="" doi={() => {}} batBuoc />)
    const o = screen.getByRole('textbox', { name: 'Tên thương mại' })
    expect(o).toHaveAttribute('aria-required', 'true')
  })

  it('gợi ý KHÔNG nằm trong tên — nó là mô tả (aria-describedby)', () => {
    render(<OChu ten="slug" nhan="Mã" giaTri="" doi={() => {}} goiY="Chữ thường, không dấu" />)
    const o = screen.getByRole('textbox', { name: 'Mã' })
    expect(o).toHaveAccessibleDescription('Chữ thường, không dấu')
  })
})
