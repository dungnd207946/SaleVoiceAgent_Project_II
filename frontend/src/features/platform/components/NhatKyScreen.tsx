/**
 * Màn «Nhật ký» (`/audit`, M8) — đọc `control.audit_log` của workspace hiện tại.
 * Spec: odyssey-portal-backend/docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md §6.
 *
 * Bộ lọc là `useState`, KHÔNG search param: bộ lọc ở đây không phải link gửi đi
 * được (khác `?tab=` của /projects) và không cần Back.
 *
 * LỖI: nguyên văn CHỈ với `LoiApi` (403 của BE nói đúng vai trò và tên quyền
 * còn thiếu, đó là thứ người dùng cần để đi xin quyền); lỗi mạng/`fetch` thô
 * rơi về câu chung «Không tải được nhật ký.» như mọi màn khác.
 */
import { useState } from 'react'
import { KhoRong } from '@/components/ui/TrangThai'
import { NUT_PHU } from '@/components/ui/Bang'
import { LoiApi } from '@/lib/http'
import { LOC_MAC_DINH, useNhatKy, type LocNhatKy } from '../nhatKy'
import { BangNhatKy } from './BangNhatKy'
import { BoLocNhatKy } from './BoLocNhatKy'

export function NhatKyScreen() {
  const [loc, datLoc] = useState<LocNhatKy>(LOC_MAC_DINH)
  const q = useNhatKy(loc)
  const dong = q.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="flex flex-col gap-4 px-7 pt-[22px] pb-15 max-md:px-4">
      <BoLocNhatKy loc={loc} doi={datLoc} />
      {q.isError ? (
        <div
          className="rounded-lg border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-[14px]"
          role="alert"
        >
          <p>{q.error instanceof LoiApi ? q.error.message : 'Không tải được nhật ký.'}</p>
          <button type="button" className={`${NUT_PHU} mt-2`} onClick={() => void q.refetch()}>
            Thử lại
          </button>
        </div>
      ) : null}
      {q.isPending ? <p className="text-[14px] text-muted">Đang tải…</p> : null}
      {q.isSuccess && dong.length === 0 ? (
        <KhoRong
          tieuDe="Chưa có hoạt động nào"
          huongDan={
            loc.nhom || loc.tu || loc.denHet
              ? 'Không có hoạt động nào khớp bộ lọc — thử nới nhóm hoặc khoảng ngày.'
              : 'Workspace này chưa ghi hoạt động nào.'
          }
        />
      ) : null}
      {dong.length > 0 ? (
        <BangNhatKy
          dong={dong}
          conNua={q.hasNextPage}
          dangTaiThem={q.isFetchingNextPage}
          taiThem={() => void q.fetchNextPage()}
        />
      ) : null}
    </div>
  )
}
