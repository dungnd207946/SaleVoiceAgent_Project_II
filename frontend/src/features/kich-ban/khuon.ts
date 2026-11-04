/**
 * Khuôn nút LƯU của kịch bản workspace (BE `modules/playbook/contracts.py::NutVao`) và các phép thuần trên nó.
 *
 * Payload `PUT /playbook` LUÔN dựng từ `nodes` mà `GET /playbook` vừa trả: BE đã lọc tool agent gỡ khỏi các nút đó
 * (`nut.tuong_thich`), nên dựng từ đây thì không bao giờ 422 trên một tình huống người dùng không sửa (spec đợt 3 §2).
 */
import { boDau } from '@/lib/boDau'
import type { LoiApi } from '@/lib/http'
import type { BuocVao, GioiHan, NutKichBan, NutVao } from './api'

/** Nút `GET /playbook` (khuôn playbook.json + trường tương thích) → khuôn `PUT`. */
export function veKhuon(n: NutKichBan): NutVao {
  return {
    id: n.id,
    ten: n.ten ?? n.id,
    nhom: n.nhom,
    bat: n.bat,
    kenh: [...n.kenh],
    dau_hieu: [...n.dau_hieu],
    lam: [...n.lam],
    tool: [...n.tool],
    cam: [...n.cam],
    khi_thieu: n.khi_thieu,
    cau_ket: n.cau_ket,
    lan_2: n.lan_2,
    chi_lan_2: n.chi_lan_2,
    nguon: n.nguon,
    buoc: n.buoc.map((b) => ({ id: b.id, lam: b.lam })),
  }
}

export const laSale = (n: Pick<NutKichBan, 'lop'>) => n.lop === 'sale'
export const boSale = (nodes: readonly NutKichBan[]): NutVao[] => nodes.filter(laSale).map(veKhuon)
export const heThong = (nodes: readonly NutKichBan[]): NutKichBan[] =>
  nodes.filter((n) => n.lop === 'he_thong')

/** Độ dài theo KÝ TỰ (code point) như `len()` của Python — `.length` đếm UTF-16, emoji tính hai. */
export const doDai = (s: string) => [...s].length

export type TruongNut =
  | 'ten'
  | 'nhom'
  | 'kenh'
  | 'dau_hieu'
  | 'lam'
  | 'buoc'
  | 'cam'
  | 'tool'
  | 'khi_thieu'
  | 'cau_ket'
  | 'lan_2'
  | 'chi_lan_2'

/** Nhãn MỘT nguồn cho cả bản xem lẫn form (luật «xem trước, sửa sau» điều 1). */
export const NHAN_TRUONG: Record<TruongNut, string> = {
  ten: 'Tên tình huống',
  nhom: 'Nhóm',
  kenh: 'Kênh',
  dau_hieu: 'Khi nào dùng',
  lam: 'Agent làm gì',
  buoc: 'Các bước',
  cam: 'Không được làm',
  tool: 'Kỹ năng nên dùng',
  khi_thieu: 'Khi thiếu tài liệu',
  cau_ket: 'Câu kết hỏi khách',
  lan_2: 'Khi khách lặp lại lần 2, chuyển sang',
  chi_lan_2: 'Chỉ dùng khi được chuyển tới',
}

/** Kênh khi CHỈ một kênh — chữ chung cho form, bản xem, «Xem bản mẫu». Vắng kênh = cả hai. */
export const NHAN_KENH: Record<string, string> = { chat: 'Chỉ chat', voice: 'Chỉ cuộc gọi' }

export type LoiNut = Partial<Record<TruongNut, string>>

/** Khuôn của form «Thêm tình huống» — một ô trống sẵn cho hai mục bắt buộc. `id` gán lúc lưu (`idRieng`). */
export const nutTrong = (): NutVao => ({
  id: '',
  ten: '',
  nhom: '',
  bat: true,
  kenh: [],
  dau_hieu: [''],
  lam: [''],
  tool: [],
  cam: [],
  khi_thieu: '',
  cau_ket: '',
  lan_2: '',
  chi_lan_2: false,
  nguon: '',
  buoc: [],
})

