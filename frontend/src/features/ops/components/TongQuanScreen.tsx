/**
 * Màn `/dashboard` — Tổng quan (Task 11, lắp Task 6 + Task 8-10 thành màn thật).
 *
 * Bố cục lưới bento 2 hàng và khoảng cách PORT từ `docs/design/demo-tong-quan.html`
 * (bản đã duyệt — file đó GIỮ LẠI để đối chiếu, không xoá). Thứ tự ô và nội dung
 * ô Chuyển sale/Chi phí đã rời bản demo (shape «Cần bạn» 06/10 — xem `SPAN`,
 * `OChuyenSale`, `OChiPhi`).
 *
 * KHOÁ TRONG MỘT MÀN — không cuộn:
 *   · `72px` là chiều cao THẬT của `Topbar` (`h-[72px]`, `components/shell/
 *     Topbar.tsx`) — màn này render làm con của `<main>` trong `routes/_app.tsx`,
 *     ngay dưới `<Topbar/>`, nên khung ngoài phải trừ đúng số đó. Số này KHÔNG
 *     rút được ra một hằng dùng chung với `Topbar.tsx`: `components/shell/*`
 *     bị cấm sửa (xem CLAUDE.md), nên đây là con số viết tay, không phải sót
 *     — đổi chiều cao Topbar thì phải tự tay sửa cả hai chỗ.
 *   · `dvh` chứ không `vh`: trên di động `100vh` cao hơn chỗ thật sự nhìn thấy
 *     (thanh địa chỉ chưa thu), nên một khung "không cuộn" đo bằng `vh` vẫn
 *     cuộn được vài chục pixel. `overflow-hidden` + `min-h-0` trên MỌI ô của
 *     lưới — thiếu một ô là ô đó tự phình theo nội dung và đẩy cả lưới ra
 *     ngoài màn.
 *
 * KHÔNG dùng `useLang()`/`useSession()`: `tests/overview-man.test.tsx` render
 * `TongQuanScreen` mà không dựng `LangProvider`/`SessionProvider` (cùng lý lẽ
 * `khoa-dau-noi.test.tsx:11`). Bốn component ô (Task 8-10) cũng không đụng
 * hai thứ đó, cùng một lý do.
 *
 * ⚠️ `<Link>` (TanStack Router) thì CÓ, từ round fix 2026-08-13 — đảo lại
 * quyết định ban đầu của file này. Màn mọc hai đường đi thật («Xem tất cả →»
 * ở ô ①, «Thử agent» ở thẻ dẫn hướng lúc rỗng), và một `<a href>` trần ở
 * đó là tải lại cả tài liệu: SPA boot lại, `GET /me` chạy lại, màn chớp
 * trắng — cái giá đó đắt hơn hẳn việc test phải bọc thêm một router. Router
 * bọc trong test là `createRootRoute` + `createMemoryHistory`, đúng khuôn
 * `tests/quality-review-card.test.tsx` đã dùng sẵn cho cùng tình huống;
 * KHÔNG phải boot cả `routeTree` thật.
 *
 * Tiêu đề «Tổng quan» KHÔNG lặp lại ở đây — `Topbar` đã render nó từ nhãn nav
 * (`dashboardNav.label`), một `<h1>` thứ hai là chữ trùng (cùng lỗi `/convos`
 * đã sửa 2026-08-09). Hàng đầu màn vì thế chỉ còn ĐÚNG nhãn kỳ, đọc như phụ
 * đề của cái `<h1>` ở topbar ngay trên nó.
 *
 * Bộ lọc khoảng thời gian ở đầu màn của demo (7 ngày/4 tuần/Tất cả) là TRANG
 * TRÍ, backend chỉ nhận một cửa sổ — CẮT theo đúng scope note của task, đừng
 * thêm lại. Nhãn kỳ thì KHÔNG phải trang trí: nó là câu duy nhất nói ra màn
 * đang tóm tắt khoảng nào, và thiếu nó thì mọi con số trên màn là số của một
 * kỳ vô danh.
 *
 * NĂM Ô BẤM ĐƯỢC, MỘT KIỂU (06/10) — rê chuột vào CẢ Ô thì nhấc lên + viền
 * đậm + mũi tên trượt vào (kỹ thuật STRETCHED-LINK, đoạn dưới), bấm chỗ nào
 * trong ô cũng đi tới ĐÚNG MỘT đích (`/chuyen-sale` hàng đợi chưa liên hệ ·
 * `/convos` · `/quality` · `/projects` · `/billing`). Ô Chi phí từng là hai
 * tile hai đích (2026-08-27 → 06/10) nên từng không theo kiểu này.
 *
 * KHÔNG bọc cả ô trong `<Link>` — ô ① đã có link «Xem tất cả →» bên trong,
 * lồng `<a>` trong `<a>` là HTML không hợp lệ, và bọc cả ô sẽ nuốt mọi phần
 * tử tương tác bên trong nó (vùng vẽ biểu đồ, sáu hàng ô ⑤). Dùng kỹ thuật
 * STRETCHED-LINK thay vào: ô mang `O_BAM_DUOC` (có `relative`), link duy
 * nhất ở ĐẦU ô mang `after:absolute after:inset-0` để vùng bấm nở ra trọn ô
 * mà không cần một phần tử bọc thứ hai. Phần tử nào bên trong ô cần giữ
 * tương tác riêng (vùng vẽ + hàng nhãn ngày của ô ①, sáu hàng của ô ⑤) thì
 * mang `relative z-10` để vẽ TRÊN lớp phủ đó — thứ tự stacking chuẩn: mọi
 * phần tử positioned mang z dương luôn vẽ trên phần tử positioned z auto
 * (như `::after` ở đây), bất kể thứ tự DOM, nên không cần đụng gì tới link.
 */
