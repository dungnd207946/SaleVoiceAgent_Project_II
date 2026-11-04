import { describe, expect, it } from 'vitest'
import {
  buocVideo,
  daNhay,
  daoChieu,
  datGioTay,
  DOAN,
  doanCua,
  GIAN_CACH_GIO_TAY_MS,
  KHUNG,
  khungGoc,
  giayVeNghi,
  NOI_TRUOC_GIO_TAY_MS,
  taoBoDoNoi,
  TIN_HIEU_IM,
  TRANG_DAU,
  type TinHieuLoa,
  type TrangVideo,
} from '@/features/platform/nguoiDan'

// Logic THUẦN của người dẫn (`SanKhauAgent`). Phần vẽ (WebGL + <video>) không
// chạy dưới jsdom, nên mọi quyết định «chạy tiếp, đảo chiều, đổi video» dồn
// vào đây — và bài mô phỏng cuối file canh LỜI HỨA của cả thiết kế: mọi bước
// chuyển chỉ thuộc tập đã ĐO là liền mạch, không bao giờ chen một khung lạ.

const tin = (p: Partial<TinHieuLoa>): TinHieuLoa => ({ ...TIN_HIEU_IM, ...p })
const boDo = () => taoBoDoNoi({ nguong: 0.05, giuMs: 800, giuGiuaCauMs: 1500 })

describe('taoBoDoNoi — gateway cũ (không có sự kiện lượt): đo theo tiếng', () => {
  it('vượt ngưỡng ⇒ nói ngay; im quá `giuMs` ⇒ thôi', () => {
    const noi = boDo()
    expect(noi(tin({}), 0, 1)).toBe(false)
    expect(noi(tin({ muc: 0.2 }), 10, 1)).toBe(true)
    expect(noi(tin({}), 800, 1)).toBe(true)
    expect(noi(tin({}), 811, 1)).toBe(false)
  })
})

describe('taoBoDoNoi — có sự kiện lượt: biết chính xác còn bao nhiêu audio', () => {
  it('lượt CÒN MỞ ⇒ bắc cầu khoảng lặng giữa hai câu tới `giuGiuaCauMs`', () => {
    const noi = boDo()
    expect(noi(tin({ luotMo: true, coSuKienLuot: true, conLai: 1, capNhat: 0 }), 0, 1)).toBe(true)
    // Hàng đợi cạn (giữa hai câu) nhưng lượt chưa xong ⇒ vẫn nói.
    const can = tin({ luotMo: true, coSuKienLuot: true, conLai: 0, capNhat: 1200 })
    expect(noi(can, 2400, 1)).toBe(true)
    expect(noi(can, 2600, 1)).toBe(false)
  })

  it('lượt ĐÃ XONG ⇒ nói tới khi audio còn lại = thời gian đường về, rồi thôi NGAY', () => {
    const noi = boDo()
    // Còn 3s audio, đường về mất 1s.
    const t = tin({ coSuKienLuot: true, conLai: 3, capNhat: 0 })
    expect(noi(t, 0, 1)).toBe(true)
    expect(noi(t, 1900, 1)).toBe(true) // còn 1,1s > 1s
    expect(noi(t, 2050, 1)).toBe(false) // còn 0,95s ≤ 1s ⇒ bắt đầu về, khép đúng lúc tiếng tắt
  })

  it('đã thôi thì CHỐT — không bật lại khi hai đại lượng cùng giảm và chạm nhau', () => {
    const noi = boDo()
    const t = tin({ coSuKienLuot: true, conLai: 1, capNhat: 0 })
    expect(noi(t, 100, 1)).toBe(false)
    // Đi về làm đường về ngắn lại; audio cũng cạn dần — vẫn im.
    expect(noi(t, 200, 0.5)).toBe(false)
  })

  it('khối audio MỚI tới sau khi đã chốt ⇒ nói lại', () => {
    const noi = boDo()
    expect(noi(tin({ coSuKienLuot: true, conLai: 0.5, capNhat: 0 }), 0, 1)).toBe(false)
    expect(noi(tin({ coSuKienLuot: true, conLai: 2.5, capNhat: 100 }), 100, 1)).toBe(true)
  })

  it('lượt mới mở ⇒ bỏ chốt', () => {
    const noi = boDo()
    expect(noi(tin({ coSuKienLuot: true, conLai: 0, capNhat: 0 }), 0, 1)).toBe(false)
    expect(noi(tin({ coSuKienLuot: true, luotMo: true, conLai: 0.4, capNhat: 50 }), 50, 1)).toBe(
      true,
    )
  })
})

