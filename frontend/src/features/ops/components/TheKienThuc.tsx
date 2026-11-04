/**
 * Ô ⑤ màn Tổng quan — năm HÀNG, mỗi hàng một thước khắc vạch cho biết agent
 * đọc được bao nhiêu phần của kho (và bật bao nhiêu phần năng lực của nó).
 *
 * PORT nguyên bố cục/số đo/thước khắc vạch từ `docs/design/demo-tong-quan.html`
 * § `/* ── ⑤ Kiến thức` (CSS) + `/* ══ ⑤ KIẾN THỨC` (JS) — không thiết kế lại.
 *
 * VÌ SAO HÀNG + THƯỚC KHẮC VẠCH, không phải năm ô có thanh bo tròn: ô ③
 * Khách đánh giá đã dùng thanh bo tròn ĐẶC cho phân bố sao, và hai ô nằm
 * cùng một màn. Cùng một hình thì mắt đọc ra CÙNG một loại số, trong khi
 * một bên là phân bố phiếu còn bên kia là độ phủ kho dữ liệu. Thước 14 nấc
 * RỜI còn đọc được giá trị thô ("11 trên 14 vạch") khi in đen trắng — thứ
 * thanh đặc không cho.
 *
 * Thước tô MỘT sắc (`--color-ac`) mờ dần về đầu, KHÔNG xanh/vàng/đỏ theo
 * mức: độ phủ là đại lượng liên tục, thang liên tục thì một sắc chuyển đậm
 * nhạt. Màu trạng thái (viên nhãn bên phải) để dành cho nơi nó đi kèm CHỮ.
 *
 * TOOLTIP mỗi hàng (round fix 2026-08-14) — bị bỏ sót ở đợt review tooltip
 * ô ① trước đó. PORT nội dung từ demo § `gan(n, ...)` của khối ⑤ (bản đã
 * duyệt), dùng khung `HopTip`/`useTip` chung tách từ `BieuDoNgay.tsx`
 * (`./Tip.tsx`) — ô ① là người dùng đầu, ô này là người dùng thứ hai.
 *
 * Tip của «Dự án» đã VIẾT LẠI so với demo, không PORT nguyên văn: demo nói
 * view `agent_api` lọc `published` — view đó đã BỎ HẲN (migration `0917`, xem
 * CLAUDE.md backend mục "agent_api đã bỏ hoàn toàn"). Agent giờ đọc thẳng
 * `tenant_data`, lọc `status='published'` là việc của bên đọc chứ không còn
 * view nào làm hộ. Giữ Ý NGHIỆP VỤ (agent không thấy bản nháp), bỏ tham
 * chiếu `agent_api`.
 *
 * MỖI HÀNG LÀ `<Link>` TỚI ĐÚNG MÀN QUẢN LÝ THỨ NÓ ĐẾM (`DICH`). Hai bước:
 * hàng thành `<Link>` (round fix 2026-08-14) vì ô cha (`OKienThuc`) mang một
 * stretched-link «Quản lý →» phủ trọn ô — chỉ nâng `z-index` cho hàng mà
 * không cho nó điều hướng thì bấm vào hàng KHÔNG có gì xảy ra trong khi bấm
 * chỗ khác của ô lại đi; rồi sáu đích-giống-nhau tách thành đích RIÊNG (cùng
 * ngày, sau phản hồi người dùng): hover tô sáng TỪNG hàng là một lời hứa về
 * sáu đường đi khác nhau, giao đúng một `/projects` cho cả sáu là nuốt lời
 * ngay tại chỗ vừa hứa. Là `<Link>` thật thì được cả chuột giữa/Ctrl+click/mở
 * tab mới — thứ một `onClick` tự viết không cho. `relative z-10` để hàng vẽ
 * TRÊN lớp phủ của ô cha (không thì lớp phủ nuốt mất tooltip/focus của hàng).
 * `tabIndex={0}` cũ BỎ — `<Link>` tự tabbable, giữ lại là dư một bậc tab.
 *
 * HAI HÀNG ĐÃ BỎ (2026-08-14, người dùng chốt): «Hồ sơ đủ trường» và «Tài
 * liệu dự án» (kho `documents`, gõ tay trong tab «Tài liệu» của `/pform`).
 * Thay bằng «Kỹ năng agent», và hàng tài liệu còn lại đổi NGUỒN sang kho
 * `/kb` (`kb_files`) — xem `NHAN.taiLieuTraCuu`. Cột SQL nguồn (`tai_lieu_*`
 * từ `documents`, `ho_so_du_truong_*`) đã gỡ hẳn khỏi `repo.kien_thuc`, không
 * chỉ ẩn ở FE: cần dựng lại thì đọc backend trước.
 */
