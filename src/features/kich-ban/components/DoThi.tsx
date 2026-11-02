// Sơ đồ cây kịch bản — CHỈ ĐỂ XEM (người dùng chốt 2026-10-01): không kéo nút, không lưu vị trí.
// Gốc → nhóm → tình huống, trái sang phải; màu chấm = tỷ lệ đạt. Bấm một tình huống để mở bảng chi tiết.
// Phóng = đổi viewBox (null = vừa khung). Kéo nền hoặc cuộn để dời; Ctrl/⌘ + cuộn (chụm hai ngón trên
// trackpad) để phóng — kiểu Figma, vì cuộn-là-phóng thì trackpad Mac không dời được.
// Cảm ứng (tablet; điện thoại dùng `DanhSachNut`): một ngón dời, hai ngón chụm để phóng quanh trung
// điểm. Mỗi ngón theo `pointerId` — bản trước ghi đè một biến `keo` cho mọi ngón nên hai ngón làm
// sơ đồ giật qua lại giữa hai vị trí (audit 05/10).
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { Icon } from '@/components/icons'
import type { NutKichBan, SoDoNut } from '../api'
import { HAU_TO_MAU, type LoaiMau } from '../khuon'
import {
  CAY,
  TEN_NHOM,
  boCucCay,
  canh,
  khop,
  mauTiLe,
  pct,
  pctNgan,
  tenNut,
  type Mau,
} from '../logic'

const MAU_CHAM: Record<Mau, string> = {
  xanh: 'fill-ac stroke-ac',
  vang: 'fill-badge-warn-fg stroke-badge-warn-fg',
  do: 'fill-badge-alert-fg stroke-badge-alert-fg',
  xam: 'fill-n6 stroke-n6',
}

const LE = 30 // lề quanh cây trong khung vừa
const PHONG_MIN = 0.5 // so với vừa khung
const PHONG_MAX = 4
const BUOC_PHONG = 1.25
// `pointer-coarse:` 40px — vùng chạm trên máy cảm ứng; bản cũ 32px ở mọi máy.
const NUT_BAN_DO =
  'inline-flex h-8 min-w-8 cursor-pointer items-center justify-center rounded-md border border-border-field bg-surface px-2 text-[13px] hover:bg-fill-strong disabled:cursor-default disabled:opacity-40 pointer-coarse:h-10 pointer-coarse:min-w-10'

type Khung = { x: number; y: number; w: number; h: number }

interface Props {
  nodes: NutKichBan[]
  soDo: Record<string, SoDoNut>
  chon: string | undefined
  q: string
  onChon: (id: string) => void
  toanManHinh: boolean
  /** Vắng ⇒ không có nút toàn màn hình (trình duyệt không hỗ trợ — Safari iPhone). */
  onToanManHinh?: (() => void) | undefined
  /** So với mẫu (bản riêng) — vắng ở trạng thái mẫu. */
  loaiMau?: Record<string, LoaiMau> | undefined
}

