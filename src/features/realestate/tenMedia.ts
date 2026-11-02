/**
 * Tên hiển thị của một media — `fileName` nếu có, ngược lại suy từ URL.
 *
 * VÌ SAO PHẢI SUY: đo trên `aina_prod` 2026-08-25, `fileName` RỖNG cho toàn bộ 93
 * video và 19 tour 360 (chúng là link ngoài, không phải tệp trong kho ta), nên một
 * giao diện «ưu tiên tên tệp» mà chỉ đọc `fileName` sẽ để trống 112 thẻ.
 *
 * Ba nguồn ngoài chiếm gần hết số đó và mỗi nguồn giấu tên ở một chỗ khác nhau —
 * YouTube ở query `v`, Google Drive ở path `/file/d/<id>`, Kuula ở `/share/<id>`.
 * Không có bảng này thì cả ba hiện ra cùng một chữ «youtube.com», tức ba thẻ cạnh
 * nhau trông y hệt.
 */
const CAT = 14

function ngan(s: string): string {
  return s.length > CAT ? `${s.slice(0, CAT)}…` : s
}

/** `https://…/a/b/toan-canh.webp?x=1` → `toan-canh.webp`. Rỗng nếu không có đoạn nào. */
function doanCuoi(duong: string): string {
  const sach = duong.split('?')[0]?.split('#')[0] ?? ''
  const doan = sach.split('/').filter(Boolean)
  return doan[doan.length - 1] ?? ''
}

export function tenTuUrl(url: string): string {
  if (!url) return ''
  let u: URL
  try {
    u = new URL(url)
  } catch {
    // Khoá kho tệp (không phải URL tuyệt đối) — đoạn cuối là tên tệp thật.
    return doanCuoi(url)
  }
  const host = u.hostname.replace(/^www\./, '')

  if (host === 'youtube.com' || host === 'youtu.be') {
    const ma = host === 'youtu.be' ? doanCuoi(u.pathname) : (u.searchParams.get('v') ?? '')
    return ma ? `YouTube · ${ngan(ma)}` : 'YouTube'
  }
  if (host === 'drive.google.com') {
    if (u.pathname.includes('/folders/')) return 'Google Drive · thư mục'
    const m = /\/file\/d\/([^/]+)/.exec(u.pathname)
    return m?.[1] ? `Google Drive · ${ngan(m[1])}` : 'Google Drive'
  }
  if (host === 'kuula.co') {
    const m = /\/share\/([^/?]+)/.exec(u.pathname)
    return m?.[1] ? `Kuula · ${ngan(m[1])}` : 'Kuula'
  }

  // Nguồn lạ: đoạn cuối nếu nó trông như một tên tệp, ngược lại là host.
  const cuoi = doanCuoi(u.pathname)
  return /\.[a-z0-9]{2,5}$/i.test(cuoi) ? cuoi : host
}

export function tenMedia(m: { fileName?: string | null; mediaUrl: string }): string {
  return (m.fileName ?? '').trim() || tenTuUrl(m.mediaUrl)
}
