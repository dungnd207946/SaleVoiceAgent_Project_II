export interface NhanKichBan {
  nut: string
  buoc: string | null
  dat: boolean | null
  loi: string | null
  daLam: string[]
  thieu: string[]
  viPhamCam: string[]
  thieuDuLieu: boolean
  jevNut: string | null
  doTin: number | null
}

const chuoi = (v: unknown) => (typeof v === 'string' ? v : null)
const dsChuoi = (v: unknown) =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []

// Đọc phòng thủ như `layDsCuocGoi`: meta do agent ghi (G1 `meta.playbook`), không tin hình dạng.
export function docNhanKichBan(meta: unknown): NhanKichBan | null {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null
  const p = (meta as Record<string, unknown>).playbook
  if (!p || typeof p !== 'object' || Array.isArray(p)) return null
  const r = p as Record<string, unknown>
  const nut = chuoi(r.nut)
  if (!nut) return null
  return {
    nut,
    buoc: chuoi(r.buoc),
    dat: typeof r.dat === 'boolean' ? r.dat : null,
    loi: chuoi(r.loi),
    daLam: dsChuoi(r.da_lam),
    thieu: dsChuoi(r.thieu),
    viPhamCam: dsChuoi(r.vi_pham_cam),
    thieuDuLieu: r.thieu_du_lieu === true,
    jevNut: chuoi(r.jev_nut),
    doTin: typeof r.do_tin === 'number' ? r.do_tin : null,
  }
}
