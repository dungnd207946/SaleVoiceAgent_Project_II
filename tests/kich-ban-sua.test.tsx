import { StrictMode } from 'react'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createBrowserHistory,
  createMemoryHistory,
  createRouter,
} from '@tanstack/react-router'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { server } from '../vitest.setup'
import { routeTree } from '../src/routeTree.gen'
import { LangProvider } from '../src/i18n'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import type { NutVao } from '../src/features/kich-ban/api'
import {
  FAKE_KICH_BAN,
  GHI_GIA,
  MAU_GIA,
  datLaiKichBanGia,
  epLoiGhiKichBanGia,
} from '../src/features/kich-ban/msw'

/** `trinhDuyet`: history THẬT của jsdom — Back đi qua `popstate`, đường duy nhất router xét blocker khi lùi
 *  (memory history lùi thẳng, không hỏi ai). */
function boot(path = '/kich-ban', trinhDuyet = false) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  if (trinhDuyet) window.history.replaceState(null, '', path)
  const router = createRouter({
    routeTree,
    history: trinhDuyet ? createBrowserHistory() : createMemoryHistory({ initialEntries: [path] }),
  })
  render(
    <StrictMode>
      <QueryClientProvider client={qc}>
        <LangProvider>
          <RouterProvider router={router} />
        </LangProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
  return router
}

/** Phiên KHÔNG có `agent_config.write`. */
const chiXem = () =>
  server.use(
    http.get('/api/v1/me', () =>
      HttpResponse.json({
        ...FAKE_SESSION,
        actions: FAKE_SESSION.actions.filter((a) => a !== 'agent_config.write'),
      }),
    ),
  )

/** Bộ mẫu với một tình huống đổi. */
const sua = (id: string, doi: Partial<NutVao>) =>
  MAU_GIA.map((n) => (n.id === id ? { ...n, ...doi } : n))

/** Bấm một nút khi nó đã MỞ (nút ghi khoá tới lúc `gioiHan` về). */
async function bam(name: string) {
  const b = await screen.findByRole('button', { name })
  await waitFor(() => expect(b).toBeEnabled())
  await userEvent.click(b)
}

beforeEach(() => datLaiKichBanGia())

describe('dải trạng thái + công tắc role', () => {
  it('chưa áp dụng: nói đang dùng mẫu; Khách hàng bật, Sale tắt; không Áp lại', async () => {
    boot()
    const dai = await screen.findByTestId('dai-trang-thai')
    expect(within(dai).getByText(/Đang dùng kịch bản mẫu NobleX/)).toBeInTheDocument()
    expect(within(dai).getByText(/Sửa một tình huống bất kỳ sẽ tạo bản riêng/)).toBeInTheDocument()
    expect(
      await within(dai).findByRole('switch', { name: 'Dùng kịch bản với Khách hàng' }),
    ).toBeChecked()
    expect(within(dai).getByRole('switch', { name: 'Dùng kịch bản với Sale' })).not.toBeChecked()
    expect(within(dai).queryByRole('button', { name: /Áp lại/ })).toBeNull()
  })

  it('bật Sale gửi PUT /role-dung đủ tập, rồi công tắc bật', async () => {
    boot()
    await userEvent.click(await screen.findByRole('switch', { name: 'Dùng kịch bản với Sale' }))
    await waitFor(() =>
      expect(GHI_GIA).toEqual([
        { duong: 'PUT /playbook/role-dung', body: { version: 0, roles: ['customer', 'sale'] } },
      ]),
    )
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Dùng kịch bản với Sale' })).toBeChecked(),
    )
  })

  it('role đã xoá ở /agent không bị gửi lại', async () => {
    datLaiKichBanGia({ roleDung: ['customer', 'role_da_xoa'] })
    boot()
    await userEvent.click(await screen.findByRole('switch', { name: 'Dùng kịch bản với Sale' }))
    await waitFor(() =>
      expect(GHI_GIA[0]?.body).toEqual({ version: 0, roles: ['customer', 'sale'] }),
    )
  })

  it('người chỉ xem: công tắc khoá, không Áp lại', async () => {
    chiXem()
    datLaiKichBanGia({ nut: MAU_GIA, tuTemplate: 'tv-mau-1', version: 1 })
    boot()
    expect(await screen.findByRole('switch', { name: 'Dùng kịch bản với Sale' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Áp lại/ })).toBeNull()
    // So với mẫu là ĐỌC — người chỉ xem vẫn mở được (nút «Thêm vào» trong đó mới cần quyền ghi).
    expect(screen.getByRole('button', { name: /So với mẫu/ })).toBeInTheDocument()
  })

  it('bản riêng có mẫu mới: báo, đếm, và Áp lại nói rõ mất gì', async () => {
    const rieng = { ...MAU_GIA[2]!, id: 'rieng_mau_son', ten: 'Chê màu sơn', lan_2: '' }
    datLaiKichBanGia({
      nut: [...sua('chot', { lam: ['chữ riêng'] }).filter((n) => n.id !== 'goi_dien_ra'), rieng],
      tuTemplate: 'tv-cu',
      version: 4,
    })
    boot()
    expect(await screen.findByText('NobleX có bản mẫu mới.')).toBeInTheDocument()
    expect(
      await screen.findByRole('button', { name: 'So với mẫu (1 khác · 1 chưa có)' }),
    ).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Áp lại mẫu NobleX' }))
    const hop = await screen.findByRole('dialog', { name: 'Áp lại mẫu NobleX?' })
    expect(hop).toHaveTextContent(
      '1 tình huống khác mẫu trở về bản mẫu · 1 tình huống riêng bị xoá · 1 tình huống trong mẫu được thêm.',
    )
    await userEvent.click(within(hop).getByRole('button', { name: 'Áp lại' }))
    await waitFor(() =>
      expect(GHI_GIA).toEqual([{ duong: 'POST /playbook/ap-dung', body: { version: 4 } }]),
    )
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    expect(await screen.findByText(/Bản riêng của workspace/)).toBeInTheDocument()
  })
})

