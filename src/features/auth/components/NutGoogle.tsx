/**
 * Nút «Tiếp tục với Google» — dùng chung cho màn đăng nhập và màn đăng ký;
 * backend không phân biệt hai đường (nhánh 3 của `dang_nhap_google.py` tự lo
 * việc tạo tài khoản mới khi email Google chưa từng đăng ký), nên FE cũng
 * không cần hai component.
 *
 * ⚠ THẺ `<a href>` THẬT, KHÔNG PHẢI `<button onClick>` + `fetch`. OAuth cần
 * trình duyệt RỜI KHỎI trang để tới `accounts.google.com`; một `fetch` sẽ theo
 * redirect đó rồi đâm vào CORS của Google và không bao giờ chạy được. Dùng
 * `<a>` còn cho middle-click và mở-tab-mới hoạt động miễn phí, không phải viết
 * thêm gì.
 *
 * THỨ TỰ (2026-08-21): nút Google ĐỨNG TRÊN form, gạch «hoặc» nằm giữa nó và ô
 * Email. Đường Google là đường NGẮN hơn cho phần lớn người dùng, nên nó phải
 * gặp mắt trước khi người ta kịp bắt đầu gõ tay; đặt dưới nút submit là mời
 * người ta gõ xong rồi mới biết có lối tắt. Vì vậy cụm này TỰ MANG gạch «hoặc»
 * — nó là bản lề giữa hai đường, không phải phần trang trí của một trong hai.
 *
 * KHÔNG vẽ gì ở CẢ HAI trạng thái sau — cùng một `if (!data?.google) return
 * null` bắt cả hai: đang hỏi backend (`data` còn `undefined`, chưa biết câu
 * trả lời) VÀ đã biết câu trả lời là tắt (`data.google === false`). Đang hỏi
 * cũng phải im lặng, không vẽ chỗ trống rồi nhét nút vào sau: cụm này giờ nằm
 * TRÊN form, nên nó hiện muộn sẽ đẩy cả ô Email/Mật khẩu tụt xuống dưới con
 * trỏ của người đang gõ.
 *
 * `staleTime: Infinity` — cờ này chỉ đổi khi backend đổi cấu hình
 * (`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` trong `.env`), không đáng hỏi lại
 * mỗi lần chuyển màn `/login` ↔ `/dang-ky`.
 */
import { useQuery } from '@tanstack/react-query'

import { layNhaCungCap } from '../api'

export function NutGoogle() {
  const { data } = useQuery({
    queryKey: ['auth', 'providers'],
    queryFn: layNhaCungCap,
    staleTime: Infinity,
  })

  if (!data?.google) return null

  return (
    <>
      <a
        href="/api/v1/auth/google/start"
        className="mt-7 flex h-[46px] w-full items-center justify-center gap-2 rounded-md border border-border-field bg-surface text-noi font-semibold text-fg transition hover:bg-n2 active:translate-y-px"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
          <path
            fill="#4285F4"
            d="M23.04 12.26c0-.82-.07-1.6-.21-2.36H12v4.47h6.19a5.3 5.3 0 0 1-2.3 3.47v2.89h3.72c2.18-2 3.43-4.96 3.43-8.47z"
          />
          <path
            fill="#34A853"
            d="M12 24c3.1 0 5.7-1.03 7.6-2.79l-3.72-2.89c-1.03.69-2.35 1.1-3.88 1.1-2.98 0-5.5-2.01-6.4-4.72H1.75v2.98A11.5 11.5 0 0 0 12 24z"
          />
          <path
            fill="#FBBC05"
            d="M5.6 14.7a6.9 6.9 0 0 1 0-4.42V7.3H1.75a11.5 11.5 0 0 0 0 10.38L5.6 14.7z"
          />
          <path
            fill="#EA4335"
            d="M12 4.75c1.68 0 3.19.58 4.38 1.72l3.29-3.29C17.7 1.3 15.1 0 12 0 7.5 0 3.62 2.56 1.75 6.3L5.6 9.28C6.5 6.57 9.02 4.75 12 4.75z"
          />
        </svg>
        Tiếp tục với Google
      </a>
      <div className="mt-5 flex items-center gap-3 text-nhan text-muted-2">
        <span className="h-px flex-1 bg-border" />
        hoặc
        <span className="h-px flex-1 bg-border" />
      </div>
    </>
  )
}
