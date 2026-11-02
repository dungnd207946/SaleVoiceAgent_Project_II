/**
 * Client cho luồng chat qua GATEWAY THẬT (`/v1/chat`) — nối THẲNG từ trình
 * duyệt, KHÔNG qua backend. Viết lại LẦN BỐN 2026-08-10 theo tài liệu handoff
 * chính thức của team gateway
 * (`odyssey-portal-backend/docs/build_test_agent/2026-08-10-frontend-chat-gateway-handoff.md`,
 * dẫn tới code thật `src/noble_agent/` — nguồn đáng tin hơn script mẫu trước đó).
 *
 * BA THỨ BẢN TRƯỚC (relay qua backend) LÀM SAI, sửa ở đây:
 *
 *   1. KHÔNG cần relay. Doc §1: "Browser KHÔNG set được header Authorization
 *      cho WebSocket → dùng query param — gateway tự đổi thành Bearer."
 *      `?key=<token>` nối thẳng từ trình duyệt là cách CHÍNH THỐNG, không phải
 *      một giải pháp tạm. Module `agent_demo` ở backend đã xoá (xem CLAUDE.md).
 *   2. Khoá identity là `full_name`, KHÔNG phải `name`. Script mẫu trước đó
 *      gửi `name` — theo doc §2 đó là gửi sai, "mất trắng" (worker bỏ qua im
 *      lặng); script vẫn "chạy" vì identity là optional, chỉ mỗi việc cá nhân
 *      hoá (chào theo tên) không có tác dụng.
 *   3. "Sẵn sàng" phải chờ event `session_id` (§4.1), KHÔNG phải chờ WS mở —
 *      mở TCP xong không có nghĩa handshake đã được gateway chấp nhận.
 */

import type { DanhTinhKhach } from './danhTinhKhach'

// ─── Cấu hình kết nối — 2 ô, KHÔNG lưu server ───────────────────────────────

export interface CauHinhGateway {
  readonly wsUrl: string
  readonly apiKey: string
}

/** Các trường thu thập trên form (`danhTinhKhach.ts`) — khoá gửi lên gateway
 *  giữ NGUYÊN `full_name`/`phone`/`gender`, đúng những khoá worker đọc (doc §2),
 *  cộng `role` (key role trong cấu hình chung). */
export type DanhTinhGateway = DanhTinhKhach

/** Một chip gợi ý — `label` để hiện, `text` để gửi khi bấm (doc §4.2, khác
 *  hẳn hình dạng chuỗi trần bản trước đoán sai). */
export interface GoiY {
  readonly label: string
  readonly text: string
}

/**
 * Card ảnh/video (`send_media`, doc §4.3) — CÙNG hình dạng ở cả hai kênh (doc
 * §8: "Auth + handshake giống nhau" giữa `/v1/chat` và `/v1/voice`, và payload
 * `send_media` không đổi theo kênh). Định nghĩa Ở ĐÂY để `giongNoi.ts` dùng
 * lại, cùng lý do `gopKhoaVaoUrl`/`locTrongDanhTinh` đã export từ tệp này.
 *
 * Khác biệt DUY NHẤT giữa hai kênh là NƠI dữ liệu này xuất hiện: Chat phải
 * đào trong `tool_done.result` (không có event `media` riêng — xem
 * `docMediaTuKetQua` dưới), Voice nhận qua event `media` độc lập.
 */
export interface MedItemAnh {
  readonly kind: 'image'
  readonly url: string
  readonly label?: string
  readonly thumb?: string
  /** Số tấm ảnh, DUY NHẤT trong cả cuộc trò chuyện (không phải theo lượt). Câu
   *  trả lời trỏ tới nó bằng chữ — «(xem ảnh 3)» — nên không hiện số ra thì
   *  người đọc không biết đó là tấm nào. Optional: agent bản cũ chưa gửi. */
  readonly index?: number
}
/** Video YouTube — agent đã bóc `video_id` (11 ký tự) từ URL. */
export interface MedItemVideoYouTube {
  readonly kind: 'video'
  readonly video_id: string
  readonly title?: string
}
/**
 * Video KHÔNG phải YouTube (2026-08-25) — Google Drive `file/d/<id>`, Vimeo,
 * mp4… Agent giữ kiến thức provider ở MỘT chỗ (như bóc YouTube id): Drive được
 * `embed_url` (`…/file/d/<id>/preview`, nhúng iframe được) + `thumb`
 * (`drive.google.com/thumbnail?id=…`); folder Drive / host khác chỉ có `url`.
 * Portal mở `url` tab mới — `embed_url` dành cho client có lightbox (AINA).
 */
