/**
 * Ô nhập dùng chung của mọi form trong portal — label + control + lỗi field.
 *
 * ⚠️ FILE NÀY TRƯỚC Ở `features/realestate/components/OTruong.tsx`, và docstring
 * của nó đã ghi sẵn: Chỗ dùng chung thật sự thì phải nằm ở `components/`, việc
 * đó để lần dọn sau. Lần dọn đó là đây — form user của M2b cần đúng những ô
 * này, và `tests/module-boundaries.test.ts` (Luật 3) cấm `features/auth` import
 * ruột `features/realestate`. (Shim `export *` ở chỗ cũ đã gỡ 2026-10-06.)
 *
 * VÌ SAO TÁCH: sáu thực thể cộng lại có ~60 ô. Viết tay từng ô nghĩa là 60 lần
 * lặp cùng bốn thứ (label, dấu `*`, lỗi field, khoảng cách), và lần thứ 60 sẽ
 * thiếu một trong bốn — thường là lỗi field, tức một ô đỏ mà không nói vì sao.
 *
 * BA QUY TẮC CHUNG NẰM Ở ĐÂY, KHÔNG Ở CHỖ GỌI:
 *   · Ô số rỗng gửi `null`, KHÔNG gửi `""` — cột `numeric` nullable ở DB nhận
 *     `null`; `""` thì Pydantic trả 422 và người dùng thấy "lỗi" khi họ chỉ đơn
 *     giản là không nhập.
 *   · `aria-invalid` + `aria-describedby` — trình đọc màn hình phải nghe được
 *     GỢI Ý (lúc bình thường) và LÝ DO (lúc lỗi), không chỉ thấy viền đổi màu.
 *   · Lỗi hiện NGAY DƯỚI ô, không gom về đầu form: 60 ô thì một danh sách lỗi ở
 *     đầu form buộc người dùng tự dò xem "mediaUrl" là ô nào.
 *
 * ─── Diện mạo ───────────────────────────────────────────────────────────────
 * Khung ô nhập, thẻ nhóm và dòng cảnh báo lấy ĐÚNG lớp của
 * `features/agent/components/AgentStudio.tsx` (màn M5, đã chốt với chủ sản phẩm).
 *
 * NGOẠI LỆ: `OChonNhieu` KHÔNG còn dùng chip bo tròn của AgentStudio — xem
 * docstring của nó. Quy ước hiện tại: pill bo tròn = chọn-MỘT / bộ lọc, ô token
 * = trường chọn-NHIỀU trong form nhập liệu.
 */
import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useDongKhiRaNgoai } from '@/lib/dongKhiRaNgoai'
import { so } from '@/lib/dinhDang'

/** Một lựa chọn của `OChon`/`OChonNhieu`. Cùng hình dạng `realestate/enums.MucChon`. */
export interface MucChon {
  readonly value: string
  readonly nhan: string
}

/**
 * Khung ô nhập — `focus:ring` là ĐIỀU KIỆN TIẾP CẬN, không phải trang trí:
 * `outline-none` mà không thay bằng dấu hiệu focus khác là lấy đi mốc duy nhất
 * của người dùng bàn phím.
 *
 * Placeholder nghiêng + 13px để ví dụ không bị đọc thành dữ liệu đã gõ, và sắc
 * riêng `--color-placeholder` (nhạt hơn `muted-3`). Nó chỉ render khi ô ĐANG SỬA:
 * ở chế độ xem, một ví dụ mờ trong ô rỗng bị đọc thành dữ liệu thật.
 */
export const O_CHUNG =
  'w-full rounded-md border border-border-field bg-surface px-3 py-[10px] text-noi outline-none transition-colors placeholder:text-than placeholder:italic focus:border-ac focus:ring-2 focus:ring-ac/15 max-md:text-base'
const O_LOI = 'border-badge-alert-fg focus:border-badge-alert-fg focus:ring-badge-alert-fg/15'

// Ô bị khoá hiện như giá trị đã điền (nhãn và chữ), không hiện ô nhập mờ.
const EMPTY_VALUE = <span className="text-muted-3">—</span>

export function ReadField({
  label,
  hideLabel,
  children,
}: {
  label: string
  hideLabel?: boolean | undefined
  children: ReactNode
}) {
  return (
    <dl className="m-0 min-w-0">
      <dt className={hideLabel ? 'sr-only' : 'mb-1 text-phu text-muted'}>{label}</dt>
      <dd className="m-0 text-noi leading-[1.5] text-fg">{children}</dd>
    </dl>
  )
}

