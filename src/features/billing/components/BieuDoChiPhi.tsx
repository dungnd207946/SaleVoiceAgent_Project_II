/**
 * Thẻ TRÁI của mục ② `/billing` — chi phí theo NGÀY, đường + vùng tô.
 *
 * PORT hình học từ `docs/design/demo-usage-billing.html` § `veChart()` sang JSX SVG
 * thuần: cùng lề (48/10/14/24), cùng bốn vạch mờ + nhãn `k`, cùng nền cuối
 * tuần, cùng đường trung bình gạch đứt, cùng nhãn ngày chỉ ở mốc 1·5·10·…
 *
 * MỘT ĐƯỜNG, KHÔNG PHẢI CỘT CHỒNG THEO COMPONENT — quyết định của bản demo,
 * giữ nguyên: thẻ «Theo component» ngay bên phải đã mã hoá chiều component và
 * làm tốt hơn hẳn; chart này lo chiều THỜI GIAN. Cột chồng cũng không còn chỗ
 * cho đường trung bình, mốc so sánh rẻ nhất của cả thẻ.
 *
 * ⚠️ `Number(chi_phi)` CHỈ để tính TOẠ ĐỘ PIXEL. Mọi con số ĐƯA LÊN MÀN đi qua
 * `tien()`/`chiaTien()` (nhận `Tien` = chuỗi). Hai việc khác nhau: sai số float
 * ở chữ số thứ 16 dịch một điểm chart đi 0 pixel, nhưng ở một con số tiền thì
 * nó là một con số sai. Đừng "gọn hoá" bằng cách parse một lần rồi dùng chung.
 *
 * ĐO KHUNG bằng `ResizeObserver` chứ không `viewBox` cố định: thẻ nằm trong
 * lưới `luoi-tien` và bị thẻ bên cạnh kéo cao/thấp theo nội dung. `viewBox` cố
 * định co giãn cả CHỮ theo tỷ lệ khung — đúng thứ làm chart bản demo vòng 2
 * không bo sát thẻ. Prop `co` ghi đè phép đo, dành cho test (jsdom luôn trả
 * `clientWidth = 0`) — cùng khuôn `BieuDoNgay` của `features/ops`.
 *
 * ⚠️ ĐO CẢ HAI CHIỀU, và chiều CAO là chiều dễ quên. Bản đầu chỉ đo bề rộng
 * rồi khoá `height` vào một hằng 260px — trong khi thẻ này nằm trong lưới
 * `items-stretch` cạnh thẻ «Theo component», thẻ kia cao bao nhiêu thì thẻ này
 * bị kéo cao bấy nhiêu (đo được: ~430px). Thân thẻ giãn theo, nhưng SVG thì
 * không: chart nằm gọn ở NỬA TRÊN, để lại một mảng trắng bên dưới. Chiều cao
 * là thứ do BỐ CỤC quyết định, không phải thứ component tự đặt — hằng dưới đây
 * vì thế là `min-height` (sàn để chart không bị bóp dẹp khi thẻ bên kia ngắn),
 * KHÔNG phải `height`.
 */
import { useEffect, useRef, useState } from 'react'
import { MAU_KHONG_TINH_TIEN, nhanComponent } from '../component-hien'
import { SO, chiaTien, tien, type Tien } from '../dinh-dang'
import type { DongNgay } from '../kieu'

/**
 * Lề vùng vẽ, TÍNH TỪ MÉP THẺ. Bản demo có hai tầng lề (thẻ `padding:10px 14px
 * 6px` rồi `veChart()` cộng thêm 48/10/14/24 bên trong) — ở đây gộp lại thành
 * một tầng: SVG phủ trọn thân thẻ (`inset-0`), mọi khoảng trắng nằm trong bốn
 * hằng này. Hai tầng lề mà chỉ nhớ một là cách chart lệch khỏi thẻ.
 * `PL` rộng nhất vì nó phải chứa nhãn trục tiền («125k»).
 */
const PT = 18
const PR = 20
const PB = 28
const PL = 56
/** SÀN, không phải chiều cao cố định — xem cảnh báo ở docstring đầu file. */
const CAO_TOI_THIEU = 244
const SO_MOC = 4

/** Bước lưới «đẹp» gần nhất phủ được `dinh` trong ~`SO_MOC` vạch. Không có
 *  bước cố định như bản demo (`25000`): dữ liệu thật của một workspace nhỏ có
 *  đỉnh vài nghìn đồng, một bước 25k cho ra biểu đồ phẳng lì sát đáy. */
