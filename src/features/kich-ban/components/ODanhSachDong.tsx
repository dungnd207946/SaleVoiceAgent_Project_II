/**
 * Danh sách Ý của một trường nút (Khi nào dùng · Agent làm gì · Các bước · Không được làm): mỗi ý một ô, nút bỏ ý,
 * «+ Thêm ý» khoá khi đủ trần. Mỗi ý một ô chứ không một textarea «mỗi dòng một ý»: ý dài tự xuống dòng trong ô nên
 * «dòng» trên màn không phải «ý» — người dùng không đếm được mình đang có mấy ý.
 */
import { useId } from 'react'
import { NUT_HANG } from '@/components/ui/Bang'
import { O_CHUNG } from '@/components/ui/Truong'
import { Icon } from '@/components/icons'
import { doDai } from '../khuon'

interface Props {
  nhan: string
  giaTri: readonly string[]
  doiY: (i: number, s: string) => void
  them: () => void
  bo: (i: number) => void
  toiDa: number
  /** Trần ký tự mỗi ý (`maxKyTu`); vắng ⇒ không báo. */
  kyTuMoiY?: number | undefined
  /** Tổng ký tự đã tính theo luật của trường + trần; vắng ⇒ không hiện. */
  tong?: { gia: number; toiDa: number } | undefined
  batBuoc?: boolean | undefined
  goiY?: string | undefined
  loi?: string | undefined
}

export function ODanhSachDong({
  nhan,
  giaTri,
  doiY,
  them,
  bo,
  toiDa,
  kyTuMoiY,
  tong,
  batBuoc,
  goiY,
  loi,
}: Props) {
  const id = useId()
  const moTa = loi ? `${id}-loi` : goiY ? `${id}-goiy` : undefined
  return (
    <div role="group" aria-labelledby={`${id}-nhan`} aria-describedby={moTa}>
      <p id={`${id}-nhan`} className="mb-1.5 text-phu text-muted">
        {nhan}
        {batBuoc ? (
          <span className="text-badge-alert-fg" aria-hidden="true">
            {' '}
            *
          </span>
        ) : null}
      </p>
      <ol className="space-y-2">
        {giaTri.map((y, i) => (
          <li key={i} className="flex items-start gap-2">
            <textarea
              aria-label={`${nhan} — ý ${i + 1}`}
              rows={2}
              value={y}
              onChange={(e) => doiY(i, e.target.value)}
              aria-invalid={!!loi}
              // Lỗi nối tới TỪNG ô (mô tả của group không được đọc khi focus vào ô bên trong).
              aria-describedby={loi ? `${id}-loi` : undefined}
              // ponytail: `field-sizing: content` tự giãn theo chữ ở Chromium; Safari giữ 2 hàng và cuộn trong ô.
              className={`${O_CHUNG} resize-none leading-[1.55] [field-sizing:content]`}
            />
            <button
              type="button"
              aria-label={`Bỏ ý ${i + 1} của ${nhan}`}
              onClick={() => bo(i)}
              className="mt-2 cursor-pointer rounded-sm p-1 text-muted hover:text-fg"
            >
              <Icon name="trash" className="size-4" />
            </button>
          </li>
        ))}
      </ol>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          disabled={giaTri.length >= toiDa}
          onClick={them}
          className={`${NUT_HANG} cursor-pointer disabled:opacity-50`}
        >
          + Thêm ý
        </button>
        <span className="text-phu text-muted tabular-nums">
          {giaTri.length}/{toiDa} ý{tong ? ` · ${tong.gia}/${tong.toiDa} ký tự` : null}
          {kyTuMoiY && giaTri.some((y) => doDai(y.trim()) > kyTuMoiY)
            ? ` · có ý quá ${kyTuMoiY} ký tự`
            : null}
        </span>
      </div>
      {goiY && !loi ? (
        <p id={`${id}-goiy`} className="mt-1 text-phu leading-[1.45] text-muted-2">
          {goiY}
        </p>
      ) : null}
      {loi ? (
        <p
          id={`${id}-loi`}
          className="mt-1 text-phu leading-[1.45] font-medium text-badge-alert-fg"
        >
          {loi}
        </p>
      ) : null}
    </div>
  )
}
