/**
 * Màn `/pform` — form dự án, khung 10 tab.
 *
 * `code` TỚI TỪ SEARCH PARAM, không phải path param: `tests/nav-registry.test.ts`
 * khoá thư mục `routes/_app` ở đúng 18 file .tsx, nên `/projects/$code` không
 * dựng được. `/pform?code=VHOP2` cho cùng thứ — deep-link được, back/forward
 * được, refresh được — mà không thêm file route.
 *
 * TAB CŨNG Ở SEARCH PARAM (`?tab=quy-can`; `can` là id cũ, còn sống làm alias),
 * không phải `useState`: xem docstring của
 * `routes/_app/pform.tsx`. Component này chỉ NHẬN tab và điều hướng khi đổi — URL
 * là nguồn sự thật duy nhất, nên không có trạng thái thứ hai để lệch.
 *
 * KHÔNG TAB NÀO BỊ KHOÁ (spec 2026-08-21 issue 1). Mười tab chia hai hạng:
 *   · Tổng quan · Vị trí · Ảnh 360 — đều là CỘT của hàng `projects`, và
 *     `POST /projects` nhận đủ cả 19 ô trong một request. Lúc tạo mới, cả ba tab
 *     mở CÙNG một form tạo (`TongQuanTab` ở chế độ `moi` gom luôn `region`/
 *     `address`/`link360`): đang tạo thì chỉ có MỘT bản ghi, chia nó ra ba lần
 *     lưu là mời người dùng mất phần đã gõ ở hai tab kia.
 *   · Bảy tab còn lại POST vào `/projects/{code}/…` nên thật sự cần dự án —
 *     chúng hiện một ô hỏi tên (`CongDatTen.tsx`) thay cho nội dung.
 *
 * Tiêu đề + hàng tab ở `KhungDuAn.tsx` — dùng chung với `/uform` để mở một căn
 * không làm mất ngữ cảnh dự án.
 */
import { useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { docDuAn, type DuAn } from '../api'
import { LoiApi } from '@/lib/http'
import { LoiTai } from '@/components/ui/TrangThai'
import { cauLoi } from '../thongDiep'
import { CAO_MAN, KHUNG_MAN, VUNG_TAB, NUT_PHU } from '@/components/ui/Bang'
import { KhungSuaProvider, useSaveStatus } from '../khungSua'
import { setEditing, useEditing } from '../editMode'
import { TinDuAn } from './TinDuAn'
import { DaiDangSua, DauDuAn } from './KhungDuAn'
import { ID_TAB_DU_AN, TAB_DU_AN, type TenTabDuAn } from '../tabDuAn'
import { CongDatTen } from './CongDatTen'
import { TongQuanTab } from './TongQuanTab'
import { ViTriTab } from './ViTriTab'
import { Anh360Tab } from './Anh360Tab'
import { MatBangTab } from './MatBangTab'
import { PhanKhuTab } from './PhanKhuTab'
import { ToaTab } from './ToaTab'
import { CanTab } from './CanTab'
import { TaiLieuTab } from './TaiLieuTab'
import { MediaTab } from './MediaTab'
import { TienDoTab } from './TienDoTab'
import { panelTab } from '@/components/ui/panelTab'

/** Tab nào là CỘT của hàng `projects` — lúc tạo mới chúng chung một form. */

export function DuAnForm({ code, tab }: { code?: string | undefined; tab: TenTabDuAn }) {
  const nav = useNavigate()

  const q = useQuery({
    queryKey: ['re', code],
    queryFn: () => docDuAn(code!),
    enabled: !!code,
  })

  const [loiStatus, setLoiStatus] = useState<unknown>(null)
  // Một cờ cho mọi tab và màn một căn của cùng dự án; mở khoá dự án A không mở khoá dự án B.
  const dangSua = useEditing(code)
  const doiSua = (v: boolean) => setEditing(v && code ? code : null)
  const saveStatus = useSaveStatus()

  if (code && q.isPending)
    return <p className="px-7 py-6 text-[14px] text-muted max-md:px-4 max-md:py-4">Đang tải…</p>

  if (code && q.error) {
    const mat = q.error instanceof LoiApi && q.error.code === 'PROJECT_NOT_FOUND'
    return mat ? (
      <div className="space-y-3 px-7 py-6 text-[14px] max-md:px-4 max-md:py-4">
        <p>Không có dự án nào mã {code} — có thể nó vừa bị xoá.</p>
        <Link to="/projects" className={NUT_PHU}>
          Về danh sách dự án
        </Link>
      </div>
    ) : (
      <div className="px-7 py-6 max-md:px-4 max-md:py-4">
        <LoiTai viec="dự án" thuLai={() => void q.refetch()} />
      </div>
    )
  }

  const duAn: DuAn | null = q.data ?? null

  const diToiTab = (id: TenTabDuAn) =>
    void nav({ to: '/pform', search: code ? { code, tab: id } : { tab: id }, replace: true })

  const doiTab = (id: TenTabDuAn) => {
    if (id !== tab) diToiTab(id)
  }

  /** Tạo xong thì Ở LẠI tab đang mở, ở chế độ sửa — người dùng vào tab đó là có việc ở đó. */
  const daTao = (ma: string) => {
    setEditing(ma)
    void nav({ to: '/pform', search: { code: ma, tab } })
  }
  const cong = (
    <CongDatTen nhanTab={TAB_DU_AN.find((t) => t.id === tab)?.nhan ?? 'Tab này'} daTao={daTao} />
  )

  return (
    <KhungSuaProvider value={{ duAn, dangSua, doiSua, ...saveStatus }}>
      <div className={KHUNG_MAN}>
        {/* Đầu trang đứng yên, chỉ vùng tab cuộn: nút Sửa/Xong luôn thấy. */}
        <div
          data-testid="pform-dinh"
          className="sticky top-0 z-20 -mx-7 flex-none border-b border-border bg-bg px-7 pt-6 pb-3 max-md:-mx-4 max-md:px-4"
        >
          <DauDuAn code={code} duAn={duAn} tab={tab} doiTab={doiTab} onLoiStatus={setLoiStatus} />
        </div>
        <DaiDangSua />

        {loiStatus != null && (
          <div
            className="mt-3 rounded-xl border border-badge-alert-fg/40 bg-badge-alert-bg p-3 text-[13px]"
            role="alert"
          >
            {cauLoi(loiStatus, 'đổi trạng thái')}
          </div>
        )}

        {/* Chỉ vùng NÀY cuộn (`VUNG_TAB`), cả trang thì không. Nhờ vậy hàng nút
            đáy và chân bảng ở cùng một độ cao trên cả mười tab — trước đó cả
            trang cuộn nên chúng nhảy mỗi lần đổi tab. */}
        <div className={VUNG_TAB} {...panelTab(ID_TAB_DU_AN, tab)}>
          {!code || !duAn ? (
            cong
          ) : (
            <>
              {tab === 'tong-quan' && <TongQuanTab key={duAn.projectCode} duAn={duAn} />}
              {tab === 'vi-tri' && (
                <ViTriTab key={duAn.projectCode} duAn={duAn} projectCode={code} />
              )}
              {tab === 'anh-360' && (
                <Anh360Tab key={duAn.projectCode} duAn={duAn} projectCode={code} />
              )}
              {tab === 'phan-khu' && <PhanKhuTab key={code} projectCode={code} />}
              {tab === 'toa' && <ToaTab key={code} projectCode={code} />}
              {tab === 'mat-bang' && <MatBangTab projectCode={code} />}
              {tab === 'quy-can' && <CanTab key={code} projectCode={code} />}
              {tab === 'media' && <MediaTab projectCode={code} />}
              {tab === 'tien-do' && <TienDoTab projectCode={code} />}
              {tab === 'tai-lieu' && <TaiLieuTab key={code} projectCode={code} cao={CAO_MAN} />}
            </>
          )}
        </div>
        {duAn && <TinDuAn duAn={duAn} />}
      </div>
    </KhungSuaProvider>
  )
}