function LongText({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement>(null)
  const [open, setOpen] = useState(false)
  const [overflow, setOverflow] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (el) setOverflow(el.scrollHeight > el.clientHeight + 1)
  }, [text])
  return (
    <>
      <p
        ref={ref}
        className={`max-w-[78ch] whitespace-pre-line leading-[1.7] text-n10 ${open ? '' : 'line-clamp-6'}`}
      >
        {text}
      </p>
      {(overflow || open) && (
        <button
          type="button"
          className="mt-1 text-than font-medium text-ac hover:text-acd"
          onClick={() => setOpen(!open)}
        >
          {open ? 'Thu gọn' : 'Xem thêm'}
        </button>
      )}
    </>
  )
}

/** id của phần tử mô tả một ô: lỗi nếu có, ngược lại là gợi ý. */
function idMoTa(ten: string, goiY?: string | undefined, loi?: string | undefined) {
  if (loi) return `${ten}-loi`
  if (goiY) return `${ten}-goiy`
  return undefined
}

interface KhungProps {
  ten: string
  nhan: string
  batBuoc?: boolean | undefined
  /** Câu giải thích dưới ô — dùng cho field mà tên không tự nói hết. */
  goiY?: string | undefined
  loi?: string | undefined
  children: ReactNode
}

/**
 * Dấu `*` đỏ của ô bắt buộc. ẨN với trình đọc màn hình — tên ô từng đọc ra «Tên
 * thương mại *» (đọc một ký tự sao, audit 05/10); nghĩa «bắt buộc» đi qua
 * `aria-required` của chính ô, hoặc chữ sr-only (`docRa`) ở `<legend>` của một
 * nhóm, vì `fieldset` không mang `aria-required`.
 */
function DauBatBuoc({ docRa }: { docRa?: boolean }) {
  return (
    <>
      <span className="text-badge-alert-fg" title="Bắt buộc" aria-hidden="true">
        {' '}
        *
      </span>
      {docRa && <span className="sr-only"> (bắt buộc)</span>}
    </>
  )
}

/** Gợi ý + lỗi đứng NGOÀI `<label>` (audit 05/10): trong label thì chúng nhập vào
 *  TÊN của ô, và trình đọc màn hình đọc cả câu gợi ý mỗi lần focus — chúng đã tới
 *  ô qua `aria-describedby` rồi. */
function Khung({ ten, nhan, batBuoc, goiY, loi, children }: KhungProps) {
  return (
    <div>
      <label className="block">
        <span className="mb-1.5 block text-phu text-muted">
          {nhan}
          {batBuoc && <DauBatBuoc />}
        </span>
        {children}
      </label>
      {goiY && !loi && (
        <span className="mt-1 block text-phu leading-[1.45] text-muted-2" id={`${ten}-goiy`}>
          {goiY}
        </span>
      )}
      {loi && (
        <span
          className="mt-1 block text-phu leading-[1.45] font-medium text-badge-alert-fg"
          id={`${ten}-loi`}
        >
          {loi}
        </span>
      )}
    </div>
  )
}

interface ChuProps {
  ten: string
  nhan: string
  giaTri: string
  doi: (v: string) => void
  batBuoc?: boolean | undefined
  goiY?: string | undefined
  loi?: string | undefined
  /** Không sửa được — dùng cho `projectCode` lúc PATCH (khoá nghiệp vụ). */
  khoa?: boolean | undefined
  hangChu?: number | undefined
  /** `email` · `tel` — mở đúng bàn phím trên mobile và bật validate của trình duyệt. */
  loai?: 'text' | 'email' | 'tel' | undefined
  /** Chữ mờ trong ô rỗng. */
  goiYTrongO?: string | undefined
  /**
   * `required` của HTML — TÁCH khỏi `batBuoc`.
   *
   * `batBuoc` chỉ vẽ dấu `*`; năm form của realestate dựa vào đúng hành vi đó
   * (chúng để backend trả 422 làm nguồn sự thật, và một `required` thầm thêm vào
   * sẽ chặn submit ở những ô mà trước giờ submit được). Ô nào muốn trình duyệt
   * chặn thật thì nói ra ở đây.
   */
  chanTrong?: boolean | undefined
  /** Rời ô — chỗ nối của `useLuuTungO`: `doi` gõ, `xong` gửi. */
  xong?: (() => void) | undefined
  /** Ở chế độ xem không hiện nhãn — khi tiêu đề thẻ đã là tên ô. */
  hideLabelInView?: boolean | undefined
}

