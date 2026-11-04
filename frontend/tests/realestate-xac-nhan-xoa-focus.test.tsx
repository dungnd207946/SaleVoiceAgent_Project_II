/**
 * Hộp xác nhận xoá INLINE (`role="alertdialog"`, không phải overlay): tên khả truy cập,
 * và đường đi của focus theo APG — vào nút ít phá huỷ nhất, về nút xoá khi Huỷ, về chỗ ổn
 * định khi hàng đã biến mất. Dùng tab Tài liệu; Phân khu / Căn dùng chung `useXacNhanXoa`.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { boot, datApiDoc, moSuaDuAn } from './re-fixture'

async function moXacNhan() {
  datApiDoc()
  boot('/pform?code=VHOP2')
  await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
  await screen.findByText('Chính sách bán hàng Q3')
  await moSuaDuAn()
  const nutXoa = screen.getByRole('button', { name: 'Xoá' })
  await userEvent.click(nutXoa)
  return { nutXoa, hop: await screen.findByRole('alertdialog') }
}

describe('hộp xác nhận xoá inline', () => {
  it('có tên + mô tả, focus vào Huỷ', async () => {
    const { hop } = await moXacNhan()

    expect(hop).toHaveAccessibleName(/Xoá Chính sách bán hàng Q3\?/)
    expect(hop).toHaveAccessibleDescription(/không hoàn tác được/)
    expect(within(hop).getByRole('button', { name: 'Huỷ' })).toHaveFocus()
  })

  it('Huỷ trả focus về nút xoá đã mở hộp', async () => {
    const { nutXoa, hop } = await moXacNhan()

    await userEvent.click(within(hop).getByRole('button', { name: 'Huỷ' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(nutXoa).toHaveFocus()
  })

  it('xoá xong, focus về nút «Thêm tài liệu» chứ không rơi về <body>', async () => {
    const { hop } = await moXacNhan()

    await userEvent.click(within(hop).getByRole('button', { name: 'Xoá' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Thêm tài liệu' })).toHaveFocus()
  })
})
