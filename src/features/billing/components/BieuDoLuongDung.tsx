/**
 * Line chart của màn `/usage` — MỘT tab, nét gradient + vùng tô.
 *
 * KHÔNG phải bản sao của `BieuDoChiPhi` (`/billing`) dù cùng là line chart: ở đó
 * một đường TIỀN với trục `₫` và tooltip tách theo component; ở đây đường SỐ ĐO
 * với trục theo đơn vị của chính tab, và tooltip có dòng ngữ cảnh «N phiên».
 * Hình học (monotone/thẳng, đo khung, mốc trục) là cùng một họ vì cùng một
 * portal — đừng "hợp nhất" hai component: chúng sẽ mọc bảy prop `if` để phục vụ
 * hai câu hỏi khác nhau.
 *
 * ⚠️ ĐƯỜNG THỨ HAI (`tab.duong2`, hiện chỉ `stt`) CÓ TRỤC RIÊNG BÊN PHẢI, và
 * đó là điều kiện chứ không phải trang trí. Hai chuỗi khác ĐƠN VỊ (giây vs ký
 * tự) mà chung một trục thì trục lấy theo chuỗi lớn hơn và chuỗi kia nằm bẹp
 * dưới đáy — đúng lỗi biểu đồ gộp bảy service của vòng thiết kế trước. Trên dữ
 * liệu thật: 431 giây cạnh 1.887 ký tự.
 *
 * Đường 2 vẽ NÉT LIỀN, MÀU RIÊNG (`--d`/`--d2` — token `--color-u-<ma>2`, xem
 * `theme.css`), KHÔNG vùng tô và KHÔNG quầng sáng. Bản đầu phân biệt bằng nét
 * đứt; người dùng chốt đổi sang màu (2026-08-25).
 *
 * ⚠️ Màu đó KHÔNG mượn của tab nào. Bảy hue là định danh của bảy tab và rail
 * bày đủ bảy chấm ngay bên trái, nên một đường hổ phách trong biểu đồ STT thì
 * mắt ghép được nó với chấm «Thời gian gọi». Token riêng, chọn bằng ĐO: ΔE 24,6
 * tới màu tab gần nhất — lớn hơn khoảng cách 20,0 mà `stt`↔`tts` đang sống với.
 *
 * ⚠️ ĐƯỜNG 2 CÓ VÙNG TÔ (người dùng chốt 2026-08-25, đảo quyết định trước đó).
 * Cái giá đã biết và chấp nhận: hai mảng tô chồng nhau thì độ mờ CỘNG lại
 * (0.3 + 0.3 ≈ 0.5), nên chỗ giao đậm hơn cả hai vùng — mắt có thể đọc nó
 * thành một mức thứ ba không chuỗi nào có. Chọn hai hue cách nhau 104° là để
 * chỗ giao vẫn phân giải được thành «tím chồng lam» chứ không thành một mảng
 * bùn. Đừng bù bằng cách bóp `stop-opacity` của đường 2 xuống thấp hơn đường
 * chính: người dùng yêu cầu «giống những line khác», và một vùng tô nhạt hơn
 * đọc thành «dữ liệu kém tin hơn».
 *
 * THỨ TỰ VẼ: CẢ HAI vùng tô trước, rồi mới tới nét. Vẽ vùng tô của đường 2 sau
 * nét đường 1 thì mảng mờ đó phủ lên chính cái nét nó đứng cạnh và làm nét
 * loang màu — đúng lớp lỗi «chấm trắng làm đường đọc ra đứt đoạn».
 *
 * Quầng sáng (`feGaussianBlur`) CHỈ đường chính có: nó là thứ duy nhất còn lại
 * nói đâu là số đo dẫn của tab, sau khi hai đường đã ngang nhau về nét và tô.
 *
 * ĐO KHUNG bằng `ResizeObserver`, CẢ HAI CHIỀU. Prop `co` ghi đè phép đo, dành
 * cho test (jsdom luôn trả `clientWidth = 0`) — cùng khuôn `BieuDoChiPhi` và
 * `BieuDoNgay` của `features/ops`. Chiều CAO là chiều dễ quên: thẻ này cao theo
 * RAIL bảy mục bên cạnh, nên mọi hằng px viết ở đây đều sai (bản vẽ vòng 6 khoá
 * 326px và để lại một mảng trắng ~70px dưới trục ngày).
 */
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as SuKienPhim,
  type PointerEvent as SuKienTro,
} from 'react'

