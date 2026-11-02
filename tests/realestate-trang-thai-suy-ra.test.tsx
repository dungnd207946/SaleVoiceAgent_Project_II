/**
 * `status` của CĂN là giá trị SUY RA từ completeness. Của DỰ ÁN thì KHÔNG nữa —
 * nó là ô người dùng chọn từ 2026-08-11, canh ở
 * `realestate-trang-thai-o-chon.test.tsx`. File này giữ phần còn đúng: phép suy
 * của căn, nhãn «Agent đã đọc» phải đọc `status` THẬT, và `archived` không bị hồi
 * sinh sau lưng người dùng.
 *
 * Vì sao canh ở tầng HTTP chứ không unit-test hàm suy: cái sai đắt nhất không
 * phải phép suy tính lệch, mà là form GỬI THIẾU `status` — lúc đó DB dùng
 * DEFAULT 'draft' và agent im lặng không đọc bản ghi nào. Chỉ thân request nói
 * được điều đó.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import {
  CAN,
  DU_AN,
  TAI_LIEU,
  boot,
  datApiDoc,
  giaTriXem,
  moSuaCan,
  moSuaDuAn,
  trang,
} from './re-fixture'

function batThanPatch() {
  const than: Record<string, unknown>[] = []
  server.use(
    http.patch('/api/v1/projects/:code', async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(DU_AN)
    }),
  )
  return than
}

/**
 * ⚠️ NHÓM NÀY ĐÃ ĐẢO CHIỀU (spec 2026-08-21 issue 5) và lý lẽ cũ của nó SAI.
 *
 * Bản cũ đòi thân PATCH luôn MANG `status`, viện lý «bỏ trống thì DB dùng DEFAULT
 * 'draft'». Điều đó không đúng với PATCH: backend dùng `model_dump(exclude_unset=
 * True)` nên trường vắng mặt KHÔNG được cập nhật, còn DEFAULT chỉ áp lúc INSERT.
 * Bằng chứng nằm ở backend: `test_cong_phat_hanh.py::
 * test_sua_o_khong_lien_quan_cua_du_an_published_thieu_truong` PATCH đúng một ô
 * `developer` và `status` vẫn `published`.
 *
 * Giữ bất biến sai đó là mở một lỗ THẬT: chip Trạng thái ở hàng tab PATCH riêng
 * `{status}`, còn `TongQuanTab` đọc `v.status` một lần lúc mount — nên mỗi lần
 * lưu tab Tổng quan sẽ hoàn nguyên thứ chip vừa đổi, im lặng, với response 200.
 */
describe('status của DỰ ÁN chỉ có MỘT người sở hữu — chip ở hàng tab', () => {
  it('PATCH từ tab Tổng quan KHÔNG mang status', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'draft' } })
    const than = batThanPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    const o = screen.getByRole('textbox', { name: /Đơn vị phát triển/ })

    await userEvent.type(o, 'X')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(Object.keys(than[0]!)).not.toContain('status')
  })

  it('xoá trắng Tổng quan của một dự án nháp cũng không mang status', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'draft' } })
    const than = batThanPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    await userEvent.clear(screen.getByRole('textbox', { name: /Giới thiệu dự án/ }))
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(Object.keys(than[0]!)).not.toContain('status')
    expect(than[0]!.overview).toBe('')
  })

  it('dự án NHÁP thiếu trường: KHÔNG câu nào — cả hai câu cũ đều sai chỗ', async () => {
    // Câu «Agent chưa đọc dữ liệu này» đã BỎ (người dùng chốt 2026-08-21): dự án
    // nháp thì đương nhiên agent chưa đọc, và nó hiện ở mọi lượt mở một dự án
    // đang làm dở. Câu «Chưa phát hành được» thì thuộc chip trạng thái, chỗ người
    // dùng thật sự cố phát hành.
    datApiDoc({ project: { ...DU_AN, status: 'draft', region: '' } })
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    expect(screen.queryByText(/agent chưa đọc/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/chưa phát hành được/i)).not.toBeInTheDocument()
  })
})

