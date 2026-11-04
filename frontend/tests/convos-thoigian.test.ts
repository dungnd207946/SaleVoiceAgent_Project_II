import { describe, expect, it } from 'vitest'
import { gioNgan, khoangKy, mocNgay, thoiLuong } from '@/features/ops/thoiGian'

/**
 * Mốc dựng theo giờ ĐỊA PHƯƠNG của máy chạy test — KHÔNG viết chuỗi ISO có hậu tố
 * `+07:00`.
 *
 * VÌ SAO: `thoiGian.ts` chia ngày bằng `getFullYear()/getMonth()/getDate()`, mà ba
 * hàm đó đọc theo múi giờ của TIẾN TRÌNH, không theo hậu tố trong chuỗi ISO. Một ca
 * `'2026-07-26T23:50:00+07:00'` là 16:50 ngày 26 dưới `TZ=UTC` — tức nó rơi sang một
 * ngày khác, và test ĐỎ trên code ĐÚNG. Máy dev ở đây chạy Asia/Bangkok nên chuyện
 * đó không lộ ra; container CI thường là UTC. Đã đo: dưới `TZ=UTC`, bốn ca dùng
 * chuỗi `+07:00` đỏ hết dù `thoiGian.ts` không sai một dòng nào.
 *
 * Dựng mốc theo giờ địa phương làm test độc lập múi giờ, VÀ kiểm đúng hợp đồng thật:
 * "hôm nay" là hôm nay theo lịch của người đang xem màn hình.
 *
 * `thang` ở đây đếm từ 1 — `new Date()` đếm tháng từ 0, và đó là một trong những
 * chỗ dễ lệch nhất khi đọc code test.
 */
function luc(nam: number, thang: number, ngay: number, gio: number, phut = 0): Date {
  return new Date(nam, thang - 1, ngay, gio, phut)
}

const iso = (d: Date) => d.toISOString()

const BAY_GIO = luc(2026, 7, 27, 18)

describe('gioNgan', () => {
  it('hôm nay thì chỉ hiện giờ', () => {
    expect(gioNgan(iso(luc(2026, 7, 27, 14, 22)), BAY_GIO)).toBe('14:22')
  })

  it('hôm qua thì nói «hôm qua», không phải một con số ngày', () => {
    expect(gioNgan(iso(luc(2026, 7, 26, 9, 10)), BAY_GIO)).toBe('hôm qua')
  })

  it('trong tuần thì đếm số ngày', () => {
    expect(gioNgan(iso(luc(2026, 7, 24, 9, 10)), BAY_GIO)).toBe('3 ngày trước')
  })

  it('cũ hơn một tuần thì hiện ngày đầy đủ', () => {
    expect(gioNgan(iso(luc(2026, 7, 14, 16, 40)), BAY_GIO)).toBe('14/07/2026')
  })

  // Hai ca dưới đây ĐỨNG SÁT NỬA ĐÊM, và đó là toàn bộ lý do chúng tồn tại.
  // Mọi ca ở trên đều cách nửa đêm vài giờ, nên chúng xanh cho CẢ hai cách tính:
  // đếm theo lịch (đúng) và đếm số giờ trôi qua rồi chia 24 (sai). Không có hai ca
  // này thì `soNgayCach` có thể bị viết lại thành phép chia trần mà không ai đỏ.

  it('qua nửa đêm là «hôm qua», dù mới cách 20 phút', () => {
    // Giết biến thể `Math.floor(elapsed / 86_400_000)`: 20 phút ⇒ 0 ngày ⇒ «hôm nay».
    const rangSang = luc(2026, 7, 27, 0, 10)
    const truoc = iso(luc(2026, 7, 26, 23, 50))
    expect(gioNgan(truoc, rangSang)).toBe('hôm qua')
    expect(mocNgay(truoc, rangSang)).toBe('hom-qua')
  })

  it('cùng ngày lịch nhưng cách gần 24 tiếng vẫn là hôm nay', () => {
    // Giết biến thể `Math.round(elapsed / 86_400_000)`: 23h40 ⇒ 1 ngày ⇒ «hôm qua».
    const toiMuon = luc(2026, 7, 27, 23, 50)
    const sang = iso(luc(2026, 7, 27, 0, 10))
    expect(gioNgan(sang, toiMuon)).toBe('00:10')
    expect(mocNgay(sang, toiMuon)).toBe('hom-nay')
  })
})

describe('thoiLuong', () => {
  it('tính hiệu hai mốc thành m:ss', () => {
    expect(thoiLuong('2026-07-27T14:22:00Z', '2026-07-27T14:23:48Z')).toBe('1:48')
  })

  it('ketThuc null ⇒ null, KHÔNG phải «0:00»', () => {
    // «0:00» là một con số SAI: nó nói cuộc hội thoại dài 0 giây, chứ không nói
    // «chưa biết nó dài bao lâu».
    expect(thoiLuong('2026-07-27T14:22:00Z', null)).toBeNull()
  })

  it('batDau null ⇒ null', () => {
    expect(thoiLuong(null, '2026-07-27T14:23:48Z')).toBeNull()
  })
})

describe('mocNgay', () => {
  it('phân nhóm để danh sách có nhịp', () => {
    expect(mocNgay(iso(luc(2026, 7, 27, 14, 22)), BAY_GIO)).toBe('hom-nay')
    expect(mocNgay(iso(luc(2026, 7, 26, 9, 10)), BAY_GIO)).toBe('hom-qua')
    expect(mocNgay(iso(luc(2026, 7, 23, 9, 10)), BAY_GIO)).toBe('tuan-truoc')
    expect(mocNgay(iso(luc(2026, 6, 1, 9, 10)), BAY_GIO)).toBe('cu-hon')
  })
})

describe('khoangKy', () => {
  /* Nhãn kỳ của màn Tổng quan. KHÔNG qua `new Date()`: chuỗi vào đã là ngày
     lịch, và `new Date('2026-08-07')` parse theo UTC nên ở múi giờ âm nó lùi
     một ngày — cùng cái bẫy đã ghi ở đầu file này. */

  it('cùng năm ⇒ in năm MỘT lần, ở cuối', () => {
    expect(khoangKy('2026-08-07', '2026-08-13')).toBe('07/08 – 13/08/2026')
  })

  it('vắt qua năm ⇒ in cả hai năm', () => {
    expect(khoangKy('2025-12-28', '2026-01-03')).toBe('28/12/2025 – 03/01/2026')
  })

  it('thiếu một đầu ⇒ `null`, để chỗ gọi ẨN HẲN nhãn', () => {
    /* Chuỗi rỗng là "thiếu" (`api.ts` cố ý không bịa ngày khi backend cũ bỏ
       khoá `moc`). Trả `'– 13/08/2026'` là vẽ một khoảng trống có dấu gạch
       nối, tức nói rằng có một kỳ ở đó mà người đọc không đọc được. */
    expect(khoangKy('', '2026-08-13')).toBeNull()
    expect(khoangKy('2026-08-07', '')).toBeNull()
    expect(khoangKy('', '')).toBeNull()
  })

  it('chuỗi không đúng dạng ISO ⇒ `null`, không in ra rác', () => {
    expect(khoangKy('07/08/2026', '2026-08-13')).toBeNull()
  })
})
