import { describe, expect, it } from 'vitest'
import type { Media } from '@/features/platform/chatGateway'
import {
  anhHienTai,
  ALBUM_TOI_THIEU_LUOT,
  anhTuMedia,
  cachHien,
  giuAnh,
  kcVong,
  kieuThe,
  LUAN_PHIEN_TRONG,
  nhanBoAnh,
  nhipDoiAnh,
  sangAnh,
  themAnh,
  THOI_GIAN_DOI_ANH_MS,
  xongLuot,
} from '@/features/platform/sanKhau'

const media = (items: unknown[]): Media => ({ items }) as unknown as Media

describe('anhTuMedia — các ảnh nào thành nền sân khấu', () => {
  it('lấy MỌI ảnh theo thứ tự, bản gốc `url`', () => {
    expect(
      anhTuMedia(
        media([
          { kind: 'image', url: 'https://x/1.jpg', thumb: 'https://x/t1.jpg' },
          { kind: 'video', video_id: 'abcdefghijk' },
          { kind: 'image', url: 'https://x/2.jpg' },
        ]),
      ),
    ).toEqual(['https://x/1.jpg', 'https://x/2.jpg'])
  })

  it('thiếu `url` thì dùng `thumb`; ảnh trùng chỉ giữ một', () => {
    expect(
      anhTuMedia(
        media([
          { kind: 'image', url: '', thumb: 'https://x/t.jpg' },
          { kind: 'image', url: 'https://x/t.jpg' },
        ]),
      ),
    ).toEqual(['https://x/t.jpg'])
  })

  it('card không có ảnh ⇒ mảng rỗng (không đổi nền)', () => {
    expect(anhTuMedia(media([{ kind: 'video', video_id: 'abcdefghijk' }]))).toEqual([])
    expect(anhTuMedia(media([]))).toEqual([])
  })
})

