/**
 * Màn `agent` — Agent Studio (M5). Nguồn nghiệp vụ: AG_01.
 *
 * Bốn thứ màn này phải giữ, và cả bốn đều là lời hứa với người dùng chứ không
 * phải chi tiết kỹ thuật:
 *   · Không bao giờ hiện markdown hay tên hàm (BR02 · §II.3)
 *   · Sáu rào chắn hiện ra nhưng KHÔNG có công tắc (BR08)
 *   · Nói THẬT trạng thái áp dụng, không giả vờ tức thời (BR09)
 *   · Chat thử khoá khi chưa Sẵn sàng (BR13)
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

const PAYLOAD = {
  schema_version: 3,
  danh_tinh: {
    ten_agent: 'Mai',
    ten_thuong_hieu: 'An Phú Land',
    tu_xung: 'em',
    goi_khach: 'anh/chị',
    loi_chao: '',
  },
  pham_vi: {
    linh_vuc: 'realestate',
    lam_gi: 'Tư vấn dự án và đặt lịch tham quan.',
    khong_lam_gi: 'Hậu mãi và giá riêng — chuyển người thật.',
    phong_ban: [{ ten: 'CSKH', khi_nao: 'Khách hỏi việc ngoài phạm vi' }],
    cau_tu_choi: '',
  },
  giong: { giong_dieu: 'than_thien', do_dai: 'trung_binh' },
  tools: { enabled: ['find_project', 'kb_search'] },
}

/** Payload riêng của role Sale — KHÁC Khách hàng ở phần RIÊNG (phạm vi, giọng, kỹ năng
 *  chung) để các bài phân biệt được tab nào đang hiện. Phần chung giống hệt. */
const PAYLOAD_SALE = {
  ...PAYLOAD,
  pham_vi: { ...PAYLOAD.pham_vi, lam_gi: 'Báo giá nội bộ và quỹ căn cho sale.' },
  giong: { giong_dieu: 'ngan_gon', do_dai: 'ngan' },
  tools: { enabled: ['find_project', 'kb_search', 'escalate'] },
}

type Payload = typeof PAYLOAD
/** `cauHinh` của body `PUT /config` — theo `key` của role (backend `0967`). */
type BodyPut = Record<string, Payload>

interface RoleGia {
  key: string
  ten: string
  icon: string | null
  cauHinh: Record<string, unknown>
}

/** Fake `/config` + `/config/roles` CÓ TRẠNG THÁI cho tập role — thêm/xoá phải hiện lại ở
 *  lượt GET kế tiếp, đúng như backend. Mặc định hai role: Khách hàng (mặc định) · Sale.
 *  Trả về `roles` + nhật ký request role để bài test đối chiếu. */
function datApi(
  opts: {
    trangThai?: string
    laMacDinh?: boolean
    customer?: Record<string, unknown>
    sale?: Record<string, unknown>
    soRoleToiDa?: number
    them?: { key: string; ten: string; icon?: string | null }[]
  } = {},
) {
  const roles: RoleGia[] = [
    { key: 'customer', ten: 'Khách hàng', icon: 'khach', cauHinh: opts.customer ?? PAYLOAD },
    { key: 'sale', ten: 'Sale', icon: 'sale', cauHinh: opts.sale ?? PAYLOAD_SALE },
    ...(opts.them ?? []).map((t) => ({ icon: null, ...t, cauHinh: PAYLOAD })),
  ]
  const goi: { method: string; key?: string; body?: unknown }[] = []
  server.use(
    http.get('/api/v1/config', () =>
      HttpResponse.json({
        vaiTro: roles.map((r) => ({
          key: r.key,
          ten: r.ten,
          icon: r.icon,
          macDinh: r.key === 'customer',
          cauHinh: r.cauHinh,
          laMacDinh: opts.laMacDinh ?? false,
        })),
        version: 3,
        soRoleToiDa: opts.soRoleToiDa ?? 10,
      }),
    ),
    http.get('/api/v1/config/status', () =>
      HttpResponse.json({ trangThaiAgent: opts.trangThai ?? 'san_sang', version: 3 }),
    ),
    http.post('/api/v1/config/roles', async ({ request }) => {
      const body = (await request.json()) as {
        ten: string
        saoChepTu: string | null
        icon: string
      }
      goi.push({ method: 'POST', body })
      if (roles.some((r) => r.ten.toLowerCase() === body.ten.toLowerCase()))
        return HttpResponse.json(
          { error: { code: 'ROLE_TEN_DA_DUNG', message: `Đã có role tên «${body.ten}»` } },
          { status: 409 },
        )
      const key = `role_${roles.length}`
      const nguon = roles.find((r) => r.key === body.saoChepTu)
      roles.push({ key, ten: body.ten, icon: body.icon, cauHinh: nguon?.cauHinh ?? PAYLOAD })
      return HttpResponse.json(
        { key, ten: body.ten, icon: body.icon, macDinh: false },
        { status: 201 },
      )
    }),
    http.patch('/api/v1/config/roles/:key', async ({ params, request }) => {
      const body = (await request.json()) as { ten?: string; icon?: string }
      goi.push({ method: 'PATCH', key: String(params.key), body })
      const r = roles.find((x) => x.key === params.key)!
      if (body.ten !== undefined) r.ten = body.ten
      if (body.icon !== undefined) r.icon = body.icon
      return HttpResponse.json({
        key: r.key,
        ten: r.ten,
        icon: r.icon,
        macDinh: r.key === 'customer',
      })
    }),
    http.delete('/api/v1/config/roles/:key', ({ params }) => {
      goi.push({ method: 'DELETE', key: String(params.key) })
      roles.splice(
        roles.findIndex((x) => x.key === params.key),
        1,
      )
      return new HttpResponse(null, { status: 204 })
    }),
  )
  return { roles, goi }
}

