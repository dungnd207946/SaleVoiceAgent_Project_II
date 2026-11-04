import { createFileRoute } from '@tanstack/react-router'
import { PhienKhach } from '@/features/ops/components/PhienKhach'

// `session` — deep-link đúng phiên từ màn `/quality` (feedback CSAT): mỗi dòng
// feedback gắn với một `session_id` cụ thể, và khách có thể có nhiều phiên —
// không có tham số này, `PhienKhach` luôn rơi về phiên MỚI NHẤT của khách
// (xem `chon`/`useState` trong component), nên bấm vào một dòng feedback cũ có
// thể mở nhầm sang phiên khác của cùng khách, im lặng không báo lỗi gì.
// `export` bắt buộc: `src/routeTree.gen.ts` re-export kiểu route qua tên này —
// không export thì `tsc -b` báo TS4023 "cannot be named" (cùng lý do
// `TimKiem` ở `convos.index.tsx` cũng `export`).
export interface TimKiemPhien {
  session?: string | undefined
  seq?: number | undefined
}

// Component đặt tên riêng (không phải arrow inline): `Route.useParams()` là một
// React Hook, và `react-hooks/rules-of-hooks` chỉ nhận diện hook bên trong một
// hàm component tên viết hoa hoặc một hàm `useXxx` — cùng khuôn với
// `invite.$token.tsx`.
export const Route = createFileRoute('/_app/convos/$phone')({
  validateSearch: (s: Record<string, unknown>): TimKiemPhien => ({
    session: typeof s.session === 'string' ? s.session : undefined,
    seq: typeof s.seq === 'number' ? s.seq : undefined,
  }),
  component: ManChiTietKhach,
})

function ManChiTietKhach() {
  const { phone } = Route.useParams()
  const { session, seq } = Route.useSearch()
  // FINDING 4 (review cuối nhánh M7): `key={phone}` — không có nó, state
  // `chon` (phiên đang chọn) bên trong `PhienKhach` sống sót qua lần điều
  // hướng A -> B (component cùng cây, React không dựng lại nếu không có key
  // đổi), nên đi từ khách A sang khách B sẽ hiện transcript của A cho tới khi
  // người dùng tự bấm chọn lại. Lỗi này không lộ ra trước Finding 1 vì không
  // ai điều hướng được giữa hai khách qua route con. `session` chỉ ảnh hưởng
  // giá trị KHỞI TẠO của `chon` trong lần mount đó — vẫn cần `key={phone}` để
  // reset đúng lúc đổi KHÁCH, hai việc không thay được cho nhau.
  //
  // `PhienKhach.phienMoDau` khai `?: string` KHÔNG kèm `| undefined` —
  // `exactOptionalPropertyTypes` cấm gán tường minh `undefined` vào đó (`session`
  // có kiểu `string | undefined` từ `validateSearch`), nên trải object có điều
  // kiện thay vì gán thẳng — cùng lối `convos.index.tsx` đã dùng cho `q`/`chuyen`.
  return (
    <PhienKhach
      key={phone}
      phone={phone}
      {...(session !== undefined ? { phienMoDau: session } : {})}
      {...(seq !== undefined ? { luotMoDau: seq } : {})}
    />
  )
}
