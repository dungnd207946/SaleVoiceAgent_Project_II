/**
 * Phân loại tài liệu — cột Loại, thanh lọc, và ô chọn loại trong form.
 *
 * `documents` không có cột phân loại: backend mã hoá loại bằng tiền tố ở đầu
 * `title` và tách ra ở biên HTTP. Frontend KHÔNG được biết về tiền tố đó — nó
 * chỉ thấy hai trường rời nhau. Một test bắt được chữ «CSBH — » trong ô tiêu đề
 * nghĩa là tiền tố đã lọt ra ngoài.
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, delay, http } from 'msw'
import { server } from '../vitest.setup'
import { TAI_LIEU, boot, datApiDoc, moSuaDuAn, trang } from './re-fixture'

const CSBH = { ...TAI_LIEU, id: 71, loai: 'csbh', title: 'Bảng giá đợt 3' }
const PHAP_LY = { ...TAI_LIEU, id: 72, loai: 'phap_ly', title: 'Sổ đỏ' }
const KHAC = { ...TAI_LIEU, id: 73, loai: 'khac', title: 'Brochure' }

async function moTabTaiLieu() {
  boot('/pform?code=VHOP2')
  await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
}

describe('cột Loại', () => {
  it('bảng hiện nhãn tiếng Việt của loại, không hiện mã máy', async () => {
    datApiDoc({ documents: trang([CSBH, PHAP_LY]) })
    await moTabTaiLieu()

    expect(await screen.findByText('Chính sách bán hàng')).toBeInTheDocument()
    expect(screen.getByText('Pháp lý')).toBeInTheDocument()
    expect(screen.queryByText('csbh')).not.toBeInTheDocument()
    expect(screen.queryByText('phap_ly')).not.toBeInTheDocument()
  })

  it('tiêu đề KHÔNG mang tiền tố — tiền tố là việc của backend', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    await moTabTaiLieu()

    expect(await screen.findByText('Bảng giá đợt 3')).toBeInTheDocument()
    expect(screen.queryByText(/CSBH —/)).not.toBeInTheDocument()
  })
})

describe('thanh lọc theo loại', () => {
  it('mỗi loại hiện số lượng của nó, và bấm vào thì bảng chỉ còn loại đó', async () => {
    datApiDoc({ documents: trang([CSBH, PHAP_LY, KHAC]) })
    await moTabTaiLieu()

    const thanh = await screen.findByRole('group', { name: 'Lọc theo loại' })
    expect(within(thanh).getByRole('button', { name: /Tất cả 3/ })).toBeInTheDocument()
    expect(within(thanh).getByRole('button', { name: /Chính sách bán hàng 1/ })).toBeInTheDocument()

    await userEvent.click(within(thanh).getByRole('button', { name: /Chính sách bán hàng 1/ }))

    expect(screen.getByText('Bảng giá đợt 3')).toBeInTheDocument()
    expect(screen.queryByText('Sổ đỏ')).not.toBeInTheDocument()
    expect(screen.queryByText('Brochure')).not.toBeInTheDocument()
  })

  it('lọc một loại rỗng thì nói rõ là rỗng vì bộ lọc, không phải kho rỗng', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    await moTabTaiLieu()

    const thanh = await screen.findByRole('group', { name: 'Lọc theo loại' })
    await userEvent.click(within(thanh).getByRole('button', { name: /Hướng dẫn 0/ }))

    expect(screen.getByText(/Không có tài liệu nào thuộc loại này/)).toBeInTheDocument()
  })
})

// I2 — lọc là client-side trên TRANG ĐANG XEM (không phải toàn bộ danh sách),
// nên số đếm/câu rỗng chỉ đúng cho hàng của trang này. Banner phải LUÔN hiện,
// không chỉ lúc còn trang sau — nói sai phạm vi dù chỉ một lần cũng gây hiểu lầm
// («CSBH 4» đọc thành 4/237 hàng của dự án, không phải 4/20 hàng của trang này).
describe('lọc trên danh sách nhiều trang', () => {
  function datHaiTrang() {
    // total=21, 20 hàng/trang ⇒ 2 trang. Trang 1 (offset=0) = 1 tài liệu `khac`.
    // Trang 2 (offset=20) = 1 tài liệu `csbh` — đúng probe của reviewer.
    server.use(
      http.get('/api/v1/projects/:code/documents', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset') ?? 0)
        return HttpResponse.json(offset ? trang([CSBH], null, 21) : trang([KHAC], null, 21))
      }),
    )
  }

  it('KHÔNG còn banner «chỉ tính trang đang xem»', async () => {
    // Bỏ 2026-08-21 cùng đợt dọn chú thích: câu này tả cơ chế phân trang của
    // chính app, và thanh «Hiện 1–20 / 57» ngay dưới bảng đã nói đúng điều đó.
    datApiDoc({ documents: { items: [TAI_LIEU], total: 57, nextCursor: 'c2' } })
    boot('/pform?code=VHOP2&tab=tai-lieu')
    await screen.findByText(TAI_LIEU.title)

    expect(screen.queryByText(/chỉ tính trang đang xem/)).not.toBeInTheDocument()
  })

  it('lọc một loại rỗng khi còn trang khác thì gợi ý thử trang khác, không nói chắc chắn rỗng', async () => {
    datApiDoc()
    datHaiTrang()
    await moTabTaiLieu()

    const thanh = await screen.findByRole('group', { name: 'Lọc theo loại' })
    await userEvent.click(within(thanh).getByRole('button', { name: /Chính sách bán hàng 0/ }))

    expect(
      screen.getByText(/Chưa thấy tài liệu Chính sách bán hàng nào trong trang đang xem/),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Bỏ bộ lọc để xem tất cả/)).not.toBeInTheDocument()
  })
})

// I3 — thí nghiệm của reviewer: xoá `loai: t.loai` khỏi `sua()` không làm suite đỏ.
// Test này phải là cổng canh cho đúng chỗ đó.
describe('sửa giữ nguyên loại (đường SỬA, không phải đường TẠO)', () => {
  it('mở một tài liệu csbh rồi đổi Loại — PATCH mang loai và title trần', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    const than: Record<string, unknown>[] = []
    server.use(
      http.patch('/api/v1/projects/:code/documents/:id', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(CSBH)
      }),
    )
    await moTabTaiLieu()

    await userEvent.click(await screen.findByText('Bảng giá đợt 3'))
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
    // Ô Loại lưu ngay lúc đổi; chọn LẠI đúng giá trị đang có để thân gửi vẫn là
    // `csbh` — đó chính là bất biến cần canh (`loai` nhập vào `title` ở backend,
    // nên gửi thiếu nó là xoá phân loại).
    await userEvent.selectOptions(await screen.findByRole('combobox', { name: /Loại/ }), 'csbh')

    await waitFor(() => expect(than).toHaveLength(1))
    // Thân chỉ mang `loai` — `_payload_tai_lieu` của backend lấy nốt phần đuôi
    // `title` từ chính hàng đang có, đúng ca nó được viết ra để phục vụ.
    expect(than[0]).toEqual({ loai: 'csbh' })
  })
})

// M1 — thí nghiệm của reviewer: xoá đồng thời nhãn cột `Loại` khỏi `COT` và dòng
// `DongXem` ở bản xem không làm suite đỏ, dù nó làm mọi cột sau Tiêu đề lệch nhãn.
describe('cổng canh diện mạo cột/dòng Loại', () => {
  it('tiêu đề cột Loại có mặt trong bảng', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    await moTabTaiLieu()

    expect(await screen.findByRole('columnheader', { name: 'Loại' })).toBeInTheDocument()
  })

  it('bản xem có dòng Loại với nhãn tiếng Việt của loại', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    await moTabTaiLieu()

    await userEvent.click(await screen.findByText('Bảng giá đợt 3'))
    await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))

    expect(screen.getByText('Loại')).toBeInTheDocument()
    expect(screen.getByText('Chính sách bán hàng')).toBeInTheDocument()
  })
})

describe('form tài liệu', () => {
  it('tạo mới gửi `loai` rời khỏi `title`', async () => {
    datApiDoc({ documents: trang([]) })
    const than: Record<string, unknown>[] = []
    server.use(
      http.post('/api/v1/projects/:code/documents', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(CSBH, { status: 201 })
      }),
    )
    await moTabTaiLieu()
    await moSuaDuAn()

    await userEvent.click(await screen.findByRole('button', { name: 'Thêm tài liệu' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Tiêu đề/ }), 'Bảng giá đợt 3')
    await userEvent.selectOptions(screen.getByRole('combobox', { name: /Loại/ }), 'csbh')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu tài liệu' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.title).toBe('Bảng giá đợt 3')
    expect(than[0]!.loai).toBe('csbh')
    // `documents` không có luật completeness — luôn `published`. Nghiệm thu: bỏ
    // `status: 'published'` khỏi thân gửi TẠO MỚI (`taoTaiLieu`) phải làm bài
    // này đỏ — bài canh riêng cho SỬA (`suaTaiLieu`, PATCH) ở dưới (M-3): trước
    // bản vá này CHỈ có bài POST, nên bỏ `status: 'published'` CHỈ khỏi nhánh
    // PATCH của `TaiLieuTab` vẫn 428 passed.
    expect(than[0]!.status).toBe('published')
  })

  /**
   * ⚠️ BÀI «sửa … cũng gửi status: published» ĐÃ BỎ. Lý lẽ của nó — «PATCH không
   * được rơi về draft» — không đúng với PATCH: backend dùng `exclude_unset=True`
   * nên trường vắng mặt KHÔNG được cập nhật. Cùng lỗi lý lẽ đã sửa cho dự án ở
   * `realestate-trang-thai-suy-ra.test.tsx`. Đường TẠO thì vẫn gửi tường minh.
   */
  it('không chọn loại thì mặc định là Khác', async () => {
    datApiDoc({ documents: trang([]) })
    const than: Record<string, unknown>[] = []
    server.use(
      http.post('/api/v1/projects/:code/documents', async ({ request }) => {
        than.push((await request.json()) as Record<string, unknown>)
        return HttpResponse.json(KHAC, { status: 201 })
      }),
    )
    await moTabTaiLieu()
    await moSuaDuAn()

    await userEvent.click(await screen.findByRole('button', { name: 'Thêm tài liệu' }))
    await userEvent.type(screen.getByRole('textbox', { name: /Tiêu đề/ }), 'Brochure')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu tài liệu' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]!.loai).toBe('khac')
  })
})

