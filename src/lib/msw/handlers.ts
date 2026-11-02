/**
 * MSW handler — spec §4②: mỗi module ship kèm fake để module khác dev được
 * mà không cần backend chạy.
 *
 * File này chỉ có seam của M2a (`/api/v1/me`). Module khác THÊM file
 * `features/<module>/msw.ts` rồi cắm vào `HANDLERS` bên dưới — cùng khuôn với
 * nav-registry: thêm một dòng, không sửa gì khác.
 *
 * Ba workspace giả lấy đúng tên trong prototype để so màn với thiết kế được.
 */
import { http, HttpResponse } from 'msw'
import { ALL_ACTIONS } from '../actions'
import type { Session } from '../session'
import { avatarGia } from './avatarGia'
import { opsHandlers } from '@/features/ops/msw'
import { qualityHandlers } from '@/features/quality/msw'
import { nguonHandlers } from '@/features/realestate/msw'
import { billingHandlers } from '@/features/billing/msw'
import { nhatKyHandlers } from '@/features/platform/mswNhatKy'
import { nhanVatHandlers } from '@/features/platform/mswNhanVat'
import { kichBanHandlers } from '@/features/kich-ban/msw'
import { kbWebHandlers } from '@/features/kb-web/msw'

export const FAKE_SESSION: Session = {
  user: {
    id: 'u_fake_dang',
    name: 'Trần Hải Đăng',
    email: 'dang@anphuland.vn',
    initials: 'TĐ',
    // Backend thật sinh bằng DiceBear (`core/avatar.py`, seed = name). Fake chỉ
    // cần LÀ một data URI SVG hợp lệ — bản sao viết tay, không có cổng parity.
    avatar: avatarGia('TĐ'),
    coMatKhau: true,
    phone: null,
    jobTitle: null,
  },
  // Tổ chức sở hữu ba workspace dưới đây (migration 0102). Fake để cùng một org
  // là đúng: backend không bao giờ trả workspace của hai tổ chức trong một phiên.
  // `plan: null` — khớp backend thật. `control.tenants` cố ý không có cột plan
  // (migration 0002) và màn billing đã hoãn khỏi MVP. Fake trả 'Growth' thì màn
  // giả đẹp hơn màn thật, và không ai phát hiện tới lúc tắt MSW.
  workspaces: [
    { id: 'ws_anphu', slug: 'anphu', name: 'An Phú Land', plan: null },
    { id: 'ws_sunrise', slug: 'sunrise', name: 'Sunrise Land', plan: null },
    { id: 'ws_haven', slug: 'haven', name: 'Havenly Property', plan: null },
  ],
  currentWorkspaceId: 'ws_anphu',
  // Đủ 15 nhóm — dev FE thấy được mọi mục nav.
  // Muốn thử giao diện của vai trò hẹp hơn: sửa dòng này tại chỗ, hoặc dùng
  // `server.use(...)` trong test (xem tests/shell.test.tsx).
  actions: ALL_ACTIONS,
}

/** Cấu hình agent giả — cùng hình dạng `ConfigPayload` v3 của backend (M5).
 *
 * `schema_version` PHẢI là 3, khớp `contracts.SCHEMA_VERSION_HIEN_TAI`. Payload này
 * mang tên trường v3 (`tu_xung`/`goi_khach` tách đôi) nên khai `2` là một hình dạng
 * KHÔNG TỒN TẠI được: backend thật trả 409 `DRAFT_SCHEMA_CU` lúc publish. Một mock
 * nói dối về hình dạng response là mầm của đúng lớp bug mà nhánh này đang chữa. */
export const FAKE_CONFIG = {
  schema_version: 3,
  danh_tinh: {
    ten_agent: 'Mai',
    ten_thuong_hieu: 'An Phú Land',
    tu_xung: 'em',
    goi_khach: 'anh/chị',
    loi_chao: '',
  },
  pham_vi: {
    linh_vuc: 'realestate',
    lam_gi: 'Tư vấn dự án và đặt lịch tham quan.',
    khong_lam_gi: 'Hậu mãi và giá riêng — chuyển người thật.',
    phong_ban: [{ ten: 'CSKH', khi_nao: 'Khách hỏi việc ngoài phạm vi tư vấn' }],
    cau_tu_choi: '',
  },
  giong: { giong_dieu: 'than_thien', do_dai: 'trung_binh' },
  tools: {
    enabled: [
      'find_project',
      'discover_projects',
      'get_document',
      'search_units',
      'kb_search',
      'booking',
      'update_customer',
      'send_media',
      'escalate',
    ],
  },
}

/** Tập role của fake `/config` (backend `0967`) — có TRẠNG THÁI, cùng khuôn `USERS_GIA`.
 *  Test nào thêm/xoá role qua fake này phải gọi `RESET_ROLE_CONFIG_GIA()`. */
const ROLE_CONFIG_BAN_DAU = [
  { key: 'customer', ten: 'Khách hàng', icon: 'khach' },
  { key: 'sale', ten: 'Sale', icon: 'sale' },
]
const ROLE_CONFIG_GIA: { key: string; ten: string; icon: string | null }[] =
  structuredClone(ROLE_CONFIG_BAN_DAU)
export function RESET_ROLE_CONFIG_GIA(): void {
  ROLE_CONFIG_GIA.splice(0, ROLE_CONFIG_GIA.length, ...structuredClone(ROLE_CONFIG_BAN_DAU))
}

// ─── Dữ liệu giả của M4 (KB Bất động sản) ───────────────────────────────────
// Một bản ghi cho mỗi thực thể, dùng lại ở mọi handler bên dưới: sửa một chỗ là
// cả năm thực thể vẫn khớp nhau (`projectCode`/`zoneCode`/`unitCode` phải trùng,
// nếu không thì dropdown phân khu của form căn trỏ vào một mã không tồn tại).

export const FAKE_DU_AN = {
  id: 1,
  projectCode: 'VHOP2',
  name: 'Vinhomes Ocean Park 2',
  category: ['chung_cu', 'biet_thu'],
  region: 'Hà Nội',
  address: 'Gia Lâm, Hà Nội',
  investor: 'Vinhomes',
  developer: 'Vinhomes',
  totalLandAreaM2: 4_580_000,
  floorAreaM2: 1_200_000,
  buildDensityPct: 21.5,
  productScale: '3 toà · 1.240 căn hộ · 68 shophouse',
  amenities: 'Biển hồ nước mặn, công viên trung tâm, trường liên cấp.',
  ownershipForm: 'Sổ hồng lâu dài',
  handoverStandard: [
    {
      item: 'Mặt ngoài',
      material: 'Hoàn thiện sơn, ốp đá chân tường',
      brand: '',
      origin: '',
      note: '',
    },
    { item: 'Bên trong', material: 'Bàn giao thô', brand: '', origin: '', note: '' },
  ],
  totalInvestmentVnd: 87_000_000_000_000,
  salePhase: 'dang_ban',
  overview: 'Đại đô thị biển hồ phía đông Hà Nội, quy mô 458 ha.',
  link360: 'https://kuula.co/share/vhop2',
  coverMediaId: null,
  mapMediaId: null,
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
  totalUnits: 1240,
  numBuildings: 3,
  managementFeeVndM2: 15000,
  parkingCarFeeVnd: 1_500_000,
  parkingMotoFeeVnd: 120_000,
}

export const FAKE_PHAN_KHU = {
  id: 10,
  projectCode: 'VHOP2',
  zoneCode: 'ZURICH',
  name: 'Zurich',
  category: 'chung_cu',
  productScale: '2 toà · 620 căn',
  overview: 'Phân khu căn hộ view hồ.',
  coverMediaId: null,
  mapMediaId: null,
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
  salePhase: 'dang_ban',
  note: 'Sát hồ trung tâm',
  amenities: 'Bể bơi riêng, vườn nướng BBQ',
  numBuildings: 2,
  totalUnits: 620,
}

