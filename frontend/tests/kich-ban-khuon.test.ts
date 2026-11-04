import { describe, expect, it } from 'vitest'
import { LoiApi } from '@/lib/http'
import { type NutVao } from '@/features/kich-ban/api'
import {
  chanXoa,
  chuanHoa,
  doDai,
  heThong,
  idBuocMoi,
  idRieng,
  kiemBo,
  kiemNut,
  nhomThem,
  nutTrong,
  phanLoi422,
  soMau,
  thayNut,
  themNut,
  xoaNut,
  type TruongNut,
} from '@/features/kich-ban/khuon'
import { nhanKyNang } from '@/features/kich-ban/logic'
import { FAKE_KICH_BAN, GIOI_HAN_GIA as G, MAU_GIA } from '@/features/kich-ban/msw'

const HT = heThong(FAKE_KICH_BAN.nodes)
const MAU = FAKE_KICH_BAN.nodes.filter((n) => n.lop === 'sale')
const TEN: Record<string, string> = {
  che_dat: 'Khách chê đắt',
  che_dat_downsell: 'Chê đắt lần hai',
  chot: 'Chốt căn',
  chuyen_that: 'Chuyển cho chuyên viên',
  goi_dien_ra: 'Gọi điện cho khách',
}
const nut = (d: Partial<NutVao> = {}): NutVao => ({
  ...nutTrong(),
  id: 'rieng_x',
  ten: 'X',
  nhom: 'phan_doi',
  dau_hieu: ['a'],
  lam: ['b'],
  ...d,
})

describe('doDai', () => {
  it('đếm theo ký tự như len() của Python — emoji là MỘT', () => {
    expect(doDai('a😀')).toBe(2)
    expect('a😀'.length).toBe(3)
    expect(doDai('Chê đắt')).toBe(7)
  })
})

describe('idRieng', () => {
  it('bỏ dấu, chữ thường, gạch dưới', () =>
    expect(idRieng('Chê màu sơn!', new Set())).toBe('rieng_che_mau_son'))
  it('đ thành d', () => expect(idRieng('Đặt cọc', new Set())).toBe('rieng_dat_coc'))
  it('trùng thì thêm hậu tố', () =>
    expect(idRieng('Chê màu sơn', new Set(['rieng_che_mau_son', 'rieng_che_mau_son_2']))).toBe(
      'rieng_che_mau_son_3',
    ))
  it('tên toàn ký hiệu', () => expect(idRieng('!!!', new Set())).toBe('rieng_tinh_huong'))
  it('tên dài vẫn khớp khuôn, kể cả khi thêm hậu tố', () => {
    const ten = 'Đây là một tình huống có cái tên rất là dài dòng'
    const a = idRieng(ten, new Set())
    const b = idRieng(ten, new Set([a]))
    for (const id of [a, b]) {
      expect(id).toMatch(new RegExp(G.khuonIdRieng))
      expect(id).toMatch(new RegExp(G.khuonId))
    }
    expect(b.endsWith('_2')).toBe(true)
  })
})

describe('phép trên bộ', () => {
  it('idBuocMoi lấp chỗ trống nhỏ nhất', () =>
    expect(
      idBuocMoi([
        { id: 'b1', lam: '' },
        { id: 'b3', lam: '' },
      ]),
    ).toBe('b2'))
  it('chuanHoa: strip, bỏ ý rỗng, bỏ bước rỗng', () =>
    expect(
      chuanHoa(
        nut({
          ten: '  X ',
          dau_hieu: [' a ', '', '  '],
          khi_thieu: ' k ',
          buoc: [
            { id: 'b1', lam: ' ' },
            { id: 'b2', lam: ' c' },
          ],
        }),
      ),
    ).toMatchObject({ ten: 'X', dau_hieu: ['a'], khi_thieu: 'k', buoc: [{ id: 'b2', lam: 'c' }] }))
  it('thay / thêm / xoá giữ thứ tự', () => {
    expect(thayNut(MAU_GIA, { ...MAU_GIA[2]!, ten: 'Y' }).map((n) => n.ten)[2]).toBe('Y')
    expect(themNut(MAU_GIA, nut()).at(-1)!.id).toBe('rieng_x')
    expect(xoaNut(MAU_GIA, 'chot').map((n) => n.id)).toEqual([
      'che_dat',
      'che_dat_downsell',
      'goi_dien_ra',
    ])
  })
})

describe('soMau', () => {
  it('giống / khác / riêng / chưa có — theo id + hash', () => {
    const sale = [{ ...MAU[0]!, hash: 'doi' }, MAU[1]!, { ...MAU[2]!, id: 'rieng_x', hash: 'h' }]
    const s = soMau(sale, MAU)
    expect(s.loai).toEqual({ che_dat: 'khac', che_dat_downsell: 'giong', rieng_x: 'rieng' })
    expect(s.chuaCo.map((n) => n.id)).toEqual(['chot', 'goi_dien_ra'])
  })
})

