/**
 * Chuyển VI/EN. Prototype còn hook CSS `[data-ls]` nhưng KHÔNG có markup của
 * nút này trong bản tải về — nên hình dáng dưới đây dựng từ chính hook đó:
 * nhánh đang chọn có nền trắng, chữ #14161a, shadow nhẹ; nhánh còn lại phẳng
 * trên rãnh xám.
 *
 * ĐÃ RỜI THANH TRÊN, VỀ MENU «Hồ sơ & tuỳ chọn» (người dùng chốt 2026-08-09).
 * Ngôn ngữ là một TUỲ CHỌN của người dùng, đặt cạnh đúng cái menu mang tên
 * «Hồ sơ & tuỳ chọn» thì nó ở chỗ người ta sẽ đi tìm; ở thanh trên nó chiếm một
 * vị trí đắt ngang tiêu đề màn cho thứ mỗi người đổi một lần rồi thôi.
 *
 * Hai nút `aria-pressed` trong một `role="group"` có nhãn. Prop `trongMenu`
 * (`menuitemradio` + `aria-checked`) BỎ 2026-10-05 cùng lúc `UserMenu` thôi là
 * `role="menu"`: `menuitemradio` ngoài một menu là vai ARIA không hợp lệ.
 */
import { useLang } from '@/i18n'
import type { Lang } from '@/lib/nav-types'

const OPTIONS: readonly Lang[] = ['vi', 'en']

export function LangToggle() {
  const { lang, setLang } = useLang()

  return (
    <div
      role="group"
      aria-label="Ngôn ngữ"
      className="flex flex-none gap-0.5 rounded-md bg-fill-strong p-0.5"
    >
      {OPTIONS.map((opt) => (
        <button
          key={opt}
          type="button"
          aria-pressed={lang === opt}
          onClick={() => setLang(opt)}
          className={`rounded-sm px-2.5 py-1 text-phu font-semibold uppercase transition-colors ${
            lang === opt ? 'bg-surface text-fg shadow-chon' : 'text-muted-2 hover:text-fg'
          }`}
        >
          {opt}
        </button>
      ))}
    </div>
  )
}
