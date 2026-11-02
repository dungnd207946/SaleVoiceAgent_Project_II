/**
 * Ô ① màn Tổng quan — hai đường Chat/Voice trên 7 ngày, dải crosshair bám chuột,
 * tooltip đọc số của ngày đang trỏ.
 *
 * PORT nguyên hình học/gradient/thứ tự vẽ từ `docs/design/demo-tong-quan.html`
 * § `ve()` (bản đã duyệt) sang JSX SVG thuần — không thiết kế lại.
 *
 * THANG BĂNG là quyết định gốc, không phải thang mép-tới-mép: chia vùng vẽ
 * thành đúng N ô (N = số ngày trong `chuoi`) và đặt điểm dữ liệu ở TÂM ô.
 * Hệ quả — không còn con số magic nào:
 *   · dải ngày đang xem = TRỌN một ô, luôn nằm trong lưới, KHÔNG cần kẹp
 *   · dải và vạch dọc cao đúng PT → PT+ih, khít đường nền
 *   · vạch lưới dọc đi XUYÊN đúng tâm ô ⇒ đúng điểm dữ liệu
 *   · hàng nhãn ngày chỉ cần cùng lề trái/phải rồi chia N ô đều — tâm tự
 *     trùng toạ độ X của điểm dữ liệu
 *   · bám chuột dùng `Math.floor` theo Ô, KHÔNG `Math.round` theo điểm
 *
 * `var()` KHÔNG được phân giải trong presentation attribute của SVG (rơi về
 * mặc định, im lặng) — bẫy này ăn `stop-color` và `rx`. Mọi `<stop>` dưới đây
 * đặt màu qua `style`, không qua attribute. Các attribute khác (`stroke`,
 * `fill`) dùng `var(--color-…)` trực tiếp vẫn đúng, giống bản demo.
 *
 * TOOLTIP là phần PORT SAU (round fix 2026-08-13) — bản đầu đánh rơi nó, và
 * hai hậu quả đo được: (a) `khac` của mỗi ngày (43/302 phiên, 14%) không xuất
 * hiện ở BẤT KỲ đâu theo ngày, dù backend tính nó, có test cho nó, đẩy nó qua
 * JSON và khai nó trong `NgayHoiThoai`; (b) `dangXem` chỉ còn đổi màu — một
 * điều khiển tương tác không trả lại thông tin nào. Nội dung và hình thức
 * PORT từ `docs/design/demo-tong-quan.html` § `moTip`/`tipCho` (bản đã duyệt).
 *
 * `position: fixed` chứ không `absolute`: ô này nằm trong một thẻ lưới mang
 * `overflow-hidden` (bắt buộc, xem `TongQuanScreen`), nên một tooltip absolute
 * bị CẮT ngay ở mép thẻ — đúng lý do bản demo treo `#tip` ở tầng `<body>`.
 *
 * ⚠️ Câu tiếp theo ở đây TRƯỚC ĐÂY viết "`fixed` chỉ bị nhốt lại bởi tổ tiên
 * có `transform`/`filter`/`contain`, và không tổ tiên nào của ô này có" — câu
 * đó đã SAI kể từ khi `O_BAM_DUOC` (`TongQuanScreen.tsx`, cùng ngày) thêm
 * `hover:-translate-y-0.5` vào thẻ cha: rê chuột vào để đọc tooltip CHÍNH LÀ
 * lúc thẻ mọc `transform`. `HopTip` vì thế portal ra `document.body` — lý do
 * đầy đủ ở docstring `./Tip.tsx`, đừng gỡ portal đó đi.
 *
 * Khung tooltip (vị trí/kẹp/lật + state) đã TÁCH sang `./Tip.tsx` (2026-08-14)
 * khi `TheKienThuc.tsx` (ô ⑤) thành người dùng thứ hai — component `Tip` dưới
 * đây giờ chỉ còn phần NỘI DUNG riêng của ô này (ngày/kênh), khung dùng
 * `HopTip` chung.
 *
 * `relative z-10` trên vùng vẽ + hàng nhãn ngày (round fix 2026-08-14, ô ①
 * thành bấm được) — ô cha giờ có một `<Link>` ở đầu ô mang `after:absolute
 * after:inset-0` (stretched-link, phủ TRỌN ô để điều hướng sang `/convos`).
 * Không nâng z-index hai vùng này thì lớp phủ đó NUỐT mất chuột: bấm vào
 * biểu đồ để xem một ngày sẽ điều hướng nhầm sang `/convos`, trong khi việc
 * người dùng đang làm là XEM DỮ LIỆU, không phải rời màn. `z-10` (dương,
 * tường minh) đứng trên lớp phủ `z-index: auto` của `::after` theo đúng thứ
 * tự stacking chuẩn (positioned + z dương luôn vẽ trên positioned + z auto,
 * bất kể thứ tự DOM) — không cần đụng gì tới `::after`.
 */
