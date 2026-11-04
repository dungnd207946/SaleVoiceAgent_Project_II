/**
 * «So với mẫu NobleX» (spec §4f): ba nhóm — khác mẫu · có trong mẫu nhưng bản riêng chưa có · riêng của workspace.
 * «Khác» là so với bản mẫu HIỆN TẠI: BE không giữ mẫu lúc áp dụng nên không phân biệt được ai đổi.
 */
import { useState } from 'react'
import { NUT_PHU } from '@/components/ui/Bang'
import type { DuLieuKichBan, NutKichBan, TemplateKichBan } from '../api'
import { boSale, heThong, nhomThem, themNut, veKhuon, type SoMau } from '../khuon'
import { tenNut } from '../logic'
import { cauLoi, useGhi } from '../useGhi'

interface Props {
  data: DuLieuKichBan
  mau: TemplateKichBan
  so: SoMau
  ghiDuoc: boolean
  onChon: (id: string) => void
  onDong: () => void
  khung?: string | undefined
}

export function SoVoiMau({
  data,
  mau,
  so,
  ghiDuoc,
  onChon,
  onDong,
  khung = 'rounded-lg border border-border bg-surface p-4',
}: Props) {
  const { ghi, dangGhi, ten } = useGhi(data, mau.gioiHan)
  const [bao, setBao] = useState<Record<string, string>>({})
  const tenCa = { ...Object.fromEntries(mau.nodes.map((n) => [n.id, tenNut(n)])), ...ten }
  const theo = (l: 'khac' | 'rieng') => data.nodes.filter((n) => so.loai[n.id] === l)

  const nhomCua = (m: NutKichBan) =>
    nhomThem(m, boSale(data.nodes), heThong(data.nodes), mau.nodes, tenCa)

  async function themVao(m: NutKichBan) {
    const nhom = nhomCua(m)
    if (typeof nhom === 'string') return setBao((b) => ({ ...b, [m.id]: nhom }))
    // Một lần ghi cho cả nhóm — thêm từng cái thì lần ghi đầu đã hỏng ở `kiemBo`.
    const kq = await ghi((bo) => nhom.reduce((b, n) => themNut(b, veKhuon(n)), bo))
    if (!kq.ok) setBao((b) => ({ ...b, [m.id]: kq.loiBo[0] ?? cauLoi(kq.loi) }))
  }

  const danhSach = (tieuDe: string, ds: NutKichBan[], testId: string) => (
    <section data-testid={testId} className="space-y-1">
      <h3 className="text-phu font-medium text-muted">
        {tieuDe} ({ds.length})
      </h3>
      {ds.length ? (
        <ul className="space-y-1">
          {ds.map((n) => (
            <li key={n.id}>
              <button
                type="button"
                onClick={() => onChon(n.id)}
                className="block w-full cursor-pointer rounded-md border border-border-field px-3 py-1.5 text-left text-than hover:bg-fill-strong"
              >
                {tenNut(n)}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-than text-muted">Không có.</p>
      )}
    </section>
  )

  return (
    <aside data-testid="so-voi-mau" className={`space-y-4 ${khung}`}>
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-muc font-semibold">So với mẫu NobleX</h2>
        <button type="button" onClick={onDong} className={`${NUT_PHU} cursor-pointer`}>
          Đóng
        </button>
      </div>
      <p className="text-phu text-muted">
        So với bản mẫu hiện tại — không phân biệt bạn tự sửa hay NobleX đổi mẫu.
      </p>
      {danhSach('Khác mẫu', theo('khac'), 'nhom-khac')}
      <section data-testid="nhom-chua-co" className="space-y-1">
        <h3 className="text-phu font-medium text-muted">
          Có trong mẫu, chưa có trong bản của bạn ({so.chuaCo.length})
        </h3>
        {so.chuaCo.length ? (
          <ul className="space-y-2">
            {so.chuaCo.map((m) => {
              const nhom = nhomCua(m)
              const cung =
                typeof nhom === 'string' ? [] : nhom.slice(1).map((n) => `«${tenNut(n)}»`)
              return (
                <li key={m.id} className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="min-w-0 flex-1 text-than">
                      {tenNut(m)}
                      {cung.length ? (
                        <span className="block text-phu text-muted">
                          Thêm cùng {cung.join(', ')}
                        </span>
                      ) : null}
                    </span>
                    {ghiDuoc ? (
                      <button
                        type="button"
                        disabled={dangGhi}
                        onClick={() => void themVao(m)}
                        aria-label={`Thêm «${tenNut(m)}»${cung.length ? ` cùng ${cung.join(', ')}` : ''} vào bản của bạn`}
                        className={`${NUT_PHU} cursor-pointer disabled:opacity-50`}
                      >
                        Thêm vào
                      </button>
                    ) : null}
                  </div>
                  {bao[m.id] ? (
                    <p role="alert" className="text-phu text-badge-alert-fg">
                      {bao[m.id]}
                    </p>
                  ) : null}
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="text-than text-muted">Không có.</p>
        )}
      </section>
      {danhSach('Riêng của workspace', theo('rieng'), 'nhom-rieng')}
    </aside>
  )
}
