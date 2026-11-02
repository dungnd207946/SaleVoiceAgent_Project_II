/**
 * Form đăng nhập. Lỗi hiện TẠI CHỖ, không đẩy sang màn lỗi toàn trang: người
 * gõ sai mật khẩu cần gõ lại, không cần một trang báo lỗi.
 *
 * 409 NO_WORKSPACE nói khác hẳn — đó không phải lỗi của người dùng và gõ lại
 * không giúp được gì (PQ_01 Q01: trạng thái HỎNG, không phải rỗng).
 *
 * ── DÁNG MÀN (2026-08-10) ──────────────────────────────────────────────────
 * MỘT cột giữa. Bản trước có lúc là lưới hai cột với một mặt tối bên phải kể
 * một cuộc gọi «đang diễn». Bỏ, vì hai lẽ — lẽ thứ hai mới là lẽ nặng:
 *   ① Người tới đây đã mua rồi và đang muốn vào làm việc; mọi thứ trưng ở đây
 *      đều nằm chắn giữa họ và ô mật khẩu.
 *   ② Đây là màn TRƯỚC xác thực. Dữ liệu tenant không được xuất hiện ở chỗ chưa
 *      đăng nhập. Bản ghi hôm ấy là số giả, nhưng nó để sẵn một cái khuôn mời
 *      người viết sau cắm dữ liệu thật vào.
 *
 * CÓ nút Google từ 2026-08-18 (spec dang-nhap-google-oauth) — nó là một <a href>
 * thật sang `/api/v1/auth/google/start`, không phải một lời hứa suông: seam có
 * `layNhaCungCap()` và nút TỰ ẨN khi backend báo tính năng tắt.
 *
 * VẪN KHÔNG có «Quên mật khẩu?» và KHÔNG có Apple/SSO: chưa có đường nào ở
 * backend, và một link chết là thứ người dùng bấm đúng vào lúc bí nhất.
 */
import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { KhungXacThuc } from '@/components/ui/KhungXacThuc'
import { LoiApi } from '@/lib/http'
import { dangNhap } from '../api'
import { NutGoogle } from './NutGoogle'

// `loiBanDau?: string | undefined`, KHÔNG chỉ `loiBanDau?: string`: tsconfig
// bật `exactOptionalPropertyTypes`, nên một prop khai `?: string` TRẦN từ
// chối cả việc gán tường minh `undefined` cho nó — mà `routes/login.tsx` gán
// đúng thế khi URL không có `?loi=`. Thêm `| undefined` vào type là mở đúng
// cửa đó mà không phải đổi cách gọi ở phía route.
export function LoginForm({ loiBanDau }: { loiBanDau?: string | undefined } = {}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [matKhau, setMatKhau] = useState('')
  const [loi, setLoi] = useState<LoiApi | null>(null)
  const [dangGui, setDangGui] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setLoi(null)
    setDangGui(true)
    try {
      const phien = await dangNhap(email, matKhau)
      // Đặt sẵn vào cache để `_app` không phải fetch lại ngay sau redirect.
      queryClient.setQueryData(['session'], phien)
      await navigate({ to: '/dashboard' })
    } catch (err) {
      setLoi(err instanceof LoiApi ? err : new LoiApi('UNKNOWN', String(err)))
    } finally {
      setDangGui(false)
    }
  }

  return (
    <KhungXacThuc tieuDe="Đăng nhập" onSubmit={onSubmit}>
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
        className="mt-1.5 h-11 w-full rounded-md border border-border-field bg-surface px-3 text-noi focus:border-ac focus:outline-none focus:ring-[3px] focus:ring-acs"
      />

      <label htmlFor="mat-khau" className="mt-[18px] block text-than font-semibold text-fg">
        Mật khẩu
      </label>
      <input
        id="mat-khau"
        type="password"
        autoComplete="current-password"
        required
        placeholder="Nhập mật khẩu"
        value={matKhau}
        onChange={(e) => setMatKhau(e.target.value)}
        className="mt-1.5 h-11 w-full rounded-md border border-border-field bg-surface px-3 text-noi focus:border-ac focus:outline-none focus:ring-[3px] focus:ring-acs"
      />

      {/* `loi` (lỗi của LẦN BẤM này) đè `loiBanDau` (lỗi từ `?loi=` mang tới
            khi vừa vào màn) — người vừa gõ lại và bấm thì cái họ vừa làm mới
            hơn cái đã có sẵn trên URL. */}
      {(loi || loiBanDau) && (
        <p
          role="alert"
          className="mt-[18px] rounded-md border border-badge-alert-fg/25 bg-badge-alert-bg px-3 py-3 text-than leading-[1.5] text-badge-alert-fg"
        >
          {/* NO_WORKSPACE không còn tới từ đường đăng nhập: từ 2026-08-15
                backend cho phiên không workspace và FE đưa tới màn tạo workspace
                đầu tiên. Mã này giờ chỉ còn ở `POST /me/workspace`. */}
          {loi ? loi.message : loiBanDau}
        </p>
      )}

      <button
        type="submit"
        disabled={dangGui}
        className="mt-[26px] h-[46px] w-full rounded-md bg-ac text-noi font-semibold text-white transition hover:bg-acd active:translate-y-px disabled:opacity-60"
      >
        {dangGui ? 'Đang đăng nhập…' : 'Đăng nhập'}
      </button>

      <p className="mt-4 text-center text-[13px] text-muted">
        Chưa có tài khoản?{' '}
        <Link to="/dang-ky" className="font-semibold text-ac">
          Đăng ký
        </Link>
      </p>
    </KhungXacThuc>
  )
}
