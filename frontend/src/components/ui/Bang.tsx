/**
 * Diện mạo dùng chung của MỌI bảng trong portal — dự án · phân khu · căn · tài
 * liệu (M4) và người dùng (M2b).
 *
 * ⚠️ FILE NÀY TRƯỚC Ở `features/realestate/components/Bang.tsx`. Chuyển ra
 * `components/` vì `features/auth` cũng cần nó, và `tests/module-boundaries.test.ts`
 * (Luật 3) cấm một module import ruột module khác — đúng như vậy: hai module
 * không được dính nhau chỉ vì chung một cái viền. Docstring của
 * `features/realestate/components/OTruong.tsx` đã dặn trước chỗ này. (Shim
 * `export *` ở chỗ cũ đã gỡ 2026-10-06 — realestate import thẳng từ đây.)
 *
 * VÌ SAO MỘT MODULE: năm bảng có cùng một hình dạng (thẻ trắng bo góc, dải công
 * cụ trên, vùng cuộn ở giữa, `thead` dính, hàng bấm được). Chép class vào từng
 * file là năm chỗ phải sửa mỗi lần đổi một sắc độ, và cái thứ năm luôn là cái bị
 * quên — nhìn thấy ngay: cùng một portal mà bảng này kẻ đậm hơn bảng kia.
 *
 * Token lấy từ `odyssey-dashboard-prototype/design/Tenant Portal.dc.html`, khối
 * `data-s="projects"`.
 *
 * BA MÃ MÀU TRƯỚC VIẾT THẲNG (`#ecebe7` · `#fafaf8` · `#f2f1ee`) giờ đã có tên
 * trong `styles/theme.css` (`fill-strong` · `fill` · `rule`) — nợ mà docstring
 * này hẹn dọn đã dọn xong, không còn mã màu nào trong tệp.
 *
 * BO GÓC theo thang khoá 3 bậc của `theme.css`: nút nhỏ trong hàng = `sm`(6px)
 * · ô nhập/nút/tab = `md`(8px) · thẻ bọc bảng = `lg`(12px) · pill = `full`.
 *
 * ⚠️ Viết ĐỦ CHUỖI cho biến thể `hover:`, không ghép `hover:${NEN_HEAD}`:
 * Tailwind 4 quét văn bản nguồn, nên class dựng bằng nội suy không có trong CSS
 * xuất ra và hiệu ứng mất im lặng — không có lỗi nào để lần.
 */
import type { KeyboardEvent as PhimReact, ReactNode } from 'react'
import { Icon, type IconName } from '@/components/icons'
import { idTab } from './panelTab'

/**
 * Hàng nút hành động — MỘT khuôn cho cả portal (chốt 2026-08-08).
 *
 * `justify-end` (căn PHẢI) + **nút chính đứng CUỐI**. Vị trí cuối cùng bên phải
 * là chỗ mắt dừng lại, và nó phải là hành động xác nhận — đó đã là khuôn của cả
 * 5 hộp thoại trong portal (`LuuApDung` · `TaoKhoa` · `ThuHoiKhoa` · `KhoaMoi` ·
 * `TaoWorkspace`), nên form trong trang đi theo là hết chuyện hai khuôn.
 *
 * Trước đó portal có 12 hàng nút căn trái (5 form + 7 hộp xác nhận inline) và 5
 * hộp thoại căn phải: chuyển màn là nút nhảy sang bên kia và mắt phải đi tìm
 * lại. Dùng hằng này cho MỌI hàng nút mới; muốn thêm khoảng cách trên thì ghép
 * `mt-*`, đừng khai lại `flex … gap-*`.
 *
 * Chữ xác nhận ngắn («Đã lưu.», «Đã áp dụng vN») đi TRƯỚC cụm nút — nó là kết
 * quả của lần bấm trước, không phải một hành động.
 */
export const HANG_NUT = 'flex flex-wrap items-center justify-end gap-2'

/**
 * `HANG_NUT` DÁN ĐÁY — biến thể riêng, KHÔNG đổi `HANG_NUT` gốc.
 *
 * `HANG_NUT` có 53 chỗ dùng ở nhiều feature; làm nó sticky là làm mọi form trong
 * app dán đáy. Chỉ những form dài của `/pform` cần điều đó (spec 2026-08-21
 * issue 7: «các nút này nên cố định, chỉ cuộn thông tin thôi»).
 *
 * Nền đục + viền trên là bắt buộc, không trang trí: một hàng nút trong suốt nằm
 * trên nội dung đang cuộn thì chữ chạy xuyên qua nút.
 *
 * ⚠️ KHÔNG `-mx-4` (bỏ 2026-08-21). Hàng này nằm trong vùng `overflow-y-auto`, mà
 * `overflow-y: auto` ép trục x thành `auto` theo spec — nên 16px lề âm mỗi bên
 * sinh một THANH CUỘN NGANG cho cả vùng, ở mọi tab.
 */
export const HANG_NUT_DAN =
  'sticky bottom-0 z-10 mt-auto flex flex-nowrap items-center justify-end gap-2 overflow-hidden border-t border-border-strong bg-surface px-4 py-2.5'