export interface MedItemVideoUrl {
  readonly kind: 'video'
  readonly url: string
  readonly embed_url?: string
  readonly thumb?: string
  readonly title?: string
}
export type MedItemVideo = MedItemVideoYouTube | MedItemVideoUrl
/** Tour 360 — link kuula/matterport, agent gửi qua `send_media`. */
export interface MedItemTour {
  readonly kind: 'tour'
  readonly url: string
  readonly label?: string
}
/** Tệp nguồn của câu trả lời — `kb_search` gửi kèm khi hit lấy từ một tài liệu. */
export interface MedItemTep {
  readonly kind: 'file'
  readonly url: string
  readonly label?: string
  readonly thumb?: string
  readonly page?: number
}
export type MucMedia = MedItemAnh | MedItemVideo | MedItemTour | MedItemTep

export interface Media {
  readonly caption?: string
  readonly message?: string
  readonly items: readonly MucMedia[]
}

/** `items[]` — bỏ phần tử thiếu `kind` hợp lệ, không đoán. */
export function chuanHoaMedia(m: Record<string, unknown>): Media {
  const thoRa = Array.isArray(m['items']) ? m['items'] : []
  const items: MucMedia[] = []
  for (const it of thoRa) {
    if (typeof it !== 'object' || it === null) continue
    const g = it as Record<string, unknown>
    if (g['kind'] === 'image' && typeof g['url'] === 'string') {
      items.push({
        kind: 'image',
        url: g['url'],
        ...(typeof g['label'] === 'string' ? { label: g['label'] } : {}),
        ...(typeof g['thumb'] === 'string' ? { thumb: g['thumb'] } : {}),
        ...(typeof g['index'] === 'number' && g['index'] > 0 ? { index: g['index'] } : {}),
      })
    } else if (g['kind'] === 'video' && typeof g['video_id'] === 'string') {
      items.push({
        kind: 'video',
        video_id: g['video_id'],
        ...(typeof g['title'] === 'string' ? { title: g['title'] } : {}),
      })
    } else if (g['kind'] === 'video' && typeof g['url'] === 'string') {
      // Thiếu CẢ `video_id` lẫn `url` thì rơi qua đây không khớp ⇒ bỏ, không đoán.
      items.push({
        kind: 'video',
        url: g['url'],
        ...(typeof g['embed_url'] === 'string' ? { embed_url: g['embed_url'] } : {}),
        ...(typeof g['thumb'] === 'string' ? { thumb: g['thumb'] } : {}),
        ...(typeof g['title'] === 'string' ? { title: g['title'] } : {}),
      })
    } else if (g['kind'] === 'tour' && typeof g['url'] === 'string') {
      items.push({
        kind: 'tour',
        url: g['url'],
        ...(typeof g['label'] === 'string' ? { label: g['label'] } : {}),
      })
    } else if (g['kind'] === 'file' && typeof g['url'] === 'string') {
      items.push({
        kind: 'file',
        url: g['url'],
        ...(typeof g['label'] === 'string' ? { label: g['label'] } : {}),
        ...(typeof g['thumb'] === 'string' ? { thumb: g['thumb'] } : {}),
        ...(typeof g['page'] === 'number' && g['page'] > 0 ? { page: g['page'] } : {}),
      })
    }
  }
  return {
    ...(typeof m['caption'] === 'string' ? { caption: m['caption'] } : {}),
    ...(typeof m['message'] === 'string' ? { message: m['message'] } : {}),
    items,
  }
}

/**
 * Kênh chat KHÔNG có event `media` riêng (doc §4.3) — card ảnh/video nằm
 * trong `tool_done.result`, một CHUỖI chứa JSON. Trả `null` nếu `result`
 * không parse được hoặc không mang `items[]` (không phải mọi tool đều là
 * `send_media` — `kb_search`, `booking`, `escalate`, … đi qua đây mà không có
 * card, đúng mẫu `handleToolDone()` ở doc: chỉ xét CẤU TRÚC, không xét tên
 * tool, và bỏ qua khi `items` rỗng — `{ items: [] }` là "không có media", agent
 * tự nói bằng lời).
 */
export function docMediaTuKetQua(result: unknown): Media | null {
  let r: unknown
  if (typeof result === 'string') {
    try {
      r = JSON.parse(result)
    } catch {
      return null
    }
  } else {
    r = result
  }
  if (typeof r !== 'object' || r === null) return null
  const g = r as Record<string, unknown>
  if (!Array.isArray(g['items']) || g['items'].length === 0) return null
  return chuanHoaMedia(g)
}

