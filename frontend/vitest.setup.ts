import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, vi } from 'vitest'
import { setupServer } from 'msw/node'
import { HANDLERS } from './src/lib/msw/handlers'
import { setEditing } from './src/features/realestate/editMode'

/**
 * Cùng handler với trình duyệt — một nguồn fake duy nhất. Test nào cần vai trò
 * hẹp hơn thì `server.use(...)` ghi đè trong chính test đó.
 *
 * `onUnhandledRequest: 'error'` (khác với trình duyệt dùng 'bypass'): trong test,
 * một request không có handler là lỗi cần thấy, không phải thứ nên đi ra mạng.
 */
export const server = setupServer(...HANDLERS)

// Lip sync MuseTalk (`avatarLipSync.ts`) bật bằng `VITE_AVATAR_WS_URL` trong
// `.env` của máy dev — vitest cũng nạp `.env`, nên TẮT ở đây để mọi bài test
// thấy đúng người dẫn mặc định (clip Kling) bất kể máy chạy test cấu hình gì.
vi.stubEnv('VITE_AVATAR_WS_URL', '')

// jsdom không có `window.scrollTo`; TanStack Router gọi nó khi đổi route.
// Không stub thì mỗi lần điều hướng in một trang "Not implemented", che mất
// lỗi thật trong output test.
window.scrollTo = () => {}

// jsdom cũng không có `IntersectionObserver`. Trang `/` dùng nó cho hai việc —
// hiện dần khi cuộn, và đổi màu thanh điều hướng khi rời hero — nên thiếu stub
// là boot('/') ném ngay lúc mount.
//
// Stub KHÔNG BAO GIỜ bắn callback, cố ý: nó giữ mọi thứ ở trạng thái ĐẦU (chưa
// hiện). Một stub tự động báo "đang giao" sẽ phải gọi callback ngoài `act()`,
// và test sẽ chạy trên một trạng thái không phải thứ trình duyệt thật dựng ra
// lúc mount. Chữ vẫn nằm trong DOM (chỉ `opacity-0`) nên `getByText` vẫn thấy.
class QuanSatGia implements IntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly thresholds: readonly number[] = []
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}
globalThis.IntersectionObserver = QuanSatGia

// jsdom cũng không có `ResizeObserver`. `BieuDoNgay` (`features/ops/components/
// BieuDoNgay.tsx`, Task 8) tự đo khung bằng nó khi KHÔNG nhận prop `co` — đúng
// hành vi màn thật (`TongQuanScreen.tsx`, Task 11) — nên boot cả app và đi qua
// `/dashboard` (`boot.test.tsx`, `tao-workspace.test.tsx`, `dang-xuat.test.tsx`,
// `doi-workspace.test.tsx`) ăn `ReferenceError` giữa lúc mount nếu thiếu stub.
//
// Stub KHÔNG BAO GIỜ bắn callback — cùng lý lẽ `QuanSatGia` ở trên: SVG bên
// trong `BieuDoNgay` chờ `clientWidth`/`clientHeight` > 0 (luôn là 0 dưới
// jsdom) nên không vẽ gì, nhưng không bài test nào ở `overview-man.test.tsx`
// kiểm hình học SVG đó (hình học đã có test riêng của `BieuDoNgay` qua prop
// `co`) — chúng kiểm số liệu văn bản, thứ không cần `ResizeObserver` bắn.
class QuanSatKichThuoc implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver = QuanSatKichThuoc

// jsdom có `HTMLDialogElement` nhưng KHÔNG có `showModal()`/`close()` (jsdom #3294).
// `HopThoai` gọi cả hai lúc mount/unmount. Shim chỉ bật/tắt thuộc tính `open` —
// đủ để `getByRole('dialog')` thấy hộp thoại. Nền inert, top layer, focus ban đầu
// là việc của trình duyệt thật; test của `HopThoai` không giả vờ kiểm chúng.
HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
  this.setAttribute('open', '')
}
HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
  this.removeAttribute('open')
}

// `findBy*`/`waitFor` mặc định chỉ chờ 1000ms — quá sát trên runner CI dùng chung
// (shell executor chạy nhiều job cùng lúc) và trên máy dev có repo ở ổ chậm. Ở
// ngưỡng đó cả suite đỏ NGẪU NHIÊN: đo được 13 test rụng khi chạy song song, xanh
// lại khi chạy tuần tự. Nâng lên 5s không làm test đúng chậm đi (chúng resolve
// sớm), chỉ bỏ đi lớp nhiễu đó — và cũng đã kiểm: test hỏng thật vẫn hỏng ở 5s.
configure({ asyncUtilTimeout: 5000 })

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

// Cờ đang sửa của hồ sơ dự án sống ở cấp module: dọn sau mỗi bài để bài sau mở ra ở chế độ xem.
// Gỡ màn trước rồi mới tắt cờ, để việc tắt cờ không thành một lần cập nhật ngoài `act()`.
afterEach(() => {
  cleanup()
  setEditing(null)
})
