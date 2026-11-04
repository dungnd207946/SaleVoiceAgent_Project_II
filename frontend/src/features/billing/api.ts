/**
 * Client HTTP của module `billing` — 12 endpoint (6 tenant qua `billing.read`,
 * 6 admin nền tảng qua header `X-Platform-Admin-Token`).
 *
 * ⚠️ `summary`/`by-key` có thể ném `409 NHIEU_DON_VI_TIEN` (mới 2026-08-20):
 * khoảng `[from, to)` đang hỏi có usage định giá bằng nhiều hơn một đơn vị
 * tiền. Message đã liệt kê các đơn vị xung đột — hiện nguyên message đó, đừng
 * nuốt lỗi rồi tự bịa câu chung chung.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { goi } from '@/lib/http'
import type {
  BoGia,
  ChiTietPhien,
  DanhSachKey,
  DanhSachPhien,
  DongGiaIn,
  DongOwner,
  GanBoGiaIn,
  PhanTich,
  PreviewGia,
  TongQuan,
  UsageTheoNgay,
} from './kieu'

/** Chỉ dùng NỘI BỘ tệp này — không module/test nào khác import (đo 2026-08-20). */
const KEY_BILLING = ['billing'] as const

/**
 * Query param BE là `from`/`to` (alias), kiểu `date` ⇒ `YYYY-MM-DD`, KHÔNG
 * phải `tu`/`den`, KHÔNG phải ISO datetime. Gọi `giaiMaKy()` (`./ky`) ở tầng
 * màn để có đúng định dạng này rồi truyền `from`/`to` xuống các hook dưới đây
 * — hàm này chỉ ghép query string, không tự format.
 */
function ky(from: string, to: string): string {
  return new URLSearchParams({ from, to }).toString()
}

/** `enabled: Boolean(from && to)` — mọi call site hiện có (`UsageScreen` qua
 *  `giaiMaKy()`) luôn có cả hai nên hành vi không đổi; thêm để `TongQuanScreen`
 *  (module `ops`, gọi qua `contracts`) truyền được kỳ RỖNG lúc `moc` của
 *  overview thiếu (backend cũ chưa gửi khoá đó) mà không bắn một request với
 *  `from=&to=`. */
export function useTongQuan(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'summary', from, to],
    queryFn: () => goi<TongQuan>(`/api/v1/billing/summary?${ky(from, to)}`),
    enabled: Boolean(from && to),
  })
}

export function usePhanTich(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'breakdown', from, to],
    queryFn: () => goi<PhanTich>(`/api/v1/billing/breakdown?${ky(from, to)}`),
  })
}

/**
 * Nguồn DUY NHẤT của thẻ biểu đồ màn `/usage` — MỘT request cho cả bảy tab.
 *
 * Đổi tab KHÔNG gọi lại API: `queryKey` chỉ mang kỳ, còn tab là phép chọn trên
 * dữ liệu đã có. Bảy tab bảy request là bảy trạng thái tải cho một thứ người
 * dùng đọc như một.
 *
 * ⚠️ `/usage` KHÔNG gọi `usePhanTich()`. `theo_component[]` của `/breakdown` có
 * sẵn đúng bộ số đo TỔNG KỲ, nhưng lấy tổng từ đó là hai nguồn cho một con số:
 * tổng cả kỳ và tổng của chuỗi ngày phải bằng nhau, mà hai câu SQL khác nhau
 * thì ngày nào lệch sẽ lệch ÂM THẦM — rail nói một số, biểu đồ vẽ một số khác,
 * không cổng nào đỏ. Cộng chuỗi ngày ở FE (`tomTatChuoi()` ở `./chuoi`) thì hai
 * con số KHÔNG THỂ lệch nhau.
 */
export function useUsageTheoNgay(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'usage-by-day', from, to],
    queryFn: () => goi<UsageTheoNgay>(`/api/v1/billing/usage-by-day?${ky(from, to)}`),
  })
}

export function useTheoKey(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'by-key', from, to],
    queryFn: () => goi<DanhSachKey>(`/api/v1/billing/by-key?${ky(from, to)}`),
  })
}

export function useTheoOwner(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'by-owner', from, to],
    queryFn: () => goi<DongOwner[]>(`/api/v1/billing/by-owner?${ky(from, to)}`),
  })
}