import { Link } from '@tanstack/react-router'
import { Icon, type IconName } from '@/components/icons'
import type { MucKienThuc } from '../api'
import { so } from '@/lib/dinhDang'
import { DongTip, GhiChuTip, HopTip } from './Tip'
import { useTip } from './useTip'

const NAC = 14

/**
 * Lời của MỘT hàng. Bốn mục kho dùng nguyên bộ mặc định (`LOI_KHO`); `kyNang`
 * khai đè cả ba câu vì nó đếm NĂNG LỰC agent, không đếm hiện vật trong kho —
 * để nguyên «Agent đọc đủ»/«Tổng trong kho» cho một hàng kỹ năng là bịa ra
 * một cái kho không tồn tại, đúng kiểu nói sai mà cả ô này sinh ra để tránh.
 */
interface Loi {
  /** Nhãn dòng `thay` trong tooltip. */
  readonly thay: string
  /** Nhãn dòng `tong` trong tooltip. */
  readonly tong: string
  /** Viên nhãn bên phải khi ĐẦY. */
  readonly du: string
  /** Viên nhãn khi hụt — nhận sẵn phần thiếu đã định dạng. */
  readonly thieu: (n: string) => string
}

const LOI_KHO: Loi = {
  thay: 'Agent đọc được',
  tong: 'Tổng trong kho',
  du: 'Agent đọc đủ',
  thieu: (n) => `${n} chưa đọc được`,
}

/**
 * Bảng nhãn tra theo `khoa`. Ba dòng đầu ghi «đã phát hành» GIỐNG HỆT NHAU
 * có chủ ý — cột `dk` nói ĐÚNG cái lọc SQL đang chạy (`status = 'published'`
 * cho cả ba bảng), ba dòng trùng nhau chính là thông tin: «ba mục này cùng
 * một luật». `can` KHÔNG ghi «còn mở bán» (bản demo có, nhưng SQL không lọc
 * theo `sale_status` — câu đó nói một điều kiện không tồn tại).
 */
const NHAN: Readonly<
  Record<
    string,
    { readonly ten: string; readonly dk: string; readonly icon: IconName; readonly loi?: Loi }
  >
> = {
  // Icon chọn theo NGHĨA, không theo "có sẵn để tsc không đỏ" (lỗi review đã
  // bắt 2026-08-13): toà nhà = dự án · lưới ô = các phân khu trên mặt bằng ·
  // cửa mở = một căn/sản phẩm · tài liệu = kb · con bot = chính agent, và
  // cũng đúng mark của màn `/agent` mà hàng này dẫn tới.
  duAn: { ten: 'Dự án', dk: 'đã phát hành', icon: 'projects' },
  phanKhu: { ten: 'Phân khu', dk: 'đã phát hành', icon: 'dashboard' },
  can: { ten: 'Căn / sản phẩm', dk: 'đã phát hành', icon: 'can' },
  // Tên + icon KHỚP NGUYÊN mục nav `/kb` (`features/kb/nav.ts`) — hàng này
  // đếm `kb_files`, tức đúng nội dung màn nó dẫn tới. ĐỪNG đổi thành «Tài
  // liệu dự án»: đó là kho KIA (`documents`, gõ tay trong tab «Tài liệu» của
  // `/pform`, agent đọc bằng `get_document`), và một lần lẫn hai kho đã làm ô
  // này hiện 6/6 trong lúc `/kb` trống trơn (2026-08-14). Tên đổi «Tài liệu
  // tra cứu» → «Tài liệu chung» (2026-08-28, chủ dự án chốt, đổi hiển thị
  // thôi) — khoá `taiLieuTraCuu` (khớp `overview.kienThuc` backend trả) GIỮ
  // NGUYÊN, đổi nó là đổi một API đang chạy để đổi lấy lợi ích bằng không.
  taiLieuTraCuu: { ten: 'Tài liệu chung', dk: 'đã nhúng vector', icon: 'kb' },
  // Khớp mục nav `/du-lieu-ngoai`. Đếm DỰ ÁN có hồ sơ web, không đếm bài báo.
  duLieuNgoai: {
    ten: 'Dữ liệu ngoài',
    dk: 'dự án có hồ sơ',
    icon: 'duLieuNgoai',
    loi: {
      thay: 'Có hồ sơ',
      tong: 'Dự án đã phát hành',
      du: 'Đủ hồ sơ',
      thieu: (n) => `${n} chưa có hồ sơ`,
    },
  },
  kyNang: {
    ten: 'Kỹ năng agent',
    dk: 'đang bật',
    icon: 'agent',
    loi: {
      thay: 'Đang bật',
      tong: 'Tổng kỹ năng',
      du: 'Đã bật đủ',
      thieu: (n) => `${n} chưa bật`,
    },
  },
}

