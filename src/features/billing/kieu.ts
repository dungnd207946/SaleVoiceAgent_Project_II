import type { Tien } from './dinh-dang'

/**
 * Kiểu của 11 response module `billing`.
 *
 * ⚠️ TẤT CẢ snake_case. `modules/billing` KHÔNG khai `alias_generator`, khác
 * `modules/ops` (màn /convos, /dashboard) vốn CÓ khai alias camelCase. Copy
 * pattern `res.chiPhiTong` từ màn ops sang đây ra `undefined` — không phải lỗi,
 * chỉ là `NaN` hiện thành «—» và không gì đỏ. Nguồn: hợp đồng BE
 * `odyssey-portal-backend/docs/contracts/usage-billing.md` §0.
 *
 * Bốn ngoại lệ NGƯỢC (camelCase) — tất cả ở phía admin, đánh dấu ⚠️ tại chỗ:
 * `DongGiaIn` (2 field), `GanBoGiaIn` (cả 2 field), `PreviewGia` (dict tay của
 * BE), và body gửi lên của hai model đó — KHÔNG có `populate_by_name` ở BE nên
 * gửi sai tên (vd `unit_price` thay vì `unitPrice`) là 422, không phải bị bỏ qua.
 */

/** `TongQuanOut.canh_bao` — §5 hợp đồng. KHÔNG phải chip trang trí. */
export interface CanhBao {
  /** Số cặp (component, metric) có usage nhưng CHƯA có dòng giá khớp — đang mất doanh thu NGAY LÚC NÀY, hiện như lỗi (đỏ), không phải info chip. */
  thieu_gia: number
  /** Số nhãn `purpose` agent gửi lên mà NobleX chưa xác nhận tính tiền hay không — KHÔNG lọc theo tenant. */
  nhan_chua_phan_loai: number
  /** Số event không có số đo nào (mọi cột lượng đều 0) ⇒ không tính được tiền cho event đó. */
  event_khong_so_do: number
  /** SỐ ĐẾM (không phải tỷ lệ/%) event `component='llm'` có `exact=false` — đo THIẾU token. Đừng tự chia ra phần trăm. */
  llm_khong_chinh_xac: number
}

export interface TongQuan {
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  /**
   * Thời lượng `component='call'` trong kỳ — KHÔNG cộng chéo component (BE
   * sửa 2026-08-20, commit `9d78d04`). TRƯỚC đó field này cộng chéo
   * vad+call+stt+tts+speaker_verify và ra số gấp ~2.64× thời lượng cuộc gọi
   * thật — đừng viết lại phép cộng đó ở FE (kể cả khi tự tính từ `events`).
   * Phiên không có hàng `call` (vd phiên chat) trả `0`, không phải `null`.
   */
  voice_sec: number
  so_phien: number
  so_key: number
  chi_phi: Tien
  /** Phần của `chi_phi` do dữ liệu ngoài (purpose `kb_web`). */
  chi_phi_du_lieu_ngoai?: Tien
  currency: string
  canh_bao: CanhBao
}

/** Một component trong MỘT ngày — nguồn của tooltip biểu đồ. */
export interface PhanNgay {
  component: string
  chi_phi: Tien
}

/** Một ngày của kỳ — mục ② «Tiền đi đâu», trục thời gian. */
export interface DongNgay {
  /** `YYYY-MM-DD`. */
  ngay: string
  /**
   * `'0'` là NGÀY THẬT KHÔNG PHÁT SINH, không phải ngày thiếu dữ liệu — BE
   * chèn đủ mọi ngày của kỳ (`repo.theo_ngay()`). Đừng lọc bỏ hàng 0 trước
   * khi vẽ: bỏ đi là biểu đồ nối thẳng qua chỗ trũng, tức vẽ ra một mức tiền
   * dương cho ngày agent không chạy.
   */
  chi_phi: Tien
  /**
   * Tách theo component của CHÍNH ngày đó, đã xếp theo tiền giảm dần. Rỗng ở
   * ngày không phát sinh. `chi_phi` ở trên = tổng mảng này (BE cộng từ cùng
   * những hàng ấy) — đừng cộng lại ở FE để «kiểm tra», hai số đó cùng nguồn.
   */
  phan: PhanNgay[]
}

