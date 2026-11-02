### Task 3: Kiểu + client API + fake MSW

**Files:**
- Create: `src/features/billing/kieu.ts`
- Create: `src/features/billing/api.ts`
- Modify: `src/features/billing/contracts.ts`
- Modify: `src/lib/msw/handlers.ts`

**Interfaces:**
- Consumes: `Tien` (Task 2)
- Produces: `useTongQuan(kyFrom, kyTo)` · `useTheoKey(...)` · `useTheoOwner(...)` · `usePhien(..., limit, offset)` · `useChiTietPhien(sessionId)` · `useBoGia()` · `taoBoGia` · `themDongGia` · `kichHoat` · `usePreview(pb, tenant)` · `ganChoWorkspace` · `KEY_BILLING`

- [ ] **Step 1: Viết `kieu.ts` — snake_case, sinh từ hợp đồng BE**

```ts
import type { Tien } from './dinh-dang'

/**
 * Kiểu của 11 response module `billing`.
 *
 * ⚠️ TẤT CẢ snake_case. `modules/billing` KHÔNG khai `alias_generator`, khác
 * `modules/ops` (màn /convos, /dashboard) vốn CÓ khai alias camelCase. Copy
 * pattern `res.chiPhiTong` từ màn ops sang đây ra `undefined` — không phải lỗi,
 * chỉ là `NaN` hiện thành «—» và không gì đỏ. Nguồn: hợp đồng BE
 * `odyssey-portal-backend/docs/contracts/usage-billing.md` §0.
 */
export interface CanhBao {
  thieu_gia: number
  nhan_chua_phan_loai: number
  event_khong_so_do: number
  llm_khong_chinh_xac: number
}

export interface TongQuan {
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  /** Thời lượng `component='call'` — KHÔNG cộng chéo component (BE sửa 9d78d04). */
  voice_sec: number
  so_phien: number
  so_key: number
  chi_phi: Tien
  currency: string
  canh_bao: CanhBao
}

export interface DongKey {
  /** `null` = nhóm «Chưa phân loại (không có khoá)». KHÔNG được ẩn. */
  agent_key_id: number | null
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
  chi_phi_tong: Tien
  currency: string
}

export interface DongOwner {
  user_id: string | null
  ten: string | null
  email: string | null
  so_key: number
  so_phien: number
  chi_phi: Tien
}

export interface PhienUsage {
  session_id: string
  agent_key_id: number | null
  key_label: string | null
  customer_name: string | null
  phone: string | null
  channel: string
  bat_dau: string | null
  so_turn: number
  input_tokens: number
  output_tokens: number
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
  turn_idx: number | null
  component: string
  purpose: string
  /** `''` ở component audio (DEFAULT '', không NULL) — hiện «—». */
  provider: string
  model: string
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  audio_sec: number
  /** `units` nay = SỐ LẦN GỌI cho mọi component (agent chuẩn hoá 2026-08-20). */
  units: number
  /** Ký tự. Cơ sở tính tiền của `tts`/`embed`, và vế CỘNG THÊM của `stt`. */
  text_units: number
  exact: boolean
  chi_phi: Tien
  occurred_at: string
}

export interface ChiTietPhien {
  phien: PhienUsage
  events: EventUsage[]
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

/** ⚠️ camelCase — dict viết tay ở BE, KHÁC mọi response khác của module. */
export interface PreviewGia {
  chiPhi: Tien
  currency: string
}

/** ⚠️ Body GỬI LÊN: `unitPrice`/`perUnits` phải camelCase, còn lại tên thường.
 *  Không có `populate_by_name` ⇒ gửi `unit_price` sẽ ăn 422. */
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

/** ⚠️ Body GỬI LÊN: CẢ HAI field camelCase. `effectiveFrom` phải tz-aware. */
export interface GanBoGiaIn {
  priceVersionId: number
  effectiveFrom: string
}
```

- [ ] **Step 2: Viết `api.ts`**

Đọc `src/features/platform/api.ts` để copy ĐÚNG khuôn `goi()` (xử lý lỗi `{error:{code,message}}`, ném `LoiApi`) — đừng viết `fetch` trần. Rồi:

