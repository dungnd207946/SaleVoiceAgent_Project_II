/**
 * Màn lỗi dùng chung — `defaultErrorComponent` của router (`main.tsx`).
 *
 * VÌ SAO CÓ: trước 2026-08-27 portal KHÔNG có error boundary nào, ở đâu cả. Một
 * lỗi render bất kỳ trong 20 màn — một `.map` trên `undefined`, một payload lệch
 * hình dạng — rơi thẳng vào ErrorComponent MẶC ĐỊNH của TanStack: dòng chữ
 * «Something went wrong!» kèm stack trần, không nút nào, không đường về.
 *
 * Đó chính là màn người dùng gặp trong sự cố UAT 2026-08-25. Lần đó chỉ ca
 * chunk-404-sau-deploy được vá (`lib/napLaiKhiChunkHong.ts`); mọi lỗi còn lại
 * vẫn đi ra đúng chỗ cũ suốt hai ngày sau đó.
 *
 * ⚠ HAI NGỮ CẢNH, một component. `defaultErrorComponent` thay chỗ component
 * của route ĐANG lỗi, nên nếu `/convos` ném thì màn này render BÊN TRONG layout
 * `_app` — rail + panel + topbar còn nguyên, người dùng bấm đi chỗ khác được.
 * Chỉ khi chính `_app` ném (vd `SessionProvider`) nó mới chiếm trọn trang. Vì
 * thế KHÔNG khai `min-h-screen`: đặt trong vùng nội dung thì nó thành một hộp
 * rỗng cao lênh khênh, còn đứng một mình thì `py-20` đã đủ để chữ không dính
 * mép trên.
 *
 * BA HÀNH ĐỘNG, xếp theo xác suất chữa được:
 *  · «Tải lại trang» — nạp lại bundle. Đây là cú chữa cho ca bundle cũ sau
 *    deploy mà `napLaiKhiChunkHong` KHÔNG tự nạp lại được: nó có giãn cách 10s
 *    chống vòng lặp vô hạn, và trong 10s đó lỗi đi thẳng tới đây.
 *  · «Thử lại» — `reset()` của router, dựng lại boundary mà không mất state app.
 *    Đủ cho lỗi thoáng qua (một request lỗi, một race).
 *  · «Về Tổng quan» — `<a href>` chứ KHÔNG `<Link>`, cố ý: điều hướng mềm giữ
 *    nguyên cây React đang hỏng, nên nó có thể rơi lại vào chính lỗi vừa gặp.
 *    Nạp cứng thì chắc chắn sạch. Cùng lý lẽ với `notFoundComponent` ở
 *    `routes/__root.tsx`.
 *
 * Hàng nút CĂN GIỮA chứ không dùng hằng `HANG_NUT` (căn phải): luật hàng-nút
 * của repo nói về form trong trang · hộp xác nhận inline · hộp thoại — đây
 * không phải cái nào trong ba. Nó là một trang thông báo căn giữa, và bạn cùng
 * họ với nó là `notFoundComponent`, vốn cũng căn giữa.
 */
import { useEffect } from 'react'
import type { ErrorComponentProps } from '@tanstack/react-router'

/**
 * BẢN SAO của `NUT_CHINH`/`NUT_PHU` trong `components/ui/Bang.tsx`, CỐ Ý — và
 * `tests/man-loi.test.tsx` có cổng parity so từng ký tự, cùng khuôn
 * `contracts/*.json` ↔ `src/lib/*`. Đổi hằng bên đó mà quên đây là ĐỎ.
 *
 * Vì sao không import thẳng: màn này là `defaultErrorComponent` của router nên
 * nó nằm trong chunk ENTRY, và `Bang.tsx` import `@/components/icons` → kéo cả
 * `lucide-react` theo. Đo được: entry 86.9 → 93.1 KB gz (+6.2) chỉ để lấy hai
 * chuỗi class. Cái giá đó rơi vào MỌI lần tải trang, kể cả trang giới thiệu
 * công khai và `/login` vốn không cần một icon nào — đổi lấy một màn gần như
 * không bao giờ render.
 *
 * Cũng KHÔNG lazy-load màn này: ca hỏng đáng giá nhất của nó chính là bundle cũ
 * sau deploy, tức đúng lúc `import()` một chunk mới là thứ không tin được.
 */
const NUT_CHINH_LOP =
  'h-9 max-md:h-10 inline-flex items-center justify-center rounded-md bg-ac px-[15px] text-than font-semibold text-white disabled:opacity-50'
const NUT_PHU_LOP =
  'h-9 max-md:h-10 inline-flex items-center justify-center rounded-md border border-border-field px-[15px] text-than'

/** `error` khai là `Error` nhưng lúc chạy ném được BẤT CỨ gì — kể cả một chuỗi. */
function loiThanhChu(e: unknown): string {
  if (e instanceof Error && e.message) return e.message
  if (typeof e === 'string' && e) return e
  return 'Không có mô tả lỗi.'
}

/**
 * `napLai` tiêm được CHỈ để test — `window.location.reload` là thuộc tính
 * unforgeable của `Location` trong jsdom, không spy nổi. Cùng seam, cùng lý do
 * với `datNapLaiKhiChunkHong(napLai)` ở `lib/napLaiKhiChunkHong.ts`. Router chỉ
 * truyền `error`/`info`/`reset`, nên bản chạy thật luôn dùng giá trị mặc định.
 */
export function ManLoi({
  error,
  reset,
  napLai = () => window.location.reload(),
}: ErrorComponentProps & { napLai?: () => void }) {
  // Màn chỉ hiện `message`; stack thì vào console để người trực còn lần được.
  // Khác `console.log` mỗi frame của `chatGateway.ts` ở chỗ đây là sự kiện hiếm
  // và không mang nội dung hội thoại của khách.
  useEffect(() => {
    console.error('[ManLoi] lỗi render:', error)
  }, [error])

  return (
    <div className="grid place-items-center px-6 py-20 text-center">
      <div className="max-w-[460px]">
        <p className="text-trang font-bold text-fg">Màn này gặp lỗi</p>
        <p className="mt-2 text-noi leading-[1.55] text-muted">
          Phần còn lại của portal vẫn dùng được. Nếu vừa có bản cập nhật, tải lại trang thường là
          đủ.
        </p>

        <p className="mt-4 break-words rounded-md border border-border-soft bg-fill-strong px-3 py-2 text-left font-mono text-phu text-muted-2">
          {loiThanhChu(error)}
        </p>

        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          <button type="button" className={NUT_PHU_LOP} onClick={reset}>
            Thử lại
          </button>
          <button type="button" className={NUT_CHINH_LOP} onClick={napLai}>
            Tải lại trang
          </button>
        </div>

        <a href="/dashboard" className="mt-4 inline-block text-[13px] text-muted hover:text-fg">
          Về Tổng quan
        </a>
      </div>
    </div>
  )
}