/** Một component trong kỳ — mục ②, thẻ phải. */
export interface DongComponent {
  component: string
  so_event: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  audio_sec: number
  text_units: number
  units: number
  /**
   * `'0'` KHÔNG có nghĩa "không dùng" — nghĩa là chưa dòng giá nào khớp
   * component này (đang nằm trong `canh_bao.thieu_gia`), hoặc purpose của nó
   * `billable = false`. UI phải nói ra sự khác biệt đó, đừng hiện `0 ₫` trơn.
   */
  chi_phi: Tien
  /** Phần của `chi_phi` do dữ liệu ngoài. */
  chi_phi_du_lieu_ngoai?: Tien
}

export interface PhanTich {
  theo_ngay: DongNgay[]
  theo_component: DongComponent[]
  chi_phi_tong: Tien
  currency: string
}

/**
 * Các cột TÁCH `chi_phi` của CHÍNH một hàng theo dịch vụ — chung cho bảng «Lượt dùng»
 * ba chiều (khoá · người tạo · phiên). Trong MỘT hàng, tổng các trường này THƯỜNG bằng
 * `chi_phi` — trừ khi hàng có usage của một component NGOÀI các mã này (`component` là
 * `text` không CHECK phía BE), khi đó phần tiền đó vẫn cộng vào `chi_phi`/`chi_phi_tong`
 * nhưng không lộ ra ở cột nào (xem `canh_bao.thieu_gia`). Đừng tự cộng lại để "kiểm tra" —
 * `chi_phi` đã là con số đúng của hàng, đúng lý lẽ `DongNgay.chi_phi`.
 */
export interface ChiPhiTheoDichVu {
  chi_phi_llm: Tien
  chi_phi_tts: Tien
  chi_phi_stt: Tien
  chi_phi_embed: Tien
  chi_phi_search?: Tien
  chi_phi_call: Tien
  chi_phi_vad: Tien
  chi_phi_speaker_verify: Tien
}

export interface DongKey extends ChiPhiTheoDichVu {
  /**
   * `null` = nhóm «Chưa phân loại (không có khoá)» — usage KHÔNG gắn được với
   * khoá nào (agent ghi usage trước khi tạo phiên, hoặc conversation không có
   * khoá). KHÔNG ĐƯỢC ẩn khỏi UI/khỏi tổng: usage của nhóm này vẫn được tính
   * tiền và cộng vào `chi_phi_tong` — lọc bỏ dòng này mà vẫn hiện
   * `chi_phi_tong` là tổng dòng < tổng hiển thị.
   */
  agent_key_id: number | null
  /** Hàng hệ thống: usage của dữ liệu ngoài, không thuộc khoá nào. */
  du_lieu_ngoai?: boolean
  /** `''` khi `agent_key_id === null` (COALESCE về rỗng, không phải `null`). Tự hiện nhãn "Chưa phân loại" — BE KHÔNG gửi nhãn hiển thị nào cho ca này. */
  label: string
  key_prefix: string
  nguoi_tao: string
  nguoi_tao_ten: string | null
  da_thu_hoi: boolean
  so_phien: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  voice_sec: number
  so_event: number
  chi_phi: Tien
}

export interface DanhSachKey {
  items: DongKey[]
  total: number
  /** Tổng TOÀN BỘ `rated_usage` của tenant/khoảng — CÓ gồm nhóm `agent_key_id: null`. Đối chiếu đúng bằng tổng các hàng của `items` (kể cả hàng null). */
  chi_phi_tong: Tien
  currency: string
}

export interface DongOwner extends ChiPhiTheoDichVu {
  /** `null` = cùng nhóm "chưa phân loại" như `DongKey` (sửa 2026-08-20: trước đó INNER JOIN làm rớt nhóm này khỏi màn theo-owner). */
  user_id: string | null
  /** Hàng hệ thống: usage của dữ liệu ngoài. */
  du_lieu_ngoai?: boolean
  ten: string | null
  email: string | null
  so_key: number
  so_phien: number
  /**
   * Sáu cột LƯỢNG (thêm BE 2026-08-24) — khớp ĐÚNG bộ cột của `DongKey` để bảng
   * «Lượt dùng chi tiết» đổi chiều gộp mà không đổi bộ cột.
   *
   * ⚠️ `chi_phi = 0` ở đây nghĩa là «chưa có giá», KHÔNG phải «không dùng» —
   * `repo.theo_owner()` đổi bảng dẫn sang `usage_events` cùng lượt, nên owner có
   * số đo mà chưa được định giá KHÔNG còn biến khỏi bảng.
   * ⚠️ `voice_sec` CHỈ đếm `component = 'call'`. Đừng tự cộng `audio_sec` chéo
   * component để suy ra nó — bốn quãng audio chồng lấn nhau trong thời gian.
   */
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  voice_sec: number
  so_event: number
  chi_phi: Tien
}

