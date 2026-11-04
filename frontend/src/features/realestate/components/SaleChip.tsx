/** Chip giai đoạn bán (dự án, phân khu, toà) và trạng thái bán (căn) — chỉ đọc. */
import type { ReactNode } from 'react'
import { SALE_PHASE, SALE_STATUS, nhanCua } from '../enums'

const TONE = {
  ok: 'bg-acs text-acd',
  warn: 'bg-badge-warn-bg text-badge-warn-fg',
  neutral: 'bg-badge-neutral-bg text-badge-neutral-fg',
}

export function Chip({
  tone = 'neutral',
  children,
}: {
  tone?: keyof typeof TONE
  children: ReactNode
}) {
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-phu font-medium whitespace-nowrap ${TONE[tone]}`}
    >
      {children}
    </span>
  )
}

export function SalePhaseChip({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-3">—</span>
  const tone = value === 'dang_ban' ? 'ok' : value === 'sap_mo_ban' ? 'warn' : 'neutral'
  return <Chip tone={tone}>{nhanCua(SALE_PHASE, value)}</Chip>
}

export function SaleStatusChip({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-3">—</span>
  const tone = value === 'available' ? 'ok' : value === 'booked' ? 'warn' : 'neutral'
  return <Chip tone={tone}>{nhanCua(SALE_STATUS, value)}</Chip>
}
