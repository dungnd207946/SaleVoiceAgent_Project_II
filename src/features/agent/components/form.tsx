import type { ReactNode } from 'react'
import { nhanCua, type KyNang } from '@/lib/tools'
import { Icon, type IconName } from '@/components/icons'
export { DongXem as Dong, GiaTri } from '@/components/ui/Truong'
import { RAO_CHAN } from './hangChung'
import { O_LOP } from './lop'

/** Thẻ trắng của prototype: bo 12px, viền `border`, đệm 20px.
 *
 * `icon` là TUỲ CHỌN và hai khu dùng: Rào chắn (`shield` — nói «đây là phần bảo
 * vệ» khi khu này không còn câu chữ nào giải thích) và Chuẩn hoá cách đọc
 * (`voice` — khu duy nhất nói về kênh thoại). Đừng gắn icon cho mọi khu: năm mark
 * cạnh năm tiêu đề thì không mark nào còn nghĩa. */
export function The(props: {
  tieuDe: string
  icon?: IconName
  phu?: string
  /** Bỏ vỏ thẻ (viền · nền · bo · đệm) — dùng khi thẻ nằm TRONG một khung đã có vỏ
   *  (`KhoiVaiTro`): thẻ trong thẻ là hai lớp vỏ cho một nhóm nội dung. Đệm do
   *  khung đặt, để các khu trong khung đứng chung MỘT lưới. */
  phang?: boolean
  children: ReactNode
}) {
  return (
    <section className={props.phang ? undefined : 'rounded-xl border border-border bg-surface p-5'}>
      {/* 15px = đúng cỡ tiêu đề của MỌI thẻ nhóm form (`NhomTruong`,
          `components/ui/Truong.tsx`) — 16px dành cho đầu mục KHỐI/BẢNG
          (`DauMuc`, `ThanhCong`), hai vai khác nhau. */}
      <h2 className="flex items-center gap-2 text-the font-semibold">
        {props.icon && <Icon name={props.icon} className="size-[18px] flex-none text-ac" />}
        {props.tieuDe}
      </h2>
      {props.phu && <p className="mt-1 text-phu text-muted-2">{props.phu}</p>}
      <div className="mt-4">{props.children}</div>
    </section>
  )
}

export function O(props: {
  nhan: string
  giaTri: string
  toiDa: number
  doi: (v: string) => void
  /** Chiếm trọn hàng trong `LUOI_O` — dành cho ô chứa cả câu. */
  rong?: boolean
  /**
   * Chữ mờ trong ô rỗng — CÂU MẪU, không phải nhắc lại nhãn.
   *
   * Tám ô ở màn này đều là ô viết tự do, và nhãn của chúng (Xưng hô,
   * Agent làm gì) nói ĐỀ BÀI mà không nói HÌNH DẠNG câu trả lời. Người config
   * lần đầu nhìn ô Agent không làm gì rỗng thì không biết nên gõ một danh sách,
   * một đoạn văn, hay một câu — nên một câu mẫu đúng bối cảnh tư vấn bất động
   * sản/tài chính là chỗ nhanh nhất để nói điều đó.
   *
   * Chỉ «VD: …», KHÔNG kèm một câu giảng nghĩa trước đó: nhãn đã nói ô này là gì
   * rồi, và một placeholder hai vế thì vế mẫu — thứ duy nhất bắt chước được — bị
   * đẩy ra khỏi bề rộng ô.
   */
  goiYTrongO?: string
}) {
  return (
    <label className={props.rong ? 'block sm:col-span-2' : 'block'}>
      <span className="mb-1.5 block text-phu text-muted">{props.nhan}</span>
      <input
        className={O_LOP}
        value={props.giaTri}
        maxLength={props.toiDa}
        placeholder={props.goiYTrongO}
        onChange={(e) => props.doi(e.target.value)}
      />
    </label>
  )
}

