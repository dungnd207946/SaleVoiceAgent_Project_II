/**
 * Thanh đánh giá cuối phiên — DÙNG CHUNG cho tab Chat và tab Voice của
 * `/thu-agent`, và là chỗ DUY NHẤT gọi `POST /api/v1/agent/feedback`.
 *
 * Màn `/thu-agent` đóng vai một APP NGOÀI: nó nối thẳng gateway bằng khoá thô,
 * nên nó cũng ghi feedback đúng cách app ngoài ghi — cùng `AGENT_API_KEY`, cùng
 * endpoint, không đi qua phiên đăng nhập portal. Xem `guiFeedbackAgent()` ở
 * `../api.ts` (có cả cảnh báo vì sao app THẬT phải để BE của nó gọi).
 *
 * **5 SAO, KHÔNG PHẢI thumbs up/down.** Hợp đồng `FeedbackIn.rating` là số
 * nguyên 1-5, và migration `0921_bang_agent_feedback` ghi rõ đó là quyết định
 * sản phẩm chốt 2026-08-12. Một cặp 👍/👎 map thành 5/1 sẽ ghi vào đúng cột đó
 * nhưng làm biểu đồ phân bố sao ở màn `/quality` chỉ còn hai cột — nói sai về
 * chất lượng thật bằng chính dữ liệu thật.
 *
 * **Nhận xét là TUỲ CHỌN** — `comment` rỗng hợp lệ ở backend (`default=""`),
 * và không phải ai chấm sao cũng muốn viết thêm. Bắt buộc nó là đổi một feedback
 * lấy không có feedback nào.
 *
 * KHÔNG có `sessionId` ⇒ thanh vẫn hiện nhưng nút Gửi khoá, kèm câu nói RÕ vì
 * sao (`ghiChuThieuSession`). Ẩn hẳn thì người dùng tưởng tính năng biến mất;
 * hiện một nút bấm được rồi báo lỗi sau khi bấm thì tệ hơn nữa. Đây là tình
 * trạng THẬT của tab Voice hôm nay — xem `TuyChonGiongNoi.onSessionId`.
 */
import { useEffect, useRef, useState } from 'react'
import { HANG_NUT } from '@/components/ui/Bang'
import { useLang } from '@/i18n'
import { LoiApi } from '@/lib/http'
import { guiFeedbackAgent } from '../api'

const MOC_SAO = [1, 2, 3, 4, 5] as const

/** Trần của `FeedbackIn.comment` phía backend. Cắt ở đây để người dùng thấy
 *  giới hạn lúc gõ, thay vì gõ xong 2500 ký tự rồi ăn 422. */
const TRAN_NHAN_XET = 2000