/**
 * Đường về («‹ <đích>») — MỘT hình dạng cho mọi cấp (chốt 2026-08-08).
 *
 * Sắc `muted`, 13px, KHÔNG accent: đường về không phải hành động chính của màn.
 * Tô accent thì nó hút mắt trước cả tiêu đề bản ghi mà nó đứng cạnh — và một màn
 * có thể có HAI đường về lồng nhau (form dự án → «‹ Kiến thức», form phân khu
 * bên trong → «‹ Danh sách phân khu»), lúc đó cái trong đậm hơn cái ngoài là nói
 * ngược thứ bậc.
 *
 * Hằng chứ không phải một component: ba chỗ dùng ba THẺ khác nhau — `<Link>`
 * (đổi route), `<button>` gọi `nav()` (đổi search param), `<button>` chỉ đóng một
 * form inline (KHÔNG đổi URL, nên một `<a>` ở đó là lời hứa sai). Ép chung một
 * component là ép chung cả hành vi.
 */
export const DUONG_VE =
  'inline-flex items-center gap-1 text-than font-medium text-muted transition-colors hover:text-fg'

export const NEN_PILL = 'bg-fill-strong'
export const NEN_HEAD = 'bg-fill-strong'
export const KE_HANG = 'border-rule'
const HOVER_HANG = 'hover:bg-fill'

/**
 * CHIỀU CAO CHUNG của mọi ô điều khiển trên dải công cụ — ô nhập, `<select>`,
 * nút. `h-9` = 36px, khoá cứng.
 *
 * VÌ SAO PHẢI KHOÁ, ĐO ĐƯỢC (Chromium 1440px, màn `/users`): trước đây không ô
 * nào đặt chiều cao, mỗi ô tự suy ra từ `padding + line-height + border` nên ba
 * ô cạnh nhau ra ba số khác nhau:
 *   · ô tìm (`<input>`) .......... 36.8px  (line-height 18.75 + 16 pad + 2 viền)
 *   · `<select>` ................. 36.0px  (`line-height: normal` của select khác)
 *   · nút chính .................. 34.8px  (KHÔNG có viền, hụt đúng 2px)
 * Lệch 0.8-2.0px là đủ thấy mép dưới không thẳng hàng. `box-sizing: border-box`
 * (mặc định của Tailwind) làm `h-9` thắng cả ba khác biệt trên cùng một lúc.
 *
 * Nút phải kèm `inline-flex items-center` — chiều cao cố định thì `py` không
 * còn canh giữa được chữ nữa.
 *
 * XUẤT RA NGOÀI từ 2026-08-09: dải lọc của `/convos` có một nhóm nút khoảng
 * thời gian không phải `<input>` lẫn `<button>` đơn, nên không dùng lại được
 * `O_LOC`/`NUT_PHU` — nhưng nó vẫn phải cao đúng 36px như hai thứ đứng cạnh.
 */
export const CAO_O = 'h-9 max-md:h-10'

/**
 * Ô lọc / ô tìm trên dải công cụ.
 *
 * BỎ `outline-none`: nó tắt vòng focus mà KHÔNG thay bằng gì, nên người dùng
 * bàn phím Tab tới ô này là mất dấu hoàn toàn. Vòng focus giờ do `:focus-visible`
 * ở `theme.css` lo cho cả portal; `focus:border-fg` giữ lại để viền đậm thêm.
 */
export const O_LOC = `${CAO_O} rounded-md border border-border-field px-3 text-than focus:border-fg max-md:text-base`
/** Nút hành động chính (xanh accent). */
export const NUT_CHINH = `${CAO_O} inline-flex items-center justify-center rounded-md bg-ac px-[15px] text-than font-semibold text-white disabled:opacity-50`
/** Nút phụ trên dải công cụ / trong hộp xác nhận. */
export const NUT_PHU = `${CAO_O} inline-flex items-center justify-center rounded-md border border-border-field px-[15px] text-than`
/** Nút trong ô cuối của một hàng — nhỏ hơn để không đè nội dung hàng. */
export const NUT_HANG =
  'rounded-sm border border-border-field px-2 py-1 text-phu text-muted hover:border-fg'
/**
 * Nút hàng mang việc PHÁ HUỶ (xoá lời mời). Cùng hình dạng `NUT_HANG` — chỉ đổi
 * sắc độ chữ/viền: một nút đỏ đầy nền cạnh hai nút viền mảnh sẽ hút mắt về đúng
 * thứ người dùng ít làm nhất.
 */
export const NUT_HANG_XOA =
  'rounded-sm border border-badge-alert-fg/30 px-2 py-1 text-phu text-badge-alert-fg hover:border-badge-alert-fg'

// `max-md:size-10` — spec §5.4 "vùng chạm ≥40px trên mobile"; icon giữ `size-4`
// bên trong (không phóng to icon, chỉ nới vùng bấm quanh nó).
const NUT_ICON =
  'inline-flex size-7 max-md:size-10 flex-none items-center justify-center rounded-sm border transition-colors disabled:opacity-60 disabled:cursor-not-allowed'
const NUT_ICON_THUONG = `${NUT_ICON} border-border-field text-muted hover:border-fg hover:text-fg`
/** XÁM khi nghỉ, đỏ khi rê/focus (quieter 05/10). Đỏ thường trực là một cột thùng rác
 *  báo động trên MỌI hàng của mọi bảng, cho một việc chưa ai định làm — màu cảnh báo
 *  lặp N lần thì hết còn là cảnh báo. Đỏ hiện đúng lúc tay đã đặt vào nút. */
const NUT_ICON_XOA = `${NUT_ICON} border-border-field text-muted hover:border-badge-alert-fg hover:bg-badge-alert-bg hover:text-badge-alert-fg focus-visible:border-badge-alert-fg focus-visible:text-badge-alert-fg`

