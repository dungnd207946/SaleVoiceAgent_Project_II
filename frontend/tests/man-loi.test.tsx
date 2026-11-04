/**
 * Màn lỗi dùng chung (`ManLoi`) + việc nó thật sự được nối làm
 * `defaultErrorComponent` của router.
 *
 * Trước 2026-08-27 portal KHÔNG có error boundary nào, ở đâu cả: một lỗi render
 * bất kỳ trong 20 màn rơi vào ErrorComponent mặc định của TanStack — «Something
 * went wrong!» + stack trần, không nút nào, không đường về. Đó là màn của sự cố
 * UAT 2026-08-25, và lần đó chỉ ca chunk-404 được vá.
 *
 * Bài ⑤ là bài đắt nhất ở đây: nó dựng một route THẬT rồi cho nó ném, thay vì
 * chỉ mount `ManLoi` trực tiếp. Một component đúng mà không ai nối vào router
 * thì sự cố lặp lại nguyên xi.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from '@tanstack/react-router'
import { ManLoi } from '../src/components/ManLoi'

afterEach(() => vi.restoreAllMocks())

/** React và router đều log lỗi ra console khi boundary bắt — im nó đi cho sạch. */
function imConsole() {
  vi.spyOn(console, 'error').mockImplementation(() => {})
}

describe('ManLoi', () => {
  it('① hiện thông điệp lỗi để người dùng còn báo lại được', () => {
    imConsole()
    render(<ManLoi error={new Error('units.map is not a function')} reset={() => {}} />)

    expect(screen.getByText('Màn này gặp lỗi')).toBeInTheDocument()
    expect(screen.getByText('units.map is not a function')).toBeInTheDocument()
  })

  it('② lỗi không phải Error (ném một chuỗi) vẫn ra chữ, không ra "undefined"', () => {
    imConsole()
    // `ErrorComponentProps.error` khai là `Error` nhưng lúc chạy ném được bất cứ
    // gì — một `throw 'oops'` ở tầng nào đó là đủ.
    render(<ManLoi error={'oops' as unknown as Error} reset={() => {}} />)

    expect(screen.getByText('oops')).toBeInTheDocument()
  })

  it('③ «Thử lại» gọi reset của router; «Tải lại trang» nạp lại bundle', async () => {
    imConsole()
    const reset = vi.fn()
    const napLai = vi.fn()
    render(<ManLoi error={new Error('x')} reset={reset} napLai={napLai} />)

    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(reset).toHaveBeenCalledTimes(1)
    expect(napLai).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole('button', { name: 'Tải lại trang' }))
    expect(napLai).toHaveBeenCalledTimes(1)
  })

  it('④ «Về Tổng quan» là nạp CỨNG, không phải điều hướng mềm', () => {
    imConsole()
    render(<ManLoi error={new Error('x')} reset={() => {}} />)

    // Điều hướng mềm giữ nguyên cây React đang hỏng nên có thể rơi lại vào
    // chính lỗi vừa gặp. `<a href>` thì chắc chắn dựng lại từ đầu.
    expect(screen.getByRole('link', { name: 'Về Tổng quan' })).toHaveAttribute('href', '/dashboard')
  })
})

describe('nối vào router', () => {
  it('⑤ một route ném lỗi thì hiện ManLoi, KHÔNG hiện "Something went wrong!"', async () => {
    imConsole()

    const goc = createRootRoute()
    const man = createRoute({
      getParentRoute: () => goc,
      path: '/',
      component: () => {
        throw new Error('màn này vỡ')
      },
    })
    const router = createRouter({
      routeTree: goc.addChildren([man]),
      history: createMemoryHistory({ initialEntries: ['/'] }),
      defaultErrorComponent: ManLoi,
    })

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    render(<RouterProvider router={router as any} />)

    expect(await screen.findByText('Màn này gặp lỗi')).toBeInTheDocument()
    expect(screen.getByText('màn này vỡ')).toBeInTheDocument()
    expect(screen.queryByText(/Something went wrong/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Tải lại trang' })).toBeInTheDocument()
  })

  /**
   * `ManLoi` CHÉP TAY hai chuỗi class của `Bang.tsx` để không kéo `icons.tsx`
   * (→ `lucide-react`) vào chunk entry — đo được +6.2 KB gz, trả ở mọi lần tải
   * trang kể cả `/` và `/login`. Bản sao thì phải có cổng, cùng khuôn
   * `contracts/*.json` ↔ `src/lib/*`.
   */
  it('⑦ hai chuỗi class chép tay vẫn khớp từng ký tự với Bang.tsx', async () => {
    const { NUT_CHINH, NUT_PHU } = await import('../src/components/ui/Bang')
    imConsole()
    render(<ManLoi error={new Error('x')} reset={() => {}} />)

    expect(screen.getByRole('button', { name: 'Tải lại trang' }).className).toBe(NUT_CHINH)
    expect(screen.getByRole('button', { name: 'Thử lại' }).className).toBe(NUT_PHU)
  })

  it('⑥ main.tsx khai defaultErrorComponent', () => {
    // `main.tsx` có side effect (createRoot, MSW) nên không import được trong
    // jsdom — quét văn bản, cùng lối `nap-lai-khi-chunk-hong`.
    const main = readFileSync(resolve(__dirname, '../src/main.tsx'), 'utf8')
    expect(main).toMatch(/defaultErrorComponent:\s*ManLoi/)
  })
})
