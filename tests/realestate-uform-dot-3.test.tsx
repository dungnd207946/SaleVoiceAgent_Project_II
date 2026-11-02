/**
 * `/uform` đợt 3 — spec 2026-08-21 §5.3. Còn lại đúng phần BỐ CỤC; phần dấu bắt
 * buộc đã chuyển sang `realestate-dau-bat-buoc.test.tsx` (xem ghi chú dưới).
 */
import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { boot, datApiDoc } from './re-fixture'


/**
 * ⚠️ NHÓM «hai ô bắt buộc» ĐÃ CHUYỂN sang `realestate-dau-bat-buoc.test.tsx`.
 *
 * Bản 2026-08-21 đầu cắt còn 2 dấu `*` và đưa hai ô cổng phát hành sang nhãn chữ
 * «cần để phát hành». Người dùng bỏ nhãn chữ đó, rồi yêu cầu «field nào require
 * thì phải có dấu * đỏ» — nên cổng phát hành quay về dùng CHÍNH dấu `*`, và form
 * căn có 5 dấu: 2 khoá lúc tạo + 3 trường cổng.
 */
describe('bố cục ba tầng', () => {
  it('khối breadcrumb + hàng tab dán trên đỉnh', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2')
    const dinh = await screen.findByTestId('uform-dinh')
    expect(dinh.className).toMatch(/\bsticky\b/)
    expect(dinh.className).toMatch(/\btop-0\b/)
  })

  it('hàng tab nằm TRONG khối dán — cuộn xuống vẫn nhảy tab được', async () => {
    datApiDoc()
    boot('/uform?code=VHOP2')
    const dinh = await screen.findByTestId('uform-dinh')
    expect(within(dinh).getByRole('tab', { name: 'Quỹ căn' })).toBeInTheDocument()
  })
})