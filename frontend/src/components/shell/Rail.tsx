/**
 * Rail — cột 68px ngoài cùng, bốn mảng của portal.
 *
 * BẤM MỘT MẢNG LÀ ĐIỀU HƯỚNG tới màn đầu của mảng đó, không phải chỉ đổi nội
 * dung panel. Nhờ vậy mảng đang sáng LUÔN suy ra được từ route hiện tại và
 * không có trạng thái "đang xem mảng khác" nào phải giữ — một nguồn sự thật.
 *
 * Giá phải trả: không ngó được mục của mảng khác mà không rời màn đang mở. Đó
 * chính là việc của ⌘K, và là lý do palette có mặt trong cùng đợt thay đổi này
 * chứ không phải một tính năng rời.
 *
 * "Màn đầu của mảng" lấy từ danh sách ĐÃ LỌC QUYỀN — người không có quyền xem
 * màn đầu thì đi tới màn được phép đầu tiên, không đi tới một cái 403.
 */
import { Link, useRouterState } from '@tanstack/react-router'
import { Icon } from '@/components/icons'
import { useLang } from '@/i18n'
import { groupFor } from '@/lib/nav-registry'
import { flattenLeaves } from '@/lib/nav-types'
import type { NavGroup } from '@/lib/nav-types'
import { useNavGroups } from './useNavGroups'

/**
 * Dấu thương hiệu ở đầu rail — bản ĐỦ, chữ **NX** ghép + dòng **AGENT**.
 *
 * Bản đầu là một chữ **X** trần: nó vừa lặp lại đúng ký tự accent của wordmark
 * cũ, vừa đọc thành logo của mạng xã hội X. NX là hai chữ cái đứng cùng nhau nên
 * không còn nhầm được, và vẫn là viết tắt của chính cái tên.
 *
 * Dùng `<img>` trỏ vào `public/logo-nx-agent.svg` chứ KHÔNG chép path vào đây:
 * cùng một tệp với màn `/login`, nên logo hai chỗ không bao giờ lệch nhau. Bộ
 * path đã buộc phải nhân đôi một lần ở `favicon.svg` (tệp tĩnh, ngoài Tailwind);
 * bản thứ ba trong `src/` là bản sẽ quên sửa.
 *
 * ⚠️ Ô này **44px** chứ không 36px như bản chỉ-NX: dòng AGENT chiếm khoảng 1/5
 * chiều cao, ở 36px nó đo ra ~4.8px và đọc thành một vệt. 44px là cỡ lớn nhất
 * còn thở được trong rail 68px (còn 12px mỗi bên).
 *
 * Nền và bo góc nằm TRONG tệp SVG, nên `Link` không tô nền nữa — phản hồi rê
 * chuột chuyển sang `hover:opacity`.
 */
function BrandMark({ to }: { to: string }) {
  return (
    <Link
      to={to}
      aria-label="NobleX Agent"
      className="flex size-11 flex-none rounded-lg transition-opacity hover:opacity-85"
    >
      <img src="/logo-nx-agent.svg" alt="" aria-hidden="true" className="size-11" />
    </Link>
  )
}

function RailItem({ group, active }: { group: NavGroup; active: boolean }) {
  const { t } = useLang()
  // Mục đầu của KHỐI đầu — `useNavGroups` đã bỏ khối rỗng và mảng rỗng, nên
  // `segments[0].entries[0]` luôn là màn được phép đầu tiên của mảng.
  const first = flattenLeaves([group])[0]
  if (!first) return null

  return (
    <Link
      to={first.path}
      data-rail={group.key}
      // `data-current`, KHÔNG phải `aria-current`. `<Link>` của TanStack tự đặt
      // `aria-current="page"` khi `to` khớp route đang mở và nó GHI ĐÈ giá trị
      // truyền vào — nên một `aria-current="true"` viết tay ở đây cho ra
      // "page" lúc đang ở màn đầu của mảng và "true" lúc đang ở màn khác trong
      // cùng mảng. Một thuộc tính đổi giá trị theo route mà ý nghĩa không đổi
      // là thứ bài test sau sẽ đọc sai.
      //
      // Để router giữ `aria-current`: nó đúng theo nghĩa hẹp (link này CÓ trỏ
      // tới trang đang mở) và không bao giờ nói dối. Còn "mảng nào đang mở" thì
      // trình đọc màn hình lấy được từ `aria-label` của panel ngay bên cạnh —
      // panel tự khai tên mảng của nó.
      data-current={active ? 'true' : undefined}
      className={`flex w-14 flex-col items-center gap-1 rounded-md py-2 text-center ${
        // Mảng đang mở = THẺ TRẮNG NỔI trên rãnh, đúng idiom `NhomTab` của portal
        // (`Bang.tsx:326`) — rail giờ là một rãnh chìm n3, nên nền chọn phải NỔI
        // LÊN khỏi nó. `bg-acs` (#e7f2ee) là bậc dành cho nền TRẮNG: đặt lên n3 nó
        // gần bằng chính nền rail và mục đang mở đọc thành chìm.
        //
        // Hover SÁNG dần về phía thẻ trắng (n5 → n3): trên một rãnh chìm, rê chuột
        // là xem trước trạng thái chọn, nên nó đi cùng chiều với thẻ nổi chứ không
        // chìm thêm.
        active ? 'bg-surface text-ac shadow-chon' : 'text-nav hover:bg-fill-strong'
      }`}
    >
      <Icon name={group.icon} className="size-5 flex-none" />
      <span
        // 11px (sàn thang cỡ chữ, trước 10px) ⇒ bỏ `px-1` của thẻ + tracking dương: lòng
        // thẻ 48px cắt «Vận hành» đậm thành «Vận h…» (đo 2026-10-05); 56px vừa cả bốn nhãn.
        className={`w-full truncate text-nhan leading-[1.3] ${
          // KHÔNG `text-muted-2` (n7) nữa: nhãn này 10px và nền rail giờ là n5 —
          // n7 trên n5 chỉ còn 3.47, trượt AA. Để nhãn thừa hưởng `text-nav` (n9)
          // của link: 5.35 trên n5, và icon/chữ cùng một sắc thì cụm đọc liền một
          // khối thay vì hai tầng mờ dần.
          active ? 'font-semibold' : 'font-medium'
        }`}
      >
        {t(group.label)}
      </span>
    </Link>
  )
}

