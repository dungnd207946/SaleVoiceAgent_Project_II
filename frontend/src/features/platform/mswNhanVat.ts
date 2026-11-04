/**
 * Fake MSW của `/api/v1/nhan-vat` — CÓ TRẠNG THÁI (tạo → dựng → sẵn sàng, chọn, xoá),
 * vì màn tạo-rồi-theo-dõi đọc lại chính thứ vừa ghi. Mỗi lần `GET /nhan-vat/{id}` của
 * một nhân vật đang dựng đẩy tiến độ lên một nấc — đủ để thấy thanh tiến độ chạy ở dev.
 *
 * ⚠ Không phải nguồn sự thật về backend (`modules/nhan_vat/router.py` mới là). Video xem
 * trước không có thật ở fake (`xemTruoc: []`), poster dùng ảnh người dẫn mặc định.
 */
import { http, HttpResponse } from 'msw'
import type { DanhSachNhanVat, NhanVat } from './nhanVat'

const CAU_DEMO = [
  'Xin chào, tôi là trợ lý ảo của quý khách. Rất vui được hỗ trợ quý khách hôm nay.',
  'Quý khách cần tìm hiểu thông tin gì, cứ hỏi tôi nhé, tôi sẽ trả lời ngay.',
  'Cảm ơn quý khách đã quan tâm. Hẹn gặp lại quý khách lần sau!',
]

let DS: NhanVat[] = []
let soMoi = 0

export function RESET_NHAN_VAT_GIA(ds: NhanVat[] = []): void {
  DS = ds.map((x) => ({ ...x }))
  soMoi = 0
}

function tim(id: unknown): NhanVat | undefined {
  return DS.find((x) => x.id === id)
}

function tien(nv: NhanVat): void {
  if (nv.trangThai === 'san_sang' || nv.trangThai === 'loi') return
  nv.tienDo = Math.min(1, nv.tienDo + 0.25)
  nv.buoc = nv.tienDo < 0.5 ? 'tach_nen' : 'do_mat'
  if (nv.tienDo >= 1) {
    nv.trangThai = 'san_sang'
    nv.buoc = null
    nv.avatarId = `nv-${nv.id.padEnd(32, '0').slice(0, 32)}`
    nv.posterUrl = '/nhan-vat-lipsync.png'
  }
}

export const nhanVatHandlers = [
  http.get('/api/v1/nhan-vat', () =>
    HttpResponse.json<DanhSachNhanVat>({
      nhanVat: DS,
      dangDung: DS.find((x) => x.dangDung)?.id ?? null,
      taoTuAnh: true,
      nhaCungCap: 'gia',
      toiDa: 10,
      cauDemo: CAU_DEMO,
    }),
  ),
  http.get('/api/v1/nhan-vat/dang-dung', () => {
    const nv = DS.find((x) => x.dangDung && x.trangThai === 'san_sang')
    return HttpResponse.json(
      nv
        ? { id: nv.id, ten: nv.ten, avatarId: nv.avatarId, posterUrl: nv.posterUrl }
        : { id: null, ten: null, avatarId: null, posterUrl: null },
    )
  }),
  http.put('/api/v1/nhan-vat/dang-dung', async ({ request }) => {
    const { id } = (await request.json()) as { id: string | null }
    if (id !== null && tim(id)?.trangThai !== 'san_sang') {
      return HttpResponse.json(
        { error: { code: 'NHAN_VAT_CHUA_SAN_SANG', message: 'Nhân vật chưa dựng xong' } },
        {
          status: 409,
        },
      )
    }
    for (const x of DS) x.dangDung = x.id === id
    const nv = id ? tim(id) : undefined
    return HttpResponse.json(
      nv
        ? { id: nv.id, ten: nv.ten, avatarId: nv.avatarId, posterUrl: nv.posterUrl }
        : { id: null, ten: null, avatarId: null, posterUrl: null },
    )
  }),
  http.post('/api/v1/nhan-vat', async ({ request }) => {
    const f = await request.formData().catch(() => null)
    const nguon = (f?.get('nguon') as 'video' | 'anh' | null) ?? 'video'
    soMoi += 1
    const nv: NhanVat = {
      id: `gia-${soMoi}`,
      ten: (f?.get('ten') as string | null) ?? `Nhân vật ${soMoi}`,
      nguon,
      trangThai: nguon === 'anh' ? 'tao_video' : 'dung',
      buoc: null,
      tienDo: 0,
      loi: null,
      dangDung: false,
      avatarId: null,
      posterUrl: null,
      xemTruoc: [],
      taoLuc: new Date().toISOString(),
    }
    DS.push(nv)
    return HttpResponse.json(nv, { status: 201 })
  }),
  http.get('/api/v1/nhan-vat/:id', ({ params }) => {
    const nv = tim(params['id'])
    if (!nv)
      return HttpResponse.json(
        { error: { code: 'NHAN_VAT_KHONG_TON_TAI', message: 'Không có' } },
        { status: 404 },
      )
    tien(nv)
    return HttpResponse.json(nv)
  }),
  http.post('/api/v1/nhan-vat/:id/thu-lai', ({ params }) => {
    const nv = tim(params['id'])
    if (!nv) return new HttpResponse(null, { status: 404 })
    Object.assign(nv, { trangThai: 'dung', loi: null, tienDo: 0.3, buoc: null })
    return HttpResponse.json(nv)
  }),
  http.post('/api/v1/nhan-vat/:id/xem-truoc', () =>
    HttpResponse.json(
      { error: { code: 'NHAN_VAT_XEM_TRUOC_LOI', message: 'Bản giả lập không render video.' } },
      { status: 502 },
    ),
  ),
  http.delete('/api/v1/nhan-vat/:id', ({ params }) => {
    DS = DS.filter((x) => x.id !== params['id'])
    return new HttpResponse(null, { status: 204 })
  }),
]
