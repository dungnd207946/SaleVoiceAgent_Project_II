/**
 * Slide-over chi tiết MỘT bộ giá (Task 9) — form thêm dòng giá + preview
 * per-tenant + kích hoạt. Mở từ `BangGiaScreen.tsx` (ô «Bộ giá mặc định» hoặc
 * một hàng trong bảng danh sách).
 *
 * KHUÔN LỚP NỔI cùng `features/billing/components/ChiTietPhien.tsx` (Task 6)
 * — đóng qua CẢ BA đường (nút ×, bấm nền, Escape), trả focus về đúng phần tử đã mở nó
 * (`BangGiaScreen` truyền `onDong` sau khi tự giữ ref, cùng cơ chế
 * `oKichHoatRef`/`moPhien` của `UsageScreen.tsx`). Vỏ dialog (`<dialog>` qua
 * `HopThoai`) dùng CHUNG `./PanelKhung` (review 2026-08-20 — trước đó ba nơi
 * trong module này giữ ba bản COPY NGUYÊN VĂN, xem docstring `PanelKhung.tsx`).
 *
 * ⚠️ KHÔNG có endpoint đọc `price_item` của một bộ giá (`liet_ke_bang_gia`
 * chỉ trả metadata — `id, code, name, currency, status, is_default,
 * created_at`). Panel vì thế KHÔNG hiện được bảng dòng giá đã nhập, CHỈ hiện
 * form THÊM dòng — không có bảng rỗng nào cả (một bảng rỗng không giải thích
 * trông như dữ liệu chưa tải xong), thay vào đó một dòng chữ mờ nói thẳng lý
 * do. Muốn biết một bộ giá đã đủ dòng hay chưa: dùng «Preview» (xem có tính
 * ra số hợp lý không) hoặc bấm «Kích hoạt» (BE tự đối chiếu `pricing_basis`,
 * trả `409 BANG_GIA_CON_LO` kèm danh sách còn thiếu nếu chưa đủ).
 *
 * ⚠️ `usePreview()` cần `tenant` — bộ chọn Workspace lấy từ `useSession()`
 * (`lib/session.tsx`). `PreviewGia` trả MỘT tổng (camelCase, xem `kieu.ts`),
 * KHÔNG tách theo component — không có nguồn cho việc đó.
 *
 * ⚠️ «Tổng hiện tại» để so sánh chỉ đọc được cho ĐÚNG workspace hiện tại của
 * phiên đăng nhập: `GET /billing/summary` xác thực bằng cookie phiên và tự
 * suy tenant từ đó (`p.tenant_id`, không nhận tham số `tenant`) — khác hẳn
 * `usePreview()` (admin, nhận `tenant` tường minh). Nên khi Workspace được
 * CHỌN để preview KHÔNG PHẢI workspace hiện tại của phiên, panel không có
 * cách nào đọc "tổng hiện tại" của tenant đó — chỉ hiện số preview MỚI, không
 * bịa ra một con số "cũ" sai tenant. So sánh cũ→mới→Δ chỉ hiện khi hai tenant
 * trùng nhau.
 *
 * ⚠️ Luật «STT chỉ MỘT cơ sở» đã HẸP LẠI từ migration `0948` — chỉ cặp THỜI
 * LƯỢNG (`STT_THOI_LUONG` = `audio_sec`/`wall_ms`) loại trừ nhau; `text_units`
 * ĐỘC LẬP, cộng thêm. `metricBiKhoa()` dưới đây CHỈ khoá option thời lượng
 * còn lại khi metric ĐANG CHỌN cũng là thời lượng — khoá sai (vd khoá luôn
 * `text_units`) là chặn một dòng giá hợp lệ.
 *
 * ⚠️ Body `POST .../items`: CHỈ `unitPrice`/`perUnits` camelCase, phần còn lại
 * (`component`/`purpose`/`provider`/`model`/`metric`/`note`) giữ tên thường —
 * BE không khai `populate_by_name`, gửi sai tên là `422`, không phải bị bỏ
 * qua im lặng (xem `kieu.ts::DongGiaIn`). `unitPrice` giữ NGUYÊN chuỗi người
 * gõ — KHÔNG qua `Number()` (đó là tiền, `numeric(20,10)`), nên ô "Đơn giá"
 * ở đây là `<input type="text">` viết tay, không dùng `OSo` (component đó tự
 * `Number()` giá trị).
 *
 * `purpose` là `<select>` liệt kê `PURPOSE_TINH_KHACH` (`pricingBasis.ts`) +
 * một lựa chọn rỗng "mọi purpose" — bốn purpose `billable = false` KHÔNG xuất
 * hiện, vì tạo dòng giá cho chúng là dòng không bao giờ khớp (xem docstring
 * của hằng đó).
 *
 * «Kích hoạt» `disabled` tới khi `usePreview()` đã CHẠY THÀNH CÔNG cho đúng
 * `pbId` này trong phiên hiện tại — theo dõi bằng chính `previewQ.isSuccess`
 * (query chỉ `enabled` sau khi bấm nút «Preview», xem `tenantXacNhan` bên
 * dưới — CHỌN workspace không tự bắn request). Panel mount lại (đổi `pbId`,
 * `key` ở `BangGiaScreen`) reset trạng thái này về `false` — đúng nghĩa
 * "preview cho ĐÚNG bộ này", không phải "đã preview bộ nào đó".
 */