describe('nhãn "Agent đã đọc" đọc status THẬT, không chỉ completeness (C-1)', () => {
  it('dự án đủ ba trường nhưng status vẫn draft thì KHÔNG khẳng định agent đã đọc', async () => {
    // Kịch bản C-1: người dùng vừa điền Khu vực ở tab Vị trí (PATCH riêng, xem
    // `ViTriTab.tsx`) nhưng chưa quay lại tab Tổng quan để Lưu — hoặc trước bản
    // vá này, `ViTriTab` không hề gửi `status`. Bản ghi đủ trường mà vẫn `draft`.
    datApiDoc({ project: { ...DU_AN, status: 'draft' } })
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    // Câu «Đủ dữ liệu rồi — bấm Lưu để agent bắt đầu đọc» đã bỏ cùng nút Lưu.
    // Phần còn giữ nguyên và là phần quan trọng: KHÔNG được khẳng định agent đã
    // đọc một dự án còn ở nháp.
    expect(screen.queryByText(/Agent đã đọc dữ liệu này/)).not.toBeInTheDocument()
  })

  it('CĂN đủ ba trường nhưng status vẫn draft thì KHÔNG khẳng định agent đã đọc', async () => {
    // Mirror của bài trên nhưng cho CĂN — trước bản vá này `CanForm.tsx:405-414`
    // chỉ xét `thieu.length`, không đọc `can?.status`, nên một căn `draft` đủ
    // trường (DB hiện có đầy căn kiểu này — form cũ mặc định `MOI.status =
    // 'draft'`) hiện SAI thành "Agent đã đọc dữ liệu này".
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({ ...CAN, status: 'draft' }),
      ),
    )
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    // Câu «Đủ dữ liệu rồi» cũng đã bỏ (2026-08-21) cùng hai câu «Agent đã / chưa
    // đọc dữ liệu này» của CĂN. Phần quan trọng ở lại: không khẳng định gì.
    await screen.findByText('Thông tin căn')
    expect(screen.queryByText(/Agent đã đọc dữ liệu này/)).not.toBeInTheDocument()
  })
})

describe('status suy ra ở form căn (C-2)', () => {
  function batThanCanPost() {
    const than: Record<string, unknown>[] = []
    server.use(
      http.post('/api/v1/projects/:code/units', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(CAN, { status: 201 })
      }),
    )
    return than
  }

  function batThanCanPatch() {
    const than: Record<string, unknown>[] = []
    server.use(
      http.patch('/api/v1/projects/:code/units/:id', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(CAN)
      }),
    )
    return than
  }

  // Nghiệm thu (C-2): tháo phép suy khỏi `CanForm.onSubmit` (về `mLuu.mutate(gia_tri)`
  // trần) phải làm CẢ HAI bài dưới đỏ — trước bản vá này, `npm test` toàn repo xanh
  // 100% dù phép suy đã bị tháo hẳn, vì không cổng nào canh thân request của căn.
  it('POST /projects/:code/units — đủ ba trường bắt buộc thì gửi published', async () => {
    datApiDoc()
    const than = batThanCanPost()
    boot('/uform?code=VHOP2')
    await screen.findByRole('option', { name: /Zurich/ })

    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Phân khu/ }), 'ZURICH')
    await userEvent.type(screen.getByRole('textbox', { name: /Mã căn/ }), 'ZR-A-1203')
    await userEvent.type(screen.getByRole('spinbutton', { name: /DT thông thuỷ/ }), '78.5')
    await userEvent.type(screen.getByRole('spinbutton', { name: /Giá bán/ }), '5600000000')
    await userEvent.click(screen.getByRole('button', { name: 'Tạo căn' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.status).toBe('published')
  })

  it('PATCH /projects/:code/units/:id — thiếu Giá bán thì gửi draft', async () => {
    datApiDoc()
    const than = batThanCanPatch()
    boot('/uform?code=VHOP2&unit=41')
    await moSuaCan()

    await userEvent.clear(screen.getByRole('spinbutton', { name: /Giá bán/ }))
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.status).toBe('draft')
  })
})