/** Ô chữ một dòng, hoặc `textarea` khi có `hangChu`. */
export function OChu({
  ten,
  nhan,
  giaTri,
  doi,
  batBuoc,
  goiY,
  loi,
  khoa,
  hangChu,
  loai = 'text',
  goiYTrongO,
  chanTrong,
  xong,
  hideLabelInView,
}: ChuProps) {
  if (khoa)
    return (
      <ReadField label={nhan} hideLabel={hideLabelInView}>
        {giaTri.trim() === '' ? EMPTY_VALUE : hangChu ? <LongText text={giaTri} /> : giaTri}
      </ReadField>
    )
  const chung = `${O_CHUNG} ${loi ? O_LOI : ''}`
  return (
    <Khung ten={ten} nhan={nhan} batBuoc={batBuoc} goiY={goiY} loi={loi}>
      {hangChu ? (
        <textarea
          name={ten}
          rows={hangChu}
          value={giaTri}
          placeholder={goiYTrongO}
          onChange={(e) => doi(e.target.value)}
          onBlur={xong}
          aria-invalid={!!loi}
          aria-required={batBuoc || undefined}
          aria-describedby={idMoTa(ten, goiY, loi)}
          className={`${chung} leading-[1.55]`}
        />
      ) : (
        <input
          name={ten}
          type={loai}
          value={giaTri}
          required={chanTrong}
          placeholder={goiYTrongO}
          onChange={(e) => doi(e.target.value)}
          onBlur={xong}
          aria-invalid={!!loi}
          aria-required={batBuoc || undefined}
          aria-describedby={idMoTa(ten, goiY, loi)}
          className={chung}
        />
      )}
    </Khung>
  )
}

/**
 * Ô CHỈ ĐỌC — nhãn + giá trị + một chip nói vì sao không sửa được.
 *
 * Không phải `<input disabled>`: một ô nhập bị làm mờ vẫn nói đây là ô của
 * bạn, tạm thời khoá, trong khi Tổ chức thì KHÔNG BAO GIỜ sửa được từ màn này
 * (backend suy `org_id` từ phiên và bỏ qua mọi thứ client gửi). Hai chuyện khác
 * nhau nên trông khác nhau — và một `<p>` thì Tab không dừng lại ở đó, đúng: nó
 * không có gì để làm.
 */
export function OChiDoc({
  nhan,
  giaTri,
  chip,
}: {
  nhan: string
  giaTri: ReactNode
  chip?: string | undefined
}) {
  return (
    <div className="block">
      <span className="mb-1.5 block text-phu text-muted">{nhan}</span>
      <p className="flex min-h-[42px] flex-wrap items-center gap-2 rounded-md border border-dashed border-border-strong bg-border-soft/60 px-3 py-[10px] text-noi text-fg">
        <span className="font-medium">{giaTri}</span>
        {chip && (
          <span className="rounded bg-badge-neutral-bg px-1.5 py-0.5 text-phu font-medium text-badge-neutral-fg">
            {chip}
          </span>
        )}
      </p>
    </div>
  )
}

interface SoProps {
  ten: string
  nhan: string
  giaTri: number | null
  doi: (v: number | null) => void
  batBuoc?: boolean | undefined
  goiY?: string | undefined
  loi?: string | undefined
  min?: number | undefined
  max?: number | undefined
  /** `1` = số nguyên (tầng, phòng ngủ); `any` = thập phân (diện tích, giá). */
  buoc?: number | 'any' | undefined
  /**
   * Chữ mờ trong ô rỗng — với ô SỐ thì đây là chỗ nói ĐƠN VỊ VÀ ĐỘ LỚN mong đợi.
   *
   * Nhãn Giá bán (VND) không phân biệt được 5.6 với 5600000000, và `goiY` bên
   * dưới thì người dùng đọc sau khi đã nhập sai. Một con số mẫu ngay trong ô
   * (5600000000) nói đúng thứ cần nói trước lúc gõ.
   */
  goiYTrongO?: string | undefined
  /** Rời ô — xem `ChuProps.xong`. */
  xong?: (() => void) | undefined
  khoa?: boolean | undefined
  /** Đơn vị: đứng sau số ở chế độ xem, nằm cuối ô nhập khi sửa. */
  unit?: string | undefined
  /** Cách hiện số ở chế độ xem, thay cho số kèm đơn vị. */
  format?: ((n: number) => ReactNode) | undefined
}

