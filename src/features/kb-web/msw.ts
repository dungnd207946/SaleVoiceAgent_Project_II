/**
 * Fake MSW của `/api/v1/kb-web/*` — dev không backend và test. Có trạng thái trong tiến trình
 * (bật/tắt nguồn, thêm chủ đề, lưu lịch) để màn hình thấy kết quả của chính thao tác vừa làm.
 */
import { http, HttpResponse } from 'msw'
import type { ChiTietDuAn, ChuDe, DuAn, KetQuaThu, Lich, LichTong, MucHoSo, Nguon, TongQuan, Viec } from './api'

const T0 = Date.now()
const luc = (phutTruoc: number) => new Date(T0 - phutTruoc * 60_000).toISOString()
const sau = (phut: number) => new Date(T0 + phut * 60_000).toISOString()

let viecGia: Viec[] = [
  {
    id: 9003,
    loai: 'kbweb_project',
    mode: 'init',
    duAn: 'NCTH',
    duAnTen: 'NOBLE CRYSTAL TÂY HỒ',
    trangThai: 'running',
    nguoi: 'u_fake_dang',
    nguoiTen: 'Đặng Thành',
    taoLuc: luc(6),
    batDau: luc(5),
    ketThuc: null,
    soLuong: 0,
    thongDiep: '',
  },
  {
    id: 9002,
    loai: 'kbweb_run',
    mode: 'nightly',
    duAn: null,
    trangThai: 'success',
    nguoi: 'lich',
    taoLuc: luc(60 * 12),
    batDau: luc(60 * 12),
    ketThuc: luc(60 * 12 - 22),
    soLuong: 212,
    thongDiep: 'crawl: 212; bản tin: 10; xếp việc nightly: 23',
    chiPhi: '1840.5000000000',
  },
  {
    id: 9001,
    loai: 'kbweb_project',
    mode: 'nightly',
    duAn: 'NOXH1',
    duAnTen: 'NOXH VSIP Bắc Ninh',
    trangThai: 'failed',
    nguoi: 'lich',
    taoLuc: luc(60 * 11),
    batDau: luc(60 * 11),
    ketThuc: luc(60 * 11 - 3),
    soLuong: 0,
    thongDiep: 'ConnectError: All connection attempts failed',
    chiPhi: '6370.0000000000',
  },
]

let nguonGia: Nguon[] = [
  nguon(1, 'cafef.vn', 'CafeF', true, 'news', 142),
  nguon(2, 'vnexpress.net', 'VnExpress', true, 'news', 97),
  nguon(3, 'dantri.com.vn', 'Dân trí', true, 'news', 88),
  nguon(4, 'baoxaydung.vn', 'Báo Xây dựng', true, 'news', 31),
  nguon(5, 'quyhoach.hanoi.vn', 'Quy hoạch Hà Nội', true, 'living', 0),
  nguon(6, 'cafeland.vn', 'CafeLand', true, 'news', 52, 'browser'),
  { ...nguon(7, 'tuoitre.vn', 'Tuổi Trẻ', true, 'news', 44), bat: false },
  {
    ...nguon(8, 'sunshinegroup.vn', 'Sunshine Group', false, 'living', 0),
    tinhTrang: 'no_feed',
    ghiChu: 'Không tìm thấy kênh bài mới (RSS/sitemap). Sẽ theo dõi như một trang cố định, kiểm mỗi tháng.',
  },
]

function nguon(
  id: number,
  domain: string,
  ten: string,
  macDinh: boolean,
  theoDoi: 'news' | 'living',
  bai: number,
  cheDo: 'http' | 'browser' = 'http',
): Nguon {
  return {
    id,
    domain,
    ten,
    bat: true,
    macDinh,
    cheDo,
    theoDoi,
    baiBayNgay: bai,
    tinhTrang: 'ok',
    ghiChu: '',
    thuLuc: luc(60 * 12),
  }
}

