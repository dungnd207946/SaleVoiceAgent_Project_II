import { StrictMode } from 'react'
import { describe, expect, it } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useLuuTungO } from '../src/features/realestate/useLuuTungO'

type Props = { banDau: { bedrooms: number | null }; khoa: unknown }

describe('useLuuTungO dưới StrictMode', () => {
  it('bản ghi tải xong thì state nhận giá trị của nó', () => {
    const luu = async () => undefined
    const dau: Props = { banDau: { bedrooms: null }, khoa: 'moi' }
    const { result, rerender } = renderHook(
      ({ banDau, khoa }: Props) => useLuuTungO(banDau, luu, khoa),
      {
        wrapper: StrictMode,
        initialProps: dau,
      },
    )
    rerender({ banDau: { bedrooms: 3 }, khoa: 41 })
    expect(result.current.v.bedrooms).toBe(3)
  })
})