function buocLuoi(dinh: number): number {
  if (dinh <= 0) return 1
  const tho = dinh / SO_MOC
  const bac = 10 ** Math.floor(Math.log10(tho))
  const ty = tho / bac
  const nhan = ty <= 1 ? 1 : ty <= 2 ? 2 : ty <= 2.5 ? 2.5 : ty <= 5 ? 5 : 10
  return nhan * bac
}

/** `YYYY-MM-DD` → thứ trong tuần theo giờ ĐỊA PHƯƠNG. `new Date(iso)` parse
 *  chuỗi ISO trần theo UTC nên lệch một ngày ở múi giờ âm — cùng bẫy đã ghi ở
 *  `features/ops/components/BieuDoNgay.tsx::ngayLe`. */
function thu(iso: string): number {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y ?? 0, (m ?? 1) - 1, d ?? 1).getDay()
}

/**
 * Nhãn trục ngang: `dd/MM` — CÓ THÁNG, và theo đúng khuôn ngày của portal
 * (`01/08 – 31/08/2026` ở hàng chọn kỳ ngay phía trên, `dinhDangLuc()` ở
 * `/pricing`). KHÔNG dùng dạng «Aug 01»: đó sẽ là chuỗi tháng tiếng Anh duy
 * nhất trong một giao diện tiếng Việt, và nó lệch khuôn với chính khoảng ngày
 * mà người dùng vừa đọc cách đó 40px.
 *
 * Bỏ tháng đi (bản đầu chỉ hiện `01`, `05`, `10`) là buộc người đọc suy tháng
 * từ nút kỳ đang chọn — và với kỳ «30 ngày» thì chuỗi BẮC QUA hai tháng, lúc
 * đó không suy được nữa.
 */
function nhanNgay(iso: string): string {
  const [, m = '', d = ''] = iso.split('-')
  return `${d}/${m}`
}

/** `dd/MM/yyyy` — tooltip có chỗ cho cả năm, trục ngang thì không. */
function nhanNgayDay(iso: string): string {
  const [y = '', m = '', d = ''] = iso.split('-')
  return `${d}/${m}/${y}`
}

function nhanMoc(v: number): string {
  return v >= 10_000 ? `${SO(Math.round(v / 1000))}k` : SO(Math.round(v))
}

/**
 * Bước nhảy nhãn ngày, tính theo CHỈ SỐ chứ không theo ngày-trong-tháng.
 * Bản demo chọn mốc 1·5·10·15·20 — đúng cho đúng một kỳ là «tháng này»; kỳ
 * «7 ngày» rơi vào 14→20 chỉ còn hai nhãn, và kỳ «30 ngày» bắc qua hai tháng
 * thì mốc lặp lại. Theo chỉ số thì mọi kỳ đều ra ~6 nhãn, luôn có ngày đầu và
 * ngày cuối.
 */
function buocNhanNgay(n: number): number {
  return Math.max(1, Math.ceil(n / 6))
}

