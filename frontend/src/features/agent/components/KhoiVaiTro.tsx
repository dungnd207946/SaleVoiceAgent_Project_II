/**
 * Khối cấu hình RIÊNG theo role của `/agent` — mỗi role một tab + các thẻ tab đó đổi (Phạm
 * vi · Giọng điệu · Kỹ năng chung). Dùng CHUNG cho chế độ xem và sửa: bố cục không nhảy khi
 * bấm Sửa, và state tab sống ở `AgentStudio` nên tab đang mở giữ nguyên.
 *
 * ── TAB GẮN VÀO KHUNG (người dùng chốt 2026-09-29) ─────────────────────────────────────
 * Hàng tab LÀ đầu khung; gạch chân accent của tab đang mở đè lên kẻ đáy đầu khung — mắt đi
 * thẳng từ tab xuống đúng phần thân nó điều khiển.
 *
 * ── NHIỀU ROLE: TAB ƯU TIÊN + MENU «+N» (người dùng chốt 2026-09-30) ──────────────────
 * Role là dữ liệu (backend `0967`, tới `soRoleToiDa`), nên hàng tab không được giả định
 * «vừa». Bản trước để tràn ngang: tab thứ năm, sáu trôi khỏi mép phải và không còn đường
 * tới. Nay theo khuôn priority+ (GitHub/Linear): ĐO bề rộng từng tab, hiện bao nhiêu tab
 * vừa, phần còn lại gom vào nút «+N» mở một menu (có ô tìm khi danh sách dài). Ba luật:
 *   · Tab ĐANG MỞ luôn hiện trên hàng — chọn một role từ menu thì nó thế chỗ tab cuối,
 *     không bao giờ «đang mở mà không thấy mình ở đâu».
 *   · Hiện TẤT CẢ khi vừa — nút «+N» chỉ có khi thật sự thiếu chỗ.
 *   · Phím ←/→ trên hàng tab đi qua MỌI role, kể cả role đang nằm trong menu.
 * Đo bằng một hàng tab BÓNG (ẩn, cùng class) thay vì đo tab thật: tab thật đang bị ẩn thì
 * không có bề rộng để đo, và đo-rồi-ẩn-rồi-đo lại là vòng lặp nhấp nháy.
 * jsdom không có bố cục (mọi bề rộng = 0) ⇒ không đo được ⇒ hiện tất cả; test canh phần
 * tràn giả `offsetWidth`/`clientWidth` (khuôn `MenuHang`).
 *
 * ── CHUYỂN ĐỘNG ───────────────────────────────────────────────────────────────────────
 * Gạch chân là MỘT thanh trượt từ tab cũ sang tab mới (`left`/`width`, 300ms), và thân
 * khối trượt vào theo đúng HƯỚNG đó (`tab-vao-phai`/`-trai` ở `theme.css`, 220ms). Cả hai
 * tắt dưới `prefers-reduced-motion`. Lần vẽ đầu KHÔNG trượt (thanh hiện thẳng ở chỗ).
 *
 * ── THAO TÁC ROLE ─────────────────────────────────────────────────────────────────────
 * «+ Thêm role» sau dãy tab; «Sửa»(tên + icon)/«Xoá» của ĐÚNG tab đang mở ở mép phải — gắn
 * vào tab chứ không vào menu riêng, để không bao giờ phải hỏi «xoá role nào?». Role mặc
 * định («Khách hàng») không có nút Xoá (backend chặn cả ở DB). Ba thao tác ÁP DỤNG NGAY.
 * Dưới `lg` các nút chỉ còn icon (tên vẫn ở `aria-label`) để nhường chỗ cho tab.
 *
 * ⚠ NGOẠI LỆ CÓ Ý THỨC của luật 4 Design token («hàng tab dùng `NhomTab`») — kiểu KHÁC HẲN
 * (tab-thuộc-khung, không phải segmented), dùng đúng một chỗ. Có chỗ thứ hai thì chuyển
 * vào `components/ui/`, đừng chép.
 *
 * A11y: `tablist`/`tab`/`tabpanel` (WAI-ARIA Tabs, roving `tabIndex`); nút «+N» là
 * `aria-haspopup="menu"`, menu đi bằng ↑/↓, Enter chọn, Esc đóng và trả focus về nút.
 */
