/**
 * Khung dán cố định + chỉ báo nạp kiến thức.
 *
 * Yêu cầu của người dùng (spec 2026-08-21 issue 7): «các nút này nên cố định, chỉ cuộn thông tin
 * thôi». Từ 2026-10-08 nút Sửa/Xong nằm ở khối đỉnh, cùng hàng tab; không còn hàng dán đáy.
 *
 * Chỉ báo nạp kiến thức (`KbBadge`) đứng ở khối đỉnh và CHỈ hiện khi đang nạp hoặc lỗi — lúc
 * bình thường im lặng. Số mục đã tới agent nằm ở thẻ «Kiến thức cho agent» của tab Tổng quan.
 *
 * ⚠️ THƯỚC «Độ hoàn thiện n/12» ĐÃ BỎ (người dùng chốt 2026-08-25): thước nói «bạn còn thiếu ô
 * nào», chỉ báo nạp nói «bao nhiêu mục đã tới agent». Bài dưới canh thước không quay lại.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { DU_AN, KB_DA_NAP, boot, datApiDoc, trang } from './re-fixture'

/** Trường mềm để trống ⇒ thước tụt nhưng cổng vẫn cho phát hành. */
const THIEU_MEM = {
  ...DU_AN,
  amenities: '',
  floorAreaM2: null,
  buildDensityPct: null,
  ownershipForm: '',
  handoverStandard: [],
}

const DANG_NAP = { ...KB_DA_NAP, indexing: true, done: 3, total: 12 }

describe('đầu trang dán, chỉ vùng tab cuộn', () => {
  it('khối breadcrumb + hàng tab dán trên đỉnh', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    const dinh = await screen.findByTestId('pform-dinh')
    expect(dinh.className).toMatch(/\bsticky\b/)
    expect(dinh.className).toMatch(/\btop-0\b/)
  })

  it('nút Sửa ở khối đỉnh; không còn hàng dán đáy', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    const dinh = await screen.findByTestId('pform-dinh')
    expect(dinh).toContainElement(await screen.findByRole('button', { name: 'Sửa' }))
    expect(screen.queryByTestId('pform-day')).not.toBeInTheDocument()
  })

  it('chip trạng thái nằm TRONG khối dán — cuộn xuống vẫn thấy', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=quy-can')
    const dinh = await screen.findByTestId('pform-dinh')
    expect(dinh).toContainElement(screen.getByRole('button', { name: /Trạng thái dự án/ }))
  })
})

describe('chỉ báo nạp kiến thức', () => {
  it('nạp đủ ⇒ đầu trang im lặng; số mục nằm ở thẻ Kiến thức cho agent', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await waitFor(() =>
      expect(screen.getByRole('group', { name: 'Kiến thức cho agent' })).toHaveTextContent(
        /12\/12\s*mục/,
      ),
    )
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('đang nạp ⇒ thanh ở khối đỉnh, phần trăm theo done/total', async () => {
    datApiDoc({ kbStatus: [DANG_NAP] })
    boot('/pform?code=VHOP2')
    const thanh = await screen.findByRole('progressbar')
    expect(thanh).toHaveAttribute('aria-valuenow', '25')
    expect(screen.getByTestId('pform-dinh')).toContainElement(thanh)
  })

  it('dự án RỖNG ⇒ không thanh nào — 0/0 không phải một tiến độ', async () => {
    datApiDoc({ kbStatus: [{ ...KB_DA_NAP, total: 0, done: 0 }] })
    boot('/pform?code=VHOP2')
    const the = await screen.findByRole('group', { name: 'Kiến thức cho agent' })
    await waitFor(() => expect(the).toHaveTextContent('Chưa có gì để nạp'))
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })

  it('thước Độ hoàn thiện KHÔNG còn ở đâu trên form', async () => {
    datApiDoc({ project: THIEU_MEM })
    boot('/pform?code=VHOP2')
    await screen.findByRole('group', { name: 'Thông tin chung' })
    expect(screen.queryByText(/Độ hoàn thiện/)).not.toBeInTheDocument()
    expect(screen.queryByTestId('pform-thuoc-do')).not.toBeInTheDocument()
  })

  it.each(['vi-tri', 'media'])('đang nạp thì thấy ở tab %s, kể cả tab chỉ có ảnh', async (tab) => {
    datApiDoc({ project: THIEU_MEM, media: trang([]), kbStatus: [DANG_NAP] })
    boot(`/pform?code=VHOP2&tab=${tab}`)
    expect(await screen.findByRole('progressbar')).toBeInTheDocument()
  })

  it('lỗi nạp ⇒ đầu trang báo lỗi kèm nút Thử lại', async () => {
    datApiDoc({ kbStatus: [{ ...KB_DA_NAP, hasError: true }], media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')
    const dinh = await screen.findByTestId('pform-dinh')
    await waitFor(() => expect(dinh).toHaveTextContent(/Lỗi nạp kiến thức cho agent/))
    expect(within(dinh).getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
  })

  it('KHÔNG hiện lúc tạo mới — chưa có dự án nào để nạp', async () => {
    datApiDoc()
    boot('/pform')
    await screen.findByRole('textbox', { name: /Tên thương mại/ })
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
  })
})

describe('tiến độ nạp KHÔNG được lẫn với cổng chặn', () => {
  it('thiếu trường mềm: vẫn phát hành được, không câu chặn nào', async () => {
    datApiDoc({ project: { ...THIEU_MEM, status: 'draft' } })
    boot('/pform?code=VHOP2')
    await screen.findByRole('group', { name: 'Kiến thức cho agent' })
    expect(screen.queryByText(/Chưa phát hành được/)).not.toBeInTheDocument()
  })
})
