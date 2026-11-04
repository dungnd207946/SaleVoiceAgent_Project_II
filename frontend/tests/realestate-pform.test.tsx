/**
 * Màn `/pform` — form dự án (M4).
 *
 * Năm thứ màn này phải giữ:
 *   · 16 ô của `projects` + 1 ô media gửi lên đúng ALIAS camelCase của `router.py`
 *     — lệch một tên là một trường người dùng tưởng đã lưu mà backend không nhận
 *     (`extra="forbid"` trả 422, nhưng tên đúng-mà-sai-chỗ thì không ai thấy).
 *   · Ô số RỖNG gửi `null`, không gửi `""`.
 *   · 422 gắn lỗi vào ĐÚNG ô, không hiện repr Python ở đầu form.
 *   · Chặn publish khi thiếu completeness — TRƯỚC khi gửi request.
 *   · Không có `?code` thì mọi tab con bị khoá (chúng cần một dự án đã tồn tại).
 */
import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { server } from '../vitest.setup'
import { TAB_DU_AN } from '../src/features/realestate/tabDuAn'
import {
  CAN,
  DU_AN,
  DU_AN_THIEU,
  PHAN_KHU,
  TAI_LIEU,
  boot,
  datApiDoc,
  loi422,
  moSuaDuAn,
  trang,
} from './re-fixture'

/** Bắt thân request POST/PATCH cuối cùng. */
function batThan(duong: string, method: 'post' | 'patch', tra: object = DU_AN, status = 200) {
  const than: Record<string, unknown>[] = []
  server.use(
    http[method](duong, async ({ request }) => {
      than.push((await request.json()) as Record<string, unknown>)
      return HttpResponse.json(tra, { status })
    }),
  )
  return than
}

describe('form dự án — tạo mới', () => {
  // Bài "mọi tab con bị khoá" ĐÃ BỊ ĐẢO NGƯỢC (spec 2026-08-21 issue 1) — hành vi
  // mới có file riêng: `realestate-khong-khoa-tab.test.tsx`. Giữ lại một bài neo
  // ở đây để `TAB_DU_AN` vẫn được dùng và không tab nào lặng lẽ bị khoá lại.
  it('chưa có `?code` thì cả chín tab đều bấm được', async () => {
    boot('/pform')

    expect(await screen.findByRole('tab', { name: 'Tổng quan' })).toBeEnabled()
    for (const t of TAB_DU_AN) {
      expect(screen.getByRole('tab', { name: t.nhan })).toBeEnabled()
    }
    expect(screen.getByRole('button', { name: 'Tiếp' })).toBeInTheDocument()
  })

  it('POST tạo mới mang ĐÚNG tên — đường tạo chỉ có một ô', async () => {
    const than = batThan('/api/v1/projects', 'post')
    // POST thành công ⇒ màn điều hướng sang `?code=` và ĐỌC lại dự án. Không khai
    // đường đọc thì MSW (`onUnhandledRequest: 'error'`) ghi một lỗi lặng lẽ.
    datApiDoc()
    boot('/pform')
    await screen.findByRole('button', { name: 'Tiếp' })

    await userEvent.type(screen.getByRole('textbox', { name: /Tên thương mại/ }), 'Ocean Park 2')
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))

    await waitFor(() => expect(than).toHaveLength(1))
    // `projectCode` KHÔNG được gửi: mã suy từ tên ở backend (spec §3.1).
    expect(than[0]).toEqual({ name: 'Ocean Park 2' })
  })

  it('PATCH gửi đúng alias camelCase, và ô số xoá trắng gửi `null` không gửi `""`', async () => {
    // Bất biến này trước đây đo trên POST 19 ô của form tạo. Đường tạo giờ chỉ có
    // một ô, nên chỗ duy nhất còn dựng payload từ ô nhập là đường PATCH.
    datApiDoc()
    const than = batThan('/api/v1/projects/:code', 'patch')
    boot('/pform?code=VHOP2')
    await moSuaDuAn()

    const o = screen.getByRole('spinbutton', { name: /Tổng diện tích đất/ })
    await userEvent.clear(o)
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(than[0]).toEqual({ totalLandAreaM2: null })
    expect(Object.keys(than[0]!)).not.toContain('total_land_area_m2')
  })

  it('ô chọn nhiều gửi MẢNG, không phải chuỗi ghép', async () => {
    datApiDoc()
    const than = batThan('/api/v1/projects/:code', 'patch')
    boot('/pform?code=VHOP2')

    // Loại hình là ô token: danh mục nằm trong panel, phải mở panel trước.
    await moSuaDuAn()
    await userEvent.click(screen.getByRole('button', { name: 'Chọn từ danh sách' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Biệt thự' }))

    await waitFor(() => expect(than).toHaveLength(1))
    // `text[]` ở DB ⇒ MẢNG. `DU_AN` có sẵn `['chung_cu','biet_thu']` nên bỏ tick
    // «Biệt thự» còn lại đúng một mục.
    expect(than[0]).toEqual({ category: ['chung_cu'] })
  })

  it('tạo xong thì chuyển sang `?code=` và tab con hiện nội dung THẬT', async () => {
    batThan('/api/v1/projects', 'post')
    datApiDoc()
    boot('/pform')
    await screen.findByRole('button', { name: 'Tiếp' })

    await userEvent.type(screen.getByRole('textbox', { name: /Tên thương mại/ }), 'X')
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))

    // Chín tab đã bấm được từ TRƯỚC khi tạo, nên phép canh không còn là
    // enabled/disabled mà là: tab con thôi hỏi tên và hiện nội dung của nó.
    await userEvent.click(await screen.findByRole('tab', { name: 'Phân khu' }))
    expect(await screen.findByText('Zurich')).toBeInTheDocument()
    expect(screen.queryByText(/Dự án này tên gì/)).not.toBeInTheDocument()
  })
})

