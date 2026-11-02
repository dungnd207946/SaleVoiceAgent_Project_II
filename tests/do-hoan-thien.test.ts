/**
 * Cổng CHẶN phát hành `thieuTruongDuAn` — năm trường `BAT_BUOC.project`.
 * (Thước mềm `doHoanThien` n/12 đã gỡ 2026-10-06: không màn nào dùng.)
 */
import { describe, expect, it } from 'vitest'
import { BAT_BUOC, thieuTruongDuAn } from '../src/features/realestate/completeness'

const DU = Object.fromEntries(BAT_BUOC.project.map((t) => [t, 'x'])) as Record<
  (typeof BAT_BUOC.project)[number],
  unknown
>

describe('thieuTruongDuAn', () => {
  it('đủ năm trường cứng thì cho phát hành', () => {
    expect(thieuTruongDuAn(DU)).toEqual([])
  })

  it('thiếu trường cứng thì nói đúng trường đó', () => {
    expect(thieuTruongDuAn({ ...DU, overview: '' })).toEqual(['overview'])
  })
})
