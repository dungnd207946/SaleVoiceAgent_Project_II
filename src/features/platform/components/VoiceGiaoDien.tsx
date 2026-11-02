/**
 * Các mảnh GIAO DIỆN của tab Voice (`/thu-agent`) — bố cục «cuộc gọi video»
 * (người dùng chọn phương án A từ bản vẽ `docs/design/demo-voice-san-khau.html`,
 * 2026-10-01):
 *
 * ```
 * ┌ thiết lập năm ô + Áp dụng (ở lại sau Áp dụng) ────────────────────── ┐
 * ├────────── trái: phần còn lại ─────┬──── phải ≤ min(48%,640px) ─────┤
 * │ Hội thoại                         │ sân khấu 3:2 (nền + người dẫn)  │
 * │   bong bóng… (tự cuộn)            │   nhãn trạng thái · đếm ảnh     │
 * │                                   │   phụ đề câu agent đang nói     │
 * │                                   │   (cao kín cột, nhân vật giữ cỡ)│
 * │                                   │ thanh cuộc gọi                  │
 * │                                   │ (đánh giá sau cuộc gọi)         │
 * └───────────────────────────────────┴─────────────────────────────────┘
 * ```
 *
 * Hội thoại được NHIỀU chỗ hơn sân khấu là có chủ ý (người dùng: «ưu tiên phần
 * hội thoại… để người dùng đỡ nhìn thấy nhân vật bị giả»); hội thoại TRÁI, sân
 * khấu PHẢI (người dùng chốt 2026-10-02). Desktop: cả vùng Voice cao VỪA một
 * màn — không cuộn trang; hội thoại dài thì chỉ khung hội thoại cuộn. Hai cột
 * cao BẰNG NHAU, cạnh dưới sát đáy màn: sân khấu kéo cao lấp kín cột (không
 * còn ô trống bên dưới — bản «Gợi ý để thử» lấp chỗ đó đã bị bỏ, người dùng
 * chê không hợp lý). Dưới `lg`: xếp dọc, sân khấu 3:2 ở trên.
 *
 * Tệp chỉ có component (eslint `react-refresh/only-export-components`); logic
 * cuộc gọi vẫn ở `CheGiongNoi` (`ThuAgentScreen.tsx`).
 */
import { useEffect, useState } from 'react'
import { Icon } from '@/components/icons'
import { useLang } from '@/i18n'
import { useTuCuonCuoi } from '../useTuCuonCuoi'

/** Hai cột desktop, cao bằng PHẦN CÒN LẠI của vùng Voice (`flex-1` — vùng
 *  Voice cao đúng một màn, xem `KHUNG_VOICE`). Bản trước khoá cứng
 *  `100dvh − 236px`, số đo theo dòng thiết lập THU GỌN: lúc chưa Áp dụng thì
 *  form năm ô cao hơn nên trang cuộn thừa một đoạn trống (người dùng báo
 *  2026-10-02). DOM giữ sân khấu TRƯỚC (mobile xếp dọc sân khấu trên); desktop
 *  đảo bằng `order`. `min-h` giữ cho màn lùn không bóp hội thoại thành sợi chỉ.
 *  280px chứ không 340 (05/10): thẻ «Cần một API Key» (84px) chỉ hiện khi chưa có
 *  khoá dùng được, và ở 1280×720 nó chỉ chừa 287px ⇒ 340 làm trang cuộn 29px.
 *  280 vẫn đủ cột sân khấu (180 sân khấu + 64 thanh gọi + khe). */
export function BoCucVoice({
  sanKhau,
  hoiThoai,
}: {
  sanKhau: React.ReactNode
  hoiThoai: React.ReactNode
}) {
  return (
    <div className="grid grid-cols-1 gap-4 lg:min-h-[280px] lg:flex-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,min(48%,640px))] lg:grid-rows-[minmax(0,1fr)]">
      <div className="flex min-h-0 flex-col gap-3 lg:order-2">{sanKhau}</div>
      <div className="flex min-h-0 flex-col max-lg:h-[62vh] max-lg:min-h-[360px] lg:order-1">
        {hoiThoai}
      </div>
    </div>
  )
}

/** Lớp của vùng Voice: desktop cao ĐÚNG phần màn dưới topbar (72px) và xếp
 *  dọc, để `BoCucVoice` (`flex-1`) lấp vừa chỗ còn lại dù phía trên là form năm
 *  ô hay dòng thu gọn. */
export const KHUNG_VOICE = 'lg:flex lg:h-[calc(100dvh-72px)] lg:flex-col'

/** Khung hội thoại cao TRỌN cột phải: đầu khung cố định, thân tự cuộn theo
 *  chữ mới (trừ khi người dùng đang cuộn lên đọc lại — `useTuCuonCuoi`). */
