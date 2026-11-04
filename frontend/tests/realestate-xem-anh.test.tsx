/**
 * Xem ảnh trên portal — lightbox, hai bố cục, nhúng 360, nhãn khu vực.
 *
 * Trước bản vá này portal GIỮ đủ dữ liệu media nhưng không cho xem: ảnh render
 * 112×80px không bấm được, link 360 chỉ là một thẻ `<a>`, và `region` hiện giá
 * trị máy `mien_nam` ra màn hình.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { KHU_VUC, MEDIA_CATEGORY, nhanCua } from '../src/features/realestate/enums'
import { DU_AN, MEDIA, boot, datApiDoc, giaTriXem, moSuaDuAn, trang } from './re-fixture'

const ANH = (id: number, category: string, caption: string) => ({
  ...MEDIA,
  id,
  category,
  caption,
  mediaUrl: `https://x/${id}.webp`,
})

describe('nhãn khu vực', () => {
  it('dịch ba giá trị máy sang tiếng Việt', () => {
    expect(nhanCua(KHU_VUC, 'mien_nam')).toBe('Miền Nam')
    expect(nhanCua(KHU_VUC, 'mien_bac')).toBe('Miền Bắc')
    expect(nhanCua(KHU_VUC, 'mien_trung')).toBe('Miền Trung')
  })

  it('giá trị tự do đi qua nguyên văn — hai kiểu dữ liệu sống chung', () => {
    expect(nhanCua(KHU_VUC, 'Quận 7, TP.HCM')).toBe('Quận 7, TP.HCM')
  })

  it('bản xem của tab Vị trí hiện nhãn tiếng Việt, không hiện giá trị máy', async () => {
    datApiDoc({ project: { ...DU_AN, region: 'mien_nam' }, media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')

    await waitFor(() => expect(giaTriXem('Khu vực')).toHaveTextContent('Miền Nam'))
    expect(giaTriXem('Khu vực')).not.toHaveTextContent('mien_nam')
  })

  it('tab Vị trí dịch giá trị máy ra tiếng Việt cạnh ô nhập', async () => {
    // Ô nhập buộc hiện đúng thứ sẽ được lưu (`mien_nam`) vì nó tự lưu khi rời ô —
    // bản chỉ-đọc cũ dịch được vì nó không phải ô nhập. Nên phần dịch chuyển
    // xuống một dòng cạnh ô: không có nó, người dùng chỉ thấy giá trị máy.
    datApiDoc({ project: { ...DU_AN, region: 'mien_nam' }, media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()

    const o = await screen.findByRole('textbox', { name: /Khu vực/ })
    expect(o).toHaveValue('mien_nam')
    expect(o).toHaveAccessibleDescription(/Miền Nam/)
  })

  it('chữ tự do thì không thêm dòng dịch nào — không có gì để dịch', async () => {
    datApiDoc({ project: { ...DU_AN, region: 'Quận 7, TP.HCM' }, media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()

    const o = await screen.findByRole('textbox', { name: /Khu vực/ })
    expect(o).toHaveValue('Quận 7, TP.HCM')
    expect(o).not.toHaveAccessibleDescription(/Khách nghe là/)
  })
})

describe('danh mục media thứ 8', () => {
  it('csbh có nhãn tiếng Việt', () => {
    expect(nhanCua(MEDIA_CATEGORY, 'csbh')).toBe('Chính sách bán hàng')
  })

  it('tab Media có folder Chính sách bán hàng', async () => {
    datApiDoc({ media: trang([ANH(91, 'csbh', 'Bảng giá Q3')]) })
    boot('/pform?code=VHOP2&tab=media')

    expect(await screen.findByText('Chính sách bán hàng')).toBeInTheDocument()
  })
})

describe('lightbox', () => {
  it('bấm ảnh mở lightbox, Esc đóng', async () => {
    datApiDoc({ media: trang([ANH(91, 'mat_bang', 'Mặt bằng tầng 5')]) })
    boot('/pform?code=VHOP2&tab=mat-bang')

    await userEvent.click(await screen.findByRole('button', { name: 'Phóng to: Mặt bằng tầng 5' }))
    const hop = await screen.findByRole('dialog')
    expect(within(hop).getByText('Mặt bằng tầng 5')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('đi được sang ảnh kế trong cùng bộ', async () => {
    datApiDoc({
      media: trang([ANH(91, 'mat_bang', 'Tầng 5'), ANH(92, 'mat_bang', 'Tầng 12')]),
    })
    boot('/pform?code=VHOP2&tab=mat-bang')

    await userEvent.click(await screen.findByRole('button', { name: 'Phóng to: Tầng 5' }))
    const hop = await screen.findByRole('dialog')
    await userEvent.click(within(hop).getByRole('button', { name: 'Ảnh kế' }))
    expect(within(hop).getByText('Tầng 12')).toBeInTheDocument()
  })
})

describe('bố cục gallery của tab Mặt bằng', () => {
  it('một ảnh lớn object-contain, phần còn lại là thumbnail', async () => {
    datApiDoc({
      media: trang([ANH(91, 'mat_bang', 'Tầng 5'), ANH(92, 'mat_bang', 'Tầng 12')]),
    })
    boot('/pform?code=VHOP2&tab=mat-bang')

    const lon = await screen.findByTestId('anh-lon')
    expect(lon).toHaveClass('object-contain')
    expect(screen.getAllByTestId('anh-thumb')).toHaveLength(2)
  })
})

describe('nhúng 360', () => {
  it('link https được nhúng iframe, và vẫn có link mở tab mới', async () => {
    datApiDoc({ project: { ...DU_AN, link360: 'https://kuula.co/share/x' } })
    boot('/pform?code=VHOP2&tab=anh-360')

    const khung = await screen.findByTitle('Tham quan 360')
    expect(khung).toHaveAttribute('src', 'https://kuula.co/share/x')
    expect(screen.getByRole('link', { name: /Mở ở tab mới/ })).toBeInTheDocument()
  })

  it('link http KHÔNG nhúng — trình duyệt chặn mixed content im lặng', async () => {
    datApiDoc({ project: { ...DU_AN, link360: 'http://kuula.co/share/x' } })
    boot('/pform?code=VHOP2&tab=anh-360')

    expect(await screen.findByRole('link', { name: /Mở ở tab mới/ })).toBeInTheDocument()
    expect(screen.queryByTitle('Tham quan 360')).not.toBeInTheDocument()
  })
})
