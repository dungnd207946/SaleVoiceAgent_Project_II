/**
 * Ô hiện một token đẩy dữ liệu — che sẵn, con mắt mở tại chỗ, nút copy bên cạnh.
 *
 * THAY CHO MỘT HỘP THOẠI (người dùng chốt 2026-08-14). Bản trước phải bấm mở
 * dialog để đọc chuỗi; mở tại chỗ bỏ được một cú bấm và một lần mất ngữ cảnh, và
 * chuỗi hiện ra đúng chỗ mắt đang nhìn.
 *
 * ── BA QUYẾT ĐỊNH NHỎ, MỖI CÁI MỘT LÝ DO ───────────────────────────────────
 *
 * ① **Che bằng số chấm CỐ ĐỊNH, không theo độ dài token thật.** Số chấm chạy theo
 *    độ dài là rò một phần bí mật: nhìn hai ô là biết hai token khác cỡ nhau, và
 *    với một định dạng token có tiền tố cố định thì độ dài nói khá nhiều.
 *
 * ② **Copy KHÔNG cần mở.** Việc thường làm là dán chuỗi sang chỗ khác chứ không
 *    phải đọc nó bằng mắt — bắt mở ra trước là bắt phơi bí mật lên màn hình cho
 *    một việc không cần nhìn. (Cũng vì thế nút copy đứng ngoài, không nằm trong
 *    ô bị che.)
 *
 * ③ **Chuỗi hiện ra là `<span>`, không phải `<input readOnly>`.** Ô nhập kéo
 *    theo trình quản lý mật khẩu nhảy vào, và `readOnly` vẫn trông như thứ gõ
 *    được. Đây là dữ liệu để đọc, không phải một trường của form.
 */
import { useState } from 'react'
import { NutIcon } from '@/components/ui/Bang'
import { useSaoChep } from '@/lib/saoChep'

const SO_CHAM = 40
const CHE = '•'.repeat(SO_CHAM)
const O =
  'flex min-w-0 flex-1 items-center rounded-md border border-border-field bg-surface px-3 py-2 font-mono text-phu leading-[1.5]'

export function OToken({ token, nhan }: { readonly token: string; readonly nhan: string }) {
  const [hien, setHien] = useState(false)
  const { daCopy, loiCopy, copy } = useSaoChep()

  return (
    <>
      <div className="flex items-center gap-1.5">
        <div className={O}>
          <span className={`min-w-0 truncate ${hien ? 'text-fg' : 'text-muted-2'}`}>
            {hien ? token : CHE}
          </span>
        </div>
        <NutIcon
          icon={hien ? 'cheBiMat' : 'hienBiMat'}
          nhan={hien ? `Che token ${nhan}` : `Hiện token ${nhan}`}
          onClick={() => setHien((v) => !v)}
        />
        <NutIcon
          icon={daCopy ? 'check' : 'copy'}
          nhan={daCopy ? 'Đã copy' : `Copy token ${nhan}`}
          onClick={() => void copy(token)}
        />
      </div>
      {loiCopy && (
        <p role="alert" className="mt-1 text-[12px] text-badge-alert-fg">
          Trình duyệt không cho copy tự động — bấm con mắt rồi bôi đen chuỗi.
        </p>
      )}
    </>
  )
}
