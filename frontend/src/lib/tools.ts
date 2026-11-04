/**
 * 11 kỹ năng của agent — tên nghiệp vụ và bảng phụ thuộc.
 *
 * ⚠ NGUỒN KHÔNG PHẢI FILE NÀY. Nguồn là `modules/config/tools.py` của repo
 * backend — cùng chỗ mà `RULES.md` sinh danh mục kỹ năng từ đó. File này là bản
 * sao cho FE, và `tests/tools-parity.test.ts` canh nó khớp `contracts/tools.json`
 * (artefact backend sinh ra rồi copy sang). Cùng cơ chế với `actions.ts`.
 *
 * VÌ SAO PHẢI LÀ MỘT NGUỒN: prompt của agent dạy gọi những kỹ năng đang bật, còn
 * màn này quyết định bật cái nào. Hai danh sách chép tay là hai danh sách sẽ
 * lệch — và lệch ở đây nghĩa là người dùng tắt một kỹ năng mà agent vẫn hứa làm
 * nó với khách. Đó đúng là lỗi AG_01 §6 đang bắt sửa.
 *
 * Không mang `moTa`: nó là câu dạy LLM, không hiện ra giao diện. Có nó trong
 * artefact để người sửa nhãn đọc được, nhưng đưa vào bundle JS là chở theo vài
 * trăm byte không ai đọc.
 */

export interface KyNang {
  readonly ten: string
  /** Tên NGHIỆP VỤ. AG_01 §II.3: không bao giờ hiện tên hàm cho người dùng. */
  readonly nhan: string
}

/** Thứ tự là thứ tự NGHIỆP VỤ, cũng là thứ tự toggle trên màn hình. */
export const MUOI_HAI_KY_NANG: readonly KyNang[] = [
  { ten: 'find_project', nhan: 'Nhận diện tên dự án' },
  { ten: 'discover_projects', nhan: 'Khám phá & giới thiệu dự án' },
  { ten: 'get_document', nhan: 'Gửi tài liệu của dự án' },
  { ten: 'search_units', nhan: 'Tìm & gợi ý căn' },
  { ten: 'kb_search', nhan: 'Tra tài liệu của workspace' },
  { ten: 'booking', nhan: 'Đặt lịch tham quan' },
  { ten: 'update_customer', nhan: 'Ghi nhận thông tin khách' },
  { ten: 'send_media', nhan: 'Gửi ảnh và video dự án' },
  { ten: 'escalate', nhan: 'Chuyển người thật' },
  { ten: 'tinh_tra_gop', nhan: 'Tính trả góp' },
  // ⚠ CHƯA AN TOÀN ĐỂ BẬT CHO TENANT THẬT (2026-09-07) — xem
  // odyssey-portal-backend/docs/superpowers/specs/2026-09-07-analyze-projects-sql-ro-portal-design.md §0:
  // role sandbox Postgres phía agent không chặn được contacts/conversations/dữ liệu
  // chưa published do GRANT SELECT ... TO PUBLIC trên tenant_data. Entry này để sẵn
  // cho lúc lỗ hổng đóng — đừng bật nó cho workspace thật trước đó.
  { ten: 'analyze_projects', nhan: 'Thống kê & tồn kho' },
]

/**
 * Kỹ năng nào cần kỹ năng nào mới chạy đúng.
 *
 * Backend validate lại đúng bảng này và TỪ CHỐI 422 — cảnh báo chỉ ở đây là
 * cảnh báo bỏ qua được bằng một `curl`. Chỗ này để người dùng thấy trước khi bị
 * từ chối, không phải để thay việc từ chối.
 */
export const PHU_THUOC: Readonly<Record<string, readonly string[]>> = {
  booking: ['find_project'],
  get_document: ['find_project'],
  send_media: ['find_project'],
}

/**
 * Tên tool đã NGHỈ → tool đã nuốt nó (merge 2026-09-07).
 *
 * Bản chép tay của `odyssey-agent/src/noble_agent/agent/agent_config.py::TOOL_ALIASES`,
 * cùng lệ với chính tệp này. Không nhét được vào `MUOI_HAI_KY_NANG`: sổ đó bị cổng
 * parity ép khớp `contracts/tools.json` đúng từng dòng, và một tên đã nghỉ nằm
 * trong đó sẽ hiện ra Agent Studio như một kỹ năng còn bật được.
 *
 * VÌ SAO CẦN: `MUOI_HAI_KY_NANG` là sổ HIỆN HÀNH, còn
 * `escalations.missing_data_tool` là NHẬT KÝ — hàng do agent bản trước-merge ghi
 * mang tên cũ và nằm đó vĩnh viễn. Không nối hai thứ thì màn /chuyen-sale in chữ
 * `check_inventory` cho sale đọc. Config tenant chưa migrate cũng còn chở tên cũ
 * (đúng lý do agent giữ `TOOL_ALIASES`), nên màn Agent Studio hưởng theo.
 */
export const TEN_DA_NGHI: Readonly<Record<string, string>> = {
  recommend_units: 'search_units',
  get_project_overview: 'discover_projects',
  check_inventory: 'analyze_projects',
}

/** Nhãn NGHIỆP VỤ của một kỹ năng. AG_01 §II.3: không bao giờ trả tên hàm —
 * tên lạ hoàn toàn rơi về «Kỹ năng khác» chứ không lộ `snake_case` ra màn. */
export function nhanCua(ten: string): string {
  const hienHanh = TEN_DA_NGHI[ten] ?? ten
  return MUOI_HAI_KY_NANG.find((k) => k.ten === hienHanh)?.nhan ?? 'Kỹ năng khác'
}

/** Các cặp [kỹ năng đang bật, thứ nó cần mà đang tắt]. Rỗng nghĩa là hợp lệ. */
export function thieuPhuThuoc(dangBat: readonly string[]): Array<[string, string]> {
  const bat = new Set(dangBat)
  return [...bat]
    .sort()
    .flatMap((ten) =>
      (PHU_THUOC[ten] ?? [])
        .filter((can) => !bat.has(can))
        .map((can): [string, string] => [ten, can]),
    )
}
