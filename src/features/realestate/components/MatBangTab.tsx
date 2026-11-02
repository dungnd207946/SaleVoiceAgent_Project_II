/**
 * Tab Mặt bằng — một vùng ảnh `mat_bang` của dự án.
 *
 * MỘT VÙNG, KHÔNG PHẢI HAI (spec vòng 2 §4.5): «mặt bằng» và «mặt bằng tổng
 * thể» là cùng một thứ, nên `projects.map_media_id` thôi được ghi và agent trả
 * cả bộ ảnh — hợp đồng `docs/contracts/mat-bang-agent.md` của repo backend.
 *
 * Mặt bằng của PHÂN KHU nằm trong form phân khu, không ở đây (lọc `zoneCode`/
 * `unitCode` rỗng) — cùng luật với các tab media khác.
 */
import { useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, type Media } from '../api'
import { LoiTai } from '@/components/ui/TrangThai'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'

export function MatBangTab({ projectCode }: { projectCode: string }) {
  const qc = useQueryClient()
  const media = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  if (media.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (media.error) return <LoiTai viec="ảnh mặt bằng" thuLai={() => void media.refetch()} />

  return (
    <div className="space-y-4 pb-2">
      <VungMedia
        projectCode={projectCode}
        category="mat_bang"
        nhan="Mặt bằng"
        boCuc="gallery"
        anh={media.items.filter((m) => !m.zoneCode && !m.unitCode && m.category === 'mat_bang')}
        lamMoi={() => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })}
      />
    </div>
  )
}
