/**
 * Client HTTP của module agent (M5). Hình dạng lỗi giống mọi endpoint khác:
 * `{error:{code,message}}` — xem `docs/contracts/auth.md` ở repo backend.
 *
 * Kiểu `ConfigPayload` ở đây là bản chép tay của `modules/config/contracts.py`.
 * Nguồn là bên Python: nó vừa dựng form vừa render bundle, nên hai bên lệch
 * nghĩa là màn hình cho sửa một trường mà agent không đọc. Cổng canh chỗ này
 * hiện là 422 của backend, không phải một test — khoảng hở đã biết, và nó khép
 * lại khi `contracts/openapi.json` có (spec tổng §4①, còn treo).
 */
import { goi } from '@/lib/http'

/** Bản chép của `contracts.SCHEMA_VERSION_HIEN_TAI`. Backend TỪ CHỐI `PUT /config`
 *  (409 `CONFIG_SCHEMA_CU`) khi `schema_version` của một role khác số này — form này là
 *  client v3, nên nó phải khai đúng 3, nếu không nó tự khoá đường Lưu của chính mình. */
export const SCHEMA_VERSION_HIEN_TAI = 3

export interface PhongBan {
  ten: string
  khi_nao: string
}

/** Một mục của từ điển cách đọc TTS. Bản chép tay của `NormalizationEntry` phía Python. */
export interface NormalizationEntry {
  term: string
  read_as: string
}

/** Khớp `Field(max_length=…)` phía backend — quá thì 422. */
export const NORMALIZATION_TERM_TOI_DA = 60
export const NORMALIZATION_READ_AS_TOI_DA = 200
export const NORMALIZATION_SO_MUC_TOI_DA = 200

export interface ConfigPayload {
  schema_version: number
  danh_tinh: {
    ten_agent: string
    ten_thuong_hieu: string
    /** Agent tự gọi mình là gì (VD `em`). Tách khỏi `goi_khach` từ schema v3. */
    tu_xung: string
    /** Agent gọi khách là gì (VD `anh/chị`). */
    goi_khach: string
    loi_chao: string
  }
  pham_vi: {
    linh_vuc: string
    lam_gi: string
    khong_lam_gi: string
    phong_ban: PhongBan[]
    cau_tu_choi: string
  }
  giong: { giong_dieu: string; do_dai: string }
  tools: { enabled: string[] }
  /** Lớp CHỒNG LÊN bộ nền trong repo agent, không thay nó. Trùng khoá thì tenant thắng. */
  tts_normalization: NormalizationEntry[]
}

/** Người dùng agent. Từ backend `0967` role là DỮ LIỆU của workspace
 *  (`tenant_data.role_config`), không còn danh sách đóng: `VaiTro` là `key` — bất biến,
 *  BE sinh từ tên lúc tạo, là khoá của `PUT /config`. Tên hiển thị nằm ở `VaiTroMeta.ten`. */
export type VaiTro = string

/** Role mặc định: mọi workspace luôn có, không xoá được (bản chép `contracts.KEY_ROLE_MAC_DINH`). */
export const KEY_ROLE_MAC_DINH = 'customer'

export interface VaiTroMeta {
  key: VaiTro
  ten: string
  /** MÃ icon của tab (bảng mã ở `iconVaiTro.ts`). `null`/mã lạ ⇒ FE tự chọn theo `key`. */
  icon: string | null
  /** Role mặc định (`customer`) — không xoá được. */
  macDinh: boolean
}

export interface VaiTroOut extends VaiTroMeta {
  cauHinh: ConfigPayload
  /** True = role này chưa từng được lưu, `cauHinh` là bộ platform sinh (AG_01 bước 2). */
  laMacDinh: boolean
}

/** Cấu hình theo `key` của MỌI role — đúng hình dạng `cauHinh` trong body `PUT /config`. */
export type CauHinh = Record<VaiTro, ConfigPayload>

export interface CauHinhOut {
  /** Theo thứ tự tab. Luôn có ít nhất role mặc định. */
  vaiTro: VaiTroOut[]
  /** Số đếm tăng mỗi lần Lưu/đổi role (mọi role cùng số). `null` = chưa lưu lần nào. */
  version: number | null
  /** Trần số role của một workspace — hết chỗ thì ẩn nút «Thêm role». */
  soRoleToiDa: number
}

/** Chip trạng thái của AG_01 §II.3 — SUY từ agent đang chạy, không phải cờ portal. */
export type TrangThaiAgent = 'dang_cap' | 'dang_ap_dung' | 'san_sang' | 'mat_ket_noi'

export interface TrangThaiOut {
  trangThaiAgent: TrangThaiAgent
  version: number | null
}

export interface LuuOut {
  /** Số vừa ghi — agent nạp lại cấu hình khi thấy số này đổi. */
  version: number
  /** Theo role: trường nào khác so với bản đang lưu trước đó (BR15). */
  truongDaDoi: Record<VaiTro, string[]>
}

export type RoleOut = VaiTroMeta

export const docCauHinh = () => goi<CauHinhOut>('/api/v1/config')
export const docTrangThai = () => goi<TrangThaiOut>('/api/v1/config/status')

/** Lưu = ÁP DỤNG NGAY cho mọi role, một giao dịch (backend `0966`).
 *
 *  Tập khoá của `c` phải trùng ĐÚNG tập role đang có — lệch (tab khác vừa thêm/xoá role)
 *  thì 409 `CONFIG_ROLE_DA_DOI` và không gì được ghi.
 *
 *  Không còn bản nháp · xem trước · xuất bản · quay lui: `/config/draft`,
 *  `/config/preview`, `/config/publish`, `/config/versions` đã bỏ phía backend (404). */
export const luuCauHinh = (c: CauHinh) =>
  goi<LuuOut>('/api/v1/config', { method: 'PUT', body: JSON.stringify({ cauHinh: c }) })

/** Ba thao tác role (backend `0967`) — ÁP DỤNG NGAY, không chờ «Lưu và áp dụng»: chúng
 *  đổi TẬP role, không đổi nội dung cấu hình. `saoChepTu` = key role nguồn để chép cấu
 *  hình; bỏ trống thì role mới dùng bộ mặc định. */
export const taoRole = (ten: string, saoChepTu: VaiTro | null, icon: string) =>
  goi<RoleOut>('/api/v1/config/roles', {
    method: 'POST',
    body: JSON.stringify({ ten, saoChepTu, icon }),
  })
/** Đổi tên và/hoặc icon — khoá vắng mặt là giữ nguyên. `key` không bao giờ đổi. */
export const suaRole = (key: VaiTro, thay: { ten?: string; icon?: string }) =>
  goi<RoleOut>(`/api/v1/config/roles/${encodeURIComponent(key)}`, {
    method: 'PATCH',
    body: JSON.stringify(thay),
  })
export const xoaRole = (key: VaiTro) =>
  goi<undefined>(`/api/v1/config/roles/${encodeURIComponent(key)}`, { method: 'DELETE' })
