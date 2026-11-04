/**
 * Màn `/projects` — danh sách dự án + tab «Tài liệu gửi khách» (M4).
 *
 * Bốn thứ màn này phải giữ:
 *   · Kho rỗng là HƯỚNG DẪN, lỗi tải là LỖI — hai câu khác nhau, vì "chưa có dự
 *     án nào" hiện lúc backend chết sẽ khiến người dùng nhập lại thứ đã nhập.
 *   · Phân trang CÓ SỐ (vòng 2 §4.8): số trang suy từ `total` của server, không
 *     từ `items.length` — xem thêm `tests/realestate-phan-trang.test.tsx`.
 *   · Badge thiếu dữ liệu hiện đúng field còn thiếu (`02a §7`).
 *   · `__ALL__` không có nút Xoá — nó là row hệ thống.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { DU_AN, DU_AN_THIEU, boot, datApiDoc, trang } from './re-fixture'

describe('danh sách dự án', () => {
  it('hiện mã, tên và nhãn enum bằng tiếng Việt (không lộ giá trị máy)', async () => {
    datApiDoc({ projects: trang([DU_AN]) })
    boot('/projects')

    expect(await screen.findByText('VHOP2')).toBeInTheDocument()
    // Tra TRONG BẢNG: nhãn trạng thái cũng là <option> của dropdown lọc, nên
    // `screen.getByText` toàn màn sẽ trúng hai chỗ và báo lỗi "nhiều phần tử".
    const bang = within(screen.getByRole('table'))
    expect(bang.getByText('Vinhomes Ocean Park 2')).toBeInTheDocument()
    expect(bang.getByText('Đang bán')).toBeInTheDocument()
    expect(bang.getByText('Chung cư, Biệt thự')).toBeInTheDocument()
    // Giá trị enum dạng máy không được rò ra giao diện.
    expect(screen.queryByText('dang_ban')).not.toBeInTheDocument()
    expect(screen.queryByText('published')).not.toBeInTheDocument()
    // Cột Trạng thái đã bỏ (status suy ra, không còn hiển thị) — không lộ lại.
    expect(screen.queryByRole('columnheader', { name: 'Trạng thái' })).not.toBeInTheDocument()

    // Số `<th>` phải bằng số `<td>` một hàng — bỏ một mục COT mà quên `<td>`
    // (hoặc ngược lại) làm mọi cột sau nó lệch nhãn, im lặng.
    const soTh = screen.getAllByRole('columnheader').length
    const soTd = screen.getAllByRole('row')[1]!.querySelectorAll('td').length
    expect(soTd).toBe(soTh)
  })

  it('kho rỗng hiện hướng dẫn, KHÔNG hiện như lỗi', async () => {
    datApiDoc({ projects: trang([]) })
    boot('/projects')

    expect(await screen.findByText('Chưa có dự án nào.')).toBeInTheDocument()
    // Không `role="alert"` — kho rỗng là trạng thái bình thường của workspace mới.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('backend chết thì nói KHÔNG TẢI ĐƯỢC, không nói "chưa có dự án nào"', async () => {
    server.use(http.get('/api/v1/projects', () => new HttpResponse(null, { status: 500 })))
    boot('/projects')

    expect(await screen.findByRole('alert')).toHaveTextContent('Không tải được danh sách dự án')
    expect(screen.queryByText('Chưa có dự án nào.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
  })

  it('badge thiếu dữ liệu nêu đúng field còn thiếu', async () => {
    datApiDoc({ projects: trang([DU_AN, DU_AN_THIEU]) })
    boot('/projects')

    // Cổng phát hành nay là NĂM trường (spec 2026-08-21 §3.5) — `Tổng quan` QUAY
    // LẠI danh sách, ngược quyết định 2026-08-18. `DU_AN_THIEU` để trống cả hai.
    expect(await screen.findByText(/Thiếu: Khu vực, Tổng quan/)).toBeInTheDocument()
    // `Tiện ích` CỐ Ý ngoài cổng (rỗng ở 94/94 dự án published trên Aurora, §3.5.1).
    expect(screen.queryByText(/Thiếu:.*Tiện ích/)).not.toBeInTheDocument()
    // Dự án đủ dữ liệu KHÔNG có badge.
    const hangDu = screen.getByText('Vinhomes Ocean Park 2').closest('tr')!
    expect(within(hangDu).queryByText(/Thiếu:/)).not.toBeInTheDocument()
  })

  it('total lớn hơn một trang thì có nút sang trang 2, bấm gửi đúng offset', async () => {
    // 21 dự án, 20/trang ⇒ 2 trang — đúng ngưỡng biên.
    let lan = 0
    server.use(
      http.get('/api/v1/projects', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset') ?? 0)
        lan += 1
        return offset
          ? HttpResponse.json(trang([{ ...DU_AN, id: 3, projectCode: 'TRANG2' }], null, 21))
          : HttpResponse.json(trang([DU_AN], null, 21))
      }),
    )
    boot('/projects')

    expect(await screen.findByText('VHOP2')).toBeInTheDocument()
    const thanh = screen.getByRole('navigation', { name: 'Phân trang' })
    await userEvent.click(within(thanh).getByRole('button', { name: '2' }))

    expect(await screen.findByText('TRANG2')).toBeInTheDocument()
    expect(lan).toBe(2)
  })

  it('total vừa đúng một trang thì không có nút sang trang 2', async () => {
    datApiDoc({ projects: trang([DU_AN]) })
    boot('/projects')

    expect(await screen.findByText('VHOP2')).toBeInTheDocument()
    const thanh = screen.getByRole('navigation', { name: 'Phân trang' })
    expect(within(thanh).queryByRole('button', { name: '2' })).not.toBeInTheDocument()
  })

  it('tìm kiếm và lọc khu vực gửi lên SERVER, không lọc mảng đã tải', async () => {
    const xin: string[] = []
    server.use(
      http.get('/api/v1/projects', ({ request }) => {
        const u = new URL(request.url)
        xin.push(`${u.searchParams.get('search') ?? ''}|${u.searchParams.get('region') ?? ''}`)
        return HttpResponse.json(trang([DU_AN]))
      }),
    )
    boot('/projects')
    await screen.findByText('VHOP2')

    await userEvent.type(screen.getByLabelText('Tìm theo mã hoặc tên dự án'), 'ocean')
    await userEvent.type(screen.getByLabelText('Lọc theo khu vực'), 'Hà Nội')

    // Đợi request CUỐI: mỗi ký tự gõ vào sinh một query mới, nên assert ngay sau
    // `type()` là đọc một request giữa chuỗi gõ (`o|H`), không phải request cuối.
    await waitFor(() => expect(xin.at(-1)).toBe('ocean|Hà Nội'))
    // Nếu bộ lọc chạy ở client thì chỉ có đúng MỘT lần gọi, không có lần nào mang
    // tham số — đó là thứ assert trên loại trừ.
    expect(xin.length).toBeGreaterThan(1)
  })

  it('xoá dự án nói rõ dữ liệu con bị xoá cùng và không hoàn tác được', async () => {
    datApiDoc({ projects: trang([DU_AN]) })
    boot('/projects')
    await screen.findByText('VHOP2')

    await userEvent.click(screen.getByRole('button', { name: 'Xoá' }))
    const hop = screen.getByRole('alertdialog')
    expect(hop).toHaveTextContent('Mọi phân khu, căn, tài liệu và media của dự án này bị xoá cùng')
    expect(hop).toHaveTextContent('không hoàn tác được')
  })
})

/**
 * Bài «tab `__ALL__` đọc tài liệu dùng chung» ĐÃ XOÁ (2026-08-08) cùng chính cái
 * tab đó — người dùng chốt mọi tài liệu phải gắn với một dự án.
 *
 * Thay bằng một CỔNG theo chiều ngược lại: màn này không được mọc lại đường vào
 * kho `__ALL__`. Endpoint và dữ liệu cũ vẫn còn ở backend, nên "vô tình dựng lại"
 * là một thay đổi CHẠY ĐƯỢC, không phải một lỗi biên dịch — đúng loại hồi quy
 * cần một bài test chứ không phải một dòng chú thích.
 */
