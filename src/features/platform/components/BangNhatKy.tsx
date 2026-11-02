/**
 * Bảng nhật ký: Thời gian · Người · Hành động · Chi tiết + chân «Tải thêm».
 * Không sắp xếp, không chọn hàng — nhật ký đọc theo dòng thời gian, mới nhất trước.
 */
import {
  Bang,
  ChanBang,
  DauBang,
  HANG_NUT,
  Hang,
  NUT_PHU,
  TD,
  TD_PHU,
  TheBang,
  VungCuon,
} from '@/components/ui/Bang'
import { dinhDangLuc } from '../api'
import { tenNguoi, tomTatChiTiet } from '../hienNhatKy'
import { nhanHanhDong } from '../so-hanh-dong'
import type { DongNhatKy } from '../nhatKy'

const COT = [
  { nhan: 'Thời gian' },
  { nhan: 'Người' },
  { nhan: 'Hành động' },
  { nhan: 'Chi tiết', rong: 'w-full' },
]

export function BangNhatKy({
  dong,
  conNua,
  dangTaiThem,
  taiThem,
}: {
  readonly dong: readonly DongNhatKy[]
  readonly conNua: boolean
  readonly dangTaiThem: boolean
  readonly taiThem: () => void
}) {
  return (
    <TheBang>
      <VungCuon>
        <Bang nhan="Nhật ký hoạt động">
          <DauBang cot={COT} />
          <tbody>
            {dong.map((d) => {
              const tt = tomTatChiTiet(d.chiTiet)
              return (
                <Hang key={d.id}>
                  <td className={TD_PHU}>{dinhDangLuc(d.luc)}</td>
                  <td className={`${TD} whitespace-nowrap`} title={d.actorEmail ?? undefined}>
                    {tenNguoi(d)}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>{nhanHanhDong(d.hanhDong)}</td>
                  <td className={`${TD} font-mono text-phu text-muted`} title={tt.dayDu}>
                    {tt.ngan}
                  </td>
                </Hang>
              )
            })}
          </tbody>
        </Bang>
      </VungCuon>
      {conNua ? (
        <ChanBang>
          <div className={HANG_NUT}>
            <button type="button" className={NUT_PHU} disabled={dangTaiThem} onClick={taiThem}>
              {dangTaiThem ? 'Đang tải…' : 'Tải thêm'}
            </button>
          </div>
        </ChanBang>
      ) : null}
    </TheBang>
  )
}
