/**
 * Bảng đầy đủ của từ điển cách đọc TTS.
 *
 * DIALOG NÀY KHÔNG LƯU. Nó sửa bản nháp trong bộ nhớ qua `doi`; bản nháp chỉ ra khách khi
 * bấm «Lưu và áp dụng» ở ngoài.
 *
 * KHÔNG CÓ NÚT ĐÓNG (người dùng chốt 2026-08-24): nút duy nhất là «Thêm». Đóng bằng Esc
 * hoặc bấm ra ngoài. Một nút «Lưu» ở đây sẽ nói dối, còn «Xong» thì bị đọc thành đã lưu —
 * bỏ cả hai là cách duy nhất không hứa gì. Nút «Thêm» mang mark `save` (đĩa mềm, người
 * dùng chốt 2026-08-25) nhưng nhãn/aria-label vẫn là «Thêm» — nó chỉ ghi vào bản nháp.
 *
 * `doi` vắng mặt = chỉ-đọc (dùng ở bản tóm tắt).
 */
import { useId, useState } from 'react'
import {
  NORMALIZATION_READ_AS_TOI_DA,
  NORMALIZATION_SO_MUC_TOI_DA,
  NORMALIZATION_TERM_TOI_DA,
  type NormalizationEntry,
} from '../api'
import { NutIcon } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { O_LOP } from './lop'

export function NormalizationDialog({
  muc,
  doi,
  onDong,
}: {
  muc: NormalizationEntry[]
  doi?: ((m: NormalizationEntry[]) => void) | undefined
  onDong: () => void
}) {
  const id = useId()
  const [term, setTerm] = useState('')
  const [readAs, setReadAs] = useState('')
  const [loi, setLoi] = useState('')

  /** Enter trong hai ô = bấm Thêm.
   *
   * Phải tự bắt: nút Thêm là `NutIcon`, tức `type="button"`, nên form không còn nút submit
   * nào và trình duyệt KHÔNG kích hoạt submit ngầm. Bản đầu tin là có — test bắt được. */
  function enter(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter') {
      e.preventDefault()
      them()
    }
  }

  function them(e?: React.FormEvent) {
    e?.preventDefault()
    if (!doi) return
    const t = term.trim()
    const r = readAs.trim()
    if (t === '' || r === '') return setLoi('Điền cả hai ô.')
    if (t === r) return setLoi('Hai ô giống nhau — mục này không làm gì.')
    if (muc.length >= NORMALIZATION_SO_MUC_TOI_DA)
      return setLoi(`Tối đa ${NORMALIZATION_SO_MUC_TOI_DA} mục.`)
    // So không phân biệt hoa/thường, khớp đúng phép validate của backend.
    if (muc.some((m) => m.term.toLowerCase() === t.toLowerCase()))
      return setLoi('Đã có mục này trong bảng.')
    doi([...muc, { term: t, read_as: r }])
    setTerm('')
    setReadAs('')
    setLoi('')
  }

  return (
    <HopThoai
      onDong={onDong}
      aria-labelledby={`${id}-tieu-de`}
      className={`${KHUNG_HOP_THOAI} flex max-h-[80dvh] max-w-[620px] flex-col`}
    >
      <h2 id={`${id}-tieu-de`} className="text-[16.5px] font-semibold leading-tight text-fg">
        Chuẩn hoá cách đọc
      </h2>
      <div className="mt-4 min-h-0 flex-1 overflow-y-auto rounded-lg border border-border">
        <table className="w-full text-than">
          <thead className="sticky top-0 bg-fill-strong text-left text-phu text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">Từ hoặc mã</th>
              <th className="px-3 py-2 font-medium">Đọc thành</th>
              {doi && <th className="w-16 px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {muc.length === 0 && (
              <tr>
                <td colSpan={doi ? 3 : 2} className="px-3 py-4 text-muted">
                  Chưa có mục nào.
                </td>
              </tr>
            )}
            {muc.map((m, i) => (
              <tr key={m.term} className="border-t border-rule">
                <td className="px-3 py-2 font-mono">{m.term}</td>
                <td className="px-3 py-2">{m.read_as}</td>
                {doi && (
                  <td className="px-3 py-2 text-right">
                    <NutIcon
                      icon="trash"
                      nhan={`Xoá ${m.term}`}
                      phaHuy
                      onClick={() => doi(muc.filter((_, j) => j !== i))}
                    />
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {doi && (
        /* Ô nhập phải `block`: inline-block trong label để lại khe descender dưới ô, đáy
         * label thấp hơn đáy ô ~4px và `items-end` căn nút theo đáy label — nút tụt xuống. */
        <form onSubmit={them} className="mt-3 flex flex-wrap items-end gap-2">
          <label className="flex-1 text-phu text-muted">
            Từ hoặc mã
            <input
              value={term}
              onChange={(e) => setTerm(e.target.value)}
              onKeyDown={enter}
              maxLength={NORMALIZATION_TERM_TOI_DA}
              placeholder="VD: NCLB"
              className={`${O_LOP} mt-1 block`}
            />
          </label>
          <label className="flex-[2] text-phu text-muted">
            Đọc thành
            <input
              value={readAs}
              onChange={(e) => setReadAs(e.target.value)}
              onKeyDown={enter}
              maxLength={NORMALIZATION_READ_AS_TOI_DA}
              placeholder="VD: Noble Crystal Long Biên"
              className={`${O_LOP} mt-1 block`}
            />
          </label>
          <NutIcon icon="save" nhan="Thêm" onClick={() => them()} />
        </form>
      )}
      {loi !== '' && <p className="mt-2 text-phu text-badge-alert-fg">{loi}</p>}
    </HopThoai>
  )
}