export function DoThi({
  nodes,
  soDo,
  chon,
  q,
  onChon,
  toanManHinh,
  onToanManHinh,
  loaiMau,
}: Props) {
  const bc = useMemo(() => {
    const duoi: Record<string, string> = {}
    for (const [id, l] of Object.entries(loaiMau ?? {})) {
      const h = HAU_TO_MAU[l]
      if (h) duoi[id] = h
    }
    return boCucCay(nodes, duoi)
  }, [nodes, loaiMau])
  const vua = useMemo<Khung>(
    () => ({ x: -LE, y: -LE, w: bc.rong + 2 * LE, h: bc.cao + 2 * LE }),
    [bc],
  )
  const [zoom, setZoom] = useState<Khung | null>(null)
  const vb = zoom ?? vua
  const svgRef = useRef<SVGSVGElement>(null)
  const keo = useRef<{ x: number; y: number; s: number } | null>(null)
  const daKeo = useRef(false)
  /** Các ngón/con trỏ đang ấn, theo `pointerId` — vị trí màn hình mới nhất. */
  const tro = useRef(new Map<number, { x: number; y: number }>())
  /** Khoảng cách + trung điểm (màn hình) của hai ngón ở nhịp trước — `null` khi không chụm. */
  const chum = useRef<{ kc: number; x: number; y: number } | null>(null)

  // Phóng quanh điểm `o` (toạ độ sơ đồ) — mặc định giữa khung đang xem.
  const phong = useCallback(
    (f: number, o?: { x: number; y: number }) =>
      setZoom((z) => {
        const c = z ?? vua
        const w = Math.min(Math.max(c.w / f, vua.w / PHONG_MAX), vua.w / PHONG_MIN)
        const r = w / c.w
        const p = o ?? { x: c.x + c.w / 2, y: c.y + c.h / 2 }
        return { x: p.x - (p.x - c.x) * r, y: p.y - (p.y - c.y) * r, w, h: c.h * r }
      }),
    [vua],
  )
  const doi = useCallback(
    (dx: number, dy: number) =>
      setZoom((z) => {
        const c = z ?? vua
        return { ...c, x: c.x + dx, y: c.y + dy }
      }),
    [vua],
  )

  // React gắn wheel dạng passive → không chặn được trang cuộn/trình duyệt phóng; phải tự gắn.
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return
    const lan = (e: WheelEvent) => {
      e.preventDefault()
      const m = svg.getScreenCTM?.()
      if (!m) return
      const d = e.deltaMode === 1 ? 16 : 1 // Firefox chuột: đơn vị dòng
      // Kẹp delta: một nấc chuột ~100 còn chụm trackpad ~1–10 mỗi sự kiện — không kẹp thì chuột nhảy ×2,7.
      if (e.ctrlKey || e.metaKey)
        phong(
          Math.exp(-Math.max(-60, Math.min(60, e.deltaY * d)) * 0.005),
          new DOMPoint(e.clientX, e.clientY).matrixTransform(m.inverse()),
        )
      else doi((e.deltaX * d) / m.a, (e.deltaY * d) / m.a)
    }
    svg.addEventListener('wheel', lan, { passive: false })
    return () => svg.removeEventListener('wheel', lan)
  }, [phong, doi])

  /** Tab tới một nút đang nằm ngoài khung nhìn (đã phóng to) thì kéo khung theo. */
  const keoToi = (x: number, y: number) => {
    const le = Math.min(vb.w, vb.h) * 0.12
    const dx = x < vb.x + le ? x - (vb.x + le) : x > vb.x + vb.w - le ? x - (vb.x + vb.w - le) : 0
    const dy = y < vb.y + le ? y - (vb.y + le) : y > vb.y + vb.h - le ? y - (vb.y + vb.h - le) : 0
    if (dx || dy) doi(dx, dy)
  }

  /**
   * Một ngón rời (thả, bị trình duyệt huỷ để cuộn, mất capture). Còn đúng một ngón thì dời tiếp
   * TỪ CHỖ ngón đó đang đứng — không thì sơ đồ nhảy về vị trí lúc ngón đó mới chạm.
   */
  const thaTro = (id: number, svg: SVGSVGElement) => {
    if (!tro.current.delete(id)) return
    chum.current = null
    const con = [...tro.current.values()][0]
    keo.current = tro.current.size === 1 && con ? { ...con, s: svg.getScreenCTM?.()?.a ?? 1 } : null
  }

  const phim = (e: KeyboardEvent, id: string) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onChon(id)
    }
  }
  const tiepCuaChon = canh(nodes).filter((e) => e.source === chon || e.target === chon)

  return (
    <div
      className={`relative overflow-hidden rounded-lg border border-border bg-surface ${
        toanManHinh ? 'h-full' : 'h-[calc(100dvh-210px)] min-h-[420px]'
      }`}
    >
      {/* `will-change-transform`: Safari để lại VỆT chữ khi SVG co giãn theo khung chi tiết trượt ra/vào
          (đã tái hiện trên WebKit 2026-10-01). Lớp vẽ riêng buộc vẽ lại trọn SVG mỗi khung hình. Ảnh chụp
          headless KHÔNG thấy lỗi này. */}
      <svg
        ref={svgRef}
        viewBox={`${vb.x} ${vb.y} ${vb.w} ${vb.h}`}
        // `group` chứ không `img`: trong `role="img"` mọi con là trình bày, nên các nút
        // tình huống bấm được nằm trong một «ảnh» — WebKit/VoiceOver có thể gộp cả sơ
        // đồ thành một ảnh và nuốt mất các nút (audit 05/10).
        role="group"
        aria-label="Sơ đồ cây các tình huống kịch bản theo nhóm"
        className="block h-full w-full cursor-grab touch-none select-none will-change-transform active:cursor-grabbing"
        onPointerDown={(e) => {
          if (e.button !== 0) return
          // Chuột chỉ có MỘT con trỏ: nhả chuột ngoài sơ đồ (chưa kéo nên chưa capture) để lại
          // một mục mồ côi, và cú nhấn sau sẽ bị đọc thành ngón thứ hai — tức chụm.
          if (e.pointerType === 'mouse') tro.current.clear()
          tro.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
          if (tro.current.size === 2) {
            // Ngón thứ hai: bỏ dời, bắt đầu chụm. Đánh dấu đã kéo để thả tay không mở nhầm nút.
            const [a, b] = [...tro.current.values()] as [
              { x: number; y: number },
              { x: number; y: number },
            ]
            chum.current = {
              kc: Math.hypot(b.x - a.x, b.y - a.y),
              x: (a.x + b.x) / 2,
              y: (a.y + b.y) / 2,
            }
            keo.current = null
            daKeo.current = true
            return
          }
          if (tro.current.size > 2) return
          daKeo.current = false
          keo.current = { x: e.clientX, y: e.clientY, s: e.currentTarget.getScreenCTM?.()?.a ?? 1 }
        }}
        onPointerMove={(e) => {
          if (!tro.current.has(e.pointerId)) return
          tro.current.set(e.pointerId, { x: e.clientX, y: e.clientY })
          const c = chum.current
          if (c && tro.current.size >= 2) {
            const [a, b] = [...tro.current.values()] as [
              { x: number; y: number },
              { x: number; y: number },
            ]
            const kc = Math.hypot(b.x - a.x, b.y - a.y)
            const x = (a.x + b.x) / 2
            const y = (a.y + b.y) / 2
            const m = e.currentTarget.getScreenCTM?.()
            if (m && c.kc > 0 && kc > 0) {
              // Hai ngón cùng trôi = dời; khoảng cách đổi = phóng quanh trung điểm.
              doi(-(x - c.x) / m.a, -(y - c.y) / m.a)
              phong(kc / c.kc, new DOMPoint(x, y).matrixTransform(m.inverse()))
            }
            chum.current = { kc, x, y }
            return
          }
          const k = keo.current
          if (!k) return
          const dx = e.clientX - k.x
          const dy = e.clientY - k.y
          if (!daKeo.current && Math.hypot(dx, dy) < 4) return
          if (!daKeo.current) {
            daKeo.current = true
            e.currentTarget.setPointerCapture?.(e.pointerId)
          }
          keo.current = { ...k, x: e.clientX, y: e.clientY }
          doi(-dx / k.s, -dy / k.s)
        }}
        onPointerUp={(e) => thaTro(e.pointerId, e.currentTarget)}
        onPointerCancel={(e) => thaTro(e.pointerId, e.currentTarget)}
        onLostPointerCapture={(e) => thaTro(e.pointerId, e.currentTarget)}
        // Thả tay sau khi kéo: trình duyệt vẫn bắn click — chặn ở pha bắt để không mở nhầm tình huống.
        onClickCapture={(e) => {
          if (!daKeo.current) return
          daKeo.current = false
          e.stopPropagation()
        }}
      >
        <defs>
          <marker
            id="kich-ban-mui-ten"
            viewBox="0 0 10 10"
            refX={9}
            refY={5}
            markerWidth={7}
            markerHeight={7}
            orient="auto-start-reverse"
          >
            <path d="M0,0 L10,5 L0,10 z" className="fill-ac" />
          </marker>
        </defs>

        {/* Gốc → nhóm: cong rồi chạy thẳng một đoạn để tên nhóm nằm lên trên. */}
        {bc.nhom.map((g) => {
          const dau = CAY.xNhom - 150
          const giua = (CAY.gocRong + dau) / 2
          return (
            <g key={g.nhom}>
              <path
                d={`M${CAY.gocRong},${bc.gocY} C${giua},${bc.gocY} ${giua},${g.y} ${dau},${g.y} L${CAY.xNhom},${g.y}`}
                className="fill-none stroke-border-strong"
                strokeWidth={1.5}
              />
              {nodes
                .filter((n) => n.nhom === g.nhom)
                .map((n) => {
                  const y = bc.nut[n.id]!.y
                  return (
                    <path
                      key={n.id}
                      d={`M${CAY.xNhom},${g.y} C${CAY.xNhom + 80},${g.y} ${CAY.xNut - 80},${y} ${CAY.xNut},${y}`}
                      className="fill-none stroke-border-strong"
                      strokeWidth={1}
                    />
                  )
                })}
              <circle cx={CAY.xNhom} cy={g.y} r={5} className="fill-muted" />
              <text
                x={CAY.xNhom - 8}
                y={g.y - 7}
                textAnchor="end"
                className="fill-fg text-the font-semibold"
              >
                {TEN_NHOM[g.nhom] ?? g.nhom}
                <tspan className="fill-muted font-normal"> · {g.so}</tspan>
              </text>
            </g>
          )
        })}

        {/* Chuyển tiếp chỉ hiện cho tình huống đang chọn — vòng ra bên phải nhãn, mũi tên chỉ đích. */}
        {tiepCuaChon.map((e) => {
          const a = bc.nut[e.source]
          const b = bc.nut[e.target]
          if (!a || !b) return null
          const c = Math.max(a.cuoi, b.cuoi) + 30 + Math.abs(b.y - a.y) * 0.12
          return (
            <path
              key={e.id}
              d={`M${a.cuoi + 6},${a.y} C${c},${a.y} ${c},${b.y} ${b.cuoi + 6},${b.y}`}
              className="fill-none stroke-ac"
              strokeWidth={2}
              markerEnd="url(#kich-ban-mui-ten)"
            />
          )
        })}

        {nodes.map((n) => {
          const y = bc.nut[n.id]!.y
          const nhap = n.trang_thai === 'nhap'
          const mau = mauTiLe(soDo[n.id], nhap)
          const luong = n.loai === 'luong'
          const dangChon = chon === n.id
          const hauTo = HAU_TO_MAU[loaiMau?.[n.id] ?? 'giong']
          return (
            <g
              key={n.id}
              data-testid={`nut-${n.id}`}
              data-mau={mau}
              data-nhap={nhap ? 'true' : undefined}
              role="button"
              tabIndex={0}
              aria-pressed={dangChon}
              aria-label={`${tenNut(n)}${hauTo ?? ''} — ${TEN_NHOM[n.nhom] ?? n.nhom}, ${pct(soDo[n.id])}`}
              onClick={() => onChon(n.id)}
              onKeyDown={(e) => phim(e, n.id)}
              onFocus={() => keoToi(CAY.xNut, y)}
              opacity={khop(n, q) ? 1 : 0.2}
              // Vòng focus là KHUNG quanh cả hàng (vùng bấm), không chỉ nét chấm 5,5px dày
              // lên — nét 1,5 → 3 trên một chấm nhỏ là chỉ báo focus không ai thấy.
              className="cursor-pointer outline-none [&:focus-visible>rect]:stroke-ac [&:focus-visible>rect]:stroke-2 [&:focus-visible_circle]:stroke-ac [&:focus-visible_circle]:stroke-[3]"
            >
              <title>{`${tenNut(n)} · ${pct(soDo[n.id])} · ${soDo[n.id]?.soLuot ?? 0} lượt`}</title>
              {/* Vùng bấm phủ cả hàng — chấm 6px + chữ thì bấm trượt giữa các con chữ. */}
              <rect
                x={CAY.xNut - 10}
                y={y - CAY.hang / 2}
                width={bc.nut[n.id]!.cuoi - CAY.xNut + 14}
                height={CAY.hang}
                rx={6}
                className="fill-transparent"
              />
              <circle
                cx={CAY.xNut}
                cy={y}
                r={luong ? 7 : 5.5}
                className={nhap ? 'fill-surface stroke-n6' : MAU_CHAM[mau]}
                strokeWidth={luong ? 2.5 : 1.5}
                strokeDasharray={nhap ? '2 2' : undefined}
              />
              <text
                x={CAY.xNut + 12}
                y={y}
                dy={5}
                className={`fill-fg text-the ${dangChon ? 'font-semibold' : ''}`}
              >
                {tenNut(n)}
                {luong ? ' ▸' : ''}
                {/* %đạt bằng CHỮ cạnh tên: ba màu chấm xanh/hổ phách/đỏ gần bằng nhau về độ
                    sáng (0,148 / 0,131 / 0,135) — người khó phân biệt màu không đọc được chúng
                    (audit 05/10, WCAG 1.4.1). Chưa đủ lượt chấm ⇒ không in, chấm xám tự nói. */}
                {pctNgan(soDo[n.id]) && (
                  <tspan className="fill-muted-2 text-phu font-normal">
                    {` · ${pctNgan(soDo[n.id])}`}
                  </tspan>
                )}
                {hauTo ? (
                  <tspan className="fill-muted-2 text-phu font-normal">{hauTo}</tspan>
                ) : null}
              </text>
            </g>
          )
        })}

        <rect
          x={0}
          y={bc.gocY - 30}
          width={CAY.gocRong}
          height={60}
          rx={12}
          className="fill-surface stroke-ac"
          strokeWidth={2}
        />
        <text
          x={CAY.gocRong / 2}
          y={bc.gocY - 4}
          textAnchor="middle"
          className="fill-fg text-[17px] font-semibold"
        >
          Kịch bản
        </text>
        <text
          x={CAY.gocRong / 2}
          y={bc.gocY + 17}
          textAnchor="middle"
          className="fill-muted text-[14px]"
        >
          bán hàng
        </text>
      </svg>

      <div className="absolute top-2 right-2 flex gap-1">
        <button
          type="button"
          aria-label="Thu nhỏ"
          className={NUT_BAN_DO}
          onClick={() => phong(1 / BUOC_PHONG)}
        >
          −
        </button>
        <button
          type="button"
          aria-label="Phóng to"
          className={NUT_BAN_DO}
          onClick={() => phong(BUOC_PHONG)}
        >
          +
        </button>
        <button
          type="button"
          aria-label="Vừa khung"
          title="Vừa khung"
          className={NUT_BAN_DO}
          disabled={zoom === null}
          onClick={() => setZoom(null)}
        >
          <Icon name="vuaKhung" className="size-4" />
        </button>
        {onToanManHinh ? (
          <button
            type="button"
            aria-label={toanManHinh ? 'Thoát toàn màn hình' : 'Toàn màn hình'}
            title={toanManHinh ? 'Thoát toàn màn hình' : 'Toàn màn hình'}
            className={NUT_BAN_DO}
            onClick={onToanManHinh}
          >
            <Icon name={toanManHinh ? 'thoatToanManHinh' : 'toanManHinh'} className="size-4" />
          </button>
        ) : null}
      </div>
      {/* Gợi ý theo loại con trỏ, không theo bề rộng: tablet cảm ứng không có Ctrl/⌘ + cuộn. */}
      <p className="pointer-events-none absolute bottom-2 left-3 text-[12px] text-muted-3">
        <span className="pointer-coarse:hidden">Kéo để di chuyển · Ctrl/⌘ + cuộn để phóng</span>
        <span className="hidden pointer-coarse:inline">
          Kéo để di chuyển · chụm hai ngón để phóng
        </span>
      </p>
    </div>
  )
}
