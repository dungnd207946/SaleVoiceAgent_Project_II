import { beforeEach, describe, expect, it } from 'vitest'
import { LoiApi } from '@/lib/http'
import {
  apDungMau,
  datRoleDung,
  luuKichBan,
  taiKichBan,
  taiTemplate,
} from '@/features/kich-ban/api'
import { boSale, veKhuon } from '@/features/kich-ban/khuon'
import { FAKE_KICH_BAN, datLaiKichBanGia, epLoiGhiKichBanGia } from '@/features/kich-ban/msw'

beforeEach(() => datLaiKichBanGia())

describe('veKhuon — nút GET thành khuôn PUT', () => {
  it('chỉ đúng các khoá NutVao, bước không mang tool', () => {
    const n = FAKE_KICH_BAN.nodes.find((x) => x.id === 'chot')!
    const v = veKhuon(n)
    expect(Object.keys(v).sort()).toEqual([
      'bat',
      'buoc',
      'cam',
      'cau_ket',
      'chi_lan_2',
      'dau_hieu',
      'id',
      'kenh',
      'khi_thieu',
      'lam',
      'lan_2',
      'nguon',
      'nhom',
      'ten',
      'tool',
    ])
    expect(v.buoc[0]).toEqual({ id: n.buoc[0]!.id, lam: n.buoc[0]!.lam })
  })

  it('boSale bỏ nút hệ thống', () => {
    expect(boSale(FAKE_KICH_BAN.nodes).map((n) => n.id)).toEqual([
      'che_dat',
      'che_dat_downsell',
      'chot',
      'goi_dien_ra',
    ])
  })
})

describe('API ghi kịch bản (qua fake)', () => {
  it('chưa áp dụng: trạng thái mẫu, version 0, chỉ customer', async () => {
    const d = await taiKichBan(7)
    expect(d.kichBan).toMatchObject({ trangThai: 'mau', version: 0, roleDung: ['customer'] })
  })

  it('PUT lưu thành bản riêng; chỉ nút đổi mới đổi hash', async () => {
    const d = await taiKichBan(7)
    const bo = boSale(d.nodes).map((n) => (n.id === 'chot' ? { ...n, lam: ['chữ mới'] } : n))
    expect(await luuKichBan({ version: 0, nut: bo })).toMatchObject({
      trangThai: 'rieng',
      version: 1,
    })
    const sau = await taiKichBan(7)
    const h = (x: typeof d, id: string) => x.nodes.find((n) => n.id === id)!.hash
    expect(sau.nodes.find((n) => n.id === 'chot')!.lam).toEqual(['chữ mới'])
    expect(h(sau, 'chot')).not.toBe(h(d, 'chot'))
    expect(h(sau, 'che_dat')).toBe(h(d, 'che_dat'))
  })

  it('version lệch → LoiApi PLAYBOOK_DA_DOI', async () => {
    await expect(luuKichBan({ version: 5, nut: [] })).rejects.toMatchObject({
      code: 'PLAYBOOK_DA_DOI',
    })
  })

  it('422 mang fields', async () => {
    epLoiGhiKichBanGia(422, {
      error: {
        code: 'VALIDATION_ERROR',
        message: 'x',
        fields: [{ field: 'body.nut[0].lam', reason: 'tối đa 6 dòng' }],
      },
    })
    const e = await luuKichBan({ version: 0, nut: [] }).catch((x: unknown) => x)
    expect(e).toBeInstanceOf(LoiApi)
    expect((e as LoiApi).truong).toEqual([{ field: 'body.nut[0].lam', reason: 'tối đa 6 dòng' }])
  })

  it('áp lại mẫu rồi đặt role', async () => {
    await apDungMau(0)
    expect(await datRoleDung({ version: 1, roles: ['customer', 'sale'] })).toMatchObject({
      trangThai: 'rieng',
      version: 2,
      roleDung: ['customer', 'sale'],
    })
  })

  it('template có gioiHan, chỉ nút lớp sale', async () => {
    const t = await taiTemplate()
    expect(t.gioiHan?.maxNut).toBe(40)
    expect(t.nodes.every((n) => n.lop === 'sale')).toBe(true)
  })
})
