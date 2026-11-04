export type TenKy = 'thang-nay' | 'thang-truoc' | '7-ngay' | '30-ngay'

const iso = (d: Date) => d.toISOString().slice(0, 10)

/**
 * Kỳ → khoảng `from`/`to` dạng `YYYY-MM-DD` (BE khai `date`, không datetime).
 * `to` là mốc NỬA MỞ: BE lọc `occurred_at < to`, nên «tháng này» phải trả ngày
 * đầu tháng SAU, không phải hôm nay — trả hôm nay là cắt mất usage của hôm nay.
 */
export function giaiMaKy(
  ky: TenKy,
  homNay = new Date(),
): { from: string; to: string; dangChay: boolean } {
  const y = homNay.getUTCFullYear()
  const m = homNay.getUTCMonth()
  switch (ky) {
    case 'thang-nay':
      return {
        from: iso(new Date(Date.UTC(y, m, 1))),
        to: iso(new Date(Date.UTC(y, m + 1, 1))),
        dangChay: true,
      }
    case 'thang-truoc':
      return {
        from: iso(new Date(Date.UTC(y, m - 1, 1))),
        to: iso(new Date(Date.UTC(y, m, 1))),
        dangChay: false,
      }
    case '7-ngay':
    case '30-ngay': {
      const n = ky === '7-ngay' ? 7 : 30
      const den = new Date(Date.UTC(y, m, homNay.getUTCDate() + 1))
      const tu = new Date(Date.UTC(y, m, homNay.getUTCDate() + 1 - n))
      return { from: iso(tu), to: iso(den), dangChay: true }
    }
  }
}
