/**
 * Màn API Keys — khoá đấu nối agent (M8).
 *
 * ĐIỀU BỘ TEST NÀY BẢO VỆ, theo thứ tự quan trọng:
 *
 *   1. Khoá thô hiện ĐÚNG MỘT LẦN và người dùng không đóng dialog được khi chưa
 *      tick đã lưu. Sai chỗ này là người dùng mất một bí mật không lấy lại được —
 *      backend chỉ lưu sha256.
 *   2. Ô khoá chứa ĐÚNG chuỗi khoá trần — không tiền tố `AGENT_API_KEY=`, không
 *      nhãn nào chen vào (đổi 2026-08-24: ô + nút copy icon kiểu OpenAI) — và nút
 *      copy đưa đúng chuỗi ấy vào clipboard. Hai dòng `ENDPOINT_*_URL` đã bỏ
 *      (2026-08-21) — chúng mang mô hình subdomain-mỗi-tenant đã lỗi thời, nên bài
 *      test ở đây canh cả chiều NGƯỢC: chúng không được quay lại.
 *   3. `Escape` KHÔNG đóng dialog khoá (khác mọi dialog khác trong app).
 *
 * RENDER COMPONENT TRỰC TIẾP, không boot router — cùng lý lẽ `members.test.tsx:11`
 * đã viết: đơn vị đang kiểm là `TichHopApiScreen`.
 *
 * `LangProvider` là BẮT BUỘC: `useLang()` ném nếu ở ngoài provider.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LangProvider } from '../src/i18n'
import { TichHopApiScreen } from '../src/features/platform/components/TichHopApiScreen'
import {
  DUONG_TAI_LIEU_GATEWAY,
  TEN_BIEN_KHOA,
  WS_URL_CHAT_MAC_DINH,
  WS_URL_VOICE_MAC_DINH,
} from '../src/features/platform/api'
import {
  ENDPOINT_CHAT_URL_GIA,
  ENDPOINT_VOICE_URL_GIA,
  RESET_KHOA_GIA,
} from '../src/lib/msw/handlers'
import { server } from '../vitest.setup'

function boot() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <TichHopApiScreen />
      </LangProvider>
    </QueryClientProvider>,
  )
}

/** Dialog đang mở. Dùng `within` để không khớp nhầm chữ ở màn phía sau. */
function hopThoai() {
  return within(screen.getByRole('dialog'))
}

/**
 * Chờ `KhoaMoiDialog` mở, trả về ô khoá — `<code>` chứa chuỗi khoá trần.
 *
 * NEO VÀO Ô KHOÁ, KHÔNG VÀO CÂU CẢNH BÁO: màn chính cũng nói "Khoá chỉ hiện một
 * lần lúc tạo" ở phần mô tả, nên `findByText(/chỉ hiện một lần/)` khớp HAI chỗ và
 * ném "Found multiple elements". Ô khoá thì chỉ dialog này có.
 *
 * `findByRole('dialog')` cũng không phân biệt được — `TaoKhoaDialog` và
 * hộp xác nhận Tắt khoá cùng `role="dialog"`.
 *
 * TESTID chứ không `findByText(/^ody_ag_/)`: màn chính in `key_prefix` của mọi
 * khoá cũ ở dạng `ody_ag_7Fk2…`, nên neo bằng chuỗi khoá là khớp nhiều chỗ; và
 * `<code>` không có role nào để neo.
 */
async function choKhoiKhoa(): Promise<HTMLElement> {
  return screen.findByTestId('gia-tri-khoa')
}

/** Ô khoá — chuỗi khoá thô, không tiền tố. */
function giaTriKhoa(): HTMLElement {
  return screen.getByTestId('gia-tri-khoa')
}

beforeEach(() => {
  // Handler giả có state (mảng `KHOA_GIA` bị `unshift`/`splice`), nên không reset
  // là test sau đọc bàn của test trước — cùng khuôn `RESET_USERS_GIA()`.
  RESET_KHOA_GIA()
})

