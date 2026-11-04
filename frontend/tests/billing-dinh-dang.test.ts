import { describe, expect, it } from 'vitest'
import {
  chiaTien,
  congTien,
  giay,
  phanTram,
  rong,
  soSanhTien,
  tien,
  tienDay,
  tienGon,
  token,
} from '@/features/billing/dinh-dang'
import { giaiMaKy } from '@/features/billing/ky'

describe('tien', () => {
  it('VND không chữ số thập phân, dấu . phân nghìn', () => {
    expect(tien('1204500.4821')).toBe('1.204.500')
  })
  it('nhận string chứ không number — Decimal(20,10) mất chính xác khi qua number', () => {
    // 9007199254740993 > Number.MAX_SAFE_INTEGER: qua number sẽ thành …992
    expect(tien('9007199254740993')).toBe('9.007.199.254.740.993')
  })
  it('0 vẫn là 0, không phải chuỗi rỗng', () => {
    expect(tien('0')).toBe('0')
  })
  it('0.5 làm tròn lên 1 (round half away from zero)', () => {
    expect(tien('0.5')).toBe('1')
  })
  it('số âm: -1204500.6 làm tròn về -1.204.501, giữ dấu', () => {
    expect(tien('-1204500.6')).toBe('-1.204.501')
  })
  it('không có phần thập phân vẫn nhóm nghìn đúng', () => {
    expect(tien('1204500')).toBe('1.204.500')
  })
})

describe('tienGon', () => {
  it('dưới 1 triệu giữ nguyên số đầy đủ như tien(), không có bậc', () => {
    expect(tienGon('125011.4000000000')).toEqual({ so: '125.011', hau: '' })
    expect(tienGon('999999.4')).toEqual({ so: '999.999', hau: '' })
  })
  it('rút về triệu/tỷ, ĐÚNG 3 chữ số lẻ dấu chấm, CẮT chứ không làm tròn', () => {
    expect(tienGon('98768432.9')).toEqual({ so: '98.768', hau: 'triệu' })
    expect(tienGon('1000000')).toEqual({ so: '1.000', hau: 'triệu' })
    expect(tienGon('999999900')).toEqual({ so: '999.999', hau: 'triệu' })
    expect(tienGon('12345678901')).toEqual({ so: '12.345', hau: 'tỷ' })
    expect(tienGon('1234567890123')).toEqual({ so: '1234.567', hau: 'tỷ' })
  })
  it('nhận dạng mũ của Pydantic', () => {
    expect(tienGon('0E-10')).toEqual({ so: '0', hau: '' })
  })
})

describe('tienDay', () => {
  it('giữ 4 chữ số thập phân cho tooltip đối soát', () => {
    expect(tienDay('1204500.4821')).toBe('1.204.500,4821 ₫')
  })
})

describe('token', () => {
  it('< 10 000 hiện nguyên', () => expect(token(9999)).toBe('9.999'))
  it('≥ 10 000 rút về k', () => expect(token(48250)).toBe('48k'))
  // Dấu CHẤM, không phải dấu phẩy — ngoại lệ có ý thức với locale vi-VN, xem
  // docstring `token()`. Bài này là chỗ duy nhất khoá lại quyết định đó.
  it('≥ 1 000 000 rút về M, 2 số lẻ, thập phân bằng dấu CHẤM', () =>
    expect(token(1204500)).toBe('1.20M'))
})

describe('giay', () => {
  it('< 60 hiện giây một số lẻ, hậu tố LIỀN như nhánh ≥ 60 (`1h 20m 21s`)', () =>
    expect(giay(48.24)).toBe('48,2s'))
  it('≥ 60 tách giờ/phút/giây', () => expect(giay(4821)).toBe('1h 20m 21s'))
  it('142.44 của fixture BE', () => expect(giay(142.44)).toBe('2m 22s'))
})

describe('phanTram', () => {
  it('một số lẻ', () => expect(phanTram(148, 4352)).toBe('3,4%'))
  it('mẫu 0 ra — chứ không NaN%', () => expect(phanTram(5, 0)).toBe('—'))
})

describe('rong', () => {
  // provider/model của component audio là '' (DEFAULT '', KHÔNG phải NULL)
  it("'' ra —", () => expect(rong('')).toBe('—'))
  it('null ra —', () => expect(rong(null)).toBe('—'))
  it('có giá trị thì trả nguyên', () => expect(rong('anthropic')).toBe('anthropic'))
})

describe('congTien', () => {
  it('cộng đúng khi số chữ số thập phân KHÁC NHAU giữa các phần tử', () => {
    expect(congTien(['1', '2.50'])).toBe('3.50')
  })
  it('mảng rỗng ra "0"', () => {
    expect(congTien([])).toBe('0')
  })
  it('CHÍNH XÁC trên số vượt Number.MAX_SAFE_INTEGER — không qua Number', () => {
    // 9007199254740993 + 1 qua `Number` sẽ dính lại ở …994 (mất chính xác im lặng).
    expect(congTien(['9007199254740993', '1'])).toBe('9007199254740994')
  })
})

describe('soSanhTien', () => {
  it('bằng nhau dù viết khác số 0 ở cuối', () => {
    expect(soSanhTien('0.30', '0.3')).toBe(0)
  })
  it('phân biệt được hai số CHỈ khác nhau ở phần vượt Number.MAX_SAFE_INTEGER', () => {
    expect(soSanhTien('9007199254740993', '9007199254740992')).toBe(1)
  })
  it('âm nhỏ hơn dương', () => {
    expect(soSanhTien('-1', '0.0000000001')).toBe(-1)
  })
})

