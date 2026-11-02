/** Cách hiện số ở chế độ xem của hồ sơ dự án: số mono, đơn vị đứng sau, số tiền lớn quy ra tỷ, triệu. */
import { so } from '@/lib/dinhDang'

function mono(n: number | string) {
  return <span className="font-mono tabular-nums">{typeof n === 'number' ? so(n) : n}</span>
}

function decimal2(n: number): string {
  return n.toLocaleString('vi-VN', { maximumFractionDigits: 2 })
}

function sub(text: string) {
  return <span className="block text-phu text-muted-2">{text}</span>
}

export const plainNumber = (n: number) => mono(n)

export const percent = (n: number) => <>{mono(n)}%</>

export const areaWithHectare = (n: number) => (
  <>
    {mono(n)} m²{n >= 10_000 && sub(`khoảng ${decimal2(n / 10_000)} ha`)}
  </>
)

export const vndLarge = (n: number) =>
  n >= 1_000_000_000 ? <>{mono(decimal2(n / 1_000_000_000))} tỷ đồng</> : <>{mono(n)} đồng</>

export const priceBillion = (n: number) =>
  n >= 1_000_000_000 ? (
    <>
      {mono(decimal2(n / 1_000_000_000))} tỷ đồng
      <span className="block text-phu text-muted-2">{mono(n)} đ</span>
    </>
  ) : (
    <>{mono(n)} đồng</>
  )

export const pricePerM2 = (n: number) =>
  n >= 1_000_000 ? (
    <>
      {mono(decimal2(n / 1_000_000))} triệu/m²
      <span className="block text-phu text-muted-2">{mono(n)} đ/m²</span>
    </>
  ) : (
    <>{mono(n)} đ/m²</>
  )
