/**
 * Màn «Cài đặt workspace» (`/workspace`, mảng Quản trị) — đổi tên và xoá.
 *
 * NĂM ĐIỀU NEO LẠI Ở ĐÂY:
 *
 *   ① **Mã workspace hiện ra, và hiện là CHỈ ĐỌC.** `tenants.id` là khoá cách ly
 *      dùng cho bốn việc (policy RLS · role `agent_<id>` · `tenants/<id>/` trên
 *      kho tệp · collection `kb_<id>`) và nó KHÔNG đổi theo tên. Người dùng đổi
 *      tên rồi gặp mã cũ trong log sẽ tưởng là lỗi — nên màn phải nói trước.
 *
 *   ② **Lưu gọi `PATCH` THẬT.** Không phải đổi state client rồi để switcher tự
 *      trôi. Cùng bất biến `tao-workspace.test.tsx` đã neo cho đường tạo.
 *
 *   ③ **Lỗi 409 hiện TẠI CHỖ và không nuốt chữ người dùng vừa gõ.**
 *
 *   ④ **Nút xoá bị KHOÁ tới khi gõ đúng mã workspace.** Xoá là không hoàn tác;
 *      một `confirm` một-cú-bấm quá rẻ so với hậu quả.
 *
 *   ⑤ **Xoá xong thì RỜI MÀN.** Ở lại `/workspace` là ở lại màn cài đặt của một
 *      workspace vừa biến mất — và mọi request của màn đó sẽ 403.
 *
 * Handler khai bằng `server.use(...)` tại chỗ, KHÔNG thêm vào
 * `lib/msw/handlers.ts` — cùng khuôn `tao-workspace.test.tsx`.
 */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

// `noUncheckedIndexedAccess` bật, nên hai dòng khẳng định dưới đây không phải
// nghi thức chiều lòng `tsc`: chúng biến một giả định về fixture thành thứ nổ ra
// ngay lúc nạp module. Rút `FAKE_SESSION.workspaces` xuống dưới hai phần tử thì
// cả file này báo đúng lý do, thay vì chín bài đỏ với «không tìm thấy phần tử».
const WS = FAKE_SESSION.workspaces[0] // ws_anphu · «An Phú Land» — workspace đang mở
const WS_KHAC = FAKE_SESSION.workspaces[1] // workspace phiên chuyển sang sau khi xoá
if (!WS || !WS_KHAC) throw new Error('FAKE_SESSION phải có ít nhất hai workspace')

function boot() {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/workspace'] }),
  })
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
  return router
}

/** Ô tên — chờ màn dựng xong rồi mới trả về. */
function oTen() {
  return screen.findByLabelText(/Tên workspace/)
}

async function moDialogXoa() {
  await userEvent.click(await screen.findByRole('button', { name: /Xoá workspace này/ }))
  return screen.findByRole('dialog')
}