describe('bảng khoá', () => {
  it('hiện nhãn, tiền tố và phân biệt "Chưa dùng" với mốc thời gian', async () => {
    boot()

    expect(await screen.findByText('Pod chat production')).toBeInTheDocument()
    expect(screen.getByText(/ody_ag_7Fk2/)).toBeInTheDocument()
    // Khoá thứ hai có `last_used_at: null` — phải ra chữ, không phải ô trống.
    expect(screen.getByText('Chưa dùng')).toBeInTheDocument()
  })

  it('không khoá nào thì hiện hướng dẫn, và KHÔNG có endpoint nào trên màn', async () => {
    server.use(
      http.get('/api/v1/agent/keys', () =>
        HttpResponse.json({
          endpoint_chat_url: ENDPOINT_CHAT_URL_GIA,
          endpoint_voice_url: ENDPOINT_VOICE_URL_GIA,
          keys: [],
        }),
      ),
    )
    boot()

    expect(await screen.findByText(/Chưa có khoá đấu nối nào/)).toBeInTheDocument()
    // Hai khối ENDPOINT_URL đứng trên bảng khoá ĐÃ BỎ (2026-08-20), và từ
    // 2026-08-21 chúng rời luôn khối env của `KhoaMoiDialog`. Hai URL vẫn về từ
    // `/agent/keys` — hợp đồng backend không đổi — nhưng KHÔNG chỗ nào ở FE hiện
    // chúng nữa.
    expect(screen.queryByText(ENDPOINT_CHAT_URL_GIA)).not.toBeInTheDocument()
    expect(screen.queryByText(ENDPOINT_VOICE_URL_GIA)).not.toBeInTheDocument()
  })

  it('403 nói KHÔNG CÓ QUYỀN, không trả bảng rỗng', async () => {
    server.use(
      http.get('/api/v1/agent/keys', () =>
        HttpResponse.json({ error: { code: 'FORBIDDEN', message: 'x' } }, { status: 403 }),
      ),
    )
    boot()

    expect(await screen.findByText(/không có quyền/i)).toBeInTheDocument()
  })

  it('lỗi hạ tầng nói khác 403 — không hoá trang thành "không có quyền"', async () => {
    server.use(http.get('/api/v1/agent/keys', () => new HttpResponse(null, { status: 500 })))
    boot()

    expect(await screen.findByText(/Không tải được danh sách khoá/)).toBeInTheDocument()
    expect(screen.queryByText(/không có quyền/i)).not.toBeInTheDocument()
  })
})

describe('link tài liệu API', () => {
  it('nằm trong thẻ WS Gateway, dưới hai WS URL, mở tab mới', async () => {
    boot()

    const link = await screen.findByTestId('link-tai-lieu-gateway')
    expect(link).toHaveAttribute('href', DUONG_TAI_LIEU_GATEWAY)
    // Tài liệu là thứ đọc song song với màn quản trị khoá — điều hướng cùng tab
    // là bắt người ta rời màn rồi quay lại.
    expect(link).toHaveAttribute('target', '_blank')
    // `noopener`: trang đích do backend serve nhưng vẫn là tab khác origin logic.
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
  })

  it('đứng SAU hai WS URL trong DOM — thứ tự đọc là URL trước, tài liệu sau', async () => {
    boot()

    const chat = await screen.findByTestId('gia-tri-ws-chat-list')
    const voice = screen.getByTestId('gia-tri-ws-voice-list')
    const link = screen.getByTestId('link-tai-lieu-gateway')

    // Node.compareDocumentPosition: FOLLOWING = 4.
    expect(chat.compareDocumentPosition(link) & 4).toBeTruthy()
    expect(voice.compareDocumentPosition(link) & 4).toBeTruthy()
  })
})