/**
 * SỐ ĐO của một component trong MỘT ngày — `GET /billing/usage-by-day`.
 *
 * KHÔNG có trường tiền nào, và đó là hợp đồng chứ không phải thiếu sót: `/usage`
 * là màn LƯỢNG. Xem `docs/contracts/usage-billing.md` §`/billing/usage-by-day`.
 *
 * ⚠️ KHÔNG cộng các cột này qua nhiều component. `audio_sec` của
 * `vad`/`stt`/`call` đo những quãng CHỒNG LẤN nhau trong thời gian — cộng chéo
 * ra một con số không tồn tại (đo được 386,38s cho một cuộc gọi thật 142,44s).
 */
export interface PhanUsageNgay {
  component: string
  so_event: number
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  audio_sec: number
  text_units: number
  units: number
  /**
   * `wall_ms` của RIÊNG `purpose='stream'` — mili giây, không phải giây.
   *
   * ⚠️ KHÁC tổng `wall_ms` của component: bên agent ghi `wall_ms` cho MỌI event
   * như một độ trễ xử lý, chỉ vế `stream` mới là «thời gian stream mở» mà
   * `billing.pricing_basis` đem tính. BE đã lọc sẵn (bất biến 5 của
   * `repo.usage_theo_ngay()`) — đừng cộng bù thêm gì ở đây.
   */
  wall_ms_stream: number
  /**
   * `text_units` của RIÊNG `purpose='conversation'` — KÝ TỰ transcript của `stt`.
   *
   * ⚠️ KHÔNG thay `text_units`: cột kia là số đo chính của `tts`/`embed`. Với
   * `tts` hai cột bằng nhau (mọi dòng `tts` đều `conversation`) — đừng suy từ đó
   * rằng chúng thay thế được cho nhau.
   */
  text_units_hoi_thoai: number
  /** in + out + cache_read của dữ liệu ngoài (purpose `kb_web`). */
  token_du_lieu_ngoai?: number
  text_units_du_lieu_ngoai?: number
}

/** Một NGÀY của kỳ. `phan` RỖNG = ngày đã ĐO và không có usage nào — không
 *  phải ngày thiếu dữ liệu, và biểu đồ phải vẽ nó chạm đáy chứ không nối thẳng
 *  qua. `so_phien` là thuộc tính của NGÀY (không của component) và KHÔNG cộng
 *  được qua các ngày: một phiên bắc qua nửa đêm được đếm ở cả hai ngày. */
export interface UsageNgay {
  ngay: string
  so_phien: number
  phan: PhanUsageNgay[]
}

export interface UsageTheoNgay {
  theo_ngay: UsageNgay[]
}

export interface PhienUsage extends ChiPhiTheoDichVu {
  session_id: string
  agent_key_id: number | null
  key_label: string | null
  customer_name: string | null
  phone: string | null
  channel: string
  bat_dau: string | null
  so_turn: number
  /** Bảng «Lượt dùng theo phiên» của `/billing` KHÔNG hiện hai cột này (thay
   *  bằng bảy cột `chi_phi_<component>` ngay dưới, 2026-08-27) — màn LƯỢNG
   *  `/usage` (bảng riêng, `BangLuotDungUsage.tsx`) vẫn hiện, nên field GIỮ. */
  input_tokens: number
  output_tokens: number
  /** Cùng ngữ nghĩa `TongQuan.voice_sec` — thời lượng `call` của riêng phiên này, không cộng chéo component. */
  voice_sec: number
  chi_phi: Tien
  exact: boolean
}

export interface DanhSachPhien {
  items: PhienUsage[]
  total: number
}

