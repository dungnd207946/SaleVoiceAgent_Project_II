/**
 * Client HTTP của màn «Dữ liệu ngoài» — hợp đồng `docs/contracts/kb-web.md` (repo backend),
 * tiền tố `/api/v1/kb-web`. Mọi mốc thời gian là ISO có múi giờ; `nhan.ts` dịch mã → chữ.
 */
import { useQuery } from '@tanstack/react-query'
import { goi as goiApi } from '@/lib/http'

export type Mode = 'nightly' | 'weekly' | 'rebuild'
export type TrangThaiViec = 'queued' | 'running' | 'success' | 'failed'
export type TinhTrangNguon = 'ok' | 'blocked' | 'no_feed' | 'timeout' | 'private'

export interface Viec {
  readonly id: number
  readonly loai: 'kbweb_run' | 'kbweb_project' | 'kbweb_probe'
  readonly mode: string
  readonly duAn: string | null
  readonly duAnTen?: string | null
  /** Chỉ lượt kiểm tra nguồn. */
  readonly url?: string | null
  readonly tinhTrangNguon?: TinhTrangNguon | null
  readonly trangThai: TrangThaiViec
  readonly nguoi: string
  /** Tên người bấm; vắng với lượt theo lịch. */
  readonly nguoiTen?: string | null
  readonly taoLuc: string
  readonly batDau: string | null
  readonly ketThuc: string | null
  readonly soLuong: number
  readonly thongDiep: string
  /** Tiền của lượt chạy (VND, chuỗi decimal); null khi chưa ghi sổ hoặc không có quyền xem chi phí. */
  readonly chiPhi?: string | null
}

export interface TongQuan {
  readonly soDuAn: number
  readonly soDuAnCoHoSo: number
  readonly hoSoCuNhat: string | null
  readonly baiBayNgay: number
  readonly baiBaMuoiNgay: number
  readonly soNguonBat: number
  readonly groundingThang: number
  readonly groundingTran: number
  readonly trinhDuyetHomNay: number
  readonly trinhDuyetTran: number
  readonly dangChay: readonly Viec[]
  readonly loiGanDay: readonly Viec[]
  readonly lanKeTiep: string | null
}

export interface Nguon {
  readonly id: number
  readonly domain: string
  readonly ten: string
  readonly bat: boolean
  readonly macDinh: boolean
  readonly cheDo: 'http' | 'browser'
  readonly theoDoi: 'news' | 'living'
  readonly baiBayNgay: number
  readonly tinhTrang: TinhTrangNguon | null
  readonly ghiChu: string
  readonly thuLuc: string | null
}

export interface NguonDeXuat {
  readonly domain: string
  readonly ten: string
  readonly cheDo: 'http' | 'browser'
  readonly theoDoi: 'news' | 'living'
  readonly rss: readonly string[]
  readonly sitemapIndex: string
  readonly newsSitemaps: readonly string[]
  readonly categoryPages: readonly string[]
  readonly articlePattern: string
}

export interface KetQuaThu {
  readonly trangThai: TinhTrangNguon
  readonly ghiChu: string
  readonly soBai: number
  readonly soTrangThu: number
  readonly soTrangDoc: number
  readonly daCo: boolean
  readonly deXuat: NguonDeXuat | null
}

export interface ThuDangChay {
  readonly token: string
  readonly jobId: number
}

export interface TrangThaiThu {
  readonly trangThai: 'dang_chay' | 'xong' | 'loi'
  readonly ketQua: KetQuaThu | null
}

export interface ChuDe {
  readonly id: number
  readonly code: string
  readonly ten: string
  readonly nhan: string
  readonly moTa: string
  readonly cauTim: readonly string[]
  readonly tuKhoa: readonly string[]
  readonly bat: boolean
  readonly macDinh: boolean
  readonly vaoHoSo: boolean
  readonly thuTu: number
}