describe('giayVeNghi — thời gian từ vị trí hiện tại tới khung miệng khép', () => {
  it('đã ở khung khép ⇒ chỉ còn độ trễ kế hoạch', () => {
    expect(giayVeNghi(5)).toBeCloseTo(giayVeNghi(110), 5)
    expect(giayVeNghi(5)).toBeLessThan(0.3)
  })

  it('càng sâu trong vùng nói càng lâu, xa nhất ở giữa', () => {
    expect(giayVeNghi(30)).toBeLessThan(giayVeNghi(55))
    expect(giayVeNghi(90)).toBeLessThan(giayVeNghi(65))
    expect(giayVeNghi(59)).toBeLessThan(2.5)
  })
})

describe('bố cục tệp — bốn đoạn, đảo chiều về đúng khung kề', () => {
  it('khungGoc theo đúng bảng trong docstring', () => {
    expect([khungGoc(0), khungGoc(120), khungGoc(121), khungGoc(241)]).toEqual([0, 120, 0, 120])
    expect([khungGoc(242), khungGoc(362), khungGoc(363), khungGoc(409)]).toEqual([120, 0, 46, 0])
  })

  it('đảo chiều F ⇄ R sang khung KỀ (k ⇒ k−1 khi lùi, k ⇒ k+1 khi tiến)', () => {
    for (const k of [1, 15, 60, 119]) {
      const r = daoChieu(k)!
      expect(doanCua(r)).toBe('R')
      expect(khungGoc(r)).toBe(k - 1)
      expect(khungGoc(daoChieu(r)!)).toBe(k)
    }
  })

  it('đảo chiều G ⇄ GR chỉ có trước lúc nhấc tay', () => {
    const g = DOAN.gDau + 20
    expect(doanCua(daoChieu(g)!)).toBe('GR')
    expect(khungGoc(daoChieu(g)!)).toBe(19)
    expect(daoChieu(DOAN.gDau + KHUNG.nhacTay + 1)).toBeNull()
  })
})

/** Các bước chuyển ĐÃ ĐO là liền mạch (xem docstring `nguoiDan.ts`). */
function hopLe(tu: number, toi: number): boolean {
  if (toi === tu + 1) return true // khung kế tiếp (gồm F120 → G0)
  const noiVong: readonly number[] = [DOAN.fCuoi, DOAN.gCuoi, DOAN.grCuoi]
  if (toi === KHUNG.vongVe && noiVong.includes(tu)) return true
  if (tu === DOAN.rCuoi && toi === DOAN.gDau) return true // R khung 0 ≈ G0
  return daoChieu(tu) === toi
}

/** Chạy mô phỏng: mỗi bước một khung. Trả các vị trí đã hiện. */
function moPhong(
  s0: TrangVideo,
  i0: number,
  kichBan: (buoc: number) => boolean,
  soBuoc: number,
  rand: () => number = () => 0,
): { daHien: number[]; s: TrangVideo } {
  let s = s0
  let i = i0
  const daHien = [i]
  for (let b = 0; b < soBuoc; b++) {
    const bayGio = b * 40
    s = buocVideo(s, i, kichBan(b), bayGio, rand).trang
    const kh = s.keHoach
    let sau = i + 1
    if (kh && i === kh.tai) {
      sau = kh.toi
      s = daNhay(s)
    }
    expect(hopLe(i, sau), `bước ${b}: ${i} → ${sau}`).toBe(true)
    expect(sau).toBeLessThanOrEqual(DOAN.grCuoi)
    i = sau
    daHien.push(i)
  }
  return { daHien, s }
}