describe('cài đặt workspace — đổi tên', () => {
  it('① hiện mã workspace và điền sẵn tên đang dùng', async () => {
    boot()

    expect(await oTen()).toHaveValue(WS.name)
    // Mã hiện ra ở đâu đó trên màn, và KHÔNG phải một ô nhập.
    const ma = await screen.findByText(WS.id)
    expect(ma.tagName).not.toBe('INPUT')
  })

  it('② Lưu gọi PATCH /api/v1/workspaces/:id với đúng tên đã gõ', async () => {
    const daGoi = vi.fn()
    server.use(
      http.patch('/api/v1/workspaces/:id', async ({ params, request }) => {
        const body = (await request.json()) as { name: string }
        daGoi(params.id, body)
        return HttpResponse.json({ id: params.id, name: body.name })
      }),
    )
    boot()

    await userEvent.clear(await oTen())
    await userEvent.type(await oTen(), 'An Phú Land 2')
    await userEvent.click(screen.getByRole('button', { name: /^Lưu$/ }))

    await vi.waitFor(() => {
      expect(daGoi).toHaveBeenCalledWith(WS.id, { name: 'An Phú Land 2' })
    })
  })

  it('② lưu xong thì tên mới hiện ở switcher — phiên được nạp lại, không chỉ màn này', async () => {
    const PHIEN_MOI = {
      ...FAKE_SESSION,
      workspaces: [{ ...WS, name: 'An Phú Land 2' }, ...FAKE_SESSION.workspaces.slice(1)],
    }
    let daSua = false
    server.use(
      http.patch('/api/v1/workspaces/:id', async ({ params, request }) => {
        daSua = true
        const body = (await request.json()) as { name: string }
        return HttpResponse.json({ id: params.id, name: body.name })
      }),
      http.get('/api/v1/me', () => HttpResponse.json(daSua ? PHIEN_MOI : FAKE_SESSION)),
    )
    boot()

    await userEvent.clear(await oTen())
    await userEvent.type(await oTen(), 'An Phú Land 2')
    await userEvent.click(screen.getByRole('button', { name: /^Lưu$/ }))

    // Switcher ở chân sidebar đọc `session.workspaces` — nó chỉ đổi chữ khi
    // ['session'] thật sự được nạp lại.
    expect(await screen.findByRole('button', { name: /An Phú Land 2/ })).toBeInTheDocument()
  })

  it('③ 409 trùng tên: hiện thông điệp của backend, giữ nguyên chữ đã gõ', async () => {
    server.use(
      http.patch('/api/v1/workspaces/:id', () =>
        HttpResponse.json(
          {
            error: {
              code: 'WORKSPACE_TRUNG_TEN',
              message: "Bạn đã có một workspace tên 'Sunrise Land'",
            },
          },
          { status: 409 },
        ),
      ),
    )
    boot()

    await userEvent.clear(await oTen())
    await userEvent.type(await oTen(), 'Sunrise Land')
    await userEvent.click(screen.getByRole('button', { name: /^Lưu$/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/đã có một workspace tên/)
    expect(await oTen()).toHaveValue('Sunrise Land')
  })

  it('nút Lưu khoá khi tên chưa đổi hoặc rỗng', async () => {
    boot()
    await oTen()

    const luu = screen.getByRole('button', { name: /^Lưu$/ })
    expect(luu).toBeDisabled()

    await userEvent.clear(await oTen())
    expect(luu).toBeDisabled()

    await userEvent.type(await oTen(), 'Tên Khác')
    expect(luu).toBeEnabled()
  })
})

describe('cài đặt workspace — xoá', () => {
  it('④ nút xác nhận khoá tới khi gõ ĐÚNG mã workspace', async () => {
    boot()
    const dialog = await moDialogXoa()

    const nut = within(dialog).getByRole('button', { name: /^Xoá vĩnh viễn$/ })
    expect(nut).toBeDisabled()

    await userEvent.type(within(dialog).getByLabelText(/Nhập mã workspace/), 'ws_sai')
    expect(nut).toBeDisabled()

    await userEvent.clear(within(dialog).getByLabelText(/Nhập mã workspace/))
    await userEvent.type(within(dialog).getByLabelText(/Nhập mã workspace/), WS.id)
    expect(nut).toBeEnabled()
  })

  it('gọi DELETE /api/v1/workspaces/:id đúng workspace đang mở', async () => {
    const daXoa = vi.fn()
    server.use(
      http.delete('/api/v1/workspaces/:id', ({ params }) => {
        daXoa(params.id)
        return new HttpResponse(null, { status: 204 })
      }),
    )
    boot()

    const dialog = await moDialogXoa()
    await userEvent.type(within(dialog).getByLabelText(/Nhập mã workspace/), WS.id)
    await userEvent.click(within(dialog).getByRole('button', { name: /^Xoá vĩnh viễn$/ }))

    await vi.waitFor(() => {
      expect(daXoa).toHaveBeenCalledWith(WS.id)
    })
  })

  it('⑤ xoá xong thì rời màn cài đặt của workspace vừa biến mất', async () => {
    const PHIEN_SAU = {
      ...FAKE_SESSION,
      workspaces: FAKE_SESSION.workspaces.slice(1),
      currentWorkspaceId: WS_KHAC.id,
    }
    let daXoa = false
    server.use(
      http.delete('/api/v1/workspaces/:id', () => {
        daXoa = true
        return new HttpResponse(null, { status: 204 })
      }),
      http.get('/api/v1/me', () => HttpResponse.json(daXoa ? PHIEN_SAU : FAKE_SESSION)),
    )
    const router = boot()

    const dialog = await moDialogXoa()
    await userEvent.type(within(dialog).getByLabelText(/Nhập mã workspace/), WS.id)
    await userEvent.click(within(dialog).getByRole('button', { name: /^Xoá vĩnh viễn$/ }))

    // Đo trên ROUTER, không đo bằng "ô tên đã biến mất" — cùng khuôn
    // `dang-xuat.test.tsx`. Đo bằng sự vắng mặt của một phần tử thì một màn
    // đích render lỗi cũng làm test xanh, và nó buộc test phải chờ màn
    // `/dashboard` dựng xong (kèm mọi query của nó) chỉ để trả lời một câu về
    // điều hướng.
    await vi.waitFor(() => {
      expect(router.state.location.pathname).toBe('/dashboard')
    })
  })

  it('409 workspace cuối cùng: thông điệp hiện TRONG dialog, dialog không đóng', async () => {
    server.use(
      http.delete('/api/v1/workspaces/:id', () =>
        HttpResponse.json(
          {
            error: {
              code: 'WORKSPACE_CUOI_CUNG',
              message:
                'Đây là workspace duy nhất của bạn. Tạo một workspace khác trước khi xoá cái này.',
            },
          },
          { status: 409 },
        ),
      ),
    )
    boot()

    const dialog = await moDialogXoa()
    await userEvent.type(within(dialog).getByLabelText(/Nhập mã workspace/), WS.id)
    await userEvent.click(within(dialog).getByRole('button', { name: /^Xoá vĩnh viễn$/ }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/workspace duy nhất/)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})