import { DINH_DANG, NHAN_DON_VI, nhanMocTruc, timTab } from '../so-tab-usage'
import type { TabUsage } from '../so-tab-usage'
import type { ChuoiTab } from '../chuoi-usage'
import { bienMau, bienMauPhu, dongBoMoc, mocNgay, mocTruc, ngayVN } from '../truc-usage'

/** Lề trong SVG — chỗ cho hai trục. */
const PL = 58
const PR = 16
/* Lề của tab HAI ĐƯỜNG: rộng hơn vì mỗi bên còn chở một NHÃN TRỤC quay dọc
   (`mocTruc` chỉ in số, mà một cột số trần không nói nó đo cái gì). Đo: mốc
   rộng nhất ~30px + khe 10px + nhãn xoay ~14px. */
const PL2 = 74
const PR2 = 62
/** Khoảng cách từ mép SVG tới đường tâm của nhãn trục quay dọc. */
const LE_NHAN_TRUC = 13
const PT = 18
const PB = 28
const CAO_TOI_THIEU = 260

/**
 * KIỂU NÉT — đổi MỘT hằng này là đổi cả bảy tab. Ba lựa chọn khác nhau về
 * NGHĨA, không chỉ về hình:
 *
 *  'thang' Nối thẳng điểm-tới-điểm + chấm mỗi ngày. Nét nói đúng thứ có thật:
 *          N SỐ ĐO, và giữa hai ngày thì không có dữ liệu nào. Hai ngày nghỉ
 *          thành hai chữ V gãy — đọc ra ngay là «rơi về 0».
 *  'bac'   Bậc thang CĂN GIỮA ngày. Đúng nhất về hợp đồng (`theo_ngay` là XÔ
 *          theo ngày, giá trị đúng cho trọn ngày chứ không cho một điểm lúc
 *          00:00) và rất đẹp khi một đường — nhưng người dùng chốt 'thang'.
 *  'muot'  Monotone cubic. Đẹp nhưng VẼ RA dữ liệu không có: đường cong giữa
 *          hai ngày là nội suy, mà ở đây không có lượng dùng lúc 12h trưa nằm
 *          giữa hai xô ngày.
 *
 * ⚠️ Đổi sang 'muot' thì PHẢI là monotone (Fritsch–Carlson), KHÔNG Catmull-Rom:
 * spline tự do vượt ngưỡng ở chỗ dữ liệu đổi chiều gấp, và ở đây chỗ đó là hai
 * ngày nghỉ, nên đường sẽ chui xuống dưới 0 — tức vẽ ra một lượng dùng ÂM.
 */
const KIEU_NET: 'thang' | 'bac' = 'thang'

interface Diem {
  readonly x: number
  readonly y: number
}

function netThang(p: readonly Diem[]): string {
  return p.map((o, i) => `${i ? 'L' : 'M'}${o.x.toFixed(1)},${o.y.toFixed(1)}`).join('')
}

/** Bậc thang CĂN GIỮA: đổi bậc ở ĐÚNG ranh giới giữa hai ngày. `step-after` sẽ
 *  đẩy cả hình lệch nửa ngày sang phải. */
function netBac(p: readonly Diem[]): string {
  let d = `M${p[0]!.x.toFixed(1)},${p[0]!.y.toFixed(1)}`
  for (let i = 0; i < p.length - 1; i++) {
    const xm = ((p[i]!.x + p[i + 1]!.x) / 2).toFixed(1)
    d += `L${xm},${p[i]!.y.toFixed(1)}L${xm},${p[i + 1]!.y.toFixed(1)}`
  }
  const cuoi = p[p.length - 1]!
  return `${d}L${cuoi.x.toFixed(1)},${cuoi.y.toFixed(1)}`
}

