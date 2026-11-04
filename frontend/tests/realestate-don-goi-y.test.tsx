/**
 * Dọn câu chú thích dưới ô — spec 2026-08-21 §3.4b (issue 8).
 *
 * Luật: cắt câu chỉ nói lại nhãn, hoặc chỉ tả cơ chế nội bộ. Giữ câu cảnh báo
 * một cái sai đắt, hoặc nói một hệ quả người dùng không tự thấy được.
 *
 * File này canh CẢ HAI CHIỀU. Chỉ canh chiều cắt thì lần dọn sau sẽ cắt tiếp
 * theo cảm giác «trông gọn hơn» và mang theo mấy câu đang giữ người dùng khỏi
 * gõ 5.6 vào ô nhận đồng.
 */
import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CAN, DU_AN, TAI_LIEU, boot, datApiDoc, moSuaCan, moSuaDuAn, trang } from './re-fixture'

describe('cắt: câu chỉ nói lại nhãn hoặc tả cơ chế nội bộ', () => {
  it('ô Ảnh cover thôi kể nó lưu vào danh mục nào', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    expect(screen.queryByText(/Lưu vào danh mục Tổng quan/)).not.toBeInTheDocument()
  })

  // Ô nhập của tab này chỉ render sau khi bấm Sửa — không bấm thì bài xanh mà
  // chẳng kiểm gì, vì câu cần kiểm chưa bao giờ được vẽ.
  it('ô Link 360 thôi liệt kê dịch vụ — placeholder đã nêu', async () => {
    datApiDoc({ project: { ...DU_AN, link360: '' } })
    boot('/pform?code=VHOP2&tab=anh-360')
    await moSuaDuAn()
    await screen.findByRole('textbox', { name: /Link tham quan 360/ })
    expect(screen.queryByText(/Kuula, Matterport/)).not.toBeInTheDocument()
  })

  it('ô Loại tài liệu thôi tả cơ chế lọc của chính app', async () => {
    datApiDoc({ documents: trang([TAI_LIEU]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: /Thêm tài liệu/ }))
    expect(screen.queryByText(/nằm ở nhóm nào khi lọc/)).not.toBeInTheDocument()
  })

  // ⚠️ Phần «GIỮ câu chỉ đường sang tab Media» đã BỎ (người dùng chốt
  // 2026-08-21): đợt dọn thứ hai cắt sạch chú thích dưới ô ở form dự án, kể cả
  // câu này. Bài giữ lại chiều cắt của cả hai nửa.
  it('ô Tiện ích không còn chú thích nào', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    expect(screen.queryByText(/Chỉ mô tả bằng chữ/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Ảnh tiện ích đặt ở tab Media/)).not.toBeInTheDocument()
  })
})

describe('bỏ nốt: ba câu nhắc lại chính nhãn ô', () => {
  /**
   * Ba câu này TỪNG được giữ lại có lý lẽ («chặn một cái sai đắt», «cặp ô phân
   * biệt»), người dùng bỏ hẳn 2026-08-25. Bài đảo chiều chứ không xoá: một ô tiền
   * KHÔNG có câu nhắc đơn vị là quyết định, và quyết định thì phải có cổng canh —
   * nếu không ai đó sẽ «khôi phục» nó như sửa một thiếu sót.
   */
  it('ô tiền thôi nhắc đơn vị — ở cả form dự án và form căn', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    expect(screen.queryByText(/Nguyên đồng, không phải tỷ/)).not.toBeInTheDocument()
  })

  it('cặp ô tầng thôi giải thích, nhãn tự nói', async () => {
    datApiDoc()
    boot(`/uform?code=VHOP2&unit=${CAN.id}`)
    await moSuaCan()
    expect(screen.queryByText(/Căn nằm ở tầng số mấy/)).not.toBeInTheDocument()
    expect(screen.queryByText(/khác ô trên/)).not.toBeInTheDocument()
    // Nhãn đổi cùng đợt: «Căn ở tầng» → «Căn nằm ở tầng», tức câu giải thích cũ
    // được nâng lên làm chính nhãn thay vì đứng dưới ô lặp lại nó.
    expect(screen.getByLabelText(/Căn nằm ở tầng/)).toBeInTheDocument()
  })

  it('hai câu `phu` của nhóm ô căn cũng bỏ', async () => {
    datApiDoc()
    boot(`/uform?code=VHOP2&unit=${CAN.id}`)
    await moSuaCan()
    expect(screen.queryByText(/hướng đông nam/)).not.toBeInTheDocument()
    expect(screen.queryByText(/được phép báo giá căn này/)).not.toBeInTheDocument()
  })

  it('ô Tệp đính kèm vẫn nói ảnh và PDF scan cần Duyệt', async () => {
    datApiDoc({ documents: trang([TAI_LIEU]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: /Thêm tài liệu/ }))
    expect(await screen.findByText(/cần bấm Duyệt trước khi agent dùng/)).toBeInTheDocument()
  })
})

/**
 * Câu dùng chung của hai ô `overview` (dự án và phân khu) — «Agent dùng đoạn này
 * để trả lời khách…» — đã BỎ HẲN cùng hằng `HINT_OVERVIEW` và tệp `hints.ts`
 * (người dùng chốt 2026-08-21).
 *
 * Bài này canh việc nó KHÔNG quay lại ở một trong hai ô: một câu dùng chung được
 * dựng lại ở một chỗ thôi là đúng cái bất đối xứng mà hằng kia sinh ra để chống.
 */
describe('ô Tổng quan không còn chú thích dùng chung', () => {
  const CAU = /Agent dùng đoạn này để trả lời khách/

  it('ô Tổng quan của dự án không còn câu đó', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    expect(screen.queryByText(CAU)).not.toBeInTheDocument()
  })

  it('ô Tổng quan của phân khu cũng không', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=phan-khu')
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: /Thêm phân khu/ }))
    await screen.findByRole('textbox', { name: /Tên phân khu/ })
    expect(screen.queryByText(CAU)).not.toBeInTheDocument()
  })
})