describe('tạo khoá', () => {
  it('ô khoá chỉ chứa chuỗi khoá trần, đúng một dòng', async () => {
    const u = userEvent.setup()
    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))

    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))

    const khoi = await choKhoiKhoa()

    // Dialog khoá mới THAY CHỖ dialog nhãn — không được cùng hiện, cả hai z-70.
    expect(screen.getAllByRole('dialog')).toHaveLength(1)

    // Ô khoá: ĐÚNG chuỗi khoá, không tiền tố, không dấu `=`, không nhãn chen vào.
    expect(khoi.textContent).toMatch(/^ody_ag_/)
    expect(khoi.textContent).not.toContain(TEN_BIEN_KHOA)
    expect(khoi.textContent).not.toContain('=')
    // ĐÚNG một dòng — không `\n` nào.
    expect(khoi.textContent!.split('\n')).toHaveLength(1)

    // Tên biến vẫn phải NÓI RA ở đâu đó trong dialog — bên agent không tự đoán nó.
    expect(hopThoai().getByText(TEN_BIEN_KHOA)).toBeInTheDocument()

    // Hai dòng endpoint đã bỏ. Canh cả TÊN BIẾN lẫn GIÁ TRỊ: bỏ tên mà vẫn in URL
    // trần thì người đọc vẫn mang một địa chỉ chết đi đấu nối.
    const chuTrongDialog = screen.getByRole('dialog').textContent!
    expect(chuTrongDialog).not.toContain('ENDPOINT_CHAT_URL')
    expect(chuTrongDialog).not.toContain('ENDPOINT_VOICE_URL')
    expect(hopThoai().queryByText(ENDPOINT_CHAT_URL_GIA)).not.toBeInTheDocument()
    expect(hopThoai().queryByText(ENDPOINT_VOICE_URL_GIA)).not.toBeInTheDocument()
    // PORTAL_URL cố ý KHÔNG có: nó là hằng số nền tảng ops đặt trong pod.
    expect(chuTrongDialog).not.toContain('PORTAL_URL')
  })

  it('nút Đóng bị chặn tới khi tick "Tôi đã lưu khoá"', async () => {
    const u = userEvent.setup()
    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))
    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))
    await choKhoiKhoa()

    const dong = hopThoai().getByRole('button', { name: 'Đóng' })
    expect(dong).toBeDisabled()

    await u.click(hopThoai().getByLabelText(/Tôi đã lưu khoá/))
    expect(dong).toBeEnabled()
  })

  it('Escape KHÔNG đóng dialog khoá — đóng vô tình là mất khoá thật', async () => {
    const u = userEvent.setup()
    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))
    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))
    await choKhoiKhoa()

    await u.keyboard('{Escape}')

    // Vẫn còn. `TaoKhoaDialog` thì Escape đóng được — khác biệt là có chủ ý.
    expect(screen.getByTestId('gia-tri-khoa')).toBeInTheDocument()
  })

  it('đóng dialog rồi thì khoá thô không còn trong DOM', async () => {
    const u = userEvent.setup()
    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))
    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))
    await choKhoiKhoa()
    const khoaTho = giaTriKhoa().textContent!
    expect(khoaTho).toMatch(/^ody_ag_/)

    await u.click(hopThoai().getByLabelText(/Tôi đã lưu khoá/))
    await u.click(hopThoai().getByRole('button', { name: 'Đóng' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(document.body.textContent).not.toContain(khoaTho)
  })

  it('nút Copy đưa GIÁ TRỊ khoá vào clipboard, không kèm tiền tố AGENT_API_KEY=', async () => {
    // jsdom KHÔNG có `navigator.clipboard`, nhưng `userEvent.setup()` tự cài một
    // bản giả. Nên phải setup TRƯỚC rồi spy lên bản đó.
    //
    // ⚠ Thứ tự này không đổi được: bản trước gọi `vi.stubGlobal('navigator', …)`
    // trước `setup()`, và `setup()` ghi đè `navigator.clipboard` ngay sau — spy
    // không bao giờ được gọi, test đỏ với "called 0 times" mà code thì đúng.
    const u = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()

    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))
    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))
    await choKhoiKhoa()

    await u.click(hopThoai().getByRole('button', { name: /^Copy key$/ }))

    expect(writeText).toHaveBeenCalledOnce()
    const daCopy = writeText.mock.calls[0]![0]
    // Khoá TRẦN: chỗ dán nó thường là một ô nhập, ở đó tiền tố là rác phải xoá tay.
    expect(daCopy).toMatch(/^ody_ag_/)
    expect(daCopy).not.toContain('AGENT_API_KEY')
    expect(daCopy).not.toContain('\n')
    // …và ô khoá trên màn in ĐÚNG chuỗi ấy, không thêm bớt ký tự nào.
    expect(giaTriKhoa().textContent).toBe(daCopy)
    // Copy xong thì nói ra — icon đổi hình người dùng trình đọc màn hình không thấy.
    expect(hopThoai().getByText('Đã copy khoá')).toBeInTheDocument()
    writeText.mockRestore()
  })

  it('dấu ✓ TỰ trở về icon copy — bấm copy được nhiều lần', async () => {
    // Một dấu ✓ đứng vĩnh viễn nói «xong rồi» về một nút vẫn bấm được; ai dán khoá
    // vào hai chỗ (secret manager rồi `.env`) cần bấm lần hai.
    const u = userEvent.setup()
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()

    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))
    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))
    await choKhoiKhoa()

    await u.click(hopThoai().getByRole('button', { name: /^Copy key$/ }))
    expect(hopThoai().getByText('Đã copy khoá')).toBeInTheDocument()

    // Đồng hồ thật (1600ms) — `waitFor` mặc định chờ tới 5s (`vitest.setup.ts`).
    await waitFor(() => expect(hopThoai().queryByText('Đã copy khoá')).not.toBeInTheDocument())

    // …và bấm lại được, lần này clipboard nhận thêm một lượt.
    await u.click(hopThoai().getByRole('button', { name: /^Copy key$/ }))
    expect(writeText).toHaveBeenCalledTimes(2)
    expect(hopThoai().getByText('Đã copy khoá')).toBeInTheDocument()
    writeText.mockRestore()
  })

  it('nút copy có cursor-pointer — Tailwind v4 không tự đặt cho <button>', async () => {
    // jsdom không vẽ nên không rê chuột kiểm được; khoá đúng lớp, cùng lối bài
    // canh bộ lớp hover của `HangHanhDong` ở `tests/thu-agent.test.tsx`.
    const u = userEvent.setup()
    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))
    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))
    await choKhoiKhoa()

    expect(hopThoai().getByRole('button', { name: /^Copy key$/ })).toHaveClass('cursor-pointer')
  })

  it('CHỈ hiện khoá — hai WS URL không có trong dialog (đã có ở thẻ ngoài)', async () => {
    // Đảo chốt 2026-08-24. Không phải đổi ý về nội dung: thẻ «Kết nối WS Gateway»
    // ở chính màn này (thêm 2026-08-25, ĐÚNG MỘT NGÀY SAU) đã hiện cả hai URL kèm
    // nút copy, thường trực. Phép thử của dialog: giá trị nào đóng dialog rồi còn
    // xem lại được thì thuộc về màn, không thuộc về đây.
    const u = userEvent.setup()
    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))
    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))
    await choKhoiKhoa()

    const hop = hopThoai()
    // Tên biến của khoá VẪN phải nói ra — bên agent không tự đoán được chuỗi đó.
    expect(hop.getByText(TEN_BIEN_KHOA)).toBeInTheDocument()

    // Hai URL: không tên biến, không giá trị, không nút copy nào trong dialog.
    for (const ten of ['WS_URL_CHAT', 'WS_URL_VOICE']) {
      expect(hop.queryByText(ten)).not.toBeInTheDocument()
    }
    for (const url of [WS_URL_CHAT_MAC_DINH, WS_URL_VOICE_MAC_DINH]) {
      expect(hop.queryByText(url)).not.toBeInTheDocument()
    }
    expect(hop.queryByTestId('gia-tri-ws-chat')).not.toBeInTheDocument()
    expect(hop.queryByTestId('gia-tri-ws-voice')).not.toBeInTheDocument()
    expect(hop.queryByRole('button', { name: /Copy WS URL/ })).not.toBeInTheDocument()

    // Đúng MỘT nút copy trong dialog ⇒ biên nhận «Đã copy khoá» không còn mơ hồ.
    expect(hop.getAllByRole('button', { name: /^Copy/ })).toHaveLength(1)
  })

  it('hai WS URL vẫn còn trên MÀN, chỉ rời dialog — đừng bỏ nhầm cả hai chỗ', async () => {
    // Cổng canh chiều ngược: gỡ chúng khỏi dialog là đúng CHỈ KHI thẻ ngoài còn
    // giữ chúng. Bỏ cả hai chỗ là người dùng không còn đường nào lấy được URL.
    boot()
    expect(await screen.findByTestId('gia-tri-ws-chat-list')).toHaveTextContent(
      WS_URL_CHAT_MAC_DINH,
    )
    expect(screen.getByTestId('gia-tri-ws-voice-list')).toHaveTextContent(WS_URL_VOICE_MAC_DINH)
  })

  it('lỗi API thì dialog KHÔNG đóng và nhãn đã gõ không mất', async () => {
    server.use(
      http.post('/api/v1/agent/keys', () =>
        HttpResponse.json(
          { error: { code: 'NOT_PROVISIONED', message: 'Cấp phát chưa xong: thiếu role' } },
          { status: 409 },
        ),
      ),
    )
    const u = userEvent.setup()
    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))
    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod thử')
    await u.click(hopThoai().getByRole('button', { name: 'Tạo khoá' }))

    expect(await screen.findByText(/thiếu role/)).toBeInTheDocument()
    // Đóng dialog khi lỗi là ném người dùng về màn cũ mà không nói vì sao.
    expect(hopThoai().getByLabelText(/Nhãn/)).toHaveValue('Pod thử')
  })
})