import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from 'react'
import { useDongKhiRaNgoai } from '@/lib/dongKhiRaNgoai'
import { Icon } from '@/components/icons'
import { boDau } from '@/lib/boDau'
import { KEY_ROLE_MAC_DINH, type VaiTro, type VaiTroMeta } from '../api'
import { iconCua } from '../iconVaiTro'
import { soTabVua, tabHien } from '../tabUuTien'
import { cauLoi, useVaiTro } from '../useVaiTro'
import { SuaRoleDialog, ThemRoleDialog, XoaRoleDialog } from './VaiTroDialog'

const TAB =
  'group flex flex-none cursor-pointer items-center gap-2 border-b-2 px-3.5 py-3 text-than font-medium whitespace-nowrap transition-colors'
const TAB_MO = `${TAB} text-fg`
const TAB_DONG = `${TAB} border-transparent text-muted hover:text-fg`

/** Nút thao tác trong hàng tab — chữ nhỏ + icon, không viền: một nút có viền cạnh các tab
 *  đọc thành hành động chính cạnh tranh với chính các tab. */
const NUT_TAC =
  'flex flex-none cursor-pointer items-center gap-1.5 rounded-sm px-2 py-1.5 text-phu font-medium text-muted whitespace-nowrap transition-colors hover:bg-fill-strong hover:text-fg max-md:min-h-10 max-md:min-w-10 max-md:justify-center'

/** Từ bao nhiêu role ẩn thì menu có ô tìm — ít hơn thì liếc là thấy, ô tìm chỉ chiếm chỗ. */
const TIM_TU = 5

type HopThoai = 'them' | 'sua' | 'xoa' | null

