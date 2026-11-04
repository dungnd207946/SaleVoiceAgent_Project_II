/**
 * Màn `/settings` — «Hồ sơ & tuỳ chọn», vào từ menu avatar chân sidebar.
 *
 * BA THẺ, khuôn thẻ chép từ `CaiDatWorkspace` (màn anh em gần nhất):
 *   ① Hồ sơ — avatar + tên/SĐT/chức danh/email, XEM TRƯỚC SỬA SAU (luật của
 *     mọi màn có form bản ghi): mặc định là bản chỉ-đọc, form chỉ mở khi bấm
 *     «Sửa hồ sơ». Email CHỈ ĐỌC ở cả hai chế độ — đổi email cần luồng xác
 *     minh, ngoài phạm vi màn này.
 *   ② Ngôn ngữ — cùng tuỳ chọn với toggle trong menu avatar, một nguồn
 *     (`useLang`, localStorage). KHÔNG import `LangToggle` của shell: đó là
 *     component của shell, màn feature tự vẽ hai radio bằng `useLang()`.
 *   ③ Mật khẩu — tài khoản Google-only (`coMatKhau: false`) thấy câu giải
 *     thích thay vì hai ô nhập (khối tách sang `KhoiMatKhau.tsx`).
 *
 * Form sửa hồ sơ MOUNT MỚI mỗi lần bấm «Sửa» (state khởi tạo từ session lúc
 * mount) và UNMOUNT hẳn khi xem — «Huỷ» vì thế tự đặt lại: lần Sửa sau không
 * còn chữ gõ dở, và chế độ xem không để lại ô nhập nào trong DOM.
 *
 * Lưu xong ghi `Session` server trả về THẲNG vào cache `['session']` (cùng lối
 * `LoginForm`/`switchWorkspace`) — tên + avatar ở chân sidebar đổi ngay.
 */
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { O_CHUNG } from '@/components/ui/Truong'
import { CO_EN, useLang } from '@/i18n'
import { useSession } from '@/lib/session'
import type { SessionUser } from '@/lib/session'
import { LoiApi } from '@/lib/http'
import { suaHoSo } from '../api'
import { DoiAvatarDialog } from './DoiAvatarDialog'
import { KhoiMatKhau } from './KhoiMatKhau'

export const THE = 'rounded-xl border border-border bg-surface p-5'
export const TIEU_DE_THE = 'mb-4 text-the font-semibold text-fg'
const NHAN = 'mb-1.5 block text-phu text-muted'
const LUOI = 'grid gap-x-6 gap-y-4 md:grid-cols-2'

export function HoSoScreen() {
  const { t } = useLang()
  const { session } = useSession()
  const [dangSua, setDangSua] = useState(false)
  const [moAvatar, setMoAvatar] = useState(false)
  const u = session.user

  return (
    <div className="space-y-3.5 px-7 py-6 max-md:px-4 max-md:py-4">
      <section className={THE}>
        <h2 className={TIEU_DE_THE}>{t({ vi: 'Hồ sơ', en: 'Profile' })}</h2>

        <div className="flex items-start gap-5">
          {/* Avatar LUÔN hiện ở cả hai chế độ — nó không phải một ô của form,
              đổi qua dialog riêng. Ảnh bo bằng chính nó, span không overflow. */}
          <div className="flex flex-col items-center gap-2.5">
            <span
              aria-hidden="true"
              className="grid size-16 flex-none place-items-center overflow-hidden rounded-full bg-ac text-[20px] font-bold text-white"
            >
              {u.avatar ? <img src={u.avatar} alt="" className="size-full" /> : u.initials}
            </span>
            <button
              type="button"
              onClick={() => setMoAvatar(true)}
              className={`${NUT_PHU} !h-8 !px-3 !text-phu`}
            >
              {t({ vi: 'Đổi avatar', en: 'Change avatar' })}
            </button>
          </div>

          <div className="min-w-0 flex-1">
            {dangSua ? (
              <FormHoSo u={u} onDong={() => setDangSua(false)} />
            ) : (
              <XemHoSo u={u} onSua={() => setDangSua(true)} />
            )}
          </div>
        </div>
      </section>

      {/* Ẩn khi EN tắt (`CO_EN`, i18n) — chỉ khung có bản dịch, chưa phải nội dung màn. */}
      {CO_EN && (
        <section className={THE}>
          <h2 className={TIEU_DE_THE}>{t({ vi: 'Ngôn ngữ hiển thị', en: 'Display language' })}</h2>
          <ChonNgonNgu />
        </section>
      )}

      <KhoiMatKhau />

      {moAvatar && <DoiAvatarDialog onDong={() => setMoAvatar(false)} />}
    </div>
  )
}

