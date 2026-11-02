/**
 * Bốn tab chuyên đề của màn dự án — Vị trí · Ảnh 360 · Mặt bằng · Tiến độ.
 *
 * Mỗi tab ghi vào cùng row `projects`, nên thứ phải canh là: nó PATCH ĐÚNG phần
 * của mình. Gửi kèm trường của tab khác là ghi đè thứ người dùng không mở ra xem.
 *
 * Từ 2026-08-21 các tab TỰ LƯU TỪNG Ô, nên «phần của mình» hẹp hơn nữa: đúng một
 * trường mỗi lượt PATCH.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import {
  DU_AN,
  DU_AN_THIEU,
  MEDIA,
  boot,
  datApiDoc,
  giaTriXem,
  loi422,
  moSuaDuAn,
  trang,
} from './re-fixture'

/** Thu mọi thân PATCH `/projects/:code` để assert nó chỉ chứa phần của tab. */
function batPatch() {
  const than: Record<string, unknown>[] = []
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(DU_AN)
    }),
  )
  return than
}

describe('tab Vị trí', () => {
  it('hiện khu vực, địa chỉ dạng chữ và thẻ bản đồ vị trí', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')

    await waitFor(() => expect(giaTriXem('Khu vực')).toHaveTextContent('Hà Nội'))
    expect(giaTriXem('Địa chỉ')).toHaveTextContent('Gia Lâm')
    expect(screen.queryByRole('textbox', { name: /Khu vực/ })).not.toBeInTheDocument()
    expect(await screen.findByRole('group', { name: 'Bản đồ vị trí' })).toBeInTheDocument()
  })

  it('PATCH gửi ĐÚNG ô vừa rời — không kèm ô bên cạnh, không kèm tab khác', async () => {
    datApiDoc({ media: trang([]) })
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()

    const o = screen.getByRole('textbox', { name: /Khu vực/ })
    await userEvent.clear(o)
    await userEvent.type(o, 'Hưng Yên')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    // KHÔNG `address` (ô bên cạnh, không ai sửa) và KHÔNG `status` (chip ở hàng
    // tab sở hữu nó) — gửi kèm là ghi đè thứ người dùng không mở ra xem.
    expect(than[0]).toEqual({ region: 'Hưng Yên' })
  })

  it('tab Tổng quan không còn hai ô đã dời sang đây', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    await screen.findByRole('group', { name: 'Thông tin chung' })
    expect(screen.queryByText('Khu vực')).not.toBeInTheDocument()
    expect(screen.queryByText('Địa chỉ')).not.toBeInTheDocument()
  })

  it('đổi sang dự án khác thì ô nhập mang giá trị của dự án MỚI, không của dự án vừa xem', async () => {
    const DU_AN_KHAC = { ...DU_AN_THIEU, region: 'Hưng Yên', address: 'Văn Giang' }
    datApiDoc({ media: trang([]) })
    server.use(
      http.get('/api/v1/projects/:code', ({ params }) =>
        HttpResponse.json(params.code === DU_AN.projectCode ? DU_AN : DU_AN_KHAC),
      ),
    )
    const moTab = (code: string) => ({ to: '/pform', search: { code, tab: 'vi-tri' } }) as const

    // Ghé DU_AN_KHAC MỘT LẦN trước để nó vào cache react-query. Lần ghé sau,
    // `docDuAn` không còn `isPending` nên `DuAnForm` KHÔNG rơi vào nhánh «Đang
    // tải…» — tab không unmount, và đó là lúc state cũ ở lại được.
    const oKhuVuc = () => giaTriXem('Khu vực')

    const router = boot(`/pform?code=${DU_AN_KHAC.projectCode}&tab=vi-tri`)
    await waitFor(() => expect(oKhuVuc()).toHaveTextContent('Hưng Yên'))

    await router.navigate(moTab(DU_AN.projectCode))
    await waitFor(() => expect(oKhuVuc()).toHaveTextContent('Hà Nội'))

    await router.navigate(moTab(DU_AN_KHAC.projectCode))
    await waitFor(() => expect(oKhuVuc()).toHaveTextContent('Hưng Yên'))
  })

  it('ảnh vi_tri của phân khu KHÔNG lẫn vào vùng cấp dự án (I-4)', async () => {
    // Xoá mệnh đề `!m.zoneCode && !m.unitCode &&` ở `ViTriTab.tsx` → 411 passed
    // (review) — cùng lỗ đã có cổng canh ở `MatBangTab` ngay trên, chưa có ở đây.
    datApiDoc({
      media: trang([
        { ...MEDIA, id: 93, category: 'vi_tri', caption: 'Vị trí dự án' },
        { ...MEDIA, id: 94, category: 'vi_tri', zoneCode: 'ZURICH', caption: 'Vị trí phân khu' },
      ]),
    })
    boot('/pform?code=VHOP2&tab=vi-tri')

    const vung = await screen.findByRole('group', { name: 'Bản đồ vị trí' })
    expect(within(vung).getByText('Vị trí dự án')).toBeInTheDocument()
    expect(within(vung).queryByTestId('anh-thumb')).not.toBeInTheDocument()
    expect(screen.queryByText('Vị trí phân khu')).not.toBeInTheDocument()
  })
})

