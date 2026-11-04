/**
 * Client cho kênh Voice qua GATEWAY THẬT (`/v1/voice`) — nối THẲNG từ trình
 * duyệt, giống hệt cơ chế Chat (`chatGateway.ts`). Viết lại TOÀN BỘ 2026-08-11
 * theo tài liệu spec chính thức của team gateway
 * (`odyssey-portal-backend/docs/build_test_agent/gateway-voice-ws-spec.md`).
 *
 * BA THỨ BẢN TRƯỚC (mô hình "vé" `POST /agent/try/voice`) LÀM SAI, sửa ở đây:
 *
 *   1. KHÔNG cần vé/backend đứng giữa. Bản trước giả định portal không lưu
 *      khoá thô nên phải xin backend đổi `keyId` lấy một `wsUrl` ngắn hạn.
 *      Giả định đó đã SAI từ 2026-08-11: migration `0918` phía backend lưu
 *      THÊM khoá thô (`Khoa.api_key`), và Chat đã đổi sang nối thẳng bằng
 *      khoá đó — Voice dùng lại ĐÚNG cơ chế này (doc §1: "Auth + handshake
 *      giống nhau" giữa `/v1/chat` và `/v1/voice`).
 *   2. Path `/v1/stream` KHÔNG CÒN TỒN TẠI (doc §1: "path cũ /v1/stream đã bỏ,
 *      KHÔNG có alias" — dùng path sẽ nhận đóng WS `4004 unknown_route`).
 *      Path đúng là `/v1/voice`.
 *   3. Giao thức event bản trước là ĐOÁN (từ README `odyssey-tester`, tên event
 *      như `user_transcript`/`agent_text` KHÔNG khớp thật). Spec thật (§3) có
 *      10 loại event khác hẳn: `partial_transcript`/`transcript` (lời khách),
 *      `agent_speaking` (lời agent — TỪNG CÂU, có `turn_id`/`sentence_id`, không
 *      per-token như chat), `agent_done`/`agent_interrupted`, `tool_start`/
 *      `tool_done` (KHÔNG mang `result` — khác chat), `media` (card ảnh/video,
 *      RIÊNG một event — khác chat phải đào trong `tool_done.result`),
 *      `error`/`session_ended`.
 *
 * ⚠ KHÔNG CÓ TEST TỰ ĐỘNG CHO PHẦN ÂM THANH (mic/loa). jsdom không có
 * `AudioContext` lẫn `getUserMedia`, MSW không giả lập WebSocket nhị phân —
 * nên phần khó nhất (tái lấy mẫu, hàng đợi phát) chỉ nghiệm thu được bằng tai,
 * với một gateway thật. Phần EVENT PARSER (`xuLySuKienGiongNoi`) thì THUẦN —
 * test được, xem `tests/thu-agent.test.tsx`.
 */

import { moAvatar, TRE_PHAT_S, uocLuongGiayNoi, type VeAvatar } from './avatarLipSync'
import {
  chuanHoaMedia,
  dichLyDoDong,
  gopKhoaVaoUrl,
  locTrongDanhTinh,
  type Media,
} from './chatGateway'
import { batChuongCho, coTieng, TOI_DA_S } from './chuongCho'
import type { DanhTinhKhach } from './danhTinhKhach'

/** Alias — card media có hình dạng CHUNG cho cả hai kênh, định nghĩa thật ở
 *  `chatGateway.ts` (xem docstring `Media` ở đó). Giữ tên riêng cho voice vì
 *  đây là tên đã dùng khắp `ThuAgentScreen.tsx`. */
export type MediaGiongNoi = Media

// ─── Cấu hình kết nối — 2 ô, giống Chat ─────────────────────────────────────

export interface CauHinhGiongNoi {
  readonly wsUrl: string
  readonly apiKey: string
}

/** Nhịp lấy mẫu chiều BẠN → AGENT. Gateway chốt cứng 16kHz (doc §2, uplink
 *  "chắc chắn — gateway hardcode"). */
const NHIP_LEN = 16000

/**
 * Nhịp lấy mẫu chiều AGENT → BẠN. **48000, KHÔNG PHẢI 24000.**
 *
 * Doc §2 giải thích: worker publish TTS ở 24kHz, nhưng gateway subscribe bằng
 * `rtc.AudioStream(track)` KHÔNG truyền `sample_rate` → SDK LiveKit dùng
 * default 48000 và tự resample TRƯỚC khi đẩy byte ra WS — nên byte trên dây
 * là 48kHz dù nguồn phát ở 24kHz. Đây là spec MỚI HƠN (2026-08-07, "áp dụng từ
 * commit thêm event-forward") và ĂN ĐỨT mọi tài liệu/script cũ ghi 24000 —
 * đã ghi rõ trong spec là script `smoke_gateway_voice.py` "cũng sai theo".
 * Phát ở 24kHz nghe chậm một nửa + trầm.
 */
