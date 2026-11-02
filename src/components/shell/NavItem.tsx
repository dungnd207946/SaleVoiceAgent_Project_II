/**
 * Một mục nav. Padding 9px/11px và chữ 13.5px giữ nguyên số của prototype; bo
 * góc và màu chữ giờ lấy từ thang của `theme.css` (`rounded-md` = 8px, `nav`)
 * chứ không còn viết cứng — đổi nhận diện là sửa một chỗ, không phải tệp này.
 * Active thì nền `acs` + chữ `ac` + weight 600.
 */
import { Link } from '@tanstack/react-router'
import { Icon } from '@/components/icons'
import { useLang } from '@/i18n'
import type { NavLeaf } from '@/lib/nav-types'
import { useDongNav } from './LopPhu'

// 13.5px chứ không 14.5px như sidebar 250px cũ: panel hẹp hơn sidebar, nên
// nhãn dài nhất lúc đo («Thành viên & Phân quyền», nay là «Người dùng» —
// 2026-08-09) phải nhỏ lại mới đủ chỗ. Bề rộng
// panel được chọn theo đúng cỡ chữ này — đổi số ở đây thì đo lại 240px bên
// `NavPanel.tsx`, hai con số buộc vào nhau.
const BASE =
  'flex items-center gap-2.5 rounded-md px-[11px] py-[9px] text-than text-nav hover:bg-fill'
/**
 * Mục đang mở = THẺ TRẮNG NỔI trên nền chrome, cùng idiom với rail và với
 * `NhomTab`. `bg-acs` (#e7f2ee) là bậc vẽ cho nền TRẮNG: đặt lên `chrome-2` nó
 * chỉ sáng hơn nền khoảng một mức, thành một mảng xanh nhợt đọc không ra là
 * đang-chọn hay đang-hover. Thẻ trắng + chữ accent thì nói cả hai bằng hình.
 */
const ACTIVE = 'bg-surface font-semibold text-ac shadow-chon hover:bg-surface'

interface Props {
  readonly item: NavLeaf
  /** Mục nằm trong một khối lĩnh vực gập được — thụt vào, KHÔNG icon. */
  readonly nested?: boolean
}

/**
 * `nested` quay lại 2026-08-08 cùng khối lĩnh vực gập được, nhưng khác bản cũ ở
 * một điểm: mục con **bỏ hẳn icon** thay vì thu nhỏ icon.
 *
 * Vì đầu khối đã mang icon của lĩnh vực, và ngay dưới nó «Kiến thức» lại là
 * chính cái toà nhà ấy còn «Kỹ năng» là con robot — ba mark khác cỡ chồng lên
 * nhau trong 40px chiều cao đọc thành nhiễu, không thành cấu trúc. Chỗ thụt
 * vào cộng với icon của đầu khối đã nói đủ "hai cái này thuộc về nó".
 *
 * `pl-[17px]`, KHÔNG phải 37: nét dọc nối cha–con ở `NavPanel` đã đẩy con sang
 * 19px + 1px viền, nên 17 nữa là chữ rơi đúng 37px — thẳng hàng với chữ của
 * đầu khối, giống hệt vị trí trước khi có nét gạch. Sửa một trong ba số thì
 * sửa cả ba.
 */
export function NavItem({ item, nested = false }: Props) {
  const { t } = useLang()
  const dongNav = useDongNav()
  const lop = nested ? `${BASE} pl-[17px]` : BASE

  return (
    <Link
      to={item.path}
      data-nav={item.key}
      className={lop}
      activeProps={{ className: `${lop} ${ACTIVE}` }}
      onClick={() => dongNav?.()}
    >
      {!nested && <Icon name={item.icon} className="size-4 shrink-0 opacity-85" />}
      <span className="truncate">{t(item.label)}</span>
    </Link>
  )
}