describe('form dự án — lỗi', () => {
  it('422 gắn lỗi vào ĐÚNG ô, không hiện repr thô của backend', async () => {
    server.use(
      http.post('/api/v1/projects', () =>
        loi422([{ field: 'body.name', reason: 'String should have at least 1 character' }]),
      ),
    )
    boot('/pform')
    await screen.findByRole('button', { name: 'Tiếp' })

    await userEvent.type(screen.getByRole('textbox', { name: /Tên thương mại/ }), 'X')
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))

    const oTen = await screen.findByRole('textbox', { name: /Tên thương mại/ })
    await waitFor(() => expect(oTen).toHaveAttribute('aria-invalid', 'true'))
    // Lỗi nằm cạnh chính ô đó, và `aria-describedby` trỏ tới nó.
    expect(oTen).toHaveAccessibleDescription(/at least 1 character/)
    // Câu ở cuối form nói CÓ lỗi và bao nhiêu, không dán `body.name` vào mặt người dùng.
    expect(screen.getByRole('alert')).toHaveTextContent('Một ô chưa hợp lệ')
    expect(screen.queryByText(/body\.name/)).not.toBeInTheDocument()
  })

  it('409 trùng mã nói rõ phải chọn mã khác', async () => {
    server.use(
      http.post('/api/v1/projects', () =>
        HttpResponse.json(
          { error: { code: 'DUPLICATE_CODE', message: 'Mã dự án đã tồn tại trong dự án này' } },
          { status: 409 },
        ),
      ),
    )
    boot('/pform')
    await screen.findByRole('button', { name: 'Tiếp' })

    // Mã suy từ tên nên 409 giờ tới từ hai tên rút về cùng một mã — thông điệp
    // không đổi, người dùng vẫn cần biết phải đổi tên/mã.
    await userEvent.type(screen.getByRole('textbox', { name: /Tên thương mại/ }), 'Akari City')
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Mã này đã tồn tại')
  })

  it('mã dự án không tồn tại thì chỉ đường về danh sách, KHÔNG mời thử lại', async () => {
    datApiDoc()
    boot('/pform?code=KHONGCO')

    expect(await screen.findByText(/Không có dự án nào mã KHONGCO/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Thử lại' })).not.toBeInTheDocument()
  })
})

/**
 * ⚠️ NHÓM «cổng completeness» CŨ ĐÃ BỎ. Bốn bài ở đó đo câu «Agent chưa đọc dữ
 * liệu này — còn thiếu …» trong form TẠO, và cả hai thứ đó đều không còn: câu bị
 * bỏ theo yêu cầu người dùng (2026-08-21), còn form tạo chỉ có một ô tên.
 *
 * Cổng phát hành thật nằm ở chip trạng thái — `realestate-chip-trang-thai.test.tsx`.
 */