const NHIP_XUONG = 48000

export type TrangThaiGiongNoi = 'nghi' | 'dang_noi' | 'dang_mo' | 'song' | 'loi'

// ─── Catalog event thật (doc §3) ─────────────────────────────────────────────

export interface TuyChonGiongNoi {
  readonly cauHinh: CauHinhGiongNoi
  readonly danhTinh: DanhTinhKhach
  readonly onTrangThai: (t: TrangThaiGiongNoi) => void
  /** 0…1 — để vẽ vạch mức mic. Chỉ để nhìn, không ai đọc số này. */
  readonly onMuc: (m: number) => void
  /**
   * 0…1 — mức to nhỏ của tiếng AGENT đang ra loa (không phải mic). Nuôi người
   * dẫn trên sân khấu (`SanKhauAgent`): có tiếng thì mấp máy môi, im thì đứng
   * yên. Đo ở ĐẦU RA chứ không theo event `agent_speaking`: event đến theo
   * CÂU và sớm hơn tiếng thật (audio còn nằm trong hàng đợi `mocPhat`), bám vào
   * nó thì người nói trước khi có tiếng và im trước khi dứt câu.
   * Nhịp gọi = nhịp `onaudioprocess` (~85ms); đóng phiên thì gọi lần cuối với 0.
   *
   * `conLai` = số giây audio agent CÒN trong hàng đợi phát (`mocPhat` −
   * `currentTime`, ≥ 0). Đây là thứ CHÍNH XÁC duy nhất về «còn nói bao lâu»:
   * mức to nhỏ chỉ nói «lúc này có tiếng không», nên dựa vào nó thì phải chờ
   * một khoảng lặng đủ dài mới dám coi là im (người dẫn dừng trễ 1–2s). Cũng
   * được gọi NGAY khi một khối audio mới vừa xếp lịch, không chờ nhịp đo.
   */
  readonly onMucLoa: (m: number, conLai: number) => void
  /** Ghi đè liên tục khi khách đang nói — KHÔNG append (doc §3.1). */
  readonly onPartialTranscript: (text: string) => void
  /** Bản chốt của lượt khách, mở một turn mới. */
  readonly onTranscript: (text: string, turnId: string) => void
  /** Từng CÂU của agent — nối vào bong bóng cùng `turnId`, không per-token. */
  readonly onAgentSpeaking: (text: string, turnId: string) => void
  readonly onAgentDone: (turnId: string) => void
  readonly onAgentInterrupted: (turnId: string, lastCompletedSentenceId: number) => void
  readonly onToolStart: (tool: string, args: unknown) => void
  readonly onToolDone: (tool: string) => void
  readonly onMedia: (m: MediaGiongNoi) => void
  /** Lỗi phía worker (STT chết…) — phiên CÓ THỂ vẫn tiếp tục (doc §3.6). */
  readonly onError: (message: string) => void
  /**
   * `session_id` của phiên voice — event ĐẦU TIÊN, trước mọi frame audio
   * (`gateway-voice-ws-spec.md` §3.0, gateway thêm 2026-08-13; trước đó kênh
   * voice không có event này còn `/v1/chat` thì đã có từ đầu).
   *
   * Giá trị là **tên room LiveKit** — `transport/livekit/worker.py` dựng
   * `RoomSession(session_id=ctx.room.name)`, nên đây đúng là `session_id` mà
   * agent ghi vào `tenant_data.conversations`, tức id phải gửi kèm khi ghi
   * feedback (`POST /agent/feedback`).
   *
   * ⚠️ **KHÔNG thay thế bằng `call_id` của FE.** Tên room do
   * `gateway/livekit_bridge.py::room_name()` sinh theo
   * `{tenant_id}-{call_id}-{ms}-{hex}`; hai vế `ms`/`hex` sinh Ở SERVER nên
   * client không suy ra được — đoán bừa là ghi feedback vào một session_id
   * không tồn tại, và hàng đó JOIN trượt `conversations`.
   *
   * Gateway chạy bản cũ thì callback không bao giờ được gọi: người gọi phải
   * chịu được `null` (xem `CheGiongNoi` — vẫn hiện thanh đánh giá nhưng khoá
   * nút Gửi kèm câu giải thích), KHÔNG được coi là luôn có.
   */
  readonly onSessionId: (id: string) => void
  readonly onSessionEnded: (reason: string) => void
  /** WS đóng NGOÀI Ý MUỐN (server đóng, mất mạng…) — đã dịch (code, reason).
   *  KHÔNG gọi khi tự đóng bằng `dong()` (bấm Dừng/rời màn): guard `daDong`
   *  chặn trước khi tới đây, nên người gọi không cần tự lọc lần nữa. */
  readonly onDong: (message: string) => void
  /**
   * Tiếng chuông chờ bắt máy (`chuongCho.ts`) bật/tắt — `true` ngay khi bấm
   * Bắt đầu, `false` khi tiếng agent đầu tiên ra loa (hoặc khách nói trước,
   * hoặc phiên đóng, hoặc hết `TOI_DA_S`). Tuỳ chọn: chỉ để đổi nhãn trạng thái.
   */
  readonly onDoChuong?: (dang: boolean) => void
  /**
   * Lip sync thật (MuseTalk, `avatarLipSync.ts`). Có ⇒ audio agent phát TRỄ
   * `TRE_PHAT_S` và mỗi khối được gửi kèm thời điểm phát sang avatar service;
   * `ve()` trả hàm vẽ của sân khấu lúc frame tới hạn (`null` = chưa có chỗ vẽ).
   * Service không nối được ⇒ phát thẳng như cũ, không trễ.
   */
  readonly avatar?: { readonly url: string; readonly ve: () => VeAvatar | null }
}