/**
 * Nút hành động trong ô cuối một hàng, dạng ICON VUÔNG 28px.
 *
 * VÌ SAO ICON THAY VÌ CHỮ: nhãn chữ dài ngắn khác nhau («Sửa» 2 ký tự, «Mời
 * lại» 7, «Thu hồi» 7) nên cột hành động của mỗi bảng rộng một kiểu, và trong
 * cùng một bảng, hàng có ba nút đẩy cột rộng gấp đôi hàng có một nút — mép phải
 * của bảng gãy theo từng hàng. Icon vuông đều nhau khoá chiều rộng cột lại.
 *
 * ⚠️ `nhan` VÀO CẢ `title` LẪN `aria-label`, không phải chọn một:
 *   · `title` là thứ hiện ra khi rê chuột — không có nó thì một cái thùng rác
 *     trần là câu đố.
 *   · `aria-label` là TÊN KHẢ TRUY CẬP. Trình đọc màn hình đọc cái này, và mọi
 *     bài test đang tìm nút bằng `getByRole('button', { name: 'Sửa' })` cũng
 *     khớp vào chính nó. Bỏ `aria-label` là vừa mù trình đọc màn hình vừa đỏ
 *     một loạt test — hai hậu quả, cùng một dòng thiếu.
 * `Icon` đã có `aria-hidden`, nên không có chuyện đọc trùng.
 */
export function NutIcon({
  icon,
  nhan,
  onClick,
  disabled,
  phaHuy,
}: {
  readonly icon: IconName
  readonly nhan: string
  readonly onClick: () => void
  readonly disabled?: boolean | undefined
  /** Việc không hoàn tác được (xoá) — đỏ khi rê/focus (`NUT_ICON_XOA`). */
  readonly phaHuy?: boolean | undefined
}) {
  return (
    <button
      type="button"
      title={nhan}
      aria-label={nhan}
      onClick={onClick}
      disabled={disabled}
      className={phaHuy ? NUT_ICON_XOA : NUT_ICON_THUONG}
    >
      <Icon name={icon} className="size-4" />
    </button>
  )
}
/**
 * `align-middle` KHÔNG PHẢI trang trí (thêm 2026-08-10, đo trên trình duyệt).
 *
 * Ô bảng mặc định căn theo BASELINE. Hàng nào có một ô cao (khối tên + email hai
 * dòng, 38px) và các ô còn lại một dòng (pill 21px) thì pill bám vào baseline của
 * DÒNG ĐẦU ô cao, chứ không vào giữa hàng — đo ở `/users`: tâm hàng y=227, mà ba
 * ô kia có tâm 219 · 219 · 224. Bốn tâm khác nhau trên một hàng, và mắt đọc ra
 * "pill trôi lên" dù từng ô đều đúng padding.
 *
 * Bảng một dòng đều thì không thấy — đó là lý do lỗi này sống lâu. Nhưng
 * `align-middle` đúng cho MỌI bảng dữ liệu, không riêng bảng có ô hai dòng.
 */
export const TD = 'px-4 py-3 align-middle'
/** Ô chữ phụ trong hàng (loại hình, vị trí…) — nhạt hơn cột định danh. */
export const TD_PHU = 'px-4 py-3 align-middle whitespace-nowrap text-nav'

/**
 * Ô SỐ — căn phải, `font-mono`, `tabular-nums`, không xuống dòng.
 *
 * `theme.css` đã ghi thành luật ở dòng khai `--font-mono`: «MỌI con số dùng
 * font này». Trước 2026-08-21 luật đó chỉ được giữ ở những chỗ nhớ gõ tay
 * `font-mono`, nên cùng một màn có số chạy hai font: thẻ KPI mục ① của
 * `/billing` là JetBrains Mono, còn CÙNG những con số đó trong bảng mục ③ là
 * Be Vietnam Pro — người dùng đọc ra ngay là "hai kiểu chữ".
 *
 * `tabular-nums` là vế thứ hai, và nó chỉ thấy được khi bảng CUỘN hoặc SẮP
 * LẠI: chữ số tỷ lệ làm mỗi hàng rộng một khác, nên cột tiền căn phải vẫn
 * "rung" theo từng hàng dù mọi hàng đều đúng padding. Với font mono thì bề
 * rộng vốn đã đều, nhưng khai tường minh để ô còn đúng khi ai đó đổi font.
 *
 * KHÔNG gộp vào `TD`: cột CHỮ (tên khoá, email) dùng font mono là sai — mono
 * đọc chậm hơn hẳn ở văn xuôi, và nó nói "đây là mã máy" về một thứ không phải.
 */
export const TD_SO = 'px-4 py-3 align-middle text-right font-mono tabular-nums whitespace-nowrap'
export const PILL =
  'inline-block rounded-full px-2 py-0.5 text-nhan font-semibold whitespace-nowrap'

/**
 * Hàng chip LỌC — cùng hình dạng hàng tab (segmented control), giữ màu riêng của
 * từng chip (người dùng chốt 2026-08-21).
 *
 * Trước đợt này mỗi chip là một pill/nút viền rời nhau, nên một hàng bốn chip
 * màu đọc thành bốn nút hành động chứ không thành «một trong mấy». Rãnh xám bao
 * ngoài + chip đang chọn nổi lên là đúng thứ `NhomTab` đã nói ở hàng tab phía
 * trên, và hai bộ chọn-một trong một màn không nên có hai hình dạng.
 */
export const NHOM_LOC = `${NEN_PILL} inline-flex flex-wrap items-center gap-1 rounded-md p-1`
const LOC_CHUNG = 'rounded-sm px-3 py-[5px] text-phu font-medium'
/**
 * Chip đang chọn: nổi lên + viền trong bằng CHÍNH màu chữ của chip (`ring-current`),
 * nên dấu chọn không dựa vào màu nền. Chip chưa chọn giữ trọn màu: bản trước làm mờ
 * nó `opacity-55`, chữ tụt còn ~2,4:1 (audit 05/10). Nút chip phải mang `aria-pressed`.
 */
