// Kiểu chép tay từ odyssey-portal-backend `modules/playbook/contracts.py` — đổi ở đó thì đổi ở đây.
import {
  keepPreviousData,
  useIsMutating,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { goi as goiApi, LoiApi } from '@/lib/http'

const GOC = '/api/v1'

const goi = <T>(duong: string) => goiApi<T>(`${GOC}${duong}`, {}, `GET ${duong}`)

const gui = <T>(method: 'PUT' | 'POST', duong: string, body: unknown) =>
  goiApi<T>(`${GOC}${duong}`, { method, body: JSON.stringify(body) }, `${method} ${duong}`)

export type Ngay = 7 | 30 | 90

export interface BuocKichBan {
  id: string
  lam: string
  tool: string[]
}
export interface NutKichBan {
  id: string
  /** Tên hiển thị tiếng Việt (agent xuất từ 2026-10-01) — tuỳ chọn: JSON cũ chưa có. */
  ten?: string
  loai: 'phan_xa' | 'luong'
  nhom: string
  trang_thai: 'dung' | 'nhap'
  kenh: string[]
  dau_hieu: string[]
  lam: string[]
  cam: string[]
  tool: string[]
  can_du_lieu: string[]
  khi_thieu: string
  tiep: Record<string, string>
  dieu_kien: Record<string, unknown>
  buoc: BuocKichBan[]
  nguon: string
  /** Đợt 1/2: lớp sale (workspace sửa được) hay hệ thống (NobleX giữ, chỉ xem). */
  lop: 'sale' | 'he_thong'
  /** Hash định nghĩa nút (BE `nut.bam_nut` = agent `loader.node_hash`) — số đo đếm theo hash này. */
  hash: string
  /** Nút bắt buộc phải có (`gioiHan.khoaXoa`) — không xoá được, chỉ tắt được. */
  khoaXoa: boolean
  bat: boolean
  lan_2: string
  chi_lan_2: boolean
  cau_ket: string
  /** Bản viết lại cho người đọc, song song TỪNG DÒNG với chữ gốc (chữ gốc viết cho LLM: IN HOA, mũi tên, mã tool).
   *  Agent xuất từ 2026-10-02 — tuỳ chọn: JSON cũ chưa có, nút mới có thể chưa viết. */
  hien?: {
    dau_hieu?: string[]
    lam?: string[]
    cam?: string[]
    buoc?: string[]
    khi_thieu?: string
  }
}
export interface MucDem {
  ten: string
  so: number
}
export interface SoDoNut {
  soLuot: number
  daCham: number
  dat: number
  tiLeDat: number | null
  thieuDuLieu: number
  hayThieu: MucDem[]
  hayPham: MucDem[]
  jevSo: number
  jevKhop: number | null
}
export interface DuLieuKichBan {
  version: string
  promptVersion: string
  nodes: NutKichBan[]
  soDo: Record<string, SoDoNut>
  nutCu: Record<string, number>
  phienBanCu: number
  nguon: string[]
  coDuLieu: boolean
  kichBan: KichBan
}
export interface LuotNut {
  sessionId: string
  seq: number
  phone: string | null
  taoLuc: string
  khach: string | null
  agent: string
  dat: boolean | null
  thieu: string[]
  viPhamCam: string[]
  thieuDuLieu: boolean
  buoc: string | null
  jevNut: string | null
}
export interface LocLuot {
  ngay: Ngay
  nguon?: string | undefined
  chiKhongDat: boolean
}

function qs(ngay: Ngay, nguon?: string, them: Record<string, string> = {}): string {
  const p = new URLSearchParams({ ngay: String(ngay), ...them })
  if (nguon) p.set('nguon', nguon)
  return p.toString()
}

export function taiKichBan(ngay: Ngay, nguon?: string): Promise<DuLieuKichBan> {
  return goi<DuLieuKichBan>(`/playbook?${qs(ngay, nguon)}`)
}

export async function taiLuotNut(nut: string, loc: LocLuot): Promise<LuotNut[]> {
  const them: Record<string, string> = loc.chiKhongDat ? { dat: 'false' } : {}
  const d = await goi<{ luot: LuotNut[] }>(
    `/playbook/${encodeURIComponent(nut)}/luot?${qs(loc.ngay, loc.nguon, them)}`,
  )
  return d.luot
}

export function useKichBan(ngay: Ngay, nguon?: string) {
  return useQuery({
    queryKey: ['kich-ban', ngay, nguon ?? ''],
    queryFn: () => taiKichBan(ngay, nguon),
    // Đổi khoảng ngày / nguồn giữ bản đang hiện tới lúc bản mới về: `data` rỗng một nhịp là khung chi tiết unmount —
    // kéo theo form đang sửa dở mất chữ. `kichBan.version` không phụ thuộc bộ lọc nên bản cũ vẫn ghi đúng.
    placeholderData: keepPreviousData,
  })
}

export function useLuotNut(nut: string | null, loc: LocLuot) {
  return useQuery({
    queryKey: ['kich-ban', 'luot', nut, loc],
    queryFn: () => taiLuotNut(nut!, loc),
    enabled: nut !== null,
  })
}

export interface BuocVao {
  id: string
  lam: string
}

/** Khuôn nút LƯU (BE `NutVao`, `extra="forbid"`) — payload `PUT /playbook` chỉ mang đúng các khoá này. */
export interface NutVao {
  id: string
  ten: string
  nhom: string
  bat: boolean
  kenh: string[]
  dau_hieu: string[]
  lam: string[]
  tool: string[]
  cam: string[]
  khi_thieu: string
  cau_ket: string
  lan_2: string
  chi_lan_2: boolean
  nguon: string
  buoc: BuocVao[]
}

/** Luật agent xuất trong `playbook.json` (`gioiHan`) — form đọc số ở đây, không chép tay. */
export interface GioiHan {
  nhom: string[]
  kenh: string[]
  tool: string[]
  khoaXoa: string[]
  khuonId: string
  khuonIdRieng: string
  maxNut: number
  maxTen: number
  maxTool: number
  maxDong: { dau_hieu: number; lam: number; cam: number }
  maxBuoc: number
  maxKyTu: number
  maxDauHieuTong: number
  maxCamTong: number
  maxCau: number
}

export interface KichBan {
  trangThai: 'mau' | 'rieng'
  version: number
  tuTemplate: string | null
  templateVersion: string
  coTemplateMoi: boolean
  roleDung: string[]
  capNhatLuc: string | null
  capNhatBoi: string | null
}

export interface TemplateKichBan {
  templateVersion: string
  nodes: NutKichBan[]
  /** Vắng khi BE chưa có MR trả khối này — màn khoá nút ghi, phần xem vẫn chạy. */
  gioiHan?: GioiHan | undefined
}

export const taiTemplate = () => goi<TemplateKichBan>('/playbook/template')
export const luuKichBan = (b: { version: number; nut: NutVao[] }) =>
  gui<KichBan>('PUT', '/playbook', b)
export const apDungMau = (version: number) => gui<KichBan>('POST', '/playbook/ap-dung', { version })
export const datRoleDung = (b: { version: number; roles: string[] }) =>
  gui<KichBan>('PUT', '/playbook/role-dung', b)

/** Template tĩnh theo bản deploy — tải một lần. Khoá KHÔNG bắt đầu bằng `'kich-ban'`: làm mới sau mỗi lần ghi
 *  (`['kich-ban']`) không cần kéo lại nó. */
export function useTemplate() {
  return useQuery({ queryKey: ['kich-ban-template'], queryFn: taiTemplate, staleTime: Infinity })
}

const KHOA_GHI = ['kich-ban-ghi'] as const

/**
 * Có lần ghi nào đang chạy không — khoá DÙNG CHUNG cho mọi nút ghi của màn. Ba endpoint chung MỘT `version`
 * (`kich_ban.version`), nên khoá theo từng control là bấm hai control khác nhau liền nhau ra 409 do chính mình.
 */
export const useDangGhiKichBan = () => useIsMutating({ mutationKey: KHOA_GHI }) > 0

/**
 * Ba lời gọi ghi. Thành công ⇒ `onSuccess` TRẢ promise làm mới `['kich-ban']`, nên mutation còn `isPending` tới lúc
 * `GET /playbook` mới về: nút ghi khoá tới khi màn cầm `version` mới (Review Focus 1). 409 ⇒ làm mới ngay để lần
 * Lưu sau cầm bản mới; role vừa bị xoá ở tab khác (422 `PLAYBOOK_ROLE_KHONG_CO`) ⇒ làm mới danh sách role.
 */
export function useGhiKichBan() {
  const qc = useQueryClient()
  const lamMoi = () => qc.invalidateQueries({ queryKey: ['kich-ban'] })
  const khiLoi = (e: Error) => {
    if (!(e instanceof LoiApi)) return
    if (e.code === 'PLAYBOOK_DA_DOI') void lamMoi()
    if (e.code === 'PLAYBOOK_ROLE_KHONG_CO') void qc.invalidateQueries({ queryKey: ['config'] })
  }
  return {
    luu: useMutation({
      mutationKey: KHOA_GHI,
      mutationFn: luuKichBan,
      onSuccess: lamMoi,
      onError: khiLoi,
    }),
    apDung: useMutation({
      mutationKey: KHOA_GHI,
      mutationFn: apDungMau,
      onSuccess: lamMoi,
      onError: khiLoi,
    }),
    roleDung: useMutation({
      mutationKey: KHOA_GHI,
      mutationFn: datRoleDung,
      onSuccess: lamMoi,
      onError: khiLoi,
    }),
  }
}
