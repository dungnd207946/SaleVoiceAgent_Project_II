/**
 * Chia 12 kỹ năng ra hai tab là tầng HIỂN THỊ (spec 2026-08-07 §3.2). Hai bài
 * này canh hai cách nó mục ruỗng: (1) một tên trong KY_NANG_CHUNG bị backend đổi
 * mà không ai hay — hằng số trỏ vào hư không, kỹ năng đó lặng lẽ rơi sang tab
 * BĐS; (2) hai tab không chia trọn sổ — một kỹ năng biến mất khỏi giao diện.
 */
import { describe, expect, it } from 'vitest'
import { KY_NANG_CHUNG, KY_NANG_TAB_BDS, KY_NANG_TAB_CHUNG } from '../src/features/agent/kyNang'
import { MUOI_HAI_KY_NANG } from '../src/lib/tools'

describe('chia kỹ năng ra tab', () => {
  it('mỗi tên trong KY_NANG_CHUNG tồn tại trong sổ kỹ năng', () => {
    const ten = new Set(MUOI_HAI_KY_NANG.map((k) => k.ten))
    for (const t of KY_NANG_CHUNG) expect(ten.has(t), `'${t}' không có trong sổ`).toBe(true)
  })

  it('hai tab chia trọn sổ, không sót không trùng', () => {
    expect(KY_NANG_TAB_CHUNG.length + KY_NANG_TAB_BDS.length).toBe(MUOI_HAI_KY_NANG.length)
    const tenBds = new Set(KY_NANG_TAB_BDS.map((k) => k.ten))
    expect(KY_NANG_TAB_CHUNG.filter((k) => tenBds.has(k.ten))).toEqual([])
  })

  it('3 kỹ năng chung đúng như spec đã chốt', () => {
    expect([...KY_NANG_CHUNG].sort()).toEqual(['escalate', 'kb_search', 'update_customer'])
  })
})
