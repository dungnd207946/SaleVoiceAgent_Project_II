/**
 * Hộp thoại tạo workspace. Mở từ switcher ở chân sidebar.
 *
 * VÌ SAO LÀ DIALOG CHỨ KHÔNG PHẢI MỘT MÀN RIÊNG:
 * form có ĐÚNG một ô. Một màn full-page cho một ô nhập là bắt người dùng rời khỏi
 * chỗ họ đang làm, rồi tìm đường về. Điểm vào đã đúng chỗ rồi — mục + Tạo
 * workspace mới nằm ngay trong switcher, cạnh danh sách workspace hiện có.
 *
 * Nó cũng giữ FE khỏi phải khai một màn mới trong `lib/nav-registry.ts` +
 * `lib/screens.ts` — hai file đang được sửa bởi effort vai-trò-động.
 *
 * SỐ ĐO LẤY TỪ SWITCHER, không tự nghĩ: viền `border-border-field` bo 10px, chữ
 * 12.5px, nút dùng `NUT_CHINH`/`NUT_PHU` của `components/ui/Bang.tsx`. Dialog
 * bật lên giữa màn với shadow toả rộng hơn shadow của menu (28px) vì nó nằm
 * trên một lớp cao hơn. NHÃN Ô thì KHÔNG lấy từ switcher: nhãn nhóm của menu
 * (10px uppercase) là nhãn-nhóm-menu, còn đây là nhãn một Ô NHẬP — dùng đúng
 * khuôn nhãn form của portal (12.5px `text-muted`, `components/ui/Truong.tsx`);
 * bản đầu chép nhầm khuôn menu và lệch với mọi form khác (sửa 2026-08-21).
 */
import { useEffect, useId, useRef, useState } from 'react'
import { NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { O_CHUNG } from '@/components/ui/Truong'
import { useLang } from '@/i18n'
import { LoiApi } from '@/lib/http'
import { slugDuKien, taoWorkspace } from '../api'
import type { WorkspaceMoi } from '../api'

export function TaoWorkspaceDialog({
  onDong,
  onXong,
}: {
  onDong: () => void
  onXong: (ws: WorkspaceMoi) => Promise<void> | void
}) {
  const { t } = useLang()
  const [ten, setTen] = useState('')
  const [dangGui, setDangGui] = useState(false)
  const [loi, setLoi] = useState<string | null>(null)
  const oRef = useRef<HTMLInputElement>(null)
  const idTen = useId()
  const idLoi = useId()

  useEffect(() => {
    oRef.current?.focus()
  }, [])

  const tenSach = ten.trim()
  const slug = slugDuKien(tenSach)

  async function guiForm(e: React.FormEvent) {
    e.preventDefault()
    if (!tenSach || dangGui) return
    setLoi(null)
    setDangGui(true)
    try {
      const ws = await taoWorkspace(tenSach)
      await onXong(ws)
    } catch (err) {
      setLoi(
        err instanceof LoiApi
          ? err.message
          : err instanceof Error
            ? err.message
            : t({ vi: 'Không tạo được workspace', en: 'Could not create workspace' }),
      )
      setDangGui(false)
    }
  }

  return (
    <HopThoai
      onDong={onDong}
      aria-labelledby={`${idTen}-tieu-de`}
      className={`${KHUNG_HOP_THOAI} max-w-[420px]`}
    >
      <h2 id={`${idTen}-tieu-de`} className="text-[16.5px] font-semibold leading-tight text-fg">
        {t({ vi: 'Tạo workspace mới', en: 'Create new workspace' })}
      </h2>
      <p className="mt-1.5 text-[13px] leading-[1.55] text-muted">
        {t({
          vi: 'Workspace là một không gian dữ liệu riêng: dự án, tài liệu và agent của nó không thấy được từ workspace khác.',
          en: 'A workspace is an isolated data space: its projects, documents and agent are invisible from other workspaces.',
        })}
      </p>

      <form onSubmit={guiForm} className="mt-4">
        <label htmlFor={idTen} className="mb-1.5 block text-phu text-muted">
          {t({ vi: 'Tên workspace', en: 'Workspace name' })}
        </label>
        <input
          ref={oRef}
          id={idTen}
          value={ten}
          onChange={(e) => setTen(e.target.value)}
          maxLength={80}
          disabled={dangGui}
          aria-describedby={loi ? idLoi : undefined}
          placeholder={t({ vi: 'Sàn Đông Nam', en: 'South East Sales' })}
          className={O_CHUNG}
        />

        <p className="mt-2 flex items-baseline gap-1.5 text-[12px] text-muted-2">
          <span>{t({ vi: 'Mã dự kiến', en: 'Expected code' })}</span>
          <span className="font-mono text-phu text-nav">{tenSach ? slug : '—'}</span>
        </p>

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
          <button type="submit" disabled={!tenSach || dangGui} className={NUT_CHINH}>
            {dangGui
              ? t({ vi: 'Đang tạo…', en: 'Creating…' })
              : t({ vi: 'Tạo workspace', en: 'Create workspace' })}
          </button>
        </div>
      </form>
    </HopThoai>
  )
}
