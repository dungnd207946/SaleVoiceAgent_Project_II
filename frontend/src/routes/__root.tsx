import { createRootRoute, Outlet } from '@tanstack/react-router'

/**
 * Route gốc. Cố tình MỎNG: provider nằm ở `main.tsx`, layout nằm ở `_app.tsx`.
 * Ai thêm gì vào đây thì thêm cho cả 18 màn — nên cân nhắc.
 */
export const Route = createRootRoute({
  component: Outlet,
  notFoundComponent: () => (
    <div className="grid min-h-screen place-items-center bg-bg px-6 text-center">
      <div>
        <p className="text-trang font-bold text-fg">Không có màn này</p>
        <p className="mt-2 text-noi text-muted">
          Đường dẫn không khớp route nào. Danh sách màn:{' '}
          <code className="font-mono">src/lib/screens.ts</code>
        </p>
        <a href="/dashboard" className="mt-4 inline-block text-noi font-semibold">
          Về Tổng quan
        </a>
      </div>
    </div>
  ),
})
