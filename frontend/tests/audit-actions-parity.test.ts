/**
 * CỔNG PARITY sổ mã hành động nhật ký — BE ↔ FE.
 *
 * Nguồn: `core/nhat_ky_ma.py` của repo backend → artefact `contracts/audit-actions.json`
 * (copy byte-for-byte, cùng cơ chế `actions.json`). FE dịch mã ra tiếng Việt ở
 * `features/platform/so-hanh-dong.ts`. Thêm điểm ghi mới ở BE mà quên nhãn ở đây
 * ⇒ bài (b) đỏ; giữ nhãn cho mã đã bỏ ⇒ bài (c) đỏ; mã có tiền tố mới rơi ra ngoài
 * mọi bộ lọc ⇒ bài (d) đỏ.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import {
  NHAN_HANH_DONG,
  NHOM_LOC,
  nhanHanhDong,
  tienToCua,
} from '../src/features/platform/so-hanh-dong'

const DUONG_JSON = resolve(import.meta.dirname, '../contracts/audit-actions.json')

function maTuArtefact(): string[] {
  return JSON.parse(readFileSync(DUONG_JSON, 'utf-8')).actions
}

describe('cổng parity sổ mã hành động nhật ký', () => {
  it('(a) artefact không rỗng', () => {
    // Đếm TRƯỚC khi so: tập rỗng ⊆ mọi tập, không đếm thì artefact rỗng làm cổng xanh mãi.
    expect(maTuArtefact().length).toBeGreaterThanOrEqual(40)
  })

  it('(b) mọi mã trong artefact có nhãn tiếng Việt', () => {
    const thieu = maTuArtefact().filter((ma) => !(ma in NHAN_HANH_DONG))
    expect(thieu, 'thêm nhãn vào so-hanh-dong.ts').toEqual([])
  })

  it('(c) sổ FE không có mã lạ ngoài artefact', () => {
    const co = new Set(maTuArtefact())
    const la = Object.keys(NHAN_HANH_DONG).filter((ma) => !co.has(ma))
    expect(la, 'mã không còn ở BE — bỏ nhãn').toEqual([])
  })

  it('(d) tiền tố của mọi mã thuộc ĐÚNG MỘT nhóm lọc', () => {
    for (const ma of maTuArtefact()) {
      const nhom = NHOM_LOC.filter((n) => n.tienTo.includes(tienToCua(ma)))
      expect(nhom.length, `mã ${ma} (tiền tố ${tienToCua(ma)})`).toBe(1)
    }
  })

  it('(e) nhãn không trùng mã, không rỗng', () => {
    for (const [ma, nhan] of Object.entries(NHAN_HANH_DONG)) {
      expect(nhan.trim().length, ma).toBeGreaterThan(0)
      expect(nhan, ma).not.toBe(ma)
    }
  })

  it('nhanHanhDong rơi về mã thô khi chưa có nhãn', () => {
    expect(nhanHanhDong('kb.upload')).toBe('Tải lên tài liệu kiến thức')
    expect(nhanHanhDong('x.y')).toBe('x.y')
  })
})
