/**
 * Client HTTP của module kb (M6). Hình dạng lỗi giống mọi endpoint khác:
 * `{error:{code,message}}`.
 */
import { goi } from '@/lib/http'

export interface TaiLieu {
  readonly id: number
  readonly tenFile: string
  readonly loai: string
  readonly kichThuoc: number
  readonly state: 'dang_xu_ly' | 'san_sang' | 'loi'
  readonly chunkCount: number
  readonly loiMessage: string
  readonly uploadedAt: string
  readonly uploadedBy: string | null
}

export function danhSach(): Promise<TaiLieu[]> {
  return goi<TaiLieu[]>('/api/v1/kb/files', {}, 'GET /api/v1/kb/files')
}

export function taiLen(file: File): Promise<TaiLieu> {
  const form = new FormData()
  form.append('file', file)
  return goi<TaiLieu>('/api/v1/kb/files', { method: 'POST', body: form }, 'POST /api/v1/kb/files')
}

export function xoa(id: number): Promise<void> {
  const duong = `/api/v1/kb/files/${id}`
  return goi<void>(duong, { method: 'DELETE' }, `DELETE ${duong}`)
}

/**
 * Một đoạn (chunk) của bản ĐÃ NẠP — Task 15, `sectionPath` rỗng ngoài mọi tiêu đề.
 * `overlapsPrev`: đoạn này mở đầu bằng phần đuôi lặp lại của đoạn trước (chunker
 * mượn lại qua ranh giới) — Task 16.
 */
export interface DoanNoiDung {
  readonly idx: number
  readonly text: string
  readonly sectionPath: string
  readonly overlapsPrev: boolean
}

export function noiDungDaNap(id: number): Promise<DoanNoiDung[]> {
  const duong = `/api/v1/kb/files/${id}/noi-dung`
  return goi<DoanNoiDung[]>(duong, {}, `GET ${duong}`)
}
