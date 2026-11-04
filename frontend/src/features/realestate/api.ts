/**
 * Client HTTP của module realestate (M4) — KB Bất động sản.
 *
 * Hình dạng lỗi giống mọi endpoint khác: `{error:{code,message}}`, cộng
 * `error.fields` cho 422 (xem `LoiApi.truong`).
 *
 * Kiểu ở đây là bản chép tay của `modules/realestate/contracts.py` + các DTO ghi
 * trong `router.py`. Nguồn là bên Python — nó vừa dựng form vừa là thứ agent
 * đọc, nên hai bên lệch nghĩa là màn hình cho sửa một trường agent không thấy.
 * Cổng canh hiện là 422 của backend, không phải một test (cùng khoảng hở đã ghi
 * ở `features/agent/api.ts`; khép lại khi `contracts/openapi.json` có).
 *
 * BỐN CỘT KHÔNG CÓ MẶT trong kiểu ghi (`*In`/`*Patch`): `id`/`tenantId`/
 * `createdAt`/`updatedAt` do hệ thống quản. Hai cột `coverMediaId`/`mapMediaId`
 * CÓ ở kiểu đọc nhưng KHÔNG ở kiểu ghi — router tự gán chúng từ `coverMedia`/
 * `mapMedia`, xem `OMedia`.
 */
import { goi as goiApi } from '@/lib/http'

/** Tiền tố mọi đường dẫn. `/api/v1` do `api/app.py` gắn, không phải router. */
const GOC = '/api/v1'

const goi = <T>(duong: string, init?: RequestInit) => goiApi<T>(`${GOC}${duong}`, init, duong)

// ─── Kiểu đọc (khớp `contracts.py`) ─────────────────────────────────────────

export type TrangThai = 'draft' | 'published' | 'archived'

/** Một hạng mục của `projects.handover_standard` (jsonb mảng). Chỉ `item` bắt buộc. */
export interface HangMucBanGiao {
  item: string
  material: string
  brand: string
  origin: string
  note: string
}

export interface DuAn {
  readonly id: number
  readonly projectCode: string
  readonly name: string
  readonly category: readonly string[]
  readonly region: string
  readonly address: string
  readonly investor: string
  readonly developer: string
  readonly totalLandAreaM2: number | null
  readonly floorAreaM2: number | null
  readonly buildDensityPct: number | null
  readonly productScale: string
  readonly amenities: string
  readonly ownershipForm: string
  readonly handoverStandard: readonly HangMucBanGiao[]
  readonly totalInvestmentVnd: number | null
  readonly salePhase: string
  readonly overview: string
  readonly link360: string
  readonly coverMediaId: number | null
  readonly mapMediaId: number | null
  readonly status: TrangThai
  readonly createdAt: string
  readonly updatedAt: string
  readonly totalUnits?: number | null | undefined
  readonly numBuildings?: number | null | undefined
  readonly managementFeeVndM2?: number | null | undefined
  readonly parkingCarFeeVnd?: number | null | undefined
  readonly parkingMotoFeeVnd?: number | null | undefined
}

export interface PhanKhu {
  readonly id: number
  readonly projectCode: string
  readonly zoneCode: string
  readonly name: string
  readonly category: string | null
  readonly productScale: string
  readonly overview: string
  readonly coverMediaId: number | null
  readonly mapMediaId: number | null
  readonly status: TrangThai
  readonly createdAt: string
  readonly updatedAt: string
  readonly salePhase?: string | null | undefined
  readonly note?: string | undefined
  readonly amenities?: string | undefined
  readonly numBuildings?: number | null | undefined
  readonly totalUnits?: number | null | undefined
  /** Số căn đã nhập của phân khu (backend đếm). */
  readonly unitCount?: number | undefined
}