export function usePhien(from: string, to: string, limit: number, offset: number) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'sessions', from, to, limit, offset],
    queryFn: () =>
      goi<DanhSachPhien>(
        `/api/v1/billing/sessions?${ky(from, to)}&limit=${limit}&offset=${offset}`,
      ),
    /** Giữ dữ liệu cũ khi đổi trang/kỳ — về skeleton là nhảy layout, mất chỗ đang đọc. */
    placeholderData: (truoc: DanhSachPhien | undefined) => truoc,
  })
}

export function useChiTietPhien(sessionId: string | undefined) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'session', sessionId],
    queryFn: () => goi<ChiTietPhien>(`/api/v1/billing/sessions/${encodeURIComponent(sessionId!)}`),
    enabled: Boolean(sessionId),
  })
}

/* ── Admin: header `X-Platform-Admin-Token`, KHÔNG phải cookie phiên ────────
   Token lưu `sessionStorage` — token quản trị nền tảng không được sống qua
   phiên trình duyệt (mở tab mới đã phải nhập lại). Cùng lý lẽ `guiFeedbackAgent()`
   của module platform: endpoint này không nhận phiên, nên `goi()` trần (không
   header admin) không dùng được. */
const KHOA_TOKEN = 'billing.admin.token'
export const docToken = (): string => sessionStorage.getItem(KHOA_TOKEN) ?? ''
export const luuToken = (t: string): void => sessionStorage.setItem(KHOA_TOKEN, t)

function goiAdmin<T>(duong: string, init: RequestInit = {}): Promise<T> {
  return goi<T>(
    `/api/v1${duong}`,
    { ...init, headers: { 'X-Platform-Admin-Token': docToken(), ...init.headers } },
    duong,
  )
}

/**
 * ⚠️ `enabled: Boolean(docToken())` — thiếu token thì KHÔNG gọi. Không có
 * khiên này, màn `/pricing` bắn request admin ngay lúc mở (chưa ai gõ token)
 * và luôn nhận 401; bài test "chưa có token" của Task 8 sẽ test một nhánh
 * chết vì request đã đi trước khi màn kịp hiện ô nhập.
 */
export function useBoGia() {
  return useQuery({
    queryKey: [...KEY_BILLING, 'price-versions'],
    queryFn: () => goiAdmin<BoGia[]>('/admin/billing/price-versions'),
    enabled: Boolean(docToken()),
  })
}

export function useTaoBoGia() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { code: string; name: string; currency: string }) =>
      goiAdmin<{ id: number }>('/admin/billing/price-versions', {
        method: 'POST',
        body: JSON.stringify(b),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY_BILLING, 'price-versions'] }),
  })
}

export function useThemDongGia(pb: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: DongGiaIn) =>
      goiAdmin<{ id: number }>(`/admin/billing/price-versions/${pb}/items`, {
        method: 'POST',
        body: JSON.stringify(b),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY_BILLING, 'price-versions'] }),
  })
}

/** ⚠️ Kích hoạt LÀ hành động có kiểm tra thật: BE so `pricing_basis` với các
 *  dòng giá đã nhập, chặn `409 BANG_GIA_CON_LO` nếu còn thiếu. */
export function useKichHoat(pb: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () =>
      goiAdmin<{ status: string }>(`/admin/billing/price-versions/${pb}/activate`, {
        method: 'POST',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY_BILLING, 'price-versions'] }),
  })
}

/** ⚠️ Preview là PER-TENANT (`tenant` bắt buộc) và trả MỘT tổng, không tách
 *  component. Cửa sổ thời gian do BE quyết, FE không truyền được. */
export function usePreview(pb: number | null, tenant: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'preview', pb, tenant],
    queryFn: () =>
      goiAdmin<PreviewGia>(
        `/admin/billing/price-versions/${pb!}/preview?tenant=${encodeURIComponent(tenant)}`,
      ),
    enabled: Boolean(pb && tenant),
    staleTime: 0,
  })
}

/**
 * ⚠️ Gán bảng giá cho tenant KHÔNG được BE xác thực trước (không đòi
 * `status === 'active'`, không kiểm đủ giá) — chỉ chặn mốc lùi vào quá khứ đã
 * định giá và mốc trước khoảng đang mở. Đừng trình bày hành động này như đã
 * được xác thực an toàn; `canh_bao.thieu_gia` của tenant đó là cách phát hiện
 * DUY NHẤT, và nó chỉ kêu SAU khi một phần usage đã bị định giá bằng 0.
 */
export function useGanChoWorkspace(tenantId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: GanBoGiaIn) =>
      goiAdmin<{ status: string }>(
        `/admin/billing/tenants/${encodeURIComponent(tenantId)}/price-version`,
        { method: 'POST', body: JSON.stringify(b) },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY_BILLING }),
  })
}
