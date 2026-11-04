import { ACTIONS } from '@/lib/actions'
import type { NavLeaf } from '@/lib/nav-types'

/**
 * Ba màn của khối «Chi phí». Tách khỏi `features/deferred/nav.ts`: hai màn
 * `usage`/`billing` từng nằm ở đó với `requiredActions: [WORKSPACE_ADMIN]` —
 * SAI so với backend, vốn gác 5 endpoint bằng `billing.read`. Hai bộ điều kiện
 * khác nhau cho cùng một màn là lỗi im lặng theo CẢ HAI chiều: role có
 * `billing.read` mà không phải workspace admin thì không thấy nav dù API trả
 * 200; workspace admin không có `billing.read` thì thấy nav rồi ăn 403.
 *
 * Nhãn DỊCH CẢ BA (spec 2026-08-20 usage-billing-fe) — đảo quyết định cũ ở
 * `deferred/nav.ts` («giữ nguyên tiếng Anh ở CẢ HAI ngôn ngữ»). Lý lẽ cũ là
 * «bản dịch mỗi nơi một kiểu»; nay spec đã CHỐT bản dịch nên lý lẽ đó hết
 * hiệu lực, và «Bảng giá» không có dạng tiếng Anh ngắn hợp lý trong nav này —
 * giữ tiếng Anh cho hai mục kia sẽ tạo ra một nhóm lai, đúng thứ chú thích cũ
 * cảnh báo, nay ở quy mô ba mục.
 */
export const usageNav: NavLeaf = {
  kind: 'leaf',
  key: 'usage',
  path: '/usage',
  label: { vi: 'Usage', en: 'Usage' },
  icon: 'usage',
  requiredActions: [ACTIONS.BILLING_READ],
}

export const billingNav: NavLeaf = {
  kind: 'leaf',
  key: 'billing',
  path: '/billing',
  label: { vi: 'Billing', en: 'Billing' },
  icon: 'billing',
  requiredActions: [ACTIONS.BILLING_READ],
}

/**
 * `pricingNav` ĐÃ XOÁ 2026-08-21 (người dùng chốt) — portal này là hệ thống cho
 * user ngoài dùng, họ không được đặt giá. Giá nay do migration `0949` của
 * backend seed (một `price_version` `is_default` phủ mọi tenant), không còn ai
 * vận hành màn giá trong ứng dụng.
 *
 * Route `/pricing` và `BangGiaScreen` GIỮ NGUYÊN: nó là đường duy nhất sửa giá
 * bằng tay, và nó vốn đã gác bằng `X-Platform-Admin-Token` chứ không bằng phiên
 * tenant — nên «ẩn khỏi nav» không hạ một lớp bảo vệ nào, chỉ thôi mời user vào
 * một màn họ không dùng được. Mục nay khai ở `OFF_NAV` (`lib/nav-registry.ts`)
 * để rail còn tô sáng mảng «Quản trị» và topbar còn có tiêu đề.
 *
 * KHÔNG khôi phục export này chỉ để «cho tiện»: một `NavLeaf` không ai import là
 * code chết, và `tests/nav-registry.test.ts` sẽ đỏ ngay nếu nó quay lại `NAV`
 * mà `screens.ts` vẫn khai `inNav: false`.
 */