/** Toà / block. `buildingCode` trùng `units.block` của các căn thuộc toà. */
export interface Toa {
  readonly id: number
  readonly projectCode: string
  readonly zoneCode: string | null
  readonly buildingCode: string
  readonly name: string
  readonly numFloors: number | null
  readonly numBasements: number | null
  readonly unitsPerFloor: number | null
  readonly elevatorsPassenger: number | null
  readonly elevatorsService: number | null
  readonly carSlots: number | null
  readonly motoSlots: number | null
  readonly ceilingHeightM: number | null
  readonly facing: string | null
  readonly salePhase: string | null
  readonly amenities: string
  readonly overview: string
  readonly status: TrangThai
  readonly unitCount: number
  readonly createdAt: string
  readonly updatedAt: string
}

export interface Can {
  readonly id: number
  readonly projectCode: string
  readonly zoneCode: string | null
  readonly zoneName: string | null
  readonly unitCode: string
  readonly productType: string
  readonly bedrooms: number | null
  readonly block: string | null
  readonly floor: number | null
  readonly numFloors: number | null
  readonly direction: string | null
  readonly areaBuiltM2: number | null
  readonly areaWallM2: number | null
  readonly areaLandM2: number | null
  readonly priceVnd: number | null
  readonly pricePerM2Vnd: number | null
  readonly saleStatus: string
  readonly imageUrl: string | null
  readonly status: TrangThai
  readonly createdAt: string
  readonly updatedAt: string
  readonly views?: readonly string[] | undefined
  readonly isCorner?: boolean | null | undefined
  readonly openSides?: number | null | undefined
  readonly bathrooms?: number | null | undefined
  readonly handoverCondition?: string | null | undefined
  readonly hrBalconyM2?: number | null | undefined
  readonly hrLoggiaM2?: number | null | undefined
  readonly lrFrontageM?: number | null | undefined
  readonly lrDepthM?: number | null | undefined
  readonly lrRoadWidthM?: number | null | undefined
}

export type LoaiTaiLieu = 'csbh' | 'phap_ly' | 'huong_dan' | 'khac'

export interface TaiLieu {
  readonly id: number
  readonly projectCode: string
  readonly loai: LoaiTaiLieu
  readonly title: string
  readonly body: string
  readonly fileUrl: string | null
  readonly bodyChoDuyet: boolean
  readonly status: TrangThai
  readonly createdAt: string
  readonly updatedAt: string
}

export interface Media {
  readonly id: number
  readonly projectCode: string
  readonly zoneCode: string | null
  readonly unitCode: string | null
  readonly contentType: string
  readonly category: string
  readonly caption: string
  readonly fileName: string
  readonly mediaUrl: string
  readonly thumbUrl: string | null
  readonly contentHash: string
  readonly uploadedBy: string | null
  readonly status: TrangThai
  readonly createdAt: string
  readonly updatedAt: string
}

export interface Trang<T> {
  readonly items: readonly T[]
  readonly nextCursor: string | null
  readonly total: number
}

export const SENTINEL = '__ALL__'

// ─── Kiểu ghi ───────────────────────────────────────────────────────────────

export interface MediaKem {
  mediaUrl: string
  caption?: string | undefined
  fileName?: string | undefined
  contentType?: string | undefined
  thumbUrl?: string | null | undefined
  contentHash?: string | undefined
}

export interface DuAnGhi {
  projectCode?: string | undefined
  name?: string | undefined
  category?: readonly string[] | undefined
  region?: string | undefined
  address?: string | undefined
  investor?: string | undefined
  developer?: string | undefined
  totalLandAreaM2?: number | null | undefined
  floorAreaM2?: number | null | undefined
  buildDensityPct?: number | null | undefined
  productScale?: string | undefined
  amenities?: string | undefined
  ownershipForm?: string | undefined
  handoverStandard?: readonly HangMucBanGiao[] | undefined
  totalInvestmentVnd?: number | null | undefined
  totalUnits?: number | null | undefined
  numBuildings?: number | null | undefined
  managementFeeVndM2?: number | null | undefined
  parkingCarFeeVnd?: number | null | undefined
  parkingMotoFeeVnd?: number | null | undefined
  salePhase?: string | undefined
  overview?: string | undefined
  link360?: string | undefined
  status?: TrangThai | undefined
  coverMedia?: MediaKem | null | undefined
  mapMedia?: MediaKem | null | undefined
}

