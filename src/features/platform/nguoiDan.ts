/**
 * Logic THUẦN của người dẫn trên sân khấu tab Voice (`components/SanKhauAgent`).
 *
 * Không phải lip-sync: miệng mấp máy theo LÚC CÓ TIẾNG, không khớp từng âm
 * tiết. Muốn khớp khẩu hình thật thì phải render phía server (MuseTalk,
 * Wav2Lip…) — việc của vòng sau.
 *
 * **Bộ clip Kling (2026-10-01).** Hai clip 5,04s / 121 khung tạo bằng Kling
 * với Start frame = End frame = CÙNG một ảnh gốc: `video1_only_speak.mp4`
 * (nói, tay đan) và `video_2_hand_raise.mp4` (nói rồi đưa tay giới thiệu).
 * Nhờ vậy khung cuối mỗi clip gần trùng khung đầu của cả hai — đo trên ma
 * trận lệch mọi cặp khung (ảnh 154×210): hai khung liền kề lệch trung vị
 * 0,53; F120→F1 0,55; F120→G0 0,93; G120→F1 0,93. Mọi chỗ nối vì thế là một
 * cú đổi TỨC THÌ giữa hai khung gần như một — giữ đúng luật «không ghép khung
 * lạ, không hoà trộn» của bản trước.
 *
 * `public/nguoi-dan.mp4` DỰNG SẴN bốn đoạn nối liền (ghép alpha xếp chồng):
 *
 * ```
 * vị trí tệp:  0 …… 120 | 121 …… 241 | 242 …… 362 | 363 …… 409
 * khung gốc:   F 0→120   | G 0→120    | F 120→0    | G 46→0
 *              nói xuôi  | đưa tay    | nói ngược  | G ngược (trước khi nhấc tay)
 * ```
 *
 * - NÓI: F chạy liền; cuối F (120) cắt về F1. Muốn đưa tay thì KHÔNG cắt —
 *   F120 chạy thẳng sang G0 (vị trí 121) — hết G (241) cắt về F1.
 * - CHỜ: đi xuôi–ngược trong khung 1–15 (miệng khép, mắt mở, chuyển động
 *   rất nhẹ — thay cho một ảnh đứng im, thứ người dùng thấy «chưa tự nhiên»).
 *   Đảo chiều = sang khung KỀ ở đoạn chiều kia (`daoChieu`), liền mạch tuyệt
 *   đối, chỉ hướng chuyển động đổi.
 * - THÔI NÓI: đi về đoạn miệng khép GẦN NHẤT — lùi (R) về ≤ 15, hoặc tiến
 *   tới ≥ 104 rồi nối vòng. Trong G mà tay chưa nhấc thì lùi bằng đoạn G
 *   ngược về G0 (≈ F0); tay đã nhấc thì chạy cho hết cử chỉ.
 *
 * Bảng này chỉ đúng cho đúng tệp đó. Dựng lại tệp (đổi clip, đổi khung) là
 * PHẢI đo lại `KHUNG` và sửa `DOAN`.
 */

export const FPS = 24
/** Giây của GIỮA vị trí `n` trong tệp — tua đúng ranh giới hai khung thì
 *  trình duyệt có thể dừng ở khung trước. */
export const khung = (n: number): number => (n + 0.5) / FPS
/** Vị trí đang hiện ở thời điểm `t` (giây video). */
export const khungCua = (t: number): number => Math.floor(t * FPS)

/** Tốc độ phát khi nói/đưa tay. Clip Kling đã được dặn «nói khẽ, chậm», nên
 *  để gần nguyên tốc — chậm quá thì môi trễ hẳn so với tiếng. */
export const TOC_DO = 1.1
/** Tốc độ lúc CHỜ: vòng 1–15 chỉ ~0,6s ở tốc độ gốc, chậm lại cho thành nhịp
 *  thở chứ không thành rung. */
export const TOC_NGHI = 0.45

/** Ranh giới bốn đoạn trong tệp (vị trí, gồm cả hai đầu). */
export const DOAN = {
  fDau: 0,
  fCuoi: 120,
  gDau: 121,
  gCuoi: 241,
  rDau: 242,
  rCuoi: 362,
  grDau: 363,
  grCuoi: 409,
} as const

