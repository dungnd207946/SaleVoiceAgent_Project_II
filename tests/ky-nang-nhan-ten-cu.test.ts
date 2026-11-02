/**
 * `nhanCua()` phải trả NHÃN NGHIỆP VỤ cho cả tên tool đã nghỉ.
 *
 * `MUOI_HAI_KY_NANG` là sổ HIỆN HÀNH — cổng parity ép nó khớp
 * `contracts/tools.json` từng dòng. Nhưng `escalations.missing_data_tool` là
 * NHẬT KÝ: hàng do agent bản trước-merge ghi mang tên cũ và nằm đó vĩnh viễn.
 * Không nối hai thứ đó thì màn /chuyen-sale in chữ `check_inventory` cho sale
 * đọc — đúng thứ AG_01 §II.3 cấm, và đã xảy ra trên màn thật.
 */
import { describe, expect, it } from 'vitest'

import { MUOI_HAI_KY_NANG, TEN_DA_NGHI, nhanCua } from '../src/lib/tools'

describe('nhãn kỹ năng cho tên đã nghỉ', () => {
  it('check_inventory ra nhãn của tool đã nuốt nó', () => {
    expect(nhanCua('check_inventory')).toBe('Thống kê & tồn kho')
  })

  it('mọi tên đã nghỉ đều ra nhãn, không tên nào rơi về chuỗi thô', () => {
    for (const cu of Object.keys(TEN_DA_NGHI)) {
      expect(nhanCua(cu)).not.toBe(cu)
    }
  })

  it('mỗi tên đã nghỉ trỏ tới một kỹ năng CÓ THẬT trong sổ hiện hành', () => {
    // Không có bài này thì một lần đổi tên tool sau đây làm bảng trỏ vào hư
    // không, và `nhanCua` lặng lẽ quay về hiện tên hàm.
    const co = new Set(MUOI_HAI_KY_NANG.map((k) => k.ten))
    for (const [cu, moi] of Object.entries(TEN_DA_NGHI)) {
      expect(co.has(moi), `${cu} → ${moi} không còn trong sổ`).toBe(true)
    }
  })

  it('tên đã nghỉ KHÔNG được nằm trong sổ hiện hành', () => {
    // Nằm trong đó là nó lại hiện ra màn Agent Studio như một kỹ năng bật được,
    // và cổng parity với `contracts/tools.json` sẽ đỏ.
    const co = new Set(MUOI_HAI_KY_NANG.map((k) => k.ten))
    for (const cu of Object.keys(TEN_DA_NGHI)) {
      expect(co.has(cu), `${cu} vừa nghỉ vừa còn trong sổ`).toBe(false)
    }
  })

  it('không nhãn nào trông như tên hàm', () => {
    // Cổng chung, không chỉ cho ba tên hôm nay: một tool MỚI mà FE chưa biết
    // cũng không được lọt ra màn dưới dạng `snake_case`.
    for (const ten of [...MUOI_HAI_KY_NANG.map((k) => k.ten), ...Object.keys(TEN_DA_NGHI)]) {
      expect(nhanCua(ten)).not.toMatch(/_/)
    }
    expect(nhanCua('mot_tool_tuong_lai')).not.toMatch(/_/)
  })
})
