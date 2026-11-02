/**
 * Màn `/pricing` (Task 8) — dải token quản trị nền tảng + ba ô số + bảng danh
 * sách bộ giá + panel chi tiết một bộ giá (Task 9, `PanelBoGia.tsx`) + panel
 * gán bộ giá cho workspace (Task 10, `PanelGanWorkspace.tsx`, mở từ nút «Gán
 * workspace» cạnh «Bộ giá mới» ở dải công cụ mục ②).
 *
 * ⚠️ SỬA 2026-08-20 (review coordinator): bản đầu render hai ô «Bộ giá mặc
 * định»/«Bộ đang áp» là `<button onClick={() => {}}>` — viền focus, con trỏ
 * tay, tab tới được, bấm thì không gì xảy ra. Đó là ĐIỀU KHIỂN CHẾT, tệ hơn
 * không phải nút: người dùng bấm một lần, không thấy phản hồi, kết luận màn
 * lỗi rồi lần sau không bấm nữa. Task 8 để CẢ BA ô là `<div>` cho tới khi có
 * panel để mở.
 *
 * ⚠️ TASK 9: CHỈ «Bộ giá mặc định» đổi thành `<button>` (mở `PanelBoGia` cho
 * ĐÚNG bộ mặc định) — «Bộ đang áp» và «Tổ hợp chưa có giá» VẪN LÀ `<div>`.
 * Khác nhau ở CHỖ CÓ ĐÍCH: «Bộ giá mặc định» trỏ vào ĐÚNG MỘT bộ giá (có `id`),
 * còn «Bộ đang áp» là một PHÉP ĐẾM (có thể nhiều bộ đang active — bấm vào thì
 * mở panel cho bộ nào?) và «Tổ hợp chưa có giá» không có nguồn dữ liệu tách
 * dòng (đã ghi ở Task 8). Không có đích rõ ràng thì vẫn là `<div>`, kể cả sau
 * khi panel thật đã tồn tại — bấm một số đếm mở ra một bản ghi ngẫu nhiên còn
 * tệ hơn không mở gì.
 *
 * Hàng bảng ② mở panel cho ĐÚNG bộ giá của hàng đó — vừa qua click cả hàng
 * (`Hang mo={...}`, khuôn chuẩn `components/ui/Bang.tsx::Hang`) vừa qua một
 * `<button>` thật quanh tên bộ giá (bàn phím/trình đọc màn hình tới được —
 * `Hang` cố ý KHÔNG nhận focus bằng Tab, một phần tử tương tác thật trong
 * hàng là bắt buộc, xem docstring `Hang`). Nút đó cũng là điểm neo `oMoRef`
 * để trả focus đúng chỗ lúc đóng panel — cùng khuôn `oKichHoatRef`/`moPhien`
 * của `UsageScreen.tsx`.
 *
 * BA Ô KHÁC BẢN VẼ `docs/design/demo-usage-billing.html` (spec §0.7) — bản vẽ có
 * «Doanh thu kỳ này» (toàn nền tảng, KHÔNG có endpoint — `/billing/summary`
 * là per-tenant qua RLS) và «Workspace giá riêng» (cần `tenant_price_version`,
 * cũng không có endpoint). Ba ô THẬT, đúng nguồn:
 *
 *   · Bộ giá mặc định — `useBoGia()` → hàng `is_default`, hiện TÊN (20px sans,
 *     KHÔNG mono) + `code` (mono 12,5px) — ép tên vào mono chỉ vì hai ô kia là
 *     số thì tên đọc như mã máy.
 *   · Bộ đang áp — `useBoGia()` → đếm `status === 'active'`.
 *   · Tổ hợp chưa có giá — `/billing/summary` → `canh_bao.thieu_gia`, CHỈ là
 *     SỐ ĐẾM. `price_coverage_gap` không có endpoint trả DÒNG chi tiết nào —
 *     ô này KHÔNG PHẢI nút, một ô bấm được mà mở ra panel rỗng là hứa một thứ
 *     không có.
 *
 * ⚠️ HAI LUỒNG XÁC THỰC ĐỘC LẬP TRÊN CÙNG MỘT MÀN. Ô «Tổ hợp chưa có giá» đọc
 * `/billing/summary` — endpoint TENANT qua cookie phiên (`billing.read`),
 * KHÔNG cần token quản trị nền tảng. Hai ô kia + bảng danh sách đọc
 * `/admin/billing/*` — cần header `X-Platform-Admin-Token` (`docToken()`/
 * `luuToken()`, Task 3). Vì thế `useTongQuan()` gọi VÔ ĐIỀU KIỆN (không đợi
 * token). Bảng + hai ô kia gói TRONG nhánh `!coToken`: bài test "thiếu token"
 * canh KHÔNG có request tới `/api/v1/admin/billing/*`, và ẩn luôn nút «Bộ giá
 * mới» — mở dialog đó rồi gửi cũng gọi `POST /admin/billing/price-versions`,
 * không có lý do bày một nút dẫn thẳng tới một request sẽ luôn 401.
 *
 * DẢI TOKEN đầu màn: một dòng chữ mờ 12,5px — KHÔNG PHẢI dải cảnh báo, nó
 * không cảnh báo gì. Token lưu `sessionStorage` (Task 3), KHÔNG `localStorage`:
 * token quản trị nền tảng không được sống qua phiên trình duyệt.
 */
