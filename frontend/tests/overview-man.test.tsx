/**
 * Màn `/dashboard` — Tổng quan (Task 11).
 *
 * KHÔNG boot `routeTree` thật — đơn vị đang kiểm là `TongQuanScreen`, không
 * phải cái shell quanh nó (cùng lý lẽ `khoa-dau-noi.test.tsx:11`; `/dashboard`
 * đi qua shell đã có cổng riêng ở `tests/boot.test.tsx`). Nhưng từ round fix
 * 2026-08-13 màn có `<Link>` thật (ô ① «Xem tất cả →», thẻ dẫn hướng «Thử
 * agent →»), mà `<Link>` cần router context — nên bọc một router TỐI THIỂU
 * (`createRootRoute` + `createMemoryHistory`), đúng khuôn
 * `tests/quality-review-card.test.tsx` đã dùng cho cùng tình huống. Không
 * `LangProvider`, không `SessionProvider`: màn không đụng tới hai thứ đó.
 *
 * ⚠️ `RouterProvider` render lần đầu ở trạng thái "pending" rồi mới khớp
 * route (microtask) — nên truy vấn ĐẦU TIÊN sau mỗi `veRoi()` phải là
 * `findBy*`/`waitFor`, không `getBy*` đồng bộ.
 *
 * Dùng CHUNG `server` từ `vitest.setup.ts` (đã `listen()` với `HANDLERS`, và
 * `HANDLERS` đã gồm `opsHandlers` — xem `src/lib/msw/handlers.ts`). KHÔNG
 * dựng `setupServer(...)` riêng ở đây: hai server cùng chặn một request khiến
 * handler chạy HAI LẦN cho một lượt gọi (đo được: bài "Thử lại" dưới đây đếm
 * `lanGoi = 2` ngay sau lần tải đầu, trước khi bấm gì).
 *
 * Số liệu đối chiếu ĐỌC TỪ `features/ops/msw.ts::OVERVIEW_GIA`, không tin số
 * trong brief (đã lỗi thời): tổng hội thoại `302`, Chat `153`, Voice `106`,
 * kỳ `2026-08-07` → `2026-08-13`.
 */
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { http, HttpResponse, delay } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { O_BAM_DUOC, TongQuanScreen } from '@/features/ops/components/TongQuanScreen'
import type { Overview } from '@/features/ops/api'
import { server } from '../vitest.setup'

// `TongQuanScreen.tsx` tự polyfill `ResizeObserver` (jsdom không có) ở
// module-scope khi global chưa có sẵn — không cần stub gì thêm ở đây.

function veRoi() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={qc}>
        <TongQuanScreen />
      </QueryClientProvider>
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

/** Overview đủ hình dạng, mọi số về 0 — dùng cho các ca "tenant mới toanh". */
const RONG: Overview = {
  moc: { tuNgay: '2026-08-07', tinhDen: '2026-08-13' },
  hoiThoai: {
    tong: 0,
    truoc: 0,
    theoNgay: Array.from({ length: 7 }, (_, i) => ({
      ngay: `2026-08-${String(7 + i).padStart(2, '0')}`,
      chat: 0,
      voice: 0,
      khac: 0,
      tong: 0,
    })),
    theoKenh: [],
  },
  chuyenSale: { chuyen: 0, tuXuLy: 0 },
  danhGia: {
    trungBinh: 0,
    truoc: null,
    tong: 0,
    theoSao: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
  },
  kienThuc: { muc: [] },
}

function datOverview(o: Overview) {
  server.use(http.get('/api/v1/overview', () => HttpResponse.json(o)))
}

