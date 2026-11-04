/**
 * Slide-over chi tiết MỘT phiên — màn cuối của `/billing` (Task 6). Mở qua
 * search param `?phien=<session_id>` (đọc/ghi param này là việc của
 * `UsageScreen.tsx` — component ở đây chỉ nhận `sessionId` + gọi `onDong`,
 * KHÔNG tự biết cách xoá search param).
 *
 * Vỏ dialog (`<dialog>` qua `HopThoai`: focus lúc mở + Escape + bấm nền +
 * khung + nút ×) dùng CHUNG `./PanelKhung` với `PanelBoGia`/`PanelGanWorkspace`
 * (review 2026-08-20 — trước đó ba nơi giữ ba bản COPY NGUYÊN VĂN, xem
 * docstring `PanelKhung.tsx`); chỗ gọi không còn tự dựng lớp phủ. Trả focus lúc đóng theo khuôn `oKichHoatRef` của
 * `LightboxAnh` (trong
 * `features/platform/components/ThuAgentScreen.tsx`) — chỉ khác là ref đó
 * SỐNG Ở `UsageScreen.tsx`, vì phần tử kích hoạt (nút trong hàng Phiên, tận
 * trong `BangLuotDung.tsx`) và slide-over này không cùng cây component;
 * `UsageScreen` truyền một hàm `moPhien` xuống hai lớp props để nhận lại
 * đúng phần tử đó rồi trả focus khi `onDong` chạy — component này không biết
 * gì về việc đó, chỉ gọi `onDong`.
 *
 * ⚠️ LUẬT CỨNG SỐ MỘT CỦA TASK NÀY: `ghi_chu_turn` hiện NGUYÊN VĂN, LUÔN
 * HIỆN, KHÔNG tooltip/`title`, KHÔNG `<details>`. Lý do nằm ở chính field đó
 * (xem `kieu.ts::ChiTietPhien.ghi_chu_turn`): `turn_idx` của dòng audio là
 * XẤP XỈ (TTS của lượt N nằm ở lô ghi nhận N+1) — người đối soát tiền theo
 * từng lượt mà không có câu này sẽ thấy lệch và kết luận "hệ thống tính sai"
 * trong khi tổng theo phiên luôn đúng. Banner đứng NGAY DƯỚI khối đầu, TRÊN
 * timeline, dải `bg-badge-warn-bg`.
 *
 * ⚠️ KHÔNG cộng `audio_sec` của nhiều event lại — đúng phép cộng chéo
 * component mà BE vừa sửa ở tầng của họ (xem `kieu.ts::TongQuan.voice_sec` và
 * `EventUsage.audio_sec`). Mỗi event hiện `audio_sec` CỦA RIÊNG NÓ; panel này
 * không có dòng tổng giây nào.
 *
 * SỐ ĐO THEO COMPONENT (cơ sở tính tiền THẬT, đổi ở migration `0948`
 * 2026-08-20 — `units` nay là SỐ LẦN GỌI cho MỌI component, không còn là ký
 * tự/đoạn như trước): `llm` → token in/out; `embed`/`tts` → `text_units` ký
 * tự (KHÔNG phải `units`); `stt` → `audio_sec` VÀ `text_units`, hai vế ĐỘC
 * LẬP, hiện CẢ HAI (vendor kiểu Soniox thu hai đồng hồ riêng); `vad`/
 * `speaker_verify`/`call` → `audio_sec`. Xem `soDoEvent()` dưới đây.
 *
 * Nhóm theo `turn_idx` bằng ĐƯỜNG KẺ + nhãn «Lượt N», KHÔNG accordion — người
 * đối soát cần thấy hết cùng lúc, gập bớt là giấu đúng thứ họ đang tìm.
 *
 * Tiền từng event dùng `tienDay()` (4 chữ số thập phân — chỗ đối soát), tổng
 * phiên dùng `tien()` (làm tròn để hiện, xem `dinh-dang.ts`).
 *
 * MỌI con số ở panel này `font-mono tabular-nums` (2026-08-21) — cùng luật với
 * `TD_SO` của bảng và thẻ KPI. Ở ĐÂY nó không chỉ là nhất quán: panel là chỗ
 * ĐỐI SOÁT (`tienDay()` in 4 chữ số thập phân), và một cột số 4 chữ số thập
 * phân bằng font tỷ lệ thì hai dòng liền nhau lệch dấu phẩy — mắt không so
 * được hàng nào lớn hơn hàng nào nếu không đọc từng chữ số.
 */