import { type ReactNode, useEffect, useRef, useState } from 'react'
import { type UseQueryResult, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Icon } from '@/components/icons'
import { NUT_CHINH } from '@/components/ui/Bang'
import {
  SparklineChiPhi,
  TopDichVu,
  giaiMaKy,
  tien,
  tienGon,
  useTongQuan,
} from '@/features/billing/contracts'
import { LoiApi } from '@/lib/http'
import {
  type Ca,
  hoSoNgoai,
  KHOA_HO_SO_NGOAI,
  KHOA_OVERVIEW,
  type LocCa,
  type MucKienThuc,
  type Overview,
  type TrangCa,
  danhSachCa,
  overview,
} from '../api'
import { so, soLe1 } from '@/lib/dinhDang'
import { daCho, gioNgan, khoangKy } from '../thoiGian'
import { BieuDoNgay } from './BieuDoNgay'
import { TheDanhGia } from './TheDanhGia'
import { TheKienThuc } from './TheKienThuc'

// Stub `ResizeObserver` cho jsdom (Task 8's `BieuDoNgay` cần nó khi không
// nhận prop `co`) sống ở `vitest.setup.ts`, CẠNH stub `IntersectionObserver`
// đã có sẵn ở đó — cùng lý do, cùng khuôn, không lặp lại ở đây.

/** Màn buổi sáng để mở cả ngày: làm mới khi quay lại tab và mỗi 30 giây (critique
 *  05/10). Mặc định toàn app tắt `refetchOnWindowFocus` (`main.tsx`) — chỉ màn này bật.
 *  `refetchInterval` tự dừng khi tab ẩn. */
const LAM_MOI_MS = 30_000

/** Hàng đợi «Chưa liên hệ, cũ nhất trước» — CÙNG `loc` với `/chuyen-sale?tab=new&cu=true`
 *  nên CÙNG khoá query `['escalations', loc]` của `HopThuSale`: bấm sang là danh sách có
 *  sẵn, và nhận ca ở đó (invalidate `['escalations']`) thì số ở đây tự đúng lại. */
const LOC_CHO_GOI: LocCa = { trangThai: 'new', sapXep: 'cu' }

/** `/escalations` gác bằng `convos.read`, Tổng quan bằng `overview.read` — một vai trò
 *  có thể xem màn này mà không mở được hộp ca. Khi đó ô chỉ còn tỉ lệ chuyển, không link. */
function laThieuQuyen(e: unknown): boolean {
  return e instanceof LoiApi && e.code === 'FORBIDDEN'
}

type CaChoGoi = UseQueryResult<TrangCa>

/** Tra tên hiển thị của một kênh. `null` = agent bản cũ chưa gửi `source`. */
const TEN_KENH: Readonly<Record<string, string>> = {
  chat: 'Chat',
  voice: 'Voice',
  zalo_oa: 'Zalo OA',
}
/** Màu đường của kênh trên `BieuDoNgay` — CÙNG bảng `VE` ở đó (ds1 Chat, ds2 Voice). */
const MAU_DUONG: Record<string, string> = { chat: 'var(--color-ds1)', voice: 'var(--color-ds2)' }

function tenKenh(k: string | null): string {
  // Kênh lạ (không nằm trong TEN_KENH) hiện NGUYÊN VĂN, không đoán hộ — cùng
  // luật `Phien.source` đã ghi ở `api.ts`.
  return k === null ? 'Chưa rõ' : (TEN_KENH[k] ?? k)
}

/** Khuôn của MỌI ô trong lưới — kể cả khung skeleton, để hai trạng thái tải/
 *  xong không nhảy hình học. `min-h-0`/`min-w-0` bắt buộc: mặc định
 *  `min-height/width: auto` của flex/grid item không cho co lại dưới nội
 *  dung, và một ô phình là cả lưới bị đẩy ra ngoài màn. */
const O_CO =
  'flex min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-border bg-surface px-4 py-3.5'

/** Modifier cho ô bấm được — ghép SAU `O_CO`. Ô Chuyển sale BỎ nó khi vai trò
 *  không mở được `/chuyen-sale` (không link thì không nhấc). Bốn lớp hiệu ứng:
 *   · nâng + viền: `-translate-y-0.5` + `border-strong` + bóng `noi-nhe`
 *     (token mới, `theme.css` — nhẹ hơn `noi` vì ô này NHẤC LÊN chứ không
 *     NỔI HẲN như tooltip).
 *   · nhấn xuống: `active:` trả lại vị trí + bỏ bóng — phản hồi lúc bấm.
 *   · bàn phím: `focus-within:border-ac` để Tab tới thấy ô nào đang nhắm
 *     (link bên trong đã có `:focus-visible` toàn cục của repo).
 *   · `select-none`: kéo chuột qua một ô-là-nút mà bôi đen chữ là cảm giác
 *     hỏng — đây là "hiệu ứng select chuột" đúng nghĩa người dùng muốn.
 *  `motion-reduce:` tắt hẳn transform/transition cho người tắt chuyển động.
 *  `group` để mũi tên (`MuiTen`) trượt vào theo `group-hover`. */
// `export` để test so trực tiếp với hằng này (không chép tay từng lớp sang
// file test) — đổi tên lớp ở đây thì bài test tự đúng theo.
export const O_BAM_DUOC =
  'group relative transition-[transform,box-shadow,border-color] duration-200 ease-out select-none hover:-translate-y-0.5 hover:border-border-strong hover:shadow-noi-nhe active:translate-y-0 active:shadow-none focus-within:border-ac motion-reduce:transform-none motion-reduce:transition-none'