describe('giaiMaKy', () => {
  it('thang-nay: to là đầu tháng SAU, không phải hôm nay', () => {
    expect(giaiMaKy('thang-nay', new Date('2026-08-20T00:00:00Z'))).toEqual({
      from: '2026-08-01',
      to: '2026-09-01',
      dangChay: true,
    })
  })

  it('thang-truoc: bắc qua mốc năm — tháng 1 trả về tháng 12 năm trước', () => {
    expect(giaiMaKy('thang-truoc', new Date('2026-01-15T00:00:00Z'))).toEqual({
      from: '2025-12-01',
      to: '2026-01-01',
      dangChay: false,
    })
  })

  it('thang-truoc: ca thường (không bắc qua năm)', () => {
    expect(giaiMaKy('thang-truoc', new Date('2026-08-20T00:00:00Z'))).toEqual({
      from: '2026-07-01',
      to: '2026-08-01',
      dangChay: false,
    })
  })

  it('7-ngay: cửa sổ 7 ngày kết thúc ở đầu ngày MAI (nửa mở)', () => {
    expect(giaiMaKy('7-ngay', new Date('2026-08-20T00:00:00Z'))).toEqual({
      from: '2026-08-14',
      to: '2026-08-21',
      dangChay: true,
    })
  })

  it('30-ngay: bắc qua mốc tháng', () => {
    expect(giaiMaKy('30-ngay', new Date('2026-08-20T00:00:00Z'))).toEqual({
      from: '2026-07-22',
      to: '2026-08-21',
      dangChay: true,
    })
  })
})

describe('chiaTien', () => {
  it('giữ ĐỦ chữ số thập phân của toán hạng — không đọc chuỗi thành số lớn hơn 10^k lần', () => {
    // Bản đầu ép `soLe = 4` trong khi `x` có 10 chữ số thập phân. `veBigInt()`
    // chỉ `padEnd`, không cắt — nên `'125000.5000000000'` bị đọc thành
    // 1.250.005.000.000.000 và kết quả ra 31.250.125.000 thay vì 31.250,125.
    // Sai IM LẶNG: không kiểu nào đỏ, chỉ một con số trên màn hình lớn gấp
    // một triệu lần.
    expect(tien(chiaTien('125000.5000000000', 4))).toBe('31.250')
  })

  it('chia hết và chia lẻ đều đúng, cả với chuỗi không phần thập phân', () => {
    expect(chiaTien('100', 4)).toBe('25.0000')
    expect(chiaTien('10.0000', 3)).toBe('3.3333')
  })

  it('mẫu số 0 hoặc âm trả «0» thay vì ném — kỳ rỗng không được làm sập màn', () => {
    expect(chiaTien('125000.5000000000', 0)).toBe('0')
    expect(chiaTien('125000.5000000000', -3)).toBe('0')
  })
})

/**
 * KÝ HIỆU MŨ — dạng chuỗi THẬT của một `Decimal` bằng 0 trên cột `numeric(20,10)`.
 *
 * Pydantic serialize `Decimal` bằng `str()`, và `str()` chuyển sang ký hiệu mũ
 * khi số mũ điều chỉnh < -6: `str(Decimal('0.0000000000'))` ra `'0E-10'`, KHÔNG
 * phải `'0'`. Đường tới được không cần bug nào cả — bảng giá MẶC ĐỊNH
 * (`0949_seed_bang_gia_mac_dinh`) khai `unit_price = 0` cho `vad.audio_sec`,
 * `speaker_verify.audio_sec` và hai vế `stt`, còn `billing.rate_usage()` chỉ lọc
 * `qty > 0` chứ không lọc `amount > 0`. Mọi phiên voice vì thế đều sinh dòng
 * `rated_usage` tiền 0, và `sum(amount)` của riêng chúng về tới FE là `"0E-10"`.
 *
 * Trước bản vá, cả năm hàm dưới đây ném `SyntaxError: Cannot convert 0E-10 to a
 * BigInt` và làm sập nguyên màn `/usage` — không phải hiện sai một con số.
 */
describe('Tien ở ký hiệu mũ', () => {
  it('tien() đọc "0E-10" ra 0, không ném', () => {
    expect(tien('0E-10')).toBe('0')
  })

  it('tienDay() đọc "0E-10" ra 0,0000 ₫', () => {
    expect(tienDay('0E-10')).toBe('0,0000 ₫')
  })

  it('congTien() cộng được dòng mũ lẫn với dòng thường', () => {
    expect(congTien(['0E-10', '9000.0000000000'])).toBe('9000.0000000000')
  })

  it('soSanhTien() xếp "0E-10" ngang "0"', () => {
    expect(soSanhTien('0E-10', '0')).toBe(0)
  })

  it('chiaTien() chia được toán hạng dạng mũ', () => {
    expect(chiaTien('0E-10', 31)).toBe('0.0000000000')
  })

  /**
   * Bẫy ngay cạnh: mũ âm KHÁC 0 phải giữ đúng ĐỘ LỚN. Một phép vá chỉ bắt riêng
   * chuỗi `'0E-10'` sẽ để `'1E-10'` lọt xuống `veBigInt()`, ở đó `padEnd` biến
   * `'1'` thành `1` nguyên đồng — sai gấp 10^10 lần và sai IM LẶNG, đúng lớp lỗi
   * mà docstring `chiaTien()` đã ghi.
   */
  it('mũ âm khác 0 giữ đúng độ lớn — "1E-10" là một phần mười tỷ, không phải 1', () => {
    expect(soSanhTien('1E-10', '0')).toBe(1)
    expect(soSanhTien('1E-10', '1')).toBe(-1)
    expect(congTien(['1E-10', '1E-10'])).toBe('0.0000000002')
  })
})