function XemHoSo({ u, onSua }: { u: SessionUser; onSua: () => void }) {
  const { t } = useLang()
  const chuaDat = t({ vi: 'Chưa đặt', en: 'Not set' })
  return (
    <>
      {/* Cùng ô, cùng thứ tự, cùng nhãn với form bên dưới — người bấm Sửa phải
          tìm lại đúng ô vừa đọc. Ô rỗng nói thành chữ, không để <dd> trống. */}
      <dl className={LUOI}>
        <DongHoSo nhan={t({ vi: 'Họ tên', en: 'Full name' })}>{u.name}</DongHoSo>
        <DongHoSo nhan={t({ vi: 'Số điện thoại', en: 'Phone' })}>{u.phone ?? chuaDat}</DongHoSo>
        <DongHoSo nhan={t({ vi: 'Chức danh', en: 'Job title' })}>{u.jobTitle ?? chuaDat}</DongHoSo>
        <DongHoSo nhan="Email">{u.email}</DongHoSo>
      </dl>
      <div className={`${HANG_NUT} mt-4`}>
        <button type="button" onClick={onSua} className={NUT_PHU}>
          {t({ vi: 'Sửa hồ sơ', en: 'Edit profile' })}
        </button>
      </div>
    </>
  )
}

function DongHoSo({ nhan, children }: { nhan: string; children: string }) {
  return (
    <div>
      <dt className="text-phu text-muted">{nhan}</dt>
      <dd className="mt-0.5 text-[14px] text-fg">{children}</dd>
    </div>
  )
}

function FormHoSo({ u, onDong }: { u: SessionUser; onDong: () => void }) {
  const { t } = useLang()
  const queryClient = useQueryClient()
  const [ten, setTen] = useState(u.name)
  const [sdt, setSdt] = useState(u.phone ?? '')
  const [chucDanh, setChucDanh] = useState(u.jobTitle ?? '')

  const luu = useMutation({
    mutationFn: suaHoSo,
    onSuccess: (moi) => {
      queryClient.setQueryData(['session'], moi)
      onDong()
    },
  })

  function gui(e: React.FormEvent) {
    e.preventDefault()
    if (!ten.trim() || luu.isPending) return
    luu.mutate({
      name: ten.trim(),
      phone: sdt.trim() || null,
      jobTitle: chucDanh.trim() || null,
    })
  }

  return (
    <form onSubmit={gui}>
      <div className={LUOI}>
        <div>
          <label htmlFor="hs-ten" className={NHAN}>
            {t({ vi: 'Họ tên', en: 'Full name' })}
          </label>
          <input
            id="hs-ten"
            value={ten}
            onChange={(e) => setTen(e.target.value)}
            maxLength={120}
            className={O_CHUNG}
          />
        </div>
        <div>
          <label htmlFor="hs-sdt" className={NHAN}>
            {t({ vi: 'Số điện thoại', en: 'Phone' })}
          </label>
          <input
            id="hs-sdt"
            value={sdt}
            onChange={(e) => setSdt(e.target.value)}
            maxLength={32}
            className={O_CHUNG}
          />
        </div>
        <div>
          <label htmlFor="hs-chuc-danh" className={NHAN}>
            {t({ vi: 'Chức danh', en: 'Job title' })}
          </label>
          <input
            id="hs-chuc-danh"
            value={chucDanh}
            onChange={(e) => setChucDanh(e.target.value)}
            maxLength={120}
            className={O_CHUNG}
          />
        </div>
        <div>
          {/* KHÔNG phải ô nhập — kể cả readonly (cùng lý «Mã workspace»):
              chuỗi để ĐỌC, và một ô có viền mời người ta gõ vào rồi không cho. */}
          <p className={NHAN}>Email</p>
          <p className="py-[11px] text-[14px] leading-[1.5] text-nav">{u.email}</p>
        </div>
      </div>

      {luu.error && (
        <p
          role="alert"
          className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] text-badge-alert-fg"
        >
          {luu.error instanceof LoiApi
            ? luu.error.message
            : t({ vi: 'Không lưu được hồ sơ', en: 'Could not save the profile' })}
        </p>
      )}

      <div className={`${HANG_NUT} mt-4`}>
        <button type="button" onClick={onDong} className={NUT_PHU}>
          {t({ vi: 'Huỷ', en: 'Cancel' })}
        </button>
        <button type="submit" disabled={!ten.trim() || luu.isPending} className={NUT_CHINH}>
          {luu.isPending ? t({ vi: 'Đang lưu…', en: 'Saving…' }) : t({ vi: 'Lưu', en: 'Save' })}
        </button>
      </div>
    </form>
  )
}

function ChonNgonNgu() {
  const { lang, setLang, t } = useLang()
  const MUC = [
    { ma: 'vi' as const, nhan: 'Tiếng Việt' },
    { ma: 'en' as const, nhan: 'English' },
  ]
  return (
    <div
      role="radiogroup"
      aria-label={t({ vi: 'Ngôn ngữ hiển thị', en: 'Display language' })}
      className="flex gap-2"
    >
      {MUC.map((m) => (
        <button
          key={m.ma}
          type="button"
          role="radio"
          aria-checked={lang === m.ma}
          onClick={() => setLang(m.ma)}
          className={`${NUT_PHU} ${lang === m.ma ? '!border-ac bg-acs' : ''}`}
        >
          {m.nhan}
        </button>
      ))}
    </div>
  )
}
