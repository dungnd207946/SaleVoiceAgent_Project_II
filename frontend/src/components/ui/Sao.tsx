/**
 * Hiển thị rating 1-5 sao (chỉ đọc — không phải input chọn sao). Dùng ở
 * `/quality` (danh sách + tổng quan) và `PhienKhach.tsx` (feedback một phiên).
 *
 * `gia` nhận SỐ LẺ: 3.58 ⇒ ba sao tô đầy + ngôi thứ tư tô 58% bề rộng. Điểm
 * trung bình gần như không bao giờ tròn, và làm tròn nó lên/xuống một sao là
 * bịa ra tới nửa sao chênh so với con số in ngay cạnh (`4.5` mà 5 sao đầy đọc
 * thành "hoàn hảo"). Rating của MỘT feedback thì luôn là số nguyên nên nhánh
 * lẻ không bao giờ chạy ở danh sách.
 *
 * `data-sao="on"/"off"/"phan"` — móc test, không phải class hiển thị; sao tô
 * một phần thêm `data-phan="<phần trăm>"`.
 */
import { Icon } from '@/components/icons'

const NAM_SAO = [1, 2, 3, 4, 5] as const

/** Phần trăm bề rộng được tô của ngôi sao thứ `n` — 0, 100, hoặc ở giữa. */
function phanTramCuaSao(n: number, gia: number): number {
  if (gia >= n) return 100
  if (gia <= n - 1) return 0
  // Làm tròn về số nguyên phần trăm: 99.6% và 0.4% mắt không phân biệt được
  // với đầy/rỗng, nhưng lại rơi vào nhánh "một phần" và vẽ thêm một lớp phủ.
  return Math.round((gia - (n - 1)) * 100)
}

export function Sao({ gia, kichThuoc = 14 }: { gia: number; kichThuoc?: number }) {
  const co = { width: kichThuoc, height: kichThuoc }
  return (
    // `role="img"` + tên bằng chữ: năm icon `aria-hidden` không nói gì với trình đọc màn
    // hình, mà đây là dữ liệu chính của `/quality` (WCAG 1.1.1, audit 05/10 P1 #4).
    <span
      role="img"
      aria-label={`${gia.toLocaleString('vi-VN', { maximumFractionDigits: 2 })} trên 5 sao`}
      className="inline-flex items-center gap-0.5 text-ac"
    >
      {NAM_SAO.map((n) => {
        const phan = phanTramCuaSao(n, gia)
        if (phan === 100)
          return (
            <span key={n} data-sao="on">
              <Icon name="star" className="fill-current text-ac" style={co} />
            </span>
          )
        if (phan === 0)
          return (
            <span key={n} data-sao="off">
              <Icon name="star" className="text-border-field" style={co} />
            </span>
          )
        return (
          <span
            key={n}
            data-sao="phan"
            data-phan={phan}
            className="relative inline-block shrink-0"
            style={co}
          >
            <Icon name="star" className="absolute inset-0 text-border-field" style={co} />
            {/* Lớp phủ cắt theo bề rộng — sao bên dưới vẫn vẽ trọn nét viền,
                nên phần chưa đạt tới không bị mất đường bao. */}
            <span
              className="absolute inset-y-0 left-0 overflow-hidden"
              style={{ width: `${phan}%` }}
            >
              <Icon name="star" className="fill-current text-ac" style={co} />
            </span>
          </span>
        )
      })}
    </span>
  )
}