/** Bắt `cauHinh` trong body của `PUT /config`. `ref.gui` là null cho tới khi request tới. */
function batPut(opts: { status?: number } = {}) {
  const ref: { gui: BodyPut | null; soLan: number } = { gui: null, soLan: 0 }
  server.use(
    http.put('/api/v1/config', async ({ request }) => {
      ref.soLan += 1
      ref.gui = ((await request.json()) as { cauHinh: BodyPut }).cauHinh
      if (opts.status)
        return HttpResponse.json({ error: { code: 'X', message: 'x' } }, { status: opts.status })
      return HttpResponse.json({ version: 4, truongDaDoi: {} })
    }),
  )
  return ref
}

async function luuVaXacNhan() {
  await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))
  await userEvent.click(await screen.findByRole('button', { name: 'Xác nhận áp dụng' }))
}

/**
 * `/agent` mở ra ở chế độ XEM (2026-08-08) — bài nào cần ô nhập phải bấm Sửa
 * trước. Trả về ô «Tên agent» đã tìm thấy, nên gọi xong là form chắc chắn đã mở.
 */
async function moFormSua() {
  await userEvent.click(await screen.findByRole('button', { name: 'Sửa cấu hình' }))
  return screen.findByDisplayValue('Mai')
}

function boot(duong = '/agent') {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [duong] }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