/**
 * Khung gốc quan trọng (đo 2026-10-01):
 * - `cho` 1–15: miệng khép, mắt mở, cười nhẹ, chuyển động rất nhỏ — vòng chờ.
 *   (0–16 và 104–120 đều «yên»; vòng chờ dùng đầu thấp vì đi ngược được.)
 * - `yenCao` 104: từ đây tới 120 miệng lại khép — thôi nói ở nửa sau thì tiến.
 * - `nhacTay` 46: clip G tay đứng yên tới ~46, nhấc lên 48–96, về chỗ ~100.
 * - `vongVe` 1: đích nối vòng (F120→F1 lệch 0,55 ≈ hai khung liền kề).
 * - `noiDau`…`noiCuoi` 22–100: vùng ĐANG NÓI. Đo độ mở miệng từng khung
 *   (lệch vùng miệng so với khung 0): 0–16 < 1 và 104–120 < 3,4 là miệng KHÉP
 *   (tư thế gốc Kling đặt ở hai đầu clip); 17–103 ≥ 5. Bản đầu cho F chạy hết
 *   vòng 0→120 nên mỗi ~5s nói lại có ~1,5s miệng khép giữa lúc audio vẫn
 *   phát (người dùng báo «1–2 giây về nghỉ»). Nay khi nói chỉ xuôi–ngược trong
 *   vùng này; chỉ ra tư thế gốc khi im hoặc khi đưa tay (G bắt đầu từ đó).
 * - `gKhep` 102: clip G miệng khép lại từ đây (đo cùng cách, < 3,7).
 */
export const KHUNG = {
  choDau: 1,
  choCuoi: 15,
  yenCao: 104,
  nhacTay: 46,
  vongVe: 1,
  noiDau: 22,
  noiCuoi: 100,
  gKhep: 102,
} as const

/** Đoạn của vị trí `i`. */
export type Doan = 'F' | 'G' | 'R' | 'GR'
export function doanCua(i: number): Doan {
  if (i <= DOAN.fCuoi) return 'F'
  if (i <= DOAN.gCuoi) return 'G'
  if (i <= DOAN.rCuoi) return 'R'
  return 'GR'
}

/** Khung gốc (trong clip của đoạn đó) của vị trí `i`. */
export function khungGoc(i: number): number {
  switch (doanCua(i)) {
    case 'F':
      return i
    case 'G':
      return i - DOAN.gDau
    case 'R':
      return DOAN.rCuoi - i
    case 'GR':
      return DOAN.grCuoi - i
  }
}

/**
 * Vị trí ĐẢO CHIỀU của `i`: khung KỀ theo chiều ngược lại, ở đoạn chiều kia.
 * F khung k (xuôi) ⇒ R khung k−1; R khung k (ngược) ⇒ F khung k+1. Tương tự
 * G ⇄ GR (chỉ trong phần G trước khi nhấc tay). Cả hai cặp ra một công thức
 * đối xứng `tổng − i`. `null` nếu `i` không có đối (G sau khi nhấc tay).
 */
export function daoChieu(i: number): number | null {
  const d = doanCua(i)
  // F khung k ở vị trí k; R khung k ở vị trí rCuoi − k ⇒ F k → R (k−1) = rCuoi+1−k.
  if (d === 'F' || d === 'R') return DOAN.rCuoi + 1 - i
  if (d === 'GR' || (d === 'G' && khungGoc(i) <= KHUNG.nhacTay))
    return DOAN.gDau + DOAN.grCuoi + 1 - i
  return null
}

/** Đặt kế hoạch trước bấy nhiêu khung để video phụ kịp tua tới đích. */
export const TRUOC = 4

/** Đang nói thì đổi chiều ngẫu nhiên sau mỗi 1,2–3s — đổi theo nhịp cố định
 *  (hoặc chỉ ở hai biên) thì chuỗi cử động lại thành một vòng lặp đều. */
const DAO_IT_NHAT_MS = 1_200
const DAO_THEM_MS = 1_800

/** Nói liên tục bấy lâu thì (nếu được) đưa tay — «đưa tay sau một lúc nói». */
export const NOI_TRUOC_GIO_TAY_MS = 3_000
/**
 * Đưa tay cách nhau ÍT NHẤT chừng này + tới `GIO_TAY_LECH_MS` ngẫu nhiên, tính
 * từ lúc THẬT SỰ vào G ⇒ nói liên tục thì ~10–15s một lần (người dùng chốt
 * 2026-10-01; bản trước 15s + 0–8s đọc ra «ít quá»). Thấp hơn nữa thì gần như
 * lúc nào cũng đang đưa tay: bản thân một lần đưa tay đã là cả clip G (~5,6s).
 */
