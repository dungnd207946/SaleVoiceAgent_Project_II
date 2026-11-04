/**
 * Bỏ dấu tiếng Việt — dùng cho tìm kiếm không dấu ở ⌘K.
 *
 * TÁCH KHỎI `CommandPalette.tsx` (2026-08-09) vì hai lý do, và lý do thứ hai
 * mới là lý do thật:
 *   · `react-refresh/only-export-components` cảnh báo khi một tệp component
 *     xuất thêm hằng/hàm — fast refresh mất tác dụng cho cả tệp.
 *   · Nó KHÔNG phải chuyện của giao diện. Đây là một phép chuẩn hoá chuỗi tiếng
 *     Việt; để nó nằm trong một component là để một quy tắc ngôn ngữ trốn trong
 *     một tệp mà không ai nghĩ tới khi đi tìm.
 */

/**
 * Mọi dấu tổ hợp (Unicode category Mark). Sau `normalize('NFD')` thì dấu tiếng
 * Việt tách ra đúng thành các ký tự thuộc nhóm này.
 *
 * `\p{M}` chứ KHÔNG phải một dải mã viết thẳng: dấu tổ hợp đứng một mình không
 * hiện gì trên màn hình, nên `/[<U+0300>-<U+036F>]/` trông y như `/[-]/` với
 * người đọc tiếp theo — không ai sửa đúng được thứ mình không nhìn thấy. Cờ `u`
 * là bắt buộc để `\p{...}` có hiệu lực.
 */
const DAU_TO_HOP = /\p{M}/gu

/**
 * "Hội thoại" → "hoi thoai".
 *
 * `đ`/`Đ` KHÔNG phải chữ có dấu tổ hợp — trong Unicode nó là một ký tự riêng,
 * NFD không tách được gì ra khỏi nó. Thiếu hai lần thay tay ở dưới thì gõ
 * "du an" không bao giờ khớp «Dự án».
 *
 * ⚠ NHÁNH `đ` HIỆN KHÔNG CÓ NHÃN MÀN NÀO CHẠM TỚI. Sau lần đổi tên 2026-08-09
 * («Nhật ký & Dữ liệu» → «Nhật ký») và lần trước đó («Dự án» → «Kiến thức»),
 * không nhãn nào còn chữ `đ` — nên `tests/command-palette.test.tsx` canh hàm này
 * TRỰC TIẾP thay vì qua ô tìm. Ngày nào có một nhãn mang `đ`, kéo bài đó trở lại
 * tầng giao diện.
 */
export function boDau(s: string): string {
  return s
    .normalize('NFD')
    .replace(DAU_TO_HOP, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
    .toLowerCase()
}