import { useRef, useState } from 'react'
import {
  Bang,
  DauBang,
  Hang,
  NUT_CHINH,
  NUT_PHU,
  O_LOC,
  PILL,
  PILL_SAT_TRAI,
  TheBang,
  ThanhCong,
  VungCuon,
} from '@/components/ui/Bang'
import { KhoRong, LoiTai } from '@/components/ui/TrangThai'
import { docToken, luuToken, useBoGia, useTaoBoGia, useTongQuan } from '../api'
import { SO, dinhDangLuc } from '../dinh-dang'
import { giaiMaKy } from '../ky'
import { thongDiep } from '../loi'
import type { BoGia } from '../kieu'
import { PanelBoGia } from './PanelBoGia'
import { PanelGanWorkspace } from './PanelGanWorkspace'
import { TaoBoGiaDialog } from './TaoBoGiaDialog'
import { SO_LON } from './lop'
import { TieuDeMuc } from './TieuDeMuc'

/**
 * Dải token quản trị nền tảng — MỘT DÒNG mờ (`text-phu text-muted`), ô
 * nhập `type="password"` + nút Lưu + pill trạng thái. Không phải dải cảnh báo
 * (không nền đỏ/vàng, không `role="alert"`) — thiếu token không phải một sự
 * cố, nó chỉ là chưa đăng nhập vào phần quản trị của màn này.
 */
function DaiToken({
  coToken,
  onLuu,
}: {
  readonly coToken: boolean
  readonly onLuu: (t: string) => void
}) {
  const [nhap, setNhap] = useState('')

  function guiForm(e: React.FormEvent) {
    e.preventDefault()
    if (nhap.trim() === '') return
    onLuu(nhap.trim())
    setNhap('')
  }

  return (
    <form
      onSubmit={guiForm}
      className="flex flex-none flex-wrap items-center gap-2 text-phu text-muted"
    >
      <label htmlFor="billing-admin-token">Token quản trị nền tảng</label>
      <input
        id="billing-admin-token"
        type="password"
        value={nhap}
        onChange={(e) => setNhap(e.target.value)}
        placeholder="X-Platform-Admin-Token"
        className={`${O_LOC} w-[260px]`}
      />
      <button type="submit" className={NUT_PHU}>
        Lưu
      </button>
      <span
        className={`${PILL} ${coToken ? 'bg-acs text-ac' : 'bg-badge-neutral-bg text-badge-neutral-fg'}`}
      >
        {coToken ? 'Đã có token' : 'Chưa có token'}
      </span>
    </form>
  )
}

const O_THE = 'flex flex-col gap-1.5 rounded-lg border border-border bg-surface p-4'
const NHAN_O = 'text-nhan font-semibold uppercase tracking-[.07em] text-muted-2'