describe('tạo bản nháp thiếu trường vẫn được', () => {
  it('chỉ có tên cũng tạo được — backend chỉ chặn lúc publish', async () => {
    const than = batThan('/api/v1/projects', 'post')
    datApiDoc()
    boot('/pform')
    await screen.findByRole('button', { name: 'Tiếp' })

    await userEvent.type(screen.getByRole('textbox', { name: /Tên thương mại/ }), 'X')
    await userEvent.click(screen.getByRole('button', { name: 'Tiếp' }))

    await waitFor(() => expect(than).toEqual([{ name: 'X' }]))
  })
})

describe('form dự án — đang sửa', () => {
  it('nạp giá trị server, và không còn ô mã dự án để khoá', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    // Không còn chế độ XEM (2026-08-21): ô nhập có ngay, và giá trị server phải
    // sang được nguyên vẹn — đó chính là thứ bài này canh.
    await moSuaDuAn()

    const oTen = await screen.findByRole('textbox', { name: /Tên thương mại/ })
    expect(oTen).toHaveValue('Vinhomes Ocean Park 2')
    // Ô «Mã dự án» ĐÃ BỎ (spec §3.1) — bản trước hiện nó ở dạng khoá để người dùng
    // thấy mình đang sửa dự án nào; việc đó nay do chip mono trên breadcrumb làm.
    expect(screen.queryByRole('textbox', { name: /Mã dự án/ })).not.toBeInTheDocument()
  })

  it('PATCH không gửi `projectCode`', async () => {
    datApiDoc()
    const than = batThan('/api/v1/projects/:code', 'patch')
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    const o = screen.getByRole('textbox', { name: /Tên thương mại/ })

    await userEvent.type(o, ' mở rộng')
    await userEvent.tab()

    await waitFor(() => expect(than).toHaveLength(1))
    expect(Object.keys(than[0]!)).not.toContain('projectCode')
    expect(than[0]!.name).toBe('Vinhomes Ocean Park 2 mở rộng')
  })

  it('breadcrumb hiện mã và tên dự án đang mở', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    // Tra theo TÊN, không theo `level: 1` đơn thuần: shell có h1 riêng (Topbar),
    // nên `findByRole('heading', {level: 1})` trả về cái nào là chuyện thứ tự DOM.
    expect(
      await screen.findByRole('heading', { name: 'Vinhomes Ocean Park 2', level: 2 }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('VHOP2').length).toBeGreaterThan(0)
    // Và có đường về danh sách — form không phải ngõ cụt.
    //
    // Khoanh vào `<main>`: panel của shell LUÔN hiện mục «Kiến thức» khi đang ở
    // mảng Agent (mà /pform thuộc mảng đó), nên truy vấn trần khớp hai link.
    //
    // Chữ là «Kiến thức» — ĐÚNG nhãn của màn đích. Trước 2026-08-08 nó là «Bất
    // động sản», tức nhãn của KHỐI bọc mục nav chứ không phải của mục nav; bài
    // test này khoá luôn chỗ đó vì đường về nói sai tên là người dùng phải đoán
    // nó dẫn đi đâu.
    const main = within(screen.getByRole('main'))
    expect(main.getByRole('link', { name: /Kiến thức/ })).toBeInTheDocument()
  })

  it('tab Tổng quan chia các phần như mockup 2026-10-08', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')

    for (const ten of [
      'Thông tin chung',
      'Giới thiệu dự án',
      'Tiện ích',
      'Quy mô và mật độ',
      'Phí dịch vụ',
      'Sở hữu và bàn giao',
      'Ảnh cover',
      'Kiến thức cho agent',
      'Cập nhật',
    ]) {
      expect(await screen.findByRole('group', { name: ten })).toBeInTheDocument()
    }
    // Tên nhóm cũ phải mất hẳn — còn lại nghĩa là đã đổi tên mà không xếp lại ô.
    for (const cu of ['Tổng quan', 'Quy mô & mật độ', 'Sở hữu & bàn giao']) {
      expect(screen.queryByRole('group', { name: cu })).not.toBeInTheDocument()
    }
  })

  /**
   * ⚠️ BA BÀI CỔNG «XEM = SỬA» ĐÃ BỎ Ở ĐÂY. Chúng so nhãn ô giữa `TomTatDuAn`
   * (chế độ XEM) và `TongQuanTab` (chế độ SỬA) — hai chế độ đó không còn tồn
   * tại: form tự lưu nên ô nhập luôn hiện, `TomTatDuAn.tsx` đã xoá khỏi cây.
   *
   * Cổng đó canh một lớp lỗi thật (một ô rơi khỏi một trong hai chế độ mà không
   * ai thấy). Với một chế độ duy nhất thì lớp lỗi đó không còn chỗ tồn tại.
   */
  it('key={duAn?.projectCode ?? "moi"} chặn TongQuanTab mang bản nháp của dự án vừa xem (I-5)', async () => {
    // Xoá `key` này ở `DuAnForm.tsx` → 411 passed (review). Kịch bản: hâm B vào
    // cache, sang A, gõ dở tên, rồi `router.navigate` THẲNG về B — thiếu `key`
    // thì `useState` của `TongQuanTab` giữ nguyên bản nháp của A trong khi tiêu
    // đề đã nói B.
    const DU_AN_KHAC = { ...DU_AN_THIEU }
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code', ({ params }) =>
        HttpResponse.json(params.code === DU_AN.projectCode ? DU_AN : DU_AN_KHAC),
      ),
    )
    const moTab = (code: string) => ({ to: '/pform', search: { code, tab: 'tong-quan' } }) as const

    // Ghé B một lần trước để vào cache react-query — nếu không, lần điều hướng
    // sau rơi vào `q.isPending`, `DuAnForm` unmount tự nhiên và bug biến mất mà
    // không nhờ `key`.
    const router = boot(`/pform?code=${DU_AN_KHAC.projectCode}`)
    await screen.findByRole('heading', { name: new RegExp(DU_AN_KHAC.name), level: 2 })

    await router.navigate(moTab(DU_AN.projectCode))
    await moSuaDuAn()
    const o = await screen.findByRole('textbox', { name: /Tên thương mại/ })
    await userEvent.type(o, 'X')

    await router.navigate(moTab(DU_AN_KHAC.projectCode))

    // `key` buộc dựng lại: bản xem mang tên của B, không phải bản nháp "…X" của A.
    await screen.findByRole('heading', { name: new RegExp(DU_AN_KHAC.name), level: 2 })
    await waitFor(() =>
      expect(
        within(screen.getByRole('group', { name: 'Thông tin chung' })).getByText(DU_AN_KHAC.name),
      ).toBeInTheDocument(),
    )
  })
})