export interface PhanKhuGhi {
  zoneCode?: string | undefined
  name?: string | undefined
  category?: string | null | undefined
  productScale?: string | undefined
  overview?: string | undefined
  status?: TrangThai | undefined
  coverMedia?: MediaKem | null | undefined
  mapMedia?: MediaKem | null | undefined
  salePhase?: string | null | undefined
  note?: string | undefined
  amenities?: string | undefined
  numBuildings?: number | null | undefined
  totalUnits?: number | null | undefined
}

export interface ToaGhi {
  buildingCode?: string | undefined
  zoneCode?: string | null | undefined
  name?: string | undefined
  numFloors?: number | null | undefined
  numBasements?: number | null | undefined
  unitsPerFloor?: number | null | undefined
  elevatorsPassenger?: number | null | undefined
  elevatorsService?: number | null | undefined
  carSlots?: number | null | undefined
  motoSlots?: number | null | undefined
  ceilingHeightM?: number | null | undefined
  facing?: string | null | undefined
  salePhase?: string | null | undefined
  amenities?: string | undefined
  overview?: string | undefined
  status?: TrangThai | undefined
}

export interface CanGhi {
  zoneCode?: string | undefined
  unitCode?: string | undefined
  productType?: string | undefined
  bedrooms?: number | null | undefined
  block?: string | null | undefined
  floor?: number | null | undefined
  numFloors?: number | null | undefined
  direction?: string | null | undefined
  areaBuiltM2?: number | null | undefined
  areaWallM2?: number | null | undefined
  areaLandM2?: number | null | undefined
  priceVnd?: number | null | undefined
  pricePerM2Vnd?: number | null | undefined
  saleStatus?: string | undefined
  imageUrl?: string | null | undefined
  status?: TrangThai | undefined
  views?: readonly string[] | undefined
  isCorner?: boolean | null | undefined
  openSides?: number | null | undefined
  bathrooms?: number | null | undefined
  handoverCondition?: string | null | undefined
  hrBalconyM2?: number | null | undefined
  hrLoggiaM2?: number | null | undefined
  lrFrontageM?: number | null | undefined
  lrDepthM?: number | null | undefined
  lrRoadWidthM?: number | null | undefined
}

export interface TaiLieuGhi {
  title?: string | undefined
  loai?: LoaiTaiLieu | undefined
  body?: string | undefined
  fileUrl?: string | null | undefined
  status?: TrangThai | undefined
}

export interface MediaGhi {
  contentType?: string | undefined
  category?: string | undefined
  mediaUrl?: string | undefined
  zoneCode?: string | null | undefined
  unitCode?: string | null | undefined
  caption?: string | undefined
  fileName?: string | undefined
  thumbUrl?: string | null | undefined
  contentHash?: string | undefined
  status?: TrangThai | undefined
}

// ─── Kho tệp ────────────────────────────────────────────────────────────────

export interface TepDaLen {
  readonly key: string
  readonly contentHash: string
  readonly contentType: string
}

export function taiTepLen(tep: File): Promise<TepDaLen> {
  const form = new FormData()
  form.append('file', tep)
  return goiApi<TepDaLen>(
    `${GOC}/realestate/uploads`,
    { method: 'POST', body: form },
    'POST /realestate/uploads',
  )
}