export interface PhienGiongNoi {
  dong: () => void
  /** Lip sync: yêu cầu nhân vật đưa tay giới thiệu. Không bật lip sync ⇒ không làm gì. */
  gioTay?: () => void
}

/**
 * Hạ nhịp lấy mẫu bằng TRUNG BÌNH CỘNG từng ô, không phải lấy mẫu gần nhất.
 *
 * Lấy mẫu gần nhất (nearest-neighbour) rẻ hơn một chút nhưng gập tần số cao
 * xuống dải nghe được — giọng nói ra lạo xạo kim loại, và người nghe sẽ đổ cho
 * agent chứ không đổ cho hàm này. Trung bình cộng là bộ lọc thông thấp nghèo
 * nàn nhưng đủ cho giọng nói ở 16kHz.
 */
export function haNhip(vao: Float32Array, nhipVao: number): Int16Array {
  if (nhipVao === NHIP_LEN) return sangPcm16(vao)
  if (nhipVao < NHIP_LEN) throw new Error('Nhịp lấy mẫu của mic thấp hơn 16kHz')

  const tiLe = nhipVao / NHIP_LEN
  const daiRa = Math.floor(vao.length / tiLe)
  const ra = new Int16Array(daiRa)

  for (let i = 0; i < daiRa; i++) {
    const dau = Math.floor(i * tiLe)
    const cuoi = Math.min(Math.floor((i + 1) * tiLe), vao.length)
    let tong = 0
    for (let j = dau; j < cuoi; j++) tong += vao[j] as number
    ra[i] = kepPcm16(tong / Math.max(1, cuoi - dau))
  }
  return ra
}

function sangPcm16(vao: Float32Array): Int16Array {
  const ra = new Int16Array(vao.length)
  for (let i = 0; i < vao.length; i++) ra[i] = kepPcm16(vao[i] as number)
  return ra
}

/** −1…1 → Int16. Kẹp TRƯỚC khi nhân: không kẹp thì mẫu quá biên quấn vòng từ
 *  đỉnh dương sang đỉnh âm, nghe thành tiếng nổ lụp bụp chứ không phải méo. */
function kepPcm16(m: number): number {
  const k = Math.max(-1, Math.min(1, m))
  return k < 0 ? k * 0x8000 : k * 0x7fff
}

/** Mức to nhỏ (RMS) của một khối mẫu, đưa về 0…1 để vẽ vạch. */
export function mucRms(khoi: Float32Array): number {
  let tong = 0
  for (let i = 0; i < khoi.length; i++) tong += (khoi[i] as number) ** 2
  // ×4 để giọng nói bình thường lấp được phần lớn vạch — RMS của giọng nói
  // quanh 0.05–0.2, vẽ thẳng thì vạch gần như không nhúc nhích.
  return Math.min(1, Math.sqrt(tong / khoi.length) * 4)
}

