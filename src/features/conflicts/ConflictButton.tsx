/** Nút icon mâu thuẫn: số cảnh báo đang mở, viền nhấp nháy khi đang kiểm tra, tooltip khi rê chuột. */
import { useId } from 'react'
import { CAO_O } from '@/components/ui/Bang'
import { Icon } from '@/components/icons'

const SIZE = {
  toolbar: `${CAO_O} w-9 max-md:w-10 rounded-md`,
  chip: 'mb-1 h-[22px] w-[26px] rounded-md',
} as const

function hint(count: number, checking: boolean): string {
  if (checking) return 'Đang kiểm tra dữ liệu…'
  if (count > 0) return `Có ${count} chỗ tài liệu và thông tin đã điền ghi khác nhau. Bấm để xem.`
  return 'Kiểm tra chỗ tài liệu và thông tin đã điền ghi khác nhau.'
}

export function ConflictButton({
  count,
  checking,
  size,
  onClick,
}: {
  count: number
  checking: boolean
  size: keyof typeof SIZE
  onClick: () => void
}) {
  const tipId = useId()
  const label = checking ? 'Mâu thuẫn dữ liệu — đang kiểm tra' : `Mâu thuẫn dữ liệu: ${count}`
  return (
    <span className="group relative inline-flex flex-none">
      <button
        type="button"
        aria-label={label}
        aria-describedby={tipId}
        onClick={onClick}
        className={`relative inline-flex cursor-pointer items-center justify-center border border-border-field bg-surface text-nav hover:border-fg ${SIZE[size]} ${checking ? 'vien-kiem' : ''}`}
      >
        <Icon name="mauThuan" className={size === 'chip' ? 'size-3.5' : 'size-[17px]'} />
        {!checking && count > 0 ? (
          <span className="absolute -top-2 -right-2 min-w-[18px] rounded-full border-2 border-surface bg-badge-warn-fg px-1 text-center font-mono text-nhan leading-[14px] text-white">
            {count}
          </span>
        ) : null}
      </button>
      <span
        id={tipId}
        role="tooltip"
        className="pointer-events-none invisible absolute top-full right-0 z-50 mt-2 w-[240px] rounded-md bg-fg px-2.5 py-1.5 text-phu leading-snug text-surface opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 group-has-[:focus-visible]:visible group-has-[:focus-visible]:opacity-100"
      >
        <span className="block font-semibold">Mâu thuẫn dữ liệu</span>
        {hint(count, checking)}
      </span>
    </span>
  )
}

/** Đứng vào chỗ nút «Kiểm tra» của popup trong lúc dự án đang được kiểm tra. */
export function CheckingChip() {
  return (
    <span
      role="status"
      className="inline-flex flex-none items-center gap-1.5 rounded-full bg-acs px-2.5 py-0.5 text-phu font-medium whitespace-nowrap text-acd"
    >
      <span aria-hidden className="cham-kiem size-1.5 rounded-full bg-ac" />
      Đang kiểm tra
    </span>
  )
}
