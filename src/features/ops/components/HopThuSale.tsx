/**
 * Màn «Chuyển sale» — hộp thư những lượt agent đã hứa với khách là sẽ có chuyên
 * viên liên hệ. Master–detail: danh sách trái, chi tiết phải.
 *
 * Bộ lọc + trang + ca đang mở nằm ở SEARCH PARAM (route đẩy xuống đây), không
 * phải `useState`: F5 hoặc gửi link cho đồng nghiệp vẫn ra đúng ca đang xem.
 */
import { type ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CAO_O,
  ChonMot,
  DUONG_VE,
  HANG_NUT,
  HANG_NUT_DAN,
  NUT_CHINH,
  NUT_PHU,
  O_LOC,
} from '@/components/ui/Bang'
import { HopThoai, KHUNG_HOP_THOAI } from '@/components/ui/HopThoai'
import { LoiTai } from '@/components/ui/TrangThai'
import { O_CHUNG } from '@/components/ui/Truong'
import { useKhoManHinh } from '@/lib/khoManHinh'
import { type Ca, type LocCa, type TabCa, TRANG_CA, danhSachCa, nhanCa } from '../api'
import { CaChiTiet, NutCa } from './CaChiTiet'
import { CaRow } from './CaRow'

const TAB: { ma: TabCa; nhan: string }[] = [
  { ma: 'new', nhan: 'Chưa liên hệ' },
  { ma: 'contacted', nhan: 'Đang xử lý' },
  { ma: 'done', nhan: 'Xong' },
  { ma: 'all', nhan: 'Tất cả' },
]

/** Tiêu đề cột danh sách theo tab. Trước là «Ca cần gọi lại» ở MỌI tab — kể cả
 *  tab «Xong», và tab «Tất cả» đếm luôn ca đã xong vào số «cần gọi lại». */
const TIEU_DE_DS: Record<TabCa, string> = {
  new: 'Ca cần gọi lại',
  contacted: 'Ca đang xử lý',
  done: 'Ca đã xong',
  all: 'Tất cả ca',
}

type TrangThaiDich = 'new' | 'contacted' | 'done'
const DICH: readonly string[] = ['new', 'contacted', 'done']

/**
 * Lần đổi trạng thái vừa xong: `ca` là bản server trả về sau PATCH, `truoc` là
 * trạng thái để «Hoàn tác» quay về.
 *
 * Ca này được GHIM đang mở cho tới khi người dùng tự rời nó (chọn hàng khác,
 * đổi bộ lọc, «‹ Danh sách»), kể cả khi nó vừa rớt khỏi tab đang lọc. Trước đây
 * nhận ca ở tab «Chưa liên hệ» thì ca rời trang, desktop rơi về `items[0]` —
 * critique 05/10 tái hiện: hai ca cùng một khách (12 và 13), khung chi tiết đổi
 * sang ca 13 dưới ĐÚNG cái nút «Nhận ca này» đang giữ focus, Enter lần hai nhận
 * luôn ca 13. Mobile thì bị đẩy về danh sách, số vừa nhận biến mất.
 */
interface VuaDoi {
  readonly ca: Ca
  readonly truoc: string
}

function loiBao({ ca, truoc }: VuaDoi): string {
  const ai = ca.ten ?? ca.phone
  const cua = ai ? `ca ${ai}` : 'ca'
  if (ca.trangThai === 'done') return `Đã đánh dấu xong ${cua}.`
  if (ca.trangThai === 'new') return `Đã trả ${cua} về «Chưa liên hệ».`
  return truoc === 'done' ? `Đã mở lại ${cua}.` : `Đã nhận ${cua}.`
}

