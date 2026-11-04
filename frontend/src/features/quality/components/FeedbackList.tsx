/**
 * Container của màn `/quality` — chạy TanStack Query, render tải/lỗi/rỗng,
 * dải chip lọc sao, dải thống kê (Task 6), danh sách review (Task 7), và nút
 * "Trang sau".
 *
 * Cùng khuôn `KhachList({ loc, datLoc })` (features/ops): route mẹ (Task 10)
 * giữ state lọc ở search param, component này không tự giữ filter nào —
 * mọi lượt bấm chip/Trang sau chỉ gọi `datLoc` với `loc` mới, route mẹ mới là
 * nơi state thật sự sống.
 */
import { useQuery } from '@tanstack/react-query'
import { Icon } from '@/components/icons'
import { MUC_CHON, NHOM_CHON } from '@/components/ui/Bang'
import { danhSachFeedback, type LocFeedback } from '../api'
import { FeedbackReviewCard } from './FeedbackReviewCard'
import { FeedbackTongQuan } from './FeedbackTongQuan'

const NAM_SAO = [5, 4, 3, 2, 1] as const

/**
 * Đổi bộ lọc sao (bấm chip hoặc "Tất cả") ⇒ trang MỚI: trả `loc` KHÔNG MANG
 * khoá `ratings` LẪN `beforeId`. Trước đây hàm này CHỦ Ý giữ `beforeId` (đổi
 * lọc mà không mất trang đang xem) — nhưng đó tạo ra một cursor ẨN: bấm "Trang
 * sau" rồi đổi sang lọc "5 sao" sẽ hỏi "5 sao cũ hơn id X" mà không có gì
 * trên màn nói cursor còn sống. Nơi DUY NHẤT được đặt `beforeId` là handler
 * "Trang sau" bên dưới — đổi lọc luôn bắt đầu lại từ trang đầu, tức bỏ TOÀN
 * BỘ `loc` hiện có, không riêng hai field đang biết tên.
 *
 * Trả `{}` KHÔNG PHẢI vì lười gọi tên field — chính vì hàm này nêu tên field
 * là đúng thứ đã gây lỗi ở Finding 1 (bản cũ dựng lại object bằng cách nêu
 * tên `beforeId`, nên `LocFeedback` thêm field thứ ba sẽ bị rơi mất mà không
 * ai thấy). "Bắt đầu lại từ trang đầu" nghĩa là KHÔNG mang gì qua trang mới —
 * `{}` diễn đúng nghĩa đó cho bất kỳ số field `LocFeedback` có, hôm nay hay
 * sau này.
 */
function boLoc(): LocFeedback {
  return {}
}

/**
 * Tấm nền của cả màn — cùng khuôn `Khung` của `KhachList.tsx`. Ba trạng thái
 * (đang tải · lỗi · rỗng) dùng CHUNG khung này, không mỗi cái một kiểu.
 */
function Khung({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-7 py-6 max-md:px-4 max-md:py-4">
      <div className="overflow-hidden rounded-lg border border-border bg-surface">{children}</div>
    </div>
  )
}

