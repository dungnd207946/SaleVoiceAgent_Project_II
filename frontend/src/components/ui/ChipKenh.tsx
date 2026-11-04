/**
 * Chip KÊNH của một phiên — `conversations.source` do agent ghi
 * (`base_session`/`telephony` → `voice`, `text_chat` → `chat`).
 *
 * Ở `components/ui/` chứ không ở một feature: **hai** module dùng nó —
 * `features/quality` (card feedback ở `/quality`) và `features/ops` (danh sách
 * phiên ở `/convos/$phone`) — và luật ranh giới cấm module này import ruột
 * module kia (`tests/module-boundaries.test.ts`). Để hai bản sao thì màu hai
 * màn lệch nhau ở lần sửa sau, mà chip này tồn tại chính là để nhận ra kênh
 * bằng màu.
 *
 * MÀU: mỗi kênh một sắc riêng (token `badge-kenh-*` ở `theme.css`, đã đo WCAG)
 * — người dùng quét danh sách bằng mắt trước khi đọc nhãn, hai chip xám giống
 * hệt nhau thì phải đọc từng cái. Không dùng accent: accent dành cho hành động
 * chính và mục nav đang mở.
 *
 * ⚠️ Chip kênh là badge DUY NHẤT của portal CÓ VIỀN, và đó không phải trang
 * trí: nó đứng trên HAI nền (thẻ trắng ở `/quality`, nền `acs` của hàng phiên
 * đang chọn ở `/convos`), còn mọi badge tint-nhạt khác chỉ đứng trên trắng. Nền
 * nhạt trên `acs` cho tỉ lệ 1.00 — chip biến mất; viền là thứ tách nó ra. Ba
 * lượt mới ra hình dạng này, đọc khối comment `badge-kenh-*` ở `theme.css`
 * trước khi bỏ viền đi cho "gọn".
 *
 * Riêng chip kênh LẠ vẫn để tint nhạt KHÔNG viền (`badge-neutral`): nó CHỈ
 * render ở `/quality` (nền trắng, cạnh badge «Cần chú ý» cũng tint nhạt) vì
 * `/convos` bật `anKhiLa` — không có ca nào nó đứng trên `acs`.
 */
import { Icon, type IconName } from '@/components/icons'

const KENH: Readonly<Record<string, { nhan: string; icon: IconName; lop: string }>> = {
  chat: {
    nhan: 'Chat',
    icon: 'convos',
    lop: 'border-badge-kenh-chat-vien bg-badge-kenh-chat-bg text-badge-kenh-chat-fg',
  },
  voice: {
    nhan: 'Voice',
    icon: 'voice',
    lop: 'border-badge-kenh-voice-vien bg-badge-kenh-voice-bg text-badge-kenh-voice-fg',
  },
}

export function ChipKenh({
  source,
  anKhiLa,
}: {
  /** `null` = chưa biết kênh ⇒ KHÔNG vẽ gì. Hai ca gộp vào đây: chưa có hàng
   *  `conversations` khớp, và agent bản cũ chưa gửi trường này. */
  source: string | null
  /**
   * Kênh LẠ (backend thêm `zalo`/`facebook`…) thì ẩn luôn thay vì hiện nguyên
   * văn. Mặc định `false` — cột nguồn là `text` không CHECK có chủ ý, nên nuốt
   * im lặng một kênh mới là giấu đúng thứ cần thấy.
   *
   * `/convos/$phone` bật cờ này: ở đó chip đứng trong một danh sách CÓ BỘ LỌC
   * theo kênh (`locTheoNguon`, hai tab Chat/Voice), và một chip nằm ngoài tập
   * mà bộ lọc biết sẽ hứa một tab không tồn tại.
   */
  anKhiLa?: boolean
}) {
  if (source === null) return null
  const k = KENH[source]
  if (!k) {
    if (anKhiLa) return null
    return (
      <span className="inline-flex shrink-0 items-center rounded-full bg-badge-neutral-bg px-2 py-0.5 text-phu text-badge-neutral-fg">
        {source}
      </span>
    )
  }
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-[1px] text-phu font-medium ${k.lop}`}
    >
      <Icon name={k.icon} className="size-3.5" />
      {k.nhan}
    </span>
  )
}
