import type { Action } from './actions'
import type { IconName } from '@/components/icons'

/** VI mặc định, EN thứ hai — spec §6.2. */
export type Lang = 'vi' | 'en'
export type Label = Readonly<Record<Lang, string>>

interface NavBase {
  readonly label: Label
  readonly icon: IconName
  /**
   * Quyền cần có để THẤY mục này. Bắt buộc, không rỗng.
   *
   * ⚠ ẨN NÚT KHÔNG PHẢI BẢO VỆ (PQ_01 §BR-Q03). Đây chỉ để đỡ rối mắt. Mọi
   * quyền phải kiểm ở tầng API bằng `require(action)`. Ai xoá check ở API vì
   * "nav đã ẩn rồi" là đang tạo lỗ hổng.
   */
  readonly requiredActions: readonly [Action, ...Action[]]
}

/** Mục nav dẫn tới một màn. `key` khớp `data-screen` của prototype. */
export interface NavLeaf extends NavBase {
  readonly kind: 'leaf'
  readonly key: string
  readonly path: string
}

/**
 * Một KHỐI trong panel: vài mục dưới một nhãn chữ nhỏ in hoa.
 *
 * `label: null` = khối mở đầu, không nhãn — mảng nào cũng bắt đầu bằng một
 * khối như thế, và mảng đơn giản (Vận hành · Quản trị) chỉ có đúng nó.
 *
 * KHỐI CÓ NHÃN THÌ GẬP ĐƯỢC (2026-08-08), khối không nhãn thì không.
 *
 * Đây KHÔNG phải sự quay lại của cấp cha «Lĩnh vực» đã bỏ. Cái cũ bọc TRỌN
 * mảng chứa nó — một cú bấm để mở ra đúng thứ vốn đã là toàn bộ nội dung, tức
 * không nói thêm gì. Cái này bọc đúng ruột của MỘT lĩnh vực trong khi còn
 * những lĩnh vực khác bên cạnh, nên quan hệ cha/con là thật và đáng vẽ ra.
 *
 * Mặc định MỞ: mục đích của khối là cho thấy Kiến thức và Kỹ năng thuộc về
 * lĩnh vực nào, mà gập sẵn thì không thấy gì. Gập là để dọn, không phải mặc
 * định.
 *
 * VÌ SAO CẦN: agent gồm phần CHUNG (danh tính, rào chắn, kỹ năng chung) và
 * phần RIÊNG TỪNG LĨNH VỰC (kiến thức + kỹ năng của lĩnh vực đó). Hai thứ đó
 * nằm phẳng cạnh nhau là mất đúng thông tin quan trọng nhất của màn Agent:
 * cái gì áp cho mọi lĩnh vực, cái gì chỉ áp cho một.
 */
export interface NavSegment {
  readonly label: Label | null
  /**
   * Icon của đầu khối. Chỉ khối CÓ NHÃN mới cần — khối không nhãn không có đầu
   * để gắn icon vào.
   */
  readonly icon?: IconName
  /**
   * Mã lĩnh vực nếu khối này LÀ một lĩnh vực (`bds`, `taichinh`, …).
   *
   * Khối mang mã thì sống chết theo công tắc ở màn «Quản lý lĩnh vực»: tắt lĩnh
   * vực ⇒ khối biến mất khỏi panel, và kỹ năng của nó không vào payload gửi
   * agent. Khối KHÔNG mang mã (phần chung, phần hệ thống) luôn hiện.
   */
  readonly linhVuc?: string
  readonly entries: readonly NavLeaf[]
}

/**
 * Một MẢNG của rail: Vận hành · Agent · Quản trị.
 *
 * `key` và `icon` là hai trường mọc thêm khi sidebar một cột thành rail + panel
 * (2026-08-07). Rail cần một icon cho chính cái mảng, và cần một khoá ổn định
 * để `OFF_NAV` trỏ tới — nhãn thì đổi theo ngôn ngữ nên không làm khoá được.
 *
 * Thêm ở ĐÂY chứ không đặc-biệt-hoá trong Rail: luật của repo là "thấy mình
 * đang sửa shell để thêm một màn thì nghĩa là kiểu nav thiếu một trường".
 */
export interface NavGroup {
  readonly key: string
  readonly label: Label
  readonly icon: IconName
  readonly segments: readonly NavSegment[]
}

/** Duyệt phẳng mọi leaf — dùng cho test và cho lọc quyền. */
export function flattenLeaves(groups: readonly NavGroup[]): readonly NavLeaf[] {
  return groups.flatMap((g) => g.segments.flatMap((s) => s.entries))
}

/** Khối một-mục-không-nhãn — dạng thường gặp nhất, đỡ lặp `{ label: null }`. */
export function khoi(...entries: readonly NavLeaf[]): NavSegment {
  return { label: null, entries }
}

/**
 * Một màn có "đang mở" hay không. Khớp chính xác, hoặc là tổ tiên của route con
 * (`/convos/$phone` thuộc về mục `/convos`).
 *
 * MỘT chỗ định nghĩa, ba chỗ dùng: rail tô sáng mảng, panel tô sáng mục, topbar
 * lấy tiêu đề. Trước đây Topbar tự viết lại phép so này — hai bản của cùng một
 * luật là hai chỗ để lệch nhau.
 */
export function matchesPath(path: string, pathname: string): boolean {
  return pathname === path || pathname.startsWith(`${path}/`)
}