describe('album ảnh — tự lướt sau 2 lượt hoặc 6,5s, đóng khi xem hết + đủ 3 lượt', () => {
  const BA = ['a.jpg', 'b.jpg', 'c.jpg']

  it('chưa có ảnh ⇒ không có ảnh hiện tại (nền mặc định)', () => {
    expect(anhHienTai(LUAN_PHIEN_TRONG)).toBeNull()
  })

  it('card mới ⇒ hiện ảnh 1 ngay', () => {
    expect(anhHienTai(nhanBoAnh(LUAN_PHIEN_TRONG, BA, 0))).toBe('a.jpg')
  })

  it('đủ 2 lượt trả lời ⇒ sang ảnh kế (dù chưa đủ thời gian)', () => {
    let s = nhanBoAnh(LUAN_PHIEN_TRONG, BA, 0)
    s = xongLuot(s, 1000)
    expect(anhHienTai(s)).toBe('a.jpg')
    s = xongLuot(s, 2000)
    expect(anhHienTai(s)).toBe('b.jpg')
  })

  it('đủ thời gian ⇒ sang ảnh kế (dù chưa đủ 2 lượt); đếm lại từ lúc đổi', () => {
    let s = nhanBoAnh(LUAN_PHIEN_TRONG, BA, 0)
    s = xongLuot(s, 1000) // 1 lượt
    expect(nhipDoiAnh(s, THOI_GIAN_DOI_ANH_MS - 1)).toBe(s) // chưa tới ⇒ CHÍNH s
    s = nhipDoiAnh(s, THOI_GIAN_DOI_ANH_MS)
    expect(anhHienTai(s)).toBe('b.jpg')
    // Lượt đếm dở trước khi đổi KHÔNG mang sang ảnh mới.
    s = xongLuot(s, THOI_GIAN_DOI_ANH_MS + 100)
    expect(anhHienTai(s)).toBe('b.jpg')
  })

  it('xem hết + quá giờ nhưng CHƯA đủ 3 lượt ⇒ chưa đóng, lướt vòng về ảnh đầu', () => {
    let s = nhanBoAnh(LUAN_PHIEN_TRONG, ['a.jpg', 'b.jpg'], 0)
    s = nhipDoiAnh(s, THOI_GIAN_DOI_ANH_MS) // b — đã xem hết
    for (let n = 2; n <= 6; n++) s = nhipDoiAnh(s, n * THOI_GIAN_DOI_ANH_MS) // 48s, 0 lượt
    expect(s.ds).toHaveLength(2)
    expect(anhHienTai(s)).toBe('a.jpg')
  })

  it('xem HẾT + đủ 3 lượt + ảnh cuối đứng đủ giờ ⇒ album ĐÓNG, về nền mặc định', () => {
    let s = nhanBoAnh(LUAN_PHIEN_TRONG, BA, 0)
    for (let n = 1; n <= 2; n++) s = nhipDoiAnh(s, n * THOI_GIAN_DOI_ANH_MS)
    expect(anhHienTai(s)).toBe('c.jpg')
    s = xongLuot(s, 2 * THOI_GIAN_DOI_ANH_MS + 1)
    s = xongLuot(s, 2 * THOI_GIAN_DOI_ANH_MS + 2) // lượt 2 ⇒ lướt sang a
    s = xongLuot(s, 2 * THOI_GIAN_DOI_ANH_MS + 3) // lượt 3
    expect(s.luotTuLucMo).toBe(ALBUM_TOI_THIEU_LUOT)
    const t = 2 * THOI_GIAN_DOI_ANH_MS + 2
    expect(nhipDoiAnh(s, t + THOI_GIAN_DOI_ANH_MS - 1)).toBe(s)
    expect(nhipDoiAnh(s, t + THOI_GIAN_DOI_ANH_MS)).toBe(LUAN_PHIEN_TRONG)
  })

  it('chỉ MỘT ảnh ⇒ đứng yên, chỉ đóng khi đủ 3 lượt', () => {
    let s = nhanBoAnh(LUAN_PHIEN_TRONG, ['a.jpg'], 0)
    s = xongLuot(xongLuot(s, 1), 2)
    s = nhipDoiAnh(s, 60_000) // 2 lượt ⇒ vẫn mở dù đã 60s
    expect(anhHienTai(s)).toBe('a.jpg')
    s = xongLuot(s, 61_000)
    // Giờ của ảnh tính từ nhịp lúc 60s (lượt xong không đặt lại giờ).
    expect(nhipDoiAnh(s, 60_000 + THOI_GIAN_DOI_ANH_MS - 1)).toBe(s)
    expect(nhipDoiAnh(s, 60_000 + THOI_GIAN_DOI_ANH_MS)).toBe(LUAN_PHIEN_TRONG)
  })

  it('người dùng lướt ⇒ giờ tính lại, đang xem thì không bị đóng ngang', () => {
    let s = nhanBoAnh(LUAN_PHIEN_TRONG, ['a.jpg', 'b.jpg'], 0)
    for (let k = 0; k < 3; k++) s = { ...s, luotTuLucMo: s.luotTuLucMo + 1 }
    s = sangAnh(s, 1, 13_000) // vuốt tới b lúc 13s ⇒ đã xem hết, đủ lượt
    expect(nhipDoiAnh(s, 13_000 + THOI_GIAN_DOI_ANH_MS - 1)).toBe(s)
    s = giuAnh(s, 17_000) // đang chạm
    expect(nhipDoiAnh(s, 17_000 + THOI_GIAN_DOI_ANH_MS - 1)).toBe(s)
    expect(nhipDoiAnh(s, 17_000 + THOI_GIAN_DOI_ANH_MS)).toBe(LUAN_PHIEN_TRONG)
  })

  it('lướt lùi từ ảnh đầu ⇒ vòng về ảnh cuối', () => {
    const s = sangAnh(nhanBoAnh(LUAN_PHIEN_TRONG, BA, 0), -1, 10)
    expect(anhHienTai(s)).toBe('c.jpg')
  })

  it('card mới ⇒ THAY cả bộ, bắt đầu lại từ ảnh 1; card không ảnh ⇒ giữ bộ cũ', () => {
    let s = nhipDoiAnh(nhanBoAnh(LUAN_PHIEN_TRONG, BA, 0), THOI_GIAN_DOI_ANH_MS)
    expect(anhHienTai(s)).toBe('b.jpg')
    s = nhanBoAnh(s, ['x.jpg', 'y.jpg'], 9000)
    expect(anhHienTai(s)).toBe('x.jpg')
    expect(nhanBoAnh(s, [], 9500)).toBe(s)
  })
})

