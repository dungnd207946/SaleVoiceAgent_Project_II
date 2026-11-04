import { describe, expect, it } from 'vitest'
import {
  CAY,
  banDoc,
  boCucCay,
  canh,
  docDe,
  mauTiLe,
  nhanCanh,
  tenNut,
} from '@/features/kich-ban/logic'
import { FAKE_KICH_BAN } from '@/features/kich-ban/msw'

const s = (tiLeDat: number | null, daCham: number) => ({
  soLuot: daCham,
  daCham,
  dat: 0,
  tiLeDat,
  thieuDuLieu: 0,
  hayThieu: [],
  hayPham: [],
  jevSo: 0,
  jevKhop: null,
})

describe('mauTiLe', () => {
  it('ngưỡng', () => {
    expect(mauTiLe(s(0.8, 10), false)).toBe('xanh')
    expect(mauTiLe(s(0.79, 10), false)).toBe('vang')
    expect(mauTiLe(s(0.6, 10), false)).toBe('vang')
    expect(mauTiLe(s(0.59, 10), false)).toBe('do')
  })
  it('xám khi < 5 lượt chấm, không có số đo, hoặc nháp', () => {
    expect(mauTiLe(s(1, 4), false)).toBe('xam')
    expect(mauTiLe(undefined, false)).toBe('xam')
    expect(mauTiLe(s(1, 50), true)).toBe('xam')
  })
})

describe('bản đồ', () => {
  it('mỗi cặp tiep một cạnh, nhãn tiếng Việt', () => {
    const e = canh(FAKE_KICH_BAN.nodes)
    expect(e).toContainEqual(
      expect.objectContaining({
        source: 'che_dat',
        target: 'che_dat_downsell',
        label: 'gặp lần 2',
      }),
    )
    expect(e).toContainEqual(
      expect.objectContaining({
        source: 'chot',
        target: 'chuyen_that',
        label: 'gặp lần 2',
      }),
    )
    expect(nhanCanh('khoa_moi_chua_co')).toBe('khoa moi chua co')
  })

  it('sơ đồ cây: mỗi tình huống một hàng, cùng nhóm liền nhau theo thứ tự hành trình', () => {
    const bc = boCucCay(FAKE_KICH_BAN.nodes)
    const ids = FAKE_KICH_BAN.nodes.map((n) => n.id)
    expect(Object.keys(bc.nut).sort()).toEqual([...ids].sort())
    expect(bc.nhom.map((g) => g.nhom)).toEqual(['mo_dau', 'phan_doi', 'chot', 'chuyen_nguoi'])
    // hàng đi xuống đúng thứ tự nhóm, không hai tình huống chung một hàng
    const thuTu = bc.nhom.flatMap((g) =>
      FAKE_KICH_BAN.nodes.filter((n) => n.nhom === g.nhom).map((n) => bc.nut[n.id]!.y),
    )
    expect(thuTu).toEqual([...thuTu].sort((a, b) => a - b))
    expect(new Set(thuTu).size).toBe(ids.length)
    // nhóm đứng giữa các con của nó; gốc đứng giữa cả cây
    const pd = bc.nhom.find((g) => g.nhom === 'phan_doi')!
    expect(pd.y).toBe((bc.nut.che_dat!.y + bc.nut.che_dat_downsell!.y) / 2)
    expect(pd.so).toBe(2)
    expect(bc.gocY).toBe((Math.min(...thuTu) + Math.max(...thuTu)) / 2)
    // khung bao trọn nhãn dài nhất
    for (const p of Object.values(bc.nut)) {
      expect(p.cuoi).toBeGreaterThan(CAY.xNut)
      expect(p.cuoi).toBeLessThan(bc.rong)
    }
    expect(bc.cao).toBe(Math.max(...thuTu))
  })

  it('hậu tố «· khác mẫu» được tính vào bề ngang nhãn — mũi tên chuyển tiếp bắt đầu SAU nó', () => {
    const tron = boCucCay(FAKE_KICH_BAN.nodes)
    const coDuoi = boCucCay(FAKE_KICH_BAN.nodes, { chot: ' · khác mẫu' })
    expect(coDuoi.nut.chot!.cuoi).toBeGreaterThanOrEqual(tron.nut.chot!.cuoi + 80)
    expect(coDuoi.nut.che_dat!.cuoi).toBe(tron.nut.che_dat!.cuoi)
  })

  it('JSON cũ chưa có tên thì hiện mã', () => {
    expect(tenNut({ id: 'che_dat' })).toBe('che_dat')
    expect(tenNut({ id: 'che_dat', ten: 'Khách chê đắt' })).toBe('Khách chê đắt')
  })
})

describe('docDe — chữ viết cho LLM thành chữ cho người xem', () => {
  const ten = { che_dat: 'Khách chê đắt', chuyen_that: 'Chuyển cho chuyên viên' }

  it('tên tool (kèm tham số) thành tên kỹ năng', () => {
    expect(
      docDe("khách nêu mức → update_customer(budget) + search_units(scope='in_project')", ten),
    ).toBe('khách nêu mức → «Ghi nhận thông tin khách» + «Tìm & gợi ý căn»')
  })

  it('mã nút thành tên nút', () => {
    expect(docDe('chê đắt là che_dat; đòi cam kết là chuyen_that', ten)).toBe(
      'chê đắt là «Khách chê đắt»; đòi cam kết là «Chuyển cho chuyên viên»',
    )
  })

  it('từ kỹ thuật thành tiếng Việt', () => {
    expect(docDe('chỉ từ kb, nói số liệu không nằm trong kết quả tool', ten)).toBe(
      'chỉ từ tài liệu, nói số liệu không nằm trong kết quả tra cứu',
    )
    expect(docDe('find_project not_found → giữ NGUYÊN filter_sql', ten)).toBe(
      '«Nhận diện tên dự án» không tìm thấy → giữ NGUYÊN bộ lọc',
    )
  })

  it('chữ tiếng Việt thường không bị đụng', () => {
    const cau = 'chốt MỘT lời dẫn CÓ/KHÔNG, không mở đầu bằng "nhưng"'
    expect(docDe(cau, ten)).toBe(cau)
  })
})

describe('banDoc — chữ cho người đọc', () => {
  const ten = { che_dat_downsell: 'Chê đắt lần hai' }
  const goc = FAKE_KICH_BAN.nodes.find((n) => n.id === 'che_dat')!

  it('có hien đủ dòng thì dùng hien, và tra ngược chữ gốc ra chữ hien', () => {
    const d = banDoc(goc, ten)
    expect(d.dauHieu).toEqual(goc.hien!.dau_hieu)
    expect(d.khiThieu).toBe(goc.hien!.khi_thieu)
    expect(d.dich(goc.cam[2]!)).toBe(goc.hien!.cam![2])
    expect(d.dich('chuỗi classifier tự viết, kb')).toBe('chuỗi classifier tự viết, tài liệu')
  })

  it('hien lệch số dòng hoặc vắng thì rơi về docDe từng mục', () => {
    const d = banDoc({ ...goc, hien: { ...goc.hien, lam: ['một dòng'] } }, ten)
    expect(d.lam).toEqual(goc.lam.map((s) => docDe(s, ten)))
    expect(d.cam).toEqual(goc.hien!.cam)
    expect(banDoc({ ...goc, hien: {} }, ten).khiThieu).toBe(docDe(goc.khi_thieu, ten))
  })
})
