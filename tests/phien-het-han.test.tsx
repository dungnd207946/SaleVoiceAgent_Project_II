/**
 * Phiên hết hạn GIỮA LÚC đang đứng trên một màn phải đưa người dùng về /login.
 *
 * Lỗi thật (2026-09-30): phiên chết trong Redis, mọi request dữ liệu nhận 401,
 * nhưng `SessionProvider` chỉ xét `GET /me` — mà `/me` chỉ fetch lại khi có
 * observer mới mount (và `refetchOnWindowFocus: false`). Đứng yên trên một màn
 * thì không gì gọi lại `/me`, nên màn cứ «không tải được dữ liệu» mãi.
 *
 * Bài ② là lý do KHÔNG điều hướng thẳng khi gặp 401: portal có những request 401
 * mà phiên vẫn sống (Bearer khoá agent ở `/agent/feedback`, `X-Platform-Admin-Token`
 * ở `/pricing`). Chỉ `/me` mới trả lời được «phiên còn không».
 */
import { afterEach, describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import { datCanhPhienHetHan } from '../src/lib/canhPhienHetHan'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

const moiClient = () => new QueryClient({ defaultOptions: { queries: { retry: false } } })

let go: (() => void) | undefined
afterEach(() => {
  go?.()
  go = undefined
})

/** Dựng app ở /dashboard, cài bộ canh ĐÚNG như main.tsx cài, chờ phiên nạp xong. */
async function boot() {
  const queryClient = moiClient()
  go = datCanhPhienHetHan(() => queryClient.invalidateQueries({ queryKey: ['session'] }))
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: ['/dashboard'] }),
  })
  render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
  await screen.findByRole('button', { name: FAKE_SESSION.user.name })
  return { router, queryClient }
}

const khong401 = () =>
  HttpResponse.json(
    { error: { code: 'UNAUTHENTICATED', message: 'Chưa đăng nhập hoặc phiên đã hết hạn' } },
    { status: 401 },
  )

describe('phiên hết hạn giữa chừng', () => {
  it('① request dữ liệu nhận 401 và /me cũng 401 ⇒ về /login', async () => {
    const { router, queryClient } = await boot()

    // Phiên chết: từ giờ MỌI đường API đều 401, kể cả /me.
    server.use(http.all('/api/*', khong401))
    // Màn nạp lại dữ liệu mà KHÔNG mount observer mới — đúng tình huống đứng yên.
    await queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== 'session' })

    await expect.poll(() => router.state.location.pathname).toBe('/login')
  })

  it('② 401 của một request KHÔNG dùng phiên, /me vẫn 200 ⇒ ở lại màn', async () => {
    const { router } = await boot()
    let soLanGoiMe = 0
    server.use(
      http.get('/api/v1/me', () => {
        soLanGoiMe++
        return HttpResponse.json(FAKE_SESSION)
      }),
      http.post('/api/v1/agent/feedback', khong401),
    )

    await fetch('/api/v1/agent/feedback', { method: 'POST' })

    // Có hỏi lại /me — đó là cách duy nhất biết phiên còn sống…
    await expect.poll(() => soLanGoiMe).toBeGreaterThan(0)
    // …và vì nó còn sống thì không ai bị đá ra.
    expect(router.state.location.pathname).toBe('/dashboard')
  })

  it('③ 401 của CHÍNH /me không kích lại bộ canh (không vòng lặp)', async () => {
    let soLanKich = 0
    go = datCanhPhienHetHan(() => {
      soLanKich++
    })
    server.use(http.get('/api/v1/me', khong401), http.patch('/api/v1/me/ho-so', khong401))

    await fetch('/api/v1/me')
    await fetch('/api/v1/me/ho-so', { method: 'PATCH' })

    // `/me` trần bị bỏ qua; đường con của nó (`/me/ho-so`) vẫn là request dữ liệu.
    expect(soLanKich).toBe(1)
  })

  it('④ response đi qua NGUYÊN VẸN — người gọi vẫn đọc được thân lỗi', async () => {
    go = datCanhPhienHetHan(() => {})
    server.use(http.get('/api/v1/overview', khong401))

    const res = await fetch('/api/v1/overview')

    expect(res.status).toBe(401)
    expect(await res.json()).toMatchObject({ error: { code: 'UNAUTHENTICATED' } })
  })

  it('⑤ main.tsx cài bộ canh (tệp có side effect, không import được trong jsdom)', () => {
    const main = readFileSync(resolve(__dirname, '../src/main.tsx'), 'utf8')
    expect(main).toMatch(/datCanhPhienHetHan\(/)
  })
})
