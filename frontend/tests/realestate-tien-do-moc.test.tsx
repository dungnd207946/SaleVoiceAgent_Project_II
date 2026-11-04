/**
 * Tab Tiến độ dạng TIMELINE THEO MỐC (2026-08-25, người dùng chốt theo giao
 * diện bảng hàng AINA): media `tien_do` nhóm theo «Tiến độ dd/mm/yyyy — <mốc>»
 * trong caption (khuôn do adapter AINA phát — xem docstring `moc.ts`), mốc mới
 * nhất trước; ảnh không mang tiền tố nhóm theo ngày tạo, KHÔNG bị văng khỏi
 * timeline. Lưới phẳng cũ mất thông tin mốc: 30 ảnh của 3 tháng đọc thành một
 * đống không phân biệt được đợt nào mới.
 */
import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { nhanTrongMoc, nhomTheoMoc } from '../src/features/realestate/moc'
import type { Media } from '../src/features/realestate/api'
import { MEDIA, boot, datApiDoc, trang } from './re-fixture'

// `as Media`: fixture MEDIA là object thường (`status: string`), các test khác
// spread nó vào JSON fake nên không sao — ở đây gọi thẳng hàm nhận `Media`.
const anh = (id: number, caption: string, them: Partial<Media> = {}): Media => ({
  ...(MEDIA as Media),
  id,
  category: 'tien_do',
  caption,
  ...them,
})

describe('nhomTheoMoc — nhóm media tien_do theo mốc trong caption', () => {
  it('cùng «ngày — mốc» về một nhóm, nhóm xếp mới nhất trước', () => {
    const ds = nhomTheoMoc([
      anh(1, 'Tiến độ 01/04/2026 — 04/2026 — Móng toà A'),
      anh(2, 'Tiến độ 01/05/2026 — 05/2026 — Flycam biển'),
      anh(3, 'Tiến độ 01/05/2026 — 05/2026'),
    ])
    expect(ds.map((g) => g.ngay)).toEqual(['01/05/2026', '01/04/2026'])
    expect(ds[0]!.tieuDe).toBe('05/2026')
    expect(ds[0]!.anh.map((m) => m.id)).toEqual([2, 3])
  })

  it('caption không mang tiền tố ⇒ nhóm theo NGÀY TẠO, vẫn nằm trong timeline', () => {
    const ds = nhomTheoMoc([
      anh(1, 'Móng tháng 7', { createdAt: '2026-07-15T03:00:00Z' }),
      anh(2, 'Tiến độ 01/05/2026 — 05/2026'),
    ])
    expect(ds.map((g) => g.ngay)).toEqual(['15/07/2026', '01/05/2026'])
    expect(ds[0]!.tieuDe).toBe('')
  })

  it('nhanTrongMoc: chỉ phần RIÊNG của ảnh — caption đầy đủ lặp dưới từng ảnh là nhiễu', () => {
    expect(nhanTrongMoc(anh(1, 'Tiến độ 01/05/2026 — 05/2026 — Flycam biển'))).toBe('Flycam biển')
    expect(nhanTrongMoc(anh(2, 'Tiến độ 01/05/2026 — 05/2026 — Flycam — góc biển'))).toBe(
      'Flycam — góc biển',
    )
    expect(nhanTrongMoc(anh(3, 'Tiến độ 01/05/2026 — 05/2026'))).toBe('')
    expect(nhanTrongMoc(anh(4, 'Móng tháng 7'))).toBe('Móng tháng 7')
  })
})

describe('tab Tiến độ — timeline theo mốc', () => {
  it('nhóm theo mốc, mới nhất trước; nhãn ảnh là phần riêng, không lặp caption mốc', async () => {
    datApiDoc({
      media: trang([
        anh(97, 'Tiến độ 01/04/2026 — 04/2026 — Móng toà A'),
        anh(98, 'Tiến độ 01/05/2026 — 05/2026 — Flycam biển'),
        anh(99, 'Tiến độ 01/05/2026 — 05/2026'),
      ]),
    })
    boot('/pform?code=VHOP2&tab=tien-do')

    const vung = (await screen.findByRole('heading', { name: 'Tiến độ', level: 3 })).closest(
      'section',
    )!
    // Thứ tự nhóm đọc từ DOM — mốc 05/2026 phải đứng TRƯỚC 04/2026.
    const ngay = within(vung)
      .getAllByTestId('moc-ngay')
      .map((el) => el.textContent)
    expect(ngay).toEqual(['01/05/2026', '01/04/2026'])
    expect(within(vung).getByText('05/2026')).toBeInTheDocument()
    // Nhãn dưới ảnh: phần riêng, KHÔNG phải nguyên caption dài.
    expect(within(vung).getByText('Flycam biển')).toBeInTheDocument()
    expect(
      within(vung).queryByText('Tiến độ 01/05/2026 — 05/2026 — Flycam biển', {
        selector: 'p',
      }),
    ).not.toBeInTheDocument()
  })

  it('ảnh upload tay (không tiền tố) vào nhóm theo ngày tạo; sửa/xoá và thêm ảnh vẫn còn', async () => {
    datApiDoc({
      media: trang([
        anh(97, 'Móng tháng 7', { createdAt: '2026-07-15T03:00:00Z' }),
        anh(98, 'Tiến độ 01/05/2026 — 05/2026 — Flycam biển'),
      ]),
    })
    boot('/pform?code=VHOP2&tab=tien-do')

    const vung = (await screen.findByRole('heading', { name: 'Tiến độ', level: 3 })).closest(
      'section',
    )!
    expect(
      within(vung)
        .getAllByTestId('moc-ngay')
        .map((el) => el.textContent),
    ).toEqual(['15/07/2026', '01/05/2026'])
    expect(within(vung).getByText('Móng tháng 7')).toBeInTheDocument()
    // Timeline không được nuốt thao tác của VungMedia: nút sửa/xoá từng ảnh
    // (aria mang caption ĐẦY ĐỦ) + nút thêm ảnh của cả vùng.
    expect(
      within(vung).getByRole('button', {
        name: 'Xoá ảnh — Tiến độ 01/05/2026 — 05/2026 — Flycam biển',
      }),
    ).toBeInTheDocument()
    expect(within(vung).getByRole('button', { name: '＋ Thêm ảnh / video' })).toBeInTheDocument()
  })

  it('video tiến độ nằm trong nhóm mốc của nó, đếm chung ở header vùng', async () => {
    datApiDoc({
      media: trang([
        anh(97, 'Tiến độ 01/05/2026 — 05/2026 — Flycam biển'),
        anh(98, 'Tiến độ 01/05/2026 — 05/2026 — Bay drone', { contentType: 'video' }),
      ]),
    })
    boot('/pform?code=VHOP2&tab=tien-do')

    const vung = (await screen.findByRole('heading', { name: 'Tiến độ', level: 3 })).closest(
      'section',
    )!
    expect(within(vung).getByText('2 mục', { selector: 'span' })).toBeInTheDocument()
    // Video render trong ĐÚNG nhóm (chỉ có một nhóm ở fixture này).
    expect(within(vung).getAllByTestId('moc-ngay')).toHaveLength(1)
    expect(within(vung).getByText(/Video/, { selector: 'a' })).toBeInTheDocument()
  })
})
