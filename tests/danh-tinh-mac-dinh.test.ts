import { describe, expect, it } from 'vitest'
import { danhTinhMacDinh, TEN_MAC_DINH } from '../src/features/platform/danhTinhKhach'

describe('danhTinhMacDinh — giá trị điền sẵn của màn Thử agent', () => {
  it('tên thuộc ba tên chốt, SĐT 10 chữ số bắt đầu bằng 0, giới tính nam', () => {
    for (let i = 0; i < 50; i++) {
      const d = danhTinhMacDinh()
      expect(TEN_MAC_DINH).toContain(d['full_name'])
      expect(d['phone']).toMatch(/^0\d{9}$/)
      expect(d['gender']).toBe('nam')
      expect(d['role']).toBeUndefined() // role điền sau, từ danh sách server
    }
  })

  it('phủ được cả ba tên (rand ở hai đầu khoảng)', () => {
    expect(danhTinhMacDinh(() => 0)['full_name']).toBe('Dũng')
    expect(danhTinhMacDinh(() => 0.5)['full_name']).toBe('Dự')
    expect(danhTinhMacDinh(() => 0.999)['full_name']).toBe('Thế')
  })
})
