/**
 * Dọn khoá gateway dạng RÕ mà bản cũ của màn «Thử agent» còn để lại trong
 * localStorage. Chạy một lần mỗi lần mở app, từ `main.tsx`.
 *
 * VÌ SAO CÓ TỆP NÀY — một quyết định đã tự hết hiệu lực mà không ai dọn theo:
 * 2026-08-10 màn Thử agent bắt người dùng DÁN khoá thô vào một ô nhập, nên nó
 * lưu khoá xuống localStorage với lý lẽ «gõ lại một chuỗi dài mỗi lần mở màn
 * tốn hơn rủi ro nó nằm trên máy chính người đó». 2026-08-11 ô dán đổi thành
 * `<select>` chọn khoá theo tên (khoá thô về từ `/agent/keys`), và đường ĐỌC
 * lại localStorage bị bỏ — nhưng đường GHI thì không. Từ hôm đó tới
 * 2026-08-27, portal ghi một khoá `ody_ag_…` dạng rõ xuống máy người dùng ở
 * mỗi lần bấm «Áp dụng» và KHÔNG BAO GIỜ đọc lại: rủi ro giữ nguyên, lợi ích
 * bằng không.
 *
 * Vì sao đáng dọn chứ không chỉ ngừng ghi: `docs/contracts/dau-noi-agent.md`
 * §2b nói khoá này không được chạm trình duyệt end-user — nó mở được cả
 * `/runtime-credentials`, tức mật khẩu Postgres của tenant. Ngừng ghi chỉ chặn
 * khoá MỚI; khoá đã nằm đó thì nằm đó mãi cho tới khi có ai xoá.
 *
 * ⚠ ĐỂ Ở `lib/`, KHÔNG ở `features/platform/`, và KHÔNG import gì từ đó:
 * `main.tsx` gọi hàm này, mà `chatGateway.ts`/`giongNoi.ts` đang nằm gọn trong
 * chunk lazy của `/thu-agent`. Import từ đó là kéo cả WebSocket + AudioContext
 * vào bundle entry để đổi lấy hai lời gọi `removeItem`.
 *
 * ĐÂY LÀ MÃ DI TRÚ, có hạn dùng: xoá được khi đã đủ chắc mọi máy từng mở
 * `/thu-agent` trong khoảng 10–27/08/2026 đã mở lại portal ít nhất một lần.
 */

/** Hai khoá của bản cũ — chat và voice cố ý tách nhau, xem `giongNoi.ts`. */
const KHOA_CU = ['thu-agent-gateway:cau-hinh', 'thu-agent-voice:cau-hinh'] as const

export function donKhoaThoCu(): void {
  // localStorage NÉM chứ không trả null ở vài cấu hình trình duyệt (Safari chặn
  // site data). Một cú dọn không thành thì thôi — nó không được phép làm app
  // không khởi động nổi.
  try {
    for (const k of KHOA_CU) localStorage.removeItem(k)
  } catch {
    /* không có localStorage thì cũng không có gì để dọn */
  }
}
