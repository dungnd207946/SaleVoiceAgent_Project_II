import { describe, expect, it } from 'vitest'
import { checkedTime } from '../src/features/conflicts/time'

describe('giờ kiểm tra lần cuối', () => {
  const now = new Date(2026, 9, 14, 16, 0)

  it('hôm nay, hôm qua, ngày khác', () => {
    expect(checkedTime(new Date(2026, 9, 14, 14, 32).toISOString(), now)).toBe('14:32 hôm nay')
    expect(checkedTime(new Date(2026, 9, 13, 9, 10).toISOString(), now)).toBe('09:10 hôm qua')
    expect(checkedTime(new Date(2026, 9, 8, 16, 5).toISOString(), now)).toBe('08/10 16:05')
  })
})
