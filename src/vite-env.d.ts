/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** '0' = tắt MSW (dùng backend thật). Mặc định bật. */
  readonly VITE_MSW?: string
  /** WS URL gateway agent — tab Chat của /thu-agent. Rỗng = domain prod. */
  readonly VITE_AGENT_WS_URL_CHAT?: string
  /** WS URL gateway agent — tab Voice của /thu-agent. Rỗng = domain prod. */
  readonly VITE_AGENT_WS_URL_VOICE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
