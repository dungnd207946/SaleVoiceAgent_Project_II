/**
 * Màn «Dữ liệu ngoài» (`/du-lieu-ngoai`) — năm tab:
 * Tổng quan (kèm nhật ký chạy) · Nguồn · Chủ đề · Lịch chạy · Hồ sơ dự án. Tab đang mở nằm ở search param
 * (`?tab=`) để F5/link giữ đúng chỗ. KHÔNG có `<h1>` ở đây — Topbar render từ nhãn nav.
 */
import { useNavigate, useSearch } from '@tanstack/react-router'
import { NhomTab, type MucTab } from '@/components/ui/Bang'
import { useSession } from '@/lib/session'
import { ACTIONS } from '@/lib/actions'
import { TabChuDe } from './TabChuDe'
import { TabDuAn } from './TabDuAn'
import { TabLich } from './TabLich'
import { TabNguon } from './TabNguon'
import { TabTongQuan } from './TabTongQuan'

export type TabDuLieuNgoai = 'tong-quan' | 'nguon' | 'chu-de' | 'lich' | 'du-an'

const TAB: readonly MucTab<TabDuLieuNgoai>[] = [
  { id: 'tong-quan', nhan: 'Tổng quan' },
  { id: 'nguon', nhan: 'Nguồn' },
  { id: 'chu-de', nhan: 'Chủ đề' },
  { id: 'lich', nhan: 'Lịch chạy' },
  { id: 'du-an', nhan: 'Hồ sơ dự án' },
]

export function DuLieuNgoaiScreen() {
  const { tab, duAn } = useSearch({ from: '/_app/du-lieu-ngoai' })
  const navigate = useNavigate({ from: '/du-lieu-ngoai' })
  const dangMo: TabDuLieuNgoai = tab ?? 'tong-quan'
  const doi = (t: TabDuLieuNgoai) => void navigate({ search: { tab: t } })
  const { session } = useSession()
  const suaDuoc = session?.actions.includes(ACTIONS.KB_WEB_WRITE) ?? false

  // Màn chặn chiều cao (khuôn `DuAnList`): tab có bảng phân trang lấp phần còn lại và chỉ thân bảng cuộn,
  // nên thanh phân trang đứng yên ở đáy; tab còn lại cuộn cả vùng nội dung.
  const bangCao = dangMo === 'du-an' || dangMo === 'tong-quan' || dangMo === 'chu-de'
  return (
    <div className="flex h-[calc(100dvh-72px)] flex-col gap-5 overflow-hidden px-7 py-6 max-md:h-[calc(100dvh-56px)] max-md:px-4 max-md:py-4">
      <div className="flex-none">
        <NhomTab muc={TAB} dangMo={dangMo} doi={doi} nhan="Dữ liệu ngoài" />
      </div>
      <div className={bangCao ? 'flex min-h-0 flex-1 flex-col' : 'min-h-0 flex-1 overflow-y-auto'}>
        {dangMo === 'tong-quan' && <TabTongQuan />}
        {dangMo === 'nguon' && <TabNguon suaDuoc={suaDuoc} />}
        {dangMo === 'chu-de' && <TabChuDe suaDuoc={suaDuoc} />}
        {dangMo === 'lich' && <TabLich suaDuoc={suaDuoc} />}
        {dangMo === 'du-an' && <TabDuAn suaDuoc={suaDuoc} moSan={duAn} />}
      </div>
    </div>
  )
}