describe('archived không bị hồi sinh sau lưng người dùng (I-1)', () => {
  // Từ 2026-08-11 `status` là ô chọn, nên `archived` chỉ đổi khi người dùng TỰ
  // đổi ô đó. Hai bài dưới canh hai đường khác nhau tới cùng một bất biến: tab
  // Vị trí không được gửi `status` (nếu gửi, nó tính lại và hồi sinh bản ghi), và
  // tab Tổng quan phải gửi lại đúng `archived` chứ không phải giá trị suy ra.

  it('tab Vị trí: dự án archived, sửa Địa chỉ → PATCH không mang status', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'archived' } })
    const than = batThanPatch()
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()

    await userEvent.clear(screen.getByRole('textbox', { name: /Địa chỉ/ }))
    await userEvent.type(screen.getByRole('textbox', { name: /Địa chỉ/ }), 'Long Biên')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).not.toHaveProperty('status')
  })

  it('tab Tổng quan: dự án archived đủ trường, Lưu → PATCH không mang status nên giữ archived', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'archived' } })
    const than = batThanPatch()
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    const o = screen.getByRole('textbox', { name: /Đơn vị phát triển/ })

    await userEvent.type(o, 'X')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    // Giữ `archived` bằng cách KHÔNG gửi trường đó: `exclude_unset=True` của
    // backend không cập nhật cột vắng mặt. Gửi lại `v.status` (đọc lúc mount) là
    // cách cũ, và nó hoàn nguyên thứ chip vừa đổi.
    expect(Object.keys(than[0]!)).not.toContain('status')
  })

  it('tab Tổng quan, chế độ XEM: dự án archived đủ trường → hiện câu archived, không mời bấm Lưu', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'archived' } })
    boot('/pform?code=VHOP2')

    expect(await screen.findByText(/đã lưu trữ nên agent không đọc/)).toBeInTheDocument()
    expect(screen.queryByText(/Đủ dữ liệu rồi/)).not.toBeInTheDocument()
  })
})

describe('archived giữ nguyên qua phép suy của CĂN — không bị hồi sinh (I-2, vòng 4)', () => {
  // Nghiệm thu: bỏ nhánh `archived` khỏi `trangThaiCan` phải làm bài dưới đỏ —
  // thân PATCH khi đó mang `status: 'published'` thay vì `'archived'`. Trước bản
  // vá này KHÔNG bài nào canh chuyện đó (xem docstring đã sửa ở describe I-1 bên
  // trên) — tháo hẳn nhánh này thì `npm test` toàn repo vẫn xanh 428/428.
  it('PATCH một căn archived đủ trường, sửa Đơn giá/m² → thân PATCH giữ archived', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({ ...CAN, status: 'archived' }),
      ),
    )
    const than: Record<string, unknown>[] = []
    server.use(
      http.patch('/api/v1/projects/:code/units/:id', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(CAN)
      }),
    )
    boot('/uform?code=VHOP2&unit=41')
    const o = await moSuaCan()
    void o

    const dg = screen.getByRole('spinbutton', { name: /Đơn giá/ })
    await userEvent.clear(dg)
    await userEvent.type(dg, '81000000')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.status).toBe('archived')
  })
})

describe('archived thắng completeness — nhãn không được ngụ ý điền nốt là agent đọc lại (vòng 3, I-1)', () => {
  // Nghiệm thu: đảo nhánh `archived` xuống lại SAU `thieu.length > 0` ở
  // `TongQuanTab` phải làm bài dưới đỏ — câu «còn thiếu» sẽ hiện ra thay vì
  // câu archived.
  it('tab Tổng quan: dự án archived THIẾU overview → hiện câu archived, không hiện câu còn thiếu', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'archived', overview: '' } })
    boot('/pform?code=VHOP2')

    expect(await screen.findByText(/đã lưu trữ nên agent không đọc/)).toBeInTheDocument()
    expect(screen.queryByText(/còn thiếu/)).not.toBeInTheDocument()
  })
})