import { useId, type ReactNode } from 'react'
import { useSaoChep } from '@/lib/saoChep'
import { NutIcon, PILL } from '@/components/ui/Bang'
import { ChipKenh } from '@/components/ui/ChipKenh'
import { LoiTai } from '@/components/ui/TrangThai'
import { useChiTietPhien } from '../api'
import { giay, rong, soSanhTien, tien, tienDay, token } from '../dinh-dang'
import { SO_LON } from './lop'
import type { ChiTietPhien as ChiTietPhienData, EventUsage } from '../kieu'
import { PanelKhung } from './PanelKhung'

/** Nút copy `session_id` — copy hỏng không mất gì, session_id đã hiện sẵn trên màn. */
function NutCopySessionId({ sessionId }: { readonly sessionId: string }) {
  const { daCopy, copy } = useSaoChep()
  return (
    <NutIcon
      icon={daCopy ? 'check' : 'copy'}
      nhan={daCopy ? 'Đã copy' : 'Copy session_id'}
      onClick={() => void copy(sessionId)}
    />
  )
}

/**
 * `occurred_at` là ISO CÓ offset — đọc THẲNG từ chuỗi, không qua `Date`/múi
 * giờ trình duyệt (cùng lý do `hienGio` ở `BangLuotDung.tsx`). Giữ GIÂY, khác
 * bảng tổng hợp: ở đây đang đối soát THỨ TỰ event trong cùng một phút.
 */
function hienGioGiay(iso: string): string {
  const m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})/.exec(iso)
  if (!m) return iso
  const [, thang, ngay, gio, phut, giayStr] = m
  return `${ngay}/${thang} ${gio}:${phut}:${giayStr}`
}

/**
 * Số đo hiện cho MỘT event — chọn field theo cơ sở tính tiền THẬT của
 * component đó. ĐỪNG đổi field đọc ở đây mà không đọc lại
 * `kieu.ts::EventUsage` trước — đây chính là chỗ fake của Task 3 hỏi (event
 * `tts` với `units:7, text_units:1115` phải đọc ra "1.115 ký tự", không phải
 * "7").
 */
function soDoEvent(e: EventUsage): string {
  switch (e.component) {
    case 'llm':
      return `${token(e.input_tokens)} → ${token(e.output_tokens)}`
    case 'embed':
    case 'tts':
      return `${token(e.text_units)} ký tự`
    case 'stt':
      return `${giay(e.audio_sec)} · ${token(e.text_units)} ký tự`
    case 'vad':
    case 'speaker_verify':
    case 'call':
      return giay(e.audio_sec)
    default:
      // Component lạ (BE thêm sau) — không đoán cơ sở tính tiền, hiện số lần
      // gọi trần thay vì tự bịa một câu chuyện tiền không kiểm chứng được.
      return `${token(e.units)} lần gọi`
  }
}

const KHONG_TINH_TIEN: ReactNode = (
  <span className={`${PILL} bg-badge-neutral-bg text-badge-neutral-fg`}>Không tính tiền</span>
)

/**
 * Một dòng trong timeline. Tiền bằng 0 ⇒ chữ `text-muted` + pill «Không tính
 * tiền». Đây là trạng thái BÌNH THƯỜNG (event không tính phí), không phải lỗi
 * hay giá trị thiếu — không gạch bỏ, không đỏ.
 *
 * ⚠️ So bằng `soSanhTien()`, KHÔNG bằng `=== '0'`. BE chỉ trả đúng chuỗi `'0'`
 * khi event không có dòng `rated_usage` nào; event CÓ dòng tiền mà tổng bằng 0
 * (bảng giá mặc định khai `unit_price = 0` cho `vad`/`speaker_verify`/`stt`) về
 * tới đây là `'0E-10'` — xem `veThapPhan()` ở `dinh-dang.ts`. So chuỗi trần bỏ
 * sót đúng ca phổ biến nhất, và bỏ sót ở màn ĐỐI SOÁT.
 */