describe('tab phân khu', () => {
  it('kho rỗng nói phải tạo phân khu trước khi nhập căn', async () => {
    datApiDoc({ zones: trang([]) })
    boot('/pform?code=VHOP2')
    await screen.findByRole('tab', { name: 'Phân khu' })

    await userEvent.click(screen.getByRole('tab', { name: 'Phân khu' }))
    expect(await screen.findByText('Dự án này chưa có phân khu nào.')).toBeInTheDocument()
    expect(screen.getByText(/tạo phân khu trước khi nhập quỹ căn/)).toBeInTheDocument()
  })

  it('tạo phân khu KHÔNG gửi `projectCode` (kế thừa từ path)', async () => {
    datApiDoc({ zones: trang([]) })
    const than = batThan('/api/v1/projects/:code/zones', 'post', {}, 201)
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Phân khu' }))
    await moSuaDuAn()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm phân khu' }))

    await userEvent.type(screen.getByRole('textbox', { name: /Tên phân khu/ }), 'Zurich')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu phân khu' }))

    await waitFor(() => expect(than).toHaveLength(1))
    expect(Object.keys(than[0]!)).not.toContain('projectCode')
    // `zones` không có luật completeness — luôn `published`. Nghiệm thu: bỏ
    // `status: 'published'` khỏi thân gửi TẠO MỚI (`taoPhanKhu`) phải làm bài
    // này đỏ — bài canh riêng cho SỬA (`suaPhanKhu`, PATCH) ở ngay dưới (M-3):
    // trước bản vá này CHỈ có bài POST, nên bỏ `status: 'published'` CHỈ khỏi
    // nhánh PATCH của `PhanKhuTab` vẫn 428 passed.
    expect(than[0]!.status).toBe('published')
  })

  /**
   * ⚠️ BÀI «sửa … cũng gửi status: published» ĐÃ BỎ. Lý lẽ của nó — «PATCH không
   * được rơi về draft» — không đúng với PATCH: backend dùng `exclude_unset=True`
   * nên trường vắng mặt KHÔNG được cập nhật. Cùng lỗi lý lẽ đã sửa cho dự án ở
   * `realestate-trang-thai-suy-ra.test.tsx`. Đường TẠO thì vẫn gửi tường minh.
   */
  it('key={code} chặn PhanKhuTab mang dữ liệu dự án vừa xem (I-2)', async () => {
    // Xoá `key` này ở `DuAnForm.tsx` → 411 passed (review). Kịch bản dựng lại
    // đúng cái review nêu: hai dự án cùng có một phân khu CÙNG MÃ `ZURICH` (rất
    // thường: `PK-1`, `TOA-A`). Hâm B vào cache, sang A, rồi `router.navigate`
    // THẲNG về B (không qua `doiTab`) — thiếu `key` thì danh sách vẫn hiện đúng
    // (`ds` khoá theo `projectCode`), nhưng nếu người dùng đã mở "Zurich của A"
    // ra xem trước khi rời đi thì bản xem đó còn đọng lại.
    const ZONE_A = { ...PHAN_KHU, name: 'Zurich của A', overview: 'Nội dung của A' }
    const ZONE_B = {
      ...PHAN_KHU,
      projectCode: DU_AN_THIEU.projectCode,
      name: 'Zurich của B',
      overview: 'Nội dung của B',
    }
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code', ({ params }) =>
        HttpResponse.json(params.code === DU_AN.projectCode ? DU_AN : DU_AN_THIEU),
      ),
      http.get('/api/v1/projects/:code/zones', ({ params }) =>
        HttpResponse.json(trang([params.code === DU_AN.projectCode ? ZONE_A : ZONE_B])),
      ),
    )
    const moTab = (code: string) => ({ to: '/pform', search: { code, tab: 'phan-khu' } }) as const

    // Ghé B một lần trước để vào cache — nếu không, lần điều hướng sau rơi vào
    // `q.isPending` và cả `DuAnForm` unmount tự nhiên, che mất đúng lỗi cần canh.
    const router = boot(`/pform?code=${DU_AN_THIEU.projectCode}&tab=phan-khu`)
    await screen.findByText('Zurich của B')

    await router.navigate(moTab(DU_AN.projectCode))
    await userEvent.click(await screen.findByText('Zurich của A'))
    expect(await screen.findByRole('heading', { name: 'Zurich của A' })).toBeInTheDocument()

    await router.navigate(moTab(DU_AN_THIEU.projectCode))

    // `key` buộc dựng lại: về danh sách của B, không còn màn chi tiết "Zurich của A".
    expect(await screen.findByText('Zurich của B')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Zurich của A' })).not.toBeInTheDocument()
  })
})