export function BieuDoLuongDung({
  chuoi,
  co,
}: {
  readonly chuoi: ChuoiTab
  readonly co?: { readonly rong: number; readonly cao: number } | undefined
}) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [doDuoc, datDoDuoc] = useState({ rong: 0, cao: 0 })
  /** `null` = không trỏ vào đâu. `x`/`y` là toạ độ CON TRỎ trong khung, dùng
   *  cho tooltip bám theo chuột — `i` một mình không đủ vì tooltip phải đi theo
   *  cả chiều dọc, còn `i` chỉ nói được cột nào. */
  const [tro, datTro] = useState<{ i: number; x: number; y: number } | null>(null)
  /** Ngày đang xem đến từ BÀN PHÍM — chỉ khi đó mới đọc nó qua vùng `aria-live`
   *  (rê chuột mà cũng đọc thì trình đọc màn hình nói liên hồi theo từng pixel). */
  const [quaPhim, datQuaPhim] = useState(false)

  useEffect(() => {
    const el = hostRef.current
    if (!el) return
    const dat = () =>
      datDoDuoc((truoc) =>
        truoc.rong === el.clientWidth && truoc.cao === el.clientHeight
          ? truoc
          : { rong: el.clientWidth, cao: el.clientHeight },
      )
    const qs = new ResizeObserver(dat)
    qs.observe(el)
    dat()
    return () => qs.disconnect()
  }, [])

  const tab = timTab(chuoi.ma)
  const W = co?.rong ?? doDuoc.rong
  const H = Math.max(co?.cao ?? doDuoc.cao, CAO_TOI_THIEU)
  const n = chuoi.gia.length
  const pr = tab.duong2 ? PR2 : PR
  const pl = tab.duong2 ? PL2 : PL

  // Chạm ra ngoài biểu đồ thì tắt tooltip cảm ứng (chuột đã tắt ở `pointerleave`).
  useEffect(() => {
    if (!tro) return
    const ngoai = (e: globalThis.PointerEvent) => {
      if (!hostRef.current?.contains(e.target as Node)) datTro(null)
    }
    document.addEventListener('pointerdown', ngoai)
    return () => document.removeEventListener('pointerdown', ngoai)
  }, [tro])

  /** Bàn phím (audit 05/10 — trước đó biểu đồ chỉ dùng được bằng chuột/chạm): Tab vào
   *  khung, ←/→ đi từng ngày, Home/End về hai đầu, Esc tắt. Không có con trỏ để
   *  bám nên tooltip đặt ở đúng cột của ngày đó, cao 1/3 khung. */
  function phim(e: SuKienPhim<HTMLDivElement>) {
    if (!W || n === 0) return
    const dang = tro?.i
    let i: number | null
    if (e.key === 'ArrowRight') i = dang === undefined ? 0 : Math.min(n - 1, dang + 1)
    else if (e.key === 'ArrowLeft') i = dang === undefined ? n - 1 : Math.max(0, dang - 1)
    else if (e.key === 'Home') i = 0
    else if (e.key === 'End') i = n - 1
    else if (e.key === 'Escape' && tro) i = null
    else return
    e.preventDefault()
    datQuaPhim(true)
    if (i === null) return datTro(null)
    const x = n === 1 ? pl + (W - pl - pr) / 2 : pl + (i * (W - pl - pr)) / (n - 1)
    datTro({ i, x, y: H / 3 })
  }

  function doTro(e: SuKienTro<HTMLDivElement>) {
    if (!W || n < 2) return
    datQuaPhim(false)
    const r = e.currentTarget.getBoundingClientRect()
    const b = (r.width - pl - pr) / (n - 1)
    const i = Math.round((e.clientX - r.left - pl) / b)
    // Sự kiện không mang toạ độ (một số trình duyệt/thiết bị, và jsdom khi
    // `PointerEvent` không tồn tại) ⇒ `i` là `NaN`, `clamp` không cứu được
    // vì `Math.min(x, NaN)` cũng là `NaN`, và `chuoi.ngay[NaN]` là
    // `undefined` ⇒ tooltip NÉM giữa lúc rê chuột. Bỏ qua lượt đó.
    if (!Number.isFinite(i)) return
    datTro({
      i: Math.max(0, Math.min(n - 1, i)),
      x: e.clientX - r.left,
      y: e.clientY - r.top,
    })
  }

  return (
    <div
      ref={hostRef}
      // `touch-pan-y`: vuốt NGANG trên biểu đồ là dò từng ngày, vuốt dọc vẫn cuộn trang.
      className="relative mt-2 min-h-[260px] flex-1 touch-pan-y"
      style={{ ...bienMau(chuoi.ma), ...(tab.duong2 ? bienMauPhu(chuoi.ma) : {}) }}
      data-bieu-do={chuoi.ma}
      // Chuột: rời khung thì tắt. CẢM ỨNG: `pointerleave` bắn ngay sau khi nhấc ngón, nên
      // tắt ở đó là tooltip chỉ loé lên — chạm giữ lại tới khi chạm ra ngoài (effect dưới).
      onPointerLeave={(e) => e.pointerType === 'mouse' && datTro(null)}
      // `pointerdown` cũng đặt tooltip: một cú CHẠM không sinh `pointermove` nào, nên bản cũ
      // chạm vào biểu đồ không hiện gì trên điện thoại (audit 05/10).
      onPointerDown={doTro}
      onPointerMove={doTro}
      tabIndex={0}
      role="group"
      aria-label={`${tab.duong2?.nhanChinh ?? tab.nhan} theo ngày. Phím mũi tên trái phải để xem từng ngày.`}
      onKeyDown={phim}
      onBlur={() => datTro(null)}
    >
      {W > 0 && n > 0 ? <Ve chuoi={chuoi} tab={tab} W={W} H={H} iTro={tro?.i ?? null} /> : null}
      {tro && W > 0 && n > 0 ? (
        <HopTip chuoi={chuoi} tab={tab} i={tro.i} x={tro.x} y={tro.y} W={W} H={H} />
      ) : null}
      <p className="sr-only" aria-live="polite" data-testid="bieu-do-doc">
        {tro && quaPhim ? docNgay(chuoi, tab, tro.i) : ''}
      </p>
    </div>
  )
}

