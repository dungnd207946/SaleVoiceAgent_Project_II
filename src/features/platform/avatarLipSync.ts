/**
 * Lip sync THẬT cho người dẫn tab Voice — nối tới avatar service MuseTalk
 * (`MuseTalk/scripts/avatar_server.py`, ws :8020). Bật khi có
 * `VITE_AVATAR_WS_URL`; vắng ⇒ sân khấu giữ người dẫn cũ (clip Kling, chỉ
 * mấp máy theo LÚC CÓ TIẾNG — xem `nguoiDan.ts`).
 *
 * ĐỒNG HỒ LÀ `AudioContext` CỦA TRÌNH DUYỆT, không phải server:
 *   1. `giongNoi.ts` xếp lịch mỗi khối PCM agent TRỄ `TRE_PHAT_S` so với lúc
 *      nhận (chỉ khi hàng đợi phát đang trống — các khối sau nối đuôi như cũ),
 *      rồi gửi khối đó kèm THỜI ĐIỂM PHÁT (`tStart`, giây của AudioContext).
 *   2. Server render khẩu hình cho từng 40ms audio, trả frame mang đúng thời
 *      điểm phát của 40ms đó. Khoảng trễ là thời gian để render kịp.
 *   3. Vòng `requestAnimationFrame` ở đây vẽ frame khi `currentTime` tới hạn
 *      — hình và tiếng cùng một đồng hồ nên khớp tuyệt đối, mạng khựng thì
 *      chỉ MẤT FRAME (giữ frame trước), không bao giờ làm lệch tiếng.
 *   4. Ngoài lúc nói, server đẩy frame idle (miệng khép) 25 fps, vẽ ngay.
 *
 * Gói tin (little-endian):
 *   lên:  [f64 ctxNow][f64 tStart][PCM16 48 kHz mono]
 *   xuống:[u8 loai][7 byte đệm][f64 t][JPEG «stacked alpha»] — loai 0 idle, 1 nói
 *
 * ⚠ Không có test tự động cho phần này (jsdom không có AudioContext,
 * createImageBitmap, WebSocket nhị phân) — nghiệm thu bằng mắt + tai.
 */

import { wsUrlCungOrigin } from './api'

/** Trễ phát audio khi bật lip sync. Đo 2026-10-06 trên 5060 Ti (chung card
 *  VieNeu TTS): trễ 1,0s ⇒ frame về sớm hơn hạn tối thiểu 87ms; 1,2s dư ~270ms. */
export const TRE_PHAT_S = 1.2
/** Ảnh chờ (tư thế 0, đã tách nền) — sinh bởi avatar service (`poster.png`). */
export const ANH_CHO_AVATAR = '/nhan-vat-lipsync.png'
/** Tốc độ đọc của OmniVoice — đo 2026-10-14 trên 805 câu thật trong log TTS: median 17,5
 *  ký tự/giây, sai số ước lượng p90 chỉ 4% (độ dài audio gần như tỉ lệ thuận số ký tự).
 *  Đổi engine TTS thì đo lại. */
export const KY_TU_MOI_GIAY = 17.5

/** Câu `text` (từ `agent_speaking`) đọc mất bao nhiêu giây — để avatar service không đưa tay
 *  khi câu không còn đủ dài cho trọn cử chỉ (xem `KetNoiAvatar.cau`). */
export function uocLuongGiayNoi(text: string): number {
  return text.trim().length / KY_TU_MOI_GIAY
}

/** Frame nói tới hạn quá chừng này mà chưa vẽ ⇒ bỏ (đã muộn, vẽ là lệch tiếng). */
const QUA_HAN_S = 0.08

/**
 * URL avatar service — đọc lúc gọi (không lúc nạp module) để test tắt được.
 *
 * Hai dạng:
 *  - đường dẫn `/lipsync/avatar` (bản deploy, đặt ở Dockerfile) ⇒ CÙNG ORIGIN, đi qua
 *    nginx của portal: `wss://` theo trang, và nginx gắn token phía server — trình
 *    duyệt không bao giờ thấy ODYSSEY_MODELS_TOKEN (xem deploy/*.conf.template).
 *  - URL đầy đủ `ws://localhost:8020/avatar` (máy dev, `.env`) ⇒ nối thẳng service.
 * Rỗng ⇒ tắt lip sync, sân khấu dùng người dẫn Kling cũ.
 *
 * `avatarId` = nhân vật workspace tự tạo (`nhanVat.ts`) ⇒ `?avatar=<id>`; vắng ⇒
 * người dẫn mặc định của service. Nhân vật chưa có trên service ⇒ server đóng 4404,
 * cuộc gọi vẫn chạy (tiếng không chờ hình), sân khấu đứng ở ảnh chờ.
 */
export function urlAvatar(avatarId?: string | null): string {
  const u = (import.meta.env.VITE_AVATAR_WS_URL as string | undefined) ?? ''
  const goc = u.startsWith('/') ? wsUrlCungOrigin(u) : u
  if (!goc || !avatarId) return goc
  return `${goc}${goc.includes('?') ? '&' : '?'}avatar=${encodeURIComponent(avatarId)}`
}

export type VeAvatar = (anh: ImageBitmap) => void