describe('bấm cả dòng trong tab con', () => {
  it('bấm một ô trơn của dòng phân khu thì MỞ XEM phân khu đó, rồi Sửa mới ra form', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Phân khu' }))
    await screen.findByText('Zurich')

    // Số `<th>` phải bằng số `<td>` một hàng — bỏ một mục COT mà quên `<td>`
    // (hoặc ngược lại) làm mọi cột sau nó lệch nhãn, im lặng.
    const soTh = screen.getAllByRole('columnheader').length
    const hang = screen.getAllByRole('row')[1]!
    expect(hang.querySelectorAll('td').length).toBe(soTh)

    // Ô Loại hình — chữ trơn.
    await userEvent.click(within(hang).getByText('Chung cư'))

    // Mở ra là bản xem dạng chữ, không có ô nhập; bấm Sửa mới nhập được.
    expect(await screen.findByText('Thông tin phân khu')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Tên phân khu/ })).not.toBeInTheDocument()
    await moSuaDuAn()
    expect(screen.getByRole('textbox', { name: /Tên phân khu/ })).toBeEnabled()
    // Mã phân khu không có ô nhập: nó tự sinh và bất biến.
    expect(screen.queryByRole('textbox', { name: /Mã phân khu/ })).not.toBeInTheDocument()
    expect(screen.getByText('ZURICH')).toBeInTheDocument()
  })

  it('bấm một ô trơn của dòng tài liệu thì MỞ XEM, rồi Sửa mới ra form', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
    await screen.findByText('Chính sách bán hàng Q3')

    await userEvent.click(screen.getByText(/ký tự/))

    expect(await screen.findByText('Nội dung tài liệu')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Tiêu đề/ })).not.toBeInTheDocument()
    await moSuaDuAn()
    expect(screen.getByRole('textbox', { name: /Tiêu đề/ })).toHaveValue(
      'Chính sách bán hàng Q3',
    )
  })

  it('bấm Xoá trong dòng tài liệu không mở form sửa', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
    await screen.findByText('Chính sách bán hàng Q3')
    await moSuaDuAn()

    await userEvent.click(screen.getByRole('button', { name: 'Xoá' }))

    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: /Tiêu đề/ })).not.toBeInTheDocument()
  })
})