export const FAKE_TOA = {
  id: 7,
  projectCode: 'VHOP2',
  zoneCode: 'ZURICH',
  buildingCode: 'A',
  name: 'Toà A',
  numFloors: 30,
  numBasements: 2,
  unitsPerFloor: 12,
  elevatorsPassenger: 4,
  elevatorsService: 1,
  carSlots: 250,
  motoSlots: 900,
  ceilingHeightM: 3.1,
  facing: 'dong_nam',
  salePhase: 'dang_ban',
  amenities: 'Sảnh khách sạn, bể bơi tầng mái',
  overview: 'Toà nhìn thẳng ra hồ trung tâm.',
  status: 'published',
  unitCount: 1,
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

export const FAKE_CAN = {
  id: 41,
  projectCode: 'VHOP2',
  zoneCode: 'ZURICH',
  zoneName: 'Zurich',
  unitCode: 'ZR-A-1203',
  productType: 'chung_cu',
  bedrooms: 3,
  block: 'A',
  floor: 12,
  numFloors: 1,
  direction: 'dong_nam',
  areaBuiltM2: 78.5,
  areaWallM2: 82,
  areaLandM2: null,
  priceVnd: 5_600_000_000,
  pricePerM2Vnd: 71_337_579,
  saleStatus: 'available',
  imageUrl: null,
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
  views: ['ho', 'noi_khu'],
  isCorner: true,
  openSides: 2,
  bathrooms: 2,
  handoverCondition: 'hoan_thien',
  hrBalconyM2: 4.5,
  hrLoggiaM2: 2,
  lrFrontageM: null,
  lrDepthM: null,
  lrRoadWidthM: null,
}

export const FAKE_TAI_LIEU = {
  id: 70,
  projectCode: 'VHOP2',
  title: 'Chính sách bán hàng Q3',
  body: 'Chiết khấu thanh toán nhanh, tiến độ 8 đợt…',
  fileUrl: 'tenants/fake/kb-bds/abc/csbh-q3.pdf',
  bodyChoDuyet: false,
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

export const FAKE_MEDIA = {
  id: 90,
  projectCode: 'VHOP2',
  zoneCode: null,
  unitCode: null,
  contentType: 'image',
  category: 'tong_quan',
  caption: 'Toàn cảnh dự án',
  fileName: 'toan-canh.webp',
  mediaUrl: 'tenants/fake/kb-bds/deadbeef/toan-canh.webp',
  thumbUrl: null,
  contentHash: 'deadbeef',
  uploadedBy: 'u_fake_dang',
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

const FAKE_DU_AN_THIEU = {
  ...FAKE_DU_AN,
  id: 2,
  projectCode: 'CHUAXONG',
  name: 'Dự án chưa xong',
  overview: '',
  status: 'draft',
}

/* ── M2b — user giả CÓ TRẠNG THÁI ────────────────────────────────────────────
 *
 * Xem khối handler `/api/v1/members` dưới đây để biết vì sao có trạng thái thay vì
 * hằng số. Kiểu khai tại chỗ chứ không import từ `features/auth/api`: MSW là hạ
 * tầng của `lib/`, và `lib/` biết hình dạng endpoint của một module là chiều phụ
 * thuộc mà `tests/module-boundaries.test.ts` cấm (xem ALLOWLIST của nó).
 */
/**
 * `roleId` trỏ vào `VaiTroToChucGia.id` (bàn giả vai trò, khai Ở DƯỚI trong
 * cùng file này) — KHÔNG còn 1-trong-4 mã cố định. Đây chính là chỗ liên thông
 * Task 8 phải dựng: `USERS_GIA` và `VAI_TRO_GIA` giờ có một CẦU NỐI thật
 * (`roleId`), thay vì hai bàn giả sống tách biệt như trước. Hai bàn này hiện
 * ra ở hai TAB của `/users` (Thành viên và Vai trò).
 */
interface MembershipGia {
  workspaceId: string
  roleId: string
  expiresAt: string | null
}

interface UserGia {
  id: string
  email: string
  name: string
  phone: string | null
  jobTitle: string | null
  lifecycle: 'pending' | 'active' | 'suspended'
  createdAt: string
  memberships: MembershipGia[]
}

/**
 * Một dòng membership CÒN HIỆU LỰC — không hạn, hoặc hạn còn ở tương lai.
 *
 * MỘT nguồn cho luật này: mọi chỗ hỏi người này ĐANG có quyền gì PHẢI gọi hàm
 * này thay vì viết lại biểu thức — như phép lọc thành viên của `GET /members`:
 * nó trả lời về quyền HIỆN TẠI, nên một vé đã chết không được tính.
 *
 * ⚠ KHÔNG dùng cho `userCount` của vai trò. Đó là câu hỏi KHÁC — còn hàng nào
 * trỏ tới vai trò này không, tức có xoá được vai trò không — và backend trả lời
 * bằng một `count(*)` KHÔNG lọc `expires_at`. Xem `soNguoiDungVaiTro()` ở dưới:
 * bản trước gọi hàm này ở đó và vì thế fake đi NGƯỢC backend.
 */
function conHieuLuc(m: MembershipGia): boolean {
  return !m.expiresAt || new Date(m.expiresAt).getTime() > Date.now()
}

/**
 * `roleId` -> TÊN vai trò hiện tại. MỘT chỗ dịch, dùng bởi `GET`/`PATCH /members`.
 *
 * `?? roleId` (rơi về chính id) chứ không phải `?? 'Không rõ'`: một id rò ra chỗ
 * đáng lẽ là tên là TÍN HIỆU — nó nói thẳng rằng membership đang trỏ tới một vai
 * trò không có trong `VAI_TRO_GIA` (của tổ chức khác, hoặc bịa ra), đúng thứ cổng
 * 422 `ROLE_NOT_FOUND` của `/members` tồn tại để chặn. KHÔNG kể đã xoá vào đây: từ khi
 * `soNguoiDungVaiTro` đếm như backend, `DELETE /roles/:id` từ chối mọi vai trò
 * còn membership trỏ tới, nên một vai trò đã xoá không thể còn ai trỏ tới.
 *
 * Khai SAU `USERS_GIA` nhưng đọc `VAI_TRO_GIA` (khai còn XA hơn ở dưới) —
 * an toàn: đây là hàm, thân hàm chỉ chạy lúc handler nhận request, tức sau khi
 * toàn bộ module đã chạy xong và mọi `const` đã có giá trị.
 */
function tenVaiTroGia(roleId: string): string {
  return VAI_TRO_GIA.find((r) => r.id === roleId)?.name ?? roleId
}

/** Đúng khuôn `{error:{code,message}}` của `api/loi.py` — FE chỉ đọc một hình dạng. */
function loiGia(status: number, code: string, message: string) {
  return HttpResponse.json({ error: { code, message } }, { status })
}

// `tsconfig` bật `noUncheckedIndexedAccess`, nên `workspaces[0]` có kiểu
// `Workspace | undefined` — và điều đó ĐÚNG cả về nghĩa: một ngày ai đó rút
// FAKE_SESSION về một workspace thì bàn giả này không được vỡ im lặng.
const WS_GIA_1 = FAKE_SESSION.workspaces[0]?.id ?? 'ws_anphu'
const WS_GIA_2 = FAKE_SESSION.workspaces[1]?.id ?? WS_GIA_1

/**
 * Workspace ĐANG MỞ — biến ghi được, KHÔNG đọc `FAKE_SESSION.currentWorkspaceId`
 * (hằng, đứng yên suốt phiên).
 *
 * Vì sao phải có: `POST /me/workspace` trước đây chỉ TRẢ VỀ một bản sao mang
 * `currentWorkspaceId` mới mà không ghi lại đâu cả, nên sau khi bấm switcher thì
 * phiên phía FE đã sang workspace khác trong khi `GET /members` vẫn lọc theo
 * workspace khởi đầu. `MemberList` lấy `workspaceId` từ `session`, tức hàng nó
 * HIỆN và hàng nó PATCH đến từ hai workspace khác nhau — rò dữ liệu xuyên
 * workspace, đúng thứ hợp đồng cách ly tồn tại để chặn.
 */
// `?? WS_GIA_1`: `Session.currentWorkspaceId` thành `string | null` từ 2026-08-15
// (phiên chưa có workspace là hợp lệ), nhưng `FAKE_SESSION` LUÔN có workspace —
// mọi handler dưới đây ghim vào một workspace cụ thể và không có nhánh nào cho
// `null`. Ép kiểu ở đúng một chỗ, thay vì rắc `!` khắp nơi.
let WS_DANG_MO: string = FAKE_SESSION.currentWorkspaceId ?? WS_GIA_1

/** Bàn giả sống suốt phiên — cùng khuôn `RESET_USERS_GIA()`/`RESET_VAI_TRO_GIA()`. */
export function RESET_WS_DANG_MO(): void {
  WS_DANG_MO = FAKE_SESSION.currentWorkspaceId ?? WS_GIA_1
}

/**
 * Bàn khởi đầu: chính user của `FAKE_SESSION` (chủ tổ chức, không membership) +
 * một người `pending` để dev thấy ngay hai nút Mời lại/Xoá mà không phải tạo.
 *
 * `roleId` dưới đây là CHUỖI LẶP LẠI của `VAI_TRO_GIA.id` (khai ở dưới, xa hơn
 * trong file) — chủ ý viết literal, không import chéo giữa hai bàn giả trong
 * CÙNG một file. Hai user `role_gia_qt` (Quản trị) + một user `role_gia_xem`
 * (Người xem) là NGUỒN THẬT của `userCount` mà `VAI_TRO_GIA` từng ghi cứng —
 * xem `soNguoiDungVaiTro()` ở dưới.
 */
const USERS_GIA: UserGia[] = [
  {
    id: FAKE_SESSION.user.id,
    email: FAKE_SESSION.user.email,
    name: FAKE_SESSION.user.name,
    phone: '0901234567',
    jobTitle: 'Tổng giám đốc',
    lifecycle: 'active',
    createdAt: '2026-07-01T00:00:00Z',
    memberships: [],
  },
  {
    id: 'u_fake_lan',
    email: 'lan@anphuland.vn',
    name: 'Nguyễn Thị Lan',
    phone: null,
    jobTitle: 'CSKH',
    lifecycle: 'active',
    createdAt: '2026-07-15T00:00:00Z',
    memberships: [{ workspaceId: WS_GIA_1, roleId: 'role_gia_qt', expiresAt: null }],
  },
  {
    id: 'u_fake_minh',
    email: 'minh@anphuland.vn',
    name: 'Phạm Văn Minh',
    phone: null,
    jobTitle: 'Vận hành',
    lifecycle: 'active',
    createdAt: '2026-07-20T00:00:00Z',
    memberships: [{ workspaceId: WS_GIA_2, roleId: 'role_gia_qt', expiresAt: null }],
  },
  {
    id: 'u_fake_cho',
    email: 'cho@anphuland.vn',
    name: 'Người Chờ Mời',
    phone: null,
    jobTitle: null,
    lifecycle: 'pending',
    createdAt: '2026-08-02T00:00:00Z',
    memberships: [{ workspaceId: WS_GIA_2, roleId: 'role_gia_xem', expiresAt: null }],
  },
]

/** Dựng lại bàn khởi đầu — cho test cần bàn sạch giữa hai `it()`. */
export function RESET_USERS_GIA(): void {
  USERS_GIA.splice(0, USERS_GIA.length, ...structuredClone(USERS_GIA_BAN_DAU))
}
const USERS_GIA_BAN_DAU = structuredClone(USERS_GIA)

// ─── M2b — vai trò tự định nghĩa cấp tổ chức (phan-quyen-dong, task 7) ──────
//
// KIỂU RIÊNG, không import từ `features/auth/api.ts`: cùng lý lẽ `UserGia` ở
// trên — module giả này đứng độc lập với module tính năng, chỉ cần khớp HÌNH
// DẠNG, không cần khớp KIỂU.

interface VaiTroToChucGia {
  id: string
  name: string
  description: string | null
  // KHÔNG có `userCount` ở đây (khác bản trước Task 8): số người dùng một vai
  // trò không phải trạng thái để LƯU, mà là một phép TÍNH trên `USERS_GIA` —
  // xem `soNguoiDungVaiTro()` ngay dưới. Ghi cứng con số này là đúng lỗi
  // docstring bản trước đã cảnh báo: nó đứng yên trong khi user thật được gán/
  // gỡ vai trò ở tab Thành viên, và hai tab Vai trò + Thành viên bắt đầu
  // nói hai sự thật khác nhau.
}

/**
 * Số user ĐANG CẦM một vai trò — tính trên `USERS_GIA.memberships[].roleId`,
 * không đọc từ một trường lưu sẵn. Đây LÀ cầu nối liên thông hai tab của
 * `/users`: tạo vai trò mới ở tab Vai trò rồi gán cho ai ở tab Thành viên
 * thì số này đổi ngay ở LẦN ĐỌC KẾ TIẾP — không cần một bước đồng bộ nào ở
 * giữa vì không có gì phải đồng bộ.
 *
 * KHÔNG lọc `conHieuLuc(m)` — điều kiện DUY NHẤT là `m.roleId === roleId`, vì
 * đó là điều kiện duy nhất của backend. `repo.dem_nguoi_dung_vai_tro` là
 * `SELECT count(*) FROM control.memberships WHERE role_id = $1`, không có vị từ
 * `expires_at`; docstring `liet_ke_vai_tro` bên đó nói thẳng chủ ý: đếm CẢ
 * membership đã hết hạn, vì xoá vai trò sẽ vỡ FK khi hàng đó vẫn tồn tại
 * (migration `0104_vai_tro_dong` đặt `(org_id, role_id)` là `ON DELETE
 * RESTRICT`), nên báo con số nhỏ hơn thực tế là đẩy người dùng vào một 409 khó
 * hiểu. Vé hỗ trợ hết hạn VẪN là một hàng trong `memberships` — BR-Q08 nói nó
 * ngừng có tác dụng, KHÔNG nói nó bị xoá — nên vai trò nó trỏ tới vẫn không xoá
 * được. Bản trước lọc `conHieuLuc(m)` ở đây và vì thế mã hoá luật NGƯỢC với
 * backend: fake cho xoá, backend thật trả 409 `ROLE_IN_USE`. Một fake nói dối
 * theo hướng DỄ HƠN thật là fake vô dụng — nó để lọt đúng lớp lỗi nó tồn tại
 * để bắt.
 *
 * Đếm theo USER (không theo DÒNG membership): một user cầm vai trò A ở hai
 * workspace vẫn là MỘT người đang dùng A, đúng ngữ nghĩa cột Đang gán của
 * bảng ở tab Vai trò. ⚠ Đây là chỗ CÒN LỆCH backend, chỉ là chưa quan sát
 * được: `count(*)` bên kia đếm HÀNG, nên cùng dữ liệu đó backend trả 2 còn fake
 * trả 1. Không bàn giả nào hiện có một người cầm cùng vai trò ở hai workspace
 * nên hai bên đang ra cùng số; dựng một bàn như thế là làm lệch hiện hình.
 */
function soNguoiDungVaiTro(roleId: string): number {
  return USERS_GIA.filter((u) => u.memberships.some((m) => m.roleId === roleId)).length
}

/** Ba vai trò mẫu.
 *
 * `role_gia_qt` được `u_fake_lan` + `u_fake_minh` cầm, `role_gia_xem` được
 * `u_fake_cho` cầm (xem `USERS_GIA` ở trên) — nên `soNguoiDungVaiTro` tính ra
 * đúng 2/1/0 mà bản trước Task 8 từng ghi cứng, chỉ khác là giờ TÍNH RA. */
const VAI_TRO_GIA: VaiTroToChucGia[] = [
  {
    id: 'role_gia_qt',
    name: 'Quản trị',
    description: 'Toàn quyền vận hành, kiến thức và cấu hình',
  },
  {
    id: 'role_gia_xem',
    name: 'Người xem',
    description: 'Chỉ xem, không sửa được gì',
  },
  {
    id: 'role_gia_trong',
    name: 'Trống',
    description: null,
  },
]

/** Dựng lại bàn khởi đầu — cùng khuôn `RESET_USERS_GIA()`. */
export function RESET_VAI_TRO_GIA(): void {
  VAI_TRO_GIA.splice(0, VAI_TRO_GIA.length, ...structuredClone(VAI_TRO_GIA_BAN_DAU))
}
const VAI_TRO_GIA_BAN_DAU = structuredClone(VAI_TRO_GIA)

/**
 * Lời mời đang treo của fake — hàng `kind='invite'` mà `GET /members` trả kèm.
 *
 * PHẢI có ít nhất một hàng `userId: null`: đó là hình dạng mà mọi bug của thay đổi
 * này nằm trong (React key rỗng, `/members/null`, cột tên trống). Một fake chỉ có
 * hàng `member` nói dối theo hướng dễ hơn thật — đúng cái bẫy CLAUDE.md đã ghi.
 *
 * ⚠ PHẢI CÓ CẢ một hàng `userId` KHÔNG null (`invite_existing`) — trước đợt sửa
 * finding A, mảng này chỉ có MỘT hàng và nó là `userId: null`, nên KHÔNG test nào
 * ở repo này hay repo FE render được một hàng `invite_existing` thật — đúng lỗ
 * hổng mà finding A đã chỉ ra (email biến mất khỏi hàng đó vì tên JOIN được từ
 * `users` thắng chỗ email lẽ ra phải đứng). `userId` trỏ vào `u_fake_minh` (có
 * sẵn trong `USERS_GIA`, `active`) — CHỌN người CHƯA phải thành viên của
 * `WS_GIA_1` (anh ta chỉ thuộc `WS_GIA_2`) để hàng `invite` này không trùng một
 * hàng `member` khác của cùng người trong cùng workspace, giữ fixture đơn giản.
 */
// `tenantId: WS_GIA_1` — WORKSPACE ĐANG MỞ MẶC ĐỊNH, chuyển VỀ đây 2026-08-22
// (Task 11) cùng lúc `UserAdmin.tsx` được sửa để render đúng hàng `userId`/
// `name`/`lifecycle` null. Trước đó nó bị PARK Ở `WS_GIA_2` có chủ ý — đặt ở
// đây thì `ten.trim()` (bản `UserAdmin.tsx` cũ, chưa biết `kind`) NÉM ngay lúc
// render và sập `boot.test.tsx` (bài đi qua TOÀN BỘ 20 màn). Giờ `UserAdmin.tsx`
// rẽ theo `kind` trước khi đụng `m.name`, nên hàng này đứng đúng chỗ dữ liệu
// thật sẽ đứng: cùng workspace với phần lớn thành viên khác của fake.
const LOI_MOI_GIA: {
  email: string
  userId: string | null
  roleId: string
  tenantId: string
}[] = [
  { email: 'chuaco@anphuland.vn', userId: null, roleId: VAI_TRO_GIA[1]!.id, tenantId: WS_GIA_1 },
  {
    email: 'minh@anphuland.vn',
    userId: 'u_fake_minh',
    roleId: VAI_TRO_GIA[1]!.id,
    tenantId: WS_GIA_1,
  },
]

/**
 * Dựng lại bàn khởi đầu — cùng khuôn `RESET_USERS_GIA()`/`RESET_VAI_TRO_GIA()`.
 *
 * BẮT BUỘC có, không phải tuỳ chọn: handler `DELETE /members/invites/:email`
 * `splice` thẳng vào `LOI_MOI_GIA` (mảng module-level, sống suốt phiên như
 * `USERS_GIA`). Thiếu reset thì một test xoá lời mời giả sẽ để bàn trống cho
 * MỌI test chạy sau trong cùng file — kể cả những bài không hề nhắc tới lời
 * mời — và bài đỏ ở xa hẳn chỗ gây ra nó.
 */
export function RESET_LOI_MOI_GIA(): void {
  LOI_MOI_GIA.splice(0, LOI_MOI_GIA.length, ...structuredClone(LOI_MOI_GIA_BAN_DAU))
}
const LOI_MOI_GIA_BAN_DAU = structuredClone(LOI_MOI_GIA)

/** `LOI_MOI_GIA[number]` -> hình dạng hàng `MemberOut` với `kind: 'invite'`. */
function raHangLoiMoi(l: (typeof LOI_MOI_GIA)[number]) {
  const u = l.userId === null ? undefined : USERS_GIA.find((x) => x.id === l.userId)
  return {
    kind: 'invite' as const,
    userId: l.userId,
    name: u?.name ?? null,
    email: l.email,
    roleId: l.roleId,
    role: tenVaiTroGia(l.roleId),
    lifecycle: u?.lifecycle ?? null,
    invitedAt: '2026-08-22T03:00:00Z',
    expiresAt: '2026-08-29T03:00:00Z',
    // Hàng lời mời không mang avatar (backend trả null có chủ ý — FE hiện phong bì).
    avatar: null,
  }
}

// ─── Khoá đấu nối agent (M8 · màn `api`) ─────────────────────────────────────

/**
 * Hai ENDPOINT_URL giả — khớp công thức thật `wss://<tenant>.<domain>/v1/<kind>`
 * của `enrollment/endpoint.py`. Tenant lấy từ `FAKE_SESSION.currentWorkspaceId`
 * để dev thấy nó đổi theo workspace, đúng như bản thật.
 */
export const ENDPOINT_CHAT_URL_GIA = `wss://${FAKE_SESSION.currentWorkspaceId}.agents.noblex.vn/v1/chat`
export const ENDPOINT_VOICE_URL_GIA = `wss://${FAKE_SESSION.currentWorkspaceId}.agents.noblex.vn/v1/voice`

interface KhoaGia {
  id: number
  /** Khoá THÔ (migration `0918`) — `null` = khoá tạo trước đó, không có bản thô. */
  api_key: string | null
  key_prefix: string
  label: string
  created_at: string
  last_used_at: string | null
  status: 'active' | 'inactive'
  revoked_at: string | null
}

/**
 * Bàn khởi đầu: một khoá đang dùng · một khoá chưa dùng · một khoá đã tắt.
 *
 * BA khoá chứ không một: cột Dùng cuối có hai nhánh (có mốc / `null` → "Chưa
 * dùng") và cột Trạng thái có hai nhánh (`active` / `inactive`). Một bàn chỉ có
 * một khoá thì các nhánh kia không bao giờ hiện ra lúc dev nhìn màn hình.
 */
export const KHOA_GIA: KhoaGia[] = [
  {
    id: 1,
    api_key: null,
    key_prefix: 'ody_ag_7Fk2',
    label: 'Pod chat production',
    created_at: '2026-08-01T09:12:00.000Z',
    last_used_at: '2026-08-05T08:30:00.000Z',
    status: 'active',
    revoked_at: null,
  },
  {
    id: 2,
    api_key: 'ody_ag_Qm91mOcKdEvKeYfOrDeVeLoPmEnTxx02',
    key_prefix: 'ody_ag_Qm91',
    label: '',
    created_at: '2026-07-28T14:02:00.000Z',
    last_used_at: null,
    status: 'active',
    revoked_at: null,
  },
  // Khoá thứ ba, ĐÃ TẮT — nhánh `status: 'inactive'` phải hiện ra lúc dev mở màn,
  // cùng lý lẽ với hai nhánh của cột Dùng cuối ở trên. Thiếu nó thì diện mạo của
  // hàng tắt (badge, nút «Bật lại») không ai nhìn thấy cho tới khi lên production.
  {
    id: 3,
    api_key: null,
    key_prefix: 'ody_ag_Zx8L',
    label: 'Pod thử nghiệm',
    created_at: '2026-07-20T10:45:00.000Z',
    last_used_at: '2026-07-25T16:10:00.000Z',
    status: 'inactive',
    revoked_at: '2026-07-26T09:00:00.000Z',
  },
]

const KHOA_GIA_BAN_DAU = structuredClone(KHOA_GIA)

export function RESET_KHOA_GIA(): void {
  KHOA_GIA.splice(0, KHOA_GIA.length, ...structuredClone(KHOA_GIA_BAN_DAU))
  _idKe = 100
}

let _idKe = 100

/**
 * Sổ lĩnh vực — fake CÓ TRẠNG THÁI, khác phần lớn handler ở tệp này.
 *
 * Phải có trạng thái vì màn «Quản lý lĩnh vực» bật/tắt rồi đọc lại ngay, và một
 * fake trả hằng số sẽ làm công tắc bật lên rồi tự nhảy về — trông y như lỗi
 * client. Reset theo tiến trình test (`server.resetHandlers()` KHÔNG đụng biến
 * này), nên test nào đổi trạng thái phải tự `server.use(...)` đè lại.
 *
 * ⚠ BẢN SAO VIẾT TAY, KHÔNG CÓ CỔNG PARITY — cùng hạng với `contracts/*.json`.
 * Backend chưa có hai endpoint này; hình dạng do FE định ở
 * `features/agent/linhVuc.ts`. Đừng lấy hành vi của fake làm sự thật về backend.
 */
const FAKE_LINH_VUC = [
  { ma: 'bds', ten: 'Bất động sản', bat: true, soKyNang: 9, coDuLieu: true },
  { ma: 'taichinh', ten: 'Tài chính', bat: false, soKyNang: 0, coDuLieu: false },
]

export const HANDLERS = [
  http.get('/api/v1/linh-vuc', () => HttpResponse.json(FAKE_LINH_VUC)),
  http.patch('/api/v1/linh-vuc/:ma', async ({ params, request }) => {
    const { bat } = (await request.json()) as { bat: boolean }
    const i = FAKE_LINH_VUC.findIndex((l) => l.ma === params['ma'])
    if (i === -1) return new HttpResponse(null, { status: 404 })
    FAKE_LINH_VUC[i] = { ...(FAKE_LINH_VUC[i] as (typeof FAKE_LINH_VUC)[number]), bat }
    return HttpResponse.json(FAKE_LINH_VUC[i])
  }),

  ...opsHandlers,
  ...qualityHandlers,
  ...kbWebHandlers,
  ...nguonHandlers,
  ...billingHandlers,
  ...nhatKyHandlers,
  ...nhanVatHandlers,
  ...kichBanHandlers,
  // ─── Khoá đấu nối agent ────────────────────────────────────────────────────
  //
  // Hai `endpoint_*_url` trả về KỂ CẢ khi `keys` rỗng — bản thật bọc list trong
  // một object đúng vì lý do đó, và handler giả phải giữ nguyên hình dạng ấy,
  // nếu không test màn rỗng sẽ xanh trên một shape không tồn tại ở production.
  // `?status=` lọc — ĐÚNG như backend (`repo.liet_ke_khoa_cua_tenant`). Không
  // truyền thì trả TẤT CẢ, kể cả khoá đã tắt.
  http.get('/api/v1/agent/keys', ({ request }) => {
    const status = new URL(request.url).searchParams.get('status')
    const keys = status ? KHOA_GIA.filter((k) => k.status === status) : KHOA_GIA
    return HttpResponse.json({
      endpoint_chat_url: ENDPOINT_CHAT_URL_GIA,
      endpoint_voice_url: ENDPOINT_VOICE_URL_GIA,
      keys,
    })
  }),
  http.post('/api/v1/agent/keys', async ({ request }) => {
    const { label } = (await request.json()) as { label?: string }
    if ((label ?? '').length > 60) {
      return HttpResponse.json(
        { error: { code: 'VALIDATION', message: 'Nhãn dài quá 60 ký tự' } },
        { status: 422 },
      )
    }
    const id = _idKe++
    // Tiền tố 12 ký tự đầu — ĐÚNG như `bi_mat.sinh_khoa()` cắt. Bịa một tiền tố
    // không phải đoạn đầu của khoá là để test tin vào một quan hệ không có thật.
    const api_key = `ody_ag_${'x'.repeat(4)}${id}${'y'.repeat(30)}`
    KHOA_GIA.unshift({
      id,
      api_key,
      key_prefix: api_key.slice(0, 12),
      label: label ?? '',
      created_at: new Date().toISOString(),
      last_used_at: null,
      status: 'active',
      revoked_at: null,
    })
    return HttpResponse.json(
      {
        id,
        api_key,
        key_prefix: api_key.slice(0, 12),
        endpoint_chat_url: ENDPOINT_CHAT_URL_GIA,
        endpoint_voice_url: ENDPOINT_VOICE_URL_GIA,
      },
      { status: 201 },
    )
  }),
  // Bật/tắt. ⚠️ HÀNG Ở LẠI — backend chỉ đặt `revoked_at`, KHÔNG có câu `DELETE`
  // nào trên `control.agent_keys`. Bản trước handler này `splice()` hàng ra khỏi
  // mảng, tức fake mã hoá một luật NGƯỢC với backend — đúng lớp lỗi mà gotcha
  // `userCount` trong CLAUDE.md đã ghi. Xoá hàng ở đây là để test tin rằng khoá
  // biến mất, trong khi thật ra nó chỉ đổi trạng thái.
  http.post('/api/v1/agent/keys/:id', async ({ params, request }) => {
    const { status } = (await request.json()) as { status?: string }
    if (status !== 'active' && status !== 'inactive') {
      return HttpResponse.json(
        { error: { code: 'VALIDATION', message: `status không hợp lệ: ${status}` } },
        { status: 422 },
      )
    }
    const k = KHOA_GIA.find((x) => x.id === Number(params.id))
    if (!k) {
      return HttpResponse.json(
        { error: { code: 'NOT_FOUND', message: `Không có khoá ${params.id}` } },
        { status: 404 },
      )
    }
    k.status = status
    k.revoked_at = status === 'inactive' ? new Date().toISOString() : null
    return HttpResponse.json(k)
  }),
  // Xoay khoá: phát khoá MỚI cùng nhãn + thu hồi khoá CŨ, một lượt. Response
  // CÙNG HÌNH DẠNG với `POST /agent/keys` (chứa khoá thô, `KhoaMoiDialog` dùng
  // lại nguyên).
  http.post('/api/v1/agent/keys/:id/rotate', ({ params }) => {
    const cu = KHOA_GIA.find((x) => x.id === Number(params.id))
    if (!cu) {
      return HttpResponse.json(
        { error: { code: 'NOT_FOUND', message: `Không có khoá ${params.id}` } },
        { status: 404 },
      )
    }
    cu.status = 'inactive'
    cu.revoked_at = new Date().toISOString()

    const id = _idKe++
    const api_key = `ody_ag_${'x'.repeat(4)}${id}${'y'.repeat(30)}`
    KHOA_GIA.unshift({
      id,
      api_key,
      key_prefix: api_key.slice(0, 12),
      label: cu.label,
      created_at: new Date().toISOString(),
      last_used_at: null,
      status: 'active',
      revoked_at: null,
    })
    return HttpResponse.json(
      {
        id,
        api_key,
        key_prefix: api_key.slice(0, 12),
        endpoint_chat_url: ENDPOINT_CHAT_URL_GIA,
        endpoint_voice_url: ENDPOINT_VOICE_URL_GIA,
      },
      { status: 201 },
    )
  }),
  // Feedback cuối phiên — đường HTTP DUY NHẤT mà `/thu-agent` gọi ngoài
  // `/agent/keys`. Xác thực bằng `Authorization: Bearer <api_key>` (KHÔNG phải
  // cookie phiên), đúng ba cổng xác thực tách rời của `enrollment/router.py`;
  // fake kiểm đúng vế đó vì nó là thứ dễ quên nhất ở phía gọi. Trả 204 rỗng.
  http.post('/api/v1/agent/feedback', async ({ request }) => {
    if (!(request.headers.get('Authorization') ?? '').startsWith('Bearer ')) {
      return HttpResponse.json(
        { error: { code: 'INVALID_AGENT_KEY', message: 'Khoá đấu nối không hợp lệ' } },
        { status: 401 },
      )
    }
    const b = (await request.json()) as { session_id?: string; rating?: number }
    // Backend: `session_id` min_length=1, `rating` 1-5 (`FeedbackIn`). Fake
    // phải từ chối đúng những ca đó — một fake dễ tính hơn thật là fake để lọt
    // đúng lớp lỗi nó sinh ra để bắt (xem gotcha `userCount` ở CLAUDE.md).
    if (!b.session_id || typeof b.rating !== 'number' || b.rating < 1 || b.rating > 5) {
      return HttpResponse.json(
        { error: { code: 'VALIDATION', message: 'session_id rỗng hoặc rating ngoài 1-5' } },
        { status: 422 },
      )
    }
    return new HttpResponse(null, { status: 204 })
  }),
  // KHÔNG CÓ FAKE CHO WEBSOCKET của `/thu-agent` (2026-08-10) — màn nối THẲNG từ
  // trình duyệt tới gateway thật (`chatGateway.ts`), không đi qua backend nào
  // cả, nên MSW (chỉ chặn HTTP) không có gì để can thiệp. Dưới `VITE_MSW=1`
  // form mở được nhưng bấm «Áp dụng» sẽ không kết nối được gì — đúng thật,
  // không phải thiếu sót: tính năng này chỉ có ý nghĩa với gateway thật.

  // CỐ Ý trả `FAKE_SESSION` nguyên bản, KHÔNG chèn `WS_DANG_MO` vào
  // `currentWorkspaceId`. Đúng là làm vậy thì một lần F5 trên trình duyệt bật
  // ngược về workspace đầu — nhưng đã đo: nó làm đỏ 2 test ở
  // `tests/doi-workspace.test.tsx`. `WS_DANG_MO` sống suốt phiên module, nên một
  // `it()` bấm switcher sang Sunrise là mọi `it()` SAU đó boot thẳng vào Sunrise
  // và không còn tìm thấy nút An Phú Land để bấm. Từng `it()` bắt đầu từ một
  // phiên sạch là kỳ vọng ĐÚNG; chỗ sai nếu có nằm ở việc thiếu reset toàn cục,
  // không nằm ở test. Ai muốn nối `/me` vào `WS_DANG_MO` thì phải giải quyết
  // chuyện reset trước — xem `RESET_WS_DANG_MO()`.
  http.get('/api/v1/me', () => HttpResponse.json(FAKE_SESSION)),
  // ── Màn «Hồ sơ & tuỳ chọn» ────────────────────────────────────────────────
  // PATCH trộn body vào user rồi trả về — KHÔNG có trạng thái: màn ghi cache
  // `['session']` từ response nên đủ cho mọi luồng; reload dưới MSW mất thay
  // đổi là hành vi chấp nhận được của fake.
  http.patch('/api/v1/me/ho-so', async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>
    const u = FAKE_SESSION.user
    return HttpResponse.json({
      ...FAKE_SESSION,
      user: {
        ...u,
        name: typeof body.name === 'string' ? body.name : u.name,
        phone: 'phone' in body ? body.phone : u.phone,
        jobTitle: 'jobTitle' in body ? body.jobTitle : u.jobTitle,
        // Seed mới ⇒ avatar mới; backend thật sinh DiceBear, fake chỉ cần một
        // data URI KHÁC để màn thấy ảnh đổi.
        avatar:
          'avatarSeed' in body && body.avatarSeed !== null
            ? avatarGia(String(body.avatarSeed).slice(0, 2).toUpperCase(), '#7c5cd6')
            : u.avatar,
      },
    })
  }),
  // Backend thật trả 4 ô × 6 style, seed mang TIỀN TỐ `style:` (hợp đồng
  // `core/avatar.py::_tach` — FE chỉ round-trip chuỗi, không parse).
  http.get('/api/v1/me/avatar-goi-y', () =>
    HttpResponse.json(
      ['thumbs', 'pixel-art', 'bottts', 'avataaars', 'lorelei', 'notionists'].flatMap((style, k) =>
        Array.from({ length: 4 }, (_, i) => ({
          seed: `${style}:goi-y-${i + 1}`,
          avatar: avatarGia(`G${k * 4 + i + 1}`, i % 2 ? '#7c5cd6' : '#0a7ea4'),
        })),
      ),
    ),
  ),
  // Kiểm tối thiểu như backend: mật khẩu mới < 10 ký tự là 422 — form đã chặn
  // nút, fake canh để một regression phía form không đi qua im lặng.
  http.post('/api/v1/me/mat-khau', async ({ request }) => {
    const body = (await request.json()) as { matKhauHienTai?: string; matKhauMoi?: string }
    if (!body.matKhauHienTai || (body.matKhauMoi ?? '').length < 10) {
      return HttpResponse.json(
        { error: { code: 'VALIDATION', message: 'Thiếu hoặc mật khẩu mới quá ngắn' } },
        { status: 422 },
      )
    }
    return new HttpResponse(null, { status: 204 })
  }),
  // Cửa Google — dev mặc định BẬT nên nút hiện ra ở cả /login lẫn /dang-ky.
  // Test cần cửa TẮT tự `server.use(...)` đè giá trị này (xem tests/nut-google.test.tsx).
  http.get('/api/v1/auth/providers', () => HttpResponse.json({ google: true })),
  http.post('/api/v1/auth/login', () => HttpResponse.json(FAKE_SESSION)),
  // Tự đăng ký (đổi 2026-08-17) — KHÔNG còn nhận `password`, KHÔNG còn trả
  // `Session`/đặt cookie. Thân trả về của CẢ 201 lẫn 200 là `{daGuiLai}`:
  //   · email mới                -> 201, daGuiLai: false
  //   · email `pending` (đã đăng ký dở, thư vừa gửi LẠI) -> 200, daGuiLai: true
  //   · email đã có tài khoản CÓ mật khẩu -> 409 EMAIL_TAKEN
  // Sentinel theo đúng lối `da.ton.tai@x.vn` đã có: `dang.cho@x.vn` mô phỏng
  // nhánh 200/pending, mọi email khác rơi vào nhánh 201/mới.
  http.post('/api/v1/auth/register', async ({ request }) => {
    const { email } = (await request.json()) as { email: string; name: string }
    if (email === 'da.ton.tai@x.vn')
      return loiGia(409, 'EMAIL_TAKEN', 'Email này đã được dùng cho một tài khoản khác')
    if (email === 'dang.cho@x.vn') return HttpResponse.json({ daGuiLai: true }, { status: 200 })
    return HttpResponse.json({ daGuiLai: false }, { status: 201 })
  }),

  http.post('/api/v1/auth/logout', () => new HttpResponse(null, { status: 204 })),
  http.post('/api/v1/me/workspace', async ({ request }) => {
    const { workspaceId } = (await request.json()) as { workspaceId: string }
    // GHI LẠI, không chỉ trả về: `GET /members` đọc `WS_DANG_MO` để cùng một
    // workspace với phiên mà FE vừa nhận (xem docstring `WS_DANG_MO`).
    WS_DANG_MO = workspaceId
    return HttpResponse.json({ ...FAKE_SESSION, currentWorkspaceId: workspaceId })
  }),
  // NỐI THẬT với `USERS_GIA`/`VAI_TRO_GIA` (Task gộp Users+Roles, 2026-08-06) —
  // bản trước là 2 dòng viết cứng, đứng NGOÀI hai bàn giả đó. `u_fake_dang`
  // (chủ tổ chức) từng bị gán cứng Quản trị ở đây dù `USERS_GIA` của owner
  // luôn `memberships: []` (owner không cần membership — bỏ qua mọi workspace
  // riêng). Giờ tính đúng: chỉ user có
  // membership CÒN HIỆU LỰC (`conHieuLuc`) ở đúng workspace đang mở mới xuất
  // hiện. Hàng trả về mang CẢ `roleId` lẫn `role` — cùng hình dạng backend thật
  // từ 2026-08-07 (`contracts.py MemberOut`): id để cột Vai trò neo `<select>`
  // vào, tên để hiện. Phép dịch id -> tên gọi `tenVaiTroGia`.
  http.get('/api/v1/members', () => {
    const hienTai = WS_DANG_MO
    const hangThanhVien = USERS_GIA.flatMap((u) => {
      const m = u.memberships.find((mm) => mm.workspaceId === hienTai && conHieuLuc(mm))
      // KHÔNG còn nhánh "chủ tổ chức hiện dù không có membership": nhánh owner
      // trong `doc_quyen()` đã bỏ 2026-08-15, nên không membership nghĩa là
      // không thuộc workspace này — và không hiện trong bảng thành viên.
      if (!m) return []
      return [
        {
          kind: 'member' as const,
          userId: u.id,
          name: u.name,
          email: u.email,
          roleId: m.roleId,
          role: tenVaiTroGia(m.roleId),
          lifecycle: u.lifecycle,
          invitedAt: null,
          expiresAt: null,
          // Backend thật sinh DiceBear (`avatar_seed or name` — cùng công thức
          // `/me`); fake chỉ cần MỘT data URI đúng hình dạng, cùng lối `/me` trên.
          avatar: avatarGia(u.name.slice(0, 1).toUpperCase()),
        },
      ]
    })
    // Hàng `invite` (2026-08-22) — lời mời đang treo của ĐÚNG workspace đang mở.
    // Xem docstring `LOI_MOI_GIA` cho vì sao ít nhất một hàng phải mang `userId: null`.
    return HttpResponse.json([
      ...hangThanhVien,
      ...LOI_MOI_GIA.filter((l) => l.tenantId === hienTai).map(raHangLoiMoi),
    ])
  }),

  // ── Hợp đồng FE ĐỊNH TRƯỚC (2026-08-09) — backend CHƯA CÓ 4 đường này ──────
  //
  // Fake CÓ TRẠNG THÁI (ghi vào `USERS_GIA`), hiếm ở tệp này — cần thế vì màn
  // mời rồi đọc lại bảng ngay trong một nhịp. Cùng lối fake của `/linh-vuc`.
  //
  // ⚠ ĐỪNG lấy hành vi ở đây làm sự thật về backend. Tệp này là bản sao viết tay
  // KHÔNG có cổng parity nào canh (xem CLAUDE.md, vụ `soNguoiDungVaiTro`).
  http.post('/api/v1/members', async ({ request }) => {
    const { emails, roleId } = (await request.json()) as { emails: string[]; roleId: string }
    if (!VAI_TRO_GIA.some((r) => r.id === roleId))
      return loiGia(422, 'ROLE_NOT_FOUND', 'Vai trò được chọn không tồn tại')

    // Lỗi TỪNG DÒNG (2026-08-17, mới): `loi` là mảng RIÊNG cạnh `invites`, một
    // email hỏng không kéo cả lô rớt theo. Sentinel theo đúng lối
    // `da.ton.tai@x.vn` của `/auth/register`: email này giả một người đang tự
    // đăng ký dở (chưa đặt mật khẩu xong) — KHÔNG mời được lúc này.
    const loi: { email: string; ma: string }[] = []
    type MoiRa = { email: string; userId: string; invitePath: string | null; daCo: boolean }
    const invites = emails.flatMap((raw): MoiRa[] => {
      const email = raw.trim().toLowerCase()
      if (email === 'dang.ky.do.dang@x.vn') {
        loi.push({ email, ma: 'USER_PENDING_SIGNUP' })
        return []
      }
      const co = USERS_GIA.find((u) => u.email === email)
      if (co) {
        const daTrongWs = co.memberships.some((m) => m.workspaceId === WS_DANG_MO)
        if (!daTrongWs) co.memberships.push({ workspaceId: WS_DANG_MO, roleId, expiresAt: null })
        return [{ email, userId: co.id, invitePath: null, daCo: true }]
      }
      const moi = {
        id: `u_${email.split('@')[0]?.replace(/[^a-z0-9]+/gi, '_') ?? 'user'}`,
        email,
        name: email.split('@')[0] ?? email,
        phone: null,
        jobTitle: null,
        lifecycle: 'pending' as const,
        createdAt: new Date().toISOString(),
        memberships: [{ workspaceId: WS_DANG_MO, roleId, expiresAt: null }],
      }
      USERS_GIA.push(moi)
      // Token khác nhau mỗi lần: token cố định làm bài "mời lại sinh link mới" xanh sai.
      return [
        {
          email,
          userId: moi.id,
          invitePath: `/invite/tok_gia_${USERS_GIA.length}_${Date.now()}`,
          daCo: false,
        },
      ]
    })
    return HttpResponse.json({ invites, loi }, { status: 201 })
  }),

  http.patch('/api/v1/members/:id', async ({ params, request }) => {
    const { roleId } = (await request.json()) as { roleId: string }
    const u = USERS_GIA.find((x) => x.id === params.id)
    if (!u) return loiGia(404, 'MEMBER_NOT_FOUND', 'Không tìm thấy thành viên này')
    // Vệ CHỦ TỔ CHỨC (409 CANNOT_CHANGE_OWNER_ROLE) XOÁ 2026-08-15: không còn
    // `orgRole`, và mọi thành viên trong bảng này đều có một hàng `memberships`
    // thật — kể cả người tạo workspace, người giờ mang vai trò "Quản trị".
    if (!VAI_TRO_GIA.some((r) => r.id === roleId))
      return loiGia(422, 'ROLE_NOT_FOUND', 'Vai trò được chọn không tồn tại')
    const m = u.memberships.find((mm) => mm.workspaceId === WS_DANG_MO)
    if (!m) return loiGia(404, 'MEMBER_NOT_FOUND', 'Người này không còn ở workspace đang mở')
    m.roleId = roleId
    return HttpResponse.json({
      userId: u.id,
      name: u.name,
      email: u.email,
      roleId,
      role: tenVaiTroGia(roleId),
      lifecycle: u.lifecycle,
      // LUÔN `false`: trường này là di sản của tầng tổ chức đã bỏ, giữ trong
      // hợp đồng giả cho tới khi FE thôi đọc nó.
    })
  }),

  http.delete('/api/v1/members/:id', ({ params }) => {
    const u = USERS_GIA.find((x) => x.id === params.id)
    if (!u) return loiGia(404, 'MEMBER_NOT_FOUND', 'Không tìm thấy thành viên này')
    // Vệ CANNOT_REMOVE_OWNER xoá cùng `orgRole` (2026-08-15).
    const i = u.memberships.findIndex((mm) => mm.workspaceId === WS_DANG_MO)
    if (i >= 0) u.memberships.splice(i, 1)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/v1/members/:id/invite', ({ params }) => {
    const u = USERS_GIA.find((x) => x.id === params.id)
    if (!u) return loiGia(404, 'MEMBER_NOT_FOUND', 'Không tìm thấy thành viên này')
    if (u.lifecycle !== 'pending')
      return loiGia(409, 'USER_NOT_PENDING', 'Người này đã đặt mật khẩu — không cần mời lại')
    return HttpResponse.json({ invitePath: `/invite/tok_gia_lai_${Date.now()}` })
  }),

  // Hai đường mới 2026-08-22 — thao tác trên LỜI MỜI (định danh bằng EMAIL,
  // không phải userId: một lời mời cho email chưa có tài khoản không có
  // `userId` nào để neo vào). KHÁC `POST /members/:id/invite` ngay trên — đường
  // đó phục vụ hàng THÀNH VIÊN còn `pending` (di sản).
  http.post('/api/v1/members/invites/:email/resend', ({ params }) => {
    const email = decodeURIComponent(String(params.email))
    if (!LOI_MOI_GIA.some((l) => l.email === email))
      return loiGia(404, 'INVITE_NOT_FOUND', 'Không có lời mời đang chờ cho địa chỉ này')
    return HttpResponse.json({ invitePath: null })
  }),
  http.delete('/api/v1/members/invites/:email', ({ params }) => {
    const email = decodeURIComponent(String(params.email))
    const i = LOI_MOI_GIA.findIndex((l) => l.email === email)
    if (i === -1)
      return loiGia(404, 'INVITE_NOT_FOUND', 'Không có lời mời đang chờ cho địa chỉ này')
    LOI_MOI_GIA.splice(i, 1)
    return new HttpResponse(null, { status: 204 })
  }),

  // Hai đường CÔNG KHAI. Token bắt đầu bằng `tok_gia` -> hợp lệ; còn lại -> 404,
  // để dev xem được cả hai nhánh của màn nhận lời mời mà không phải sửa file này.
  //
  // `kind` HAI -> BA GIÁ TRỊ 2026-08-22: `tok_gia_dk_*` giả một token TỰ ĐĂNG KÝ
  // (`signup`, không thuộc workspace nào -> `workspaceName: null`); `tok_gia_moi_*`
  // giả lời mời một email CHƯA có tài khoản (`invite_new`, chưa có hàng `users`
  // nào -> `name: null`, cần đặt mật khẩu); còn lại (kể cả `tok_gia` trần dùng ở
  // phần lớn test) giả lời mời một email ĐÃ có tài khoản (`invite_existing`, chỉ
  // cần một cú bấm, KHÔNG được gửi `password`).
  http.get('/api/v1/invites/:token', ({ params }) => {
    const token = String(params.token)
    if (!token.startsWith('tok_gia'))
      return loiGia(404, 'INVITE_INVALID', 'Lời mời không hợp lệ hoặc đã hết hiệu lực')
    const workspaceName = FAKE_SESSION.workspaces[0]?.name ?? null
    if (token.startsWith('tok_gia_dk_'))
      return HttpResponse.json({
        email: 'nguoi.moi@anphuland.vn',
        name: 'Người Được Mời',
        kind: 'signup',
        workspaceName: null,
      })
    if (token.startsWith('tok_gia_moi_'))
      return HttpResponse.json({
        email: 'chuaco@anphuland.vn',
        name: null,
        kind: 'invite_new',
        workspaceName,
      })
    return HttpResponse.json({
      email: 'nguoi.moi@anphuland.vn',
      name: 'Người Được Mời',
      kind: 'invite_existing',
      workspaceName,
    })
  }),
  http.post('/api/v1/invites/accept', async ({ request }) => {
    const { token } = (await request.json()) as { token: string }
    return token.startsWith('tok_gia')
      ? new HttpResponse(null, { status: 204 })
      : loiGia(404, 'INVITE_INVALID', 'Lời mời không hợp lệ hoặc đã hết hiệu lực')
  }),

  // ── M2b — vai trò cấp tổ chức. GET only từ 2026-08-09, xem ghi chú ở dưới ──
  //
  // Danh sách CÓ TRẠNG THÁI như `USERS_GIA` ở trên — không phải vì FE còn ghi
  // (không còn), mà vì `userCount` phải TÍNH RA từ `USERS_GIA` thật
  // (`soNguoiDungVaiTro()` ở trên) chứ không phải một con số ghi cứng — hộp
  // thoại đổi vai trò và hộp thoại mời đọc danh sách này để dựng ô chọn.
  http.get('/api/v1/roles', () =>
    HttpResponse.json(
      VAI_TRO_GIA.map((r) => ({
        id: r.id,
        name: r.name,
        description: r.description,
        userCount: soNguoiDungVaiTro(r.id),
      })),
    ),
  ),
  // ⚠ POST/PATCH/DELETE /roles (2026-08-09) và GET /roles/:id · GET /actions
  // (2026-10-06) ĐÃ XOÁ khỏi fake — FE không gọi. Endpoint VẪN SỐNG ở backend thật;
  // FE gọi lại thì dựng lại handler. Xem spec 2026-08-09 §2.1.

  // M5 — Agent Studio. Trạng thái giả là Sẵn sàng để dev thấy ô chat thử mở;
  // đổi `trangThaiAgent` tại chỗ để xem ba nhánh khoá (AG_01 ER_06).
  // Hợp đồng backend `0966`/`0967`: MỘT cấu hình cho MỖI role, role là dữ liệu. Fake CÓ
  // TRẠNG THÁI cho TẬP role (thêm/đổi tên/xoá phải hiện lại ngay ở tab) nhưng KHÔNG nhớ nội
  // dung cấu hình — PUT trả version mà không ghi (reload dưới MSW là về FAKE_CONFIG).
  http.get('/api/v1/config', () =>
    HttpResponse.json({
      vaiTro: ROLE_CONFIG_GIA.map((r) => ({
        ...r,
        macDinh: r.key === 'customer',
        cauHinh: FAKE_CONFIG,
        laMacDinh: false,
      })),
      version: 3,
      soRoleToiDa: 10,
    }),
  ),
  http.get('/api/v1/config/status', () =>
    HttpResponse.json({ trangThaiAgent: 'san_sang', version: 3 }),
  ),
  http.put('/api/v1/config', async ({ request }) => {
    const { cauHinh } = (await request.json()) as { cauHinh: Record<string, unknown> }
    const keys = ROLE_CONFIG_GIA.map((r) => r.key)
    if (Object.keys(cauHinh).sort().join() !== [...keys].sort().join())
      return loiGia(
        409,
        'CONFIG_ROLE_DA_DOI',
        'Danh sách role vừa thay đổi ở nơi khác — tải lại màn hình rồi Lưu lại',
      )
    return HttpResponse.json({
      version: 4,
      truongDaDoi: Object.fromEntries(keys.map((k) => [k, []])),
    })
  }),
  http.post('/api/v1/config/roles', async ({ request }) => {
    const { ten, icon = null } = (await request.json()) as { ten: string; icon?: string | null }
    const t = ten.trim()
    if (ROLE_CONFIG_GIA.some((r) => r.ten.toLowerCase() === t.toLowerCase()))
      return loiGia(409, 'ROLE_TEN_DA_DUNG', `Đã có role tên «${t}»`)
    if (ROLE_CONFIG_GIA.length >= 10)
      return loiGia(
        409,
        'ROLE_QUA_GIOI_HAN',
        'Mỗi workspace tối đa 10 role — xoá bớt role không dùng',
      )
    // Bản thu gọn của `role_config.key_tu_ten` phía backend — đủ để key hợp lệ và không trùng.
    const goc =
      t
        .normalize('NFD')
        .replace(/[\u0300-\u036f]/g, '')
        .replace(/đ/gi, 'd')
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '') || 'role'
    let key = goc
    for (let n = 2; ROLE_CONFIG_GIA.some((r) => r.key === key); n++) key = `${goc}_${n}`
    ROLE_CONFIG_GIA.push({ key, ten: t, icon })
    return HttpResponse.json({ key, ten: t, icon, macDinh: false }, { status: 201 })
  }),
  http.patch('/api/v1/config/roles/:key', async ({ params, request }) => {
    const r = ROLE_CONFIG_GIA.find((x) => x.key === params.key)
    if (!r) return loiGia(404, 'ROLE_KHONG_TON_TAI', 'Không có role này')
    const { ten, icon } = (await request.json()) as { ten?: string; icon?: string }
    if (ten !== undefined) r.ten = ten.trim()
    if (icon !== undefined) r.icon = icon
    return HttpResponse.json({ ...r, macDinh: r.key === 'customer' })
  }),
  http.delete('/api/v1/config/roles/:key', ({ params }) => {
    if (params.key === 'customer')
      return loiGia(409, 'ROLE_MAC_DINH', 'Role mặc định (Khách hàng) không xoá được')
    const i = ROLE_CONFIG_GIA.findIndex((x) => x.key === params.key)
    if (i < 0) return loiGia(404, 'ROLE_KHONG_TON_TAI', 'Không có role này')
    ROLE_CONFIG_GIA.splice(i, 1)
    return new HttpResponse(null, { status: 204 })
  }),
  // M6 — Tài liệu. Ba trạng thái để dev thấy cả ba nhánh hiển thị cùng lúc.
  http.get('/api/v1/kb/files', () =>
    HttpResponse.json([
      {
        id: 1,
        tenFile: 'chinh-sach-ban-hang.pdf',
        loai: 'pdf',
        kichThuoc: 240_000,
        state: 'san_sang',
        chunkCount: 18,
        loiMessage: '',
        uploadedAt: '2026-07-30T08:00:00Z',
        uploadedBy: 'u_fake_dang',
      },
      {
        id: 2,
        tenFile: 'bang-gia-quy-3.xlsx',
        loai: 'xlsx',
        kichThuoc: 51_200,
        state: 'dang_xu_ly',
        chunkCount: 0,
        loiMessage: '',
        uploadedAt: '2026-07-31T02:00:00Z',
        uploadedBy: 'u_fake_lan',
      },
      {
        id: 3,
        tenFile: 'so-do-mat-bang.pdf',
        loai: 'pdf',
        kichThuoc: 1_800_000,
        state: 'loi',
        chunkCount: 0,
        loiMessage:
          'File này không có lớp chữ — có thể là ảnh scan. Hãy nạp bản có chữ, hoặc chuyển ảnh thành văn bản trước khi nạp lại.',
        uploadedAt: '2026-07-29T10:00:00Z',
        uploadedBy: 'u_fake_dang',
      },
    ]),
  ),
  http.delete('/api/v1/kb/files/:id', () => new HttpResponse(null, { status: 204 })),

  // ─── M4 — KB Bất động sản ─────────────────────────────────────────────────
  // Một dự án ĐỦ dữ liệu và một dự án THIẾU `overview`: dev thấy ngay cả badge
  // thiếu dữ liệu ở bảng lẫn cổng chặn publish, không phải tự dựng dữ liệu.
  // `total` có mặt như backend thật (`Trang<T>`) — thiếu nó thì thanh phân trang của
  // bản dev in «Hiện 0–0 / 0» ngay trên hai hàng đang hiện (audit 05/10).
  http.get('/api/v1/projects', () =>
    HttpResponse.json({
      items: [FAKE_DU_AN, FAKE_DU_AN_THIEU],
      nextCursor: null,
      total: 2,
    }),
  ),
  // ĐỨNG TRƯỚC `/projects/:code`: MSW khớp theo thứ tự khai, và `:code` nhận cả
  // chuỗi `kb-status`.
  http.get('/api/v1/projects/kb-status', () =>
    HttpResponse.json([
      { projectCode: 'NPLB', indexing: true, hasError: false },
      { projectCode: 'CHUAXONG', indexing: false, hasError: true },
    ]),
  ),
  http.post('/api/v1/projects/:code/sync-kb', () =>
    HttpResponse.json({ jobId: 1, state: 'queued' }, { status: 202 }),
  ),
  http.get('/api/v1/projects/:code/enrich-status', () => HttpResponse.json([])),
  http.post('/api/v1/projects/:code/documents/:id/approve', () =>
    HttpResponse.json({ approved: true }, { status: 202 }),
  ),
  http.post('/api/v1/media/draft-caption', () =>
    HttpResponse.json({ jobId: 3, state: 'queued' }, { status: 202 }),
  ),
  http.get('/api/v1/media/draft-caption/:jobId', () =>
    HttpResponse.json({ state: 'success', caption: 'Toà căn hộ ven sông, mặt tiền kính.' }),
  ),
  http.get('/api/v1/projects/:code', ({ params }) =>
    params.code === 'CHUAXONG'
      ? HttpResponse.json(FAKE_DU_AN_THIEU)
      : HttpResponse.json(FAKE_DU_AN),
  ),
  http.post('/api/v1/projects', () => HttpResponse.json(FAKE_DU_AN, { status: 201 })),
  http.patch('/api/v1/projects/:code', () => HttpResponse.json(FAKE_DU_AN)),
  http.delete('/api/v1/projects/:code', () => new HttpResponse(null, { status: 204 })),

  http.get('/api/v1/projects/:code/zones', () =>
    HttpResponse.json({ items: [FAKE_PHAN_KHU], nextCursor: null, total: 1 }),
  ),
  http.post('/api/v1/projects/:code/zones', () =>
    HttpResponse.json(FAKE_PHAN_KHU, { status: 201 }),
  ),
  http.patch('/api/v1/projects/:code/zones/:zone', () => HttpResponse.json(FAKE_PHAN_KHU)),
  http.delete('/api/v1/projects/:code/zones/:zone', () => new HttpResponse(null, { status: 204 })),

  http.get('/api/v1/projects/:code/buildings', () =>
    HttpResponse.json({ items: [FAKE_TOA], total: 1 }),
  ),
  http.post('/api/v1/projects/:code/buildings', () => HttpResponse.json(FAKE_TOA, { status: 201 })),
  http.patch('/api/v1/projects/:code/buildings/:building', () => HttpResponse.json(FAKE_TOA)),
  http.delete(
    '/api/v1/projects/:code/buildings/:building',
    () => new HttpResponse(null, { status: 204 }),
  ),

  http.get('/api/v1/projects/:code/units', () =>
    HttpResponse.json({ items: [FAKE_CAN], nextCursor: null, total: 1 }),
  ),
  http.get('/api/v1/projects/:code/units/:id', () => HttpResponse.json(FAKE_CAN)),
  http.post('/api/v1/projects/:code/units', () => HttpResponse.json(FAKE_CAN, { status: 201 })),
  http.patch('/api/v1/projects/:code/units/:id', () => HttpResponse.json(FAKE_CAN)),
  http.delete('/api/v1/projects/:code/units/:id', () => new HttpResponse(null, { status: 204 })),

  http.get('/api/v1/projects/:code/documents', () =>
    HttpResponse.json({ items: [FAKE_TAI_LIEU], nextCursor: null, total: 1 }),
  ),
  http.post('/api/v1/projects/:code/documents', () =>
    HttpResponse.json(FAKE_TAI_LIEU, { status: 201 }),
  ),
  http.patch('/api/v1/projects/:code/documents/:id', () => HttpResponse.json(FAKE_TAI_LIEU)),
  http.delete(
    '/api/v1/projects/:code/documents/:id',
    () => new HttpResponse(null, { status: 204 }),
  ),

  http.get('/api/v1/projects/:code/media', () =>
    HttpResponse.json({ items: [], nextCursor: null, total: 0 }),
  ),
  http.post('/api/v1/projects/:code/media', () => HttpResponse.json(FAKE_MEDIA, { status: 201 })),
  http.patch('/api/v1/projects/:code/media/:id', () => HttpResponse.json(FAKE_MEDIA)),
  http.delete('/api/v1/projects/:code/media/:id', () => new HttpResponse(null, { status: 204 })),

  http.post('/api/v1/realestate/uploads', () =>
    HttpResponse.json(
      {
        key: 'tenants/fake/kb-bds/deadbeef/anh.webp',
        contentHash: 'deadbeef',
        contentType: 'image/webp',
      },
      { status: 201 },
    ),
  ),
  // Kho tệp giả không có byte nào — trả 404 để ảnh vỡ THẤY ĐƯỢC. Trả một ảnh
  // placeholder sẽ làm dev tin đường đọc tệp đã chạy trong khi nó chưa được thử.
  http.get('/api/v1/realestate/files', () =>
    HttpResponse.json(
      { error: { code: 'NO_FILE', message: 'Kho tệp giả — chạy backend thật để xem ảnh' } },
      { status: 404 },
    ),
  ),
]
