/**
 * MÔ PHỎNG tab Voice của `/thu-agent` — CHỈ DÙNG Ở DEV (`/mo-phong-voice.html`).
 *
 * Render đúng `ThuAgentScreen` THẬT (cùng component, cùng CSS) nhưng thay ba
 * thứ bên ngoài bằng đồ giả chạy trong trình duyệt, để xem trước giao diện khi
 * hệ thống chưa có dữ liệu thật (người dùng yêu cầu 2026-10-02):
 *
 * - HTTP (`/agent/keys` · `/config` · `/agent/feedback`) ⇒ MSW, cùng fake của `make dev`;
 * - `WebSocket` ⇒ «gateway giả» chạy một KỊCH BẢN hội thoại: chào, khách hỏi,
 *   agent gửi ảnh (`media` — album trên sân khấu), trả lời giá… Mỗi câu agent
 *   kèm khung audio PCM thật (tiếng rì rầm nhỏ) để chuông chờ, người dẫn nhép
 *   môi, phụ đề, đồng hồ cuộc gọi chạy đúng đường ống thật;
 * - `getUserMedia` ⇒ một luồng micro im lặng (không xin quyền).
 *
 * `vite build` chỉ lấy `index.html` làm đầu vào nên trang này không lên
 * production. Ảnh mẫu của album: `background1.jpg` + ảnh ngẫu nhiên từ picsum.photos.
 */
/* eslint-disable react-refresh/only-export-components -- tệp ENTRY của trang dev, không phải module HMR */
import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from '@tanstack/react-router'
import '@/styles/theme.css'
import { LangProvider } from '@/i18n'
import { ThuAgentScreen } from '@/features/platform/components/ThuAgentScreen'
import { startMsw } from '@/lib/msw/browser'

// ─── Micro giả: luồng im lặng, không xin quyền ───────────────────────────────

Object.defineProperty(navigator, 'mediaDevices', {
  configurable: true,
  value: {
    getUserMedia: async () => new AudioContext().createMediaStreamDestination().stream,
  },
})

// ─── Ảnh mẫu ─────────────────────────────────────────────────────────────────

const anh = (seed: string, label: string, index: number) => ({
  kind: 'image',
  url: `https://picsum.photos/seed/${seed}/1200/800`,
  thumb: `https://picsum.photos/seed/${seed}/400/267`,
  label,
  index,
})
const ALBUM_5 = [
  {
    kind: 'image',
    url: '/background1.jpg',
    thumb: '/background1.jpg',
    label: 'Phối cảnh tổng thể',
    index: 1,
  },
  anh('noble-phong-khach', 'Phòng khách căn 2PN', 2),
  anh('noble-ho-boi', 'Hồ bơi vô cực tầng 5', 3),
  anh('noble-cong-vien', 'Công viên nội khu', 4),
  anh('noble-sanh', 'Sảnh đón tiếp', 5),
]
const ALBUM_1 = [anh('noble-mat-bang', 'Mặt bằng căn 2PN — 72 m²', 1)]

// ─── Gateway giả + kịch bản ──────────────────────────────────────────────────

const NHIP = 48_000

/** Khung PCM16 48kHz «rì rầm» — đủ to để vượt ngưỡng `coTieng` (tắt chuông
 *  chờ) và ngưỡng nhép môi của người dẫn, nhỏ để không chói tai. Nhịp âm tiết
 *  ~4/giây để người dẫn mấp máy theo nhịp, không há miệng liên tục. */
function tiengRiRam(giay: number, pha = 0): ArrayBuffer[] {
  const khoi: ArrayBuffer[] = []
  const moiKhoi = NHIP / 10
  const tong = Math.floor(giay * NHIP)
  for (let dau = 0; dau < tong; dau += moiKhoi) {
    const pcm = new Int16Array(Math.min(moiKhoi, tong - dau))
    for (let k = 0; k < pcm.length; k++) {
      const t = (dau + k) / NHIP + pha
      const amTiet = Math.max(0, Math.sin(2 * Math.PI * 3.7 * t)) ** 0.6
      const x =
        (0.6 * Math.sin(2 * Math.PI * 165 * t) + 0.4 * Math.sin(2 * Math.PI * 247 * t)) * amTiet
      pcm[k] = Math.round(x * 0.06 * 0x7fff)
    }
    khoi.push(pcm.buffer)
  }
  return khoi
}

type Buoc = { sau: number; lam: (g: GatewayGia) => void }

let phienHienTai: GatewayGia | null = null
let soLuot = 0