export interface EventUsage {
  event_id: number
  seq: number
  /** XẤP XỈ — TTS của lượt N có thể nằm trong lô ghi nhận của lượt N+1. Đừng để người dùng đối chiếu tiền theo từng lượt bằng field này; xem `ChiTietPhien.ghi_chu_turn`. */
  turn_idx: number | null
  component: string
  purpose: string
  /** `''` ở component audio (DEFAULT '', không NULL) — hiện «—», dùng `rong()` của `dinh-dang.ts`. */
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  /** Giây audio của MỘT component, tại event này — chỗ DUY NHẤT của module trả `audio_sec` tách theo component. ĐỪNG tự cộng `audio_sec` của nhiều event/component lại thành "tổng giây audio" — đó đúng là phép cộng chéo mà `voice_sec` cấp tổng đã bỏ (mục 3 hợp đồng BE). Hiện từng component một dòng/một thanh riêng. */
  audio_sec: number
  /**
   * ⚠️ Đổi ngữ nghĩa 2026-08-20 (migration `0948`, bên agent chuẩn hoá): nay
   * là SỐ LẦN GỌI/sự kiện, THỐNG NHẤT cho MỌI component (lời gọi LLM, clause
   * TTS đã synth, lần mở stream STT, lần verify giọng, lời gọi embed).
   * ĐỪNG dùng field này để giải thích tiền `tts`/`embed` — đó là việc của
   * `text_units`. Trước đây mỗi component tự hiểu `units` một kiểu khác nhau
   * (`tts` là số ký tự, `embed` là số đoạn) — bản cũ đã bỏ.
   */
  units: number
  /**
   * Lượng text theo KÝ TỰ (cột mới, migration `0948`). Là cơ sở tính tiền
   * của `tts` (ký tự đưa vào TTS) và `embed` (ký tự đem embed, đ/ký tự);
   * với `stt`/`conversation` đây là vế CỘNG THÊM vào `audio_sec` (hai cơ sở
   * cộng nhau — luật "STT chỉ một cơ sở" chỉ áp cho cặp THỜI LƯỢNG
   * audio_sec/wall_ms, không áp cho text_units).
   * ⚠️ Ví dụ thật của TTS: `units: 7, text_units: 1115` — 7 clause đã synth,
   * 1115 ký tự đưa vào TTS (tiền tính theo con số thứ hai).
   * Dòng ghi TRƯỚC 2026-08-20 mang layout cũ: `text_units = 0` và không được
   * tính tiền cho phần ký tự (dữ liệu dev/test, BE xác nhận không backfill).
   */
  text_units: number
  exact: boolean
  chi_phi: Tien
  occurred_at: string
}

export interface ChiTietPhien {
  phien: PhienUsage
  events: EventUsage[]
  /**
   * Câu do chính BE soạn sẵn, giải thích `turn_idx` xấp xỉ. Màn chi tiết
   * phiên PHẢI hiện NGUYÊN VĂN field này (banner/tooltip) — không hiện thì
   * người dùng đối chiếu tiền theo từng lượt, thấy lệch, và báo "hệ thống
   * tính sai" trong khi hệ thống đúng (tổng theo phiên luôn đúng).
   */
  ghi_chu_turn: string
}

export interface BoGia {
  id: number
  code: string
  name: string
  currency: string
  status: 'active' | 'inactive'
  is_default: boolean
  created_at: string
}

/**
 * ⚠️ camelCase — response DUY NHẤT của cả module không snake_case. BE trả một
 * dict viết tay `{"chiPhi": "...", "currency": "..."}` ở `preview_bang_gia`,
 * KHÔNG qua model Pydantic có alias. Preview là PER-TENANT và trả MỘT tổng,
 * không tách theo component.
 */
export interface PreviewGia {
  chiPhi: Tien
  currency: string
}

/**
 * ⚠️ Body GỬI LÊN `POST .../price-versions/{pb}/items`: CHỈ `unitPrice`/
 * `perUnits` camelCase, các field còn lại giữ tên thường. Model BE khai
 * `extra="forbid"` và KHÔNG có `populate_by_name` ⇒ gửi `unit_price` thay vì
 * `unitPrice` là `422 VALIDATION_ERROR`, không phải bị bỏ qua im lặng.
 */
export interface DongGiaIn {
  component: string
  purpose: string
  provider: string
  model: string
  metric: string
  unitPrice: string
  perUnits: number
  note: string
}

/**
 * ⚠️ Body GỬI LÊN `POST .../tenants/{tenant_id}/price-version`: CẢ HAI field
 * camelCase (khác `DongGiaIn` — ở đây không có field nào giữ tên thường).
 * `effectiveFrom` phải tz-aware. Endpoint này KHÔNG kiểm bảng giá đã active
 * hay đủ giá trước khi gán (xem hợp đồng BE §6) — chỉ chặn mốc lùi vào quá
 * khứ đã định giá (`MOC_QUA_KHU_DA_DINH_GIA`) và mốc trước khoảng đang mở
 * (`MOC_TRUOC_KHOANG_DANG_MO`).
 */
export interface GanBoGiaIn {
  priceVersionId: number
  effectiveFrom: string
}
