import { type KeyboardEvent, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Icon } from '@/components/icons'
import { CAO_O } from '@/components/ui/Bang'
import { BAC_LEAD, NGHIA_BAC, NHAN_BAC, type LocStage as GiaLoc } from '../lead'
import { ChipStage } from './ChipStage'

/**
 * Bộ lọc stage — MỘT ô 36px, bấm mới mở menu (người dùng chốt 2026-09-30: bày sáu nút
 * ra thì chiếm chỗ). Không dùng `<select>` gốc: option gốc không vẽ được chip màu, mà
 * chip trong menu là thứ dạy màu nào là bậc nào.
 *
 * Menu PORTAL ra `document.body`, `position: fixed` theo toạ độ nút: tấm nền
 * `KhachList` mang `overflow-hidden`, lọc ra 0 khách thì tấm nền chỉ cao ~200px và
 * một menu `absolute` bị cắt mất (cùng bài học `HopTip`, CLAUDE.md 2026-08-14).
 * Menu `fixed` không đi theo nút khi cuộn ⇒ cuộn/đổi cỡ cửa sổ là đóng.
 */
const MUC: readonly { gia: GiaLoc | undefined; nhan: string }[] = [
  { gia: undefined, nhan: 'Tất cả' },
  ...BAC_LEAD.map((b) => ({ gia: b, nhan: NHAN_BAC[b] })),
  { gia: 'none', nhan: 'Chưa phân loại' },
]

const RONG_MENU = 220
const CAO_MENU_UOC = 290 // 6 mục × ~36px + 2 kẻ + đệm — đủ để quyết lật, không cần đo

export function LocStage({
  gia,
  doi,
}: {
  gia: GiaLoc | undefined
  doi: (v: GiaLoc | undefined) => void
}) {
  const [mo, setMo] = useState(false)
  const [viTri, setViTri] = useState<{ left: number; top: number } | null>(null)
  const nutRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const mucRef = useRef<(HTMLButtonElement | null)[]>([])
  const dangChon = Math.max(
    0,
    MUC.findIndex((m) => m.gia === gia),
  )

  useLayoutEffect(() => {
    if (!mo || !nutRef.current) return
    const r = nutRef.current.getBoundingClientRect()
    const latLen = r.bottom + 6 + CAO_MENU_UOC > window.innerHeight && r.top - 6 - CAO_MENU_UOC > 0
    setViTri({ left: r.left, top: latLen ? r.top - 6 - CAO_MENU_UOC : r.bottom + 6 })
  }, [mo])

  useEffect(() => {
    if (!mo) return
    mucRef.current[dangChon]?.focus()
    const dong = () => setMo(false)
    const bamNgoai = (e: MouseEvent) => {
      const t = e.target as Node
      if (!menuRef.current?.contains(t) && !nutRef.current?.contains(t)) dong()
    }
    document.addEventListener('mousedown', bamNgoai)
    window.addEventListener('scroll', dong, true)
    window.addEventListener('resize', dong)
    return () => {
      document.removeEventListener('mousedown', bamNgoai)
      window.removeEventListener('scroll', dong, true)
      window.removeEventListener('resize', dong)
    }
  }, [mo, dangChon])

  const chon = (v: GiaLoc | undefined) => {
    doi(v)
    setMo(false)
    nutRef.current?.focus()
  }

  const phim = (e: KeyboardEvent) => {
    const i = mucRef.current.findIndex((el) => el === document.activeElement)
    if (e.key === 'Escape') {
      e.preventDefault()
      setMo(false)
      nutRef.current?.focus()
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      const buoc = e.key === 'ArrowDown' ? 1 : -1
      mucRef.current[(i + buoc + MUC.length) % MUC.length]?.focus()
    }
  }

  const lopNut = mo
    ? 'border border-ac bg-surface ring-[3px] ring-acs'
    : gia
      ? 'border border-ac bg-surface'
      : 'border border-border-field bg-bg'

  return (
    <>
      <button
        ref={nutRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={mo}
        onClick={() => setMo((v) => !v)}
        className={`${CAO_O} ${lopNut} flex min-w-[176px] cursor-pointer items-center gap-2 rounded-md pl-3 pr-2.5 text-than max-md:min-w-0`}
      >
        <span className="text-muted-2">Stage</span>
        {gia && gia !== 'none' ? (
          <ChipStage stage={gia} />
        ) : (
          <span className="font-medium text-fg">
            {gia === 'none' ? 'Chưa phân loại' : 'Tất cả'}
          </span>
        )}
        <span className={`ml-auto text-muted-2 transition-transform ${mo ? 'rotate-180' : ''}`}>
          <Icon name="moXuong" className="size-3.5" />
        </span>
      </button>
      {mo &&
        createPortal(
          <div
            ref={menuRef}
            role="menu"
            aria-label="Lọc theo stage"
            onKeyDown={phim}
            style={
              viTri ? { left: viTri.left, top: viTri.top, width: RONG_MENU } : { width: RONG_MENU }
            }
            className="fixed z-[80] rounded-lg border border-border-strong bg-surface p-1.5 shadow-menu"
          >
            {MUC.map((m, i) => (
              <div key={m.nhan}>
                {(i === 1 || i === MUC.length - 1) && (
                  <hr className="mx-1 my-1 border-border-soft" />
                )}
                <button
                  ref={(el) => {
                    mucRef.current[i] = el
                  }}
                  type="button"
                  role="menuitemradio"
                  aria-checked={m.gia === gia}
                  onClick={() => chon(m.gia)}
                  className={`flex w-full cursor-pointer items-center gap-2.5 rounded-sm px-2.5 py-[7px] text-left text-than outline-none focus-visible:bg-n2 focus-visible:ring-2 focus-visible:ring-ac focus-visible:ring-inset ${
                    m.gia === gia ? 'bg-acs' : 'hover:bg-n2'
                  }`}
                >
                  {m.gia && m.gia !== 'none' ? (
                    <>
                      <ChipStage stage={m.gia} />
                      {/* Nghĩa của bậc ngay trong menu — chỗ người ta CHỌN bậc là chỗ cần biết
                          MQL khác SQL ở đâu. Vào tên truy cập luôn: «SQL đủ điều kiện mua». */}
                      <span className="text-phu text-muted">{NGHIA_BAC[m.gia]}</span>
                    </>
                  ) : (
                    <span className="text-muted">{m.nhan}</span>
                  )}
                  {/* Icon SVG chứ không ký tự ✓: ký tự lọt vào tên truy cập và `textContent`
                      của mục («SQL ✓»), nên trình đọc màn hình đọc thừa một dấu. */}
                  <Icon
                    name="check"
                    className={`ml-auto size-3.5 text-ac ${m.gia === gia ? '' : 'invisible'}`}
                  />
                </button>
              </div>
            ))}
          </div>,
          document.body,
        )}
    </>
  )
}
