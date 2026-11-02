/**
 * Khởi động app bằng CÂY ROUTE THẬT (`src/routeTree.gen.ts`), không dựng router
 * bằng tay.
 *
 * VÌ SAO TÁCH KHỎI `shell.test.tsx`: file đó dựng router trong bộ nhớ với
 * màn giả — nó canh được shell và canh được quyền, nhưng KHÔNG canh
 * được `routeTree.gen.ts` (file do plugin sinh). Nếu ai thêm route mà quên
 * `make routes-fe`, hoặc layout `_app` bị nối sai, thì mọi test kia vẫn xanh mà
 * `npm run dev` mở ra màn trắng. Test này bít đúng khoảng đó.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { TONG_DANH_GIA_GIA } from '../src/lib/msw/danhGiaGia'
import { routeTree } from '../src/routeTree.gen'

/**
 * Dấu hiệu để nhận ra route đã mở, khoá theo path bỏ `/` đầu. Thêm route mới
 * vào `_app` mà quên thêm dòng ở đây thì bài «mọi màn mở được» đỏ.
 */
const DAU_HIEU_MAN_THAT: Record<string, string> = {
  // Màn Kịch bản (G3) — chú giải màu chỉ có sau khi lazy chunk + query bản đồ về.
  'kich-ban': 'Đạt từ 80%',
  // Màn Hồ sơ & tuỳ chọn (2026-08-22, thay ScreenStub). Dấu hiệu là nút «Sửa
  // hồ sơ» — chỉ hiện sau khi SessionProvider có phiên, và không trùng nhãn
  // nav «Hồ sơ & tuỳ chọn» mà Topbar render thành <h1> (bẫy đã ghi ở kb/users).
  settings: 'Sửa hồ sơ',
  // M2b — UserAdmin, trục đổi sang WORKSPACE (2026-08-09). Bảng phẳng, không
  // còn tab. KHÔNG dùng chữ «Thành viên» trần: nó khớp CẢ tiêu đề khối
  // (`<h2>`, `DauMuc`) LẪN tên cột đầu bảng (`<th>`, `COT`) — hai phần tử, một
  // chuỗi. Nút chính trên dải công cụ («Mời thành viên») là chỗ duy nhất mang
  // đúng cụm đó, và nó chỉ hiện sau khi query đầu về (không phải khung chờ).
  users: 'Mời thành viên',
  // `/roles` KHÔNG còn là một màn riêng: nó redirect sang `/users`. Trước
  // 2026-08-09 nó mang thêm `?tab=vai-tro` để mở đúng tab Vai trò; tab đó đã rời
  // giao diện cùng ngày (13 action ở lại backend, xem UserAdmin.tsx), nên `/roles`
  // giờ hạ cánh lên ĐÚNG bảng thành viên mà `/users` cũng mở — cùng dấu hiệu.
  roles: 'Mời thành viên',
  // M7 — HopThuSale. Dấu hiệu là tiêu đề cột danh sách, KHÔNG phải nhãn nav
  // «Chuyển sale»: `Topbar` render nhãn đó thành `<h1>` và panel cũng có đúng
  // chữ ấy — cùng bẫy đã ghi ở `kb`/`users`/`api`. Chuỗi này chỉ hiện sau khi
  // query về, nên nó còn chứng minh màn nạp được dữ liệu.
  // Tab mặc định là «Tất cả» ⇒ tiêu đề cột là «Tất cả ca» (đổi theo tab từ 05/10).
  'chuyen-sale': 'Tất cả ca',
  agent: 'Rào chắn đang bảo vệ workspace', // M5 — AgentStudio («Cấu hình chung»)
  // M5 — KyNangBds, tách khỏi /agent 2026-08-07. Dấu hiệu là tiêu đề thẻ, KHÔNG
  // phải nhãn nav «Kỹ năng»: `Topbar` render nhãn đó thành `<h1>` và panel cũng
  // có đúng chữ ấy — cùng bẫy đã ghi ở `kb`/`users`/`api`/`projects`.
  'ky-nang-bds': 'Kỹ năng Bất động sản',
  // M5 — QuanLyLinhVuc (2026-08-08). Dấu hiệu là chữ trong HÀNG của bảng, không
  // phải tên lĩnh vực «Bất động sản»: chuỗi đó cũng là NHÃN KHỐI trong panel
  // Agent nên sẽ trúng hai phần tử. Chuỗi này chỉ hiện sau khi query lĩnh vực
  // về, nên nó còn chứng minh màn nạp được dữ liệu chứ không đứng ở «Đang tải…».
  domains: 'chưa có dữ liệu để agent tra',
  // M6 — DuLieuNgoaiScreen (2026-10-05). Dấu hiệu là tiêu đề khối của tab Tổng
  // quan, KHÔNG phải nhãn nav «Dữ liệu ngoài» (Topbar + panel cùng mang chữ đó);
  // chỉ hiện sau khi query overview về.
  'du-lieu-ngoai': 'Kho dữ liệu ngoài của workspace',
  // M8 — ThuAgentScreen, chat qua gateway thật (2026-08-10). Dấu hiệu là nhãn
  // ô «API Key»:
  //   · KHÔNG dùng nhãn nav «Thử agent» — `Topbar` render nó thành `<h1>` và
  //     panel cũng có đúng chữ ấy, nên sẽ trúng hai phần tử.
  //   · Ô này hiện ngay khi khoá tải xong (không cần WS nào), khác câu mời
  //     trong khung chat — khung đó chỉ hiện SAU khi kết nối WS thành công.
  //   · Trước 2026-08-11 (lần hai) dùng nhãn ô «WS URL» — ô đó đã bỏ khỏi UI
  //     (fix cứng trong code, xem `CLAUDE.md` mục Thử agent).
  'thu-agent': 'API Key',
  // M8 — TichHopApiScreen (khoá đấu nối agent). Dấu hiệu là TIÊU ĐỀ THẺ BẢNG,
  // không phải nhãn nav API Keys: `Topbar.tsx:43` render nhãn đó thành `<h1>` nên
  // dùng nó sẽ trúng hai phần tử — cùng cái bẫy đã ghi ở `users` và `projects`.
  // Trước đây dòng này là câu mô tả dưới tiêu đề; câu đó đã bỏ (2026-08-08). Chuỗi
  // mới chỉ hiện SAU khi query khoá về, nên nó còn chứng minh màn nạp được dữ
  // liệu chứ không đứng ở «Đang tải…» — cùng lối mục `domains`.
  'api-keys': 'Khoá đấu nối agent',
  kb: 'Tên tệp', // M6 — TaiLieuList (nhãn cột; chuỗi dropzone bị cắt bởi nội suy)
  // M4 — ba màn KB BĐS. Dấu hiệu chọn chuỗi KHÔNG trùng nhãn nav: sidebar cũng có
  // mục Bất động sản, nên dùng nó sẽ trúng hai phần tử và `findByText` đỏ.
  projects: 'Kinh doanh', // DuAnList — nhãn cột bảng dự án (mã + tên gộp một ô)
  pform: 'Dự án mới', // DuAnForm — tiêu đề lúc chưa có `?code`
  uform: 'Về danh sách dự án', // CanForm — `/uform` trần thiếu `?code`, chỉ có đường về
  // M7 — KhachList (Task 5). Dấu hiệu là tên một khách trong fake MSW
  // (`features/ops/msw.ts`), KHÔNG phải nhãn nav «Hội thoại»: `Topbar` render
  // nhãn đó thành `<h1>` và sidebar cũng có đúng chữ ấy, nên dùng lại nó sẽ
  // trúng hai phần tử — cùng bẫy đã ghi ở `kb`/`users`/`roles`/`api`/`projects`.
  // (2026-08-07: `KhachList` trước đây còn tự render `<h1>Hội thoại</h1>` thành
  // ra ba chỗ; nó đã hạ xuống `<h2>` nên giờ chỉ còn topbar + sidebar.)
  // KHÔNG dùng mốc ngày («Hôm nay»/«Tuần trước» …) — nó phụ thuộc ngày chạy
  // test so với timestamp cố định trong fake data.
  convos: 'Nguyễn Minh Anh',
  // M7 — FeedbackList (Task 10, un-defer 2026-08-12). Dấu hiệu là dòng thống
  // kê «N lượt đánh giá» của `FeedbackTongQuan`, KHÔNG phải nhãn nav «Chất
  // lượng»: `Topbar` render nhãn đó thành `<h1>` và panel cũng có đúng chữ
  // ấy — cùng bẫy đã ghi ở `kb`/`users`/`api`/`projects`/`convos`. Chuỗi này
  // chỉ hiện SAU khi query feedback về, nên nó còn chứng minh màn nạp được dữ
  // liệu chứ không đứng ở «Đang tải…».
  // Con số là TỔNG của tenant (`lib/msw/danhGiaGia.ts`), KHÔNG phải số hàng
  // trong trang đầu — fake `items` vẫn đúng 5 bản ghi mẫu, nhưng `total` đi
  // theo backend thật (thống kê tính trên toàn bộ, bất kể phân trang) và dùng
  // chung nguồn với ô ③ màn Tổng quan.
  quality: `${TONG_DANH_GIA_GIA} lượt đánh giá`,
  // M7 — TongQuanScreen (Task 11). Dấu hiệu là link «Xem chi phí» của ô Chi phí
  // (06/10 — tiêu đề ô hai tile cũ đã bỏ),
  // KHÔNG phải nhãn nav «Tổng quan»: `Topbar` render nhãn đó thành `<h1>` và
  // panel cũng có đúng chữ ấy — cùng bẫy đã ghi ở `kb`/`users`/`api`/
  // `projects`/`convos`/`quality`. Chuỗi này chỉ hiện ở nhánh ĐÃ CÓ DỮ LIỆU
  // (không đứng ở khung chờ `tong-quan-dang-tai` lẫn khung lỗi
  // `tong-quan-loi`), nên nó còn chứng minh màn nạp được `overview()` — cùng
  // lối `domains`/`quality`.
  dashboard: 'Xem chi phí',
  // M11 — UsageScreen (Task 4, un-defer 2026-08-20 spec usage-billing-fe).
  // ⚠️ KHOÁ LÀ `billing`, KHÔNG phải `usage`: nội dung chuyển chỗ 2026-08-24
  // (người dùng chốt — `billing` = xem số tiền · chi phí). Dấu hiệu là tiêu đề mục ③ «Lượt dùng chi tiết», KHÔNG phải nhãn nav
  // «Billing»: `Topbar` render nhãn đó thành `<h1>` và panel cũng có đúng
  // chữ ấy — cùng bẫy đã ghi ở `kb`/`users`/`api`/`projects`/`convos`/
  // `quality`/`dashboard`. Chuỗi này chỉ hiện SAU khi `/billing/summary` về
  // (không đứng ở khung skeleton 5 thẻ xám, cùng gate với thẻ KPI), nên nó
  // còn chứng minh màn nạp được dữ liệu. ⚠️ KHÔNG dùng lại «Tổng chi phí»
  // (đổi 2026-08-25): từ khi bảng ③ mọc cột cùng tên, `findByText` trần khớp
  // CẢ HAI (tiêu đề thẻ KPI lẫn nút cột sắp xếp) và ném «found multiple
  // elements» — đây là dấu hiệu DUY NHẤT trong bảng này, không đi qua
  // `getByRole('heading', …)` như các bài trong `billing-usage.test.tsx`.
  billing: 'Lượt dùng chi tiết',
  // M8 — UsageLuongDungScreen (spec 2026-08-24 man-usage-bay-tab). Dấu hiệu là
  // tiêu đề thẻ ② «Lượt dùng chi tiết», KHÔNG phải nhãn nav «Usage»: `Topbar`
  // render nhãn đó thành `<h1>` và panel cũng có đúng chữ ấy — cùng bẫy đã ghi
  // ở `kb`/`users`/`api`/`projects`/`convos`/`quality`/`dashboard`/`billing`.
  //
  // ⚠️ KHÔNG còn dùng nhãn mục rail «Thời gian gọi» (đúng ở đây tới
  // 2026-08-25): tab «Khoá»/«Người tạo» của bảng ② đổi cột «Giây gọi» →
  // «Thời gian gọi» cùng ngày, và tab đó MỞ MẶC ĐỊNH (`gop: 'khoa'` ở
  // `validateSearch`) — nên chuỗi đó nay khớp CẢ mục rail lẫn tiêu đề cột
  // trong cùng một lượt render, `findByText` ném «multiple elements». Cũng
  // KHÔNG dùng «Token» (mục rail ĐẦU): nó là tiêu đề mặc định của biểu đồ nên
  // khớp ở hai chỗ cùng lúc, và nó là chuỗi con của «Token quản trị nền tảng»
  // — dấu hiệu của `pricing` ngay dưới. Một dấu hiệu khớp hai màn thì bài này
  // thôi phân biệt được màn nào đã mở.
  //
  // Chuỗi «Lượt dùng chi tiết» hiện NGAY lúc mount (`ThanhCong` không đợi
  // `isPending`) — khác quy ước «chỉ hiện sau khi có dữ liệu» của các dấu hiệu
  // khác trong bảng này, nhưng nó vẫn ở SAU async `RouterProvider`/lazy route
  // nên `findByText` vẫn cần cho route mở đúng component (cùng lý lẽ `pricing`
  // dưới đây).
  usage: 'Lượt dùng chi tiết',
  // M8 — NhatKyScreen (2026-08-25, thay ScreenStub). Dấu hiệu là nhãn công tắc
  // «Hiện hoạt động của agent», KHÔNG phải nhãn nav «Nhật ký» (Topbar render
  // nhãn đó thành <h1>, panel cũng có — cùng bẫy đã ghi ở kb/users/…). Chuỗi này
  // hiện NGAY lúc mount (thanh lọc không đợi request), nên chỉ chứng minh route
  // mở đúng component — cùng hạng `pricing`.
  audit: 'Hiện hoạt động của agent',
  // M9 — BangGiaScreen (Task 8, spec usage-billing-fe). Dấu hiệu là nhãn ô
  // token quản trị nền tảng, KHÔNG phải nhãn nav «Bảng giá» — cùng bẫy đã ghi
  // ở `kb`/`users`/`api`/`billing`. Chuỗi này hiện NGAY lúc mount (không đợi
  // request nào về, đúng chủ ý: thiếu token thì màn không gọi API admin), nên
  // nó không chứng minh được việc nạp dữ liệu — chỉ chứng minh route mở đúng
  // component, việc `boot.test.tsx` cần canh ở đây.
  pricing: 'Token quản trị nền tảng',
  // M2a — CaiDatWorkspace. Dấu hiệu là nhãn ô «Mã workspace», KHÔNG phải nhãn
  // nav «Cài đặt workspace»: `Topbar` render nhãn đó thành `<h1>` và panel cũng
  // có đúng chữ ấy — cùng bẫy đã ghi ở `kb`/`users`/`api`/`projects`/`convos`.
  // Cũng KHÔNG dùng `<h2>` «Thông tin workspace»: nó hiện trước cả khi có gì để
  // hiện, còn nhãn này đứng ngay trên chính mã workspace lấy từ phiên.
  workspace: 'Mã workspace',
}