let chuDeGia: ChuDe[] = [
  chuDe(1, 'transit', 'Giao thông công cộng', 'Hạ tầng giao thông – Công cộng', [
    'metro xe buýt gần {project}',
    '{location} tuyến metro tiến độ',
  ]),
  chuDe(2, 'education', 'Giáo dục', 'Tiện ích – Giáo dục', ['trường học gần {location}', 'trường quốc tế {location}']),
  chuDe(3, 'healthcare', 'Y tế', 'Tiện ích – Y tế', ['bệnh viện gần {location}', 'bệnh viện đa khoa {location}']),
  chuDe(4, 'legal', 'Pháp lý dự án', 'Pháp lý', ['{project} pháp lý giấy phép xây dựng', '{project} sổ hồng cấp sổ']),
  chuDe(5, 'price_trend', 'Mặt bằng giá', 'Mặt bằng giá', ['giá nhà đất {location} hiện nay', 'giá bán {project}']),
  { ...chuDe(6, 'employment', 'Việc làm và hành chính', 'Việc làm và hành chính', ['khu công nghiệp gần {location}']), bat: false },
  { ...chuDe(7, 'nearby_projects', 'Dự án lân cận', 'Dự án lân cận', ['dự án bất động sản gần {project}']), vaoHoSo: false },
  {
    ...chuDe(8, 'cho_thue', 'Cho thuê và dòng tiền', 'Cho thuê và dòng tiền', [
      'giá thuê căn hộ {project}',
      'tỷ suất cho thuê {location}',
    ]),
    macDinh: false,
    moTa: 'Giá thuê căn hộ, nhà phố ở dự án và khu vực; tỷ suất cho thuê.',
  },
]

function chuDe(id: number, code: string, ten: string, nhan: string, cauTim: string[]): ChuDe {
  return { id, code, ten, nhan, moTa: '', cauTim, tuKhoa: [], bat: true, macDinh: true, vaoHoSo: true, thuTu: id }
}

let lichGia: Lich[] = [
  {
    mode: 'nightly',
    bat: true,
    gio: '01:10',
    ngayTrongTuan: [],
    soThang: null,
    ngayTrongChuKy: null,
    latCat: 1,
    lanGanNhat: luc(60 * 12),
    lanKeTiep: sau(60 * 12),
  },
  {
    mode: 'weekly',
    bat: true,
    gio: '04:00',
    ngayTrongTuan: [1, 3, 5],
    soThang: null,
    ngayTrongChuKy: null,
    latCat: 3,
    lanGanNhat: luc(60 * 30),
    lanKeTiep: sau(60 * 40),
  },
  {
    mode: 'rebuild',
    bat: true,
    gio: '05:00',
    ngayTrongTuan: [],
    soThang: 3,
    ngayTrongChuKy: 'd1',
    latCat: 1,
    lanGanNhat: null,
    lanKeTiep: sau(60 * 24 * 40),
  },
]
let gioiHanGia = { groundingThang: 1000, trinhDuyetNgay: 300, ngayHoi: 28 }

const duAnGia: DuAn[] = [
  { code: 'NPTTL', ten: 'NOBLE PALACE TÂY THĂNG LONG', soMuc: 3, soChuDe: 7, capNhatLuc: luc(60 * 12), dangChay: false, viecGanNhat: null },
  { code: 'NCTH', ten: 'NOBLE CRYSTAL TÂY HỒ', soMuc: 5, soChuDe: 7, capNhatLuc: luc(60 * 36), dangChay: true, viecGanNhat: viecGia[0] ?? null },
  { code: 'NOXH1', ten: 'NOXH VSIP Bắc Ninh', soMuc: 1, soChuDe: 7, capNhatLuc: luc(60 * 24 * 3), dangChay: false, viecGanNhat: viecGia[2] ?? null },
  { code: 'LEP', ten: 'LUMIÈRE ESSENCE PEAK', soMuc: 0, soChuDe: 7, capNhatLuc: null, dangChay: false, viecGanNhat: null },
]