/** Form → payload: strip, bỏ ý rỗng và bước rỗng (BE coi «có dòng rỗng» là lỗi). BE strip lại bằng Python. */
export function chuanHoa(n: NutVao): NutVao {
  const ds = (x: string[]) => x.map((s) => s.trim()).filter(Boolean)
  return {
    ...n,
    ten: n.ten.trim(),
    dau_hieu: ds(n.dau_hieu),
    lam: ds(n.lam),
    cam: ds(n.cam),
    khi_thieu: n.khi_thieu.trim(),
    cau_ket: n.cau_ket.trim(),
    buoc: n.buoc.map((b) => ({ ...b, lam: b.lam.trim() })).filter((b) => b.lam),
  }
}

/** `rieng_<tên bỏ dấu>` — luôn khớp `gioiHan.khuonIdRieng` (`^rieng_[a-z0-9_]{1,33}$`); trùng thì `_2`, `_3`… */
export function idRieng(ten: string, daCo: ReadonlySet<string>): string {
  const slug =
    boDau(ten)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '') || 'tinh_huong'
  for (let i = 1; ; i++) {
    const duoi = i === 1 ? '' : `_${i}`
    const id = `rieng_${slug.slice(0, 33 - duoi.length).replace(/_+$/, '')}${duoi}`
    if (!daCo.has(id)) return id
  }
}

/** Id cho bước mới: `b<n>` nhỏ nhất chưa dùng — bước cũ GIỮ id (số đo theo bước đọc id). */
export function idBuocMoi(buoc: readonly BuocVao[]): string {
  const co = new Set(buoc.map((b) => b.id))
  for (let i = 1; ; i++) if (!co.has(`b${i}`)) return `b${i}`
}

export const thayNut = (bo: readonly NutVao[], moi: NutVao) =>
  bo.map((n) => (n.id === moi.id ? moi : n))
export const themNut = (bo: readonly NutVao[], moi: NutVao) => [...bo, moi]
export const xoaNut = (bo: readonly NutVao[], id: string) => bo.filter((n) => n.id !== id)

export type LoaiMau = 'giong' | 'khac' | 'rieng'
export interface SoMau {
  loai: Record<string, LoaiMau>
  chuaCo: NutKichBan[]
}

/** So lớp sale đang chạy với mẫu HIỆN TẠI theo id + hash (spec §5). */
export function soMau(sale: readonly NutKichBan[], mau: readonly NutKichBan[]): SoMau {
  const hashMau = new Map(mau.map((n) => [n.id, n.hash]))
  const loai: Record<string, LoaiMau> = {}
  for (const n of sale) {
    const h = hashMau.get(n.id)
    loai[n.id] = h === undefined ? 'rieng' : h === n.hash ? 'giong' : 'khac'
  }
  const co = new Set(sale.map((n) => n.id))
  return { loai, chuaCo: mau.filter((n) => !co.has(n.id)) }
}

/** Luật từng ô (BE `kiem.py`, số từ `gioiHan`) — chạy trên nút ĐÃ `chuanHoa`. Mỗi ô một lỗi đầu tiên. */
export function kiemNut(n: NutVao, g: GioiHan): LoiNut {
  const loi: LoiNut = {}
  const dat = (k: TruongNut, cau: string) => {
    loi[k] ??= cau
  }
  if (!n.ten) dat('ten', 'Chưa có tên tình huống')
  else if (doDai(n.ten) > g.maxTen) dat('ten', `Tối đa ${g.maxTen} ký tự`)
  if (!g.nhom.includes(n.nhom)) dat('nhom', 'Chọn một nhóm')
  if (n.kenh.some((k) => !g.kenh.includes(k))) dat('kenh', 'Kênh không hợp lệ')
  for (const k of ['dau_hieu', 'lam', 'cam'] as const) {
    if (k !== 'cam' && n[k].length === 0) dat(k, 'Cần ít nhất một ý')
    if (n[k].length > g.maxDong[k]) dat(k, `Tối đa ${g.maxDong[k]} ý`)
    if (k !== 'cam' && n[k].some((x) => doDai(x) > g.maxKyTu))
      dat(k, `Mỗi ý tối đa ${g.maxKyTu} ký tự`)
  }
  if (doDai(n.dau_hieu.join(' | ')) > g.maxDauHieuTong)
    dat('dau_hieu', `Tổng tối đa ${g.maxDauHieuTong} ký tự`)
  if (n.cam.reduce((s, x) => s + doDai(x), 0) > g.maxCamTong)
    dat('cam', `Tổng tối đa ${g.maxCamTong} ký tự`)
  if (n.tool.some((t) => !g.tool.includes(t))) dat('tool', 'Có kỹ năng không còn dùng được')
  if (n.tool.length > g.maxTool) dat('tool', `Tối đa ${g.maxTool} kỹ năng`)
  for (const k of ['khi_thieu', 'cau_ket'] as const)
    if (doDai(n[k]) > g.maxCau) dat(k, `Tối đa ${g.maxCau} ký tự`)
  if (n.buoc.length > g.maxBuoc) dat('buoc', `Tối đa ${g.maxBuoc} bước`)
  if (n.buoc.some((b) => doDai(b.lam) > g.maxKyTu))
    dat('buoc', `Mỗi bước tối đa ${g.maxKyTu} ký tự`)
  if (n.lan_2 && n.lan_2 === n.id) dat('lan_2', 'Không chuyển sang chính nó')
  return loi
}