function boot(path: string) {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  // KHÔNG bọc <SessionProvider> ở đây — nó nằm trong route `_app`, giống hệt
  // main.tsx. Bọc thêm ở đây thì test không còn kiểm được vị trí thật của nó.
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

describe('app khởi động bằng routeTree.gen.ts thật', () => {
  /**
   * `/` là TRANG GIỚI THIỆU công khai, không còn redirect sang /dashboard
   * (2026-08-10). Trước đó `_app/index.tsx` đá thẳng sang dashboard; hai thứ
   * không sống chung được vì `_app` là layout pathless nên `_app/index.tsx`
   * cũng ra path `/`.
   *
   * Điểm phải canh ở đây là trang này đứng NGOÀI `_app`: nó không được kéo
   * theo shell, vì shell nằm dưới `SessionProvider` và provider đó chặn cả cây
   * trên `GET /api/v1/me`. Có shell ở `/` nghĩa là ai đó đã nhét route này vào
   * trong `_app`, và trang sẽ trắng với người chưa đăng nhập.
   */
  it('vào `/` thì thấy trang giới thiệu, KHÔNG kéo theo shell', async () => {
    boot('/')
    expect(await screen.findByText(/Có người nghe máy/)).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Mảng' })).not.toBeInTheDocument()
  })

  it('/dashboard có shell và có màn', async () => {
    boot('/dashboard')
    // Panel của layout `_app` — nếu layout nối sai thì không có nó. `aria-label`
    // của panel LÀ tên mảng đang mở, nên truy vấn này khẳng định luôn rằng
    // /dashboard nằm đúng trong mảng Vận hành.
    const nav = await screen.findByRole('navigation', { name: 'Vận hành' })
    expect(within(nav).getByText('Tổng quan')).toBeInTheDocument()
    // nội dung màn dashboard — xem `DAU_HIEU_MAN_THAT.dashboard` cho lý do
    // chọn đúng chuỗi này.
    expect(await screen.findByText('Xem chi phí')).toBeInTheDocument()
  })

  it('<title> mang tên màn đang mở (WCAG 2.4.2)', async () => {
    boot('/dashboard')
    await screen.findByRole('navigation', { name: 'Vận hành' })
    await waitFor(() => expect(document.title).toBe('Tổng quan · NobleX Agent'))
  })

  /**
   * Nút thu gọn sidebar (2026-08-24): ẨN PANEL 240px, GIỮ RAIL — rail là điều
   * hướng chính giữa các mảng, ẩn luôn nó thì chỉ còn ⌘K. Nút nằm ở ĐÁY RAIL
   * chứ không trong panel: nó phải còn nhìn thấy được ở CẢ trạng thái đã thu
   * gọn (bản đầu đặt ở Topbar thì lấn vào tiêu đề màn — người dùng chê ngay).
   *
   * Test ở ĐÂY chứ không ở shell.test.tsx: state thu gọn sống trong layout
   * `_app.tsx` thật, còn shell.test.tsx dựng root riêng không đi qua `_app` —
   * test bên đó sẽ phải chép lại phần nối dây, tức test một bản sao.
   */
  it('nút thu gọn ẩn panel màn nhưng giữ rail; bấm lại thì panel trở lại', async () => {
    boot('/dashboard')
    const user = userEvent.setup()
    // Panel đang mở — aria-label của nó là tên mảng.
    await screen.findByRole('navigation', { name: 'Vận hành' })

    await user.click(screen.getByRole('button', { name: 'Thu gọn thanh bên' }))
    expect(screen.queryByRole('navigation', { name: 'Vận hành' })).not.toBeInTheDocument()
    // Rail phải CÒN — chỉ panel 240px bị thu, không phải cả sidebar.
    expect(screen.getByRole('navigation', { name: 'Mảng' })).toBeInTheDocument()

    // Cùng chỗ đó giờ là nút mở lại (hai nhãn, hai mark — không phải một nút
    // đổi nghĩa ngầm theo trạng thái).
    await user.click(screen.getByRole('button', { name: 'Mở thanh bên' }))
    expect(await screen.findByRole('navigation', { name: 'Vận hành' })).toBeInTheDocument()
  })

  it('mọi màn đều mở được qua cây route thật', async () => {
    const duong = Object.values(createRouter({ routeTree }).routesById)
      .filter((r) => r.parentRoute?.id === '/_app')
      .map((r) => r.fullPath)
    for (const p of duong) {
      const { unmount } = boot(p)
      const dauHieu = DAU_HIEU_MAN_THAT[p.slice(1)]
      expect(dauHieu, `route ${p} chưa có dấu hiệu trong DAU_HIEU_MAN_THAT`).toBeDefined()
      expect(
        await screen.findByText(dauHieu!),
        `route ${p} không mở được — chạy \`make routes\` chưa?`,
      ).toBeInTheDocument()
      // Layout phải bọc mọi màn, không chỉ màn đầu. Kiểm bằng RAIL chứ không
      // bằng panel: `aria-label` của panel đổi theo mảng, còn rail tên cố định
      // «Mảng» ở mọi màn — vòng lặp này đi qua mọi màn thuộc cả ba mảng.
      expect(screen.getByRole('navigation', { name: 'Mảng' })).toBeInTheDocument()
      unmount()
    }
  })

  it('route CON /convos/$phone render được màn chi tiết, không kẹt ở danh sách', async () => {
    // Cổng riêng cho Finding 1 của review cuối nhánh M7: `ManConvos` (route cha
    // `/convos`) từng trả THẲNG `<KhachList/>`, không có `<Outlet/>` — bấm một
    // hàng khách đổi URL sang `/convos/$phone` nhưng màn vẫn là danh sách,
    // `PhienKhach` (Task 6) không bao giờ mount. Vòng lặp "mọi màn đều mở được"
    // ở trên KHÔNG bắt được lỗi này: nó chỉ đi route cấp một `/convos` (route cha),
    // không khai route con `/convos/$phone` — điều hướng tới ĐÚNG route con là
    // thứ 14 test của `tests/convos-phien.test.tsx` không kiểm được, vì file đó
    // dựng `PhienKhach` trực tiếp bằng router tối giản, không đi qua
    // `routeTree.gen.ts` thật (xem docstring `dung()` ở đó).
    //
    // Đã tự kiểm cổng này là cổng THẬT: tạm bỏ `<Outlet/>` ở `convos.tsx`, chạy
    // đúng test này, thấy ĐỎ (route con không mount, không tìm thấy chuỗi cột
    // phiên) — dán output đỏ vào `final-fix-report.md`. Hoàn tác ngay sau đó.
    boot('/convos/0912448111')
    // Chuỗi của cột phiên (Phien Anh 1, fake MSW `features/ops/msw.ts`) — chỉ
    // `PhienKhach` render, `KhachList` không có chuỗi này.
    expect(await screen.findByText(/27\/07\/2026/)).toBeInTheDocument()
    // Ký tự đường về là `‹`, không phải `←` (2026-08-09): link này đã chuyển
    // sang hằng `DUONG_VE` dùng chung của portal.
    expect(screen.getByText('‹ Tất cả khách')).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Mảng' })).toBeInTheDocument()
  })

  it('đường dẫn không tồn tại ra màn 404, không phải màn trắng', async () => {
    boot('/duong-dan-khong-co-that')
    expect(await screen.findByText('Không có màn này')).toBeInTheDocument()
  })

  it('provider phiên nằm trong `_app`, không bọc router', async () => {
    // Nếu ai chuyển SessionProvider trở lại main.tsx thì /login sẽ bị chặn bởi
    // splash "Đang tải phiên…" và test này đỏ.
    boot('/login')
    expect(await screen.findByLabelText('Email')).toBeInTheDocument()
  })
})