export const GIAN_CACH_GIO_TAY_MS = 8_000
const GIO_TAY_LECH_MS = 6_000

/** Một lần đổi video: khi vị trí đang hiện tới `tai` thì sang `toi`. */
export interface KeHoach {
  readonly tai: number
  readonly toi: number
  /** Sang rồi chạy tiếp hay đứng yên ở đó. */
  readonly phat: boolean
}

/**
 * - `nghi`    — vòng chờ xuôi–ngược trong khung 1–15
 * - `noi`     — đang có tiếng
 * - `ve_nghi` — vừa hết tiếng, đang đi về đoạn miệng khép
 */
export type CheDoVideo = 'nghi' | 'noi' | 've_nghi'

export interface TrangVideo {
  readonly cheDo: CheDoVideo
  /** `performance.now()` lúc bắt đầu lượt nói hiện tại. */
  readonly batDauNoi: number
  /** `performance.now()` từ lúc nào ĐƯỢC tự đưa tay lần nữa. */
  readonly henGioTay: number
  /** Có yêu cầu đưa tay (tự động hoặc từ ngoài) — rẽ vào G ở cuối F kế tiếp. */
  readonly muonGioTay: boolean
  /** Tự đưa tay sau `NOI_TRUOC_GIO_TAY_MS` nói liên tục. */
  readonly tuDongGioTay: boolean
  /** `performance.now()` của lần đổi chiều ngẫu nhiên kế tiếp khi đang nói. */
  readonly henDao: number
  readonly keHoach: KeHoach | null
}

export const TRANG_DAU: TrangVideo = {
  cheDo: 'nghi',
  batDauNoi: 0,
  henGioTay: -Infinity,
  muonGioTay: false,
  tuDongGioTay: true,
  henDao: Infinity,
  keHoach: null,
}

/** Gọi sau khi component đã thi hành kế hoạch. */
export const daNhay = (s: TrangVideo): TrangVideo => ({ ...s, keHoach: null })

/** Yêu cầu đưa tay từ NGOÀI (logic hội thoại) — rẽ vào G ở lần tới cuối F
 *  kế tiếp, nếu lúc đó vẫn đang nói. Chỗ để sau này nối «khi nào đưa tay». */
export const datGioTay = (s: TrangVideo): TrangVideo => ({ ...s, muonGioTay: true })

const keHoach = (tai: number, toi: number, phat: boolean): KeHoach => ({ tai, toi, phat })

/**
 * Một nhịp — gọi mỗi khung hình với `i` = vị trí đang hiện của video chính.
 * `phat: true` = video chính đang dừng thì cho chạy. Kế hoạch đổi video (nếu
 * có) nằm ở `trang.keHoach`. `rand` tiêm được để test tất định.
 */