describe('thao tác trên một tình huống', () => {
  it('tình huống hệ thống: chip chỉ xem, không nút ghi', async () => {
    boot('/kich-ban?nut=chuyen_that')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByText('Hệ thống NobleX — chỉ xem')).toBeInTheDocument()
    await screen.findByTestId('dai-trang-thai')
    expect(within(b).queryByRole('switch', { name: 'Đang dùng' })).toBeNull()
    expect(within(b).queryByRole('button', { name: 'Xoá' })).toBeNull()
  })

  it('bật một tình huống đang tắt: PUT cả bộ sale, chỉ nó đổi, không lẫn trường tương thích', async () => {
    boot('/kich-ban?nut=goi_dien_ra')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByText('Đang tắt — agent không chọn')).toBeInTheDocument()
    await userEvent.click(await within(b).findByRole('switch', { name: 'Đang dùng' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect(GHI_GIA[0]!.body).toEqual({
      version: 0,
      nut: MAU_GIA.map((n) => (n.id === 'goi_dien_ra' ? { ...n, bat: true } : n)),
    })
  })

  it('hai cú bấm liền nhau không gửi version cũ (Review Focus 1)', async () => {
    boot('/kich-ban?nut=goi_dien_ra')
    const sw = await screen.findByRole('switch', { name: 'Đang dùng' })
    await userEvent.click(sw)
    await userEvent.click(sw)
    await waitFor(() =>
      expect(screen.getByRole('switch', { name: 'Đang dùng' })).not.toBeDisabled(),
    )
    expect(screen.queryByRole('alert')).toBeNull()
    expect(GHI_GIA.map((g) => (g.body as { version: number }).version)).toEqual(
      GHI_GIA.map((_, i) => i),
    )
  })

  it('tình huống khoá xoá: có công tắc, không có Xoá', async () => {
    boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    await within(b).findByRole('switch', { name: 'Đang dùng' })
    expect(within(b).queryByRole('button', { name: 'Xoá' })).toBeNull()
  })

  it('xoá: hỏi lại, PUT thiếu đúng tình huống đó, khung đóng (Review Focus 5)', async () => {
    const router = boot('/kich-ban?nut=chot')
    await bam('Xoá')
    const hop = await screen.findByRole('dialog', { name: 'Xoá «Chốt căn»?' })
    await userEvent.click(within(hop).getByRole('button', { name: 'Xoá' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect((GHI_GIA[0]!.body as { nut: { id: string }[] }).nut.map((n) => n.id)).toEqual([
      'che_dat',
      'che_dat_downsell',
      'goi_dien_ra',
    ])
    await waitFor(() => expect(router.state.location.search).not.toHaveProperty('nut'))
  })

  it('xoá bị chặn khi tình huống khác chuyển sang nó — bấm lý do mở tình huống kia', async () => {
    datLaiKichBanGia({
      nut: [...MAU_GIA, { ...MAU_GIA[2]!, id: 'rieng_hoi_lai', ten: 'Hỏi lại', lan_2: 'chot' }],
      tuTemplate: 'tv-mau-1',
      version: 1,
    })
    const router = boot('/kich-ban?nut=chot')
    await bam('Xoá')
    const hop = await screen.findByRole('dialog', { name: 'Chưa xoá được «Chốt căn»' })
    expect(within(hop).queryByRole('button', { name: 'Xoá' })).toBeNull()
    await userEvent.click(
      within(hop).getByRole('button', { name: /«Hỏi lại» chuyển sang tình huống này/ }),
    )
    await waitFor(() =>
      expect(router.state.location.search).toMatchObject({ nut: 'rieng_hoi_lai' }),
    )
    expect(GHI_GIA).toEqual([])
  })

  it('khác mẫu: xem hai bản, dùng bản mẫu', async () => {
    datLaiKichBanGia({
      nut: sua('chot', { lam: ['chữ riêng của sàn'] }),
      tuTemplate: 'tv-mau-1',
      version: 2,
    })
    boot('/kich-ban?nut=chot')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(await within(b).findByText('Khác mẫu')).toBeInTheDocument()
    await userEvent.click(within(b).getByRole('button', { name: 'Xem bản mẫu' }))
    const hai = within(b).getByTestId('so-hai-ban')
    expect(hai).toHaveTextContent('chữ riêng của sàn')
    expect(hai).toHaveTextContent(MAU_GIA[2]!.lam[0]!)
    await userEvent.click(within(b).getByRole('button', { name: 'Dùng bản mẫu' }))
    const hop = await screen.findByRole('dialog', { name: 'Thay «Chốt căn» bằng bản mẫu?' })
    await userEvent.click(within(hop).getByRole('button', { name: 'Dùng bản mẫu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect(GHI_GIA[0]!.body).toEqual({ version: 2, nut: MAU_GIA })
    expect(await within(b).findByText('Giống mẫu')).toBeInTheDocument()
  })

  it('409: báo câu của BE', async () => {
    epLoiGhiKichBanGia(409, {
      error: {
        code: 'PLAYBOOK_DA_DOI',
        message: 'Kịch bản vừa thay đổi ở nơi khác — tải lại rồi lưu lại',
      },
    })
    boot('/kich-ban?nut=goi_dien_ra')
    await userEvent.click(await screen.findByRole('switch', { name: 'Đang dùng' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Kịch bản vừa thay đổi ở nơi khác')
  })

  it('người chỉ xem: không công tắc, không Xoá', async () => {
    chiXem()
    boot('/kich-ban?nut=chot')
    const b = await screen.findByTestId('bang-chi-tiet')
    await screen.findByTestId('dai-trang-thai')
    expect(within(b).queryByRole('switch')).toBeNull()
    expect(within(b).queryByRole('button', { name: 'Xoá' })).toBeNull()
    expect(within(b).queryByRole('button', { name: 'Sửa' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Thêm tình huống' })).toBeNull()
  })
})

describe('form sửa / thêm tình huống', () => {
  it('Sửa: lưu PUT cả bộ với đúng tình huống đó đổi, rồi về bản xem', async () => {
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    const o = within(f).getByLabelText('Agent làm gì — ý 1')
    await userEvent.clear(o)
    await userEvent.type(o, 'chốt bằng một câu hỏi có hoặc không')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect(GHI_GIA[0]!.body).toEqual({
      version: 0,
      nut: sua('chot', { lam: ['chốt bằng một câu hỏi có hoặc không'] }),
    })
    await waitFor(() => expect(screen.queryByTestId('form-nut')).toBeNull())
    expect(
      within(await screen.findByTestId('bang-chi-tiet')).getByText(
        'chốt bằng một câu hỏi có hoặc không',
      ),
    ).toBeInTheDocument()
  })

  it('trạng thái mẫu: form báo lần lưu đầu tạo bản riêng', async () => {
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    expect(await screen.findByText(/Lần lưu này tạo bản riêng cho workspace/)).toBeInTheDocument()
  })

  it('409: giữ chữ đang gõ, cảnh báo chính tình huống này vừa đổi, lần Lưu sau cầm version mới', async () => {
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    const o = within(f).getByLabelText('Agent làm gì — ý 1')
    await userEvent.clear(o)
    await userEvent.type(o, 'bản của tôi')
    // Người khác lưu xen vào: đổi chính tình huống này, version lên 3.
    datLaiKichBanGia({
      nut: sua('chot', { lam: ['bản của người khác'] }),
      tuTemplate: 'tv-mau-1',
      version: 3,
    })
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    expect(await within(f).findByText(/Kịch bản vừa thay đổi ở nơi khác/)).toBeInTheDocument()
    expect(within(f).getByLabelText('Agent làm gì — ý 1')).toHaveValue('bản của tôi')
    expect(await within(f).findByText(/cũng vừa được sửa ở nơi khác/)).toBeInTheDocument()
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(2))
    expect(GHI_GIA.map((g) => (g.body as { version: number }).version)).toEqual([0, 3])
  })

  it('422 trên tình huống đang sửa: lỗi hiện dưới đúng ô', async () => {
    epLoiGhiKichBanGia(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Dữ liệu gửi lên không hợp lệ (1 lỗi): body.nut[2].lam',
        fields: [{ field: 'body.nut[2].lam', reason: 'mỗi dòng tối đa 200 ký tự' }],
      },
    })
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    // Phải đổi một chữ: Lưu khi không đổi gì thì không gửi (bài «Lưu khi chưa đổi gì»).
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), ' x')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    expect(await within(f).findByText('mỗi dòng tối đa 200 ký tự')).toBeInTheDocument()
  })

  it('Thêm: id rieng_ sinh từ tên, màn mở tình huống mới', async () => {
    const router = boot()
    await bam('Thêm tình huống')
    const f = await screen.findByTestId('form-nut')
    await userEvent.type(within(f).getByLabelText(/Tên tình huống/), 'Chê màu sơn')
    await userEvent.selectOptions(within(f).getByLabelText(/^Nhóm/), 'phan_doi')
    await userEvent.type(within(f).getByLabelText('Khi nào dùng — ý 1'), 'khách chê màu sơn')
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), 'gửi ảnh mẫu màu thật')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect((GHI_GIA[0]!.body as { nut: NutVao[] }).nut.at(-1)).toEqual({
      id: 'rieng_che_mau_son',
      ten: 'Chê màu sơn',
      nhom: 'phan_doi',
      bat: true,
      kenh: [],
      dau_hieu: ['khách chê màu sơn'],
      lam: ['gửi ảnh mẫu màu thật'],
      tool: [],
      cam: [],
      khi_thieu: '',
      cau_ket: '',
      lan_2: '',
      chi_lan_2: false,
      nguon: '',
      buoc: [],
    })
    await waitFor(() =>
      expect(router.state.location.search).toMatchObject({ nut: 'rieng_che_mau_son' }),
    )
  })

  it('Thêm mà để trống: báo lỗi tại chỗ, không gửi gì', async () => {
    boot()
    await bam('Thêm tình huống')
    const f = await screen.findByTestId('form-nut')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    expect(await within(f).findByText('Chưa có tên tình huống')).toBeInTheDocument()
    expect(within(f).getByText('Chọn một nhóm')).toBeInTheDocument()
    expect(GHI_GIA).toEqual([])
  })

  it('sửa dở rồi chọn tình huống khác: hỏi trước; Ở lại giữ form, Bỏ thì đi', async () => {
    const router = boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), ' thêm')
    fireEvent.click(screen.getByTestId('nut-che_dat'))
    const hop = await screen.findByRole('dialog', { name: 'Bỏ phần đang sửa?' })
    await userEvent.click(within(hop).getByRole('button', { name: 'Ở lại' }))
    expect(router.state.location.search).toMatchObject({ nut: 'chot' })
    expect(screen.getByTestId('form-nut')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('nut-che_dat'))
    const hop2 = await screen.findByRole('dialog', { name: 'Bỏ phần đang sửa?' })
    await userEvent.click(within(hop2).getByRole('button', { name: 'Bỏ' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ nut: 'che_dat' }))
    expect(screen.queryByTestId('form-nut')).toBeNull()
  })

  it('tool agent đã gỡ không theo nút vào payload (Review Focus 4)', async () => {
    server.use(
      http.get('/api/v1/playbook', () =>
        HttpResponse.json({
          ...FAKE_KICH_BAN,
          nodes: FAKE_KICH_BAN.nodes.map((n) =>
            n.id === 'chot' ? { ...n, tool: [...n.tool, 'tool_da_go'] } : n,
          ),
        }),
      ),
    )
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    await userEvent.click(
      within(await screen.findByTestId('form-nut')).getByRole('button', { name: 'Lưu' }),
    )
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    const chot = (GHI_GIA[0]!.body as { nut: NutVao[] }).nut.find((n) => n.id === 'chot')!
    expect(chot.tool).not.toContain('tool_da_go')
  })

  it('không tải được giới hạn: nút ghi khoá kèm lý do, phần xem vẫn chạy', async () => {
    server.use(
      http.get('/api/v1/playbook/template', () =>
        HttpResponse.json({ error: { code: 'X', message: 'hỏng' } }, { status: 500 }),
      ),
    )
    boot('/kich-ban?nut=chot')
    const them = await screen.findByRole('button', { name: 'Thêm tình huống' })
    await waitFor(() =>
      expect(them).toHaveAttribute('title', 'Không tải được giới hạn kịch bản — tải lại trang'),
    )
    expect(them).toBeDisabled()
    expect(await screen.findByRole('button', { name: 'Sửa' })).toBeDisabled()
    expect(within(screen.getByTestId('bang-chi-tiet')).getByText('Chốt căn')).toBeInTheDocument()
  })

  it('bản xem cùng nhãn với form', async () => {
    boot('/kich-ban?nut=che_dat')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByText('Kỹ năng nên dùng')).toBeInTheDocument()
    expect(within(b).getByText('Câu kết hỏi khách')).toBeInTheDocument()
    expect(within(b).getByText('Khi khách lặp lại lần 2, chuyển sang')).toBeInTheDocument()
  })
})

describe('so với mẫu', () => {
  const RIENG = { ...MAU_GIA[2]!, id: 'rieng_mau_son', ten: 'Chê màu sơn', lan_2: '' }
  const datRieng = () =>
    datLaiKichBanGia({
      nut: [
        ...sua('che_dat', { cau_ket: 'hỏi khách có muốn xem căn rẻ hơn' }).filter(
          (n) => n.id !== 'chot',
        ),
        RIENG,
      ],
      tuTemplate: 'tv-cu',
      version: 5,
    })

  it('sơ đồ ghi chữ khác mẫu / riêng sau tên', async () => {
    datRieng()
    boot()
    await waitFor(() => expect(screen.getByTestId('nut-che_dat')).toHaveTextContent('· khác mẫu'))
    expect(screen.getByTestId('nut-rieng_mau_son')).toHaveTextContent('· riêng')
    expect(screen.getByTestId('nut-goi_dien_ra')).not.toHaveTextContent('mẫu')
  })

  it('mở So với mẫu: ba nhóm; bấm một tình huống thì mở nó', async () => {
    datRieng()
    const router = boot()
    await userEvent.click(
      await screen.findByRole('button', { name: 'So với mẫu (1 khác · 1 chưa có)' }),
    )
    const p = await screen.findByTestId('so-voi-mau')
    expect(within(p).getByTestId('nhom-khac')).toHaveTextContent('Khách chê đắt')
    expect(within(p).getByTestId('nhom-chua-co')).toHaveTextContent('Chốt căn')
    expect(within(p).getByTestId('nhom-rieng')).toHaveTextContent('Chê màu sơn')
    await userEvent.click(within(p).getByRole('button', { name: 'Khách chê đắt' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ nut: 'che_dat' }))
    expect(router.state.location.search).not.toHaveProperty('so')
  })

  it('Thêm vào: gửi nút mẫu giữ nguyên id', async () => {
    datRieng()
    boot('/kich-ban?so=mau')
    await bam('Thêm «Chốt căn» vào bản của bạn')
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect((GHI_GIA[0]!.body as { nut: NutVao[] }).nut.at(-1)).toEqual(MAU_GIA[2])
  })

  it('Thêm vào một cặp chuyển sang nhau: thêm cả hai trong một lần ghi', async () => {
    datLaiKichBanGia({
      nut: MAU_GIA.filter((n) => n.id !== 'che_dat' && n.id !== 'che_dat_downsell'),
      tuTemplate: 'tv-mau-1',
      version: 3,
    })
    boot('/kich-ban?so=mau')
    expect(await screen.findByText('Thêm cùng «Chê đắt lần hai»')).toBeInTheDocument()
    await bam('Thêm «Khách chê đắt» cùng «Chê đắt lần hai» vào bản của bạn')
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect((GHI_GIA[0]!.body as { nut: NutVao[] }).nut.slice(-2)).toEqual([MAU_GIA[0], MAU_GIA[1]])
  })
})

describe('sau review cả nhánh', () => {
  it('đổi khoảng thời gian khi đang sửa: chữ đang gõ còn nguyên', async () => {
    const router = boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const o = within(await screen.findByTestId('form-nut')).getByLabelText('Agent làm gì — ý 1')
    await userEvent.clear(o)
    await userEvent.type(o, 'CHỮ ĐANG GÕ')
    await userEvent.click(screen.getByRole('button', { name: '30 ngày' }))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ ngay: 30 }))
    await new Promise((r) => setTimeout(r, 50))
    const f = await screen.findByTestId('form-nut')
    expect(within(f).getByLabelText('Agent làm gì — ý 1')).toHaveValue('CHỮ ĐANG GÕ')
  })

  it('khoá ghi DÙNG CHUNG: đang ghi role thì «Đang dùng» cũng khoá — không tự 409 (Review Focus 1)', async () => {
    // GET chậm: cửa sổ giữa lúc ghi xong và lúc màn cầm version mới đủ rộng để bấm control khác.
    server.use(
      http.get('/api/v1/playbook', async () => {
        await delay(300)
      }),
    )
    boot('/kich-ban?nut=goi_dien_ra')
    const dung = await screen.findByRole('switch', { name: 'Đang dùng' })
    await waitFor(() => expect(dung).toBeEnabled())
    await userEvent.click(screen.getByRole('switch', { name: 'Dùng kịch bản với Sale' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(1))
    expect(screen.getByRole('switch', { name: 'Đang dùng' })).toBeDisabled()
    await waitFor(() => expect(screen.getByRole('switch', { name: 'Đang dùng' })).toBeEnabled())
    await userEvent.click(screen.getByRole('switch', { name: 'Đang dùng' }))
    await waitFor(() => expect(GHI_GIA).toHaveLength(2))
    expect(GHI_GIA.map((g) => (g.body as { version: number }).version)).toEqual([0, 1])
  })

  it('Back khi đang sửa dở: hỏi trước; Ở lại giữ form, Bỏ thì về', async () => {
    const router = boot('/kich-ban', true)
    fireEvent.click(await screen.findByTestId('nut-chot'))
    await waitFor(() => expect(router.state.location.search).toMatchObject({ nut: 'chot' }))
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), ' thêm')
    router.history.back()
    const hop = await screen.findByRole('dialog', { name: 'Bỏ phần đang sửa?' })
    await userEvent.click(within(hop).getByRole('button', { name: 'Ở lại' }))
    expect(router.state.location.search).toMatchObject({ nut: 'chot' })
    expect(screen.getByTestId('form-nut')).toBeInTheDocument()
    router.history.back()
    const hop2 = await screen.findByRole('dialog', { name: 'Bỏ phần đang sửa?' })
    await userEvent.click(within(hop2).getByRole('button', { name: 'Bỏ' }))
    await waitFor(() => expect(router.state.location.search).not.toHaveProperty('nut'))
    expect(screen.queryByTestId('form-nut')).toBeNull()
    window.history.replaceState(null, '', '/')
  })

  it('Lưu khi chưa đổi gì: không ghi (không tạo bản riêng), về bản xem', async () => {
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    await userEvent.click(
      within(await screen.findByTestId('form-nut')).getByRole('button', { name: 'Lưu' }),
    )
    await waitFor(() => expect(screen.queryByTestId('form-nut')).toBeNull())
    expect(GHI_GIA).toEqual([])
    expect(screen.getByTestId('dai-trang-thai')).toHaveTextContent('Đang dùng kịch bản mẫu NobleX')
  })
})