describe('form căn cũng phải nói archived, không chỉ nói completeness (vòng 3, I-2)', () => {
  // Nghiệm thu: bỏ nhánh `can?.status === 'archived'` khỏi `CanForm` phải làm
  // bài dưới đỏ — câu «Agent đã đọc dữ liệu này» sẽ hiện ra thay vì câu archived.
  it('căn archived ĐỦ trường → hiện câu archived, không hiện câu Agent đã đọc', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({ ...CAN, status: 'archived' }),
      ),
    )
    boot('/uform?code=VHOP2&unit=41')
    // Nhãn archived nằm TRONG form sửa (cùng khối `thieu.length > 0 ? … : …`),
    // không ở bản tóm tắt chế độ xem — phải bấm Sửa trước, như `moSuaCan()`.
    await moSuaCan()

    expect(await screen.findByText(/đã lưu trữ nên agent không đọc/)).toBeInTheDocument()
    expect(screen.queryByText(/Agent đã đọc dữ liệu này/)).not.toBeInTheDocument()
  })

  // Nghiệm thu: bỏ dòng archived khỏi chế độ xem của `CanForm` phải làm bài dưới đỏ.
  it('căn archived ĐỦ trường, CHẾ ĐỘ XEM (chưa bấm Sửa) → cũng hiện câu archived (I-1)', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/units/:id', () =>
        HttpResponse.json({ ...CAN, status: 'archived' }),
      ),
    )
    boot('/uform?code=VHOP2&unit=41')

    expect(await screen.findByText(/đã lưu trữ nên agent không đọc/)).toBeInTheDocument()
  })
})

describe('tab Vị trí: ô thiếu được nói tại Ô, không bằng một câu ở cuối tab (I-2)', () => {
  it('dự án published thiếu Khu vực ⇒ dấu `*` ở ô, KHÔNG câu cảnh báo', async () => {
    // ⚠️ ĐỔI HAI LẦN. Dòng cảnh báo từng ở `TongQuanTab`, rồi chuyển sang
    // `TinDuAn` để mọi tab đều thấy, rồi BỎ HẲN (người dùng chốt 2026-08-21):
    // dấu `*` đỏ ngay tại ô nói cùng một điều mà không cần một câu ở cuối trang.
    datApiDoc({ project: { ...DU_AN, region: '' } })
    boot('/pform?code=VHOP2&tab=vi-tri')

    // Chế độ xem chỉ hiện «—»; dấu `*` là của ô nhập, hiện khi bấm Sửa.
    await waitFor(() => expect(giaTriXem('Khu vực')).toHaveTextContent('—'))
    await moSuaDuAn()
    const nhan = await screen.findByText('Khu vực')
    expect(nhan).toHaveTextContent('*')
    expect(screen.queryByText(/Agent sẽ thôi đọc dự án này/)).not.toBeInTheDocument()
  })

  // (M-2, vòng 3): dự án archived vốn đã không được agent đọc, nên xoá trắng
  // Khu vực không "sẽ" đổi gì — câu "sẽ thôi đọc" ở đây là sai cho ca này.
  it('dự án archived thiếu Khu vực → KHÔNG hiện cảnh báo "sẽ thôi đọc"', async () => {
    datApiDoc({ project: { ...DU_AN, status: 'archived', region: '' } })
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()

    expect(screen.queryByText(/Agent sẽ thôi đọc dự án này/)).not.toBeInTheDocument()
  })
})

describe('câu còn-thiếu chọn đúng THỜI theo status hiện tại, cả hai hướng (I-4)', () => {
  it('TongQuanTab: dự án ĐANG published mà thiếu Khu vực → không câu nào', async () => {
    // Đảo lần thứ BA. 2026-08-11 nói «Chưa phát hành được» + mờ nút Lưu; rồi «Agent
    // sẽ thôi đọc dự án này»; nay không câu nào (2026-08-21). Cả hai câu cũ đều
    // phải ở lại trong bài này: dựng lại một trong hai là đỏ ngay.
    datApiDoc({ project: { ...DU_AN, region: '' } }) // DU_AN mặc định `published`
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    expect(screen.queryByText(/Agent sẽ thôi đọc dự án này/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Chưa phát hành được/)).not.toBeInTheDocument()
  })

  it('ViTriTab: dự án CHƯA published (draft), xoá Khu vực → im lặng, không hù', async () => {
    // «Agent sẽ thôi đọc» sai THỜI ở đây — agent chưa từng đọc một dự án draft.
    // Câu «chưa đọc» thì đã bỏ (2026-08-21), nên đúng là KHÔNG câu nào.
    datApiDoc({ project: { ...DU_AN, status: 'draft' } })
    boot('/pform?code=VHOP2&tab=vi-tri')
    await moSuaDuAn()

    await userEvent.clear(screen.getByRole('textbox', { name: /Khu vực/ }))

    expect(screen.queryByText(/Agent chưa đọc dữ liệu này/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Agent sẽ thôi đọc dự án này/)).not.toBeInTheDocument()
  })
})

