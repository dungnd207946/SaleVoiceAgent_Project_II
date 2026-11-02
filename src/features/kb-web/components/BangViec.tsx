/** Bảng nhật ký lượt chạy ở tab Tổng quan. */
import type { ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Bang, DauBang, Hang, NUT_HANG, PILL, TD, TD_PHU, TheBang, VungCuon, type Cot } from '@/components/ui/Bang'
import { KhoRong } from '@/components/ui/TrangThai'
import { chayNgay, lamMoiDuAn, type Mode, type Viec } from '../api'
import { ketQuaViec, nguoiViec, phamViViec, tenViec } from '../nhan'
import { luc } from '../thoiGian'

const COT_DAU: readonly Cot[] = [{ nhan: 'Thời gian' }, { nhan: 'Việc' }, { nhan: 'Phạm vi' }, { nhan: 'Người chạy' }]
const COT_CHI_PHI: Cot = { nhan: 'Chi phí', phai: true }
const COT_CUOI: readonly Cot[] = [{ nhan: 'Kết quả' }, { nhan: '' }]

function hienChiPhi(x: string | null | undefined): string {
  return x == null ? '—' : `${Math.round(Number(x)).toLocaleString('vi-VN')} ₫`
}

export function ChamDangChay({ chu }: { chu: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] text-fg">
      <span className="inline-block size-2 animate-pulse rounded-full bg-ac" />
      {chu}
    </span>
  )
}

export function BangViec({
  viec,
  rong,
  huongDan,
  chan,
  cao,
  daChayLai,
}: {
  viec: readonly Viec[]
  rong: string
  huongDan: string
  chan?: ReactNode
  /** `CAO_MAN`: bảng lấp phần còn lại của màn, `chan` (phân trang) đứng yên ở đáy. */
  cao?: string
  /** id lượt lỗi đã có lượt sau cùng việc — không hiện nút Chạy lại. */
  daChayLai?: ReadonlySet<number>
}) {
  const qc = useQueryClient()
  const chayLai = useMutation({
    mutationFn: (v: Viec) =>
      v.loai === 'kbweb_run' ? chayNgay(v.mode as Mode) : lamMoiDuAn(v.duAn ?? '', v.mode === 'rebuild' ? 'rebuild' : 'init'),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kb-web'] }),
  })

  if (viec.length === 0)
    return (
      <div className="p-4">
        <KhoRong tieuDe={rong} huongDan={huongDan} />
      </div>
    )

  // Cột chi phí chỉ hiện khi BE trả tiền (người xem có quyền xem chi phí).
  const coChiPhi = viec.some((v) => v.chiPhi != null)
  const cot = coChiPhi ? [...COT_DAU, COT_CHI_PHI, ...COT_CUOI] : [...COT_DAU, ...COT_CUOI]

  return (
    <TheBang cao={cao}>
      <VungCuon>
        <Bang nhan="Nhật ký chạy">
          <DauBang cot={cot} />
          <tbody>
            {viec.map((v) => {
              const kq = ketQuaViec(v)
              const coChayLai = v.trangThai === 'failed' && v.loai !== 'kbweb_probe' && !daChayLai?.has(v.id)
              return (
                <Hang key={v.id}>
                  <td className={TD_PHU}>{luc(v.batDau ?? v.taoLuc)}</td>
                  <td className={`${TD} font-medium whitespace-nowrap text-fg`}>{tenViec(v)}</td>
                  <td className={`${TD} max-w-[240px] truncate whitespace-nowrap`} title={phamViViec(v)}>
                    {phamViViec(v)}
                  </td>
                  <td className={TD_PHU}>{nguoiViec(v)}</td>
                  {coChiPhi && (
                    <td className={`${TD} text-right font-mono whitespace-nowrap tabular-nums`}>{hienChiPhi(v.chiPhi)}</td>
                  )}
                  <td className={TD}>
                    <span className="inline-flex items-center gap-2.5">
                      {v.trangThai === 'running' ? (
                        <ChamDangChay chu="Đang chạy" />
                      ) : (
                        <span className={`${PILL} whitespace-nowrap ${kq.mau}`}>{kq.nhan}</span>
                      )}
                      {kq.chiTiet && (
                        <span className="text-[13px] text-muted" title={v.trangThai === 'failed' ? v.thongDiep : undefined}>
                          {kq.chiTiet}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className={`${TD} text-right`}>
                    {coChayLai && (
                      <button type="button" className={`${NUT_HANG} whitespace-nowrap`} onClick={() => chayLai.mutate(v)} disabled={chayLai.isPending}>
                        Chạy lại
                      </button>
                    )}
                  </td>
                </Hang>
              )
            })}
          </tbody>
        </Bang>
      </VungCuon>
      {chan}
    </TheBang>
  )
}
