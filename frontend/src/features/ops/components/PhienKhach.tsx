/** Màn chi tiết một khách: header + cột phiên + transcript (spec §5.2). Chỉ xem. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { Icon } from '@/components/icons'
import { DUONG_VE, NhomTab } from '@/components/ui/Bang'
import { ChipKenh } from '@/components/ui/ChipKenh'
import { Sao } from '@/components/ui/Sao'
import { useKhoManHinh } from '@/lib/khoManHinh'
// Mặt tiền công khai của `features/quality` — KHÔNG import `@/features/quality/api`
// trực tiếp, cổng ranh giới module (`tests/module-boundaries.test.ts`) chỉ cho
// import qua `contracts.ts` giữa hai feature khác nhau.
import { feedbackCuaPhien } from '@/features/quality/contracts'
import { type Phien, PHONE_TRONG, chiTietPhien, phienCuaKhach } from '../api'
import { mauCua, noiDungAvatar } from '../avatar'
import { ngayGio, thoiLuong } from '../thoiGian'
import { nhanDoiTuong } from '../lead'
import { ChanDungKhach } from './ChanDungKhach'
import { ChipStage, DiemLead } from './ChipStage'
import { Transcript } from './Transcript'
import { panelTab } from '@/components/ui/panelTab'

type TabNguon = 'tat-ca' | 'chat' | 'voice'

const TABS: { ma: TabNguon; nhan: string }[] = [
  { ma: 'tat-ca', nhan: 'Tất cả' },
  { ma: 'chat', nhan: 'Chat' },
  { ma: 'voice', nhan: 'Voice' },
]

/** `null`/giá trị lạ CHỈ hiện ở tab "Tất cả" — không suy đoán hộ kênh chưa biết. */
function locTheoNguon(items: readonly Phien[], tab: TabNguon): readonly Phien[] {
  if (tab === 'chat') return items.filter((p) => p.source === 'chat')
  if (tab === 'voice') return items.filter((p) => p.source === 'voice')
  return items
}

/**
 * Tấm nền CAO CỐ ĐỊNH = phần còn lại của cửa sổ (cùng số với `HopThuSale`:
 * 120px = Topbar `h-[72px]` + `py-6` trên/dưới), để hai cột CUỘN RIÊNG.
 *
 * Trước 2026-09-24 cả màn cuộn chung một thanh ở `<main>`: đọc hết một phiên
 * dài mà khách còn nhiều phiên thì cột trái vẫn kéo dài xuống bên dưới đoạn
 * hội thoại, trang dài mãi; ngược lại một khách 40 phiên đẩy transcript ngắn
 * lên đầu rồi để một khoảng trắng dài bên phải. Giờ header khách · hàng tab
 * kênh · dòng thông tin phiên đứng yên, chỉ DANH SÁCH PHIÊN và NỘI DUNG PHIÊN
 * cuộn — mỗi cái một thanh (`min-h-0` ở mọi tầng flex là bắt buộc: thiếu một
 * tầng thì con cao theo nội dung và `overflow-y-auto` không bao giờ bật).
 *
 * Mobile: 88px = topbar 56px + `py-4` trên/dưới (32px).
 */
const CAO_KHUNG = 'h-[calc(100vh-120px)] max-md:h-[calc(100dvh-88px)]'

/** Tấm nền đủ ba cột: danh sách 300 + hội thoại ≥ 520 + chân dung 300. */
const RONG_BA_COT = 1120

