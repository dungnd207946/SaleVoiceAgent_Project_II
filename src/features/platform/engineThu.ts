/**
 * Engine / model trang Thử agent (tab Chat) chọn cho RIÊNG một phiên. Agent nhận qua tin
 * `{"type":"engine", engine, provider?, model?}` ngay sau `session_id` và trả `engine_ok` — chỉ khi worker bật
 * `CHAT_SEND_TRACE` (môi trường thử); tắt thì trả `error`, khách thật không đổi được model.
 *
 * `MODEL_V2` là bản CHÉP TAY: provider phải là slot agent có khoá (`dashscope` · `vllm` · `gemini`), model đã đối
 * chiếu với API thật lúc viết (14/10/2026). Thiếu khoá ⇒ agent báo lỗi ngay lúc đổi; model sai tên ⇒ lỗi ở lượt đầu.
 */

/** `''` = theo cấu hình server (không gửi tin engine). */
export type EngineThu = '' | 'legacy' | 'v2'

export interface ChonEngine {
  readonly engine: EngineThu
  /** `provider/model` trong `MODEL_V2`, `''` = model mặc định của server. Chỉ có nghĩa khi engine = v2. */
  readonly model: string
}

/** Mặc định V2 + Qwen3.6 35B-A3B DashScope (người dùng chốt 14/10) — «Theo server» vẫn chọn được. */
export const CHON_MAC_DINH: ChonEngine = { engine: 'v2', model: 'dashscope/qwen3.6-35b-a3b' }

export const MODEL_V2: readonly { readonly gt: string; readonly nhan: string }[] = [
  { gt: 'dashscope/qwen3.6-35b-a3b', nhan: 'Qwen3.6 35B-A3B · DashScope' },
  { gt: 'vllm/qwen3.6-35b-a3b', nhan: 'Qwen3.6 35B-A3B · self-host' },
  { gt: 'dashscope/qwen3.7-flash', nhan: 'Qwen3.7 Flash · DashScope' },
  { gt: 'gemini/gemini-2.5-flash', nhan: 'Gemini 2.5 Flash' },
  { gt: 'gemini/gemini-3.1-flash-lite', nhan: 'Gemini 3.1 Flash-Lite' },
  { gt: 'gemini/gemini-3.5-flash-lite', nhan: 'Gemini 3.5 Flash-Lite' },
  { gt: 'gemini/gemini-3.7-flash', nhan: 'Gemini 3.7 Flash' },
]

/** Tin gửi agent sau `session_id`; `null` = theo server, không gửi gì. */
export function tinDoiEngine(c: ChonEngine): Record<string, string> | null {
  if (c.engine === '') return null
  const tin: Record<string, string> = { type: 'engine', engine: c.engine }
  const i = c.model.indexOf('/')
  if (c.engine === 'v2' && i > 0) {
    tin['provider'] = c.model.slice(0, i)
    tin['model'] = c.model.slice(i + 1)
  }
  return tin
}