export function FeedbackList({
  loc,
  datLoc,
}: {
  loc: LocFeedback
  datLoc: (l: LocFeedback) => void
}) {
  const ds = useQuery({
    queryKey: ['quality', 'feedback', loc],
    queryFn: () => danhSachFeedback(loc),
  })

  // Bấm sao đang chọn lại: bỏ khỏi bộ lọc (multi-select) thay vì thay thế —
  // người dùng có thể muốn xem đồng thời 1★ và 2★ (đều là "cần chú ý").
  const toggleSao = (n: number) => {
    const dangChon = loc.ratings ?? []
    const moi = dangChon.includes(n) ? dangChon.filter((r) => r !== n) : [...dangChon, n]
    datLoc(moi.length > 0 ? { ...boLoc(), ratings: moi } : boLoc())
  }

  if (ds.isPending)
    return (
      <Khung>
        <p className="p-6 text-[14px] text-muted">Đang tải…</p>
      </Khung>
    )
  // Hai nguyên nhân, hai câu — cùng lý do `KhachList.tsx` đã ghi: backend chết
  // mà hiện "chưa có feedback nào" thì người vận hành ngồi đợi một thứ không
  // bao giờ tới, và không ai báo sự cố.
  if (ds.error)
    return (
      <Khung>
        <p className="p-6 text-[14px]">Không tải được feedback.</p>
      </Khung>
    )

  const dangChon = loc.ratings ?? []
  // Chốt vào biến cục bộ để TypeScript giữ được phần hẹp `!== null` xuyên qua
  // closure `onClick` bên dưới — thu qua `ds.data.nextBeforeId` lần hai trong
  // arrow function không được hẹp lại kiểu.
  const tiepTheo = ds.data.nextBeforeId

  return (
    <Khung>
      <FeedbackTongQuan
        total={ds.data.total}
        theoSao={ds.data.theoSao}
        diemTrungBinh={ds.data.diemTrungBinh}
      />
      <div className="flex flex-wrap items-center gap-2 border-b border-border-soft px-6 py-3 max-md:px-4">
        <span id="loc-sao" className="mr-1 text-[13px] text-muted">
          Lọc theo sao:
        </span>
        {/* Cùng hình `ChonMot` nhưng chọn được NHIỀU sao (1★ + 2★ = «cần chú ý»), nên
            dựng tay bằng hai chuỗi class của nó. Tên nút là «5 sao»: ký tự ★ bị đọc
            thành «black star». */}
        <div role="group" aria-labelledby="loc-sao" className={`${NHOM_CHON} max-md:w-full`}>
          <button
            type="button"
            aria-pressed={dangChon.length === 0}
            onClick={() => datLoc(boLoc())}
            className={MUC_CHON}
          >
            Tất cả
          </button>
          {NAM_SAO.map((n) => (
            <button
              key={n}
              type="button"
              aria-label={`${n} sao`}
              aria-pressed={dangChon.includes(n)}
              onClick={() => toggleSao(n)}
              className={MUC_CHON}
            >
              <Icon name="star" className="size-3.5 fill-current text-ac" />
              {n}
            </button>
          ))}
        </div>
      </div>

      {ds.data.items.length === 0 ? (
        // Kho rỗng là BÌNH THƯỜNG (đã lọc hết, hoặc chưa có feedback nào) —
        // không role="alert", không màu đỏ. Khác hẳn nhánh lỗi phía trên.
        <p className="px-6 py-12 text-center text-[14px] text-muted max-md:px-4">
          Chưa có feedback nào.
        </p>
      ) : (
        ds.data.items.map((f) => <FeedbackReviewCard key={f.id} feedback={f} />)
      )}

      {tiepTheo !== null && (
        // Nhãn "Trang sau" (không phải "Xem thêm"): bấm nút này THAY THẾ
        // trang đang xem bằng trang kế (Finding 3) — nó không cộng dồn danh
        // sách, nên nhãn hứa "xem thêm" (tích luỹ) là nói sai hành vi thật.
        // Nút cùng lý do KHÔNG chuyển sang `useInfiniteQuery`: đó là đổi hình
        // dạng luồng dữ liệu, không cần cho một màn tổng quan như thế này —
        // Back của trình duyệt đã đóng vai "trang trước" (route push, xem
        // Finding 5 ở `quality.tsx`), nên thay-thế + nhãn trung thực là đủ.
        <div className="p-4 text-center">
          <button
            type="button"
            onClick={() => datLoc({ ...loc, beforeId: tiepTheo })}
            className="rounded-md border border-border-field px-5 py-2 text-[13px]"
          >
            Trang sau
          </button>
        </div>
      )}
    </Khung>
  )
}