export const LOC_CHON = `${LOC_CHUNG} shadow-chon ring-1 ring-current ring-inset`
export const LOC = LOC_CHUNG

/**
 * Kéo pill ra sát mép cột, để CHỮ TRONG PILL thẳng hàng với CHỮ TIÊU ĐỀ cột.
 *
 * `PILL` có `px-2`, nên đặt pill vào một ô căn trái thì hộp pill trùng mép cột
 * còn chữ bên trong thụt vào 8px. Mắt đọc chữ, không đọc hộp — nên tiêu đề và
 * giá trị nhìn ra lệch nhau dù mọi padding đều "đúng".
 *
 * Đo ở `/users` (mép CHỮ bằng `Range`, không phải mép hộp):
 *   · Thành viên (không phải pill) — tiêu đề 353 · nội dung 353 ......... khớp
 *   · Vai trò    (pill, căn trái)  — tiêu đề 776 · nội dung 784 ......... +8
 *   · Trạng thái (pill, căn phải)  — tiêu đề 1265 · nội dung 1257 ....... −8
 *
 * Hộp pill khi đó thò ra ngoài mép chữ tiêu đề 8px — đó là căn chỉnh QUANG HỌC,
 * đúng như cách chữ nghiêng hay dấu ngoặc kép được kéo lố ra lề.
 */
export const PILL_SAT_TRAI = '-ml-2'

/**
 * Thẻ trắng bọc một bảng.
 *
 * `cao` truyền vào một class chiều cao. Có chiều cao thì bảng CUỘN BÊN TRONG và
 * `thead` dính mới có nghĩa; không truyền thì thẻ cao theo nội dung (dùng cho
 * bảng ngắn nằm trong một form đã dài).
 *
 * KẺ ĐÓNG dưới hàng cuối chỉ thêm cho thẻ `CAO_MAN`, và đây là chỗ duy nhất biết
 * đủ để quyết định điều đó.
 *
 * `Hang` chỉ vẽ `border-t`, nên mỗi kẻ là vách NGĂN giữa hai hàng và hàng cuối
 * không có mép dưới. Hầu hết thẻ không sao: chúng ÔM SÁT bảng (`cao` rỗng, hoặc
 * `max-h-…` co theo nội dung), nên viền thẻ nằm ngay dưới hàng cuối và chính nó
 * là kẻ đóng. Thêm `border-b` cho những thẻ đó là đặt hai kẻ CÙNG MÀU cách nhau
 * 0.5px — đo được ở `/api-keys`: đáy thẻ dày ~2.5px trong khi ba cạnh kia 1px.
 *
 * `CAO_MAN` (`flex-1`) là ngoại lệ duy nhất: thẻ bị ép cao hết màn nên bảng ngắn
 * để lại vài trăm px trắng bên dưới, viền thẻ ở tận đáy khoảng trắng ấy và không
 * đóng hộ được. Không có kẻ này thì thân bảng hụt mép, đọc như đang tải dở.
 */
export function TheBang({ cao = '', children }: { cao?: string | undefined; children: ReactNode }) {
  const dong = cao === CAO_MAN ? '[&_tbody>tr:last-child]:border-b' : ''
  return (
    <div
      className={`flex ${cao} ${dong} flex-col overflow-hidden rounded-lg border border-border bg-surface`}
    >
      {children}
    </div>
  )
}

/**
 * Bảng chiếm hết chiều cao còn lại của màn (`/projects`).
 *
 * KHÔNG CÒN LÀ MỘT CON SỐ (2026-08-08). Trước đây nó là `h-[calc(100vh-247px)]`,
 * tức mã hoá cứng tổng chiều cao của mọi thứ nằm trên bảng. Hai vấn đề, cả hai
 * đo được:
 *   · Nó SAI ngay khi phần trên đổi. Bỏ ba dòng thừa ở đầu `/projects` là con số
 *     lệch 71px, và trước đó nó đã lệch theo chiều ngược lại — thẻ tràn khỏi
 *     đáy cửa sổ nên cả trang phải cuộn, đúng thứ một bảng-cuộn-bên-trong sinh
 *     ra để tránh.
 *   · Nó không thể đúng cùng lúc ở hai trạng thái: badge «N dự án chưa đủ dữ
 *     liệu» xuất hiện/biến mất theo dữ liệu và dịch bảng 42px.
 *
 * Thay bằng `flex-1` — bảng lấy phần còn lại, bao nhiêu cũng đúng. `min-h-0` là
 * bắt buộc: mặc định `min-height: auto` của flex item không cho con co lại dưới
 * nội dung, và vùng cuộn bên trong sẽ đẩy thẻ phình ra thay vì cuộn.
 *
 * ⚠️ Chỉ có nghĩa khi CHA là một flex column CÓ chiều cao chặn — xem `DuAnList`.
 */
export const CAO_MAN = 'min-h-0 flex-1'
/**
 * Màn của MỘT bản ghi (`/pform`, `/uform`) — cao đúng phần còn lại của cửa sổ.
 *
 * 72px là chiều cao Topbar (`components/shell/Topbar.tsx`). Cùng khuôn với
 * `DuAnList` và `TongQuanScreen`; ba màn dài của app đều chặn chiều cao ở đây rồi
 * cho phần GIỮA cuộn, thay vì để cả trang cuộn.
 *
 * ⚠️ VÌ SAO KHÔNG để cả trang cuộn: hàng nút và chân bảng khi đó nằm ở một độ cao
 * KHÁC NHAU trên mỗi tab (tab ngắn thì cao, tab dài thì phải cuộn mới thấy), và
 * đổi tab là chúng nhảy. Chặn chiều cao ở gốc thì mọi tab dùng đúng một khung.
 */
