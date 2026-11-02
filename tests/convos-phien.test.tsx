import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  RouterProvider,
  createMemoryHistory,
  createRootRoute,
  createRouter,
} from '@tanstack/react-router'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { HttpResponse, http } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { PhienKhach } from '@/features/ops/components/PhienKhach'
import { server } from '../vitest.setup'
import { boGiaLap, giaLapManHinh } from './man-hinh'

/**
 * `PhienKhach` có `<Link to="/convos">` (nút «Tất cả khách») — `Link` của
 * tanstack-router cần một `RouterProvider` làm tổ tiên, nếu không `useLinkProps`
 * đọc router từ context ra `null` và render nổ ngay
 * (`Cannot read properties of null (reading 'isServer')`, đo được khi chạy đúng
 * bản `render(<QueryClientProvider>…</QueryClientProvider>)` mà brief chép ra:
 * cả 11 test đỏ vì lỗi này, không phải vì logic màn sai). Cùng cách dựng router
 * tối giản mà `tests/convos-list.test.tsx` đã dùng cho `KhachRow` — KHÔNG đi qua
 * `routeTree.gen.ts` thật.
 */
function dung(phone = '0912448111', phienMoDau?: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const rootRoute = createRootRoute({
    component: () => (
      <QueryClientProvider client={qc}>
        {/* `phienMoDau?: string` không kèm `| undefined` — `exactOptionalPropertyTypes`
            cấm gán tường minh `undefined`, trải object có điều kiện như route thật. */}
        <PhienKhach phone={phone} {...(phienMoDau !== undefined ? { phienMoDau } : {})} />
      </QueryClientProvider>
    ),
  })
  const router = createRouter({
    routeTree: rootRoute,
    history: createMemoryHistory({ initialEntries: ['/'] }),
  })
  return render(<RouterProvider router={router} />)
}

/** Chờ panel chi tiết hiện ĐÚNG phiên `id`. Mã phiên không còn in ra màn
 *  (2026-09-24), nên đọc từ `data-session` của dòng thông tin phiên. */
async function choPhien(id: string) {
  await waitFor(() => expect(screen.getByTestId('dong-phien')).toHaveAttribute('data-session', id))
}