import { useId, useState, type ReactNode } from 'react'
import { HANG_NUT, NUT_CHINH, NUT_PHU, PILL } from '@/components/ui/Bang'
import { O_CHUNG, OChiDoc, OChon, OChu, DongTrangThai } from '@/components/ui/Truong'
import { useSession } from '@/lib/session'
import { useBoGia, useKichHoat, usePreview, useThemDongGia, useTongQuan } from '../api'
import { tien } from '../dinh-dang'
import { giaiMaKy } from '../ky'
import { thongDiep } from '../loi'
import {
  PRICING_BASIS,
  PURPOSE_TINH_KHACH,
  STT_THOI_LUONG,
  basisCua,
  metricCua,
} from '../pricingBasis'
import type { DongGiaIn } from '../kieu'
import { PanelKhung } from './PanelKhung'

/** Component duy nhất, đúng thứ tự xuất hiện trong `PRICING_BASIS`. */
const DS_COMPONENT: readonly string[] = [...new Set(PRICING_BASIS.map((b) => b.component))]

/** Nhãn hiển thị của metric — copy tay từ cột `label` của `billing.metric`
 *  (`pricing-schema.sql` §1), chỉ giữ các metric THẬT SỰ dùng để tính giá
 *  (bỏ `units`/`event_count` — metric phụ, không nằm trong `pricing_basis`). */
const TEN_METRIC: Record<string, string> = {
  input_tokens: 'Input token',
  output_tokens: 'Output token',
  cache_read_tokens: 'Cache read token',
  cache_write_tokens: 'Cache write token',
  audio_sec: 'Thời lượng audio (audio_sec)',
  text_units: 'Ký tự text (text_units)',
  wall_ms: 'Thời gian kết nối (wall_ms)',
}

/** Khoá option thời lượng CÒN LẠI khi metric đang chọn cũng là thời lượng —
 *  xem docstring đầu file. `text_units` không bao giờ bị khoá bởi hàm này. */
function metricBiKhoa(m: string, hienTai: string, component: string): boolean {
  if (component !== 'stt') return false
  const thoiLuong = (v: string): v is (typeof STT_THOI_LUONG)[number] =>
    (STT_THOI_LUONG as readonly string[]).includes(v)
  return thoiLuong(m) && thoiLuong(hienTai) && m !== hienTai
}

/** Form thêm MỘT dòng giá — sinh option từ `pricing_basis`, đơn vị hiện
 *  thành chữ ngay trong ô nhập, `perUnits` không cho gõ tay. */