describe('tab Ảnh 360', () => {
  it('hiện link hiện có và mở được ra tab mới', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=anh-360')

    // Tab NHÚNG khung 360; link chỉ còn là đường thoát khi nhà cung cấp chặn nhúng.
    const link = await screen.findByRole('link', { name: 'Mở ở tab mới' })
    expect(link).toHaveAttribute('href', 'https://kuula.co/share/x')
    expect(screen.getByText('kuula.co/share/x')).toBeInTheDocument()
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('PATCH chỉ gửi link360', async () => {
    datApiDoc()
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=anh-360')

    await moSuaDuAn()
    const o = screen.getByRole('textbox', { name: /Link tham quan 360/ })
    await userEvent.clear(o)
    await userEvent.type(o, 'https://kuula.co/share/moi')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ link360: 'https://kuula.co/share/moi' })
  })

  it('chưa có link thì nói rõ chưa có, không hiện link rỗng', async () => {
    datApiDoc({ project: { ...DU_AN, link360: '' } })
    boot('/pform?code=VHOP2&tab=anh-360')

    expect(await screen.findByText(/Chưa có link tham quan 360/)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /kuula/ })).not.toBeInTheDocument()
  })

  it('tab Tổng quan không còn ô link360', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    await moSuaDuAn()
    await screen.findByRole('textbox', { name: /Tên thương mại/ })
    expect(screen.queryByRole('textbox', { name: /Link tham quan 360/ })).not.toBeInTheDocument()
  })

  it('chế độ XEM tab Tổng quan không còn khai link360 đã dời', async () => {
    // `VHOP2` có `link360` thật trong `DU_AN` — nếu `TomTatDuAn` còn đọc
    // `v.link360` (nay luôn `undefined` vì `TongQuanTab` đã bỏ trường này khỏi
    // `tuDuAn()`), màn sẽ khẳng định sai «Chưa đặt» thay vì không nhắc gì.
    datApiDoc()
    boot('/pform?code=VHOP2')

    await screen.findByRole('group', { name: 'Sở hữu và bàn giao' })
    expect(screen.queryByText(/Link tham quan 360/)).not.toBeInTheDocument()
  })

  it('đổi sang dự án khác thì hiện đúng link của dự án MỚI, không của dự án vừa xem', async () => {
    const DU_AN_KHAC = { ...DU_AN_THIEU, link360: 'https://kuula.co/share/khac' }
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code', ({ params }) =>
        HttpResponse.json(params.code === DU_AN.projectCode ? DU_AN : DU_AN_KHAC),
      ),
    )
    const moTab = (code: string) => ({ to: '/pform', search: { code, tab: 'anh-360' } }) as const

    // Ghé DU_AN_KHAC MỘT LẦN trước để nó vào cache react-query — cùng lý do
    // đã nêu ở test tương tự của `ViTriTab` phía trên: chỉ khi dự án đã có
    // trong cache, `DuAnForm` mới không rơi vào nhánh «Đang tải…» giữa hai lần
    // điều hướng, và đó mới là lúc `key` còn thiếu để lộ state cũ.
    const router = boot(`/pform?code=${DU_AN_KHAC.projectCode}&tab=anh-360`)
    expect(await screen.findByRole('link', { name: 'Mở ở tab mới' })).toHaveAttribute(
      'href',
      'https://kuula.co/share/khac',
    )

    await router.navigate(moTab(DU_AN.projectCode))
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Mở ở tab mới' })).toHaveAttribute(
        'href',
        'https://kuula.co/share/x',
      ),
    )

    // Dự án THIẾU đã ở cache từ lần ghé đầu, nên lần điều hướng này KHÔNG đi
    // qua nhánh «Đang tải…» của `DuAnForm` — `Anh360Tab` không unmount, và đây
    // đúng là chỗ thiếu `key` để lại `value` khởi tạo từ dự án vừa xem trước đó.
    // Ô NHẬP là nơi lộ ra: khung xem đọc thẳng `duAn.link360` nên luôn đúng bất
    // kể `key`.
    await router.navigate(moTab(DU_AN_KHAC.projectCode))
    await moSuaDuAn()
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: /Link tham quan 360/ })).toHaveValue(
        'https://kuula.co/share/khac',
      ),
    )
  })
})