function Ve({
  chuoi,
  tab,
  W,
  H,
  iTro,
}: {
  readonly chuoi: ChuoiTab
  readonly tab: TabUsage
  readonly W: number
  readonly H: number
  readonly iTro: number | null
}) {
  const n = chuoi.gia.length
  const donVi = tab.donVi
  const fmt = DINH_DANG[donVi]
  const d2 = tab.duong2
  const gia2 = chuoi.gia2
  const pr = d2 ? PR2 : PR
  const pl = d2 ? PL2 : PL
  const soChia = Math.max(3, Math.min(6, Math.round((H - PT - PB) / 95)))
  /* Đỉnh 0 (cả kỳ không phát sinh) ⇒ trần 1: chia cho 0 ra `NaN`, và SVG lặng
     lẽ không vẽ gì — không lỗi, không hình, không dấu hiệu. */
  const mocGoc = mocTruc(Math.max(chuoi.dinh, 1), donVi, soChia)
  /* Hai trục phải dùng CHUNG các đường kẻ ngang — xem `dongBoMoc`. */
  const [moc, moc2] =
    d2 && gia2
      ? dongBoMoc(mocGoc, mocTruc(Math.max(chuoi.dinh2 ?? 0, 1), d2.donVi, soChia))
      : [mocGoc, null]
  const tran = moc[moc.length - 1]!
  const tran2 = moc2 ? moc2[moc2.length - 1]! : 1
  /** Bước chia — quyết định ĐƠN VỊ của cả trục (xem `nhanMocTruc`). */
  const buoc = moc.length > 1 ? moc[1]! - moc[0]! : tran
  const buoc2 = moc2 && moc2.length > 1 ? moc2[1]! - moc2[0]! : tran2
  const X = (i: number) => (n === 1 ? pl + (W - pl - pr) / 2 : pl + (i * (W - pl - pr)) / (n - 1))
  const Y = (v: number) => PT + (1 - v / tran) * (H - PT - PB)
  const Y2 = (v: number) => PT + (1 - v / tran2) * (H - PT - PB)
  const day = Y(0)
  const p: Diem[] = chuoi.gia.map((v, i) => ({ x: X(i), y: Y(v) }))
  const p2: Diem[] | null = gia2 ? gia2.map((v, i) => ({ x: X(i), y: Y2(v) })) : null
  const net = (q: readonly Diem[]) => (KIEU_NET === 'bac' ? netBac(q) : netThang(q))
  const d = n < 2 ? '' : net(p)
  const dd2 = p2 && n >= 2 ? net(p2) : ''
  const cuoi = p[n - 1]!
  const gid = `u-vung-${chuoi.ma}`
  const nid = `u-net-${chuoi.ma}`
  const qid = `u-quang-${chuoi.ma}`
  const nid2 = `u-net2-${chuoi.ma}`
  const gid2 = `u-vung2-${chuoi.ma}`

  return (
    <svg
      width={W}
      height={H}
      className="absolute inset-0 block overflow-visible"
      role="img"
      aria-label={
        `${d2?.nhanChinh ?? tab.nhan} theo ngày, đơn vị ${NHAN_DON_VI[donVi]}, tổng ${fmt(chuoi.tong)}, ` +
        `hoạt động ${chuoi.soNgayHoatDong}/${n} ngày` +
        (d2
          ? `; ${d2.nhan}, đơn vị ${NHAN_DON_VI[d2.donVi]}, tổng ${DINH_DANG[d2.donVi](chuoi.tong2 ?? 0)}`
          : '')
      }
    >
      <defs>
        {/* Nét chạy ĐẶC → VỪA (`--c` → `--a`), KHÔNG `--a` → `--b`: nét là
            «graphical object» của WCAG 1.4.11 nên CẢ HAI đầu phải ≥ 3.0, mà
            `--b` chỉ đạt 1.5–1.8 — bản đầu để nửa cuối mỗi đường không đủ
            tương phản. `--b` vì thế chỉ còn phục vụ vùng tô bên dưới. */}
        <linearGradient id={nid} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="var(--c)" />
          <stop offset="1" stopColor="var(--a)" />
        </linearGradient>
        {/* Gradient dừng ở `stop-opacity: 0`, KHÔNG dừng ở một màu nền cụ thể —
            thẻ có thể đổi nền, và một màu nền ghim trong gradient thành một vệt đục. */}
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--a)" stopOpacity="0.3" />
          <stop offset="0.55" stopColor="var(--a)" stopOpacity="0.1" />
          <stop offset="1" stopColor="var(--b)" stopOpacity="0" />
        </linearGradient>
        <filter id={qid} x="-10%" y="-30%" width="120%" height="180%">
          <feGaussianBlur stdDeviation="4" />
        </filter>
        {/* Nét đường 2 chạy ĐẶC → VỪA như đường chính (`--d` → `--d2`): cả hai
            đầu đều ≥ 3.0 trên `surface`, xem `theme.css`. */}
        {d2 ? (
          <>
            <linearGradient id={nid2} x1="0" y1="0" x2="1" y2="0">
              <stop offset="0" stopColor="var(--d)" />
              <stop offset="1" stopColor="var(--d2)" />
            </linearGradient>
            {/* Vùng tô: CÙNG ba stop với đường chính, chỉ đổi token. Stop cuối
                `stop-opacity: 0` nên hue ở đó vô hình — đó là lý do bộ token
                của đường 2 không cần bậc thứ ba (`--color-ub-*`). */}
            <linearGradient id={gid2} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="var(--d2)" stopOpacity="0.3" />
              <stop offset="0.55" stopColor="var(--d2)" stopOpacity="0.1" />
              <stop offset="1" stopColor="var(--d2)" stopOpacity="0" />
            </linearGradient>
          </>
        ) : null}
      </defs>

      {moc.map((v, k) => (
        <g key={v}>
          <line
            x1={pl}
            y1={Y(v)}
            x2={W - pr}
            y2={Y(v)}
            stroke={v === 0 ? 'var(--color-border-strong)' : 'var(--color-rule)'}
            strokeWidth="1"
            strokeDasharray={v === 0 ? undefined : '3 5'}
          />
          <text
            x={pl - 10}
            y={Y(v) + 3.5}
            textAnchor="end"
            fontFamily="var(--font-mono)"
            fontSize="11"
            fill="var(--color-muted-2)"
          >
            {nhanMocTruc(donVi, v, buoc)}
          </text>
          {/* Trục PHẢI của đường 2. Nhãn sắc `muted-2` như trục trái, KHÔNG tô
              theo màu đường: cỡ 10px thì `--a` chỉ đạt 3.25–3.85, dưới ngưỡng
              4.5 của WCAG cho CHỮ. Cái buộc trục vào đường là hai thứ khác —
              chú giải trên đầu thẻ, và chính ĐỊNH DẠNG của con số (trái đọc ra
              `2m`, phải đọc ra `1.2k`). */}
          {moc2 ? (
            <text
              x={W - pr + 10}
              y={Y(v) + 3.5}
              textAnchor="start"
              fontFamily="var(--font-mono)"
              fontSize="11"
              fill="var(--color-muted-2)"
            >
              {nhanMocTruc(d2!.donVi, moc2[k]!, buoc2)}
            </text>
          ) : null}
        </g>
      ))}

      {/* NHÃN TRỤC quay dọc — chỉ ở tab hai đường (người dùng yêu cầu cho trục
          phải; trục trái đi kèm vì một biểu đồ hai trục mà chỉ một bên có nhãn
          đọc ra thành lỗi bày đặt, không thành thứ bậc).
          Tab một đường KHÔNG có: ở đó chip «đơn vị …» trên đầu thẻ đã nói, và
          thêm một nhãn dọc là hai chỗ nói cùng một điều.

          ⚠️ ĐƠN VỊ LẤY TỪ SỔ (`NHAN_DON_VI`), không gõ tay. Trục phải của STT
          là KÝ TỰ — `text_units` là ký tự theo migration `0948` và
          `billing.metric` khai `('text_units','Ký tự text',…,'character')`.
          Gõ «token» vào đây là dạy sai đúng cái đơn vị mà cả sổ tab tồn tại để
          giữ cho khỏi lệch. */}
      {d2 ? (
        <>
          <NhanTruc x={LE_NHAN_TRUC} H={H} chu={NHAN_DON_VI[donVi]} />
          <NhanTruc x={W - LE_NHAN_TRUC} H={H} chu={NHAN_DON_VI[d2.donVi]} />
        </>
      ) : null}

      {mocNgay(W - pl - pr, n).map((i) => (
        <text
          key={i}
          x={X(i)}
          y={H - 8}
          textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
          fontFamily="var(--font-mono)"
          fontSize="11"
          fill={chuoi.soPhien[i] ? 'var(--color-muted-2)' : 'var(--color-n6)'}
        >
          {ngayVN(chuoi.ngay[i]!)}
        </text>
      ))}

      {/* HAI VÙNG TÔ, vẽ trước MỌI nét — xem docstring §thứ tự vẽ. */}
      {d ? (
        <path
          d={`${d}L${cuoi.x.toFixed(1)},${day}L${p[0]!.x.toFixed(1)},${day}Z`}
          fill={`url(#${gid})`}
        />
      ) : null}
      {dd2 ? (
        <path
          d={`${dd2}L${p2![n - 1]!.x.toFixed(1)},${day}L${p2![0]!.x.toFixed(1)},${day}Z`}
          fill={`url(#${gid2})`}
        />
      ) : null}

      {d ? (
        <>
          <path
            d={d}
            fill="none"
            stroke="var(--a)"
            strokeWidth="4"
            opacity="0.3"
            filter={`url(#${qid})`}
            strokeLinecap="round"
          />
          <path
            d={d}
            fill="none"
            stroke={`url(#${nid})`}
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        </>
      ) : null}

      {/* Chấm mỗi ngày — nói ra rằng nét này nối N SỐ ĐO, không phải một dòng
          liên tục. Vẽ TRƯỚC vòng tròn ngày-0 để cái sau đè lên.

          ⚠️ TÔ ĐẶC màu đường, KHÔNG phải vòng tròn ruột trắng. Bản đầu dùng
          `fill: surface` + viền: 21 lỗ trắng nằm ĐÚNG trên nét làm đường đọc
          ra thành ĐỨT ĐOẠN — người dùng báo đúng chữ đó. Một chấm đặc cùng màu
          thì nó là một nút TRÊN đường, không phải một lỗ thủng qua đường. */}
      {KIEU_NET === 'thang'
        ? p.map((o, i) =>
            chuoi.gia[i] === 0 ? null : (
              <circle key={i} cx={o.x} cy={o.y} r="2.4" fill="var(--c)" />
            ),
          )
        : null}

      {/* ĐƯỜNG 2 — nét LIỀN màu riêng, KHÔNG quầng (vùng tô đã vẽ ở trên cùng
          hai mảng). Vẽ SAU đường chính nên nằm trên. Chấm cùng cỡ: hai đường
          ngang hàng nhau về dữ liệu, thứ bậc nói bằng quầng của đường kia. */}
      {dd2 ? (
        <>
          <path
            d={dd2}
            fill="none"
            stroke={`url(#${nid2})`}
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
            data-duong2
          />
          {p2!.map((o, i) =>
            gia2![i] === 0 ? null : <circle key={i} cx={o.x} cy={o.y} r="2.4" fill="var(--d)" />,
          )}
        </>
      ) : null}

      {/* NGÀY 0: vòng tròn RỖNG ngay trên đáy — «đã ĐO và bằng 0», phân biệt với
          «thiếu dữ liệu» (không vẽ gì). Hợp đồng §theo_ngay. */}
      {chuoi.gia.map((v, i) =>
        v === 0 ? (
          <circle
            key={`k${i}`}
            cx={X(i)}
            cy={day}
            r="2.8"
            fill="var(--color-surface)"
            stroke="var(--color-n6)"
            strokeWidth="1.2"
          />
        ) : null,
      )}

      {iTro !== null && p[iTro] ? (
        <g>
          <line
            x1={p[iTro]!.x}
            y1={PT - 6}
            x2={p[iTro]!.x}
            y2={day}
            stroke="var(--color-border-field)"
            strokeWidth="1"
            strokeDasharray="3 3"
            opacity="0.6"
          />
          <circle
            cx={p[iTro]!.x}
            cy={p[iTro]!.y}
            r="4"
            fill="var(--c)"
            stroke="var(--color-surface)"
            strokeWidth="2"
          />
          {p2?.[iTro] ? (
            <circle
              cx={p2[iTro]!.x}
              cy={p2[iTro]!.y}
              r="4"
              fill="var(--d)"
              stroke="var(--color-surface)"
              strokeWidth="2"
            />
          ) : null}
        </g>
      ) : null}
    </svg>
  )
}