export type TrangThaiChatGateway = 'dang_mo' | 'song' | 'dong'

/** `engine_ok` — agent đã dựng lại bộ não của phiên theo tin `engine` (trang Thử agent). */
export interface EngineDangChay {
  readonly engine: string
  readonly provider: string
  readonly model: string
}

/** `trace` — luồng xử lý một lượt của engine v2, tới SAU `done` (chỉ worker bật CHAT_SEND_TRACE). */
export interface TraceLuot {
  readonly turnId: string
  readonly engine: string
  readonly trace: Record<string, unknown>
}

export interface TuyChonChatGateway {
  readonly cauHinh: CauHinhGateway
  readonly danhTinh: DanhTinhGateway
  readonly onTrangThai: (t: TrangThaiChatGateway) => void
  readonly onToken: (text: string) => void
  readonly onToolStart: (tool: string, args: unknown) => void
  readonly onToolDone: (tool: string, result: unknown) => void
  /** Card ảnh/video rút ra từ `tool_done.result` khi nó mang `items[]` không
   *  rỗng (doc §4.3) — xem `docMediaTuKetQua`. Bắn CÙNG lúc với `onToolDone`
   *  của chính lượt gọi tool đó, không phải một event riêng. */
  readonly onMedia: (m: Media) => void
  readonly onDone: () => void
  /** `session_id` của phiên — event ĐẦU TIÊN, luôn có (doc §4.1). Đây là ĐÚNG
   *  id mà worker dùng khi ghi `tenant_data.conversations`, nên cũng là id phải
   *  gửi kèm khi ghi feedback (`POST /agent/feedback`). Bắn TRƯỚC
   *  `onTrangThai('song')` để người gọi có id ngay lúc khung chat mở ra. */
  readonly onSessionId: (id: string) => void
  readonly onSuggestions: (items: readonly GoiY[]) => void
  /** Lỗi MỘT LƯỢT từ gateway (event `{"type":"error"}`) — KHÔNG đóng phiên;
   *  doc §4.2 mục 5: "vẫn có `done` sau đó, đừng để UI kẹt ở đang trả lời". */
  readonly onError: (message: string) => void
  /** WS đóng — `message` ĐÃ được dịch từ (code, reason) theo bảng doc §2.
   *  Người gọi tự quyết định có hiện hay không (ví dụ bỏ qua khi TỰ đóng). */
  readonly onClose: (message: string) => void
  /** Trang Thử agent: agent nhận tin `engine`. Tuỳ chọn — Voice không dùng. */
  readonly onEngineOk?: (e: EngineDangChay) => void
  readonly onTrace?: (t: TraceLuot) => void
}

export interface PhienChatGatewayMo {
  readonly gui: (text: string) => void
  readonly reset: () => void
  /** Gửi tin `{"type":"engine",…}` (dựng bởi `tinDoiEngine`) — chỉ sau `session_id`. */
  readonly doiEngine: (tin: Record<string, string>) => void
  readonly dong: () => void
}

/**
 * `?key=` hoặc `&key=` nếu URL đã có query string sẵn (doc §1).
 *
 * EXPORT — Voice (`giongNoi.ts`) dùng lại đúng hàm này: doc handoff §8 nói rõ
 * "Auth + handshake giống nhau" giữa `/v1/chat` và `/v1/voice`, nên đây là quy
 * tắc CHUNG của gateway, không phải quy tắc riêng của kênh chat.
 */
export function gopKhoaVaoUrl(wsUrl: string, apiKey: string): string {
  const noi = wsUrl.includes('?') ? '&' : '?'
  return `${wsUrl}${noi}key=${encodeURIComponent(apiKey)}`
}

/** EXPORT — cùng lý do `gopKhoaVaoUrl`, khung bắt tay `{identity, call_id}` là
 *  chung cho cả hai kênh (doc §8). */
export function locTrongDanhTinh(d: DanhTinhGateway): Record<string, string> {
  const ra: Record<string, string> = {}
  if (d.full_name) ra['full_name'] = d.full_name
  if (d.phone) ra['phone'] = d.phone
  if (d.gender) ra['gender'] = d.gender
  if (d.role) ra['role'] = d.role
  return ra
}

/**
 * Mở một phiên. Trả về thứ để gửi tin/reset/đóng — người gọi PHẢI giữ và gọi
 * `dong()` lúc rời màn: một WebSocket không đóng là một kết nối treo.
 */