/**
 * Mở một phiên. Trả về thứ để ĐÓNG nó — người gọi bắt buộc phải giữ và gọi
 * `dong()`, kể cả khi có lỗi: đèn mic của trình duyệt tắt theo `MediaStream`,
 * không theo trạng thái React.
 */
export async function moPhienGiongNoi(o: TuyChonGiongNoi): Promise<PhienGiongNoi> {
  o.onTrangThai('dang_noi')

  // AudioContext dựng TRƯỚC khi xin mic, ngay trong lượt bấm: (1) tiếng chuông
  // chờ phải kêu từ lúc bấm, kể cả lúc hộp thoại quyền mic còn mở; (2) Safari
  // chỉ cho AudioContext phát tiếng khi nó được tạo trong cử chỉ người dùng —
  // tạo sau một `await` dài là có thể bị treo ở `suspended`.
  const ctx = new AudioContext()
  let chuong: ReturnType<typeof batChuongCho> | null = batChuongCho(ctx)
  o.onDoChuong?.(true)
  const henTatChuong = window.setTimeout(() => tatChuong(), TOI_DA_S * 1000)
  function tatChuong(): void {
    if (!chuong) return
    chuong.tat()
    chuong = null
    window.clearTimeout(henTatChuong)
    o.onDoChuong?.(false)
  }

  // Xin mic TRƯỚC khi mở WS: hộp thoại quyền của trình duyệt có thể treo hàng
  // chục giây, và một WS mở sẵn trong lúc đó sẽ hết giờ hoặc bị gateway đóng vì
  // im lặng (doc §1: bắt tay phải gửi trong 10s). Người dùng từ chối quyền thì
  // cũng không tốn một kết nối nào.
  let dongTieng: MediaStream
  try {
    dongTieng = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
  } catch {
    tatChuong()
    void ctx.close()
    o.onTrangThai('loi')
    o.onError('Không dùng được micro. Trình duyệt chỉ cho phép trên HTTPS hoặc localhost.')
    return { dong: () => {} }
  }

  const nguon = ctx.createMediaStreamSource(dongTieng)
  const avatar = o.avatar ? moAvatar({ url: o.avatar.url, ctx, ve: o.avatar.ve }) : null
  const bam = ctx.createScriptProcessor(4096, 1, 1)
  // Mọi khối audio agent đi qua ĐÂY rồi mới ra loa — chỗ duy nhất đo được
  // "agent đang phát tiếng thật" (xem `onMucLoa`).
  const loa = ctx.createAnalyser()
  loa.fftSize = 2048
  loa.connect(ctx.destination)
  const mauLoa = new Float32Array(loa.fftSize)
  let ws: WebSocket | null = null
  let daDong = false
  // Mốc phát kế tiếp — hàng đợi audio xuống phải nối ĐUÔI nhau, không cùng phát
  // ở `currentTime`, nếu không các khối chồng lên nhau thành tiếng ù.
  let mocPhat = 0
  let mucLoa = 0

  function dong(): void {
    if (daDong) return
    daDong = true
    tatChuong()
    bam.disconnect()
    nguon.disconnect()
    loa.disconnect()
    dongTieng.getTracks().forEach((t) => t.stop())
    avatar?.dong()
    void ctx.close()
    ws?.close()
    o.onMucLoa(0, 0)
    o.onTrangThai('nghi')
  }

  o.onTrangThai('dang_mo')
  try {
    ws = new WebSocket(gopKhoaVaoUrl(o.cauHinh.wsUrl, o.cauHinh.apiKey))
  } catch {
    dong()
    o.onTrangThai('loi')
    o.onError('Địa chỉ phiên thử không hợp lệ.')
    return { dong }
  }
  ws.binaryType = 'arraybuffer'

  ws.onopen = () => {
    // Bắt tay: gateway chờ một JSON định danh trước khi nhận mẫu (doc §1,
    // 10s). `call_id` Ở KÊNH VOICE CÓ DÙNG (đặt tên room) — khác chat.
    ws?.send(
      JSON.stringify({
        identity: locTrongDanhTinh(o.danhTinh),
        call_id: `portal-${Math.floor(performance.now())}`,
      }),
    )
    o.onTrangThai('song')
    mocPhat = ctx.currentTime
    nguon.connect(bam)
    bam.connect(ctx.destination)
  }

  bam.onaudioprocess = (e) => {
    const khoi = e.inputBuffer.getChannelData(0)
    o.onMuc(mucRms(khoi))
    loa.getFloatTimeDomainData(mauLoa)
    mucLoa = mucRms(mauLoa)
    o.onMucLoa(mucLoa, Math.max(0, mocPhat - ctx.currentTime))
    if (ws?.readyState !== WebSocket.OPEN) return
    const pcm = haNhip(khoi, ctx.sampleRate)
    if (pcm.length) ws.send(pcm.buffer)
  }

  ws.onmessage = (e) => {
    if (typeof e.data !== 'string') {
      // BINARY = audio agent (48kHz, xem hằng NHIP_XUONG) — phát qua loa.
      // Tiếng trả lời đầu tiên ⇒ «bắt máy»: tắt chuông chờ. Chỉ khung CÓ
      // TIẾNG — track LiveKit gửi khung im lặng ngay từ lúc worker vào phòng.
      const khoi = e.data as ArrayBuffer
      if (chuong && coTieng(new Int16Array(khoi))) tatChuong()
      // Lip sync: hàng đợi phát đang trống ⇒ dời mốc ra sau `TRE_PHAT_S` để
      // avatar kịp render khẩu hình; các khối sau nối đuôi như cũ (không trễ thêm).
      if (avatar?.sanSang() && mocPhat < ctx.currentTime + 0.02)
        mocPhat = ctx.currentTime + TRE_PHAT_S
      const batDau = phatPcm16(
        ctx,
        loa,
        khoi,
        NHIP_XUONG,
        () => mocPhat,
        (t) => (mocPhat = t),
      )
      if (batDau !== null) avatar?.gui(khoi, batDau)
      o.onMucLoa(mucLoa, Math.max(0, mocPhat - ctx.currentTime))
      return
    }
    let m: Record<string, unknown>
    try {
      m = JSON.parse(e.data) as Record<string, unknown>
    } catch {
      return // quy tắc phòng thủ §5.1: parse fail → skip
    }
    // Khách nói trước khi agent lên tiếng ⇒ cuộc gọi rõ ràng đã thông,
    // chuông không được kêu đè lên lời khách.
    if (m['type'] === 'partial_transcript' || m['type'] === 'transcript') tatChuong()
    // Lip sync: báo hết lượt kèm mốc audio cuối đã xếp lịch (xem `KetNoiAvatar.hetLuot`).
    if (m['type'] === 'agent_done' || m['type'] === 'agent_interrupted') avatar?.hetLuot(mocPhat)
    // Lip sync: agent gửi `agent_speaking` NGAY TRƯỚC frame audio đầu của câu ⇒ câu bắt đầu
    // phát ở cuối hàng đợi hiện tại (hàng đợi trống thì sau `TRE_PHAT_S`, như khối audio kế).
    if (m['type'] === 'agent_speaking' && avatar && typeof m['text'] === 'string') {
      const batDau =
        avatar.sanSang() && mocPhat < ctx.currentTime + 0.02
          ? ctx.currentTime + TRE_PHAT_S
          : Math.max(mocPhat, ctx.currentTime)
      avatar.cau(batDau, uocLuongGiayNoi(m['text']))
    }
    xuLySuKienGiongNoi(m, o)
  }

  ws.onerror = () => {
    o.onTrangThai('loi')
  }
  ws.onclose = (e) => {
    // `daDong` đã `true` khi CHÍNH `dong()` gọi `ws.close()` (đặt trước khi
    // gọi, xem trên) — nên tới đây với `daDong` còn `false` chỉ có thể là
    // gateway/mạng đóng NGOÀI Ý MUỐN. Tự đóng thì `dong()` đã tự báo trạng
    // thái 'nghi', không cần gọi lại gì ở đây.
    if (daDong) return
    daDong = true
    tatChuong()
    avatar?.dong()
    o.onTrangThai('nghi')
    o.onDong(dichLyDoDong(e.code, e.reason, 'voice'))
  }

  return { dong, gioTay: () => avatar?.gioTay() }
}