/** Link «đầu ô» của bốn ô bấm được — CHÍNH nó mang stretched-link
 *  (`after:absolute after:inset-0`), không phải một phần tử bọc riêng. Cố ý
 *  KHÔNG mang `relative`: `::after` phải neo vào ô cha (`O_BAM_DUOC` mới là
 *  ancestor `relative`), neo vào chính link thì vùng bấm chỉ to bằng mấy chữ
 *  «Xem tất cả →». */
const LIEN_O =
  'ml-auto inline-flex items-center gap-1 text-[11.5px] text-ac after:absolute after:inset-0 hover:text-acd'

/** Mũi tên trượt vào lúc rê chuột — DẠY người dùng ô này dẫn đi đâu, không
 *  phải trang trí thuần (spec). Nghỉ: lùi lại + ẩn. `group-hover`: về vị trí
 *  + hiện. `motion-reduce`: hiện thẳng, không chuyển động. */
function MuiTen() {
  return (
    <span
      aria-hidden="true"
      className="inline-block -translate-x-1 opacity-0 transition-[transform,opacity] duration-200 ease-out group-hover:translate-x-0 group-hover:opacity-100 motion-reduce:translate-x-0 motion-reduce:opacity-100 motion-reduce:transition-none"
    >
      →
    </span>
  )
}

/** Span theo lưới **24 cột** (gấp đôi 12 cột gốc của demo) — người dùng chốt
 *  2026-09-08: Usage/Khách đánh giá/Chuyển sale rộng BẰNG NHAU, Hội thoại giữ
 *  NGUYÊN tỉ lệ, Kiến thức nới ra để thẳng mép với Usage. Trên lưới 12 cột
 *  gốc không chia được — Hội thoại cố định 5/12 thì hai ô còn lại của hàng 1
 *  phải bằng nhau và cộng đủ 7/12, tức 3,5 cột mỗi ô, không phải số nguyên.
 *  Nhân đôi lên 24 cột thì mọi cạnh đều rơi vào số nguyên: Hội thoại 10 (=
 *  5×2, KHÔNG đổi tỉ lệ) · Usage/Khách đánh giá/Chuyển sale đều 7 · Kiến thức
 *  17 (= 10 + 7, thẳng mép phải với Usage) · Chuyển sale 24-17=7 (thẳng mép
 *  với Khách đánh giá, cùng 7).
 *
 *  «Cần bạn» (shape 06/10): Chuyển sale về HÀNG 1 (chỗ Usage từ lượt swap 2026-09-08),
 *  Chi phí xuống hàng 2 — xếp theo mức GẤP, không theo module. Trong DOM Chuyển sale
 *  đứng ĐẦU: điện thoại (một cột) thấy nó trước tiên và Tab dừng ở nó trước (trước là
 *  điểm dừng thứ 24). Từ `md`, `hoiThoai` mang `md:-order-1` để lưới vẫn vẽ Hội thoại
 *  ở cột trái như cũ. Khoá SPAN nay đặt theo đúng component dùng nó.
 *  Dưới 1240px mọi ô về `span 12` (= nửa 24 cột, đúng bằng `span 6` cũ trên
 *  nửa 12 cột — hành vi thu gọn 2-ô-một-hàng không đổi). */
const SPAN = {
  // ⚠️ Fix round 1 (Task 6 reopened): `hoiThoai` mọc `max-md:min-h-[260px]` —
  // `BieuDoNgay` đo kích thước qua `ResizeObserver` trên một `div` mang
  // `min-h-0 flex-1` (xem `BieuDoNgay.tsx`), và trên mobile `LUOI` đổi sang
  // `max-md:auto-rows-auto` (hàng cao theo NỘI DUNG thay vì `1fr` cố định).
  // Một cột flex có chiều cao `auto` không cho một hậu duệ `flex-1` (flex-
  // basis 0%) mượn chỗ để lớn lên — đo thật trên trình duyệt: `clientHeight`
  // của `bocRef` ra 0, SVG không vẽ gì (điều kiện `W > 0 && H > 0` chặn cả
  // path). `TheDanhGia`/sparkline `OChiPhi` KHÔNG dính lỗi này
  // vì chúng không đo bằng `ResizeObserver` — SVG mang `width`/`height` cố
  // định hoặc dùng `viewBox` + `preserveAspectRatio`, không phụ thuộc chiều
  // cao đo được của cha. `min-h-[260px]` cho `<section>` (chính ô, không
  // phải `div` bọc chart) một sàn chiều cao THẬT — flex-column bên trong nó
  // (`O_CO` là `flex flex-col`) khi đó có main size đã resolve (≥260px) để
  // phân phối cho `flex-1`, nên `bocRef` nhận lại chiều cao > 0. 260 khớp số
  // đã có sẵn trong ghi chú Step 3 của brief Task 6 (không phải số tự chọn).
  hoiThoai:
    'col-span-[10] max-[1240px]:col-span-[12] max-md:col-span-full max-md:min-h-[260px] md:-order-1',
  chuyenSale: 'col-span-[7] max-[1240px]:col-span-[12] max-md:col-span-full',
  danhGia: 'col-span-[7] max-[1240px]:col-span-[12] max-md:col-span-full',
  kienThuc: 'col-span-[17] max-[1240px]:col-span-[12] max-md:col-span-full',
  chiPhi: 'col-span-[7] max-[1240px]:col-span-[12] max-md:col-span-full',
} as const

