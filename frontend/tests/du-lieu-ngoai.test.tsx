/**
 * Màn «Dữ liệu ngoài» (`/du-lieu-ngoai`) — bốn thứ phải giữ:
 *   · Tổng quan nói bằng số thật của workspace, không bày mã kỹ thuật (`nightly`, `kbweb_run`).
 *   · Nguồn nào cũng xoá được; công tắc bật/tắt nằm ở cột đầu.
 *   · Người không có `kb_web.write` thấy mọi thứ nhưng không có nút sửa/chạy.
 *   · Lượt thử nguồn là bất đồng bộ: hiện «đang thử» rồi mới hiện kết quả.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { FAKE_SESSION } from '../src/lib/msw/handlers'
import { server } from '../vitest.setup'
import { guiCau, hienCau } from '../src/features/kb-web/cauTim'
import { thanMuc } from '../src/features/kb-web/hoSo'
import { daChayLai, ketQuaViec } from '../src/features/kb-web/nhan'
import type { Viec } from '../src/features/kb-web/api'
import { luc, sapToi } from '../src/features/kb-web/thoiGian'

function boot(duong = '/du-lieu-ngoai') {
  const router = createRouter({ routeTree, history: createMemoryHistory({ initialEntries: [duong] }) })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

describe('màn Dữ liệu ngoài', () => {
  it('tab Tổng quan hiện số dự án có hồ sơ và việc đang chạy bằng chữ thường', async () => {
    boot()
    expect(await screen.findByText('Dự án có hồ sơ')).toBeInTheDocument()
    expect(screen.getByText('3 / 4')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cập nhật ngay' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Viết lại toàn bộ hồ sơ' })).not.toBeInTheDocument()
    expect(screen.getByText('Bài báo thu trong 7 ngày')).toBeInTheDocument()
    expect(screen.queryByText('Hồ sơ cũ nhất')).not.toBeInTheDocument()
    expect(screen.queryByText(/Lần tự chạy kế tiếp/)).not.toBeInTheDocument()
    expect(screen.getByText('Tạo hồ sơ')).toBeInTheDocument()
    expect(screen.getByText('Cập nhật hồ sơ')).toBeInTheDocument()
    expect(screen.getByText('Đang chạy')).toBeInTheDocument()
    expect(screen.getByText('NOBLE CRYSTAL TÂY HỒ')).toBeInTheDocument()
    expect(screen.getAllByText('Đặng Thành').length).toBeGreaterThan(0)
    expect(screen.queryByText(/u_fake_dang/)).not.toBeInTheDocument()
    expect(screen.queryByText('nightly')).not.toBeInTheDocument()
    expect(screen.queryByText('kbweb_run')).not.toBeInTheDocument()
    expect(screen.getByText('Không kết nối được dịch vụ xử lý, thử lại sau')).toBeInTheDocument()
    expect(screen.queryByText(/ConnectError/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Google/)).not.toBeInTheDocument()
    expect(screen.getByText('Nhật ký chạy')).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: 'Nhật ký' })).not.toBeInTheDocument()
  })

  it('nhật ký có cột chi phí khi BE trả tiền, ẩn cột khi không có quyền xem', async () => {
    boot()
    expect(await screen.findByRole('columnheader', { name: 'Chi phí' })).toBeInTheDocument()
    expect(screen.getByText('1.841 ₫')).toBeInTheDocument()
    expect(screen.getByText('6.370 ₫')).toBeInTheDocument()
  })

  it('không có quyền xem chi phí thì không có cột Chi phí', async () => {
    const res = await fetch('/api/v1/kb-web/jobs?limit=200')
    const ds = ((await res.json()) as Viec[]).map((v) => ({ ...v, chiPhi: null }))
    server.use(http.get('/api/v1/kb-web/jobs', () => HttpResponse.json(ds)))
    boot()
    expect(await screen.findByText('Nhật ký chạy')).toBeInTheDocument()
    await screen.findByText('NOBLE CRYSTAL TÂY HỒ')
    expect(screen.queryByRole('columnheader', { name: 'Chi phí' })).not.toBeInTheDocument()
  })

  it('tab Nguồn: mọi nguồn xoá được, công tắc ở ô đầu, tình trạng là một nhãn', async () => {
    boot('/du-lieu-ngoai?tab=nguon')
    const hang = (await screen.findByText('Sunshine Group')).closest('tr') as HTMLElement
    expect(within(hang).getByRole('button', { name: 'Xoá' })).toBeInTheDocument()
    const cafef = screen.getByText('CafeF').closest('tr') as HTMLElement
    expect(within(cafef).getByRole('button', { name: 'Xoá' })).toBeInTheDocument()
    expect(within(cafef.querySelector('td') as HTMLElement).getByRole('switch', { name: 'CafeF' })).toBeChecked()
    expect(within(cafef).getByText('Hoạt động')).toBeInTheDocument()
    expect(screen.queryByText('Theo dõi')).not.toBeInTheDocument()
  })

  it('tab Chủ đề: bấm Thêm chủ đề mở hộp thoại, không có hàng Tổng quan', async () => {
    boot('/du-lieu-ngoai?tab=chu-de')
    await userEvent.click(await screen.findByRole('button', { name: 'Thêm chủ đề' }))
    expect(screen.getByRole('dialog', { name: 'Thêm chủ đề' })).toBeInTheDocument()
    expect(screen.queryByText('luôn có')).not.toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Mô tả' })).toBeInTheDocument()
    expect(screen.queryByRole('columnheader', { name: 'Loại' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Áp dụng/ })).not.toBeInTheDocument()
  })

  it('thử nguồn: hiện đang thử rồi kết quả, và nút thêm khi dùng được', async () => {
    server.use(
      http.get('/api/v1/kb-web/sources/probe/:token', () =>
        HttpResponse.json({
          trangThai: 'xong',
          ketQua: {
            trangThai: 'ok',
            ghiChu: '',
            soBai: 86,
            soTrangThu: 2,
            soTrangDoc: 2,
            daCo: false,
            deXuat: {
              domain: 'cafeland.vn',
              ten: 'CafeLand',
              cheDo: 'http',
              theoDoi: 'news',
              rss: ['https://cafeland.vn/rss'],
              sitemapIndex: '',
              newsSitemaps: [],
              categoryPages: [],
              articlePattern: '',
            },
          },
        }),
      ),
    )
    boot('/du-lieu-ngoai?tab=nguon')
    const o = await screen.findByPlaceholderText('https://cafeland.vn/tin-tuc/')
    await userEvent.type(o, 'cafeland.vn')
    await userEvent.click(screen.getByRole('button', { name: 'Thử nguồn' }))
    expect(await screen.findByText(/86 bài bất động sản/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thêm vào nguồn' })).toBeEnabled()
  })

  it('không có kb_web.write thì không có nút sửa và công tắc bị khoá', async () => {
    server.use(
      http.get('/api/v1/me', () =>
        HttpResponse.json({ ...FAKE_SESSION, actions: FAKE_SESSION.actions.filter((a) => a !== 'kb_web.write') }),
      ),
    )
    boot('/du-lieu-ngoai?tab=nguon')
    const cafef = (await screen.findByText('CafeF')).closest('tr') as HTMLElement
    expect(within(cafef).getByRole('switch', { name: 'CafeF' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Thử nguồn' })).not.toBeInTheDocument()
  })

  it('tab Lịch hiện ba nhịp với chữ «mỗi» và nút Chạy ngay', async () => {
    boot('/du-lieu-ngoai?tab=lich')
    expect(await screen.findByText('Cập nhật mỗi tuần')).toBeInTheDocument()
    expect(screen.getByText('Viết lại toàn bộ hồ sơ')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Chạy ngay' })).toHaveLength(3)
    const tuan = screen.getByText('Cập nhật mỗi tuần').closest('div.rounded-lg') as HTMLElement
    await userEvent.click(within(tuan).getByRole('button', { name: 'Sửa' }))
    const hop = screen.getByRole('dialog', { name: 'Sửa lịch «Cập nhật mỗi tuần»' })
    expect(within(hop).getByRole('button', { name: 'T3', pressed: true })).toBeInTheDocument()
    expect(screen.queryByText('Giới hạn chi phí')).not.toBeInTheDocument()
    await userEvent.click(within(hop).getByRole('button', { name: 'Huỷ' }))
    const vietLai = screen.getByText('Viết lại toàn bộ hồ sơ').closest('div.rounded-lg') as HTMLElement
    await userEvent.click(within(vietLai).getByRole('button', { name: 'Sửa' }))
    expect(within(screen.getByRole('dialog')).getByRole('option', { name: 'Mỗi 5 tháng' })).toBeInTheDocument()
    expect(screen.queryByText(/hằng/)).not.toBeInTheDocument()
  })

  it('tab Dự án mở được chi tiết với mục hồ sơ và bài báo', async () => {
    boot('/du-lieu-ngoai?tab=du-an')
    const ten = await screen.findByRole('button', { name: 'NOBLE PALACE TÂY THĂNG LONG' })
    expect(screen.queryByRole('button', { name: 'Cập nhật' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Tạo hồ sơ' })).not.toBeInTheDocument()
    expect(screen.queryByText('mới')).not.toBeInTheDocument()
    await userEvent.click(ten)
    expect(await screen.findByText(/chủ đề có dữ liệu/)).toBeInTheDocument()
    expect(screen.getAllByText('Chưa có dữ liệu').length).toBeGreaterThan(0)
    expect(await screen.findByText('Giao thông công cộng')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Ẩn mục' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Bỏ ẩn' }).length).toBeGreaterThan(0)
    const muc = screen.getByRole('button', { name: /Giao thông công cộng/ })
    expect(muc).toHaveAttribute('aria-expanded', 'false')
    const truoc = document.querySelectorAll('p.whitespace-pre-line').length
    await userEvent.click(muc)
    expect(muc).toHaveAttribute('aria-expanded', 'true')
    expect(document.querySelectorAll('p.whitespace-pre-line').length).toBe(truoc + 1)
    await userEvent.click(muc)
    expect(muc).toHaveAttribute('aria-expanded', 'false')
    await waitFor(() => expect(screen.getByRole('tab', { name: /Bài báo đã thu/ })).toBeInTheDocument())
    await userEvent.click(screen.getByRole('tab', { name: /Bài báo đã thu/ }))
    expect(await screen.findByText('đã loại')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dùng lại' })).toBeInTheDocument()
  })
})

describe('liên kết với màn khác', () => {
  it('link có duAn mở thẳng hồ sơ của dự án đó', async () => {
    boot('/du-lieu-ngoai?tab=du-an&duAn=NPTTL')
    expect(await screen.findByText(/chủ đề có dữ liệu/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '‹ Danh sách dự án' })).toBeInTheDocument()
  })

  it('hồ sơ dự án hiện đúng các chủ đề đang bật ở tab Chủ đề, bằng tên của tab đó', async () => {
    boot('/du-lieu-ngoai?tab=du-an&duAn=NPTTL')
    expect(await screen.findByText('3 / 7 chủ đề có dữ liệu', { exact: false })).toBeInTheDocument()
    for (const ten of ['Giao thông công cộng', 'Pháp lý dự án', 'Dự án lân cận', 'Giáo dục', 'Cho thuê và dòng tiền'])
      expect(screen.getByText(ten)).toBeInTheDocument()
    expect(screen.queryByText('Việc làm và hành chính')).not.toBeInTheDocument()
    expect(screen.queryByText('Tiện ích – Giáo dục')).not.toBeInTheDocument()
    expect(screen.getAllByText('Chưa có dữ liệu')).toHaveLength(3)
    expect(screen.getByText('đang ẩn')).toBeInTheDocument()
  })

  it('màn dự án ở Kiến thức có dòng hồ sơ dữ liệu ngoài dẫn sang đúng dự án', async () => {
    server.use(
      http.get('/api/v1/kb-web/projects', () =>
        HttpResponse.json([{ code: 'VHOP2', ten: 'Vinhomes Ocean Park 2', soMuc: 13, capNhatLuc: null, dangChay: false, viecGanNhat: null }]),
      ),
    )
    boot('/pform?code=VHOP2')
    const dong = await screen.findByTestId('ho-so-ngoai')
    expect(dong).toHaveTextContent('13 mục')
    expect(within(dong).getByRole('link', { name: 'Xem hồ sơ' }).getAttribute('href')).toContain('duAn=VHOP2')
  })

  it('dòng hồ sơ dữ liệu ngoài ở Kiến thức ghi số chủ đề có dữ liệu trên tổng', async () => {
    server.use(
      http.get('/api/v1/kb-web/projects', () =>
        HttpResponse.json([
          { code: 'VHOP2', ten: 'Vinhomes Ocean Park 2', soMuc: 13, soChuDe: 16, capNhatLuc: null, dangChay: false, viecGanNhat: null },
        ]),
      ),
    )
    boot('/pform?code=VHOP2')
    expect(await screen.findByTestId('ho-so-ngoai')).toHaveTextContent('13 / 16 chủ đề có dữ liệu')
  })
})

describe('backend cũ chưa trả ten/an/soChuDe', () => {
  it('bảng dự án và hồ sơ vẫn hiện được, tên mục lấy từ nhãn', async () => {
    server.use(
      http.get('/api/v1/kb-web/projects', () =>
        HttpResponse.json([{ code: 'NPTTL', ten: 'NOBLE PALACE TÂY THĂNG LONG', soMuc: 2, capNhatLuc: null, dangChay: false, viecGanNhat: null }]),
      ),
      http.get('/api/v1/kb-web/projects/NPTTL', () =>
        HttpResponse.json({
          code: 'NPTTL',
          ten: 'NOBLE PALACE TÂY THĂNG LONG',
          muc: [{ nhan: 'Tiện ích – Y tế', noiDung: 'Tiện ích – Y tế: Bệnh viện [1].', nguon: [], capNhatLuc: null }],
          mucAn: ['Tiện ích – Y tế'],
          bai: [],
          dangChay: false,
        }),
      ),
    )
    boot('/du-lieu-ngoai?tab=du-an')
    expect(await screen.findByRole('button', { name: 'NOBLE PALACE TÂY THĂNG LONG' })).toBeInTheDocument()
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'NOBLE PALACE TÂY THĂNG LONG' }))
    expect(await screen.findByText('Tiện ích – Y tế')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Bỏ ẩn' })).toBeInTheDocument()
    expect(screen.getByText(/0 \/ 1 chủ đề có dữ liệu/)).toBeInTheDocument()
  })
})

describe('hàm thuần', () => {
  const viec = (id: number, trangThai: Viec['trangThai'], extra: Partial<Viec> = {}): Viec => ({
    id,
    loai: 'kbweb_project',
    mode: 'rebuild',
    duAn: 'SRC',
    trangThai,
    nguoi: 'u',
    taoLuc: '2026-10-05T07:00:00Z',
    batDau: null,
    ketThuc: null,
    soLuong: 18,
    thongDiep: '',
    ...extra,
  })

  it('lượt lỗi đã có lượt sau cùng việc thì không cần Chạy lại', () => {
    const ds = [viec(3, 'success'), viec(2, 'failed'), viec(1, 'failed', { duAn: 'NPLB' })]
    expect([...daChayLai(ds)]).toEqual([2])
  })

  it('kết quả viết bằng chữ, không bày thông điệp nội bộ', () => {
    expect(ketQuaViec(viec(1, 'success'))).toMatchObject({ nhan: 'Thành công', chiTiet: '18 mục hồ sơ' })
    expect(ketQuaViec(viec(1, 'success', { loai: 'kbweb_probe', tinhTrangNguon: 'timeout', soLuong: 0 })).nhan).toBe('Không phản hồi')
  })

  it('đổi biến {project}/{location} sang chữ người đọc và ngược lại', () => {
    expect(hienCau('giá bán {project} ở {location}')).toBe('giá bán {dự án} ở {khu vực}')
    expect(guiCau('giá bán {dự án} ở {khu vực}')).toBe('giá bán {project} ở {location}')
  })

  it('thân mục bỏ hai dòng hệ thống và nhãn chủ đề', () => {
    expect(
      thanMuc({
        nhan: 'Tổng quan',
        ten: 'Tổng quan',
        noiDung: '(Cập nhật 05/10/2026)\n[Dự án X — Y]\nTổng quan: Dự án lớn [1].',
        nguon: [],
        capNhatLuc: null,
        an: false,
      }),
    ).toBe('Dự án lớn [1].')
  })

  it('mốc thời gian: hôm nay / hôm qua / ngày', () => {
    const bayGio = new Date(2026, 9, 5, 10, 0)
    expect(luc(new Date(2026, 9, 5, 1, 10).toISOString(), bayGio)).toBe('hôm nay 01:10')
    expect(luc(new Date(2026, 9, 4, 16, 20).toISOString(), bayGio)).toBe('hôm qua 16:20')
    expect(luc(new Date(2026, 9, 3, 1, 10).toISOString(), bayGio)).toBe('03/10 01:10')
    expect(sapToi(new Date(2026, 9, 6, 1, 10).toISOString(), bayGio)).toBe('mai 01:10')
    expect(sapToi(new Date(2026, 9, 7, 4, 0).toISOString(), bayGio)).toBe('T4 07/10 04:00')
    expect(luc(null)).toBe('—')
  })
})
