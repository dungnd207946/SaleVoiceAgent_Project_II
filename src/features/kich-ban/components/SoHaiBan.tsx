/** «Xem bản mẫu» (spec §4b): chỉ các mục KHÁC nhau, bản của workspace trên, bản mẫu dưới. Không diff từng dòng. */
import type { NutKichBan, NutVao } from '../api'
import { NHAN_KENH, NHAN_TRUONG, veKhuon } from '../khuon'
import { TEN_NHOM, nhanKyNang } from '../logic'

const TRUONG: (keyof NutVao)[] = [
  'ten',
  'nhom',
  'bat',
  'kenh',
  'dau_hieu',
  'lam',
  'buoc',
  'cam',
  'tool',
  'khi_thieu',
  'cau_ket',
  'lan_2',
  'chi_lan_2',
]
const NHAN: Record<string, string> = { ...NHAN_TRUONG, bat: 'Đang dùng' }
function hien(k: keyof NutVao, n: NutVao, ten: Record<string, string>): string[] {
  switch (k) {
    case 'nhom':
      return [TEN_NHOM[n.nhom] ?? n.nhom]
    case 'bat':
      return [n.bat ? 'Đang dùng' : 'Đang tắt']
    case 'chi_lan_2':
      return [n.chi_lan_2 ? 'Có' : 'Không']
    case 'kenh':
      return [n.kenh.length === 1 ? (NHAN_KENH[n.kenh[0]!] ?? n.kenh[0]!) : 'Cả chat và cuộc gọi']
    case 'tool':
      return n.tool.map(nhanKyNang)
    case 'buoc':
      return n.buoc.map((b, i) => `${i + 1}. ${b.lam}`)
    case 'lan_2':
      return [n.lan_2 ? (ten[n.lan_2] ?? n.lan_2) : 'Không chuyển']
    case 'dau_hieu':
    case 'lam':
    case 'cam':
      return n[k]
    default:
      return [String(n[k])]
  }
}

function Ban({ nhan, ds, mau = false }: { nhan: string; ds: string[]; mau?: boolean }) {
  return (
    <div className={`rounded-sm px-2 py-1.5 text-than ${mau ? 'bg-fill' : 'bg-surface'}`}>
      <p className="text-phu text-muted-2">{nhan}</p>
      {ds.length ? (
        <ul className="list-disc pl-4">
          {ds.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      ) : (
        <p className="text-muted">(trống)</p>
      )}
    </div>
  )
}

export function SoHaiBan({
  cua,
  mau,
  ten,
}: {
  cua: NutKichBan
  mau: NutKichBan
  ten: Record<string, string>
}) {
  const a = veKhuon(cua)
  const b = veKhuon(mau)
  const khac = TRUONG.filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
  return (
    <section data-testid="so-hai-ban" className="space-y-3 rounded-md border border-border p-3">
      {khac.map((k) => (
        <div key={k} className="space-y-1">
          <h4 className="text-phu font-medium text-muted">{NHAN[k]}</h4>
          <Ban nhan="Bản của bạn" ds={hien(k, a, ten)} />
          <Ban nhan="Bản mẫu" ds={hien(k, b, ten)} mau />
        </div>
      ))}
    </section>
  )
}
