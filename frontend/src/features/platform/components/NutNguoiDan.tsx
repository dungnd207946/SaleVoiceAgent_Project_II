/**
 * Nút «Người dẫn» nổi trên sân khấu tab Voice.
 *
 * Nút là ANH EM của `SanKhauAgent` (không phải con): sân khấu `aria-hidden` và nhận cử
 * chỉ kéo album — đặt nút bên trong là giấu nó khỏi trình đọc màn hình và để cú kéo nuốt
 * mất cú bấm. Chỉ có khi lip sync bật (`VITE_AVATAR_WS_URL`): người dẫn Kling cũ không đổi
 * nhân vật được.
 */
import { useState, type ReactNode } from 'react'
import { Icon } from '@/components/icons'
import { urlAvatar } from '../avatarLipSync'
import { useNguoiDanDangDung } from '../nhanVat'
import { NguoiDanDialog } from './NguoiDanDialog'

/** Bọc sân khấu: thêm nút «Người dẫn» ở góc trên trái (khi lip sync bật). */
export function KhungNguoiDan({ children }: { children: ReactNode }) {
  const [mo, setMo] = useState(false)
  const nv = useNguoiDanDangDung()
  if (!urlAvatar()) return <>{children}</>
  return (
    <div className="relative flex min-h-0 flex-col lg:flex-1">
      {children}
      <button
        type="button"
        onClick={() => setMo(true)}
        className="absolute left-3 top-3 z-20 inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-surface/90 px-2.5 py-1.5 text-phu font-medium text-fg shadow-menu backdrop-blur hover:bg-surface"
      >
        <Icon name="agent" className="size-4" />
        <span className="max-w-[160px] truncate">{nv?.ten ?? 'Người dẫn mặc định'}</span>
        <Icon name="caret" className="size-3.5 text-muted" />
      </button>
      {mo && <NguoiDanDialog onDong={() => setMo(false)} />}
    </div>
  )
}
