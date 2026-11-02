/**
 * Popup mâu thuẫn dùng chung, ba cách mở (spec 2026-10-14 §7):
 * - `workspace`: icon ở màn Kiến thức — ba nhóm: có mâu thuẫn, chưa kiểm tra, không mâu thuẫn;
 * - `project`: icon ở màn dự án;
 * - `afterSave`: tự bật ở màn dự án khi có cảnh báo mới (sau khi lưu, hoặc do người khác/cổng nạp).
 */
import { useId, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { NUT_CHINH, NUT_PHU } from '@/components/ui/Bang'
import { XacNhan } from '@/components/ui/XacNhan'
import {
  dismissConflict,
  projectConflicts,
  scanAll,
  scanProject,
  type Conflict,
  type ConflictSummary,
} from './api'
import { CheckingChip } from './ConflictButton'
import { ConflictItem } from './ConflictItem'
import { SUMMARY_KEY, projectKey } from './keys'
import { checkedTime } from './time'
import { useReloadWhenDone, useSummary } from './useSummary'

export type ConflictDialogMode =
  | { kind: 'workspace' }
  | { kind: 'project'; code: string; name: string }
  | { kind: 'afterSave'; code: string; conflicts: Conflict[] }

function useDismiss(onDone?: (id: number) => void) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: dismissConflict,
    onSuccess: (_, id) => {
      onDone?.(id)
      void qc.invalidateQueries({ queryKey: ['conflicts'] })
    },
  })
}

function useScanProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: scanProject,
    onSuccess: () => void qc.invalidateQueries({ queryKey: SUMMARY_KEY }),
  })
}

function ConflictList({
  code,
  items,
  onClose,
}: {
  code: string
  items: Conflict[]
  onClose: () => void
}) {
  const dismiss = useDismiss()
  return (
    <ul>
      {items.map((c) => (
        <ConflictItem
          key={c.id}
          conflict={c}
          code={code}
          onOpen={onClose}
          onDismiss={(id) => dismiss.mutate(id)}
          dismissing={dismiss.isPending && dismiss.variables === c.id}
        />
      ))}
    </ul>
  )
}

const NUT_KIEM_HANG =
  'rounded-sm border border-ac px-2 py-1 text-phu font-medium text-ac hover:bg-acs'

function ScanAction({
  code,
  checking,
  large = false,
}: {
  code: string
  checking: boolean
  large?: boolean
}) {
  const scan = useScanProject()
  if (checking || scan.isPending) return <CheckingChip />
  return (
    <button
      type="button"
      className={`flex-none cursor-pointer ${large ? NUT_CHINH : NUT_KIEM_HANG}`}
      onClick={() => scan.mutate(code)}
    >
      Kiểm tra
    </button>
  )
}

function FailedNote() {
  return <span className="text-phu text-badge-alert-fg">Lần kiểm tra trước bị lỗi</span>
}

function ProjectGroup({ row, onClose }: { row: ConflictSummary; onClose: () => void }) {
  const [open, setOpen] = useState(false)
  const list = useQuery({
    queryKey: projectKey(row.projectCode),
    queryFn: () => projectConflicts(row.projectCode),
    enabled: open,
  })
  useReloadWhenDone(row.projectCode, row.checking)
  return (
    <div className="border-t border-border first:border-t-0">
      <div className="flex items-center gap-3">
        <button
          type="button"
          aria-expanded={open}
          className="flex flex-1 cursor-pointer items-center gap-2 py-3 text-left"
          onClick={() => setOpen(!open)}
        >
          <Chevron open={open} />
          <span className="text-than font-semibold text-fg">{row.name || row.projectCode}</span>
          <span className="text-phu text-badge-warn-fg">{row.open} mâu thuẫn</span>
          {row.failed && !row.checking && <FailedNote />}
        </button>
        <ScanAction code={row.projectCode} checking={row.checking} />
      </div>
      {open && (
        <div className="pb-2 pl-5">
          {list.isPending ? (
            <p className="py-2 text-phu text-muted">Đang tải…</p>
          ) : (
            <ConflictList code={row.projectCode} items={list.data ?? []} onClose={onClose} />
          )}
        </div>
      )}
    </div>
  )
}

