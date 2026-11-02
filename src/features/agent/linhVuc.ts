/**
 * Lĩnh vực của agent — sổ các vertical và công tắc bật/tắt từng cái.
 *
 * ⚠ HỢP ĐỒNG DO FE ĐỊNH TRƯỚC, BACKEND CHƯA CÓ. Cùng lối đã dùng cho
 * `POST /agent/try` (spec 2026-08-07 §5.2): FE khai hình dạng, `lib/msw/handlers.ts`
 * fake, backend làm sau. Khi backend làm xong mà hình dạng khác thì SỬA Ở ĐÂY
 * là xong — không màn nào tự gọi `fetch` cho hai endpoint này.
 *
 * VÌ SAO KHÔNG NHÉT VÀO `ConfigPayload`. Đó là chỗ đúng về nghĩa (lĩnh vực là
 * cấu hình agent) và cũng là chỗ đúng về luồng (đã có Lưu và áp dụng). Nhưng
 * backend đặt `extra="forbid"` trên payload — thêm một khoá lạ là **422 ngay**,
 * không có đường ra từ UI. Nên trạng thái bật/tắt sống ở endpoint riêng cho tới
 * khi backend mở thêm trường.
 *
 * VIỆC GATING THÌ KHÔNG PHẢI CHỜ AI. «Tắt lĩnh vực ⇒ agent không dùng nữa»
 * không cần trường mới: FE chỉ việc KHÔNG đưa tên kỹ năng của lĩnh vực đang tắt
 * vào `tools.enabled` — một mảng backend vốn đã nhận tập con bất kỳ. Xem
 * `locKyNangTheoLinhVuc` ở dưới và chỗ dùng nó trong `useBanNhap.ts`.
 */
import { KY_NANG_TAB_BDS } from './kyNang'

export interface LinhVuc {
  /** Khớp `NavSegment.linhVuc` trong `lib/nav-registry.ts`. */
  readonly ma: string
  readonly ten: string
  readonly bat: boolean
  /** Số kỹ năng thuộc lĩnh vực này — để màn quản lý nói rõ tắt đi là mất gì. */
  readonly soKyNang: number
  /** Đã có dữ liệu để agent tra chưa. `false` ⇒ bật lên cũng chưa trả lời được. */
  readonly coDuLieu: boolean
}

/**
 * Kỹ năng thuộc về lĩnh vực nào — nghịch đảo của `kyNang.ts`.
 *
 * `KY_NANG_CHUNG` KHÔNG thuộc lĩnh vực nào nên không bao giờ bị tắt theo lĩnh
 * vực: tra tài liệu, cập nhật khách, chuyển người thật là việc agent làm bất kể
 * đang nói chuyện về cái gì.
 */
const KY_NANG_CUA_LINH_VUC: Readonly<Record<string, readonly string[]>> = {
  bds: KY_NANG_TAB_BDS.map((k) => k.ten),
  // Vertical #2 chưa có kỹ năng riêng nào.
  taichinh: [],
}

/**
 * Bỏ khỏi `tools.enabled` mọi kỹ năng thuộc một lĩnh vực đang TẮT.
 *
 * Gọi lúc XUẤT BẢN, không gọi lúc gõ: người dùng tắt một lĩnh vực rồi bật lại
 * mà mất sạch lựa chọn kỹ năng của họ là một cú xoá dữ liệu không ai xin phép.
 * Bản nháp giữ nguyên; chỉ thứ GỬI ĐI mới bị lọc.
 */
export function locKyNangTheoLinhVuc(
  enabled: readonly string[],
  danhSach: readonly LinhVuc[],
): string[] {
  const tat = new Set(
    danhSach.filter((l) => !l.bat).flatMap((l) => KY_NANG_CUA_LINH_VUC[l.ma] ?? []),
  )
  return enabled.filter((t) => !tat.has(t))
}

export async function docLinhVuc(): Promise<LinhVuc[]> {
  const r = await fetch('/api/v1/linh-vuc', { credentials: 'include' })
  if (!r.ok) throw new Error('Không đọc được danh sách lĩnh vực')
  return (await r.json()) as LinhVuc[]
}

export async function datLinhVuc(ma: string, bat: boolean): Promise<LinhVuc> {
  const r = await fetch(`/api/v1/linh-vuc/${ma}`, {
    method: 'PATCH',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bat }),
  })
  if (!r.ok) throw new Error('Không đổi được trạng thái lĩnh vực')
  return (await r.json()) as LinhVuc
}