export function KhungHoiThoaiVoice({
  soLuot,
  dangTraLoi = false,
  children,
}: {
  soLuot: number
  /** Lượt agent đang mở (`agent_speaking` → `agent_done`) ⇒ `aria-busy`:
   *  trình đọc màn hình chờ trọn lượt rồi mới đọc, không đọc từng câu. */
  dangTraLoi?: boolean
  children: React.ReactNode
}) {
  const { t } = useLang()
  const hop = useTuCuonCuoi<HTMLDivElement>()
  const ten = t({ vi: 'Hội thoại', en: 'Conversation' })
  return (
    <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border bg-surface">
      <header className="flex flex-none items-center justify-between border-b border-border px-5 py-3">
        <h2 className="text-[14px] font-semibold text-fg">{ten}</h2>
        {soLuot > 0 && (
          <span className="font-mono text-[11.5px] text-muted-2">
            {soLuot} {t({ vi: 'lượt', en: soLuot === 1 ? 'turn' : 'turns' })}
          </span>
        )}
      </header>
      <div
        ref={hop}
        role="log"
        aria-label={ten}
        aria-busy={dangTraLoi}
        className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-y-auto px-5 py-4"
      >
        {children}
      </div>
    </section>
  )
}

/** Hội thoại còn trống — mời bắt đầu, nói rõ trải nghiệm là một CUỘC GỌI. */
export function HoiThoaiTrong({ chu }: { chu?: string }) {
  const { t } = useLang()
  return (
    <div className="my-auto flex flex-col items-center gap-3 px-6 py-8 text-center">
      <span className="grid size-12 place-items-center rounded-full bg-acs text-ac">
        <Icon name="voice" className="size-6" />
      </span>
      <p className="text-[14px] font-semibold text-fg">
        {t({ vi: 'Trò chuyện với agent bằng giọng nói', en: 'Talk to the agent by voice' })}
      </p>
      <p className="max-w-[40ch] text-[13px] leading-[1.55] text-muted-2">
        {chu ??
          t({
            vi: 'Bấm «Bắt đầu trò chuyện», cho phép micro rồi nói như một cuộc gọi. Chưa có tin nhắn.',
            en: 'Press «Start talking», allow the microphone and speak as on a call. No messages yet.',
          })}
      </p>
    </div>
  )
}

/**
 * Lớp phủ trên sân khấu: nhãn trực tiếp / agent đang nói (trái trên), đếm ảnh
 * nền đang luân phiên (phải trên), phụ đề câu agent đang nói (trái dưới — phía
 * bên kia người dẫn, không đè lên người). Chỉ để NHÌN: chữ thật nằm trong khung
 * hội thoại, nên cả lớp `aria-hidden` theo sân khấu.
 */
export function LopPhuSanKhau({
  trucTiep,
  agentNoi,
  cau,
  soAnh,
  anhThu,
}: {
  trucTiep: boolean
  agentNoi: boolean
  cau: string | null
  soAnh: number
  anhThu: number
}) {
  const { t } = useLang()
  return (
    <div className="pointer-events-none absolute inset-0 z-10">
      {/* Dải tối mờ cho phụ đề KHÔNG ở đây: lớp này nằm trên người dẫn, nên dải tối
          đặt ở đây là làm tối luôn nhân vật — xem `SanKhauAgent.toiDay`. */}
      {trucTiep && (
        <span className="absolute left-3 top-3 inline-flex items-center gap-2 rounded-full bg-panel/55 px-2.5 py-1 text-[11.5px] font-medium text-white backdrop-blur-md">
          <span
            className={`size-2 rounded-full ${agentNoi ? 'bg-white' : 'bg-ac san-khau-truc-tiep'}`}
          />
          {agentNoi
            ? t({ vi: 'Agent đang nói', en: 'Agent speaking' })
            : t({ vi: 'Trực tiếp', en: 'Live' })}
          {agentNoi && (
            <span className="inline-flex h-2.5 items-end gap-[2px]">
              {[0, 1, 2, 3].map((i) => (
                <i
                  key={i}
                  className="san-khau-song block w-[2px] rounded-full bg-white"
                  style={{ animationDelay: `${i * 0.13}s` }}
                />
              ))}
            </span>
          )}
        </span>
      )}
      {soAnh > 1 && (
        <span className="absolute right-3 top-3 inline-flex items-center gap-1.5 rounded-full bg-panel/55 px-2.5 py-1 backdrop-blur-md">
          {Array.from({ length: soAnh }, (_, i) => (
            <span
              key={i}
              className={`size-1.5 rounded-full ${i === anhThu ? 'bg-white' : 'bg-white/40'}`}
            />
          ))}
          <span className="ml-0.5 font-mono text-nhan text-white">
            {anhThu + 1}/{soAnh}
          </span>
        </span>
      )}
      {cau && (
        // Chữ phụ đề đi qua CSS `content: attr(data-cau)`, KHÔNG làm nút chữ
        // trong DOM: nó là BẢN SAO để nhìn của câu đã có trong khung hội thoại
        // — để nó thành chữ thật là trình đọc màn hình đọc hai lần, và mọi
        // truy vấn theo chữ (test) thấy hai chỗ cho một câu.
        <p
          data-cau={cau}
          className="absolute bottom-3 left-3 line-clamp-3 max-w-[58%] @max-md:line-clamp-2 text-[13px] font-medium leading-[1.5] text-white [text-shadow:0_1px_6px_rgb(0_0_0/0.45)] after:content-[attr(data-cau)]"
        />
      )}
    </div>
  )
}

