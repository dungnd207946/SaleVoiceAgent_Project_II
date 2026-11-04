import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import { server } from '../vitest.setup'
import { ConflictDialog, type ConflictDialogMode } from '../src/features/conflicts/ConflictDialog'
import type { Conflict } from '../src/features/conflicts/api'

const CHU_DAU_TU: Conflict = {
  id: 41,
  summary: 'Chủ đầu tư khác nhau',
  createdAt: '2026-10-14T02:00:00Z',
  left: {
    entity: 'documents',
    recordId: 7,
    field: null,
    label: 'Brochure.pdf',
    quote: 'Công ty CP Bách Giang',
  },
  right: {
    entity: 'projects',
    recordId: 9,
    field: 'investor',
    label: 'Chủ đầu tư',
    quote: 'Noble',
  },
}
const CSBH: Conflict = {
  ...CHU_DAU_TU,
  id: 42,
  summary: 'Hai CSBH khác thời hạn',
  right: {
    entity: 'documents',
    recordId: 8,
    field: null,
    label: 'CSBH số 617',
    quote: 'đến hết 31/12/2026',
  },
}

function boot(mode: ConflictDialogMode, onClose = vi.fn()) {
  const root = createRootRoute()
  const home = createRoute({
    getParentRoute: () => root,
    path: '/',
    component: () => <ConflictDialog mode={mode} onClose={onClose} />,
  })
  const pform = createRoute({
    getParentRoute: () => root,
    path: '/pform',
    validateSearch: (s: Record<string, unknown>) => s as { code?: string; tab?: string },
    component: () => <p>màn dự án</p>,
  })
  const router = createRouter({
    routeTree: root.addChildren([home, pform]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return { router, onClose }
}

function workspaceApi() {
  server.use(
    http.get('/api/v1/conflicts/summary', () =>
      HttpResponse.json([
        {
          projectCode: 'nplb',
          name: 'NOBLE PALACE LONG BIÊN',
          open: 2,
          checking: false,
          failed: false,
          checkedAt: '2026-10-14T02:00:00Z',
        },
        {
          projectCode: 'slc',
          name: 'SUNSHINE LEGEND CITY',
          open: 1,
          checking: true,
          failed: false,
          checkedAt: '2026-10-14T02:00:00Z',
        },
        {
          projectCode: 'alluvia',
          name: 'ALLUVIA CITY',
          open: 0,
          checking: false,
          failed: false,
          checkedAt: '2026-10-08T09:05:00Z',
        },
        {
          projectCode: 'moi',
          name: 'DỰ ÁN MỚI',
          open: 0,
          checking: false,
          failed: false,
          checkedAt: null,
        },
        {
          projectCode: 'hong',
          name: 'DỰ ÁN HỎNG',
          open: 0,
          checking: false,
          failed: true,
          checkedAt: '2026-10-14T02:00:00Z',
        },
      ]),
    ),
    http.get('/api/v1/projects/nplb/conflicts', () => HttpResponse.json([CHU_DAU_TU, CSBH])),
  )
}

describe('popup mâu thuẫn — cả workspace', () => {
  it('mỗi dự án một hàng, mặc định thu gọn, bấm thì hiện mục', async () => {
    workspaceApi()
    boot({ kind: 'workspace' })
    const hang = await screen.findByRole('button', { name: /NOBLE PALACE LONG BIÊN/ })
    expect(hang).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText('Chủ đầu tư khác nhau')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Đang kiểm tra')
    await userEvent.click(hang)
    expect(await screen.findByText('Chủ đầu tư khác nhau')).toBeInTheDocument()
    expect(hang).toHaveAttribute('aria-expanded', 'true')
  })

  it('ba nhóm theo thứ tự, chỉ nhóm có mâu thuẫn mở sẵn', async () => {
    workspaceApi()
    boot({ kind: 'workspace' })
    const coMauThuan = await screen.findByRole('button', { name: /^Có mâu thuẫn \d/ })
    const nhom = screen.getAllByRole('button', {
      name: /^(Có mâu thuẫn|Chưa kiểm tra|Không mâu thuẫn) \d/,
    })
    expect(nhom.map((n) => n.textContent)).toEqual([
      '›Có mâu thuẫn2',
      '›Chưa kiểm tra2',
      '›Không mâu thuẫn1',
    ])
    expect(coMauThuan).toHaveAttribute('aria-expanded', 'true')
    expect(screen.queryByText('DỰ ÁN MỚI')).not.toBeInTheDocument()
    await userEvent.click(nhom[1]!)
    expect(screen.getByText('DỰ ÁN MỚI')).toBeInTheDocument()
    expect(screen.getByText('Lần kiểm tra trước bị lỗi')).toBeInTheDocument()
    await userEvent.click(nhom[2]!)
    expect(screen.getByText('ALLUVIA CITY')).toBeInTheDocument()
    expect(screen.getByText(/^Kiểm tra lần cuối 08\/10 \d\d:\d\d$/)).toBeInTheDocument()
  })

  it('«Kiểm tra tất cả dự án» hỏi xác nhận rồi mới gọi API', async () => {
    workspaceApi()
    const goi = vi.fn()
    server.use(
      http.post(
        '/api/v1/conflicts/scan',
        () => (goi(), HttpResponse.json({ queued: 2 }, { status: 202 })),
      ),
    )
    boot({ kind: 'workspace' })
    await userEvent.click(await screen.findByRole('button', { name: 'Kiểm tra tất cả dự án' }))
    expect(goi).not.toHaveBeenCalled()
    const hoi = await screen.findByRole('dialog', { name: 'Kiểm tra mâu thuẫn của mọi dự án?' })
    await userEvent.click(within(hoi).getByRole('button', { name: 'Kiểm tra' }))
    await vi.waitFor(() => expect(goi).toHaveBeenCalledTimes(1))
  })
})

describe('popup mâu thuẫn — một dự án', () => {
  it('«Không phải mâu thuẫn» gọi đúng id và mục biến mất', async () => {
    let con = [CHU_DAU_TU, CSBH]
    const bo = vi.fn()
    server.use(
      http.get('/api/v1/conflicts/summary', () => HttpResponse.json([])),
      http.get('/api/v1/projects/nplb/conflicts', () => HttpResponse.json(con)),
      http.post('/api/v1/conflicts/:id/dismiss', ({ params }) => {
        bo(Number(params.id))
        con = con.filter((c) => c.id !== Number(params.id))
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot({ kind: 'project', code: 'nplb', name: 'NOBLE PALACE LONG BIÊN' })
    expect(await screen.findByText('Chủ đầu tư khác nhau')).toBeInTheDocument()
    await userEvent.click(screen.getAllByRole('button', { name: 'Không phải mâu thuẫn' })[0]!)
    await vi.waitFor(() => expect(bo).toHaveBeenCalledWith(41))
    await vi.waitFor(() =>
      expect(screen.queryByText('Chủ đầu tư khác nhau')).not.toBeInTheDocument(),
    )
    expect(screen.getByText('Hai CSBH khác thời hạn')).toBeInTheDocument()
  })
})

describe('popup mâu thuẫn — lần kiểm tra cuối', () => {
  afterEach(() => vi.useRealTimers())

  function projectApi(row: object, items: Conflict[] = []) {
    server.use(
      http.get('/api/v1/conflicts/summary', () =>
        HttpResponse.json([{ projectCode: 'nplb', name: 'NPLB', open: items.length, ...row }]),
      ),
      http.get('/api/v1/projects/nplb/conflicts', () => HttpResponse.json(items)),
    )
  }

  it('ghi giờ và kết quả lần cuối', async () => {
    projectApi({ checking: false, failed: false, checkedAt: new Date().toISOString() }, [CSBH])
    boot({ kind: 'project', code: 'nplb', name: 'NPLB' })
    expect(
      await screen.findByText(/^Kiểm tra lần cuối \d\d:\d\d hôm nay · 1 mâu thuẫn$/),
    ).toBeInTheDocument()
  })

  it('chưa kiểm tra lần nào', async () => {
    projectApi({ checking: false, failed: false, checkedAt: null })
    boot({ kind: 'project', code: 'nplb', name: 'NPLB' })
    expect(await screen.findByText('Chưa kiểm tra lần nào')).toBeInTheDocument()
  })

  it('lần cuối bị lỗi', async () => {
    projectApi({ checking: false, failed: true, checkedAt: new Date().toISOString() })
    boot({ kind: 'project', code: 'nplb', name: 'NPLB' })
    expect(
      await screen.findByText(/^Lần kiểm tra lúc \d\d:\d\d hôm nay bị lỗi$/),
    ).toBeInTheDocument()
  })

  it('đang chạy thì hiện chip, chạy xong tự tải lại danh sách', async () => {
    let checking = true
    let items: Conflict[] = []
    server.use(
      http.get('/api/v1/conflicts/summary', () =>
        HttpResponse.json([
          {
            projectCode: 'nplb',
            name: 'NPLB',
            open: items.length,
            checking,
            failed: false,
            checkedAt: null,
          },
        ]),
      ),
      http.get('/api/v1/projects/nplb/conflicts', () => HttpResponse.json(items)),
    )
    vi.useFakeTimers({ shouldAdvanceTime: true })
    boot({ kind: 'project', code: 'nplb', name: 'NPLB' })
    expect(await screen.findByRole('status')).toHaveTextContent('Đang kiểm tra')
    expect(screen.queryByRole('button', { name: 'Kiểm tra' })).not.toBeInTheDocument()
    checking = false
    items = [CHU_DAU_TU]
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_500)
    })
    expect(await screen.findByText('Chủ đầu tư khác nhau')).toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Kiểm tra' })).toBeInTheDocument()
  })
})

describe('popup mâu thuẫn — sau khi lưu', () => {
  it('«Mở» đóng popup và tới đúng tab của nguồn', async () => {
    const { router, onClose } = boot({ kind: 'afterSave', code: 'nplb', conflicts: [CHU_DAU_TU] })
    expect(await screen.findByText('Có 1 mâu thuẫn mới')).toBeInTheDocument()
    expect(screen.getByText('Trường «Chủ đầu tư» của dự án')).toBeInTheDocument()
    const mo = screen.getAllByRole('button', { name: 'Mở' })
    await userEvent.click(mo[1]!)
    expect(onClose).toHaveBeenCalled()
    await vi.waitFor(() =>
      expect(router.state.location.search).toEqual({ code: 'nplb', tab: 'tong-quan' }),
    )
  })

  it('nguồn tài liệu dẫn tới tab Tài liệu', async () => {
    const { router } = boot({ kind: 'afterSave', code: 'nplb', conflicts: [CHU_DAU_TU] })
    await userEvent.click((await screen.findAllByRole('button', { name: 'Mở' }))[0]!)
    await vi.waitFor(() =>
      expect(router.state.location.search).toEqual({ code: 'nplb', tab: 'tai-lieu' }),
    )
  })
})
