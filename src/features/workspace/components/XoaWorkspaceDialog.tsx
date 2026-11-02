/**
 * Hộp thoại xác nhận xoá workspace.
 *
 * GÕ LẠI MÃ WORKSPACE ĐỂ MỞ KHOÁ NÚT — không phải một `confirm` một-cú-bấm.
 *
 * Đây là hành động phá huỷ duy nhất trong portal mà một cú bấm nhầm không có
 * đường lùi nào — và nghĩa là ĐÚNG NGHĨA ĐÓ: backend xoá cứng ngay trong request,
 * 31 bảng đi theo cascade, cộng collection Qdrant và toàn bộ tệp. Không kỳ chờ,
 * không thùng rác, ops cũng không phục hồi được. Bắt gõ lại mã buộc người dùng
 * ĐỌC xem họ đang ở workspace nào — và đó chính là lỗi thật cần chặn, vì switcher
 * cho phép đứng ở workspace này mà tưởng mình đang ở workspace kia.
 *
 * GÕ MÃ (`ws_anphu`) CHỨ KHÔNG GÕ TÊN («An Phú Land»): tên đổi được, và người
 * dùng vừa có thể đổi nó ở ngay thẻ phía trên. Mã thì bất biến — nó là thứ duy
 * nhất trên màn này chỉ đúng một workspace, mãi mãi.
 *
 * Số đo lấy từ `TaoWorkspaceDialog` — hai dialog cùng lớp phủ thì phải cùng bề
 * rộng, cùng bo góc, cùng bóng đổ; lệch nhau là hai hộp thoại trông như của hai
 * ứng dụng.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { CAO_O, HANG_NUT, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { useLang } from '@/i18n'
import type { Workspace } from '@/lib/session'
import { LoiApi } from '@/lib/http'
import { xoaWorkspace } from '../api'

const O_MA =
  'w-full rounded-md border border-border-field px-3 py-2.5 font-mono text-than outline-none focus:border-ac'
const NUT_XOA = `${CAO_O} inline-flex items-center justify-center rounded-md bg-badge-alert-fg px-[15px] text-than font-semibold text-white disabled:opacity-50`

export function XoaWorkspaceDialog({
  workspace,
  onDong,
  onXong,
}: {
  readonly workspace: Workspace
  readonly onDong: () => void
  /** Gọi SAU khi backend trả 204. Người gọi lo rời màn và nạp lại phiên. */
  readonly onXong: () => Promise<void> | void
}) {
  const { t } = useLang()
  const [ma, setMa] = useState('')
  const [dangXoa, setDangXoa] = useState(false)
  const [loi, setLoi] = useState<string | null>(null)
  const oRef = useRef<HTMLInputElement>(null)
  const id = useId()

  useEffect(() => {
    oRef.current?.focus()
  }, [])

  // So sánh CHÍNH XÁC, không `trim()` và không bỏ qua hoa/thường. Mã workspace
  // luôn là chữ thường không dấu (`^[a-z][a-z0-9_]{1,30}$`), nên "gõ gần đúng"
  // ở đây nghĩa là chưa đọc kỹ — và đọc kỹ chính là việc mà ô này tồn tại để bắt.
  const khop = ma === workspace.id

  async function guiForm(e: React.FormEvent) {
    e.preventDefault()
    if (!khop || dangXoa) return
    setLoi(null)
    setDangXoa(true)
    try {
      await xoaWorkspace(workspace.id)
      // KHÔNG `setDangXoa(false)` ở nhánh này — cùng bẫy `TaoWorkspaceDialog` đã
      // mắc: `onXong` điều hướng và nạp lại phiên, nên nút phải ở nguyên «Đang
      // xoá…» cho tới lúc dialog bị gỡ khỏi cây.
      await onXong()
    } catch (err) {
      // Dialog KHÔNG đóng khi lỗi. 409 «workspace cuối cùng» là câu người dùng
      // phải đọc được; đóng dialog là nuốt nó và để họ bấm lại lần nữa.
      setLoi(
        err instanceof LoiApi
          ? err.message
          : err instanceof Error
            ? err.message
            : t({ vi: 'Không xoá được workspace', en: 'Could not delete the workspace' }),
      )
      setDangXoa(false)
    }
  }

  return (
    <HopThoai
      onDong={onDong}
      aria-labelledby={`${id}-tieu-de`}
      className={`${KHUNG_HOP_THOAI} max-w-[420px]`}
    >
      <h2 id={`${id}-tieu-de`} className="text-[16.5px] font-semibold leading-tight text-fg">
        {t({ vi: 'Xoá workspace này?', en: 'Delete this workspace?' })}
      </h2>
      <p className="mt-1.5 text-[13px] leading-[1.55] text-muted">
        {t({
          vi: 'Không thể hoàn tác. Dự án, tài liệu, hội thoại và cấu hình agent của workspace này sẽ bị xoá, và mọi thành viên mất quyền truy cập ngay.',
          en: 'This cannot be undone. Projects, documents, conversations and agent configuration will be wiped, and every member loses access immediately.',
        })}
      </p>

      <form onSubmit={guiForm} className="mt-4">
        <label htmlFor={`${id}-ma`} className="block pb-1.5 text-phu leading-[1.5] text-nav">
          {t({ vi: 'Nhập mã workspace để xác nhận:', en: 'Type the workspace ID to confirm:' })}{' '}
          <span className="font-mono font-semibold text-fg">{workspace.id}</span>
        </label>
        <input
          ref={oRef}
          id={`${id}-ma`}
          value={ma}
          onChange={(e) => setMa(e.target.value)}
          disabled={dangXoa}
          autoComplete="off"
          spellCheck={false}
          aria-describedby={loi ? `${id}-loi` : undefined}
          className={O_MA}
        />

        {loi && (
          <p
            id={`${id}-loi`}
            role="alert"
            className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] text-badge-alert-fg"
          >
            {loi}
          </p>
        )}

        <div className={`${HANG_NUT} mt-5`}>
          <button type="button" onClick={onDong} disabled={dangXoa} className={NUT_PHU}>
            {t({ vi: 'Huỷ', en: 'Cancel' })}
          </button>
          <button type="submit" disabled={!khop || dangXoa} className={NUT_XOA}>
            {dangXoa
              ? t({ vi: 'Đang xoá…', en: 'Deleting…' })
              : t({ vi: 'Xoá vĩnh viễn', en: 'Delete permanently' })}
          </button>
        </div>
      </form>
    </HopThoai>
  )
}
