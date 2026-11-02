/**
 * Thẻ «Mật khẩu» của màn Hồ sơ — đổi mật khẩu của CHÍNH MÌNH.
 *
 * `coMatKhau: false` (tài khoản Google-only) ⇒ HỘP THÔNG BÁO đóng khung thay
 * vì ba ô nhập (khuôn theo ảnh người dùng chốt 2026-08-22): nói rõ đổi Ở ĐÂU —
 * vào tài khoản Google — chứ không chỉ nói «không có mật khẩu»; và để người ta
 * gõ xong mới ăn 409 là một form biết trước sẽ hỏng. Backend cũ chưa trả
 * trường này (vắng khoá) ⇒ coi như CÓ mật khẩu — đa số user; ca hiếm gõ sai
 * vẫn nhận thông điệp 409 rõ ràng từ server.
 *
 * Ô «Nhập lại mật khẩu mới» là kiểm TRA PHÍA FE, backend không có trường này:
 * đổi xong KHÔNG có bước xác nhận nào khác (không email, không đăng xuất phiên
 * — chốt thiết kế, xem docstring `service.doi_mat_khau` backend), nên một cú
 * gõ nhầm là bị khoá ngoài tài khoản. Không khớp thì khoá nút + nói tại chỗ,
 * không chờ submit.
 *
 * Đổi xong chỉ dọn ba ô và báo «Đã đổi mật khẩu.».
 */
import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH } from '@/components/ui/Bang'
import { O_CHUNG } from '@/components/ui/Truong'
import { useLang } from '@/i18n'
import { useSession } from '@/lib/session'
import { LoiApi } from '@/lib/http'
import { doiMatKhau } from '../api'
import { THE, TIEU_DE_THE } from './HoSoScreen'

const NHAN = 'mb-1.5 block text-phu text-muted'

export function KhoiMatKhau() {
  const { t } = useLang()
  const { session } = useSession()
  const [hienTai, setHienTai] = useState('')
  const [moi, setMoi] = useState('')
  const [nhapLai, setNhapLai] = useState('')

  const doi = useMutation({
    mutationFn: () => doiMatKhau(hienTai, moi),
    onSuccess: () => {
      setHienTai('')
      setMoi('')
      setNhapLai('')
    },
  })

  if (session.user.coMatKhau === false) {
    return (
      <section className={THE}>
        <h2 className={TIEU_DE_THE}>{t({ vi: 'Mật khẩu', en: 'Password' })}</h2>
        <div className="rounded-lg border border-border px-4 py-3 text-than leading-[1.6] text-nav">
          {t({
            vi: 'Tài khoản này đăng nhập bằng SSO với Google. Hãy đăng nhập vào tài khoản Google và đổi mật khẩu ở đó.',
            en: 'You signed in using SSO with your Google account. Sign into your Google account and change the password there.',
          })}
        </div>
      </section>
    )
  }

  const khongKhop = nhapLai !== '' && nhapLai !== moi
  const chuaHopLe = !hienTai || moi.length < 10 || nhapLai !== moi

  function gui(e: React.FormEvent) {
    e.preventDefault()
    if (chuaHopLe || doi.isPending) return
    doi.mutate()
  }

  return (
    <section className={THE}>
      <h2 className={TIEU_DE_THE}>{t({ vi: 'Mật khẩu', en: 'Password' })}</h2>

      <form onSubmit={gui}>
        {/* BA cột một hàng, không phải lưới 2 cột của form hồ sơ: ba ô này là
            MỘT bộ — 2 cột đẩy «Nhập lại» xuống hàng dưới cạnh một ô trống,
            người dùng bắt được ngay («lệch thế», 2026-08-22). */}
        <div className="grid gap-x-6 gap-y-4 md:grid-cols-3">
          <div>
            <label htmlFor="mk-hien-tai" className={NHAN}>
              {t({ vi: 'Mật khẩu hiện tại', en: 'Current password' })}
            </label>
            <input
              id="mk-hien-tai"
              type="password"
              autoComplete="current-password"
              value={hienTai}
              onChange={(e) => setHienTai(e.target.value)}
              className={O_CHUNG}
            />
          </div>
          <div>
            <label htmlFor="mk-moi" className={NHAN}>
              {t({ vi: 'Mật khẩu mới', en: 'New password' })}
            </label>
            <input
              id="mk-moi"
              type="password"
              autoComplete="new-password"
              value={moi}
              onChange={(e) => setMoi(e.target.value)}
              maxLength={200}
              className={O_CHUNG}
            />
            <p className="mt-1 text-[12px] leading-[1.45] text-muted-2">
              {t({ vi: 'Ít nhất 10 ký tự.', en: 'At least 10 characters.' })}
            </p>
          </div>
          <div>
            <label htmlFor="mk-nhap-lai" className={NHAN}>
              {t({ vi: 'Nhập lại mật khẩu mới', en: 'Confirm new password' })}
            </label>
            <input
              id="mk-nhap-lai"
              type="password"
              autoComplete="new-password"
              value={nhapLai}
              onChange={(e) => setNhapLai(e.target.value)}
              maxLength={200}
              className={O_CHUNG}
            />
            {khongKhop && (
              <p className="mt-1 text-[12px] leading-[1.45] text-badge-alert-fg">
                {t({ vi: 'Mật khẩu nhập lại không khớp.', en: 'Passwords do not match.' })}
              </p>
            )}
          </div>
        </div>

        {doi.error && (
          <p
            role="alert"
            className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] text-badge-alert-fg"
          >
            {doi.error instanceof LoiApi
              ? doi.error.message
              : t({ vi: 'Không đổi được mật khẩu', en: 'Could not change the password' })}
          </p>
        )}

        <div className={`${HANG_NUT} mt-4`}>
          {doi.isSuccess && !doi.isPending && (
            <span role="status" className="mr-auto text-[13px] text-muted">
              {t({ vi: 'Đã đổi mật khẩu.', en: 'Password changed.' })}
            </span>
          )}
          <button type="submit" disabled={chuaHopLe || doi.isPending} className={NUT_CHINH}>
            {doi.isPending
              ? t({ vi: 'Đang đổi…', en: 'Changing…' })
              : t({ vi: 'Đổi mật khẩu', en: 'Change password' })}
          </button>
        </div>
      </form>
    </section>
  )
}
