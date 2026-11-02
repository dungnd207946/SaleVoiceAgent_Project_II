/**
 * Ba hộp thoại của role người dùng agent — thêm · sửa (tên + icon) · xoá (backend `0967`).
 *
 * Cả ba ÁP DỤNG NGAY khi xác nhận (xem `useVaiTro.ts`), nên câu cuối mỗi hộp nói thẳng
 * điều đó — người đang ở chế độ Sửa sẽ tưởng phải chờ «Lưu và áp dụng».
 *
 * Khung là `HopThoai` (`KHUNG_HOP_THOAI`) như `LuuApDungDialog.tsx` — hai bộ dialog của cùng
 * màn phải trông như nhau.
 */
import {
  useEffect,
  useId,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent as PhimReact,
  type ReactNode,
} from 'react'
import { Icon } from '@/components/icons'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import type { VaiTroMeta } from '../api'
import { ICON_VAI_TRO, iconCua, iconGoiY } from '../iconVaiTro'
import { NUT_CHINH, NUT_PHU, O_LOP } from './lop'

/** Khớp `contracts._ten_role` phía backend. */
const TEN_ROLE_TOI_DA = 40

function Vo(props: { tieuDe: string; dong: () => void; khoaDong: boolean; children: ReactNode }) {
  return (
    <HopThoai
      onDong={props.dong}
      khoaDong={props.khoaDong}
      aria-label={props.tieuDe}
      className={`${KHUNG_HOP_THOAI} max-w-[460px]`}
    >
      <h2 className="text-[16.5px] font-semibold leading-tight text-fg">{props.tieuDe}</h2>
      {props.children}
    </HopThoai>
  )
}

function KhoiLoi({ loi }: { loi: string }) {
  return (
    <p
      role="alert"
      className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] font-medium text-badge-alert-fg"
    >
      {loi}
    </p>
  )
}

function GhiChu({ children }: { children: ReactNode }) {
  return <p className="mt-3.5 text-phu leading-[1.5] text-muted-2">{children}</p>
}

function HangNut(props: {
  dangGui: boolean
  nhanChinh: string
  nhanDangGui: string
  khoaChinh?: boolean
  onDong: () => void
  onChinh?: () => void
}) {
  return (
    <div className="mt-5 flex items-center justify-end gap-2">
      <button type="button" onClick={props.onDong} disabled={props.dangGui} className={NUT_PHU}>
        Huỷ
      </button>
      <button
        type={props.onChinh ? 'button' : 'submit'}
        onClick={props.onChinh}
        disabled={props.dangGui || props.khoaChinh}
        className={NUT_CHINH}
      >
        {props.dangGui ? props.nhanDangGui : props.nhanChinh}
      </button>
    </div>
  )
}

/**
 * Bộ chọn icon — lưới ô vuông, khuôn `radiogroup` (WAI-ARIA): mũi tên đi giữa các ô, chỉ ô
 * đang chọn nằm trong vòng Tab. Hình đang dùng ở role KHÁC được đánh dấu chấm nhỏ chứ
 * không bị khoá: trùng hình vẫn hợp lệ, chỉ là không nên — chặn cứng thì tới role thứ
 * mười tám là hết đường chọn.
 */
function ChonIcon(props: {
  chon: string
  doi: (ma: string) => void
  daDung: ReadonlySet<string>
  khoa: boolean
}) {
  const id = useId()
  const refs = useRef<(HTMLButtonElement | null)[]>([])
  const iChon = Math.max(
    0,
    ICON_VAI_TRO.findIndex((i) => i.ma === props.chon),
  )

  function phim(e: PhimReact) {
    const buoc = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key]
    if (!buoc) return
    e.preventDefault()
    const n = ICON_VAI_TRO.length
    const moi = (iChon + buoc + n) % n
    props.doi((ICON_VAI_TRO[moi] as (typeof ICON_VAI_TRO)[number]).ma)
    refs.current[moi]?.focus()
  }

  return (
    <>
      <p id={id} className="mt-3.5 mb-1.5 text-phu text-muted">
        Icon
      </p>
      <div
        role="radiogroup"
        aria-labelledby={id}
        onKeyDown={phim}
        className="grid grid-cols-9 gap-1.5 max-md:grid-cols-6"
      >
        {ICON_VAI_TRO.map((i, k) => {
          const dangChon = i.ma === props.chon
          return (
            <button
              key={i.ma}
              ref={(el) => {
                refs.current[k] = el
              }}
              type="button"
              role="radio"
              aria-checked={dangChon}
              aria-label={i.nhan}
              title={i.nhan}
              tabIndex={dangChon ? 0 : -1}
              disabled={props.khoa}
              onClick={() => props.doi(i.ma)}
              className={`relative grid aspect-square cursor-pointer place-items-center rounded-md border transition-[color,background-color,border-color,transform] duration-150 active:scale-95 ${
                dangChon
                  ? 'border-ac bg-acs text-ac'
                  : 'border-border bg-surface text-muted hover:border-border-strong hover:text-fg'
              }`}
            >
              <Icon name={i.icon} className="size-[18px]" />
              {props.daDung.has(i.ma) && !dangChon && (
                <span
                  aria-hidden="true"
                  className="absolute top-1 right-1 size-1.5 rounded-full bg-muted-3"
                />
              )}
            </button>
          )
        })}
      </div>
    </>
  )
}