// 120px = Topbar `h-[72px]` + `py-6` trên/dưới. Khung CHỐT chiều cao thay vì co
// theo số ca: 3 ca thì bảng cao một phần tư màn, 10 ca lại đẩy trang dài ra.
// Mobile: 88px = topbar 56px + `py-4` trên/dưới (32px).
//
// MÀN THẤP (≤500px — điện thoại xoay ngang, adapt 06/10): chốt chiều cao ở đây là
// chốt cả danh sách vào phần còn lại sau cụm lọc — đo 667×375 danh sách còn 9px,
// 844×390 còn một hàng. Màn thấp thì khung cao theo nội dung và cả `<main>` cuộn.
// `overflow-clip` chứ không `hidden`: `hidden` biến khung thành vùng cuộn và hàng nút
// `sticky bottom-0` dính vào khung (không bao giờ cuộn) thay vì đáy màn.
const CAO_KHUNG =
  'h-[calc(100vh-120px)] max-md:h-[calc(100dvh-88px)] [@media(max-height:500px)]:h-auto! [@media(max-height:500px)]:overflow-clip!'
/** Vùng cuộn riêng (danh sách, chi tiết) — màn thấp thì thôi cuộn riêng, xem `CAO_KHUNG`. */
const VUNG_CUON = 'min-h-0 flex-1 overflow-y-auto [@media(max-height:500px)]:overflow-visible'

function Khung({ children }: { children: ReactNode }) {
  return (
    <div className="px-7 py-6 max-md:px-4 max-md:py-4">
      <div
        className={`flex ${CAO_KHUNG} flex-col overflow-hidden rounded-xl border border-border bg-surface`}
      >
        {children}
      </div>
    </div>
  )
}