describe('ô Loại hình dạng ô token chọn nhiều', () => {
  /**
   * Ô này chỉ có ở một dự án ĐÃ TỒN TẠI — đường tạo mới còn đúng một ô tên
   * (2026-08-21). Dựng dự án với `category: []` để phép «chưa tick» đúng, và khai
   * PATCH vì mỗi cú tick nay tự lưu.
   */
  async function moForm() {
    datApiDoc({ project: { ...DU_AN, category: [] } })
    batThan('/api/v1/projects/:code', 'patch')
    boot('/pform?code=VHOP2')
    await moSuaDuAn()
    return screen.getByRole('button', { name: 'Chọn từ danh sách' })
  }

  /** Mở panel danh mục và trả về nút mở (để kiểm focus sau Escape). */
  async function moPanel() {
    const nut = await moForm()
    await userEvent.click(nut)
    return nut
  }

  it('danh mục nằm sau một cú bấm — chưa mở panel thì không có checkbox nào', async () => {
    const nut = await moForm()

    // Đây là cái giá của hình dạng token, và nó được neo lại có chủ ý: ai đổi ô
    // này về dạng hiện-sẵn thì test này đỏ và họ phải đọc lại docstring.
    expect(screen.queryByRole('checkbox', { name: 'Chung cư' })).not.toBeInTheDocument()

    await userEvent.click(nut)
    expect(screen.getByRole('checkbox', { name: 'Chung cư' })).toBeInTheDocument()
  })

  it('mỗi mục là một checkbox thật — bật/tắt được, không phải chọn một chiều', async () => {
    await moPanel()

    // `role=checkbox` chứ không phải `<div onClick>`: đó là điều làm ô này dùng
    // được bằng bàn phím và đọc được bằng trình đọc màn hình.
    const o = screen.getByRole('checkbox', { name: 'Chung cư' })
    expect(o).not.toBeChecked()

    await userEvent.click(o)
    expect(o).toBeChecked()

    await userEvent.click(o)
    expect(o).not.toBeChecked()
  })

  it('chọn nhiều thì giữ cả hai và panel không tự đóng', async () => {
    await moPanel()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Chung cư' }))
    // Panel còn mở sau cú tick thứ nhất — đóng lại sau mỗi lần tick thì chọn
    // nhiều thành mở panel n lần.
    await userEvent.click(screen.getByRole('checkbox', { name: 'Biệt thự' }))

    // Đúng cái `<select multiple>` làm sai: chọn cái thứ hai KHÔNG được mất cái thứ nhất.
    expect(screen.getByRole('checkbox', { name: 'Chung cư' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'Biệt thự' })).toBeChecked()
    // Nhãn KHÔNG còn đếm «· đã chọn n» (người dùng chốt 2026-08-21): token nằm
    // ngay trong ô, đếm lại chúng ở nhãn là nói hai lần cùng một điều.
    expect(screen.queryByText(/đã chọn/)).not.toBeInTheDocument()
  })

  it('mục đã chọn hiện thành token trong ô, bỏ được bằng nút × của nó', async () => {
    await moPanel()

    await userEvent.click(screen.getByRole('checkbox', { name: 'Chung cư' }))
    await userEvent.click(screen.getByRole('checkbox', { name: 'Biệt thự' }))

    // Đây là điều bù lại cho việc danh mục bị ẩn: cái đã chọn hiện thành CHỮ
    // ngay trong ô, không phải mở panel ra mới biết mình đã chọn gì.
    await userEvent.click(screen.getByRole('button', { name: 'Bỏ chọn Chung cư' }))

    expect(screen.queryByRole('button', { name: 'Bỏ chọn Chung cư' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Bỏ chọn Biệt thự' })).toBeInTheDocument()
  })

  it('Escape đóng panel và trả focus về nút mở', async () => {
    const nut = await moPanel()

    await userEvent.keyboard('{Escape}')

    expect(screen.queryByRole('checkbox', { name: 'Chung cư' })).not.toBeInTheDocument()
    // Không trả focus thì người dùng bàn phím bị bỏ ở `<body>` và phải Tab lại
    // từ đầu form 60 ô.
    expect(nut).toHaveFocus()
  })

  it('dấu ✓ đi kèm màu — mục đã chọn không chỉ phân biệt bằng màu', async () => {
    await moPanel()

    const nhan = () => screen.getByRole('checkbox', { name: 'Chung cư' }).closest('label')!
    expect(nhan().textContent).not.toContain('✓')

    await userEvent.click(screen.getByRole('checkbox', { name: 'Chung cư' }))

    // `color-not-only`: người mù màu vẫn thấy mục nào đang chọn.
    expect(nhan().textContent).toContain('✓')
  })
})

describe('khối trạng thái của form dự án', () => {
  it('đủ dữ liệu thì IM LẶNG — số mục đã tới agent nằm ở thẻ Kiến thức cho agent', async () => {
    // Câu «Agent đã đọc dữ liệu này» đã bỏ (2026-08-21). Đầu trang chỉ báo khi
    // đang nạp hoặc lỗi; con số nằm ở thẻ Kiến thức cho agent của tab Tổng quan.
    datApiDoc()
    boot('/pform?code=VHOP2')

    await waitFor(() =>
      expect(screen.getByRole('group', { name: 'Kiến thức cho agent' })).toHaveTextContent(
        /12\/12\s*mục/,
      ),
    )
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText(/Agent đã đọc dữ liệu này/)).not.toBeInTheDocument()
  })
})

describe('đường về khi mở một bản ghi', () => {
  it('mở phân khu thì có đường về danh sách NGAY TRÊN form, không chỉ Huỷ ở cuối', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Phân khu' }))
    await userEvent.click(await screen.findByText('Zurich'))
    await screen.findByText('Thông tin phân khu')

    // Màn phân khu dài hơn một màn hình, nên đường ra phải ở TRÊN đầu.
    await userEvent.click(screen.getByRole('button', { name: '‹ Danh sách phân khu' }))

    expect(screen.queryByText('Thông tin phân khu')).not.toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('mở tài liệu cũng có đường về danh sách tài liệu', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2')
    await userEvent.click(await screen.findByRole('tab', { name: 'Tài liệu' }))
    await userEvent.click(await screen.findByText('Chính sách bán hàng Q3'))
    await screen.findByText('Nội dung tài liệu')

    await userEvent.click(screen.getByRole('button', { name: '‹ Danh sách tài liệu' }))

    expect(screen.queryByText('Nội dung tài liệu')).not.toBeInTheDocument()
    expect(screen.getByRole('table')).toBeInTheDocument()
  })

  it('`?tab=` mở sẵn đúng tab — đường về từ màn một căn trả đúng chỗ vừa rời', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=can')

    // Không phải tab Thông tin: quỹ căn mở ngay.
    expect(await screen.findByRole('searchbox', { name: 'Tìm theo mã căn' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Quỹ căn' })).toHaveAttribute('aria-selected', 'true')
  })

  it('`?tab=` giá trị lạ thì về tab đầu, không màn trắng', async () => {
    datApiDoc()
    boot('/pform?code=VHOP2&tab=khong-co-tab-nay')

    expect(await screen.findByRole('tab', { name: 'Tổng quan' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })
})

describe('tab tài liệu', () => {
  it('key={code} chặn TaiLieuTab mang bản đang sửa của dự án vừa xem (I-2)', async () => {
    const DOC_A = { ...TAI_LIEU, title: 'Tài liệu của A', body: 'Nội dung A' }
    const DOC_B = {
      ...TAI_LIEU,
      projectCode: DU_AN_THIEU.projectCode,
      title: 'Tài liệu của B',
      body: 'Nội dung B',
    }
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code', ({ params }) =>
        HttpResponse.json(params.code === DU_AN.projectCode ? DU_AN : DU_AN_THIEU),
      ),
      http.get('/api/v1/projects/:code/documents', ({ params }) =>
        HttpResponse.json(trang([params.code === DU_AN.projectCode ? DOC_A : DOC_B])),
      ),
    )
    const moTab = (code: string) => ({ to: '/pform', search: { code, tab: 'tai-lieu' } }) as const

    // Hâm cache B trước: thiếu bước này, điều hướng sau rơi vào `q.isPending`,
    // `DuAnForm` unmount tự nhiên và lỗi tự biến mất — test thành luôn-xanh.
    const router = boot(`/pform?code=${DU_AN_THIEU.projectCode}&tab=tai-lieu`)
    await screen.findByText('Tài liệu của B')

    await router.navigate(moTab(DU_AN.projectCode))
    await userEvent.click(await screen.findByText('Tài liệu của A'))
    expect(await screen.findByText('Nội dung tài liệu')).toBeInTheDocument()

    await router.navigate(moTab(DU_AN_THIEU.projectCode))

    expect(await screen.findByText('Tài liệu của B')).toBeInTheDocument()
    expect(screen.queryByText('Nội dung tài liệu')).not.toBeInTheDocument()
  })
})

describe('tab quỹ căn', () => {
  it('key={code} chặn CanTab giữ hộp xoá của căn dự án vừa xem khi đổi dự án (I-2)', async () => {
    // `CanTab` không có form sửa inline (khác `TaiLieuTab`/`PhanKhuTab`) — thứ
    // dẫn xuất từ dự án mà thiếu `key` sẽ mắc lại là `sapXoa`, hộp xác nhận xoá:
    // nó giữ nguyên object `Can` cũ (id + unitCode của dự án vừa rời) qua lần đổi
    // `projectCode`, vì `useState` không tự xoá khi chỉ prop đổi mà không remount.
    const CAN_A = { ...CAN, unitCode: 'CAN-CUA-A' }
    const CAN_B = { ...CAN, id: 99, projectCode: DU_AN_THIEU.projectCode, unitCode: 'CAN-CUA-B' }
    const ZONE_B = { ...PHAN_KHU, projectCode: DU_AN_THIEU.projectCode }
    datApiDoc()
    server.use(
      http.get('/api/v1/projects/:code', ({ params }) =>
        HttpResponse.json(params.code === DU_AN.projectCode ? DU_AN : DU_AN_THIEU),
      ),
      http.get('/api/v1/projects/:code/zones', ({ params }) =>
        HttpResponse.json(trang([params.code === DU_AN.projectCode ? PHAN_KHU : ZONE_B])),
      ),
      http.get('/api/v1/projects/:code/units', ({ params }) =>
        HttpResponse.json(trang([params.code === DU_AN.projectCode ? CAN_A : CAN_B])),
      ),
    )
    const moTab = (code: string) => ({ to: '/pform', search: { code, tab: 'quy-can' } }) as const

    // Hâm cache B trước: xem lý do ở test I-2 của tab Tài liệu.
    const router = boot(`/pform?code=${DU_AN_THIEU.projectCode}&tab=quy-can`)
    await screen.findByText('CAN-CUA-B')

    await router.navigate(moTab(DU_AN.projectCode))
    await screen.findByText('CAN-CUA-A')
    await moSuaDuAn()
    await userEvent.click(screen.getByRole('button', { name: 'Xoá' }))
    expect(await screen.findByText(/Xoá căn CAN-CUA-A/)).toBeInTheDocument()

    await router.navigate(moTab(DU_AN_THIEU.projectCode))

    // `key` buộc dựng lại: `sapXoa` về `null`, hộp xoá của CAN-CUA-A (dự án cũ)
    // không còn đè lên màn của B.
    expect(await screen.findByText('CAN-CUA-B')).toBeInTheDocument()
    expect(screen.queryByText(/Xoá căn CAN-CUA-A/)).not.toBeInTheDocument()
  })
})