/** Luật cả bộ (BE `kiem_bo` phần cả bộ) — chỉ để báo sớm bằng TÊN; BE 422 vẫn là chốt chặn. */
export function kiemBo(
  bo: readonly NutVao[],
  heThongNodes: readonly NutKichBan[],
  g: GioiHan,
  ten: Record<string, string>,
): string[] {
  const goi = (id: string) => `«${ten[id] ?? id}»`
  const loi: string[] = []
  if (bo.length > g.maxNut) loi.push(`Tối đa ${g.maxNut} tình huống`)
  const idHt = new Set(heThongNodes.map((n) => n.id))
  const thay = new Set<string>()
  for (const n of bo) {
    if (thay.has(n.id) || idHt.has(n.id)) loi.push(`${goi(n.id)} trùng mã với một tình huống khác`)
    thay.add(n.id)
  }
  const tatCa = new Set([...thay, ...idHt])
  for (const n of bo)
    if (n.lan_2 && n.lan_2 !== n.id && !tatCa.has(n.lan_2))
      loi.push(`${goi(n.id)} chuyển sang một tình huống không còn trong kịch bản`)
  const dich = new Set([...bo, ...heThongNodes].map((n) => n.lan_2).filter(Boolean))
  for (const n of bo)
    if (n.chi_lan_2 && !dich.has(n.id))
      loi.push(
        `${goi(n.id)} chỉ dùng khi được chuyển tới, nhưng không tình huống nào chuyển sang nó`,
      )
  const thieu = g.khoaXoa.filter((id) => !thay.has(id))
  if (thieu.length) loi.push(`Không được xoá ${thieu.map(goi).join(', ')}`)
  return loi
}

export interface LyDoChan {
  id: string
  cau: string
}

/**
 * Vì sao chưa xoá được `id` (spec §4e) — rỗng = xoá được. Mỗi lý do mang id tình huống để mở nó.
 * Nguồn «chuyển sang nó» chỉ tính nút SALE: BE `kiem_bo` không kiểm `lan_2` của nút hệ thống (người dùng cũng không
 * sửa được nút đó). Còn đích chỉ-lần-2 thì tính cả nguồn hệ thống — đúng tập `dich` của BE.
 */
export function chanXoa(
  id: string,
  bo: readonly NutVao[],
  heThongNodes: readonly NutKichBan[],
  ten: Record<string, string>,
): LyDoChan[] {
  const goi = (x: string) => `«${ten[x] ?? x}»`
  const tatCa = [...bo, ...heThongNodes]
  const out: LyDoChan[] = bo
    .filter((n) => n.id !== id && n.lan_2 === id)
    .map((n) => ({
      id: n.id,
      cau: `${goi(n.id)} chuyển sang tình huống này khi khách lặp lại — đổi ở ${goi(n.id)} trước`,
    }))
  const x = bo.find((n) => n.id === id)
  const z = x?.lan_2 ? tatCa.find((n) => n.id === x.lan_2) : undefined
  if (z?.chi_lan_2 && !tatCa.some((n) => n.id !== id && n.lan_2 === z.id))
    out.push({
      id: z.id,
      cau: `${goi(z.id)} chỉ tới được từ tình huống này — xoá ${goi(z.id)} hoặc bỏ «${NHAN_TRUONG.chi_lan_2}» ở ${goi(z.id)} trước`,
    })
  return out
}