export function KhoiVaiTro({
  vaiTro,
  dangMo,
  doi,
  soRoleToiDa,
  children,
}: {
  vaiTro: VaiTroMeta[]
  dangMo: VaiTro
  doi: (r: VaiTro) => void
  soRoleToiDa: number
  children: ReactNode
}) {
  const goc = useId()
  const [hop, setHop] = useState<HopThoai>(null)
  const { mTao, mSua, mXoa } = useVaiTro()

  const keys = vaiTro.map((v) => v.key)
  const roleMo = vaiTro.find((v) => v.key === dangMo)
  const coThem = vaiTro.length < soRoleToiDa

  // ── Đo & chia ───────────────────────────────────────────────────────────
  const dauKhung = useRef<HTMLDivElement>(null)
  const bong = useRef<HTMLDivElement>(null)
  const phaiRef = useRef<HTMLDivElement>(null)
  const [k, setK] = useState<number | null>(null)
  const [nhip, setNhip] = useState(0)

  useEffect(() => {
    const el = dauKhung.current
    if (!el) return
    const ro = new ResizeObserver(() => setNhip((n) => n + 1))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const chuKy = vaiTro.map((v) => `${v.key}:${v.ten}`).join('|')
  useLayoutEffect(() => {
    const khung = dauKhung.current
    const hangBong = bong.current
    if (!khung || !hangBong) return
    const rong = Array.from(hangBong.children, (c) => (c as HTMLElement).offsetWidth)
    // Chỗ cho tab = bề ngang đầu khung − đệm hai bên (px-2) − cụm nút bên phải.
    const cho = khung.clientWidth - 16 - (phaiRef.current?.offsetWidth ?? 0)
    const moi = soTabVua(rong, cho)
    setK((cu) => (cu === moi ? cu : moi))
  }, [chuKy, nhip, coThem, roleMo?.macDinh])

  const hien = k === null ? keys : tabHien(keys, k, dangMo)
  const an = vaiTro.filter((v) => !hien.includes(v.key))
  const chuoiHien = hien.join('|')

  // ── Gạch chân trượt ─────────────────────────────────────────────────────
  const nut = useRef<Partial<Record<VaiTro, HTMLButtonElement | null>>>({})
  const [gach, setGach] = useState<{ x: number; w: number; truot: boolean } | null>(null)
  useLayoutEffect(() => {
    const el = nut.current[dangMo]
    if (!el || el.offsetWidth === 0) {
      setGach(null)
      return
    }
    const x = el.offsetLeft
    const w = el.offsetWidth
    setGach((cu) => (cu && cu.x === x && cu.w === w ? cu : { x, w, truot: cu !== null }))
  }, [dangMo, chuoiHien, nhip])

  // ── Hướng chuyển tab (cho thân khối trượt vào đúng chiều) ───────────────
  const truoc = useRef<number | null>(null)
  const iMo = keys.indexOf(dangMo)
  const huong =
    truoc.current === null || truoc.current === iMo ? null : iMo > truoc.current ? 'phai' : 'trai'
  useEffect(() => {
    truoc.current = iMo
  }, [iMo])

  // Phím ←/→ có thể trỏ vào role đang nằm trong menu — nó chỉ có nút sau lần vẽ kế tiếp.
  const canFocus = useRef<VaiTro | null>(null)
  useLayoutEffect(() => {
    if (canFocus.current && canFocus.current === dangMo) {
      nut.current[dangMo]?.focus()
      canFocus.current = null
    }
  })

  function phim(e: KeyboardEvent) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const moi =
      keys[(iMo + (e.key === 'ArrowRight' ? 1 : -1) + keys.length) % keys.length] ?? dangMo
    canFocus.current = moi
    doi(moi)
  }

  function mo(h: Exclude<HopThoai, null>) {
    mTao.reset()
    mSua.reset()
    mXoa.reset()
    setHop(h)
  }

  return (
    <section className="rounded-lg border border-border-strong">
      <div
        ref={dauKhung}
        className="relative flex items-center gap-1 rounded-t-lg border-b border-border bg-surface px-2"
      >
        {/* Hàng BÓNG để đo — cùng class với tab thật, không nhìn thấy, không đọc được. */}
        <div
          ref={bong}
          aria-hidden="true"
          className="pointer-events-none invisible absolute top-0 left-0 flex gap-1"
        >
          {vaiTro.map((r) => (
            <span key={r.key} className={TAB_DONG}>
              <Icon name={iconCua(r)} className="size-4 flex-none" />
              {r.ten}
            </span>
          ))}
        </div>

        <div
          role="tablist"
          aria-label="Cấu hình theo người dùng agent"
          onKeyDown={phim}
          className="relative -mb-px flex min-w-0 gap-1 self-stretch"
        >
          {hien.map((key) => {
            const r = vaiTro.find((v) => v.key === key) as VaiTroMeta
            const mo = dangMo === key
            return (
              <button
                key={key}
                ref={(el) => {
                  nut.current[key] = el
                }}
                type="button"
                role="tab"
                id={`${goc}-tab-${key}`}
                aria-controls={`${goc}-panel`}
                aria-selected={mo}
                tabIndex={mo ? 0 : -1}
                // Không đo được thanh trượt (jsdom, lần vẽ đầu) ⇒ tab tự kẻ gạch chân.
                className={mo ? `${TAB_MO} ${gach ? 'border-transparent' : 'border-ac'}` : TAB_DONG}
                onClick={() => doi(key)}
              >
                <Icon
                  name={iconCua(r)}
                  className={`size-4 flex-none transition-colors ${mo ? 'text-ac' : ''}`}
                />
                {r.ten}
              </button>
            )
          })}
          {gach && (
            <span
              aria-hidden="true"
              data-testid="gach-tab"
              className={`absolute bottom-0 h-0.5 rounded-full bg-ac motion-safe:ease-[cubic-bezier(0.16,1,0.3,1)] ${
                gach.truot ? 'motion-safe:transition-[left,width] motion-safe:duration-300' : ''
              }`}
              style={{ left: gach.x, width: gach.w }}
            />
          )}
        </div>

        {an.length > 0 && (
          <MenuRoleAn
            an={an}
            chon={(key) => {
              canFocus.current = key
              doi(key)
            }}
          />
        )}

        <div ref={phaiRef} className="ml-auto flex flex-none items-center gap-0.5 pl-1">
          {/* Hết chỗ thì ẨN nút chứ không khoá: một nút xám không lời giải thích bắt người
              dùng đoán; backend vẫn trả 409 có câu nói rõ trần cho ai gọi thẳng API. */}
          {coThem && (
            <button
              type="button"
              className={NUT_TAC}
              aria-label="Thêm role"
              title="Thêm role"
              onClick={() => mo('them')}
            >
              <Icon name="them" className="size-3.5" />
              <span className="max-lg:hidden">Thêm role</span>
            </button>
          )}
          {roleMo && (
            <>
              <span aria-hidden="true" className="mx-1 h-4 w-px bg-border" />
              <button
                type="button"
                className={NUT_TAC}
                aria-label={`Sửa role ${roleMo.ten}`}
                title="Sửa tên và icon"
                onClick={() => mo('sua')}
              >
                <Icon name="edit" className="size-3.5" />
                <span className="max-lg:hidden">Sửa</span>
              </button>
              {!roleMo.macDinh && (
                <button
                  type="button"
                  className={`${NUT_TAC} hover:text-badge-alert-fg`}
                  aria-label={`Xoá role ${roleMo.ten}`}
                  title="Xoá role"
                  onClick={() => mo('xoa')}
                >
                  <Icon name="trash" className="size-3.5" />
                  <span className="max-lg:hidden">Xoá</span>
                </button>
              )}
            </>
          )}
        </div>
      </div>

      <div
        role="tabpanel"
        id={`${goc}-panel`}
        aria-labelledby={`${goc}-tab-${dangMo}`}
        className="overflow-hidden rounded-b-lg bg-surface"
      >
        {/* Các khu trong khung là `The phang`, ngăn bằng kẻ mảnh — không phải thẻ
            viền xếp trong khung viền (quieter 05/10). Đệm đặt ở đây (`*:p-5`) cho
            mọi khu con, để chúng đứng chung một lưới hai cột. */}
        <div
          key={dangMo}
          data-huong={huong ?? ''}
          className={`flex flex-col divide-y divide-border-soft *:p-5 max-md:*:p-4 ${
            huong === 'phai' ? 'tab-vao-phai' : huong === 'trai' ? 'tab-vao-trai' : ''
          }`}
        >
          {children}
        </div>
      </div>

      {hop === 'them' && (
        <ThemRoleDialog
          vaiTro={vaiTro}
          dangGui={mTao.isPending}
          loi={cauLoi(mTao.error)}
          onDong={() => setHop(null)}
          onTao={(ten, icon) =>
            mTao.mutate(
              { ten, saoChepTu: null, icon },
              {
                onSuccess: (r) => {
                  setHop(null)
                  // Mở luôn tab vừa tạo — việc kế tiếp gần như chắc chắn là chỉnh nó.
                  doi(r.key)
                },
              },
            )
          }
        />
      )}
      {hop === 'sua' && roleMo && (
        <SuaRoleDialog
          role={roleMo}
          vaiTro={vaiTro}
          dangGui={mSua.isPending}
          loi={cauLoi(mSua.error)}
          onDong={() => setHop(null)}
          onSua={(thay) =>
            mSua.mutate({ key: roleMo.key, ...thay }, { onSuccess: () => setHop(null) })
          }
        />
      )}
      {hop === 'xoa' && roleMo && !roleMo.macDinh && (
        <XoaRoleDialog
          role={roleMo}
          dangGui={mXoa.isPending}
          loi={cauLoi(mXoa.error)}
          onDong={() => setHop(null)}
          onXoa={() =>
            mXoa.mutate(roleMo.key, {
              onSuccess: () => {
                setHop(null)
                doi(KEY_ROLE_MAC_DINH)
              },
            })
          }
        />
      )}
    </section>
  )
}

/** Nút «+N» + menu các role không vừa hàng tab. */
function MenuRoleAn({ an, chon }: { an: VaiTroMeta[]; chon: (key: VaiTro) => void }) {
  const [mo, setMo] = useState(false)
  const [tim, setTim] = useState('')
  const [sang, setSang] = useState(0)
  const boc = useRef<HTMLDivElement>(null)
  const nutRef = useRef<HTMLButtonElement>(null)
  const oTim = useRef<HTMLInputElement>(null)
  const menuId = useId()

  const loc = tim.trim() ? an.filter((v) => boDau(v.ten).includes(boDau(tim.trim()))) : an

  // Escape trong menu đã qua `phim` (trả focus); hook chỉ còn bắt bấm ra ngoài.
  useDongKhiRaNgoai(boc, mo, () => setMo(false))

  useEffect(() => {
    if (!mo) return
    setSang(0)
    setTim('')
    // Có ô tìm thì con trỏ vào đó (gõ là lọc ngay); không thì vào menu cho ↑/↓ chạy.
    ;(oTim.current ?? boc.current?.querySelector<HTMLElement>('[role="menuitem"]'))?.focus()
  }, [mo])

  function dong(traFocus: boolean) {
    setMo(false)
    if (traFocus) nutRef.current?.focus()
  }

  function phim(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.preventDefault()
      dong(true)
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (loc.length === 0) return
      setSang((s) => (s + (e.key === 'ArrowDown' ? 1 : -1) + loc.length) % loc.length)
    } else if (e.key === 'Enter') {
      const v = loc[sang]
      if (!v) return
      e.preventDefault()
      setMo(false)
      chon(v.key)
    }
  }

  return (
    // Phím bắt ở vỏ (nút + menu), không ở riêng menu: Esc phải đóng được cả khi focus
    // còn nằm trên nút «+N».
    <div ref={boc} onKeyDown={mo ? phim : undefined} className="relative flex-none">
      <button
        ref={nutRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={mo}
        aria-controls={mo ? menuId : undefined}
        aria-label={`${an.length} role khác`}
        onClick={() => setMo((m) => !m)}
        className={`flex cursor-pointer items-center gap-1 rounded-sm px-2 py-1.5 text-phu font-semibold transition-colors ${
          mo ? 'bg-fill-strong text-fg' : 'text-muted hover:bg-fill-strong hover:text-fg'
        }`}
      >
        +{an.length}
        <Icon
          name="moXuong"
          className={`size-3.5 transition-transform duration-200 ${mo ? 'rotate-180' : ''}`}
        />
      </button>

      {mo && (
        <div className="menu-vao absolute top-full left-0 z-30 mt-1.5 w-64 rounded-lg border border-border-field bg-surface p-1 shadow-menu">
          {an.length >= TIM_TU && (
            <div className="relative mb-1">
              <Icon
                name="timKiem"
                className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-2"
              />
              <input
                ref={oTim}
                value={tim}
                onChange={(e) => {
                  setTim(e.target.value)
                  setSang(0)
                }}
                placeholder="Tìm role…"
                aria-label="Tìm role"
                className="w-full rounded-md border border-border bg-surface py-1.5 pr-2 pl-8 text-[13px] outline-none focus:border-ac"
              />
            </div>
          )}
          <div id={menuId} role="menu" aria-label="Role khác" className="max-h-72 overflow-y-auto">
            {loc.map((v, i) => (
              <button
                key={v.key}
                type="button"
                role="menuitem"
                tabIndex={i === sang ? 0 : -1}
                onMouseEnter={() => setSang(i)}
                onClick={() => {
                  setMo(false)
                  chon(v.key)
                }}
                className={`flex w-full cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-than transition-colors ${
                  i === sang ? 'bg-fill-strong text-fg' : 'text-fg'
                }`}
              >
                <span className="grid size-6 flex-none place-items-center rounded-md bg-fill text-muted">
                  <Icon name={iconCua(v)} className="size-3.5" />
                </span>
                <span className="truncate">{v.ten}</span>
              </button>
            ))}
            {loc.length === 0 && (
              <p className="px-2.5 py-2 text-[13px] text-muted">Không có role nào khớp.</p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