/**
 * Nhãn của một trục dọc — chữ quay -90°, căn giữa theo chiều cao vùng vẽ.
 *
 * `transform` quay quanh CHÍNH điểm neo (`rotate(-90 x y)`) chứ không quanh gốc
 * SVG: quay quanh gốc rồi bù lại bằng `translate` thì mỗi lần đổi `H` phải tính
 * lại tay, và chữ trôi khỏi trục ở cỡ khung khác.
 */
function NhanTruc({ x, H, chu }: { readonly x: number; readonly H: number; readonly chu: string }) {
  const y = (PT + (H - PB)) / 2
  return (
    <text
      x={x}
      y={y}
      transform={`rotate(-90 ${x} ${y})`}
      textAnchor="middle"
      fontFamily="var(--font-mono)"
      fontSize="11"
      letterSpacing="0.05em"
      fill="var(--color-muted-2)"
      data-nhan-truc
    >
      {chu}
    </text>
  )
}

/** Câu đọc một ngày cho trình đọc màn hình — cùng nội dung với `HopTip`. */
function docNgay(chuoi: ChuoiTab, tab: TabUsage, i: number): string {
  const d2 = tab.duong2
  const sp = chuoi.soPhien[i] ?? 0
  const mot = (nhan: string, gia: number, fmt: (n: number) => string) =>
    `${nhan} ${gia === 0 ? 'không có' : fmt(gia)}`
  return (
    `${ngayVN(chuoi.ngay[i]!)}: ` +
    mot(d2?.nhanChinh ?? tab.nhan, chuoi.gia[i] ?? 0, DINH_DANG[tab.donVi]) +
    (d2 ? `; ${mot(d2.nhan, chuoi.gia2?.[i] ?? 0, DINH_DANG[d2.donVi])}` : '') +
    `; ${sp ? `${sp} phiên` : 'không có phiên'}`
  )
}

