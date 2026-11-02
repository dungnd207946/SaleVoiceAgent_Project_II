/**
 * Thanh trên — tiêu đề màn và ô mở ⌘K. Cao 72px, sticky, nền `bg` 86% + blur
 * 10px, viền dưới `border`.
 *
 * KHÔNG CÒN TOGGLE NGÔN NGỮ (người dùng chốt 2026-08-09) — nó chuyển vào menu
 * «Hồ sơ & tuỳ chọn» ở đáy panel; xem `LangToggle.tsx`.
 *
 * Tiêu đề lấy từ chính nav item của màn, KHÔNG có bảng tiêu đề riêng — hai
 * nguồn cho một chuỗi là hai chỗ để lệch nhau. Bảng `EXTRA_TITLES` từng nằm ở
 * file này cho bốn màn ngoài nav đã chuyển sang `OFF_NAV` trong nav-registry
 * (2026-08-07): rail cần đúng danh sách path ấy để biết tô sáng mảng nào, và
 * hai bảng cùng danh sách là hai chỗ để quên cập nhật một chỗ.
 */
import { useRouterState } from '@tanstack/react-router'
import { useEffect } from 'react'
import { Icon } from '@/components/icons'
import { CAO_O } from '@/components/ui/Bang'
import { useLang } from '@/i18n'
import { titleFor } from '@/lib/nav-registry'

/**
 * `⌘K` trên Mac, `Ctrl K` ở nơi khác. Đọc `navigator.platform` một lần lúc
 * dựng module: bàn phím không đổi giữa chừng, và một `useEffect` cho việc này
 * là một lần render thừa trên mọi màn.
 *
 * Đây CHỈ là nhãn hiển thị. Phím tắt thật nghe cả `metaKey` lẫn `ctrlKey` (xem
 * CommandPalette) nên đoán sai nền tảng thì nhãn xấu, không phải phím chết.
 */
const LA_MAC =
  typeof navigator !== 'undefined' &&
  /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent)

export function Topbar({ moNav }: { moNav?: () => void } = {}) {
  const { t } = useLang()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const label = titleFor(pathname)
  const tieuDe = label ? t(label) : ''

  // `<title>` theo màn (WCAG 2.4.2): trước 2026-10-05 mọi tab trình duyệt và mọi
  // mục lịch sử đều tên «NobleX Agent · Portal», trình đọc màn hình đổi route mà
  // không nghe tên màn mới. Rời shell (đăng xuất) thì trả lại tên gốc.
  useEffect(() => {
    const goc = document.title
    document.title = tieuDe ? `${tieuDe} · NobleX Agent` : goc
    return () => {
      document.title = goc
    }
  }, [tieuDe])

  return (
    <header className="sticky top-0 z-30 flex h-[72px] items-center gap-3.5 border-b border-border bg-bg/86 px-7 backdrop-blur-[10px] max-md:h-14 max-md:gap-2 max-md:px-4">
      {/* Nút thu gọn panel KHÔNG ở đây — từng đặt trước <h1> này một lượt
          (2026-08-24) và người dùng chê ngay: nó lấn vào tiêu đề màn. Nút giờ ở
          ĐÁY RAIL (xem `Rail.tsx`) — rail hiện ở cả hai trạng thái nên nút
          không cần mượn chỗ của thanh tiêu đề. */}
      {/* ☰ CHỈ khi layout truyền `moNav` (mobile). Desktop giữ quyết định
          2026-08-24: nút thu gọn ở đáy rail, không lấn tiêu đề. Ở mobile không
          còn rail nên đây là chỗ duy nhất. */}
      {moNav && (
        <button
          type="button"
          aria-label="Mở menu"
          onClick={moNav}
          className="-ml-2 flex size-10 flex-none cursor-pointer items-center justify-center rounded-md text-nav hover:bg-fill-strong"
        >
          <Icon name="moPanel" className="size-5" />
        </button>
      )}
      {/* `<h1>` chứ không phải `<div>`: mỗi màn phải có đúng một tiêu đề cấp
          một, nếu không screen reader không có mốc để nhảy tới nội dung. */}
      <h1 className="min-w-0 flex-1 truncate text-trang font-bold tracking-[-0.02em] text-fg max-md:text-[20px]">
        {tieuDe}
      </h1>

      {/*
        Nút này KHÔNG mở palette bằng cách gọi thẳng vào nó — nó phát đúng sự
        kiện bàn phím mà palette đã nghe. Một đường vào, không phải hai: nếu nút
        gọi một `open()` riêng thì phím tắt và nút thành hai cách mở có thể lệch
        hành vi (ví dụ nút quên lưu focus để trả về lúc đóng).

        Và nó phải tồn tại: một tính năng chỉ có phím tắt là một tính năng không
        ai tìm ra.
      */}
      {/* HÌNH DẠNG LÀ MỘT Ô TÌM, không phải một nút con (thiết kế lại
          2026-08-09). Bản trước là một nút bó sát chữ, cao 29px, chữ 12.5px —
          nhỏ hơn mọi ô điều khiển khác của portal (`CAO_O` = 36px) và nằm lọt
          thỏm trong thanh cao 72px. Nó cũng đọc thành "một nút nữa" chứ không
          phải chỗ để gõ.

          Ba thứ làm nó thành ô tìm: bề rộng CỐ ĐỊNH (không bó theo chữ) · chữ
          gợi ý màu `muted-2` như placeholder · phím tắt đẩy hẳn về mép phải
          bằng `ml-auto` và vẽ thành phím thật có viền.

          Rộng cố định là chủ ý: một ô co theo độ dài chữ sẽ đổi bề rộng khi
          chuyển VI↔EN («Tìm màn» / «Find a screen»), và cả góc phải thanh trên
          nhảy theo ngôn ngữ.

          Vẫn là `<button>` chứ KHÔNG phải `<input>`: gõ thật diễn ra trong ô của
          palette. Một `<input>` ở đây sẽ nhận phím rồi phải chuyển tiếp sang
          palette — hai ô nhập cho một việc, và cái ở trên thì không bao giờ
          giữ được chữ. */}
      <button
        type="button"
        onClick={() =>
          document.dispatchEvent(
            new KeyboardEvent('keydown', { key: 'k', metaKey: true, bubbles: true }),
          )
        }
        className={`${CAO_O} flex w-[248px] flex-none items-center gap-2.5 rounded-md border border-border-field bg-surface px-3 text-than transition-colors hover:border-border-strong max-md:w-10 max-md:justify-center max-md:px-0`}
      >
        <Icon name="search" className="size-4 flex-none text-muted-2" />
        <span className="text-muted-2 max-md:sr-only">
          {t({ vi: 'Tìm màn', en: 'Find a screen' })}
        </span>
        <kbd
          aria-hidden="true"
          className="ml-auto flex-none rounded-sm border border-border-field bg-fill px-1.5 py-[1px] font-mono text-nhan text-muted-2 max-md:hidden"
        >
          {LA_MAC ? '⌘K' : 'Ctrl K'}
        </kbd>
      </button>
    </header>
  )
}