export interface KetNoiAvatar {
  /** Đã nối và server sẵn sàng — chỉ khi đó mới nên trễ phát để chờ hình. */
  sanSang(): boolean
  /** Gửi một khối PCM16 48 kHz sẽ phát ở `tStart` (giây AudioContext). */
  gui(pcm: ArrayBuffer, tStart: number): void
  /** Đưa tay giới thiệu (agent vừa gửi ảnh) — server rẽ vào đoạn G ở lần tới cuối F. */
  gioTay(): void
  /** Một câu (`agent_speaking`) bắt đầu ở `t` (giây AudioContext), dài ~`giay` giây. Server chỉ
   *  đưa tay khi câu còn đủ dài để làm TRỌN cử chỉ — đưa tay sát cuối câu thì hết câu tay đang
   *  giơ, nhân vật về chờ đột ngột. */
  cau(t: number, giay: number): void
  /** Lượt trả lời đã xong (`agent_done`/`agent_interrupted`); audio đã xếp lịch hết ở `t`
   *  (giây AudioContext). Avatar service dùng nó để thôi «giữ đang nói» và đưa nhân vật
   *  về tư thế chờ đúng lúc tiếng tắt, thay vì cử động thừa ~1s sau câu cuối. */
  hetLuot(t: number): void
  dong(): void
}

interface KhungCho {
  t: number
  anh: ImageBitmap
}

export function moAvatar(o: {
  url: string
  ctx: AudioContext
  ve: () => VeAvatar | null
}): KetNoiAvatar {
  let ws: WebSocket | null = null
  let san = false
  let daDong = false
  let raf = 0
  const hangDoi: KhungCho[] = [] // frame nói, xếp theo t
  let tCuoiNoi = -Infinity // t của frame nói gần nhất đã vẽ
  // Đếm để chẩn đoán giật (in ra console lúc đóng): frame nói đã vẽ · bỏ vì giải
  // mã xong thì đã quá hạn · bị frame sau đè trong cùng một nhịp vẽ · frame chờ đã vẽ.
  const dem = { noi: 0, quaHan: 0, biDe: 0, cho: 0 }

  const ve = (anh: ImageBitmap): void => {
    const f = o.ve()
    if (f) f(anh)
    anh.close()
  }

  try {
    ws = new WebSocket(o.url)
    ws.binaryType = 'arraybuffer'
  } catch {
    ws = null
  }
  if (ws) {
    ws.onmessage = (e) => {
      if (typeof e.data === 'string') {
        if ((JSON.parse(e.data) as { type?: string }).type === 'ready') san = true
        return
      }
      const buf = e.data as ArrayBuffer
      const dv = new DataView(buf)
      const loai = dv.getUint8(0)
      const t = dv.getFloat64(8, true)
      void createImageBitmap(new Blob([buf.slice(16)], { type: 'image/jpeg' })).then((anh) => {
        if (daDong) return anh.close()
        const bayGio = o.ctx.currentTime
        if (loai === 1) {
          if (t < bayGio - QUA_HAN_S) {
            dem.quaHan++
            return anh.close()
          }
          let i = hangDoi.length
          while (i > 0 && (hangDoi[i - 1] as KhungCho).t > t) i--
          hangDoi.splice(i, 0, { t, anh })
          return
        }
        // Idle: chỉ vẽ khi không có lời nói nào đang/sắp hiện — nếu không, frame
        // idle (miệng khép) chen giữa hai frame nói thành nháy miệng.
        const sapNoi = hangDoi.length > 0 && (hangDoi[0] as KhungCho).t <= bayGio + 0.04
        if (sapNoi || bayGio < tCuoiNoi + 0.06) return anh.close()
        dem.cho++
        ve(anh)
      })
    }
    ws.onclose = () => {
      san = false
    }
  }

  const nhip = (): void => {
    const bayGio = o.ctx.currentTime
    let moi: KhungCho | null = null
    while (hangDoi.length > 0 && (hangDoi[0] as KhungCho).t <= bayGio) {
      const k = hangDoi.shift() as KhungCho
      if (moi) {
        moi.anh.close()
        dem.biDe++
      }
      moi = k
    }
    if (moi) {
      dem.noi++
      tCuoiNoi = moi.t
      ve(moi.anh)
    }
    raf = requestAnimationFrame(nhip)
  }
  raf = requestAnimationFrame(nhip)

  return {
    sanSang: () => san && ws?.readyState === WebSocket.OPEN,
    gui(pcm, tStart) {
      if (!san || ws?.readyState !== WebSocket.OPEN) return
      const goi = new Uint8Array(16 + pcm.byteLength)
      const dv = new DataView(goi.buffer)
      dv.setFloat64(0, o.ctx.currentTime, true)
      dv.setFloat64(8, tStart, true)
      goi.set(new Uint8Array(pcm), 16)
      ws.send(goi.buffer)
    },
    hetLuot(t) {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'het_luot', t }))
    },
    gioTay() {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'gio_tay' }))
    },
    cau(t, giay) {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'cau', t, s: giay }))
    },
    dong() {
      if (!daDong) console.info('[avatar] frame:', dem)
      daDong = true
      cancelAnimationFrame(raf)
      for (const k of hangDoi.splice(0)) k.anh.close()
      ws?.close()
    },
  }
}
