/**
 * Nạp lại trang khi một chunk lazy-load không tải được — gần như luôn là SAU
 * DEPLOY: tab đang giữ bundle cũ, container mới chỉ mang chunk hash mới, nên
 * cú `import()` đầu tiên tới màn chưa mở là 404 (Safari: «Importing a module
 * script failed»). Vite phát `vite:preloadError` (cancelable) đúng lúc đó —
 * xem Vite docs › Build › Load Error Handling. `preventDefault()` chặn Vite ném
 * lại, nên ErrorComponent không chớp lên trước khi trang nạp lại.
 *
 * GIÃN CÁCH: chỉ nạp lại nếu lần nạp lại trước đã quá `GIAN_CACH_NAP_LAI_MS`.
 * Không có khoá này, một bản deploy tự nó thiếu chunk sẽ đẩy mọi tab vào vòng
 * nạp lại vô hạn — tệ hơn màn lỗi. Ghi vào `sessionStorage` vì nó phải sống
 * qua chính cú nạp lại và chỉ thuộc về tab này.
 *
 * `napLai` tiêm được để test — `window.location.reload` trong jsdom không
 * spy được (thuộc tính unforgeable của `Location`).
 */
export const KHOA_LAN_NAP_LAI = 'odyssey:lan-nap-lai-chunk-hong'
export const GIAN_CACH_NAP_LAI_MS = 10_000

export function datNapLaiKhiChunkHong(
  napLai: () => void = () => window.location.reload(),
): () => void {
  const xuLy = (e: Event): void => {
    const lanTruoc = Number(sessionStorage.getItem(KHOA_LAN_NAP_LAI) ?? 0)
    const bayGio = Date.now()
    if (bayGio - lanTruoc < GIAN_CACH_NAP_LAI_MS) return
    sessionStorage.setItem(KHOA_LAN_NAP_LAI, String(bayGio))
    e.preventDefault()
    napLai()
  }
  window.addEventListener('vite:preloadError', xuLy)
  return () => window.removeEventListener('vite:preloadError', xuLy)
}