/**
 * Những tình huống MẪU phải thêm CÙNG `m` để bộ còn hợp lệ (spec §4f): `m` trước, rồi tình huống nó chuyển sang
 * (nếu bản riêng chưa có) và tình huống chuyển sang nó (nếu nó chỉ dùng khi được chuyển tới) — lan theo chuỗi.
 * Bắt thêm từng cái thì cặp X→Z (Z chỉ-lần-2) kẹt nhau: X cần Z có trước, Z cần X có trước.
 * Trả CÂU khi không tự thêm được: nguồn đã có trong bản riêng nhưng thôi chuyển sang — ghi đè nó là xoá chữ người dùng.
 */
export function nhomThem(
  m: NutKichBan,
  bo: readonly NutVao[],
  heThongNodes: readonly NutKichBan[],
  mau: readonly NutKichBan[],
  ten: Record<string, string>,
): NutKichBan[] | string {
  const goi = (id: string) => `«${ten[id] ?? id}»`
  const nhom: NutKichBan[] = [m]
  const co = (dk: (n: NutVao | NutKichBan) => boolean) => [...bo, ...heThongNodes, ...nhom].some(dk)
  for (let i = 0; i < nhom.length; i++) {
    const n = nhom[i]!
    if (n.lan_2 && !co((x) => x.id === n.lan_2)) {
      const z = mau.find((x) => x.id === n.lan_2)
      if (!z) return `Cần thêm ${goi(n.lan_2)} trước`
      nhom.push(z)
    }
    if (n.chi_lan_2 && !co((x) => x.lan_2 === n.id)) {
      const nguon = mau.find((x) => x.lan_2 === n.id)
      if (!nguon) return 'Chưa tình huống nào chuyển sang tình huống này'
      if (bo.some((x) => x.id === nguon.id))
        return `Cần đặt ${goi(nguon.id)} chuyển sang tình huống này trước`
      nhom.push(nguon)
    }
  }
  return nhom
}

export interface PhanLoi {
  cuaNut: LoiNut
  nutKhac: LyDoChan[]
  chung: string[]
}

const DUONG_LOI = /^body\.nut\[(\d+)\]\.(\w+)(?:\[(\d+)\])?/

/** 422 `fields` (`body.nut[i].<trường>[...]`) → lỗi dưới ô của tình huống đang sửa / câu cho tình huống khác / chung. */
export function phanLoi422(
  e: Pick<LoiApi, 'truong' | 'message'>,
  moi: readonly NutVao[],
  idDangSua: string | null,
  ten: Record<string, string>,
): PhanLoi {
  const out: PhanLoi = { cuaNut: {}, nutKhac: [], chung: [] }
  for (const f of e.truong) {
    const m = DUONG_LOI.exec(f.field)
    const n = m ? moi[Number(m[1])] : undefined
    if (!m || !n) {
      out.chung.push(f.reason)
      continue
    }
    const truong = m[2] as TruongNut
    const cau = m[3] !== undefined ? `Bước ${Number(m[3]) + 1}: ${f.reason}` : f.reason
    if (n.id === idDangSua && truong in NHAN_TRUONG) out.cuaNut[truong] ??= cau
    else
      out.nutKhac.push({
        id: n.id,
        cau: `«${ten[n.id] ?? n.id}» chưa hợp lệ: ${NHAN_TRUONG[truong] ?? truong} — ${cau}`,
      })
  }
  if (!e.truong.length) out.chung.push(e.message)
  return out
}

/** Chữ sau tên tình huống trên sơ đồ / danh sách (spec §4h) — CHỮ, không ký hiệu: font tự host không có ✎/＋. */
export const HAU_TO_MAU: Partial<Record<LoaiMau, string>> = {
  khac: ' · khác mẫu',
  rieng: ' · riêng',
}
