/**
 * Hai quyết định của đợt quieter 05/10 mà không bài nào khác canh.
 *
 * ① Trang `/` in kỹ năng TỪ SỔ (`lib/tools.ts`), không chép tay: bản chép tay cũ
 *    còn «12 việc» và tên đã nghỉ sau đợt gộp tool 09/2026. `analyze_projects`
 *    không lên trang công khai (sổ ghi chưa an toàn cho tenant thật).
 * ② Nút xoá trong bảng XÁM lúc nghỉ, đỏ chỉ khi rê/focus (người dùng chốt).
 */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { KY_NANG_BDS, KY_NANG_CHUNG, SO_KY_NANG } from '../src/components/landing/duLieuMau'
import { NutIcon } from '../src/components/ui/Bang'
import { MUOI_HAI_KY_NANG } from '../src/lib/tools'

describe('quieter 05/10', () => {
  it('① kỹ năng ở trang `/` = sổ hiện hành, trừ analyze_projects', () => {
    const nhan = new Set(MUOI_HAI_KY_NANG.map((k) => k.nhan))
    const trang = [...KY_NANG_CHUNG.map((k) => k.nhan), ...KY_NANG_BDS]
    expect(trang.filter((n) => !nhan.has(n))).toEqual([])
    expect(trang).not.toContain(MUOI_HAI_KY_NANG.find((k) => k.ten === 'analyze_projects')?.nhan)
    expect(SO_KY_NANG).toBe(MUOI_HAI_KY_NANG.length - 1)
  })

  it('② nút xoá không mang sắc đỏ lúc nghỉ — chỉ sau `hover:`/`focus-visible:`', () => {
    render(<NutIcon icon="trash" nhan="Xoá" phaHuy onClick={() => {}} />)
    const lop = screen.getByRole('button', { name: 'Xoá' }).className.split(/\s+/)
    expect(
      lop.filter((c) => c.includes('badge-alert') && !/^(hover|focus-visible):/.test(c)),
    ).toEqual([])
    expect(lop).toContain('hover:text-badge-alert-fg')
  })
})
