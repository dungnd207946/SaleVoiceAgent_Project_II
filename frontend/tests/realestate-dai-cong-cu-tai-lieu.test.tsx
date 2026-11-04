/**
 * Dải công cụ của tab Tài liệu là MỘT hàng: chip lọc bên trái, nút Thêm bên phải.
 *
 * Trước đợt này nút đứng riêng một hàng phía trên hàng chip, và hàng đó trống
 * hoác — hai dải công cụ cho một bảng (người dùng chốt 2026-08-21).
 *
 * Từ 2026-10-08 nút Thêm chỉ có khi đang sửa.
 */
import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { TAI_LIEU, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

describe('dải công cụ của tab Tài liệu là MỘT hàng', () => {
  it('nút Thêm tài liệu đứng cùng hàng với chip lọc', async () => {
    datApiDoc({ documents: trang([TAI_LIEU]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await screen.findByText(TAI_LIEU.title)
    await moSuaDuAn()

    const chip = screen.getByRole('group', { name: 'Lọc theo loại' })
    const hang = chip.parentElement!
    expect(within(hang).getByRole('button', { name: 'Thêm tài liệu' })).toBeInTheDocument()
  })

  it('đang tải thì vẫn có nút Thêm, chỉ chưa có chip', async () => {
    datApiDoc({ documents: trang([TAI_LIEU]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await moSuaDuAn()

    expect(await screen.findByRole('button', { name: 'Thêm tài liệu' })).toBeInTheDocument()
  })

  it('mở form thêm tài liệu thì dải công cụ nhường chỗ cho form', async () => {
    datApiDoc({ documents: trang([TAI_LIEU]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm tài liệu' }))

    expect(await screen.findByRole('textbox', { name: /Tiêu đề/ })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Lọc theo loại' })).not.toBeInTheDocument()
  })
})
