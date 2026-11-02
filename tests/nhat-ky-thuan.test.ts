/**
 * Phần THUẦN của màn Nhật ký — không DOM: dựng URL request, cộng ngày, hiển thị
 * người/chi tiết, và bộ lọc của fake MSW (fake CÓ xử lý tham số để test màn kiểm
 * được hành vi thật, cùng lý do `features/realestate/msw.ts`).
 */
import { describe, expect, it } from 'vitest'
import {
  LOC_MAC_DINH,
  SO_MOI_TRANG,
  congMotNgay,
  duongNhatKy,
} from '../src/features/platform/nhatKy'
import { tenNguoi, tomTatChiTiet } from '../src/features/platform/hienNhatKy'
import { NHAT_KY_GIA, locNhatKyGia } from '../src/features/platform/mswNhatKy'
import { tienToCua } from '../src/features/platform/so-hanh-dong'
import type { DongNhatKy } from '../src/features/platform/nhatKy'

function thamSo(duong: string): URLSearchParams {
  return new URL(duong, 'http://x').searchParams
}

describe('duongNhatKy', () => {
  it('mặc định: chỉ limit, KHÔNG có may/nhom/from/to', () => {
    const p = thamSo(duongNhatKy(LOC_MAC_DINH))
    expect(p.get('limit')).toBe(String(SO_MOI_TRANG))
    expect([...p.keys()]).toEqual(['limit'])
  })
  it('nhóm → danh sách tiền tố cách nhau dấu phẩy', () => {
    const p = thamSo(duongNhatKy({ ...LOC_MAC_DINH, nhom: 'thanh-vien' }))
    expect(p.get('nhom')).toBe('thanh_vien,user,role,owner')
  })
  it('«đến hết ngày D» gửi to = D + 1 (cận trên MỞ của API)', () => {
    const p = thamSo(duongNhatKy({ ...LOC_MAC_DINH, tu: '2026-08-01', denHet: '2026-08-31' }))
    expect(p.get('from')).toBe('2026-08-01')
    expect(p.get('to')).toBe('2026-09-01')
  })
  it('may=true và cursor', () => {
    const p = thamSo(duongNhatKy({ ...LOC_MAC_DINH, may: true }, 'abc'))
    expect(p.get('may')).toBe('true')
    expect(p.get('cursor')).toBe('abc')
  })
  it('congMotNgay qua cuối tháng/năm', () => {
    expect(congMotNgay('2026-02-28')).toBe('2026-03-01')
    expect(congMotNgay('2026-12-31')).toBe('2027-01-01')
  })
})

describe('tenNguoi / tomTatChiTiet', () => {
  it('các actor đặc biệt, người đã xoá, actor lạ', () => {
    expect(tenNguoi({ actorId: 'u_x', actorTen: 'Hải Đỗ' })).toBe('Hải Đỗ')
    expect(tenNguoi({ actorId: 'agent', actorTen: null })).toBe('Agent')
    expect(tenNguoi({ actorId: 'platform_admin', actorTen: null })).toBe('NobleX')
    expect(tenNguoi({ actorId: '', actorTen: null })).toBe('Hệ thống')
    expect(tenNguoi({ actorId: 'cron', actorTen: null })).toBe('Hệ thống')
    expect(tenNguoi({ actorId: 'ingest', actorTen: null })).toBe('Cổng nạp')
    expect(tenNguoi({ actorId: 'ingest_token:12', actorTen: null })).toBe('Cổng nạp')
    expect(tenNguoi({ actorId: 'token:5', actorTen: null })).toBe('Cổng nạp')
    expect(tenNguoi({ actorId: 'u_da_xoa', actorTen: null })).toBe('u_da_xoa')
    expect(tenNguoi({ actorId: 'la_hoac_moi', actorTen: null })).toBe('la_hoac_moi')
  })
  it('khoá: giá trị · mảng nối phẩy · object lồng JSON · cắt 120 ký tự', () => {
    const t = tomTatChiTiet({ project_code: 'NT2', truong: ['name', 'price'], meta: { a: 1 } })
    expect(t.dayDu).toBe('project_code: NT2 · truong: name, price · meta: {"a":1}')
    expect(t.ngan).toBe(t.dayDu)
    const dai = tomTatChiTiet({ x: 'a'.repeat(200) })
    expect(dai.ngan.length).toBe(120)
    expect(dai.ngan.endsWith('…')).toBe(true)
    expect(dai.dayDu.length).toBeGreaterThan(120)
    expect(tomTatChiTiet({})).toEqual({ ngan: '', dayDu: '' })
  })
})