export function buocVideo(
  s: TrangVideo,
  i: number,
  dangNoi: boolean,
  bayGio: number,
  rand: () => number = Math.random,
): { trang: TrangVideo; phat?: true } {
  const d = doanCua(i)
  const k = khungGoc(i)
  const tai = i + TRUOC

  // ── Đang có tiếng ──
  if (dangNoi) {
    const henDaoMoi = () => bayGio + DAO_IT_NHAT_MS + rand() * DAO_THEM_MS
    let t: TrangVideo =
      s.cheDo === 'noi'
        ? s
        : { ...s, cheDo: 'noi', batDauNoi: bayGio, henDao: henDaoMoi(), keHoach: null }
    if (
      t.tuDongGioTay &&
      !t.muonGioTay &&
      bayGio - t.batDauNoi >= NOI_TRUOC_GIO_TAY_MS &&
      bayGio >= t.henGioTay
    )
      t = { ...t, muonGioTay: true }
    if (t.keHoach) {
      // Kế hoạch dừng (về chờ) đặt lúc vừa im ⇒ có tiếng lại thì chạy tiếp.
      if (!t.keHoach.phat) t = { ...t, keHoach: { ...t.keHoach, phat: true } }
      return { trang: t, phat: true }
    }
    const dao = (): { trang: TrangVideo; phat: true } => ({
      trang: { ...t, henDao: henDaoMoi(), keHoach: keHoach(tai, daoChieu(tai)!, true) },
      phat: true,
    })
    const kTai = khungGoc(tai)

    // G ngược (đang lùi về chờ) ⇒ quay lại chiều xuôi ngay.
    if (d === 'GR') {
      const dc = daoChieu(tai)
      if (dc !== null && doanCua(tai) === d)
        return { trang: { ...t, keHoach: keHoach(tai, dc, true) }, phat: true }
      return { trang: t, phat: true }
    }

    // Đã vào G ⇒ yêu cầu đưa tay đã được thực hiện. Khoảng cách tới lần tự
    // đưa tay sau tính từ ĐÂY, không từ lúc có yêu cầu.
    if (d === 'G') {
      if (t.muonGioTay)
        t = {
          ...t,
          muonGioTay: false,
          henGioTay: bayGio + GIAN_CACH_GIO_TAY_MS + rand() * GIO_TAY_LECH_MS,
        }
      if (i >= DOAN.gCuoi - TRUOC)
        return { trang: { ...t, keHoach: keHoach(DOAN.gCuoi, KHUNG.vongVe, true) }, phat: true }
      return { trang: t, phat: true }
    }

    if (d === 'R') {
      // Muốn đưa tay khi đang lùi ⇒ về tư thế gốc theo hướng GẦN hơn: nửa
      // dưới thì lùi tiếp tới khung 0 (≈ G0) rồi nối sang G; nửa trên thì đổi
      // sang tiến tới 120 (nhánh F bên dưới chạy thẳng sang G).
      if (t.muonGioTay) {
        if (k > (KHUNG.choDau + DOAN.fCuoi) / 2 && doanCua(tai) === 'R')
          return { trang: { ...t, keHoach: keHoach(tai, daoChieu(tai)!, true) }, phat: true }
        if (i >= DOAN.rCuoi - TRUOC)
          return { trang: { ...t, keHoach: keHoach(DOAN.rCuoi, DOAN.gDau, true) }, phat: true }
        return { trang: t, phat: true }
      }
      // Sắp chạm biên dưới vùng nói (hoặc tới hẹn ngẫu nhiên) ⇒ đổi chiều.
      // KẸP điểm đổi chiều trong đoạn R: tiếng tới đúng lúc vòng chờ đang lùi
      // sát khung 0 thì `tai` rơi ra ngoài R — bản trước bỏ qua, để video
      // chạy lọt sang GR rồi bị lật thành G: ĐƯA TAY mà không ai yêu cầu.
      const taiR = Math.min(tai, DOAN.rCuoi)
      const kR = khungGoc(taiR)
      const daoR = () => ({
        trang: { ...t, henDao: henDaoMoi(), keHoach: keHoach(taiR, daoChieu(taiR)!, true) },
        phat: true as const,
      })
      if (kR <= KHUNG.noiDau) return daoR()
      if (bayGio >= t.henDao && kR <= KHUNG.noiCuoi) return daoR()
      return { trang: t, phat: true }
    }

    // d === 'F'
    if (t.muonGioTay) {
      // Nửa dưới ⇒ đổi sang lùi (nhánh R lùi tới khung 0 rồi sang G): đường về
      // tư thế gốc ngắn hơn. Đo trên trình duyệt: tay lên cao nhất ~5s sau khi
      // ảnh hiện khi cứ đi tiếp theo chiều đang đi; chọn hướng gần bớt ~1–2s.
      if (k <= (KHUNG.choDau + DOAN.fCuoi) / 2 && k > KHUNG.choDau && doanCua(tai) === 'F')
        return { trang: { ...t, keHoach: keHoach(tai, daoChieu(tai)!, true) }, phat: true }
      // Cuối F chạy thẳng sang G (không cần kế hoạch). GIỮ cờ tới khi thật sự
      // vào G — xoá sớm thì nhịp sau lại đặt kế hoạch nối vòng về F1.
      return { trang: t, phat: true }
    }
    if (doanCua(tai) === 'F' && kTai >= KHUNG.noiDau) {
      if (kTai >= KHUNG.noiCuoi) return dao()
      if (bayGio >= t.henDao) return dao()
    }
    // Lọt qua biên trên (vừa thôi muốn đưa tay…) ⇒ nối vòng như cũ.
    if (i >= DOAN.fCuoi - TRUOC)
      return { trang: { ...t, keHoach: keHoach(DOAN.fCuoi, KHUNG.vongVe, true) }, phat: true }
    return { trang: t, phat: true }
  }

  // ── Im lặng ── (nhân vật vẫn LUÔN chuyển động: đi về chờ hoặc vòng chờ,
  // nên mọi nhánh đều cho phát — video lúc mở trang đang dừng)
  if (s.cheDo === 'noi') {
    // Vừa hết tiếng: bỏ yêu cầu đưa tay chưa kịp rẽ, chọn đường về chờ.
    const t: TrangVideo = { ...s, cheDo: 've_nghi', muonGioTay: false, keHoach: null }
    if (d === 'F') {
      if (k <= KHUNG.choCuoi) return { trang: { ...t, cheDo: 'nghi' }, phat: true }
      // Nửa đầu: lùi (R) về ≤ 15. Nửa sau: tiến tới ≥ 104 rồi nối vòng về F1.
      if (k < (KHUNG.choCuoi + KHUNG.yenCao) / 2 && tai <= DOAN.fCuoi)
        return { trang: { ...t, keHoach: keHoach(tai, daoChieu(tai)!, true) }, phat: true }
      return { trang: t, phat: true }
    }
    // Đang lùi mà còn xa đoạn miệng khép dưới ⇒ đổi sang tiến tới ≥ 104.
    if (d === 'R') {
      if (k > (KHUNG.choCuoi + KHUNG.yenCao) / 2 && doanCua(tai) === 'R')
        return { trang: { ...t, keHoach: keHoach(tai, daoChieu(tai)!, true) }, phat: true }
      return { trang: t, phat: true }
    }
    if (d === 'G' && k <= KHUNG.nhacTay - TRUOC)
      return { trang: { ...t, keHoach: keHoach(tai, daoChieu(tai)!, true) }, phat: true }
    return { trang: t, phat: true }
  }

  if (s.keHoach) return { trang: s, phat: true }

  if (s.cheDo === 've_nghi') {
    if (d === 'F' && k <= KHUNG.choCuoi && k >= KHUNG.choDau)
      return { trang: { ...s, cheDo: 'nghi' }, phat: true }
    if (d === 'R' && k <= KHUNG.choCuoi) return { trang: { ...s, cheDo: 'nghi' }, phat: true }
    if (d === 'F' && i >= DOAN.fCuoi - TRUOC)
      return { trang: { ...s, keHoach: keHoach(DOAN.fCuoi, KHUNG.vongVe, true) }, phat: true }
    if (d === 'G' && i >= DOAN.gCuoi - TRUOC)
      return { trang: { ...s, keHoach: keHoach(DOAN.gCuoi, KHUNG.vongVe, true) }, phat: true }
    // Hết đoạn G ngược (về G0 ≈ F0) ⇒ sang F1.
    if (d === 'GR' && i >= DOAN.grCuoi - TRUOC)
      return { trang: { ...s, keHoach: keHoach(DOAN.grCuoi, KHUNG.vongVe, true) }, phat: true }
    return { trang: s, phat: true }
  }

  // ── Chờ: xuôi–ngược trong khung 1–15 ──
  if (d === 'F' && k >= KHUNG.choCuoi - TRUOC)
    return {
      trang: { ...s, keHoach: keHoach(KHUNG.choCuoi, daoChieu(KHUNG.choCuoi)!, true) },
      phat: true,
    }
  if (d === 'R' && k <= KHUNG.choDau + TRUOC) {
    const r = DOAN.rCuoi - KHUNG.choDau // vị trí R của khung chờ đầu
    return { trang: { ...s, keHoach: keHoach(r, daoChieu(r)!, true) }, phat: true }
  }
  // Lọt ra ngoài vùng chờ (không nên xảy ra) ⇒ về như lúc vừa im.
  if (!((d === 'F' || d === 'R') && k <= KHUNG.choCuoi))
    return { trang: { ...s, cheDo: 've_nghi' }, phat: true }
  return { trang: s, phat: true }
}

