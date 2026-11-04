/**
 * Cổng client overview. Kiểm KHIÊN trước hết — backend cũ/chưa deploy bỏ hẳn
 * một khoá khỏi JSON, và `undefined` lọt mọi guard `!== null` ở component.
 */
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { overview } from '@/features/ops/api'

const DAY_DU = {
  moc: { tuNgay: '2026-08-07', tinhDen: '2026-08-13' },
  hoiThoai: {
    tong: 3,
    truoc: 2,
    theoNgay: [{ ngay: '2026-08-13', chat: 2, voice: 1, khac: 0, tong: 3 }],
    theoKenh: [
      { kenh: 'chat', n: 2 },
      { kenh: null, n: 1 },
    ],
  },
  chuyenSale: { chuyen: 1, tuXuLy: 2 },
  danhGia: {
    trungBinh: 4.33,
    truoc: null,
    tong: 190,
    theoSao: { '1': 4, '2': 8, '3': 20, '4': 48, '5': 110 },
  },
  kienThuc: { muc: [{ khoa: 'duAn', thay: 8, tong: 12 }] },
}

const server = setupServer()
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

describe('overview()', () => {
  it('đọc đủ năm khối', async () => {
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(DAY_DU)))

    const o = await overview()

    expect(o.hoiThoai.tong).toBe(3)
    expect(o.hoiThoai.theoNgay[0]?.chat).toBe(2)
    expect(o.chuyenSale.chuyen).toBe(1)
    expect(o.danhGia.theoSao['5']).toBe(110)
    expect(o.kienThuc.muc[0]?.khoa).toBe('duAn')
  })

  it('backend thiếu khoá `theoKenh` ⇒ mảng rỗng, KHÔNG undefined', async () => {
    const thieu = { ...DAY_DU, hoiThoai: { ...DAY_DU.hoiThoai, theoKenh: undefined } }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.hoiThoai.theoKenh).toEqual([])
  })

  it('backend bỏ hẳn khoá `chuyenSale` ⇒ cả hai bậc là 0, KHÔNG undefined', async () => {
    const thieu = { ...DAY_DU, chuyenSale: undefined }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.chuyenSale.chuyen).toBe(0)
    expect(o.chuyenSale.tuXuLy).toBe(0)
  })

  it('backend bỏ hẳn khoá `moc` ⇒ chuỗi rỗng, KHÔNG bịa ngày', async () => {
    const thieu = { ...DAY_DU, moc: undefined }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.moc.tuNgay).toBe('')
    expect(o.moc.tinhDen).toBe('')
  })

  it('backend bỏ hẳn `kienThuc.muc` ⇒ mảng rỗng, KHÔNG undefined', async () => {
    const thieu = { ...DAY_DU, kienThuc: { muc: undefined } }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.kienThuc.muc).toEqual([])
  })

  it('`theoSao` thiếu một bậc ⇒ bậc đó là 0, không phải undefined', async () => {
    const thieu = { ...DAY_DU, danhGia: { ...DAY_DU.danhGia, theoSao: { '5': 110 } } }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.danhGia.theoSao['1']).toBe(0)
    expect(o.danhGia.theoSao['5']).toBe(110)
  })

  it('phần tử `theoNgay` thiếu `khac` ⇒ 0, KHÔNG undefined', async () => {
    /* Khiên phải xuống tới PHẦN TỬ: `theoNgay ?? []` chỉ cứu ca backend bỏ hẳn
       mảng. `khac` là khoá MỚI NHẤT của `NgayOut`, tức khoá đầu tiên vắng mặt
       khi API chưa deploy — và `undefined` ở đó đi thẳng vào `Y(undefined)` =
       `NaN`, rồi `<path d="M NaN NaN …">` bị trình duyệt bỏ qua LẶNG LẼ. */
    const thieu = {
      ...DAY_DU,
      hoiThoai: { ...DAY_DU.hoiThoai, theoNgay: [{ ngay: '2026-08-13', chat: 2, voice: 1 }] },
    }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.hoiThoai.theoNgay[0]?.khac).toBe(0)
  })

  it('phần tử `theoNgay` thiếu `tong` ⇒ CỘNG LẠI từ ba thành phần, không phải 0', async () => {
    /* Ngoại lệ DUY NHẤT không rơi về 0: hợp đồng định nghĩa `tong` bằng đúng
       tổng ba thành phần, nên dựng lại từ chúng là ĐỌC hợp đồng chứ không bịa
       số (khác `moc.tuNgay` — ở đó payload không tái tạo được gì). Để `?? 0`
       thì tooltip in ra «Chat 2 · Voice 1 · Khác 3 · Tổng 0». */
    const thieu = {
      ...DAY_DU,
      hoiThoai: {
        ...DAY_DU.hoiThoai,
        theoNgay: [{ ngay: '2026-08-13', chat: 2, voice: 1, khac: 3 }],
      },
    }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.hoiThoai.theoNgay[0]?.tong).toBe(6)
  })

  it('phần tử `theoKenh` thiếu `n` ⇒ 0; thiếu `kenh` ⇒ null («Chưa rõ»)', async () => {
    const thieu = { ...DAY_DU, hoiThoai: { ...DAY_DU.hoiThoai, theoKenh: [{}] } }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.hoiThoai.theoKenh[0]).toEqual({ kenh: null, n: 0 })
  })

  it('phần tử `kienThuc.muc` thiếu `thay`/`tong` ⇒ 0, không NaN ở thước', async () => {
    const thieu = { ...DAY_DU, kienThuc: { muc: [{ khoa: 'duAn' }] } }
    server.use(http.get('/api/v1/overview', () => HttpResponse.json(thieu)))

    const o = await overview()

    expect(o.kienThuc.muc[0]).toEqual({ khoa: 'duAn', thay: 0, tong: 0 })
  })

  it('lỗi HTTP ném LoiApi mang code của backend', async () => {
    server.use(
      http.get('/api/v1/overview', () =>
        HttpResponse.json(
          { error: { code: 'FORBIDDEN', message: 'Không có quyền' } },
          { status: 403 },
        ),
      ),
    )

    await expect(overview()).rejects.toMatchObject({ code: 'FORBIDDEN' })
  })
})