const CA: [TruongNut, Partial<NutVao>, string][] = [
  ['ten', { ten: '' }, 'Chưa có tên tình huống'],
  ['ten', { ten: 'x'.repeat(61) }, 'Tối đa 60 ký tự'],
  ['nhom', { nhom: 'khac' }, 'Chọn một nhóm'],
  ['kenh', { kenh: ['fax'] }, 'Kênh không hợp lệ'],
  ['dau_hieu', { dau_hieu: [] }, 'Cần ít nhất một ý'],
  ['lam', { lam: Array<string>(7).fill('a') }, 'Tối đa 6 ý'],
  ['lam', { lam: ['x'.repeat(201)] }, 'Mỗi ý tối đa 200 ký tự'],
  ['dau_hieu', { dau_hieu: Array<string>(6).fill('x'.repeat(60)) }, 'Tổng tối đa 360 ký tự'],
  ['cam', { cam: Array<string>(6).fill('a') }, 'Tối đa 5 ý'],
  ['cam', { cam: ['x'.repeat(200), 'x'.repeat(121)] }, 'Tổng tối đa 320 ký tự'],
  ['tool', { tool: ['tinh_tra_gop'] }, 'Có kỹ năng không còn dùng được'],
  [
    'tool',
    { tool: ['kb_search', 'booking', 'escalate', 'send_media', 'find_project'] },
    'Tối đa 4 kỹ năng',
  ],
  ['khi_thieu', { khi_thieu: 'x'.repeat(161) }, 'Tối đa 160 ký tự'],
  ['cau_ket', { cau_ket: 'x'.repeat(161) }, 'Tối đa 160 ký tự'],
  [
    'buoc',
    { buoc: Array.from({ length: 7 }, (_, i) => ({ id: `b${i + 1}`, lam: 'a' })) },
    'Tối đa 6 bước',
  ],
  ['buoc', { buoc: [{ id: 'b1', lam: 'x'.repeat(201) }] }, 'Mỗi bước tối đa 200 ký tự'],
  ['lan_2', { lan_2: 'rieng_x' }, 'Không chuyển sang chính nó'],
]

describe('kiemNut — mỗi luật một ca', () => {
  it('nút hợp lệ không lỗi', () => expect(kiemNut(nut(), G)).toEqual({}))
  it('200 ký tự có emoji vẫn hợp lệ (đếm code point)', () =>
    expect(kiemNut(nut({ lam: ['😀'.repeat(200)] }), G)).toEqual({}))
  it.each(CA)('%s', (k, d, cau) => expect(kiemNut(nut(d), G)[k]).toBe(cau))
})

describe('kiemBo — luật cả bộ', () => {
  it('bộ mẫu hợp lệ', () => expect(kiemBo(MAU_GIA, HT, G, TEN)).toEqual([]))
  it('quá số tình huống', () =>
    expect(kiemBo(MAU_GIA, HT, { ...G, maxNut: 3 }, TEN)).toContain('Tối đa 3 tình huống'))
  it('trùng mã với nút hệ thống', () =>
    expect(kiemBo([...MAU_GIA, nut({ id: 'chuyen_that' })], HT, G, TEN)).toContain(
      '«Chuyển cho chuyên viên» trùng mã với một tình huống khác',
    ))
  it('chuyển sang tình huống không còn', () =>
    expect(kiemBo([...MAU_GIA, nut({ lan_2: 'khong_co' })], HT, G, TEN)).toContain(
      '«rieng_x» chuyển sang một tình huống không còn trong kịch bản',
    ))
  it('chỉ-lần-2 mồ côi', () =>
    expect(kiemBo(thayNut(MAU_GIA, { ...MAU_GIA[0]!, lan_2: '' }), HT, G, TEN)).toContain(
      '«Chê đắt lần hai» chỉ dùng khi được chuyển tới, nhưng không tình huống nào chuyển sang nó',
    ))
  it('thiếu tình huống khoá xoá', () =>
    expect(kiemBo(xoaNut(MAU_GIA, 'che_dat'), HT, G, TEN)).toContain(
      'Không được xoá «Khách chê đắt»',
    ))
})

