/**
 * Avatar GIẢ cho fake MSW — backend thật trả data URI SVG sinh bằng DiceBear
 * (`core/avatar.py` — style khai ở đó, hiện là thumbs; seed = tên). Fake không kéo thư viện
 * DiceBear JS vào chỉ để dựng dữ liệu giả: một SVG chữ-trên-nền-màu tự vẽ đủ
 * giống về HÌNH DẠNG hợp đồng (một data URI ảnh), và đó là thứ duy nhất
 * component đọc.
 *
 * Ở `lib/msw/` vì HAI nơi dùng (`lib/msw/handlers.ts` cho /me, `features/ops/msw.ts`
 * cho khách) — cùng lý do `danhGiaGia.ts` sống ở đây.
 */
export function avatarGia(chu: string, nen = '#0a7ea4'): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">` +
    `<rect width="100" height="100" fill="${nen}"/>` +
    `<text x="50" y="50" font-family="sans-serif" font-size="40" fill="#fff" ` +
    `text-anchor="middle" dominant-baseline="central">${chu}</text></svg>`
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
}