/**
 * Thanh CUỘC GỌI dưới sân khấu: ô mức micro (vòng sáng to dần theo tiếng) ·
 * trạng thái + đồng hồ cuộc gọi · nút chính. Một nút đổi vai theo trạng thái
 * (Bắt đầu xanh ↔ Kết thúc đỏ), như nút gọi/cúp của một cuộc gọi thật.
 */
export function ThanhGoi({
  nhan,
  dangNghe,
  giay,
  datMucRef,
  dangChay,
  khoa,
  goiY,
  onBatDau,
  onKetThuc,
}: {
  nhan: string
  dangNghe: boolean
  giay: number
  /** Kênh đẩy mức mic (~12 lần/giây, mỗi khối mic một lần) THẲNG vào thanh
   *  này. Qua state của màn thì mỗi khối mic vẽ lại cả sân khấu lẫn khung hội
   *  thoại. Vắng ⇒ mức 0. */
  datMucRef?: React.MutableRefObject<(m: number) => void>
  dangChay: boolean
  /** Chưa Áp dụng thiết lập ⇒ nút Bắt đầu khoá, `goiY` nói vì sao. */
  khoa?: boolean
  goiY?: string
  onBatDau: () => void
  onKetThuc: () => void
}) {
  const { t } = useLang()
  const [muc, setMuc] = useState(0)
  useEffect(() => {
    if (!datMucRef) return
    datMucRef.current = setMuc
    return () => {
      datMucRef.current = () => {}
    }
  }, [datMucRef])
  const phanTram = Math.round(muc * 100)
  const mm = String(Math.floor(giay / 60)).padStart(2, '0')
  const ss = String(giay % 60).padStart(2, '0')
  return (
    <div className="flex flex-none items-center gap-3 rounded-lg border border-border bg-surface px-3.5 py-3">
      {/* Vạch mức mic — bằng chứng NHÌN THẤY ĐƯỢC rằng mic đang vào. Không có
          nó thì "Đang nghe" chỉ là một dòng chữ, và người dùng nói vào khoảng
          không mà không biết máy có nhận không. Nay là vòng sáng quanh icon mic. */}
      <div
        role="meter"
        aria-label={t({ vi: 'Mức micro', en: 'Microphone level' })}
        aria-valuenow={phanTram}
        aria-valuemin={0}
        aria-valuemax={100}
        className={`relative grid size-10 flex-none place-items-center rounded-full ${dangNghe ? 'bg-acs text-ac' : 'bg-fill-strong text-muted-2'}`}
      >
        <span
          aria-hidden="true"
          className="absolute -inset-1 rounded-full border-2 border-ac transition-[opacity,transform] duration-100"
          style={{
            opacity: dangNghe ? 0.15 + muc * 0.85 : 0,
            transform: `scale(${1 + muc * 0.18})`,
          }}
        />
        <Icon name="mic" className="size-[18px]" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className={`size-2 flex-none rounded-full ${dangNghe ? 'bg-ac' : 'bg-muted-2'}`} />
          {/* `status` sống suốt cuộc gọi, chỉ CHỮ đổi — nên «Đang gọi…» → «Đang
              nghe» được đọc lên (WCAG 4.1.3). Đồng hồ cố ý ở NGOÀI: nó đổi mỗi
              giây. Lỗi đi `role="alert"` riêng (`Loi` ở `ThuAgentScreen`). */}
          <span role="status" className="truncate text-than font-medium text-fg">
            {nhan}
          </span>
          {dangChay && (
            <span
              className="ml-auto font-mono text-[12px] text-muted-2"
              aria-label={t({ vi: 'Thời lượng', en: 'Duration' })}
            >
              {mm}:{ss}
            </span>
          )}
        </div>
        {goiY && <p className="mt-0.5 truncate text-[12px] text-muted-2">{goiY}</p>}
      </div>
      {dangChay ? (
        <button
          type="button"
          onClick={onKetThuc}
          className="inline-flex flex-none cursor-pointer items-center gap-2 rounded-full bg-badge-alert-fg px-4 py-2.5 text-than font-semibold text-white shadow-sm transition-transform hover:scale-[1.03]"
        >
          <Icon name="cupMay" className="size-4" />
          {t({ vi: 'Kết thúc', en: 'End' })}
        </button>
      ) : (
        <button
          type="button"
          onClick={onBatDau}
          disabled={khoa}
          className="inline-flex flex-none cursor-pointer items-center gap-2 rounded-full bg-ac px-4 py-2.5 text-than font-semibold text-white shadow-sm transition-transform hover:scale-[1.03] hover:bg-acd disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:scale-100"
        >
          <Icon name="goiDien" className="size-4" />
          {t({ vi: 'Bắt đầu trò chuyện', en: 'Start talking' })}
        </button>
      )}
    </div>
  )
}
