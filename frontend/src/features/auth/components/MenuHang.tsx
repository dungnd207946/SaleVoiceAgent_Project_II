/**
 * Menu `⋯` cuối hàng bảng của `/users`.
 *
 * Sống ở `features/auth/components/` nên KHÔNG dùng lại được ở module khác —
 * `tests/module-boundaries.test.ts` chặn import ruột xuyên feature. Bảng nào
 * khác cần cùng hình dạng thì lặp lại pattern (như `Bang.tsx` đã lặp `NhomTab`
 * cho nhiều màn), không import thẳng file này.
 *
 * VÌ SAO MENU CHỨ KHÔNG PHẢI NÚT RỜI TRONG HÀNG: mục nặng nhất ở đây là ĐỔI VAI
 * TRÒ. Luật «xem trước, sửa sau» (CLAUDE.md) nói *form mở sẵn nói «hãy điền»
 * trong khi việc thật là «hãy đọc», và nó mời gõ nhầm vào dữ liệu đang phát
 * hành* — một `<select>` quyền hạn luôn sống trong bảng là đúng ca đó. Bản
 * trước 2026-08-09 có `<select>` như thế; nay nó ở sau hai cú bấm. Giá: một cú
 * bấm nữa cho một việc HIẾM, đổi lấy an toàn cho một bảng ĐỌC THƯỜNG XUYÊN.
 *
 * DISCLOSURE, KHÔNG phải `role="menu"` (2026-10-05, audit a11y): `role="menu"` hứa
 * mô hình phím của ARIA — ↑↓ Home End, roving tabindex, type-ahead — mà menu này
 * không có (chỉ Tab đi qua các nút). Hứa mà không giữ còn tệ hơn không hứa, nên:
 * trigger mang `aria-expanded` + `aria-controls`, danh sách là các nút thường.
 *
 * ⚠ TRẢ FOCUS VỀ TRIGGER TRƯỚC KHI MENU UNMOUNT, đồng bộ trong handler. Mục «Đổi
 * vai trò…» mở `HopThoai`, mà `HopThoai` nhớ `activeElement` lúc mở để trả focus lúc
 * đóng; menu unmount mà focus còn trên mục vừa bấm thì focus rơi về `<body>` và
 * hộp thoại ghi nhận `<body>` làm chỗ trả. Bấm ra ngoài chỉ trả khi focus đang nằm
 * trong menu — còn không thì cú bấm đã chuyển focus tới chỗ người dùng muốn.
 *
 * ⚠ MENU TỰ LẬT LÊN KHI BỊ CẮT (2026-08-17) — người dùng báo: mở menu ở hàng CUỐI
 * list thì thẻ bị che, phải cuộn xuống mới thấy. Xem `vungCat()` cho vật đo và
 * `useLayoutEffect` cho luật lật. Menu vẫn `absolute` (KHÔNG `createPortal` như
 * `HopTip`) có chủ ý: neo vào hàng nghĩa là cuộn list thì menu đi
 * theo đúng hàng nó thuộc về, còn `position: fixed` sẽ đứng im rồi trôi khỏi hàng.
 *
 * ⚠ jsdom KHÔNG có engine bố cục — mọi `getBoundingClientRect` trả 0 và
 * `getComputedStyle().overflowY` trả `visible`, nên KHÔNG bài render nào bắt được
 * lớp lỗi này một cách tự nhiên. Hai bài canh hướng ở `tests/thanh-vien.test.tsx`
 * phải GIẢ hình học (`vi.spyOn` lên `getBoundingClientRect`); đọc hướng qua
 * `data-huong` trên hộp mục. Đổi luật lật thì sửa cả hai bài đó.
 */
import { useId, useLayoutEffect, useRef, useState } from 'react'
import { useDongKhiRaNgoai } from '@/lib/dongKhiRaNgoai'

/**
 * Mép TRÊN và DƯỚI của thứ sẽ CẮT menu — không phải mép viewport.
 *
 * Bảng thành viên có HAI tầng cắt lồng nhau (`components/ui/Bang.tsx`): `TheBang`
 * mang `overflow-hidden` + `max-h-[560px]`, và vùng cuộn bên trong nó mang
 * `overflow-auto`. Menu là `absolute` trong một `<td>` nên nằm trong cả hai ⇒ đo
 * theo `window.innerHeight` là đo sai vật: ở hàng cuối list, menu vẫn còn thừa chỗ
 * so với màn hình nhưng đã bị cắt từ lâu bởi cái gần nhất.
 *
 * Giao với viewport cho ca vùng cuộn cao hơn màn hình — lúc đó chính màn hình mới
 * là mép hẹp hơn.
 */