export function BieuDoChiPhi({
  chuoi,
  chiPhiTong,
  mau,
  co,
}: {
  readonly chuoi: readonly DongNgay[]
  readonly chiPhiTong: Tien
  /** `component → màu`, phát từ `bangMau()` ở tầng trên. DÙNG CHUNG với thẻ
   *  «Theo component» — xem `component-hien.ts` vì sao không tự tính ở đây. */
  readonly mau: Readonly<Record<string, string>>
  readonly co?: { readonly rong: number; readonly cao: number } | undefined
}) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const [doDuoc, datDoDuoc] = useState({ rong: 0, cao: 0 })

  useEffect(() => {
    const el = hostRef.current
    if (!el || co) return
    // So TRƯỚC khi `set`: mỗi lần đặt state là một object MỚI, nên `set` vô
    // điều kiện làm React vẽ lại ở mọi lượt observer bắn (kể cả lượt kích
    // thước không đổi), và vòng vẽ-lại đó lại chạm layout.
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
  }, [co])

  const [dangTro, datDangTro] = useState<number | null>(null)

  const W = co?.rong ?? doDuoc.rong
  const H = co?.cao ?? doDuoc.cao
  const w = W - PL - PR
  const h = H - PT - PB
  const n = chuoi.length

  // Vẽ được hay không thì HÀNG ĐẦU THẺ vẫn phải hiện (nó mang «TB …/ngày») —
  // nên phép chặn nằm quanh riêng phần SVG, không quanh cả component. Chặn cả
  // chiều cao: lượt render ĐẦU (trước khi `ResizeObserver` kịp đo) có `H = 0`,
  // và `h` âm cho ra một `path` với toạ độ ngược.
  const veDuoc = W >= 120 && H >= 120 && n >= 2

  const gt = chuoi.map((d) => Number(d.chi_phi))
  const dinh = Math.max(...gt, 0)
  const buoc = buocLuoi(dinh)
  const tran = Math.max(Math.ceil(dinh / buoc) * buoc, buoc)
  const X = (i: number) => PL + (w * i) / (n - 1)
  const Y = (v: number) => PT + h - (v / tran) * h
  const buocNhan = buocNhanNgay(n)
  const tb = chiaTien(chiPhiTong, Math.max(n, 1))
  const yTb = Y(Number(tb))

  const moc: number[] = []
  for (let v = buoc; v <= tran + 1e-9; v += buoc) moc.push(v)

  const diem = chuoi.map((_, i) => `${X(i).toFixed(1)},${Y(gt[i] ?? 0).toFixed(1)}`)
  const duong = `M${diem.join(' L')}`
  const vung = `M${PL},${Y(0)} L${diem.join(' L')} L${PL + w},${Y(0)} Z`

  const tro = dangTro === null ? null : chuoi[dangTro]

  return (
    <div className="flex min-w-0 flex-col rounded-lg border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-rule px-4 py-2.5">
        <h3 className="text-than font-medium text-fg">Chi phí theo ngày</h3>
        <p className="ml-auto text-phu text-muted">
          <b className="font-mono font-medium tabular-nums text-fg">TB {tien(tb)}đ/ngày</b>
        </p>
      </div>
      <div ref={hostRef} className="relative flex-1" style={{ minHeight: CAO_TOI_THIEU }}>
        {veDuoc && (
          <svg
            width={W}
            height={H}
            className="absolute inset-0 overflow-visible"
            role="img"
            aria-label={`Chi phí theo ngày, ${n} ngày, tổng ${tien(chiPhiTong)} ₫`}
          >
            <defs>
              {/* `stop-color` qua ATTRIBUTE không phân giải `var()` — nó rơi về
                  mặc định, im lặng. Đặt qua `style` (bẫy đã ghi ở `BieuDoNgay`). */}
              <linearGradient id="bd-chi-phi" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" style={{ stopColor: 'var(--color-ac)', stopOpacity: 0.22 }} />
                <stop offset="100%" style={{ stopColor: 'var(--color-ac)', stopOpacity: 0.02 }} />
              </linearGradient>
            </defs>

            {/* Nền cuối tuần — nhịp tuần đọc được mà không tốn một dòng chú thích */}
            {chuoi.map((d, i) => {
              const t = thu(d.ngay)
              if (t !== 0 && t !== 6) return null
              const x0 = i === 0 ? PL : (X(i) + X(i - 1)) / 2
              const x1 = i === n - 1 ? PL + w : (X(i) + X(i + 1)) / 2
              return (
                <rect
                  key={d.ngay}
                  x={x0}
                  y={PT}
                  width={Math.max(x1 - x0, 1)}
                  height={h}
                  fill="var(--color-n3)"
                  opacity={0.55}
                />
              )
            })}

            {moc.map((v) => (
              <g key={v}>
                <line
                  x1={PL}
                  x2={PL + w}
                  y1={Y(v)}
                  y2={Y(v)}
                  stroke="var(--color-border)"
                  shapeRendering="crispEdges"
                />
                <text
                  x={PL - 9}
                  y={Y(v) + 3.5}
                  textAnchor="end"
                  className="fill-muted-2 font-mono text-nhan"
                >
                  {nhanMoc(v)}
                </text>
              </g>
            ))}
            <line
              x1={PL}
              x2={PL + w}
              y1={Y(0)}
              y2={Y(0)}
              stroke="var(--color-border-strong)"
              shapeRendering="crispEdges"
            />
            <text
              x={PL - 9}
              y={Y(0) + 3.5}
              textAnchor="end"
              className="fill-muted-2 font-mono text-nhan"
            >
              0
            </text>

            <line
              x1={PL}
              x2={PL + w}
              y1={yTb}
              y2={yTb}
              stroke="var(--color-n6)"
              strokeDasharray="3 3"
            />
            {/* Nhãn mang LUÔN CON SỐ. Bản đầu chỉ ghi «TB» và người đọc đầu
                tiên đã phải hỏi «đường này là gì» — một chú thích cần người
                khác giải thích thì nó chưa làm xong việc của nó. */}
            <text
              x={PL + w}
              y={yTb - 6}
              textAnchor="end"
              className="fill-muted-2 font-mono text-nhan"
            >
              TB {tien(tb)} ₫
            </text>

            <path d={vung} fill="url(#bd-chi-phi)" />
            <path
              d={duong}
              fill="none"
              stroke="var(--color-ac)"
              strokeWidth={1.75}
              strokeLinejoin="round"
              strokeLinecap="round"
            />

            {chuoi.map((d, i) => {
              if (i % buocNhan !== 0 && i !== n - 1) return null
              // Hai nhãn cuối chồng nhau khi `n - 1` không rơi đúng bước —
              // bỏ nhãn theo bước, giữ nhãn CUỐI (mốc kết kỳ đáng đọc hơn).
              if (i !== n - 1 && n - 1 - i < buocNhan / 2) return null
              return (
                <text
                  key={d.ngay}
                  x={X(i)}
                  y={H - 8}
                  textAnchor={i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'}
                  className={
                    i === 0 || i === n - 1
                      ? 'fill-fg font-mono text-nhan font-medium'
                      : 'fill-muted-2 font-mono text-nhan'
                  }
                >
                  {nhanNgay(d.ngay)}
                </text>
              )
            })}

            {/* Vùng bắt chuột theo CỘT, không theo điểm: rê ngang bất kỳ đâu
                trong dải của một ngày cũng đọc được ngày đó. */}
            {chuoi.map((d, i) => {
              const x0 = i === 0 ? PL : (X(i) + X(i - 1)) / 2
              const x1 = i === n - 1 ? PL + w : (X(i) + X(i + 1)) / 2
              const hien = dangTro === i
              return (
                <g
                  key={d.ngay}
                  tabIndex={0}
                  onMouseEnter={() => datDangTro(i)}
                  onFocus={() => datDangTro(i)}
                  onMouseLeave={() => datDangTro(null)}
                  onBlur={() => datDangTro(null)}
                  aria-label={`${nhanNgayDay(d.ngay)}: ${tien(d.chi_phi)} ₫`}
                >
                  {hien && (
                    <>
                      <line
                        x1={X(i)}
                        x2={X(i)}
                        y1={PT}
                        y2={Y(0)}
                        stroke="var(--color-ac)"
                        strokeDasharray="2 2"
                      />
                      <circle
                        cx={X(i)}
                        cy={Y(gt[i] ?? 0)}
                        r={4}
                        fill="var(--color-surface)"
                        stroke="var(--color-ac)"
                        strokeWidth={2}
                      />
                    </>
                  )}
                  <rect x={x0} y={PT} width={Math.max(x1 - x0, 1)} height={h} fill="transparent" />
                </g>
              )
            })}
          </svg>
        )}

        {tro && dangTro !== null && (
          <div
            className="pointer-events-none absolute z-10 min-w-[196px] -translate-x-1/2 -translate-y-full rounded-md bg-panel px-3 py-2.5 text-n1 shadow-noi"
            // Kẹp theo bề ngang thẻ: tooltip rộng ~200px và neo giữa, nên ở
            // hai ngày ĐẦU/CUỐI nó tràn ra ngoài thẻ (bị cắt bên trái, hoặc
            // đè sang thẻ «Theo component» bên phải).
            style={{
              left: Math.min(Math.max(X(dangTro), 104), W - 104),
              top: Y(Number(tro.chi_phi)) - 12,
            }}
            role="status"
          >
            <p className="font-mono text-nhan opacity-70">{nhanNgayDay(tro.ngay)}</p>
            <p className="mt-1.5 flex items-baseline justify-between gap-5 border-b border-white/15 pb-1.5 text-phu font-semibold">
              <span>Tổng</span>
              <span className="font-mono tabular-nums">{tien(tro.chi_phi)} ₫</span>
            </p>
            {/* Tách theo component — thứ thẻ bên phải chỉ trả lời được cho CẢ
                KỲ. Lọc dòng 0 đồng: một component chưa có giá (hoặc purpose
                không tính tiền) vẫn có hàng ở BE, và `0 ₫` xen giữa các dòng
                có tiền chỉ làm loãng thứ người ta đang đọc. */}
            {tro.phan.filter((x) => Number(x.chi_phi) !== 0).length > 0 ? (
              <ul className="mt-1.5 flex flex-col gap-0.5">
                {tro.phan
                  .filter((x) => Number(x.chi_phi) !== 0)
                  .map((x) => (
                    <li key={x.component} className="flex items-center gap-2 text-nhan">
                      <i
                        aria-hidden
                        className="size-2 flex-none rounded-[2px]"
                        style={{ background: mau[x.component] ?? MAU_KHONG_TINH_TIEN }}
                      />
                      <span className="opacity-90">{nhanComponent(x.component)}</span>
                      <span className="ml-auto font-mono tabular-nums">{tien(x.chi_phi)}</span>
                    </li>
                  ))}
              </ul>
            ) : (
              <p className="mt-1.5 text-nhan opacity-70">Không phát sinh</p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
