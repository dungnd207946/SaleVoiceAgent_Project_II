/**
 * Thanh phân trang — `‹ 1 2 [3] … 12 ›` + ô chọn số hàng.
 *
 * `nav[aria-label]` chứ không một `<div>`: đây là điều hướng, và test lẫn trình
 * đọc màn hình đều cần một mốc để tra thanh này thay vì mọi nút số trên trang.
 *
 * ⚠ `dangTai` KHÔNG phải cờ trang trí — thiếu nó thì thanh này NÓI DỐI. Trước
 * khi response đầu về, `total` là 0 nên thanh vẽ ra «Hiện 0–0 / 0» kèm đúng một
 * nút trang «1» đang bật: ba khẳng định về một tập dữ liệu chưa ai biết gì.
 * Người dùng thấy nó chớp qua ở MỌI lần mở bảng, và test thấy tệ hơn thế —
 * `await findByRole('navigation')` trả về NGAY, nên một bài chờ thanh rồi bấm
 * nút trang «3» sẽ đọc bảng lúc nó còn rỗng.
 *
 * Đó là cách 3 bài `tests/realestate-phan-trang.test.tsx` đỏ suốt từ `80a581c`
 * (26/08): commit đó bỏ early-return `isPending` khỏi `CanTab` — bỏ là ĐÚNG,
 * tiền đề «phân khu bắt buộc» đã chết từ migration `0902` — nhưng early-return
 * ấy đang âm thầm gánh vai trò cổng CHỜ DỮ LIỆU cho thanh này. Nay cổng nằm
 * đúng chỗ của nó: thanh tự biết mình chưa có gì để nói.
 *
 * Chuyển từ `features/realestate/components/` sang đây khi `/convos` cần cùng
 * thanh phân trang — cùng lý do và cùng khuôn shim như `Bang`.
 *
 * `useTrangSo` dùng `placeholderData: keepPreviousData`, nên `isPending` chỉ
 * bật ở lần nạp ĐẦU. Đổi trang hay đổi bộ lọc thì thanh KHÔNG biến mất — không
 * có cú nhảy bố cục nào, và đó là lý do cờ này lấy `isPending` chứ không phải
 * `isFetching`.
 */
import { NUT_PHU } from './Bang'

/** Các cỡ trang MẶC ĐỊNH cho ô «Mỗi trang» (bảng realestate). Sống ở đây
 *  (không ở `useTrangSo` của realestate) để module khác dùng được thanh này mà
 *  không import chéo module (Luật 3). Màn cần bộ cỡ khác thì truyền `luaChon`
 *  — đừng sửa hằng này, nó đổi ô chọn của cả bốn bảng realestate. */
export const SO_HANG_CHON = [20, 50, 100] as const

// `max-md:` 40px — vùng chạm ≥40px trên mobile (spec responsive §5.4); bản cũ 28px.
const NUT_TRANG = 'min-w-8 rounded px-2 py-1 text-than max-md:h-10 max-md:min-w-10'

interface Props {
  trang: number
  soTrang: number
  total: number
  soHang: number
  doiTrang: (n: number) => void
  /** Vắng ⇒ không có ô «Mỗi trang» — cỡ trang cố định (bảng phiên của `/billing`). */
  doiSoHang?: (n: number) => void
  /**
   * Lần nạp ĐẦU chưa xong ⇒ không render gì. Mặc định `false` cho chỗ gọi đã
   * cầm sẵn dữ liệu trong tay (`VungMedia` phân trang client-side).
   */
  dangTai?: boolean
  /** Các cỡ trang trong ô «Mỗi trang». Vắng = `SO_HANG_CHON`. */
  luaChon?: readonly number[]
}

/** Dãy số trang quanh trang hiện tại, `null` = dấu `…`. */
function daySo(trang: number, soTrang: number): (number | null)[] {
  if (soTrang <= 7) return Array.from({ length: soTrang }, (_, i) => i + 1)
  const quanh = [trang - 1, trang, trang + 1].filter((n) => n > 1 && n < soTrang)
  const day: (number | null)[] = [1]
  if (quanh[0] !== undefined && quanh[0] > 2) day.push(null)
  day.push(...quanh)
  if (quanh[quanh.length - 1] !== undefined && quanh[quanh.length - 1]! < soTrang - 1)
    day.push(null)
  day.push(soTrang)
  return day
}

export function ThanhTrang({
  trang,
  soTrang,
  total,
  soHang,
  doiTrang,
  doiSoHang,
  dangTai = false,
  luaChon = SO_HANG_CHON,
}: Props) {
  if (dangTai) return null

  const dau = total === 0 ? 0 : (trang - 1) * soHang + 1
  const cuoi = Math.min(trang * soHang, total)

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 px-3 py-2 text-than">
      <span className="text-muted">
        Hiện {dau}–{cuoi} / {total}
      </span>

      <nav aria-label="Phân trang" className="flex items-center gap-1">
        <button
          type="button"
          className={NUT_PHU}
          disabled={trang <= 1}
          onClick={() => doiTrang(trang - 1)}
          aria-label="Trang trước"
        >
          ‹
        </button>
        {daySo(trang, soTrang).map((n, i) =>
          n === null ? (
            <span key={`x${i}`} className="px-1 text-muted">
              …
            </span>
          ) : (
            <button
              key={n}
              type="button"
              aria-current={n === trang ? 'page' : undefined}
              className={`${NUT_TRANG} ${n === trang ? 'bg-acs text-ac font-medium' : 'text-muted'}`}
              onClick={() => doiTrang(n)}
            >
              {n}
            </button>
          ),
        )}
        <button
          type="button"
          className={NUT_PHU}
          disabled={trang >= soTrang}
          onClick={() => doiTrang(trang + 1)}
          aria-label="Trang sau"
        >
          ›
        </button>
      </nav>

      {doiSoHang && (
        <label className="flex items-center gap-2">
          Mỗi trang
          <select
            className="o-chon rounded border border-border-field px-2 py-1 max-md:h-10"
            value={soHang}
            onChange={(e) => doiSoHang(Number(e.target.value))}
          >
            {luaChon.map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  )
}
