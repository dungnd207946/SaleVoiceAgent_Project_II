/**
 * Client + hook của màn «Nhật ký» — `GET /api/v1/audit`.
 * Hợp đồng: `odyssey-portal-backend/docs/contracts/audit.md`.
 *
 * `useInfiniteQuery` chứ không phải trang số: API là keyset (`nextCursor`), và
 * nhật ký là dòng thời gian — «Tải thêm» đúng nghĩa hơn «Trang 3/17».
 * Khoá query mang cả `loc`: đổi bộ lọc là một chuỗi trang MỚI, không nối vào
 * chuỗi cũ.
 */

import { useInfiniteQuery } from '@tanstack/react-query'
import { goi } from '@/lib/http'
import { NHOM_LOC } from './so-hanh-dong'

export interface DongNhatKy {
  readonly id: number
  /** ISO có múi giờ, từ `timestamptz`. */
  readonly luc: string
  readonly hanhDong: string
  /** Nguyên văn cột `actor`: `u_<id>` · `agent` · `platform_admin` · `''`. */
  readonly actorId: string
  readonly actorTen: string | null
  readonly actorEmail: string | null
  readonly chiTiet: Readonly<Record<string, unknown>>
}

export interface TrangNhatKy {
  readonly items: readonly DongNhatKy[]
  readonly nextCursor: string | null
}

/** Trạng thái bộ lọc trên màn — `useState`, KHÔNG search param. */
export interface LocNhatKy {
  /** `NhomLoc.ma` hoặc null = tất cả. */
  readonly nhom: string | null
  /** `YYYY-MM-DD` hoặc null. */
  readonly tu: string | null
  /** «Đến HẾT ngày» — API nhận cận trên MỞ nên gửi `+1 ngày`, xem `duongNhatKy`. */
  readonly denHet: string | null
  /** Hiện hành động máy (`actorId = 'agent'`). Mặc định ẩn. */
  readonly may: boolean
}

export const LOC_MAC_DINH: LocNhatKy = { nhom: null, tu: null, denHet: null, may: false }

export const SO_MOI_TRANG = 50
export const KHOA_NHAT_KY = ['audit'] as const

/** `YYYY-MM-DD` + 1 ngày, tính bằng UTC để không lệ thuộc múi giờ máy. */
export function congMotNgay(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + 1)).toISOString().slice(0, 10)
}

export function duongNhatKy(loc: LocNhatKy, cursor?: string): string {
  const p = new URLSearchParams()
  p.set('limit', String(SO_MOI_TRANG))
  const nhom = loc.nhom ? NHOM_LOC.find((n) => n.ma === loc.nhom) : undefined
  if (nhom) p.set('nhom', nhom.tienTo.join(','))
  if (loc.tu) p.set('from', loc.tu)
  if (loc.denHet) p.set('to', congMotNgay(loc.denHet))
  if (loc.may) p.set('may', 'true')
  if (cursor) p.set('cursor', cursor)
  return `/api/v1/audit?${p.toString()}`
}

export function taiNhatKy(loc: LocNhatKy, cursor?: string): Promise<TrangNhatKy> {
  return goi<TrangNhatKy>(duongNhatKy(loc, cursor))
}

export function useNhatKy(loc: LocNhatKy) {
  return useInfiniteQuery({
    queryKey: [...KHOA_NHAT_KY, loc],
    queryFn: ({ pageParam }) => taiNhatKy(loc, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (cuoi) => cuoi.nextCursor ?? undefined,
  })
}
