/**
 * ⚠️ BẢN SAO VIẾT TAY của `billing.pricing_basis` — 11 dòng hạt giống của
 * migration `0943`, cập nhật theo `0948_billing_text_units` (2026-08-20).
 * KHÔNG có endpoint nào lộ bảng này, nên KHÔNG có cổng parity nào canh nó.
 * Ngày BE thêm một cơ sở tính tiền, file này nói sai mà không gì đỏ, và người
 * vận hành nhập giá vào một metric không tồn tại → dòng giá không bao giờ khớp.
 * Cùng hạng `lib/tools.ts` / `contracts/*.json` — xem mục «Fake MSW KHÔNG phải
 * nguồn sự thật» trong `CLAUDE.md` (gotcha `userCount`, sửa ở `f03da45`): một
 * bản sao không cổng canh mà bị coi là sự thật đã từng gây một vòng thiết kế
 * sai trước đây, đừng lặp lại kiểu đó với file này.
 *
 * ĐÃ YÊU CẦU BE: `GET /admin/billing/pricing-basis`. Xem spec §13.
 * Nguồn khi viết: `docs/build_module_usage&billing/pricing-schema.sql` +
 * migration `0943_billing_pricing.py` / `0948_billing_text_units.py`.
 *
 * ⚠️ Dòng `call` ĐÃ SỬA so với bản nháp đầu của task này: nháp ghi nhầm
 * `metric: 'wall_ms'` — đối chiếu lại `pricing-schema.sql` dòng
 * `('call', '', 'audio_sec', 'thời lượng cuộc gọi — phí nền tảng/phút')` và cả
 * hai migration `0943`/`0948` thì `call` tính theo `audio_sec` (giây), không
 * phải `wall_ms` (mili-giây). `per_units` theo đó là 60 (60 giây/phút), không
 * phải 60_000 (chỉ đúng khi đơn vị nguồn là mili-giây).
 */
/** Chỉ dùng NỘI BỘ tệp này — không module/test nào khác import (đo 2026-08-20). */
interface Basis {
  readonly component: string
  readonly metric: string
  readonly per_units: number
  readonly dvi: string
  /** Một số cơ sở chỉ áp cho một `purpose` cụ thể. */
  readonly purpose?: string
}

export const PRICING_BASIS: readonly Basis[] = [
  { component: 'llm', metric: 'input_tokens', per_units: 1_000_000, dvi: 'đ /1M token' },
  { component: 'llm', metric: 'output_tokens', per_units: 1_000_000, dvi: 'đ /1M token' },
  { component: 'llm', metric: 'cache_write_tokens', per_units: 1_000_000, dvi: 'đ /1M token' },
  { component: 'llm', metric: 'cache_read_tokens', per_units: 1_000_000, dvi: 'đ /1M token' },
  { component: 'embed', metric: 'text_units', per_units: 1, dvi: 'đ /ký tự' },
  { component: 'tts', metric: 'text_units', per_units: 1, dvi: 'đ /ký tự' },
  { component: 'stt', metric: 'audio_sec', per_units: 1, dvi: 'đ /giây', purpose: 'conversation' },
  {
    component: 'stt',
    metric: 'text_units',
    per_units: 1,
    dvi: 'đ /ký tự',
    purpose: 'conversation',
  },
  { component: 'stt', metric: 'wall_ms', per_units: 60_000, dvi: 'đ /phút', purpose: 'stream' },
  { component: 'vad', metric: 'audio_sec', per_units: 1, dvi: 'đ /giây' },
  { component: 'speaker_verify', metric: 'audio_sec', per_units: 1, dvi: 'đ /giây' },
  { component: 'call', metric: 'audio_sec', per_units: 60, dvi: 'đ /phút' },
  { component: 'search', metric: 'units', per_units: 1, dvi: 'đ /lượt', purpose: 'kb_web' },
]

/**
 * Luật «STT chỉ MỘT cơ sở» — HẸP HƠN so với bản 0943. Từ `0948`, vế `text_units`
 * của STT là ĐỘC LẬP và CỘNG THÊM (vendor kiểu Soniox thu hai đồng hồ), nên chỉ
 * còn cặp THỜI LƯỢNG loại trừ nhau. Index `price_item_stt_single_basis` đã nới
 * theo. Đã kiểm cả hai chiều ở BE: `audio_sec + text_units` ĐƯỢC PHÉP,
 * `audio_sec + wall_ms` BỊ CHẶN.
 */
export const STT_THOI_LUONG = ['audio_sec', 'wall_ms'] as const

export const basisCua = (component: string, metric: string) =>
  PRICING_BASIS.find((b) => b.component === component && b.metric === metric)

export const metricCua = (component: string) =>
  PRICING_BASIS.filter((b) => b.component === component)

/**
 * Bản sao viết tay của `billing.purpose` (CHỈ các dòng `billable = true`) —
 * `pricing-schema.sql` §3c. Dùng cho `<select>` `purpose` của form thêm dòng
 * giá (Task 9): tạo dòng giá cho một purpose `billable = false`
 * (`memory`/`warm_cache`/`addressee_gate`/`semcache` — tối ưu nội bộ, giá vốn)
 * là một dòng giá KHÔNG BAO GIỜ khớp, vì `rate_usage()` lọc bỏ usage của các
 * purpose đó TRƯỚC khi khớp giá (`coalesce(pu.billable, true)` trong câu SELECT
 * — vế lọc, độc lập với `price_item`). Nên danh sách chọn ở đây chỉ liệt kê
 * phần TÍNH KHÁCH; để trống (`''`) vẫn hợp lệ và có nghĩa "mọi purpose"
 * (wildcard, khớp `billing.price_item.purpose = ''`).
 *
 * ⚠️ Cùng hạng bản sao viết tay như `PRICING_BASIS` — không có endpoint nào lộ
 * bảng `billing.purpose`, không có cổng parity nào canh. Ngày BE thêm/bớt một
 * purpose thì sửa tay ở đây theo đúng `pricing-schema.sql` §3c.
 */
export const PURPOSE_TINH_KHACH: readonly string[] = [
  'conversation',
  'summary',
  'suggestions',
  'embed',
  'stream',
  'session',
  'kb_web',
]