describe('màn chi tiết một khách', () => {
  it('liệt kê các phiên, mới nhất trên đầu', async () => {
    dung()
    expect(await screen.findByText(/27\/07\/2026/)).toBeInTheDocument()
    expect(screen.getByText(/21\/07\/2026/)).toBeInTheDocument()
  })

  it('phiên không có lượt nào hiện «Chưa có tin nhắn», không phải ô trống', async () => {
    // Cột phiên hiện `tinNhanDau` (lượt seq=0) thay cho `summary` — đổi 07/08 vì
    // panel "Tóm tắt của agent" ở màn chi tiết đã trùng ý với summary ở đây.
    dung()
    expect(await screen.findByText(/chưa có tin nhắn/i)).toBeInTheDocument()
  })

  it('chip kênh của phiên mang sắc RIÊNG cho Chat và Voice, không cùng một xám', async () => {
    // Dùng chung `components/ui/ChipKenh` với card feedback ở `/quality` — hai
    // màn phải cùng màu cho cùng một kênh, nên bài này canh phía ops còn
    // `quality-review-card.test.tsx` canh phía kia. jsdom không tính CSS nên
    // chỉ khoá được lớp token (cùng lối `tests/o-chon.test.ts`).
    dung()
    const chat = await screen.findByText('Chat')
    expect(chat).toHaveClass('bg-badge-kenh-chat-bg', 'text-badge-kenh-chat-fg')
    expect(screen.getByText('Voice')).toHaveClass(
      'bg-badge-kenh-voice-bg',
      'text-badge-kenh-voice-fg',
    )
  })

  it('phiên có source lạ/null KHÔNG hiện chip — danh sách này có bộ lọc theo kênh', async () => {
    dung()
    await screen.findByText('Chat')
    // Fixture có đúng một phiên `source: null` (agent trước `0916`).
    expect(screen.getAllByText(/^(Chat|Voice)$/)).toHaveLength(2)
  })

  it('ketThuc NULL thì KHÔNG in «0:00» ở đâu cả', async () => {
    dung()
    await screen.findByText(/27\/07\/2026/)
    expect(screen.queryByText('0:00')).not.toBeInTheDocument()
  })

  it('render lượt nói theo đúng thứ tự seq', async () => {
    dung()
    const bong = await screen.findAllByTestId('bong-bong')
    expect(bong[0]).toHaveTextContent('Còn căn nào 3 phòng ngủ')
    expect(bong[1]).toHaveTextContent('Dạ hiện Ocean Park 2 còn 4 căn')
  })

  it('role lạ vẫn HIỆN, và hiện dạng DÒNG HỆ THỐNG chứ không phải bong bóng', async () => {
    // Hai nửa của yêu cầu, phải assert cả hai. Chỉ kiểm "có chữ đó trên màn" thì
    // một regression render nó thành bong bóng chat bình thường vẫn xanh — mà đó
    // đúng là thứ yêu cầu này cấm: `role` lạ không được trông như lời của khách
    // hay của agent.
    dung()
    const dong = await screen.findByText(/một role không nằm trong ba giá trị/i)
    expect(dong).toBeInTheDocument()
    expect(dong).not.toHaveAttribute('data-testid', 'bong-bong')
    expect(dong.className).toContain('text-center')
  })

  it('mỗi lượt NÓI RA ai nói — không chỉ bằng màu + căn trái/phải (WCAG 1.3.1)', async () => {
    dung()
    const bong = await screen.findAllByTestId('bong-bong')
    expect(bong[0]).toHaveTextContent(/^Khách: Còn căn nào 3 phòng ngủ/)
    expect(bong[1]).toHaveTextContent(/^Agent: Dạ hiện Ocean Park 2 còn 4 căn/)
    // Tiền tố chỉ cho trình đọc màn hình — mắt đã đọc được từ màu + căn lề.
    expect(within(bong[0]!).getByText('Khách:')).toHaveClass('sr-only')
    const dong = screen.getByText(/một role không nằm trong ba giá trị/i)
    expect(dong).toHaveTextContent(/^Hệ thống: /)
  })

  it('header khách hiện CHỮ CÁI dù backend trả avatar — cùng khuôn danh sách khách', async () => {
    // (2026-08-25) Lịch sử hội thoại thôi dùng avatar backend — chữ cái từ ĐẦU +
    // CUỐI của tên, lấy từ phiên CÓ TÊN. Backend vẫn trả `avatar`, FE thôi đọc.
    const AVATAR_THU =
      "data:image/svg+xml;charset=utf-8,%3Csvg%20xmlns%3D'http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg'%2F%3E"
    server.use(
      http.get('/api/v1/convos/khach/:phone/phien', () =>
        HttpResponse.json([
          {
            sessionId: 's-anh-1',
            phone: '0912448111',
            ten: 'Nguyễn Minh Anh',
            avatar: AVATAR_THU,
            batDau: '2026-07-27T14:22:00+07:00',
            ketThuc: '2026-07-27T14:23:48+07:00',
            soLuot: 6,
            tinNhanDau: 'Còn căn nào 3PN không em?',
            summary: null,
            duAn: null,
            tenDuAn: null,
            daChuyen: false,
            runningVersion: null,
            source: 'chat',
          },
        ]),
      ),
    )
    const { container } = dung()
    await screen.findByText('Nguyễn Minh Anh')
    expect(screen.getByText('NA')).toBeInTheDocument()
    expect(container.querySelector('img')).not.toBeInTheDocument()
  })

  it('lượt có meta méo vẫn hiện bong bóng, chỉ mất phần công cụ', async () => {
    // Ghi đè bằng `server.use` chứ không nhét vào fake dùng chung: đây là ca của
    // riêng test này, và fake chung đã mang đủ sáu ca biên khác.
    server.use(
      http.get('/api/v1/convos/phien/:sessionId', () =>
        HttpResponse.json({
          phien: {
            sessionId: 's-meo',
            ten: 'Méo',
            batDau: '2026-07-27T14:22:00+07:00',
            ketThuc: null,
            soLuot: 2,
            summary: null,
            duAn: null,
            daChuyen: false,
            runningVersion: null,
          },
          luot: [
            {
              seq: 0,
              role: 'user',
              content: 'câu hỏi bình thường',
              taoLuc: '2026-07-27T14:22:00+07:00',
              meta: 'không phải object',
            },
            {
              seq: 1,
              role: 'assistant',
              content: 'câu trả lời bình thường',
              taoLuc: '2026-07-27T14:23:00+07:00',
              meta: { tool_calls: 'không phải mảng' },
            },
          ],
          skillCalls: [],
        }),
      ),
    )
    dung()
    expect(await screen.findByText('câu hỏi bình thường')).toBeInTheDocument()
    expect(screen.getByText('câu trả lời bình thường')).toBeInTheDocument()
    expect(screen.queryByText(/không phải mảng/)).not.toBeInTheDocument()
  })

  it('cuộc gọi tool ghép từ hai hàng thành MỘT khối, kết quả đóng mặc định, tham số có preview', async () => {
    // Ca chốt 07/08: một cuộc gọi tool thật là HAI hàng (assistant rỗng +
    // tool), không phải một hàng như bản cũ tưởng. Tên hàm hiện ngay.
    //
    // Đổi 07/08: tham số giờ có PREVIEW một dòng hiện SẴN (không phải bấm mới
    // thấy) — yêu cầu "muốn show cả arguments" không nên bắt người dùng đoán có
    // tham số hay không rồi mới bấm. Kết quả thì VẪN đóng: nó có thể rất dài
    // (`{"total":4,"unit_ids":[...]}` là bản ngắn — kết quả thật có thể dài hơn
    // nhiều), tràn ra giữa hội thoại là đúng thứ thiết kế đóng-mặc-định ban đầu
    // muốn tránh.
    dung()
    await screen.findByText('Còn căn nào 3 phòng ngủ dưới 6 tỷ ở Ocean Park 2 không em?')

    expect(await screen.findByText('search_units')).toBeInTheDocument()
    // Preview MỘT DÒNG (JSON.stringify gọn, không cách sau dấu `:`) — hiện sẵn.
    expect(
      screen.getByText('{"project":"VOP2","max_price":6000000000,"bedrooms":3}'),
    ).toBeInTheDocument()
    // Kết quả vẫn đóng cho tới khi bấm.
    expect(screen.queryByText(/"total"/)).not.toBeInTheDocument()
    // Bản ĐẸP (nhiều dòng, có cách sau `:`) của tham số cũng vẫn đóng — chỉ
    // preview một dòng là hiện sẵn, không phải cả khối.
    expect(screen.queryByText(/"project": "VOP2"/)).not.toBeInTheDocument()

    await userEvent.click(screen.getByText('search_units'))

    expect(await screen.findByText(/"project": "VOP2"/)).toBeInTheDocument()
    expect(screen.getByText(/"total": 4/)).toBeInTheDocument()
  })

  it('hàng tool mồ côi (không hàng assistant nào khai) vẫn HIỆN, không biến mất', async () => {
    // Lịch sử bị cắt đầu, hoặc dữ liệu lệch: một kết quả không có yêu cầu nào
    // đi trước trong đúng phiên này. Phải vẫn hiện — im lặng bỏ là mất dữ liệu.
    server.use(
      http.get('/api/v1/convos/phien/:sessionId', () =>
        HttpResponse.json({
          phien: {
            sessionId: 's-moi-coi',
            ten: null,
            batDau: null,
            ketThuc: null,
            soLuot: 1,
            summary: null,
            duAn: null,
            daChuyen: false,
            runningVersion: null,
          },
          luot: [
            {
              seq: 0,
              role: 'tool',
              content: '{"ok":true}',
              taoLuc: '2026-07-27T14:22:00+07:00',
              meta: { name: 'huy_lich_hen', tool_call_id: 'call-khong-ai-khai' },
            },
          ],
          skillCalls: [],
        }),
      ),
    )
    dung()
    expect(await screen.findByText('huy_lich_hen')).toBeInTheDocument()
  })

  it('assistant rỗng cả nội dung và tool_calls thì KHÔNG render bong bóng trống', async () => {
    server.use(
      http.get('/api/v1/convos/phien/:sessionId', () =>
        HttpResponse.json({
          phien: {
            sessionId: 's-rong',
            ten: null,
            batDau: null,
            ketThuc: null,
            soLuot: 2,
            summary: null,
            duAn: null,
            daChuyen: false,
            runningVersion: null,
          },
          luot: [
            {
              seq: 0,
              role: 'user',
              content: 'còn không',
              taoLuc: '2026-07-27T14:22:00+07:00',
              meta: {},
            },
            {
              seq: 1,
              role: 'assistant',
              content: '',
              taoLuc: '2026-07-27T14:22:05+07:00',
              meta: {},
            },
          ],
          skillCalls: [],
        }),
      ),
    )
    dung()
    await screen.findByText('còn không')
    expect(screen.getAllByTestId('bong-bong')).toHaveLength(1)
  })

  it('mốc giờ có mặt trong DOM nhưng ẩn bằng opacity, KHÔNG bị display:none', async () => {
    // Nếu ẩn bằng display:none thì lúc hover cả cột tin nhắn bị xô xuống 16px —
    // chuyển động mượt cỡ nào cũng không cứu được cảm giác đó (spec §5.3).
    dung()
    const gio = await screen.findAllByTestId('moc-gio')
    expect(gio[0]).toBeInTheDocument()
    expect(gio[0]!.className).toContain('opacity-0')
    expect(gio[0]!.className).not.toContain('hidden')
  })

  it('mốc giờ mở được bằng BÀN PHÍM, không chỉ bằng chuột', async () => {
    // Ràng buộc 2 của §5.3. jsdom không áp CSS thật nên không quan sát được
    // opacity đổi; thứ kiểm được — và là thứ hỏng nếu ai xoá — là hai điều:
    // lượt nhận được focus, và lớp `group-focus-within` có mặt cạnh `group-hover`.
    // Nói rõ giới hạn này ở đây để người sau không tưởng test đã chứng minh hiệu ứng.
    dung()
    const gio = await screen.findAllByTestId('moc-gio')
    expect(gio[0]!.className).toContain('group-focus-within/msg:opacity-100')

    const bong = screen.getAllByTestId('bong-bong')
    bong[0]!.focus()
    expect(document.activeElement).toBe(bong[0])
  })

  it('theme.css còn giữ hai luật cho máy không chuột và người giảm chuyển động', async () => {
    // Ràng buộc 3 và 4 của §5.3 sống trong CSS, mà jsdom không chạy CSS. Cổng
    // này là cổng NGUỒN, không phải cổng hành vi: xoá một trong hai khối media
    // query thì nó đỏ. Không hơn — nó không chứng minh trình duyệt xử lý đúng.
    // KHÔNG viết `new URL('../src/styles/theme.css', import.meta.url)`: Vite
    // dò đúng cú pháp `new URL(chuỗi, import.meta.url)` để coi nó là tham chiếu
    // asset và đổi sang URL dev-server (`http://localhost:.../…`) — `readFile`
    // của Node từ chối URL đó với "The URL must be of scheme file:" (đo được
    // khi viết brief theo đúng cú pháp gốc, xem báo cáo). Ghép đường dẫn qua
    // `fileURLToPath` ở hai dòng riêng để tránh đúng mẫu Vite tìm.
    const thuMuc = path.dirname(fileURLToPath(import.meta.url))
    const css = await readFile(path.resolve(thuMuc, '../src/styles/theme.css'), 'utf8')
    expect(css).toMatch(/@media \(hover: none\)[\s\S]*?\.moc-gio[\s\S]*?opacity:\s*1/)
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.moc-gio/)
  })

  it('bấm sang phiên 0 lượt thì hiện câu giải thích, không phải màn trắng', async () => {
    dung()
    await screen.findByText(/27\/07\/2026/)
    await userEvent.click(screen.getByText(/21\/07\/2026/))
    expect(await screen.findByText(/chưa có bản ghi hội thoại/i)).toBeInTheDocument()
  })

  it('phiên không lượt nào có tool_calls thì dùng skill_calls mức phiên, dồn cuối', async () => {
    dung()
    await screen.findByText(/27\/07\/2026/)
    await userEvent.click(screen.getByText(/21\/07\/2026/))
    expect(await screen.findByText(/công cụ agent đã gọi/i)).toBeInTheDocument()
    expect(screen.getByText(/create_appointment/)).toBeInTheDocument()
  })

  it('header lấy tên của phiên mới nhất, không hiện «null»', async () => {
    dung()
    expect(await screen.findByText('Nguyễn Minh Anh')).toBeInTheDocument()
    expect(screen.queryByText(/null/i)).not.toBeInTheDocument()
  })

  it('nhóm ẩn danh nói rõ nó KHÔNG phải một người', async () => {
    dung('_')
    expect(await screen.findByText(/không phải một người/i)).toBeInTheDocument()
  })

  it('phien mang đúng phone của khách đang xem', async () => {
    dung()
    // `PHIEN_ANH_1`/`PHIEN_ANH_2` (msw.ts) đều `phone: '0912448111'`, khớp
    // `dung()` mặc định mở khách này — không có gì trên màn HIỆN trực tiếp
    // `phone` (đã hiện sẵn ở header), test này chỉ canh KIỂU DỮ LIỆU không vỡ
    // khi component render (nếu `Phien.phone` bị đọc sai tên field, React sẽ
    // KHÔNG throw — nên đây là cổng type-level, xem Step 2, test này chỉ xác
    // nhận component vẫn render bình thường sau khi field mới thêm vào).
    expect(await screen.findByText(/27\/07\/2026/)).toBeInTheDocument()
  })

  it('truyền phienMoDau thì chọn ĐÚNG phiên đó, không phải phiên mới nhất', async () => {
    // PHIEN_GIA['0912448111'] (msw.ts) = [PHIEN_ANH_1 (27/07), PHIEN_ANH_2 (21/07)]
    // — mặc định (không phienMoDau) chọn PHIEN_ANH_1 (mới nhất). Truyền sessionId
    // của PHIEN_ANH_2 phải chọn đúng nó, dù nó KHÔNG phải phiên đầu danh sách.
    dung('0912448111', 's-anh-2')
    await screen.findByText(/21\/07\/2026/)
    // Đợi panel chi tiết tải ĐÚNG phiên s-anh-2 (id hiện ở thanh trên cùng panel
    // chi tiết, nay trên `data-session`) trước khi đếm bong bóng — hàng danh sách của CẢ HAI phiên luôn
    // hiện sẵn bất kể phiên nào đang chọn, nên `findByText(/21\/07\/2026/)` một
    // mình không phân biệt được panel chi tiết đã chọn đúng phiên hay còn đang
    // tải phiên khác (s-anh-1) — đếm bong bóng ngay sau đó sẽ đọc SAI 0 một
    // cách trùng hợp lúc panel còn "Đang tải…", che mất phiên mặc định sai.
    await choPhien('s-anh-2')
    // PHIEN_ANH_2 có `soLuot: 0` — transcript rỗng, khác PHIEN_ANH_1 (có 6 lượt).
    expect(screen.queryAllByTestId('bong-bong')).toHaveLength(0)
  })

  it('phienMoDau không thuộc danh sách của khách này thì rơi về phiên mới nhất, không lỗi', async () => {
    dung('0912448111', 'sess-khong-ton-tai')
    expect(await screen.findByText(/27\/07\/2026/)).toBeInTheDocument()
  })

  it('phiên có feedback thì hiện sao + comment cạnh header', async () => {
    server.use(
      http.get('/api/v1/agent/feedback', () =>
        HttpResponse.json({
          items: [
            {
              id: 1,
              session_id: 's-anh-1',
              rating: 4,
              comment: 'Khá ổn',
              created_at: '2026-08-12T09:00:00+07:00',
              customer_name: 'Nguyễn Minh Anh',
              phone: '0912448111',
            },
          ],
          next_before_id: null,
          total: 1,
          theo_sao: { '1': 0, '2': 0, '3': 0, '4': 1, '5': 0 },
          diem_trung_binh: 4,
        }),
      ),
    )
    dung()
    await screen.findByText(/27\/07\/2026/)
    expect(await screen.findByText('Khá ổn')).toBeInTheDocument()
  })

  it('phiên KHÔNG có feedback thì không hiện gì thêm, không lỗi', async () => {
    server.use(
      http.get('/api/v1/agent/feedback', () =>
        HttpResponse.json({
          items: [],
          next_before_id: null,
          total: 0,
          theo_sao: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 },
          diem_trung_binh: 0,
        }),
      ),
    )
    dung()
    // Đợi ĐÚNG hàng header của panel chi tiết (nơi badge feedback sẽ chèn vào)
    // đã render xong, KHÔNG chỉ đợi danh sách phiên bên trái (nó tải xong sớm
    // hơn `ct`/`fb` và tới trước, nên một `findByText` trên danh sách rồi
    // `queryByText` đồng bộ ngay sau có thể "qua" một cách giả — kể cả khi
    // badge render lỗi — vì khối chứa `fb.data` còn chưa kịp vẽ. Dòng
    // `dong-phien` (mang `data-session`) là CÙNG hàng với chỗ feedback chèn vào.
    await choPhien('s-anh-1')
    expect(screen.queryByText('Khá ổn')).not.toBeInTheDocument()
  })
})