// Cổng 2 — `coDuLieu = !ds.isPending && !ds.error` (`TaiLieuTab.tsx:97`, dùng ở
// `:239`). Thanh lọc đọc số đếm từ `ds.items` — lúc đang tải hoặc lỗi, số đó
// luôn là 0, một con số CHẮC CHẮN SAI (không phải chưa đủ), cùng hạng lỗi
// «bộ đếm 0/6 lúc tải» Task 3 đã bị bắt.
describe('thanh lọc chỉ hiện khi coDuLieu (không hiện lúc đang tải hoặc lỗi)', () => {
  it('đang tải: thanh lọc chưa có trong DOM, chỉ xuất hiện sau khi dữ liệu về', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/documents', async () => {
        // `delay()` mở một cửa sổ `isPending` đo được — không có nó thì response
        // giả lập trả ngay trong cùng tick, không kịp bắt được trạng thái đang tải.
        await delay(50)
        return HttpResponse.json(trang([CSBH]))
      }),
    )
    await moTabTaiLieu()

    // `getBy`/`queryBy`, KHÔNG `findBy`: đây là khoảnh khắc TRƯỚC khi dữ liệu về,
    // lúc `ds.isPending` còn `true`.
    expect(screen.queryByRole('group', { name: 'Lọc theo loại' })).not.toBeInTheDocument()

    expect(await screen.findByRole('group', { name: 'Lọc theo loại' })).toBeInTheDocument()
  })

  it('lỗi tải: thanh lọc không hiện, chỉ câu lỗi hiện', async () => {
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code/documents', () =>
        HttpResponse.json({ error: { code: 'SERVER_ERROR', message: 'lỗi' } }, { status: 500 }),
      ),
    )
    await moTabTaiLieu()

    // Chữ thật của `LoiTai` (`TrangThai.tsx`): `Không tải được {viec}.` với
    // `viec="danh sách tài liệu"` truyền từ `TaiLieuTab.tsx`.
    expect(await screen.findByText('Không tải được danh sách tài liệu.')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Lọc theo loại' })).not.toBeInTheDocument()
  })
})

