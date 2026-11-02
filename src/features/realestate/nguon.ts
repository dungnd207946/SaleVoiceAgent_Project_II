/**
 * Cổng nạp dữ liệu ngoài — hợp đồng HTTP của tab «Nguồn dữ liệu» (`/projects`).
 *
 * ⚠️ FE ĐỊNH HỢP ĐỒNG TRƯỚC — BACKEND CHƯA CÓ. Cùng lối `/agent/try` và
 * `/api/v1/linh-vuc` đã đi: dựng màn trên fake MSW để nhìn thấy thiết kế trước
 * khi chốt spec. **Đừng lấy hành vi của fake làm sự thật về backend** (luật đã
 * ghi ở CLAUDE.md, mục Gotchas — `handlers.ts` là bản sao viết tay không có cổng
 * parity nào canh).
 *
 * ── VÌ SAO CÓ CỔNG NÀY ──────────────────────────────────────────────────────
 * Tenant đã có hệ thống riêng (CRM/ERP/web bán hàng) chứa sẵn dự án · phân khu ·
 * quỹ căn. Hướng đầu tiên — Odyssey viết một adapter cho từng API của từng khách
 * — không tổng quát hoá được: mỗi nơi một kiểu xác thực, một kiểu phân trang,
 * một kiểu báo lỗi, một cách biết cái gì vừa đổi.
 *
 * ── SCHEMA CỐ ĐỊNH, ADAPTER Ở PHÍA KHÁCH (chốt 2026-08-14) ─────────────────
 * Odyssey công bố MỘT hợp đồng và MỘT cổng. Hệ thống của khách phải gửi **đúng
 * schema này**; việc dịch từ mô hình của họ sang là adapter **bên họ viết, chạy
 * ở phía họ**. Mình chỉ cung cấp đầu vào.
 *
 * Một vòng thiết kế trước đó đi hướng «vỏ cố định + ruột tự do (`attributes`
 * JSONB) + bảng ánh xạ trường theo tenant», và nó đã bị BỎ: nó đẩy việc map sang
 * cho quản trị workspace ngồi bấm tay, và đẻ ra một tập phép biến đổi phải bảo
 * trì. Đừng dựng lại nó — xem `docs/superpowers/specs/` khi spec ra đời.
 *
 * ── HAI LUẬT ĐI KÈM SCHEMA CỐ ĐỊNH ─────────────────────────────────────────
 *  1. **Trường lạ ⇒ BỎ QUA IM LẶNG, không từ chối bản ghi** (chốt 2026-08-14).
 *     Hệ thống bên khách sẽ mọc thêm cột theo thời gian; nếu mỗi lần như thế là
 *     một sự cố bên mình thì hợp đồng này giòn tới mức không dùng được.
 *  2. **Phiên bản nằm trên đường dẫn** (`/v1/`), và luật đổi schema là **chỉ
 *     thêm, không đổi tên, không bỏ**. Schema cố định nghĩa là N adapter ngoài
 *     kia đang code vào nó — thêm một trường bắt buộc là làm gãy tất cả.
 */

import { goi } from '@/lib/http'

const GOC = '/api/v1'

export const LINH_VUC = 'realestate'

export const PHIEN_BAN = 'v1'

const NEN = `${GOC}/ingest/${LINH_VUC}/${PHIEN_BAN}`

// ─── Kiểu đọc ───────────────────────────────────────────────────────────────

export type Entity = 'project' | 'zone' | 'unit' | 'document' | 'media'

export const NHAN_ENTITY: Readonly<Record<Entity, string>> = {
  project: 'Dự án',
  zone: 'Phân khu',
  unit: 'Căn',
  document: 'Tài liệu',
  media: 'Media',
}

export interface Token {
  readonly id: number
  readonly label: string
  readonly token: string
}

export interface ThongKeNap {
  readonly nhanCuoiLuc: string | null
  readonly soNhan24h: number
  readonly soGhiDuoc24h: number
  readonly soHong24h: number
}

export interface TongQuanNguon {
  readonly diemNap: string
  readonly docsUrl: string
  readonly thongKe: ThongKeNap
  readonly tokens: readonly Token[]
}

export interface LoiNap {
  readonly id: number
  readonly entity: Entity
  readonly externalId: string
  readonly truong: string
  readonly lyDo: string
  readonly nhanLuc: string
}

// ─── Đường gọi ──────────────────────────────────────────────────────────────

export const Q_TONG_QUAN = ['re', 'nguon', 'tong-quan'] as const
export const Q_LOI = ['re', 'nguon', 'loi'] as const

export const taiTongQuan = () => goi<TongQuanNguon>(`${NEN}/tong-quan`)
export const taiLoi = () => goi<{ readonly loi: readonly LoiNap[] }>(`${NEN}/loi`)

export const taoToken = (label: string) =>
  goi<Token>(`${NEN}/keys`, { method: 'POST', body: JSON.stringify({ label }) })

export const xoaToken = (id: number) => goi<void>(`${NEN}/keys/${id}`, { method: 'DELETE' })
