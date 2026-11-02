import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '@/i18n'
import { datNapLaiKhiChunkHong } from '@/lib/napLaiKhiChunkHong'
import { donKhoaThoCu } from '@/lib/donKhoaThoCu'
import { datCanhPhienHetHan } from '@/lib/canhPhienHetHan'
import { ManLoi } from '@/components/ManLoi'
import { routeTree } from './routeTree.gen'
import '@/styles/theme.css'

// Sau deploy, tab đang mở bundle cũ sẽ 404 ở chunk đầu tiên của màn chưa mở
// (sự cố UAT 2026-08-25) — nạp lại trang thay vì rơi vào màn «Something went
// wrong!». Cài TRƯỚC router: sự kiện phát từ chính cú lazy-load của route.
datNapLaiKhiChunkHong()

// Dọn khoá gateway dạng rõ mà bản cũ của màn «Thử agent» còn để lại — ngừng ghi
// thôi thì chỉ chặn khoá MỚI, khoá đã nằm trên máy vẫn nằm đó mãi. Mã DI TRÚ,
// có hạn dùng: xem docstring của tệp.
donKhoaThoCu()

/**
 * `defaultErrorComponent` — LƯỚI AN TOÀN cho mọi màn. Không có nó, một lỗi render
 * bất kỳ rơi vào ErrorComponent mặc định của TanStack («Something went wrong!» +
 * stack trần, không đường về) — đúng màn của sự cố UAT 2026-08-25, mà lần đó chỉ
 * ca chunk-404 được vá. Portal trước đây KHÔNG có error boundary nào, ở đâu cả.
 *
 * Đặt ở router chứ không ở `__root.tsx`: `errorComponent` của route gốc chỉ bắt
 * lỗi của CHÍNH nó, còn mặc định ở đây phủ mọi route con không tự khai.
 */
const router = createRouter({ routeTree, defaultErrorComponent: ManLoi })

// Router cần biết kiểu của cây route để `<Link to="...">` được kiểm lúc compile.
// Sai path ⇒ lỗi TypeScript, không phải màn 404 lúc chạy.
declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Fail loud (spec §6.2) — không retry vô hạn để che lỗi backend.
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

// Phiên hết hạn giữa lúc đứng yên trên một màn: mọi request dữ liệu 401 mà `/me`
// không ai hỏi lại. 401 ⇒ hỏi lại `/me`; nó 401 thì `SessionProvider` đưa về
// /login. `cancelRefetch: false` — một màn bắn năm request cùng 401 thì năm lần
// kích gộp vào MỘT lượt `/me` đang bay, không huỷ-rồi-gọi-lại năm lần.
datCanhPhienHetHan(() =>
  queryClient.invalidateQueries({ queryKey: ['session'] }, { cancelRefetch: false }),
)

/**
 * MSW chỉ nạp khi `VITE_MSW !== '0'`. Import ĐỘNG nên bundle production không
 * chứa msw — nếu import tĩnh thì fake data đi theo lên production, và một
 * handler quên tắt là dữ liệu giả hiện cho khách hàng thật.
 */
async function enableMocks(): Promise<void> {
  if (import.meta.env.VITE_MSW === '0') return
  const { startMsw } = await import('@/lib/msw/browser')
  await startMsw()
}

const rootEl = document.getElementById('root')
if (!rootEl) throw new Error('Không tìm thấy #root trong index.html')

void enableMocks().then(() => {
  createRoot(rootEl).render(
    <StrictMode>
      {/*
        KHÔNG bọc <SessionProvider> ở đây — nó nằm trong `routes/_app.tsx`.
        Provider chặn cả cây trên GET /api/v1/me; bọc ở đây thì màn /login cũng
        không render được khi endpoint đó trả 401. Xem docstring của _app.tsx.
      */}
      <QueryClientProvider client={queryClient}>
        <LangProvider>
          <RouterProvider router={router} />
        </LangProvider>
      </QueryClientProvider>
    </StrictMode>,
  )
})