function PlainRow({ row, note }: { row: ConflictSummary; note: ReactNode }) {
  return (
    <div className="flex items-center gap-3 border-t border-border py-2 first:border-t-0">
      <span className="text-than text-fg">{row.name || row.projectCode}</span>
      <span className="flex-1">{note}</span>
      <ScanAction code={row.projectCode} checking={row.checking} />
    </div>
  )
}

function Chevron({ open }: { open: boolean }) {
  return (
    <span aria-hidden className={`text-muted-2 transition-transform ${open ? 'rotate-90' : ''}`}>
      ›
    </span>
  )
}

function Section({
  title,
  count,
  defaultOpen,
  children,
}: {
  title: string
  count: number
  defaultOpen: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="border-t border-border first:border-t-0">
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center gap-2 py-3 text-left"
        onClick={() => setOpen(!open)}
      >
        <Chevron open={open} />
        <span className="text-than font-semibold text-fg">{title}</span>
        <span className="text-phu text-muted-2">{count}</span>
      </button>
      {open && <div className="pb-2 pl-5">{children}</div>}
    </section>
  )
}

/** Có mâu thuẫn → chưa kiểm tra (gồm lượt gần nhất hỏng) → không mâu thuẫn. */
function groupRows(rows: ConflictSummary[]) {
  const withConflicts = rows.filter((r) => r.open > 0)
  const unchecked = rows.filter((r) => r.open === 0 && (!r.checkedAt || r.failed))
  const clean = rows.filter((r) => r.open === 0 && r.checkedAt && !r.failed)
  return { withConflicts, unchecked, clean }
}

