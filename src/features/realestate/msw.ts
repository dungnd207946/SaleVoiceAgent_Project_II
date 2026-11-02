/**
 * Fake MSW của cổng nạp dữ liệu ngoài (tab «Nguồn dữ liệu» ở `/projects`).
 *
 * Tệp RIÊNG, không nhét vào `lib/msw/handlers.ts` — cùng khuôn `features/ops/msw.ts`
 * và `features/quality/msw.ts`, và vì tệp gom kia đã 57KB. Fake CŨ của realestate
 * (dự án · phân khu · căn · media) vẫn ở tệp gom; không chuyển chúng sang đây,
 * đó là việc khác.
 *
 * ⚠️ FAKE CÓ TRẠNG THÁI — hiếm, cùng lý do `FAKE_LINH_VUC`: màn này tạo khoá rồi
 * đọc lại ngay, và xoá khoá rồi thấy hàng biến mất. Fake không giữ trạng thái
 * thì cả hai luồng đó không nhìn được.
 *
 * ⚠️ BẢN SAO VIẾT TAY, KHÔNG CÓ CỔNG PARITY, và backend CHƯA CÓ endpoint nào ở
 * đây. Đừng lấy hành vi của tệp này làm sự thật về backend (luật CLAUDE.md, mục
 * Gotchas — đã có một vòng thiết kế tin ngược và trả giá).
 */
import { HttpResponse, http } from 'msw'
import { LINH_VUC, PHIEN_BAN, type Token, type LoiNap } from './nguon'

const NEN = `/api/v1/ingest/${LINH_VUC}/${PHIEN_BAN}`

const DIEM_NAP_GIA = `https://ingest.noblex.vn/api/v1/ingest/${LINH_VUC}/${PHIEN_BAN}/events`

// Từ 2026-08-21 backend phục vụ Swagger CỦA RIÊNG cổng nạp dưới `/api/v1/…`
// (không còn neo hash vào `/docs` của cả portal).
const DOCS_URL_GIA = `https://ingest.noblex.vn/api/v1/ingest/${LINH_VUC}/${PHIEN_BAN}/docs`

const TOKEN: Token[] = [
  {
    id: 1,
    label: 'ERP Anphu — job đẩy quỹ căn',
    token: 'ody_in_4Rt8_9wKmZq2vLxNbHc7pJf3dSgYaEuTiOr5A',
  },
  {
    id: 2,
    label: 'Web bán hàng — đẩy tài liệu',
    token: 'ody_in_Lp07_Bd6yQwErTyUiOpAsDfGhJkLzXcVbNm41',
  },
]

const LOI: LoiNap[] = [
  {
    id: 1,
    entity: 'unit',
    externalId: 'TSA-B-0907',
    truong: 'priceVnd',
    lyDo: 'Phải là số, nhận được chuỗi "4,85 tỷ"',
    nhanLuc: '2026-08-14T02:55:12.000Z',
  },
  {
    id: 2,
    entity: 'unit',
    externalId: 'TSA-B-1102',
    truong: 'saleStatus',
    lyDo: 'Giá trị "giu_cho" không hợp lệ — chỉ nhận available · booked · sold',
    nhanLuc: '2026-08-14T02:55:12.000Z',
  },
  {
    id: 3,
    entity: 'document',
    externalId: 'DOC-CSBH-07',
    truong: '',
    lyDo: 'Thiếu occurredAt — không xác định được thứ tự so với bản đang có',
    nhanLuc: '2026-08-13T19:04:00.000Z',
  },
]

const BAN_DAU = structuredClone({ TOKEN, LOI })

/** Test nào đổi trạng thái fake phải gọi cái này ở `beforeEach`. */
export function RESET_NGUON_GIA(): void {
  TOKEN.splice(0, TOKEN.length, ...structuredClone(BAN_DAU.TOKEN))
  LOI.splice(0, LOI.length, ...structuredClone(BAN_DAU.LOI))
  idKe = 100
}

let idKe = 100

export const nguonHandlers = [
  http.get(`${NEN}/tong-quan`, () =>
    HttpResponse.json({
      diemNap: DIEM_NAP_GIA,
      docsUrl: DOCS_URL_GIA,
      thongKe: {
        nhanCuoiLuc: '2026-08-14T02:55:12.000Z',
        soNhan24h: 1284,
        soGhiDuoc24h: 1281,
        soHong24h: 3,
      },
      tokens: TOKEN,
    }),
  ),

  http.post(`${NEN}/keys`, async ({ request }) => {
    const { label } = (await request.json()) as { label?: string }
    const ten = (label ?? '').trim()
    if (ten === '' || ten.length > 60) {
      return HttpResponse.json(
        {
          error: {
            code: 'VALIDATION',
            message: 'Nhãn bắt buộc, tối đa 60 ký tự',
            fields: [{ field: 'body.label', reason: 'bắt buộc, tối đa 60 ký tự' }],
          },
        },
        { status: 422 },
      )
    }
    idKe += 1
    const tho = `ody_in_${String(idKe)}_${'Kf3nQ8sVzR6mTbYwHxLpAeUdCgJi'.slice(0, 28)}`
    const moi: Token = {
      id: idKe,
      label: ten,
      token: tho,
    }
    TOKEN.unshift(moi)
    return HttpResponse.json(moi, { status: 201 })
  }),

  http.delete(`${NEN}/keys/:id`, ({ params }) => {
    const i = TOKEN.findIndex((k) => String(k.id) === params['id'])
    if (i === -1) return new HttpResponse(null, { status: 404 })
    TOKEN.splice(i, 1)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get(`${NEN}/loi`, () => HttpResponse.json({ loi: LOI })),
]