describe('bộ tab mười', () => {
  it('mười tab, đúng thứ tự, không còn CSBH', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    const hangTab = await screen.findByRole('tablist')
    const ten = within(hangTab)
      .getAllByRole('tab')
      .map((t) => t.textContent?.trim())
    expect(ten).toEqual([
      'Tổng quan',
      'Vị trí',
      'Ảnh 360',
      'Mặt bằng',
      'Phân khu',
      'Toà',
      'Quỹ căn',
      'Tiến độ',
      'Media',
      'Tài liệu',
    ])
  })

  it('link cũ ?tab=csbh mở tab Tài liệu, không rơi về Tổng quan', async () => {
    datApiDoc({ documents: trang([CSBH]) })
    boot('/pform?code=VHOP2&tab=csbh')

    expect(await screen.findByRole('tab', { name: 'Tài liệu' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    // Và nó hiện TOÀN BỘ tài liệu, không lọc sẵn theo csbh: tab CSBH đã bỏ,
    // nên không còn khái niệm "mở sẵn ở một loại".
    expect(await screen.findByRole('group', { name: 'Lọc theo loại' })).toBeInTheDocument()
  })
})

describe('badge màu theo loại', () => {
  it('mỗi loại một class màu khác nhau, và pill thanh lọc cùng màu với badge', async () => {
    datApiDoc({ documents: trang([CSBH, PHAP_LY, KHAC]) })
    await moTabTaiLieu()

    const badgeCsbh = await screen.findByText('Chính sách bán hàng')
    const badgePhapLy = screen.getByText('Pháp lý')
    expect(badgeCsbh.className).not.toBe(badgePhapLy.className)
    expect(badgeCsbh.className).toMatch(/badge-doc-csbh/)
    expect(badgePhapLy.className).toMatch(/badge-doc-phaply/)

    const thanh = screen.getByRole('group', { name: 'Lọc theo loại' })
    const pillCsbh = within(thanh).getByRole('button', { name: /Chính sách bán hàng/ })
    expect(pillCsbh.className).toMatch(/badge-doc-csbh/)
  })

  it('loại lạ vẫn có nền, không mất class', async () => {
    datApiDoc({ documents: trang([{ ...KHAC, id: 99, loai: 'loai_thu_nam' }]) })
    await moTabTaiLieu()

    const badge = await screen.findByText('loai_thu_nam')
    expect(badge.className).toMatch(/badge-neutral/)
  })
})