export function PhienKhach({
  phone,
  phienMoDau,
  luotMoDau,
}: {
  phone: string
  phienMoDau?: string
  luotMoDau?: number
}) {
  const an = phone === PHONE_TRONG
  const ds = useQuery({ queryKey: ['convos', 'phien', phone], queryFn: () => phienCuaKhach(phone) })
  const [tab, setTab] = useState<TabNguon>('tat-ca')
  const [chon, setChon] = useState<string | null>(phienMoDau ?? null)
  const kho = useKhoManHinh()
  const mobile = kho === 'mobile'
  /**
   * Chân dung khách là cột thứ ba khi TẤM NỀN đủ rộng; không đủ thì nút «i» (Thông tin khách)
   * ở header cho nó THAY vùng nội dung, «‹ Hội thoại» trả về.
   *
   * Đo bề rộng tấm nền, KHÔNG dùng tầng `desktop` (≥1024): thanh nav 240px gập/mở
   * được nên cùng một cửa sổ cho hai bề rộng khác nhau — ở 1024px với nav mở, ba
   * cột chừa cho đoạn hội thoại chưa tới 100px. jsdom đo ra 0 ⇒ rơi về luật tầng.
   */
  const khung = useRef<HTMLDivElement>(null)
  const [rongKhung, setRongKhung] = useState(0)
  const coCotChanDung = rongKhung > 0 ? rongKhung >= RONG_BA_COT : kho === 'desktop'
  const [xemChanDung, setXemChanDung] = useState(false)
  /**
   * Mobile: một cột một lúc (spec §6.3). State RIÊNG, không suy từ `chon`: `sid`
   * luôn rơi về phiên đầu khi chưa chọn, nên suy từ đó thì mobile luôn nhảy
   * thẳng vào transcript. Mở link có `phienMoDau` là ý muốn xem phiên đó ⇒ true.
   * Nằm NGOÀI nhánh mobile/desktop: xoay máy giữa chừng không mất phiên đang xem.
   */
  const [dangXemPhien, setDangXemPhien] = useState(phienMoDau !== undefined)
  const hienDs = !mobile || (!dangXemPhien && !xemChanDung)
  const hienCt = !mobile || dangXemPhien || xemChanDung
  const chanDungThayNoiDung = !coCotChanDung && xemChanDung && !an
  // Đổi tab mà `chon` không còn thuộc danh sách đã lọc ⇒ rơi về phiên đầu tiên
  // của tab mới, KHÔNG cần reset `chon` thủ công ở handler onClick.
  const dsLoc = locTheoNguon(ds.data ?? [], tab)
  const sid =
    chon !== null && dsLoc.some((p) => p.sessionId === chon) ? chon : (dsLoc[0]?.sessionId ?? null)
  const ct = useQuery({
    queryKey: ['convos', 'chitiet', sid],
    queryFn: () => chiTietPhien(sid!),
    enabled: sid !== null,
  })
  // Feedback (nếu có) của phiên đang xem — module `quality` sở hữu khái niệm
  // này, `ops` chỉ đọc qua mặt tiền `contracts.ts`. Một phiên KHÔNG có feedback
  // là chuyện thường (đa số phiên không được khách chấm), không phải lỗi —
  // khác `/quality` (danh sách) nơi rỗng phải nói thành chữ ở §7 của kế hoạch.
  const fb = useQuery({
    queryKey: ['agent-feedback', sid],
    queryFn: () => feedbackCuaPhien(sid!),
    enabled: sid !== null,
  })

  // Hàng phiên đang chọn được kéo vào tầm nhìn ở cột trái — ca deep-link
  // `?session=` từ `/quality` tới một phiên nằm dưới mép danh sách. (Vùng nội
  // dung bên phải về ĐẦU nhờ `key={sid}`, xem chỗ render nó.)
  const hangChon = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    hangChon.current?.scrollIntoView?.({ block: 'nearest' })
  }, [sid])

  // Đo TRƯỚC khi vẽ (layout effect) để cột thứ ba không chớp hiện rồi biến. Tấm
  // nền chỉ có sau khi danh sách phiên về, nên đo lại theo `ds.data`.
  const coKhung = ds.data !== undefined
  useLayoutEffect(() => {
    const el = khung.current
    if (!el) return
    const do_ = () => setRongKhung(el.getBoundingClientRect().width)
    do_()
    const ro = new ResizeObserver(do_)
    ro.observe(el)
    return () => ro.disconnect()
  }, [coKhung])

  // Hai trạng thái này cũng phải nằm trong tấm nền như màn chính, nếu không thì
  // lúc tải xong người dùng thấy cái hộp bật ra từ chỗ không có gì.
  if (ds.isPending)
    return (
      <div className="px-7 py-6 max-md:px-4 max-md:py-4">
        <div className="rounded-xl border border-border bg-surface p-6 text-[14px] text-muted">
          Đang tải…
        </div>
      </div>
    )
  if (ds.error)
    return (
      <div className="px-7 py-6 max-md:px-4 max-md:py-4">
        <div className="rounded-xl border border-border bg-surface p-6 text-[14px]">
          Không tải được các phiên của khách này.
        </div>
      </div>
    )

  // Tên GỐC (chưa rơi về số) — avatar dùng cái này, KHÔNG dùng `ten` bên dưới:
  // `noiDungAvatar(null)` trả icon người, còn nếu truyền số điện thoại vào thì
  // lấy nhầm chữ số đầu làm chữ cái. Cùng logic `KhachRow.tsx`
  // (`noiDungAvatar(khach.ten)`) — hai màn phải cho CÙNG một avatar với cùng
  // một khách.
  // `Phien.avatar` backend vẫn trả nhưng KHÔNG còn ai đọc (2026-08-25): lịch sử
  // hội thoại vẽ chữ cái mặc định như bảng Thành viên — xem `noiDungAvatar`.
  const phienCoTen = ds.data.find((p) => p.ten)
  const tenGoc = phienCoTen?.ten ?? null
  // Tên của phiên MỚI NHẤT (danh sách đã sắp giảm dần). Không có tên ở phiên nào
  // thì dùng số làm tên — hiện chuỗi 'null' hay ô trống đều tệ hơn.
  const ten = an ? 'Chưa có số' : (tenGoc ?? phone)
  const soChat = ds.data.filter((p) => p.source === 'chat').length
  const soVoice = ds.data.filter((p) => p.source === 'voice').length
  // Lead HIỆN TẠI = phiên mới nhất CÓ lead (spec §2). `ds.data` đã sắp mới nhất trước và
  // lead của mỗi phiên là hàng ca mới nhất của nó ⇒ trùng đúng lead của hàng khách ở
  // `/convos`. Đọc `ds.data`, KHÔNG `dsLoc`: đổi tab kênh không được đổi lead hiện tại.
  const leadNay = ds.data.find((p) => p.leadStage)
  // Mã dự án → tên, lấy từ chính các phiên đã tải: chân dung hiện tên thay mã mà
  // không thêm request nào.
  const tenDuAn = new Map(
    ds.data.flatMap((p) => (p.duAn && p.tenDuAn ? [[p.duAn, p.tenDuAn] as const] : [])),
  )

  return (
    // MỘT tấm nền cho cả màn — cùng lý lẽ với `KhachList.Khung` (07/08): trước
    // đây header, nút quay lại và hai cột nằm trần trên `--color-bg`, và vùng
    // chat còn dùng ĐÚNG màu nền trang, nên bong bóng khách màu trắng trôi trên
    // chính nền trang. Hai cột giờ là hai vùng của cùng một tấm, ngăn bằng một
    // đường kẻ, chứ không phải hai thẻ rời đặt cạnh nhau.
    <div className="px-7 py-6 max-md:px-4 max-md:py-4">
      <div
        ref={khung}
        className={`flex ${CAO_KHUNG} flex-col overflow-hidden rounded-xl border border-border bg-surface`}
      >
        <div className="shrink-0 border-b border-border-soft px-5 py-4">
          {/* `DUONG_VE` — hằng đường-về dùng chung của portal. Bản trước tô xanh
              accent, tức cùng sắc với NÚT HÀNH ĐỘNG CHÍNH, cho một đường lui;
              và mũi tên `←` là ký tự thứ hai cho cùng một việc mà `‹` đã làm ở
              `VeLai`/`LinkVe`. Docstring `DUONG_VE` liệt kê đúng ba thẻ dùng nó,
              trong đó có `<Link>` đổi route — chính là ca này. */}
          <Link to="/convos" className={DUONG_VE}>
            ‹ Tất cả khách
          </Link>
          <div className="mt-3 flex items-center gap-3 max-md:flex-wrap">
            <span
              className={`flex size-[46px] items-center justify-center rounded-full text-[17px] font-semibold ${
                an ? 'bg-border-soft text-muted-3' : mauCua(phone)
              }`}
            >
              {an ? noiDungAvatar(null) : noiDungAvatar(tenGoc)}
            </span>
            <div>
              <p className="text-[18px] font-semibold">{ten}</p>
              <p className="font-mono text-[13px] text-muted-2">
                {an
                  ? `${ds.data.length} phiên ẩn danh — KHÔNG phải một người`
                  : `${phone} · ${ds.data.length} phiên`}
              </p>
            </div>
            {!an && !coCotChanDung && (
              <button
                type="button"
                title="Thông tin khách"
                aria-label="Thông tin khách"
                onClick={() => setXemChanDung((v) => !v)}
                aria-pressed={xemChanDung}
                className={`inline-flex size-9 flex-none cursor-pointer items-center justify-center rounded-md border border-border-field transition-colors hover:border-fg hover:text-fg ${
                  xemChanDung ? 'bg-acs text-fg' : 'text-muted'
                }`}
              >
                <Icon name="thongTin" className="size-[18px]" />
              </button>
            )}
            {/* Nhóm «Chưa có số» là nhiều người (header tự nói thế) — một «lead hiện tại»
                cho cả nhóm là nói sai. Chip TỪNG PHIÊN vẫn giữ: lead một phiên là của một người. */}
            {!an && leadNay?.leadStage && (
              <div
                data-testid="lead-hien-tai"
                className="ml-auto flex items-start gap-3.5 rounded-lg border border-border bg-n2 py-2.5 pl-4 pr-3.5 max-md:ml-0 max-md:basis-full"
              >
                <div>
                  <p className="text-[12px] text-muted-2">Lead hiện tại</p>
                  <div className="mt-1.5">
                    <ChipStage stage={leadNay.leadStage} />
                  </div>
                </div>
                {leadNay.leadScore !== null && leadNay.leadScore !== undefined && (
                  <>
                    <span aria-hidden className="w-px self-stretch bg-border" />
                    <div>
                      <p className="text-[12px] text-muted-2">Điểm</p>
                      <p className="mt-1.5 font-mono text-[20px] font-medium leading-[22px] tracking-tight tabular-nums">
                        {leadNay.leadScore}
                      </p>
                    </div>
                  </>
                )}
                {leadNay.audience && (
                  <>
                    <span aria-hidden className="w-px self-stretch bg-border" />
                    <div>
                      <p className="text-[12px] text-muted-2">Đối tượng</p>
                      <p className="mt-1.5 text-than font-medium leading-[22px]">
                        {nhanDoiTuong(leadNay.audience)}
                      </p>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>

        {ds.data.length === 0 ? (
          <p className="px-5 py-12 text-center text-[14px] text-muted">
            Khách này không còn phiên nào.
          </p>
        ) : (
          <div className="flex min-h-0 flex-1">
            {hienDs && (
              <div className="flex w-[300px] shrink-0 flex-col border-r border-border-soft max-md:w-full max-md:border-r-0">
                {/* Đếm trên CHÍNH danh sách phiên của khách này (`ds.data`), không
                  gọi thêm API — khớp `soPhien` đã tải sẵn cho màn này.

                  DÙNG `NhomTab`, BỎ PILL TỐI (người dùng chốt 2026-08-09). Ngày
                  07/08 chỗ này chốt là pill tối `bg-fg` + chữ trắng, cố ý khác
                  khung của `KHOANG`. Ngày 08/08 lại chốt bộ tab của portal về
                  segmented control, và chính vì lý do chống lại pill tối: một
                  mảng gần-đen đọc thành NÚT CHÍNH chứ không phải «trang đang
                  xem». Hai lần chốt chỏi nhau ở đúng ô này; lần sau thắng.

                  `role="tablist"` của `NhomTab` là đúng ở đây (khác `KHOANG` bên
                  `KhachList` — chỗ đó là bộ LỌC nên vẫn để nút thường): ba mục
                  này chọn một trong ba CÁCH XEM cùng một vùng, và danh sách phiên
                  ngay dưới chính là panel của mục đang chọn. */}
                <div className="shrink-0 border-b border-border-soft p-2">
                  <NhomTab
                    nhan="Lọc phiên theo kênh"
                    idPanel="tab-phien-kenh"
                    dangMo={tab}
                    doi={setTab}
                    muc={TABS.map((t) => ({
                      id: t.ma,
                      nhan: `${t.nhan} ${t.ma === 'tat-ca' ? ds.data.length : t.ma === 'chat' ? soChat : soVoice}`,
                    }))}
                  />
                </div>

                <div
                  data-testid="cuon-phien"
                  className="min-h-0 flex-1 overflow-y-auto"
                  {...panelTab('tab-phien-kenh', tab)}
                >
                  {dsLoc.length === 0 ? (
                    <p className="px-3.5 py-8 text-center text-[13px] text-muted">
                      Không có phiên nào ở mục này.
                    </p>
                  ) : (
                    dsLoc.map((p) => {
                      const dai = thoiLuong(p.batDau, p.ketThuc)
                      return (
                        <button
                          key={p.sessionId}
                          ref={p.sessionId === sid ? hangChon : undefined}
                          type="button"
                          onClick={() => {
                            setChon(p.sessionId)
                            setDangXemPhien(true)
                            setXemChanDung(false)
                          }}
                          className={`block w-full border-b border-border-soft px-3.5 py-3 text-left last:border-b-0 ${
                            p.sessionId === sid
                              ? 'border-l-[3px] border-l-ac bg-acs'
                              : 'hover:bg-bg'
                          }`}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="text-than font-semibold">{ngayGio(p.batDau)}</span>
                            {/* `null`/giá trị lạ KHÔNG hiện badge (`anKhiLa`) — xem
                            `locTheoNguon` và docstring `ChipKenh`. Mỗi kênh MỘT
                            SẮC RIÊNG từ 2026-08-13, dùng chung đúng component
                            với card feedback ở `/quality`. */}
                            <ChipKenh source={p.source} anKhiLa />
                          </span>
                          <span
                            className={`mt-0.5 block truncate text-phu ${p.tinNhanDau ? 'text-muted' : 'italic text-muted-3'}`}
                          >
                            {p.tinNhanDau ?? 'Chưa có tin nhắn nào.'}
                          </span>
                          <span className="mt-1 flex items-center justify-between gap-2">
                            <span className="min-w-0 truncate font-mono text-[11.5px] text-muted-2">
                              {p.soLuot} lượt{dai ? ` · ${dai}` : ''}
                              {p.tenDuAn || p.duAn ? (
                                <span className="font-sans"> · {p.tenDuAn || p.duAn}</span>
                              ) : null}
                            </span>
                            {p.leadStage && <ChipStage stage={p.leadStage} />}
                          </span>
                        </button>
                      )
                    })
                  )}
                </div>
              </div>
            )}

            {hienCt && chanDungThayNoiDung && (
              <div className="flex min-w-0 flex-1 flex-col">
                <button
                  type="button"
                  onClick={() => setXemChanDung(false)}
                  className={`${DUONG_VE} shrink-0 border-b border-border-soft px-4 py-2.5 text-left`}
                >
                  ‹ Hội thoại
                </button>
                <ChanDungKhach phone={phone} tenDuAn={tenDuAn} className="flex-1" />
              </div>
            )}

            {hienCt && !chanDungThayNoiDung && (
              <div className="flex min-w-0 flex-1 flex-col">
                {mobile && (
                  <button
                    type="button"
                    onClick={() => setDangXemPhien(false)}
                    className={`${DUONG_VE} shrink-0 border-b border-border-soft px-4 py-2.5 text-left`}
                  >
                    ‹ Các phiên
                  </button>
                )}
                {sid === null && (
                  <p className="p-6 text-center text-[14px] text-muted">
                    Không có phiên nào ở mục này.
                  </p>
                )}
                {sid !== null && ct.isPending && (
                  <p className="p-6 text-[14px] text-muted">Đang tải…</p>
                )}
                {sid !== null && ct.error && (
                  <p className="p-6 text-[14px]">Không tải được nội dung phiên này.</p>
                )}
                {sid !== null && ct.data && (
                  <>
                    {/* BỎ mã phiên (`green_park-c-…-ca6c`) và «config vN» khỏi dòng
                      này (người dùng chốt 2026-09-24): hai chuỗi máy đó không giúp
                      người vận hành đọc phiên, chỉ chiếm chỗ đầu hàng. Mã phiên
                      vẫn nằm trên `data-session` — seam cho test biết panel đang
                      hiện ĐÚNG phiên nào, không hiện ra màn. */}
                    <div
                      data-testid="dong-phien"
                      data-session={ct.data.phien.sessionId}
                      className="flex shrink-0 items-center gap-4 border-b border-border-soft px-4 py-2.5 text-phu text-muted-2 max-md:flex-wrap max-md:gap-x-3 max-md:gap-y-1"
                    >
                      <span>{ngayGio(ct.data.phien.batDau)}</span>
                      {thoiLuong(ct.data.phien.batDau, ct.data.phien.ketThuc) && (
                        <span className="font-semibold text-fg">
                          {thoiLuong(ct.data.phien.batDau, ct.data.phien.ketThuc)}
                        </span>
                      )}
                      <span>{ct.data.phien.soLuot} lượt</span>
                      {ct.data.phien.leadStage && (
                        <>
                          <span aria-hidden className="h-4 w-px bg-border max-md:hidden" />
                          <ChipStage stage={ct.data.phien.leadStage} />
                          {ct.data.phien.leadScore !== null &&
                            ct.data.phien.leadScore !== undefined && (
                              <DiemLead diem={ct.data.phien.leadScore} />
                            )}
                          {ct.data.phien.audience && (
                            <span className="text-[12px] text-muted">
                              {nhanDoiTuong(ct.data.phien.audience)}
                            </span>
                          )}
                        </>
                      )}
                      {fb.data && (
                        <span className="ml-auto flex items-center gap-1.5">
                          <Sao gia={fb.data.rating} kichThuoc={13} />
                          {/* KHÔNG bọc dấu ngoặc kép quanh comment: chữ ngoặc là
                            text node RIÊNG cạnh {fb.data.comment}, `getNodeText`
                            của testing-library nối CẢ hai text-node con trực
                            tiếp của span thành một chuỗi (`"Khá ổn"` thay vì
                            `Khá ổn`) — test khớp chữ chính xác sẽ trượt. Cùng
                            quy ước với `FeedbackReviewCard.tsx` (comment không
                            có ngoặc kép, chỉ nghiêng). */}
                          {fb.data.comment && <span className="italic">{fb.data.comment}</span>}
                        </span>
                      )}
                    </div>
                    {/* Khay chat KHÔNG còn `bg-bg`: đó đúng bằng màu nền trang, nên
                      bong bóng khách (trắng) trôi trên chính nền trang và cả vùng
                      mất cảm giác có khay chứa. Khay giờ trắng, và bong bóng khách
                      đổi sang `bg-bg` bên `Transcript` để nổi lên trên nó. */}
                    {/* `key={sid}`: đổi phiên là một vùng cuộn MỚI, tức về đầu. Không
                      có nó thì phiên đã có trong cache (bấm lại phiên vừa xem)
                      dùng lại đúng phần tử cũ và giữ vị trí cuộn của phiên trước
                      — mở một phiên mà thấy giữa chừng đoạn chat. Phiên CHƯA có
                      trong cache thì tự về đầu vì vùng này unmount lúc «Đang
                      tải…», nên lỗi chỉ lộ ở ca cache — dễ lọt. */}
                    <div
                      key={sid}
                      data-testid="cuon-noi-dung"
                      className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4"
                    >
                      {ct.data.phien.summary && (
                        // `badge-neutral`, KHÔNG `badge-warn`: đây là thông tin bình thường
                        // (agent tự tóm tắt phiên), không phải cảnh báo — vàng đọc sai thành
                        // "có gì đó cần chú ý". Cũng KHÔNG `bg-acs`: màu đó đã là ngôn ngữ
                        // riêng của "lời agent nói" (bong bóng, card tool ở Transcript.tsx),
                        // dùng lại đây sẽ làm summary trông như một bong bóng chat.
                        <div className="rounded-lg border border-badge-neutral-bg bg-badge-neutral-bg px-3 py-2.5 text-than leading-[1.55] text-fg">
                          <p className="mb-1 text-phu font-semibold text-badge-neutral-fg">
                            Tóm tắt của agent
                          </p>
                          {ct.data.phien.summary}
                        </div>
                      )}
                      <Transcript
                        luot={ct.data.luot}
                        skillCallsDuPhong={ct.data.skillCalls}
                        {...(luotMoDau !== undefined && sid === phienMoDau
                          ? { toSang: luotMoDau }
                          : {})}
                      />
                    </div>
                  </>
                )}
              </div>
            )}

            {coCotChanDung && !an && (
              <ChanDungKhach
                phone={phone}
                tenDuAn={tenDuAn}
                className="w-[300px] shrink-0 border-l border-border-soft"
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