export interface Lich {
  readonly mode: Mode
  readonly bat: boolean
  readonly gio: string
  readonly ngayTrongTuan: readonly number[]
  /** Viết lại mỗi N tháng (1..12); chỉ `rebuild`. */
  readonly soThang: number | null
  readonly ngayTrongChuKy: 'd1' | 'd15' | 'first_sunday' | null
  readonly latCat: number
  readonly lanGanNhat: string | null
  readonly lanKeTiep: string | null
}

export interface GioiHan {
  readonly groundingThang: number
  readonly trinhDuyetNgay: number
  readonly ngayHoi: number
}

export interface LichTong {
  readonly lich: readonly Lich[]
  readonly gioiHan: GioiHan
}

export interface LichGui {
  readonly mode: Mode
  readonly bat: boolean
  readonly gio: string
  readonly ngayTrongTuan?: readonly number[]
  readonly soThang?: number | null
  readonly ngayTrongChuKy?: 'd1' | 'd15' | 'first_sunday' | null
  readonly latCat?: number
}

export interface DuAn {
  readonly code: string
  readonly ten: string
  readonly soMuc: number
  /** Backend cũ chưa trả. */
  readonly soChuDe?: number
  readonly capNhatLuc: string | null
  readonly dangChay: boolean
  readonly viecGanNhat: Viec | null
}

/** Một dòng cho «Tổng quan» và cho mỗi chủ đề đang bật ở tab Chủ đề, cùng thứ tự. */
export interface MucHoSo {
  readonly nhan: string
  /** Backend cũ chưa trả — dùng `nhan`. */
  readonly ten?: string
  /** Rỗng = chưa có thông tin. */
  readonly noiDung: string
  readonly nguon: readonly { readonly url: string; readonly ten: string; readonly ngay: string | null }[]
  readonly capNhatLuc: string | null
  /** Backend cũ chưa trả — xem `mucAn`. */
  readonly an?: boolean
}

export interface BaiDaThu {
  readonly url: string
  readonly tieuDe: string
  readonly domain: string
  readonly ngayDang: string | null
  readonly thuLuc: string | null
  readonly loai: boolean
}

export interface ChiTietDuAn {
  readonly code: string
  readonly ten: string
  readonly muc: readonly MucHoSo[]
  readonly mucAn: readonly string[]
  readonly bai: readonly BaiDaThu[]
  readonly dangChay: boolean
}

const GOC = '/api/v1/kb-web'

const goi = <T>(duong: string, init: { method?: string; body?: string } = {}) =>
  goiApi<T>(`${GOC}${duong}`, { credentials: 'include', ...init }, `${init.method ?? 'GET'} ${duong}`)

const json = (body: unknown) => JSON.stringify(body)

// ─── đọc ─────────────────────────────────────────────────────────────────────

export const docTongQuan = () => goi<TongQuan>('/overview')
export const docWorker = () => goi<{ dangChay: boolean }>('/worker')
export const docNguon = () => goi<Nguon[]>('/sources')
export const docChuDe = () => goi<ChuDe[]>('/topics')
export const docLich = () => goi<LichTong>('/schedules')
export const docDuAn = () => goi<DuAn[]>('/projects')
export const docChiTietDuAn = (code: string) => goi<ChiTietDuAn>(`/projects/${encodeURIComponent(code)}`)
export const docNhatKy = (limit = 50) => goi<Viec[]>(`/jobs?limit=${limit}`)

// ─── nguồn ───────────────────────────────────────────────────────────────────

export const thuNguon = (url: string) => goi<ThuDangChay>('/sources/probe', { method: 'POST', body: json({ url }) })
export const ketQuaThu = (token: string) => goi<TrangThaiThu>(`/sources/probe/${encodeURIComponent(token)}`)
export const themNguon = (body: NguonDeXuat & { tinhTrang: 'ok' | 'no_feed'; ghiChu: string }) =>
  goi<Nguon>('/sources', { method: 'POST', body: json(body) })
