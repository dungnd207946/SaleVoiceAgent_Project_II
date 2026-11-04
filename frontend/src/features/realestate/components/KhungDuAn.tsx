/**
 * Khung chung của hai màn thuộc một dự án — `/pform` và `/uform`.
 *
 * VÌ SAO CHUNG: `/uform` (một căn) là màn RIÊNG chỉ vì
 * `tests/nav-registry.test.ts` khoá thư mục route ở đúng 18 file, không phải vì
 * nó là một ngữ cảnh khác. Với người dùng, một căn nằm TRONG dự án — nên hàng
 * tab và tiêu đề dự án phải còn đó, y như lúc mở một phân khu. Bản trước
 * `/uform` tự dựng header riêng và hàng tab biến mất, làm người dùng tưởng mình
 * đã rời khỏi dự án.
 *
 * Danh sách chín tab và phép làm sạch `?tab=` ở `../tabDuAn.ts` — file route cần
 * chúng lúc `validateSearch`, trước khi render bất cứ gì.
 */
import { Link, useNavigate } from '@tanstack/react-router'
import { Children, Fragment, type ReactNode } from 'react'
import { DUONG_VE, NUT_CHINH, NhomTab, type MucTab } from '@/components/ui/Bang'
import { gioPhut } from '@/lib/dinhDang'
import { ID_TAB_DU_AN, TAB_DU_AN, type TenTabDuAn } from '../tabDuAn'
import { LOAI_HINH, nhanCua } from '../enums'
import { useKhungSua } from '../khungSua'
import { useKbStatus } from '../useKbStatus'
import { StatusChip } from './StatusChip'
import { KbBadge } from './KbBadge'
import { Chip, SalePhaseChip } from './SaleChip'
import { ProjectConflictButton } from '@/features/conflicts/contracts'
import type { DuAn } from '../api'
export function DuongDan({ children }: { children: ReactNode }) {
  const muc = Children.toArray(children)
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
      {muc.map((m, i) => (
        <Fragment key={i}>
          {i > 0 && (
            <span aria-hidden className="text-[13px] text-muted-3">
              ›
            </span>
          )}
          {m}
        </Fragment>
      ))}
    </div>
  )
}

interface Props {
  code?: string | undefined
  duAn?: DuAn | null | undefined
  tab: TenTabDuAn
  doiTab: (id: TenTabDuAn) => void
  onLoiStatus?: ((e: unknown) => void) | undefined
  /** Hiện nút Sửa/Xong; màn tạo căn mới thì không. */
  editToggle?: boolean | undefined
}

/** Đầu trang dự án: tên, mã, chip, chip trạng thái; hàng tab và nút Sửa/Xong. */
export function DauDuAn({ code, duAn, tab, doiTab, onLoiStatus, editToggle = true }: Props) {
  // Không tab nào bị khoá (spec 2026-08-21 issue 1). Sáu tab cần dự án đã tồn
  // tại thì tự hỏi tên tại chỗ — xem `CongDatTen.tsx`.
  const muc: MucTab<TenTabDuAn>[] = TAB_DU_AN.map((t) => ({ ...t }))
  const { dangSua, doiSua, saving, savedAt } = useKhungSua()
  const kb = useKbStatus()
  const tt = code ? kb.byCode[code] : undefined

  return (
    <div>
      <DuongDan>
        <Link to="/projects" className={DUONG_VE}>
          Kiến thức
        </Link>
        <span className="text-than font-medium text-muted">Dự án</span>
      </DuongDan>
      <div className="mt-2 flex items-start justify-between gap-4 max-md:flex-col max-md:gap-2">
        <div className="min-w-0">
          <h2 className="text-trang leading-tight font-semibold text-fg">
            {duAn?.name || (code ? <span className="font-mono">{code}</span> : 'Dự án mới')}
          </h2>
          {code && (
            <div className="mt-1.5 flex flex-wrap items-center gap-2">
              <span className="font-mono text-[12px] text-muted-2">{code}</span>
              {duAn && <SalePhaseChip value={duAn.salePhase} />}
              {duAn?.category.map((c) => (
                <Chip key={c}>{nhanCua(LOAI_HINH, c)}</Chip>
              ))}
            </div>
          )}
        </div>
        {code && duAn?.status && (
          <div className="flex flex-none items-center gap-3">
            {tt && (tt.indexing || tt.hasError) && <KbBadge tt={tt} />}
            <ProjectConflictButton code={code} name={duAn.name || code} />
            <StatusChip projectCode={code} status={duAn.status} onLoi={onLoiStatus ?? (() => {})} />
          </div>
        )}
      </div>
      <div className="mt-4 flex items-center justify-between gap-3 max-md:flex-col max-md:items-stretch">
        <div className="min-w-0 flex-1 overflow-x-auto max-md:w-full [&_[role=tab]]:whitespace-nowrap">
          <NhomTab muc={muc} dangMo={tab} doi={doiTab} idPanel={ID_TAB_DU_AN} />
        </div>
        {code && duAn && (
          <div className="flex flex-none items-center justify-end gap-3">
            {dangSua && (
              <span className="text-phu text-muted-2" role="status">
                {saving ? 'Đang lưu…' : savedAt ? `Đã lưu lúc ${gioPhut(savedAt)}` : ''}
              </span>
            )}
            {editToggle && (
              <button type="button" className={NUT_CHINH} onClick={() => doiSua(!dangSua)}>
                {dangSua ? 'Xong' : 'Sửa'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/** Dải báo đang sửa, ngay dưới đầu trang. */
export function DaiDangSua() {
  const { dangSua, duAn } = useKhungSua()
  if (!dangSua || !duAn) return null
  return (
    <p
      data-testid="dai-dang-sua"
      className="-mx-7 flex-none border-b border-ac/20 bg-acs px-7 py-2 text-than text-acd max-md:-mx-4 max-md:px-4"
    >
      Đang sửa dự án. Mỗi ô tự lưu khi rời ô, áp dụng cho mọi tab và màn chi tiết; bấm Xong để về
      chế độ xem.
    </p>
  )
}

export function VeLai({ nhan, ve }: { nhan: string; ve: () => void }) {
  return (
    <button type="button" onClick={ve} className={DUONG_VE}>
      ‹ {nhan}
    </button>
  )
}

export function LinkVe({ code, tab, nhan }: { code: string; tab: TenTabDuAn; nhan: string }) {
  const nav = useNavigate()
  return (
    <button
      type="button"
      onClick={() => void nav({ to: '/pform', search: { code, tab } })}
      className={DUONG_VE}
    >
      {nhan}
    </button>
  )
}
