/** Một mâu thuẫn: dòng tóm tắt, hai nguồn kèm đoạn trích, «Mở» tới tab sửa, «Không phải mâu thuẫn». */
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { NUT_HANG } from '@/components/ui/Bang'
import type { Conflict, ConflictSide } from './api'

const TAB_OF: Record<string, 'tai-lieu' | 'tong-quan' | 'phan-khu' | 'toa'> = {
  documents: 'tai-lieu',
  projects: 'tong-quan',
  zones: 'phan-khu',
  buildings: 'toa',
}

function where(side: ConflictSide): string {
  if (side.field) {
    const owner = side.entity === 'projects' ? 'của dự án' : ''
    return `Trường «${side.label}» ${owner}`.trim()
  }
  return `Tài liệu «${side.label}»`
}

/** Trích dẫn dài thì gọn còn hai dòng, bấm «Xem thêm» để mở hết. */
function Quote({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement>(null)
  const [open, setOpen] = useState(false)
  const [overflow, setOverflow] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (el) setOverflow(el.scrollHeight > el.clientHeight + 1)
  }, [text])
  return (
    <div className="col-span-2">
      <p ref={ref} className={`text-muted ${open ? '' : 'line-clamp-2'}`}>
        «{text}»
      </p>
      {(overflow || open) && (
        <button
          type="button"
          className="cursor-pointer text-phu font-medium text-ac hover:text-acd"
          onClick={() => setOpen(!open)}
        >
          {open ? 'Thu gọn' : 'Xem thêm'}
        </button>
      )}
    </div>
  )
}

function Source({ side, code, onOpen }: { side: ConflictSide; code: string; onOpen: () => void }) {
  const nav = useNavigate()
  const tab = TAB_OF[side.entity ?? ''] ?? 'tong-quan'
  return (
    <div className="mt-2 grid grid-cols-[1fr_auto] gap-x-3 text-than">
      <span className="text-phu font-medium text-fg">{where(side)}</span>
      <button
        type="button"
        className="cursor-pointer text-phu text-ac hover:text-acd"
        onClick={() => {
          onOpen()
          void nav({ to: '/pform', search: { code, tab } })
        }}
      >
        Mở
      </button>
      <Quote text={side.quote} />
    </div>
  )
}

export function ConflictItem({
  conflict,
  code,
  onDismiss,
  onOpen,
  dismissing,
}: {
  conflict: Conflict
  code: string
  onDismiss: (id: number) => void
  onOpen: () => void
  dismissing?: boolean
}) {
  return (
    <li className="border-t border-border py-3 first:border-t-0">
      <div className="flex items-center justify-between gap-4">
        <mark className="rounded-sm bg-badge-warn-bg px-1 text-than font-semibold text-badge-warn-fg">
          {conflict.summary}
        </mark>
        <button
          type="button"
          className={`${NUT_HANG} flex-none cursor-pointer whitespace-nowrap disabled:opacity-50`}
          disabled={dismissing}
          onClick={() => onDismiss(conflict.id)}
        >
          Không phải mâu thuẫn
        </button>
      </div>
      <Source side={conflict.left} code={code} onOpen={onOpen} />
      <Source side={conflict.right} code={code} onOpen={onOpen} />
    </li>
  )
}
