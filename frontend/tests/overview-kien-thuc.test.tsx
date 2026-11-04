import { fireEvent, render, screen, within } from '@testing-library/react'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { describe, expect, it } from 'vitest'
import { TheKienThuc } from '@/features/ops/components/TheKienThuc'
import type { MucKienThuc } from '@/features/ops/api'

const MUC: MucKienThuc[] = [
  { khoa: 'duAn', thay: 8, tong: 12 },
  { khoa: 'phanKhu', thay: 31, tong: 47 },
  { khoa: 'can', thay: 964, tong: 1203 },
  { khoa: 'taiLieuTraCuu', thay: 189, tong: 214 },
  { khoa: 'kyNang', thay: 12, tong: 12 },
]

/**
 * Năm hàng của `TheKienThuc` là `<Link>` (round fix 2026-08-14, ô ⑤ bấm được)
 * — `Link` cần router context, nên `render()` trần không chạy được nữa. Bọc
 * router TỐI THIỂU đúng khuôn `tests/quality-review-card.test.tsx`/
 * `overview-man.test.tsx`.
 *
 * `RouterProvider` render lần đầu ở trạng thái "pending" rồi mới khớp route
 * (microtask) — truy vấn ĐẦU TIÊN sau mỗi `veRoi()` phải là `findBy*`, không
 * `getBy*` đồng bộ.
 */
