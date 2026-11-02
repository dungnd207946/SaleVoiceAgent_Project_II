import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
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
import {
  ProjectConflictButton,
  WorkspaceConflictButton,
} from '../src/features/conflicts/ConflictEntry'
import type { Conflict } from '../src/features/conflicts/api'

const MOI: Conflict = {
  id: 7,
  summary: 'Chủ đầu tư khác nhau',
  createdAt: '2026-10-14T03:00:00Z',
  left: {
    entity: 'documents',
    recordId: 7,
    field: null,
    label: 'Brochure.pdf',
    quote: 'Bách Giang',
  },
  right: {
    entity: 'projects',
    recordId: 9,
    field: 'investor',
    label: 'Chủ đầu tư',
    quote: 'Noble',
  },
}

function boot(ui: React.ReactNode) {
  const root = createRootRoute()
  const home = createRoute({ getParentRoute: () => root, path: '/', component: () => <>{ui}</> })
  const router = createRouter({
    routeTree: root.addChildren([home]),
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
}

afterEach(() => vi.useRealTimers())

describe('nút mâu thuẫn ở màn Kiến thức', () => {
  it('hiện tổng số cảnh báo của workspace và mở popup', async () => {
    server.use(
      http.get('/api/v1/conflicts/summary', () =>
        HttpResponse.json([
          { projectCode: 'nplb', name: 'NPLB', open: 3, checking: false, failed: false },
          { projectCode: 'slc', name: 'SLC', open: 1, checking: false, failed: false },
        ]),
      ),
    )
    boot(<WorkspaceConflictButton />)
    const nut = await screen.findByRole('button', { name: 'Mâu thuẫn dữ liệu: 4' })
    await userEvent.click(nut)
    expect(await screen.findByRole('heading', { name: /Mâu thuẫn dữ liệu/ })).toBeInTheDocument()
  })
})

describe('nút mâu thuẫn ở màn dự án', () => {
  it('đang có job thì hiện trạng thái đang kiểm tra', async () => {
    server.use(
      http.get('/api/v1/conflicts/summary', () => HttpResponse.json([])),
      http.get('/api/v1/projects/nplb/conflicts/check', () =>
        HttpResponse.json({ checking: true, failed: false, conflicts: [] }),
      ),
    )
    boot(<ProjectConflictButton code="nplb" name="NPLB" />)
    expect(
      await screen.findByRole('button', { name: 'Mâu thuẫn dữ liệu — đang kiểm tra' }),
    ).toBeInTheDocument()
  })

  it('có mâu thuẫn mới thì tự bật popup, không có thì không bật', async () => {
    let tra: Conflict[] = []
    const moc: string[] = []
    server.use(
      http.get('/api/v1/conflicts/summary', () => HttpResponse.json([])),
      http.get('/api/v1/projects/nplb/conflicts/check', ({ request }) => {
        moc.push(new URL(request.url).searchParams.get('since') ?? '')
        return HttpResponse.json({ checking: tra.length === 0, failed: false, conflicts: tra })
      }),
    )
    vi.useFakeTimers({ shouldAdvanceTime: true })
    boot(<ProjectConflictButton code="nplb" name="NPLB" />)
    await screen.findByRole('button', { name: /Mâu thuẫn dữ liệu/ })
    expect(screen.queryByText('Có 1 mâu thuẫn mới')).not.toBeInTheDocument()
    tra = [MOI]
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3_500)
    })
    expect(await screen.findByText('Có 1 mâu thuẫn mới')).toBeInTheDocument()
    expect(moc.length).toBeGreaterThanOrEqual(2)
  })
})

describe('tooltip của nút mâu thuẫn', () => {
  it('nói icon dùng để làm gì, theo trạng thái', async () => {
    server.use(
      http.get('/api/v1/conflicts/summary', () =>
        HttpResponse.json([
          { projectCode: 'nplb', name: 'NPLB', open: 3, checking: false, failed: false },
        ]),
      ),
    )
    boot(<WorkspaceConflictButton />)
    const nut = await screen.findByRole('button', { name: 'Mâu thuẫn dữ liệu: 3' })
    expect(nut).toHaveAccessibleDescription(
      'Mâu thuẫn dữ liệu Có 3 chỗ tài liệu và thông tin đã điền ghi khác nhau. Bấm để xem.',
    )
  })
})