/**
 * Phân loại 10 event thật (doc §3). THUẦN — nhận JSON đã parse, gọi callback
 * tương ứng. Test được không cần WS/AudioContext, xem `tests/thu-agent.test.tsx`.
 *
 * Liệt kê tường minh (không rơi vào `default` im lặng) để phân biệt "type đã
 * biết nhưng field lệch" khỏi "type THẬT SỰ lạ" — quy tắc phòng thủ §5.1 nói
 * bỏ qua type lạ, nhưng bỏ qua ÂM THẦM một type tưởng đã biết mà backend đổi
 * tên field bên trong thì không ai thấy lỗi. Cảnh báo Console cho ca đó.
 */
export function xuLySuKienGiongNoi(m: Record<string, unknown>, o: TuyChonGiongNoi): void {
  switch (m['type']) {
    case 'partial_transcript':
      o.onPartialTranscript(String(m['text'] ?? ''))
      return
    case 'transcript':
      o.onTranscript(String(m['text'] ?? ''), String(m['turn_id'] ?? ''))
      return
    case 'agent_speaking':
      o.onAgentSpeaking(String(m['text'] ?? ''), String(m['turn_id'] ?? ''))
      return
    case 'agent_done':
      o.onAgentDone(String(m['turn_id'] ?? ''))
      return
    case 'agent_interrupted':
      o.onAgentInterrupted(
        String(m['turn_id'] ?? ''),
        typeof m['last_completed_sentence_id'] === 'number' ? m['last_completed_sentence_id'] : -1,
      )
      return
    case 'tool_start':
      o.onToolStart(String(m['tool'] ?? ''), m['args'])
      return
    case 'tool_done':
      o.onToolDone(String(m['tool'] ?? ''))
      return
    case 'media':
      o.onMedia(chuanHoaMedia(m))
      return
    case 'error':
      o.onError(String(m['message'] ?? 'Lỗi không rõ từ agent.'))
      return
    case 'session_id':
      // Event đầu tiên (spec §3.0, thêm 2026-08-13) — xem `TuyChonGiongNoi.onSessionId`.
      o.onSessionId(String(m['session_id'] ?? ''))
      return
    case 'session_ended':
      o.onSessionEnded(String(m['reason'] ?? ''))
      return
    default:
      // ⚠️ Cùng lý lẽ `chatGateway.ts` — một event lệch tài liệu cần thấy
      // ngay, không phải "khách nói vào khoảng không mà UI im lặng" rồi
      // không biết vì sao.
      console.warn(
        '[giongNoi] event lạ, KHÔNG xử lý — kiểm tra tên `type` có đúng gateway-voice-ws-spec.md không:',
        m,
      )
      return
  }
}