class GatewayGia {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  readyState = 0
  binaryType = 'arraybuffer'
  onopen: (() => void) | null = null
  onmessage: ((e: { data: unknown }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((e: { code: number; reason: string }) => void) | null = null
  private hen: number[] = []

  readonly url: string

  constructor(url: string) {
    this.url = url
    // eslint-disable-next-line @typescript-eslint/no-this-alias -- nút bảng điều khiển cần phiên đang mở
    phienHienTai = this
    // Chuông chờ kêu ~2 nhịp rồi «bắt máy» như một cuộc gọi thật.
    this.henGio(500, () => {
      this.readyState = 1
      this.onopen?.()
      this.gui({ type: 'session_id', session_id: `mo-phong-${Date.now()}` })
      this.chay(KICH_BAN)
    })
  }
  send(): void {}
  close(): void {
    this.hen.forEach((h) => window.clearTimeout(h))
    this.hen = []
    if (this.readyState === 3) return
    this.readyState = 3
    if (phienHienTai === this) phienHienTai = null
    this.onclose?.({ code: 1000, reason: '' })
  }
  henGio(ms: number, f: () => void): void {
    this.hen.push(
      window.setTimeout(
        () => (this.readyState === 1 || this.readyState === 0 ? f() : undefined),
        ms,
      ),
    )
  }
  gui(o: unknown): void {
    this.onmessage?.({ data: JSON.stringify(o) })
  }
  chay(kb: readonly Buoc[]): void {
    let t = 0
    for (const b of kb) {
      t += b.sau
      this.henGio(t, () => b.lam(this))
    }
  }
  /** Agent nói từng câu: `agent_speaking` + audio của câu đó, rồi `agent_done`. */
  noi(turn: string, cau: readonly string[], giayMoiCau = 3.2): void {
    cau.forEach((c, i) =>
      this.henGio(i * giayMoiCau * 1000, () => {
        this.gui({ type: 'agent_speaking', text: c, turn_id: turn })
        for (const k of tiengRiRam(giayMoiCau - 0.25, i)) this.onmessage?.({ data: k })
      }),
    )
    this.henGio(cau.length * giayMoiCau * 1000 - 600, () =>
      this.gui({ type: 'agent_done', turn_id: turn }),
    )
  }
  /** Khách nói: vài bản nháp `partial_transcript` rồi bản chốt `transcript`. */
  khachNoi(turn: string, cau: string): void {
    const tu = cau.split(' ')
    tu.forEach((_, i) =>
      this.henGio(i * 180, () =>
        this.gui({ type: 'partial_transcript', text: tu.slice(0, i + 1).join(' ') }),
      ),
    )
    this.henGio(tu.length * 180 + 300, () =>
      this.gui({ type: 'transcript', text: cau, turn_id: turn }),
    )
  }
  guiAnh(items: readonly unknown[], caption: string): void {
    this.gui({ type: 'tool_start', tool: 'send_media', args: {} })
    this.henGio(700, () => {
      this.gui({ type: 'tool_done', tool: 'send_media' })
      this.gui({ type: 'media', items, caption })
    })
  }
}

const KICH_BAN: readonly Buoc[] = [
  {
    sau: 600,
    lam: (g) =>
      g.noi('chao', [
        'Dạ em chào anh, em là trợ lý tư vấn dự án Noble Crystal ạ.',
        'Anh đang quan tâm căn hộ mấy phòng ngủ để em tư vấn kỹ hơn ạ?',
      ]),
  },
  { sau: 7_400, lam: (g) => g.khachNoi('t1', 'Cho anh xem hình ảnh dự án được không em') },
  {
    sau: 2_600,
    lam: (g) => {
      g.guiAnh(ALBUM_5, 'Noble Crystal — hình ảnh dự án')
      g.henGio(900, () =>
        g.noi('t1', [
          'Dạ em gửi anh một số hình ảnh của dự án ạ.',
          'Đây là phối cảnh tổng thể hai toà tháp bốn mươi tầng, ngay cạnh tuyến metro.',
          'Tiếp theo là phòng khách căn hai phòng ngủ, hồ bơi vô cực và công viên nội khu ạ.',
        ]),
      )
    },
  },
  { sau: 12_500, lam: (g) => g.khachNoi('t2', 'Căn hai phòng ngủ giá khoảng bao nhiêu em') },
  {
    sau: 2_600,
    lam: (g) =>
      g.noi('t2', [
        'Dạ căn hai phòng ngủ diện tích từ bảy mươi hai mét vuông, giá từ khoảng bốn phẩy hai tỷ ạ.',
        'Hiện dự án có chính sách thanh toán ba mươi phần trăm nhận nhà ạ.',
      ]),
  },
  { sau: 8_000, lam: (g) => g.khachNoi('t3', 'Có mặt bằng căn đó không em') },
  {
    sau: 2_600,
    lam: (g) => {
      g.guiAnh(ALBUM_1, 'Mặt bằng căn 2PN')
      g.henGio(900, () =>
        g.noi('t3', [
          'Dạ đây là mặt bằng căn hai phòng ngủ bảy mươi hai mét vuông ạ.',
          'Phòng khách và ban công hướng Đông Nam, rất thoáng anh nhé.',
        ]),
      )
    },
  },
]

window.WebSocket = GatewayGia as unknown as typeof WebSocket

// ─── Bảng điều khiển mô phỏng ────────────────────────────────────────────────

function nutTheoChu(re: RegExp): HTMLElement | undefined {
  return [...document.querySelectorAll<HTMLElement>('button, [role=tab]')].find((b) =>
    re.test(b.textContent ?? ''),
  )
}

function BangDieuKhien() {
  const [, ve] = useState(0)
  useEffect(() => {
    const id = window.setInterval(() => ve((n) => n + 1), 500)
    return () => window.clearInterval(id)
  }, [])
  const coPhien = phienHienTai?.readyState === 1
  const nut =
    'h-8 flex-none cursor-pointer whitespace-nowrap rounded-md border border-border-field bg-surface px-3 text-phu text-fg hover:bg-fill-strong disabled:cursor-not-allowed disabled:opacity-50'
  return (
    <div
      className={`fixed right-3 top-3 z-[90] flex max-w-[calc(100vw-24px)] items-center gap-2 rounded-lg border border-border bg-surface/95 p-2.5 shadow-lg backdrop-blur-md ${
        new URLSearchParams(location.search).has('nhung')
          ? 'left-3 flex-nowrap overflow-x-auto p-1.5'
          : 'flex-wrap'
      }`}
    >
      <span className="px-1 text-[11.5px] font-semibold text-muted">MÔ PHỎNG</span>
      <button
        type="button"
        className={nut}
        onClick={() => {
          nutTheoChu(/^Voice$/)?.click()
          window.setTimeout(() => nutTheoChu(/^Áp dụng$/)?.click(), 400)
        }}
      >
        ① Mở Voice + Áp dụng
      </button>
      <button
        type="button"
        className={nut}
        onClick={() => nutTheoChu(/Bắt đầu trò chuyện/)?.click()}
      >
        ② Gọi (chạy kịch bản)
      </button>
      <button
        type="button"
        className={nut}
        disabled={!coPhien}
        onClick={() => {
          const g = phienHienTai
          if (!g) return
          soLuot += 1
          g.guiAnh(ALBUM_5, 'Noble Crystal — hình ảnh dự án')
          g.henGio(900, () => g.noi(`them-${soLuot}`, ['Dạ em gửi anh thêm hình ảnh dự án ạ.']))
        }}
      >
        Gửi album 5 ảnh
      </button>
      <button
        type="button"
        className={nut}
        disabled={!coPhien}
        onClick={() => {
          const g = phienHienTai
          if (!g) return
          soLuot += 1
          g.guiAnh(ALBUM_1, 'Mặt bằng căn 2PN')
        }}
      >
        Gửi 1 ảnh
      </button>
      {!new URLSearchParams(location.search).has('nhung') && (
        <a className={`${nut} inline-flex items-center no-underline`} href="?mobile=1">
          Xem khung điện thoại
        </a>
      )}
    </div>
  )
}

// ─── Khung app (rail + panel giả để bề ngang nội dung giống thật) ────────────

function KhungApp() {
  return (
    <div className="flex h-dvh bg-bg">
      <div className="hidden w-[68px] flex-none bg-chrome-1 lg:block" />
      <div className="hidden w-[240px] flex-none border-r border-border bg-chrome-2 lg:block" />
      <main className="relative h-dvh min-w-0 flex-1 overflow-auto">
        <header className="sticky top-0 z-30 flex h-[72px] items-center border-b border-border bg-bg/86 px-7 backdrop-blur-[10px] max-md:h-14 max-md:px-4">
          <h1 className="m-0 text-[17px] font-semibold text-fg">Thử agent</h1>
        </header>
        <ThuAgentScreen />
      </main>
      <BangDieuKhien />
    </div>
  )
}

function KhungDienThoai() {
  return (
    <div className="flex min-h-dvh flex-col items-center gap-3 bg-fill-strong py-6">
      <a className="text-[13px]" href="?">
        ‹ Về khung desktop
      </a>
      <iframe
        title="Mô phỏng điện thoại"
        src="?nhung=1"
        className="h-[844px] w-[390px] rounded-[28px] border-8 border-n10 bg-bg shadow-xl"
      />
    </div>
  )
}

const goc = createRootRoute({
  component: () =>
    new URLSearchParams(location.search).has('mobile') ? <KhungDienThoai /> : <KhungApp />,
})
const router = createRouter({
  routeTree: goc,
  history: createMemoryHistory({ initialEntries: ['/thu-agent'] }),
})
const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })

void startMsw().then(() =>
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={qc}>
        <LangProvider>
          <RouterProvider router={router} />
        </LangProvider>
      </QueryClientProvider>
    </StrictMode>,
  ),
)
