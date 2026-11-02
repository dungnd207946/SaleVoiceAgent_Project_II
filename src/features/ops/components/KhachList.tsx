/**
 * Màn danh sách khách (spec §5.1). Chỉ xem.
 *
 * Ba bộ lọc nằm ở state cục bộ của component NÀY và được route đẩy lên search
 * param (Task 5 step 6) — không phải hai nguồn sự thật: component nhận giá trị
 * và hàm đặt giá trị từ route.
 */
import { type ReactNode, useEffect, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { ChonMot, O_LOC } from '@/components/ui/Bang'
import { ThanhTrang } from '@/components/ui/ThanhTrang'
import { type LocKhach, SO_HANG_KHACH, SO_HANG_KHACH_MAC_DINH, danhSachKhach } from '../api'
import { NHAN_MOC, type MocNgay, mocNgay } from '../thoiGian'
import { KhachRow } from './KhachRow'
import { LocStage } from './LocStage'

const KHOANG: { ma: NonNullable<LocKhach['tuNgay']>; nhan: string }[] = [
  { ma: '7', nhan: '7 ngày' },
  { ma: '30', nhan: '30 ngày' },
  { ma: 'all', nhan: 'Tất cả' },
]

const THU_TU_MOC: MocNgay[] = ['hom-nay', 'hom-qua', 'tuan-truoc', 'cu-hon']

/**
 * Tấm nền của cả màn.
 *
 * MỌI thứ của màn nằm trong đây — tiêu đề, thanh lọc, danh sách, câu báo lỗi,
 * màn rỗng. Trước 07/08 chúng nằm trần trên `--color-bg` và chỉ từng hàng khách
 * mới có nền trắng, nên màn đọc ra như mấy mảnh giấy rời đặt trên bàn xám thay
 * vì nội dung trong một hộp. Ba trạng thái (đang tải · lỗi · rỗng) dùng CHUNG
 * khung này chứ không mỗi cái một kiểu — nếu không, chuyển giữa các trạng thái
 * sẽ thấy cái hộp nhấp nháy hiện ra rồi biến mất.
 */
function Khung({ children }: { children: ReactNode }) {
  return (
    <div className="px-7 py-6 max-md:px-4 max-md:py-4">
      <div className="overflow-hidden rounded-xl border border-border bg-surface">{children}</div>
    </div>
  )
}

export function KhachList({
  loc = {},
  datLoc,
  bayGio,
}: {
  loc?: LocKhach
  datLoc?: (l: LocKhach) => void
  bayGio?: Date | undefined
}) {
  const [nhap, setNhap] = useState(loc.q ?? '')
  // `keepPreviousData`: đổi trang/đổi lọc thì danh sách cũ đứng yên tới khi
  // trang mới về — không rơi lại vào «Đang tải…» (cả tấm nền nháy) ở mỗi lần
  // bấm số trang. `isPending` vì thế chỉ bật ở lần nạp ĐẦU.
  const ds = useQuery({
    queryKey: ['convos', 'khach', loc],
    queryFn: () => danhSachKhach(loc),
    placeholderData: keepPreviousData,
  })

  const trang = loc.trang ?? 1
  const soHang = loc.soHang ?? SO_HANG_KHACH_MAC_DINH
  const tongKhach = ds.data?.tongKhach ?? 0
  const soTrang = Math.max(1, Math.ceil(tongKhach / soHang))

  // Đổi BỘ LỌC (không phải đổi trang) ⇒ về trang 1: trang 7 của «30 ngày» không
  // có nghĩa gì với «7 ngày». Chỉ khi chính lời gọi chỉ đổi `trang` thì mới giữ.
  const doi = (p: Partial<LocKhach>) =>
    datLoc?.({ ...loc, ...p, ...('trang' in p ? {} : { trang: 1 }) })

  // URL gõ tay `?trang=99`, hoặc dữ liệu co lại dưới chân người đang xem trang
  // cuối ⇒ kéo về trang cuối có thật thay vì hiện «Chưa có hội thoại nào» —
  // câu đó là nói dối khi tenant vẫn còn khách ở các trang trước.
  useEffect(() => {
    if (ds.data && !ds.isPlaceholderData && trang > soTrang) doi({ trang: soTrang })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ds.data, ds.isPlaceholderData, trang, soTrang])

  if (ds.isPending)
    return (
      <Khung>
        <p className="p-6 text-[14px] text-muted">Đang tải…</p>
      </Khung>
    )
  // Hai nguyên nhân, hai câu. Backend chết mà hiện "chưa có hội thoại nào" thì
  // người vận hành ngồi đợi một thứ không bao giờ tới, và không ai báo sự cố.
  if (ds.error)
    return (
      <Khung>
        <p className="p-6 text-[14px]">Không tải được danh sách hội thoại.</p>
      </Khung>
    )

  const nhom = new Map<MocNgay, typeof ds.data.items>()
  for (const k of ds.data.items) {
    const m = mocNgay(k.ganNhat, bayGio)
    nhom.set(m, [...(nhom.get(m) ?? []), k])
  }

  return (
    <Khung>
      <div className="border-b border-border-soft px-5 py-4">
        {/* KHÔNG CÒN TIÊU ĐỀ «Hội thoại» Ở ĐÂY (2026-08-09).
            Nó từng là `<h1>` — trùng đúng `<h1>` mà `Topbar` render từ nhãn nav —
            rồi hạ xuống `<h2>` để hết lỗi hai-tiêu-đề-cấp-một. Nhưng hạ bậc
            không làm nó bớt thừa: đo được hai chữ «Hội thoại» y hệt nhau ở
            y=19 và y=113. Khác `/ky-nang-bds` (tiêu đề thẻ ở đó thêm được tên
            lĩnh vực), ở đây nó không thêm một chữ nào. Thẻ bắt đầu thẳng bằng
            dải lọc. */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Ô nhập và nhóm nút lấy nền `bg-bg`, KHÔNG `bg-surface`: chúng đang
              nằm trên tấm trắng, nên trắng-trên-trắng chỉ còn cái viền để nhận
              ra — một ô bấm được phải tự nói ra rằng nó bấm được.

              DÙNG `O_LOC` (tức `CAO_O`, 36px) THAY VÌ SỐ ĐO RIÊNG. Đo bản trước
              trên cùng một dải: ô tìm 39px · nhóm khoảng 36px — lệch 3px nên mép
              dưới không thẳng, cộng bo góc 12px so với 8px và cỡ chữ 14px so với
              13.5px. Đây đúng là lỗi mà docstring `CAO_O` nói đã khoá cho cả
              portal; màn này chưa bao giờ được kéo vào hệ đó. */}
          <input
            type="search"
            aria-label="Tìm khách theo tên hoặc số điện thoại"
            className={`${O_LOC} w-[250px] bg-bg max-md:w-full max-md:basis-full`}
            placeholder="Tìm tên hoặc số điện thoại…"
            value={nhap}
            onChange={(e) => {
              setNhap(e.target.value)
              doi({ q: e.target.value })
            }}
          />
          {/* Khoảng thời gian là BỘ LỌC, không phải tab ⇒ `ChonMot`, không `NhomTab`. */}
          <ChonMot
            nhan="Khoảng thời gian"
            muc={KHOANG}
            chon={loc.tuNgay ?? '30'}
            doi={(ma) => doi({ tuNgay: ma })}
            className="max-md:w-full"
          />
          <LocStage
            gia={loc.stage}
            doi={(v) => {
              if (v) {
                doi({ stage: v })
              } else {
                // Bỏ HẲN khoá `stage` (không gán `undefined`): `exactOptionalPropertyTypes`
                // cấm khoá tuỳ chọn mang `undefined` tường minh.
                const { stage: _bo, ...conLai } = loc
                void _bo
                datLoc?.({ ...conLai, trang: 1 })
              }
            }}
          />
          <label className="flex items-center gap-2 text-than text-muted">
            <input
              type="checkbox"
              checked={!!loc.daChuyen}
              onChange={(e) => doi({ daChuyen: e.target.checked })}
            />
            {/* KHÔNG viết "đã chuyển" liền nhau — badge chip cũng dùng đúng cụm đó,
                và test đếm badge bằng regex /đã chuyển/i trên toàn màn (§ tự soát
                Task 5): nhãn bộ lọc chứa cùng cụm sẽ luôn cộng thêm 1, không do
                số khách daChuyen thật. */}
            Chỉ khách đã được chuyển sales
          </label>
          <span className="ml-auto font-mono text-phu text-muted-2">
            {/* Con số TỔNG của cả tập đã lọc (backend `dem_tong`), không phải của
                trang đang xem — phần «đang xem hàng nào» là việc của thanh phân
                trang ở chân thẻ («Hiện 51–100 / 132»). Trước khi có phân trang,
                chỗ này tự nói «Đang xem 50 / 132 khách» để khỏi cắt cụt im lặng
                (FINDING 2, review cuối nhánh M7); nay các trang còn lại tới được
                nên câu đó không còn việc gì để làm. */}
            {ds.data.tongKhach} khách · {ds.data.tongPhien} phiên
          </span>
        </div>
      </div>

      {ds.data.items.length === 0 ? (
        // Kho rỗng là BÌNH THƯỜNG — không role="alert", không màu đỏ.
        // Không viền đứt nữa: khối này đã nằm trong tấm nền, thêm một cái khung
        // nữa bên trong là hai đường viền lồng nhau chẳng để làm gì.
        <div className="px-5 py-14 text-center">
          <p className="text-the font-semibold">Chưa có hội thoại nào</p>
          {/* <p className="mx-auto mt-1.5 max-w-[440px] text-than leading-relaxed text-muted">
            Khi khách bắt đầu nhắn với agent, họ sẽ hiện ở đây — nhóm theo số điện thoại, người nhắn
            gần nhất lên đầu.
          </p> */}
        </div>
      ) : (
        THU_TU_MOC.filter((m) => nhom.has(m)).map((m) => (
          <div key={m}>
            {/* Mốc ngày có thụt lề `px-5`, còn hàng thì KHÔNG (hàng tự mang lề
                của nó) — nhờ vậy dải nền hover chạy trọn chiều ngang tấm. */}
            <div className="flex items-center gap-2.5 px-5 pb-2 pt-4">
              <span className="text-[12px] font-semibold uppercase tracking-wider text-muted-3">
                {NHAN_MOC[m]}
              </span>
              <span className="h-px flex-1 bg-border" />
            </div>
            {nhom.get(m)!.map((k) => (
              <KhachRow key={k.phone} khach={k} bayGio={bayGio} />
            ))}
          </div>
        ))
      )}

      {/* Kho rỗng thì không có gì để phân trang — «Hiện 0–0 / 0» cạnh câu «Chưa
          có hội thoại nào» là hai chỗ nói cùng một điều. */}
      {tongKhach > 0 && (
        <div className="border-t border-border-soft">
          <ThanhTrang
            trang={Math.min(trang, soTrang)}
            soTrang={soTrang}
            total={tongKhach}
            soHang={soHang}
            doiTrang={(n) => doi({ trang: n })}
            doiSoHang={(n) => doi({ soHang: n })}
            luaChon={SO_HANG_KHACH}
          />
        </div>
      )}
    </Khung>
  )
}