export function Rail({
  panelThuGon,
  onDoiThuGon,
}: {
  /**
   * Nút thu gọn panel màn (2026-08-24). CẢ HAI prop tuỳ chọn: state sống ở
   * layout `_app.tsx` (nơi quyết định có render `NavPanel` hay không), rail chỉ
   * là chỗ ĐẶT nút. Vì sao ở ĐÁY RAIL: nút phải còn nhìn thấy được ở cả trạng
   * thái đã thu gọn (đặt trong panel thì thu gọn xong nút biến mất theo), và
   * bản đầu đặt ở Topbar trước tiêu đề màn thì người dùng chê ngay — nó lấn
   * vào tiêu đề. Rail hiện ở cả hai trạng thái và đáy rail đang trống.
   * Không truyền `onDoiThuGon` (shell.test.tsx dựng `<Rail />` trần, không có
   * panel nào để thu) thì nút không render — nút không nối với gì là nút nói dối.
   */
  panelThuGon?: boolean
  onDoiThuGon?: () => void
}) {
  const { t } = useLang()
  const groups = useNavGroups()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const active = groupFor(groups, pathname)

  // Không mảng nào qua được bộ lọc quyền ⇒ không có gì để dẫn tới. Trả `null`
  // thay vì một rail trống: một cột 68px rỗng cạnh panel rỗng trông như hỏng
  // render, còn màn thì vẫn tự nói được vì sao nó rỗng.
  const home = flattenLeaves(groups)[0]
  if (!home) return null

  return (
    /* Bậc 1 của thang chrome (`theme.css`). Không viền phải: chênh tông giữa
       chrome-1 và chrome-2 đã là ranh giới rồi, thêm một hairline nữa là ba
       đường dọc trong 68px. */
    <aside className="sticky top-0 z-40 flex h-screen max-lg:h-dvh w-[68px] flex-none flex-col items-center bg-chrome-1 pb-3">
      {/* Dải 72px = chiều cao `Topbar` và của đầu panel. Ba cột cùng một dải thì
          logo · tên workspace · tiêu đề màn nằm trên CÙNG một trục ngang, và mục
          rail đầu tiên không thò lên trên đường kẻ ngang của dải. */}
      <div className="flex h-[72px] flex-none items-center">
        <BrandMark to={home.path} />
      </div>
      {/* `mt-2` = `py-2` của `nav` trong panel ⇒ mục đầu của hai cột cùng mép trên. */}
      <nav aria-label="Mảng" className="mt-2 flex flex-col gap-1">
        {groups.map((g) => (
          <RailItem key={g.key} group={g} active={g.key === active?.key} />
        ))}
      </nav>
      {onDoiThuGon && (
        /* Hai nhãn + hai mark theo trạng thái (tiền lệ `hienBiMat`/`cheBiMat`):
           một icon đơn đổi nghĩa ngầm thì người dùng phải nhớ panel đang mở hay
           đang thu mới đoán được cú bấm làm gì. `mt-auto` đẩy nút xuống đáy —
           tách hẳn khỏi ba mục mảng để không đọc thành mảng thứ tư.
           `cursor-pointer` phải viết ra — Tailwind v4 không tự đặt cho <button>. */
        <button
          type="button"
          aria-label={t(
            panelThuGon
              ? { vi: 'Mở thanh bên', en: 'Expand sidebar' }
              : { vi: 'Thu gọn thanh bên', en: 'Collapse sidebar' },
          )}
          aria-expanded={!panelThuGon}
          onClick={onDoiThuGon}
          className="mt-auto flex size-9 flex-none cursor-pointer items-center justify-center rounded-md text-nav transition-colors hover:bg-fill-strong"
        >
          <Icon name={panelThuGon ? 'moPanel' : 'thuPanel'} className="size-5" />
        </button>
      )}
    </aside>
  )
}
