/**
 * Bốn thẻ KPI đầu màn `/billing` — mục ① (Task 4). Component TRÌNH BÀY thuần,
 * đọc thẳng `TongQuan` (Task 3) — không tự gọi API.
 *
 * THANG CHỮ (chín bậc, `CLAUDE.md` §Design token — không có bậc thứ mười):
 * ⚠️ BỐN CON SỐ CHỈ KHÁC NHAU Ở CỠ. Font · độ đậm · `leading` · `tracking` ·
 * `tabular-nums` khoá chung trong hằng `SO_LON` (`./lop.ts`) — đọc docstring ở
 * đó trước khi định cho một thẻ một kiểu riêng.
 *   · `32px` — CHỈ số của thẻ «Tổng chi phí» (thẻ nhấn, đứng đầu).
 *   · `26px` — số của ba thẻ còn lại.
 *   · `15px` sans 600 — không dùng ở đây (đó là tiêu đề THẺ khi thẻ có tiêu đề
 *     riêng biệt với nhãn; ở đây nhãn CHÍNH LÀ tiêu đề thẻ, dùng bậc nhãn).
 *   · `10.5px` sans 600 uppercase — nhãn KPI (`Tổng chi phí`, `Token`, …).
 *   · `11px` mono — dòng chân của thẻ Token (in/out/cache), mức nhỏ nhất.
 *   · `12.5px` — phụ đề đơn vị tiền (VND) dưới số lớn.
 *
 * `tabular-nums` (trong `SO_LON`) — cùng luật với ô số của bảng (`TD_SO`,
 * `components/ui/Bang.tsx`). Không có nó thì con số ĐỔI BỀ RỘNG khi đổi kỳ, và
 * bốn thẻ cạnh nhau xê dịch mép mỗi lần tải lại một kỳ khác.
 *
 * ── HÌNH TRONG THẺ (2026-08-21, demo `docs/design/demo-usage-tong-quan.html` §D) ──
 * Hai thẻ đầu mang thêm một hình; hai thẻ cuối KHÔNG. Đó là chủ ý, không phải
 * làm dở:
 *   · «Tổng chi phí» — sparkline theo ngày, truyền vào qua prop `hinhChiPhi`
 *     (`SparklineChiPhi`). Component đó TỰ gọi `/breakdown`; tệp này không
 *     biết gì về request ấy nên vẫn là component trình bày thuần.
 *   · «Token» — thanh xếp lớp in/out/cache, đúng ba con số đang nằm ở dòng
 *     chân ngay dưới. Không cần thêm dữ liệu gì.
 *   · Phiên · Thời lượng gọi — KHÔNG có nguồn theo ngày.
 *     `theo_ngay` chỉ trả TIỀN; không field nào trả phiên/giây/khoá theo ngày,
 *     cũng không có field nào so với kỳ trước. **Đừng vẽ sparkline giả cho
 *     chúng** — cần thì xin BE `usage-by-day` trước (đã ghi là BE mới trong
 *     `docs/design/demo-usage.html`).
 * Lưới `grid` căng các thẻ cùng hàng bằng chiều cao nhau, nên hai thẻ cuối chỉ
 * còn khoảng trắng ở đáy — KHÔNG chèn ô giữ chỗ vào đó.
 *
 * KHÔNG CÓ HIỆU ỨNG HOVER ở bất kỳ thẻ nào (người dùng chốt khi xem demo).
 * Thẻ KPI không bấm được — một thẻ nhấc lên hay đổ bóng khi rê chuột là hứa
 * một cú bấm không tồn tại. Đừng thêm `transition`/`hover:` vào `THE`.
 *
 * ⚠️ Nhãn thẻ thứ tư là «Thời lượng gọi», KHÔNG phải «Thời lượng voice» —
 * `voice_sec` của BE chỉ đếm `component='call'` (BE sửa 2026-08-20, commit
 * `9d78d04`). Nhãn «voice» hứa tổng mọi thành phần âm thanh (vad/stt/tts/call)
 * — sai, và BE đã đo được: cộng chéo ra ~2.64× số thật. `title` giải thích vì
 * sao không cộng gộp được: các quãng audio đó CHỒNG LẤN nhau trong thời gian
 * (agent nghe trong lúc TTS đang phát), nên "cộng thời lượng của từng bước"
 * không ra "tổng thời gian trôi qua" — cùng lý do không cộng `EventUsage.
 * audio_sec` của nhiều component lại (xem `kieu.ts::EventUsage.audio_sec`).
 */
import type { ReactNode } from 'react'
import type { TongQuan } from '../kieu'
import { SO, giay, tien, token } from '../dinh-dang'
import { SO_LON } from './lop'

const THE = 'flex flex-col gap-1.5 rounded-lg border border-border bg-surface p-4'
const NHAN = 'text-nhan font-semibold uppercase tracking-[.07em] text-muted-2'

