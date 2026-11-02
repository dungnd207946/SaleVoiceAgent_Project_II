/**
 * Tab Media — folder hai mức cho bốn danh mục không có tab chuyên đề.
 *
 * BỐN, KHÔNG PHẢI BẢY (spec vòng 2 §3): `vi_tri`/`mat_bang`/`tien_do` đã có tab
 * riêng và rời khỏi đây, nên mỗi danh mục media chỉ còn thấy được ở đúng MỘT
 * chỗ. Vòng 1 giữ cả bảy và phải viết một câu giải thích «cùng một ảnh, không
 * phải bản sao» — một danh mục một chỗ thì không cần câu nào.
 *
 * FOLDER, KHÔNG PHẢI BỐN VÙNG MỞ SẴN: sau khi bỏ trần 6 ảnh, một danh mục có
 * thể có hàng chục ảnh — bốn vùng mở sẵn thành một trang không cuộn hết.
 *
 * MỨC ĐANG XEM Ở STATE, KHÔNG Ở URL: thêm `?folder=` là thêm một nguồn sự thật
 * cho một trạng thái không ai deep-link tới. Đổi tab là remount nên về mức 1.
 */
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { danhSachMedia, nguonAnh, type Media } from '../api'
import { MEDIA_CATEGORY, MEDIA_CATEGORY_TAB_RIENG } from '../enums'
import { LoiTai } from '@/components/ui/TrangThai'
import { useTrangCuon } from './useTrangCuon'
import { VungMedia } from './VungMedia'
import { NUT_PHU } from '@/components/ui/Bang'

const DANH_MUC = MEDIA_CATEGORY.filter((dm) => !MEDIA_CATEGORY_TAB_RIENG.includes(dm.value))

export function MediaTab({ projectCode }: { projectCode: string }) {
  const qc = useQueryClient()
  const [dangMo, setDangMo] = useState<string | null>(null)

  const ds = useTrangCuon<Media>(['re', projectCode, 'media'], (c) =>
    danhSachMedia(projectCode, { limit: 200, cursor: c }),
  )

  if (ds.isPending) return <p className="text-[14px] text-muted">Đang tải…</p>
  if (ds.error) return <LoiTai viec="danh sách media" thuLai={() => void ds.refetch()} />

  const capDuAn = ds.items.filter((m) => !m.zoneCode && !m.unitCode)
  const lamMoi = () => void qc.invalidateQueries({ queryKey: ['re', projectCode, 'media'] })
  const cuaDanhMuc = (v: string) => capDuAn.filter((m) => m.category === v)

  const mo = DANH_MUC.find((dm) => dm.value === dangMo)
  if (mo) {
    return (
      <div className="space-y-3">
        <button type="button" className={NUT_PHU} onClick={() => setDangMo(null)}>
          ‹ Mọi danh mục
        </button>
        <VungMedia
          projectCode={projectCode}
          category={mo.value}
          nhan={mo.nhan}
          anh={cuaDanhMuc(mo.value)}
          lamMoi={lamMoi}
        />
      </div>
    )
  }

  return (
    <div className="space-y-4" data-testid="media-muc-1">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {DANH_MUC.map((dm) => {
          const cua = cuaDanhMuc(dm.value)
          const bia = cua.find((m) => m.contentType === 'image')
          return (
            <button
              key={dm.value}
              type="button"
              className="rounded-xl border border-border bg-surface p-3 text-left hover:border-border-field"
              onClick={() => setDangMo(dm.value)}
            >
              <div className="mb-2 flex h-36 items-center justify-center rounded bg-fill-strong text-[12px] text-muted">
                {bia ? (
                  <img
                    src={nguonAnh(bia.thumbUrl ?? bia.mediaUrl)}
                    alt=""
                    className="h-36 w-full rounded object-cover"
                  />
                ) : (
                  'Chưa có ảnh'
                )}
              </div>
              <p className="text-[14px] font-medium">{dm.nhan}</p>
              <p className="text-[12px] text-muted">{cua.length} mục</p>
            </button>
          )
        })}
      </div>
    </div>
  )
}