function vungCat(tu: HTMLElement): { tren: number; duoi: number } {
  for (let n = tu.parentElement; n; n = n.parentElement) {
    const tran = getComputedStyle(n).overflowY
    if (tran === 'auto' || tran === 'scroll' || tran === 'hidden') {
      const o = n.getBoundingClientRect()
      return { tren: Math.max(o.top, 0), duoi: Math.min(o.bottom, window.innerHeight) }
    }
  }
  return { tren: 0, duoi: window.innerHeight }
}

export interface MucMenu {
  readonly key: string
  readonly nhan: string
  readonly onChon: () => void
  /** Tô sắc cảnh báo — dành cho mục không hoàn tác được. */
  readonly phaHuy?: boolean
}

export function MenuHang({ nhan, muc }: { nhan: string; muc: readonly MucMenu[] }) {
  const [mo, setMo] = useState(false)
  const boc = useRef<HTMLDivElement>(null)
  const hopMuc = useRef<HTMLDivElement>(null)
  const nutMo = useRef<HTMLButtonElement>(null)
  const idMenu = useId()
  const [huong, setHuong] = useState<'duoi' | 'tren'>('duoi')

  /**
   * Menu bị vùng cuộn cắt ⇒ MỞ NGƯỢC LÊN. Đo bằng `useLayoutEffect` nên việc đổi
   * hướng xong TRƯỚC khi trình duyệt vẽ — không có cú nháy nào.
   *
   * Đo menu THẬT thay vì nhẩm `số mục × chiều cao dòng`: menu này có 1–3 mục tuỳ
   * hàng, và một hằng nhẩm sai sẽ sai âm thầm đúng ở hàng cuối, tức đúng chỗ đang
   * hỏng. Mỗi lần mở đều đo lại từ `'duoi'` (đặt lại ở nhánh `!mo`) để lần mở sau
   * không thừa hưởng kết quả đo của một hàng khác.
   *
   * ⚠ CHỈ lật khi phía TRÊN thật sự đủ chỗ. Lật vô điều kiện là đổi bug lấy bug:
   * hàng ĐẦU list sẽ bị cắt ở mép trên y như hàng cuối đang bị cắt ở mép dưới.
   * Không bên nào đủ thì thà giữ `'duoi'` — ở đó còn cuộn tới được.
   */
  useLayoutEffect(() => {
    if (!mo) {
      setHuong('duoi')
      return
    }
    const hop = hopMuc.current
    const nut = boc.current
    if (!hop || !nut) return
    const oMuc = hop.getBoundingClientRect()
    const oNut = nut.getBoundingClientRect()
    const vung = vungCat(nut)
    const chatDuoi = oMuc.bottom > vung.duoi
    const duChoTren = oMuc.height <= oNut.top - vung.tren
    if (chatDuoi && duChoTren) setHuong('tren')
  }, [mo])

  // Bấm RA NGOÀI và Esc đều đóng. Thiếu vế đầu thì mở hai menu cùng lúc trên hai
  // hàng, và người dùng không biết mục mình sắp bấm thuộc về ai.
  useDongKhiRaNgoai(boc, mo, (e) => {
    if (e.type === 'keydown' || hopMuc.current?.contains(document.activeElement))
      nutMo.current?.focus()
    setMo(false)
  })

  if (muc.length === 0) return null

  return (
    <div ref={boc} className="relative inline-block text-left">
      <button
        ref={nutMo}
        type="button"
        aria-label={`Thao tác với ${nhan}`}
        aria-expanded={mo}
        aria-controls={idMenu}
        onClick={() => setMo((v) => !v)}
        className="inline-flex h-8 w-8 items-center justify-center rounded-sm text-muted hover:bg-fill max-md:size-10"
      >
        <span aria-hidden="true">⋯</span>
      </button>
      {mo && (
        <div
          ref={hopMuc}
          id={idMenu}
          data-testid="menu-hang"
          data-huong={huong}
          className={`absolute right-0 z-50 min-w-[196px] rounded-lg border border-border bg-surface py-1 shadow-lg ${
            huong === 'tren' ? 'bottom-full mb-1' : 'mt-1'
          }`}
        >
          {muc.map((m) => (
            <button
              key={m.key}
              type="button"
              onClick={() => {
                nutMo.current?.focus()
                setMo(false)
                m.onChon()
              }}
              className={`block w-full px-3.5 py-2 text-left text-than hover:bg-fill ${
                m.phaHuy ? 'text-badge-alert-fg' : 'text-fg'
              }`}
            >
              {m.nhan}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