export function nguonAnh(gia_tri: string | null | undefined): string {
  if (!gia_tri) return ''
  if (/^https?:\/\//i.test(gia_tri)) return gia_tri
  return `${GOC}/realestate/files?key=${encodeURIComponent(gia_tri)}`
}

/** True = giá trị là nguồn ngoài (không phải tệp trong kho của ta). */
export function laNguonNgoai(gia_tri: string | null | undefined): boolean {
  return !!gia_tri && /^https?:\/\//i.test(gia_tri)
}

// ─── Dự án ──────────────────────────────────────────────────────────────────

export interface LocDuAn {
  search?: string | undefined
  region?: string | undefined
  limit?: number | undefined
  offset?: number | undefined
  cursor?: string | null | undefined
}

function qs(loc: Record<string, string | number | null | undefined>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(loc)) {
    if (v === undefined || v === null || v === '') continue
    p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function danhSachDuAn(loc: LocDuAn = {}): Promise<Trang<DuAn>> {
  return goi(`/projects${qs({ ...loc, cursor: loc.cursor ?? undefined })}`)
}

export function docDuAn(projectCode: string): Promise<DuAn> {
  return goi(`/projects/${encodeURIComponent(projectCode)}`)
}

export function taoDuAn(body: DuAnGhi): Promise<DuAn> {
  return goi('/projects', { method: 'POST', body: JSON.stringify(body) })
}

export function suaDuAn(projectCode: string, body: DuAnGhi): Promise<DuAn> {
  return goi(`/projects/${encodeURIComponent(projectCode)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function xoaDuAn(projectCode: string): Promise<void> {
  return goi(`/projects/${encodeURIComponent(projectCode)}`, { method: 'DELETE' })
}

// ─── Phân khu ───────────────────────────────────────────────────────────────

export interface LocTrang {
  readonly limit?: number
  readonly offset?: number
  readonly cursor?: string | null
}

export function danhSachPhanKhu(projectCode: string, loc: LocTrang = {}): Promise<Trang<PhanKhu>> {
  return goi(
    `/projects/${encodeURIComponent(projectCode)}/zones${qs({ ...loc, cursor: loc.cursor ?? undefined })}`,
  )
}

export function taoPhanKhu(projectCode: string, body: PhanKhuGhi): Promise<PhanKhu> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/zones`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function suaPhanKhu(
  projectCode: string,
  zoneCode: string,
  body: PhanKhuGhi,
): Promise<PhanKhu> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/zones/${encodeURIComponent(zoneCode)}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function xoaPhanKhu(projectCode: string, zoneCode: string): Promise<void> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/zones/${encodeURIComponent(zoneCode)}`, {
    method: 'DELETE',
  })
}

export function danhSachToa(
  projectCode: string,
): Promise<{ items: readonly Toa[]; total: number }> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/buildings`)
}

export function taoToa(projectCode: string, body: ToaGhi): Promise<Toa> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/buildings`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function suaToa(projectCode: string, buildingCode: string, body: ToaGhi): Promise<Toa> {
  return goi(
    `/projects/${encodeURIComponent(projectCode)}/buildings/${encodeURIComponent(buildingCode)}`,
    { method: 'PATCH', body: JSON.stringify(body) },
  )
}

export function xoaToa(projectCode: string, buildingCode: string): Promise<void> {
  return goi(
    `/projects/${encodeURIComponent(projectCode)}/buildings/${encodeURIComponent(buildingCode)}`,
    { method: 'DELETE' },
  )
}

// ─── Căn ────────────────────────────────────────────────────────────────────

export interface LocCan {
  zone_code?: string | undefined
  product_type?: string | undefined
  sale_status?: string | undefined
  direction?: string | undefined
  unit_code?: string | undefined
  /** Lọc theo trạng thái phát hành. Rỗng = mọi trạng thái. */
  status?: TrangThai | '' | undefined
  sort?: SapXepCan | undefined
  desc?: 'true' | undefined
  limit?: number | undefined
  offset?: number | undefined
  cursor?: string | null | undefined
}

export type SapXepCan = 'price_vnd' | 'bedrooms' | 'area_built_m2'

export interface FacetCan {
  readonly productType: readonly string[]
  readonly direction: readonly string[]
}

export function facetCan(projectCode: string): Promise<FacetCan> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/units/facets`)
}

export function danhSachCan(projectCode: string, loc: LocCan = {}): Promise<Trang<Can>> {
  return goi(
    `/projects/${encodeURIComponent(projectCode)}/units${qs({ ...loc, cursor: loc.cursor ?? undefined })}`,
  )
}

