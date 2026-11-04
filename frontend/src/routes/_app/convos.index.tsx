import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { type LocKhach, SO_HANG_KHACH, SO_HANG_KHACH_MAC_DINH } from '@/features/ops/api'
import { KhachList } from '@/features/ops/components/KhachList'
import { type LocStage, laLocStage } from '@/features/ops/lead'

/**
 * Màn danh sách khách (spec §5.1) — route INDEX của `/convos`, tách ra khỏi
 * `convos.tsx` (Finding 1, review cuối nhánh M7): route cha giờ chỉ là layout
 * `<Outlet/>`, và đây là route con hiện đúng khi URL là `/convos` trần (chưa
 * chọn khách).
 *
 * Bộ lọc nằm ở SEARCH PARAM, không phải `useState`: F5 hoặc gửi link cho đồng
 * nghiệp thì vẫn ra đúng danh sách đang xem. Phân trang cũng vậy (`trang`,
 * `so` = số hàng mỗi trang): mặc định (trang 1, `SO_HANG_KHACH_MAC_DINH` hàng) thì KHÔNG
 * ghi lên URL cho link gọn.
 */
export interface TimKiem {
  q?: string | undefined
  tu?: '7' | '30' | 'all' | undefined
  chuyen?: boolean | undefined
  trang?: number | undefined
  so?: number | undefined
  /** Lọc theo lead mới nhất — `lead|mql|sql|hen_gap|none`. Vắng = mọi stage. */
  stage?: LocStage | undefined
}

/** `?trang=` gõ tay về thành SỐ, `<Link search>` có thể về thành chuỗi — nhận cả hai. */
function soNguyenDuong(v: unknown): number | undefined {
  const n = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
  return Number.isInteger(n) && n >= 1 ? n : undefined
}

export const Route = createFileRoute('/_app/convos/')({
  validateSearch: (s: Record<string, unknown>): TimKiem => ({
    q: typeof s.q === 'string' ? s.q : undefined,
    tu: s.tu === '7' || s.tu === 'all' ? s.tu : undefined,
    chuyen: s.chuyen === true || s.chuyen === 'true' ? true : undefined,
    trang: soNguyenDuong(s.trang),
    // Chỉ nhận cỡ trang có trong ô «Mỗi trang» — `?so=100000` gõ tay không được
    // biến thành một request vượt trần `GIOI_HAN_TRANG` rồi ăn 422.
    so: SO_HANG_KHACH.find((n) => n === soNguyenDuong(s.so)),
    // Giá trị lạ trên URL ⇒ coi như không lọc (spec §4.2) — không gửi `lead_stage=xyz`
    // lên để ăn 422.
    stage: laLocStage(s.stage) ? s.stage : undefined,
  }),
  component: ManDanhSachKhach,
})

function ManDanhSachKhach() {
  const s = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  // `LocKhach` (Task 4, `api.ts`) khai `q?`/`daChuyen?` KHÔNG kèm `| undefined`
  // — `exactOptionalPropertyTypes` cấm gán tường minh `undefined` vào đó, nên
  // trải object có điều kiện, đừng gán `q: s.q` thẳng khi `s.q` là `undefined`.
  const loc: LocKhach = {
    tuNgay: s.tu ?? '30',
    ...(s.q !== undefined ? { q: s.q } : {}),
    ...(s.chuyen !== undefined ? { daChuyen: s.chuyen } : {}),
    ...(s.trang !== undefined ? { trang: s.trang } : {}),
    ...(s.so !== undefined ? { soHang: s.so } : {}),
    ...(s.stage !== undefined ? { stage: s.stage } : {}),
  }

  return (
    <KhachList
      loc={loc}
      datLoc={(l) => {
        const tu = l.tuNgay === '30' ? undefined : l.tuNgay
        const chuyen = l.daChuyen || undefined
        const q = l.q || undefined
        const stage = l.stage
        // Đổi MỘT MÌNH trang là PUSH (Back = trang trước, cùng lệ `/billing`);
        // đổi lọc là REPLACE — gõ ô tìm không được để lại một mục lịch sử mỗi phím.
        const chiDoiTrang =
          q === s.q &&
          tu === s.tu &&
          chuyen === s.chuyen &&
          stage === s.stage &&
          l.soHang === loc.soHang
        void navigate({
          search: {
            q,
            tu,
            chuyen,
            stage,
            trang: l.trang && l.trang > 1 ? l.trang : undefined,
            so:
              l.soHang === undefined || l.soHang === SO_HANG_KHACH_MAC_DINH ? undefined : l.soHang,
          },
          replace: !chiDoiTrang,
        })
      }}
    />
  )
}