describe('chanXoa', () => {
  it('được xoá khi không ai trỏ tới', () => expect(chanXoa('chot', MAU_GIA, HT, TEN)).toEqual([]))
  it('chặn khi có tình huống chuyển sang nó', () =>
    expect(
      chanXoa('chot', [...MAU_GIA, nut({ id: 'rieng_a', lan_2: 'chot' })], HT, {
        ...TEN,
        rieng_a: 'A',
      }),
    ).toEqual([
      { id: 'rieng_a', cau: '«A» chuyển sang tình huống này khi khách lặp lại — đổi ở «A» trước' },
    ]))
  it('nút HỆ THỐNG chuyển sang nó không chặn — BE chỉ kiểm lan_2 của nút sale', () =>
    expect(chanXoa('chot', MAU_GIA, [{ ...HT[0]!, lan_2: 'chot' }], TEN)).toEqual([]))
  it('chặn khi nó là đường duy nhất tới một tình huống chỉ-lần-2', () =>
    expect(chanXoa('che_dat', MAU_GIA, HT, TEN)).toEqual([
      {
        id: 'che_dat_downsell',
        cau: '«Chê đắt lần hai» chỉ tới được từ tình huống này — xoá «Chê đắt lần hai» hoặc bỏ «Chỉ dùng khi được chuyển tới» ở «Chê đắt lần hai» trước',
      },
    ]))
})

describe('nhomThem', () => {
  const m = (id: string) => MAU.find((n) => n.id === id)!
  const ids = (x: ReturnType<typeof nhomThem>) => (typeof x === 'string' ? x : x.map((n) => n.id))
  const thieuHai = MAU_GIA.filter((n) => n.id !== 'che_dat' && n.id !== 'che_dat_downsell')
  it('một mình khi không phụ thuộc gì còn thiếu', () =>
    expect(ids(nhomThem(m('chot'), xoaNut(MAU_GIA, 'chot'), HT, MAU, TEN))).toEqual(['chot']))
  it('chuyển sang tình huống chưa có ⇒ thêm cùng nó (không kẹt «cần cái kia trước»)', () =>
    expect(ids(nhomThem(m('che_dat'), thieuHai, HT, MAU, TEN))).toEqual([
      'che_dat',
      'che_dat_downsell',
    ]))
  it('chỉ-lần-2 mà chưa ai chuyển sang ⇒ thêm cùng nguồn trong mẫu', () =>
    expect(ids(nhomThem(m('che_dat_downsell'), thieuHai, HT, MAU, TEN))).toEqual([
      'che_dat_downsell',
      'che_dat',
    ]))
  it('nguồn đã có trong bản riêng nhưng thôi chuyển sang ⇒ báo, không ghi đè nó', () =>
    expect(
      nhomThem(
        m('che_dat_downsell'),
        thayNut(xoaNut(MAU_GIA, 'che_dat_downsell'), { ...MAU_GIA[0]!, lan_2: '' }),
        HT,
        MAU,
        TEN,
      ),
    ).toBe('Cần đặt «Khách chê đắt» chuyển sang tình huống này trước'))
})

describe('phanLoi422', () => {
  const e = (fields: { field: string; reason: string }[]) =>
    new LoiApi('VALIDATION_ERROR', 'Dữ liệu gửi lên không hợp lệ', 422, fields)
  it('lỗi của tình huống đang sửa vào đúng ô; bước mang số thứ tự', () => {
    const p = phanLoi422(
      e([
        { field: 'body.nut[2].lam', reason: 'tối đa 6 dòng' },
        { field: 'body.nut[2].buoc[1].lam', reason: 'không được rỗng' },
      ]),
      MAU_GIA,
      'chot',
      TEN,
    )
    expect(p.cuaNut).toEqual({ lam: 'tối đa 6 dòng', buoc: 'Bước 2: không được rỗng' })
    expect(p.nutKhac).toEqual([])
  })
  it('lỗi của tình huống khác thành câu có tên + id để mở', () =>
    expect(
      phanLoi422(
        e([{ field: 'body.nut[0].tool', reason: 'tool không tồn tại: x' }]),
        MAU_GIA,
        'chot',
        TEN,
      ).nutKhac,
    ).toEqual([
      {
        id: 'che_dat',
        cau: '«Khách chê đắt» chưa hợp lệ: Kỹ năng nên dùng — tool không tồn tại: x',
      },
    ]))
  it('lỗi cả bộ và 422 không fields vào nhóm chung', () => {
    expect(
      phanLoi422(e([{ field: 'body.nut', reason: 'tối đa 40 nút' }]), MAU_GIA, null, TEN).chung,
    ).toEqual(['tối đa 40 nút'])
    expect(phanLoi422(e([]), MAU_GIA, null, TEN).chung).toEqual(['Dữ liệu gửi lên không hợp lệ'])
  })
})

it('nhanKyNang có nhãn cho no_lookup_needed', () =>
  expect(nhanKyNang('no_lookup_needed')).toBe('Không cần tra cứu'))