export function HopThuSale({
  loc = {},
  datLoc,
  caDangMo,
  moCa,
  bayGio,
}: {
  loc?: LocCa
  datLoc?: (l: LocCa) => void
  caDangMo?: number | undefined
  /** `day` = mở ca bằng một mục lịch sử MỚI (điện thoại, từ danh sách) — xem route. */
  moCa?: (id: number | undefined, day?: boolean) => void
  bayGio?: Date | undefined
}) {
  const [nhap, setNhap] = useState(loc.q ?? '')
  const [hopGhiChu, setHopGhiChu] = useState<Ca | null>(null)
  const [vuaDoi, setVuaDoi] = useState<VuaDoi | null>(null)
  const tieuDe = useRef<HTMLHeadingElement>(null)
  const qc = useQueryClient()
  // Hộp thư mở cả ca làm việc: lấy lại khi quay lại tab và mỗi 30 giây (critique
  // 05/10 — ca mới không tự hiện, ca đồng nghiệp đã nhận vẫn mời «Nhận ca này»).
  // Mặc định toàn app TẮT `refetchOnWindowFocus` (`main.tsx`); `refetchInterval` tự
  // dừng khi tab ẩn. Làm mới KHÔNG được đổi ca đang hiện — xem `giu` bên dưới.
  const ds = useQuery({
    queryKey: ['escalations', loc],
    queryFn: () => danhSachCa(loc),
    refetchOnWindowFocus: true,
    refetchInterval: 30_000,
  })
  // Ca đang hiện ở khung chi tiết, buộc vào NGỮ CẢNH (bộ lọc + `?ca=`). Đổi ngữ cảnh
  // là việc của người dùng; còn trong cùng ngữ cảnh thì dữ liệu mới về KHÔNG được
  // thay ca khác vào chỗ đó — đúng lớp lỗi «nhận nhầm ca» của harden 05/10: ca mới
  // chen lên đầu ⇒ desktop (rơi về `items[0]`) đổi ca dưới con trỏ; đồng nghiệp nhận
  // ca đang xem ⇒ ca rời tab, khung chi tiết nhảy đi (điện thoại: đá về danh sách).
  const ngCanh = JSON.stringify([loc, caDangMo ?? null])
  const [giu, setGiu] = useState<{ ngCanh: string; ca: Ca } | null>(null)

  // `useKhoManHinh` PHẢI gọi TRƯỚC hai `return` sớm bên dưới (isPending/isError)
  // — một hook nằm sau nhánh return sớm thì số hook gọi được đổi giữa các lần
  // render của CÙNG một instance (tải xong ⇒ không còn return sớm nữa), và
  // React ném "Rendered more hooks than during the previous render." Rules of
  // Hooks cấm đúng ca này, không phải chuyện phong cách.
  const mobile = useKhoManHinh() === 'mobile'
  const dsEl = useRef<HTMLDivElement | null>(null)
  const quayVe = useRef<{ ca: number; ds: number; trang: number } | null>(null)

  const doi = (p: Partial<LocCa>) => {
    setVuaDoi(null)
    datLoc?.({ ...loc, ...p, trang: p.trang ?? 1 })
  }
  const roiCa = (id: number | undefined) => {
    setVuaDoi(null)
    if (id !== undefined && mobile) {
      const el = dsEl.current
      const trang = el?.closest('main')
      quayVe.current = { ca: id, ds: el?.scrollTop ?? 0, trang: trang?.scrollTop ?? 0 }
      // Màn thấp: `<main>` đang cuộn tới hàng vừa bấm — mở ca mà giữ nguyên chỗ đó
      // là rơi vào giữa phần chi tiết, không thấy tên khách.
      if (trang) trang.scrollTop = 0
    }
    moCa?.(id, id !== undefined && mobile)
  }

  // Rời ca bằng Back của trình duyệt/điện thoại thì không đi qua `roiCa`: `?ca=` mất
  // mà ghim còn ⇒ ca vừa đổi hiện lại ngay, Back như không ăn. Rời là rời — cùng
  // nghĩa «‹ Danh sách»: thôi ghim, thôi báo. (Mẫu «suy state từ prop lần trước».)
  const [caTruoc, setCaTruoc] = useState(caDangMo)
  if (caTruoc !== caDangMo) {
    setCaTruoc(caDangMo)
    if (caDangMo === undefined) setVuaDoi(null)
  }

  // Điện thoại: danh sách UNMOUNT khi mở một ca, nên về lại là về ĐẦU danh sách và
  // focus rơi về `<body>`. Ghi lúc mở ca (`roiCa`), trả lại lúc danh sách gắn lại:
  // vị trí cuộn của CẢ danh sách lẫn `<main>` (màn thấp thì `<main>` mới là thứ cuộn,
  // xem `CAO_KHUNG`) + focus vào hàng vừa xem. Ref callback ổn định ⇒ chỉ chạy khi
  // phần tử MỚI gắn vào, không mỗi render.
  const ganDs = useCallback((el: HTMLDivElement | null) => {
    dsEl.current = el
    const v = quayVe.current
    if (!el || !v) return
    quayVe.current = null
    el.scrollTop = v.ds
    const trang = el.closest('main')
    if (trang) trang.scrollTop = v.trang
    el.querySelector<HTMLElement>(`[data-ca="${v.ca}"]`)?.focus({ preventScroll: true })
  }, [])

  const gui = useMutation({
    mutationFn: (v: { id: number; trangThai: TrangThaiDich; truoc: string; ghiChu?: string }) =>
      nhanCa(
        v.id,
        v.ghiChu === undefined
          ? { trangThai: v.trangThai }
          : { trangThai: v.trangThai, ghiChu: v.ghiChu },
      ),
    onSuccess: (ca, v) => {
      setHopGhiChu(null)
      setVuaDoi({ ca, truoc: v.truoc })
      // Ghi `?ca=` cho ĐÚNG ca vừa đổi: desktop không có `?ca=` thì đang hiện
      // `items[0]`, và đó là chỗ ca kế tiếp lẻn vào.
      moCa?.(ca.id)
      void qc.invalidateQueries({ queryKey: ['escalations'] })
      void qc.invalidateQueries({ queryKey: ['escalation-notes'] })
    },
  })

  // Nút vừa bấm biến mất theo trạng thái cũ (ví dụ «Nhận ca này»), focus rơi về
  // `<body>`. Đưa nó về tiêu đề ca: người dùng bàn phím đứng lại đúng ca vừa
  // làm, và vùng `role="status"` đọc kết quả.
  useEffect(() => {
    if (vuaDoi) tieuDe.current?.focus()
  }, [vuaDoi])
  if (ds.isPending)
    return (
      <Khung>
        <p className="p-6 text-[14px] text-muted">Đang tải…</p>
      </Khung>
    )

  // Chỉ khi CHƯA từng có danh sách. Lần làm mới hỏng thì `ds.data` vẫn là bản cũ —
  // thay cả hộp thư bằng khung lỗi vì một nhịp mạng là cất mất thứ đang làm dở.
  if (!ds.data)
    return (
      <Khung>
        <div className="p-6">
          <LoiTai viec="danh sách ca" thuLai={() => void ds.refetch()} />
        </div>
      </Khung>
    )

  const { items, tongCa, duAnCo } = ds.data
  // Ca KHỚP trang hiện tại — có thể `undefined` (URL trỏ ca đã rời trang, ví
  // dụ vừa đổi trạng thái nên rớt khỏi tab đang lọc, hoặc `?ca=` cũ/chia sẻ).
  const caTrenTrang = items.find((c) => c.id === caDangMo)
  // Ca vừa đổi trạng thái đứng TRƯỚC dữ liệu danh sách: lúc refetch chưa về,
  // `items` còn bản cũ (vẫn `new`, vẫn «Nhận ca này»). `caDangMo === undefined`
  // là nhịp render trước khi `moCa` kịp ghi URL.
  const ghim =
    vuaDoi && (caDangMo === undefined || caDangMo === vuaDoi.ca.id) ? vuaDoi.ca : undefined
  const caGiu = giu?.ngCanh === ngCanh ? giu.ca : undefined
  // Bản MỚI NHẤT của ca đang giữ nếu nó còn trên trang; không còn thì bản cũ.
  const tuoi = caGiu && (items.find((c) => c.id === caGiu.id) ?? caGiu)
  const caMo = ghim ?? caTrenTrang ?? (caDangMo !== undefined ? tuoi : undefined)
  // Desktop GIỮ NGUYÊN hành vi cũ: luôn hiện cả hai cột, ca không khớp thì
  // `dangMo` rơi về `items[0]` — có ngữ cảnh (danh sách vẫn hiện, hàng sáng
  // lên đổi) nên không gây nhầm. Mobile thì KHÔNG rơi về ca khác: rơi về
  // `items[0]` mà không hiện danh sách là bày một ca ngẫu nhiên có cùng nút
  // «Nhận ca này» — người dùng tưởng thao tác trước chưa ăn và bấm nhận nhầm
  // ca (xem final-review.md Important #1).
  const dangMo = mobile ? caMo : (caMo ?? tuoi ?? items[0])
  if (dangMo && caGiu !== dangMo) setGiu({ ngCanh, ca: dangMo })
  // Ca đang hiện vừa RỜI danh sách vì lần làm mới (không phải vì chính người này đổi —
  // ca đó là `ghim`): đồng nghiệp đã đổi trạng thái, hoặc ca mới đẩy nó sang trang
  // sau. Không có endpoint đọc một ca để lấy bản mới, nên giữ bản cũ, NÓI RA, và cất
  // nút đổi trạng thái — bấm «Nhận ca này» trên bản cũ là giành ca của đồng nghiệp.
  const roi = !!dangMo && !ghim && !items.some((c) => c.id === dangMo.id)
  // Rẽ theo CA CÓ KHỚP TRANG HAY KHÔNG, không theo `caDangMo` thô: `?ca=` cũ
  // vẫn "có giá trị" nhưng không còn trỏ vào ca nào hiện diện — hiện chi tiết
  // lúc đó là hiện một khối trống hoặc (trước sửa) một ca khác.
  const hienDs = !mobile || caMo === undefined
  const hienCt = !mobile || caMo !== undefined
  const nhanCaMo = (tt: 'new' | 'contacted') => {
    if (dangMo) gui.mutate({ id: dangMo.id, trangThai: tt, truoc: dangMo.trangThai })
  }
  const trang = loc.trang ?? 1
  const soTrang = Math.max(1, Math.ceil(tongCa / TRANG_CA))
  const dau = tongCa === 0 ? 0 : (trang - 1) * TRANG_CA + 1

  return (
    <Khung>
      {/* Điện thoại đang xem MỘT ca: cụm lọc (~230px, 27% màn) không có việc gì ở
          đây — nó lọc danh sách, mà danh sách đang ẩn. Trả chỗ cho ca. */}
      {!(mobile && hienCt) && (
        <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border-soft px-5 py-3">
          {/* Điện thoại: ô tìm lên ĐẦU, trọn dòng — tìm một khách là việc đầu tiên của CSKH mở
            hộp này trên điện thoại; bốn trạng thái trọn dòng, nhãn không xuống dòng. */}
          <ChonMot
            nhan="Trạng thái ca"
            muc={TAB}
            chon={loc.trangThai ?? 'all'}
            doi={(ma) => doi({ trangThai: ma })}
            className="max-md:w-full"
          />

          {/* `min-w-0`: thiếu nó thì bề rộng tối thiểu của ô chọn đẩy «Cũ nhất trước»
            xuống một hàng riêng ở 390px. */}
          <label className="ml-auto flex items-center gap-1.5 text-phu text-muted max-md:ml-0 max-md:min-w-0 max-md:flex-1">
            Dự án
            <select
              value={loc.duAn ?? ''}
              onChange={(e) => doi({ duAn: e.target.value })}
              aria-label="Lọc theo dự án"
              className={`${O_LOC} o-chon bg-surface max-md:h-10 max-md:min-w-0 max-md:flex-1`}
            >
              <option value="">Tất cả</option>
              {duAnCo.map((d) => (
                <option key={d.ma} value={d.ma}>
                  {d.ten || d.ma}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            onClick={() => doi({ sapXep: loc.sapXep === 'cu' ? 'moi' : 'cu' })}
            aria-pressed={loc.sapXep === 'cu'}
            className={`${CAO_O} rounded-md border px-3 text-phu transition max-md:h-10
                      ${loc.sapXep === 'cu' ? 'border-ac text-ac' : 'border-border-field text-muted hover:text-fg'}`}
          >
            Cũ nhất trước
          </button>

          <form
            className="max-md:order-first max-md:basis-full"
            onSubmit={(e) => {
              e.preventDefault()
              doi({ q: nhap })
            }}
          >
            <input
              type="search"
              aria-label="Tìm ca theo tên hoặc số điện thoại"
              value={nhap}
              onChange={(e) => setNhap(e.target.value)}
              placeholder="Tìm theo tên hoặc số điện thoại"
              className={`${O_LOC} w-[280px] bg-surface max-md:h-10 max-md:w-full`}
            />
          </form>
        </div>
      )}

      {/* Vùng `role="status"` LUÔN có mặt (rỗng khi chưa có gì để nói): trình đọc
          màn hình chỉ đọc chắc chắn khi nội dung đổi trong một vùng đã tồn tại. */}
      <div
        className={
          ghim && vuaDoi
            ? 'flex shrink-0 items-center gap-3 border-b border-border-soft bg-acs px-5 py-2 max-md:px-4 max-md:py-0.5'
            : undefined
        }
      >
        <p role="status" className="min-w-0 flex-1 text-than text-fg">
          {ghim && vuaDoi ? loiBao(vuaDoi) : ''}
        </p>
        {ghim && vuaDoi && DICH.includes(vuaDoi.truoc) && (
          <button
            type="button"
            disabled={gui.isPending}
            onClick={() =>
              gui.mutate({
                id: ghim.id,
                trangThai: vuaDoi.truoc as TrangThaiDich,
                truoc: ghim.trangThai,
              })
            }
            className="shrink-0 rounded-sm px-1 text-than font-medium text-ac hover:text-acd disabled:opacity-50 max-md:min-h-10 max-md:px-2"
          >
            Hoàn tác
          </button>
        )}
      </div>

      {gui.isError && !hopGhiChu && (
        <div
          role="alert"
          className="flex shrink-0 items-center gap-3 border-b border-border-soft bg-badge-alert-bg px-5 py-2.5 text-[13px] text-badge-alert-fg max-md:px-4"
        >
          <p className="min-w-0 flex-1">Không cập nhật được ca: {(gui.error as Error).message}</p>
          {gui.variables && (
            <button
              type="button"
              disabled={gui.isPending}
              onClick={() => gui.variables && gui.mutate(gui.variables)}
              className="shrink-0 rounded-sm px-1 font-medium underline underline-offset-2 disabled:opacity-50 max-md:min-h-10 max-md:px-2"
            >
              Thử lại
            </button>
          )}
        </div>
      )}

      {tongCa === 0 && !dangMo ? (
        // Khối rỗng theo đúng khuôn `/convos`/`/quality`: căn giữa, tiêu đề đậm
        // + câu hướng dẫn — không phải một dòng trần dạt trái trên đầu khung
        // trống (người dùng chê lệch concept 2026-08-21). Rỗng là BÌNH THƯỜNG:
        // không role="alert", không màu đỏ.
        <div className="px-5 py-14 text-center">
          <p className="text-the font-semibold">Không có ca nào khớp bộ lọc này</p>
          {/* <p className="mx-auto mt-1.5 max-w-[440px] text-than leading-relaxed text-muted">
            Khi agent chuyển một phiên cho người thật, ca sẽ hiện ở đây. Thử đổi trạng thái, dự án
            hoặc từ khoá đang lọc.
          </p> */}
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(300px,380px)_1fr] max-md:grid-cols-1">
          {hienDs && (
            <div className="flex min-h-0 flex-col border-r border-border-soft max-md:border-r-0">
              <div className="flex shrink-0 items-baseline justify-between border-b border-border-soft px-5 py-2.5">
                <span className="text-phu font-semibold text-muted">
                  {TIEU_DE_DS[loc.trangThai ?? 'all']}
                </span>
                {ds.isRefetchError && (
                  <span role="status" className="mr-auto ml-2 text-nhan text-badge-alert-fg">
                    · chưa làm mới được, sẽ thử lại
                  </span>
                )}
                <span className="font-mono text-[12px] text-muted-2">{tongCa}</span>
              </div>

              <div ref={ganDs} className={VUNG_CUON}>
                {items.map((c) => (
                  <CaRow
                    key={c.id}
                    ca={c}
                    dangChon={c.id === dangMo?.id}
                    chon={() => roiCa(c.id)}
                    bayGio={bayGio}
                  />
                ))}
                {/* Tab vừa hết ca nhưng ca vừa đổi vẫn ghim bên phải. */}
                {items.length === 0 && (
                  <p className="px-5 py-6 text-than text-muted">Không còn ca nào trong mục này.</p>
                )}
              </div>

              <div className="flex shrink-0 items-center justify-between border-t border-border-soft px-5 py-2.5">
                <span className="font-mono text-[12px] text-muted-2">
                  {dau}–{Math.min(trang * TRANG_CA, tongCa)} / {tongCa}
                </span>
                <span className="flex gap-1.5">
                  <button
                    type="button"
                    disabled={trang <= 1}
                    onClick={() => datLoc?.({ ...loc, trang: trang - 1 })}
                    aria-label="Trang trước"
                    className={`${NUT_PHU} disabled:opacity-40 max-md:min-w-10`}
                  >
                    ‹
                  </button>
                  <button
                    type="button"
                    disabled={trang >= soTrang}
                    onClick={() => datLoc?.({ ...loc, trang: trang + 1 })}
                    aria-label="Trang sau"
                    className={`${NUT_PHU} disabled:opacity-40 max-md:min-w-10`}
                  >
                    ›
                  </button>
                </span>
              </div>
            </div>
          )}

          {hienCt && (
            <div className="flex min-h-0 flex-col">
              <div className={VUNG_CUON}>
                {mobile && (
                  <button
                    type="button"
                    onClick={() => roiCa(undefined)}
                    className={`${DUONG_VE} block w-full border-b border-border-soft px-4 py-2.5 text-left`}
                  >
                    ‹ Danh sách
                  </button>
                )}
                {roi && (
                  <p
                    role="status"
                    className="border-b border-border-soft bg-badge-warn-bg px-5 py-2.5 text-than text-badge-warn-fg max-md:px-4"
                  >
                    Ca này vừa thay đổi và không còn trong danh sách đang xem — thông tin dưới đây
                    có thể đã cũ. Chọn lại ca từ danh sách để làm tiếp.
                  </p>
                )}
                {dangMo && (
                  // `key` theo ca: đổi sang ca khác là dựng lại cả khối, không để
                  // React tái dùng cái nút đang giữ focus cho một ca khác.
                  <CaChiTiet
                    key={dangMo.id}
                    ca={dangMo}
                    tieuDeRef={tieuDe}
                    anNut={mobile || roi}
                    dangGui={gui.isPending}
                    nhan={nhanCaMo}
                    moGhiChu={() => setHopGhiChu(dangMo)}
                  />
                )}
              </div>
              {/* Điện thoại: nút ca DÁN ĐÁY khung, ngoài vùng cuộn — trong tầm ngón
                cái, và không trôi mất khi đọc tóm tắt/hội thoại/ghi chú. */}
              {mobile && dangMo && !roi && (
                <div className={`${HANG_NUT_DAN} shrink-0`}>
                  <NutCa
                    ca={dangMo}
                    them="min-w-0 flex-auto max-md:h-11 max-md:px-2"
                    dangGui={gui.isPending}
                    nhan={nhanCaMo}
                    moGhiChu={() => setHopGhiChu(dangMo)}
                  />
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {hopGhiChu && (
        <GhiChuModal
          ca={hopGhiChu}
          dong={() => setHopGhiChu(null)}
          dangGui={gui.isPending}
          loi={gui.isError ? (gui.error as Error).message : null}
          luu={(ghiChu) =>
            gui.mutate({ id: hopGhiChu.id, trangThai: 'done', truoc: hopGhiChu.trangThai, ghiChu })
          }
        />
      )}
    </Khung>
  )
}

function GhiChuModal({
  ca,
  dong,
  luu,
  dangGui,
  loi,
}: {
  ca: Ca
  dong: () => void
  luu: (ghiChu: string) => void
  dangGui: boolean
  /** Lỗi của lần lưu vừa rồi. Phải hiện TRONG hộp: băng lỗi của màn nằm dưới
   *  lớp nền của hộp thoại, bấm lưu hỏng mà không thấy gì. Ô ghi chú giữ nguyên. */
  loi: string | null
}) {
  const [chu, setChu] = useState('')

  return (
    <HopThoai
      onDong={dong}
      aria-labelledby="tieu-de-ghi-chu"
      className={`${KHUNG_HOP_THOAI} max-w-[460px]`}
    >
      <h3 id="tieu-de-ghi-chu" className="text-muc font-semibold">
        Đánh dấu xong
      </h3>
      <p className="mt-1 text-phu text-muted-2">
        {ca.ten ?? 'Khách chưa cho tên'} · {ca.phone ?? 'chưa có số'}
      </p>

      {ca.ghiChu && (
        <div className="mt-4 rounded-lg border border-border bg-bg px-3 py-2">
          <p className="text-[12px] text-muted-2">
            Ghi chú gần nhất{ca.nguoiXuLy ? ` · ${ca.nguoiXuLy}` : ''}
          </p>
          <p className="mt-1 text-[13px] leading-[1.6]">{ca.ghiChu}</p>
        </div>
      )}

      <label htmlFor="ghi-chu" className="mt-4 block text-than font-medium text-fg">
        Ghi chú kết quả
      </label>
      <textarea
        id="ghi-chu"
        value={chu}
        onChange={(e) => setChu(e.target.value)}
        rows={4}
        maxLength={2000}
        placeholder="Đã gọi lại, khách chốt xem nhà thứ Bảy 14h. Đã gửi bảng giá qua Zalo."
        className={`${O_CHUNG} mt-1.5 resize-y leading-[1.55]`}
      />

      {loi && (
        <p role="alert" className="mt-3 text-[13px] text-badge-alert-fg">
          Không lưu được: {loi}
        </p>
      )}

      <div className={`${HANG_NUT} mt-4`}>
        <button type="button" onClick={dong} className={NUT_PHU}>
          Huỷ
        </button>
        <button
          type="button"
          disabled={dangGui}
          onClick={() => luu(chu)}
          className={`${NUT_CHINH} transition-colors hover:bg-acd`}
        >
          Lưu và đánh dấu xong
        </button>
      </div>
    </HopThoai>
  )
}