export const KHUNG_MAN =
  'flex h-[calc(100dvh-72px)] flex-col overflow-hidden px-7 pb-6 max-md:h-[calc(100dvh-56px)] max-md:px-4 max-md:pb-4'

/**
 * Vùng GIỮA của màn đó — phần duy nhất cuộn.
 *
 * `min-h-0` là bắt buộc: mặc định `min-height: auto` của flex item không cho con
 * co dưới nội dung, và vùng cuộn sẽ đẩy cả khung phình ra thay vì cuộn.
 *
 * ⚠️ KHỐI, KHÔNG PHẢI FLEX. Nội dung tab mang `TAB_DAY` (`min-h-full`), và
 * `min-height: 100%` **thay** `min-height: auto` — mất luôn cái sàn theo nội dung.
 * Trong một flex container CÓ chiều cao xác định (đúng cái `flex-1` này tạo ra),
 * flex item vì thế bị BÓP về đúng 100% và nhóm ô cuối của tab dài bị cắt: đo được
 * trên tab Tổng quan, nhóm «Sở hữu & bàn giao» còn trơ cái tiêu đề. Là khối thì
 * không có phép co nào chạy — `min-h-full` quay về nghĩa «ít nhất, còn hơn thì
 * cao theo nội dung».
 *
 * `max-md:overscroll-contain` (Task 11 Fix round 1) — vệ binh THÊM, không phải
 * fix chính: gốc bệnh là một `<input sr-only>` của `OMedia`/`OTep` không có
 * containing block bên trong VUNG_TAB nên trôi ra tới `<main>` (đã sửa bằng
 * `max-md:relative` ở hai `<label>` bọc nó). Chặn `overscroll-behavior` ở đây
 * chỉ để cuộn chuột quá đáy VUNG_TAB không chain lên tổ tiên nào KHÁC nếu một
 * chỗ tương tự lọt qua sau này — mobile-only theo đúng yêu cầu vòng sửa,
 * không đổi hành vi desktop.
 */
export const VUNG_TAB = 'min-h-0 flex-1 overflow-y-auto pt-5 max-md:overscroll-contain'

/** Nội dung một tab FORM: ít nhất cao bằng vùng cuộn, dài hơn thì cuộn. */
export const TAB_DAY = 'min-h-full'

/**
 * Nội dung một tab DANH SÁCH: cao ĐÚNG bằng vùng cuộn.
 *
 * ⚠️ Phải là `h-full`, không dùng `TAB_DAY`. Thẻ bảng dùng `CAO_MAN` (`flex-1` +
 * `min-h-0`) nên nó chỉ ăn hết chỗ khi CHA có chiều cao XÁC ĐỊNH; với `min-h-full`
 * thì cha cao theo nội dung, thẻ lấy chiều cao của 28 hàng và **bảng thôi cuộn bên
 * trong thẻ** — hàng chạy khỏi đáy màn, chân bảng («Hiện 1–20 / 28») không thấy
 * đâu. Đo được trên tab Quỹ căn: vùng cuộn 689px, thẻ 1213px, tràn trong thẻ = 0.
 *
 * Đây là mặt ĐỐI của bẫy ở `VUNG_TAB`: form cần sàn theo nội dung, danh sách cần
 * chiều cao xác định. Một lớp cho cả hai thì luôn có một bên sai.
 */
export const TAB_KHUNG = 'h-full'

/**
 * Dải công cụ trên thẻ — ô lọc bên trái, nút chính bên phải.
 *
 * Mobile xuống dòng (`max-md:flex-wrap`): một hàng cứng thì nhóm ô lọc
 * (`min-w-0 flex-1`) bị bóp nhỏ hơn nội dung của chính nó và ô nhập tràn ra ĐÈ
 * lên nút cùng hàng — đo được ở `/projects` và `/users` (360–430px).
 */
export function ThanhCong({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-none items-center gap-2.5 border-b border-border-soft px-4 py-3 max-md:flex-wrap">
      {children}
    </div>
  )
}

/** Vùng cuộn của thẻ. Bọc bảng, hoặc trạng thái rỗng/lỗi (tự có padding). */
export function VungCuon({
  children,
  ...aria
}: {
  children: ReactNode
  /** `panelTab(…)` khi vùng là nội dung của một `NhomTab`. */
  role?: 'tabpanel'
  id?: string
  'aria-labelledby'?: string
}) {
  return (
    <div className="min-h-0 flex-1 overflow-auto" {...aria}>
      {children}
    </div>
  )
}

/** Dải dưới thẻ — chỗ của nút Tải thêm hoặc một câu chú thích. */
export function ChanBang({ children }: { children: ReactNode }) {
  return <div className="flex-none border-t border-border-soft px-4 py-3">{children}</div>
}

/**
 * `nhan` → `aria-label` của `<table>` (2026-08-10).
 *
 * Bảng nào cũng cần MỘT cái tên cho trình đọc màn hình, nhưng không phải bảng
 * nào cũng cần một `<h2>` VẼ RA cái tên đó: khi màn chỉ có một bảng, nhãn nav →
 * `<h1>` của Topbar đã nói đúng chữ ấy rồi, và một `<h2>` lặp lại là cùng một
 * chữ hai lần cách nhau 77px (đo ở `/users`). Truyền `nhan` thì tên vẫn tới
 * được trình đọc màn hình mà mắt không phải đọc lại.
 *
 * Màn có HAI bảng trở lên thì vẫn dùng `DauMuc` — ở đó cái tên phải nhìn thấy
 * được, vì không nhãn thì không biết bảng nào là bảng nào.
 */