/** Lưới bento — DÙNG CHUNG cho cả ba trạng thái (skeleton/lỗi ẩn nó/nội dung
 *  thật), để hình học không lệch giữa lúc tải và lúc xong. 2 hàng đều nhau ở
 *  ≥1240px; dưới đó 3 hàng vì mọi ô đã về nửa lưới. 24 cột (không phải 12) —
 *  xem docstring `SPAN`. */
const LUOI =
  'grid min-h-0 flex-1 grid-cols-[repeat(24,minmax(0,1fr))] grid-rows-[1fr_1fr] gap-3.5 max-[1240px]:grid-rows-[repeat(3,1fr)] max-md:flex-none max-md:grid-cols-1 max-md:grid-rows-none max-md:auto-rows-auto'

/** Khung ngoài của cả màn — trừ đúng chiều cao Topbar, khoá không cuộn. */
function Khung({ children }: { readonly children: ReactNode }) {
  return (
    <div className="flex h-[calc(100dvh-72px)] flex-col overflow-hidden px-7 py-6 max-md:h-auto max-md:overflow-visible max-md:px-4 max-md:py-4">
      {children}
    </div>
  )
}

/**
 * Hàng đầu màn — ĐÚNG một dòng: kỳ mà mọi con số bên dưới nói về, và lúc số
 * được lấy về.
 *
 * `moc` được `api.ts` che chắn rất kỹ rồi bị bỏ quên suốt bản đầu (không
 * component nào đọc `.moc`), nên màn tóm tắt bảy ngày mà không nói bảy ngày
 * nào. Hai thứ của hàng này trong demo KHÔNG port sang: tiêu đề «Tổng quan»
 * (Topbar đã có) và tên workspace (cần `useSession()` — xem đầu file).
 *
 * «Cập nhật hh:mm» (critique 05/10) là `dataUpdatedAt` của `/overview` — giờ
 * trình duyệt NHẬN số, mà backend tính số lúc trả lời, nên đó đúng là «số tươi
 * tới đâu». Bản đầu bỏ nó vì lúc đó màn không tự làm mới: một đồng hồ đứng im
 * cả buổi là nói dối; nay màn làm mới mỗi 30 giây nên giờ này luôn đi. Lần làm
 * mới hỏng thì giữ số cũ và NÓI RA — không thay cả màn bằng khung lỗi.
 *
 * `khoangKy` trả `null` khi `moc` rỗng ⇒ chỉ phần «Kỳ …» biến mất.
 */
function HangDau({
  moc,
  capNhat,
  loiLamMoi,
}: {
  readonly moc: Overview['moc']
  readonly capNhat: number
  readonly loiLamMoi: boolean
}) {
  const ky = khoangKy(moc.tuNgay, moc.tinhDen)
  return (
    <p className="mb-3 flex-none text-phu text-muted-2">
      {ky !== null && (
        <>
          <span data-testid="tq-ky">
            Kỳ <b className="font-mono font-medium text-muted">{ky}</b>
          </span>
          {' · '}
        </>
      )}
      <span data-testid="tq-cap-nhat">
        Cập nhật{' '}
        <b className="font-mono font-medium text-muted">
          {gioNgan(new Date(capNhat).toISOString())}
        </b>
      </span>
      {loiLamMoi && <span className="text-badge-alert-fg"> · chưa làm mới được, sẽ thử lại</span>}
    </p>
  )
}

/**
 * Tenant chưa có gì để tóm tắt — spec §4.4: KHÔNG hiện lưới toàn số 0.
 *
 * Điều kiện là HAI vế (`hoiThoai.tong === 0` VÀ `danhGia.tong === 0`), không
 * phải một. Kho Kiến thức đếm TỒN KHO chứ không đếm theo kỳ (xem docstring
 * `doc_overview` bên backend), nên một tenant đã nạp xong 1.203 căn nhưng
 * chưa bật agent vẫn có một ô đáng xem — cắt cả lưới vì nó chưa có phiên là
 * giấu đúng thứ nó vừa làm xong. Chỉ khi cả hội thoại LẪN đánh giá đều rỗng
 * thì màn mới thật sự không có gì để tóm tắt: ô ① rỗng, ô ② là 0/0, ô ③ đã
 * tự nói «Chưa có đánh giá» — ba phần tư lưới là chỗ trống có viền.
 *
 * Ca chưa liên hệ KHÔNG theo kỳ: ca của tuần trước vẫn chờ gọi dù tuần này
 * không có phiên nào. Thẻ này thay cả lưới nên phải tự nói số đó (nguyên tắc
 * 4 của PRODUCT.md) — trước đây nó giấu luôn ô Chuyển sale.
 */
