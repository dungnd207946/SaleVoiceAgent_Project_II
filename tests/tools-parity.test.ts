/**
 * Nửa FE của cổng parity 13 kỹ năng. Nửa BE là
 * `odyssey-portal-backend/tests/api/test_contracts.py`.
 *
 * Đọc `contracts/tools.json` — ARTEFACT backend sinh rồi copy sang — chứ không
 * đọc file Python. Hai repo riêng, và artefact là thứ duy nhất đi qua được ranh
 * giới đó.
 *
 * Vì sao cổng này đáng có: prompt của agent dạy gọi những kỹ năng đang bật, còn
 * màn Agent Studio quyết định bật cái nào. Lệch nhau nghĩa là người dùng tắt một
 * kỹ năng mà agent vẫn hứa làm nó với khách — AG_01 §6 gọi đó là lỗi chặn ship.
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { MUOI_HAI_KY_NANG, PHU_THUOC } from '../src/lib/tools'

const DUONG_JSON = resolve(dirname(fileURLToPath(import.meta.url)), '../contracts/tools.json')

interface Artefact {
  tools: Array<{ ten: string; nhan: string; moTa: string }>
  phuThuoc: Record<string, string[]>
}

function docArtefact(): Artefact {
  return JSON.parse(readFileSync(DUONG_JSON, 'utf-8')) as Artefact
}

describe('parity 11 kỹ năng BE ↔ FE', () => {
  it('artefact có đúng 11 kỹ năng', () => {
    // Đếm TRƯỚC khi so: tập rỗng so tập rỗng thì bằng nhau, nên không có phép
    // đếm này thì một artefact hỏng làm cổng xanh vĩnh viễn.
    expect(docArtefact().tools).toHaveLength(11)
  })

  it('tools.ts có đúng 11 kỹ năng', () => {
    expect(MUOI_HAI_KY_NANG).toHaveLength(11)
  })

  it('cùng tên, cùng THỨ TỰ', () => {
    // Thứ tự là thứ tự nghiệp vụ và cũng là thứ tự toggle trên màn hình — so tập
    // hợp thôi thì đảo thứ tự lọt qua, và người dùng thấy một danh sách lộn xộn.
    expect(MUOI_HAI_KY_NANG.map((k) => k.ten)).toEqual(docArtefact().tools.map((t) => t.ten))
  })

  it('cùng nhãn nghiệp vụ', () => {
    const tuArtefact = Object.fromEntries(docArtefact().tools.map((t) => [t.ten, t.nhan]))
    const tuFe = Object.fromEntries(MUOI_HAI_KY_NANG.map((k) => [k.ten, k.nhan]))

    expect(tuFe).toEqual(tuArtefact)
  })

  it('cùng bảng phụ thuộc', () => {
    // Lệch bảng này nghĩa là FE cảnh báo một đằng còn BE từ chối một nẻo.
    expect(PHU_THUOC).toEqual(docArtefact().phuThuoc)
  })
})
