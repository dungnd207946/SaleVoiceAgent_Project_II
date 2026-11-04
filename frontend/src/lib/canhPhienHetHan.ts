/**
 * Canh phiên hết hạn GIỮA LÚC đang đứng trên một màn.
 *
 * `SessionProvider` đẩy về /login khi `GET /api/v1/me` trả 401 — nhưng `/me` chỉ
 * fetch lại khi có observer mới mount (`staleTime` 30s, `refetchOnWindowFocus:
 * false`). Phiên chết trong Redis mà người dùng đứng yên trên một màn thì mọi
 * request dữ liệu nhận 401 «phiên đã hết hạn», màn hiện «không tải được», và
 * không gì gọi lại `/me` để phát hiện. Lỗi thật, 2026-09-30.
 *
 * Vì sao canh ở `fetch` chứ không ở `QueryCache.onError`: còn những chỗ gọi
 * `fetch` trần (không qua `lib/http.ts`), và không lời gọi nào cũng đi qua React
 * Query. `fetch` là chỗ DUY NHẤT mọi request đi qua cùng một hình dạng.
 *
 * Vì sao 401 chỉ KÍCH hỏi lại `/me` chứ không điều hướng thẳng: portal có request
 * 401 mà phiên vẫn sống — Bearer khoá agent (`POST /agent/feedback`, màn Thử agent)
 * và `X-Platform-Admin-Token` (`/pricing`). Chỉ `/me` trả lời được «phiên còn
 * không»; 401 ở đó thì `SessionProvider` tự đưa về /login như lúc chưa đăng nhập.
 *
 * `/api/v1/me` trần bị BỎ QUA: nó chính là câu hỏi lại, kích tiếp từ nó là vòng
 * lặp vô hạn (401 → hỏi lại → 401 → …). Đường con (`/me/ho-so`…) vẫn được canh.
 *
 * Response trả về NGUYÊN VẸN cho người gọi — bộ canh chỉ nhìn `status`, không đọc
 * thân, nên màn vẫn hiện đúng thông điệp lỗi của nó trong lúc chờ `/me`.
 */
const DUONG_ME = '/api/v1/me'

function duongCua(input: RequestInfo | URL): string | null {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  try {
    const url = new URL(raw, window.location.origin)
    return url.origin === window.location.origin ? url.pathname : null
  } catch {
    return null
  }
}

/** Cài bộ canh; trả hàm gỡ (test dùng — `main.tsx` cài một lần cho cả vòng đời tab). */
export function datCanhPhienHetHan(khiGap401: () => unknown): () => void {
  const fetchGoc = window.fetch
  window.fetch = async (input, init) => {
    const res = await fetchGoc(input, init)
    if (res.status === 401) {
      const duong = duongCua(input)
      if (duong?.startsWith('/api/') && duong !== DUONG_ME) void khiGap401()
    }
    return res
  }
  return () => {
    window.fetch = fetchGoc
  }
}
