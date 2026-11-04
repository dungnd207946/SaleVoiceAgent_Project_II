/**
 * Sparkline tiền theo ngày cho thẻ «Tổng chi phí» (mục ① `/billing`).
 *
 * ⚠️ VÌ SAO NÓ LÀ MỘT COMPONENT RIÊNG THAY VÌ MỘT HOOK TRONG `UsageScreen`.
 * Bản đầu (2026-08-21) gọi `usePhanTich(from, to)` ngay trong thân
 * `UsageScreen` rồi truyền `theo_ngay` xuống. Sai, và sai theo cách đo được:
 * thân component chạy ở MỌI nhánh — `/summary` đang tải, `/summary` lỗi,
 * `so_phien === 0` — nên nó bắn `/breakdown` ở cả ba nhánh mà mục ② (chỗ DUY
 * NHẤT cần dữ liệu đó) không hề mount. Một request cho một cái card không
 * render, và trong test thì `onUnhandledRequest: 'error'` của `vitest.setup.ts`
 * biến nó thành 9 bài đỏ ở những nhánh vốn chưa bao giờ chạm `/breakdown`.
 *
 * Đặt phép gọi vào một component chỉ được mount TRONG nhánh thành công thì
 * hình học của request khớp lại với hình học của giao diện: không nhánh nào
 * khác chạm tới nó. Và vẫn KHÔNG thêm request nào — `PhanTichChiPhi` ngay dưới
 * dùng đúng `queryKey` này, nên React Query gộp hai observer thành một lượt.
 *
 * KHÔNG hiện gì khi đang tải hoặc lỗi (không skeleton, không câu báo): năm con
 * số của mục ① sống bằng `/summary` và đã hiện xong: `/breakdown` hỏng thì thẻ
 * mất đúng cái hình. Mục ② ngay dưới là chỗ báo lỗi ấy, một lần, kèm nút thử
 * lại — báo hai lần cho cùng một request là hai lần cho một sự cố.
 */
import { usePhanTich } from '../api'
import type { DongNgay } from '../kieu'

/**
 * `viewBox` + `preserveAspectRatio="none"` thay cho đo bề rộng: thẻ này rộng
 * 1/5 hàng và co theo lưới, nên không có con số pixel nào đúng ở mọi cỡ màn.
 * `BieuDoChiPhi` phải đo bằng `ResizeObserver` vì nó có nhãn TRỤC — chữ mà bị
 * kéo giãn phi tỉ lệ thì méo; ở đây không có chữ nào nên kéo giãn là vô hại.
 * ⚠️ Đúng một thứ KHÔNG được giãn theo: nét vẽ. `vector-effect="non-scaling-stroke"`
 * giữ nó 1.4px thật — thiếu nó thì nét dày mỏng khác nhau theo bề rộng thẻ.
 *
 * ⚠️ `Number(chi_phi)` CHỈ để tính TOẠ ĐỘ — cùng luật đã ghi ở đầu
 * `BieuDoChiPhi.tsx`. Không con số nào của hàm này lên màn dưới dạng chữ.
 *
 * Trả `null` ở hai ca, cả hai đều là ca THẬT:
 *   · dưới 2 điểm — kỳ «Tháng này» vào đúng ngày 1 chỉ có MỘT ngày, và một
 *     `polyline` một điểm không vẽ ra gì ngoài một dấu chấm vô nghĩa;
 *   · đỉnh = 0 — kỳ có phiên nhưng chưa quy ra tiền (thiếu dòng giá). Chia cho
 *     0 ra `NaN` và SVG lặng lẽ không vẽ; chặn ở đây để nó là quyết định chứ
 *     không phải tai nạn. Con số 0 trên thẻ đã nói đủ điều đó rồi.
 *
 * `caoPx` TUỲ CHỌN (mặc định 30, khớp thẻ «Tổng chi phí» mục ① `/billing`) —
 * ô Chi phí `/dashboard` (`TongQuanScreen.tsx`, qua `features/billing/contracts`)
 * truyền một số NHỎ HƠN vì tile ở đó hẹp hơn hẳn thẻ KPI. `viewBox` giữ
 * NGUYÊN `H = 30` bất kể `caoPx` — toạ độ Y không đổi, chỉ HỘP HIỂN THỊ co
 * lại; `preserveAspectRatio="none"` vốn đã kéo giãn phi tỉ lệ nên bóp chiều
 * cao không làm méo gì thêm. Đặt qua `style`, KHÔNG qua class Tailwind động
 * (`h-[${caoPx}px]`) — scanner JIT của Tailwind v4 chỉ phát biến/class nó
 * NHÌN THẤY được trong mã nguồn dạng chuỗi tĩnh (cùng bẫy đã ghi ở
 * `theme.css` cho bảy hệ màu gradient của `/usage`), một class ghép bằng
 * template string sẽ bị cắt khỏi bundle production.
 */
function Ve({ chuoi, caoPx }: { readonly chuoi: readonly DongNgay[]; readonly caoPx: number }) {
  const gt = chuoi.map((d) => Number(d.chi_phi))
  const dinh = Math.max(...gt, 0)
  if (gt.length < 2 || dinh <= 0) return null

  const W = 100
  const H = 30
  const x = (i: number) => (i / (gt.length - 1)) * W
  // 1px chừa mỗi đầu: đỉnh cao nhất chạm mép trên thì nét bị cắt một nửa.
  const y = (v: number) => H - 1 - (v / dinh) * (H - 2)
  const diem = gt.map((v, i) => `${x(i).toFixed(2)},${y(v).toFixed(2)}`).join(' ')

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      // `aria-hidden`: con số của kỳ đã là chữ ngay trên, và mục ② vẽ lại chính
      // chuỗi này kèm nhãn ngày. Hình ở đây không mang tin mới.
      aria-hidden="true"
      className="mt-0.5 block w-full"
      style={{ height: `${caoPx}px` }}
    >
      <polygon points={`0,${H} ${diem} ${W},${H}`} fill="var(--color-ac)" fillOpacity=".1" />
      <polyline
        points={diem}
        fill="none"
        stroke="var(--color-ac)"
        strokeWidth="1.4"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  )
}

export function SparklineChiPhi({
  from,
  to,
  caoPx = 30,
}: {
  readonly from: string
  readonly to: string
  readonly caoPx?: number
}) {
  const q = usePhanTich(from, to)
  if (!q.data) return null
  return <Ve chuoi={q.data.theo_ngay} caoPx={caoPx} />
}