// ── Hai vùng cuộn riêng (2026-09-24) ─────────────────────────────────────────
// Trước đó cả màn cuộn chung một thanh ở `<main>`: đọc hết một phiên dài mà
// còn nhiều phiên thì trang kéo dài mãi. jsdom không có engine bố cục nên
// không đo được "có cuộn thật không" — các bài dưới canh CẤU TRÚC: danh sách
// phiên và nội dung phiên nằm ở hai vùng `overflow-y-auto` TÁCH RỜI, còn hàng
// tab kênh + dòng thông tin phiên đứng NGOÀI vùng cuộn (không trôi đi).
describe('màn chi tiết một khách — cuộn riêng từng cột', () => {
  it('danh sách phiên và nội dung phiên là hai vùng cuộn tách rời', async () => {
    dung()
    await choPhien('s-anh-1')
    const cuonPhien = screen.getByTestId('cuon-phien')
    const cuonNoiDung = screen.getByTestId('cuon-noi-dung')

    for (const vung of [cuonPhien, cuonNoiDung]) {
      expect(vung).toHaveClass('overflow-y-auto', 'min-h-0', 'flex-1')
    }
    expect(cuonPhien.contains(cuonNoiDung)).toBe(false)
    expect(cuonNoiDung.contains(cuonPhien)).toBe(false)

    // Các hàng phiên nằm TRONG vùng cuộn trái…
    expect(cuonPhien).toContainElement(screen.getByText(/21\/07\/2026/).closest('button'))
    // …còn hàng tab kênh thì KHÔNG — đổi tab không được trôi mất khi cuộn.
    expect(cuonPhien).not.toContainElement(screen.getByRole('tablist'))
    // Dòng thông tin phiên (mã phiên) đứng yên, ngoài vùng cuộn nội dung.
    expect(cuonNoiDung).not.toContainElement(screen.getByTestId('dong-phien'))
  })

  it('đổi phiên ⇒ vùng nội dung là phần tử MỚI (về đầu), kể cả phiên đã có trong cache', async () => {
    dung()
    await choPhien('s-anh-1')
    const vungDau = screen.getByTestId('cuon-noi-dung')

    await userEvent.click(screen.getByText(/21\/07\/2026/))
    await choPhien('s-anh-2')
    // Quay lại phiên ĐẦU — lần này nó đã nằm trong cache nên không qua «Đang
    // tải…». Đây là ca dễ lọt: không có `key={sid}` thì phần tử cũ được dùng
    // lại và giữ nguyên vị trí cuộn của phiên trước.
    const vungHai = screen.getByTestId('cuon-noi-dung')
    await userEvent.click(screen.getByText(/27\/07\/2026/))
    await choPhien('s-anh-1')
    expect(screen.getByTestId('cuon-noi-dung')).not.toBe(vungHai)
    expect(screen.getByTestId('cuon-noi-dung')).not.toBe(vungDau)
  })
})