/** Ô tên dùng chung cho Thêm và Sửa. */
function OTen(props: { giaTri: string; doi: (v: string) => void; khoa: boolean }) {
  const id = useId()
  const ref = useRef<HTMLInputElement>(null)
  useEffect(() => {
    ref.current?.focus()
    ref.current?.select()
  }, [])
  return (
    <>
      <label htmlFor={id} className="mb-1.5 block text-phu text-muted">
        Tên role
      </label>
      <input
        ref={ref}
        id={id}
        value={props.giaTri}
        onChange={(e) => props.doi(e.target.value)}
        maxLength={TEN_ROLE_TOI_DA}
        disabled={props.khoa}
        placeholder="VD: Nhà đầu tư"
        className={O_LOP}
      />
    </>
  )
}

// ─── Thêm ───────────────────────────────────────────────────────────────────

export function ThemRoleDialog(props: {
  vaiTro: VaiTroMeta[]
  dangGui: boolean
  loi: string | null
  onDong: () => void
  /** Role mới LUÔN bắt đầu từ bộ mặc định của nền tảng (người dùng chốt 2026-09-30) —
   *  không chép từ role nào. Phần chung (Danh tính · Chuẩn hoá cách đọc) vẫn khớp mọi role
   *  vì `useBanNhap` ép nó theo role gốc. */
  onTao: (ten: string, icon: string) => void
}) {
  const [ten, setTen] = useState('')
  // Gợi ý hình CHƯA ai dùng — mở hộp là đã có một icon khác mọi tab đang có.
  const [icon, setIcon] = useState(() => iconGoiY(props.vaiTro))

  function gui(e: FormEvent) {
    e.preventDefault()
    if (props.dangGui || ten.trim() === '') return
    props.onTao(ten.trim(), icon)
  }

  return (
    <Vo tieuDe="Thêm role" dong={props.onDong} khoaDong={props.dangGui}>
      <form onSubmit={gui} className="mt-4 flex flex-col">
        <OTen giaTri={ten} doi={setTen} khoa={props.dangGui} />
        <ChonIcon
          chon={icon}
          doi={setIcon}
          daDung={new Set(props.vaiTro.map((v) => v.icon ?? ''))}
          khoa={props.dangGui}
        />

        {props.loi && <KhoiLoi loi={props.loi} />}

        <HangNut
          dangGui={props.dangGui}
          nhanChinh="Thêm role"
          nhanDangGui="Đang thêm…"
          khoaChinh={ten.trim() === ''}
          onDong={props.onDong}
        />
      </form>
    </Vo>
  )
}

// ─── Sửa (tên + icon) ────────────────────────────────────────────────────────

export function SuaRoleDialog(props: {
  role: VaiTroMeta
  /** Mọi role — để đánh dấu hình đang dùng ở role KHÁC. */
  vaiTro: VaiTroMeta[]
  dangGui: boolean
  loi: string | null
  onDong: () => void
  onSua: (thay: { ten?: string; icon?: string }) => void
}) {
  const [ten, setTen] = useState(props.role.ten)
  // Role chưa có mã icon (NULL) ⇒ bộ chọn mở ở đúng hình tab đang hiện, không ở ô đầu.
  const iconDangHien =
    ICON_VAI_TRO.find((i) => i.icon === iconCua(props.role))?.ma ?? ICON_VAI_TRO[0]!.ma
  const [icon, setIcon] = useState(props.role.icon ?? iconDangHien)
  const doiTen = ten.trim() !== props.role.ten
  const doiIcon = icon !== (props.role.icon ?? iconDangHien)

  function gui(e: FormEvent) {
    e.preventDefault()
    if (props.dangGui || ten.trim() === '' || (!doiTen && !doiIcon)) return
    // Chỉ gửi thứ ĐÃ đổi: backend chỉ tăng `version` (agent dựng lại runner) khi tên đổi.
    props.onSua({ ...(doiTen ? { ten: ten.trim() } : {}), ...(doiIcon ? { icon } : {}) })
  }

  return (
    <Vo tieuDe={`Sửa ${props.role.ten}`} dong={props.onDong} khoaDong={props.dangGui}>
      <form onSubmit={gui} className="mt-4 flex flex-col">
        <OTen giaTri={ten} doi={setTen} khoa={props.dangGui} />
        <ChonIcon
          chon={icon}
          doi={setIcon}
          daDung={
            new Set(props.vaiTro.filter((v) => v.key !== props.role.key).map((v) => v.icon ?? ''))
          }
          khoa={props.dangGui}
        />
        {props.loi && <KhoiLoi loi={props.loi} />}
        <GhiChu>Chỉ đổi tên và icon hiển thị — cấu hình của role giữ nguyên.</GhiChu>
        <HangNut
          dangGui={props.dangGui}
          nhanChinh="Lưu"
          nhanDangGui="Đang lưu…"
          khoaChinh={ten.trim() === '' || (!doiTen && !doiIcon)}
          onDong={props.onDong}
        />
      </form>
    </Vo>
  )
}

// ─── Xoá ────────────────────────────────────────────────────────────────────

export function XoaRoleDialog(props: {
  role: VaiTroMeta
  dangGui: boolean
  loi: string | null
  onDong: () => void
  onXoa: () => void
}) {
  return (
    <Vo tieuDe={`Xoá ${props.role.ten}?`} dong={props.onDong} khoaDong={props.dangGui}>
      <p className="mt-3 text-than leading-[1.55] text-fg">
        Role và toàn bộ cấu hình riêng của nó (Phạm vi, Giọng điệu, Kỹ năng chung) bị xoá ngay,
        không khôi phục được. Agent sẽ không còn phục vụ theo role này.
      </p>
      {props.loi && <KhoiLoi loi={props.loi} />}
      <HangNut
        dangGui={props.dangGui}
        nhanChinh="Xoá role"
        nhanDangGui="Đang xoá…"
        onDong={props.onDong}
        onChinh={props.onXoa}
      />
    </Vo>
  )
}