function DongEvent({ e }: { readonly e: EventUsage }) {
  const khongTinhTien = soSanhTien(e.chi_phi, '0') === 0
  return (
    <div className="flex items-start justify-between gap-4 border-t border-border-soft px-5 py-3 first:border-t-0">
      <div className="flex min-w-0 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-nhan text-muted-2">#{e.seq}</span>
          <span className={`${PILL} bg-badge-neutral-bg text-badge-neutral-fg uppercase`}>
            {e.component}
          </span>
          <span className="text-phu text-muted">{e.purpose}</span>
        </div>
        {/* provider/model MỖI PHẦN một `<span>` riêng — `''` (DEFAULT '',
            không NULL ở component audio) phải hiện `—` qua `rong()` như một
            phần tử độc lập, không ghép chung một chuỗi "— / —": người đối
            soát tìm bằng mắt từng cột, không phải đọc cả câu. */}
        <div className="text-phu text-muted">
          <span>{rong(e.provider)}</span>
          <span className="mx-1 text-muted-3">/</span>
          <span>{rong(e.model)}</span>
        </div>
        <div className="font-mono text-phu font-medium tabular-nums text-fg">{soDoEvent(e)}</div>
        <div className="font-mono text-nhan text-muted-2">{hienGioGiay(e.occurred_at)}</div>
      </div>
      <div className="flex flex-none flex-col items-end gap-1">
        <span
          className={`font-mono text-than font-semibold tabular-nums ${khongTinhTien ? 'text-muted' : ''}`}
        >
          {tienDay(e.chi_phi)}
        </span>
        {khongTinhTien && KHONG_TINH_TIEN}
      </div>
    </div>
  )
}

interface NhomLuot {
  readonly turnIdx: number | null
  readonly events: readonly EventUsage[]
}

/**
 * Nhóm theo `turn_idx`, giữ nguyên thứ tự `seq`. `turn_idx: null` gộp vào một
 * nhóm riêng «Chưa gán lượt» — kiểu cho phép null (`kieu.ts::EventUsage.
 * turn_idx`), chưa gặp trong fake nhưng không được rớt event nào khỏi
 * timeline chỉ vì thiếu lượt.
 */
function nhomTheoLuot(events: readonly EventUsage[]): NhomLuot[] {
  const sapXep = [...events].sort((a, b) => a.seq - b.seq)
  const nhom: { turnIdx: number | null; events: EventUsage[] }[] = []
  for (const e of sapXep) {
    const cuoi = nhom[nhom.length - 1]
    if (cuoi && cuoi.turnIdx === e.turn_idx) cuoi.events.push(e)
    else nhom.push({ turnIdx: e.turn_idx, events: [e] })
  }
  return nhom
}

/** Đường kẻ + nhãn «Lượt N» — KHÔNG accordion (xem docstring đầu file). */
function KhoiLuot({ nhom }: { readonly nhom: NhomLuot }) {
  return (
    <div>
      <div className="border-y border-border-soft bg-fill px-5 py-1.5 text-nhan font-semibold uppercase tracking-[.07em] text-muted-2">
        {nhom.turnIdx === null ? 'Chưa gán lượt' : `Lượt ${nhom.turnIdx}`}
      </div>
      {nhom.events.map((e) => (
        <DongEvent key={e.event_id} e={e} />
      ))}
    </div>
  )
}