export function moPhienChatGateway(o: TuyChonChatGateway): PhienChatGatewayMo {
  let daDong = false
  let daSanSang = false // đã nhận `session_id` — KHÔNG phải "WS đã mở" (doc §4.1)

  o.onTrangThai('dang_mo')
  const ws = new WebSocket(gopKhoaVaoUrl(o.cauHinh.wsUrl, o.cauHinh.apiKey))

  ws.onopen = () => {
    // Frame bắt tay BẮT BUỘC trong 10s (doc §2) — gửi ngay, đồng bộ, không
    // chờ gì cả nên luôn kịp giờ.
    ws.send(
      JSON.stringify({
        identity: locTrongDanhTinh(o.danhTinh),
        call_id: `portal-${Date.now()}`,
      }),
    )
  }

  ws.onmessage = (e) => {
    // Binary = audio TTS (doc §5) — màn thử này không bật `tts`, nên không
    // bao giờ nhận. Vẫn CẢNH BÁO nếu có: nghĩa là gateway gửi nhị phân ngoài
    // dự kiến, đúng loại lệch tài liệu cần thấy ngay, không phải im lặng.
    if (typeof e.data !== 'string') {
      console.warn('[chatGateway] nhận frame nhị phân ngoài dự kiến (không bật tts):', e.data)
      return
    }
    let m: Record<string, unknown>
    try {
      m = JSON.parse(e.data) as Record<string, unknown>
    } catch {
      console.warn('[chatGateway] frame text nhận được KHÔNG phải JSON hợp lệ:', e.data)
      return
    }

    // In NGUYÊN VĂN mọi frame nhận được, kể cả loại đã nhận diện — cảnh báo
    // "type lạ" chỉ bắt được sai TÊN `type`, không bắt được trường hợp `type`
    // đúng nhưng TÊN TRƯỜNG bên trong khác (vd `token` thật nhưng chữ nằm ở
    // `delta`/`content` chứ không phải `text` — khi đó `m['text']` là
    // `undefined`, `onToken` nhận chuỗi rỗng, KHÔNG có cảnh báo nào nổ vì
    // `type` vẫn khớp). Dòng này để thấy hình dạng THẬT của event.
    console.log('[chatGateway] nhận:', m)

    if (m['type'] === 'session_id') {
      daSanSang = true
      o.onSessionId(String(m['session_id'] ?? ''))
      o.onTrangThai('song')
      return
    }
    xuLySuKienGateway(m, o)
  }

  ws.onclose = (e) => {
    daDong = true
    o.onTrangThai('dong')
    o.onClose(dichLyDoDong(e.code, e.reason, 'chat'))
  }

  function gui(text: string): void {
    if (!daSanSang || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'user_text', text }))
  }

  function reset(): void {
    if (!daSanSang || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'reset' }))
  }

  function doiEngine(tin: Record<string, string>): void {
    if (!daSanSang || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify(tin))
  }

  function dong(): void {
    if (daDong) return
    daDong = true
    ws.close()
  }

  return { gui, reset, doiEngine, dong }
}

/**
 * 6 loại event thật xử lý ở đây (doc §4), cộng `engine_ok` / `trace` riêng của trang
 * Thử agent (worker bật CHAT_SEND_TRACE). `user_text` (echo) · `metrics` ·
 * `reset_ok` · `customer_ok` — CỐ Ý bỏ qua, không phải quên: không cái nào
 * cần cho một màn thử tối giản. Liệt kê tường minh (không rơi vào `default`)
 * để phân biệt với loại THẬT SỰ LẠ — thứ CẦN thấy khi debug (xem dưới).
 */
function xuLySuKienGateway(m: Record<string, unknown>, o: TuyChonChatGateway): void {
  switch (m['type']) {
    case 'token':
      o.onToken(String(m['text'] ?? ''))
      return
    case 'tool_start':
      o.onToolStart(String(m['tool'] ?? ''), m['args'])
      return
    case 'tool_done': {
      const result = m['result']
      o.onToolDone(String(m['tool'] ?? ''), result)
      const media = docMediaTuKetQua(result)
      if (media) o.onMedia(media)
      return
    }
    case 'done':
      o.onDone()
      return
    case 'suggestions': {
      const items = m['items']
      o.onSuggestions(
        Array.isArray(items) ? items.map(chuanHoaGoiY).filter((g): g is GoiY => g !== null) : [],
      )
      return
    }
    case 'error':
      o.onError(String(m['message'] ?? 'Lỗi không rõ từ agent.'))
      return
    case 'engine_ok':
      o.onEngineOk?.({
        engine: String(m['engine'] ?? ''),
        provider: String(m['provider'] ?? ''),
        model: String(m['model'] ?? ''),
      })
      return
    case 'trace': {
      const tr = m['trace']
      if (typeof tr === 'object' && tr !== null)
        o.onTrace?.({
          turnId: String(m['turn_id'] ?? ''),
          engine: String(m['engine'] ?? ''),
          trace: tr as Record<string, unknown>,
        })
      return
    }
    case 'user_text':
    case 'metrics':
    case 'reset_ok':
    case 'customer_ok':
      return
    default:
      // ⚠️ KHÔNG bỏ qua âm thầm — một triển khai gateway lệch tài liệu (đã đo
      // được thật: `registry_forbidden` cũng không nằm trong bảng tài liệu)
      // có thể dùng `type` khác cho đúng thứ này lẽ ra phải là `token`/`done`.
      // In ra Console để thấy NGAY thay vì "agent trả lời, UI im lặng" mà
      // không biết vì sao.
      console.warn(
        '[chatGateway] event lạ, KHÔNG xử lý — kiểm tra tên `type` có đúng doc không:',
        m,
      )
      return
  }
}

