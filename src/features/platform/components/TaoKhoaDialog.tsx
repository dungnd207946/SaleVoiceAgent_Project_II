/**
 * Hộp thoại đặt nhãn cho khoá mới.
 *
 * VÌ SAO CÓ BƯỚC NÀY thay vì bấm một nút là ra khoá ngay: ba khoá không nhãn chỉ
 * khác nhau ở 12 ký tự ngẫu nhiên của tiền tố, và lúc cần thu hồi đúng một cái
 * thì không ai biết cái nào là của pod nào. Cột `agent_keys.label` đã có trong DB
 * từ migration 0900 — bước này chỉ là cho nó một đường vào.
 *
 * Nhãn BẮT BUỘC (đổi 2026-08-07): panel Thử agent ở màn API Keys chọn khoá theo
 * tên — một khoá không tên là một dòng «—» trong dropdown, không chọn nổi. Lý
 * lẽ cũ (đừng chặn khoá dùng một lần để thử) hết đứng: giờ chính việc THỬ cần
 * cái tên.
 *
 * Số đo và class lấy từ `features/workspace/components/TaoWorkspaceDialog.tsx` —
 * hai dialog này phải trông như nhau, và đó là lý do file kia được chép chứ không
 * được "tham khảo".
 */
import { useEffect, useId, useRef, useState } from 'react'
import { NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { O_CHUNG } from '@/components/ui/Truong'
import { useLang } from '@/i18n'

/** Khớp `Field(max_length=60)` của `TaoKhoaIn` — quá 60 backend trả 422. */
export const DAI_NHAN_TOI_DA = 60

export function TaoKhoaDialog({
  dangGui,
  loi,
  onDong,
  onTao,
}: {
  dangGui: boolean
  /** Thông điệp lỗi từ lần gửi trước. Dialog KHÔNG tự đóng khi lỗi. */
  loi: string | null
  onDong: () => void
  onTao: (label: string) => void
}) {
  const { t } = useLang()
  const [nhan, setNhan] = useState('')
  const oRef = useRef<HTMLInputElement>(null)
  const idNhan = useId()
  const idLoi = useId()

  useEffect(() => {
    oRef.current?.focus()
  }, [])

  function guiForm(e: React.FormEvent) {
    e.preventDefault()
    if (dangGui) return
    if (nhan.trim() === '') return
    onTao(nhan.trim())
  }

  return (
    // Esc + bấm nền đóng được — khác `KhoaMoiDialog`. Ở đây chưa có bí mật nào để mất.
    <HopThoai
      onDong={onDong}
      khoaDong={dangGui}
      aria-labelledby={`${idNhan}-tieu-de`}
      className={`${KHUNG_HOP_THOAI} max-w-[420px]`}
    >
      <h2 id={`${idNhan}-tieu-de`} className="text-[16.5px] font-semibold leading-tight text-fg">
        {t({ vi: 'Tạo khoá đấu nối mới', en: 'Create connection key' })}
      </h2>
      <p className="mt-1.5 text-[13px] leading-[1.55] text-muted">
        {t({
          vi: 'Khoá sẽ hiện đúng một lần sau khi tạo.',
          en: 'The key lets an agent pod authenticate with this workspace. It will be shown exactly once after creation.',
        })}
      </p>

      <form onSubmit={guiForm} className="mt-4">
        <label htmlFor={idNhan} className="mb-1.5 block text-phu text-muted">
          {t({ vi: 'Nhãn', en: 'Label' })}
        </label>
        <input
          ref={oRef}
          id={idNhan}
          value={nhan}
          onChange={(e) => setNhan(e.target.value)}
          maxLength={DAI_NHAN_TOI_DA}
          disabled={dangGui}
          aria-describedby={loi ? idLoi : undefined}
          placeholder={t({ vi: 'Nhập tên của khoá', en: 'Enter key name' })}
          className={O_CHUNG}
        />
        {/* <p className="mt-2 text-[12px] text-muted-2">
            {t({
              vi: 'Để nhận ra khoá nào là của pod nào — và để chọn khoá khi thử agent.',
              en: 'So you can tell keys apart when revoking — and pick one when trying the agent.',
            })}
          </p> */}

        {loi && (
          <p
            id={idLoi}
            role="alert"
            className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] text-badge-alert-fg"
          >
            {loi}
          </p>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button type="button" onClick={onDong} disabled={dangGui} className={NUT_PHU}>
            {t({ vi: 'Huỷ', en: 'Cancel' })}
          </button>
          <button type="submit" disabled={dangGui || nhan.trim() === ''} className={NUT_CHINH}>
            {dangGui
              ? t({ vi: 'Đang tạo…', en: 'Creating…' })
              : t({ vi: 'Tạo khoá', en: 'Create key' })}
          </button>
        </div>
      </form>
    </HopThoai>
  )
}
