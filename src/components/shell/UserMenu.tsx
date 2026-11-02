/**
 * ĐÁY panel — bạn là ai, và hai việc thuộc về chính bạn: Hồ sơ · Đăng xuất.
 *
 * Tách ra khỏi `WorkspaceSwitcher` khi sidebar thành rail + panel (2026-08-07).
 * Lý do tách nằm ở đầu `WorkspaceSwitcher.tsx` — tóm tắt: hai menu giờ ở hai
 * đầu một cột cao ngang màn hình, không còn tranh nhau một góc 8px.
 *
 * Khối danh tính (tên · email · tổ chức · vai trò tổ chức) là thứ DUY NHẤT
 * trên màn phân biệt được hai tài khoản của hai tổ chức khác nhau — danh sách
 * workspace ở đỉnh panel chỉ nói có chừng này, không nói vì sao chừng này.
 *
 * Disclosure, không phải `role="menu"` — cùng lý do và cùng khuôn `WorkspaceSwitcher`
 * (đọc khối «DISCLOSURE» ở đầu tệp đó).
 */
import { useId, useRef, useState } from 'react'
import { useDongKhiRaNgoai } from '@/lib/dongKhiRaNgoai'
import { Link } from '@tanstack/react-router'
import { Icon } from '@/components/icons'
import { CO_EN, useLang } from '@/i18n'
import { useSession } from '@/lib/session'
import { LangToggle } from './LangToggle'

// `OrgRoleBadge` XOÁ 2026-08-15: `session.orgRole` không còn — tầng tổ chức đã
// bỏ ở backend (migration 0105/0106), chỉ còn vai trò TRONG workspace.