/**
 * Thanh xếp lớp in/out/cache — ba con số của dòng chân, đọc được TỈ LỆ.
 *
 * BA NẤC LÀ MỘT SẮC `ac` VỚI HAI MỨC MỜ, không phải ba token màu. Cố ý KHÔNG
 * mượn thang `--color-comp-*`: thang đó nhạt dần theo THỨ HẠNG (`bangMau()`,
 * `component-hien.ts`) nên cùng một sắc mang nghĩa khác nhau giữa hai kỳ, còn
 * ở đây màu phải KHOÁ THEO LOẠI để người dùng học được «đậm nhất là input».
 * Cũng KHÔNG khai token mới: một thang xanh thứ hai nằm cạnh `comp-*` trong
 * `theme.css` là hai bộ trông giống nhau nói hai thứ khác nhau.
 *
 * ⚠️ RANH GIỚI GIỮA BA ĐOẠN LÀ KHE 1px MÀU MẶT THẺ (`gap-px` + rãnh
 * `bg-surface`), KHÔNG trông vào tương phản giữa hai sắc kề. ĐO ĐƯỢC: `ac` ↔
 * `ac/60` chỉ 2.09, dưới ngưỡng 3.0 của WCAG 1.4.11 — và không mức mờ nào của
 * một sắc đơn vượt được (thang `comp-*` đang chạy ở mục ② cũng chỉ 1.55·2.06).
 * Nên ranh giới phải vẽ bằng HÌNH HỌC. Ba con số vẫn nằm nguyên dạng CHỮ ở
 * dòng chân ngay dưới, nên thanh là phần củng cố chứ không phải kênh duy nhất
 * — cùng thế đứng với thanh tỉ lệ của `TheComponent`.
 *
 * `tong <= 0` trả `null`: chia cho 0 ra `NaN%` và cả thanh biến mất một cách
 * im lặng. Kỳ không có token nào là ca thật (workspace mới chỉ gọi voice).
 */
function ThanhLop({
  vao,
  ra,
  cache,
}: {
  readonly vao: number
  readonly ra: number
  readonly cache: number
}) {
  const tong = vao + ra + cache
  if (tong <= 0) return null
  const pc = (v: number) => `${((v / tong) * 100).toFixed(2)}%`
  return (
    <div className="flex h-[5px] gap-px overflow-hidden rounded-full bg-surface" aria-hidden="true">
      <span className="block bg-ac" style={{ width: pc(vao) }} />
      <span className="block bg-ac/60" style={{ width: pc(ra) }} />
      <span className="block bg-ac/30" style={{ width: pc(cache) }} />
    </div>
  )
}

/**
 * Thẻ nhấn — «Tổng chi phí». Một mình ở bậc `32px`, và chiếm HAI cột lưới
 * (`col-span-2`): thẻ «API key đang hoạt động» đã BỎ (người dùng chốt
 * 2026-09-29), chỗ của nó nhường cho thẻ này để số tiền nhiều chữ số có chỗ
 * đứng — ở 1/5 hàng, số `32px` từ ~9 chữ số trở lên tràn khỏi thẻ. Số khoá
 * vẫn xem được ở bảng ③ chiều «Khoá».
 */
/**
 * Cỡ số theo ĐỘ DÀI chuỗi — thẻ hẹp nhất (~228px lòng thẻ ở 1024px) chứa ~11
 * ký tự mono cỡ 32px. Dài hơn thì hạ nấc thay vì tràn (18px chứa ~19 ký tự
 * = tới hàng triệu tỷ). Không `break-all`: đó là khác biệt NGOÀI cỡ, cổng
 * «bốn con số chỉ khác ở cỡ» sẽ đỏ. Số tiền lớn là ca thật, không phải ca
 * biên: tenant nhiều cuộc gọi dễ lên 9–12 chữ số một tháng.
 */
function coChiPhi(so: string): string {
  if (so.length <= 11) return 'text-so-lon'
  if (so.length <= 14) return 'text-so'
  // Hai nấc cuối là nấc THU NHỎ cho số rất dài, ngoài thang cỡ chữ có chủ ý —
  // chúng tồn tại để không tràn thẻ, không phải một vai chữ.
  if (so.length <= 17) return 'text-[22px]'
  return 'text-[18px]'
}

function TheChiPhi({
  chiPhi,
  duLieuNgoai,
  currency,
  hinh,
}: {
  readonly chiPhi: string
  readonly duLieuNgoai?: string | undefined
  readonly currency: string
  readonly hinh?: ReactNode
}) {
  const so = tien(chiPhi)
  return (
    <div className={`${THE} col-span-2`}>
      <h3 className={NHAN}>Tổng chi phí</h3>
      <p className={`${SO_LON} ${coChiPhi(so)}`}>{so}</p>
      <p className="text-phu text-muted">
        {currency}
        {duLieuNgoai && Number(duLieuNgoai) > 0 && <> · gồm {tien(duLieuNgoai)} ₫ dữ liệu ngoài</>}
      </p>
      {hinh}
    </div>
  )
}

