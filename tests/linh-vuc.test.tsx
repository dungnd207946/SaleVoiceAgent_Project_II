/**
 * Màn «Quản lý lĩnh vực» (`/domains`) — bật/tắt lĩnh vực của agent.
 *
 * Công tắc này hứa HAI việc, và cả hai đều phải kiểm được, vì hứa suông là cách
 * nhanh nhất để một công tắc trở thành thứ trang trí:
 *   ① khối lĩnh vực biến mất khỏi panel Agent (Kiến thức + Kỹ năng của nó)
 *   ② kỹ năng của nó KHÔNG vào `tools.enabled` gửi lên khi xuất bản
 *
 * ② là cái đáng canh nhất: nó xảy ra ở `useBanNhap`, cách màn này hai lớp, và
 * hỏng thì màn hình KHÔNG có triệu chứng nào — chỉ có agent ngoài kia vẫn làm
 * việc mà tenant tưởng đã tắt.
 */
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRouter, RouterProvider } from '@tanstack/react-router'
import { LangProvider } from '../src/i18n'
import { routeTree } from '../src/routeTree.gen'
import { locKyNangTheoLinhVuc } from '../src/features/agent/linhVuc'
import { KY_NANG_TAB_BDS, KY_NANG_CHUNG } from '../src/features/agent/kyNang'
import { server } from '../vitest.setup'

const BDS_BAT = { ma: 'bds', ten: 'Bất động sản', bat: true, soKyNang: 9, coDuLieu: true }
const BDS_TAT = { ...BDS_BAT, bat: false }
const TC_TAT = { ma: 'taichinh', ten: 'Tài chính', bat: false, soKyNang: 0, coDuLieu: false }

/** Sổ lĩnh vực cố định — KHÔNG dùng fake có trạng thái của handlers.ts, để mỗi
 *  test tự khai đúng thế giới của mình và không phụ thuộc thứ tự chạy. */
function datLinhVuc(ds: unknown[]) {
  server.use(http.get('/api/v1/linh-vuc', () => HttpResponse.json(ds)))
}

function boot(duong: string) {
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [duong] }),
  })
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <RouterProvider router={router} />
      </LangProvider>
    </QueryClientProvider>,
  )
}

describe('màn Quản lý lĩnh vực', () => {
  it('hiện mỗi lĩnh vực một hàng, kèm số kỹ năng và tình trạng dữ liệu', async () => {
    datLinhVuc([BDS_BAT, TC_TAT])
    boot('/domains')

    expect(await screen.findByText('chưa có dữ liệu để agent tra')).toBeInTheDocument()
    expect(screen.getByText('đã có dữ liệu')).toBeInTheDocument()
    expect(screen.getByRole('switch', { name: 'Bất động sản' })).toBeChecked()
    expect(screen.getByRole('switch', { name: 'Tài chính' })).not.toBeChecked()
  })

  /*
   * ĐÃ XOÁ: bài canh câu «phần agent chỉ đổi sau lần Lưu và áp dụng kế tiếp».
   *
   * Dải cảnh báo đó bị bỏ khỏi màn (người dùng chốt 2026-08-09), nên bài này
   * không còn thứ để canh. Xoá chứ không sửa thành `not.toBeInTheDocument()`:
   * một bài khẳng định "câu này KHÔNG có" là khoá cứng một quyết định biên tập,
   * và ngày ai đó muốn nói lại độ trễ thì nó chỉ đứng chắn đường.
   *
   * Cái MẤT ĐI là một lời hứa, không phải một dòng chữ: kỹ năng của lĩnh vực
   * đang tắt vẫn bị lọc lúc xuất bản (`useBanNhap.ts`), nên độ trễ vẫn còn thật
   * — giờ chỉ là không màn nào nói ra. Xem chú thích trong `QuanLyLinhVuc.tsx`.
   */

  it('tắt hết thì cảnh báo agent chỉ còn ba kỹ năng chung', async () => {
    datLinhVuc([BDS_TAT, TC_TAT])
    boot('/domains')
    expect(await screen.findByText(/Không lĩnh vực nào đang bật/)).toBeInTheDocument()
  })

  it('bấm công tắc thì PATCH đúng mã và đúng giá trị', async () => {
    let than: unknown = null
    datLinhVuc([BDS_BAT, TC_TAT])
    server.use(
      http.patch('/api/v1/linh-vuc/:ma', async ({ params, request }) => {
        const body = (await request.json()) as { bat: boolean }
        than = { ma: params['ma'], bat: body.bat }
        return HttpResponse.json({ ...BDS_TAT })
      }),
    )
    boot('/domains')

    await userEvent.click(await screen.findByRole('switch', { name: 'Bất động sản' }))
    await waitFor(() => expect(than).toEqual({ ma: 'bds', bat: false }))
  })

  it('PATCH hỏng thì báo lỗi, KHÔNG im lặng nhận là đã đổi', async () => {
    datLinhVuc([BDS_BAT, TC_TAT])
    server.use(http.patch('/api/v1/linh-vuc/:ma', () => new HttpResponse(null, { status: 500 })))
    boot('/domains')

    await userEvent.click(await screen.findByRole('switch', { name: 'Bất động sản' }))
    expect(await screen.findByText(/Chưa đổi được/)).toBeInTheDocument()
  })
})