/**
 * Ô số. Rỗng ⇒ `null`.
 *
 * `value={giaTri ?? ''}` chứ không `?? 0`: một ô diện tích hiện `0` lúc chưa nhập
 * làm người dùng tưởng đã có dữ liệu, và nếu họ bấm Lưu thì `0` được ghi thật —
 * `completeness.ts` coi `0` là ĐÃ NHẬP (đúng theo DB), nên căn đó publish được
 * với diện tích 0 m². Ô rỗng thì `thieuTruongCan` bắt được.
 *
 * `font-mono`: chữ số bảng (tabular) cho cột số — giá 5.600.000.000 và 560.000.000
 * đọc lệch nhau ngay nếu chữ số không cùng bề rộng.
 */
export function OSo({
  ten,
  nhan,
  giaTri,
  doi,
  batBuoc,
  goiY,
  loi,
  khoa,
  min,
  max,
  buoc = 'any',
  goiYTrongO,
  xong,
  unit,
  format,
}: SoProps) {
  if (khoa)
    return (
      <ReadField label={nhan}>
        {giaTri === null ? (
          EMPTY_VALUE
        ) : format ? (
          format(giaTri)
        ) : (
          <>
            <span className="font-mono tabular-nums">{so(giaTri)}</span>
            {unit && ` ${unit}`}
          </>
        )}
      </ReadField>
    )
  return (
    <Khung ten={ten} nhan={nhan} batBuoc={batBuoc} goiY={goiY} loi={loi}>
      <span className="relative block">
        <input
          name={ten}
          type="number"
          inputMode={buoc === 1 ? 'numeric' : 'decimal'}
          step={buoc}
          min={min}
          max={max}
          placeholder={goiYTrongO}
          value={giaTri ?? ''}
          onChange={(e) => doi(e.target.value === '' ? null : Number(e.target.value))}
          onBlur={xong}
          aria-invalid={!!loi}
          aria-required={batBuoc || undefined}
          aria-describedby={idMoTa(ten, goiY, loi)}
          className={`${O_CHUNG} font-mono ${unit ? 'pr-24' : ''} ${loi ? O_LOI : ''}`}
        />
        {unit && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-phu text-muted-2"
          >
            {unit}
          </span>
        )}
      </span>
    </Khung>
  )
}

interface ChonProps {
  ten: string
  nhan: string
  giaTri: string | null
  doi: (v: string) => void
  muc: readonly MucChon[]
  batBuoc?: boolean | undefined
  goiY?: string | undefined
  loi?: string | undefined
  khoa?: boolean | undefined
  /** Nhãn của lựa chọn rỗng. Không truyền ⇒ không có lựa chọn rỗng. */
  nhanRong?: string | undefined
  /** Cách hiện lựa chọn ở chế độ xem (vd chip trạng thái). */
  renderValue?: ((value: string, label: string) => ReactNode) | undefined
}

/** Dropdown chọn MỘT. */
export function OChon({
  ten,
  nhan,
  giaTri,
  doi,
  muc,
  batBuoc,
  goiY,
  loi,
  khoa,
  nhanRong,
  renderValue,
}: ChonProps) {
  if (khoa) {
    const chon = muc.find((m) => m.value === giaTri)
    return (
      <ReadField label={nhan}>
        {chon
          ? renderValue
            ? renderValue(chon.value, chon.nhan)
            : chon.nhan
          : giaTri
            ? giaTri
            : EMPTY_VALUE}
      </ReadField>
    )
  }
  return (
    <Khung ten={ten} nhan={nhan} batBuoc={batBuoc} goiY={goiY} loi={loi}>
      <select
        name={ten}
        value={giaTri ?? ''}
        onChange={(e) => doi(e.target.value)}
        aria-invalid={!!loi}
        aria-required={batBuoc || undefined}
        aria-describedby={idMoTa(ten, goiY, loi)}
        className={`${O_CHUNG} o-chon ${loi ? O_LOI : ''}`}
      >
        {nhanRong !== undefined && <option value="">{nhanRong}</option>}
        {muc.map((m) => (
          <option key={m.value} value={m.value}>
            {m.nhan}
          </option>
        ))}
      </select>
    </Khung>
  )
}

