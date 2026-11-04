/**
 * Hộp thoại tạo bộ giá mới — ba ô `code`/`name`/`currency` đúng body
 * `useTaoBoGia()` (`../api`) nhận, tối thiểu vì `POST /admin/billing/
 * price-versions` chỉ cần đúng ba trường này để tạo một hàng RỖNG (chưa có
 * dòng giá nào) — nhập dòng giá là việc của Task 9.
 *
 * Khung là `HopThoai` + `KHUNG_HOP_THOAI` (`components/ui`) — dùng chung với
 * `features/platform/components/TaoKhoaDialog.tsx`, không còn là bản chép.
 *
 * `currency` là `<select>` mang class `o-chon` (luật 6 Design token, cổng
 * `tests/o-chon.test.ts`) — KHÔNG phải ô nhập tự do: giá trị này đi thẳng vào
 * body gửi lên, gõ sai ba ký tự ISO 4217 là một bộ giá không tiền tệ nào đối
 * chiếu được về sau.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'

const O_NHAP =
  'w-full rounded-md border border-border-strong px-3 py-2.5 text-than outline-none focus:border-ac'

/** Hai đơn vị tiền tệ đã thấy trong dữ liệu thật của module (fake + hợp đồng BE §0). */
const TIEN_TE = ['VND', 'USD'] as const

export function TaoBoGiaDialog({
  dangGui,
  loi,
  onDong,
  onTao,
}: {
  readonly dangGui: boolean
  /** Thông điệp lỗi từ lần gửi trước. Dialog KHÔNG tự đóng khi lỗi. */
  readonly loi: string | null
  readonly onDong: () => void
  readonly onTao: (b: { code: string; name: string; currency: string }) => void
}) {
  const [code, setCode] = useState('')
  const [name, setName] = useState('')
  const [currency, setCurrency] = useState<string>(TIEN_TE[0])
  const oCodeRef = useRef<HTMLInputElement>(null)
  const idTieuDe = useId()
  const idCode = useId()
  const idName = useId()
  const idCurrency = useId()
  const idLoi = useId()

  useEffect(() => {
    oCodeRef.current?.focus()
  }, [])

  const hopLe = code.trim() !== '' && name.trim() !== ''

  function guiForm(e: React.FormEvent) {
    e.preventDefault()
    if (dangGui || !hopLe) return
    onTao({ code: code.trim(), name: name.trim(), currency })
  }

  return (
    <HopThoai
      onDong={onDong}
      khoaDong={dangGui}
      aria-labelledby={idTieuDe}
      className={`${KHUNG_HOP_THOAI} max-w-[420px]`}
    >
      <h2 id={idTieuDe} className="text-muc font-semibold leading-tight text-fg">
        Bộ giá mới
      </h2>

      <form onSubmit={guiForm} className="mt-4 flex flex-col gap-3.5">
        <div>
          <label
            htmlFor={idCode}
            className="block pb-1.5 text-nhan font-semibold uppercase tracking-[0.08em] text-muted-3"
          >
            Mã (code)
          </label>
          <input
            ref={oCodeRef}
            id={idCode}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            disabled={dangGui}
            placeholder="vd: vn-2026-q4"
            className={`${O_NHAP} font-mono`}
          />
        </div>

        <div>
          <label
            htmlFor={idName}
            className="block pb-1.5 text-nhan font-semibold uppercase tracking-[0.08em] text-muted-3"
          >
            Tên
          </label>
          <input
            id={idName}
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={dangGui}
            placeholder="vd: Bảng giá VND quý 4/2026"
            className={O_NHAP}
          />
        </div>

        <div>
          <label
            htmlFor={idCurrency}
            className="block pb-1.5 text-nhan font-semibold uppercase tracking-[0.08em] text-muted-3"
          >
            Tiền tệ
          </label>
          <select
            id={idCurrency}
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            disabled={dangGui}
            className={`${O_NHAP} o-chon`}
          >
            {TIEN_TE.map((tt) => (
              <option key={tt} value={tt}>
                {tt}
              </option>
            ))}
          </select>
        </div>

        {loi && (
          <p
            id={idLoi}
            role="alert"
            className="rounded-lg bg-badge-alert-bg px-3 py-2 text-phu leading-[1.5] text-badge-alert-fg"
          >
            {loi}
          </p>
        )}

        <div className={`${HANG_NUT} mt-1.5`}>
          <button type="button" onClick={onDong} disabled={dangGui} className={NUT_PHU}>
            Huỷ
          </button>
          <button type="submit" disabled={dangGui || !hopLe} className={NUT_CHINH}>
            {dangGui ? 'Đang tạo…' : 'Tạo bộ giá'}
          </button>
        </div>
      </form>
    </HopThoai>
  )
}