describe('TongQuanScreen', () => {
  it('vẽ đủ năm ô sau khi dữ liệu về', async () => {
    veRoi()
    await waitFor(() => expect(screen.getByTestId('o-hoi-thoai')).toBeInTheDocument())
    for (const k of ['o-hoi-thoai', 'o-chuyen-sale', 'o-danh-gia', 'o-kien-thuc', 'o-chi-phi']) {
      expect(screen.getByTestId(k)).toBeInTheDocument()
    }
  })

  it('tổng hội thoại và tổng theo kênh nói cùng một con số', async () => {
    veRoi()
    await waitFor(() => expect(screen.getByTestId('ht-tong')).toHaveTextContent('302'))
    expect(screen.getByTestId('ht-chu-thich')).toHaveTextContent('153')
    expect(screen.getByTestId('ht-chu-thich')).toHaveTextContent('106')
  })

  it('đang tải thì hiện khung chờ, KHÔNG hiện số 0', async () => {
    // Trễ TƯỜNG MINH thay vì đua với MSW: từ khi màn bọc router, lần render
    // đầu là "pending" của router nên khung chờ chỉ vào DOM sau một microtask
    // — không còn `getBy*` đồng bộ ngay sau `render()` được, và một `findBy*`
    // trần thì có thể rơi vào lúc dữ liệu đã về.
    server.use(
      http.get('/api/v1/overview', async () => {
        await delay(80)
        return HttpResponse.json(RONG)
      }),
    )
    veRoi()
    expect(await screen.findByTestId('tong-quan-dang-tai')).toBeInTheDocument()
    // Khung chờ không được render bất kỳ số 0 nào — một màn đầy số 0 trông
    // như workspace rỗng, không như đang tải.
    expect(screen.queryByText('0')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.queryByTestId('tong-quan-dang-tai')).not.toBeInTheDocument())
  })

  it('hiện nhãn kỳ từ `moc`, đúng khoảng backend trả về', async () => {
    /* `moc` được `api.ts` che chắn rất kỹ rồi bị bỏ quên suốt bản đầu — màn
       tóm tắt bảy ngày mà không nói bảy ngày NÀO. */
    veRoi()
    expect(await screen.findByTestId('tq-ky')).toHaveTextContent('07/08 – 13/08/2026')
  })

  it('`moc.tuNgay` rỗng (khiên đã kích hoạt) ⇒ KHÔNG vẽ nhãn kỳ nào', async () => {
    /* Chuỗi rỗng nghĩa là THIẾU (backend cũ bỏ hẳn khoá `moc`; `api.ts` cố ý
       không bịa ngày). Vẽ ra một khoảng trống có dấu gạch nối là nói rằng có
       một kỳ ở đó mà người đọc không đọc được — tệ hơn là không nói gì. */
    datOverview({
      ...RONG,
      moc: { tuNgay: '', tinhDen: '' },
      hoiThoai: { ...RONG.hoiThoai, tong: 9 },
    })
    veRoi()
    await screen.findByTestId('o-hoi-thoai')
    expect(screen.queryByTestId('tq-ky')).not.toBeInTheDocument()
  })

  it('ô ① có link «Xem tất cả →» trỏ /convos', async () => {
    /* Spec §6: đây là thứ THAY THẾ cho bảng «Cần chú ý» đã cắt. */
    veRoi()
    const lien = await screen.findByRole('link', { name: /Xem tất cả/ })
    expect(lien).toHaveAttribute('href', '/convos')
  })

  /* Round fix 2026-08-14: mỗi ô một link «đầu ô» mang stretched-link. Từ 06/10
     cả năm ô cùng kiểu, ô Chi phí hết là hai tile — xem docstring `TongQuanScreen.tsx`. */
  describe('bấm vào ô đi tới đúng màn', () => {
    it('ô Chuyển sale «Xem ca →» trỏ hàng đợi Chưa liên hệ, cũ nhất trước', async () => {
      veRoi()
      const lien = await screen.findByRole('link', { name: /Xem ca/ })
      expect(lien).toHaveAttribute('href', '/chuyen-sale?tab=new&cu=true')
    })

    it('ô ③ «Xem đánh giá →» trỏ /quality', async () => {
      veRoi()
      const lien = await screen.findByRole('link', { name: /Xem đánh giá/ })
      expect(lien).toHaveAttribute('href', '/quality')
    })

    it('ô ⑤ «Quản lý →» trỏ /projects', async () => {
      veRoi()
      const lien = await screen.findByRole('link', { name: /Quản lý/ })
      expect(lien).toHaveAttribute('href', '/projects')
    })

    it('ô Chi phí: MỘT đích /billing (kỳ tháng này), số thật, KHÔNG còn token', async () => {
      /* Shape «Cần bạn» 06/10: ô «Usage & Billing» hai tile (Chi phí → /billing ·
         Lượng dùng → /usage) thành một ô Chi phí, bỏ phần token. Số từ fake
         `BILLING_SUMMARY_GIA` (`features/billing/msw.ts`): `chi_phi_tong`
         '125010.5000000000' → `tien()` làm tròn "125.011". */
      veRoi()
      const o = await screen.findByTestId('o-chi-phi')
      const lien = within(o).getByRole('link', { name: /Xem chi phí/ })
      expect(lien.getAttribute('href')).toMatch(/^\/billing\?/)
      expect(lien.getAttribute('href')).toContain('ky=thang-nay')
      await waitFor(() => expect(o).toHaveTextContent('125.011'))
      expect(o).toHaveTextContent('VND')
      expect(o.className).toContain(O_BAM_DUOC)

      expect(within(o).queryByText(/Lượng dùng/)).not.toBeInTheDocument()
      expect(within(o).queryByText(/cache/)).not.toBeInTheDocument()
      expect(within(o).getAllByRole('link')).toHaveLength(1)
    })
  })

  /* ⚠️ BÀI NÀY CHỈ CANH ĐƯỢC HAI THỨ, KHÔNG HƠN — đọc kỹ trước khi tin nó:
     (1) CẤU TRÚC DOM: vùng vẽ + hàng nhãn ngày không phải hậu duệ của `<a>`
     nào (constraint ② của spec — không bọc cả ô trong `<Link>`).
     (2) SỰ HIỆN DIỆN CỦA LỚP `z-10` trên hai phần tử đó trong `className`.

     Nó KHÔNG canh được hành vi "bấm xuyên lớp phủ" — `userEvent.click(el)`
     trong jsdom gọi THẲNG handler trên `el` được chỉ định, KHÔNG hit-test
     theo toạ độ như trình duyệt thật. Nếu `z-10` bị xoá, bị một lớp khác đè
     (`!important`, thứ tự CSS), hay một ancestor vô tình dựng stacking
     context mới nhốt nó xuống dưới `::after` — bài test bằng `closest('a')`
     và `userEvent.click` vẫn XANH trong khi trình duyệt thật NUỐT cú bấm.
     Review round 2 (2026-08-14) chỉ đúng chỗ hổng này; sửa bằng hai việc:
       - thêm assert `z-10` có mặt (bắt được việc GỠ lớp, dù không hit-test được)
       - đóng vòng bằng THỰC NGHIỆM trên Chromium thật qua Playwright
         (`page.mouse.click()` vào toạ độ thật trong vùng vẽ/hàng nhãn ngày,
         đọc `page.url()` sau mỗi cú bấm) — ba con số đo được, một đối chứng
         ÂM (URL không đổi khi bấm vùng vẽ/nhãn ngày) và một đối chứng DƯƠNG
         (URL ĐÃ đổi sang `/convos` khi bấm vùng trống của ô, để loại trừ khả
         năng "không đổi" chỉ vì cả ô không bấm được). Kết quả 2026-08-14 (ghi
         lại — không lặp lại thí nghiệm mỗi lần đọc file này):
           · bấm toạ độ trong vùng vẽ biểu đồ → URL vẫn `.../dashboard`
           · bấm toạ độ trong hàng nhãn ngày → URL vẫn `.../dashboard`
           · bấm toạ độ trống (padding cạnh tiêu đề ô ①) → URL đổi thành
             `.../convos`
         Xem `docs/superpowers/bao-cao-o-bam-duoc.md` mục "Đóng vòng bằng
         thực nghiệm" cho script + log đầy đủ. */
  it('vùng vẽ biểu đồ + hàng nhãn ngày ô ① KHÔNG nằm trong link nào, VÀ mang lớp z-10', async () => {
    /* `bieu-do-ve` là chính vùng bám chuột (`bocRef` ở `BieuDoNgay.tsx`) —
       jsdom không có `ResizeObserver` thật nên SVG bên trong (`role="img"`)
       không vẽ được ở đây (W/H luôn 0), nhưng vùng bám chuột vẫn render bất
       kể kích thước — đủ để kiểm cấu trúc. */
    veRoi()
    const ve = await screen.findByTestId('bieu-do-ve')
    expect(ve.closest('a')).toBeNull()
    expect(ve.classList.contains('z-10')).toBe(true)
    await userEvent.click(ve)
    // Bấm vào vùng vẽ không ném lỗi, không điều hướng — vẫn cùng một cây.
    // (Đây là điều bài jsdom này chứng minh được; KHÔNG phải bằng chứng
    // "bấm xuyên lớp phủ" — xem chú thích trên.)
    expect(screen.getByTestId('o-hoi-thoai')).toBeInTheDocument()

    const nhanNgay = screen.getByTestId('nhan-ngay-0')
    expect(nhanNgay.closest('a')).toBeNull()
    // `z-10` nằm ở HÀNG bọc ngoài (`div` cha, `BieuDoNgay.tsx`), không phải ở
    // từng `<button>` nhãn ngày — nâng cả hàng một lần thay vì lặp lại trên N
    // nút. `parentElement` là đúng hàng đó (mỗi nút là con trực tiếp của nó).
    expect(nhanNgay.parentElement?.classList.contains('z-10')).toBe(true)
  })

  it('tenant 0 phiên + 0 đánh giá ⇒ thẻ dẫn hướng, KHÔNG lưới toàn số 0', async () => {
    /* Spec §4.4. Một lưới năm ô toàn 0 trông y hệt màn hỏng, và nó bắt người
       mới đọc năm chỗ để rút ra đúng một điều: chưa bắt đầu. */
    datOverview(RONG)
    veRoi()

    expect(await screen.findByTestId('tong-quan-rong')).toHaveTextContent('Chưa có hội thoại nào')
    const lien = screen.getByRole('link', { name: /Thử agent/ })
    expect(lien).toHaveAttribute('href', '/thu-agent')
    for (const k of ['o-hoi-thoai', 'o-chuyen-sale', 'o-danh-gia', 'o-kien-thuc', 'o-chi-phi']) {
      expect(screen.queryByTestId(k)).not.toBeInTheDocument()
    }
  })

  it('0 phiên NHƯNG kho kiến thức đã đầy ⇒ vẫn hiện lưới, không cắt', async () => {
    /* Hai vế chứ không một: `kienThuc` đếm TỒN KHO, không đếm theo kỳ. Tenant
       vừa nạp xong 1.203 căn mà bị cắt cả lưới là giấu đúng thứ họ vừa làm.
       Điều kiện cắt chỉ đúng khi CẢ hội thoại LẪN đánh giá đều rỗng — ca này
       có 12 lượt đánh giá nên lưới phải còn. */
    datOverview({
      ...RONG,
      danhGia: {
        ...RONG.danhGia,
        trungBinh: 4.5,
        tong: 12,
        theoSao: { '1': 0, '2': 0, '3': 0, '4': 6, '5': 6 },
      },
      kienThuc: { muc: [{ khoa: 'can', thay: 964, tong: 1203 }] },
    })
    veRoi()

    expect(await screen.findByTestId('o-kien-thuc')).toBeInTheDocument()
    expect(screen.queryByTestId('tong-quan-rong')).not.toBeInTheDocument()
  })

  it('ô Kiến thức có hàng «Dữ liệu ngoài» khi đọc được, mất hàng khi thiếu quyền', async () => {
    const co = {
      ...RONG,
      danhGia: { ...RONG.danhGia, trungBinh: 4.5, tong: 12, theoSao: { '1': 0, '2': 0, '3': 0, '4': 6, '5': 6 } },
      kienThuc: { muc: [{ khoa: 'duAn', thay: 2, tong: 2 }, { khoa: 'kyNang', thay: 5, tong: 9 }] },
    }
    datOverview(co)
    server.use(http.get('/api/v1/kb-web/overview', () => HttpResponse.json({ soDuAn: 4, soDuAnCoHoSo: 3 })))
    const { unmount } = veRoi()
    const hang = await screen.findByTestId('kt-hang-duLieuNgoai')
    expect(hang).toHaveAttribute('href', '/du-lieu-ngoai')
    unmount()

    datOverview(co)
    server.use(
      http.get('/api/v1/kb-web/overview', () =>
        HttpResponse.json({ error: { code: 'FORBIDDEN', message: 'Không có quyền' } }, { status: 403 }),
      ),
    )
    veRoi()
    expect(await screen.findByTestId('kt-hang-kyNang')).toBeInTheDocument()
    expect(screen.queryByTestId('kt-hang-duLieuNgoai')).not.toBeInTheDocument()
  })

  it('API lỗi thì hiện thông báo, không trắng màn', async () => {
    server.use(
      http.get('/api/v1/overview', () =>
        HttpResponse.json(
          { error: { code: 'FORBIDDEN', message: 'Không có quyền' } },
          { status: 403 },
        ),
      ),
    )
    veRoi()
    await waitFor(() => expect(screen.getByTestId('tong-quan-loi')).toBeInTheDocument())
    expect(screen.getByTestId('tong-quan-loi')).toHaveTextContent('Không có quyền')
  })

  it('bấm "Thử lại" gọi lại API lỗi', async () => {
    let lanGoi = 0
    server.use(
      http.get('/api/v1/overview', () => {
        lanGoi += 1
        return HttpResponse.json(
          { error: { code: 'FORBIDDEN', message: 'Không có quyền' } },
          { status: 403 },
        )
      }),
    )
    veRoi()
    await waitFor(() => expect(screen.getByTestId('tong-quan-loi')).toBeInTheDocument())
    expect(lanGoi).toBe(1)
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    await waitFor(() => expect(lanGoi).toBe(2))
  })

  /* ── Tooltip phải nằm NGOÀI thẻ ô (round fix 2026-08-14) ─────────────────
     Đây là cổng cho một lớp lỗi mà jsdom KHÔNG tự bắt được, và đó chính là
     cách nó lọt tới người dùng: ba bài tooltip ở `overview-bieu-do.test.tsx`
     và `overview-kien-thuc.test.tsx` đều XANH suốt thời gian tooltip hỏng
     trên trình duyệt thật, vì jsdom không có engine bố cục — nó không dựng
     stacking context, không đổi containing block theo `transform`, không cắt
     theo `overflow`.

     Thứ jsdom ĐO ĐƯỢC là quan hệ CHA-CON trong DOM, và đúng quan hệ đó là
     nguyên nhân: `O_BAM_DUOC` mang `hover:-translate-y-0.5`, nên hễ tooltip
     còn là hậu duệ của thẻ ô thì lúc rê chuột (= lúc thẻ có `transform`) nó
     bị thẻ nhốt lại — sai vị trí, chui xuống dưới các ô khác, và bị
     `overflow-hidden` cắt. `HopTip` vì thế portal ra `document.body`.

     Bài này đỏ ngay nếu ai đó gỡ `createPortal` trong `Tip.tsx`. */
  it('tooltip render ra ngoài thẻ ô (portal), không phải hậu duệ của ô có transform', async () => {
    veRoi()
    const o = await screen.findByTestId('o-hoi-thoai')

    fireEvent.mouseMove(screen.getByTestId('bieu-do-ve'), { clientX: 120, clientY: 200 })

    const tip = screen.getByTestId('ht-tip')
    expect(document.body.contains(tip)).toBe(true)
    // Vế QUYẾT ĐỊNH: `o` mang `hover:-translate-y-0.5`, nên tooltip là hậu duệ
    // của nó nghĩa là tooltip hỏng trên trình duyệt thật.
    expect(o.contains(tip)).toBe(false)
  })

  it('tooltip ô ⑤ Kiến thức cũng ra ngoài thẻ — hàng chỉ cao ~35px, nằm trong là bị cắt sạch', async () => {
    veRoi()
    const o = await screen.findByTestId('o-kien-thuc')

    fireEvent.mouseMove(screen.getByTestId('kt-hang-duAn'), { clientX: 300, clientY: 400 })

    const tip = screen.getByTestId('kt-tip')
    expect(document.body.contains(tip)).toBe(true)
    expect(o.contains(tip)).toBe(false)
  })

  it('tooltip ô ③ Khách đánh giá tồn tại VÀ cũng ra ngoài thẻ', async () => {
    /* Ô ③ trước round fix này KHÔNG có tooltip nào, dù demo có — nên vế đầu
       (`getByTestId` không ném) chính là bài kiểm "đã port", còn vế sau là
       cùng cổng portal với hai ô kia. */
    veRoi()
    const o = await screen.findByTestId('o-danh-gia')

    fireEvent.mouseMove(screen.getByTestId('dg-sao-5'), { clientX: 300, clientY: 400 })

    const tip = screen.getByTestId('dg-tip')
    expect(document.body.contains(tip)).toBe(true)
    expect(o.contains(tip)).toBe(false)
  })

  it('lưới có tầng mobile: một cột, không ép cao một viewport', async () => {
    // Kiểm CLASS vì jsdom không vẽ layout — hình học thật do kiem-responsive đo.
    const { container } = veRoi()
    await screen.findByTestId('o-hoi-thoai')
    // Dấu `[`/`(` phải escape trong selector CSS — nwsapi (bộ chọn của
    // jsdom) không khớp được nếu để trần, dù trình duyệt thật khớp cả hai.
    const luoi = container.querySelector('[class*="grid-cols-\\[repeat\\(24"]')!
    expect(luoi.className).toContain('max-md:grid-cols-1')
    expect(luoi.className).toContain('max-md:grid-rows-none')
    for (const id of ['o-hoi-thoai', 'o-chuyen-sale', 'o-danh-gia', 'o-kien-thuc', 'o-chi-phi']) {
      expect((await screen.findByTestId(id)).className).toContain('max-md:col-span-full')
    }
  })

  /* ── Fix round 1 (Task 6 reopened) ────────────────────────────────────────
     `max-md:auto-rows-auto` (dòng trên) làm mỗi ô cao theo NỘI DUNG thay vì
     `1fr` cố định — bên trong `o-hoi-thoai`, `BieuDoNgay` đo chiều cao bằng
     `ResizeObserver` trên một `div` mang `min-h-0 flex-1`: một cột flex có
     chiều cao `auto` không cho hậu duệ `flex-1` (flex-basis 0%) mượn chỗ để
     lớn lên, nên trên trình duyệt thật `clientHeight` đo ra 0 và SVG không
     vẽ gì (`W > 0 && H > 0` chặn cả path). `min-h-[260px]` trên chính ô cho
     flex-column bên trong một sàn chiều cao THẬT để phân phối cho `flex-1`.
     jsdom không có engine bố cục nên bài này chỉ khoá CLASS — hình học thật
     do `kiem-responsive.mjs` đo (xem report). */
  it('ô Hội thoại có sàn chiều cao ở mobile, để BieuDoNgay đo được > 0', async () => {
    veRoi()
    const o = await screen.findByTestId('o-hoi-thoai')
    expect(o.className).toContain('max-md:min-h-[260px]')
  })
})
