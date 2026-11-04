/**
 * Chia 13 kỹ năng ra hai tab: chung của agent vs riêng lĩnh vực BĐS.
 *
 * CHỈ là tầng hiển thị (spec 2026-08-07 §3.2): payload gửi backend vẫn là một
 * mảng `tools.enabled` gộp. KHÔNG sửa `lib/tools.ts` — nó là bản sao hợp đồng
 * backend có cổng parity canh, thêm trường vào đó là thêm thứ parity không so.
 *
 * Kỹ năng backend thêm sau này không có tên ở đây sẽ tự rơi vào tab BĐS —
 * mặc định đúng cho vertical #1; muốn nó thành kỹ năng chung thì thêm tên vào
 * `KY_NANG_CHUNG`. `tests/ky-nang-tab.test.ts` canh tên trỏ vào sổ thật.
 */
import { MUOI_HAI_KY_NANG, type KyNang } from '@/lib/tools'

export const KY_NANG_CHUNG: readonly string[] = ['kb_search', 'update_customer', 'escalate']

export const KY_NANG_TAB_CHUNG: readonly KyNang[] = MUOI_HAI_KY_NANG.filter((k) =>
  KY_NANG_CHUNG.includes(k.ten),
)

export const KY_NANG_TAB_BDS: readonly KyNang[] = MUOI_HAI_KY_NANG.filter(
  (k) => !KY_NANG_CHUNG.includes(k.ten),
)
