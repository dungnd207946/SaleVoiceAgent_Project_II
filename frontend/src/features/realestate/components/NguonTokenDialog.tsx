/**
 * HAI hộp thoại của token đẩy dữ liệu — tạo và xoá.
 *
 * KHÔNG có hộp thoại «xem lại»: token hiện TẠI CHỖ trong bảng, che sẵn, bấm con
 * mắt là mở (`OToken.tsx`). Người dùng chốt 2026-08-14 — một dialog chỉ để bày
 * một chuỗi bắt trả một cú bấm và một lần mất ngữ cảnh mà không mua được gì.
 *
 * Số đo và class lấy từ `features/platform/components/TaoKhoaDialog.tsx`: hai bộ
 * dialog này phải trông như nhau. **Chép chứ không import** — luật ranh giới
 * module (`tests/module-boundaries.test.ts`) cấm `features/realestate` chạm ruột
 * `features/platform`, và đó là luật đúng: hai module không được dính nhau chỉ vì
 * chung một cái viền. Ngày cả hai bộ hội đủ lý do dùng chung thì đường đi là kéo
 * chúng ra `components/ui/`, như `Bang.tsx` đã đi.
 */
import { useEffect, useId, useRef, useState } from 'react'
import { HANG_NUT, NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { O_CHUNG } from '@/components/ui/Truong'
import type { Token } from '../nguon'

export const DAI_NHAN_TOI_DA = 60

function Vo({
  moTa,
  dong,
  khoaDong = false,
  children,
}: {
  readonly moTa: string
  readonly dong: () => void
  readonly khoaDong?: boolean | undefined
  readonly children: React.ReactNode
}) {
  return (
    <HopThoai
      onDong={dong}
      khoaDong={khoaDong}
      aria-label={moTa}
      className={`${KHUNG_HOP_THOAI} max-w-[460px]`}
    >
      {children}
    </HopThoai>
  )
}

function KhoiLoi({ loi, id }: { readonly loi: string; readonly id: string }) {
  return (
    <p
      id={id}
      role="alert"
      className="mt-3 rounded-lg bg-badge-alert-bg px-3 py-2 text-[13px] leading-[1.5] text-badge-alert-fg"
    >
      {loi}
    </p>
  )
}

// ─── Tạo ────────────────────────────────────────────────────────────────────

export function TaoTokenDialog({
  dangGui,
  loi,
  onDong,
  onTao,
}: {
  readonly dangGui: boolean
  readonly loi: string | null
  readonly onDong: () => void
  readonly onTao: (label: string) => void
}) {
  const [nhan, setNhan] = useState('')
  const oRef = useRef<HTMLInputElement>(null)
  const idNhan = useId()
  const idLoi = useId()

  useEffect(() => {
    oRef.current?.focus()
  }, [])

  function gui(e: React.FormEvent) {
    e.preventDefault()
    if (dangGui || nhan.trim() === '') return
    onTao(nhan.trim())
  }

  return (
    <Vo moTa="Tạo token đẩy dữ liệu" dong={onDong} khoaDong={dangGui}>
      <h2 className="text-[16.5px] font-semibold leading-tight text-fg">Tạo token đẩy dữ liệu</h2>

      <form onSubmit={gui} className="mt-4">
        <label htmlFor={idNhan} className="mb-1.5 block text-phu text-muted">
          Nhãn
        </label>
        <input
          ref={oRef}
          id={idNhan}
          value={nhan}
          onChange={(e) => setNhan(e.target.value)}
          maxLength={DAI_NHAN_TOI_DA}
          disabled={dangGui}
          aria-describedby={loi ? idLoi : undefined}
          placeholder="VD: ERP Anphu — job đẩy quỹ căn"
          className={O_CHUNG}
        />
        {loi && <KhoiLoi loi={loi} id={idLoi} />}

        <div className={`${HANG_NUT} mt-5`}>
          <button type="button" onClick={onDong} disabled={dangGui} className={NUT_PHU}>
            Huỷ
          </button>
          <button type="submit" disabled={dangGui || nhan.trim() === ''} className={NUT_CHINH}>
            {dangGui ? 'Đang tạo…' : 'Tạo'}
          </button>
        </div>
      </form>
    </Vo>
  )
}

// ─── Xoá ────────────────────────────────────────────────────────────────────

export function XoaTokenDialog({
  token,
  dangGui,
  loi,
  onDong,
  onXoa,
}: {
  readonly token: Token
  readonly dangGui: boolean
  readonly loi: string | null
  readonly onDong: () => void
  readonly onXoa: () => void
}) {
  const idLoi = useId()

  return (
    <Vo moTa="Xoá token đẩy dữ liệu" dong={onDong} khoaDong={dangGui}>
      <h2 className="text-[16.5px] font-semibold leading-tight text-fg">Xoá {token.label}?</h2>

      {loi && <KhoiLoi loi={loi} id={idLoi} />}

      <div className={`${HANG_NUT} mt-5`}>
        <button type="button" onClick={onDong} disabled={dangGui} className={NUT_PHU}>
          Huỷ
        </button>
        <button type="button" onClick={onXoa} disabled={dangGui} className={NUT_CHINH}>
          {dangGui ? 'Đang xoá…' : 'Xoá'}
        </button>
      </div>
    </Vo>
  )
}