describe('Agent Studio — form', () => {
  it('đổi chế độ không thả focus về <body>: Sửa ⇒ ô đầu form, Huỷ ⇒ nút Sửa', async () => {
    datApi()
    boot()
    await moFormSua()
    const dangFocus = document.activeElement as HTMLElement
    expect(dangFocus).not.toBe(document.body)
    expect(['INPUT', 'TEXTAREA', 'SELECT']).toContain(dangFocus.tagName)

    await userEvent.click(screen.getByRole('button', { name: 'Huỷ' }))
    expect(await screen.findByRole('button', { name: 'Sửa cấu hình' })).toHaveFocus()
  })

  it('hiện giá trị đang có trong 8 ô', async () => {
    datApi()
    boot()
    await moFormSua()

    expect(screen.getByDisplayValue('An Phú Land')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Tư vấn dự án và đặt lịch tham quan.')).toBeInTheDocument()
  })

  it('KHÔNG còn khu «Phòng ban chuyển tiếp» — nhưng payload vẫn mang `phong_ban`', async () => {
    // Bỏ 2026-08-08: câu từ chối ngoài phạm vi tự nói được tên đầu mối. Trường
    // `pham_vi.phong_ban` VẪN nằm trong `ConfigPayload` của backend, nên nó phải đi qua
    // nguyên vẹn cho CẢ HAI role — dừng gửi là 422, gửi `[]` là âm thầm bỏ đường chuyển tiếp.
    datApi()
    const put = batPut()
    boot()
    await moFormSua()

    expect(screen.queryByLabelText('Phòng ban 1')).not.toBeInTheDocument()
    expect(screen.queryByText('Phòng ban chuyển tiếp')).not.toBeInTheDocument()

    await luuVaXacNhan()
    await waitFor(() => expect(put.gui).not.toBeNull())
    for (const r of ['sale', 'customer'] as const)
      expect(put.gui?.[r]?.pham_vi.phong_ban).toEqual([
        { ten: 'CSKH', khi_nao: 'Khách hỏi việc ngoài phạm vi' },
      ])
  })

  it('KHÔNG hiện markdown, KHÔNG hiện tên file prompt', async () => {
    // BR02: workspace không bao giờ nhìn thấy file prompt. Một textarea chứa
    // markdown ở đây là giao cho trưởng phòng kinh doanh một thứ họ không đánh
    // giá được hậu quả.
    datApi()
    const { container } = boot()
    await moFormSua()

    expect(container.textContent).not.toMatch(/SOUL\.md|RULES\.md|manifest\.toml/)
    expect(container.textContent).not.toMatch(/\{\{/)
  })
})

/**
 * XEM TRƯỚC, SỬA SAU (2026-08-08). Việc thường làm ở màn này là ĐỌC xem agent
 * đang được dặn gì; form tám ô mở sẵn nói «hãy điền» và mời gõ nhầm vào một cấu
 * hình đang chạy đúng.
 *
 * Hai lời hứa nhóm này canh:
 *   · bấm Sửa KHÔNG làm mất giá trị đang có — form mở ra là đã điền sẵn
 *   · bấm Huỷ TRẢ LẠI đúng bản trên server, không giữ lại phần vừa gõ
 */
describe('Agent Studio — xem trước, sửa sau', () => {
  it('mặc định là bản tóm tắt chỉ-đọc: có giá trị, KHÔNG có ô nhập nào', async () => {
    datApi()
    const { container } = boot()

    // Quét trong `<main>`, không quét cả màn: «An Phú Land» cũng là tên
    // workspace đang chọn ở đỉnh panel nav, nên `screen.getByText` sẽ trúng hai
    // phần tử — cùng cái bẫy đã ghi ở `boot.test.tsx`.
    const man = within(await screen.findByRole('main'))
    expect(await man.findByText('Mai')).toBeInTheDocument()
    expect(man.getByText('An Phú Land')).toBeInTheDocument()
    expect(man.getByText('Thân thiện')).toBeInTheDocument()
    // Không phải một form bị khoá: không có `<input>` nào, kể cả `disabled`.
    expect(container.querySelectorAll('main input, main textarea')).toHaveLength(0)
    expect(screen.queryByRole('button', { name: 'Lưu và áp dụng' })).not.toBeInTheDocument()
  })

  it('ô rỗng nói thành chữ «Chưa đặt», không để một dòng trống', async () => {
    // `loi_chao` và `cau_tu_choi` của PAYLOAD đều rỗng. Một `<dd>` trống trông y
    // hệt một `<dd>` chưa nạp xong, và bản tóm tắt không có ô nhập nào bên cạnh
    // để người đọc đoán ra.
    datApi()
    boot()
    await screen.findByText('Mai')

    expect(screen.getAllByText('Chưa đặt')).toHaveLength(2)
  })

  it('bấm Sửa → form mở ra ĐÃ ĐIỀN SẴN, không phải gõ lại từ đầu', async () => {
    datApi()
    boot()
    await moFormSua()

    expect(screen.getByLabelText('Tên agent')).toHaveValue('Mai')
    expect(screen.getByLabelText('Tên thương hiệu')).toHaveValue('An Phú Land')
    expect(screen.getByLabelText('Agent tự xưng')).toHaveValue('em')
    expect(screen.getByLabelText('Agent làm gì')).toHaveValue('Tư vấn dự án và đặt lịch tham quan.')
  })

  it('Huỷ trả về bản tóm tắt VÀ bỏ phần vừa gõ — bấm Sửa lại thấy giá trị cũ', async () => {
    // Nếu `huy()` chỉ đổi chế độ mà không đặt lại `form`, lần bấm Sửa sau đó mở
    // ra một form «đã có sẵn» đúng những chữ người dùng vừa từ chối.
    datApi()
    boot()
    await moFormSua()

    await userEvent.clear(screen.getByLabelText('Tên agent'))
    await userEvent.type(screen.getByLabelText('Tên agent'), 'Lan')

    await userEvent.click(screen.getByRole('button', { name: 'Huỷ' }))

    expect(await screen.findByText('Mai')).toBeInTheDocument()
    expect(screen.queryByText('Lan')).not.toBeInTheDocument()

    await moFormSua()
    expect(screen.getByLabelText('Tên agent')).toHaveValue('Mai')
  })

  it('chưa ai cấu hình gì (laMacDinh) ⇒ mở thẳng vào form, không có nút Sửa', async () => {
    // Bày bộ platform sinh ra như «cấu hình hiện tại» là báo đã xong một việc
    // chưa ai làm.
    datApi({ laMacDinh: true })
    boot()

    expect(await screen.findByDisplayValue('Mai')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sửa cấu hình' })).not.toBeInTheDocument()
  })

  it('áp dụng xong ⇒ đóng form về bản tóm tắt', async () => {
    datApi()
    batPut()
    boot()
    await moFormSua()

    await luuVaXacNhan()

    expect(await screen.findByRole('button', { name: 'Sửa cấu hình' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Tên agent')).not.toBeInTheDocument()
  })
})

describe('Agent Studio — xưng hô', () => {
  it('có HAI ô xưng hô riêng, không phải một ô `xung_ho` gộp', async () => {
    datApi()
    boot()
    await moFormSua()

    expect(screen.getByLabelText('Agent tự xưng')).toHaveValue('em')
    expect(screen.getByLabelText('Gọi khách là')).toHaveValue('anh/chị')
  })
})

/**
 * HAI ROLE (backend `0966`, người dùng chốt 2026-09-29). Danh tính · Chuẩn hoá cách đọc ·
 * Rào chắn DÙNG CHUNG; Phạm vi · Giọng điệu · Kỹ năng chung RIÊNG theo tab «Sale» /
 * «Khách hàng». «Dùng chung» chỉ ở FE — backend nhận HAI bản, nên các bài dưới canh ở
 * PAYLOAD của `PUT /config`, không ở DOM: một ô chung gõ vào mà chỉ vào một role là thứ
 * màn hình không bao giờ lộ ra.
 */
describe('Agent Studio — hai role Sale / Khách hàng', () => {
  it('có tab Sale / Khách hàng ở CẢ HAI chế độ, mặc định mở Khách hàng', async () => {
    datApi()
    boot()

    const tabs = await screen.findByRole('tablist', { name: 'Cấu hình theo người dùng agent' })
    expect(within(tabs).getByRole('tab', { name: 'Khách hàng' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
    expect(within(tabs).getByRole('tab', { name: 'Sale' })).toHaveAttribute(
      'aria-selected',
      'false',
    )
    expect(screen.getByText('Tư vấn dự án và đặt lịch tham quan.')).toBeInTheDocument()

    await moFormSua()
    expect(screen.getByRole('tab', { name: 'Khách hàng' })).toHaveAttribute('aria-selected', 'true')
  })

  it('chọn tab Sale ⇒ khu riêng hiện giá trị của Sale, khu chung không đổi', async () => {
    datApi()
    boot()
    await userEvent.click(await screen.findByRole('tab', { name: 'Sale' }))

    expect(screen.getByText('Báo giá nội bộ và quỹ căn cho sale.')).toBeInTheDocument()
    expect(screen.queryByText('Tư vấn dự án và đặt lịch tham quan.')).not.toBeInTheDocument()
    expect(within(screen.getByRole('main')).getByText('Mai')).toBeInTheDocument()
  })

  it('tab đang mở GIỮ NGUYÊN khi bấm Sửa', async () => {
    datApi()
    boot()
    await userEvent.click(await screen.findByRole('tab', { name: 'Sale' }))
    await moFormSua()

    expect(screen.getByRole('tab', { name: 'Sale' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByLabelText('Agent làm gì')).toHaveValue('Báo giá nội bộ và quỹ căn cho sale.')
  })

  it('sửa ô DÙNG CHUNG (Tên agent) ⇒ payload ghi cho CẢ HAI role', async () => {
    // Cũng là bài canh input CONTROLLED: `toHaveValue('Lan')` không bắt được một input
    // uncontrolled (trình duyệt giữ chữ trong DOM dù state đứng im) — payload thì bắt được.
    datApi()
    const put = batPut()
    boot()
    await moFormSua()

    await userEvent.clear(screen.getByLabelText('Tên agent'))
    await userEvent.type(screen.getByLabelText('Tên agent'), 'Lan')
    await luuVaXacNhan()

    await waitFor(() => expect(put.gui).not.toBeNull())
    expect(put.gui?.sale?.danh_tinh.ten_agent).toBe('Lan')
    expect(put.gui?.customer?.danh_tinh.ten_agent).toBe('Lan')
  })

  it('sửa ô RIÊNG ở tab Sale ⇒ chỉ Sale đổi, Khách hàng giữ nguyên', async () => {
    datApi()
    const put = batPut()
    boot()
    await userEvent.click(await screen.findByRole('tab', { name: 'Sale' }))
    await moFormSua()

    await userEvent.clear(screen.getByLabelText('Agent làm gì'))
    await userEvent.type(screen.getByLabelText('Agent làm gì'), 'Chỉ báo giá.')
    await luuVaXacNhan()

    await waitFor(() => expect(put.gui).not.toBeNull())
    expect(put.gui?.sale?.pham_vi.lam_gi).toBe('Chỉ báo giá.')
    expect(put.gui?.customer?.pham_vi.lam_gi).toBe('Tư vấn dự án và đặt lịch tham quan.')
  })

  it('kỹ năng chung bật/tắt theo TỪNG role', async () => {
    datApi()
    const put = batPut()
    boot()
    await userEvent.click(await screen.findByRole('tab', { name: 'Sale' }))
    await moFormSua()

    await userEvent.click(screen.getByLabelText('Tra tài liệu của workspace'))
    await luuVaXacNhan()

    await waitFor(() => expect(put.gui).not.toBeNull())
    expect(put.gui?.sale?.tools.enabled).not.toContain('kb_search')
    expect(put.gui?.customer?.tools.enabled).toContain('kb_search')
  })

  it('phần chung lệch nhau trên server ⇒ màn lấy của Khách hàng và lưu ĐỒNG BỘ cả hai', async () => {
    // Hai hàng lệch nhau vì ai đó sửa DB tay: màn phải hiện đúng thứ SẼ được lưu,
    // không để một nửa mỗi bên.
    datApi({ sale: { ...PAYLOAD_SALE, danh_tinh: { ...PAYLOAD.danh_tinh, ten_agent: 'Khác' } } })
    const put = batPut()
    boot()
    await moFormSua()
    await luuVaXacNhan()

    await waitFor(() => expect(put.gui).not.toBeNull())
    expect(put.gui?.sale?.danh_tinh.ten_agent).toBe('Mai')
  })

  it('không còn gọi route bản nháp / xem trước / xuất bản', async () => {
    datApi()
    const cu: string[] = []
    server.use(
      http.all('/api/v1/config/:cu', ({ params }) => {
        if (params.cu !== 'status') cu.push(String(params.cu))
        return HttpResponse.json({}, { status: 404 })
      }),
    )
    const put = batPut()
    boot()
    await moFormSua()
    await luuVaXacNhan()

    await waitFor(() => expect(put.soLan).toBe(1))
    expect(cu).toEqual([])
  })
})

/**
 * Cấu hình agent chia HAI MÀN (2026-08-07), theo phạm vi chứ không theo loại ô:
 *   · `/agent`       — CHUNG cho mọi lĩnh vực: danh tính, rào chắn, 3 kỹ năng chung
 *   · `/ky-nang-bds` — RIÊNG lĩnh vực Bất động sản: 9 kỹ năng còn lại
 *
 * Tab «Lĩnh vực» trong màn đã bỏ: nó giấu lĩnh vực thứ hai sau một cú bấm và
 * giấu luôn ranh giới chung ↔ riêng. Ranh giới đó giờ nằm trong nav, thành khối
 * có nhãn (`tests/shell.test.tsx`).
 *
 * ĐIỀU KHÔNG ĐỔI, và là thứ nhóm test này canh: hai màn sửa CÙNG một cấu hình,
 * và tổng vẫn đúng 12 kỹ năng — tách màn không được làm rơi mất kỹ năng nào.
 */
describe('Agent — cấu hình chung tách khỏi kỹ năng lĩnh vực', () => {
  it('màn chung có ĐÚNG 3 kỹ năng chung, không có kỹ năng BĐS', async () => {
    datApi()
    boot()
    await moFormSua()

    expect(screen.getByLabelText('Tra tài liệu của workspace')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(3)
    expect(screen.queryByLabelText('Đặt lịch tham quan')).not.toBeInTheDocument()
    // AG_01 §II.3: tên hàm không lộ ra giao diện.
    expect(screen.queryByText('kb_search')).not.toBeInTheDocument()
  })

  it('màn kỹ năng BĐS có ĐÚNG 8 kỹ năng còn lại — 3 + 8 = đủ 11, không rơi cái nào', async () => {
    datApi()
    boot('/ky-nang-bds')
    await screen.findByText('Kỹ năng Bất động sản')

    expect(screen.getByLabelText('Đặt lịch tham quan')).toBeInTheDocument()
    expect(screen.getAllByRole('checkbox')).toHaveLength(8)
    expect(screen.queryByLabelText('Tra tài liệu của workspace')).not.toBeInTheDocument()
    expect(screen.queryByText('search_units')).not.toBeInTheDocument()
  })

  it('khu Lĩnh vực có tab ĐÃ BỎ — tablist DUY NHẤT của màn là tab theo role', async () => {
    datApi()
    boot()
    await moFormSua()

    // Thứ tự tab = thứ tự `role_config.thu_tu` của server: role mặc định đứng đầu.
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent)
    expect(tabs).toEqual(['Khách hàng', 'Sale'])
    expect(screen.getAllByRole('tablist')).toHaveLength(1)
  })

  it('màn Kỹ năng BĐS CHƯA chia tab — bật một kỹ năng áp cho CẢ HAI role', async () => {
    datApi()
    const put = batPut()
    boot('/ky-nang-bds')
    await screen.findByText('Kỹ năng Bất động sản')
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument()

    await userEvent.click(screen.getByLabelText('Đặt lịch tham quan'))
    await luuVaXacNhan()

    await waitFor(() => expect(put.gui).not.toBeNull())
    expect(put.gui?.sale?.tools.enabled).toContain('booking')
    expect(put.gui?.customer?.tools.enabled).toContain('booking')
  })

  it('bật kỹ năng thiếu phụ thuộc thì cảnh báo NGAY — ở màn kỹ năng lĩnh vực', async () => {
    // find_project (phụ thuộc của booking) phải TẮT ở đây — PAYLOAD mặc định
    // bật sẵn nó, nên bài này ghi đè bằng bản nháp không có find_project.
    datApi({
      customer: { ...PAYLOAD, tools: { enabled: ['kb_search'] } },
      sale: { ...PAYLOAD_SALE, tools: { enabled: ['kb_search'] } },
    })
    boot('/ky-nang-bds')
    await screen.findByText('Kỹ năng Bất động sản')

    await userEvent.click(screen.getByLabelText('Đặt lịch tham quan'))

    expect(await screen.findByText('Cần Nhận diện tên dự án mới chạy đúng.')).toBeInTheDocument()
  })

  /**
   * Cảnh báo phải SỬA ĐƯỢC tại chỗ. Trước 2026-08-08 nó chỉ là một câu dưới đáy
   * thẻ: nói ra vấn đề rồi bỏ mặc người dùng tự dò ngược lên tìm đúng hàng.
   *
   * Và canh luôn cái bẫy của cách sửa: nút nằm TRONG `<label>` thì click vừa bật
   * phụ thuộc vừa lật công tắc của chính hàng đang cảnh báo — nên bài này khẳng
   * định cả hai kỹ năng cùng BẬT sau một cú bấm, không phải đổi chỗ cho nhau.
   */
  it('nút trong cảnh báo bật phụ thuộc mà KHÔNG tắt kỹ năng vừa bật', async () => {
    // Cùng lý do bài trên: find_project phải TẮT để cảnh báo có cơ hội hiện ra.
    datApi({
      customer: { ...PAYLOAD, tools: { enabled: ['kb_search'] } },
      sale: { ...PAYLOAD_SALE, tools: { enabled: ['kb_search'] } },
    })
    boot('/ky-nang-bds')
    await screen.findByText('Kỹ năng Bất động sản')

    await userEvent.click(screen.getByLabelText('Đặt lịch tham quan'))
    await userEvent.click(await screen.findByRole('button', { name: 'Bật Nhận diện tên dự án' }))

    expect(screen.getByLabelText('Đặt lịch tham quan')).toBeChecked()
    expect(screen.getByLabelText('Nhận diện tên dự án')).toBeChecked()
    expect(screen.queryByText(/mới chạy đúng/)).not.toBeInTheDocument()
  })

  /**
   * Cảnh báo toàn cục phải hiện ở CẢ HAI màn: "không bật kỹ năng nào" là tình
   * trạng của AGENT, không của một màn — người đang ở màn Cấu hình chung cũng
   * cần biết agent không làm được gì. Nó sống ở `KhungSuaAgent`, cái vỏ dùng
   * chung; tách màn mà để nó ở một bên là một nửa số người dùng không thấy.
   *
   * Mỗi ca đặt bản nháp chỉ bật ĐÚNG kỹ năng thuộc màn đang mở: bản nháp nằm ở
   * server, còn công tắc là state cục bộ chưa lưu — nên tắt ở màn này rồi sang
   * màn kia thì màn kia vẫn đọc lại bản nháp cũ, không nối tiếp được.
   */
  it('tắt hết kỹ năng thì cảnh báo toàn cục hiện ở màn Cấu hình chung (ER_03), nêu đúng role', async () => {
    datApi({ customer: { ...PAYLOAD, tools: { enabled: ['kb_search'] } } })
    boot()
    await moFormSua()

    await userEvent.click(screen.getByLabelText('Tra tài liệu của workspace'))
    expect(await screen.findByText(/Agent cho Khách hàng sẽ không làm/)).toBeInTheDocument()
  })

  it('tắt hết kỹ năng thì cảnh báo toàn cục hiện ở màn Kỹ năng BĐS (ER_03)', async () => {
    datApi({
      customer: { ...PAYLOAD, tools: { enabled: ['find_project'] } },
      sale: { ...PAYLOAD_SALE, tools: { enabled: ['find_project'] } },
    })
    boot('/ky-nang-bds')
    await screen.findByText('Kỹ năng Bất động sản')

    await userEvent.click(screen.getByLabelText('Nhận diện tên dự án'))
    expect(await screen.findByText(/Agent cho Khách hàng, Sale sẽ không làm/)).toBeInTheDocument()
  })
})

describe('Agent Studio — 6 rào chắn', () => {
  it('hiện đủ 6 và KHÔNG cái nào có công tắc', async () => {
    // BR08: hiện để khách yên tâm, khoá vì bốn trong sáu là điều kiện đúng đắn
    // hoặc nghĩa vụ pháp lý. Một công tắc ở đây là bán một công tắc gây sự cố.
    // Ở chế độ XEM — mặc định của màn. Sáu rào chắn phải có mặt ở cả hai chế độ:
    // chúng là lời hứa về những gì agent sẽ KHÔNG làm, bỏ khỏi thứ người dùng
    // thấy mặc định là giấu đúng phần trấn an.
    datApi()
    boot()

    const ds = await screen.findByRole('list', { name: /rào chắn/i })

    expect(ds.querySelectorAll('li')).toHaveLength(6)
    expect(ds.querySelectorAll('input, button')).toHaveLength(0)
  })
})

describe('Agent Studio — không còn chat thử', () => {
  it('màn Agent không có ô «Thử ngay» — nó đã sang màn API Keys', async () => {
    datApi()
    boot()
    await moFormSua()

    expect(screen.queryByPlaceholderText(/thử/i)).not.toBeInTheDocument()
  })
})

/**
 * Dialog xem lại. Từ backend `0966` không còn `POST /config/preview` — «Sẽ đổi» tính ở
 * client, chia nhóm Dùng chung / Sale / Khách hàng.
 */
describe('Agent Studio — dialog Lưu và áp dụng', () => {
  it('liệt kê thay đổi theo nhóm: Dùng chung một lần, phần riêng theo role', async () => {
    datApi()
    boot()
    await moFormSua()

    await userEvent.clear(screen.getByLabelText('Tên agent'))
    await userEvent.type(screen.getByLabelText('Tên agent'), 'Lan')
    await userEvent.click(screen.getByRole('tab', { name: 'Sale' }))
    await userEvent.clear(screen.getByLabelText('Agent làm gì'))
    await userEvent.type(screen.getByLabelText('Agent làm gì'), 'Chỉ báo giá.')
    await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))

    const dialog = await screen.findByRole('dialog')
    const chung = within(dialog).getByRole('list', { name: 'Sẽ đổi — Dùng chung' })
    expect(
      within(chung)
        .getAllByRole('listitem')
        .map((l) => l.textContent),
    ).toEqual(['danh_tinh.ten_agent'])
    const sale = within(dialog).getByRole('list', { name: 'Sẽ đổi — Sale' })
    expect(
      within(sale)
        .getAllByRole('listitem')
        .map((l) => l.textContent),
    ).toEqual(['pham_vi.lam_gi'])
    // Khách hàng không đổi phần riêng ⇒ không có nhóm của nó.
    expect(
      within(dialog).queryByRole('list', { name: 'Sẽ đổi — Khách hàng' }),
    ).not.toBeInTheDocument()
    // BR10: câu này phải có trong dialog xác nhận.
    expect(within(dialog).getByText(/vẫn dùng bản cũ tới khi kết thúc/)).toBeInTheDocument()
  })

  it('không có gì đổi thì dialog nói thẳng, vẫn cho áp dụng', async () => {
    datApi()
    boot()
    await moFormSua()

    await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))

    expect(await screen.findByText(/Không có thay đổi so với bản đang chạy/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Xác nhận áp dụng' })).toBeEnabled()
  })

  it('PUT hỏng thì dialog ở lại và báo chưa có gì thay đổi', async () => {
    datApi()
    batPut({ status: 422 })
    boot()
    await moFormSua()

    await luuVaXacNhan()

    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByText(/chưa có gì thay đổi/i)).toBeInTheDocument()
  })

  it('Xác nhận → một PUT /config, đóng dialog, báo đã áp dụng vN', async () => {
    datApi()
    const put = batPut()
    boot()
    await moFormSua()

    await luuVaXacNhan()

    expect(await screen.findByText(/Đã áp dụng v4/)).toBeInTheDocument()
    expect(put.soLan).toBe(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('Escape đóng dialog — cùng khuôn TaoKhoaDialog', async () => {
    datApi()
    boot()
    await moFormSua()

    await userEvent.click(screen.getByRole('button', { name: 'Lưu và áp dụng' }))
    await screen.findByRole('dialog')

    await userEvent.keyboard('{Escape}')

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})

/**
 * Role do workspace TỰ TẠO (backend `0967`): «Khách hàng» luôn có và không xoá được, các
 * role khác thêm/đổi tên/xoá ngay trên hàng tab. Ba thao tác ÁP DỤNG NGAY (không chờ «Lưu
 * và áp dụng»), và thêm/xoá giữa lúc đang sửa KHÔNG được làm mất phần đang gõ dở.
 */
describe('Agent Studio — role tự tạo', () => {
  async function themRole(ten: string) {
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm role' }))
    const dialog = await screen.findByRole('dialog', { name: 'Thêm role' })
    await userEvent.type(within(dialog).getByLabelText('Tên role'), ten)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Thêm role' }))
  }

  it('thêm role ⇒ POST với bộ MẶC ĐỊNH (không chép từ role nào), tab mới hiện và được mở', async () => {
    const { goi } = datApi()
    boot()
    await themRole('Nhà đầu tư')

    const tab = await screen.findByRole('tab', { name: 'Nhà đầu tư' })
    expect(tab).toHaveAttribute('aria-selected', 'true')
    // Icon gợi ý = hình ĐẦU TIÊN chưa role nào dùng (bỏ qua hai hình của Khách hàng/Sale).
    expect(goi).toEqual([
      { method: 'POST', body: { ten: 'Nhà đầu tư', saoChepTu: null, icon: 'vuong_mien' } },
    ])
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('hộp Thêm role KHÔNG còn ô «Cấu hình ban đầu» — role mới luôn dùng bộ mặc định', async () => {
    datApi()
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm role' }))
    const dialog = await screen.findByRole('dialog', { name: 'Thêm role' })
    expect(within(dialog).queryByLabelText('Cấu hình ban đầu')).not.toBeInTheDocument()
    expect(within(dialog).queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('thêm role giữa lúc đang sửa GIỮ phần đang gõ, và Lưu gửi đủ ba role', async () => {
    datApi()
    const put = batPut()
    boot()
    await moFormSua()
    await userEvent.clear(screen.getByLabelText('Tên agent'))
    await userEvent.type(screen.getByLabelText('Tên agent'), 'Lan')

    await themRole('Nhà đầu tư')
    await screen.findByRole('tab', { name: 'Nhà đầu tư' })
    expect(screen.getByLabelText('Tên agent')).toHaveValue('Lan')

    await luuVaXacNhan()
    await waitFor(() => expect(put.gui).not.toBeNull())
    expect(Object.keys(put.gui ?? {}).sort()).toEqual(['customer', 'role_2', 'sale'])
    // Phần chung đang gõ đi sang cả role vừa tạo.
    expect(put.gui?.role_2?.danh_tinh.ten_agent).toBe('Lan')
  })

  it('tên trùng ⇒ dialog ở lại và hiện câu của backend', async () => {
    datApi()
    boot()
    await themRole('sale')

    const dialog = screen.getByRole('dialog', { name: 'Thêm role' })
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Đã có role tên «sale»')
  })

  it('Khách hàng không có nút Xoá, role khác thì có', async () => {
    datApi()
    boot()
    await screen.findByRole('tab', { name: 'Khách hàng' })

    expect(screen.getByRole('button', { name: 'Sửa role Khách hàng' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Xoá role/ })).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Sale' }))
    expect(screen.getByRole('button', { name: 'Xoá role Sale' })).toBeInTheDocument()
  })

  it('xoá role ⇒ DELETE, tab biến mất, về tab Khách hàng', async () => {
    const { goi } = datApi()
    boot()
    await userEvent.click(await screen.findByRole('tab', { name: 'Sale' }))
    await userEvent.click(screen.getByRole('button', { name: 'Xoá role Sale' }))
    const dialog = await screen.findByRole('dialog', { name: 'Xoá Sale?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Xoá role' }))

    await waitFor(() => expect(screen.queryByRole('tab', { name: 'Sale' })).not.toBeInTheDocument())
    expect(screen.getByRole('tab', { name: 'Khách hàng' })).toHaveAttribute('aria-selected', 'true')
    expect(goi).toEqual([{ method: 'DELETE', key: 'sale' }])
  })

  it('đổi tên ⇒ PATCH CHỈ mang tên (icon không đổi thì không gửi), tab đổi tên', async () => {
    const { goi } = datApi()
    boot()
    await userEvent.click(await screen.findByRole('tab', { name: 'Sale' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sửa role Sale' }))
    const dialog = await screen.findByRole('dialog', { name: 'Sửa Sale' })
    const o = within(dialog).getByLabelText('Tên role')
    await userEvent.clear(o)
    await userEvent.type(o, 'Kinh doanh')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Lưu' }))

    const tab = await screen.findByRole('tab', { name: 'Kinh doanh' })
    expect(tab).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Báo giá nội bộ và quỹ căn cho sale.')).toBeInTheDocument()
    expect(goi).toEqual([{ method: 'PATCH', key: 'sale', body: { ten: 'Kinh doanh' } }])
  })

  it('hết chỗ (đủ trần) ⇒ không có nút Thêm role', async () => {
    datApi({ soRoleToiDa: 2 })
    boot()
    await screen.findByRole('tab', { name: 'Sale' })
    expect(screen.queryByRole('button', { name: 'Thêm role' })).not.toBeInTheDocument()
  })
})

/**
 * Hàng tab NHIỀU role (2026-09-30): không vừa thì gom vào «+N», tab đang mở luôn ở trên
 * hàng, và mỗi role một icon. jsdom không có bố cục nên bài tràn GIẢ bề rộng: mỗi tab
 * 100px, đầu khung 400px, cụm nút bên phải 80px ⇒ chỗ cho tab 304px.
 */
describe('Agent Studio — nhiều role', () => {
  const NHIEU = [
    { key: 'vip', ten: 'VIP', icon: 'vuong_mien' },
    { key: 'dau_tu', ten: 'Nhà đầu tư', icon: 'dau_tu' },
    { key: 'doi_tac', ten: 'Đối tác', icon: 'doi_tac' },
    { key: 'dai_ly', ten: 'Đại lý', icon: 'dai_ly' },
  ]

  function giaBeRong() {
    vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockImplementation(function (
      this: HTMLElement,
    ) {
      if (this.getAttribute('role') === 'tab' || this.parentElement?.getAttribute('aria-hidden'))
        return 100
      if (this.classList.contains('ml-auto')) return 80
      return 0
    })
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (
      this: HTMLElement,
    ) {
      return this.classList.contains('rounded-t-lg') ? 400 : 0
    })
  }
  afterEach(() => vi.restoreAllMocks())

  it('không đo được bề rộng (jsdom) ⇒ hiện TẤT CẢ tab, không có nút «+N»', async () => {
    datApi({ them: NHIEU })
    boot()
    await screen.findByRole('tab', { name: 'Đại lý' })
    expect(screen.getAllByRole('tab')).toHaveLength(6)
    expect(screen.queryByRole('button', { name: /role khác$/ })).not.toBeInTheDocument()
  })

  it('không vừa ⇒ gom phần dư vào «+N», chọn từ menu thì tab đó lên hàng và được mở', async () => {
    giaBeRong()
    datApi({ them: NHIEU })
    boot()

    // 304px − 60px chỗ nút «+N» = 244px ⇒ vừa 2 tab (104px/tab gồm khe).
    const nutN = await screen.findByRole('button', { name: '4 role khác' })
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Khách hàng', 'Sale'])

    await userEvent.click(nutN)
    const menu = screen.getByRole('menu', { name: 'Role khác' })
    await userEvent.click(within(menu).getByRole('menuitem', { name: 'Đại lý' }))

    const tab = await screen.findByRole('tab', { name: 'Đại lý' })
    expect(tab).toHaveAttribute('aria-selected', 'true')
    // Tab đang mở THẾ CHỖ tab cuối — số tab trên hàng không đổi.
    expect(screen.getAllByRole('tab').map((t) => t.textContent)).toEqual(['Khách hàng', 'Đại lý'])
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  })

  it('menu có ô tìm khi ẩn từ 5 role, tìm không dấu', async () => {
    giaBeRong()
    datApi({ them: [...NHIEU, { key: 'phap_ly', ten: 'Pháp lý', icon: 'phap_ly' }] })
    boot()
    await userEvent.click(await screen.findByRole('button', { name: '5 role khác' }))
    await userEvent.type(screen.getByLabelText('Tìm role'), 'dau tu')

    const menu = screen.getByRole('menu', { name: 'Role khác' })
    expect(
      within(menu)
        .getAllByRole('menuitem')
        .map((m) => m.textContent),
    ).toEqual(['Nhà đầu tư'])
    await userEvent.keyboard('{Enter}')
    expect(await screen.findByRole('tab', { name: 'Nhà đầu tư' })).toHaveAttribute(
      'aria-selected',
      'true',
    )
  })

  it('Esc đóng menu và trả focus về nút «+N»', async () => {
    giaBeRong()
    datApi({ them: NHIEU })
    boot()
    const nutN = await screen.findByRole('button', { name: '4 role khác' })
    await userEvent.click(nutN)
    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    expect(nutN).toHaveFocus()
  })

  it('phím → trên hàng tab đi tới cả role đang nằm trong menu', async () => {
    giaBeRong()
    datApi({ them: NHIEU })
    boot()
    await userEvent.click(await screen.findByRole('tab', { name: 'Sale' }))
    await userEvent.keyboard('{ArrowRight}')

    const tab = await screen.findByRole('tab', { name: 'VIP' })
    expect(tab).toHaveAttribute('aria-selected', 'true')
    expect(tab).toHaveFocus()
  })

  it('chuyển tab sang PHẢI ⇒ thân khối trượt vào từ phải; sang TRÁI ⇒ từ trái', async () => {
    datApi({ them: NHIEU })
    boot()
    await userEvent.click(await screen.findByRole('tab', { name: 'Đối tác' }))
    expect(screen.getByRole('tabpanel').firstElementChild).toHaveClass('tab-vao-phai')
    await userEvent.click(screen.getByRole('tab', { name: 'Sale' }))
    expect(screen.getByRole('tabpanel').firstElementChild).toHaveClass('tab-vao-trai')
  })

  it('role mới được gợi ý một icon CHƯA dùng, và đổi được icon trong hộp Sửa', async () => {
    const { goi } = datApi({ them: [{ key: 'vip', ten: 'VIP', icon: 'vuong_mien' }] })
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm role' }))
    const them = await screen.findByRole('dialog', { name: 'Thêm role' })
    // `vuong_mien` đã có người dùng ⇒ gợi ý hình kế tiếp.
    expect(within(them).getByRole('radio', { name: 'Nhà đầu tư' })).toHaveAttribute(
      'aria-checked',
      'true',
    )
    await userEvent.click(within(them).getByRole('button', { name: 'Huỷ' }))

    await userEvent.click(screen.getByRole('tab', { name: 'VIP' }))
    await userEvent.click(screen.getByRole('button', { name: 'Sửa role VIP' }))
    const sua = await screen.findByRole('dialog', { name: 'Sửa VIP' })
    await userEvent.click(within(sua).getByRole('radio', { name: 'Cao cấp' }))
    await userEvent.click(within(sua).getByRole('button', { name: 'Lưu' }))

    await waitFor(() =>
      expect(goi).toContainEqual({ method: 'PATCH', key: 'vip', body: { icon: 'cao_cap' } }),
    )
  })
})