/**
 * Ước tính bao nhiêu giây (thật) để từ vị trí `i` đi tới khung MIỆNG KHÉP gần
 * nhất — theo ĐÚNG đường `buocVideo` sẽ đi khi hết tiếng. Bộ đo dùng nó để
 * BẮT ĐẦU về sớm khi lượt nói đã xong: còn T giây audio, đường về mất D giây
 * ⇒ thôi nói lúc T ≈ D, miệng khép đúng lúc tiếng tắt.
 */
export function giayVeNghi(i: number): number {
  const d = doanCua(i)
  const k = khungGoc(i)
  const giua = (KHUNG.choCuoi + KHUNG.yenCao) / 2
  let n = 0
  if (d === 'F' || d === 'R') {
    if (k > KHUNG.choCuoi && k < KHUNG.yenCao) {
      // Cùng luật nhánh «vừa hết tiếng»: F nửa đầu lùi, R nửa sau tiến.
      const lui = d === 'F' ? k < giua : k <= giua
      n = lui ? k - KHUNG.choCuoi : KHUNG.yenCao - k
    }
  } else if (d === 'G') n = k <= KHUNG.nhacTay - TRUOC ? k : Math.max(0, KHUNG.gKhep - k)
  else n = k // GR: lùi về G0
  return (n + TRUOC) / (FPS * TOC_DO)
}