export function DanhGiaPhien({
  apiKey,
  sessionId,
  ghiChuThieuSession,
  onBoQua,
  onXong,
}: {
  apiKey: string
  /** `null` = chưa biết id phiên ⇒ chưa gửi được (xem docstring file). */
  sessionId: string | null
  /** Câu giải thích khi `sessionId === null`. Bỏ trống thì không hiện gì. */
  ghiChuThieuSession?: string
  onBoQua: () => void
  /**
   * Gửi xong. CÓ truyền ⇒ người gọi tự lo phần "cảm ơn" và thường gỡ luôn
   * component này (tab Chat: đóng khung, đổi nút thành dòng «Đã gửi đánh giá»
   * dưới bong bóng). KHÔNG truyền ⇒ component tự hiện lời cảm ơn tại chỗ (tab
   * Voice, nơi không có nút nào để đổi trạng thái).
   */
  onXong?: () => void
}) {
  const { t } = useLang()
  const [sao, setSao] = useState(0)
  const [nhanXet, setNhanXet] = useState('')
  const [dangGui, setDangGui] = useState(false)
  const [loi, setLoi] = useState<string | null>(null)
  const [xong, setXong] = useState(false)
  const goc = useRef<HTMLDivElement>(null)

  // Ở tab Chat, khung này mount BÊN TRONG khung hội thoại (một hộp cuộn cao
  // 46vh) khi người dùng bấm nút dưới bong bóng cuối — nếu bong bóng đó đang ở
  // sát đáy thì khung vừa mở ra đã nằm ngoài tầm nhìn. `?.` hai lần vì jsdom
  // không có `scrollIntoView` (test sẽ nổ chứ không bỏ qua).
  useEffect(() => {
    goc.current?.scrollIntoView?.({ block: 'nearest' })
  }, [])

  async function gui(): Promise<void> {
    if (sao === 0 || sessionId === null || dangGui) return
    setDangGui(true)
    setLoi(null)
    try {
      await guiFeedbackAgent(apiKey, { sessionId, rating: sao, comment: nhanXet.trim() })
      setXong(true)
      onXong?.()
    } catch (e) {
      // Hiện NGUYÊN câu của backend (`INVALID_AGENT_KEY`/`TENANT_SUSPENDED`…):
      // ở màn thử, người đọc chính là người vừa chọn khoá — họ sửa được.
      setLoi(e instanceof LoiApi ? e.message : t({ vi: 'Không gửi được.', en: 'Send failed.' }))
    } finally {
      setDangGui(false)
    }
  }

  if (xong)
    return (
      <p className="mt-3 rounded-lg border border-border bg-surface px-4 py-3 text-[13px] text-muted">
        {t({ vi: 'Cảm ơn bạn đã đánh giá.', en: 'Thanks for your feedback.' })}
      </p>
    )

  const guiDuoc = sao > 0 && sessionId !== null && !dangGui

  return (
    /* KHÔNG khoá bề rộng ở đây — chỗ gọi quyết (2026-08-24, người dùng báo lệch
       trên màn thật): tab Chat bọc `max-w-[420px]` vì thẻ nằm DƯỚI BONG BÓNG
       trong khung hội thoại; tab Voice để full-width vì thẻ đứng NGANG HÀNG với
       các thẻ full-width khác của màn — một thẻ 420px dạt trái ở đó đọc thành
       vỡ bố cục chứ không thành chủ ý. */
    <div ref={goc} className="mt-1 w-full rounded-lg border border-border bg-surface px-4 py-3.5">
      <p className="text-[13px] font-semibold text-fg">
        {t({ vi: 'Bạn thấy cuộc trò chuyện thế nào?', en: 'How was this conversation?' })}
      </p>

      {/* Roving tabindex: một điểm dừng Tab cho cả nhóm, mũi tên đi giữa các sao
          — đúng khuôn radiogroup, không phải 5 nút cùng nằm trong luồng Tab. */}
      <div
        role="radiogroup"
        aria-label={t({ vi: 'Chấm điểm', en: 'Rating' })}
        className="mt-2 flex items-center gap-1"
        onKeyDown={(e) => {
          if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
          e.preventDefault()
          const buoc = e.key === 'ArrowRight' ? 1 : -1
          setSao((c) => Math.min(5, Math.max(1, (c === 0 ? 0 : c) + buoc)))
        }}
      >
        {MOC_SAO.map((n) => (
          <button
            key={n}
            type="button"
            role="radio"
            aria-checked={sao === n}
            aria-label={t({ vi: `${n} sao`, en: `${n} star${n > 1 ? 's' : ''}` })}
            tabIndex={sao === n || (sao === 0 && n === 1) ? 0 : -1}
            onClick={() => setSao(n)}
            className={`rounded-sm px-0.5 text-[20px] leading-none ${
              n <= sao ? 'text-ac' : 'text-muted-3 hover:text-muted-2'
            }`}
          >
            <span aria-hidden="true">{n <= sao ? '★' : '☆'}</span>
          </button>
        ))}
      </div>

      <label className="mt-3 block">
        <span className="mb-1 block text-[12px] text-muted">
          {t({ vi: 'Nhận xét (tuỳ chọn)', en: 'Comment (optional)' })}
        </span>
        <textarea
          rows={2}
          maxLength={TRAN_NHAN_XET}
          value={nhanXet}
          onChange={(e) => setNhanXet(e.target.value)}
          aria-label={t({ vi: 'Nhận xét (tuỳ chọn)', en: 'Comment (optional)' })}
          placeholder={t({ vi: 'VD: Trả lời nhanh, đúng ý.', en: 'e.g. Fast and on point.' })}
          className="w-full resize-y rounded-md border border-border-field bg-surface px-2.5 py-[7px] text-than outline-none focus:border-ac"
        />
      </label>

      {sessionId === null && ghiChuThieuSession && (
        <p className="mt-2 text-phu leading-[1.5] text-muted-2">{ghiChuThieuSession}</p>
      )}

      <div className={`mt-2.5 ${HANG_NUT}`}>
        <button
          type="button"
          onClick={onBoQua}
          className="rounded-md px-3 py-[7px] text-[13px] text-muted hover:underline"
        >
          {t({ vi: 'Bỏ qua', en: 'Skip' })}
        </button>
        <button
          type="button"
          onClick={() => void gui()}
          disabled={!guiDuoc}
          className="rounded-md bg-ac px-4 py-[9px] text-than font-semibold text-white hover:bg-acd disabled:opacity-50"
        >
          {dangGui
            ? t({ vi: 'Đang gửi…', en: 'Sending…' })
            : t({ vi: 'Gửi đánh giá', en: 'Send feedback' })}
        </button>
      </div>

      {loi && (
        <p role="alert" className="mt-2 text-phu leading-[1.5] text-badge-alert-fg">
          {loi}
        </p>
      )}
    </div>
  )
}