/**
 * Đích điều hướng của từng hàng — mỗi hàng đi tới MÀN QUẢN LÝ đúng thứ nó
 * đếm, xem docstring đầu file.
 *
 * Khoá LẠ (backend thêm mục mới trước khi FE kịp khai) rơi về `/projects`
 * chứ không `undefined` — `<Link to={undefined}>` ném, và một hàng không
 * `href` là vùng bấm chết nằm giữa các hàng bấm được.
 */
const DICH: Readonly<Record<string, '/projects' | '/kb' | '/agent' | '/du-lieu-ngoai'>> = {
  duAn: '/projects',
  phanKhu: '/projects',
  can: '/projects',
  taiLieuTraCuu: '/kb',
  duLieuNgoai: '/du-lieu-ngoai',
  kyNang: '/agent',
}

/**
 * Chú thích chân tooltip — CHỈ ba mục có lời giải thích thêm; hai mục còn lại
 * (`phanKhu`, `can`) không có gì hơn ngoài hai dòng số nên không tra trong
 * bảng này. Tĩnh theo `khoa`, không phải dữ liệu backend — đây là lời giải
 * thích CƠ CHẾ, không phải một con số của một workspace.
 */
const GHI_CHU: Readonly<Record<string, string>> = {
  // Viết lại so với demo: demo dẫn view `agent_api` — view đó đã bỏ hẳn
  // (migration `0917`). Giữ nguyên Ý NGHIỆP VỤ, bỏ chi tiết kỹ thuật đã sai.
  duAn: 'Agent chỉ đọc dự án đã phát hành. Dự án còn nháp thì agent trả lời «chưa có thông tin» khi khách hỏi đúng dự án đó.',
  // Viết lại so với demo: bỏ câu "Cả 38 tệp đã nhúng xong" — đó là số của dữ
  // liệu giả trong demo, component này nhận dữ liệu thật nên không nhúng một
  // con số cụ thể vào văn bản tĩnh.
  taiLieuTraCuu:
    'Tệp phải bóc chữ → chia đoạn → nhúng vector xong thì kỹ năng «Tra tài liệu» mới đọc được.',
  // Không có trong demo (hàng này mới) — nói đúng một điều người xem không
  // suy ra được từ hai con số: kho đủ dữ liệu vẫn không cứu được kỹ năng tắt.
  duLieuNgoai:
    'Hồ sơ tổng hợp từ báo chí công khai về hạ tầng, tiện ích, quy hoạch quanh dự án. Dự án chưa có hồ sơ thì agent chỉ trả lời từ tài liệu của bạn.',
  kyNang:
    'Kỹ năng tắt thì agent không làm được việc đó, dù kho đã có đủ dữ liệu. Số này tính theo bản cấu hình đã «Lưu và áp dụng».',
}

/**
 * Số nấc đã đạt. Chỉ tô đủ `NAC` nấc khi THẬT SỰ 100% (`thay === tong`) —
 * làm tròn lên ở 13,6/14 sẽ vẽ ra một thước ĐẦY cho một kho còn thiếu, đúng
 * kiểu nói dối mà cả ô này sinh ra để tránh. `tong === 0` không rơi vào
 * nhánh chia — trả 0 nấc tường minh, tránh `NaN`.
 */
function soNacDaDat(thay: number, tong: number): number {
  if (tong <= 0) return 0
  if (thay === tong) return NAC
  return Math.min(NAC - 1, Math.round((thay / tong) * NAC))
}

function Thuoc({ thay, tong }: { readonly thay: number; readonly tong: number }) {
  const day = soNacDaDat(thay, tong)
  return (
    <span className="flex items-center gap-[3px]">
      {Array.from({ length: NAC }, (_, i) => {
        const dat = i < day
        return (
          <i
            key={i}
            data-testid={dat ? 'kt-nac-day' : undefined}
            className="h-4 w-[3px] rounded-mark"
            style={{
              background: dat ? 'var(--color-ac)' : 'var(--color-fill-strong)',
              opacity: dat ? 0.4 + 0.6 * (day === 1 ? 1 : i / (day - 1)) : 1,
            }}
          />
        )
      })}
    </span>
  )
}

