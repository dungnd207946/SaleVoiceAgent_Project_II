import { afterEach, describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { BP, useKhoManHinh } from '../src/lib/khoManHinh'
import { boGiaLap, doiRong, giaLapManHinh } from './man-hinh'

afterEach(boGiaLap)

describe('useKhoManHinh', () => {
  it('không có matchMedia (jsdom trần) ⇒ desktop — giữ nguyên mọi test cũ', () => {
    expect(window.matchMedia).toBeUndefined()
    expect(renderHook(() => useKhoManHinh()).result.current).toBe('desktop')
  })

  it.each([
    [360, 'mobile'],
    [BP.md - 1, 'mobile'],
    [BP.md, 'tablet'],
    [BP.lg - 1, 'tablet'],
    [BP.lg, 'desktop'],
    [1440, 'desktop'],
  ] as const)('%ipx ⇒ %s', (rong, mong) => {
    giaLapManHinh(rong)
    expect(renderHook(() => useKhoManHinh()).result.current).toBe(mong)
  })

  it('đổi bề rộng ⇒ render lại với tầng mới', () => {
    giaLapManHinh(1440)
    const { result } = renderHook(() => useKhoManHinh())
    act(() => doiRong(375))
    expect(result.current).toBe('mobile')
    act(() => doiRong(900))
    expect(result.current).toBe('tablet')
  })
})