/** Cỡ ƯỚC LƯỢNG của tooltip, chỉ để quyết định LẬT bên khi chạm mép. Không đo
 *  thật (`offsetWidth`) vì đo được thì đã vẽ rồi — một lượt vẽ sai chỗ rồi nhảy
 *  là thứ mắt bắt được. Ước hơi dư an toàn hơn ước thiếu. */
const TIP_RONG = 190
const TIP_CAO = 58
const TIP_LE = 14

/**
 * Tooltip BÁM CON TRỎ — trong luồng, KHÔNG `createPortal`.
 *
 * ⚠️ Bản đầu ghim `top-2 right-2`: nó đứng yên một chỗ trong khi con trỏ chạy
 * dọc trục, nên mắt phải nhảy qua lại giữa điểm đang trỏ và một hộp ở góc —
 * người dùng báo đúng chỗ đó. Nay đặt theo `x`/`y` của con trỏ (toạ độ trong
 * khung, tính ở `onPointerMove`), lệch sang phải-trên một quãng `TIP_LE` để
 * không nằm dưới chính mũi chuột, và TỰ LẬT sang trái / xuống dưới khi sắp
 * tràn mép khung.
 *
 * Khác `HopTip` của `/dashboard` (nó phải ra `document.body` vì tổ tiên có
 * `transform`): thẻ này không có `transform` và không `overflow-hidden` ở tầng
 * nào giữa đây và mép thẻ, nên một `absolute` là đủ. ⚠️ Thêm `hover:scale`/
 * `hover:-translate` cho thẻ bao là làm tooltip bị cắt VÀ trôi khỏi con trỏ —
 * đúng bug `/dashboard` đã sập 2026-08-14.
 */
