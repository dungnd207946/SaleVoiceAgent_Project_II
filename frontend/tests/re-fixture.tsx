/**
 * Đồ dùng chung cho 5 file test của M4 (KB Bất động sản).
 *
 * KHÔNG phải file `.test.tsx` nên vitest không chạy nó như một suite (`include`
 * là `tests/**\/*.test.{ts,tsx}`).
 *
 * `boot()` dựng CẢ router thật, không render component trực tiếp: điều hướng giữa
 * ba màn của M4 đi bằng search param (`/pform?code=…`), và đó là thứ dễ vỡ nhất
 * trong thiết kế này — render component với prop dựng tay sẽ bỏ qua đúng phần
 * cần canh.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory, createRouter } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { server } from '../vitest.setup'

/**
 * Trả về ROUTER, không phải kết quả `render`: bài test nào cần đi từ dự án này
 * sang dự án khác mà KHÔNG unmount màn (đúng cảnh làm state của dự án cũ rớt
 * sang dự án mới) phải gọi `router.navigate` — dựng lại một router thứ hai là
 * dựng lại cả cây, tức bỏ qua đúng chỗ cần canh.
 */
export function boot(duong: string) {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [duong] }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
  return router
}

/** Một dự án ĐỦ dữ liệu (name + region + overview) — publish được. */
export const DU_AN = {
  id: 1,
  projectCode: 'VHOP2',
  name: 'Vinhomes Ocean Park 2',
  category: ['chung_cu', 'biet_thu'],
  region: 'Hà Nội',
  address: 'Gia Lâm',
  investor: 'Vinhomes',
  developer: 'Vinhomes',
  totalLandAreaM2: 4580000,
  floorAreaM2: 1200000,
  buildDensityPct: 21.5,
  productScale: '3 toà · 1.240 căn',
  amenities: 'Biển hồ nước mặn',
  ownershipForm: 'Sổ hồng lâu dài',
  handoverStandard: [
    { item: 'Tiêu chuẩn chung', material: '', brand: '', origin: '', note: 'Bàn giao thô' },
  ],
  totalInvestmentVnd: 87000000000000,
  salePhase: 'dang_ban',
  overview: 'Đại đô thị biển hồ phía đông Hà Nội.',
  link360: 'https://kuula.co/share/x',
  coverMediaId: null,
  mapMediaId: null,
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

/** Dự án THIẾU `overview` — dùng để canh badge và cổng chặn publish. */
export const DU_AN_THIEU = {
  ...DU_AN,
  id: 2,
  projectCode: 'THIEU1',
  name: 'Dự án chưa xong',
  // Thiếu `region` — trường bắt buộc CÒN LẠI sau khi `overview` rời luật
  // completeness 2026-08-18. `overview` vẫn để rỗng vì nó không còn ảnh hưởng gì:
  // fixture này chỉ cần đại diện "dự án chưa đủ dữ liệu để phát hành".
  region: '',
  overview: '',
  status: 'draft',
}

export const PHAN_KHU = {
  id: 10,
  projectCode: 'VHOP2',
  zoneCode: 'ZURICH',
  name: 'Zurich',
  category: 'chung_cu',
  productScale: '2 toà',
  overview: 'Phân khu Zurich.',
  coverMediaId: null,
  mapMediaId: null,
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

export const CAN = {
  id: 41,
  projectCode: 'VHOP2',
  zoneCode: 'ZURICH',
  zoneName: 'Zurich',
  unitCode: 'ZR-A-1203',
  productType: 'chung_cu',
  bedrooms: 3,
  block: 'A',
  floor: 12,
  numFloors: 1,
  direction: 'dong_nam',
  areaBuiltM2: 78.5,
  areaWallM2: 82,
  areaLandM2: null,
  priceVnd: 5600000000,
  pricePerM2Vnd: 71337579,
  saleStatus: 'available',
  imageUrl: null,
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

/**
 * Giá trị CÓ THẬT trong quỹ căn — nguồn mục của hai ô lọc «loại sản phẩm» và
 * «hướng». Khớp `CAN` ở trên; bài nào cần một quỹ căn khác thì truyền
 * `datApiDoc({ facets: … })`, nếu không dropdown sẽ không có mục để chọn.
 */
export const TOA = {
  id: 7,
  projectCode: 'VHOP2',
  zoneCode: 'ZURICH',
  buildingCode: 'A',
  name: 'Toà A',
  numFloors: 30,
  numBasements: 2,
  unitsPerFloor: 12,
  elevatorsPassenger: 4,
  elevatorsService: 1,
  carSlots: 250,
  motoSlots: 900,
  ceilingHeightM: 3.1,
  facing: 'dong_nam',
  salePhase: 'dang_ban',
  amenities: 'Sảnh khách sạn',
  overview: 'Toà nhìn ra hồ.',
  status: 'published',
  unitCount: 120,
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

export const FACET_CAN = { productType: ['chung_cu'], direction: ['dong_nam'] }

export const TAI_LIEU = {
  id: 70,
  projectCode: 'VHOP2',
  loai: 'khac',
  title: 'Chính sách bán hàng Q3',
  body: 'Nội dung chính sách…',
  fileUrl: 'tenants/rew/kb-bds/abc/csbh.pdf',
  bodyChoDuyet: false,
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

export const MEDIA = {
  id: 90,
  projectCode: 'VHOP2',
  zoneCode: null,
  unitCode: null,
  contentType: 'image',
  category: 'tong_quan',
  caption: 'Toàn cảnh',
  fileName: 'toan-canh.webp',
  mediaUrl: 'tenants/rew/kb-bds/sha/toan-canh.webp',
  thumbUrl: null,
  contentHash: 'sha',
  uploadedBy: 'u_re',
  status: 'published',
  createdAt: '2026-08-01T00:00:00Z',
  updatedAt: '2026-08-01T00:00:00Z',
}

/**
 * `{items, nextCursor, total}` — khuôn phân trang của mọi danh sách M4.
 *
 * `total` mặc định `items.length` để mọi test có sẵn không phải sửa — chỉ test
 * nào cần `total` khác `items.length` (còn hàng ở trang khác) mới truyền tường minh.
 */
export function trang<T>(items: T[], nextCursor: string | null = null, total?: number) {
  return { items, nextCursor, total: total ?? items.length }
}

interface Gia {
  projects?: unknown
  zones?: unknown
  units?: unknown
  documents?: unknown
  media?: unknown
  facets?: unknown
  buildings?: unknown
  project?: unknown
  kbStatus?: unknown
  enrichStatus?: unknown
  draftCaption?: string
}

/**
 * Handler cho cả cây đọc của một dự án.
 *
 * Khai TRỌN cây (kể cả nhánh test đó không dùng) vì `vitest.setup.ts` bật
 * `onUnhandledRequest: 'error'`: một tab con gọi endpoint chưa khai sẽ làm test
 * đỏ ở một chỗ không liên quan tới thứ đang kiểm.
 */
export function datApiDoc(g: Gia = {}) {
  server.use(
    http.get('/api/v1/projects', () => HttpResponse.json(g.projects ?? trang([DU_AN]))),
    // `kb-status` PHẢI khai TRƯỚC `:code`: MSW lấy handler khớp ĐẦU TIÊN, và
    // `:code` nhận cả chuỗi `kb-status` — đứng sau là badge nhận 404.
    http.get('/api/v1/projects/kb-status', () => HttpResponse.json(g.kbStatus ?? [KB_DA_NAP])),
    http.get('/api/v1/projects/:code/enrich-status', () => HttpResponse.json(g.enrichStatus ?? [])),
    http.post('/api/v1/projects/:code/documents/:id/approve', () =>
      HttpResponse.json({ approved: true }, { status: 202 }),
    ),
    http.post('/api/v1/media/draft-caption', () =>
      HttpResponse.json({ jobId: 3, state: 'queued' }, { status: 202 }),
    ),
    http.get('/api/v1/media/draft-caption/:jobId', () =>
      HttpResponse.json({ state: 'success', caption: g.draftCaption ?? 'Mô tả máy viết nháp.' }),
    ),
    http.get('/api/v1/projects/:code', ({ params }) =>
      params.code === 'VHOP2'
        ? HttpResponse.json(g.project ?? DU_AN)
        : HttpResponse.json(
            { error: { code: 'PROJECT_NOT_FOUND', message: 'Không tìm thấy dự án' } },
            { status: 404 },
          ),
    ),
    http.get('/api/v1/projects/:code/zones', () => HttpResponse.json(g.zones ?? trang([PHAN_KHU]))),
    http.get('/api/v1/projects/:code/buildings', () =>
      HttpResponse.json(g.buildings ?? { items: [TOA], total: 1 }),
    ),
    // `units/facets` PHẢI khai TRƯỚC `units/:id` — cùng bẫy thứ tự với
    // `kb-status` ở trên: `:id` khớp luôn chuỗi `facets`.
    http.get('/api/v1/projects/:code/units/facets', () => HttpResponse.json(g.facets ?? FACET_CAN)),
    http.get('/api/v1/projects/:code/units', () => HttpResponse.json(g.units ?? trang([CAN]))),
    http.get('/api/v1/projects/:code/units/:id', () => HttpResponse.json(CAN)),
    http.get('/api/v1/projects/:code/documents', () =>
      HttpResponse.json(g.documents ?? trang([TAI_LIEU])),
    ),
    http.get('/api/v1/projects/:code/media', () => HttpResponse.json(g.media ?? trang([MEDIA]))),
  )
}

/** «Xong xuôi» — chỉ báo im lặng, không hiện gì. Đây là trạng thái BÌNH THƯỜNG. */
export const KB_DA_NAP = {
  projectCode: 'VHOP2',
  indexing: false,
  hasError: false,
  total: 12,
  done: 12,
}

export function kbDangNap(ma = 'VHOP2') {
  return { projectCode: ma, indexing: true, hasError: false, total: 12, done: 5 }
}

export function kbLoi(ma = 'VHOP2') {
  return { projectCode: ma, indexing: false, hasError: true, total: 12, done: 4 }
}

/** Thân lỗi 422 có cấu trúc, đúng khuôn `api/loi.py:_than_loi_validate`. */
export function loi422(fields: { field: string; reason: string }[]) {
  return HttpResponse.json(
    {
      error: {
        code: 'VALIDATION_ERROR',
        message: `Dữ liệu gửi lên không hợp lệ (${fields.length} lỗi): ${fields.map((f) => f.field).join(', ')}`,
        fields,
      },
    },
    { status: 422 },
  )
}

/** Giá trị của một ô ở chế độ xem (`ReadField`: `dt` nhãn, `dd` giá trị). */
export function giaTriXem(nhan: string | RegExp): HTMLElement {
  const dt = screen
    .getAllByRole('term')
    .find((el) =>
      typeof nhan === 'string' ? el.textContent === nhan : nhan.test(el.textContent ?? ''),
    )
  if (!dt) throw new Error(`Không thấy ô xem «${String(nhan)}»`)
  return dt.nextElementSibling as HTMLElement
}

/**
 * Bấm nút Sửa ở hàng tab của hồ sơ dự án — một nút mở khoá mọi tab và màn chi tiết (2026-10-08).
 * Trả về dải báo «Đang sửa dự án» để chờ tới khi chế độ sửa đã bật.
 */
export async function moSuaDuAn() {
  await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
  return screen.findByTestId('dai-dang-sua')
}

/** `/uform?unit=…` của một căn ĐÃ CÓ mở ra ở chế độ xem; cùng nút Sửa ở hàng tab. */
export async function moSuaCan() {
  await userEvent.click(await screen.findByRole('button', { name: 'Sửa' }))
  return screen.findByRole('spinbutton', { name: /Số phòng ngủ/ })
}
