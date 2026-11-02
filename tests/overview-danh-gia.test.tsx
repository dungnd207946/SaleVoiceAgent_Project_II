import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { TheDanhGia } from '@/features/ops/components/TheDanhGia'
import type { Overview } from '@/features/ops/api'

/**
 * `TheDanhGia` cần router context từ round fix 2026-08-14: năm hàng phân bố
 * sao đã thành `<Link to="/quality" search={{rating:[n]}}>` (xem docstring
 * component — hàng phải `relative z-10` để nhận `mousemove` xuyên qua
 * stretched-link của ô cha, mà một hàng nâng z-index nhưng không điều hướng
 * là một vùng bấm chết). Router TỐI THIỂU, đúng khuôn `overview-man.test.tsx`.
 */
function veDanhGia(danhGia: Overview['danhGia']) {
  const rootRoute = createRootRoute({ component: () => <TheDanhGia danhGia={danhGia} /> })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

describe('TheDanhGia', () => {
  const DG = {
    trungBinh: 4.33,
    truoc: 4.41,
    tong: 190,
    theoSao: { '1': 4, '2': 8, '3': 20, '4': 48, '5': 110 },
  } as const

  it('hiện điểm, tổng lượt và đủ 5 dòng phân bố', async () => {
    veDanhGia(DG)
    await screen.findByText('4,33')
    expect(screen.getByText('4,33')).toBeInTheDocument()
    expect(screen.getByText(/190/)).toBeInTheDocument()
    for (const n of [1, 2, 3, 4, 5]) {
      expect(screen.getByTestId(`dg-sao-${n}`)).toBeInTheDocument()
    }
  })

  it('KHÔNG làm tròn khi vẽ sao — 4,33 phải tô MỘT PHẦN ngôi thứ năm', async () => {
    /* Tên truy cập của `Sao` («4,33 trên 5 sao») nói CON SỐ, không nói hình vẽ —
       móc cho hình vẽ là `data-sao` / `data-phan` (xem `tests/sao.test.tsx`). Làm tròn 4,33 → 4 cho ra 4 ngôi «on» + 1
       «off» và KHÔNG có ngôi nào «phan» — đó chính là ca cần bắt. */
    const { container } = veDanhGia(DG)
    await screen.findByText('4,33')

    expect(container.querySelectorAll('[data-sao="on"]')).toHaveLength(4)
    const le = container.querySelectorAll('[data-sao="phan"]')
    expect(le).toHaveLength(1)
    expect(le[0]!.getAttribute('data-phan')).toBe('33')
  })

  it('`truoc = null` ⇒ KHÔNG vẽ mũi tên delta', async () => {
    veDanhGia({ ...DG, truoc: null })
    await screen.findByText('4,33')
    expect(screen.queryByTestId('dg-delta')).not.toBeInTheDocument()
  })

  it('badge delta mang ĐƠN VỊ «điểm» — không đọc nhầm thành phần trăm', async () => {
    /* Ô ① ngay bên trái có một badge trông y hệt (cùng pill, cùng font mono,
       cùng cụm mũi tên) nhưng mang PHẦN TRĂM. Không có đuôi đơn vị thì
       `▼0,08` cạnh `▲13,5%` đọc thành "giảm 0,08%" — nhỏ đi 100 lần so với
       sự thật (0,08 điểm trên thang 5 là 1,6%). */
    veDanhGia(DG)
    expect(await screen.findByTestId('dg-delta')).toHaveTextContent('0,08')
    expect(screen.getByTestId('dg-delta')).toHaveTextContent('điểm')
  })

  const RONG = {
    trungBinh: 0,
    truoc: null,
    tong: 0,
    theoSao: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
  } as const

  it('tong = 0 ⇒ «Chưa có đánh giá», KHÔNG hiện 0,00 / 5', () => {
    /* Spec §4.4. Backend cố ý giữ `truoc` là `null` chứ không `0` chính vì
       lớp lỗi này — «0 sao» và «chưa ai chấm» là hai sự thật khác nhau, và
       tenant vừa bật agent đọc `0,00 / 5` thành "khách chấm agent 0 điểm".
       `trungBinh` VẪN về 0.0 từ backend (`or 0.0` để thang 0→5 vẽ được), nên
       `tong` là biến duy nhất phân biệt được hai ca. */
    render(<TheDanhGia danhGia={RONG} />)

    expect(screen.getByTestId('dg-chua-co')).toHaveTextContent('Chưa có đánh giá')
    expect(screen.queryByText('0,00')).not.toBeInTheDocument()
    expect(screen.queryByText('/ 5')).not.toBeInTheDocument()
  })

  it('tong = 0 ⇒ KHÔNG vẽ sao và KHÔNG vẽ phân bố', () => {
    /* Ba thứ này đều là cách nói «đã đo được rồi». Bỏ mỗi con số mà vẫn để
       năm ngôi sao xám + năm thanh 0% thì màn vẫn nói dối, chỉ nói khẽ hơn. */
    const { container } = render(<TheDanhGia danhGia={RONG} />)

    expect(container.querySelector('[data-sao]')).toBeNull()
    for (const n of [1, 2, 3, 4, 5]) {
      expect(screen.queryByTestId(`dg-sao-${n}`)).not.toBeInTheDocument()
    }
  })

  it('tong = 1 vẫn vẽ đủ khối số + sao + phân bố', async () => {
    /* Kiểm NGƯỢC nhánh trên: điều kiện phải là `tong === 0`, không phải một
       ngưỡng "ít quá thì ẩn" nào đó. Một lượt chấm là một sự thật đã đo. */
    veDanhGia({ ...RONG, trungBinh: 5, tong: 1, theoSao: { ...RONG.theoSao, '5': 1 } })

    expect(await screen.findByText('5,00')).toBeInTheDocument()
    expect(screen.queryByTestId('dg-chua-co')).not.toBeInTheDocument()
    expect(screen.getByTestId('dg-sao-5')).toBeInTheDocument()
  })

  /* ── Tooltip mỗi hàng sao (round fix 2026-08-14) ─────────────────────────
     Bản đầu của ô ③ đánh rơi hẳn tooltip mà demo có (`gan(n, …)` cuối khối
     ③). «Tỉ lệ» là con số DUY NHẤT chỉ sống trong tooltip — hàng đã in sẵn
     «Lượt» ở cột phải — nên nếu tooltip không mở thì nó không tới được người
     dùng bằng đường nào ngoài đoạn `sr-only`. */
  it('rê chuột vào một hàng sao ⇒ hiện tooltip có Lượt và Tỉ lệ', async () => {
    veDanhGia(DG)
    const hang = await screen.findByTestId('dg-sao-5')
    expect(screen.queryByTestId('dg-tip')).not.toBeInTheDocument()

    await userEvent.hover(hang)

    const tip = await screen.findByTestId('dg-tip')
    expect(tip).toHaveTextContent('5 sao')
    expect(tip).toHaveTextContent('110')
    // 110/190 = 57,894… ⇒ MỘT chữ số thập phân, dấu phẩy vi-VN. `so()` (nhóm
    // hàng nghìn, không phần lẻ) sẽ in `58` — đó là ca `DongTip` đổi từ
    // `n: number` sang `gia: ReactNode` để tránh.
    expect(tip).toHaveTextContent('57,9%')
  })

  it('rời chuột ⇒ tooltip đóng', async () => {
    veDanhGia(DG)
    const hang = await screen.findByTestId('dg-sao-1')
    await userEvent.hover(hang)
    await screen.findByTestId('dg-tip')

    await userEvent.unhover(hang)
    expect(screen.queryByTestId('dg-tip')).not.toBeInTheDocument()
  })

  it('mỗi hàng dẫn sang /quality ĐÃ LỌC đúng mức sao của chính nó', async () => {
    /* Không phải trang trí: người vừa nhìn thấy «4 phiếu 1 sao» thì câu hỏi
       kế tiếp gần như luôn là «phiếu nào?». Trần `/quality` bắt họ bấm lại
       chip lọc một lần nữa cho đúng con số vừa đọc. */
    veDanhGia(DG)
    const hang = await screen.findByTestId('dg-sao-1')
    expect(hang.getAttribute('href')).toContain('/quality')
    expect(hang.getAttribute('href')).toContain('rating')
    expect(hang.getAttribute('href')).toContain('1')
  })

  it('đoạn sr-only mang đủ tỉ lệ 5 mức — tooltip chỉ mở bằng chuột', async () => {
    const { container } = veDanhGia(DG)
    await screen.findByText('4,33')

    // Đoạn TÓM TẮT nằm ngoài các hàng — mỗi hàng (link) còn một « sao» sr-only riêng
    // cho tên link («5 sao 110»), từ 2026-10-05 ký tự ★ thành icon.
    const sr = [...container.querySelectorAll('.sr-only')].find((e) => !e.closest('a'))
    expect(sr).toBeDefined()
    expect(sr!.textContent).toContain('57,9%')
    expect(sr!.textContent).toContain('1 sao')
  })
})