describe('màn danh sách KHÔNG còn đường vào kho `__ALL__`', () => {
  it('không có tab tài liệu nào, và không gọi `/projects/__ALL__/documents`', async () => {
    const xin: string[] = []
    datApiDoc({ projects: trang([DU_AN]) })
    server.use(
      http.get('/api/v1/projects/:code/documents', ({ params }) => {
        xin.push(String(params.code))
        return HttpResponse.json(trang([]))
      }),
    )
    boot('/projects')
    await screen.findByText('VHOP2')

    // ⚠️ HAI VẾ, VÀ CHỈ VẾ SAU LÀ CỔNG THẬT.
    //
    // Vế «không có tab nào» đúng ở thời điểm viết (bỏ tab `__ALL__` kéo theo cả
    // hàng tab), rồi ĐỎ ngày 2026-08-14 khi «Nguồn dữ liệu» mọc thành tab thứ
    // hai — và xanh lại cùng ngày khi tab đó bị bỏ, thành một nút cạnh «Thêm dự
    // án». Nó bám vào một chi tiết bố cục đang thay đổi, không vào thứ cần bảo
    // vệ. Giữ vì nó rẻ, nhưng ĐỪNG đọc nó thành «màn này cấm có tab».
    //
    // Cổng thật là vế dưới: kho `__ALL__` không được mọc lại đường vào. Endpoint
    // và dữ liệu cũ vẫn còn ở backend, nên dựng lại đường vào là một thay đổi
    // CHẠY ĐƯỢC, không phải một lỗi biên dịch.
    expect(screen.queryAllByRole('tab')).toHaveLength(0)
    expect(xin).not.toContain('__ALL__')
  })
})

