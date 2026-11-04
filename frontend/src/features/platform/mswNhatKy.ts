/**
 * Fake MSW của `GET /api/v1/audit` — CÓ xử lý `limit`/`cursor`/`nhom`/`from`/`to`/`may`
 * như BE, để test màn kiểm được hành vi thật (bật công tắc → hàng agent hiện;
 * «Tải thêm» → nối trang). Cùng lối `features/realestate/msw.ts`.
 *
 * Con trỏ của fake = base64(id) — đủ vì dữ liệu giả có `luc` giảm cùng `id`;
 * BE thật mã hoá cả `(luc, id)`, FE không đọc ruột cursor nên khác nhau vô hại.
 */

import { http, HttpResponse } from 'msw'
import type { DongNhatKy, TrangNhatKy } from './nhatKy'
import { tienToCua } from './so-hanh-dong'

const HAI = { actorId: 'u_fake_hai', actorTen: 'Hải Đỗ', actorEmail: 'hai@anphu.vn' }
const DANG = { actorId: 'u_fake_dang', actorTen: 'Đặng Văn Dũng', actorEmail: 'dang@anphu.vn' }
const MAY = { actorId: 'agent', actorTen: null, actorEmail: null }
const CRON = { actorId: 'cron', actorTen: null, actorEmail: null }
const HE_THONG = { actorId: '', actorTen: null, actorEmail: null }
const CONG_NAP = { actorId: 'ingest_token:7', actorTen: null, actorEmail: null }
const DA_XOA = { actorId: 'u_da_xoa', actorTen: null, actorEmail: null }

type Ai = Pick<DongNhatKy, 'actorId' | 'actorTen' | 'actorEmail'>
/** Chu kỳ 15 mẫu; hàng đầu (i = 0) là «Sửa dự án» của Hải — test màn bám vào đó. */
const MAU: readonly [string, Ai, Record<string, unknown>][] = [
  ['realestate.project.update', HAI, { project_code: 'NT2', truong: ['name', 'price'] }],
  ['thanh_vien.moi', DANG, { email: 'moi@anphu.vn', role: 'CSKH' }],
  ['agent.runtime_credentials', MAY, { agent_key_id: 3 }],
  ['ingest.tenant_im_lang', CRON, { gio_im_lang: 26 }],
  ['kb.upload', DA_XOA, { ten_file: 'bang-gia-q3.pdf' }],
  ['agent_config.publish', DANG, { version: 12, truong_da_doi: ['persona', 'tools'] }],
  ['role.sua', DANG, { role_id: 'r_cskh', truong: ['actions'] }],
  ['linh_vuc.bat', HAI, { ma: 'bds' }],
  ['workspace.doi_ten', DANG, { ten_cu: 'An Phu', ten_moi: 'An Phú Land' }],
  ['billing.price_version_kich_hoat', DANG, { price_version: 'pv_2026_q3' }],
  ['ingest.token_tao', HE_THONG, { label: 'CRM nội bộ' }],
  ['ingest.nghi_mat_tich', CONG_NAP, { so_ban_ghi: 3 }],
  ['kb.delete', HAI, { ten_file: 'cu.docx' }],
  ['realestate.unit.create', HAI, { project_code: 'NT2', unit_code: 'A-12-05' }],
  ['agent.phat_khoa', DANG, { label: 'prod' }],
]

const SO_HANG = 45
const MOC = Date.UTC(2026, 7, 25, 10, 0)
const BUOC_MS = 5.5 * 3600 * 1000 // ~10 ngày cho 45 hàng

export const NHAT_KY_GIA: readonly DongNhatKy[] = Array.from({ length: SO_HANG }, (_, i) => {
  const [hanhDong, ai, chiTiet] = MAU[i % MAU.length] as (typeof MAU)[number]
  return { id: 1000 - i, luc: new Date(MOC - i * BUOC_MS).toISOString(), hanhDong, ...ai, chiTiet }
})

function ngayVN(iso: string): string {
  return new Date(new Date(iso).getTime() + 7 * 3600 * 1000).toISOString().slice(0, 10)
}

export function locNhatKyGia(hang: readonly DongNhatKy[], p: URLSearchParams): TrangNhatKy {
  const limit = Number(p.get('limit') ?? 50)
  const nhom = p.get('nhom')?.split(',') ?? null
  const may = p.get('may') === 'true'
  const from = p.get('from')
  const to = p.get('to')
  const cursor = p.get('cursor')
  let ds = hang.filter((h) => may || h.actorId !== 'agent')
  if (nhom) ds = ds.filter((h) => nhom.includes(tienToCua(h.hanhDong)))
  if (from) ds = ds.filter((h) => ngayVN(h.luc) >= from)
  if (to) ds = ds.filter((h) => ngayVN(h.luc) < to)
  if (cursor) {
    const sau = Number(atob(cursor))
    ds = ds.filter((h) => h.id < sau)
  }
  const trang = ds.slice(0, limit)
  const cuoi = trang[trang.length - 1]
  return { items: trang, nextCursor: ds.length > limit && cuoi ? btoa(String(cuoi.id)) : null }
}

export const nhatKyHandlers = [
  http.get('/api/v1/audit', ({ request }) =>
    HttpResponse.json(locNhatKyGia(NHAT_KY_GIA, new URL(request.url).searchParams)),
  ),
]