describe('màn chi tiết một khách — dòng thông tin phiên', () => {
  it('KHÔNG in mã phiên và «config vN», vẫn giữ giờ · thời lượng · số lượt', async () => {
    // PHIEN_ANH_1 (msw.ts): sessionId `s-anh-1`, runningVersion 12, 6 lượt.
    dung()
    await choPhien('s-anh-1')
    const dong = screen.getByTestId('dong-phien')
    expect(dong).not.toHaveTextContent('s-anh-1')
    expect(dong).not.toHaveTextContent(/config/i)
    expect(screen.queryByText(/config v12/i)).not.toBeInTheDocument()
    expect(dong).toHaveTextContent('27/07/2026')
    expect(dong).toHaveTextContent('6 lượt')
  })
})

describe('PhienKhach — mobile', () => {
  afterEach(boGiaLap)

  it('mặc định CHỈ danh sách phiên; chọn phiên ⇒ CHỈ transcript; «‹ Các phiên» quay về', async () => {
    giaLapManHinh(375)
    dung()
    const nutPhien = await screen.findAllByRole('button', { name: /lượt/ })
    expect(screen.queryByTestId('dong-phien')).not.toBeInTheDocument()
    await userEvent.click(nutPhien[0]!)
    expect(await screen.findByTestId('dong-phien')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /lượt/ })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '‹ Các phiên' }))
    expect(screen.queryByTestId('dong-phien')).not.toBeInTheDocument()
    expect((await screen.findAllByRole('button', { name: /lượt/ })).length).toBeGreaterThan(0)
  })

  it('mở link có phienMoDau ⇒ vào thẳng transcript của đúng phiên đó', async () => {
    giaLapManHinh(375)
    // 's-anh-2' = phiên thứ hai của 0912448111 trong fake — cùng giá trị test
    // phienMoDau sẵn có (dòng ~373) dùng; KHÔNG phải phiên đầu, nên chứng minh
    // được là mở đúng phiên được hỏi chứ không rơi về mặc định.
    dung('0912448111', 's-anh-2')
    await choPhien('s-anh-2')
    expect(screen.queryByRole('button', { name: /lượt/ })).not.toBeInTheDocument()
  })

  it('desktop (jsdom trần) vẫn hiện cả hai cột như cũ', async () => {
    dung()
    expect(await screen.findByTestId('dong-phien')).toBeInTheDocument()
    expect((await screen.findAllByRole('button', { name: /lượt/ })).length).toBeGreaterThan(0)
  })
})