/** Tín hiệu tiếng agent do `giongNoi.ts` + sự kiện lượt nuôi (xem `SanKhauAgent`). */
export interface TinHieuLoa {
  /** Mức loa 0…1 (`onMucLoa`). */
  muc: number
  /** Giây audio còn trong hàng đợi, đo lúc `capNhat`. */
  conLai: number
  /** `performance.now()` lúc đo `conLai` — giữa hai lần đo thì tự trừ dần. */
  capNhat: number
  /** Lượt agent đang mở: từ `agent_speaking` tới `agent_done`/`agent_interrupted`. */
  luotMo: boolean
  /** Đã từng thấy sự kiện lượt — gateway cũ không gửi thì rơi về đo theo tiếng. */
  coSuKienLuot: boolean
}

export const TIN_HIEU_IM: TinHieuLoa = {
  muc: 0,
  conLai: 0,
  capNhat: 0,
  luotMo: false,
  coSuKienLuot: false,
}

/**
 * Bộ đo "agent đang nói" — trả `(tín hiệu, bây giờ, giây về nghỉ) ⇒ nói?`.
 *
 * - LƯỢT CÒN MỞ: coi là đang nói nếu có tiếng trong `giuGiuaCauMs` gần nhất —
 *   bắc cầu khoảng lặng giữa hai câu (audio về theo từng câu, giữa câu hàng
 *   đợi có thể cạn vài trăm ms).
 * - LƯỢT ĐÃ XONG: không chờ khoảng lặng nữa — còn bao nhiêu audio là BIẾT
 *   chính xác (`conLai`). Còn nhiều hơn thời gian đường về ⇒ nói tiếp; tới
 *   lúc bằng ⇒ thôi, và CHỐT (không bật lại khi hai đại lượng cùng giảm và
 *   chạm nhau) cho tới khi có khối audio mới hoặc lượt mới.
 * - Chưa từng thấy sự kiện lượt (gateway cũ): đo theo tiếng + `giuMs`.
 *
 * Bản trước chỉ có nhánh cuối với 800ms: người dẫn dừng trễ 1–2s sau khi
 * tiếng tắt (800ms chờ + đường đi về khung khép).
 */
export function taoBoDoNoi({
  nguong,
  giuMs,
  giuGiuaCauMs,
}: {
  nguong: number
  giuMs: number
  giuGiuaCauMs: number
}) {
  let lanCoTieng = -Infinity
  let conLaiTruoc = 0
  let daChot = false
  return (tin: TinHieuLoa, bayGio: number, giayVe: number): boolean => {
    const conLai = Math.max(0, tin.conLai - (bayGio - tin.capNhat) / 1000)
    // Khối audio mới vừa xếp lịch ⇒ hàng đợi DÀI ra.
    if (tin.conLai > conLaiTruoc + 0.03) daChot = false
    conLaiTruoc = tin.conLai
    if (conLai > 0.02 || tin.muc >= nguong) lanCoTieng = bayGio
    // Mốc audio HẾT theo lịch phát — chính xác hơn lần lấy mẫu cuối còn tiếng
    // (mẫu cách nhau ~85ms; khoảng lặng giữa câu phải tính từ lúc tiếng tắt).
    if (tin.conLai > 0) lanCoTieng = Math.max(lanCoTieng, tin.capNhat + tin.conLai * 1000)
    if (!tin.coSuKienLuot) return bayGio - lanCoTieng <= giuMs
    if (tin.luotMo) {
      daChot = false
      return bayGio - lanCoTieng <= giuGiuaCauMs
    }
    if (daChot) return false
    if (conLai > giayVe) return true
    daChot = true
    return false
  }
}
