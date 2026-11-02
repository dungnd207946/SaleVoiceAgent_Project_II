/**
 * Cổng HÌNH HỌC của biểu đồ. Kiểm những bất biến mà mắt đọc thành "lệch" —
 * ba lỗi này đã xảy ra thật ở bản demo và không lỗi nào làm test cũ đỏ.
 *
 * `co` là prop CHỈ-CHO-TEST của `BieuDoNgay` (jsdom không có `ResizeObserver`
 * và luôn trả `clientWidth`/`clientHeight` = 0) — truyền kích thước cố định
 * để component có gì mà vẽ. Không đổi assert nào so với brief.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { BieuDoNgay } from '@/features/ops/components/BieuDoNgay'
import type { NgayHoiThoai } from '@/features/ops/api'

const CHUOI: NgayHoiThoai[] = Array.from({ length: 7 }, (_, i) => ({
  ngay: `2026-08-${String(7 + i).padStart(2, '0')}`,
  chat: 10 + i,
  voice: 5 + i,
  khac: 0,
  tong: 15 + 2 * i,
}))

const CO = { W: 700, H: 220 }

function veRoi(dangXem = 6) {
  render(<BieuDoNgay chuoi={CHUOI} dangXem={dangXem} doiDangXem={vi.fn()} co={CO} />)
  return screen.getByRole('img')
}

describe('BieuDoNgay — hình học', () => {
  it('vẽ đúng 7 nhãn ngày, ngày cuối là hôm nay', () => {
    veRoi()
    expect(screen.getAllByTestId(/^nhan-ngay-/)).toHaveLength(7)
    expect(screen.getByTestId('nhan-ngay-6')).toHaveTextContent('13/8')
  })

  it('dải ngày đang xem rộng ĐÚNG một ô và nằm trọn trong lưới', () => {
    const svg = veRoi(0)
    const dai = svg.querySelector('[data-vai="dai"]') as SVGRectElement
    const luoi = svg.querySelector('[data-vai="nen-luoi"]') as SVGRectElement

    const x = Number(dai.getAttribute('x'))
    const w = Number(dai.getAttribute('width'))
    const lx = Number(luoi.getAttribute('x'))
    const lw = Number(luoi.getAttribute('width'))

    // Ca chốt: ở cột ĐẦU TIÊN, thang mép-tới-mép đẩy nửa dải ra ngoài lưới.
    expect(x).toBeGreaterThanOrEqual(lx)
    expect(x + w).toBeLessThanOrEqual(lx + lw + 0.01)
    expect(w).toBeCloseTo(lw / 7, 5)
  })

  it('dải cao đúng bằng lưới — không thừa ra phía dưới', () => {
    const svg = veRoi(3)
    const dai = svg.querySelector('[data-vai="dai"]') as SVGRectElement
    const luoi = svg.querySelector('[data-vai="nen-luoi"]') as SVGRectElement

    expect(Number(dai.getAttribute('y'))).toBeCloseTo(Number(luoi.getAttribute('y')), 5)
    expect(Number(dai.getAttribute('height'))).toBeCloseTo(Number(luoi.getAttribute('height')), 5)
  })

  it('vạch lưới dọc đi XUYÊN điểm dữ liệu — cùng toạ độ x', () => {
    const svg = veRoi()
    const vach = Array.from(svg.querySelectorAll('[data-vai="vach-doc"]'))
    const diem = Array.from(svg.querySelectorAll('[data-vai="diem-chat"]'))

    expect(vach).toHaveLength(7)
    expect(diem).toHaveLength(7)
    for (let i = 0; i < 7; i++) {
      expect(Number(diem[i]!.getAttribute('cx'))).toBeCloseTo(
        Number(vach[i]!.getAttribute('x1')),
        5,
      )
    }
  })

  it('tổng quát hoá theo N — chuỗi KHÁC 7 ngày vẫn khớp nhãn/điểm/tâm ô, không cứng 7', () => {
    /* Fix round 1: SVG đã tổng quát theo N = chuoi.length nhưng hàng nhãn còn
       cứng `grid-cols-7` — hai thang lại tách nhau đúng cái bệnh thang
       mép-tới-mép mà cả component này sinh ra để chữa. Dựng chuỗi 4 ngày
       (khác 7) để lộ đúng lỗi đó nếu nó quay lại. */
    const CHUOI4 = CHUOI.slice(0, 4)
    render(<BieuDoNgay chuoi={CHUOI4} dangXem={3} doiDangXem={vi.fn()} co={CO} />)
    const svg = screen.getByRole('img')

    const nhan = screen.getAllByTestId(/^nhan-ngay-/)
    const vach = Array.from(svg.querySelectorAll('[data-vai="vach-doc"]'))
    const diem = Array.from(svg.querySelectorAll('[data-vai="diem-chat"]'))

    expect(nhan).toHaveLength(4)
    expect(vach).toHaveLength(4)
    expect(diem).toHaveLength(4)

    // Hàng nhãn phải chia ĐÚNG N=4 cột — không phải 7 cứng.
    const hangNhan = nhan[0]!.parentElement as HTMLElement
    expect(hangNhan.style.gridTemplateColumns).toBe('repeat(4, 1fr)')

    // Tâm mỗi cột nhãn (suy từ CÙNG lề PL/PR + N như SVG — hằng số lấy từ
    // brief) phải khớp X[i] mà SVG dùng cho vạch lưới dọc/điểm dữ liệu — đo
    // bằng đúng cách test "vạch lưới dọc đi xuyên điểm" phía trên đang dùng:
    // đọc attribute số, không đo layout (jsdom không có layout thật).
    const PL = 30
    const PR = 16
    const buoc = (CO.W - PL - PR) / 4
    for (let i = 0; i < 4; i++) {
      const tamO = PL + (i + 0.5) * buoc
      expect(Number(vach[i]!.getAttribute('x1'))).toBeCloseTo(tamO, 5)
      expect(Number(diem[i]!.getAttribute('cx'))).toBeCloseTo(tamO, 5)
    }
  })

  it('trục y có 5 mốc, mốc trên cùng là bội của 20', () => {
    const svg = veRoi()
    const moc = Array.from(svg.querySelectorAll('[data-vai="moc-y"]'))

    expect(moc).toHaveLength(5)
    const dinh = Number(moc[moc.length - 1]!.textContent!.replace(/\D/g, ''))
    expect(dinh % 20).toBe(0)
  })

  it('gradient dùng thuộc tính `style` cho stop-color, không phải attribute', () => {
    /* `var()` KHÔNG phân giải trong presentation attribute — nó im lặng rơi về
       mặc định và gradient ra màu đen. */
    const svg = veRoi()
    for (const s of Array.from(svg.querySelectorAll('stop'))) {
      expect(s.getAttribute('stop-color')).toBeNull()
      expect(s.getAttribute('style')).toContain('stop-color')
    }
  })

  it('`aria-label` đếm theo N, không viết cứng chữ «7»', () => {
    /* Cả component đã tổng quát hoá theo `chuoi.length`, riêng nhãn này còn
       cứng — đổi `SO_NGAY` phía backend thì hình vẽ N điểm còn trình đọc màn
       hình vẫn nghe "7 ngày", và đó là chỗ DUY NHẤT không ai kiểm bằng mắt. */
    render(<BieuDoNgay chuoi={CHUOI.slice(0, 4)} dangXem={3} doiDangXem={vi.fn()} co={CO} />)
    expect(screen.getByRole('img')).toHaveAccessibleName(/\b4 ngày gần nhất/)
  })
})