/** `{label, text}` (doc §4.2) — KHÔNG phải chuỗi trần. Phần tử thiếu một
 *  trong hai khoá thì bỏ, không đoán. */
function chuanHoaGoiY(it: unknown): GoiY | null {
  if (typeof it !== 'object' || it === null) return null
  const g = it as Record<string, unknown>
  if (typeof g['label'] !== 'string' || typeof g['text'] !== 'string') return null
  return { label: g['label'], text: g['text'] }
}

/**
 * Dịch (code, reason) đóng WS sang câu người đọc được — bảng của gateway: `/v1/chat`
 * (doc §2) và `/v1/voice` (doc §1). Voice chỉ tài liệu hoá `4001`/`4004`/`4008` nhưng
 * cùng gateway, nên vẫn dịch đủ bảng — im lặng tệ hơn một câu tổng quát. KHÔNG phải
 * bảng `4401` tự đặt cho relay đã bỏ.
 *
 * `bad_credential` và `auth_api_unavailable` CỐ Ý tách câu — gộp lại là đẩy
 * người dùng đi đổi key khi lỗi thật là hạ tầng (đúng cảnh báo của doc).
 */
export function dichLyDoDong(code: number, reason: string, kenh: 'chat' | 'voice'): string {
  if (code === 4001) {
    if (reason === 'no_bearer') return 'Chưa nhập API key.'
    if (reason === 'bad_credential') return 'API key không hợp lệ.'
    if (reason === 'auth_api_unavailable') return 'Hệ thống xác thực đang bận — thử lại sau.'
    return 'Không xác thực được — kiểm tra lại API key.'
  }
  if (code === 4004) return `Sai WS URL — không phải đường /v1/${kenh} hợp lệ.`
  if (code === 4008) return 'Không gửi được bắt tay kịp thời — thử lại.'
  if (code === 4029) return 'Server đang quá tải — thử lại sau.'
  if (code === 4403) return 'Lỗi cấu hình hạ tầng phía gateway — báo team vận hành.'
  if (code === 1000) return 'Đã đóng kết nối.'
  return kenh === 'chat' ? 'Mất kết nối tới phiên chat.' : 'Mất kết nối tới phiên thử giọng nói.'
}

// ─── Cấu hình kết nối ──────────────────────────────────────────────────────
//
// ⚠ KHÔNG CÒN localStorage Ở ĐÂY, và đừng nối lại. `docCauHinhDaLuu()` +
// `luuCauHinh()` đã xoá 2026-08-27: chúng ghi khoá `ody_ag_…` dạng RÕ xuống máy
// người dùng mỗi lần bấm «Áp dụng», trong khi đường ĐỌC đã chết từ 2026-08-11
// (ô dán khoá thô đổi thành `<select>` chọn theo tên). Tức từ 11 tới 27/08 việc
// lưu chỉ còn lại rủi ro, không còn lợi ích nào.
//
// Lý lẽ cũ («gõ lại một chuỗi dài mỗi lần mở màn tốn hơn rủi ro») gắn với cái ô
// dán ĐÃ KHÔNG CÒN. Khoá này mở được cả `/runtime-credentials` = mật khẩu
// Postgres của tenant (`docs/contracts/dau-noi-agent.md` §2b), nên nó không có
// việc gì phải nằm lại trên đĩa sau khi tab đóng.
//
// Khoá cũ còn sót trên máy người dùng do `lib/donKhoaThoCu.ts` dọn.
//
// `wsUrl` cũng không cần lưu: nó là hằng trong code (`WS_URL_CHAT_MAC_DINH` ở
// `api.ts`) từ 2026-08-11, không phải thứ người dùng gõ.
