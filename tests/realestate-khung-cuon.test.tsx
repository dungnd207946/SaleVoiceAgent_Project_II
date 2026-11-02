/**
 * Khung của `/pform` và `/uform`: chặn chiều cao ở GỐC, chỉ vùng giữa cuộn.
 *
 * Trước đợt này cả trang cuộn, nên hàng nút đáy và chân bảng nằm ở một độ cao
 * khác nhau trên mỗi tab và NHẢY mỗi lần đổi tab — người dùng chỉ ra đúng chỗ đó.
 * Cùng khuôn `DuAnList` và `TongQuanScreen` đã dùng (`h-[calc(100dvh-72px)]`).
 *
 * Đây là bài về LỚP CSS, không về hành vi — chấp nhận vì bất biến này chỉ sống
 * trong lớp: bỏ `overflow-y-auto` khỏi vùng giữa là cả trang cuộn lại, và không
 * assertion nào về DOM bắt được.
 */
import { describe, expect, it } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { CAN, PHAN_KHU, TAI_LIEU, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

/** Khối cuộn = cha của nội dung tab, ngay sau khối đỉnh. */
function vungCuon(dinh: HTMLElement) {
  return dinh.parentElement!.querySelector('.overflow-y-auto')
}

/** Từ 2026-10-08 hàng nút đáy chỉ còn ở form TẠO; form tạo phân khu là một trong số đó. */
async function moFormTaoPhanKhu() {
  datApiDoc({ zones: trang([]), media: trang([]) })
  boot('/pform?code=VHOP2&tab=phan-khu')
  await moSuaDuAn()
  await userEvent.click(await screen.findByRole('button', { name: 'Thêm phân khu' }))
  return screen.findByTestId('pform-day')
}

describe('chỉ vùng giữa cuộn', () => {
  it('/pform: gốc chặn chiều cao, vùng giữa mang overflow-y-auto', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2')

    const dinh = await screen.findByTestId('pform-dinh')
    expect(dinh.parentElement!.className).toMatch(/h-\[calc\(100dvh/)
    expect(vungCuon(dinh)).not.toBeNull()
  })

  it('/uform: cùng khuôn', async () => {
    datApiDoc({ media: trang([]) })
    boot(`/uform?code=VHOP2&unit=${CAN.id}`)

    const dinh = await screen.findByTestId('uform-dinh')
    expect(dinh.parentElement!.className).toMatch(/h-\[calc\(100dvh/)
    expect(vungCuon(dinh)).not.toBeNull()
  })

  it('hàng nút đáy nằm TRONG vùng cuộn — nó dán vào đáy vùng đó, không đáy trang', async () => {
    const day = await moFormTaoPhanKhu()
    expect(vungCuon(screen.getByTestId('pform-dinh'))).toContainElement(day)
  })

  it('/uform: hàng nút NGOÀI vùng cuộn', async () => {
    // Ở `/pform` hàng nút là thứ CUỐI của tab nên dán bên trong là đủ. Ở `/uform`
    // nó submit form bằng thuộc tính `form=` và nằm ngoài vùng cuộn, để không trôi
    // lên đè nội dung nằm sau form.
    datApiDoc({ media: trang([]) })
    boot('/uform?code=VHOP2')

    const dinh = await screen.findByTestId('uform-dinh')
    expect(vungCuon(dinh)).not.toContainElement(screen.getByTestId('uform-day'))
  })

  it('hàng nút không mang lề âm — nó sinh thanh cuộn NGANG trong vùng cuộn', async () => {
    // `overflow-y: auto` ép trục x thành `auto` theo spec, nên `-mx-4` của hàng nút
    // làm cả vùng cuộn có thêm một thanh cuộn ngang ở mọi tab.
    expect((await moFormTaoPhanKhu()).className).not.toMatch(/-mx-/)
  })
})

describe('form và danh sách khai chiều cao KHÁC nhau', () => {
  /** Lớp của nội dung tab = con đầu của vùng cuộn. */
  async function lopTab(tab: string) {
    datApiDoc({ documents: trang([TAI_LIEU]), zones: trang([PHAN_KHU]), units: trang([CAN]), media: trang([]) })
    boot(`/pform?code=VHOP2&tab=${tab}`)
    const dinh = await screen.findByTestId('pform-dinh')
    // Chờ dự án về: trước đó nội dung tab là cổng đặt tên, không phải tab thật.
    await screen.findByRole('button', { name: /Trạng thái dự án/ })
    return (vungCuon(dinh)!.firstElementChild as HTMLElement).className
  }

  it.each(['tong-quan', 'vi-tri', 'anh-360'])('tab form %s: min-h-full', async (tab) => {
    // Form dài phải ĐẨY vùng cuộn dài ra; `h-full` sẽ bóp nhóm ô cuối.
    expect(await lopTab(tab)).toMatch(/\bmin-h-full\b/)
  })

  it('tab phân khu: min-h-full — danh sách hiện đủ mọi phân khu, không phân trang', async () => {
    expect(await lopTab('phan-khu')).toMatch(/\bmin-h-full\b/)
  })

  it.each(['quy-can', 'tai-lieu'])('tab danh sách %s: h-full', async (tab) => {
    // Thẻ bảng dùng `flex-1` + `min-h-0` nên nó chỉ ăn hết chỗ khi CHA có chiều
    // cao XÁC ĐỊNH. Với `min-h-full` thì thẻ lấy chiều cao của mọi hàng và bảng
    // thôi cuộn bên trong thẻ — đo được: vùng cuộn 689px, thẻ 1213px.
    const lop = await lopTab(tab)
    expect(lop).toMatch(/\bh-full\b/)
    expect(lop).not.toMatch(/\bmin-h-full\b/)
  })
})

describe('bảng của tab cao bằng vùng cuộn', () => {
  it.each([
    ['tai-lieu', 'Tài liệu'],
    ['quy-can', 'Quỹ căn'],
  ])('tab %s: thẻ bảng lấy hết chiều cao còn lại', async (tab) => {
    // `flex-1` chứ không một con số: thẻ ăn phần còn lại nên chân bảng («Hiện
    // 0–0 / 0») ở đáy kể cả khi danh sách rỗng — đúng thứ người dùng chỉ ra.
    datApiDoc({ documents: trang([TAI_LIEU]), zones: trang([PHAN_KHU]), units: trang([CAN]) })
    boot(`/pform?code=VHOP2&tab=${tab}`)

    const bang = await screen.findByRole('table')
    const the = bang.closest('.flex-1')
    expect(the).not.toBeNull()
  })
})
