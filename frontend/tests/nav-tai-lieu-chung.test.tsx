import { render, screen } from '@testing-library/react'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'
import { kbNav } from '@/features/kb/nav'
import { TheKienThuc } from '@/features/ops/components/TheKienThuc'

/**
 * Đo chữ ĐÃ VẼ RA chứ không đọc bảng nhãn trong `TheKienThuc.tsx`: bảng đó là
 * chi tiết bên trong component, và export nó ra chỉ để test đọc làm cả tệp vi
 * phạm `react-refresh/only-export-components` — CI chạy `eslint` với
 * `max-warnings 0` nên đó là job đỏ, dù `npm run build` và vitest đều xanh.
 */
function veRoi() {
  const rootRoute = createRootRoute({
    component: () => <TheKienThuc muc={[{ khoa: 'taiLieuTraCuu', thay: 1, tong: 2 }]} />,
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

describe('nhãn tab tài liệu', () => {
  it('gọi là «Tài liệu chung»', () => {
    expect(kbNav.label.vi).toBe('Tài liệu chung')
  })

  // Ô Dashboard và mục nav phải KHỚP NGUYÊN — comment ở TheKienThuc.tsx đã ghi lý do:
  // một lần lẫn hai kho làm ô đó hiện 6/6 trong lúc /kb trống trơn (2026-08-14).
  it('ô Dashboard mang đúng chữ đó', async () => {
    veRoi()
    const hang = await screen.findByTestId('kt-hang-taiLieuTraCuu')
    expect(hang.textContent).toContain(kbNav.label.vi)
  })
})