/**
 * Xếp một khối PCM16 vào hàng đợi phát. Trả thời điểm BẮT ĐẦU phát (giây
 * AudioContext) — lip sync gắn frame vào đúng mốc đó; `null` nếu khối rỗng.
 *
 * `mocPhat` đi qua getter/setter chứ không phải biến bắt được: mỗi khối phải
 * bắt đầu ở chỗ khối trước kết thúc, và giá trị đó thay đổi sau mỗi lần gọi.
 */
function phatPcm16(
  ctx: AudioContext,
  dich: AudioNode,
  buf: ArrayBuffer,
  nhip: number,
  docMoc: () => number,
  ghiMoc: (t: number) => void,
): number | null {
  const pcm = new Int16Array(buf)
  if (pcm.length === 0) return null

  const bo = ctx.createBuffer(1, pcm.length, nhip)
  const kenh = bo.getChannelData(0)
  for (let i = 0; i < pcm.length; i++) kenh[i] = (pcm[i] as number) / 0x8000

  const nguon = ctx.createBufferSource()
  nguon.buffer = bo
  nguon.connect(dich)

  // Khối đến trễ hơn mốc đã tính (mạng khựng) thì phát NGAY, đừng phát vào quá
  // khứ — `start()` với thời điểm đã qua sẽ phát tức thì nhưng mốc kế tiếp vẫn
  // tính từ số cũ, và độ trễ tích luỹ mãi không đuổi kịp.
  const batDau = Math.max(docMoc(), ctx.currentTime)
  nguon.start(batDau)
  ghiMoc(batDau + bo.duration)
  return batDau
}

// ─── Cấu hình kết nối ──────────────────────────────────────────────────────
//
// ⚠ KHÔNG CÒN localStorage Ở ĐÂY — `docCauHinhGiongNoiDaLuu()` +
// `luuCauHinhGiongNoi()` xoá 2026-08-27 cùng cặp tương ứng bên `chatGateway.ts`,
// cùng một lý do (đọc thêm docstring ở đó). Kiểu `CauHinhGiongNoi` GIỮ LẠI:
// `CheGiongNoi` vẫn nhận nó qua prop, chỉ là giá trị nay dựng tại chỗ chứ không
// đọc lên từ đĩa.
