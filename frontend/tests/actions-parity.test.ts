/**
 * CỔNG 3 — 15 nhóm hành động ở BE và FE phải khớp tuyệt đối.
 *
 * Hướng đọc: FE đọc artefact của BE, KHÔNG ngược lại. Nguồn là
 * `core/auth/actions.py` của repo backend vì đó là tầng cưỡng chế thật;
 * `lib/actions.ts` chỉ để ẩn mục nav cho đỡ rối mắt (PQ_01 §BR-Q03).
 *
 * Lệch một tên = một endpoint không ai kiểm, hoặc một mục nav hiện với người
 * không có quyền — và không ai biết tới khi M2b rà lại 18 màn.
 *
 * VÌ SAO ĐỌC JSON CHỨ KHÔNG ĐỌC THẲNG FILE .py: bản trước của cổng này resolve
 * `../../backend/src/portal/core/auth/actions.py` — đường của thời monorepo. Hai
 * repo git riêng thì file đó không tồn tại và cổng đỏ vĩnh viễn. Xem
 * `contracts/README.md`.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { ALL_ACTIONS } from '../src/lib/actions'

const DUONG_JSON = resolve(import.meta.dirname, '../contracts/actions.json')

function docActionTuArtefact(): string[] {
  return JSON.parse(readFileSync(DUONG_JSON, 'utf-8')).actions
}

describe('cổng 3 — parity actions BE ↔ FE', () => {
  it('artefact có đúng 17 nhóm', () => {
    // Đếm TRƯỚC khi so set: set rỗng so với set rỗng thì bằng nhau, nên không có
    // phép đếm này thì một artefact rỗng (`{"actions": []}`) làm cổng xanh vĩnh viễn.
    expect(docActionTuArtefact()).toHaveLength(17)
  })

  it('actions.ts có đúng 17 nhóm', () => {
    expect(ALL_ACTIONS).toHaveLength(17)
  })

  it('hai bên là cùng một tập', () => {
    expect(new Set(docActionTuArtefact())).toEqual(new Set(ALL_ACTIONS))
  })
})