/** Chip chọn một — radio thật nằm dưới `sr-only`, viền và nền nói cái nào đang chọn. */
export function Preset(props: {
  nhan: string
  cac: readonly { ma: string; nhan: string }[]
  chon: string
  doi: (v: string) => void
}) {
  return (
    <fieldset>
      <legend className="mb-2 text-phu text-muted">{props.nhan}</legend>
      <div className="flex flex-wrap gap-2">
        {props.cac.map((c) => {
          const dangChon = props.chon === c.ma
          return (
            <label
              key={c.ma}
              className={`cursor-pointer rounded-full border px-3.5 py-[7px] text-than transition-colors focus-within:ring-2 focus-within:ring-ac ${
                dangChon
                  ? 'border-ac bg-acs font-semibold text-ac'
                  : 'border-border-strong bg-surface text-muted hover:border-fg'
              }`}
            >
              <input
                type="radio"
                className="sr-only"
                name={props.nhan}
                checked={dangChon}
                onChange={() => props.doi(c.ma)}
              />
              {c.nhan}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

/** Dòng cảnh báo — hai mức, dùng đúng hai bộ token badge của prototype. */
export function Canh(props: { mau: 'warn' | 'alert'; children: ReactNode }) {
  const lop =
    props.mau === 'alert'
      ? 'bg-badge-alert-bg text-badge-alert-fg'
      : 'bg-badge-warn-bg text-badge-warn-fg'
  return (
    <p className={`mt-2.5 rounded-lg px-3 py-2 text-[13px] leading-[1.5] font-medium ${lop}`}>
      {props.children}
    </p>
  )
}

/** Sáu rào chắn — CÙNG một khối ở cả chế độ xem lẫn chế độ sửa.
 *
 * Nó không phải một ô cấu hình (BR08: hiện ra nhưng không có công tắc), nhưng nó
 * là lời hứa về những gì agent sẽ KHÔNG làm — bỏ nó khỏi màn xem, tức khỏi thứ
 * người dùng thấy mặc định, là giấu đúng phần trấn an.
 *
 * Dòng «Sáu rào chắn này không tắt được» ĐÃ BỎ (người dùng chốt 2026-08-08).
 * Luật BR08 không đổi — vẫn không có công tắc nào ở đây, và việc đó giờ nói bằng
 * hình: khiên ở đầu khu, dấu ✓ ở mỗi dòng, không một control nào. */
export function RaoChan() {
  return (
    <The icon="shield" tieuDe="Rào chắn đang bảo vệ workspace">
      {/* HAI CỘT: sáu dòng, dòng dài nhất 66 ký tự — xếp dọc một cột thì mỗi
          dòng bỏ trống hơn nửa bề rộng thẻ và khối này cao gần bằng cả khu Danh
          tính, dù nó là văn bản tĩnh giống hệt nhau ở mọi workspace. */}
      <ul
        aria-label="Rào chắn đang bảo vệ workspace"
        className="grid grid-cols-1 gap-x-6 gap-y-2.5 text-than leading-[1.5] text-nav sm:grid-cols-2"
      >
        {RAO_CHAN.map((r) => (
          <li key={r} className="flex gap-2.5">
            <span aria-hidden className="font-bold text-ac">
              ✓
            </span>
            <span>{r}</span>
          </li>
        ))}
      </ul>
    </The>
  )
}

/** Danh sách toggle kỹ năng — cùng markup công tắc 38×21 của prototype, dùng ở
 * cả tab Cấu hình chung (3 kỹ năng) và tab Bất động sản (9 kỹ năng). Checkbox
 * thật nằm dưới `sr-only` cho bàn phím và screen reader.
 *
 * `thieu` = đúng thứ `thieuPhuThuoc()` trả về: các cặp [kỹ năng đang bật, thứ nó
 * cần mà đang tắt]. Không truyền ⇒ không dòng nào (màn Cấu hình chung: cả ba kỹ
 * năng chung đều không có phụ thuộc).
 *
 * VÌ SAO CẢNH BÁO NẰM TRONG HÀNG, KHÔNG PHẢI DƯỚI ĐÁY THẺ: trước 2026-08-08
 * `KyNangBds` xếp các cảnh báo thành một chồng SAU cả chín công tắc. Bật «Thông
 * tin tổng quan dự án» (hàng 3) thì câu giải thích hiện ra cách đó sáu hàng, và
 * người dùng phải tự nối câu «Thông tin tổng quan dự án cần…» ngược lên hàng đã
 * bấm — chính vì phải nối nên câu đó buộc phải nhắc lại tên kỹ năng. Đặt vào
 * hàng thì hàng đã tự nói tên nó rồi, câu ngắn lại còn đúng phần thiếu.
 */
export function CongTacKyNang(props: {
  danhSach: readonly KyNang[]
  dangBat: readonly string[]
  doi: (ten: string, bat: boolean) => void
  thieu?: readonly (readonly [string, string])[]
}) {
  return (
    <div className="flex flex-col">
      {props.danhSach.map((k) => {
        const can = (props.thieu ?? []).filter(([ten]) => ten === k.ten).map(([, c]) => c)
        return (
          <div key={k.ten} className="border-b border-border-soft py-[11px] last:border-b-0">
            <label className="group flex cursor-pointer items-center gap-3">
              <span className="flex-1 text-[14px] font-medium">{k.nhan}</span>
              <input
                type="checkbox"
                aria-label={k.nhan}
                className="peer sr-only"
                checked={props.dangBat.includes(k.ten)}
                onChange={(e) => props.doi(k.ten, e.target.checked)}
              />
              {/* Công tắc của prototype: 38×21, núm 17px, trượt 17px. Là
                  `<span>` ăn theo `peer-checked` chứ không phải checkbox vẽ
                  lại — checkbox thật vẫn ở đó cho bàn phím và screen reader. */}
              <span className="relative h-[21px] w-[38px] flex-none rounded-full bg-border-field transition-colors peer-checked:bg-ac peer-focus-visible:ring-2 peer-focus-visible:ring-ac peer-focus-visible:ring-offset-2 after:absolute after:top-[2px] after:left-[2px] after:h-[17px] after:w-[17px] after:rounded-full after:bg-surface after:transition-transform peer-checked:after:translate-x-[17px]" />
            </label>

            {/* NÚT NẰM NGOÀI `<label>`, không lồng vào trong: một `<button>` bên
                trong label sẽ vừa chạy `onClick` vừa lật đúng công tắc của hàng
                này — bấm «Bật» để sửa phụ thuộc lại tắt mất kỹ năng vừa bật. */}
            {can.length > 0 && (
              <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1.5 text-phu leading-[1.5] text-badge-warn-fg">
                <span>Cần {can.map(nhanCua).join(' và ')} mới chạy đúng.</span>
                {/* Chữ trên nút chỉ «Bật» — câu ngay trước đã nói bật CÁI GÌ, và
                    năm trong sáu phụ thuộc trỏ về cùng «Nhận diện tên dự án»
                    nên nút mang tên đầy đủ sẽ lặp tên ấy hai lần trong một dòng
                    và ba lần trong một thẻ. Tên đầy đủ vẫn còn ở `aria-label`:
                    trình đọc màn hình duyệt theo danh sách nút, ở đó ba nút tên
                    «Bật» là ba nút không phân biệt được. */}
                <button
                  type="button"
                  aria-label={`Bật ${can.map(nhanCua).join(' và ')}`}
                  className="rounded-sm border border-badge-warn-fg/30 px-2 py-[3px] font-medium transition-colors hover:border-badge-warn-fg hover:bg-badge-warn-bg"
                  onClick={() => can.forEach((c) => props.doi(c, true))}
                >
                  Bật
                </button>
              </p>
            )}
          </div>
        )
      })}
    </div>
  )
}
