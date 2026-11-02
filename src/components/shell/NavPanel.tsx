/**
 * Panel — cột 240px, các màn của MẢNG đang mở.
 *
 * 240px là số ĐO TRÊN TRÌNH DUYỆT THẬT, không phải số tròn và không phải số
 * ước lượng: nhãn dài nhất trong nav lúc đo («Thành viên & Phân quyền», nay đã
 * đổi thành «Người dùng» — 2026-08-09) có
 * `scrollWidth` = 167px ở cỡ chữ 13.5px / Be Vietnam Pro. Cộng icon 16px,
 * khoảng cách 10px, padding mục 11px và padding nav 10px mỗi bên ⇒ 240px cho
 * đúng 172px chỗ chứa chữ, dư 5px.
 *
 * CỐ Ý KHÔNG THU 240px LẠI sau lần đổi tên đó. Bề rộng panel là số cố định cho
 * MỌI mảng — bóp nó theo nhãn dài nhất của hôm nay là để nhãn dài tiếp theo (một
 * lĩnh vực mới, một màn mới) lại tràn. 240px là trần đã đo, không phải số vừa
 * khít một chuỗi cụ thể.
 *
 * ⚠ Bản đầu đặt 228px dựa trên phép ƯỚC LƯỢNG bề rộng chữ (~154px). Đo thật
 * lệch 13px và nhãn bị `truncate` cắt mất «& Phân quyền», tức cắt đúng nửa
 * phân biệt mục này với mục khác. Đổi cỡ chữ, đổi font, hay thêm một nhãn dài
 * hơn thì ĐO LẠI trên trình duyệt, đừng nhẩm.
 *
 * KHÔNG có tiêu đề mảng ở đầu panel. Tên mảng đã nằm ngay cạnh, dưới icon rail,
 * cách 68px; in lại nó ở đây là trang trí, không phải thông tin. Trình đọc màn
 * hình vẫn có tên đó qua `aria-label` của `<nav>` — accessible name không phải
 * thứ bắt buộc phải nhìn thấy.
 *
 * Thứ tự dọc = thứ tự phạm vi, rộng trước hẹp sau: workspace nào → (rail: mảng
 * nào) → màn nào → bạn là ai. Sidebar cũ đặt workspace switcher dưới ĐÁY, tức
 * phạm vi rộng nhất lại đọc sau cùng.
 */
import { useState } from 'react'
import { useRouterState } from '@tanstack/react-router'
import { Icon } from '@/components/icons'
import { useLang } from '@/i18n'
import { groupFor } from '@/lib/nav-registry'
import { matchesPath } from '@/lib/nav-types'
import type { NavSegment } from '@/lib/nav-types'
import { NavItem } from './NavItem'
import { UserMenu } from './UserMenu'
import { useNavGroups } from './useNavGroups'
import { WorkspaceSwitcher } from './WorkspaceSwitcher'

/**
 * Khối CÓ NHÃN = một lĩnh vực, gập được.
 *
 * MẶC ĐỊNH MỞ. Khối tồn tại để cho thấy Kiến thức và Kỹ năng thuộc về lĩnh vực
 * nào; gập sẵn thì không thấy gì và cái đầu khối thành một dòng chữ vô nghĩa.
 * Gập là để dọn khi có nhiều lĩnh vực, không phải trạng thái ban đầu.
 *
 * `mo || conDangMo`: đang đứng ở một màn CON thì khối luôn mở, kể cả người dùng
 * vừa bấm gập. Đánh đổi có thật — lúc đó nút gập bấm vào không thấy gì đổi —
 * nhưng nhánh kia tệ hơn: gập lại là giấu mất chính cái mục đang sáng, tức màn
 * hình không còn nói được bạn đang ở đâu.
 */