/**
 * Tooltip — round fix 2026-08-13.
 *
 * Trước đó `NgayHoiThoai.khac` (43/302 phiên của fake, 14%) được backend tính,
 * có test, đi qua JSON, khai trong kiểu — rồi KHÔNG ai đọc; và `dangXem` chỉ
 * đổi màu, tức một điều khiển tương tác không trả lại thông tin nào.
 */
describe('BieuDoNgay — tooltip', () => {
  const CO_KHAC: NgayHoiThoai[] = [
    { ngay: '2026-08-11', chat: 30, voice: 17, khac: 7, tong: 54 },
    { ngay: '2026-08-12', chat: 27, voice: 16, khac: 6, tong: 49 },
    { ngay: '2026-08-13', chat: 27, voice: 17, khac: 16, tong: 60 },
  ]

  function ve() {
    return render(<BieuDoNgay chuoi={CO_KHAC} dangXem={2} doiDangXem={vi.fn()} co={CO} />)
  }

  it('nghỉ thì KHÔNG có tooltip nào trong DOM', () => {
    ve()
    expect(screen.queryByTestId('ht-tip')).not.toBeInTheDocument()
  })

  it('rê chuột vào khung ⇒ tooltip đọc được ngày · Chat · Voice · Khác · Tổng', () => {
    /* Năm dòng, không bốn: thiếu «Khác» thì hai đường vẽ 259/302 phiên và 43
       phiên còn lại không xuất hiện ở bất kỳ đâu THEO NGÀY. */
    const { container } = ve()
    const khung = container.querySelector('.cursor-crosshair')!
    fireEvent.mouseMove(khung, { clientX: 120, clientY: 200 })

    const tip = screen.getByTestId('ht-tip')
    for (const chu of ['Chat', 'Voice', 'Khác', 'Tổng']) {
      expect(tip).toHaveTextContent(chu)
    }
    // Ngày nào cũng được (jsdom trả rect toàn 0 nên chỉ số suy từ chuột không
    // tất định) — nhưng phải là MỘT ngày có thật trong chuỗi.
    expect(tip.textContent).toMatch(/1[123]\/8/)
  })

  it('rời khung ⇒ tooltip biến mất', () => {
    const { container } = ve()
    const khung = container.querySelector('.cursor-crosshair')!
    fireEvent.mouseMove(khung, { clientX: 120, clientY: 200 })
    expect(screen.getByTestId('ht-tip')).toBeInTheDocument()

    fireEvent.mouseLeave(khung)
    expect(screen.queryByTestId('ht-tip')).not.toBeInTheDocument()
  })

  it('tiêu điểm bàn phím trên nhãn ngày cũng mở tooltip, đúng SỐ của ngày đó', () => {
    /* Nhãn ngày là `<button>` thật để dải với tới được bằng bàn phím (spec
       §2). Nếu chỉ chuột mở tooltip thì người tab tới đây đổi được dải mà
       không đọc được con số nào — cùng cái bệnh, chỉ đổi đối tượng chịu.
       ⚠ `fireEvent.focus`, KHÔNG `el.focus()` trần: React 18 gộp lô cập nhật
       state, và một `.focus()` gọi ngoài `act()` thì handler CÓ chạy nhưng
       `setTip` chưa flush — đo được: `onFocus` đếm 1 lượt trong khi DOM vẫn
       là bản cũ. `fireEvent` tự bọc `act()`. */
    ve()
    fireEvent.focus(screen.getByTestId('nhan-ngay-0'))

    const tip = screen.getByTestId('ht-tip')
    expect(tip).toHaveTextContent('11/8')
    expect(tip).toHaveTextContent('30') // chat
    expect(tip).toHaveTextContent('17') // voice
    expect(tip).toHaveTextContent('7') // khac
    expect(tip).toHaveTextContent('54') // tong
  })

  it('ngày cuối gắn nhãn «Hôm nay» trong tooltip', () => {
    ve()
    fireEvent.focus(screen.getByTestId('nhan-ngay-2'))
    expect(screen.getByTestId('ht-tip')).toHaveTextContent('Hôm nay')
  })

  it('bảng số sr-only mang CẢ «khác» — đường duy nhất tới trình đọc màn hình', () => {
    /* Tooltip chỉ mở bằng chuột/tiêu điểm; `aria-label` của SVG chỉ nói hình
       VẼ GÌ, không nói vẽ ra SỐ MẤY. */
    const { container } = ve()
    const bang = container.querySelector('.sr-only')!
    expect(bang.textContent).toContain('khác 16')
    expect(bang.textContent).toContain('tổng 60')
  })

  /* Hồi quy cho việc tách khung tooltip (`HopTip`/`useTip`) sang
     `features/ops/components/Tip.tsx` khi `TheKienThuc.tsx` (ô ⑤) thành
     người dùng thứ hai (2026-08-14). Đây là refactor THUẦN — hình thức và
     hành vi của tooltip ô ① không được đổi gì; bài dưới lặp lại đủ ba trục
     (chuột mở/đóng, bàn phím mở, nội dung đúng) để một hồi quy trong lúc
     tách primitive không lọt qua chỉ vì các bài phía trên đã pass từ trước
     khi tách. */
  it('sau khi tách khung tooltip dùng chung: rê chuột lẫn tiêu điểm bàn phím đều còn mở đúng ht-tip', () => {
    const { container } = ve()
    const khung = container.querySelector('.cursor-crosshair')!

    fireEvent.mouseMove(khung, { clientX: 90, clientY: 220 })
    const quaChuot = screen.getByTestId('ht-tip')
    expect(quaChuot).toHaveTextContent('Chat')
    expect(quaChuot).toHaveTextContent('Voice')

    fireEvent.mouseLeave(khung)
    expect(screen.queryByTestId('ht-tip')).not.toBeInTheDocument()

    fireEvent.focus(screen.getByTestId('nhan-ngay-1'))
    const quaBanPhim = screen.getByTestId('ht-tip')
    expect(quaBanPhim).toHaveTextContent('12/8')

    fireEvent.blur(screen.getByTestId('nhan-ngay-1'))
    expect(screen.queryByTestId('ht-tip')).not.toBeInTheDocument()
  })
})
