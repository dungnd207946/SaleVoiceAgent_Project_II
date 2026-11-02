/**
 * Form tự đăng ký. Cùng khuôn `LoginForm` — một cột giữa, lỗi hiện TẠI CHỖ.
 *
 * ĐỔI 2026-08-17: backend không còn nhận mật khẩu ở đây (`POST /auth/register`
 * chỉ nhận `email`+`name`) và KHÔNG còn đặt cookie phiên trong bất kỳ trường hợp
 * nào — mật khẩu đặt ở màn `/invite/<token>` sau khi bấm link trong thư. Nên
 * form này KHÔNG có ô mật khẩu, và gửi xong KHÔNG `navigate` đi đâu cả — chỉ
 * đổi sang một trong ba màn kết quả ngay tại chỗ:
 *
 *   · 201 (`daGuiLai: false`) -> "Đã gửi liên kết… tới {email}"
 *   · 200 (`daGuiLai: true`)  -> tài khoản `pending`, thư vừa GỬI LẠI
 *   · 409 `EMAIL_TAKEN`      -> "Email này đã có tài khoản." + link Đăng nhập
 *
 * Cả 201 lẫn 200 chỉ khác nhau ở giá trị `daGuiLai` — không cần đọc mã trạng
 * thái HTTP, hợp đồng đã gói việc phân biệt vào đúng một trường boolean.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from '@tanstack/react-router'
import { useMutation } from '@tanstack/react-query'
import { KhungXacThuc } from '@/components/ui/KhungXacThuc'
import { LoiApi } from '@/lib/http'
import { dangKy } from '../api'
import { NutGoogle } from './NutGoogle'

const O =
  'mt-1.5 h-11 w-full rounded-md border border-border-field bg-surface px-3 text-noi focus:border-ac focus:outline-none focus:ring-[3px] focus:ring-acs'
const NHAN = 'mt-[18px] block text-than font-semibold text-fg'

export function DangKyForm() {
  const [email, setEmail] = useState('')
  const [ten, setTen] = useState('')

  const gui = useMutation({
    mutationFn: () => dangKy(email, ten),
  })

  const duDieuKien = email.trim() !== '' && ten.trim() !== ''

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    gui.mutate()
  }

  if (gui.data) {
    return (
      <Khung>
        <h1 className="text-[20px] font-semibold text-fg">Kiểm tra hộp thư</h1>
        <p className="mx-auto mt-3 max-w-[420px] text-[14px] text-muted">
          {gui.data.daGuiLai ? (
            <>
              Tài khoản này chưa hoàn tất đăng ký. Chúng tôi vừa <strong>gửi lại</strong> liên kết
              đặt mật khẩu tới <strong className="text-fg">{email}</strong>.
            </>
          ) : (
            <>
              Đã gửi liên kết đặt mật khẩu tới <strong className="text-fg">{email}</strong>.
            </>
          )}{' '}
          Kiểm tra hộp thư (kể cả mục spam). Liên kết có hạn 7 ngày.
        </p>
      </Khung>
    )
  }

  return (
    <KhungXacThuc tieuDe="Đăng ký" onSubmit={onSubmit}>
      <NutGoogle />

      <label htmlFor="email" className="mt-7 block text-than font-semibold text-fg">
        Email
      </label>
      <input
        id="email"
        type="email"
        autoComplete="username"
        required
        placeholder="Nhập email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className={O}
      />

      <label htmlFor="ho-ten" className={NHAN}>
        Tên người dùng
      </label>
      <input
        id="ho-ten"
        type="text"
        autoComplete="name"
        required
        placeholder="Nhập tên người dùng"
        value={ten}
        onChange={(e) => setTen(e.target.value)}
        className={O}
      />

      {gui.error &&
        (gui.error instanceof LoiApi && gui.error.code === 'EMAIL_TAKEN' ? (
          <p
            role="alert"
            className="mt-[18px] rounded-md border border-badge-alert-fg/25 bg-badge-alert-bg px-3 py-3 text-than leading-[1.5] text-badge-alert-fg"
          >
            Email này đã có tài khoản.{' '}
            <Link to="/login" className="font-semibold underline">
              Đăng nhập
            </Link>
          </p>
        ) : (
          <p
            role="alert"
            className="mt-[18px] rounded-md border border-badge-alert-fg/25 bg-badge-alert-bg px-3 py-3 text-than leading-[1.5] text-badge-alert-fg"
          >
            {gui.error instanceof LoiApi ? gui.error.message : String(gui.error)}
          </p>
        ))}

      <button
        type="submit"
        disabled={gui.isPending || !duDieuKien}
        className="mt-[26px] h-[46px] w-full rounded-md bg-ac text-noi font-semibold text-white transition hover:bg-acd active:translate-y-px disabled:opacity-60"
      >
        {gui.isPending ? 'Đang gửi…' : 'Đăng ký'}
      </button>

      <p className="mt-4 text-center text-[13px] text-muted">
        Đã có tài khoản?{' '}
        <Link to="/login" className="font-semibold text-ac">
          Đăng nhập
        </Link>
      </p>
    </KhungXacThuc>
  )
}

/** Cùng khung căn giữa với `NhanLoiMoi` — hai màn này đứng cạnh nhau trong luồng. */
function Khung({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen place-items-center bg-bg px-6 text-center text-noi text-muted">
      <div>{children}</div>
    </div>
  )
}