function KhoiLinhVuc({ seg }: { seg: NavSegment }) {
  const { t } = useLang()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const conDangMo = seg.entries.some((e) => matchesPath(e.path, pathname))
  const [mo, setMo] = useState(true)
  const hien = mo || conDangMo

  return (
    <>
      <button
        type="button"
        data-khoi={seg.label?.vi}
        aria-expanded={hien}
        onClick={() => setMo(!hien)}
        className="flex w-full items-center gap-2.5 rounded-md px-[11px] py-[9px] text-left text-than text-nav hover:bg-fill"
      >
        {seg.icon && <Icon name={seg.icon} className="size-4 shrink-0 opacity-85" />}
        <span className="truncate">{seg.label ? t(seg.label) : ''}</span>
        <Icon
          name="caret"
          strokeWidth={2}
          className={`ml-auto size-3 shrink-0 text-muted-2 transition-transform duration-150 ${hien ? 'rotate-90' : ''}`}
        />
      </button>
      {hien && (
        /*
          NÉT DỌC NỐI ĐẦU KHỐI VỚI CON. `ml-[19px]` đặt nó đúng TÂM icon của đầu
          khối (padding 11 + nửa icon 8), nên nét gạch trông như rơi thẳng
          xuống từ chính cái icon lĩnh vực — đó là thứ làm quan hệ cha/con đọc
          được mà không cần chữ đậm.

          19 (ml) + 1 (viền) + 17 (pl của mục con) = 37px, ĐÚNG vị trí chữ cũ:
          đổi cách vẽ nhưng không xê dịch chữ.
        */
        <div className="relative ml-[19px] flex flex-col gap-0.5 pl-px">
          {/*
            Vạch định vị TUYỆT ĐỐI, không phải `border-l`: viền luôn cao đúng
            bằng khối nên muốn nó ngắn hơn thì phải bóp cả khối, tức xê dịch
            mục con. Vạch rời ra thì `inset-y-1` cắt 4px mỗi đầu mà mục con
            đứng yên — nó tách khỏi đầu khối phía trên và dừng trước mép dưới,
            đọc nhẹ hơn một đường kẻ chạy suốt.

            `pl-px` thay đúng 1px mà `border-l` từng chiếm, nên ba số 19 + 1 +
            17 = 37 vẫn nguyên.
          */}
          {/* `bg-border-strong` (n5): trên nền chrome-2 thì n4 chỉ lệch nền một
              mức và vạch biến mất — mà vạch này CHÍNH LÀ thứ nói «hai mục dưới
              đây thuộc về khối trên». */}
          <span aria-hidden="true" className="absolute inset-y-1 left-0 w-px bg-border-strong" />
          {seg.entries.map((entry) => (
            <NavItem key={entry.key} item={entry} nested />
          ))}
        </div>
      )}
    </>
  )
}

export function NavPanel() {
  const { t } = useLang()
  const groups = useNavGroups()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const active = groupFor(groups, pathname)

  if (!active) return null

  return (
    /* Bậc 2 của thang chrome. Panel trắng (`surface`) làm thang gãy — nó SÁNG
       hơn cả nền trang, nên mắt đọc thành «cột tối · cột trắng · trang ngà» chứ
       không thành một chiều sâu. */
    <div className="sticky top-0 z-40 flex h-screen max-lg:h-dvh w-[240px] flex-none flex-col border-r border-border bg-chrome-2">
      <WorkspaceSwitcher />
      {/*
        `key` theo mảng: đổi mảng thì danh sách DỰNG LẠI, nên `nav-in` chạy lại.
        Không có `key` thì React tái dùng cùng các node và animation chỉ chạy
        đúng một lần trong đời trang.
      */}
      <nav
        key={active.key}
        aria-label={t(active.label)}
        className="nav-in flex flex-1 flex-col overflow-auto px-2.5 py-2"
      >
        {active.segments.map((seg, i) => (
          <div
            key={seg.label ? seg.label.vi : `_${i}`}
            className="flex flex-col gap-0.5 first:pt-0 [&+&]:pt-3"
          >
            {seg.label ? (
              <KhoiLinhVuc seg={seg} />
            ) : (
              seg.entries.map((entry) => <NavItem key={entry.key} item={entry} />)
            )}
          </div>
        ))}
      </nav>
      <UserMenu />
    </div>
  )
}