function WorkspaceBody({ titleId, onClose }: { titleId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const summary = useSummary()
  const [confirm, setConfirm] = useState(false)
  const all = useMutation({
    mutationFn: scanAll,
    onSuccess: () => {
      setConfirm(false)
      void qc.invalidateQueries({ queryKey: SUMMARY_KEY })
    },
  })
  const rows = summary.data ?? []
  const total = rows.reduce((n, r) => n + r.open, 0)
  const g = groupRows(rows)
  return (
    <>
      <Header id={titleId} title="Mâu thuẫn dữ liệu" count={total}>
        <button
          type="button"
          className={`${NUT_CHINH} cursor-pointer`}
          onClick={() => setConfirm(true)}
        >
          Kiểm tra tất cả dự án
        </button>
      </Header>
      <div className="max-h-[60vh] overflow-y-auto">
        {summary.isPending ? (
          <p className="py-3 text-than text-muted">Đang tải…</p>
        ) : rows.length === 0 ? (
          <p className="py-3 text-than text-muted">Chưa có dự án nào.</p>
        ) : (
          <>
            <Section title="Có mâu thuẫn" count={g.withConflicts.length} defaultOpen>
              {g.withConflicts.length === 0 ? (
                <p className="py-2 text-phu text-muted">Không có dự án nào.</p>
              ) : (
                g.withConflicts.map((r) => (
                  <ProjectGroup key={r.projectCode} row={r} onClose={onClose} />
                ))
              )}
            </Section>
            {g.unchecked.length > 0 && (
              <Section title="Chưa kiểm tra" count={g.unchecked.length} defaultOpen={false}>
                {g.unchecked.map((r) => (
                  <PlainRow
                    key={r.projectCode}
                    row={r}
                    note={r.failed && !r.checking ? <FailedNote /> : null}
                  />
                ))}
              </Section>
            )}
            {g.clean.length > 0 && (
              <Section title="Không mâu thuẫn" count={g.clean.length} defaultOpen={false}>
                {g.clean.map((r) => (
                  <PlainRow
                    key={r.projectCode}
                    row={r}
                    note={
                      <span className="text-phu text-muted-2">
                        Kiểm tra lần cuối {checkedTime(r.checkedAt!)}
                      </span>
                    }
                  />
                ))}
              </Section>
            )}
          </>
        )}
      </div>
      {confirm && (
        <XacNhan
          tieuDe="Kiểm tra mâu thuẫn của mọi dự án?"
          nutChinh="Kiểm tra"
          dangGui={all.isPending}
          onDongY={() => all.mutate()}
          onHuy={() => setConfirm(false)}
        >
          Lần đầu có thể mất vài phút. Kết quả hiện dần trong danh sách này.
        </XacNhan>
      )}
    </>
  )
}

function LastCheck({ row, open }: { row: ConflictSummary | undefined; open: number }) {
  if (!row?.checkedAt) return <>Chưa kiểm tra lần nào</>
  const at = checkedTime(row.checkedAt)
  if (row.failed) return <span className="text-badge-alert-fg">Lần kiểm tra lúc {at} bị lỗi</span>
  return (
    <>
      Kiểm tra lần cuối {at} · {open > 0 ? `${open} mâu thuẫn` : 'Không có mâu thuẫn'}
    </>
  )
}

function ProjectBody({
  titleId,
  code,
  name,
  onClose,
}: {
  titleId: string
  code: string
  name: string
  onClose: () => void
}) {
  const list = useQuery({ queryKey: projectKey(code), queryFn: () => projectConflicts(code) })
  const summary = useSummary()
  const row = summary.data?.find((r) => r.projectCode === code)
  useReloadWhenDone(code, Boolean(row?.checking))
  const items = list.data ?? []
  return (
    <>
      <Header
        id={titleId}
        title={`Mâu thuẫn · ${name}`}
        count={items.length}
        sub={
          summary.isPending ? null : (
            <LastCheck row={row} open={list.data?.length ?? row?.open ?? 0} />
          )
        }
      >
        <ScanAction code={code} checking={Boolean(row?.checking)} large />
      </Header>
      <div className="max-h-[60vh] overflow-y-auto">
        {list.isPending ? (
          <p className="py-3 text-than text-muted">Đang tải…</p>
        ) : items.length === 0 ? (
          <p className="py-3 text-than text-muted">Không có mâu thuẫn.</p>
        ) : (
          <ConflictList code={code} items={items} onClose={onClose} />
        )}
      </div>
    </>
  )
}

function AfterSaveBody({
  titleId,
  code,
  conflicts,
  onClose,
}: {
  titleId: string
  code: string
  conflicts: Conflict[]
  onClose: () => void
}) {
  const [items, setItems] = useState(conflicts)
  const dismiss = useDismiss((id) => setItems((xs) => xs.filter((x) => x.id !== id)))
  return (
    <>
      <Header id={titleId} title={`Có ${items.length} mâu thuẫn mới`} />
      <ul className="max-h-[60vh] overflow-y-auto">
        {items.map((c) => (
          <ConflictItem
            key={c.id}
            conflict={c}
            code={code}
            onOpen={onClose}
            onDismiss={(id) => dismiss.mutate(id)}
            dismissing={dismiss.isPending && dismiss.variables === c.id}
          />
        ))}
      </ul>
    </>
  )
}

function Header({
  id,
  title,
  count,
  sub,
  children,
}: {
  id: string
  title: string
  count?: number
  sub?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="mb-2 flex items-center justify-between gap-3 border-b border-border pb-3">
      <div className="min-w-0">
        <h2 id={id} className="text-muc leading-tight font-semibold text-fg">
          {title}
          {count !== undefined && count > 0 && (
            <span className="ml-2 text-than font-normal text-muted">{count}</span>
          )}
        </h2>
        {sub && <p className="mt-1 text-phu text-muted-2">{sub}</p>}
      </div>
      <div className="flex items-center gap-3">{children}</div>
    </div>
  )
}

export function ConflictDialog({
  mode,
  onClose,
}: {
  mode: ConflictDialogMode
  onClose: () => void
}) {
  const id = useId()
  return (
    <HopThoai onDong={onClose} aria-labelledby={id} className={`${KHUNG_HOP_THOAI} max-w-[700px]`}>
      {mode.kind === 'workspace' && <WorkspaceBody titleId={id} onClose={onClose} />}
      {mode.kind === 'project' && (
        <ProjectBody titleId={id} code={mode.code} name={mode.name} onClose={onClose} />
      )}
      {mode.kind === 'afterSave' && (
        <AfterSaveBody titleId={id} code={mode.code} conflicts={mode.conflicts} onClose={onClose} />
      )}
      <div className="mt-3 flex justify-end border-t border-border pt-3">
        <button type="button" className={`${NUT_PHU} cursor-pointer`} onClick={onClose}>
          {mode.kind === 'afterSave' ? 'Để sau' : 'Đóng'}
        </button>
      </div>
    </HopThoai>
  )
}
