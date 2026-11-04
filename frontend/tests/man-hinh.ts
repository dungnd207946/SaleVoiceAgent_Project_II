/**
 * jsdom không có `window.matchMedia` ⇒ `useKhoManHinh` trả `desktop` — nhờ vậy
 * mọi test cũ dựng đúng layout cũ. Test nào cần mobile/tablet gọi
 * `giaLapManHinh(rong)` và PHẢI `boGiaLap()` trong `afterEach`, nếu không test
 * sau trong cùng file chạy ở bề rộng giả.
 *
 * Chỉ hiểu `(max-width: Npx)` — đúng dạng truy vấn `lib/khoManHinh.ts` dùng.
 */
type Nghe = (e: MediaQueryListEvent) => void

let rongHienTai = 1440
const dsTruyVan: { q: string; nghe: Set<Nghe>; khop: boolean }[] = []

function khop(q: string, rong: number): boolean {
  const m = /max-width:\s*([\d.]+)px/.exec(q)
  return m ? rong <= Number(m[1]) : false
}

export function giaLapManHinh(rong: number): void {
  rongHienTai = rong
  dsTruyVan.length = 0
  window.matchMedia = (q: string): MediaQueryList => {
    const muc = { q, nghe: new Set<Nghe>(), khop: khop(q, rongHienTai) }
    dsTruyVan.push(muc)
    return {
      get matches() {
        return khop(q, rongHienTai)
      },
      media: q,
      onchange: null,
      addEventListener: (_: string, f: Nghe) => muc.nghe.add(f),
      removeEventListener: (_: string, f: Nghe) => muc.nghe.delete(f),
      addListener: (f: Nghe) => muc.nghe.add(f),
      removeListener: (f: Nghe) => muc.nghe.delete(f),
      dispatchEvent: () => false,
    } as unknown as MediaQueryList
  }
}

export function doiRong(rong: number): void {
  rongHienTai = rong
  for (const muc of dsTruyVan) {
    const moi = khop(muc.q, rong)
    if (moi === muc.khop) continue
    muc.khop = moi
    for (const f of muc.nghe) f({ matches: moi, media: muc.q } as MediaQueryListEvent)
  }
}

export function boGiaLap(): void {
  delete (window as { matchMedia?: unknown }).matchMedia
  dsTruyVan.length = 0
}
