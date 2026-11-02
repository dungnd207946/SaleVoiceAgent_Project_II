import { NGHIA_BAC, NHAN_BAC, laBacLead, nhanDoiTuong, type BacLead } from '../lead'

/**
 * Chip bậc phễu. CHỈ NHÃN (người dùng chốt 2026-09-30, bỏ chấm phễu) — nhãn tự nói bậc,
 * màu ấm dần củng cố. Mỗi chuỗi lớp mang `border` CÙNG token viền của nó: cổng
 * `vien-tran` đòi màu viền nằm trong cùng chuỗi, và viết trọn lớp ở đây để Tailwind
 * quét thấy (ghép `bg-lead-${n}` động thì lớp bị cắt khỏi bundle).
 */
const LOP: Record<BacLead, string> = {
  lead: 'border border-lead-1-vien bg-lead-1-bg text-lead-1-fg',
  mql: 'border border-lead-2-vien bg-lead-2-bg text-lead-2-fg',
  sql: 'border border-lead-3-vien bg-lead-3-bg text-lead-3-fg',
  hen_gap: 'border border-lead-4-vien bg-lead-4-bg text-lead-4-fg',
}

const LOP_LA = 'border border-border-strong bg-badge-neutral-bg text-badge-neutral-fg'

export function ChipStage({ stage }: { stage: string }) {
  const bac = laBacLead(stage)
  return (
    <span
      data-stage={stage}
      title={bac ? `${NHAN_BAC[stage]} — ${NGHIA_BAC[stage]}` : undefined}
      className={`inline-flex h-[22px] items-center whitespace-nowrap rounded-full px-[9px] text-[11.5px] font-semibold ${bac ? LOP[stage] : LOP_LA}`}
    >
      {bac ? NHAN_BAC[stage] : stage}
    </span>
  )
}

/** «90 điểm» — số thô, không thang (người dùng chốt: điểm chạy 30–120, không gắn với bậc). */
export function DiemLead({ diem }: { diem: number }) {
  return (
    <span className="font-mono text-phu tabular-nums text-fg">
      {diem}
      <span className="ml-[3px] font-sans text-[11.5px] text-muted-2">điểm</span>
    </span>
  )
}

/** Ô lead ở hàng khách: chip trên, «điểm · đối tượng» dưới. Phần nào NULL thì bỏ phần đó. */
export function TomTatLead({
  stage,
  diem,
  doiTuong,
}: {
  stage: string | null | undefined
  diem: number | null | undefined
  doiTuong: string | null | undefined
}) {
  if (!stage) return <span className="block text-[12px] text-muted-2">Chưa phân loại</span>
  const coDiem = diem !== null && diem !== undefined
  return (
    <>
      <span className="block">
        <ChipStage stage={stage} />
      </span>
      {(coDiem || doiTuong) && (
        <span className="mt-1.5 flex items-baseline gap-1.5 text-[12px] text-muted">
          {coDiem && <DiemLead diem={diem} />}
          {doiTuong && (
            <span>{coDiem ? `· ${nhanDoiTuong(doiTuong)}` : nhanDoiTuong(doiTuong)}</span>
          )}
        </span>
      )}
    </>
  )
}
