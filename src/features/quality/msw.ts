/**
 * Fake của màn `/quality` — 5 feedback mẫu, đủ ca biên: có/không comment,
 * có/không tên+sđt (khách ẩn danh), rating trải đều 1-5 để dải phân bố có
 * hình dạng thật khi dev không cần backend.
 *
 * ⚠️ **`total`/`theo_sao`/`diem_trung_binh` KHÔNG suy từ 5 hàng dưới đây**
 * (đổi 2026-08-14) — chúng đọc `lib/msw/danhGiaGia.ts`, dùng chung với fake
 * `GET /overview` của module `ops`. Hai lý do, và cả hai đều là hành vi của
 * backend thật chứ không phải mẹo cho khớp số:
 *   · `liet_ke_feedback_cua_tenant` phân trang `items` nhưng tính ba trường
 *     thống kê trên TOÀN BỘ feedback của tenant, bất kể bộ lọc đang áp — suy
 *     tổng từ trang đầu là mô hình hoá sai chính endpoint này;
 *   · ô ③ màn Tổng quan đọc cùng một đại lượng. Hai bảng số viết tay rời nhau
 *     làm hai màn cạnh nhau in hai con số khác nhau — xem docstring file kia.
 */
import { http, HttpResponse } from 'msw'
import { DIEM_TRUNG_BINH_GIA, PHAN_BO_SAO_GIA, TONG_DANH_GIA_GIA } from '@/lib/msw/danhGiaGia'

interface FeedbackGia {
  id: number
  session_id: string
  rating: number
  comment: string
  created_at: string
  customer_name: string | null
  phone: string | null
  /** Kênh phiên (`conversations.source`). Năm hàng dưới cố ý phủ CẢ BA ca thật:
   *  `chat`, `voice`, và `null` (agent bản cũ / chưa có hàng `conversations`) —
   *  fake chỉ có kênh đã biết thì nhánh "không vẽ chip" không bao giờ được nhìn
   *  thấy trong lúc dựng màn. */
  source: string | null
}

const FEEDBACK_GIA: FeedbackGia[] = [
  {
    id: 5,
    session_id: 's-anh-1',
    rating: 5,
    comment: 'Trả lời nhanh, đúng ý.',
    created_at: '2026-08-12T09:00:00+07:00',
    customer_name: 'Nguyễn Minh Anh',
    phone: '0912448111',
    source: 'chat',
  },
  {
    id: 4,
    session_id: 's-quang',
    rating: 2,
    comment: 'Agent trả lời chậm, hỏi 2 lần mới ra đúng thông tin căn hộ.',
    created_at: '2026-08-11T15:30:00+07:00',
    customer_name: 'Trần Quang',
    phone: '0987112222',
    source: 'voice',
  },
  {
    id: 3,
    session_id: 's-an-1',
    rating: 4,
    comment: '',
    created_at: '2026-08-11T10:15:00+07:00',
    customer_name: null,
    phone: null,
    source: null,
  },
  {
    id: 2,
    session_id: 's-hoa',
    rating: 3,
    comment: 'Tạm ổn, có vài chỗ trả lời chưa sát ý.',
    created_at: '2026-08-10T14:00:00+07:00',
    customer_name: 'Lê Thị Hoa',
    phone: '0909000111',
    source: 'chat',
  },
  {
    id: 1,
    session_id: 's-nam',
    rating: 1,
    comment: 'Không tìm được dự án tôi hỏi.',
    created_at: '2026-08-09T08:45:00+07:00',
    customer_name: 'Phạm Văn Nam',
    phone: '0933444555',
    source: 'voice',
  },
]

export const qualityHandlers = [
  http.get('/api/v1/agent/feedback', ({ request }) => {
    const url = new URL(request.url)
    const ratings = url.searchParams.getAll('rating').map(Number)
    const sessionId = url.searchParams.get('session_id')

    let loc = FEEDBACK_GIA
    if (ratings.length > 0) loc = loc.filter((f) => ratings.includes(f.rating))
    if (sessionId) loc = loc.filter((f) => f.session_id === sessionId)

    return HttpResponse.json({
      items: loc,
      next_before_id: null,
      // Ba trường thống kê KHÔNG đọc `loc`, và cũng không đọc `FEEDBACK_GIA`
      // — xem docstring đầu file.
      total: TONG_DANH_GIA_GIA,
      theo_sao: PHAN_BO_SAO_GIA,
      diem_trung_binh: DIEM_TRUNG_BINH_GIA,
    })
  }),
]