describe('tab Mặt bằng', () => {
  it('chỉ một vùng ảnh, không còn ô ảnh mặt bằng tổng', async () => {
    datApiDoc({ media: trang([{ ...MEDIA, id: 95, category: 'mat_bang', caption: 'MB dự án' }]) })
    boot('/pform?code=VHOP2&tab=mat-bang')

    expect(await screen.findByText('MB dự án')).toBeInTheDocument()
    expect(screen.getAllByTestId('anh-lon')).toHaveLength(1)
    expect(screen.queryByText('Ảnh mặt bằng tổng')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Lưu mặt bằng tổng/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Mặt bằng tổng thể' })).not.toBeInTheDocument()
  })

  it('nhảy tab từ Mặt bằng không hỏi gì — tab này không giữ gì chưa lưu', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=mat-bang')

    await screen.findByText('Chưa có ảnh.')
    await userEvent.click(screen.getByRole('tab', { name: 'Phân khu' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('ảnh mat_bang của phân khu KHÔNG lẫn vào vùng cấp dự án', async () => {
    datApiDoc({
      media: trang([
        { ...MEDIA, id: 95, category: 'mat_bang', caption: 'Mặt bằng dự án' },
        {
          ...MEDIA,
          id: 96,
          category: 'mat_bang',
          zoneCode: 'ZURICH',
          caption: 'Mặt bằng phân khu',
        },
      ]),
    })
    boot('/pform?code=VHOP2&tab=mat-bang')

    expect(await screen.findByText('Mặt bằng dự án')).toBeInTheDocument()
    expect(screen.queryByTestId('anh-thumb')).not.toBeInTheDocument()
    expect(screen.queryByText('Mặt bằng phân khu')).not.toBeInTheDocument()
  })

  it('tab Tổng quan không còn ô ảnh mặt bằng tổng', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    await moSuaDuAn()
    await screen.findByRole('textbox', { name: /Tên thương mại/ })
    expect(screen.queryByText('Ảnh mặt bằng tổng')).not.toBeInTheDocument()
  })

  it('chế độ XEM tab Tổng quan không còn nhắc ảnh mặt bằng tổng', async () => {
    // Cùng bẫy đã sập ở `region`/`address` (Task 3) và `link360` (Task 4):
    // `TomTatDuAn` đọc `v.mapMedia?.mediaUrl`, và sau khi `TongQuanTab` bỏ
    // trường này khỏi state thì `v.mapMedia` luôn `undefined` — `GiaTri` render
    // giá trị rỗng thành «Chưa đặt», khẳng định sai cho một dự án có mặt bằng
    // thật. Mở ở chế độ XEM (không bấm Sửa) là nơi bẫy này lộ ra.
    datApiDoc()
    boot('/pform?code=VHOP2')

    await screen.findByRole('group', { name: 'Sở hữu và bàn giao' })
    expect(screen.queryByText('Ảnh mặt bằng tổng')).not.toBeInTheDocument()
  })
})

describe('nhảy tab: luôn đi, và phần vừa gõ đã lưu', () => {
  /**
   * ⚠️ NHÓM NÀY THAY CHO ~20 BÀI VỀ CỜ DIRTY. Hộp «Bỏ thay đổi chưa lưu?» đã bỏ
   * (người dùng chốt 2026-08-21): ở chế độ tạo mới nó chỉ cho đúng một lựa chọn
   * thật — mất phần vừa gõ — nên nó biến việc bấm tab thành một cửa phải đi qua.
   *
   * Bất biến mới rẻ hơn để canh: bấm tab là ĐỔI TAB, và `blur` chạy trước `click`
   * nên phần vừa gõ đã lên đường.
   */
  it('gõ dở rồi bấm tab khác: không hộp nào, tab đổi thật', async () => {
    datApiDoc({ media: trang([]) })
    batPatch()
    boot('/pform?code=VHOP2&tab=vi-tri')

    await moSuaDuAn()
    await userEvent.type(screen.getByRole('textbox', { name: /Khu vực/ }), ' thêm chữ')
    await userEvent.click(screen.getByRole('tab', { name: 'Ảnh 360' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Ảnh 360' })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    )
  })

  it('phần vừa gõ được PATCH trước khi tab đổi', async () => {
    datApiDoc({ media: trang([]) })
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=vi-tri')

    await moSuaDuAn()
    await userEvent.type(screen.getByRole('textbox', { name: /Khu vực/ }), ' Mới')
    await userEvent.click(screen.getByRole('tab', { name: 'Ảnh 360' }))

    await waitFor(() => expect(than).toEqual([{ region: 'Hà Nội Mới' }]))
  })

  it('không sửa gì thì đổi tab mà không gửi request nào', async () => {
    datApiDoc({ media: trang([]) })
    const than = batPatch()
    boot('/pform?code=VHOP2&tab=vi-tri')

    await moSuaDuAn()
    await screen.findByRole('textbox', { name: /Khu vực/ })
    await userEvent.click(screen.getByRole('tab', { name: 'Ảnh 360' }))

    expect(than).toEqual([])
  })

  it('PATCH lỗi thì nói ra ngay trên tab, không im lặng', async () => {
    datApiDoc({ media: trang([]) })
    server.use(
      http.patch('/api/v1/projects/:code', () =>
        loi422([{ field: 'region', reason: 'Không hợp lệ' }]),
      ),
    )
    boot('/pform?code=VHOP2&tab=vi-tri')

    await moSuaDuAn()
    const o = screen.getByRole('textbox', { name: /Khu vực/ })
    await userEvent.type(o, 'X')
    await userEvent.tab()

    expect(await screen.findByText(/Không hợp lệ/)).toBeInTheDocument()
  })

  it('bấm chính tab đang mở thì không đi đâu', async () => {
    datApiDoc({ media: trang([]) })
    boot('/pform?code=VHOP2&tab=vi-tri')

    await waitFor(() => expect(giaTriXem('Khu vực')).toHaveTextContent('Hà Nội'))
    await userEvent.click(screen.getByRole('tab', { name: 'Vị trí' }))

    expect(screen.getByRole('tab', { name: 'Vị trí' })).toHaveAttribute('aria-selected', 'true')
  })

  /**
   * KHOẢNG HỞ CÒN LẠI, có chủ ý: form TẠO một hàng mới (phân khu · tài liệu ·
   * căn) vẫn cần một nút Lưu — chưa có hàng thì không có gì để PATCH — nên gõ dở
   * một phân khu mới rồi nhảy tab là mất, không báo. Bài này ghim đúng hiện
   * trạng đó để nó là một quyết định chứ không phải một chỗ sót.
   */
  it('form TẠO hàng mới vẫn mất nếu nhảy tab — chưa có gì để tự lưu', async () => {
    datApiDoc({ zones: trang([]) })
    boot('/pform?code=VHOP2&tab=phan-khu')

    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm phân khu' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Tên phân khu/ }), 'Sao Biển')
    await userEvent.click(screen.getByRole('tab', { name: 'Ảnh 360' }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Ảnh 360' })).toHaveAttribute(
        'aria-selected',
        'true',
      ),
    )
  })
})



describe('tab Tiến độ', () => {
  it('hiện vùng ảnh Tiến độ, và video tiến độ ở lại đây chứ không có tab Video riêng', async () => {
    datApiDoc({
      media: trang([
        { ...MEDIA, id: 97, category: 'tien_do', caption: 'Móng tháng 7' },
        {
          ...MEDIA,
          id: 98,
          category: 'tien_do',
          contentType: 'video',
          caption: 'Bay drone tháng 8',
        },
      ]),
    })
    boot('/pform?code=VHOP2&tab=tien-do')

    const vung = (await screen.findByRole('heading', { name: 'Tiến độ', level: 3 })).closest(
      'section',
    )!
    // Bộ đếm là MỘT chuỗi liền trong cùng span (`VungMedia.tsx:58-59`) — ảnh và
    // video đếm riêng bên trong nó, nên đây là một assertion trên cả chuỗi,
    // khoanh vào đúng `span` để không khớp luôn `header`/`section` bao ngoài
    // (textContent của chúng cũng chứa chuỗi này).
    // MỘT con số, không tách «ảnh · video»: bản cũ gọi mọi thứ không phải ảnh là
    // «video», nên tour 360 và link Google Drive đều bị đếm nhầm (đo trên
    // `aina_prod` 2026-08-25: 19 tour 360 + 38 link Drive nằm trong số «video»).
    expect(within(vung).getByText('2 mục', { selector: 'span' })).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Video' })).not.toBeInTheDocument()
  })

  it('ảnh tien_do của phân khu KHÔNG lẫn vào vùng cấp dự án (I-4)', async () => {
    // Xoá mệnh đề `!m.zoneCode && !m.unitCode &&` ở `TienDoTab.tsx` → 411 passed
    // (review) — cùng lỗ đã có cổng canh ở `MatBangTab`, chưa có ở đây.
    datApiDoc({
      media: trang([
        { ...MEDIA, id: 99, category: 'tien_do', caption: 'Tiến độ dự án' },
        { ...MEDIA, id: 100, category: 'tien_do', zoneCode: 'ZURICH', caption: 'Tiến độ phân khu' },
      ]),
    })
    boot('/pform?code=VHOP2&tab=tien-do')

    const vung = (await screen.findByRole('heading', { name: 'Tiến độ', level: 3 })).closest(
      'section',
    )!
    expect(within(vung).getByText('1 mục')).toBeInTheDocument()
    expect(screen.queryByText('Tiến độ phân khu')).not.toBeInTheDocument()
  })
})
