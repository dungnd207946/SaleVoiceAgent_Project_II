/**
 * Người dùng bật «giảm chuyển động» ở hệ điều hành. Đọc MỘT lần lúc gọi, không nghe
 * thay đổi: chỗ dùng quyết định lúc dựng (vẽ người dẫn hay ảnh tĩnh, có hẹn giờ tự lướt
 * hay không), và đổi cài đặt giữa chừng thì lần dựng sau sẽ theo.
 *
 * Chuyển động bằng CSS đã có nhánh `@media (prefers-reduced-motion)` ở `theme.css`;
 * hàm này cho chuyển động chạy bằng JS (vòng rAF, hẹn giờ tự đổi) — thứ media query
 * không với tới. WCAG 2.2.2: nội dung tự chạy quá 5 giây phải dừng được.
 *
 * `matchMedia` không có trong jsdom ⇒ coi là KHÔNG giảm.
 */
export function giamChuyenDong(): boolean {
  return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
}
