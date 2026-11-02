/**
 * Logic THUẦN của «sân khấu» tab Voice (`components/SanKhauAgent`) — phần nền.
 * Tách khỏi component vì eslint `react-refresh/only-export-components` cấm
 * một tệp vừa xuất component vừa xuất hàm, và để test không cần dựng DOM.
 */
import type { Media } from './chatGateway'

/**
 * Các ảnh dùng làm NỀN sân khấu từ một card media (`send_media`, event `media`
 * của Voice): MỌI ảnh của card theo đúng thứ tự — ảnh gốc `url`, thiếu thì
 * `thumb`; trùng thì bỏ. Video/tour/tệp bị bỏ qua (thumbnail YouTube hay biểu
 * tượng tệp phóng to cả sân khấu thì vỡ hạt và không nói gì về dự án) — card
 * chỉ có những thứ đó ⇒ mảng rỗng, không đổi nền.
 */
export function anhTuMedia(media: Media): readonly string[] {
  const ra: string[] = []
  for (const it of media.items) {
    if (it.kind !== 'image') continue
    const u = it.url || it.thumb
    if (u && !ra.includes(u)) ra.push(u)
  }
  return ra
}

// ─── Album ảnh trên sân khấu ──────────────────────────────────────────────────

/** Đổi sang ảnh kế sau chừng này LƯỢT agent trả lời xong… */
export const SO_LUOT_DOI_ANH = 2
/** …hoặc sau chừng này thời gian ảnh đứng yên, cái nào tới trước. Lịch sử:
 *  8s (2026-10-01) → 5s khi nền thành album → 8s → **6,5s** (người dùng chốt
 *  2026-10-02). */
export const THOI_GIAN_DOI_ANH_MS = 6_500
/** Album chỉ được đóng sau ÍT NHẤT chừng này lượt agent trả lời xong kể từ lúc
 *  mở — chưa đủ thì vẫn lướt vòng, dù đã xem hết và quá giờ (người dùng chốt
 *  2026-10-02, thay mốc thời gian tối thiểu 12s). Lượt đang nói lúc ảnh tới
 *  cũng tính khi nó xong. */
export const ALBUM_TOI_THIEU_LUOT = 3

/**
 * Album đang mở trên sân khấu. `ds` rỗng = không có album (nền mặc định).
 * Album lướt VÒNG, nhưng không mở mãi: khi MỌI ảnh đã được xem và ảnh đang
 * hiện đã đứng đủ `THOI_GIAN_DOI_ANH_MS` không ai chạm (và đã qua ≥
 * `ALBUM_TOI_THIEU_LUOT` lượt trả lời kể từ lúc mở) ⇒ đóng, về nền cũ (người dùng chốt 2026-10-02). Người
 * dùng tự lướt thì mỗi lần lướt tính lại giờ của ảnh đó — đang xem thì không
 * bị đóng ngang.
 */
export interface LuanPhienAnh {
  readonly ds: readonly string[]
  readonly i: number
  /** `performance.now()` lúc ảnh đang hiện được đưa lên. */
  readonly doiLuc: number
  /** Số lượt agent đã trả lời xong kể từ lúc đó. */
  readonly soLuot: number
  /** Chỉ số các ảnh đã từng hiện (đủ `ds.length` ⇒ đã xem hết). */
  readonly daXem: readonly number[]
  /** Số lượt agent trả lời xong kể từ lúc album MỞ (không đặt lại khi đổi ảnh). */
  readonly luotTuLucMo: number
}

export const LUAN_PHIEN_TRONG: LuanPhienAnh = {
  ds: [],
  i: 0,
  doiLuc: 0,
  soLuot: 0,
  daXem: [],
  luotTuLucMo: 0,
}

export const anhHienTai = (s: LuanPhienAnh): string | null => s.ds[s.i] ?? null

/** Lướt `buoc` ảnh (±1 khi vuốt, +1 khi tự chuyển), vòng hai đầu. */
export function sangAnh(s: LuanPhienAnh, buoc: number, bayGio: number): LuanPhienAnh {
  const n = s.ds.length
  if (n === 0) return s
  const i = (((s.i + buoc) % n) + n) % n
  return {
    ...s,
    i,
    doiLuc: bayGio,
    soLuot: 0,
    daXem: s.daXem.includes(i) ? s.daXem : [...s.daXem, i],
  }
}

/** Người dùng đang chạm/kéo ⇒ giữ ảnh hiện tại, tính lại giờ từ bây giờ. */
export const giuAnh = (s: LuanPhienAnh, bayGio: number): LuanPhienAnh =>
  s.ds.length === 0 ? s : { ...s, doiLuc: bayGio, soLuot: 0 }

/** Card media mới có ảnh ⇒ MỞ album mới (thay album cũ), từ ảnh 1. Không có ảnh ⇒ giữ nguyên. */
export function nhanBoAnh(s: LuanPhienAnh, ds: readonly string[], bayGio: number): LuanPhienAnh {
  return ds.length === 0 ? s : { ds, i: 0, doiLuc: bayGio, soLuot: 0, daXem: [0], luotTuLucMo: 0 }
}

/**
 * Một ảnh của album vừa TẢI XONG (`taiTruocAnh`) ⇒ chen vào album đang mở, giữ
 * đúng thứ tự gốc của card (`thuTu`), ảnh đang hiện vẫn là ảnh đang hiện (chỉ
 * số `i` và `daXem` được ánh xạ lại theo danh sách mới). Album đã đóng (rỗng)
 * ⇒ giữ nguyên: ảnh tải muộn không được mở lại một album người dùng đã xem xong.
 * Ảnh ĐẦU TIÊN tải xong của card thì mở album bằng `nhanBoAnh`, không qua đây.
 */