type NoiDungGia = Pick<MucHoSo, 'noiDung' | 'nguon' | 'capNhatLuc'>

const NOI_DUNG_GIA: Record<string, NoiDungGia> = {
  'Hạ tầng giao thông – Công cộng': {
    noiDung: '(Cập nhật 05/10/2026)\nHạ tầng giao thông – Công cộng: Cách ga metro số 2 khoảng 4 km, có tuyến buýt 57 chạy qua [1].',
    nguon: [{ url: 'https://dantri.com.vn/c', ten: 'Dân trí', ngay: luc(60 * 24 * 3) }],
    capNhatLuc: luc(60 * 12),
  },
  'Pháp lý': {
    noiDung: '(Cập nhật 05/10/2026)\nPháp lý: Đã có quyết định chủ trương đầu tư và giấy phép xây dựng phân khu A [1].',
    nguon: [{ url: 'https://sunshinegroup.vn/d', ten: 'Sunshine Group', ngay: null }],
    capNhatLuc: luc(60 * 12),
  },
  'Dự án lân cận': {
    noiDung:
      '(Cập nhật 05/10/2026)\nCác dự án gần NOBLE PALACE TÂY THĂNG LONG (Đan Phượng):\n- Hinode Royal Park (gần NOBLE PALACE TÂY THĂNG LONG, Hoài Đức): Khu đô thị 100 ha [1].',
    nguon: [{ url: 'https://cafef.vn/e', ten: 'CafeF', ngay: luc(60 * 24 * 10) }],
    capNhatLuc: luc(60 * 12),
  },
}
const MUC_AN_GIA = new Set(['Tiện ích – Y tế'])

function mucGia(coNoiDung: boolean): MucHoSo[] {
  const dong = chuDeGia.filter((c) => c.bat).map((c) => ({ nhan: c.nhan, ten: c.ten }))
  return dong.map((d) => ({
    ...d,
    ...((coNoiDung && NOI_DUNG_GIA[d.nhan]) || { noiDung: '', nguon: [], capNhatLuc: null }),
    an: coNoiDung && MUC_AN_GIA.has(d.nhan),
  }))
}

const CHI_TIET: Omit<ChiTietDuAn, 'muc'> = {
  code: 'NPTTL',
  ten: 'NOBLE PALACE TÂY THĂNG LONG',
  dangChay: false,
  mucAn: [...MUC_AN_GIA],
  bai: [
    { url: 'https://dantri.com.vn/c', tieuDe: 'Đan Phượng: thông xe đường Hoàng Quốc Việt kéo dài cuối 2026', domain: 'dantri.com.vn', ngayDang: luc(60 * 24 * 3), thuLuc: luc(60 * 24 * 3), loai: false },
    { url: 'https://cafef.vn/a', tieuDe: 'Noble Palace Tây Thăng Long: biệt thự hàng hiệu phía Tây', domain: 'cafef.vn', ngayDang: luc(60 * 24 * 7), thuLuc: luc(60 * 24 * 7), loai: false },
    { url: 'https://sunshinegroup.vn/d', tieuDe: 'Sunshine Group ra mắt phân khu mới', domain: 'sunshinegroup.vn', ngayDang: null, thuLuc: luc(60 * 24 * 4), loai: true },
  ],
}

function tongQuan(): TongQuan {
  return {
    soDuAn: duAnGia.length,
    soDuAnCoHoSo: duAnGia.filter((d) => d.soMuc > 0).length,
    hoSoCuNhat: luc(60 * 24 * 6),
    baiBayNgay: 412,
    baiBaMuoiNgay: 1284,
    soNguonBat: nguonGia.filter((n) => n.bat).length,
    groundingThang: 410,
    groundingTran: gioiHanGia.groundingThang,
    trinhDuyetHomNay: 12,
    trinhDuyetTran: gioiHanGia.trinhDuyetNgay,
    dangChay: viecGia.filter((v) => v.trangThai === 'running' || v.trangThai === 'queued'),
    loiGanDay: viecGia.filter((v) => v.trangThai === 'failed'),
    lanKeTiep: sau(60 * 12),
  }
}