function TheDanHuong({ caCho }: { readonly caCho: number }) {
  return (
    // MỘT thẻ nền chiếm trọn chỗ của lưới, KHÔNG phải đảo nhỏ viền đứt trôi
    // giữa màn trống (bản trước, người dùng chê nhỏ + lệch concept 2026-08-21):
    // mọi màn khác đặt nội dung — kể cả trạng thái rỗng — trong một tấm nền
    // choán khung, và `/convos` đã chốt bỏ viền đứt cho khối rỗng. Cỡ chữ
    // 15/13.5px cũng lấy đúng từ khối rỗng của `/convos`, không tự đặt cỡ bé
    // hơn. `rounded-lg` + `border-border` + `bg-surface` = đúng khuôn `O_CO`
    // của các ô lưới, nên hình học không đổi hệ giữa lúc rỗng và lúc có số.
    <section
      data-testid="tong-quan-rong"
      className="flex min-h-0 flex-1 flex-col items-center justify-center rounded-lg border border-border bg-surface px-6 text-center"
    >
      <span className="grid size-11 place-items-center rounded-md border border-border bg-fill text-muted-2">
        <Icon name="convos" className="size-5" />
      </span>
      <h2 className="mt-3 text-the font-semibold">Chưa có hội thoại nào</h2>
      {/* <p className="mt-1.5 max-w-[440px] text-than leading-relaxed text-muted">
        Workspace này chưa ghi nhận phiên nào, nên chưa có gì để tóm tắt. Thử agent một lượt để xem
        số liệu bắt đầu chạy về đây.
      </p> */}
      <Link to="/thu-agent" className={`${NUT_CHINH} mt-4`}>
        Thử agent
      </Link>
      {caCho > 0 && (
        <p data-testid="tq-rong-ca-cho" className="mt-5 text-than text-muted">
          Vẫn còn <b className="font-medium text-badge-alert-fg">{so(caCho)} ca chưa liên hệ</b> từ
          trước.{' '}
          <Link to="/chuyen-sale" search={{ tab: 'new', cu: true }}>
            Xem ca
          </Link>
        </p>
      )}
    </section>
  )
}

const O_TRONG: readonly (keyof typeof SPAN)[] = [
  'chuyenSale',
  'hoiThoai',
  'danhGia',
  'kienThuc',
  'chiPhi',
]

/** `q.isPending` — 5 khung xám đúng vị trí 5 ô. TUYỆT ĐỐI không render số 0:
 *  một màn đầy số 0 trông như workspace rỗng, không như đang tải. */
function KhungDangTai() {
  return (
    <div data-testid="tong-quan-dang-tai" className={LUOI}>
      {O_TRONG.map((k) => (
        <div key={k} className={`${O_CO} ${SPAN[k]}`}>
          <div className="h-full w-full animate-pulse rounded-md bg-fill" />
        </div>
      ))}
    </div>
  )
}

/** `q.error` — thông báo + nút Thử lại, không trắng màn. */
function KhungLoi({
  thongBao,
  onThuLai,
}: {
  readonly thongBao: string
  readonly onThuLai: () => void
}) {
  return (
    <div
      data-testid="tong-quan-loi"
      className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 text-center"
    >
      <p className="text-[14px] font-medium text-fg">Không tải được tổng quan.</p>
      <p className="max-w-md text-[13px] text-muted">{thongBao}</p>
      <button type="button" onClick={onThuLai} className={NUT_CHINH}>
        Thử lại
      </button>
    </div>
  )
}

function OHoiThoai({
  className,
  hoiThoai,
  dangXem,
  doiDangXem,
}: {
  readonly className: string
  readonly hoiThoai: Overview['hoiThoai']
  readonly dangXem: number
  readonly doiDangXem: (i: number) => void
}) {
  const { tong, truoc, theoNgay, theoKenh } = hoiThoai
  // truoc <= 0 (kỳ trước không có phiên nào) ⇒ % tăng/giảm ra chia-cho-0 —
  // ẩn mũi tên delta thay vì hiện Infinity/NaN.
  const delta = truoc > 0 ? ((tong - truoc) / truoc) * 100 : null
  const tang = delta !== null && delta >= 0

  return (
    <section data-testid="o-hoi-thoai" className={`${O_CO} ${O_BAM_DUOC} ${className}`}>
      {/* «Xem tất cả →» là thứ THAY THẾ cho bảng «Cần chú ý» đã cắt (spec §6):
          ô này tóm tắt bảy ngày, và câu hỏi kế tiếp của người đọc gần như
          luôn là «phiên nào?» — không có đường này thì họ phải quay ra panel
          nav tìm lại «Hội thoại». `<Link>`, không `<a>`: xem đầu file.
          Giờ ĐỒNG THỜI là stretched-link của cả ô (`LIEN_O`) — xem docstring
          `O_BAM_DUOC`/`LIEN_O`. */}
      <div className="mb-2 flex flex-none items-baseline gap-2">
        <h2 className="text-[12px] font-semibold">Hội thoại</h2>
        <Link to="/convos" className={LIEN_O}>
          Xem tất cả <MuiTen />
        </Link>
      </div>
      <div className="flex flex-none items-baseline gap-2.5">
        <span
          data-testid="ht-tong"
          className="font-mono text-[30px] font-medium leading-none tracking-tight"
        >
          {so(tong)}
        </span>
        <span className="text-phu text-muted-2">phiên</span>
        {delta !== null && (
          <span
            className={`inline-flex items-center gap-[3px] rounded-full px-[7px] py-0.5 font-mono text-nhan ${
              tang ? 'bg-acs text-acd' : 'bg-badge-alert-bg text-badge-alert-fg'
            }`}
          >
            {tang ? '▲' : '▼'} {soLe1(Math.abs(delta))}%
          </span>
        )}
      </div>
      {/* Dòng theo kênh KIÊM chú giải: hai kênh có đường trên biểu đồ mang chấm cùng màu
          đường — trước đó màu Chat/Voice chỉ hiện trong tooltip khi rê chuột (audit 05/10,
          WCAG 1.4.1). Kênh không có đường riêng giữ chữ trần. */}
      <p
        data-testid="ht-chu-thich"
        className="mt-2 flex flex-none flex-wrap items-center gap-x-1.5 text-[11.5px] text-muted"
      >
        {theoKenh.map((k, i) => (
          <span key={k.kenh ?? 'khac'} className="inline-flex items-center gap-1">
            {i > 0 && <span aria-hidden="true">·</span>}
            {MAU_DUONG[k.kenh ?? ''] && (
              <span
                aria-hidden="true"
                className="size-2 rounded-full"
                style={{ background: MAU_DUONG[k.kenh ?? ''] }}
              />
            )}
            {tenKenh(k.kenh)} {so(k.n)}
          </span>
        ))}
      </p>
      <div className="mt-1.5 min-h-0 flex-1">
        <BieuDoNgay chuoi={theoNgay} dangXem={dangXem} doiDangXem={doiDangXem} />
      </div>
    </section>
  )
}

