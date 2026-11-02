/**
 * Tab «Nguồn dữ liệu» của màn Kiến thức (`/projects`).
 *
 * Trả lời cho bài toán: tenant đã có hệ thống riêng chứa sẵn dự án · phân khu ·
 * quỹ căn, và **hệ thống của họ chịu trách nhiệm đẩy sang mình** — mình không đi
 * lắp API của từng khách. Toàn bộ lý lẽ ở đầu `features/realestate/nguon.ts`.
 *
 * BA khối, xếp theo thứ tự người vận hành thật sự đọc:
 *   ① Điểm nạp + tình trạng — thứ liếc mỗi sáng để biết đường đẩy còn sống
 *   ② Token đẩy dữ liệu — thứ phát một lần rồi thôi
 *   ③ Bản ghi bị từ chối — thứ mở khi ① báo có hỏng
 *
 * ⚠️ KHÔNG có khối «hợp đồng dữ liệu» nào ở đây nữa (người dùng chốt
 * 2026-08-14). Bản trước dựng hai bảng trường (vỏ bản ghi + trường của `data`)
 * chép tay từ `contracts.py`/`enums.ts`, kèm một đoạn `curl` mẫu — và chính
 * docstring của nó phải ghi *«bản sao viết tay, nguồn sự thật là backend»*.
 * Không cổng parity nào canh, nên ngày backend thêm một trường thì trang tài
 * liệu trong portal nói sai mà không ai biết. Nay chỉ còn MỘT link ra Swagger
 * của chính endpoint đó — sinh từ backend, không lệch được.
 *
 * ⚠️ CHƯA CÓ BACKEND. Cả tab chạy trên fake MSW (`features/realestate/msw.ts`) —
 * đây là bản dựng để nhìn thấy thiết kế trước khi chốt spec, cùng lối `/agent/try`
 * và `/api/v1/linh-vuc` đã đi.
 */
import { useQuery } from '@tanstack/react-query'
import { TheBang, ThanhCong } from '@/components/ui/Bang'
import { LoiTai } from '@/components/ui/TrangThai'
import { Q_TONG_QUAN, taiTongQuan } from '../nguon'
import { cachDay } from '../nguonDinhDang'
import { NguonToken } from './NguonToken'
import { NguonLoi } from './NguonLoi'

const KHOI_MA =
  'overflow-x-auto rounded-lg border border-border-field bg-fill px-3 py-2.5 font-mono text-phu leading-[1.7] text-fg'

function O({
  nhan,
  so,
  canh,
}: {
  readonly nhan: string
  readonly so: number
  readonly canh?: boolean | undefined
}) {
  return (
    <div>
      <p
        className={`text-[22px] font-semibold leading-none ${
          canh && so > 0 ? 'text-badge-alert-fg' : 'text-fg'
        }`}
      >
        {so.toLocaleString('vi-VN')}
      </p>
      <p className="mt-1.5 text-phu text-muted-2">{nhan}</p>
    </div>
  )
}

export function NguonDuLieuTab() {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: Q_TONG_QUAN,
    queryFn: taiTongQuan,
  })

  if (isPending)
    return (
      <p className="rounded-xl border border-border bg-surface p-5 text-[14px] text-muted">
        Đang tải…
      </p>
    )

  if (error) return <LoiTai viec="tình trạng nguồn dữ liệu" thuLai={() => void refetch()} />

  return (
    <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pb-2">
      <TheBang>
        <ThanhCong>
          <h3 className="mr-auto text-the font-semibold text-fg">Endpoint</h3>
          <span className="flex-none text-phu text-muted-2">
            24 giờ qua · nhận cuối {cachDay(data.thongKe.nhanCuoiLuc, new Date())}
          </span>
        </ThanhCong>

        <div className="p-4">
          <p className={KHOI_MA}>POST {data.diemNap}</p>

          <div className="mt-5 flex flex-wrap gap-x-10 gap-y-4">
            <O nhan="Đã nhận" so={data.thongKe.soNhan24h} />
            <O nhan="Ghi thành công" so={data.thongKe.soGhiDuoc24h} />
            <O nhan="Bị từ chối" so={data.thongKe.soHong24h} canh />
          </div>
          {/* Nút «Tải OpenAPI» đã BỎ (người dùng chốt 2026-08-21, cùng ngày thêm):
              trang Swagger đã có link `openapi.json` ngay dưới tiêu đề — hai đường
              cho cùng một tệp là thừa. Cần spec thì vào Tài liệu API mà lấy. */}
          <div className="mt-4 border-t border-border-soft pt-3">
            <a
              href={data.docsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="text-[13px] font-medium text-ac hover:underline"
            >
              Tài liệu API
            </a>
          </div>
        </div>
      </TheBang>

      <NguonToken tokens={data.tokens} />
      <NguonLoi />
    </div>
  )
}
