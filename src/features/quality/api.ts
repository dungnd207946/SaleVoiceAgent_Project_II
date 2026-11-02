/**
 * Client HTTP của màn `/quality` (CSAT) — feedback agent.
 *
 * Kiểu ở đây là bản chép tay của `modules/enrollment/contracts.py`
 * (`FeedbackOut`/`DanhSachFeedbackOut`). Lệch tên field thì màn hiện
 * `undefined` chứ không nổ — đổi thì đổi cùng commit.
 */
import { goi as goiApi } from '@/lib/http'

const GOC = '/api/v1/agent'

export const TRANG_MAC_DINH_FEEDBACK = 50

const goi = <T>(duong: string) => goiApi<T>(`${GOC}${duong}`, {}, duong)

export interface Feedback {
  readonly id: number
  readonly sessionId: string
  readonly rating: number
  readonly comment: string
  readonly createdAt: string
  readonly customerName: string | null
  readonly phone: string | null
  /**
   * Kênh phiên đến từ đâu — `'voice'` | `'chat'` | … `null` = chưa biết.
   *
   * KHÔNG hẹp thành union hai giá trị: cột nguồn (`conversations.source`) là
   * `text` không CHECK có chủ ý vì tập kênh chưa chốt (zalo/facebook… có thể
   * tới bất cứ lúc nào), và một union ở đây chỉ khiến chỗ dùng tin vào một lời
   * hứa backend không ký. Cùng hình dạng `PhienOut.source` mà `features/ops`
   * đã khai.
   */
  readonly source: string | null
}

export interface DanhSachFeedback {
  readonly items: readonly Feedback[]
  readonly nextBeforeId: number | null
  readonly total: number
  readonly theoSao: Readonly<Record<'1' | '2' | '3' | '4' | '5', number>>
  readonly diemTrungBinh: number
}

export interface LocFeedback {
  readonly ratings?: readonly number[]
  readonly beforeId?: number
}

/** Hình dạng RAW từ backend (snake_case) — `goi()` trả thẳng JSON, chuyển đổi ở đây. */
interface FeedbackOutTho {
  readonly id: number
  readonly session_id: string
  readonly rating: number
  readonly comment: string
  readonly created_at: string
  readonly customer_name: string | null
  readonly phone: string | null
  readonly source: string | null
}

interface DanhSachFeedbackOutTho {
  readonly items: readonly FeedbackOutTho[]
  readonly next_before_id: number | null
  readonly total: number
  readonly theo_sao: Readonly<Record<string, number>>
  readonly diem_trung_binh: number
}

function chuanHoaFeedback(r: FeedbackOutTho): Feedback {
  return {
    id: r.id,
    sessionId: r.session_id,
    rating: r.rating,
    comment: r.comment,
    createdAt: r.created_at,
    // `?? null` — KHÔNG chép thẳng. Backend cho hai field này TỪ MỘT LEFT
    // JOIN thêm sau (spec §2 việc 3, chưa lên nhánh chính lúc viết dòng này —
    // xem CLAUDE.md gốc mục "Tự bảo trì"), nên một backend cũ/chưa cập nhật
    // có thể bỏ hẳn khoá này khỏi JSON ⇒ `r.customer_name`/`r.phone` ra
    // `undefined`, không phải `null`. `FeedbackReviewCard.tsx` guard bằng
    // `feedback.phone !== null` — `undefined` lọt qua guard đó, ra
    // `<Link params={{ phone: undefined }}>` → `/convos/undefined`. Các
    // field còn lại (`id`/`rating`/`comment`/`created_at`) đã tồn tại từ bản
    // đầu của endpoint nên không cần khiên này.
    customerName: r.customer_name ?? null,
    phone: r.phone ?? null,
    // Cùng khiên `?? null`, và ở đây còn cần hơn: trường này lên backend sau
    // hai trường trên (2026-08-13), nên một backend chưa deploy bản mới bỏ hẳn
    // khoá khỏi JSON. `undefined` lọt mọi guard `!== null` — chip kênh khi đó
    // vẽ ra từ một giá trị không có.
    source: r.source ?? null,
  }
}

export async function danhSachFeedback(loc: LocFeedback = {}): Promise<DanhSachFeedback> {
  const p = new URLSearchParams()
  p.set('limit', String(TRANG_MAC_DINH_FEEDBACK))
  for (const r of loc.ratings ?? []) p.append('rating', String(r))
  if (loc.beforeId !== undefined) p.set('before_id', String(loc.beforeId))

  const tho = await goi<DanhSachFeedbackOutTho>(`/feedback?${p.toString()}`)
  return {
    items: tho.items.map(chuanHoaFeedback),
    nextBeforeId: tho.next_before_id,
    total: tho.total,
    theoSao: {
      '1': tho.theo_sao['1'] ?? 0,
      '2': tho.theo_sao['2'] ?? 0,
      '3': tho.theo_sao['3'] ?? 0,
      '4': tho.theo_sao['4'] ?? 0,
      '5': tho.theo_sao['5'] ?? 0,
    },
    diemTrungBinh: tho.diem_trung_binh,
  }
}

export async function feedbackCuaPhien(sessionId: string): Promise<Feedback | null> {
  const p = new URLSearchParams()
  p.set('session_id', sessionId)
  p.set('limit', '1')
  const tho = await goi<DanhSachFeedbackOutTho>(`/feedback?${p.toString()}`)
  return tho.items[0] ? chuanHoaFeedback(tho.items[0]) : null
}
