/**
 * Đổi workspace phải là REQUEST THẬT, và phải BỎ CACHE của workspace cũ.
 *
 * Cảnh báo đã ghi sẵn trong WorkspaceSwitcher.tsx từ M2a-FE: "mọi query đang
 * cache của workspace cũ phải bị bỏ, nếu không người dùng thấy dữ liệu workspace
 * trước trong workspace sau — đúng thứ hợp đồng cách ly tồn tại để chặn."
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { FAKE_CONFIG, FAKE_SESSION } from '../src/lib/msw/handlers'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

function boot(queryClient: QueryClient, duongDan = '/dashboard') {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [duongDan] }),
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

async function moMenuRoiChon(ten: RegExp) {
  // Lọc theo TÊN workspace đang hiện, không theo `{ expanded: false }`: nút nhóm
  // nav ("Lĩnh vực") cũng mang aria-expanded nên phép kia khớp hai nút. Tên cũng
  // nói rõ hơn là đang bấm cái gì.
  await userEvent.click(await screen.findByRole('button', { name: /An Phú Land/ }))
  await userEvent.click(await screen.findByRole('button', { name: ten }))
}

describe('đổi workspace', () => {
  it('gọi POST /api/v1/me/workspace, không chỉ đổi state client', async () => {
    const daGoi = vi.fn()
    server.use(
      http.post('/api/v1/me/workspace', async ({ request }) => {
        const body = (await request.json()) as { workspaceId: string }
        daGoi(body.workspaceId)
        return HttpResponse.json({ ...FAKE_SESSION, currentWorkspaceId: body.workspaceId })
      }),
    )
    boot(new QueryClient({ defaultOptions: { queries: { retry: false } } }))

    await moMenuRoiChon(/Sunrise Land/)

    await vi.waitFor(() => {
      expect(daGoi).toHaveBeenCalledWith('ws_sunrise')
    })
  })

  it('XOÁ cache của workspace cũ, không chỉ đánh dấu stale', async () => {
    /**
     * Đánh dấu stale là chưa đủ: dữ liệu cũ vẫn nằm trong cache và vẫn được trả
     * ngay cho mọi observer trong lúc chờ refetch — đủ để một màn sao nó vào
     * `useState` và chốt luôn bản của workspace cũ. Đo được trên trình duyệt
     * ngày 02/08: đổi sang Sunrise mà 8 ô Agent Studio vẫn là của An Phú.
     */
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    // Một query của module khác, thuộc workspace cũ.
    queryClient.setQueryData(['du-an'], ['Dự án của workspace CŨ'])
    boot(queryClient)

    await moMenuRoiChon(/Sunrise Land/)

    await vi.waitFor(() => {
      expect(queryClient.getQueryData(['du-an'])).toBeUndefined()
    })
  })

  it('màn đang mở nạp lại dữ liệu workspace mới, kể cả dữ liệu đã sao vào state', async () => {
    /**
     * Bỏ cache thôi CHƯA đủ. Màn nào sao dữ liệu server vào `useState` để sửa —
     * Agent Studio sao cả 8 ô — thì query mới về vẫn bị bản sao cũ che, vì route
     * không đổi nên component không dựng lại.
     *
     * Hậu quả không phải "hiển thị sai": bấm Lưu và áp dụng lúc đó là ghi cấu
     * hình của workspace CŨ đè lên workspace MỚI. Đúng thứ hợp đồng cách ly tồn
     * tại để chặn, chỉ là rò ở tầng state của client chứ không ở tầng request.
     */
    let hienTai = 'ws_anphu'
    server.use(
      http.post('/api/v1/me/workspace', async ({ request }) => {
        const { workspaceId } = (await request.json()) as { workspaceId: string }
        hienTai = workspaceId
        return HttpResponse.json({ ...FAKE_SESSION, currentWorkspaceId: workspaceId })
      }),
      http.get('/api/v1/config', () => {
        const cfg = {
          ...FAKE_CONFIG,
          danh_tinh: {
            ...FAKE_CONFIG.danh_tinh,
            ten_agent: hienTai === 'ws_sunrise' ? 'Trợ lý Sunrise' : 'Mai',
          },
        }
        return HttpResponse.json({
          vaiTro: [
            { key: 'customer', ten: 'Khách hàng', macDinh: true, cauHinh: cfg, laMacDinh: false },
          ],
          version: 3,
          soRoleToiDa: 10,
        })
      }),
    )
    boot(new QueryClient({ defaultOptions: { queries: { retry: false } } }), '/agent')

    // Đọc chữ chứ không đọc `value`: từ 2026-08-08 `/agent` mở ra ở chế độ XEM.
    // Bản tóm tắt đọc CÙNG state `form` mà form sửa ghi vào, nên nó vẫn là đúng
    // bản sao `useState` mà bài này canh — chỉ khác chỗ nó hiện ra thành chữ.
    expect(await screen.findByText('Mai')).toBeInTheDocument()

    await moMenuRoiChon(/Sunrise Land/)

    expect(await screen.findByText('Trợ lý Sunrise')).toBeInTheDocument()
    expect(screen.queryByText('Mai')).not.toBeInTheDocument()
  })

  it('KHÔNG bỏ cache của chính phiên — nó vừa được đặt giá trị mới', async () => {
    /**
     * `invalidateQueries` không loại trừ ['session'] thì phiên vừa nhận về bị
     * đánh dấu stale ngay, kéo theo một lượt GET /api/v1/me thừa sau MỖI lần bấm
     * switcher. Không sai kết quả, nhưng là một request mỗi thao tác — và nó che
     * mất việc `setQueryData` ở trên có tác dụng hay không.
     */
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    boot(queryClient)

    await moMenuRoiChon(/Sunrise Land/)

    await vi.waitFor(() => {
      expect(queryClient.getQueryData(['session'])).toBeDefined()
    })
    expect(queryClient.getQueryState(['session'])?.isInvalidated).toBe(false)
  })
})
