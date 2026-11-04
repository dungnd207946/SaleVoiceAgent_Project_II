import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CAO_MAN, NUT_CHINH } from '@/components/ui/Bang'
import { DauMuc } from '@/components/ui/DauMuc'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import { LoiTai } from '@/components/ui/TrangThai'
import { LoiApi } from '@/lib/http'
import { chayNgay, useNhatKy, useTongQuan, type Viec } from '../api'
import { daChayLai } from '../nhan'
import { usePhanTrang } from '../phanTrang'
import { so } from '../thoiGian'
import { BangViec } from './BangViec'

function The({ nhan, giaTri, phu }: { nhan: string; giaTri: string; phu?: string | undefined }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-3.5">
      <p className="text-[12px] text-muted">{nhan}</p>
      <p className="mt-0.5 font-mono text-[24px] font-bold tracking-[-.02em] tabular-nums">{giaTri}</p>
      {phu && <p className="mt-1 text-[12px] text-muted-2">{phu}</p>}
    </div>
  )
}

const KHONG_CO: readonly Viec[] = []

export function TabTongQuan() {
  const q = useTongQuan()
  const nhatKy = useNhatKy()
  const { hien, thanh } = usePhanTrang(nhatKy.data ?? KHONG_CO)
  const qc = useQueryClient()
  const chay = useMutation({
    mutationFn: chayNgay,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['kb-web'] }),
  })
  if (q.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (q.isError) return <LoiTai viec="tổng quan dữ liệu ngoài" thuLai={() => void q.refetch()} />
  const tq = q.data
  const loiChay = chay.error instanceof LoiApi ? chay.error.message : chay.error ? 'Không xếp được lượt chạy.' : ''

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <div className="flex-none">
        <DauMuc
          tieuDe="Kho dữ liệu ngoài của workspace"
          ghiChu="Bài báo từ các trang công khai và hồ sơ dự án tổng hợp từ các bài đó."
          phai={
            <button type="button" className={NUT_CHINH} disabled={chay.isPending} onClick={() => chay.mutate('nightly')}>
              Cập nhật ngay
            </button>
          }
        />
        {loiChay && (
          <p role="alert" className="mb-3 text-[13px] text-badge-alert-fg">
            {loiChay}
          </p>
        )}
        {chay.isSuccess && (
          <p className="mb-3 text-[13px] text-muted">Đã xếp lượt chạy, theo dõi ở nhật ký bên dưới.</p>
        )}
        <div className="grid grid-cols-2 gap-3 max-md:grid-cols-1">
          <The
            nhan="Dự án có hồ sơ"
            giaTri={`${so(tq.soDuAnCoHoSo)} / ${so(tq.soDuAn)}`}
            phu={tq.soDuAn - tq.soDuAnCoHoSo > 0 ? `${so(tq.soDuAn - tq.soDuAnCoHoSo)} chưa có` : 'đủ cả'}
          />
          <The nhan="Bài báo thu trong 7 ngày" giaTri={so(tq.baiBayNgay)} phu={`${so(tq.soNguonBat)} nguồn đang bật`} />
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <DauMuc tieuDe="Nhật ký chạy" />
        {nhatKy.isError ? (
          <LoiTai viec="nhật ký chạy" thuLai={() => void nhatKy.refetch()} />
        ) : (
          <BangViec
            viec={hien}
            rong="Chưa có lượt chạy nào trong 7 ngày qua."
            huongDan="Lượt đầu tiên sẽ xuất hiện khi lịch tới giờ hoặc khi bạn bấm «Cập nhật ngay»."
            chan={thanh.total > 0 ? <ThanhTrang {...thanh} dangTai={nhatKy.isPending} /> : undefined}
            cao={CAO_MAN}
            daChayLai={daChayLai(nhatKy.data ?? KHONG_CO)}
          />
        )}
      </div>
    </div>
  )
}
