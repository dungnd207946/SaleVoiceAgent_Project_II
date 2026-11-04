/**
 * Người dẫn TỰ TẠO của tab Voice — hợp đồng `/api/v1/nhan-vat` (backend
 * `modules/nhan_vat/contracts.py`, field camelCase y nguyên).
 *
 * Khách tạo nhân vật từ VIDEO tự quay, hoặc từ ẢNH (backend gọi API sinh video —
 * nhà cung cấp chọn bằng env phía server, `taoTuAnh` báo có dùng được không). Dựng
 * chạy NỀN (vài phút): FE thăm dò `GET /nhan-vat/{id}` tới khi `san_sang`/`loi`.
 * Nhân vật đang dùng (`dangDung`) là thứ tab Voice gửi lên service lip sync
 * (`?avatar=<avatarId>`); `null` = người dẫn mặc định.
 */
import { useQuery } from '@tanstack/react-query'
import { goi, LoiApi } from '@/lib/http'
import { urlAvatar } from './avatarLipSync'

const GOC = '/api/v1/nhan-vat'

export type TrangThaiNhanVat = 'tao_video' | 'dung' | 'xem_truoc' | 'san_sang' | 'loi'

export interface NhanVat {
  id: string
  ten: string
  nguon: 'video' | 'anh'
  trangThai: TrangThaiNhanVat
  buoc: string | null
  tienDo: number
  loi: { ma: string; huongDan: string; chiTiet: string | null } | null
  dangDung: boolean
  /** Chỉ có khi `san_sang` — id nhân vật trên service lip sync. */
  avatarId: string | null
  posterUrl: string | null
  xemTruoc: { cau: string; url: string }[]
  /** Video NGUỒN (khách upload / AI sinh từ ảnh) — có ngay khi video về kho, kể cả lúc đang
   *  dựng. Tuỳ chọn: backend cũ chưa trả trường này. */
  videoUrl?: string | null
  videoTayUrl?: string | null
  taoLuc: string
}

export interface DanhSachNhanVat {
  nhanVat: NhanVat[]
  dangDung: string | null
  taoTuAnh: boolean
  nhaCungCap: string | null
  toiDa: number
  cauDemo: string[]
}

export interface NhanVatDangDung {
  id: string | null
  ten: string | null
  avatarId: string | null
  posterUrl: string | null
}

export const KHOA_NHAN_VAT = ['nhan-vat'] as const
export const KHOA_DANG_DUNG = ['nhan-vat', 'dang-dung'] as const
export const khoaMotNhanVat = (id: string) => ['nhan-vat', 'mot', id] as const

export const taiDanhSach = () => goi<DanhSachNhanVat>(GOC)
export const taiDangDung = () => goi<NhanVatDangDung>(`${GOC}/dang-dung`)
export const taiNhanVat = (id: string) => goi<NhanVat>(`${GOC}/${id}`)
export const chonNhanVat = (id: string | null) =>
  goi<NhanVatDangDung>(`${GOC}/dang-dung`, { method: 'PUT', body: JSON.stringify({ id }) })
export const thuLai = (id: string) => goi<NhanVat>(`${GOC}/${id}/thu-lai`, { method: 'POST' })
export const xoaNhanVat = (id: string) => goi<void>(`${GOC}/${id}`, { method: 'DELETE' })

/** Đang dựng (chưa tới trạng thái dừng) ⇒ FE còn thăm dò. */
export const dangDung = (nv: Pick<NhanVat, 'trangThai'>) =>
  nv.trangThai !== 'san_sang' && nv.trangThai !== 'loi'

export interface TaoNhanVatIn {
  ten: string
  nguon: 'video' | 'anh'
  tep: File
  tepTay?: File | null
  moTa?: string
}

/**
 * Tạo nhân vật — multipart, có TIẾN ĐỘ UPLOAD (video vài chục MB): `fetch` không báo
 * tiến độ gửi nên dùng XHR. Đồng ý dùng hình ảnh (`dongY`) là điều kiện của nút gửi,
 * nên luôn gửi `true` — backend vẫn kiểm lại.
 */
export function taoNhanVat(dl: TaoNhanVatIn, onTienDo?: (phan: number) => void): Promise<NhanVat> {
  const form = new FormData()
  form.append('ten', dl.ten)
  form.append('nguon', dl.nguon)
  form.append('dongY', 'true')
  form.append('tep', dl.tep)
  if (dl.tepTay) form.append('tepTay', dl.tepTay)
  if (dl.moTa) form.append('moTa', dl.moTa)
  return new Promise((ok, hong) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', GOC)
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onTienDo?.(e.loaded / e.total)
    }
    xhr.onload = () => {
      let body: unknown = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        body = null
      }
      if (xhr.status >= 200 && xhr.status < 300) return ok(body as NhanVat)
      const e = (body as { error?: { code?: string; message?: string } } | null)?.error
      hong(new LoiApi(e?.code ?? 'UNKNOWN', e?.message ?? `${GOC} → ${xhr.status}`, xhr.status))
    }
    xhr.onerror = () => hong(new LoiApi('MANG', 'Mất kết nối khi tải lên', 0))
    xhr.send(form)
  })
}

/** Nhân vật nói thử một câu tuỳ ý — mp4 (blob URL, người gọi tự `revokeObjectURL`). */
export async function xemTruocCau(id: string, cau: string): Promise<string> {
  const res = await fetch(`${GOC}/${id}/xem-truoc`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cau }),
  })
  if (!res.ok) {
    const b = (await res.json().catch(() => null)) as {
      error?: { code?: string; message?: string }
    } | null
    throw new LoiApi(
      b?.error?.code ?? 'UNKNOWN',
      b?.error?.message ?? 'Không tạo được video xem trước',
      res.status,
    )
  }
  return URL.createObjectURL(await res.blob())
}

/** Nhãn bước dựng cho người dùng (mã bước từ backend/service lip sync). */
export const NHAN_BUOC: Record<string, string> = {
  gui_yeu_cau: 'Đang gửi ảnh cho dịch vụ tạo video',
  dang_tao_video: 'AI đang tạo video từ ảnh (vài phút)',
  cho_dung: 'Đang xếp hàng dựng nhân vật',
  cho: 'Đang xếp hàng dựng nhân vật',
  bat_dau: 'Bắt đầu dựng',
  chuan_hoa: 'Chuẩn hoá video',
  tach_nen: 'Tách nền',
  phan_tich: 'Phân tích tư thế và khẩu hình',
  do_mat: 'Dò khuôn mặt từng khung hình',
  mieng_khep: 'Chuẩn bị khẩu hình',
  xem_truoc: 'Tạo video nói thử',
}

export function nhanBuoc(nv: Pick<NhanVat, 'trangThai' | 'buoc'>): string {
  const theoBuoc = nv.buoc ? NHAN_BUOC[nv.buoc] : undefined
  if (theoBuoc) return theoBuoc
  if (nv.trangThai === 'tao_video') return 'AI đang tạo video từ ảnh (vài phút)'
  if (nv.trangThai === 'xem_truoc') return 'Tạo video nói thử'
  return 'Đang dựng nhân vật'
}

/** Nhân vật đang dùng — `null` khi lip sync tắt, chưa tải, hoặc lỗi (⇒ người dẫn mặc định). */
export function useNguoiDanDangDung(): NhanVatDangDung | null {
  const bat = !!urlAvatar()
  const q = useQuery({ queryKey: KHOA_DANG_DUNG, queryFn: taiDangDung, enabled: bat, retry: false })
  return bat ? (q.data ?? null) : null
}
