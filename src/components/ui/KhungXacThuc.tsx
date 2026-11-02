/**
 * Khung của các màn NGOÀI portal — đăng nhập · đăng ký · tạo workspace đầu tiên: một
 * form căn giữa trang, logo + tiêu đề căn GIỮA, nhãn và ô nhập bên trong căn TRÁI —
 * mắt neo vào giữa rồi rơi xuống cột nhập liệu.
 */
import type { FormEvent, ReactNode } from 'react'

export function KhungXacThuc({
  tieuDe,
  logo = true,
  rong = 'max-w-[352px]',
  onSubmit,
  children,
}: {
  tieuDe: string
  logo?: boolean
  /** Class bề rộng tối đa của form. */
  rong?: string
  onSubmit: (e: FormEvent) => void
  children: ReactNode
}) {
  return (
    <div className="grid min-h-dvh place-items-center bg-bg px-5 py-[clamp(28px,5vw,48px)]">
      <form onSubmit={onSubmit} className={`w-full ${rong}`}>
        {/*
          Bản logo ĐỦ (có dòng AGENT) chỉ sống được từ 56px trở lên — ở 36px của
          rail và 16px của tab nó là một vệt, nên hai chỗ đó dùng `favicon.svg`.
          Màn này là chỗ duy nhất trong portal có đủ khoảng trống cho nó, và cũng
          là màn duy nhất người dùng thấy khi CHƯA vào portal — tức đúng lúc cần
          biết mình đang đăng nhập vào sản phẩm nào.

          Dùng `<img>` trỏ vào tệp tĩnh chứ không chép path vào đây: bộ path đã
          nằm ở hai chỗ (`favicon.svg` + `Rail.tsx`), chỗ thứ ba là chỗ sẽ quên
          sửa.
        */}
        {logo && (
          <img
            src="/logo-nx-agent.svg"
            alt=""
            aria-hidden="true"
            width={56}
            height={56}
            className="mx-auto mb-5"
          />
        )}
        <h1 className="text-center text-[25px] font-semibold leading-[1.25] tracking-[-0.025em] text-fg">
          {tieuDe}
        </h1>
        {children}
      </form>
    </div>
  )
}
