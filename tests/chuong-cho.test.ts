import { describe, expect, it } from 'vitest'
import { coTieng, KEU_S, lichChuong, NGHI_S, TOI_DA_S } from '@/features/platform/chuongCho'

describe('lichChuong — nhịp tút chờ bắt máy', () => {
  it('kêu 1s · nghỉ 4s, tiếng đầu bắt đầu NGAY', () => {
    expect(lichChuong(10, 12)).toEqual([
      [10, 11],
      [15, 16],
      [20, 21],
    ])
    expect(KEU_S + NGHI_S).toBe(5)
  })
  it('tiếng cuối bị cắt đúng mốc tối đa, không kêu quá', () => {
    const lich = lichChuong(0, 5.5)
    expect(lich.at(-1)).toEqual([5, 5.5])
  })
  it('mặc định giới hạn TOI_DA_S', () => {
    const lich = lichChuong(0)
    expect(lich.at(-1)![1]).toBeLessThanOrEqual(TOI_DA_S)
    expect(lich).toHaveLength(Math.ceil(TOI_DA_S / (KEU_S + NGHI_S)))
  })
})

describe('coTieng — khung im lặng không tắt chuông', () => {
  it('khung toàn 0 / nhiễu nền rất nhỏ ⇒ chưa có tiếng', () => {
    expect(coTieng(new Int16Array(480))).toBe(false)
    expect(coTieng(new Int16Array(480).fill(30))).toBe(false)
    expect(coTieng(new Int16Array(0))).toBe(false)
  })
  it('khung có tiếng nói ⇒ có tiếng', () => {
    expect(coTieng(new Int16Array(480).fill(3000))).toBe(true)
  })
})