```ts
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type {
  BoGia, ChiTietPhien, DanhSachKey, DanhSachPhien, DongGiaIn,
  DongOwner, GanBoGiaIn, PreviewGia, TongQuan,
} from './kieu'

export const KEY_BILLING = ['billing'] as const

/** Query param của BE là `from`/`to` (alias), KHÔNG phải `tu`/`den`. Kiểu
 *  `date` ⇒ định dạng `YYYY-MM-DD`, không gửi ISO datetime. */
function ky(from: string, to: string): string {
  return new URLSearchParams({ from, to }).toString()
}

export function useTongQuan(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'summary', from, to],
    queryFn: () => goi<TongQuan>(`/billing/summary?${ky(from, to)}`),
  })
}

export function useTheoKey(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'by-key', from, to],
    queryFn: () => goi<DanhSachKey>(`/billing/by-key?${ky(from, to)}`),
  })
}

export function useTheoOwner(from: string, to: string) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'by-owner', from, to],
    queryFn: () => goi<DongOwner[]>(`/billing/by-owner?${ky(from, to)}`),
  })
}

export function usePhien(from: string, to: string, limit: number, offset: number) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'sessions', from, to, limit, offset],
    queryFn: () =>
      goi<DanhSachPhien>(
        `/billing/sessions?${ky(from, to)}&limit=${limit}&offset=${offset}`,
      ),
    /** Giữ dữ liệu cũ khi đổi trang/kỳ — về skeleton là nhảy layout, mất chỗ đang đọc. */
    placeholderData: (truoc) => truoc,
  })
}

export function useChiTietPhien(sessionId: string | undefined) {
  return useQuery({
    queryKey: [...KEY_BILLING, 'session', sessionId],
    queryFn: () => goi<ChiTietPhien>(`/billing/sessions/${sessionId!}`),
    enabled: Boolean(sessionId),
  })
}

/* ── Admin: header `X-Platform-Admin-Token`, KHÔNG phải cookie phiên ────────
   Token lưu `sessionStorage` — token quản trị nền tảng không được sống qua
   phiên trình duyệt. Cùng lý lẽ `guiFeedbackAgent()` của module platform:
   endpoint này không nhận phiên, nên `goi()` trần không dùng được. */
const KHOA_TOKEN = 'billing.admin.token'
export const docToken = () => sessionStorage.getItem(KHOA_TOKEN) ?? ''
export const luuToken = (t: string) => sessionStorage.setItem(KHOA_TOKEN, t)

async function goiAdmin<T>(duong: string, init: RequestInit = {}): Promise<T> {
  const r = await fetch(`/api/v1${duong}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      'X-Platform-Admin-Token': docToken(),
      ...(init.headers ?? {}),
    },
  })
  const d = await r.json().catch(() => null)
  if (!r.ok) throw Object.assign(new Error(d?.error?.message ?? r.statusText), {
    ma: d?.error?.code ?? String(r.status), status: r.status,
  })
  return d as T
}

export function useBoGia() {
  return useQuery({
    queryKey: [...KEY_BILLING, 'price-versions'],
    queryFn: () => goiAdmin<BoGia[]>('/admin/billing/price-versions'),
  })
}

export function useTaoBoGia() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: { code: string; name: string; currency: string }) =>
      goiAdmin<{ id: number }>('/admin/billing/price-versions', {
        method: 'POST', body: JSON.stringify(b),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY_BILLING, 'price-versions'] }),
  })
}

export function useThemDongGia(pb: number) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (b: DongGiaIn) =>
      goiAdmin<{ id: number }>(`/admin/billing/price-versions/${pb}/items`, {
        method: 'POST', body: JSON.stringify(b),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: [...KEY_BILLING, 'price-versions'] }),
  })
}

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
 *  component. Cửa sổ 30 ngày do BE quyết, FE không truyền được. */
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
```

⚠️ Import `goi` từ đúng chỗ của repo (đọc một `features/*/api.ts` có sẵn). Nếu repo chưa có helper dùng chung thì copy khuôn của `features/platform/api.ts`, đừng tạo helper thứ hai.

- [ ] **Step 3: Fake MSW cho 11 endpoint**

Thêm vào `src/lib/msw/handlers.ts`. **Fake phải dùng ĐÚNG snake_case** — fake camelCase là mã hoá một hợp đồng SAI, và repo đã có một vòng thiết kế tin ngược vào fake (gotcha `userCount`, sửa ở `f03da45`). Fake `/billing/by-key` phải có **hàng `agent_key_id: null`** và `chi_phi_tong` = tổng đúng các hàng (kể cả hàng null) — không có nó thì bài test §9.1 xanh vô nghĩa.

Fake admin phải **kiểm header** `X-Platform-Admin-Token`, trả `401` khi thiếu — nếu không thì màn `/pricing` chạy dưới MSW mà không bao giờ đi qua nhánh «chưa có token».

- [ ] **Step 4: `contracts.ts` — mặt tiền**

```ts
export type {
  BoGia, CanhBao, ChiTietPhien, DanhSachKey, DanhSachPhien, DongKey,
  DongOwner, EventUsage, PhienUsage, PreviewGia, TongQuan,
} from './kieu'
export { type Tien, tien } from './dinh-dang'
export { UsageScreen } from './components/UsageScreen'
export { BangGiaScreen } from './components/BangGiaScreen'
```

- [ ] **Step 5: Typecheck + suite**

Run: `npx tsc -b && NODE_OPTIONS="--no-experimental-webstorage" npx vitest run 2>&1 | tail -5`
Expected: `tsc -b` sạch; suite cùng con số fail như Task 1 Step 1.

- [ ] **Step 6: Commit**

```bash
git add src/features/billing/ src/lib/msw/handlers.ts
git commit -m "feat(billing): kiểu snake_case + client + fake MSW 11 endpoint"
```

---