function Hang({ m }: { readonly m: MucKienThuc }) {
  const nhan = NHAN[m.khoa] ?? { ten: m.khoa, dk: '', icon: 'kb' as const }
  const loi = nhan.loi ?? LOI_KHO
  const day = m.thay === m.tong && m.tong > 0
  const pc = m.tong > 0 ? Math.round((m.thay / m.tong) * 100) : 0
  const ghiChu = GHI_CHU[m.khoa]
  // `useTip()` mọc một state độc lập cho MỖI hàng — mỗi hàng chỉ cần biết vị
  // trí tooltip của chính nó, không có "hàng đang xem" nào cần đồng bộ chung
  // như dải crosshair của ô ① (`i` truyền vào luôn là `0`, primitive không
  // đọc lại giá trị này ở đây).
  const { tip, taiChuot, taiTieuDiem, an } = useTip()

  return (
    <Link
      to={DICH[m.khoa] ?? '/projects'}
      data-testid={`kt-hang-${m.khoa}`}
      data-khoa={m.khoa}
      // Hàng phải FOCUS ĐƯỢC bằng bàn phím — nếu không, tooltip là thông tin
      // chỉ chuột mới với tới, đúng cái bệnh mà tooltip ô ① đã chữa. `<Link>`
      // tự tabbable (bỏ `tabIndex` viết tay — xem docstring đầu file).
      onMouseMove={(e) => taiChuot(0, e)}
      onMouseLeave={an}
      onFocus={(e) => taiTieuDiem(0, e.currentTarget)}
      onBlur={an}
      // `text-fg` CỐ Ý — luật toàn cục `a { color: var(--color-ac) }` (theme.css)
      // ăn vào hàng này vì nó vừa đổi thành `<Link>` (tác dụng phụ của kỹ
      // thuật, không phải quyết định thiết kế): "Dự án"/"Phân khu"/… đều lên
      // xanh accent, kéo hết chú ý về cột tên trong khi thông tin chính của
      // hàng là con số + thước. Bốn link «đầu ô» (Xem tất cả/Xem phiên/Xem
      // đánh giá/Quản lý) GIỮ accent — chúng là nhãn HÀNH ĐỘNG thật. Sáu hàng
      // này là DỮ LIỆU, không phải hành động, nên về `fg` trung tính.
      // `text-fg` đặt trên chính `<a>` thắng luật toàn cục nhờ specificity
      // class > element, và `color` kế thừa xuống nên `nhan.ten` (không có
      // class màu riêng) cũng về `fg` theo — mọi span khác đã tự khai màu
      // riêng (`text-muted-2`, `text-fg`, `text-acd`/`text-badge-warn-fg`…)
      // nên không đổi.
      // Lưới 7 cột cần tối thiểu ~548px, mà ô này chỉ rộng thế khi màn ≥1240px
      // (dưới đó ô chiếm nửa lưới, còn 280–360px) — `overflow-hidden` của ô cha
      // CẮT mất cột phải thay vì tràn, nên không phép đo tràn ngang nào thấy.
      // Hai bố cục hẹp, vì hai chỗ hẹp khác nhau ở CHIỀU CAO:
      // - mobile (`max-md`): ô cao theo nội dung ⇒ hai dòng — tên · số · % trên,
      //   thước · nhãn dưới.
      // - từ `md` mà hàng < 560px (container query ở lưới cha — rẽ theo bề rộng
      //   CỦA HÀNG, không theo viewport): ô cao CỐ ĐỊNH theo lưới màn, năm hàng
      //   hai dòng không vừa ⇒ một dòng icon · tên · số · %, bỏ thước + nhãn
      //   (cùng thông tin với số/%; chi tiết còn ở tooltip — tầng này có chuột).
      //   Ô ở dải này chỉ chừa ~23px mỗi hàng nên hộp icon co 30 → 20px, không
      //   thì nó chồng lên hàng dưới.
      // Cả hai bỏ cột điều kiện (chữ phụ).
      // Template là class chứ không `style`: inline style thắng mọi biến thể.
      className="relative z-10 grid min-w-0 grid-cols-[30px_minmax(104px,1fr)_minmax(0,1.15fr)_78px_auto_46px_148px] items-center gap-3 rounded-md border border-border bg-fill px-3 text-fg no-underline transition-colors hover:border-border-strong hover:bg-acs-manh max-md:grid-cols-[30px_minmax(0,1fr)_auto_40px] max-md:gap-x-2.5 max-md:gap-y-1.5 max-md:py-2 md:@max-[560px]:grid-cols-[30px_minmax(0,1fr)_auto_40px] md:@max-[560px]:gap-x-2.5"
    >
      <span className="grid size-[30px] place-items-center rounded-sm border border-border bg-surface max-md:row-span-2 md:@max-[560px]:size-5">
        <Icon name={nhan.icon} width={14} height={14} className="text-muted" />
      </span>
      <span className="overflow-hidden truncate text-phu">{nhan.ten}</span>
      <span className="overflow-hidden truncate text-[11.5px] text-muted-2 max-md:hidden md:@max-[560px]:hidden">
        {nhan.dk}
      </span>
      <span className="whitespace-nowrap text-right font-mono text-[11.5px] text-muted-2">
        <b className="font-medium text-fg">{so(m.thay)}</b> / {so(m.tong)}
      </span>
      <span className="max-md:col-start-2 max-md:row-start-2 md:@max-[560px]:hidden">
        <Thuoc thay={m.thay} tong={m.tong} />
      </span>
      <span className="text-right font-mono text-phu tracking-tight max-md:col-start-4 max-md:row-start-1">
        {pc}%
      </span>
      <span
        className={`inline-flex max-w-full items-center gap-1.5 justify-self-start overflow-hidden rounded-full py-1 pl-2 pr-2.5 text-[11.5px] whitespace-nowrap text-ellipsis max-md:col-span-2 max-md:col-start-3 max-md:row-start-2 max-md:justify-self-end md:@max-[560px]:hidden ${
          day ? 'bg-acs text-acd' : 'bg-badge-warn-bg text-badge-warn-fg'
        }`}
      >
        <i className={`size-1.5 flex-none rounded-full ${day ? 'bg-ac' : 'bg-badge-warn-fg'}`} />
        {day ? loi.du : loi.thieu(so(m.tong - m.thay))}
      </span>

      {tip && (
        <HopTip x={tip.x} y={tip.y} testId="kt-tip">
          <div className="mb-[5px] text-[11.5px] font-semibold">{nhan.ten}</div>
          <DongTip ten={loi.thay} gia={so(m.thay)} />
          <DongTip ten={loi.tong} gia={so(m.tong)} />
          {ghiChu && <GhiChuTip>{ghiChu}</GhiChuTip>}
        </HopTip>
      )}
    </Link>
  )
}