/**
 * ⚠️ NHÓM «câu còn-thiếu có role="status"» ĐÃ XOÁ (2026-08-21) — không phải vì
 * `role="status"` thôi quan trọng, mà vì CÂU nó canh không còn tồn tại: xoá
 * trắng một ô cổng nay không sinh dòng nào.
 *
 * Bài đó vẫn XANH sau khi câu bị bỏ, vì hàng dán đáy có một `role="status"`
 * riêng (nơi báo «Đang lưu…» / «Đã lưu.») và `findByRole('status')` bắt được nó.
 * Một bài xanh nhờ bắt đúng phần tử SAI thì tệ hơn không có bài — nó khẳng định
 * một bất biến đã chết. `DongTrangThai` vẫn giữ `role` của nó cho ca lưu trữ và
 * ca lỗi lưu, và cả hai đều có bài riêng ở `realestate-tin-du-an.test.tsx`.
 */

describe('trạng thái chỉ hiện ở form dự án, không ở bảng danh sách hay bảng tài liệu', () => {
  it('bảng danh sách dự án không có cột lẫn ô lọc trạng thái', async () => {
    datApiDoc()
    boot('/projects')

    await screen.findByText('Vinhomes Ocean Park 2')
    expect(screen.queryByRole('columnheader', { name: 'Trạng thái' })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox', { name: /Trạng thái/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Đã phát hành')).not.toBeInTheDocument()
  })

  it('trạng thái hiện ở CHIP hàng tab, không còn dòng riêng trong bản tóm tắt', async () => {
    // Đảo bài 2026-08-11 lần thứ hai. Lần đó lý do là cổng XEM=SỬA đòi mọi ô của
    // chế độ sửa có `<DongXem>` tương ứng; nay ô Trạng thái đã RỜI form (issue 5)
    // nên cổng đó lại đòi điều ngược lại — và chip nói trạng thái ở mọi tab, nên
    // một dòng nữa trong bản tóm tắt là dòng thứ hai cùng nội dung.
    datApiDoc()
    boot('/pform?code=VHOP2')

    await moSuaDuAn()
    expect(await screen.findByRole('button', { name: /Trạng thái dự án/ })).toHaveTextContent(
      'Đã phát hành',
    )
    // Không nhóm ô nào nhắc lại trạng thái — chip đã nói ở mọi tab.
    const nhom = screen.getByText('Tiêu chuẩn bàn giao').closest('section')!
    expect(within(nhom).queryByText('Đã phát hành')).not.toBeInTheDocument()
  })

  it('bảng tài liệu không còn cột Trạng thái', async () => {
    datApiDoc({ documents: trang([TAI_LIEU]) })
    boot('/pform?code=VHOP2&tab=tai-lieu')

    await screen.findByText(TAI_LIEU.title)
    expect(screen.queryByRole('columnheader', { name: 'Trạng thái' })).not.toBeInTheDocument()

    // Số `<th>` phải bằng số `<td>` một hàng — bỏ một mục COT mà quên `<td>`
    // (hoặc ngược lại) làm mọi cột sau nó lệch nhãn, im lặng.
    const soTh = screen.getAllByRole('columnheader').length
    const soTd = screen.getAllByRole('row')[1]!.querySelectorAll('td').length
    expect(soTd).toBe(soTh)
  })
})
