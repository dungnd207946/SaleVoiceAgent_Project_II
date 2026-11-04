/**
 * Tiếng «tút… tút…» chờ bắt máy (ringback) của tab Voice — phát từ lúc bấm
 * «Bắt đầu trò chuyện» tới khi tiếng trả lời ĐẦU TIÊN của agent ra loa.
 *
 * Tự tổng hợp bằng Web Audio (một `OscillatorNode` + đường bao âm lượng xếp
 * lịch sẵn), không có tệp âm thanh: không thêm request, không phải chờ tải
 * đúng lúc cần phát ngay.
 *
 * Âm hiệu chuẩn hồi âm chuông của Việt Nam: **425 Hz, kêu 1s · nghỉ 4s**.
 * Tiếng đầu kêu NGAY khi bấm — người dùng cần biết cú bấm đã có tác dụng.
 *
 * ⚠️ Nối thẳng vào `ctx.destination`, KHÔNG qua `AnalyserNode` của tiếng agent
 * (`giongNoi.ts`): analyser đó nuôi người dẫn trên sân khấu, cho tiếng chuông
 * đi qua là người dẫn mấp máy môi theo tiếng tút.
 */

export const TAN_SO_CHUONG = 425
export const KEU_S = 1
export const NGHI_S = 4
/** Âm lượng đỉnh — nhỏ hơn hẳn tiếng agent, chỉ là tín hiệu nền. */
export const AM_LUONG_CHUONG = 0.12
/** Lên/xuống âm lượng ở mỗi mép tiếng — cắt vuông thì nghe «tách» ở loa. */
export const MEP_S = 0.02
/**
 * Kêu tối đa chừng này rồi tự tắt. Agent không chào trước (chờ khách nói) thì
 * tiếng chuông không được kêu mãi che mất lời khách.
 */
export const TOI_DA_S = 60

/**
 * Ngưỡng «khung audio có TIẾNG» (RMS, thang 0…1 ≈ −40 dBFS). Gateway chuyển
 * nguyên track LiveKit của agent, mà WebRTC phát khung IM LẶNG liên tục ngay
 * khi worker vào phòng — tắt chuông ở khung nhị phân ĐẦU TIÊN là tắt sau ~1s,
 * chỉ kịp một tiếng tút (người dùng báo 2026-10-02). Phải chờ khung có tiếng.
 */
export const NGUONG_CO_TIENG = 0.01

/** Khung PCM16 có tiếng nói thật (không phải khung im lặng/nhiễu nền). */
export function coTieng(pcm: Int16Array): boolean {
  if (pcm.length === 0) return false
  let e = 0
  for (let i = 0; i < pcm.length; i++) {
    const x = (pcm[i] as number) / 0x8000
    e += x * x
  }
  return Math.sqrt(e / pcm.length) >= NGUONG_CO_TIENG
}

/** Các khoảng [bắt đầu, kết thúc] (giây, theo đồng hồ `AudioContext`) của
 *  từng tiếng tút trong `tongS` giây kể từ `t0`. Thuần — để test. */
export function lichChuong(t0: number, tongS: number = TOI_DA_S): Array<readonly [number, number]> {
  const ra: Array<readonly [number, number]> = []
  for (let t = t0; t < t0 + tongS; t += KEU_S + NGHI_S) {
    ra.push([t, Math.min(t + KEU_S, t0 + tongS)])
  }
  return ra
}

export interface ChuongCho {
  /** Tắt (mờ dần trong `MEP_S`). Gọi nhiều lần vô hại. */
  readonly tat: () => void
}

export function batChuongCho(ctx: AudioContext): ChuongCho {
  const osc = ctx.createOscillator()
  const am = ctx.createGain()
  osc.type = 'sine'
  osc.frequency.value = TAN_SO_CHUONG
  am.gain.value = 0
  osc.connect(am)
  am.connect(ctx.destination)

  const t0 = ctx.currentTime + 0.03
  for (const [a, b] of lichChuong(t0)) {
    am.gain.setValueAtTime(0, a)
    am.gain.linearRampToValueAtTime(AM_LUONG_CHUONG, a + MEP_S)
    am.gain.setValueAtTime(AM_LUONG_CHUONG, b - MEP_S)
    am.gain.linearRampToValueAtTime(0, b)
  }
  osc.start(t0)
  osc.stop(t0 + TOI_DA_S)

  let daTat = false
  return {
    tat() {
      if (daTat) return
      daTat = true
      if (ctx.state === 'closed') return
      const t = ctx.currentTime
      am.gain.cancelScheduledValues(t)
      am.gain.setValueAtTime(am.gain.value, t)
      am.gain.linearRampToValueAtTime(0, t + MEP_S)
      try {
        osc.stop(t + MEP_S + 0.01)
      } catch {
        // đã dừng theo lịch `TOI_DA_S`
      }
      osc.onended = () => {
        osc.disconnect()
        am.disconnect()
      }
    },
  }
}