describe('quyền và câu lỗi', () => {
  it('người chỉ xem gõ ?them=1: không mở form thêm, không khung trống', async () => {
    chiXem()
    boot('/kich-ban?them=1')
    await screen.findByTestId('dai-trang-thai')
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByTestId('form-nut')).toBeNull()
    expect(screen.queryByText(/không còn trong kịch bản/)).toBeNull()
  })

  it('thiếu gioiHan mà gõ ?them=1: không khung trống «không còn trong kịch bản»', async () => {
    server.use(
      http.get('/api/v1/playbook/template', () =>
        HttpResponse.json({ error: { code: 'X', message: 'hỏng' } }, { status: 500 }),
      ),
    )
    boot('/kich-ban?them=1')
    await screen.findByTestId('dai-trang-thai')
    await new Promise((r) => setTimeout(r, 50))
    expect(screen.queryByText(/không còn trong kịch bản/)).toBeNull()
    expect(screen.queryByTestId('form-nut')).toBeNull()
  })

  it('lỗi gateway (502 không thân JSON): câu chung, không chữ kỹ thuật', async () => {
    epLoiGhiKichBanGia(502, {})
    boot('/kich-ban?nut=goi_dien_ra')
    const sw = await screen.findByRole('switch', { name: 'Đang dùng' })
    await waitFor(() => expect(sw).toBeEnabled())
    await userEvent.click(sw)
    const a = await screen.findByRole('alert')
    expect(a).toHaveTextContent('Chưa lưu được — thử lại.')
    expect(a.textContent).not.toMatch(/PUT|502/)
  })

  it('lỗi Áp lại cũ không đứng mãi sau một lần đổi role thành công', async () => {
    datLaiKichBanGia({ nut: MAU_GIA, tuTemplate: 'tv-mau-1', version: 1 })
    epLoiGhiKichBanGia(500, {})
    boot()
    await bam('Áp lại mẫu NobleX')
    await userEvent.click(
      within(await screen.findByRole('dialog', { name: 'Áp lại mẫu NobleX?' })).getByRole(
        'button',
        {
          name: 'Áp lại',
        },
      ),
    )
    const dai = screen.getByTestId('dai-trang-thai')
    expect(await within(dai).findByRole('alert')).toHaveTextContent('Chưa lưu được — thử lại.')
    await userEvent.click(within(dai).getByRole('switch', { name: 'Dùng kịch bản với Sale' }))
    await waitFor(() => expect(GHI_GIA.at(-1)?.duong).toBe('PUT /playbook/role-dung'))
    await waitFor(() => expect(within(dai).queryByRole('alert')).toBeNull())
  })
})