export function docCan(projectCode: string, unitId: number): Promise<Can> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/units/${unitId}`)
}

export function taoCan(projectCode: string, body: CanGhi): Promise<Can> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/units`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function suaCan(projectCode: string, unitId: number, body: CanGhi): Promise<Can> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/units/${unitId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function xoaCan(projectCode: string, unitId: number): Promise<void> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/units/${unitId}`, { method: 'DELETE' })
}

// ─── Tài liệu ───────────────────────────────────────────────────────────────

export function danhSachTaiLieu(projectCode: string, loc: LocTrang = {}): Promise<Trang<TaiLieu>> {
  return goi(
    `/projects/${encodeURIComponent(projectCode)}/documents${qs({ ...loc, cursor: loc.cursor ?? undefined })}`,
  )
}

export function taoTaiLieu(projectCode: string, body: TaiLieuGhi): Promise<TaiLieu> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/documents`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function suaTaiLieu(projectCode: string, docId: number, body: TaiLieuGhi): Promise<TaiLieu> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/documents/${docId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function xoaTaiLieu(projectCode: string, docId: number): Promise<void> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/documents/${docId}`, {
    method: 'DELETE',
  })
}

// ─── Media ──────────────────────────────────────────────────────────────────

export interface LocMedia {
  zone_code?: string | undefined
  unit_code?: string | undefined
  category?: string | undefined
  content_type?: string | undefined
  limit?: number | undefined
  offset?: number | undefined
  cursor?: string | null | undefined
}

export function danhSachMedia(projectCode: string, loc: LocMedia = {}): Promise<Trang<Media>> {
  return goi(
    `/projects/${encodeURIComponent(projectCode)}/media${qs({ ...loc, cursor: loc.cursor ?? undefined })}`,
  )
}

export function taoMedia(projectCode: string, body: MediaGhi): Promise<Media> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/media`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function suaMedia(projectCode: string, mediaId: number, body: MediaGhi): Promise<Media> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/media/${mediaId}`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export function xoaMedia(projectCode: string, mediaId: number): Promise<void> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/media/${mediaId}`, { method: 'DELETE' })
}

// ─── Nạp kiến thức cho agent ────────────────────────────────────────────────

export interface KbStatus {
  readonly projectCode: string
  readonly indexing: boolean
  readonly hasError: boolean
  /** Tổng mục agent cần biết. 0 = dự án chưa có gì để nạp. */
  readonly total: number
  /** Số mục đã lên Qdrant và không lệch. */
  readonly done: number
}

export type SyncMode = 'delta' | 'full'

export interface EnrichItem {
  readonly entity: 'media' | 'documents'
  readonly recordId: number
  readonly state: 'queued' | 'running' | 'success' | 'failed'
  readonly message: string
}

export function fetchKbStatus(): Promise<KbStatus[]> {
  return goi('/projects/kb-status')
}

export function syncKb(
  projectCode: string,
  mode: SyncMode,
): Promise<{ jobId: number; state: string }> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/sync-kb?mode=${mode}`, {
    method: 'POST',
  })
}

export function duyetTaiLieu(projectCode: string, docId: number): Promise<{ approved: boolean }> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/documents/${docId}/approve`, {
    method: 'POST',
  })
}

export function fetchEnrichStatus(projectCode: string): Promise<EnrichItem[]> {
  return goi(`/projects/${encodeURIComponent(projectCode)}/enrich-status`)
}

export interface CaptionNhap {
  readonly state: 'queued' | 'running' | 'success' | 'failed'
  readonly caption: string
}

export function taoCaptionNhap(
  mediaUrl: string,
  contentType = 'image',
  category = '',
): Promise<{ jobId: number; state: string }> {
  return goi('/media/draft-caption', {
    method: 'POST',
    body: JSON.stringify({ mediaUrl, contentType, category }),
  })
}

export function docCaptionNhap(jobId: number): Promise<CaptionNhap> {
  return goi(`/media/draft-caption/${jobId}`)
}

/** Một hàng `GET /kb-web/projects` — chỉ các trường dòng «Hồ sơ dữ liệu ngoài» ở `/pform` cần. */
export interface HoSoNgoai {
  readonly code: string
  readonly soMuc: number
  /** Backend cũ chưa trả. */
  readonly soChuDe?: number
  readonly capNhatLuc: string | null
}

/** Thiếu quyền `kb_web.read` ⇒ 403 ⇒ ném; nơi gọi coi lỗi là «không hiện dòng». */
export const docHoSoNgoai = () => goi<HoSoNgoai[]>('/kb-web/projects')
