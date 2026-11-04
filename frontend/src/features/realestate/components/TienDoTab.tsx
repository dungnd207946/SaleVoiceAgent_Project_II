/**
 * Tab Tiến độ — một vùng media `tien_do`, bố cục TIMELINE theo mốc (`moc`):
 * nhóm theo «Tiến độ dd/mm/yyyy — …» trong caption (hợp đồng với adapter AINA,
 * xem `moc.ts`), mốc mới nhất trước — 2026-08-25, người dùng chốt theo giao
 * diện bảng hàng AINA.
 *
 * KHÔNG CÓ TAB VIDEO RIÊNG, và đây là chỗ thấy rõ vì sao: `media` phân biệt bằng
 * HAI trục — `category` và `content_type`. Một tab Video cắt ngang trục
 * `category`, nên video tiến độ sẽ xuất hiện ở cả hai tab; xoá ở một chỗ thì
 * chỗ kia biến mất mà người dùng không hiểu vì sao. Video ở lại tab chủ đề.
 */
import { useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, type Media } from '../api'
import { LoiTai } from '@/components/ui/TrangThai'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'

export function TienDoTab({ projectCode }: { projectCode: string }) {
  const qc = useQueryClient()
  const media = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  if (media.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (media.error) return <LoiTai viec="ảnh tiến độ" thuLai={() => void media.refetch()} />

  return (
    <div className="space-y-4">
      <VungMedia
        projectCode={projectCode}
        category="tien_do"
        nhan="Tiến độ"
        boCuc="moc"
        anh={media.items.filter((m) => !m.zoneCode && !m.unitCode && m.category === 'tien_do')}
        lamMoi={() => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })}
      />
    </div>
  )
}
