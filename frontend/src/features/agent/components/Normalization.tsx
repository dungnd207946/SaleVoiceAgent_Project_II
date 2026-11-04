/**
 * Khu «Chuẩn hoá cách đọc» — preview 3 dòng, mở dialog để xem/sửa đầy đủ.
 *
 * Đặt NGAY TRÊN khối Rào chắn ở CẢ HAI phía (form sửa và bản tóm tắt): hai bên bắt buộc
 * khai cùng các khu theo cùng thứ tự, nếu không thì bấm «Sửa cấu hình» là ô nhảy chỗ.
 *
 * Trạng thái rỗng phải nói về BỘ NỀN mà không bày nó ra. «Chưa có mục nào» một mình làm
 * người dùng kết luận agent đang đọc `Vietcombank` theo mặt chữ — sai, và họ sẽ đi nhập
 * lại 44 mục đã có sẵn.
 */
import { useState } from 'react'
import type { NormalizationEntry } from '../api'
import { The } from './form'
import { NUT_PHU } from './lop'
import { NormalizationDialog } from './NormalizationDialog'

const SO_DONG_PREVIEW = 3

export function NormalizationPreview({
  muc,
  doi,
}: {
  muc: NormalizationEntry[]
  doi?: ((m: NormalizationEntry[]) => void) | undefined
}) {
  const [mo, setMo] = useState(false)
  const dau = muc.slice(0, SO_DONG_PREVIEW)
  const con = muc.length - dau.length

  return (
    <The
      icon="voice"
      tieuDe="Chuẩn hoá cách đọc"
      phu="Dạy agent đọc đúng mã dự án, tên thương hiệu và từ địa phương của workspace này."
    >
      {muc.length === 0 ? (
        <p className="text-than text-muted">
          Chưa có mục nào. Agent đang dùng bộ mặc định của nền tảng.
        </p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {dau.map((m) => (
            <li key={m.term} className="flex flex-wrap items-baseline gap-2 text-than">
              <span className="font-mono">{m.term}</span>
              <span className="text-muted-2">→</span>
              <span className="text-muted">{m.read_as}</span>
            </li>
          ))}
        </ul>
      )}
      {con > 0 && <p className="mt-2 text-phu text-muted-2">còn {con} mục nữa</p>}

      <button type="button" onClick={() => setMo(true)} className={`${NUT_PHU} mt-4`}>
        Xem tất cả ({muc.length})
      </button>

      {mo && <NormalizationDialog muc={muc} doi={doi} onDong={() => setMo(false)} />}
    </The>
  )
}