interface Props {
  readonly muc: readonly MucKienThuc[]
}

export function TheKienThuc({ muc }: Props) {
  // Cộng gộp theo MỤC, không lấy trung bình năm tỉ lệ — trung bình cho «dự
  // án» (12 mục) sẽ cùng trọng số với «căn» (1.203 mục), sai về nghiệp vụ.
  const a = muc.reduce((s, m) => s + m.thay, 0)
  const b = muc.reduce((s, m) => s + m.tong, 0)
  const pcTong = b > 0 ? Math.round((a / b) * 100) : 0

  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <p className="flex items-baseline gap-2.5 text-phu text-muted">
        {/* Câu phụ «Những gì agent dùng để trả lời khách» đã BỎ (người dùng
            chốt 2026-09-29, cùng lượt bỏ phụ đề của mọi ô Tổng quan) — còn
            đúng dòng tổng. Dòng tổng nói «đã sẵn sàng» thay vì «agent đọc
            được» vì hàng kỹ năng thì agent BẬT chứ không ĐỌC. */}
        <b
          data-testid="kt-tong"
          className="text-[12px] font-medium tracking-tight font-mono text-fg"
        >
          {so(a)}{' '}
          <i className="font-normal not-italic text-muted-2">
            / {so(b)} mục · {pcTong}% đã sẵn sàng
          </i>
        </b>
      </p>
      <div className="@container grid min-h-0 flex-1 auto-rows-fr gap-1.5">
        {muc.map((m) => (
          <Hang key={m.khoa} m={m} />
        ))}
      </div>

      {/* Bảng số cho trình đọc màn hình — cùng lối với `BieuDoNgay.tsx` (ô ①).
          Tooltip chỉ mở bằng chuột/tiêu điểm; đoạn chú thích cơ chế của ba
          mục (`GHI_CHU`) không hiện ở đâu khác trên hàng, nên không có đoạn
          này thì trình đọc màn hình không tới được nó bằng bất kỳ đường nào. */}
      <p className="sr-only">
        Bảng dữ liệu theo mục:{' '}
        {muc
          .map((m) => {
            const n = NHAN[m.khoa]
            const loi = n?.loi ?? LOI_KHO
            const ghiChu = GHI_CHU[m.khoa]
            return (
              `${n?.ten ?? m.khoa} — ${loi.thay.toLowerCase()} ${so(m.thay)} trên tổng ${so(m.tong)}` +
              (ghiChu ? `. ${ghiChu}` : '')
            )
          })
          .join('; ')}
      </p>
    </div>
  )
}