describe('thông tin khách (chân dung)', () => {
  afterEach(() => {
    boGiaLap()
    vi.restoreAllMocks()
  })

  const CHAN_DUNG = {
    hoSo: {
      name: 'Hải',
      full_name: 'Trần Thu Hải',
      gender: 'F',
      project_interest: 'OCEAN_PARK_2',
      budget: '3 tỷ',
      bedroom_count: '2PN',
      audience: 'end_user',
      interest_level: 'cao',
      is_buyer: true,
      notes: 'làm ở Long Biên; con sắp vào lớp 1',
      noble_user_id: 'nu_123',
    },
    ghiNho: 'Chị Hải tìm căn 2PN để ở, ngân sách khoảng 3 tỷ.',
    tinHieu: ['co_ngan_sach', 'hoi_tien', 'tin_hieu_moi'],
    capNhatLuc: '2026-07-27T14:30:00+07:00',
  }

  function datChanDung(body: object, dem?: { n: number }) {
    server.use(
      http.get('/api/v1/convos/khach/:phone/chan-dung', () => {
        if (dem) dem.n += 1
        return HttpResponse.json(body)
      }),
    )
  }

  it('desktop: cột bên phải hiện nhu cầu, ghi nhớ, ghi chú và tín hiệu đã khai thác', async () => {
    datChanDung(CHAN_DUNG)
    dung()
    const cot = await screen.findByRole('complementary', { name: 'Thông tin khách' })
    expect(
      await within(cot).findByText('Chị Hải tìm căn 2PN để ở, ngân sách khoảng 3 tỷ.'),
    ).toBeInTheDocument()
    expect(within(cot).getByText('3 tỷ')).toBeInTheDocument()
    expect(within(cot).getByText('2PN')).toBeInTheDocument()
    // Mã dự án đổi thành TÊN khi một phiên của khách có cùng mã.
    expect(within(cot).getByText('Ocean Park 2')).toBeInTheDocument()
    expect(within(cot).getByText('Trần Thu Hải')).toBeInTheDocument()
    expect(within(cot).getByText('Nữ')).toBeInTheDocument()
    expect(within(cot).getByText('Cao')).toBeInTheDocument()
    expect(within(cot).getByText('Khách mua')).toBeInTheDocument()
    expect(within(cot).getByText('làm ở Long Biên')).toBeInTheDocument()
    expect(within(cot).getByText('con sắp vào lớp 1')).toBeInTheDocument()
    expect(within(cot).getByText('Có ngân sách')).toBeInTheDocument()
    expect(within(cot).getByText('Hỏi giá')).toBeInTheDocument()
    expect(within(cot).getByText(/27\/07\/2026/)).toBeInTheDocument()
    // Khoá nội bộ không ra màn.
    expect(cot).not.toHaveTextContent('nu_123')
  })

  it('trường nhu cầu chưa có hiện «Chưa khai thác» — sale biết còn thiếu gì để hỏi', async () => {
    datChanDung(CHAN_DUNG)
    dung()
    const cot = await screen.findByRole('complementary', { name: 'Thông tin khách' })
    const muc = (await within(cot).findByText('Mục đích')).closest('div')!
    expect(muc).toHaveTextContent('Chưa khai thác')
    // Khối cá nhân KHÔNG liệt kê ô trống — chỉ hiện thứ đã có.
    expect(within(cot).queryByText('Nơi làm việc')).not.toBeInTheDocument()
  })

  it('tín hiệu lạ agent mới thêm hiện NGUYÊN VĂN, không bị bỏ', async () => {
    datChanDung(CHAN_DUNG)
    dung()
    const cot = await screen.findByRole('complementary', { name: 'Thông tin khách' })
    expect(await within(cot).findByText('tin_hieu_moi')).toBeInTheDocument()
  })

  it('agent chưa ghi gì ⇒ một câu nói thẳng, không phải một tường «Chưa khai thác»', async () => {
    datChanDung({ hoSo: {}, ghiNho: null, tinHieu: [], capNhatLuc: null })
    dung()
    const cot = await screen.findByRole('complementary', { name: 'Thông tin khách' })
    expect(await within(cot).findByText(/agent chưa ghi nhận thông tin nào/i)).toBeInTheDocument()
    expect(within(cot).queryByText('Chưa khai thác')).not.toBeInTheDocument()
  })

  it('API lỗi ⇒ báo không tải được, transcript vẫn chạy', async () => {
    server.use(
      http.get('/api/v1/convos/khach/:phone/chan-dung', () =>
        HttpResponse.json({ error: { code: 'X', message: 'hỏng' } }, { status: 500 }),
      ),
    )
    dung()
    expect(await screen.findByText(/không tải được thông tin khách/i)).toBeInTheDocument()
    expect(await screen.findAllByTestId('bong-bong')).not.toHaveLength(0)
  })

  it('nhóm «Chưa có số» ⇒ không có chân dung, không gọi API', async () => {
    const dem = { n: 0 }
    datChanDung(CHAN_DUNG, dem)
    dung('_')
    await screen.findByText(/phiên ẩn danh/)
    expect(screen.queryByRole('complementary', { name: 'Thông tin khách' })).not.toBeInTheDocument()
    expect(dem.n).toBe(0)
  })

  it('dưới desktop: KHÔNG có cột riêng, nút «i» mở panel thay nội dung rồi quay lại', async () => {
    giaLapManHinh(900)
    datChanDung(CHAN_DUNG)
    dung()
    await choPhien('s-anh-1')
    expect(screen.queryByRole('complementary', { name: 'Thông tin khách' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Thông tin khách' }))
    const cot = await screen.findByRole('complementary', { name: 'Thông tin khách' })
    expect(await within(cot).findByText('3 tỷ')).toBeInTheDocument()
    expect(screen.queryByTestId('dong-phien')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '‹ Hội thoại' }))
    expect(await screen.findByTestId('dong-phien')).toBeInTheDocument()
  })

  it('tầng desktop nhưng tấm nền HẸP (nav đang mở) ⇒ không cột thứ ba, dùng nút', async () => {
    // jsdom không bố cục — giả bề rộng tấm nền. Dưới `RONG_BA_COT` (1120) ba cột
    // chừa cho đoạn hội thoại quá ít chỗ.
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 1000,
    } as DOMRect)
    datChanDung(CHAN_DUNG)
    dung()
    await choPhien('s-anh-1')
    expect(screen.queryByRole('complementary', { name: 'Thông tin khách' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Thông tin khách' })).toBeInTheDocument()
  })

  it('tấm nền đủ rộng ⇒ cột thứ ba, không có nút', async () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      width: 1300,
    } as DOMRect)
    datChanDung(CHAN_DUNG)
    dung()
    expect(
      await screen.findByRole('complementary', { name: 'Thông tin khách' }),
    ).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Thông tin khách' })).not.toBeInTheDocument()
  })

  it('mobile: bấm nút «i» từ danh sách phiên cũng mở được', async () => {
    giaLapManHinh(375)
    datChanDung(CHAN_DUNG)
    dung()
    await screen.findAllByRole('button', { name: /lượt/ })
    await userEvent.click(screen.getByRole('button', { name: 'Thông tin khách' }))
    const cot = await screen.findByRole('complementary', { name: 'Thông tin khách' })
    expect(await within(cot).findByText('3 tỷ')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /lượt/ })).not.toBeInTheDocument()
  })
})