export function UserMenu() {
  const { t } = useLang()
  const { session, dangXuat } = useSession()
  const [open, setOpen] = useState(false)
  const [dangThoat, setDangThoat] = useState(false)
  const [loiThoat, setLoiThoat] = useState<string | null>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const nutRef = useRef<HTMLButtonElement>(null)
  const idKhoi = useId()

  useDongKhiRaNgoai(boxRef, open, (e) => {
    setOpen(false)
    if (e.type === 'keydown') nutRef.current?.focus()
  })

  return (
    /* `border-border` (n4) chứ không `border-soft` (n3): n3 giờ LÀ nền panel, một
       đường kẻ cùng màu nền là không có đường kẻ nào. */
    <div ref={boxRef} className="relative border-t border-border p-2.5">
      <button
        ref={nutRef}
        type="button"
        aria-expanded={open}
        aria-controls={idKhoi}
        onClick={() => setOpen(!open)}
        className="flex w-full min-w-0 items-center gap-2 rounded-md px-1.5 py-1.5 text-left hover:bg-fill"
      >
        {/* `aria-hidden`: ô initials LẶP LẠI đúng cái tên nằm ngay cạnh nó, nên
            không có nó thì tên nút đọc lên là «TĐ Trần Hải Đăng» — một cụm chữ
            cái vô nghĩa đứng trước mỗi lần trình đọc màn hình đọc nút này. Nó
            là hình, không phải thông tin. */}
        {/* Có avatar (DiceBear, backend trả kèm /me) thì ẢNH thay ô chữ; backend
            cũ chưa trả trường này thì giữ initials như trước. Ảnh bo bằng chính
            nó — span cha không overflow-hidden. */}
        <span
          aria-hidden="true"
          className="grid size-7 flex-none place-items-center overflow-hidden rounded-md bg-ac text-nhan font-bold text-white"
        >
          {session.user.avatar ? (
            <img src={session.user.avatar} alt="" className="size-full" />
          ) : (
            session.user.initials
          )}
        </span>
        <span className="min-w-0 flex-1 truncate text-than font-semibold leading-[1.3]">
          {session.user.name}
        </span>
        <Icon
          name="caret"
          strokeWidth={2}
          /* Menu này bật LÊN (`bottom-[calc(100%-2px)]` bên dưới), nên mũi tên
             lúc đóng phải chỉ LÊN — ngược với `WorkspaceSwitcher` ở đỉnh panel,
             nơi menu đổ xuống. Bản trước chép nguyên chiều xoay của switcher và
             chỉ xuống trong khi menu đi lên. */
          className={`size-[13px] flex-none text-muted-2 transition-transform duration-150 ${open ? 'rotate-90' : '-rotate-90'}`}
        />
      </button>

      {open && (
        <div
          id={idKhoi}
          role="group"
          aria-label={t({ vi: 'Tài khoản', en: 'Account' })}
          className="absolute bottom-[calc(100%-2px)] left-2.5 z-60 w-[236px] rounded-xl border border-border-field bg-surface p-1.5 shadow-menu-len"
        >
          <div className="flex items-center gap-2.5 px-[11px] pb-2 pt-2">
            <span
              aria-hidden="true"
              className="grid size-8 flex-none place-items-center overflow-hidden rounded-lg bg-ac text-phu font-bold text-white"
            >
              {session.user.avatar ? (
                <img src={session.user.avatar} alt="" className="size-full" />
              ) : (
                session.user.initials
              )}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-than font-semibold leading-[1.35]">
                {session.user.name}
              </span>
              <span className="block truncate text-nhan leading-[1.35] text-muted-2">
                {session.user.email}
              </span>
            </span>
          </div>
          <div className="mx-1 my-1.5 h-px bg-border-soft" />
          <Link
            to="/settings"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2.5 rounded-lg px-[11px] py-2 text-than text-nav hover:bg-bg"
          >
            <Icon name="settings" className="size-[15px] flex-none opacity-85" />
            {t({ vi: 'Hồ sơ & tuỳ chọn', en: 'Profile & preferences' })}
          </Link>

          {/* NGÔN NGỮ Ở ĐÂY, không ở thanh trên (người dùng chốt 2026-08-09).
              Đứng ngay dưới «Hồ sơ & tuỳ chọn» vì nó CHÍNH LÀ một tuỳ chọn — và
              đây là menu người ta mở khi đi tìm tuỳ chọn.

              KHÔNG đóng menu khi bấm: cả giao diện đổi chữ ngay tại chỗ, và một
              menu tự sập lúc đó thì người dùng mất luôn khung tham chiếu để biết
              mình vừa đổi sang cái gì. Hai mục còn lại đóng menu vì chúng ĐI
              chỗ khác; mục này thì không đi đâu cả. */}
          {/* Cả hàng ẩn khi EN tắt (`CO_EN`, i18n) — một hàng «Ngôn ngữ» chỉ còn VI là
              một lựa chọn không chọn được gì. */}
          {CO_EN && (
            <div className="flex items-center gap-2.5 rounded-lg px-[11px] py-1.5">
              <Icon name="ngonNgu" className="size-[15px] flex-none text-nav opacity-85" />
              <span className="min-w-0 flex-1 text-than text-nav">
                {t({ vi: 'Ngôn ngữ', en: 'Language' })}
              </span>
              <LangToggle />
            </div>
          )}

          <div className="mx-1 my-1.5 h-px bg-border-soft" />
          <button
            type="button"
            disabled={dangThoat}
            onClick={() => {
              setLoiThoat(null)
              setDangThoat(true)
              // Menu KHÔNG đóng ở đây, khác với đổi workspace: nếu request hỏng
              // thì lỗi phải hiện ở đâu đó, và chỗ duy nhất còn lại là menu này.
              void dangXuat()
                .catch((e: unknown) => {
                  setLoiThoat(e instanceof Error ? e.message : 'Không đăng xuất được')
                })
                .finally(() => setDangThoat(false))
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-[11px] py-2 text-left text-than font-semibold text-badge-alert-fg hover:bg-badge-alert-bg disabled:opacity-60"
          >
            <Icon name="logout" className="size-[15px] flex-none" />
            {dangThoat
              ? t({ vi: 'Đang đăng xuất…', en: 'Signing out…' })
              : t({ vi: 'Đăng xuất', en: 'Sign out' })}
          </button>
          {loiThoat && (
            /* `role="alert"` để trình đọc màn hình đọc ngay — người dùng vừa
               bấm một nút mà màn hình không đổi gì, im lặng là tệ nhất. */
            <p
              role="alert"
              className="mx-[11px] mb-1 mt-0.5 text-phu leading-[1.45] text-badge-alert-fg"
            >
              {loiThoat}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