let nextId = 9100
function xepViec(loai: Viec['loai'], mode: string, duAn: string | null): Viec {
  const v: Viec = {
    id: nextId++,
    loai,
    mode,
    duAn,
    trangThai: 'queued',
    nguoi: 'u_fake_dang',
    nguoiTen: 'Đặng Thành',
    taoLuc: new Date().toISOString(),
    batDau: null,
    ketThuc: null,
    soLuong: 0,
    thongDiep: '',
  }
  viecGia = [v, ...viecGia]
  return v
}

const loi = (status: number, code: string, message: string) =>
  HttpResponse.json({ error: { code, message } }, { status })

// Lượt thử giả: URL chứa «chan» ⇒ không tải được; chứa «co-dinh» ⇒ trang cố định; còn lại dùng được.
const thuGia = new Map<string, { url: string; den: number }>()
function ketQuaGia(url: string): KetQuaThu {
  const domain = url.replace(/^https?:\/\//, '').split('/')[0] ?? url
  if (url.includes('chan'))
    return { trangThai: 'blocked', ghiChu: 'Không tải được trang, kể cả bằng trình duyệt. Trang có thể đang chặn tải tự động.', soBai: 0, soTrangThu: 2, soTrangDoc: 0, daCo: false, deXuat: null }
  const deXuat = { domain, ten: domain, cheDo: 'http' as const, theoDoi: 'news' as const, rss: [`https://${domain}/rss`], sitemapIndex: '', newsSitemaps: [], categoryPages: [], articlePattern: '' }
  if (url.includes('co-dinh'))
    return { trangThai: 'no_feed', ghiChu: 'Không tìm thấy kênh bài mới (RSS/sitemap). Sẽ theo dõi như một trang cố định, kiểm mỗi tháng.', soBai: 0, soTrangThu: 0, soTrangDoc: 0, daCo: false, deXuat: { ...deXuat, theoDoi: 'living', rss: [] } }
  return { trangThai: 'ok', ghiChu: '', soBai: 86, soTrangThu: 2, soTrangDoc: 2, daCo: nguonGia.some((n) => n.domain === domain), deXuat }
}

export const kbWebHandlers = [
  http.get('/api/v1/kb-web/overview', () => HttpResponse.json(tongQuan())),
  http.get('/api/v1/kb-web/worker', () => HttpResponse.json({ dangChay: true })),
  http.get('/api/v1/kb-web/sources', () => HttpResponse.json(nguonGia)),
  http.post('/api/v1/kb-web/sources/probe', async ({ request }) => {
    const { url } = (await request.json()) as { url: string }
    const token = `t${nextId++}`
    thuGia.set(token, { url, den: Date.now() + 1200 })
    return HttpResponse.json({ token, jobId: nextId }, { status: 202 })
  }),
  http.get('/api/v1/kb-web/sources/probe/:token', ({ params }) => {
    const t = thuGia.get(String(params['token']))
    if (!t) return loi(404, 'KB_WEB_THU_KHONG_TON_TAI', 'Không có lượt thử nào với mã này')
    if (Date.now() < t.den) return HttpResponse.json({ trangThai: 'dang_chay', ketQua: null })
    return HttpResponse.json({ trangThai: 'xong', ketQua: ketQuaGia(t.url) })
  }),
  http.post('/api/v1/kb-web/sources', async ({ request }) => {
    const b = (await request.json()) as { domain: string; ten: string; cheDo: 'http' | 'browser'; theoDoi: 'news' | 'living'; tinhTrang: 'ok' | 'no_feed'; ghiChu: string }
    if (nguonGia.some((n) => n.domain === b.domain)) return loi(409, 'KB_WEB_NGUON_DA_CO', `${b.domain} đã có trong danh sách nguồn`)
    const n: Nguon = { ...nguon(nextId++, b.domain, b.ten, false, b.theoDoi, 0, b.cheDo), tinhTrang: b.tinhTrang, ghiChu: b.ghiChu, thuLuc: new Date().toISOString() }
    nguonGia = [...nguonGia, n]
    return HttpResponse.json(n, { status: 201 })
  }),
  http.patch('/api/v1/kb-web/sources/:id', async ({ params, request }) => {
    const b = (await request.json()) as { bat?: boolean; ten?: string }
    const i = nguonGia.findIndex((n) => n.id === Number(params['id']))
    if (i < 0) return loi(404, 'KB_WEB_NGUON_KHONG_TON_TAI', 'Không có nguồn này')
    const cu = nguonGia[i] as Nguon
    nguonGia[i] = { ...cu, bat: b.bat ?? cu.bat, ten: b.ten ?? cu.ten }
    return HttpResponse.json(nguonGia[i])
  }),
  http.delete('/api/v1/kb-web/sources/:id', ({ params }) => {
    const n = nguonGia.find((x) => x.id === Number(params['id']))
    if (!n) return loi(404, 'KB_WEB_NGUON_KHONG_TON_TAI', 'Không có nguồn này')
    nguonGia = nguonGia.filter((x) => x.id !== n.id)
    return new HttpResponse(null, { status: 204 })
  }),
  http.post('/api/v1/kb-web/sources/:id/retry', ({ params }) => {
    const n = nguonGia.find((x) => x.id === Number(params['id']))
    if (!n) return loi(404, 'KB_WEB_NGUON_KHONG_TON_TAI', 'Không có nguồn này')
    const token = `t${nextId++}`
    thuGia.set(token, { url: `https://${n.domain}/`, den: Date.now() + 1000 })
    return HttpResponse.json({ token, jobId: nextId }, { status: 202 })
  }),
  http.post('/api/v1/kb-web/sources/:id/probe-result', async ({ params, request }) => {
    const kq = (await request.json()) as KetQuaThu
    const i = nguonGia.findIndex((n) => n.id === Number(params['id']))
    if (i < 0) return loi(404, 'KB_WEB_NGUON_KHONG_TON_TAI', 'Không có nguồn này')
    nguonGia[i] = { ...(nguonGia[i] as Nguon), tinhTrang: kq.trangThai, ghiChu: kq.ghiChu, thuLuc: new Date().toISOString() }
    return HttpResponse.json(nguonGia[i])
  }),

  http.get('/api/v1/kb-web/topics', () => HttpResponse.json(chuDeGia)),
  http.post('/api/v1/kb-web/topics/draft', async ({ request }) => {
    const { ten } = (await request.json()) as { ten: string }
    return HttpResponse.json({ cauTim: [`${ten.toLowerCase()} {project}`, `${ten.toLowerCase()} {location}`], tuKhoa: [ten.toLowerCase()] })
  }),
  http.post('/api/v1/kb-web/topics', async ({ request }) => {
    const b = (await request.json()) as { ten: string; moTa: string; cauTim: string[]; tuKhoa: string[] }
    if (chuDeGia.length >= 20) return loi(409, 'KB_WEB_CHU_DE_QUA_GIOI_HAN', 'Tối đa 20 chủ đề mỗi workspace')
    const c: ChuDe = { ...chuDe(nextId++, b.ten.toLowerCase().replace(/\W+/g, '_'), b.ten, b.ten, b.cauTim), moTa: b.moTa, tuKhoa: b.tuKhoa, macDinh: false, thuTu: chuDeGia.length + 1 }
    chuDeGia = [...chuDeGia, c]
    return HttpResponse.json(c, { status: 201 })
  }),
  http.patch('/api/v1/kb-web/topics/:id', async ({ params, request }) => {
    const b = (await request.json()) as Partial<Pick<ChuDe, 'bat' | 'ten' | 'moTa' | 'cauTim' | 'tuKhoa'>>
    const i = chuDeGia.findIndex((c) => c.id === Number(params['id']))
    if (i < 0) return loi(404, 'KB_WEB_CHU_DE_KHONG_TON_TAI', 'Không có chủ đề này')
    const cu = chuDeGia[i] as ChuDe
    chuDeGia[i] = { ...cu, ...b, nhan: cu.macDinh ? cu.nhan : (b.ten ?? cu.nhan) }
    return HttpResponse.json(chuDeGia[i])
  }),
  http.delete('/api/v1/kb-web/topics/:id', ({ params }) => {
    const c = chuDeGia.find((x) => x.id === Number(params['id']))
    if (!c) return loi(404, 'KB_WEB_CHU_DE_KHONG_TON_TAI', 'Không có chủ đề này')
    chuDeGia = chuDeGia.filter((x) => x.id !== c.id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/v1/kb-web/schedules', () => HttpResponse.json({ lich: lichGia, gioiHan: gioiHanGia } satisfies LichTong)),
  http.put('/api/v1/kb-web/schedules', async ({ request }) => {
    const b = (await request.json()) as { lich: Partial<Lich>[]; gioiHan?: typeof gioiHanGia }
    lichGia = lichGia.map((l) => {
      const moi = b.lich.find((x) => x.mode === l.mode)
      return moi ? { ...l, ...moi, lanKeTiep: sau(60 * 6) } : l
    })
    if (b.gioiHan) gioiHanGia = b.gioiHan
    return HttpResponse.json({ lich: lichGia, gioiHan: gioiHanGia } satisfies LichTong)
  }),
  http.post('/api/v1/kb-web/schedules/:mode/run', ({ params }) => {
    const mode = String(params['mode'])
    if (viecGia.some((v) => v.loai === 'kbweb_run' && v.mode === mode && (v.trangThai === 'queued' || v.trangThai === 'running')))
      return loi(409, 'KB_WEB_DANG_CHAY', 'Lượt này đang chờ hoặc đang chạy')
    return HttpResponse.json(xepViec('kbweb_run', mode, null), { status: 202 })
  }),

  http.get('/api/v1/kb-web/projects', () => HttpResponse.json(duAnGia)),
  http.get('/api/v1/kb-web/projects/:code', ({ params }) => {
    const d = duAnGia.find((x) => x.code === params['code'])
    if (!d) return loi(404, 'KB_WEB_DU_AN_KHONG_TON_TAI', 'Không có dự án này')
    if (d.code === 'NPTTL') return HttpResponse.json({ ...CHI_TIET, muc: mucGia(true) } satisfies ChiTietDuAn)
    return HttpResponse.json({ code: d.code, ten: d.ten, muc: mucGia(false), mucAn: [], bai: [], dangChay: d.dangChay } satisfies ChiTietDuAn)
  }),
  http.post('/api/v1/kb-web/projects/:code/refresh', async ({ params, request }) => {
    const { mode } = (await request.json()) as { mode: 'init' | 'rebuild' }
    return HttpResponse.json(xepViec('kbweb_project', mode, String(params['code'])), { status: 202 })
  }),
  http.post('/api/v1/kb-web/projects/:code/items', () => new HttpResponse(null, { status: 204 })),
  http.post('/api/v1/kb-web/projects/:code/pages', () => new HttpResponse(null, { status: 204 })),

  http.get('/api/v1/kb-web/jobs', ({ request }) => {
    const ngay = Number(new URL(request.url).searchParams.get('ngay') ?? 7)
    const tu = Date.now() - ngay * 86_400_000
    return HttpResponse.json(viecGia.filter((v) => new Date(v.taoLuc).getTime() >= tu))
  }),
]
