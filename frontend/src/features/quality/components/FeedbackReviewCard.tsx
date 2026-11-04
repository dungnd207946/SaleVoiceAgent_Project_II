/**
 * Một khối feedback dạng review (kiểu Shopee) — dùng ở danh sách `/quality`
 * (Task 8 lặp mảng `Feedback` qua component này).
 *
 * ⚠️ KHÔNG che tên/sđt. Mockup lúc chốt thiết kế dùng giá trị che
 * (`Trần Văn A***`, `090***4567`) chỉ để gợi cảm giác Shopee trong lúc dựng
 * layout — quyết định cuối (plan §6) là hiện ĐẦY ĐỦ: đây là tool nội bộ,
 * nhân viên xem đúng khách của workspace mình (không phải marketplace công
 * khai), `/convos` đã hiện đầy đủ tên/số ở màn khác, và che số sẽ chặn đúng
 * hành động một feedback "Cần chú ý" đòi hỏi — gọi lại cho khách.
 */
import { Link } from '@tanstack/react-router'
import { ChipKenh } from '@/components/ui/ChipKenh'
import { Sao } from '@/components/ui/Sao'
import { gioPhut, ngayThang } from '@/lib/dinhDang'
import type { Feedback } from '../api'

function ngayGio(iso: string): string {
  const d = new Date(iso)
  return `${ngayThang(d)} · ${gioPhut(d)}`
}

function chuCaiDau(ten: string | null): string {
  return ten ? ten.trim().charAt(0).toUpperCase() : '?'
}

export function FeedbackReviewCard({ feedback }: { feedback: Feedback }) {
  const canChuY = feedback.rating <= 2

  return (
    <div className="border-b border-border-soft px-6 py-4 last:border-b-0">
      <div className="flex items-start gap-2.5">
        <span className="flex size-[34px] shrink-0 items-center justify-center rounded-full bg-acs text-[14px] font-semibold text-acd">
          {chuCaiDau(feedback.customerName)}
        </span>
        <div className="flex min-w-0 flex-col gap-px">
          <p className="flex items-center gap-1.5 text-the font-medium">
            {feedback.customerName ?? 'Khách ẩn danh'}
            <span className="text-border-strong">|</span>
            <span className="text-[13px] font-normal text-muted">
              {feedback.phone ?? '— không có số —'}
            </span>
          </p>
          <Sao gia={feedback.rating} kichThuoc={13} />
        </div>
        <p className="ml-auto shrink-0 text-[12px] text-muted-2">{ngayGio(feedback.createdAt)}</p>
      </div>
      <p
        className={`ml-[44px] mt-2 text-[14px] leading-[1.55] ${feedback.comment ? 'text-fg' : 'italic text-muted'}`}
      >
        {feedback.comment || '(không để lại nhận xét)'}
      </p>
      <div className="ml-[44px] mt-2 flex items-center gap-2.5 max-md:ml-0 max-md:flex-wrap">
        {canChuY && (
          <span className="rounded-full bg-badge-alert-bg px-2 py-0.5 text-[12px] text-badge-alert-fg">
            Cần chú ý
          </span>
        )}
        <ChipKenh source={feedback.source} />
        {feedback.phone !== null && (
          <Link
            to="/convos/$phone"
            params={{ phone: feedback.phone }}
            search={{ session: feedback.sessionId }}
            className="text-[13px] text-acd underline decoration-acs"
          >
            Xem phiên trò chuyện
          </Link>
        )}
      </div>
    </div>
  )
}
