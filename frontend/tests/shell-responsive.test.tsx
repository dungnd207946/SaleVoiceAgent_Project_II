import { afterEach, describe, expect, it } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { boGiaLap, doiRong, giaLapManHinh } from './man-hinh'

afterEach(boGiaLap)

function boot(path = '/dashboard') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  render(
    <QueryClientProvider client={qc}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
  return router
}

const lopPhu = () => screen.queryByRole('dialog', { name: 'Điều hướng' })
const navMang = () => screen.queryByRole('navigation', { name: 'Mảng' })

describe('shell — mobile', () => {
  it('mặc định KHÔNG có rail/panel trong DOM; ☰ mở lớp phủ chứa cả hai', async () => {
    giaLapManHinh(375)
    boot()
    const nut = await screen.findByRole('button', { name: 'Mở menu' })
    expect(navMang()).not.toBeInTheDocument()
    await userEvent.click(nut)
    const phu = lopPhu()!
    expect(within(phu).getByRole('navigation', { name: 'Mảng' })).toBeInTheDocument()
    expect(phu.querySelector('[data-nav]')).not.toBeNull()
    // Hộp thoại THẬT (`showModal()` ⇒ nền inert, Tab không lọt ra trang) — bản trước
    // là `<div role="dialog" aria-modal>` không giữ focus (audit 05/10).
    expect(phu.tagName).toBe('DIALOG')
  })

  it('bấm mục RAIL: điều hướng nhưng lớp phủ VẪN mở', async () => {
    giaLapManHinh(375)
    const router = boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    const rail = within(lopPhu()!).getByRole('navigation', { name: 'Mảng' })
    const links = within(rail).getAllByRole('link')
    await userEvent.click(links[links.length - 1]!)
    await waitFor(() => expect(router.state.location.pathname).not.toBe('/dashboard'))
    expect(lopPhu()).toBeInTheDocument()
  })

  it('bấm mục PANEL ⇒ đóng và UNMOUNT (không hidden)', async () => {
    giaLapManHinh(375)
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    const muc = lopPhu()!.querySelector<HTMLAnchorElement>(
      '[data-nav]:not([data-nav="dashboard"])',
    )!
    await userEvent.click(muc)
    await waitFor(() => expect(lopPhu()).not.toBeInTheDocument())
    expect(document.querySelector('[data-nav]')).toBeNull()
  })

  it('bấm mục panel ĐANG SÁNG (cùng route) vẫn đóng', async () => {
    giaLapManHinh(375)
    boot('/dashboard')
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    await userEvent.click(lopPhu()!.querySelector<HTMLAnchorElement>('[data-nav="dashboard"]')!)
    await waitFor(() => expect(lopPhu()).not.toBeInTheDocument())
  })

  it('Esc đóng và trả focus về ☰; bấm nền mờ cũng đóng', async () => {
    giaLapManHinh(375)
    boot()
    const nut = await screen.findByRole('button', { name: 'Mở menu' })
    await userEvent.click(nut)
    await userEvent.keyboard('{Escape}')
    expect(lopPhu()).not.toBeInTheDocument()
    expect(nut).toHaveFocus()
    await userEvent.click(nut)
    await userEvent.click(screen.getByRole('button', { name: 'Đóng menu' }))
    expect(lopPhu()).not.toBeInTheDocument()
  })

  it('Esc khi palette mở bên trên lớp phủ: không lỗi, focus nằm trên phần tử còn trong DOM', async () => {
    giaLapManHinh(375)
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    await userEvent.keyboard('{Meta>}k{/Meta}')
    await userEvent.keyboard('{Escape}')
    expect(document.body.contains(document.activeElement)).toBe(true)
  })

  it('ô tìm vẫn có tên «Tìm màn» ở mobile (chữ chỉ ẩn bằng sr-only)', async () => {
    giaLapManHinh(375)
    boot()
    expect(await screen.findByRole('button', { name: 'Tìm màn' })).toBeInTheDocument()
  })
})

describe('shell — tablet', () => {
  it('rail có sẵn, panel mặc định THU GỌN; mở ra là lớp phủ, bấm mục thì đóng', async () => {
    giaLapManHinh(900)
    boot()
    expect(await screen.findByRole('navigation', { name: 'Mảng' })).toBeInTheDocument()
    expect(document.querySelector('[data-nav]')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Mở menu' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Mở thanh bên' }))
    // Tablet: rail ở NGOÀI lớp phủ và phải bấm được ⇒ không modal.
    expect(lopPhu()).not.toHaveAttribute('aria-modal')
    const muc = lopPhu()!.querySelector<HTMLAnchorElement>(
      '[data-nav]:not([data-nav="dashboard"])',
    )!
    await userEvent.click(muc)
    await waitFor(() => expect(lopPhu()).not.toBeInTheDocument())
  })
})

describe('shell — đổi tầng khi lớp phủ đang mở', () => {
  it('mobile → desktop: lớp phủ đóng, panel hiện lại trong luồng', async () => {
    giaLapManHinh(375)
    boot()
    await userEvent.click(await screen.findByRole('button', { name: 'Mở menu' }))
    act(() => doiRong(1440))
    await waitFor(() => expect(lopPhu()).not.toBeInTheDocument())
    expect(document.querySelector('[data-nav]')).not.toBeNull()
    expect(screen.queryByRole('button', { name: 'Mở menu' })).not.toBeInTheDocument()
  })
})