export function themAnh(s: LuanPhienAnh, url: string, thuTu: readonly string[]): LuanPhienAnh {
  if (s.ds.length === 0 || s.ds.includes(url)) return s
  const ds = thuTu.filter((u) => u === url || s.ds.includes(u))
  const viTri = (u: string | undefined) => (u === undefined ? -1 : ds.indexOf(u))
  return {
    ...s,
    ds,
    i: Math.max(0, viTri(s.ds[s.i])),
    daXem: s.daXem.map((k) => viTri(s.ds[k])).filter((k) => k >= 0),
  }
}

/** Một lượt agent trả lời xong (`agent_done` / `agent_interrupted`). */
export function xongLuot(s: LuanPhienAnh, bayGio: number): LuanPhienAnh {
  if (s.ds.length === 0) return s
  const daDem = { ...s, luotTuLucMo: s.luotTuLucMo + 1 }
  if (s.ds.length < 2) return daDem
  const soLuot = s.soLuot + 1
  return soLuot >= SO_LUOT_DOI_ANH ? sangAnh(daDem, 1, bayGio) : { ...daDem, soLuot }
}

/** Nhịp đồng hồ: ảnh đã đứng đủ giờ ⇒ sang ảnh kế, hoặc ĐÓNG album nếu đã xem
 *  hết. Không đổi thì trả CHÍNH `s` — React bỏ qua lần vẽ lại. */
export function nhipDoiAnh(s: LuanPhienAnh, bayGio: number): LuanPhienAnh {
  if (s.ds.length === 0 || bayGio - s.doiLuc < THOI_GIAN_DOI_ANH_MS) return s
  if (s.daXem.length >= s.ds.length && s.luotTuLucMo >= ALBUM_TOI_THIEU_LUOT)
    return LUAN_PHIEN_TRONG
  return s.ds.length < 2 ? giuAnh(s, bayGio) : sangAnh(s, 1, bayGio)
}

// ─── Hình học thẻ trong album ────────────────────────────────────────────────

/** Khoảng cách VÒNG có dấu từ thẻ `j` tới thẻ đang hiện `i` trong `n` thẻ —
 *  lặp vô hạn không cần nhân bản thẻ: thẻ cuối nằm ngay «trước» thẻ đầu. */
export function kcVong(j: number, i: number, n: number): number {
  let d = (((j - i) % n) + n) % n
  if (d > n / 2) d -= n
  return d
}

export interface KieuThe {
  readonly tx: number
  readonly ty: number
  readonly tz: number
  readonly ry: number
  readonly sc: number
  readonly op: number
  readonly bl: number
  readonly z: number
}

/**
 * Vị trí của một thẻ cách thẻ chính `d` bậc (số thực — đang kéo thì lẻ), thẻ
 * rộng `w` px. Thẻ chính: nguyên cỡ, rõ, trên cùng. ±1: ló mép ~9% bề rộng
 * (đề bài ghi ±20px — thử ở demo thì thẻ còn thu 0,94 nên gần như bị che
 * hết), thu 0,94, mờ còn 45%, nhoè 2px. Xa hơn nhỏ/mờ dần; quá ±2,6 thì ẩn.
 * Nghiêng `rotateY` theo phía để chồng thẻ đọc ra một vòng album, không phải
 * một dải trượt phẳng.
 */
export function kieuThe(d: number, w: number): KieuThe {
  const a = Math.abs(d)
  const s = Math.sign(d)
  const b1 = Math.max(20, w * 0.09)
  const b2 = Math.max(32, w * 0.15)
  return {
    tx: s * (a <= 1 ? a * b1 : b1 + (a - 1) * (b2 - b1)),
    ty: Math.min(a, 2) * 3,
    tz: -a * 40,
    ry: -s * Math.min(a, 2) * 9,
    sc: 1 - Math.min(a, 3) * 0.06,
    op: a > 2.6 ? 0 : a <= 1 ? 1 - a * 0.55 : Math.max(0, 0.45 - (a - 1) * 0.2),
    bl: Math.min(a, 2.5) * 2,
    z: 100 - Math.round(a * 10),
  }
}

/** Phủ kín được nếu chỉ cắt mất tới chừng này của ảnh (theo chiều bị cắt).
 *  0,3 → 0,6 (2026-10-02): sân khấu desktop nay cao kín cột (~484×575, gần
 *  vuông), ảnh 16:9 vào đó cắt ~52% hai bên — dưới ngưỡng cũ nó thành dải ảnh
 *  giữa hai mảng mờ; phủ kín đẹp hơn và ảnh nền đủ độ phân giải để phóng.
 *  Khung rất dẹt (cắt > 60%) vẫn rơi vào contain. */
export const CAT_TOI_DA = 0.6

/**
 * Hiện ảnh nền thế nào trong khung `kw×kh`:
 * - `cover` (phủ kín) khi tỉ lệ ảnh gần tỉ lệ khung — cắt ≤ `CAT_TOI_DA`;
 * - `contain` (hiện TRỌN, hai bên/trên dưới lấp bằng chính ảnh làm mờ) khi
 *   phủ kín sẽ cắt mất nhiều hơn — vd. ảnh 3:2 trong sân khấu desktop ≈ 3,4:1
 *   bị cắt ~56% chiều dọc và phóng ×2 nên mờ.
 * Chưa biết kích thước (ảnh chưa tải, khung chưa đo) ⇒ `cover`, như cũ.
 */
export function cachHien(kw: number, kh: number, aw: number, ah: number): 'cover' | 'contain' {
  if (!kw || !kh || !aw || !ah) return 'cover'
  const r = kw / kh / (aw / ah)
  const cat = 1 - Math.min(r, 1 / r)
  return cat <= CAT_TOI_DA ? 'cover' : 'contain'
}