describe('luồng form', () => {
  afterEach(() => {
    // jsdom không có scrollIntoView — bài cuộn tự gắn bản giả, gỡ lại để bài khác thấy đúng môi trường.
    delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView
  })

  it('đang thêm dở mà bấm «Thêm tình huống» lần nữa → Bỏ: form trống lại', async () => {
    boot()
    await bam('Thêm tình huống')
    const ten = within(await screen.findByTestId('form-nut')).getByLabelText(/Tên tình huống/)
    await userEvent.type(ten, 'Chê màu sơn')
    await userEvent.click(screen.getByRole('button', { name: 'Thêm tình huống' }))
    await userEvent.click(
      within(await screen.findByRole('dialog', { name: 'Bỏ phần đang sửa?' })).getByRole('button', {
        name: 'Bỏ',
      }),
    )
    await waitFor(() =>
      expect(within(screen.getByTestId('form-nut')).getByLabelText(/Tên tình huống/)).toHaveValue(
        '',
      ),
    )
  })

  it('thêm xong, Back không mở lại form thêm rỗng', async () => {
    const router = boot()
    await bam('Thêm tình huống')
    const f = await screen.findByTestId('form-nut')
    await userEvent.type(within(f).getByLabelText(/Tên tình huống/), 'Chê màu sơn')
    await userEvent.selectOptions(within(f).getByLabelText(/^Nhóm/), 'phan_doi')
    await userEvent.type(within(f).getByLabelText('Khi nào dùng — ý 1'), 'khách chê màu sơn')
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), 'gửi ảnh mẫu màu thật')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    await waitFor(() =>
      expect(router.state.location.search).toMatchObject({ nut: 'rieng_che_mau_son' }),
    )
    router.history.back()
    await waitFor(() => expect(router.state.location.search).not.toHaveProperty('nut'))
    expect(router.state.location.search).not.toHaveProperty('them')
    expect(screen.queryByTestId('form-nut')).toBeNull()
  })

  it('lưu xong form dài: đầu khung bị khuất thì cuộn về đầu khung', async () => {
    const cuon = vi.fn()
    Object.defineProperty(Element.prototype, 'scrollIntoView', { value: cuon, configurable: true })
    boot('/kich-ban?nut=chot')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), ' x')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    await waitFor(() => expect(screen.queryByTestId('form-nut')).toBeNull())
    expect(cuon).toHaveBeenCalledWith({ block: 'start' })
  })
})

