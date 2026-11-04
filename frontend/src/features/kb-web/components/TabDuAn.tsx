import { useState } from 'react'
import { Bang, CAO_MAN, DauBang, Hang, O_LOC, PILL, TD, TD_PHU, TD_SO, TheBang, VungCuon, type Cot } from '@/components/ui/Bang'
import { DauMuc } from '@/components/ui/DauMuc'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { useDuAn, type DuAn } from '../api'
import { usePhanTrang } from '../phanTrang'
import { luc, soNgayCach } from '../thoiGian'
import { ChamDangChay } from './BangViec'
import { ChiTietDuAn } from './ChiTietDuAn'

const COT: readonly Cot[] = [
  { nhan: 'Dự án', rong: 'w-full' },
  { nhan: 'Chủ đề có dữ liệu', phai: true },
  { nhan: 'Cập nhật lúc' },
  { nhan: 'Trạng thái' },
]

/** Hồ sơ cập nhật quá số ngày này thì coi là cần cập nhật. */
const NGAY_CU = 7

type Loc = 'tat_ca' | 'chua_co' | 'cu' | 'loi'

function trangThai(d: DuAn) {
  if (d.dangChay) return <ChamDangChay chu="Đang viết" />
  if (d.viecGanNhat?.trangThai === 'failed')
    return (
      <span className={`${PILL} bg-badge-alert-bg whitespace-nowrap text-badge-alert-fg`} title={d.viecGanNhat.thongDiep}>
        Lỗi
      </span>
    )
  if (d.soMuc === 0) return <span className={`${PILL} bg-badge-neutral-bg whitespace-nowrap text-badge-neutral-fg`}>Chưa có hồ sơ</span>
  if (!d.capNhatLuc || soNgayCach(d.capNhatLuc) > NGAY_CU)
    return <span className={`${PILL} bg-badge-warn-bg whitespace-nowrap text-badge-warn-fg`}>Cần cập nhật</span>
  return <span className={`${PILL} bg-acs whitespace-nowrap text-acd`}>Đã cập nhật</span>
}

function khop(d: DuAn, loc: Loc, tim: string): boolean {
  const t = tim.trim().toLowerCase()
  if (t && !d.ten.toLowerCase().includes(t) && !d.code.toLowerCase().includes(t)) return false
  if (loc === 'chua_co') return d.soMuc === 0
  if (loc === 'cu') return d.soMuc > 0 && (!d.capNhatLuc || soNgayCach(d.capNhatLuc) > NGAY_CU)
  if (loc === 'loi') return d.viecGanNhat?.trangThai === 'failed'
  return true
}

const KHONG_CO: readonly DuAn[] = []

export function TabDuAn({ suaDuoc, moSan }: { suaDuoc: boolean; moSan?: string | undefined }) {
  const q = useDuAn()
  const [loc, setLoc] = useState<Loc>('tat_ca')
  const [tim, setTim] = useState('')
  const [moCode, setMoCode] = useState<string | null>(moSan ?? null)
  const { hien, thanh } = usePhanTrang((q.data ?? KHONG_CO).filter((d) => khop(d, loc, tim)))

  if (q.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (q.isError) return <LoiTai viec="danh sách dự án" thuLai={() => void q.refetch()} />
  const ds = q.data
  if (moCode) {
    const d = ds.find((x) => x.code === moCode)
    return <ChiTietDuAn code={moCode} ten={d?.ten ?? moCode} suaDuoc={suaDuoc} quayLai={() => setMoCode(null)} />
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <DauMuc
        tieuDe="Hồ sơ theo dự án"
        dem={`${ds.length} dự án`}
        phai={
          <>
            <select className={`o-chon ${O_LOC}`} value={loc} onChange={(e) => setLoc(e.target.value as Loc)} aria-label="Lọc dự án">
              <option value="tat_ca">Tất cả</option>
              <option value="chua_co">Chưa có hồ sơ</option>
              <option value="cu">Cần cập nhật</option>
              <option value="loi">Lỗi</option>
            </select>
            <input className={`${O_LOC} w-[220px]`} placeholder="Tìm dự án" value={tim} onChange={(e) => setTim(e.target.value)} />
          </>
        }
      />
      {ds.length === 0 ? (
        <KhoRong tieuDe="Chưa có dự án nào đã published." huongDan="Công bố một dự án ở màn Kiến thức; hồ sơ dữ liệu ngoài sẽ được dựng sau đó." />
      ) : (
        <TheBang cao={CAO_MAN}>
          <VungCuon>
            <Bang nhan="Dự án">
              <DauBang cot={COT} />
              <tbody>
                {hien.map((d) => (
                  <Hang key={d.code}>
                    <td className={TD}>
                      <button type="button" className="font-medium text-ac hover:text-acd" onClick={() => setMoCode(d.code)}>
                        {d.ten}
                      </button>
                    </td>
                    <td className={TD_SO}>{d.soChuDe === undefined ? d.soMuc : `${d.soMuc} / ${d.soChuDe}`}</td>
                    <td className={TD_PHU}>{d.capNhatLuc ? luc(d.capNhatLuc) : '—'}</td>
                    <td className={TD}>{trangThai(d)}</td>
                  </Hang>
                ))}
              </tbody>
            </Bang>
          </VungCuon>
          {thanh.total > 0 && <ThanhTrang {...thanh} />}
        </TheBang>
      )}
    </div>
  )
}