interface ChonNhieuProps {
  ten: string
  nhan: string
  giaTri: readonly string[]
  doi: (v: string[]) => void
  muc: readonly MucChon[]
  batBuoc?: boolean | undefined
  goiY?: string | undefined
  loi?: string | undefined
  khoa?: boolean | undefined
}

/**
 * Ô TOKEN chọn NHIỀU — chỉ `projects.category` (`text[]` ở DB) dùng cái này.
 *
 * ⚠️ TRƯỚC ĐÂY LÀ HÀNG CHIP BO TRÒN, và nó bị đọc sai. Phản hồi thật từ người
 * duyệt UI: hàng pill nằm ngay dưới nhãn, không có khung bao, không có ô tick
 * nào nhìn thấy được — mắt đọc nó thành THANH LỌC danh sách, không đọc thành một
 * trường đang nhập. Ba nguyên nhân đó là ba thứ được sửa ở đây: bo tròn → khung
 * ô nhập, không khung → có khung, không ô tick → ô tick vuông trong panel.
 *
 * Hình dạng mới: ô nhìn ĐÚNG NHƯ `OChu`/`OChon` bên cạnh (cùng `border-strong`,
 * cùng bo 9px, cùng `focus:ring`), mục đã chọn nằm trong ô dưới dạng token có
 * dấu ×, và toàn bộ danh mục nằm trong panel bung ra khi bấm. Trong một form 60
 * ô thì trông như một ô là thông tin, không phải trang trí.
 *
 * ĐỔI LẠI, ta MẤT thứ bản chip có: sáu lựa chọn không còn hiện sẵn. Đó là cái
 * giá đã cân: danh mục loại hình còn phình (M3 đã có `PRODUCT_TYPE` 5 mục và sẽ
 * thêm), và một hàng pill 20 mục thì tự nó là một mớ. Bù lại, cái mà
 * `<select multiple>` làm sai thì ô này KHÔNG làm sai: chọn mục thứ hai không
 * làm mất mục thứ nhất, và mục đã chọn hiện thành chữ ngay trong ô.
 *
 * KHÔNG dùng chip Giọng điệu của Agent Studio làm chuẩn nữa. Quy ước từ đây:
 * pill bo tròn = chọn-MỘT / bộ lọc (Agent Studio giữ nguyên), ô token = trường
 * chọn-NHIỀU trong form nhập liệu.
 *
 * `<input type="checkbox">` THẬT nằm dưới `sr-only`, không phải `<div onClick>`:
 * nhờ vậy Tab tới được, Space bật/tắt được, và trình đọc màn hình đọc đúng đã
 * chọn / chưa chọn. `focus-within:ring` đưa vòng focus của input ẩn ra ngoài.
 *
 * DẤU ✓ đi kèm màu, không để màu một mình: `color-not-only` — người mù màu phải
 * phân biệt được dòng đã chọn.
 *
 * Cơ chế đóng/mở lấy nguyên của `WorkspaceSwitcher` (mousedown ngoài khung +
 * Escape) — hai menu trong cùng một app không nên đóng theo hai luật khác nhau.
 * Escape trả focus về nút mở: người dùng bàn phím không bị bỏ rơi ở `<body>`.
 */