/**
 * Ba ô — mục ①. CHỈ «Bộ giá mặc định» là `<button>` (khi `macDinh` đã tải
 * xong) — nó trỏ vào ĐÚNG MỘT bộ giá, có đích để mở panel. Hai ô còn lại VẪN
 * là `<div>` KHÔNG tương tác — xem docstring đầu file vì sao (không có đích
 * rõ ràng: một phép đếm, hoặc không có nguồn tách dòng).
 *
 * `macDinh`/`soDangAp` `undefined` ⇒ chưa sẵn sàng (đang tải hoặc lỗi) — ô
 * hiện «—», KHÔNG phân biệt hai lý do đó ở TỪNG Ô: trạng thái lỗi/tải thật
 * (với nút Thử lại) nằm ở bảng danh sách ngay dưới.
 */
function BaOSo({
  macDinh,
  soDangAp,
  thieuGia,
  onMoMacDinh,
}: {
  readonly macDinh: BoGia | undefined
  readonly soDangAp: number | undefined
  readonly thieuGia: number | undefined
  readonly onMoMacDinh: (id: number, el: HTMLElement) => void
}) {
  const coLoGia = thieuGia !== undefined && thieuGia > 0
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {macDinh ? (
        <button
          type="button"
          onClick={(e) => onMoMacDinh(macDinh.id, e.currentTarget)}
          className={`${O_THE} text-left transition-colors hover:border-fg/40`}
        >
          <h3 className={NHAN_O}>Bộ giá mặc định</h3>
          <p className="truncate text-[20px] leading-tight font-semibold text-fg">{macDinh.name}</p>
          <p className="font-mono text-phu text-muted">{macDinh.code}</p>
        </button>
      ) : (
        <div className={O_THE}>
          <h3 className={NHAN_O}>Bộ giá mặc định</h3>
          <p className={`${SO_LON} text-so text-muted-3`}>—</p>
        </div>
      )}

      <div className={O_THE}>
        <h3 className={NHAN_O}>Bộ đang áp</h3>
        <p className={`${SO_LON} text-so`}>{soDangAp !== undefined ? SO(soDangAp) : '—'}</p>
      </div>

      <div className={O_THE}>
        <h3 className={NHAN_O}>Tổ hợp chưa có giá</h3>
        <p className={`${SO_LON} text-so ${coLoGia ? 'text-badge-alert-fg' : 'text-fg'}`}>
          {thieuGia !== undefined ? SO(thieuGia) : '—'}
        </p>
      </div>
    </div>
  )
}

const O_HANG = 'px-4 py-3.5 align-middle'
const O_HANG_PHU = `${O_HANG} whitespace-nowrap text-nav`

const COT = [
  { nhan: 'Bộ giá' },
  { nhan: 'Trạng thái' },
  { nhan: 'Tiền tệ' },
  { nhan: 'Tạo lúc' },
  { nhan: '', phai: true },
] as const