function FormThemDongGia({ pbId }: { readonly pbId: number }) {
  const [component, setComponent] = useState(DS_COMPONENT[0] ?? '')
  const [metric, setMetric] = useState(() => metricCua(DS_COMPONENT[0] ?? '')[0]?.metric ?? '')
  const [purpose, setPurpose] = useState('')
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [unitPrice, setUnitPrice] = useState('')
  const [note, setNote] = useState('')
  const themDongGia = useThemDongGia(pbId)
  const idGia = useId()

  const dsMetric = metricCua(component)
  const basis = basisCua(component, metric)

  function chonComponent(c: string) {
    setComponent(c)
    setMetric(metricCua(c)[0]?.metric ?? '')
    setPurpose('')
  }

  function guiForm(e: React.FormEvent) {
    e.preventDefault()
    if (themDongGia.isPending || unitPrice.trim() === '' || metric === '') return
    const body: DongGiaIn = {
      component,
      purpose,
      provider: provider.trim(),
      model: model.trim(),
      metric,
      // ⚠️ KHÔNG Number(): tiền giữ nguyên chuỗi người gõ.
      unitPrice: unitPrice.trim(),
      perUnits: basis?.per_units ?? 1,
      note: note.trim(),
    }
    themDongGia.mutate(body, {
      onSuccess: () => {
        setUnitPrice('')
        setProvider('')
        setModel('')
        setNote('')
      },
    })
  }

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-col gap-0.5">
        <h3 className="text-than font-semibold text-fg">Thêm dòng giá</h3>
        <p className="text-nhan text-muted-2">
          Chưa có cách xem lại các dòng giá đã nhập cho bộ này — chưa có endpoint đọc `price_item`.
          Dùng «Preview» hoặc «Kích hoạt» để biết bộ giá đã đủ hay còn thiếu.
        </p>
      </div>

      <form onSubmit={guiForm} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <OChon
          ten="component"
          nhan="Component"
          giaTri={component}
          doi={chonComponent}
          muc={DS_COMPONENT.map((c) => ({ value: c, nhan: c.toUpperCase() }))}
        />

        <div>
          <label htmlFor={`${idGia}-metric`} className="mb-1.5 block text-phu text-muted">
            Metric
          </label>
          <select
            id={`${idGia}-metric`}
            value={metric}
            onChange={(e) => setMetric(e.target.value)}
            className={`${O_CHUNG} o-chon`}
          >
            {dsMetric.map((b) => (
              <option
                key={b.metric}
                value={b.metric}
                disabled={metricBiKhoa(b.metric, metric, component)}
              >
                {TEN_METRIC[b.metric] ?? b.metric}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label htmlFor={idGia} className="mb-1.5 block text-phu text-muted">
            Đơn giá
          </label>
          <div className="flex items-center gap-2">
            {/* KHÔNG `type="number"` / `OSo` — giá là tiền, giữ nguyên chuỗi
                người gõ, không đi qua `Number()`. */}
            <input
              id={idGia}
              value={unitPrice}
              onChange={(e) => setUnitPrice(e.target.value)}
              placeholder="vd: 0.126"
              className={`${O_CHUNG} font-mono`}
            />
            <span className="flex-none whitespace-nowrap text-phu text-muted-2">
              {basis?.dvi ?? '—'}
            </span>
          </div>
        </div>

        <OChiDoc nhan="Per units" giaTri={String(basis?.per_units ?? '—')} />

        <OChon
          ten="purpose"
          nhan="Purpose"
          giaTri={purpose}
          doi={setPurpose}
          nhanRong="Mọi purpose"
          muc={PURPOSE_TINH_KHACH.map((p) => ({ value: p, nhan: p }))}
        />
        <OChu ten="provider" nhan="Provider" giaTri={provider} doi={setProvider} />
        <OChu ten="model" nhan="Model" giaTri={model} doi={setModel} />
        <div className="sm:col-span-2">
          <OChu ten="note" nhan="Ghi chú" giaTri={note} doi={setNote} hangChu={2} />
        </div>

        {themDongGia.isError && (
          <div className="sm:col-span-2">
            <DongTrangThai mau="alert">
              {thongDiep(themDongGia.error, 'Không thêm được dòng giá')}
            </DongTrangThai>
          </div>
        )}
        {themDongGia.isSuccess && (
          <div className="sm:col-span-2">
            <DongTrangThai mau="ok">Đã thêm dòng giá.</DongTrangThai>
          </div>
        )}

        <div className={`sm:col-span-2 ${HANG_NUT}`}>
          <button
            type="submit"
            disabled={themDongGia.isPending || unitPrice.trim() === ''}
            className={NUT_CHINH}
          >
            {themDongGia.isPending ? 'Đang thêm…' : 'Thêm dòng'}
          </button>
        </div>
      </form>
    </section>
  )
}

/** Bộ chọn Workspace + Preview + so sánh cũ→mới→Δ + nút Kích hoạt. */
function KhuPreviewVaKichHoat({
  pbId,
  trangThai,
}: {
  readonly pbId: number
  readonly trangThai: string
}) {
  const { session, currentWorkspace } = useSession()
  const [tenantChon, setTenantChon] = useState('')
  const [tenantXacNhan, setTenantXacNhan] = useState('')
  const previewQ = usePreview(pbId, tenantXacNhan)
  const kichHoat = useKichHoat(pbId)

  // «Tổng hiện tại» chỉ đọc được cho ĐÚNG workspace hiện tại của phiên — xem
  // docstring đầu file. `useTongQuan()` không nhận tham số tenant.
  const { from, to } = giaiMaKy('30-ngay')
  const tongQuanQ = useTongQuan(from, to)
  const cungTenantHienTai = tenantXacNhan !== '' && tenantXacNhan === currentWorkspace.id

  function guiPreview() {
    if (tenantChon === '') return
    setTenantXacNhan(tenantChon)
  }

  const daPreviewXong = previewQ.isSuccess && Boolean(previewQ.data)
  const dangKichHoat = trangThai === 'active'

  return (
    <section className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <h3 className="text-than font-semibold text-fg">Preview &amp; kích hoạt</h3>

      <OChon
        ten="workspace"
        nhan="Workspace"
        giaTri={tenantChon}
        doi={setTenantChon}
        nhanRong="Chọn workspace"
        muc={session.workspaces.map((w) => ({ value: w.id, nhan: w.name }))}
      />

      <div className={HANG_NUT}>
        <button
          type="button"
          onClick={guiPreview}
          disabled={tenantChon === '' || previewQ.isFetching}
          className={NUT_PHU}
        >
          {previewQ.isFetching ? 'Đang preview…' : 'Preview'}
        </button>
        <button
          type="button"
          onClick={() => kichHoat.mutate()}
          disabled={!daPreviewXong || dangKichHoat || kichHoat.isPending}
          className={`${NUT_CHINH} ml-2`}
        >
          {kichHoat.isPending ? 'Đang kích hoạt…' : dangKichHoat ? 'Đã kích hoạt' : 'Kích hoạt'}
        </button>
      </div>

      {previewQ.isError && (
        <DongTrangThai mau="alert">
          {thongDiep(previewQ.error, 'Không preview được bộ giá này')}
        </DongTrangThai>
      )}

      {daPreviewXong && previewQ.data && (
        <div className="flex flex-wrap items-end gap-4 rounded-md bg-fill px-3 py-2.5">
          {cungTenantHienTai && tongQuanQ.data && (
            <div className="flex flex-col gap-0.5">
              <span className="text-nhan font-semibold uppercase tracking-[.07em] text-muted-2">
                Hiện tại (30 ngày)
              </span>
              <span className="font-mono text-phu text-muted">
                {tien(tongQuanQ.data.chi_phi)} {tongQuanQ.data.currency}
              </span>
            </div>
          )}
          <div className="flex flex-col gap-0.5">
            <span className="text-nhan font-semibold uppercase tracking-[.07em] text-muted-2">
              Nếu dùng bộ này
            </span>
            {/* 20px — số nổi bật DUY NHẤT của panel này. */}
            <span className="text-[20px] leading-none font-semibold text-fg">
              {tien(previewQ.data.chiPhi)}{' '}
              <span className="text-phu font-normal text-muted">{previewQ.data.currency}</span>
            </span>
          </div>
          {cungTenantHienTai && tongQuanQ.data && (
            <ChenhLech cu={tongQuanQ.data.chi_phi} moi={previewQ.data.chiPhi} />
          )}
        </div>
      )}

      {!cungTenantHienTai && daPreviewXong && (
        <p className="text-nhan text-muted-2">
          Workspace đang xem preview khác workspace hiện tại của phiên đăng nhập — không đọc được
          "tổng hiện tại" của nó để so sánh (`/billing/summary` chỉ đọc theo phiên).
        </p>
      )}

      {kichHoat.isError && (
        // Hiện NGUYÊN VĂN message của BE (`409 BANG_GIA_CON_LO` đã liệt kê rõ
        // tổ hợp còn thiếu và hướng xử lý) — đừng viết lại.
        <DongTrangThai mau="alert">
          {thongDiep(kichHoat.error, 'Không kích hoạt được bộ giá này')}
        </DongTrangThai>
      )}
      {kichHoat.isSuccess && <DongTrangThai mau="ok">Đã kích hoạt.</DongTrangThai>}
    </section>
  )
}

/** `(moi - cu) / cu * 100` — CHỈ dùng `Number()` cho một tỉ lệ HIỂN THỊ (đã
 *  làm tròn 1 chữ số thập phân qua `Intl`, không phải một tổng tiền phải
 *  chính xác tuyệt đối như luật ở `dinh-dang.ts`). */
function ChenhLech({ cu, moi }: { readonly cu: string; readonly moi: string }) {
  const cuNum = Number(cu)
  const moiNum = Number(moi)
  if (!Number.isFinite(cuNum) || cuNum === 0) return null
  const phanTramThayDoi = ((moiNum - cuNum) / cuNum) * 100
  const dau = phanTramThayDoi >= 0 ? '+' : ''
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-nhan font-semibold uppercase tracking-[.07em] text-muted-2">Δ</span>
      <span
        className={`font-mono text-phu font-semibold ${
          phanTramThayDoi > 0
            ? 'text-badge-alert-fg'
            : phanTramThayDoi < 0
              ? 'text-acd'
              : 'text-muted'
        }`}
      >
        {dau}
        {phanTramThayDoi.toLocaleString('vi-VN', {
          minimumFractionDigits: 1,
          maximumFractionDigits: 1,
        })}
        %
      </span>
    </div>
  )
}

export function PanelBoGia({
  pbId,
  onDong,
}: {
  readonly pbId: number
  /** Đóng qua CẢ BA đường (nút ×, click lớp phủ, Escape) — component KHÔNG tự
   *  biết cách xoá state đang mở panel ở `BangGiaScreen`, chỉ gọi hàm này. */
  readonly onDong: () => void
}) {
  const boGia = useBoGia()
  const pb = boGia.data?.find((b) => b.id === pbId)
  const idTieuDe = useId()

  let noiDung: ReactNode
  if (boGia.isPending) {
    noiDung = (
      <div className="flex-1 p-5">
        <h2 id={idTieuDe} className="sr-only">
          Chi tiết bộ giá
        </h2>
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="h-10 animate-pulse rounded-md bg-fill" />
          ))}
        </div>
      </div>
    )
  } else if (!pb) {
    noiDung = (
      <div className="flex-1 p-5">
        <h2 id={idTieuDe} className="sr-only">
          Chi tiết bộ giá
        </h2>
        <p className="text-phu text-muted">Không tìm thấy bộ giá này.</p>
      </div>
    )
  } else {
    noiDung = (
      <>
        <div className="flex flex-none items-start justify-between gap-4 border-b border-border-soft px-5 py-4 pr-14">
          <div className="flex min-w-0 flex-col gap-1.5">
            <h2 id={idTieuDe} className="truncate text-muc font-semibold text-fg">
              {pb.name}
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-phu text-muted">{pb.code}</span>
              <span
                className={`${PILL} ${
                  pb.status === 'active'
                    ? 'bg-acs text-ac'
                    : 'bg-badge-neutral-bg text-badge-neutral-fg'
                }`}
              >
                {pb.status === 'active' ? 'Đang dùng' : 'Đã tắt'}
              </span>
              {pb.is_default && (
                <span className={`${PILL} bg-badge-neutral-bg text-badge-neutral-fg`}>
                  Mặc định
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-5">
          <KhuPreviewVaKichHoat pbId={pbId} trangThai={pb.status} />
          <FormThemDongGia pbId={pbId} />
        </div>
      </>
    )
  }

  return (
    <PanelKhung idTieuDe={idTieuDe} onDong={onDong}>
      {noiDung}
    </PanelKhung>
  )
}