export function OChonNhieu({
  ten,
  nhan,
  giaTri,
  doi,
  muc,
  batBuoc,
  goiY,
  loi,
  khoa,
}: ChonNhieuProps) {
  const [mo, setMo] = useState(false)
  const khungRef = useRef<HTMLDivElement>(null)
  const nutRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useDongKhiRaNgoai(khungRef, mo, (e) => {
    setMo(false)
    if (e.type === 'keydown') nutRef.current?.focus()
  })

  // Mở panel là đưa focus VÀO panel. Không làm thế thì Tab tiếp theo nhảy sang ô
  // sau panel, và người dùng bàn phím vừa mở một thứ họ không tới được.
  useEffect(() => {
    if (!mo) return
    panelRef.current?.querySelector<HTMLInputElement>('input[type="checkbox"]')?.focus()
  }, [mo])

  const bat = (value: string, tick: boolean) =>
    doi(tick ? [...giaTri, value] : giaTri.filter((v) => v !== value))

  if (khoa) {
    const chon = muc.filter((m) => giaTri.includes(m.value)).map((m) => m.nhan)
    return <ReadField label={nhan}>{chon.length ? chon.join(', ') : EMPTY_VALUE}</ReadField>
  }

  return (
    <fieldset>
      <legend className="mb-1.5 block text-phu text-muted">
        {nhan}
        {batBuoc && <DauBatBuoc docRa />}
      </legend>

      <div ref={khungRef} className="relative">
        {/* Bấm bất kỳ đâu trong ô cũng mở panel — vùng bấm là cả ô, không phải
            riêng cái nút cuối. Nút thật vẫn ở đó cho bàn phím. */}
        <div
          onClick={() => setMo(true)}
          className={`flex min-h-[42px] w-full cursor-pointer flex-wrap items-center gap-1.5 rounded-md border bg-surface px-2 py-[6px] transition-colors focus-within:ring-2 ${
            loi
              ? 'border-badge-alert-fg focus-within:border-badge-alert-fg focus-within:ring-badge-alert-fg/15'
              : 'border-border-field focus-within:border-ac focus-within:ring-ac/15'
          }`}
        >
          {muc
            .filter((m) => giaTri.includes(m.value))
            .map((m) => (
              <span
                key={m.value}
                className="inline-flex items-center gap-1 rounded-md bg-acs py-[3px] pl-2 pr-1 text-than font-semibold text-ac"
              >
                {m.nhan}
                <button
                  type="button"
                  aria-label={`Bỏ chọn ${m.nhan}`}
                  onClick={(e) => {
                    // Không để cú bấm này nổi lên ô ngoài — bỏ một token rồi bị
                    // mở panel là hai việc, người dùng chỉ yêu cầu một.
                    e.stopPropagation()
                    bat(m.value, false)
                  }}
                  className="flex h-4 w-4 items-center justify-center rounded text-noi leading-none text-ac/60 transition-colors hover:bg-ac/10 hover:text-acd"
                >
                  ×
                </button>
              </span>
            ))}
          <button
            ref={nutRef}
            type="button"
            aria-expanded={mo}
            aria-haspopup="listbox"
            aria-invalid={!!loi}
            aria-describedby={idMoTa(ten, goiY, loi)}
            onClick={(e) => {
              e.stopPropagation()
              setMo(!mo)
            }}
            className="flex flex-1 items-center gap-1.5 rounded px-1 py-[3px] text-left text-noi text-muted-3 outline-none transition-colors hover:text-ac"
          >
            {/* MỘT chuỗi cho cả hai trạng thái, không đổi theo `giaTri.length`.
                Nhãn của nút mở panel là thứ người dùng bàn phím và trình đọc màn
                hình dùng để tìm lại nó — đổi tên nó giữa lần bấm thứ nhất và thứ
                hai là đổi mốc dưới chân họ. */}
            Chọn từ danh sách
            <svg
              aria-hidden="true"
              viewBox="0 0 12 12"
              className={`h-[9px] w-[9px] flex-none transition-transform ${mo ? 'rotate-180' : ''}`}
            >
              <path
                d="M2 4.5 6 8.5l4-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </div>

        {mo && (
          <div
            ref={panelRef}
            className="absolute left-0 top-[calc(100%+6px)] z-20 w-full max-w-[280px] rounded-md border border-border-strong bg-surface p-1 shadow-menu"
          >
            {muc.map((m) => {
              const dangChon = giaTri.includes(m.value)
              return (
                <label
                  key={m.value}
                  className={`flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-[7px] text-than transition-colors focus-within:ring-2 focus-within:ring-ac ${
                    dangChon ? 'bg-acs font-semibold text-ac' : 'text-nav hover:bg-border-soft'
                  }`}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    name={ten}
                    value={m.value}
                    checked={dangChon}
                    onChange={(e) => bat(m.value, e.target.checked)}
                  />
                  <span
                    aria-hidden="true"
                    className={`flex h-[15px] w-[15px] flex-none items-center justify-center rounded-sm border text-nhan leading-none ${
                      dangChon ? 'border-ac bg-ac text-surface' : 'border-border-strong bg-surface'
                    }`}
                  >
                    {/* ✓ chỉ có mặt khi ĐÃ chọn — không vẽ sẵn rồi tô trong suốt.
                        Vẽ sẵn thì `textContent` của label chứa ✓ ở cả hai trạng
                        thái, và test `color-not-only` xanh mà không kiểm gì. */}
                    {dangChon ? '✓' : ''}
                  </span>
                  {m.nhan}
                </label>
              )
            })}
          </div>
        )}
      </div>

      {goiY && !loi && (
        <p className="mt-1 text-phu text-muted-2" id={`${ten}-goiy`}>
          {goiY}
        </p>
      )}
      {loi && (
        <p className="mt-1 text-phu font-medium text-badge-alert-fg" id={`${ten}-loi`}>
          {loi}
        </p>
      )}
    </fieldset>
  )
}