/** Hàng của `DsChoGoi` cao CỐ ĐỊNH — để đếm được bao nhiêu hàng vừa ô. */
const CAO_HANG_CHO = 34

/**
 * Những ca chờ lâu nhất (06/10 — ô chỉ có một con số, phần dưới trống ~270px trên
 * tenant thật). Trả lời câu kế tiếp sau «N ca chưa liên hệ»: gọi AI trước. Mỗi
 * hàng mở thẳng ca đó ở hàng đợi; `relative z-10` để nổi trên stretched-link của ô.
 *
 * Bao nhiêu hàng là do CHIỀU CAO Ô quyết (đo bằng `ResizeObserver`), không cố định:
 * cắt bằng CSS thì hàng thừa vẫn nằm trong thứ tự Tab dù không thấy. Điện thoại ô
 * cao theo nội dung nên đo ra đúng số đang vẽ — đứng ở 3. Dữ liệu là trang đầu
 * `/escalations` (≤10 ca, cũ nhất trước) đã tải cho con số — không thêm request.
 */
function DsChoGoi({ items }: { readonly items: readonly Ca[] }) {
  const [vua, setVua] = useState(3)
  const ref = useRef<HTMLUListElement>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() =>
      setVua(Math.max(1, Math.floor(el.clientHeight / CAO_HANG_CHO))),
    )
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <p className="mt-1 flex-none text-nhan text-muted-2">Chờ lâu nhất</p>
      <ul
        ref={ref}
        data-testid="cs-ds-cho"
        className="mt-1 min-h-0 flex-1 overflow-hidden max-md:flex-none"
      >
        {items.slice(0, vua).map((c) => {
          const ai = c.ten ?? c.phone ?? 'Khách chưa cho tên'
          const cho = daCho(c.taoLuc)
          return (
            <li key={c.id} style={{ height: CAO_HANG_CHO }}>
              <Link
                to="/chuyen-sale"
                search={{ tab: 'new', cu: true, ca: c.id }}
                aria-label={cho ? `${ai}, chờ ${cho}` : ai}
                className="relative z-10 -mx-2 flex h-full items-center gap-2 rounded-md px-2 text-phu text-fg transition-colors duration-150 hover:bg-fill motion-reduce:transition-none"
              >
                <span className="max-w-[60%] flex-none truncate">{ai}</span>
                <span className="min-w-0 flex-1 truncate text-muted-2">{c.tenDuAn ?? ''}</span>
                <span className="flex-none text-muted tabular-nums">{cho}</span>
              </Link>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

/**
 * Ô Chuyển sale — «Cần bạn» (shape 06/10). Mở bằng VIỆC TỒN chứ không bằng tỉ lệ:
 * nguyên tắc 4 của PRODUCT.md, ca chưa liên hệ là việc phải làm, không phải số
 * thống kê. Gauge nửa cung cũ đặt «1,3% phiên cần người thật» lên chỗ to nhất —
 * đọc như tin tốt trong lúc còn ca chưa ai gọi; nay tỉ lệ lùi xuống một dòng phụ.
 *
 * Hai nguồn, hai mốc thời gian — nhãn phải tách bạch:
 *   · số tồn + chờ lâu nhất: `/escalations` (`LOC_CHO_GOI`), HIỆN TẠI, không theo kỳ;
 *   · tỉ lệ chuyển: `/overview`, TRONG KỲ 7 ngày của nhãn đầu màn («Kỳ này …»).
 * `/escalations` hỏng thì ô vẫn còn dòng tỉ lệ; 403 (`laThieuQuyen`) thì không có
 * link — vai trò đó không mở được `/chuyen-sale`.
 *
 * Đỏ CHỈ khi còn ca chờ. Cỡ 30px là chữ lớn theo WCAG nên `badge-alert-fg` cần 3:1.
 */
function OChuyenSale({
  className,
  chuyenSale,
  cho,
}: {
  readonly className: string
  readonly chuyenSale: Overview['chuyenSale']
  readonly cho: CaChoGoi
}) {
  const { chuyen, tuXuLy } = chuyenSale
  const tong = chuyen + tuXuLy
  const khongQuyen = !cho.data && laThieuQuyen(cho.error)
  const n = cho.data?.tongCa

  const tiLe = (
    <p data-testid="cs-ti-le" className="text-phu text-muted">
      {tong > 0 ? (
        <>
          Kỳ này agent chuyển <b className="font-mono font-medium text-fg">{so(chuyen)}</b>/
          <span className="font-mono">{so(tong)}</span> phiên (
          <span className="font-mono">{soLe1((chuyen / tong) * 100)}%</span>)
        </>
      ) : (
        'Kỳ này chưa có phiên nào.'
      )}
    </p>
  )

  return (
    <section
      data-testid="o-chuyen-sale"
      className={`${O_CO} ${khongQuyen ? '' : O_BAM_DUOC} ${className}`}
    >
      <div className="mb-2 flex flex-none items-baseline gap-2">
        <h2 className="text-[12px] font-semibold">Chuyển sale</h2>
        {!khongQuyen && (
          <Link to="/chuyen-sale" search={{ tab: 'new', cu: true }} className={LIEN_O}>
            Xem ca <MuiTen />
          </Link>
        )}
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2">
        {khongQuyen ? (
          tiLe
        ) : cho.isPending ? (
          <span className="h-[30px] w-28 animate-pulse rounded bg-fill" />
        ) : n === undefined ? (
          <p className="text-than text-muted">Không tải được số ca chờ.</p>
        ) : n > 0 ? (
          <>
            <p className="flex items-baseline gap-2.5">
              <span
                data-testid="cs-cho"
                className="font-mono text-[30px] font-medium leading-none tracking-tight text-badge-alert-fg tabular-nums"
              >
                {so(n)}
              </span>
              <span className="text-than text-fg">ca chưa liên hệ</span>
            </p>
            <DsChoGoi items={cho.data?.items ?? []} />
          </>
        ) : (
          <p className="flex items-center gap-2 text-than text-muted">
            <Icon name="check" className="size-4 text-ac" />
            Không còn ca nào chờ gọi.
          </p>
        )}
      </div>
      {!khongQuyen && (
        <div className="mt-3 flex-none border-t border-border-soft pt-2.5">{tiLe}</div>
      )}
    </section>
  )
}

function ODanhGia({
  className,
  danhGia,
}: {
  readonly className: string
  readonly danhGia: Overview['danhGia']
}) {
  return (
    <section data-testid="o-danh-gia" className={`${O_CO} ${O_BAM_DUOC} ${className}`}>
      <div className="mb-2 flex flex-none items-baseline gap-2">
        <h2 className="text-[12px] font-semibold">Khách đánh giá</h2>
        <Link to="/quality" className={LIEN_O}>
          Xem đánh giá <MuiTen />
        </Link>
      </div>
      <div className="min-h-0 flex-1">
        <TheDanhGia danhGia={danhGia} />
      </div>
    </section>
  )
}

/** Hàng dữ liệu ngoài đứng cạnh các hàng kho, trước hàng kỹ năng (năng lực, không phải kho). */
function chenTruocKyNang(muc: readonly MucKienThuc[], them: MucKienThuc): readonly MucKienThuc[] {
  const i = muc.findIndex((m) => m.khoa === 'kyNang')
  return i < 0 ? [...muc, them] : [...muc.slice(0, i), them, ...muc.slice(i)]
}

function OKienThuc({
  className,
  muc,
}: {
  readonly className: string
  readonly muc: Overview['kienThuc']['muc']
}) {
  const ngoai = useQuery({ queryKey: KHOA_HO_SO_NGOAI, queryFn: hoSoNgoai, retry: false })
  const hang = ngoai.data && ngoai.data.tong > 0 ? chenTruocKyNang(muc, ngoai.data) : muc
  return (
    <section data-testid="o-kien-thuc" className={`${O_CO} ${O_BAM_DUOC} ${className}`}>
      <div className="mb-2 flex flex-none items-baseline gap-2">
        <h2 className="text-[12px] font-semibold">Kiến thức</h2>
        {/* Nhãn «Quản lý →» — đúng chữ demo dùng (`docs/design/demo-tong-quan.html`
            khối ⑤), không tự đặt tên khác. */}
        <Link to="/projects" className={LIEN_O}>
          Quản lý <MuiTen />
        </Link>
      </div>
      <div className="min-h-0 flex-1">
        <TheKienThuc muc={hang} />
      </div>
    </section>
  )
}

/**
 * Ô Chi phí — một đích (`/billing`), cùng kiểu cả-ô-bấm-được với bốn ô kia
 * (shape 06/10). Trước đó là ô «Usage & Billing» hai tile (Chi phí → `/billing`,
 * Lượng dùng → `/usage`) đứng giữa hàng 1; người dùng chốt hạ xuống hàng 2 và BỎ
 * phần token: màn buổi sáng trả lời «có gì cần tôi can thiệp», token in/out/cache
 * không dẫn tới việc gì ở đây — `/usage` vẫn ở nav.
 *
 * "Gói cước" (hạn mức/hoá đơn) vẫn KHÔNG có chỗ ở ô này — ba lý do review round 3
 * 2026-08-20 còn nguyên: `/billing` hiện đã tiêu bao nhiêu chứ không hiện gói nào,
 * `/pricing` gác bằng token quản trị nền tảng, và portal chưa có màn hoá đơn.
 *
 * ⚠️ KỲ KHOÁ VÀO "THÁNG NÀY" (2026-08-28) — `giaiMaKy('thang-nay')`, đúng tab mặc
 * định của `/billing`, KHÔNG theo kỳ 7 ngày của nhãn đầu màn: kỳ 7 ngày gần như
 * luôn trống hoạt động nên sparkline phẳng trong khi `/billing` đầy biến động.
 * Người dùng chốt, và CHỦ Ý không thêm chú thích phân biệt hai kỳ.
 *
 * Sparkline là BIỂU ĐỒ THẬT — `SparklineChiPhi` nguyên vẹn của `/billing`, cùng
 * nguồn cùng kỳ; `caoPx` 22 (18 phẳng quá, 30 mặc định cao quá cho ô này).
 */
function OChiPhi({ className }: { readonly className: string }) {
  const { from, to } = giaiMaKy('thang-nay')
  const q = useTongQuan(from, to)
  const data = q.error ? undefined : q.data
  const gon = data ? tienGon(data.chi_phi) : null

  return (
    <section data-testid="o-chi-phi" className={`${O_CO} ${O_BAM_DUOC} ${className}`}>
      <div className="mb-2 flex flex-none items-baseline gap-2">
        <h2 className="text-[12px] font-semibold">Chi phí</h2>
        <Link to="/billing" search={{ ky: 'thang-nay', gop: 'khoa', trang: 1 }} className={LIEN_O}>
          Xem chi phí <MuiTen />
        </Link>
      </div>
      <div className="flex min-h-0 flex-1 flex-col">
        {q.isPending ? (
          <span className="h-[30px] w-28 animate-pulse rounded bg-fill" />
        ) : data && gon ? (
          <>
            {/* Số RÚT GỌN (`tienGon`): số đầy đủ cỡ 30px tràn ô từ 8 chữ số. Bậc
                «triệu/tỷ» đứng cùng đơn vị tiền ở cỡ nhỏ; số đầy đủ ở `title`. */}
            <span className="flex flex-wrap items-baseline gap-x-1">
              <span
                title={`${tien(data.chi_phi)} ${data.currency}`}
                className={`whitespace-nowrap font-mono ${gon.so.length > 7 ? 'text-[22px]' : 'text-[30px]'} font-medium leading-none tracking-tight text-fg tabular-nums`}
              >
                {gon.so}
              </span>
              <span className="whitespace-nowrap font-mono text-nhan text-muted-2">
                {gon.hau ? `${gon.hau} ${data.currency}` : data.currency}
              </span>
            </span>
            <SparklineChiPhi from={from} to={to} caoPx={22} />
            <p className="mt-1.5 text-nhan text-muted-2">
              {so(data.so_phien)} phiên · {so(data.so_key)} khoá đang dùng
            </p>
            <TopDichVu
              from={from}
              to={to}
              toiDa={6}
              className="mt-3 grid min-h-0 flex-1 auto-rows-[0px] overflow-hidden grid-rows-[repeat(auto-fill,38px)] max-md:flex-none max-md:auto-rows-auto max-md:grid-rows-none"
            />
          </>
        ) : (
          <span className="font-mono text-[22px] leading-none text-muted-2">—</span>
        )}
      </div>
    </section>
  )
}

function NoiDungTongQuan({
  data,
  cho,
  dangXem,
  doiDangXem,
}: {
  readonly data: Overview
  readonly cho: CaChoGoi
  readonly dangXem: number | null
  readonly doiDangXem: (i: number) => void
}) {
  const { hoiThoai, chuyenSale, danhGia, kienThuc } = data
  // State khởi tạo `chuoi.length - 1` (HÔM NAY) — giữ ở `null` cho tới khi
  // người dùng bấm/rê chuột, rồi suy ra mặc định tại đây, vì lúc component
  // này CHƯA render thì độ dài `theoNgay` chưa biết (xem `TongQuanScreen`).
  const dangXemThuc = dangXem ?? hoiThoai.theoNgay.length - 1

  if (hoiThoai.tong === 0 && danhGia.tong === 0) {
    return <TheDanHuong caCho={cho.data?.tongCa ?? 0} />
  }

  // Thứ tự DOM = thứ tự mức gấp (Chuyển sale đầu) — xem docstring `SPAN`.
  return (
    <div className={LUOI}>
      <OChuyenSale className={SPAN.chuyenSale} chuyenSale={chuyenSale} cho={cho} />
      <OHoiThoai
        className={SPAN.hoiThoai}
        hoiThoai={hoiThoai}
        dangXem={dangXemThuc}
        doiDangXem={doiDangXem}
      />
      <ODanhGia className={SPAN.danhGia} danhGia={danhGia} />
      <OKienThuc className={SPAN.kienThuc} muc={kienThuc.muc} />
      <OChiPhi className={SPAN.chiPhi} />
    </div>
  )
}

export function TongQuanScreen() {
  const q = useQuery({
    queryKey: KHOA_OVERVIEW,
    queryFn: overview,
    refetchOnWindowFocus: true,
    refetchInterval: LAM_MOI_MS,
  })
  // Gọi SONG SONG với `/overview` (ở đây, trước mọi nhánh trả sớm), không chờ nó.
  const cho = useQuery({
    queryKey: ['escalations', LOC_CHO_GOI],
    queryFn: () => danhSachCa(LOC_CHO_GOI),
    refetchOnWindowFocus: true,
    // 403 thì hỏi lại mỗi 30 giây cũng vẫn 403.
    refetchInterval: (qr) => (laThieuQuyen(qr.state.error) ? false : LAM_MOI_MS),
  })
  const [dangXem, setDangXem] = useState<number | null>(null)

  if (q.isPending) {
    return (
      <Khung>
        <KhungDangTai />
      </Khung>
    )
  }

  // Chỉ khi CHƯA từng có số. Lần làm mới (focus/30 giây) hỏng thì `q.data` vẫn là
  // số cũ và `q.error` có giá trị — thay cả màn bằng khung lỗi lúc đó là xoá thứ
  // người dùng đang đọc vì một nhịp mạng; `HangDau` báo «chưa làm mới được».
  if (!q.data) {
    return (
      <Khung>
        <KhungLoi
          thongBao={q.error instanceof Error ? q.error.message : 'Lỗi không rõ'}
          onThuLai={() => void q.refetch()}
        />
      </Khung>
    )
  }

  return (
    <Khung>
      <HangDau moc={q.data.moc} capNhat={q.dataUpdatedAt} loiLamMoi={q.isRefetchError} />
      <NoiDungTongQuan data={q.data} cho={cho} dangXem={dangXem} doiDangXem={setDangXem} />
    </Khung>
  )
}