/** Ô định danh của bảng GỌN trên điện thoại — chiếm phần còn lại, chữ `truncate` cắt
 *  theo bề rộng ô. `max-w-0` là mẹo của bảng `auto`: không có nó, chữ `nowrap` đẩy cột
 *  rộng theo chữ và bảng lại tràn ngang. */
export const TD_GON = 'max-md:w-full max-md:max-w-0'

export function Bang({
  nhan,
  gon = false,
  children,
}: {
  nhan?: string | undefined
  /** Điện thoại: màn tự rút còn cột định danh + cột thao tác (thông tin cột giữa xuống
   *  thành dòng phụ trong ô định danh) ⇒ bỏ `min-w-[720px]`, không cuộn ngang. */
  gon?: boolean
  children: ReactNode
}) {
  return (
    // `data-bang`: móc của khối «BẢNG TRÊN ĐIỆN THOẠI» cuối `theme.css` — cột đầu (và cột
    // thao tác, nếu `DauBang` đánh dấu) dính khi cuộn ngang bảng 720px trên màn 390px.
    // Bảng gọn không cuộn ngang nên không cần (và không được) dính.
    <table
      data-bang={gon ? undefined : ''}
      aria-label={nhan}
      className={`w-full min-w-[720px] border-collapse text-than ${gon ? 'max-md:min-w-0' : ''}`}
    >
      {children}
    </table>
  )
}

export interface Cot {
  readonly nhan: string
  /** Căn phải — dùng cho cột số và cột ngày. */
  readonly phai?: boolean
  /**
   * Class bề rộng cho `<th>` — cách ĐẨY một cột sang phải mà KHÔNG căn phải nó.
   *
   * Vì sao cần phân biệt hai thứ đó: `text-right` làm mép PHẢI của giá trị trùng
   * mép phải tiêu đề, nhưng mép TRÁI thì lệch theo độ dài từng chuỗi — «Đang hoạt
   * động» và «Chờ nhận lời mời» bắt đầu ở hai chỗ khác nhau, và mắt đọc chỗ BẮT
   * ĐẦU. Muốn cột nằm sát lề phải mà chữ vẫn thẳng hàng thì phải đẩy bằng bề
   * rộng: cột trước nó nuốt phần dư (`w-full`), cột này co về nội dung.
   *
   * Thực tế chỉ dùng `w-full` (nuốt phần dư) và một phân số cho cột định danh —
   * không có `w-full` neo lại thì `table-auto` chia phần dư cho mọi cột và không
   * cột nào tới được lề.
   */
  readonly rong?: string
  /**
   * Khoá sắp xếp gửi lên SERVER. Có ⇒ tiêu đề cột thành một nút có mũi tên.
   *
   * Là khoá của server chứ không phải tên trường FE (`price_vnd`, không
   * `priceVnd`): bảng phân trang phía server nên sắp xếp cũng phải ở đó — sắp
   * mảng đã tải chỉ sắp trong một trang, và "căn đắt nhất" hoá ra là căn đắt
   * nhất trong 20 hàng đang xem.
   */
  readonly sap?: string
}

/** Cột đang sắp xếp + chiều. `null` = đang ở thứ tự mặc định. */
export interface SapXep {
  readonly cot: string
  readonly giam: boolean
}

const TH_CHUNG =
  'sticky top-0 z-[1] whitespace-nowrap px-4 py-2.5 text-nhan font-semibold uppercase tracking-[.07em]'

/**
 * `thead` từ danh sách nhãn cột.
 *
 * `sticky` cộng nền đục: thiếu nền thì hàng cuộn qua phía sau chữ tiêu đề và cả
 * hai không đọc được.
 *
 * CỘT SẮP XẾP ĐƯỢC (`Cot.sap`) render một `<button>` thật trong `<th>`, không
 * phải `onClick` trên chính `<th>`: người dùng bàn phím phải Tab tới được, và
 * trình đọc màn hình phải nghe ra đây là thứ bấm được. `aria-sort` trên `<th>`
 * là chỗ DUY NHẤT nói ra chiều đang sắp cho trình đọc màn hình — mũi tên vẽ ra
 * chỉ có mắt đọc được.
 */