export function BangGiaScreen() {
  const [coToken, setCoToken] = useState(() => Boolean(docToken()))
  const boGia = useBoGia()
  const { from, to } = giaiMaKy('thang-nay')
  const tongQuan = useTongQuan(from, to)
  const taoBoGia = useTaoBoGia()
  const [dialogMo, setDialogMo] = useState(false)
  const [panelId, setPanelId] = useState<number | null>(null)
  const [ganMo, setGanMo] = useState(false)
  // Điểm neo trả focus của `PanelGanWorkspace` (Task 10) — TÁCH khỏi `oMoRef`
  // bên dưới: `oMoRef` là của `PanelBoGia` (mở theo `id`, đóng bằng `dongPanel`),
  // còn panel gán workspace không gắn `id` nào và đóng bằng `dongGan` riêng.
  // Gộp chung một ref là trộn hai điểm neo focus của hai panel khác nhau.
  const oMoGanRef = useRef<HTMLElement | null>(null)

  // Phần tử đã mở panel (nút «Bộ giá mặc định», hoặc nút tên trong một hàng
  // bảng) — cùng khuôn `oKichHoatRef`/`moPhien` của `UsageScreen.tsx`: sống ở
  // ĐÂY vì cả nút mở lẫn `PanelBoGia` đều nằm dưới component này, không phải
  // state (đổi nó không cần vẽ lại gì, chỉ cần còn sống tới lúc đóng panel).
  const oMoRef = useRef<HTMLElement | null>(null)

  /**
   * ⚠️ SỬA sau review (2026-08-20): một hàng bảng mở panel qua HAI đường loại
   * trừ nhau — `Hang`'s `onClick` trên `<tr>` (bấm phần TRẦN của hàng) BỎ QUA
   * click phát từ phần tử tương tác (`closest(TU_BAM_DUOC)`, `Bang.tsx`), nên
   * bấm đúng nút tên đi đường `onClick` riêng của nút đó, còn bấm chỗ trống
   * còn lại của hàng đi đường `Hang mo={...}`. `Hang.mo` không nhận
   * event/element (chữ ký `mo?: () => void` — đọc `ui/Bang.tsx`, đây là
   * component DÙNG CHUNG cho cả portal, không đổi chữ ký chỉ vì một màn),
   * nên bản đầu chỉ gán `oMoRef` ở đường click-nút, để đường click-hàng-trần
   * giữ giá trị CŨ (`null` lần đầu, hoặc trỏ hàng mở TRƯỚC).
   *
   * KHÔNG thêm đường mở thứ ba, và KHÔNG đổi `Hang`. Map này ghi nhớ đúng
   * `<button>` tên của MỖI hàng (phần tử duy nhất trong hàng vừa tương tác
   * được vừa tới bằng bàn phím — `<tr>` tự nó không nhận `.focus()` vì không
   * `tabIndex`, gán `oMoRef` vào `<tr>` sẽ lặp lại đúng bug ref-callback vừa
   * sửa ở `PanelBoGia.tsx`). Cả hai đường mở (click nút, click hàng trần) giờ
   * hội tụ về ĐÚNG một target focus-được — `moPanel()` cho đường nút,
   * `Hang mo={() => moPanel(b.id, nutTenRef.current.get(b.id) ?? null)}` cho
   * đường hàng, tra đúng nút của hàng đó qua `b.id`.
   */
  const nutTenRef = useRef<Map<number, HTMLButtonElement>>(new Map())

  function dangKyNutTen(id: number, el: HTMLButtonElement | null): void {
    if (el) nutTenRef.current.set(id, el)
    else nutTenRef.current.delete(id)
  }

  function luuVaDatToken(t: string) {
    luuToken(t)
    setCoToken(Boolean(t))
  }

  function moDialog() {
    taoBoGia.reset()
    setDialogMo(true)
  }

  function moPanel(id: number, el: HTMLElement | null): void {
    oMoRef.current = el
    setPanelId(id)
  }

  /** Đóng qua CẢ BA đường của `PanelBoGia` (nút ×, click lớp phủ, Escape) —
   *  cả ba gọi ĐÚNG hàm này. */
  function dongPanel(): void {
    setPanelId(null)
    oMoRef.current?.focus()
  }

  function moGan(el: HTMLElement | null): void {
    oMoGanRef.current = el
    setGanMo(true)
  }

  /** Đóng qua CẢ BA đường của `PanelGanWorkspace` (Task 10) — cùng khuôn `dongPanel`. */
  function dongGan(): void {
    setGanMo(false)
    oMoGanRef.current?.focus()
  }

  const macDinh = coToken ? boGia.data?.find((b) => b.is_default) : undefined
  const soDangAp = coToken ? boGia.data?.filter((b) => b.status === 'active').length : undefined

  return (
    <div className="flex flex-col gap-4 p-6">
      <DaiToken coToken={coToken} onLuu={luuVaDatToken} />

      <TieuDeMuc
        so={1}
        tieuDe="Tổng quan"
        phu="Bộ giá mặc định, bộ đang áp, và tổ hợp còn thiếu giá."
      />
      <BaOSo
        macDinh={macDinh}
        soDangAp={soDangAp}
        thieuGia={tongQuan.data?.canh_bao.thieu_gia}
        onMoMacDinh={moPanel}
      />

      <TieuDeMuc
        so={2}
        tieuDe="Danh sách bộ giá"
        phu="Mỗi bộ giá là một tập giá áp cho một hoặc nhiều workspace."
      />

      {!coToken ? (
        <KhoRong
          tieuDe="Cần token quản trị nền tảng"
          huongDan="Nhập token ở dải phía trên để xem và tạo bộ giá."
        />
      ) : (
        <TheBang>
          <ThanhCong>
            <div className="ml-auto flex flex-none items-center gap-2">
              <button type="button" onClick={(e) => moGan(e.currentTarget)} className={NUT_PHU}>
                Gán workspace
              </button>
              <button type="button" onClick={moDialog} className={NUT_CHINH}>
                Bộ giá mới
              </button>
            </div>
          </ThanhCong>

          {boGia.isPending ? (
            <div className="h-[220px] animate-pulse bg-fill" />
          ) : boGia.error ? (
            <div className="p-4">
              <LoiTai viec="danh sách bộ giá" thuLai={() => void boGia.refetch()} />
            </div>
          ) : boGia.data.length === 0 ? (
            <div className="p-4">
              <KhoRong
                tieuDe="Chưa có bộ giá nào"
                huongDan="Bấm «Bộ giá mới» để tạo bộ giá đầu tiên."
              />
            </div>
          ) : (
            <VungCuon>
              <Bang nhan="Danh sách bộ giá">
                <DauBang cot={COT} />
                <tbody>
                  {boGia.data.map((b) => (
                    // `mo` tra ĐÚNG nút tên của hàng này qua `nutTenRef` (xem
                    // docstring cạnh khai báo `nutTenRef` phía trên) — đường
                    // click-hàng-trần và đường click-nút giờ hội tụ về CÙNG
                    // một `oMoRef`, không phải hai giá trị khác nhau.
                    <Hang key={b.id} mo={() => moPanel(b.id, nutTenRef.current.get(b.id) ?? null)}>
                      <td className={O_HANG}>
                        {/* `<button>` thật trong hàng (không chỉ `Hang`'s
                            onClick trên `<tr>`, vốn KHÔNG tới được bằng bàn
                            phím — xem docstring `Hang`) — cũng là điểm neo trả
                            focus lúc đóng panel, cho CẢ HAI đường mở. */}
                        <button
                          ref={(el) => dangKyNutTen(b.id, el)}
                          type="button"
                          onClick={(e) => moPanel(b.id, e.currentTarget)}
                          className="text-left text-than font-medium text-fg hover:text-ac hover:underline"
                        >
                          {b.name}
                        </button>
                        <p className="font-mono text-phu text-muted">{b.code}</p>
                      </td>
                      <td className={O_HANG}>
                        <span
                          className={`${PILL} ${PILL_SAT_TRAI} ${
                            b.status === 'active'
                              ? 'bg-acs text-ac'
                              : 'bg-badge-neutral-bg text-badge-neutral-fg'
                          }`}
                        >
                          {b.status === 'active' ? 'Đang dùng' : 'Đã tắt'}
                        </span>
                        {b.is_default && (
                          <span
                            className={`${PILL} ml-1.5 bg-badge-neutral-bg text-badge-neutral-fg`}
                          >
                            Mặc định
                          </span>
                        )}
                      </td>
                      <td className={`${O_HANG_PHU} font-mono`}>{b.currency}</td>
                      <td className={O_HANG_PHU}>{dinhDangLuc(b.created_at)}</td>
                      <td className={`${O_HANG} text-right text-muted-3`} aria-hidden>
                        ›
                      </td>
                    </Hang>
                  ))}
                </tbody>
              </Bang>
            </VungCuon>
          )}
        </TheBang>
      )}

      {dialogMo && (
        <TaoBoGiaDialog
          dangGui={taoBoGia.isPending}
          loi={taoBoGia.error ? thongDiep(taoBoGia.error, 'Không tạo được bộ giá') : null}
          onDong={() => setDialogMo(false)}
          onTao={(b) => taoBoGia.mutate(b, { onSuccess: () => setDialogMo(false) })}
        />
      )}

      {panelId !== null && <PanelBoGia key={panelId} pbId={panelId} onDong={dongPanel} />}
      {ganMo && <PanelGanWorkspace onDong={dongGan} />}
    </div>
  )
}