describe('lĩnh vực TẮT thì khối của nó rời panel Agent', () => {
  it('bật ⇒ có khối «Bất động sản» với Kiến thức + Kỹ năng + Kịch bản', async () => {
    datLinhVuc([BDS_BAT, TC_TAT])
    boot('/agent')

    const p = within(await screen.findByRole('navigation', { name: 'Agent' }))
    expect(p.getByText('Bất động sản')).toBeInTheDocument()
    expect(p.getByRole('link', { name: /Kỹ năng/ })).toBeInTheDocument()
    expect(p.getByRole('link', { name: /Kịch bản/ })).toBeInTheDocument()
    expect(p.getByRole('link', { name: /Dữ liệu ngoài/ })).toBeInTheDocument()
  })

  it('tắt ⇒ mất cả nhãn khối lẫn ba mục trong nó', async () => {
    datLinhVuc([BDS_TAT, TC_TAT])
    boot('/agent')

    const p = within(await screen.findByRole('navigation', { name: 'Agent' }))

    // `waitFor`, KHÔNG assert thẳng: `useNavGroups` cố ý coi "danh sách chưa
    // về" là "bật hết" (xem chú thích ở đó), nên lần render ĐẦU vẫn có khối —
    // nó chỉ rời đi khi query lĩnh vực trả lời. Assert ngay lập tức sẽ đọc đúng
    // khoảnh khắc trước đó và đỏ vì một lý do không phải lý do đang kiểm.
    await waitFor(() => expect(p.queryByText('Bất động sản')).not.toBeInTheDocument())
    expect(p.queryByRole('link', { name: /Kỹ năng/ })).not.toBeInTheDocument()
    expect(p.queryByRole('link', { name: /Kịch bản/ })).not.toBeInTheDocument()
    expect(p.queryByRole('link', { name: /Dữ liệu ngoài/ })).not.toBeInTheDocument()
    // Khối chung vẫn còn — tắt lĩnh vực không đụng phần chung.
    expect(p.getByText('Cấu hình chung')).toBeInTheDocument()
  })
})

/**
 * `locKyNangTheoLinhVuc` là hàm thuần — test thẳng, không qua UI. Nó là chỗ lời
 * hứa «agent không dùng nữa» thành sự thật, nên nó đáng có bài riêng chứ không
 * chỉ được chạy ké qua một bài dựng cả màn.
 */
describe('lọc kỹ năng theo lĩnh vực đang tắt', () => {
  const TEN_BDS = KY_NANG_TAB_BDS.map((k) => k.ten)

  it('lĩnh vực tắt ⇒ kỹ năng của nó rời khỏi tools.enabled', () => {
    const truoc = [...KY_NANG_CHUNG, ...TEN_BDS]
    const sau = locKyNangTheoLinhVuc(truoc, [BDS_TAT, TC_TAT])
    expect(sau).toEqual([...KY_NANG_CHUNG])
  })

  it('lĩnh vực bật ⇒ không bỏ gì cả', () => {
    const truoc = [...KY_NANG_CHUNG, ...TEN_BDS]
    expect(locKyNangTheoLinhVuc(truoc, [BDS_BAT, TC_TAT])).toEqual(truoc)
  })

  it('kỹ năng CHUNG không bao giờ bị tắt theo lĩnh vực', () => {
    // Tra tài liệu · cập nhật khách · chuyển người thật là việc agent làm bất kể
    // đang nói chuyện về lĩnh vực nào — tắt hết lĩnh vực cũng không được mất.
    const sau = locKyNangTheoLinhVuc([...KY_NANG_CHUNG], [BDS_TAT, TC_TAT])
    expect(sau).toEqual([...KY_NANG_CHUNG])
  })
})