function veRoi(muc: readonly MucKienThuc[]) {
  const rootRoute = createRootRoute({
    component: () => <TheKienThuc muc={muc} />,
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

describe('TheKienThuc', () => {
  it('vẽ đủ năm hàng theo đúng thứ tự backend trả về', async () => {
    veRoi(MUC)
    const hang = await screen.findAllByTestId(/^kt-hang-/)
    expect(hang.map((h) => h.dataset.khoa)).toEqual([
      'duAn',
      'phanKhu',
      'can',
      'taiLieuTraCuu',
      'kyNang',
    ])
  })

  /* Mỗi hàng đi tới MÀN QUẢN LÝ ĐÚNG THỨ NÓ ĐẾM (2026-08-14). Trước đó cả sáu
     hàng cùng `to="/projects"`: hover tô sáng từng hàng riêng — tức hứa sáu
     đích khác nhau — rồi giao đúng một đích. */
  it.each([
    ['duAn', '/projects'],
    ['phanKhu', '/projects'],
    ['can', '/projects'],
    ['taiLieuTraCuu', '/kb'],
    ['kyNang', '/agent'],
    ['duLieuNgoai', '/du-lieu-ngoai'],
  ])('hàng %s là link trỏ %s', async (khoa, dich) => {
    veRoi([...MUC, { khoa: 'duLieuNgoai', thay: 1, tong: 2 }])
    const hang = await screen.findByTestId(`kt-hang-${khoa}`)
    expect(hang.tagName).toBe('A')
    expect(hang).toHaveAttribute('href', dich)
  })

  it('hàng KHÔNG mang màu accent — chữ trung tính `text-fg`, không phải nhãn hành động', async () => {
    /* Hồi quy phát hiện sau lần đổi hàng thành `<Link>`: luật toàn cục
       `a { color: var(--color-ac) }` (`theme.css`) ăn vào MỌI thẻ `<a>`, kể
       cả hàng dữ liệu này — cả loạt dòng lên xanh accent, kéo chú ý về cột
       tên trong khi thông tin chính của hàng là số + thước. Bốn link «đầu ô»
       («Xem tất cả»/«Xem phiên»/«Xem đánh giá»/«Quản lý») ĐÚNG là hành động
       nên GIỮ accent — chỉ các hàng dữ liệu của ô ⑤ mới cần trung tính.
       jsdom không vẽ CSS thật (không tính được `getComputedStyle` từ
       `theme.css`/Tailwind — cùng lý do `chip-kenh-mau.test.ts` chỉ đọc file
       nguồn thay vì render), nên phép kiểm THẬT ở đây là lớp `text-fg` có
       mặt trong `className` — gỡ nó là bài này đỏ ngay lập tức. Đã xác nhận
       bằng mắt qua Chromium thật (Playwright, `getComputedStyle` bên ngoài
       vitest): rest lẫn hover đều `rgb(20, 22, 26)` = `--color-fg`, không
       lệch sang `--color-ac`/`--color-acd`. */
    veRoi(MUC)
    const hang = await screen.findByTestId('kt-hang-duAn')
    expect(hang.className).toMatch(/\btext-fg\b/)
  })

  it('mục ĐẦY hiện nhãn "đủ", mục hụt hiện phần thiếu thành lời', async () => {
    veRoi(MUC)
    await screen.findByTestId('kt-hang-duAn')
    expect(within(screen.getByTestId('kt-hang-kyNang')).getByText(/đủ/i)).toBeInTheDocument()
    expect(within(screen.getByTestId('kt-hang-duAn')).getByText(/4/)).toBeInTheDocument()
  })

  /* Hàng «Kỹ năng agent» đếm NĂNG LỰC, không đếm kho — mọi chữ trên hàng phải
     nói đúng loại đó. Dùng lại nguyên văn khuôn kho («Agent đọc đủ», «Tổng
     trong kho») là bịa ra một cái kho kỹ năng không tồn tại, và nói sai đúng
     kiểu mà cả ô này sinh ra để tránh. */
  it('hàng kỹ năng nói bằng lời của KỸ NĂNG, không phải lời của kho', async () => {
    veRoi(MUC)
    const hang = await screen.findByTestId('kt-hang-kyNang')
    expect(hang).toHaveTextContent('Kỹ năng agent')
    expect(hang.textContent).not.toMatch(/đọc/i)

    fireEvent.mouseMove(hang, { clientX: 200, clientY: 300 })
    const tip = screen.getByTestId('kt-tip')
    expect(tip).toHaveTextContent('Đang bật')
    expect(tip).toHaveTextContent('Tổng kỹ năng')
    expect(tip.textContent).not.toMatch(/trong kho/i)
  })

  /* Hàng này ĐẾM KHO `/kb` (`kb_files`), không phải tài liệu gõ tay của từng
     dự án (`documents`) — hai kho khác nhau, xem `features/kb/nav.ts`. Bản
     trước tên «Tài liệu dự án», đếm `documents`, mà bấm vào lại sang `/kb`:
     người dùng thấy 6/6 trong khi `/kb` trống trơn và hỏi «số liệu fake à?».
     Ba khẳng định dưới đây khoá cả ba mặt của cùng một sự thật — TÊN nói đúng
     kho, ĐIỀU KIỆN nói đúng cái lọc SQL đang chạy (`state = 'san_sang'`), và
     đoạn chú giải thích vì sao một tệp vừa tải lên chưa được tính. */
  it('hàng tài liệu nói đúng kho /kb, không phải kho tài liệu của dự án', async () => {
    veRoi(MUC)
    const hang = await screen.findByTestId('kt-hang-taiLieuTraCuu')
    expect(hang).toHaveTextContent('Tài liệu chung')
    expect(hang).toHaveTextContent('đã nhúng vector')

    fireEvent.mouseMove(hang, { clientX: 200, clientY: 300 })
    expect(screen.getByTestId('kt-tip')).toHaveTextContent('nhúng vector')
  })

  it('hàng kỹ năng chưa bật hết nói còn thiếu mấy kỹ năng', async () => {
    veRoi([{ khoa: 'kyNang', thay: 5, tong: 12 }])
    const hang = await screen.findByTestId('kt-hang-kyNang')
    expect(hang).toHaveTextContent('7 chưa bật')
  })

  it('thước chỉ tô đủ 14 nấc khi thật sự 100%', async () => {
    veRoi(MUC)
    await screen.findByTestId('kt-hang-duAn')
    const day = within(screen.getByTestId('kt-hang-kyNang')).getAllByTestId('kt-nac-day')
    // 189/214 = 88,3% → làm tròn lên là 12,4 ⇒ 12; nhưng ca nguy hiểm là 13,6/14.
    const gan = within(screen.getByTestId('kt-hang-taiLieuTraCuu')).getAllByTestId('kt-nac-day')

    expect(day).toHaveLength(14)
    expect(gan.length).toBeLessThanOrEqual(13)
  })

  it('không tô đủ nấc cho 99% — thước đầy cho kho còn thiếu là nói dối', async () => {
    veRoi([{ khoa: 'can', thay: 99, tong: 100 }])
    await screen.findByTestId('kt-hang-can')
    expect(screen.getAllByTestId('kt-nac-day')).toHaveLength(13)
  })

  it('cộng gộp theo MỤC, không lấy trung bình năm tỉ lệ', async () => {
    veRoi(MUC)
    // 8+31+964+189+12 = 1204 ; 12+47+1203+214+12 = 1488 ; 81%
    const tong = await screen.findByTestId('kt-tong')
    expect(tong).toHaveTextContent('1.204')
    expect(tong).toHaveTextContent('1.488')
    expect(tong).toHaveTextContent('81%')
  })

  it('mục lạ backend thêm sau vẫn vẽ được, không vỡ màn', async () => {
    veRoi([{ khoa: 'khoaMoiChuaBiet', thay: 1, tong: 2 }])
    expect(await screen.findByTestId('kt-hang-khoaMoiChuaBiet')).toBeInTheDocument()
  })

  it('mục lạ chưa có đích điều hướng thì về /projects, không thành link chết', async () => {
    /* `DICH` tra theo `khoa`; khoá backend thêm sau chưa có dòng nào ở đó.
       `to={undefined}` làm `<Link>` ném, còn một hàng không href là vùng bấm
       chết nằm giữa các hàng bấm được. `/projects` là đích trung tính vì ba
       trong năm mục hiện tại là dữ liệu của màn đó. */
    veRoi([{ khoa: 'khoaMoiChuaBiet', thay: 1, tong: 2 }])
    const hang = await screen.findByTestId('kt-hang-khoaMoiChuaBiet')
    expect(hang).toHaveAttribute('href', '/projects')
  })

  it('tong = 0 không sinh NaN%', async () => {
    veRoi([{ khoa: 'duAn', thay: 0, tong: 0 }])
    expect(await screen.findByTestId('kt-tong')).not.toHaveTextContent('NaN')
  })

  /* Tooltip mỗi hàng — round fix 2026-08-14. Người dùng phát hiện: rê chuột
     vào từng hàng của ô ⑤ không có tooltip, trong khi demo có; đợt review
     tooltip ô ① trước đó bắt được ô đó nhưng bỏ sót ô này. Dùng chung khung
     `HopTip`/`useTip` tách từ `BieuDoNgay.tsx` (`./Tip.tsx`). */
  describe('tooltip từng hàng', () => {
    it('nghỉ thì KHÔNG có tooltip nào trong DOM', async () => {
      veRoi(MUC)
      await screen.findByTestId('kt-hang-duAn')
      expect(screen.queryByTestId('kt-tip')).not.toBeInTheDocument()
    })

    it('rê chuột vào một hàng ⇒ tooltip hiện đúng tên mục · Agent đọc được · Tổng trong kho', async () => {
      veRoi(MUC)
      const hang = await screen.findByTestId('kt-hang-duAn')
      fireEvent.mouseMove(hang, { clientX: 200, clientY: 300 })

      const tip = screen.getByTestId('kt-tip')
      expect(tip).toHaveTextContent('Dự án')
      expect(tip).toHaveTextContent('Agent đọc được')
      expect(tip).toHaveTextContent('8') // thay
      expect(tip).toHaveTextContent('Tổng trong kho')
      expect(tip).toHaveTextContent('12') // tong

      fireEvent.mouseLeave(hang)
      expect(screen.queryByTestId('kt-tip')).not.toBeInTheDocument()
    })

    it('mục có lời giải thích thêm ⇒ tooltip mang đúng đoạn chú ở chân', async () => {
      veRoi(MUC)

      const duAn = await screen.findByTestId('kt-hang-duAn')
      fireEvent.mouseMove(duAn, { clientX: 200, clientY: 300 })
      // Viết lại so với demo: KHÔNG còn nhắc `agent_api` (view đã bỏ hẳn ở
      // migration `0917`), nhưng vẫn giữ ý nghiệp vụ "chưa có thông tin".
      expect(screen.getByTestId('kt-tip')).toHaveTextContent('chưa có thông tin')
      expect(screen.getByTestId('kt-tip').textContent).not.toMatch(/agent_api/i)
      fireEvent.mouseLeave(duAn)

      const kyNang = screen.getByTestId('kt-hang-kyNang')
      fireEvent.mouseMove(kyNang, { clientX: 200, clientY: 300 })
      expect(screen.getByTestId('kt-tip')).toHaveTextContent('Kỹ năng tắt')
    })

    it('mục KHÔNG có lời giải thích thêm ⇒ tooltip chỉ có hai dòng số, không có đoạn chú', async () => {
      veRoi(MUC)
      const hang = await screen.findByTestId('kt-hang-phanKhu')
      fireEvent.mouseMove(hang, { clientX: 200, clientY: 300 })
      const tip = screen.getByTestId('kt-tip')
      expect(tip).toHaveTextContent('Phân khu')
      expect(tip.querySelector('.border-t')).not.toBeInTheDocument()
    })

    it('mở được bằng bàn phím: hàng nhận tiêu điểm cũng mở tooltip đúng nội dung', async () => {
      veRoi(MUC)
      const hang = await screen.findByTestId('kt-hang-can')
      // Hàng là `<Link>` thật (bỏ `tabIndex` viết tay) — link tự tabbable,
      // không cần khoá thêm bậc tab nào. Tooltip vẫn phải mở được bằng
      // `focus`, đúng cái bệnh mà tooltip ô ① đã chữa (chỉ chuột mới với tới).
      fireEvent.focus(hang)
      const tip = screen.getByTestId('kt-tip')
      expect(tip).toHaveTextContent('Căn / sản phẩm')
      expect(tip).toHaveTextContent('964')
      expect(tip).toHaveTextContent('1.203') // so(1203) nhóm hàng nghìn kiểu vi-VN

      fireEvent.blur(hang)
      expect(screen.queryByTestId('kt-tip')).not.toBeInTheDocument()
    })
  })
})