describe('lead ở trang chi tiết khách', () => {
  const phien = (id: string, bd: string, lead: object) => ({
    sessionId: id,
    ten: 'Nguyễn Minh Anh',
    batDau: bd,
    ketThuc: null,
    soLuot: 3,
    tinNhanDau: 'xin chào',
    summary: null,
    duAn: null,
    tenDuAn: null,
    daChuyen: false,
    runningVersion: null,
    source: 'chat',
    phone: '0912448111',
    ...lead,
  })
  const P1 = phien('p-moi', '2026-07-27T14:00:00+07:00', {
    leadStage: null,
    leadScore: null,
    audience: null,
  })
  const P2 = phien('p-giua', '2026-07-25T14:00:00+07:00', {
    leadStage: 'hen_gap',
    leadScore: 90,
    audience: 'end_user',
  })
  const P3 = phien('p-cu', '2026-07-20T14:00:00+07:00', {
    leadStage: 'lead',
    leadScore: 30,
    audience: null,
  })

  function datApi() {
    server.use(
      http.get('/api/v1/convos/khach/:phone/phien', () => HttpResponse.json([P1, P2, P3])),
      http.get('/api/v1/convos/phien/:id', ({ params }) => {
        const p = [P1, P2, P3].find((x) => x.sessionId === params.id)
        return HttpResponse.json({ phien: p, luot: [], skillCalls: [] })
      }),
    )
  }

  it('ô «Lead hiện tại» = phiên mới nhất CÓ lead (bỏ qua phiên mới nhất không có lead)', async () => {
    datApi()
    dung()
    const o = await screen.findByTestId('lead-hien-tai')
    expect(within(o).getByText('Hẹn gặp')).toBeInTheDocument()
    expect(o.textContent).toContain('90')
    expect(o.textContent).toContain('Khách mua')
  })

  it('từng hàng phiên mang chip của CHÍNH phiên đó; phiên không có lead thì không chip', async () => {
    datApi()
    dung()
    await screen.findByTestId('lead-hien-tai')
    const cot = screen.getByTestId('cuon-phien')
    expect(cot.querySelectorAll('[data-stage]')).toHaveLength(2)
    expect(cot.querySelector('[data-stage="lead"]')).not.toBeNull()
  })

  it('dòng thông tin phiên hiện stage · điểm · đối tượng của phiên đang xem', async () => {
    datApi()
    dung('0912448111', 'p-giua')
    await choPhien('p-giua')
    const dong = screen.getByTestId('dong-phien')
    expect(dong.querySelector('[data-stage="hen_gap"]')).not.toBeNull()
    expect(dong.textContent).toContain('90điểm')
    expect(dong.textContent).toContain('Khách mua')
  })

  it('phiên có stage nhưng thiếu đối tượng ⇒ dòng thông tin không in «null»', async () => {
    datApi()
    dung('0912448111', 'p-cu')
    await choPhien('p-cu')
    expect(screen.getByTestId('dong-phien').textContent).not.toMatch(/null|undefined/)
  })

  it('khách không có lead nào ⇒ không có ô «Lead hiện tại»', async () => {
    server.use(http.get('/api/v1/convos/khach/:phone/phien', () => HttpResponse.json([P1])))
    dung()
    await screen.findByText(/27\/07\/2026/)
    expect(screen.queryByTestId('lead-hien-tai')).not.toBeInTheDocument()
  })

  it('nhóm «Chưa có số» ⇒ KHÔNG có ô «Lead hiện tại» dù từng phiên có lead (nhiều người, không phải một)', async () => {
    const an = { ...P2, phone: null }
    server.use(
      http.get('/api/v1/convos/khach/:phone/phien', () => HttpResponse.json([an])),
      http.get('/api/v1/convos/phien/:id', () =>
        HttpResponse.json({ phien: an, luot: [], skillCalls: [] }),
      ),
    )
    dung('_')
    await screen.findByText(/phiên ẩn danh/)
    expect(screen.queryByTestId('lead-hien-tai')).not.toBeInTheDocument()
    // Chip TỪNG PHIÊN vẫn giữ — lead của một phiên là của một người.
    expect(screen.getByTestId('cuon-phien').querySelector('[data-stage="hen_gap"]')).not.toBeNull()
  })
})