export const suaNguon = (id: number, body: { bat?: boolean; ten?: string }) =>
  goi<Nguon>(`/sources/${id}`, { method: 'PATCH', body: json(body) })
export const xoaNguon = (id: number) => goi<void>(`/sources/${id}`, { method: 'DELETE' })
export const thuLaiNguon = (id: number) => goi<ThuDangChay>(`/sources/${id}/retry`, { method: 'POST' })
export const ghiKetQuaThu = (id: number, kq: KetQuaThu) =>
  goi<Nguon>(`/sources/${id}/probe-result`, { method: 'POST', body: json(kq) })

// ─── chủ đề ──────────────────────────────────────────────────────────────────

export const soanChuDe = (ten: string, moTa: string) =>
  goi<{ cauTim: string[]; tuKhoa: string[] }>('/topics/draft', { method: 'POST', body: json({ ten, moTa }) })
export const themChuDe = (body: { ten: string; moTa: string; cauTim: string[]; tuKhoa: string[] }) =>
  goi<ChuDe>('/topics', { method: 'POST', body: json(body) })
export const suaChuDe = (
  id: number,
  body: { bat?: boolean; ten?: string; moTa?: string; cauTim?: string[]; tuKhoa?: string[] },
) => goi<ChuDe>(`/topics/${id}`, { method: 'PATCH', body: json(body) })
export const xoaChuDe = (id: number) => goi<void>(`/topics/${id}`, { method: 'DELETE' })

// ─── lịch · chạy ─────────────────────────────────────────────────────────────

export const luuLich = (body: { lich: LichGui[]; gioiHan?: GioiHan }) =>
  goi<LichTong>('/schedules', { method: 'PUT', body: json(body) })
export const chayNgay = (mode: Mode) => goi<Viec>(`/schedules/${mode}/run`, { method: 'POST' })

// ─── dự án ───────────────────────────────────────────────────────────────────

export const lamMoiDuAn = (code: string, mode: 'init' | 'rebuild') =>
  goi<Viec>(`/projects/${encodeURIComponent(code)}/refresh`, { method: 'POST', body: json({ mode }) })
export const anMuc = (code: string, nhan: string, an: boolean) =>
  goi<void>(`/projects/${encodeURIComponent(code)}/items`, { method: 'POST', body: json({ nhan, an }) })
export const loaiBai = (code: string, url: string, loai: boolean) =>
  goi<void>(`/projects/${encodeURIComponent(code)}/pages`, { method: 'POST', body: json({ url, loai }) })

// ─── hook ────────────────────────────────────────────────────────────────────

export const KHOA = {
  tongQuan: ['kb-web', 'overview'] as const,
  nguon: ['kb-web', 'sources'] as const,
  chuDe: ['kb-web', 'topics'] as const,
  lich: ['kb-web', 'schedules'] as const,
  duAn: ['kb-web', 'projects'] as const,
  chiTiet: (code: string) => ['kb-web', 'projects', code] as const,
  nhatKy: ['kb-web', 'jobs'] as const,
}

/** Có việc đang chạy thì làm tươi mỗi 5 s — khuôn poll của `kb/files`. */
function nhipPoll(dangChay: boolean) {
  return dangChay ? 5_000 : false
}

export function useTongQuan() {
  return useQuery({
    queryKey: KHOA.tongQuan,
    queryFn: docTongQuan,
    refetchInterval: (q) => nhipPoll((q.state.data?.dangChay.length ?? 0) > 0),
  })
}

export function useNhatKy() {
  return useQuery({
    queryKey: KHOA.nhatKy,
    queryFn: () => docNhatKy(500),
    refetchInterval: (q) =>
      nhipPoll((q.state.data ?? []).some((v) => v.trangThai === 'queued' || v.trangThai === 'running')),
  })
}

export function useDuAn() {
  return useQuery({
    queryKey: KHOA.duAn,
    queryFn: docDuAn,
    refetchInterval: (q) => nhipPoll((q.state.data ?? []).some((d) => d.dangChay)),
  })
}
