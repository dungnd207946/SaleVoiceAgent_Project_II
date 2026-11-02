/**
 * Cổng VĂN BẢN cho các lớp lỗi responsive mà jsdom không vẽ nên không bài render
 * nào bắt được (cùng lối `o-chon.test.ts`).
 *
 * 1. iOS Safari tự zoom khi focus một ô có chữ < 16px — màn nhảy phóng to và
 *    không tự thu lại. Mọi hằng ô nhập dùng chung phải có `max-md:text-base`.
 * 2. Chiều cao khung màn trừ 72px (topbar desktop) — ở mobile topbar là 56px.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { createElement } from 'react'
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { CAO_O, KHUNG_MAN, NutIcon, O_LOC, ThanhCong } from '../src/components/ui/Bang'
import { O_CHUNG } from '../src/components/ui/Truong'

describe('primitive responsive', () => {
  it.each([
    ['O_CHUNG', O_CHUNG],
    ['O_LOC', O_LOC],
  ])('%s: chữ 16px ở mobile (chống iOS zoom)', (_, lop) => {
    expect(lop).toContain('max-md:text-base')
  })

  it('CAO_O: 40px ở mobile, 36px giữ nguyên ở desktop', () => {
    expect(CAO_O.split(' ')).toEqual(['h-9', 'max-md:h-10'])
  })

  it('KHUNG_MAN: bản mobile trừ đúng topbar 56px', () => {
    expect(KHUNG_MAN).toContain('h-[calc(100dvh-72px)]')
    expect(KHUNG_MAN).toContain('max-md:h-[calc(100dvh-56px)]')
    expect(KHUNG_MAN).toContain('max-md:px-4')
  })

  // `NUT_ICON` (hằng class của `NutIcon`) không export — kiểm qua render thay
  // vì đọc thẳng chuỗi. Spec §5.4: icon vuông 28px desktop phải ≥40px mobile.
  it('NutIcon: size-7 desktop giữ nguyên, max-md:size-10 ở mobile', () => {
    const { getByRole } = render(
      createElement(NutIcon, { icon: 'copy', nhan: 'Sao chép', onClick: () => {} }),
    )
    const nut = getByRole('button', { name: 'Sao chép' })
    expect(nut.className).toContain('size-7')
    expect(nut.className).toContain('max-md:size-10')
  })

  // Dải công cụ (ô lọc trái · nút phải) không xuống dòng thì trên màn hẹp nhóm ô
  // lọc — `min-w-0 flex-1` — bị bóp nhỏ hơn nội dung của chính nó, ô nhập tràn ra
  // và nằm ĐÈ lên nút ở cùng hàng. Đo được ở `/projects` và `/users` (360–430px).
  it('ThanhCong: xuống dòng ở mobile, desktop giữ một hàng', () => {
    const { container } = render(createElement(ThanhCong, null, 'x'))
    const dai = container.firstElementChild as HTMLElement
    expect(dai.className).toContain('max-md:flex-wrap')
    expect(dai.className.split(' ')).not.toContain('flex-wrap')
  })

  // Hàng ô ⑤ Kiến thức (`/dashboard`) là lưới 7 cột cần ~548px, mà ô chỉ rộng
  // thế từ 1240px; ô cha `overflow-hidden` CẮT phần thừa thay vì tràn, nên đo
  // tràn ngang không thấy. Hàng phải rẽ theo bề rộng của chính nó (container
  // query) — và template phải là class: `style` inline thắng mọi biến thể.
  it('TheKienThuc: hàng co theo container, template không nằm trong style', () => {
    const nguon = readFileSync(
      join(import.meta.dirname, '../src/features/ops/components/TheKienThuc.tsx'),
      'utf8',
    )
    expect(nguon).not.toContain('gridTemplateColumns')
    expect(nguon).toContain('@container')
    expect(nguon).toContain('md:@max-[560px]:grid-cols-')
    expect(nguon).toContain('max-md:grid-cols-')
  })
})