export function DauBang({
  cot,
  sapXep = null,
  doiSap,
}: {
  cot: readonly Cot[]
  sapXep?: SapXep | null | undefined
  doiSap?: ((khoa: string) => void) | undefined
}) {
  return (
    // Cột cuối không nhãn = cột NÚT THAO TÁC (sửa/xoá/⋯) — đánh dấu để nó dính mép phải ở
    // điện thoại, không thì nút nằm ngoài màn sau một bảng cuộn ngang (audit 05/10).
    <thead className={NEN_HEAD} data-cot-thao-tac={cot.at(-1)?.nhan === '' ? '' : undefined}>
      <tr>
        {cot.map((c, i) => {
          // Hằng cục bộ, không đọc thẳng `c.sap` trong closure: TypeScript chỉ
          // giữ phép thu hẹp kiểu (`string | undefined` → `string`) qua ranh giới
          // hàm cho biến `const`, không cho thuộc tính của một object.
          const khoa = c.sap
          const sapDuoc = khoa !== undefined && doiSap !== undefined
          const dangSap = sapXep && khoa === sapXep.cot ? sapXep : null
          return (
            <th
              key={c.nhan || `trong-${i}`}
              aria-sort={
                sapDuoc
                  ? dangSap
                    ? dangSap.giam
                      ? 'descending'
                      : 'ascending'
                    : 'none'
                  : undefined
              }
              className={`${TH_CHUNG} ${NEN_HEAD} ${c.rong ?? ''} text-muted-2 ${
                c.phai ? 'text-right' : 'text-left'
              }`}
            >
              {khoa !== undefined && doiSap !== undefined ? (
                <button
                  type="button"
                  onClick={() => doiSap(khoa)}
                  className={`inline-flex items-center gap-1 uppercase tracking-[.07em] hover:text-fg max-md:-my-2.5 max-md:py-2.5 ${
                    dangSap ? 'text-fg' : ''
                  }`}
                >
                  {c.nhan}
                  {/* Mũi tên MỜ khi cột chưa sắp — nó là lời mời bấm. Không vẽ gì
                      cả thì không ai biết cột này bấm được; vẽ đậm như cột đang
                      sắp thì ba cột đều trông như đang sắp cùng lúc. */}
                  <span aria-hidden className={dangSap ? '' : 'opacity-35'}>
                    {dangSap ? (dangSap.giam ? '↓' : '↑') : '↕'}
                  </span>
                </button>
              ) : (
                c.nhan
              )}
            </th>
          )
        })}
      </tr>
    </thead>
  )
}

/** Thứ trong một hàng KHÔNG được coi là "bấm vào hàng". */
const TU_BAM_DUOC = 'a,button,input,select,textarea,label,[role="button"]'

interface HangProps {
  /** Mở bản ghi. Không truyền ⇒ hàng không bấm được (không có con trỏ tay). */
  mo?: (() => void) | undefined
  children: ReactNode
}

/**
 * Hàng bấm được — bấm bất kỳ đâu trong hàng thì mở bản ghi.
 *
 * BỎ QUA CLICK PHÁT TỪ MỘT PHẦN TỬ TƯƠNG TÁC (`closest(TU_BAM_DUOC)`): không có
 * phép kiểm này thì bấm Xoá vừa mở hộp xác nhận vừa điều hướng sang bản ghi,
 * và người dùng thấy màn nhảy đi trong lúc đang định xoá. Cùng lý do cho ô nhập
 * và link nằm trong hàng.
 *
 * ⚠️ MỘT `<tr>` CÓ `onClick` KHÔNG TỚI ĐƯỢC BẰNG BÀN PHÍM, và đó là chủ ý: click
 * hàng là đường TẮT cho chuột, không phải đường duy nhất. Mỗi bảng vẫn giữ một
 * phần tử tương tác thật trong hàng (link ở cột định danh, hoặc nút Sửa) để
 * người dùng bàn phím và trình đọc màn hình vẫn mở được bản ghi. Biến cả hàng
 * thành `<button>` sẽ lồng nút trong nút — HTML không cho, và trình đọc màn hình
 * đọc ra một khối chữ dài không có cấu trúc bảng.
 *
 * KẺ ĐÓNG của hàng cuối KHÔNG ở đây mà ở `TheBang` — xem chú thích tại đó. Tóm
 * lại: chỉ thẻ bị ép cao hơn bảng mới cần, còn thẻ ôm sát bảng thì viền thẻ đã
 * là kẻ đóng, thêm nữa là hai kẻ cách nhau nửa pixel ở đáy.
 */
export function Hang({ mo, children }: HangProps) {
  return (
    <tr
      className={`border-t ${KE_HANG} ${HOVER_HANG} align-top ${mo ? 'cursor-pointer' : ''}`}
      onClick={
        mo &&
        ((e) => {
          if (!(e.target as HTMLElement).closest(TU_BAM_DUOC)) mo()
        })
      }
    >
      {children}
    </tr>
  )
}

// ─── Nhóm tab dạng pill ─────────────────────────────────────────────────────

export interface MucTab<T extends string> {
  readonly id: T
  readonly nhan: string
  /** Mark đứng trước nhãn. Có thì MỌI mục trong nhóm nên có — một tab có icon
   *  cạnh một tab không có thì hai cái đọc thành hai hạng khác nhau. */
  readonly icon?: IconName
}

const TAB_CHUNG =
  'flex items-center gap-2 rounded-sm px-3.5 py-[7px] text-than font-medium transition-colors max-md:min-h-10 max-md:flex-none max-md:whitespace-nowrap'
/** Mục đang mở: **thẻ trắng nổi trên rãnh xám**, không phải khối đen.
 *
 * Bản trước tô `bg-panel` + chữ trắng, tức gần như đen tuyền — nó đọc thành một
 * NÚT CHÍNH chứ không phải "trang đang xem", và nó là mảng tối duy nhất trên
 * một trang giấy ấm. Kiểu segmented control (nền lõm, mục chọn nổi lên) nói
 * đúng nghĩa "một trong mấy" mà không hét. */
const TAB_CHON = `${TAB_CHUNG} bg-surface text-fg shadow-chon`
const TAB = `${TAB_CHUNG} text-muted hover:text-fg`