import { useEffect, useId, useRef, useState } from 'react'
import type { NgayHoiThoai } from '../api'
import { so } from '@/lib/dinhDang'
import { DongTip, HopTip } from './Tip'
import { useTip } from './useTip'

const PT = 14
const PR = 16
const PB = 8
const PL = 30
const SO_MOC = 4
const THU = ['CN', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7']

/**
 * Parse `YYYY-MM-DD` theo giờ ĐỊA PHƯƠNG. `new Date(iso)` parse ISO trần theo
 * UTC nên có thể lệch một ngày ở múi giờ âm — tách tay ba số rồi dựng
 * `Date(y, m-1, d)` để tránh đúng lỗi đó.
 */
function ngayLe(iso: string): { readonly thu: string; readonly nhan: string } {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(y ?? 0, (m ?? 1) - 1, d ?? 1)
  return { thu: THU[dt.getDay()] ?? '', nhan: `${dt.getDate()}/${dt.getMonth() + 1}` }
}

interface Kenh {
  readonly khoa: 'chat' | 'voice'
  readonly ten: string
  readonly mau: string
}

const VE: readonly Kenh[] = [
  { khoa: 'chat', ten: 'Chat', mau: 'var(--color-ds1)' },
  { khoa: 'voice', ten: 'Voice', mau: 'var(--color-ds2)' },
]

interface Props {
  readonly chuoi: readonly NgayHoiThoai[]
  readonly dangXem: number
  readonly doiDangXem: (i: number) => void
  /**
   * CHỈ để test truyền kích thước trực tiếp. jsdom không có `ResizeObserver`
   * và luôn trả `clientWidth`/`clientHeight` = 0, nên test không đo được gì
   * qua đường đo thật — production KHÔNG truyền prop này, tự đo bằng
   * `ResizeObserver` trên div bọc.
   */
  readonly co?: { readonly W: number; readonly H: number }
}

export function BieuDoNgay({ chuoi, dangXem, doiDangXem, co }: Props) {
  const bocRef = useRef<HTMLDivElement>(null)
  const [doTuDo, setDoTuDo] = useState({ W: 0, H: 0 })
  const { tip, taiChuot, taiTieuDiem, an } = useTip()
  const N = chuoi.length

  useEffect(() => {
    if (co) return
    const boc = bocRef.current
    if (!boc) return
    const doc = () => setDoTuDo({ W: boc.clientWidth, H: boc.clientHeight })
    doc()
    const ro = new ResizeObserver(doc)
    ro.observe(boc)
    return () => ro.disconnect()
  }, [co])

  const { W, H } = co ?? doTuDo

  function theoChuot(e: { clientX: number; clientY: number }) {
    const boc = bocRef.current
    if (!boc || N === 0) return
    const r = boc.getBoundingClientRect()
    const buoc = (r.width - PL - PR) / N
    // `floor` theo Ô, KHÔNG `round` theo điểm: thang băng cho mỗi ngày sở hữu
    // TRỌN một ô, nên con trỏ ở đâu trong ô cũng thuộc về ngày đó.
    const i = Math.min(N - 1, Math.max(0, Math.floor((e.clientX - r.left - PL) / buoc)))
    doiDangXem(i)
    taiChuot(i, e)
  }

  // Đọc ra biến TRƯỚC JSX: `noUncheckedIndexedAccess` cho `chuoi[i]` kiểu
  // `NgayHoiThoai | undefined`, và TS không hẹp được kiểu qua một phép truy
  // cập chỉ số lặp lại trong JSX (chỉ số không phải literal).
  const ngayTip = tip ? chuoi[tip.i] : undefined

  function roiKhung() {
    an()
    // Trạng thái NGHỈ của ô là HÔM NAY, không phải "ngày cuối cùng con chuột
    // vô tình đi qua" — chốt ở spec §2.
    doiDangXem(N - 1)
  }

  return (
    <div className="flex h-full flex-col">
      <div
        ref={bocRef}
        data-testid="bieu-do-ve"
        className="relative z-10 min-h-0 flex-1 cursor-crosshair"
        onMouseMove={theoChuot}
        onMouseLeave={roiKhung}
      >
        {W > 0 && H > 0 && N > 0 && <Do W={W} H={H} chuoi={chuoi} dangXem={dangXem} />}
      </div>

      {tip && ngayTip && <Tip r={ngayTip} homNay={tip.i === N - 1} x={tip.x} y={tip.y} />}

      {/* Nhãn ngày dùng ĐÚNG lề trái/phải của vùng vẽ (padding = PR/PL) VÀ
          ĐÚNG cùng N với SVG bên trên, rồi chia N ô đều — tâm mỗi ô khi đó
          trùng khít X[i]. Hai bên cùng suy ra từ một `N` và một cặp lề, nên
          tâm tự trùng — không có con số magic nào.
          `grid-cols-7` (Tailwind) từng cứng ở đây trong khi SVG đã tổng quát
          hoá theo `N = chuoi.length` — hai thang lại tách nhau ĐÚNG cái bệnh
          thang mép-tới-mép mà cả component này sinh ra để chữa: `chuoi` dài
          khác 7 (ví dụ đổi `SO_NGAY` phía backend) thì SVG vẽ N điểm ở toạ độ
          mới còn hàng nhãn vẫn chia 7 cột, cuốn dòng, và nhãn/điểm lệch nhau
          không lỗi nào nổ. Tailwind không phát được utility cho N tuỳ ý nên
          phải `gridTemplateColumns` qua `style`. */}
      <div
        className="relative z-10 mt-[7px] grid gap-0.5"
        style={{
          gridTemplateColumns: `repeat(${N}, 1fr)`,
          padding: `0 ${PR}px 0 ${PL}px`,
        }}
      >
        {chuoi.map((r, i) => {
          const { thu, nhan } = ngayLe(r.ngay)
          const homNay = i === N - 1
          const on = i === dangXem
          return (
            <button
              key={r.ngay}
              type="button"
              data-testid={`nhan-ngay-${i}`}
              onClick={() => doiDangXem(i)}
              /* Tooltip cũng mở bằng BÀN PHÍM. Nhãn ngày đã là `<button>` thật
                 (spec §2: "dải với tới được bằng bàn phím và bằng ngón tay"),
                 nhưng nếu chỉ `mousemove` mở tooltip thì người tab tới đây đổi
                 được dải mà không đọc được con số nào — đúng cái bệnh "điều
                 khiển không trả lại thông tin" của bản trước, chỉ đổi đối
                 tượng chịu. Neo vào TÂM MÉP TRÊN của chính nút. */
              onFocus={(e) => {
                doiDangXem(i)
                taiTieuDiem(i, e.currentTarget)
              }}
              onBlur={an}
              className={`flex flex-col items-center gap-px rounded-sm px-px pt-[5px] pb-1 transition ${
                on ? 'bg-ds1-mo' : 'hover:bg-fill'
              }`}
            >
              <span
                className={`whitespace-nowrap text-nhan leading-[1.25] ${
                  on ? 'font-medium text-ds1' : homNay ? 'font-medium text-muted' : 'text-muted-2'
                }`}
              >
                {homNay ? 'Hôm nay' : thu}
              </span>
              <span
                className={`whitespace-nowrap font-mono text-nhan ${
                  on ? 'text-ds1 opacity-90' : 'text-muted-2 opacity-70'
                }`}
              >
                {nhan}
              </span>
            </button>
          )
        })}
      </div>

      {/* Bảng số cho trình đọc màn hình — PORT từ đoạn `sr` cuối khối ① của
          demo. `aria-label` của SVG chỉ nói hình này VẼ GÌ, không nói nó vẽ
          RA SỐ MẤY; tooltip thì chỉ mở bằng chuột/tiêu điểm. Không có đoạn
          này thì `khac` — 14% số phiên — không tới được người dùng trình đọc
          màn hình bằng bất kỳ đường nào. */}
      <p className="sr-only">
        Bảng số theo ngày:{' '}
        {chuoi
          .map((r) => {
            const { nhan } = ngayLe(r.ngay)
            return `${nhan} — Chat ${so(r.chat)}, Voice ${so(r.voice)}, khác ${so(r.khac)}, tổng ${so(r.tong)}`
          })
          .join('; ')}
      </p>
    </div>
  )
}

/**
 * Tooltip của một ngày — PORT nội dung/thứ tự dòng từ `tipCho()` của demo.
 *
 * «Khác» gộp Zalo OA + kênh lạ + `source` NULL, vì `NgayOut` của backend chỉ
 * tách `chat`/`voice`/`khac` theo ngày (chú thích dưới con số lớn mới gọi
 * ĐÚNG TÊN từng kênh, từ `theoKenh`). Nên chấm màu ở dòng này là
 * `--color-ds-khac` — xám trung tính — chứ KHÔNG phải `--color-ds3` (teal,
 * spec dành riêng cho Zalo OA): tô teal ở đây là hứa một phép tách mà con số
 * đứng cạnh nó không có.
 *
 * «Tổng» đọc thẳng `r.tong` (backend tính, `api.ts` dựng lại từ ba thành phần
 * khi khoá vắng) chứ không cộng tay ở đây — hai chỗ cộng cùng một đại lượng
 * là hai chỗ lệch nhau được.
 */
function Tip({
  r,
  homNay,
  x,
  y,
}: {
  readonly r: NgayHoiThoai
  readonly homNay: boolean
  readonly x: number
  readonly y: number
}) {
  const { thu, nhan } = ngayLe(r.ngay)

  return (
    <HopTip x={x} y={y} testId="ht-tip">
      <div className="mb-[5px] text-[11.5px] font-semibold">
        {homNay ? 'Hôm nay · ' : ''}
        {thu} {nhan}
      </div>
      {VE.map((c) => (
        <DongTip key={c.khoa} mau={c.mau} ten={c.ten} gia={so(r[c.khoa])} />
      ))}
      <DongTip mau="var(--color-ds-khac)" ten="Khác" gia={so(r.khac)} />
      <div className="mt-1.5 flex items-center gap-2 border-t border-panel-line pt-1.5 text-nhan text-panel-muted">
        Tổng
        <b className="ml-auto font-mono font-medium text-n1">{so(r.tong)}</b>
      </div>
    </HopTip>
  )
}

/** Vẽ SVG thuần — tách khỏi `BieuDoNgay` để phần đo khung/nhãn ngày không
 * lẫn với phần hình học, và để `W`/`H` > 0 là điều kiện DUY NHẤT trước khi
 * component này được gọi (không lặp lại phép kiểm bên trong). */
function Do({
  W,
  H,
  chuoi,
  dangXem,
}: {
  readonly W: number
  readonly H: number
  readonly chuoi: readonly NgayHoiThoai[]
  readonly dangXem: number
}) {
  const uid = useId()
  const N = chuoi.length
  const iw = W - PL - PR
  const ih = H - PT - PB
  // Trần là bội của 20 để 5 mốc luôn rơi vào số nguyên tròn — một trục ghi
  // 0 · 8,75 · 17,5 là trục không ai đọc.
  const dinh = Math.max(
    20,
    Math.ceil((Math.max(...chuoi.flatMap((r) => [r.chat, r.voice])) * 1.12) / 20) * 20,
  )
  const buoc = iw / N
  const X = chuoi.map((_, i) => PL + (i + 0.5) * buoc) // TÂM ô, không phải mép
  const Y = (v: number) => PT + ih - (v / dinh) * ih
  const DAY = PT + ih // đáy lưới

  const duong = (khoa: Kenh['khoa']) =>
    chuoi.map((r, i) => `${i ? 'L' : 'M'} ${X[i]} ${Y(r[khoa])}`).join(' ')

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width={W}
      height={H}
      role="img"
      /* `N`, KHÔNG phải chữ `7` viết cứng: cả component đã tổng quát hoá theo
         `chuoi.length` (xem chú thích hàng nhãn ngày) — đổi `SO_NGAY` phía
         backend thì hình vẽ N điểm còn nhãn này vẫn đọc "7 ngày", và trình
         đọc màn hình là chỗ DUY NHẤT không ai kiểm được bằng mắt. */
      aria-label={`Số phiên Chat và Voice mỗi ngày trong ${N} ngày gần nhất`}
      className="absolute inset-0 block"
    >
      {/* Mốc đối chiếu của test — không vẽ gì, chỉ phủ đúng vùng vẽ PL,PT,iw,ih. */}
      <rect data-vai="nen-luoi" x={PL} y={PT} width={iw} height={ih} fill="none" />

      <defs>
        <linearGradient id={`${uid}-vungChat`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: 'var(--color-ds1)', stopOpacity: 0.22 }} />
          <stop offset="1" style={{ stopColor: 'var(--color-ds1)', stopOpacity: 0 }} />
        </linearGradient>
        <linearGradient id={`${uid}-vungVoice`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: 'var(--color-ds2)', stopOpacity: 0.17 }} />
          <stop offset="1" style={{ stopColor: 'var(--color-ds2)', stopOpacity: 0 }} />
        </linearGradient>
        <linearGradient id={`${uid}-dai`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: 'var(--color-ds1)', stopOpacity: 0.16 }} />
          <stop offset="1" style={{ stopColor: 'var(--color-ds1)', stopOpacity: 0.02 }} />
        </linearGradient>
        {/* Gradient NGANG theo chiều thời gian: quá khứ nhạt, hôm nay đậm
            nhất — mã hoá chiều đọc, không phải trang trí. */}
        <linearGradient id={`${uid}-netChat`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" style={{ stopColor: 'var(--color-ds1)', stopOpacity: 0.45 }} />
          <stop offset="1" style={{ stopColor: 'var(--color-ds1)', stopOpacity: 1 }} />
        </linearGradient>
        <linearGradient id={`${uid}-netVoice`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" style={{ stopColor: 'var(--color-ds2)', stopOpacity: 0.45 }} />
          <stop offset="1" style={{ stopColor: 'var(--color-ds2)', stopOpacity: 1 }} />
        </linearGradient>
      </defs>

      {/* ① Dải của ngày đang xem — TRỌN MỘT Ô, cao đúng bằng lưới */}
      <rect
        data-vai="dai"
        x={PL + dangXem * buoc}
        y={PT}
        width={buoc}
        height={ih}
        fill={`url(#${uid}-dai)`}
      />
      <line
        x1={X[dangXem]}
        x2={X[dangXem]}
        y1={PT}
        y2={DAY}
        stroke="var(--color-ds1)"
        strokeWidth={1.5}
        opacity={0.35}
      />

      {/* ② Lưới dọc — đi qua ĐÚNG tâm ô, tức đúng chỗ điểm dữ liệu đứng */}
      {X.map((x, i) => (
        <line
          key={i}
          data-vai="vach-doc"
          x1={x}
          x2={x}
          y1={PT}
          y2={DAY}
          stroke="var(--color-border-soft)"
          strokeWidth={1}
        />
      ))}

      {/* ③ Lưới ngang — 5 mốc */}
      {Array.from({ length: SO_MOC + 1 }, (_, i) => {
        const gv = (dinh * i) / SO_MOC
        const gy = Y(gv)
        return (
          <g key={i}>
            <line
              x1={PL}
              x2={W - PR}
              y1={gy}
              y2={gy}
              stroke={i === 0 ? 'var(--color-border-strong)' : 'var(--color-border)'}
              strokeWidth={1}
            />
            <text
              data-vai="moc-y"
              x={PL - 8}
              y={gy + 3.5}
              textAnchor="end"
              fill="var(--color-muted-2)"
              fontSize={11}
              fontFamily="var(--font-mono)"
            >
              {so(gv)}
            </text>
          </g>
        )
      })}

      {/* ④ Vùng nền (gradient) — vẽ CẢ HAI trước, rồi mới tới hai đường */}
      {VE.map((c) => (
        <path
          key={c.khoa}
          d={`${duong(c.khoa)} L ${X[N - 1]} ${DAY} L ${X[0]} ${DAY} Z`}
          fill={`url(#${uid}-vung${c.khoa === 'chat' ? 'Chat' : 'Voice'})`}
        />
      ))}

      {/* ⑤ Hai đường + điểm */}
      {VE.map((c) => (
        <g key={c.khoa}>
          <path
            d={duong(c.khoa)}
            fill="none"
            stroke={`url(#${uid}-${c.khoa === 'chat' ? 'netChat' : 'netVoice'})`}
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          {chuoi.map((r, i) => {
            const ke = i === dangXem
            const gia = r[c.khoa]
            return (
              <g key={r.ngay}>
                {/* Quầng sáng sau điểm đang xem — hiệu ứng nổi, và giữ cho
                    điểm không chìm vào vùng gradient bên dưới nó. */}
                {ke && <circle cx={X[i]} cy={Y(gia)} r={9} fill={c.mau} opacity={0.15} />}
                <circle
                  data-vai={c.khoa === 'chat' ? 'diem-chat' : 'diem-voice'}
                  cx={X[i]}
                  cy={Y(gia)}
                  r={ke ? 4.5 : 2.5}
                  fill={c.mau}
                  opacity={ke ? 1 : 0.4}
                  stroke={ke ? 'var(--color-surface)' : 'none'}
                  strokeWidth={ke ? 2 : 0}
                />
              </g>
            )
          })}
        </g>
      ))}
    </svg>
  )
}