describe('bản xem khớp form, lỗi nối tới ô', () => {
  it('bản xem nói «Chỉ chat» và «Chỉ dùng khi được chuyển tới» bằng đúng chữ của form', async () => {
    datLaiKichBanGia({ nut: sua('chot', { kenh: ['chat'] }), tuTemplate: 'tv-mau-1', version: 1 })
    boot('/kich-ban?nut=chot')
    expect(
      await within(await screen.findByTestId('bang-chi-tiet')).findByText('Chỉ chat'),
    ).toBeInTheDocument()
    cleanup()
    boot('/kich-ban?nut=che_dat_downsell')
    const b = await screen.findByTestId('bang-chi-tiet')
    expect(within(b).getByText('Chỉ dùng khi được chuyển tới')).toBeInTheDocument()
    expect(within(b).queryByText(/Lần 2 trong phiên/)).toBeNull()
  })

  it('lỗi 422 nối tới đúng ô nhập (aria-invalid + mô tả) — kể cả ô «Chỉ dùng khi được chuyển tới»', async () => {
    epLoiGhiKichBanGia(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'x',
        fields: [
          { field: 'body.nut[1].lam', reason: 'mỗi dòng tối đa 200 ký tự' },
          { field: 'body.nut[1].chi_lan_2', reason: 'không nút nào trỏ lan_2 tới nút này' },
        ],
      },
    })
    boot('/kich-ban?nut=che_dat_downsell')
    await bam('Sửa')
    const f = await screen.findByTestId('form-nut')
    await userEvent.type(within(f).getByLabelText('Agent làm gì — ý 1'), ' x')
    await userEvent.click(within(f).getByRole('button', { name: 'Lưu' }))
    const o = await within(f).findByLabelText('Agent làm gì — ý 1')
    await waitFor(() => expect(o).toHaveAccessibleDescription('mỗi dòng tối đa 200 ký tự'))
    const hop = within(f).getByRole('checkbox', { name: 'Chỉ dùng khi được chuyển tới' })
    expect(hop).toHaveAttribute('aria-invalid', 'true')
    expect(hop).toHaveAccessibleDescription('không nút nào trỏ lan_2 tới nút này')
  })
})