/**
 * Thẻ một nhóm field.
 *
 * `phu` là chỗ nói NHÓM NÀY DÙNG ĐỂ LÀM GÌ. Đây không phải chữ trang trí: người
 * nhập liệu không thấy được cái gì trong 60 ô này rồi sẽ tới miệng agent (hay
 * quyết định ai vào được workspace nào), nên một câu mỗi nhóm là khác biệt giữa
 * điền cho đủ và điền cho đúng việc.
 *
 * `cot` đổi số cột của lưới. Mặc định 3 cột (form dự án, ~12 ô/nhóm); form user
 * chỉ có 4 ô nên truyền `2` — ba ô một hàng rồi một ô lẻ trông như bị bỏ sót.
 */
export function NhomTruong({
  tieuDe,
  phu,
  cot = 3,
  children,
}: {
  tieuDe: string
  phu?: string | undefined
  cot?: 1 | 2 | 3 | undefined
  children: ReactNode
}) {
  // ⚠ `role="group"` + `aria-labelledby` CHỨ KHÔNG `<fieldset><legend>`. Trình
  // duyệt đặt `<legend>` vào KHE của đường viền fieldset và bỏ nó khỏi luồng
  // thường — `display:block` không thắng được hành vi đó. Kết quả (đã thấy trên
  // ảnh chụp thật): tiêu đề nhóm và câu phụ nổi lên đè lên viền trên của thẻ,
  // cắt đường viền làm hai. Cặp `group`/`aria-labelledby` là bản ARIA tương
  // đương của fieldset/legend: cùng ngữ nghĩa "nhóm field có nhãn", không có
  // hành vi bố cục đặc biệt nào.
  //
  // Cũng KHÔNG dùng `<legend className="sr-only">` + `<h2>` hiện: chuỗi tiêu đề
  // khi đó có mặt HAI LẦN trong DOM, và mọi `getByText(tieuDe)` trở thành "tìm
  // thấy nhiều phần tử".
  const id = useId()
  // ⚠ Viết ĐỦ CHUỖI từng biến thể, không ghép `md:grid-cols-${cot}`: Tailwind 4
  // quét văn bản nguồn nên class nội suy không có trong CSS xuất ra.
  const luoi = {
    1: 'grid gap-4',
    2: 'grid gap-4 md:grid-cols-2',
    3: 'grid gap-4 md:grid-cols-2 lg:grid-cols-3',
  }[cot]
  return (
    <section
      role="group"
      aria-labelledby={id}
      className="rounded-xl border border-border bg-surface p-5"
    >
      <div className="mb-4">
        <h2 id={id} className="text-the font-semibold text-fg">
          {tieuDe}
        </h2>
        {phu && <p className="mt-1 text-phu leading-[1.5] text-muted-2">{phu}</p>}
      </div>
      <div className={luoi}>{children}</div>
    </section>
  )
}

/**
 * Ô chiếm cả hàng trong `NhomTruong` (textarea dài, chọn nhiều).
 *
 * `col-span-full` (`1 / -1`) CHỨ KHÔNG `lg:col-span-3` — xem `DongXem`, cùng lý do.
 */
export function CaHang({ children }: { children: ReactNode }) {
  return <div className="col-span-full">{children}</div>
}