describe('themAnh — ảnh tải xong muộn chen vào album', () => {
  const GOC = ['a.jpg', 'b.jpg', 'c.jpg']
  it('giữ thứ tự gốc, ảnh đang hiện + đã xem không đổi', () => {
    let s = nhanBoAnh(LUAN_PHIEN_TRONG, ['c.jpg'], 0)
    s = themAnh(s, 'a.jpg', GOC)
    expect(s.ds).toEqual(['a.jpg', 'c.jpg'])
    expect(anhHienTai(s)).toBe('c.jpg')
    expect(s.daXem).toEqual([1])
    s = themAnh(s, 'b.jpg', GOC)
    expect(s.ds).toEqual(GOC)
    expect(anhHienTai(s)).toBe('c.jpg')
  })
  it('album đã đóng / ảnh đã có ⇒ giữ nguyên', () => {
    expect(themAnh(LUAN_PHIEN_TRONG, 'a.jpg', GOC)).toBe(LUAN_PHIEN_TRONG)
    const s = nhanBoAnh(LUAN_PHIEN_TRONG, ['a.jpg'], 0)
    expect(themAnh(s, 'a.jpg', GOC)).toBe(s)
  })
})

describe('cachHien — phủ kín hay hiện trọn', () => {
  it('khung rất dẹt (cắt > 60%) + ảnh 3:2 ⇒ hiện TRỌN, không phóng/cắt', () => {
    expect(cachHien(1600, 358, 600, 400)).toBe('contain')
  })
  it('mobile/tablet (khung gần tỉ lệ ảnh) ⇒ phủ kín như trước', () => {
    expect(cachHien(356, 318, 600, 400)).toBe('cover')
    expect(cachHien(700, 360, 600, 400)).toBe('cover')
  })
  it('ảnh dọc trong khung ngang ⇒ hiện trọn', () => {
    expect(cachHien(700, 360, 800, 1200)).toBe('contain')
  })
  it('chưa biết kích thước ⇒ phủ kín (chưa tải xong ảnh / chưa đo khung)', () => {
    expect(cachHien(0, 0, 600, 400)).toBe('cover')
    expect(cachHien(1600, 358, 0, 0)).toBe('cover')
  })
})

describe('hình học album xếp chồng', () => {
  it('khoảng cách vòng: thẻ cuối nằm ngay TRƯỚC thẻ đầu', () => {
    expect(kcVong(5, 0, 6)).toBe(-1)
    expect(kcVong(1, 0, 6)).toBe(1)
    expect(kcVong(0, 5, 6)).toBe(1)
  })
  it('thẻ chính rõ nguyên cỡ trên cùng; ±1 thu 0,94, mờ 45%, nhoè 2px, đối xứng', () => {
    const c = kieuThe(0, 300)
    expect([c.tx, c.sc, c.op, c.bl]).toEqual([0, 1, 1, 0])
    const t = kieuThe(-1, 300)
    const s = kieuThe(1, 300)
    expect(s.sc).toBeCloseTo(0.94)
    expect(s.op).toBeCloseTo(0.45)
    expect(s.bl).toBe(2)
    expect(t.tx).toBe(-s.tx)
    expect(s.tx).toBeGreaterThanOrEqual(20)
    expect(c.z).toBeGreaterThan(s.z)
  })
  it('xa hơn nhỏ + mờ dần, quá ±2,6 thì ẩn', () => {
    expect(kieuThe(2, 300).op).toBeLessThan(kieuThe(1, 300).op)
    expect(kieuThe(2, 300).sc).toBeLessThan(kieuThe(1, 300).sc)
    expect(kieuThe(3, 300).op).toBe(0)
  })
})