/**
 * Dòng chân dạng NHIỀU MỤC — mỗi mục một cặp `nhãn + số`, XUỐNG DÒNG được.
 *
 * Bản trước ghép cả ba thành MỘT chuỗi (`in 976k · out 38k · cache read 52k`)
 * rồi `truncate`: thẻ chỉ rộng 1/5 hàng nên chuỗi đó luôn bị cắt, và cắt ở
 * ĐUÔI — tức mục bị mất luôn là `cache read`, mất im lặng, không có dấu hiệu
 * nào ngoài dấu `…`. `truncate` đúng cho một CÁI TÊN dài (tên khoá, email:
 * cắt vẫn còn nhận ra); sai cho một danh sách SỐ, vì mỗi con số là một dữ
 * kiện độc lập, mất là mất hẳn.
 *
 * Bỏ luôn dấu `·`: khi các mục đã xuống dòng thì dấu phân cách nằm cuối dòng
 * trỏ vào khoảng trắng. Khoảng cách `gap-x-2.5` làm đúng việc của nó.
 * PORT từ `.tach` của `docs/design/demo-usage-billing.html` (cũng `flex-wrap`).
 *
 * Số ở đây KHÔNG được nhấn: không `font-medium` (chỉ `SO_LON` mới đậm), và
 * KHÔNG `text-fg` — cùng sắc `text-muted` với chữ `in`/`out`/`cache read`
 * đứng cạnh. Đây là bậc 11px nhỏ nhất của thẻ; nhấn nó lên là nó tranh chỗ
 * với con số 26px ngay trên, và cả dòng đọc thành ba con số rời rạc thay vì
 * một dòng chú thích. Vẫn giữ `font-mono` — luật «MỌI con số dùng font này»
 * ở `theme.css` nói về FONT, không nói về độ nhấn.
 */
function ChanTach({ muc }: { readonly muc: readonly (readonly [string, string])[] }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 text-nhan text-muted">
      {muc.map(([nhan, gia]) => (
        <span key={nhan} className="whitespace-nowrap">
          {nhan} <span className="font-mono tabular-nums">{gia}</span>
        </span>
      ))}
    </div>
  )
}

/** Ba thẻ số còn lại — cùng bậc `26px` mono 500, khác nhau ở dòng chân. */
function TheSo({
  nhan,
  giaTri,
  tren,
  chan,
  title,
}: {
  readonly nhan: string
  readonly giaTri: string
  /** Giữa con số và dòng chân — chỗ của `ThanhLop`. Đứng TRÊN dòng chân vì nó
   *  là hình của chính ba con số ở dòng chân; đặt dưới thì thứ nó giải thích
   *  đã trôi qua mắt rồi. */
  readonly tren?: ReactNode
  /** `ReactNode` chứ không `string`: dòng chân của thẻ Token là một danh sách
   *  xuống dòng được, không phải một câu (xem `ChanTach`). */
  readonly chan?: ReactNode
  readonly title?: string | undefined
}) {
  return (
    <div className={THE} title={title}>
      <h3 className={NHAN}>{nhan}</h3>
      <p className={`${SO_LON} text-so`}>{giaTri}</p>
      {tren}
      {chan}
    </div>
  )
}

/**
 * `hinhChiPhi` TUỲ CHỌN, và không có nó thì thẻ vẫn đủ nghĩa — đó là điều kiện
 * để mục ① không phụ thuộc vào `/breakdown`. Nhận một PHẦN TỬ đã dựng sẵn
 * (`ReactNode`) chứ không nhận dữ liệu `DongNgay[]`: như thế tệp này không biết
 * endpoint nào tồn tại, bài test dựng nó không phải dựng thêm fake HTTP, và
 * phép gọi `/breakdown` nằm ở đúng một chỗ mà NHÁNH RENDER quyết định được —
 * xem docstring `SparklineChiPhi` để biết vì sao điều đó quan trọng.
 */
export function TheKpi({
  data,
  hinhChiPhi,
}: {
  readonly data: TongQuan
  readonly hinhChiPhi?: ReactNode
}) {
  const tongToken = data.input_tokens + data.output_tokens + data.cache_read_tokens
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <TheChiPhi
        chiPhi={data.chi_phi}
        duLieuNgoai={data.chi_phi_du_lieu_ngoai}
        currency={data.currency}
        hinh={hinhChiPhi}
      />
      <TheSo
        nhan="Token"
        giaTri={token(tongToken)}
        tren={
          <ThanhLop
            vao={data.input_tokens}
            ra={data.output_tokens}
            cache={data.cache_read_tokens}
          />
        }
        chan={
          <ChanTach
            muc={[
              ['in', token(data.input_tokens)],
              ['out', token(data.output_tokens)],
              ['cache read', token(data.cache_read_tokens)],
            ]}
          />
        }
      />
      <TheSo nhan="Phiên hội thoại" giaTri={SO(data.so_phien)} />
      <TheSo
        nhan="Thời lượng gọi"
        giaTri={giay(data.voice_sec)}
        title="Chỉ thời lượng cuộc gọi. `vad`/`stt`/`tts` đo những quãng audio chồng lấn nên không cộng gộp được."
      />
    </div>
  )
}