describe('locNhatKyGia — fake xử lý tham số như BE', () => {
  const p = (s: string) => new URLSearchParams(s)
  it('mặc định ẩn agent; may=true gộp', () => {
    expect(
      locNhatKyGia(NHAT_KY_GIA, p('limit=100')).items.every((d) => d.actorId !== 'agent'),
    ).toBe(true)
    expect(
      locNhatKyGia(NHAT_KY_GIA, p('limit=100&may=true')).items.some((d) => d.actorId === 'agent'),
    ).toBe(true)
  })
  it('nhom lọc theo tiền tố', () => {
    const r = locNhatKyGia(NHAT_KY_GIA, p('limit=100&nhom=kb,ingest'))
    expect(r.items.length).toBeGreaterThan(0)
    expect(r.items.every((d) => ['kb', 'ingest'].includes(tienToCua(d.hanhDong)))).toBe(true)
  })
  it('phân trang: limit+cursor đi hết không trùng không sót', () => {
    const tatCa = locNhatKyGia(NHAT_KY_GIA, p('limit=100')).items.map((d) => d.id)
    const thay: number[] = []
    let cursor: string | null = null
    for (let i = 0; i < 20; i++) {
      const r = locNhatKyGia(NHAT_KY_GIA, p(`limit=7${cursor ? `&cursor=${cursor}` : ''}`))
      thay.push(...r.items.map((d) => d.id))
      cursor = r.nextCursor
      if (!cursor) break
    }
    expect(thay).toEqual(tatCa)
  })
  it('from/to theo ngày VN, to mở', () => {
    // Dựng 3 hàng tự tạo thay vì đào NHAT_KY_GIA: mốc UTC lệch 7h cần chính xác
    // tới từng phút để nằm hai bên lằn ranh ngày VN.
    const hangTuTao: readonly DongNhatKy[] = [
      {
        id: 1,
        luc: '2026-08-20T16:59:00Z',
        hanhDong: 'kb.upload',
        actorId: 'u_x',
        actorTen: 'X',
        actorEmail: null,
        chiTiet: {},
      },
      {
        id: 2,
        luc: '2026-08-20T17:00:00Z',
        hanhDong: 'kb.upload',
        actorId: 'u_x',
        actorTen: 'X',
        actorEmail: null,
        chiTiet: {},
      },
      {
        id: 3,
        luc: '2026-08-21T16:59:00Z',
        hanhDong: 'kb.upload',
        actorId: 'u_x',
        actorTen: 'X',
        actorEmail: null,
        chiTiet: {},
      },
    ]
    const ngay20 = locNhatKyGia(hangTuTao, p('limit=100&from=2026-08-20&to=2026-08-21'))
    expect(ngay20.items.map((d) => d.id)).toEqual([1])
    const ngay21 = locNhatKyGia(hangTuTao, p('limit=100&from=2026-08-21&to=2026-08-22'))
    expect(ngay21.items.map((d) => d.id).sort()).toEqual([2, 3])
  })
  it('dữ liệu giả: mới nhất trước, có đủ ba loại actor đặc biệt', () => {
    const luc = NHAT_KY_GIA.map((d) => d.luc)
    expect(luc).toEqual([...luc].sort().reverse())
    expect(NHAT_KY_GIA.some((d) => d.actorId === 'agent')).toBe(true)
    expect(NHAT_KY_GIA.some((d) => d.actorId === '')).toBe(true)
    expect(NHAT_KY_GIA.some((d) => d.actorTen === null && d.actorId.startsWith('u_'))).toBe(true)
  })
})