describe('bấm cả dòng để mở bản ghi', () => {
  it('bấm vào một ô KHÔNG tương tác trong dòng cũng mở dự án', async () => {
    datApiDoc({ projects: trang([DU_AN]) })
    boot('/projects')
    await screen.findByText('VHOP2')

    // Ô Vị trí — chữ trơn, không phải link hay nút.
    await userEvent.click(screen.getByRole('table').querySelector('td:nth-child(3)')!)

    // Sang màn form dự án: chín tab con của nó xuất hiện.
    expect(await screen.findByRole('tab', { name: 'Phân khu' })).toBeInTheDocument()
  })

  it('bấm Xoá trong dòng thì mở hộp xác nhận và KHÔNG điều hướng', async () => {
    // Không có phép kiểm `closest()` trong `Hang` thì click này vừa mở hộp xác
    // nhận vừa nhảy sang form dự án — người dùng thấy màn đổi trong lúc đang
    // định xoá, và hộp xác nhận biến mất cùng màn cũ.
    datApiDoc({ projects: trang([DU_AN]) })
    boot('/projects')
    await screen.findByText('VHOP2')

    await userEvent.click(screen.getByRole('button', { name: 'Xoá' }))

    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    // Vẫn ở danh sách: bảng còn đó, và không có tab nào của form dự án.
    expect(screen.getByRole('table')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Phân khu' })).not.toBeInTheDocument()
  })

  it('bấm link tên dự án vẫn mở đúng dự án (đường của bàn phím)', async () => {
    datApiDoc({ projects: trang([DU_AN]) })
    boot('/projects')

    await userEvent.click(await screen.findByRole('link', { name: 'Vinhomes Ocean Park 2' }))

    expect(await screen.findByRole('tab', { name: 'Phân khu' })).toBeInTheDocument()
  })
})