/**
 * Nhóm tab dạng segmented control — MỘT hình dạng cho cả portal.
 *
 * Dùng ở `/projects`, `/pform`, `/uform`, `/users`, và ở màn Thử agent (Chat ·
 * Voice). Màn đó trước có bộ tab RIÊNG viết tay: cùng nền `fill-strong` nhưng
 * mục chọn là thẻ trắng có bóng, trong khi `NhomTab` tô đen — hai bộ tab cạnh
 * nhau trong một sản phẩm, và người dùng chỉ ra ngay. Gộp về đây thay vì chép
 * lớp sang: hai component trông giống nhau sẽ lệch lại ở lần sửa sau.
 *
 * `nhan` = `aria-label` của tablist. Bỏ trống được khi ngữ cảnh đã nói rõ (hàng
 * tab của một bản ghi ngay dưới tên bản ghi).
 *
 * Phím theo WAI-ARIA Tabs (kích hoạt tự động — khuôn `KhoiVaiTro`): ←/→ sang tab kề
 * (vòng hai đầu), Home/End về đầu/cuối; roving `tabIndex` nên Tab
 * vào nhóm chỉ dừng ở tab đang mở. Trước 2026-10-05 nhóm khai `tablist`/`tab` mà
 * không có phím nào — trình đọc màn hình hứa một mô hình phím không tồn tại.
 * `idPanel` (tuỳ chọn): id vùng nội dung của nhóm — tab mang `aria-controls`, vùng
 * trải `panelTab(idPanel, dangMo)` (`./panelTab.ts`). Vắng ⇒ không nối, như trước.
 */
export function NhomTab<T extends string>({
  muc,
  dangMo,
  doi,
  nhan,
  idPanel,
}: {
  muc: readonly MucTab<T>[]
  dangMo: T
  doi: (id: T) => void
  nhan?: string | undefined
  idPanel?: string | undefined
}) {
  function phim(e: PhimReact<HTMLDivElement>) {
    const i = muc.findIndex((m) => m.id === dangMo)
    const toi =
      e.key === 'ArrowRight'
        ? muc[(i + 1) % muc.length]
        : e.key === 'ArrowLeft'
          ? muc[(i - 1 + muc.length) % muc.length]
          : e.key === 'Home'
            ? muc[0]
            : e.key === 'End'
              ? muc.at(-1)
              : undefined
    if (!toi) return
    e.preventDefault()
    e.currentTarget.querySelector<HTMLElement>(`[data-muc-tab="${toi.id}"]`)?.focus()
    if (toi.id !== dangMo) doi(toi.id)
  }

  return (
    <div
      className={`${NEN_PILL} inline-flex gap-1 rounded-md p-1 max-md:max-w-full max-md:overflow-x-auto`}
      role="tablist"
      aria-label={nhan}
      onKeyDown={phim}
    >
      {muc.map((m) => (
        <button
          key={m.id}
          type="button"
          role="tab"
          data-muc-tab={m.id}
          id={idPanel && idTab(idPanel, m.id)}
          aria-controls={idPanel}
          aria-selected={dangMo === m.id}
          tabIndex={dangMo === m.id ? 0 : -1}
          className={dangMo === m.id ? TAB_CHON : TAB}
          onClick={() => doi(m.id)}
        >
          {m.icon && <Icon name={m.icon} className="size-4 flex-none opacity-85" />}
          {m.nhan}
        </button>
      ))}
    </div>
  )
}

// ─── Bộ lọc chọn-một ────────────────────────────────────────────────────────

/**
 * Rãnh + thẻ nổi — CÙNG hình `NhomTab` (người dùng chốt 2026-10-05), nhưng cao
 * `CAO_O` (36px) để đứng ngang ô tìm/ô chọn trong thanh lọc; `NhomTab` cao 42px
 * vì nó đứng một mình làm đầu một vùng. Trước đợt này portal có SÁU hình cho
 * cùng một việc «chọn một trong vài»: nhóm liền nền `acs` (`/convos`), nút viền
 * rời (`/usage`, `/billing`), nền accent đặc (`/kich-ban`), pill (`/quality`)…
 *
 * Xuất cả hai chuỗi class cho chỗ cần CÙNG hình mà khác hành vi — lọc sao
 * `/quality` chọn được NHIỀU mục nên không dùng `ChonMot`, nhưng không được trông
 * như một kiểu khác. Mục đang chọn nói bằng `aria-pressed` (kiểu dựa vào nó).
 */
export const NHOM_CHON = `${NEN_PILL} inline-flex h-9 items-stretch gap-0.5 rounded-md p-[3px] max-md:h-auto`
export const MUC_CHON =
  'flex cursor-pointer items-center justify-center gap-1.5 rounded-sm px-3 text-than font-medium whitespace-nowrap text-muted transition-colors hover:text-fg aria-pressed:bg-surface aria-pressed:text-fg aria-pressed:shadow-chon max-md:min-h-10 max-md:flex-1 max-md:px-2'

/**
 * Nhóm nút chọn-một cho BỘ LỌC: `role="group"` + `aria-pressed`, KHÔNG phải
 * `tablist` — gán ngữ nghĩa tab cho một bộ lọc là hứa với trình đọc màn hình
 * một vùng nội dung đổi theo mà không có.
 */
export function ChonMot<T extends string | number>({
  muc,
  chon,
  doi,
  nhan,
  className = '',
}: {
  muc: readonly { readonly ma: T; readonly nhan: ReactNode }[]
  chon: T
  doi: (ma: T) => void
  /** `aria-label` của nhóm — nói nhóm lọc theo CÁI GÌ («Khoảng thời gian»). */
  nhan: string
  className?: string
}) {
  return (
    <div role="group" aria-label={nhan} className={`${NHOM_CHON} ${className}`}>
      {muc.map((m) => (
        <button
          key={m.ma}
          type="button"
          aria-pressed={m.ma === chon}
          onClick={() => doi(m.ma)}
          className={MUC_CHON}
        >
          {m.nhan}
        </button>
      ))}
    </div>
  )
}
