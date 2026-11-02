/**
 * Chip Trạng thái của DỰ ÁN, đứng ở cột phải hàng tab.
 *
 * VÌ SAO RA KHỎI TAB TỔNG QUAN (spec 2026-08-21 issue 5): `projects.status` là
 * thông tin của cả dự án, nhưng nó chỉ sống trong form của một tab — đứng ở tab
 * Quỹ căn thì không biết dự án đang nháp hay đã phát hành.
 *
 * ⚠️ `zones`/`units`/`documents`/`media` mỗi bảng có `status` RIÊNG, nên một chip
 * treo cố định trên hàng tab rất dễ bị đọc thành trạng thái của thứ đang xem.
 * `aria-label` và tiêu đề menu vì thế nói rõ «dự án»; chip không mang thêm chữ vì
 * hàng tab cần chỗ cho chín tab.
 *
 * PATCH RIÊNG `{status}`: backend dùng `exclude_unset=True` nên nó không đụng 18
 * ô kia. Đổi lại, tab Tổng quan phải THÔI gửi `status` — hai người sở hữu một
 * trường thì người lưu sau hoàn nguyên người lưu trước, và không lỗi nào phát ra.
 */
import { Icon } from '@/components/icons'
import { useRef, useState } from 'react'
import { useDongKhiRaNgoai } from '@/lib/dongKhiRaNgoai'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { suaDuAn, type TrangThai } from '../api'
import { TRANG_THAI, nhanCua } from '../enums'
import { MAU_TRANG_THAI as MAU } from './mauTrangThai'

interface Props {
  projectCode: string
  status: TrangThai
  onLoi: (e: unknown) => void
}

/**
 * ⚠️ CHIP KHÔNG CHẶN GÌ (người dùng chốt 2026-08-21). Bản trước làm mờ mục «Đã
 * phát hành» khi `thieuTruongDuAn()` còn trường, để thay một 422 mờ mịt bằng một
 * câu nói rõ trường nào thiếu. Rồi câu đó bị bỏ khỏi menu — còn lại một mục xám
 * không giải thích gì và KHÔNG ĐƯỜNG NÀO ĐI TIẾP: người dùng đổi sang Bản nháp
 * rồi không phát hành lại được, không biết vì sao.
 *
 * Nay mọi mục đều gửi, và 422 `INCOMPLETE_DATA` của backend đi qua `cauLoi()`
 * thành câu kể tên trường. Backend vốn là nguồn sự thật của luật này; hai bản
 * chép tay của `BAT_BUOC` giờ chỉ còn một bên cưỡng chế.
 */
export function StatusChip({ projectCode, status, onLoi }: Props) {
  const qc = useQueryClient()
  const [mo, setMo] = useState(false)
  const boc = useRef<HTMLDivElement>(null)

  const mDoi = useMutation({
    mutationFn: (s: TrangThai) => suaDuAn(projectCode, { status: s }),
    onSuccess: () => {
      setMo(false)
      void qc.invalidateQueries({ queryKey: ['re', projectCode] })
      void qc.invalidateQueries({ queryKey: ['re', 'projects'] })
    },
    onError: onLoi,
  })

  useDongKhiRaNgoai(boc, mo, () => setMo(false))

  return (
    <div ref={boc} className="relative shrink-0">
      <button
        type="button"
        aria-label={`Trạng thái dự án: ${nhanCua(TRANG_THAI, status)}`}
        aria-haspopup="menu"
        aria-expanded={mo}
        disabled={mDoi.isPending}
        onClick={() => setMo((v) => !v)}
        className={`mb-1 inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-nhan font-semibold ${MAU[status]}`}
      >
        <span aria-hidden className="size-[5px] rounded-full bg-current" />
        {nhanCua(TRANG_THAI, status)}
        <Icon name="caret" className="size-2.5 rotate-90 opacity-60" />
      </button>

      {mo && (
        <div
          role="menu"
          aria-label="Trạng thái dự án"
          className="absolute right-0 top-full z-30 mt-1 w-[168px] rounded-lg border border-border bg-surface py-1 shadow-lg"
        >
          {TRANG_THAI.map((m) => (
            <button
              key={m.value}
              type="button"
              role="menuitem"
              aria-current={m.value === status}
              onClick={() => mDoi.mutate(m.value as TrangThai)}
              className={`block w-full px-3 py-1.5 text-left text-phu hover:bg-fill ${
                m.value === status ? 'font-semibold text-acd' : ''
              }`}
            >
              {m.nhan}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
