/**
 * Bảng lỗi nạp — khối cuối của tab «Nguồn dữ liệu».
 *
 * Khối này là đường phản hồi cho BÊN KHÁCH, không phải cho NobleX. Nó phải nói
 * đủ để người bên kia sửa được mà không cần mở ticket: bản ghi nào, trường nào,
 * sai vì cái gì. Một câu «422 Unprocessable Entity» ở đây là vô dụng.
 *
 * KHO RỖNG Ở ĐÂY LÀ TIN TỐT — nên nó không dùng `KhoRong` (khối đó viết cho ca
 * "chưa có gì, hãy tạo đi"). Không có lỗi nghĩa là mọi bản ghi 24 giờ qua đều
 * vào được, và màn phải nói ra điều đó thay vì bày một lời mời hành động.
 */
import { useQuery } from '@tanstack/react-query'
import {
  Bang,
  DauBang,
  Hang,
  TD,
  TD_PHU,
  ThanhCong,
  TheBang,
  VungCuon,
  type Cot,
} from '@/components/ui/Bang'
import { LoiTai } from '@/components/ui/TrangThai'
import { NHAN_ENTITY, Q_LOI, taiLoi } from '../nguon'
import { luc } from '../nguonDinhDang'

const COT: readonly Cot[] = [
  { nhan: 'Bản ghi' },
  { nhan: 'Trường' },
  { nhan: 'Lý do', rong: 'w-full' },
  { nhan: 'Thời gian' },
]

export function NguonLoi() {
  const { data, error, isPending, refetch } = useQuery({ queryKey: Q_LOI, queryFn: taiLoi })

  if (error)
    return (
      <TheBang>
        <div className="p-4">
          <LoiTai viec="danh sách lỗi nạp" thuLai={() => void refetch()} />
        </div>
      </TheBang>
    )

  return (
    <TheBang>
      <ThanhCong>
        <h3 className="mr-auto text-the font-semibold text-fg">Bản ghi bị từ chối</h3>
      </ThanhCong>

      {isPending ? (
        <p className="p-4 text-than text-muted">Đang tải…</p>
      ) : data.loi.length === 0 ? (
        <p className="p-4 text-than text-muted">
          Không có bản ghi nào bị từ chối trong 24 giờ qua.
        </p>
      ) : (
        <VungCuon>
          <Bang nhan="Bản ghi bị từ chối">
            <DauBang cot={COT} />
            <tbody>
              {data.loi.map((l) => (
                <Hang key={l.id}>
                  <td className={`${TD} whitespace-nowrap`}>
                    <span className="font-mono text-phu font-semibold text-fg">{l.externalId}</span>
                    <span className="ml-2 text-phu text-muted-2">{NHAN_ENTITY[l.entity]}</span>
                  </td>
                  <td className={`${TD} font-mono text-phu text-muted-2`}>
                    {l.truong === '' ? (
                      <span className="font-sans text-muted-3">cả bản ghi</span>
                    ) : (
                      l.truong
                    )}
                  </td>
                  <td className={`${TD} text-fg`}>{l.lyDo}</td>
                  <td className={TD_PHU}>{luc(l.nhanLuc)}</td>
                </Hang>
              ))}
            </tbody>
          </Bang>
        </VungCuon>
      )}
    </TheBang>
  )
}