function HopTip({
  chuoi,
  tab,
  i,
  x,
  y,
  W,
  H,
}: {
  readonly chuoi: ChuoiTab
  readonly tab: TabUsage
  readonly i: number
  readonly x: number
  readonly y: number
  readonly W: number
  readonly H: number
}) {
  const sp = chuoi.soPhien[i] ?? 0
  const d2 = tab.duong2
  const latTrai = x + TIP_LE + TIP_RONG > W
  // Hộp hai dòng cao hơn hộp một dòng — ước dư đúng một dòng, nếu không thì ở
  // sát mép trên nó không lật và bị cắt mất dòng cuối.
  const latDuoi = y - TIP_LE - (d2 ? TIP_CAO + 16 : TIP_CAO) < 0
  return (
    <div
      role="tooltip"
      data-lat={`${latTrai ? 'trai' : 'phai'}-${latDuoi ? 'duoi' : 'tren'}`}
      style={{
        left: latTrai ? undefined : x + TIP_LE,
        right: latTrai ? W - x + TIP_LE : undefined,
        top: latDuoi ? y + TIP_LE : undefined,
        bottom: latDuoi ? undefined : H - y + TIP_LE,
      }}
      className="pointer-events-none absolute z-10 rounded-md bg-panel px-[11px] py-[9px] text-nhan whitespace-nowrap text-white shadow-lg"
    >
      <div className="mb-1 border-b border-white/15 pb-[5px] font-semibold">
        {ngayVN(chuoi.ngay[i]!)} · {sp ? `${sp} phiên` : 'không có phiên'}
      </div>
      <DongTip
        nhan={d2?.nhanChinh ?? tab.nhan}
        gia={chuoi.gia[i] ?? 0}
        fmt={DINH_DANG[tab.donVi]}
      />
      {d2 ? (
        <DongTip nhan={d2.nhan} gia={chuoi.gia2?.[i] ?? 0} fmt={DINH_DANG[d2.donVi]} phu />
      ) : null}
    </div>
  )
}

/**
 * Một dòng giá trị của tooltip. `phu` vẽ ô mẫu bằng màu của ĐƯỜNG 2 — cùng sắc
 * với nét trên biểu đồ, nên ô mẫu là thứ buộc dòng vào đường.
 *
 * `0` in ra `—` chứ không `0`: ngày đã đo và bằng 0 đã được nói bằng vòng tròn
 * rỗng trên chính biểu đồ; lặp lại nó ở đây thành hai cách nói cho một điều.
 */
function DongTip({
  nhan,
  gia,
  fmt,
  phu,
}: {
  readonly nhan: string
  readonly gia: number
  readonly fmt: (n: number) => string
  readonly phu?: boolean
}) {
  return (
    <div className="flex items-center gap-[9px] text-nhan">
      <i
        aria-hidden
        className="h-[3px] w-3 flex-none rounded-sm"
        style={{
          background: phu
            ? 'linear-gradient(90deg,var(--d),var(--d2))'
            : 'linear-gradient(90deg,var(--a),var(--b))',
        }}
      />
      <span className="flex-1">{nhan}</span>
      <b className="font-mono font-medium tabular-nums">{gia === 0 ? '—' : fmt(gia)}</b>
    </div>
  )
}