describe('buocVideo — mọi bước chuyển liền mạch', () => {
  it('đứng chờ lâu ⇒ chỉ xuôi–ngược trong khung 1–15 (miệng khép, mắt mở)', () => {
    const { daHien } = moPhong(TRANG_DAU, 0, () => false, 600)
    for (const p of daHien.slice(1)) {
      expect(['F', 'R']).toContain(doanCua(p))
      expect(khungGoc(p)).toBeLessThanOrEqual(KHUNG.choCuoi)
    }
    // Có đi cả hai chiều — không phải đứng im một khung.
    expect(daHien.some((p) => doanCua(p) === 'R')).toBe(true)
  })

  it('mới mở trang (video đang dừng ở vị trí 0) ⇒ vòng chờ được lệnh PHÁT', () => {
    expect(buocVideo(TRANG_DAU, 0, false, 0).phat).toBe(true)
  })

  it('ĐANG NÓI thì không chạm khung miệng khép (lỗi «1–2s về nghỉ giữa lúc nói»)', () => {
    let h = 3
    const rand = () => (h = (h * 1103515245 + 12345) % 2 ** 31) / 2 ** 31
    const { daHien } = moPhong({ ...TRANG_DAU, tuDongGioTay: false }, 0, () => true, 3000, rand)
    // Bỏ qua đoạn khởi động (từ khung chờ đi lên vùng nói).
    const sauKhoiDong = daHien.slice(daHien.findIndex((p) => khungGoc(p) >= KHUNG.noiDau))
    for (const p of sauKhoiDong) {
      expect(khungGoc(p)).toBeGreaterThanOrEqual(KHUNG.noiDau - 1)
      expect(khungGoc(p)).toBeLessThanOrEqual(KHUNG.noiCuoi + 1)
    }
  })

  it('đổi chiều khi nói ở NHIỀU chỗ khác nhau — không thành một vòng lặp đều', () => {
    let h = 11
    const rand = () => (h = (h * 1103515245 + 12345) % 2 ** 31) / 2 ** 31
    const { daHien } = moPhong({ ...TRANG_DAU, tuDongGioTay: false }, 0, () => true, 3000, rand)
    const diemDao = new Set<number>()
    for (let n = 1; n < daHien.length; n++)
      if (daoChieu(daHien[n - 1]!) === daHien[n]) diemDao.add(khungGoc(daHien[n - 1]!))
    expect(diemDao.size).toBeGreaterThan(8)
  })

  it('muốn đưa tay lúc đang LÙI ⇒ lùi tới khung 0 rồi nối thẳng sang G', () => {
    let s: TrangVideo = { ...TRANG_DAU, tuDongGioTay: false, cheDo: 'noi', henDao: Infinity }
    s = datGioTay(s)
    const { daHien } = moPhong(s, daoChieu(60)!, () => true, 200)
    const vao = daHien.indexOf(DOAN.gDau)
    expect(vao).toBeGreaterThan(0)
    expect(daHien[vao - 1]).toBe(DOAN.rCuoi)
  })

  it('lệnh đưa tay ⇒ về tư thế gốc theo hướng GẦN hơn rồi vào G', () => {
    for (const [batDau, toiDa] of [
      [30, 40], // nửa dưới F ⇒ lùi về khung 0
      [90, 40], // nửa trên F ⇒ tiến tới 120
      [daoChieu(95)!, 40], // nửa trên R ⇒ đổi sang tiến
      [daoChieu(28)!, 40], // nửa dưới R ⇒ lùi tiếp
    ] as const) {
      const s = datGioTay({ ...TRANG_DAU, tuDongGioTay: false, cheDo: 'noi', henDao: Infinity })
      const { daHien } = moPhong(s, batDau, () => true, 200)
      const vao = daHien.indexOf(DOAN.gDau)
      expect(vao, `từ vị trí ${batDau}`).toBeGreaterThan(0)
      expect(vao, `từ vị trí ${batDau}`).toBeLessThanOrEqual(toiDa)
    }
  })

  it('nói liên tục 60s ⇒ tự đưa tay ~10–15s một lần (≥ 4 lần), cách nhau ≥ GIAN_CACH', () => {
    let h = 5
    const rand = () => (h = (h * 1103515245 + 12345) % 2 ** 31) / 2 ** 31
    const { daHien } = moPhong(TRANG_DAU, 0, () => true, 1500, rand)
    const vao = daHien
      .map((p, n) => (p === DOAN.gDau && n > 0 && doanCua(daHien[n - 1]!) !== 'G' ? n : -1))
      .filter((n) => n >= 0)
    expect(vao.length).toBeGreaterThanOrEqual(4)
    for (let n = 1; n < vao.length; n++)
      expect((vao[n]! - vao[n - 1]!) * 40).toBeGreaterThanOrEqual(GIAN_CACH_GIO_TAY_MS)
  })

  it('nói ngắn (< 3s) ⇒ không đưa tay', () => {
    const { daHien } = moPhong(TRANG_DAU, 0, (b) => b < 60, 400)
    expect(daHien.some((p) => doanCua(p) === 'G')).toBe(false)
  })

  it('nói một lúc (≥ 3s) ⇒ tự đưa tay ở cuối vòng nói kế tiếp, rồi nói tiếp ở đầu F', () => {
    const buocNoi = NOI_TRUOC_GIO_TAY_MS / 40
    const { daHien } = moPhong(TRANG_DAU, 0, () => true, buocNoi + 400)
    const vaoG = daHien.findIndex((p) => doanCua(p) === 'G')
    expect(vaoG).toBeGreaterThan(0)
    // Vào G từ tư thế gốc: cuối F (khung kế tiếp) hoặc đầu dưới R (khung 0 ≈ G0).
    expect([DOAN.fCuoi, DOAN.rCuoi]).toContain(daHien[vaoG - 1])
    // Chạy TRỌN cử chỉ rồi về F1.
    const raG = daHien.indexOf(DOAN.gCuoi)
    expect(daHien[raG + 1]).toBe(KHUNG.vongVe)
  })

  it('nói liên tục ⇒ đưa tay lặp lại nhưng cách nhau ≥ GIAN_CACH_GIO_TAY_MS', () => {
    const { daHien } = moPhong(TRANG_DAU, 0, () => true, 1200)
    const vao = daHien
      .map((p, n) => (p === DOAN.gDau && n > 0 && doanCua(daHien[n - 1]!) !== 'G' ? n : -1))
      .filter((n) => n >= 0)
    expect(vao.length).toBeGreaterThanOrEqual(2)
    for (let n = 1; n < vao.length; n++)
      expect((vao[n]! - vao[n - 1]!) * 40).toBeGreaterThanOrEqual(GIAN_CACH_GIO_TAY_MS)
  })

  it('yêu cầu đưa tay từ NGOÀI ⇒ rẽ vào G ngay ở cuối F kế tiếp, dù mới nói', () => {
    const s = datGioTay({ ...TRANG_DAU, tuDongGioTay: false })
    const { daHien } = moPhong(s, 0, () => true, 200)
    expect(daHien).toContain(DOAN.gDau)
  })

  it('tắt tự động ⇒ nói dài cũng không đưa tay', () => {
    const { daHien } = moPhong({ ...TRANG_DAU, tuDongGioTay: false }, 0, () => true, 900)
    expect(daHien.some((p) => doanCua(p) === 'G')).toBe(false)
  })

  it('thôi nói ở nửa đầu F ⇒ LÙI về vòng chờ, không chạy hết clip', () => {
    const { daHien } = moPhong(TRANG_DAU, 0, (b) => b < 40, 200)
    const sauIm = daHien.slice(41)
    expect(sauIm.some((p) => doanCua(p) === 'R')).toBe(true)
    expect(Math.max(...sauIm.map(khungGoc))).toBeLessThanOrEqual(45)
    expect(khungGoc(daHien.at(-1)!)).toBeLessThanOrEqual(KHUNG.choCuoi)
  })

  it('thôi nói ở nửa sau F ⇒ TIẾN tới đoạn miệng khép rồi nối vòng về chờ', () => {
    const { daHien } = moPhong(TRANG_DAU, 0, (b) => b < 90, 300)
    expect(daHien).toContain(KHUNG.vongVe)
    expect(khungGoc(daHien.at(-1)!)).toBeLessThanOrEqual(KHUNG.choCuoi)
  })

  it('thôi nói trong G trước khi nhấc tay ⇒ lùi bằng G ngược, không giơ tay khi im', () => {
    const s = datGioTay({ ...TRANG_DAU, tuDongGioTay: false })
    // Tìm lúc vào G khi nói liên tục, rồi cho im 20 khung sau đó (tay chưa nhấc).
    const vaoG = moPhong(s, 0, () => true, 400).daHien.indexOf(DOAN.gDau)
    expect(vaoG).toBeGreaterThan(0)
    const { daHien } = moPhong(s, 0, (b) => b < vaoG + 20, 400)
    const sauIm = daHien.slice(vaoG + 21)
    expect(sauIm.some((p) => doanCua(p) === 'GR')).toBe(true)
    for (const p of sauIm)
      if (doanCua(p) === 'G') expect(khungGoc(p)).toBeLessThanOrEqual(KHUNG.nhacTay)
    expect(khungGoc(daHien.at(-1)!)).toBeLessThanOrEqual(KHUNG.choCuoi)
  })

  it('thôi nói khi tay đã nhấc ⇒ làm nốt cử chỉ rồi mới về chờ', () => {
    const s = datGioTay({ ...TRANG_DAU, tuDongGioTay: false })
    const vaoG = moPhong(s, 0, () => true, 400).daHien.indexOf(DOAN.gDau)
    const { daHien } = moPhong(s, 0, (b) => b < vaoG + 60, 500)
    expect(daHien).toContain(DOAN.gCuoi)
    expect(khungGoc(daHien.at(-1)!)).toBeLessThanOrEqual(KHUNG.choCuoi)
  })

  it('có tiếng lại lúc đang lùi về chờ ⇒ đổi chiều TRƯỚC khi chạm khung miệng khép', () => {
    const { daHien } = moPhong(TRANG_DAU, 0, (b) => b < 40 || (b >= 46 && b < 400), 300)
    const R = daHien.findIndex((p) => doanCua(p) === 'R')
    expect(R).toBeGreaterThan(0)
    const sau = daHien.slice(R)
    const quayLai = sau.findIndex((p) => doanCua(p) === 'F')
    expect(quayLai).toBeGreaterThan(0)
    // Miệng chỉ KHÉP ở khung ≤ 16 (đo độ mở miệng). Có tiếng lại khi đã lùi
    // sát biên vùng nói thì chỗ đổi chiều có thể dưới `noiDau` một chút —
    // vẫn là khung đang nói.
    for (const p of sau.slice(0, quayLai)) expect(khungGoc(p)).toBeGreaterThan(16)
  })

  it('có tiếng đúng lúc vòng chờ đang lùi SÁT khung 0 ⇒ không lọt sang GR/G (đưa tay không ai yêu cầu)', () => {
    for (const vt of [DOAN.rCuoi - 3, DOAN.rCuoi - 2, DOAN.rCuoi - 1, DOAN.rCuoi]) {
      const { daHien } = moPhong({ ...TRANG_DAU, tuDongGioTay: false }, vt, () => true, 300)
      expect(
        daHien.some((p) => doanCua(p) === 'G' || doanCua(p) === 'GR'),
        `từ ${vt}`,
      ).toBe(false)
    }
  })

  it('tắt tự đưa tay + nói/im ngẫu nhiên 5 phút ⇒ KHÔNG BAO GIỜ vào G hay GR', () => {
    let h = 19
    const rand = () => (h = (h * 1103515245 + 12345) % 2 ** 31) / 2 ** 31
    let noi = false
    let doiLuc = 0
    const { daHien } = moPhong(
      { ...TRANG_DAU, tuDongGioTay: false },
      0,
      (b) => {
        if (b >= doiLuc) {
          noi = !noi
          doiLuc = b + 3 + Math.floor(rand() * 200)
        }
        return noi
      },
      7500,
      rand,
    )
    expect(daHien.some((p) => doanCua(p) === 'G' || doanCua(p) === 'GR')).toBe(false)
  })

  it('mô phỏng ngẫu nhiên 5 phút nói/im xen kẽ: không bao giờ có bước chuyển lạ', () => {
    let h = 7
    const rand = () => (h = (h * 1103515245 + 12345) % 2 ** 31) / 2 ** 31
    let noi = false
    let doiLuc = 0
    moPhong(
      TRANG_DAU,
      0,
      (b) => {
        if (b >= doiLuc) {
          noi = !noi
          doiLuc = b + 10 + Math.floor(rand() * 300)
        }
        return noi
      },
      7500,
      rand,
    )
  })
})
