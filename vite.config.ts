// `defineConfig` lấy từ vitest/config (không phải 'vite') để khối `test` bên
// dưới được kiểm kiểu — dùng bản của 'vite' thì TS báo 'test' không tồn tại.
import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import path from 'node:path'

// VÌ SAO tanstackRouter đứng TRƯỚC react: plugin sinh `routeTree.gen.ts` từ cây file
// trong src/routes. Chạy sau react thì react đã transform xong file cũ.
export default defineConfig(({ mode }) => {
  // Tiền tố '' (không phải 'VITE_') vì biến này dùng ở ĐÂY — trong tiến trình
  // node dựng dev server — chứ không phải trong code chạy trên trình duyệt.
  // Đặt tên `VITE_` là mời nó vào bundle production, nơi nó vô nghĩa: ở
  // production frontend gọi đường tương đối và nginx mới là thứ định tuyến
  // (deploy/README.md). `envPrefix` mặc định của Vite vẫn là 'VITE_', nên biến
  // này KHÔNG lọt vào `import.meta.env` của client.
  const env = loadEnv(mode, import.meta.dirname, '')

  // Cùng tên biến với repo backend, có chủ đích: đổi cổng là sửa `PORTAL_API_PORT`
  // ở cả hai .env — một cái tên, không phải hai cái tên phải nhớ là chúng nói về
  // cùng một số. Mặc định 8100 vì đó là số dùng thật ở dev; mặc định phải là thứ
  // chạy được cho người chưa có .env.
  const congApi = env['PORTAL_API_PORT'] || '8100'

  return {
    plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
    resolve: {
      alias: { '@': path.resolve(import.meta.dirname, 'src') },
    },
    server: {
      // 5273 chứ không 5173 (mặc định vite): xem ../docs/dev-ports.md — dải cổng
      // riêng của odyssey, vì máy dev còn chạy vài project khác.
      port: 5273,
      // Mặc định Vite chỉ nghe 127.0.0.1 — máy khác trong LAN gõ IP vào là
      // connection refused. `host: true` nghe trên mọi interface để dev server
      // in ra thêm dòng «Network: http://<IP LAN>:5273/».
      //
      // LƯU Ý cookie: phiên đăng nhập đặt Secure (auth/router.py), mà miễn trừ
      // Secure-trên-http của trình duyệt CHỈ áp cho localhost — không áp cho
      // http://<IP LAN>. Máy khác mở bằng IP sẽ xem được UI nhưng đăng nhập
      // không dính cookie. Muốn đăng nhập thật thì cho máy kia ssh -L về đây và
      // mở qua localhost của chính nó (xem ../CHAY-HE-THONG.md).
      host: true,
      // Backend chạy ở `congApi` (uvicorn — `make api` ở repo
      // odyssey-portal-backend, biến PORTAL_API_PORT). Proxy để FE gọi '/api/...'
      // tương đối, không cần biến môi trường base-url và không có CORS ở dev.
      //
      // Mặc định 8100 — KHÔNG phải 8000 (credit-scoring-api) và KHÔNG phải 8080
      // (icr-keycloak), cả hai đang chạy trên máy dev này. Đổi cổng thì đặt
      // PORTAL_API_PORT trong .env của CẢ HAI repo; cùng một tên biến nên không
      // phải nhớ hai cái tên nói về cùng một số.
      //
      // Cookie phiên là Secure; trình duyệt miễn trừ http://localhost nên dev chạy
      // được, còn production thì cùng domain nên vẫn same-origin. Tách domain thì
      // phải đổi SameSite=None + Secure + token CSRF — cả ba, xem spec M2a §2.4.
      //
      // Khoá là '^/api/' (RegExp) chứ KHÔNG phải '/api': Vite khớp chuỗi thường
      // theo tiền tố, nên '/api' cuốn luôn route '/api-keys' của màn «Tích hợp &
      // API» — mở màn đó ra là proxy tới backend rồi trả 500. Đã gặp thật.
      proxy: {
        '^/api/': { target: `http://localhost:${congApi}`, changeOrigin: true },
        // WS gateway agent chạy local ở :9200 (odyssey-agent `gateway`), cùng origin như bản deploy.
        '^/v1/': { target: 'ws://localhost:9200', ws: true, changeOrigin: true },
        // Lip sync (lipsync_musetalk :8020) cùng origin như nginx bản deploy (khối
        // `/lipsync/`) ⇒ máy khác trong LAN mở bằng IP vẫn nối được; dev local tắt auth.
        '^/lipsync/': {
          target: 'ws://localhost:8020',
          ws: true,
          changeOrigin: true,
          rewrite: (p) => p.replace(/^\/lipsync/, ''),
        },
      },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['./vitest.setup.ts'],
      include: ['tests/**/*.test.{ts,tsx}'],
      // ⚠️ PHẢI lớn hơn `asyncUtilTimeout` trong vitest.setup.ts (5s), và lớn hơn
      // nhiều. Mặc định của vitest cũng là 5000: bằng nhau nghĩa là MỘT `waitFor`
      // chờ hết hạn đã ngốn trọn ngân sách của cả test, nên test chết vì
      // "Test timed out in 5000ms" thay vì báo đúng assertion nào không thoả — đã
      // gặp trên CI với `boot.test.tsx` (vòng lặp mount 18 màn) và `realestate-pform`.
      //
      // Đây là NGƯỠNG TRẦN, không phải thời gian chờ: test đúng vẫn resolve trong
      // vài trăm ms, con số này chỉ quyết định lúc nào thì coi là treo.
      testTimeout: 30000,
      hookTimeout: 30000,
    },
  }
})