/** Ba khối: đầu (định danh + tổng) · ghi_chu_turn (TRÊN timeline) · timeline. */
function NoiDung({
  data,
  idTieuDe,
}: {
  readonly data: ChiTietPhienData
  readonly idTieuDe: string
}) {
  const { phien } = data
  const chuaTinhTien = soSanhTien(phien.chi_phi, '0') === 0
  const nhom = nhomTheoLuot(data.events)
  return (
    <>
      <div className="flex flex-none items-start justify-between gap-4 border-b border-border-soft px-5 py-4 pr-14">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex items-center gap-1.5">
            <h2 id={idTieuDe} className="truncate font-mono text-than font-semibold text-fg">
              {phien.session_id}
            </h2>
            <NutCopySessionId sessionId={phien.session_id} />
          </div>
          <div className="flex flex-wrap items-center gap-2 text-phu text-muted">
            <span>{phien.customer_name ?? phien.phone ?? '—'}</span>
            <ChipKenh source={phien.channel} />
            <span>{rong(phien.key_label)}</span>
          </div>
        </div>
        <div className="flex flex-none flex-col items-end gap-0.5">
          <span className="text-nhan font-semibold uppercase tracking-[.07em] text-muted-2">
            Tổng chi phí
          </span>
          {/* 20px — số nổi bật CỦA PANEL này, không phải 32px («Chi phí kỳ»
              của màn chính là bậc riêng, xem `TheKpi.tsx`). */}
          <span className={`${SO_LON} text-[20px] ${chuaTinhTien ? 'text-muted' : ''}`}>
            {tien(phien.chi_phi)}
          </span>
          {chuaTinhTien && KHONG_TINH_TIEN}
        </div>
      </div>

      {/* LUẬT CỨNG SỐ MỘT — xem docstring đầu file. Nguyên văn, không `title`,
          không `<details>`, luôn hiện (không điều kiện nào che nó). */}
      <div className="flex-none border-b border-border-soft bg-badge-warn-bg px-5 py-3 text-than leading-[1.5] text-badge-warn-fg">
        {data.ghi_chu_turn}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {nhom.length === 0 ? (
          <p className="p-5 text-phu text-muted">Phiên này chưa ghi nhận event usage nào.</p>
        ) : (
          // key theo event ĐẦU của nhóm, KHÔNG theo `turnIdx ?? 'null'` — nhiều
          // nhóm `turn_idx: null` KHÔNG liền kề (event `call`/`vad` chen giữa
          // các lượt có số) đụng key, React cảnh báo và có thể tái dùng nhầm
          // DOM lúc refetch; ở màn đối soát tiền đó là hiện sai hàng event.
          // `nhomTheoLuot()` không bao giờ đẩy một nhóm rỗng vào mảng, nên
          // `events[0]` luôn tồn tại — `!` ở đây, không phải `noUncheckedIndexedAccess` bỏ qua.
          nhom.map((n) => <KhoiLuot key={n.events[0]!.event_id} nhom={n} />)
        )}
      </div>
    </>
  )
}

export function ChiTietPhien({
  sessionId,
  onDong,
}: {
  readonly sessionId: string
  /** Đóng qua CẢ BA đường (nút ×, click lớp phủ, Escape) — component KHÔNG tự
   *  biết cách xoá search param `phien`, chỉ gọi hàm này. `UsageScreen.tsx`
   *  vừa xoá param vừa trả focus về đúng hàng đã mở nó. */
  readonly onDong: () => void
}) {
  const q = useChiTietPhien(sessionId)
  const idTieuDe = useId()

  let noiDung: ReactNode
  if (q.isPending) {
    noiDung = (
      <div className="flex-1 p-5">
        <h2 id={idTieuDe} className="sr-only">
          Chi tiết phiên
        </h2>
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-10 animate-pulse rounded-md bg-fill" />
          ))}
        </div>
      </div>
    )
  } else if (q.error) {
    noiDung = (
      <div className="flex-1 p-5">
        <h2 id={idTieuDe} className="sr-only">
          Chi tiết phiên
        </h2>
        <LoiTai viec="chi tiết phiên" thuLai={() => void q.refetch()} />
      </div>
    )
  } else if (!q.data) {
    // Không xảy ra thật (`isPending`/`error` đã bắt hai ca kia) — giữ nhánh
    // này để TypeScript hẹp kiểu `q.data` ở nhánh cuối mà không cần `!`.
    noiDung = null
  } else {
    noiDung = <NoiDung data={q.data} idTieuDe={idTieuDe} />
  }

  return (
    <PanelKhung idTieuDe={idTieuDe} onDong={onDong}>
      {noiDung}
    </PanelKhung>
  )
}