/**
 * MỘT Ô ĐÃ ĐIỀN, ở chế độ XEM — nhãn trên, giá trị dưới.
 *
 * Ở ĐÂY chứ không ở `features/*`: cả `/agent` lẫn form dự án của `features/
 * realestate` đều mở ra ở chế độ xem rồi mới bấm Sửa, và hai module KHÔNG được
 * import ruột nhau (`tests/module-boundaries.test.ts`, Luật 3). Bản đầu sống ở
 * `features/agent/components/form.tsx`; chuyển ra đây khi màn thứ hai cần nó,
 * đúng lối `Bang.tsx` và `OTruong.ts` đã đi.
 *
 * Nhãn nằm TRÊN giá trị chứ không bên cạnh: cột hẹp, để hai bên thì nhãn dài
 * («Câu từ chối ngoài phạm vi») xuống dòng giữa chừng và mắt mất mốc.
 *
 * `rong` = chiếm trọn hàng. Prop này ở đây chứ không phải một `<div>` bọc ngoài
 * vì `<dl>` chỉ nhận `<div>`/`<dt>`/`<dd>` làm con — bọc thêm một tầng là dựng
 * đúng cái cấu trúc `dl` không cho phép.
 *
 * ⚠️ `col-span-full` (= `grid-column: 1 / -1`), KHÔNG `lg:col-span-3` (sửa
 * 2026-08-09). Bản cũ viết theo đúng một lưới — `NhomTruong` mặc định 3 cột — nên
 * khi `TomTatCauHinh` đặt nó vào lưới 2 cột thì `span 3` KHÔNG bị cắt cụt: CSS
 * Grid đẻ ra một CỘT NGẦM thứ ba để chứa vừa. Lưới lặng lẽ thành 3 cột, hai cột
 * đầu giữ `1fr` còn cột ngầm co theo nội dung, và khu Danh tính hiện ra ba ô một
 * hàng với ô thứ ba dính mép phải — đúng cái lệch trong ảnh.
 *
 * `1 / -1` đo theo lưới TƯỜNG MINH nên đúng ở cả 1, 2 và 3 cột, và không bao giờ
 * sinh thêm cột. Đây là thứ một ô «cả hàng» thật sự muốn nói.
 */
export function DongXem(props: { nhan: string; rong?: boolean; children: ReactNode }) {
  return (
    <div className={props.rong ? 'col-span-full' : undefined}>
      <dt className="text-phu text-muted">{props.nhan}</dt>
      <dd className="mt-[2px] leading-[1.5]">{props.children}</dd>
    </div>
  )
}

/**
 * Giá trị chỉ-đọc của một ô.
 *
 * Ô RỖNG nói ra thành chữ «Chưa đặt» chứ không để trống: một `<dd>` trống trông
 * y hệt một `<dd>` chưa nạp xong, và người đọc bản tóm tắt không có ô nhập nào
 * bên cạnh để đoán ra.
 */
export function GiaTri(props: { children: string }) {
  const trong = props.children.trim() === ''
  return (
    <span className={trong ? 'text-muted-3 italic' : undefined}>
      {trong ? 'Chưa đặt' : props.children}
    </span>
  )
}

/**
 * Dòng trạng thái của form — ba mức, dùng đúng ba bộ token của prototype.
 *
 * BA MỨC CHỨ KHÔNG HAI: `ok` (accent) tồn tại vì đủ dữ liệu để phát hành là
 * một thông tin người dùng cần, không phải sự vắng mặt của cảnh báo. Không có
 * nó thì cách duy nhất biết mình đã điền xong là không thấy chữ vàng nào — một
 * kết luận rút ra từ sự im lặng.
 *
 * `mau` KHÔNG đứng một mình: mỗi mức có một ký hiệu riêng (`✓ ⚠ ✕`) để người mù
 * màu vẫn phân biệt được (`color-not-only`).
 */
export function DongTrangThai({
  mau,
  children,
}: {
  mau: 'ok' | 'warn' | 'alert'
  children: ReactNode
}) {
  const lop = {
    ok: 'bg-acs text-acd',
    warn: 'bg-badge-warn-bg text-badge-warn-fg',
    alert: 'bg-badge-alert-bg text-badge-alert-fg',
  }[mau]
  const dau = { ok: '✓', warn: '⚠', alert: '✕' }[mau]
  return (
    <p
      className={`flex items-start gap-2 rounded-lg px-3 py-2 text-than leading-[1.5] font-medium ${lop}`}
      {...(mau === 'alert'
        ? { role: 'alert' as const }
        : mau === 'warn'
          ? { role: 'status' as const }
          : {})}
    >
      <span aria-hidden="true">{dau}</span>
      <span>{children}</span>
    </p>
  )
}
