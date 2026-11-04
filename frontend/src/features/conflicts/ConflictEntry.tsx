/** Hai điểm gắn của tính năng: màn Kiến thức (`DuAnList`) và đầu màn dự án (`KhungDuAn`). */
import { useState } from 'react'
import { ConflictButton } from './ConflictButton'
import { ConflictDialog } from './ConflictDialog'
import { useSummary } from './useSummary'
import { useConflictWatch } from './useConflictWatch'

export function WorkspaceConflictButton() {
  const s = useSummary()
  const [open, setOpen] = useState(false)
  const rows = s.data ?? []
  return (
    <>
      <ConflictButton
        size="toolbar"
        count={rows.reduce((n, r) => n + r.open, 0)}
        checking={rows.some((r) => r.checking)}
        onClick={() => setOpen(true)}
      />
      {open && <ConflictDialog mode={{ kind: 'workspace' }} onClose={() => setOpen(false)} />}
    </>
  )
}

export function ProjectConflictButton({ code, name }: { code: string; name: string }) {
  const s = useSummary()
  const watch = useConflictWatch(code)
  const [open, setOpen] = useState(false)
  const row = s.data?.find((r) => r.projectCode === code)
  return (
    <>
      <ConflictButton
        size="chip"
        count={row?.open ?? 0}
        checking={watch.checking || Boolean(row?.checking)}
        onClick={() => setOpen(true)}
      />
      {open && (
        <ConflictDialog mode={{ kind: 'project', code, name }} onClose={() => setOpen(false)} />
      )}
      {!open && watch.fresh.length > 0 && (
        <ConflictDialog
          mode={{ kind: 'afterSave', code, conflicts: watch.fresh }}
          onClose={watch.clear}
        />
      )}
    </>
  )
}