describe('tên khoá bắt buộc (spec 2026-08-07 §3.3)', () => {
  it('nhãn trống thì nút Tạo khoá khoá; gõ tên vào là mở', async () => {
    const u = userEvent.setup()
    boot()
    await u.click(await screen.findByRole('button', { name: /Tạo khoá mới/ }))

    const nutTao = hopThoai().getByRole('button', { name: 'Tạo khoá' })
    expect(nutTao).toBeDisabled()

    await u.type(hopThoai().getByLabelText(/Nhãn/), 'Pod chat production')
    expect(nutTao).toBeEnabled()

    // Toàn khoảng trắng = trống — trim trước khi xét.
    await u.clear(hopThoai().getByLabelText(/Nhãn/))
    await u.type(hopThoai().getByLabelText(/Nhãn/), '   ')
    expect(nutTao).toBeDisabled()
  })
})

describe('bật/tắt khoá', () => {
  it('phải xác nhận, và câu chữ nói ĐÚNG lúc pod mất kết nối', async () => {
    const u = userEvent.setup()
    boot()
    await screen.findByText('Pod chat production')

    await u.click(screen.getAllByRole('button', { name: 'Tắt khoá' })[0]!)

    // Không nói "mất kết nối ngay": credential đã bootstrap còn sống tới hết TTL.
    expect(hopThoai().getByText(/KHÔNG đứt ngay/)).toBeInTheDocument()
    expect(hopThoai().getByText(/ody_ag_7Fk2/)).toBeInTheDocument()
  })

  it('xác nhận thì hàng Ở LẠI và chuyển sang «Đã tắt»', async () => {
    // BÀI NÀY TỪNG KHOÁ HÀNH VI NGƯỢC LẠI ("hàng biến mất khỏi bảng"), và nó
    // xanh vì handler MSW `splice()` hàng ra khỏi mảng — trong khi backend chỉ
    // đặt `revoked_at` và KHÔNG có `DELETE` nào trên `control.agent_keys`. Tức
    // fake mã hoá một luật ngược với backend rồi một bài test khoá cái sai đó
    // lại; đúng lớp lỗi mà gotcha `userCount` trong CLAUDE.md đã ghi.
    const u = userEvent.setup()
    boot()
    await screen.findByText('Pod chat production')

    await u.click(screen.getAllByRole('button', { name: 'Tắt khoá' })[0]!)
    await u.click(hopThoai().getByRole('button', { name: 'Tắt khoá' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    // Hàng KHÔNG mất — nó chỉ đổi trạng thái.
    const hang = screen.getByText('Pod chat production').closest('tr')!
    expect(within(hang).getByText('Đã tắt')).toBeInTheDocument()
    expect(within(hang).getByRole('button', { name: 'Bật lại khoá' })).toBeInTheDocument()
  })

  it('bật lại được, KHÔNG hỏi xác nhận', async () => {
    // Đối xứng là cả lý do của mô hình này: tắt mà không bật lại được thì nó chỉ
    // là xoá vòng vo. `KHOA_GIA` có sẵn một khoá `inactive` (id 3).
    const u = userEvent.setup()
    boot()
    const hang = (await screen.findByText('Pod thử nghiệm')).closest('tr')!
    expect(within(hang).getByText('Đã tắt')).toBeInTheDocument()

    await u.click(within(hang).getByRole('button', { name: 'Bật lại khoá' }))

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    await waitFor(() => {
      const lai = screen.getByText('Pod thử nghiệm').closest('tr')!
      expect(within(lai).getByText('Đang dùng')).toBeInTheDocument()
    })
  })

  it('huỷ thì không tắt gì', async () => {
    const u = userEvent.setup()
    boot()
    await screen.findByText('Pod chat production')

    await u.click(screen.getAllByRole('button', { name: 'Tắt khoá' })[0]!)
    await u.click(hopThoai().getByRole('button', { name: 'Huỷ' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const hang = screen.getByText('Pod chat production').closest('tr')!
    expect(within(hang).getByText('Đang dùng')).toBeInTheDocument()
  })

  it('404 thì báo lỗi trong dialog, hàng giữ nguyên trạng thái', async () => {
    server.use(
      http.post('/api/v1/agent/keys/:id', () =>
        HttpResponse.json(
          { error: { code: 'NOT_FOUND', message: 'Không có khoá 1' } },
          { status: 404 },
        ),
      ),
    )
    const u = userEvent.setup()
    boot()
    await screen.findByText('Pod chat production')

    await u.click(screen.getAllByRole('button', { name: 'Tắt khoá' })[0]!)
    await u.click(hopThoai().getByRole('button', { name: 'Tắt khoá' }))

    expect(await screen.findByText(/Không có khoá 1/)).toBeInTheDocument()
    const hang = screen.getByText('Pod chat production').closest('tr')!
    expect(within(hang).getByText('Đang dùng')).toBeInTheDocument()
  })
})

describe('xoay khoá', () => {
  it('mở dialog xác nhận, đúng tiền tố + nhãn của khoá đang bấm', async () => {
    const u = userEvent.setup()
    boot()
    await screen.findByText('Pod chat production')

    await u.click(screen.getAllByRole('button', { name: 'Xoay khoá' })[0]!)

    expect(hopThoai().getByText(/ody_ag_7Fk2/)).toBeInTheDocument()
    expect(hopThoai().getByText(/Pod chat production/)).toBeInTheDocument()
  })

  it('xác nhận: khoá cũ chuyển "Đã tắt", khoá mới cùng nhãn hiện qua KhoaMoiDialog', async () => {
    const u = userEvent.setup()
    boot()
    await screen.findByText('Pod chat production')

    await u.click(screen.getAllByRole('button', { name: 'Xoay khoá' })[0]!)
    await u.click(hopThoai().getByRole('button', { name: 'Xoay khoá' }))

    // Dialog xác nhận THAY CHỖ dialog khoá mới — không cùng hiện.
    const khoi = await choKhoiKhoa()
    expect(screen.getAllByRole('dialog')).toHaveLength(1)
    expect(khoi.textContent).toMatch(/^ody_ag_/)
    expect(khoi.textContent).not.toMatch(/^ody_ag_7Fk2/)

    // Khoá cũ KHÔNG biến mất, chỉ chuyển "Đã tắt" — và một hàng MỚI cùng nhãn,
    // "Đang dùng", xuất hiện cạnh nó (khoá mới giữ nguyên nhãn khoá cũ).
    await waitFor(() => {
      const hangs = screen.getAllByText('Pod chat production').map((el) => el.closest('tr')!)
      expect(hangs).toHaveLength(2)
      expect(hangs.some((h) => within(h).queryByText('Đã tắt'))).toBe(true)
      expect(hangs.some((h) => within(h).queryByText('Đang dùng'))).toBe(true)
    })
  })

  it('huỷ thì không xoay gì', async () => {
    const u = userEvent.setup()
    boot()
    await screen.findByText('Pod chat production')

    await u.click(screen.getAllByRole('button', { name: 'Xoay khoá' })[0]!)
    await u.click(hopThoai().getByRole('button', { name: 'Huỷ' }))

    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    const hang = screen.getByText('Pod chat production').closest('tr')!
    expect(within(hang).getByText('Đang dùng')).toBeInTheDocument()
  })

  it('404 thì báo lỗi trong dialog xác nhận, hàng giữ nguyên', async () => {
    server.use(
      http.post('/api/v1/agent/keys/:id/rotate', () =>
        HttpResponse.json(
          { error: { code: 'NOT_FOUND', message: 'Không có khoá 1' } },
          { status: 404 },
        ),
      ),
    )
    const u = userEvent.setup()
    boot()
    await screen.findByText('Pod chat production')

    await u.click(screen.getAllByRole('button', { name: 'Xoay khoá' })[0]!)
    await u.click(hopThoai().getByRole('button', { name: 'Xoay khoá' }))

    expect(await screen.findByText(/Không có khoá 1/)).toBeInTheDocument()
    const hang = screen.getByText('Pod chat production').closest('tr')!
    expect(within(hang).getByText('Đang dùng')).toBeInTheDocument()
  })
})
