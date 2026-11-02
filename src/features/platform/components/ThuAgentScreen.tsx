/**
 * Màn «Thử agent» (`/thu-agent`) — hai cách thử: **Chat** và **Voice**, CẢ HAI
 * nối THẲNG từ trình duyệt tới gateway thật, không qua backend nào cả.
 *
 * ⚠️ VOICE VIẾT LẠI TOÀN BỘ 2026-08-11, theo tài liệu spec chính thức của team
 * gateway (`odyssey-portal-backend/docs/build_test_agent/gateway-voice-ws-spec.md`
 * + mục §8 của tài liệu handoff Chat cùng thư mục). Bản trước (khôi phục cùng
 * ngày, sớm hơn) dùng mô hình "vé" — `POST /agent/try/voice` đổi `keyId` lấy
 * một `wsUrl` ngắn hạn — vì giả định portal không lưu khoá thô. Giả định đó
 * đã SAI: Chat đã đổi sang chọn khoá thô THEO TÊN (migration `0918` backend,
 * xem `ThietLapPhien`), và Voice giờ dùng LẠI ĐÚNG khoá đó — không có vé,
 * không có backend nào ở giữa. Xem chi tiết ở docstring `giongNoi.ts`.
 *
 * Vì cơ chế kết nối giờ giống nhau (khoá thô + WS URL), **Chat và Voice dùng
 * CHUNG** `ThietLapPhien` và phần lọc khoá `khoaDungDuoc()` — chỉ khác đích
 * nối (`/v1/chat` vs `/v1/voice`) và giao thức frame sau khi nối.
 *
 * **Danh tính (`danhTinh`) + `apiKey` sống ở `ThuAgentScreen` (2026-08-11, lần
 * ba)** — KHÔNG còn là state cục bộ của từng tab. Trước đó mỗi tab tự giữ
 * riêng, nên đổi tab (unmount/remount qua ternary dưới cùng) xoá sạch chữ vừa
 * gõ — người dùng phải gõ lại họ tên/SĐT/giới tính/key mỗi lần nhìn sang tab
 * kia. Nay `CheChat`/`CheGiongNoiManHinh` NHẬN `danhTinh`/`apiKey`/setter qua
 * props, tự bọc thêm hành vi riêng của tab (tắt phiên khi sửa) rồi mới gọi
 * setter chung. CHỈ hai trường ĐÓ dùng chung — phần "phiên" (`daApDung`, WS
 * đang mở, lịch sử tin nhắn) vẫn để RIÊNG mỗi tab, vì phiên là tài nguyên sống
 * (mic, WebSocket) gắn với việc component có đang mount hay không: đổi tab
 * vẫn unmount tab cũ như trước, phiên của nó vẫn bị đóng — chỉ có CHỮ ĐÃ GÕ
 * là sống sót, không phải cuộc gọi/hội thoại đang chạy. Quay lại tab đó vẫn
 * phải bấm Áp dụng lần nữa.
 *
 * ⚠️ **WS URL KHÔNG còn là ô nhập từ 2026-08-11** — mỗi tenant dev chỉ có
 * đúng một domain gateway, không có lý do bắt gõ lại mỗi lần mở màn. Giá trị
 * FIX CỨNG trong code (`WS_URL_CHAT_MAC_DINH`/`WS_URL_VOICE_MAC_DINH`), logic mở
 * WS (`moPhienChatGateway`/`moPhienGiongNoi`) vẫn nhận đúng tham số này như
 * trước — chỉ khác nguồn: hằng số thay vì state + ô nhập.
 *
 * ─────────────────────────────────────────────────────────────────────────
 *
 * Chat qua GATEWAY THẬT (`/v1/chat`). Viết lại LẦN BỐN 2026-08-10, theo tài
 * liệu handoff chính thức của team gateway
 * (`odyssey-portal-backend/docs/build_test_agent/2026-08-10-frontend-chat-gateway-handoff.md`).
 *
 * Hình dạng form: **Họ tên · Số điện thoại · Giới tính · API Key**, BỐN ô
 * (WS URL từng là ô thứ năm — bỏ khỏi UI 2026-08-11, xem khối docstring trên).
 *
 * ĐIỂM ĐỔI Ở LẦN NÀY: bỏ hẳn relay backend (`agent_demo`, đã xoá). Tài liệu
 * handoff xác nhận trình duyệt nối THẲNG được tới gateway qua `?key=` trong
 * URL (gateway tự đổi thành `Authorization: Bearer`) — relay là dư, không
 * phải bắt buộc như suy đoán trước đó. `chatGateway.ts` giờ mở WebSocket
 * trực tiếp từ trình duyệt, không qua backend nào cả.
 *
 * API Key là `<select>` chọn THEO TÊN (2026-08-11, đảo lại quyết định
 * "dán khoá thô" ở trên) — backend từ migration `0918` lưu THÊM cột khoá thô
 * (`Khoa.api_key`, cạnh hash xác thực không đổi), theo yêu cầu tường minh của
 * người vận hành. Giá trị `<option>` là khoá thô thật (không phải `id`): WS
 * nối THẲNG từ trình duyệt, không qua backend đổi vé, nên cần chuỗi Bearer
 * thật ngay tại đây. Khoá tạo TRƯỚC migration `0918` có `api_key: null` — bị
 * lọc khỏi danh sách chọn (`khoaDungDuoc()`), không "chọn được nhưng chọn
 * xong lại rỗng".
 *
 * Lịch sử hội thoại sống trong state màn — rời màn là mất, chủ ý (ô thử,
 * không phải kênh hội thoại có lưu trữ).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useSaoChep } from '@/lib/saoChep'
import { createPortal } from 'react-dom'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { Icon } from '@/components/icons'
import { HANG_NUT, NhomTab, NUT_CHINH, NUT_PHU, type MucTab } from '@/components/ui/Bang'
import { HopThoai } from '@/components/ui/HopThoai'
import { useLang } from '@/i18n'
import { giamChuyenDong } from '@/lib/giamChuyenDong'
import { CAU_HINH_QUERY, docCauHinh } from '@/features/agent/contracts'
import { KHOA_QUERY, taiKhoa, WS_URL_CHAT_MAC_DINH, WS_URL_VOICE_MAC_DINH, type Khoa } from '../api'
import {
  chiSo,
  danhTinhMacDinh,
  locTrong,
  O_DANH_TINH,
  soTruongDaKhai,
  type FormDanhTinh,
} from '../danhTinhKhach'
import {
  moPhienChatGateway,
  type EngineDangChay,
  type GoiY,
  type MedItemAnh,
  type MucMedia,
  type PhienChatGatewayMo,
  type TraceLuot,
} from '../chatGateway'
import {
  CHON_MAC_DINH,
  MODEL_V2,
  tinDoiEngine,
  type ChonEngine,
  type EngineThu,
} from '../engineThu'
import { ID_PANEL_LUONG, LuongXuLy, PanelLuong, TomTatLuong } from './LuongXuLy'
import { useKhoManHinh } from '@/lib/khoManHinh'
import { taiTruocAnh } from '../taiAnh'
import { useTuCuonCuoi } from '../useTuCuonCuoi'
import { DanhGiaPhien } from './DanhGiaPhien'
import { TIN_HIEU_IM, type TinHieuLoa } from '../nguoiDan'
import { urlAvatar, type VeAvatar } from '../avatarLipSync'
import {
  anhHienTai,
  anhTuMedia,
  giuAnh,
  LUAN_PHIEN_TRONG,
  nhanBoAnh,
  sangAnh,
  themAnh,
  nhipDoiAnh,
  xongLuot,
  type LuanPhienAnh,
} from '../sanKhau'
import { SanKhauAgent } from './SanKhauAgent'
import { KhungNguoiDan } from './NutNguoiDan'
import { useNguoiDanDangDung } from '../nhanVat'
import {
  BoCucVoice,
  KHUNG_VOICE,
  HoiThoaiTrong,
  KhungHoiThoaiVoice,
  LopPhuSanKhau,
  ThanhGoi,
} from './VoiceGiaoDien'
import {
  moPhienGiongNoi,
  type CauHinhGiongNoi,
  type MediaGiongNoi,
  type PhienGiongNoi,
  type TrangThaiGiongNoi,
} from '../giongNoi'
import { panelTab } from '@/components/ui/panelTab'

type Che = 'chat' | 'noi'

// ─── Vỏ chung ────────────────────────────────────────────────────────────────

/**
 * Bộ tab RIÊNG viết tay ở đây đã bỏ (2026-08-08) — giờ gọi `NhomTab` dùng chung
 * (xem luật thứ 4 mục Design token trong `CLAUDE.md`).
 */
const ID_TAB_THU = 'tab-thu-agent'

function ChonChe({ che, doi }: { che: Che; doi: (c: Che) => void }) {
  const { t } = useLang()
  const muc: readonly MucTab<Che>[] = [
    { id: 'chat', nhan: t({ vi: 'Chat', en: 'Chat' }), icon: 'convos' },
    // «Voice» giữ nguyên tiếng Anh ở cả hai ngôn ngữ — đứng cạnh «Chat» vốn đã
    // vậy. Dịch một nửa cặp nhãn là làm chúng trông như hai loại khác nhau.
    { id: 'noi', nhan: t({ vi: 'Voice', en: 'Voice' }), icon: 'voice' },
  ]
  return (
    <NhomTab
      muc={muc}
      dangMo={che}
      doi={doi}
      nhan={t({ vi: 'Cách thử', en: 'How to test' })}
      idPanel={ID_TAB_THU}
    />
  )
}

/**
 * Khoá active VÀ có khoá thô (`api_key`, migration `0918`) — DÙNG CHUNG cho
 * cả hai tab. Khoá tạo trước migration đó (`api_key: null`) không có gì để
 * ghép vào WS URL; khoá đã tắt không xác thực được với gateway nào.
 */
function khoaDungDuoc(keys: readonly Khoa[]): readonly (Khoa & { api_key: string })[] {
  return keys.filter(
    (k): k is Khoa & { api_key: string } => k.status === 'active' && k.api_key !== null,
  )
}

/** Dấu bắt buộc. `aria-hidden` — `required` trên chính ô mới là thứ trình đọc
 *  màn hình đọc; một dấu sao đọc thành "sao" chỉ là nhiễu. */
function Sao() {
  return (
    <span aria-hidden="true" className="text-badge-alert-fg">
      *
    </span>
  )
}

/** Banner "cần tạo khoá trước" — DÙNG CHUNG cho cả hai tab, cùng cơ chế chọn
 *  khoá theo tên nên cùng một câu chỉ đường. */
function ChuaCoKhoa() {
  const { t } = useLang()
  return (
    <div className="mb-3.5 rounded-lg border border-border bg-surface px-5 py-4">
      <p className="text-than leading-[1.55] text-nav">
        {t({
          vi: 'Cần một API Key để thử agent — tạo khoá ở màn API Keys rồi chọn nó ở ô dưới.',
          en: 'You need an API key to test the agent — create one on the API Keys screen, then pick it below.',
        })}
      </p>
      <Link
        to="/api-keys"
        className="mt-2 inline-block text-than font-semibold text-ac hover:underline"
      >
        {t({ vi: 'Tạo API Key', en: 'Create an API key' })}
      </Link>
    </div>
  )
}

// ─── Agent ngủ / thức ────────────────────────────────────────────────────────

function AgentNguThuc({ thuc, chu }: { thuc: boolean; chu: string }) {
  return (
    <div className="flex flex-col items-center gap-3 py-6">
      <div className="relative">
        <Icon name="agent" className={`size-12 ${thuc ? 'text-ac' : 'text-muted-2 agent-ngu'}`} />
        {!thuc && (
          <span aria-hidden="true" className="absolute -right-1 -top-2">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="agent-zzz absolute font-mono text-nhan font-semibold text-muted-2"
                style={{ animationDelay: `${i * 0.9}s` }}
              >
                z
              </span>
            ))}
          </span>
        )}
      </div>
      <p className="max-w-[42ch] text-center text-[13px] leading-[1.55] text-muted-2">{chu}</p>
    </div>
  )
}

// ─── Mảnh dùng chung Chat + Voice ────────────────────────────────────────────

function KhungHoiThoai({
  dangTraLoi,
  children,
}: {
  /** Agent đang stream câu trả lời ⇒ `aria-busy`: trình đọc màn hình chờ trọn
   *  câu (`done`) rồi mới đọc, không đọc từng token. */
  dangTraLoi: boolean
  children: React.ReactNode
}) {
  const { t } = useLang()
  // Chữ ra tới đâu khung chạy theo tới đó — trừ khi người dùng đang cuộn lên
  // đọc lại (xem `useTuCuonCuoi`). Áp cho cả Chat lẫn Voice vì dùng chung khung.
  const hop = useTuCuonCuoi<HTMLDivElement>()
  return (
    /* Cao CỐ ĐỊNH `h-[46vh]`, KHÔNG phải `max-h` (2026-08-24, người dùng báo
       «bé lúc đầu, sau mới phình to»): max-h làm khung co theo nội dung — mở
       màn chỉ có dòng «Chưa có tin nhắn» thì khung lùn tịt, nhắn vài câu thì
       nó phình dần tới trần, và mọi thứ đứng dưới (nút, thẻ đánh giá) bị xô
       xuống theo TỪNG tin nhắn. Khung hội thoại là một Ô CỬA SỔ nhìn vào cuộc
       trò chuyện — kích thước cửa sổ không có lý do gì đổi theo lượng chữ bên
       trong. `min-h` giữ lại cho viewport quá lùn (46vh < 220px). Từ `lg` (14/10): khung
       co giãn kín phần còn lại của vùng tab (`KHUNG_VOICE`), 46vh chỉ còn cho màn hẹp. */
    <div
      ref={hop}
      role="log"
      aria-label={t({ vi: 'Hội thoại', en: 'Conversation' })}
      aria-busy={dangTraLoi}
      className="flex h-[46vh] min-h-[220px] flex-col gap-2.5 overflow-auto rounded-lg border border-border bg-surface p-5 lg:h-auto lg:min-h-[240px] lg:flex-1"
    >
      {children}
    </div>
  )
}

function Loi({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="mt-2.5 text-phu leading-[1.5] text-badge-alert-fg">
      {children}
    </p>
  )
}

// ─── Chế độ Chat ─────────────────────────────────────────────────────────────

/**
 * WS URL của Chat — FIX CỨNG trong code (2026-08-11, quyết định người dùng:
 * mỗi tenant dev chỉ có đúng một domain gateway, không có lý do bắt gõ lại
 * mỗi lần mở màn). KHÔNG còn ô nhập trên UI — đổi domain thì sửa hằng này,
 * không phải hướng dẫn người dùng tự dán URL.
 */
// Giá trị nằm ở `WS_URL_CHAT_MAC_DINH` trong `../api` — DÙNG CHUNG với
// `KhoaMoiDialog` (nó in URL này cạnh khoá vừa tạo). Hai bản sao của cùng một
// domain là hai chỗ phải sửa ngày đổi domain, và chỗ thứ hai sẽ bị quên.

/**
 * Bốn trường danh tính (`danhTinhKhach.ts` — họ tên · SĐT · giới tính · role) +
 * API Key (chọn theo tên, khoá thô) — NĂM ô, tất cả BẮT BUỘC, rồi một nút Áp dụng.
 *
 * DÙNG CHUNG cho cả Chat và Voice (2026-08-11) — hai kênh giờ cùng cơ chế kết
 * nối (khoá thô + WS URL riêng của từng đích `/v1/chat`/`/v1/voice`). WS URL
 * KHÔNG còn là một ô trong form này (đổi 2026-08-11) — mỗi bên (`CheChat`/
 * `CheGiongNoiManHinh`) tự truyền một hằng cố định (`WS_URL_CHAT_MAC_DINH`/
 * `WS_URL_VOICE_MAC_DINH`) khi mở phiên; logic mở WS vẫn nhận đúng tham số đó
 * như trước, chỉ là người dùng không còn gõ/sửa được nữa.
 *
 * Cùng lý lẽ bản gốc: sửa BẤT CỨ ô nào sau khi áp dụng ⇒ agent ngủ lại — danh
 * tính đi vào bắt tay của phiên, không kèm từng tin nhắn, nên một thiết lập
 * sửa nửa chừng mà phiên vẫn sống là nói dối.
 */
function ThietLapPhien({
  form,
  doi,
  apiKey,
  doiApiKey,
  khoa,
  duDe,
  daApDung,
  onApDung,
  phu,
}: {
  form: FormDanhTinh
  doi: (ma: string, v: string) => void
  apiKey: string
  doiApiKey: (v: string) => void
  khoa: readonly { id: number; api_key: string; label: string; key_prefix: string }[]
  duDe: boolean
  daApDung: boolean
  onApDung: () => void
  /** Chỉ tab Chat: bộ chọn engine/model, đứng đầu hàng nút (trái), nút Áp dụng vẫn cuối. */
  phu?: React.ReactNode
}) {
  const { t } = useLang()
  // Role là DỮ LIỆU workspace (cấu hình chung, `/config`) — không có danh sách
  // tĩnh như giới tính. Cùng khoá cache với màn cấu hình agent: thêm/xoá role ở
  // đó là danh sách ở đây đổi theo, không phải tải lại trang.
  const cauHinh = useQuery({ queryKey: CAU_HINH_QUERY, queryFn: docCauHinh })
  const vaiTro = cauHinh.data?.vaiTro ?? []

  return (
    <div className="mb-3.5 rounded-lg border border-border bg-surface px-5 py-4">
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-5">
        {O_DANH_TINH.map((o) => (
          <label key={o.ma} className="block">
            <span className="mb-1 block text-[12px] text-muted">
              {t(o.nhan)} <Sao />
            </span>
            {o.kieu === 'vaiTro' ? (
              <select
                aria-label={t(o.nhan)}
                required
                value={form[o.ma] ?? ''}
                disabled={vaiTro.length === 0}
                onChange={(e) => doi(o.ma, e.target.value)}
                className="o-chon w-full rounded-md border border-border-field bg-surface px-2.5 py-[7px] text-than disabled:opacity-60"
              >
                <option value="">
                  {cauHinh.isError
                    ? t({ vi: '— không tải được role —', en: '— could not load roles —' })
                    : t({ vi: '— chọn —', en: '— pick —' })}
                </option>
                {vaiTro.map((v) => (
                  <option key={v.key} value={v.key}>
                    {v.ten}
                  </option>
                ))}
              </select>
            ) : o.kieu === 'chon' ? (
              <select
                aria-label={t(o.nhan)}
                required
                value={form[o.ma] ?? ''}
                onChange={(e) => doi(o.ma, e.target.value)}
                className="o-chon w-full rounded-md border border-border-field bg-surface px-2.5 py-[7px] text-than"
              >
                <option value="">{t({ vi: '— chọn —', en: '— pick —' })}</option>
                {(o.chon ?? []).map((c) => (
                  <option key={c.gt} value={c.gt}>
                    {t(c.nhan)}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type={o.kieu === 'dienThoai' ? 'tel' : 'text'}
                inputMode={o.kieu === 'dienThoai' ? 'numeric' : undefined}
                aria-label={t(o.nhan)}
                required
                placeholder={o.goiY}
                value={form[o.ma] ?? ''}
                onChange={(e) =>
                  doi(o.ma, o.kieu === 'dienThoai' ? chiSo(e.target.value) : e.target.value)
                }
                className="w-full rounded-md border border-border-field bg-surface px-2.5 py-[7px] text-than"
              />
            )}
          </label>
        ))}

        {/* API Key — CHỌN theo tên, value là khoá THÔ thật (`api_key`, migration
            `0918`): WS nối THẲNG từ trình duyệt nên cần chuỗi Bearer thật ngay
            tại đây, không có bước trung gian đổi `id` lấy khoá. */}
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">
            API Key <Sao />
          </span>
          <select
            aria-label="API Key"
            required
            value={apiKey}
            disabled={khoa.length === 0}
            onChange={(e) => doiApiKey(e.target.value)}
            className="o-chon w-full rounded-md border border-border-field bg-surface px-2.5 py-[7px] text-than disabled:opacity-60"
          >
            <option value="">{t({ vi: '— chọn API Key —', en: '— pick an API key —' })}</option>
            {khoa.map((k) => (
              <option key={k.id} value={k.api_key}>
                {k.label.trim() || t({ vi: '(chưa đặt tên)', en: '(unnamed)' })} · {k.key_prefix}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className={`mt-3.5 ${HANG_NUT}`}>
        {phu}
        <button
          type="button"
          onClick={onApDung}
          disabled={!duDe || daApDung}
          className="flex-none rounded-md bg-ac px-4 py-[9px] text-than font-semibold text-white hover:bg-acd disabled:opacity-50"
        >
          {daApDung ? t({ vi: 'Đã áp dụng', en: 'Applied' }) : t({ vi: 'Áp dụng', en: 'Apply' })}
        </button>
      </div>
    </div>
  )
}

// ─── Khung chat ──────────────────────────────────────────────────────────────

interface CuocGoiCong {
  readonly tool: string
  readonly xong: boolean
}

/**
 * Một bong bóng — dùng chung hai tab. Chat: `id` là số tăng dần. Voice: `id` dạng
 * `u:<turn_id>` (lời khách, từ `transcript`) hoặc `a:<turn_id>` (lời agent, từ
 * `agent_speaking` — gộp nhiều CÂU cùng `turn_id` vào MỘT bong bóng). `turn_id` đặc biệt
 * `"greeting"`/`"idle_0"`/`"idle_1"` không đi kèm lượt khách nào (doc §3.2).
 */
interface TinNhan {
  readonly id: number | string
  readonly vai: 'ban' | 'agent'
  readonly noiDung: string
  readonly toolCalls: readonly CuocGoiCong[]
  /** Card ảnh/video — Chat rút từ `tool_done.result` (doc §4.3), Voice từ event `media`. */
  readonly media?: MediaGiongNoi
  /** Voice: `agent_interrupted` đã xảy ra cho lượt này (doc §3.3). */
  readonly ngat?: boolean
  /** Chat: luồng xử lý của engine v2 (event `trace` sau `done`), `luot` đếm từ 1 trong phiên. */
  readonly trace?: TraceLuot & { readonly luot: number }
}

/**
 * `duoi` = hàng hành động treo dưới bong bóng (kiểu ChatGPT/Claude). Hiện chỉ
 * bong bóng agent CUỐI CÙNG nhận nó, mang đúng một nút «đánh giá» — xem
 * `HangDanhGia` và chỗ gọi ở `CheChat`.
 */
function BongBong({
  tin,
  trace,
  duoi,
}: {
  tin: TinNhan
  /** Chat: khối / dòng tóm tắt luồng xử lý của lượt (CheChat quyết kiểu theo bề rộng). */
  trace?: React.ReactNode
  duoi?: React.ReactNode
}) {
  const { t } = useLang()
  const cuaBan = tin.vai === 'ban'
  return (
    <div className={`flex flex-col gap-1.5 ${cuaBan ? 'items-end' : 'items-start'}`}>
      {/* Ai nói chỉ hiện bằng màu + căn trái/phải — trình đọc màn hình cần chữ
          (WCAG 1.3.1). Đầu khối chứ không trong bong bóng: tool + media của
          lượt cũng là của agent. */}
      <span className="sr-only">{cuaBan ? t({ vi: 'Bạn', en: 'You' }) : 'Agent'}: </span>
      {tin.toolCalls.length > 0 && (
        <ul className="flex flex-col gap-1">
          {tin.toolCalls.map((tc, i) => (
            <li key={i} className="text-phu leading-[1.5]">
              <span className="mr-2 font-mono text-nhan uppercase text-muted-2">
                {tc.xong ? 'tool_done' : 'tool_start'}
              </span>
              <span className="text-nav">{tc.tool}</span>
            </li>
          ))}
        </ul>
      )}
      {tin.noiDung !== '' && (
        <div
          className={`max-w-[80%] rounded-lg px-3.5 py-2.5 text-than leading-[1.55] ${
            cuaBan ? 'bg-ac text-white' : 'bg-fill-strong text-fg'
          }`}
        >
          {tin.noiDung}
          {tin.ngat && (
            <span className="ml-1.5 text-nhan italic opacity-70">
              {t({ vi: '(đã ngắt lời)', en: '(interrupted)' })}
            </span>
          )}
        </div>
      )}
      {tin.media && <TheMedia media={tin.media} noiDung={tin.noiDung} />}
      {trace}
      {duoi}
    </div>
  )
}

/**
 * Nút icon TRẦN (không viền) của hàng hành động dưới bong bóng.
 *
 * KHÔNG dùng `NutIcon` (`components/ui/Bang.tsx`): nút đó có viền và ô vuông
 * 28px — đúng cho ô hành động cuối một HÀNG BẢNG, nhưng ở đây là hàng icon mờ
 * dưới một câu trả lời, và viền quanh chúng biến hai gợi ý phụ thành hai nút
 * chính cạnh tranh với ô nhập ngay bên dưới.
 *
 * HOVER thì NỔI NỀN + đậm nét icon (người dùng yêu cầu tường minh 2026-08-13,
 * kèm ảnh khuôn Claude): ở trạng thái nghỉ hai nút cố ý mờ để không tranh chỗ,
 * nhưng một icon mờ 16px KHÔNG phản hồi gì khi rê chuột thì đọc thành hình
 * trang trí — không ai biết nó bấm được. Nền `fill-strong` cùng bậc với chip
 * gợi ý ngay dưới; `transition-colors` để nền bật lên chứ không nháy. Trạng
 * thái đang bật (`sang`) giữ nền `acs` THƯỜNG TRỰC, không phải chỉ lúc hover:
 * khung đánh giá đang mở thì nút phải tự nói được là nó đang mở.
 */
function NutMo({
  icon,
  nhan,
  sang,
  moRong,
  onClick,
}: {
  icon: 'copy' | 'check' | 'nhanXet'
  nhan: string
  sang?: boolean
  moRong?: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={nhan}
      aria-label={nhan}
      {...(moRong === undefined ? {} : { 'aria-expanded': moRong })}
      className={`rounded-sm p-1.5 transition-colors ${
        sang ? 'bg-acs text-ac' : 'text-muted-3 hover:bg-fill-strong hover:text-fg'
      }`}
    >
      <Icon name={icon} className="size-4" />
    </button>
  )
}

/**
 * Hàng hành động dưới bong bóng agent cuối — hai nút nhỏ sắc nhạt: **copy câu
 * trả lời** và **đánh giá**. Khuôn quen thuộc của ChatGPT/Claude: hàng icon mờ
 * dưới câu trả lời, không phải form bày sẵn.
 *
 * Vì sao KHÔNG bày sẵn khung đánh giá như bản đầu: nó chiếm chỗ ngay trên ô
 * nhập ở MỌI lượt, tức mời chấm điểm giữa lúc người dùng đang hỏi tiếp — trong
 * khi việc chính của màn này là thử agent, đánh giá là việc phụ làm lúc xong.
 *
 * Icon đánh giá là **bong bóng có dòng chữ** (`nhanXet`), KHÔNG phải 👍/👎 như
 * Claude — hợp đồng `FeedbackIn.rating` là 1-5 sao, một cặp ngón tay cái hứa
 * sai thứ mở ra khi bấm. Xem thêm docstring `DanhGiaPhien`.
 */
function HangHanhDong({
  noiDung,
  mo,
  daGui,
  onBam,
}: {
  /** Chữ của CHÍNH bong bóng này — thứ nút copy đưa vào clipboard. */
  noiDung: string
  mo: boolean
  daGui: boolean
  onBam: () => void
}) {
  const { t } = useLang()
  // Không đọc `loiCopy`: chữ đang hiện trên màn và bôi đen được, copy hỏng không mất gì.
  const { daCopy, copy } = useSaoChep()

  return (
    <div className="flex items-center gap-0.5 pl-0.5">
      <NutMo
        icon={daCopy ? 'check' : 'copy'}
        nhan={
          daCopy
            ? t({ vi: 'Đã copy', en: 'Copied' })
            : t({ vi: 'Copy câu trả lời', en: 'Copy reply' })
        }
        sang={daCopy}
        onClick={() => void copy(noiDung)}
      />
      {daGui ? (
        <p className="flex items-center gap-1.5 pl-1 text-[12px] text-muted-2">
          <Icon name="star" className="size-3.5 fill-current text-ac" />
          {t({ vi: 'Đã gửi đánh giá', en: 'Feedback sent' })}
        </p>
      ) : (
        <NutMo
          icon="nhanXet"
          nhan={t({ vi: 'Đánh giá cuộc trò chuyện', en: 'Rate this conversation' })}
          sang={mo}
          moRong={mo}
          onClick={onBam}
        />
      )}
    </div>
  )
}

/** Trạng thái phiên: «Sẵn sàng» + engine/model agent báo đang chạy (`engine_ok`). */
function TrangThaiSanSang({ engineChay }: { engineChay: EngineDangChay | null }) {
  const { t } = useLang()
  return (
    <div className="flex flex-none items-center gap-2.5">
      <Icon name="agent" className="size-5 flex-none text-ac" />
      <span className="text-[13px] font-semibold text-fg">
        {t({ vi: 'Sẵn sàng', en: 'Ready' })}
      </span>
      <span className="size-[7px] flex-none rounded-full bg-ac" />
      {engineChay && (
        <span className="rounded-full bg-fill-strong px-2 py-px font-mono text-nhan text-nav">
          {engineChay.provider
            ? `${engineChay.engine} · ${engineChay.provider}/${engineChay.model}`
            : engineChay.engine}
        </span>
      )}
    </div>
  )
}

/**
 * Thẻ thiết lập THU GỌN sau Áp dụng (tab Chat, người dùng chốt 14/10): một dòng trạng thái + danh tính đang thử,
 * nhường chiều cao cho khung chat. Không đổi gì của phiên — «Sửa thiết lập» chỉ mở lại form; sửa một ô mới đóng
 * phiên như cũ. Tab Voice KHÔNG dùng (02/10 đã chốt giữ form cố định để sân khấu không nhảy).
 */
function ThanhPhienGon({
  danhTinh,
  tenKhoa,
  engineChay,
  onSua,
  onReset,
}: {
  danhTinh: FormDanhTinh
  tenKhoa: string
  engineChay: EngineDangChay | null
  onSua: () => void
  onReset: () => void
}) {
  const { t } = useLang()
  const cauHinh = useQuery({ queryKey: CAU_HINH_QUERY, queryFn: docCauHinh })
  const role = danhTinh['role'] ?? ''
  const tenRole = cauHinh.data?.vaiTro.find((v) => v.key === role)?.ten ?? role
  const gioi = O_DANH_TINH.find((o) => o.ma === 'gender')?.chon?.find(
    (c) => c.gt === danhTinh['gender'],
  )
  const phan = [
    danhTinh['full_name'],
    danhTinh['phone'],
    gioi && t(gioi.nhan),
    tenRole,
    tenKhoa,
  ].filter(Boolean)
  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-border bg-surface px-4 py-2.5">
      <TrangThaiSanSang engineChay={engineChay} />
      <span className="min-w-0 flex-1 truncate text-phu text-muted">{phan.join(' · ')}</span>
      <div className="flex flex-none items-center gap-3">
        <button type="button" onClick={onReset} className="text-phu text-muted hover:underline">
          {t({ vi: 'Reset hội thoại', en: 'Reset conversation' })}
        </button>
        <button type="button" onClick={onSua} aria-expanded={false} className={NUT_PHU}>
          {t({ vi: 'Sửa thiết lập', en: 'Edit setup' })}
        </button>
      </div>
    </div>
  )
}

/** Vùng chat đủ chỗ cho hội thoại (~460px) + panel luồng xử lý (~400px) — laptop 1280px có nav mở đo ra 916px. */
const RONG_CO_PANEL = 880

/**
 * Engine / model cho RIÊNG phiên thử (`engineThu.ts`). Đổi lựa chọn ⇒ phiên đóng như sửa một ô thiết lập — lịch sử
 * hai engine nằm ở hai chỗ khác nhau phía agent (v2 có key state riêng), trộn trong một phiên là thử sai.
 */
function BoChonEngine({ chon, doi }: { chon: ChonEngine; doi: (c: ChonEngine) => void }) {
  const { t } = useLang()
  const theoServer = t({ vi: 'Theo server', en: 'Server default' })
  return (
    <div className="mr-auto flex flex-wrap items-end gap-2.5">
      <label className="block">
        <span className="mb-1 block text-[12px] text-muted">Engine</span>
        <select
          aria-label="Engine"
          value={chon.engine}
          onChange={(e) => doi({ engine: e.target.value as EngineThu, model: '' })}
          className="o-chon rounded-md border border-border-field bg-surface px-2.5 py-[7px] text-than"
        >
          <option value="">{theoServer}</option>
          <option value="legacy">Legacy</option>
          <option value="v2">V2 (calm)</option>
        </select>
      </label>
      {chon.engine === 'v2' && (
        <label className="block">
          <span className="mb-1 block text-[12px] text-muted">Model</span>
          <select
            aria-label="Model"
            value={chon.model}
            onChange={(e) => doi({ ...chon, model: e.target.value })}
            className="o-chon rounded-md border border-border-field bg-surface px-2.5 py-[7px] text-than"
          >
            <option value="">{theoServer}</option>
            {MODEL_V2.map((m) => (
              <option key={m.gt} value={m.gt}>
                {m.nhan}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  )
}

/**
 * Chat qua gateway thật, tab «Chat» của màn Thử agent. Tách ra từ hàm màn
 * (2026-08-11, lúc gắn lại tab Voice) — state/logic Y NGUYÊN như trước. Hàng
 * tab `ChonChe` nằm ở `ThuAgentScreen`, ngoài nhánh (xem đó).
 *
 * `danhTinh`/`apiKey`/setter NHẬN từ `ThuAgentScreen` (2026-08-11, lần ba) —
 * dùng CHUNG với tab Voice, xem docstring đầu file. `daApDung` và mọi state
 * "phiên" khác vẫn cục bộ ở đây.
 */
function CheChat({
  danhTinh,
  setDanhTinh,
  apiKey,
  setApiKey,
}: {
  danhTinh: FormDanhTinh
  setDanhTinh: (f: (c: FormDanhTinh) => FormDanhTinh) => void
  apiKey: string
  setApiKey: (v: string) => void
}) {
  const { t } = useLang()
  const khoa = useQuery({ queryKey: KHOA_QUERY, queryFn: taiKhoa })

  const [daApDung, setDaApDung] = useState(false)
  const [dangKetNoi, setDangKetNoi] = useState(false)
  const [song, setSong] = useState(false)
  const [loi, setLoi] = useState<string | null>(null)

  const [tinNhan, setTinNhan] = useState<readonly TinNhan[]>([])
  const [cauHoi, setCauHoi] = useState('')
  const [goiY, setGoiY] = useState<readonly GoiY[]>([])
  // Từ event đầu của lượt agent tới `done` — `aria-busy` của khung hội thoại.
  const [dangTraLoi, setDangTraLoi] = useState(false)

  // ─ Đánh giá phiên ─
  // `sessionId` từ event ĐẦU TIÊN của gateway (doc §4.1) — cũng chính là id
  // worker dùng khi ghi `conversations`, nên gửi kèm feedback được.
  // `daTraLoi` bật ở `done` đầu tiên: mời chấm sao khi agent chưa nói câu nào
  // là hỏi về một thứ chưa xảy ra.
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [daTraLoi, setDaTraLoi] = useState(false)
  const [moDanhGia, setMoDanhGia] = useState(false)
  // Sau Áp dụng thẻ thiết lập thu thành MỘT dòng (nhường chỗ cho khung chat); «Sửa thiết lập» mở lại form.
  const [moThietLap, setMoThietLap] = useState(false)
  const [daGuiDanhGia, setDaGuiDanhGia] = useState(false)

  // ─ Engine thử ─ (`engineThu.ts`): gửi sau `session_id`, chưa «sẵn sàng» tới khi `engine_ok` (hoặc `error`).
  const [chon, setChon] = useState<ChonEngine>(CHON_MAC_DINH)
  const [dangDoiEngine, setDangDoiEngine] = useState(false)
  const [engineChay, setEngineChay] = useState<EngineDangChay | null>(null)

  const phienRef = useRef<PhienChatGatewayMo | null>(null)
  const idMoRaRef = useRef<number | null>(null)
  const idTiepTheoRef = useRef(0)
  const dongChuDongRef = useRef(false)
  // `trace` tới SAU `done` (idMoRaRef đã về null) — gắn vào bong bóng vừa xong.
  const idVuaXongRef = useRef<number | null>(null)
  const soLuotRef = useRef(0)
  // Lượt đang mở ở panel phải — CHỈ khi người dùng bấm dòng tóm tắt; null = panel đóng, chat chiếm trọn bề ngang.
  const [idTraceMo, setIdTraceMo] = useState<number | string | null>(null)
  // Panel phải khi VÙNG CHAT đủ rộng (đo thật — nav 240px gập/mở được nên tầng màn không đủ); jsdom đo 0 ⇒ theo tầng.
  const kho = useKhoManHinh()
  const vungChat = useRef<HTMLDivElement>(null)
  const [rongVung, setRongVung] = useState(0)

  useEffect(() => {
    return () => {
      dongChuDongRef.current = true
      phienRef.current?.dong()
    }
  }, [])

  const duDe = soTruongDaKhai(danhTinh) === O_DANH_TINH.length && apiKey.trim() !== ''
  const thuc = daApDung && song && !dangDoiEngine

  useEffect(() => {
    const el = vungChat.current
    if (!el) return
    const doRong = () => setRongVung(el.getBoundingClientRect().width)
    doRong()
    const ro = new ResizeObserver(doRong)
    ro.observe(el)
    return () => ro.disconnect()
  }, [thuc])

  /** Đóng phiên đang chạy (nếu có) và về chế độ soạn — dùng khi sửa BẤT CỨ ô
   *  nào sau khi đã áp dụng, đúng lý lẽ bản gốc: một thiết lập sửa nửa chừng
   *  mà phiên vẫn sống là nói dối. */
  function veLaiSoan(): void {
    if (!daApDung) return
    dongChuDongRef.current = true
    phienRef.current?.dong()
    phienRef.current = null
    setSong(false)
    setDangKetNoi(false)
    setDaApDung(false)
  }

  function doiDanhTinh(ma: string, v: string): void {
    setDanhTinh((c) => ({ ...c, [ma]: v }))
    veLaiSoan()
  }
  function doiApiKey(v: string): void {
    setApiKey(v)
    veLaiSoan()
  }
  function doiChon(c: ChonEngine): void {
    setChon(c)
    veLaiSoan()
  }

  function apDung(): void {
    if (!duDe) return
    const tinEngine = tinDoiEngine(chon)
    setLoi(null)
    setDaApDung(true)
    setMoThietLap(false)
    setDangKetNoi(true)
    setDangDoiEngine(tinEngine !== null)
    setEngineChay(null)
    dongChuDongRef.current = false
    idMoRaRef.current = null
    idVuaXongRef.current = null
    soLuotRef.current = 0
    setIdTraceMo(null)
    setTinNhan([])
    setGoiY([])
    setDangTraLoi(false)
    setSessionId(null)
    setDaTraLoi(false)
    setMoDanhGia(false)
    setDaGuiDanhGia(false)

    phienRef.current = moPhienChatGateway({
      cauHinh: { wsUrl: WS_URL_CHAT_MAC_DINH, apiKey },
      danhTinh: locTrong(danhTinh),
      onTrangThai: (tt) => {
        setDangKetNoi(tt === 'dang_mo')
        setSong(tt === 'song')
      },
      onSessionId: (id) => {
        setSessionId(id)
        if (tinEngine !== null) phienRef.current?.doiEngine(tinEngine)
      },
      onEngineOk: (e) => {
        setEngineChay(e)
        setDangDoiEngine(false)
      },
      onTrace: (tr) => {
        const id = idVuaXongRef.current
        if (id === null) return
        const luot = ++soLuotRef.current
        setTinNhan((c) => c.map((m) => (m.id === id ? { ...m, trace: { ...tr, luot } } : m)))
      },
      // ⚠️ `idMoRaRef`/`idTiepTheoRef` bị ĐỌC và GHI ở đây, TRƯỚC khi gọi
      // `setTinNhan` — KHÔNG đụng chúng ở TRONG hàm cập nhật truyền cho
      // `setTinNhan`. StrictMode (bật ở `main.tsx`) gọi hàm cập nhật đó HAI
      // LẦN ở môi trường dev để phát hiện cập nhật không-thuần; ghi ref bên
      // trong nó thì lần gọi thứ hai đọc lại giá trị lần đầu vừa ghi và rẽ
      // nhánh sai — tin nhắn agent bị tạo "ma" (id gắn vào ref) nhưng KHÔNG
      // bao giờ thật sự vào state, mọi token sau đó `map` không khớp id nào
      // và lặng lẽ không có gì hiện ra. Đã tái hiện đúng bằng test bọc
      // `<StrictMode>`, xem `tests/thu-agent.test.tsx`.
      onToken: (text) => {
        let id = idMoRaRef.current
        if (id === null) {
          id = idTiepTheoRef.current++
          idMoRaRef.current = id
        }
        setDangTraLoi(true)
        setTinNhan((c) =>
          c.some((m) => m.id === id)
            ? c.map((m) => (m.id === id ? { ...m, noiDung: m.noiDung + text } : m))
            : [...c, { id, vai: 'agent', noiDung: text, toolCalls: [] }],
        )
      },
      onToolStart: (tool) => {
        let id = idMoRaRef.current
        if (id === null) {
          id = idTiepTheoRef.current++
          idMoRaRef.current = id
        }
        setDangTraLoi(true)
        setTinNhan((c) =>
          c.some((m) => m.id === id)
            ? c.map((m) =>
                m.id === id ? { ...m, toolCalls: [...m.toolCalls, { tool, xong: false }] } : m,
              )
            : [...c, { id, vai: 'agent', noiDung: '', toolCalls: [{ tool, xong: false }] }],
        )
      },
      onToolDone: (tool) => {
        const id = idMoRaRef.current
        setTinNhan((c) =>
          c.map((m) => {
            if (m.id !== id) return m
            const idx = m.toolCalls.findLastIndex((tc) => tc.tool === tool && !tc.xong)
            if (idx === -1) return m
            const toolCalls = m.toolCalls.map((tc, i) => (i === idx ? { ...tc, xong: true } : tc))
            return { ...m, toolCalls }
          }),
        )
      },
      // Card ảnh/video rút từ `tool_done.result` (doc §4.3) — bắn cùng lượt
      // với `onToolDone` ở trên, gắn vào ĐÚNG bong bóng đang mở (`idMoRaRef`,
      // luôn đã có vì `tool_start` mở nó trước khi `tool_done` tới).
      onMedia: (media) => {
        let id = idMoRaRef.current
        if (id === null) {
          id = idTiepTheoRef.current++
          idMoRaRef.current = id
        }
        setDangTraLoi(true)
        setTinNhan((c) =>
          c.some((m) => m.id === id)
            ? c.map((m) => (m.id === id ? { ...m, media } : m))
            : [...c, { id, vai: 'agent', noiDung: '', toolCalls: [], media }],
        )
      },
      onDone: () => {
        idVuaXongRef.current = idMoRaRef.current
        idMoRaRef.current = null
        setDangTraLoi(false)
        setDaTraLoi(true)
      },
      onSuggestions: setGoiY,
      onError: (m) => {
        setLoi(m)
        setDangDoiEngine(false) // agent từ chối đổi engine ⇒ phiên vẫn chạy engine cũ, đừng kẹt chờ
      },
      onClose: (thongBao) => {
        phienRef.current = null
        setSong(false)
        setDangKetNoi(false)
        setDangTraLoi(false)
        setDangDoiEngine(false)
        if (dongChuDongRef.current) {
          dongChuDongRef.current = false
          return
        }
        setLoi(thongBao)
      },
    })
  }

  function gui(e: React.FormEvent): void {
    e.preventDefault()
    const message = cauHoi.trim()
    if (message === '' || !thuc) return
    setLoi(null)
    setGoiY([])
    const id = idTiepTheoRef.current++
    setTinNhan((c) => [...c, { id, vai: 'ban', noiDung: message, toolCalls: [] }])
    setCauHoi('')
    phienRef.current?.gui(message)
  }

  function datLai(): void {
    phienRef.current?.reset()
    setTinNhan([])
    setGoiY([])
    idMoRaRef.current = null
    idVuaXongRef.current = null
    soLuotRef.current = 0
    setIdTraceMo(null)
    setDangTraLoi(false)
    setLoi(null)
    // `reset` xoá hội thoại nhưng GIỮ NGUYÊN `session_id` (doc §4.1) — nên
    // `sessionId` không đụng tới, chỉ thu nút đánh giá lại cho tới lượt trả lời
    // kế tiếp: nút treo dưới bong bóng cuối, mà giờ không còn bong bóng nào.
    setDaTraLoi(false)
    setMoDanhGia(false)
    setDaGuiDanhGia(false)
  }

  if (khoa.isPending)
    return <p className="text-[14px] text-muted">{t({ vi: 'Đang tải…', en: 'Loading…' })}</p>

  const dungDuocChat = khoaDungDuoc(khoa.data?.keys ?? [])
  const coKhoa = dungDuocChat.length > 0

  /** Bong bóng agent CUỐI — chỗ treo nút đánh giá. `null` khi chưa có câu trả
   *  lời nào (agent chưa nói thì không có gì để chấm). */
  const idCuoiAgent = tinNhan.findLast((m) => m.vai === 'agent')?.id ?? null

  // Panel luồng xử lý (màn rộng): vùng chat đủ rộng VÀ người dùng đã mở một lượt. Hẹp hơn ⇒ mở tại chỗ.
  const coRong = rongVung > 0 ? rongVung >= RONG_CO_PANEL : kho === 'desktop'
  const luotMo = coRong ? tinNhan.find((m) => m.trace && m.id === idTraceMo)?.trace : undefined
  function dongPanel(): void {
    const luot = luotMo?.luot
    setIdTraceMo(null)
    // Trả focus về đúng dòng tóm tắt vừa mở panel — nút × biến mất cùng panel.
    vungChat.current?.querySelector<HTMLButtonElement>(`[data-luot="${luot}"]`)?.focus()
  }

  const chuNgu = !coKhoa
    ? t({ vi: 'Chưa có API Key.', en: 'No API key.' })
    : song && dangDoiEngine
      ? t({ vi: 'Đang đổi engine…', en: 'Switching engine…' })
      : dangKetNoi
        ? t({ vi: 'Đang mở phiên…', en: 'Opening session…' })
        : !duDe
          ? t({ vi: 'Điền đủ bốn trường bên trên.', en: 'Fill in all four fields above.' })
          : t({ vi: 'Bấm Áp dụng để bắt đầu.', en: 'Press Apply to start.' })

  return (
    <>
      {!coKhoa && <ChuaCoKhoa />}

      {thuc && !moThietLap ? (
        <ThanhPhienGon
          danhTinh={danhTinh}
          tenKhoa={dungDuocChat.find((k) => k.api_key === apiKey)?.label.trim() ?? ''}
          engineChay={engineChay}
          onSua={() => setMoThietLap(true)}
          onReset={datLai}
        />
      ) : (
        <ThietLapPhien
          form={danhTinh}
          doi={doiDanhTinh}
          apiKey={apiKey}
          doiApiKey={doiApiKey}
          khoa={dungDuocChat}
          duDe={duDe}
          daApDung={daApDung}
          onApDung={apDung}
          phu={<BoChonEngine chon={chon} doi={doiChon} />}
        />
      )}

      {thuc ? (
        <>
          {moThietLap && (
            <div className="mb-2.5 flex items-center justify-between">
              <TrangThaiSanSang engineChay={engineChay} />
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={datLai}
                  className="text-phu text-muted hover:underline"
                >
                  {t({ vi: 'Reset hội thoại', en: 'Reset conversation' })}
                </button>
                <button
                  type="button"
                  onClick={() => setMoThietLap(false)}
                  aria-expanded={true}
                  className="text-phu text-muted hover:underline"
                >
                  {t({ vi: 'Thu gọn thiết lập', en: 'Collapse setup' })}
                </button>
              </div>
            </div>
          )}

          <div ref={vungChat} className="lg:flex lg:min-h-0 lg:flex-1 lg:gap-4">
            <div className="flex min-w-0 flex-col lg:flex-1">
              <KhungHoiThoai dangTraLoi={dangTraLoi}>
                {tinNhan.length === 0 ? (
                  // `my-auto`: khung giờ cao cố định, câu chờ không tự căn giữa nữa
                  // — để nó dính mép trên thì nửa dưới khung là một khoảng trắng
                  // trông như thiếu gì đó.
                  <p className="my-auto px-1 py-8 text-center text-[13px] text-muted-2">
                    {t({ vi: 'Chưa có tin nhắn.', en: 'No messages yet.' })}
                  </p>
                ) : (
                  tinNhan.map((m) => (
                    <BongBong
                      key={m.id}
                      tin={m}
                      trace={
                        m.trace &&
                        (coRong ? (
                          <TomTatLuong
                            muc={m.trace}
                            mo={m.id === idTraceMo}
                            onBam={() => setIdTraceMo((c) => (c === m.id ? null : m.id))}
                            dieuKhien={ID_PANEL_LUONG}
                          />
                        ) : (
                          <LuongXuLy muc={m.trace} />
                        ))
                      }
                      duoi={
                        // CHỈ bong bóng agent cuối cùng mang hàng hành động — một
                        // nút đánh giá dưới MỖI câu trả lời là mời chấm điểm cùng
                        // một phiên nhiều lần (API ghi thành nhiều dòng, không có
                        // ràng buộc duy nhất nào chặn).
                        daTraLoi && m.id === idCuoiAgent ? (
                          <>
                            <HangHanhDong
                              noiDung={m.noiDung}
                              mo={moDanhGia}
                              daGui={daGuiDanhGia}
                              onBam={() => setMoDanhGia((c) => !c)}
                            />
                            {moDanhGia && !daGuiDanhGia && (
                              /* 420px là số của RIÊNG chỗ này (khung mở dưới bong
                             bóng, bề rộng một bong bóng): thẻ tự nó không khoá
                             bề rộng nữa — tab Voice dùng full-width. */
                              <div className="w-full max-w-[420px]">
                                <DanhGiaPhien
                                  apiKey={apiKey}
                                  sessionId={sessionId}
                                  onBoQua={() => setMoDanhGia(false)}
                                  onXong={() => {
                                    setDaGuiDanhGia(true)
                                    setMoDanhGia(false)
                                  }}
                                />
                              </div>
                            )}
                          </>
                        ) : undefined
                      }
                    />
                  ))
                )}
              </KhungHoiThoai>
            </div>
            {luotMo && (
              <div className="flex w-[min(44%,560px)] flex-none flex-col">
                <PanelLuong muc={luotMo} onDong={dongPanel} />
              </div>
            )}
          </div>

          {goiY.length > 0 && (
            <div className="mt-2.5 flex flex-wrap gap-2">
              {goiY.map((g, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => setCauHoi(g.text)}
                  className="rounded-full border border-border-field px-3 py-1 text-phu text-nav hover:bg-fill-strong"
                >
                  {g.label}
                </button>
              ))}
            </div>
          )}

          <form onSubmit={gui} className="mt-3 flex gap-2">
            <input
              className="min-w-0 flex-1 rounded-md border border-border-field bg-surface px-3 py-[9px] text-than"
              placeholder={t({ vi: 'Nhập câu hỏi để thử agent…', en: 'Ask something…' })}
              aria-label={t({ vi: 'Câu hỏi thử', en: 'Test question' })}
              value={cauHoi}
              onChange={(e) => setCauHoi(e.target.value)}
            />
            <button type="submit" disabled={cauHoi.trim() === ''} className={NUT_CHINH}>
              {t({ vi: 'Gửi', en: 'Send' })}
            </button>
          </form>
        </>
      ) : (
        <div className="rounded-lg border border-border bg-surface p-5">
          <AgentNguThuc thuc={false} chu={chuNgu} />
        </div>
      )}

      {loi && <Loi>{loi}</Loi>}
    </>
  )
}

// ─── Chế độ Voice ────────────────────────────────────────────────────────────

/**
 * WS URL của Voice — FIX CỨNG trong code (2026-08-11), CÙNG domain dev của
 * Chat, chỉ đổi path `/v1/chat` → `/v1/voice`. Không có ô nhập trên UI — xem
 * docstring `WS_URL_CHAT_MAC_DINH` phía trên.
 *
 * ⚠️ `endpoint_voice_url` (từ `taiKhoa()`) KHÔNG dùng làm giá trị này. Nó vẫn
 * theo công thức `url_endpoint_agent()` phía backend —
 * `wss://<tenant>.<domain>/v1/voice` — MỘT SUBDOMAIN RIÊNG MỖI TENANT. Spec
 * gateway (§1) nói rõ mô hình đó đã LỖI THỜI từ 2026-08-10: giờ là MỘT domain
 * chung, tenant suy từ khoá Bearer. Backend chưa cập nhật lại hàm đó (cùng
 * vấn đề `endpoint_chat_url` của Chat) — xem báo cáo sai lệch gửi kèm lần đổi
 * trước, KHÔNG phải lỗi ở FE.
 */
// Giá trị nằm ở `WS_URL_VOICE_MAC_DINH` trong `../api` — DÙNG CHUNG với
// `KhoaMoiDialog` (nó in URL này cạnh khoá vừa tạo). Hai bản sao của cùng một
// domain là hai chỗ phải sửa ngày đổi domain, và chỗ thứ hai sẽ bị quên.

const NHAN_TRANG_THAI: Record<TrangThaiGiongNoi, { vi: string; en: string }> = {
  nghi: { vi: 'Chưa bắt đầu', en: 'Not started' },
  dang_noi: { vi: 'Đang xin quyền micro…', en: 'Requesting microphone…' },
  dang_mo: { vi: 'Đang mở phiên…', en: 'Opening session…' },
  song: { vi: 'Đang nghe', en: 'Listening' },
  loi: { vi: 'Lỗi', en: 'Error' },
}

/** Nét chevron/× trong lightbox — inline svg cùng khuôn nét 1.92 của `icons.tsx`. */
function NetLightbox({ d }: { d: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.92"
      strokeLinecap="round"
      strokeLinejoin="round"
      className="size-4"
    >
      <path d={d} />
    </svg>
  )
}

/**
 * Lightbox xem ảnh — mở `thumb` trước (đã có sẵn trong lưới) rồi âm thầm
 * tải `url` gốc (có thể vài MB) và nâng cấp khi xong, đúng gợi ý doc §4.3.
 * Đóng bằng bấm nền/Esc/nút × — vỏ là `HopThoai` (giữ Tab bên trong, đóng
 * xong trả focus về nút ảnh đã mở nó).
 *
 * ĐIỀU HƯỚNG GIỮA CÁC ẢNH trong cùng card (2026-08-24) — người dùng ĐẢO chốt
 * 2026-08-11 («chỉ xem đúng ảnh vừa bấm, không mũi tên»): dùng thật với card
 * nhiều ảnh mới thấy mỗi lần xem một ảnh phải đóng-mở lại là quá đắt. Mũi tên
 * hai bên + phím ArrowLeft/ArrowRight, KẸP ở hai đầu (không vòng lại — vòng
 * thì «ảnh sau» ở ảnh cuối lặng lẽ nhảy về đầu, người xem tưởng còn ảnh mới).
 *
 * `createPortal` ra `document.body` (2026-08-24, người dùng báo ảnh mở ra
 * LỆCH HẲN SANG MỘT BÊN trên màn thật): component này mount sâu trong cây bong
 * bóng, mà `position: fixed` bị BẤT KỲ tổ tiên nào có transform/filter bắt làm
 * containing block — `inset-0` lúc đó là toạ độ so với tổ tiên đó, không phải
 * viewport. Cùng họ bug và cùng cách chữa với `HopTip` màn Tổng quan
 * (2026-08-14); jsdom không dựng containing block nên cổng test đo quan hệ
 * cha-con thay vì toạ độ. `<dialog>` modal nay lên top layer nên hết bị bắt,
 * nhưng portal VẪN giữ: card nằm trong khung hội thoại `role="log"`, và một
 * hộp thoại mở ra trong vùng live là trình đọc màn hình đọc lại trọn nó.
 */
function LightboxAnh({
  anhs,
  dau,
  onDong,
}: {
  anhs: readonly MedItemAnh[]
  dau: number
  onDong: () => void
}) {
  const { t } = useLang()
  const [viTri, setViTri] = useState(dau)
  // `?? anhs[0]` chỉ để chiều `noUncheckedIndexedAccess` — `viTri` luôn bị kẹp
  // trong [0, length-1] bởi hai chỗ đổi nó ngay dưới.
  const anh = anhs[viTri] ?? anhs[0]
  const [src, setSrc] = useState(anh ? (anh.thumb ?? anh.url) : '')
  const oDongRef = useRef<HTMLButtonElement>(null)

  const coTruoc = viTri > 0
  const coSau = viTri < anhs.length - 1

  // Focus vào nút đóng ngay khi mở — người dùng bàn phím/trình đọc màn hình
  // cần một điểm focus bên TRONG dialog, không phải đứng yên ở nút ảnh vừa
  // bấm (đã bị `aria-hidden` hoá về ý nghĩa bởi lớp phủ che nó).
  useEffect(() => {
    oDongRef.current?.focus()
  }, [])

  useEffect(() => {
    if (!anh) return
    setSrc(anh.thumb ?? anh.url)
    if (!anh.thumb || anh.thumb === anh.url) return
    let huy = false
    const img = new Image()
    img.onload = () => {
      if (!huy) setSrc(anh.url)
    }
    img.src = anh.url
    return () => {
      huy = true
    }
  }, [anh])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Kẹp bằng min/max chứ không cộng vòng — cùng luật với hai nút mũi tên.
      if (e.key === 'ArrowRight') setViTri((c) => Math.min(anhs.length - 1, c + 1))
      if (e.key === 'ArrowLeft') setViTri((c) => Math.max(0, c - 1))
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [anhs.length])

  if (!anh) return null

  return createPortal(
    // `overflow-visible`: nút × lòi ra ngoài góc khung (`-right-3 -top-3`), mà
    // UA cho `<dialog>` modal `overflow: auto` — để mặc định là nút bị cắt.
    <HopThoai
      onDong={onDong}
      aria-label={anh.label ?? t({ vi: 'Xem ảnh', en: 'View image' })}
      className="m-auto max-h-[calc(100dvh-4rem)] max-w-[calc(100vw-2rem)] overflow-visible bg-transparent p-0 text-white backdrop:bg-panel/90"
    >
      <button
        ref={oDongRef}
        type="button"
        onClick={onDong}
        aria-label={t({ vi: 'Đóng', en: 'Close' })}
        className="absolute -right-3 -top-3 z-10 flex size-8 cursor-pointer items-center justify-center rounded-full bg-surface text-fg shadow-nut-noi"
      >
        <NetLightbox d="M6 6l12 12M18 6L6 18" />
      </button>
      {anhs.length > 1 && (
        <>
          <button
            type="button"
            onClick={() => setViTri((c) => Math.max(0, c - 1))}
            disabled={!coTruoc}
            aria-label={t({ vi: 'Ảnh trước', en: 'Previous image' })}
            className="absolute -translate-y-1/2 left-2 top-1/2 z-10 flex size-9 cursor-pointer items-center justify-center rounded-full bg-surface text-fg shadow-nut-noi disabled:cursor-default disabled:opacity-40"
          >
            <NetLightbox d="M14 6l-6 6 6 6" />
          </button>
          <button
            type="button"
            onClick={() => setViTri((c) => Math.min(anhs.length - 1, c + 1))}
            disabled={!coSau}
            aria-label={t({ vi: 'Ảnh sau', en: 'Next image' })}
            className="absolute -translate-y-1/2 right-2 top-1/2 z-10 flex size-9 cursor-pointer items-center justify-center rounded-full bg-surface text-fg shadow-nut-noi disabled:cursor-default disabled:opacity-40"
          >
            <NetLightbox d="M10 6l6 6-6 6" />
          </button>
        </>
      )}
      <img
        src={src}
        alt={anh.label ?? ''}
        onError={() => setSrc(anh.url)}
        className="max-h-[85vh] max-w-[90vw] rounded-lg object-contain"
      />
      {(anh.label || anhs.length > 1) && (
        <p className="mt-2 text-center text-[13px] text-white">
          {anh.label}
          {anhs.length > 1 && (
            <span className={`font-mono text-[12px] text-white/70 ${anh.label ? 'ml-2' : ''}`}>
              {viTri + 1}/{anhs.length}
            </span>
          )}
        </p>
      )}
    </HopThoai>,
    document.body,
  )
}

/**
 * Ô ảnh trong lưới — `thumb` trước, RƠI VỀ `url` khi thumb hỏng.
 *
 * `thumb` và `url` là hai nguồn độc lập (thumb do Portal sinh rồi lưu S3, `url` thường là
 * CDN của khách), nên một thumb 404 không nói gì về ảnh gốc. Thiếu nhánh này thì một khoá
 * ghi nhầm vào payload Qdrant làm mất luôn ảnh vẫn còn sống — đúng cái đã xảy ra
 * 2026-08-13 với tenant `nobles_homes`.
 */
function AnhLuoi({ it }: { it: MedItemAnh }) {
  const [src, setSrc] = useState(it.thumb ?? it.url)
  useEffect(() => setSrc(it.thumb ?? it.url), [it])
  return (
    <img
      src={src}
      alt={it.label ?? ''}
      onError={() => setSrc(it.url)}
      className="aspect-square w-full object-cover"
    />
  )
}

/**
 * Số ảnh mà câu trả lời TRỎ TỚI bằng chữ («xem ảnh 2», «ảnh số 3»…) — chữ bao
 * quanh là lựa chọn của model, không cố định, nên chỉ neo vào "ảnh"/"image"
 * rồi số ngay sau đó (tối đa 12 ký tự không phải số ở giữa, đủ cho "ảnh số 2"
 * hay "(xem ảnh 3)").
 */
const RE_TRICH_DAN_ANH = /(ảnh|image)[^\d]{0,12}(\d+)/giu

/**
 * Bỏ khỏi card những ảnh câu trả lời KHÔNG nhắc tới — `kb_search` trả ảnh của
 * cả năm chunk lân cận, không phải mọi ảnh đều liên quan câu hỏi, còn câu trả
 * lời chỉ nói tới đúng vài tấm bằng số thứ tự (`it.index`).
 *
 * Không lọc (trả nguyên `items`) CHỈ khi không ảnh nào mang `index` — Voice
 * không có event nào chèn số này, agent bản cũ cũng vậy, nên không có gì để
 * so. Khi ảnh CÓ mang số mà không trích dẫn nào khớp — model có cơ hội trích
 * dẫn và không làm, kể cả khi đó là câu "không tìm thấy trong tài liệu" —
 * đó là dấu hiệu ảnh không thuộc câu trả lời, không phải lý do hiện hết
 * (đo được: ba câu hỏi ngoài phạm vi tài liệu vẫn kèm 2-4 ảnh không liên
 * quan vì `kb_search` luôn trả top-5 chunk). Mục khác `kind` (file/tour/
 * video) không mang số nên luôn giữ.
 */
function locTheoTrichDan(items: readonly MucMedia[], noiDung: string): readonly MucMedia[] {
  const anhCoSo = items.filter(
    (it): it is MedItemAnh => it.kind === 'image' && it.index !== undefined,
  )
  if (anhCoSo.length === 0) return items
  const soDuocNhac = new Set<number>()
  for (const m of noiDung.matchAll(RE_TRICH_DAN_ANH)) soDuocNhac.add(Number(m[2]))
  return items.filter(
    (it) => it.kind !== 'image' || it.index === undefined || soDuocNhac.has(it.index),
  )
}

/**
 * Card ảnh/video — DÙNG CHUNG cho cả hai tab (hình dạng payload giống hệt
 * nhau, doc §8). Khác nhau ở NƠI lấy ra: Voice nhận qua event `media` riêng
 * (doc §3.5), Chat phải đào trong `tool_done.result` (doc §4.3, xem
 * `docMediaTuKetQua` ở `chatGateway.ts` + `onMedia` ở `CheChat`).
 *
 * Ảnh bấm mở LIGHTBOX tại chỗ (2026-08-11) — trước đó mở `url` gốc ở tab mới,
 * bắt người dùng rời màn thử để xem một tấm ảnh. Video GIỮ NGUYÊN mở tab
 * YouTube (chốt thiết kế: không cần đồng bộ hành vi hai loại).
 *
 * `noiDung` là câu trả lời của CHÍNH bong bóng này, dùng để lọc theo trích
 * dẫn (`locTheoTrichDan`) — tính lại mỗi lần render từ props hiện tại, không
 * cache: `noiDung` chỉ lớn dần lúc stream nên một số đã khớp thì khớp mãi,
 * không có chuyện ảnh ẩn/hiện lặp lại hay khớp rồi không bao giờ lên card.
 */
function TheMedia({ media, noiDung }: { media: MediaGiongNoi; noiDung: string }) {
  const { t } = useLang()
  // Lưu VỊ TRÍ trong danh sách ảnh (không phải item): lightbox nhận trọn
  // `anhs` để điều hướng qua lại giữa các ảnh của CÙNG card (2026-08-24).
  const [anhMo, setAnhMo] = useState<number | null>(null)
  const items = locTheoTrichDan(media.items, noiDung)
  const anhs = items.filter((it): it is MedItemAnh => it.kind === 'image')

  if (items.length === 0) return null
  return (
    <div className="max-w-[280px] rounded-lg border border-border bg-surface p-3">
      {media.caption && <p className="mb-2 text-phu font-semibold text-fg">{media.caption}</p>}
      <div className="grid grid-cols-2 gap-2">
        {items.map((it, i) =>
          it.kind === 'image' ? (
            <figure key={i} className="m-0">
              <button
                type="button"
                onClick={() => setAnhMo(anhs.indexOf(it))}
                aria-label={`${t({ vi: 'Xem ảnh', en: 'View image' })}${it.label ? `: ${it.label}` : ''}`}
                className="block w-full overflow-hidden rounded-md bg-fill-strong"
              >
                <AnhLuoi it={it} />
              </button>
              {/* `index` là số câu trả lời trỏ tới bằng chữ («xem ảnh 3») — thiếu nó
                  thì một lưới ảnh không nói được ô nào ứng với câu nào. Optional:
                  agent bản cũ chưa gửi, khi đó không hiện chú thích số. */}
              {it.index !== undefined && (
                <figcaption className="mt-1 text-nhan text-muted-2">
                  <span className="font-semibold text-ac">
                    {t({ vi: 'Ảnh', en: 'Image' })} {it.index}
                  </span>
                  {it.label ? ` — ${it.label}` : ''}
                </figcaption>
              )}
            </figure>
          ) : it.kind === 'tour' ? (
            <a
              key={i}
              href={it.url}
              target="_blank"
              rel="noreferrer"
              className="flex aspect-square flex-col items-center justify-center gap-1 rounded-md bg-fill-strong p-2 text-center"
            >
              <span className="text-[20px]">🌐</span>
              <span className="line-clamp-3 text-nhan text-fg">
                {it.label ?? t({ vi: 'Tour 360', en: '360 tour' })}
              </span>
            </a>
          ) : it.kind === 'file' ? (
            <a
              key={i}
              href={it.url}
              target="_blank"
              rel="noreferrer"
              // Nhãn nằm trên thẻ `a`: nhánh có `thumb` không có chữ nào nhìn thấy, nên
              // không có nhãn thì đây là một link vô danh với trình đọc màn hình.
              aria-label={it.label ?? t({ vi: 'Tài liệu', en: 'Document' })}
              className="flex aspect-square flex-col items-center justify-center gap-1 overflow-hidden rounded-md bg-fill-strong text-center"
            >
              {it.thumb ? (
                <img src={it.thumb} alt="" className="aspect-square w-full object-cover" />
              ) : (
                <>
                  <span className="text-[20px]">📄</span>
                  <span className="line-clamp-3 px-2 text-nhan text-fg">
                    {it.label ?? t({ vi: 'Tài liệu', en: 'Document' })}
                  </span>
                </>
              )}
            </a>
          ) : (
            // Video: YouTube (video_id) hoặc biến thể url (Drive/Vimeo/mp4 — 2026-08-25).
            // Portal chỉ MỞ TAB MỚI, không có lightbox video nên `embed_url` không
            // dùng ở đây — nó dành cho client có lightbox (AINA). Không có thumb thì
            // vẽ ô nền + tiêu đề thay vì <img> rỗng.
            <a
              key={i}
              href={'video_id' in it ? `https://www.youtube.com/watch?v=${it.video_id}` : it.url}
              target="_blank"
              rel="noreferrer"
              className="relative block overflow-hidden rounded-md bg-fill-strong"
            >
              {'video_id' in it ? (
                <img
                  src={`https://img.youtube.com/vi/${it.video_id}/hqdefault.jpg`}
                  alt={it.title ?? ''}
                  className="aspect-square w-full object-cover"
                />
              ) : it.thumb ? (
                <img
                  src={it.thumb}
                  alt={it.title ?? ''}
                  className="aspect-square w-full object-cover"
                />
              ) : (
                <span className="flex aspect-square w-full items-end justify-center px-2 pb-2 text-center text-nhan text-fg">
                  <span className="line-clamp-2">
                    {it.title ?? t({ vi: 'Video', en: 'Video' })}
                  </span>
                </span>
              )}
              <span className="absolute inset-0 flex items-center justify-center text-[20px] text-white [text-shadow:0_1px_3px_rgb(0_0_0/0.6)]">
                ▶
              </span>
            </a>
          ),
        )}
      </div>
      {media.message && <p className="mt-2 text-phu text-muted">{media.message}</p>}
      {anhMo !== null && <LightboxAnh anhs={anhs} dau={anhMo} onDong={() => setAnhMo(null)} />}
    </div>
  )
}

/**
 * Widget mic — chỉ mount SAU khi đã Áp dụng thiết lập ở `CheGiongNoiManHinh`.
 * Bấm «Bắt đầu trò chuyện» mới thật sự mở WS + xin quyền mic — tách hai bước
 * (Áp dụng ≠ bắt đầu) vì xin quyền mic là một việc nặng hơn mở một WS chat,
 * đáng có một hành động NGƯỜI DÙNG BẤM riêng, không tự động theo Áp dụng.
 */
function CheGiongNoi({ cauHinh, danhTinh }: { cauHinh: CauHinhGiongNoi; danhTinh: FormDanhTinh }) {
  const { t } = useLang()
  const [trangThai, setTrangThai] = useState<TrangThaiGiongNoi>('nghi')
  const datMucRef = useRef<(m: number) => void>(() => {})
  const [tinNhan, setTinNhan] = useState<readonly TinNhan[]>([])
  const [phanTich, setPhanTich] = useState<string | null>(null)
  const [loi, setLoi] = useState<string | null>(null)
  // Chuông chờ bắt máy đang kêu (`chuongCho.ts`) — chỉ để nhãn thanh gọi nói
  // «Đang gọi…» thay vì «Đang nghe» trong lúc chưa có tiếng agent.
  const [doChuong, setDoChuong] = useState(false)
  // ─ Lớp phủ sân khấu: agent đang nói + phụ đề câu đang nói ─
  // Bật theo `agent_speaking`; TẮT khi audio của lượt phát HẾT chứ không lúc
  // `agent_done` (sự kiện đến khi agent sinh xong, audio còn trong hàng đợi) —
  // hẹn giờ theo `conLai` mà sân khấu đã có sẵn.
  const [agentNoi, setAgentNoi] = useState(false)
  const [cauNoi, setCauNoi] = useState<string | null>(null)
  // `agent_speaking` → `agent_done`/`agent_interrupted`: `aria-busy` của khung
  // hội thoại — lượt agent đến TỪNG CÂU, trình đọc màn hình đọc khi trọn lượt.
  // Khác `agentNoi` (tắt khi TIẾNG hết, sau `agent_done`).
  const [dangTraLoi, setDangTraLoi] = useState(false)
  const henTatRef = useRef<number | null>(null)
  const huyHenTat = () => {
    if (henTatRef.current !== null) window.clearTimeout(henTatRef.current)
    henTatRef.current = null
  }
  const tatSauKhiHetTieng = () => {
    huyHenTat()
    // Chỉ gọi lúc chạy (callback của phiên), khi `tinHieuRef` bên dưới đã có.
    const tre = Math.max(0, tinHieuRef.current.conLai) * 1000 + 400
    henTatRef.current = window.setTimeout(() => {
      setAgentNoi(false)
      setCauNoi(null)
    }, tre)
  }
  // Đồng hồ cuộc gọi (mm:ss) — đếm từ lúc phiên SỐNG (WS mở, đang nghe).
  const [giay, setGiay] = useState(0)
  // ─ Đánh giá sau cuộc gọi ─
  // `daGoi` bật lúc bấm «Bắt đầu», nên thanh đánh giá không hiện lúc vừa mở
  // tab. `sessionId` về từ event đầu tiên của gateway (= tên room LiveKit) —
  // `null` mà cuộc gọi VẪN có lời qua lại nghĩa là gateway đang chạy bản trước
  // 2026-08-13, khi đó thanh vẫn hiện nhưng khoá nút Gửi. Không có cả hai ⇒
  // cuộc gọi chưa từng thông (micro bị từ chối, WS hỏng, gateway đóng ngay) ⇒
  // KHÔNG hỏi đánh giá (xem `cuocGoiThong`).
  const [daGoi, setDaGoi] = useState(false)
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [boQuaDanhGia, setBoQuaDanhGia] = useState(false)
  const phien = useRef<PhienGiongNoi | null>(null)
  // Tín hiệu tiếng agent cho người dẫn trên sân khấu — REF chứ không state:
  // đổi ~12 lần/giây, qua state là vẽ lại cả danh sách tin nhắn chừng ấy lần.
  const tinHieuRef = useRef<TinHieuLoa>(TIN_HIEU_IM)
  // Hàm vẽ frame lip sync do sân khấu đăng ký (chỉ khi bật VITE_AVATAR_WS_URL).
  const veAvatarRef = useRef<VeAvatar | null>(null)
  // Người dẫn workspace đang dùng (`nhanVat.ts`) — null = người dẫn mặc định của service.
  const nguoiDan = useNguoiDanDangDung()
  // Album ảnh trên sân khấu + lệnh đưa tay: agent gửi ảnh (`send_media` ⇒
  // event `media`) thì CÁC ảnh đó mở thành album xếp chồng, tự lướt sau 6,5s
  // hoặc 2 lượt trả lời, người dùng vuốt/kéo được; xem hết thì album đóng, về
  // nền cũ (xem `sanKhau.ts`). Người dẫn đưa tay giới thiệu lúc album mới mở.
  // STATE chứ không ref: đổi hiếm, và sân khấu phải vẽ lại theo.
  const [luanPhien, setLuanPhien] = useState<LuanPhienAnh>(LUAN_PHIEN_TRONG)
  // Chỉ là ảnh của ALBUM; không có album thì sân khấu tự chạy vòng nền mặc định.
  const anhNen = anhHienTai(luanPhien)
  const album = useMemo(
    () =>
      luanPhien.ds.length > 0
        ? { ds: luanPhien.ds, i: luanPhien.i, doiLuc: luanPhien.doiLuc }
        : null,
    [luanPhien.ds, luanPhien.i, luanPhien.doiLuc],
  )
  const [lenhGioTay, setLenhGioTay] = useState(0)
  // Đang kéo album ⇒ đồng hồ đứng (không lướt khỏi tay người dùng).
  const giuAlbumRef = useRef(false)
  // Huỷ lượt tải trước ảnh của card media gần nhất (`taiTruocAnh`).
  const huyTaiAnhRef = useRef<(() => void) | null>(null)
  // Đồng hồ của album (mốc 6,5s + đóng khi xem hết). Chỉ chạy khi album mở;
  // `nhipDoiAnh` trả CHÍNH state khi chưa tới mốc nên không vẽ lại thừa.
  // Giảm chuyển động ⇒ KHÔNG có đồng hồ (WCAG 2.2.2: tự chạy quá 5s phải dừng
  // được): album đứng yên tới khi người dùng vuốt/bấm mũi tên hoặc card mới
  // thay nó; đổi ảnh theo lượt trả lời (`xongLuot`) vẫn còn — đó không phải
  // chạy theo giờ. Album vì thế cũng không tự đóng.
  const coAlbum = luanPhien.ds.length > 0
  useEffect(() => {
    if (!coAlbum || giamChuyenDong()) return
    const id = window.setInterval(() => {
      if (!giuAlbumRef.current) setLuanPhien((s) => nhipDoiAnh(s, performance.now()))
    }, 250)
    return () => window.clearInterval(id)
  }, [coAlbum])
  // Lượt (turn_id) đang mở ở phía agent — `tool_start`/`tool_done`/`media`
  // không mang `turn_id` (doc §3.4/§3.5), nên phải bám vào lượt gần nhất mở
  // bởi `transcript`. ĐỌC/GHI ở ĐÂY, ngoài hàm cập nhật của `setTinNhan` —
  // cùng lý do StrictMode đã ghi ở `chatGateway.ts`/`CheChat` phía trên.
  const turnHienTaiRef = useRef<string | null>(null)

  // Rời màn / đổi chế độ / sửa thiết lập ⇒ ĐÓNG PHIÊN (unmount gọi cleanup
  // này). Không có dòng này thì đèn mic của trình duyệt còn sáng sau khi
  // người dùng đã đi chỗ khác.
  useEffect(() => {
    return () => {
      phien.current?.dong()
      phien.current = null
      huyHenTat()
      huyTaiAnhRef.current?.()
    }
  }, [])

  const dangSong = trangThai === 'song'
  // Đồng hồ đếm từ lúc «bắt máy» (hết chuông chờ), như điện thoại thật.
  const dangThoai = dangSong && !doChuong
  useEffect(() => {
    if (!dangThoai) return
    setGiay(0)
    const batDauLuc = Date.now()
    const id = window.setInterval(() => setGiay(Math.floor((Date.now() - batDauLuc) / 1000)), 1000)
    return () => window.clearInterval(id)
  }, [dangThoai])

  /** Lấy bong bóng theo `id`, tạo mới nếu chưa có, rồi biến đổi. */
  function ganTinNhan(id: string, vai: 'ban' | 'agent', doi: (cu: TinNhan) => TinNhan): void {
    setTinNhan((c) =>
      c.some((m) => m.id === id)
        ? c.map((m) => (m.id === id ? doi(m) : m))
        : [...c, doi({ id, vai, noiDung: '', toolCalls: [] })],
    )
  }

  function batDau(): void {
    setLoi(null)
    setTinNhan([])
    // Cuộc gọi mới ⇒ nền về mặc định (ảnh của cuộc trước không còn liên quan).
    huyTaiAnhRef.current?.()
    huyTaiAnhRef.current = null
    setLuanPhien(LUAN_PHIEN_TRONG)
    huyHenTat()
    setAgentNoi(false)
    setCauNoi(null)
    setDangTraLoi(false)
    setPhanTich(null)
    turnHienTaiRef.current = null
    setDaGoi(true)
    setSessionId(null)
    setBoQuaDanhGia(false)

    const urlAv = urlAvatar(nguoiDan?.avatarId)
    void moPhienGiongNoi({
      cauHinh,
      danhTinh: locTrong(danhTinh),
      ...(urlAv ? { avatar: { url: urlAv, ve: () => veAvatarRef.current } } : {}),
      onTrangThai: setTrangThai,
      onSessionId: setSessionId,
      onDoChuong: setDoChuong,
      onMuc: (m) => datMucRef.current(m),
      onMucLoa: (m, conLai) => {
        tinHieuRef.current = { ...tinHieuRef.current, muc: m, conLai, capNhat: performance.now() }
      },
      onPartialTranscript: setPhanTich,
      onTranscript: (text, turnId) => {
        turnHienTaiRef.current = turnId
        setPhanTich(null)
        setCauNoi(null)
        ganTinNhan(`u:${turnId}`, 'ban', (m) => ({ ...m, noiDung: text }))
      },
      onAgentSpeaking: (text, turnId) => {
        tinHieuRef.current = { ...tinHieuRef.current, luotMo: true, coSuKienLuot: true }
        huyHenTat()
        setAgentNoi(true)
        setCauNoi(text)
        setDangTraLoi(true)
        ganTinNhan(`a:${turnId}`, 'agent', (m) => ({
          ...m,
          noiDung: m.noiDung ? `${m.noiDung} ${text}` : text,
        }))
      },
      onAgentDone: (turnId) => {
        tinHieuRef.current = { ...tinHieuRef.current, luotMo: false, coSuKienLuot: true }
        setLuanPhien((s) => xongLuot(s, performance.now()))
        tatSauKhiHetTieng()
        setDangTraLoi(false)
        if (turnHienTaiRef.current === turnId) turnHienTaiRef.current = null
      },
      onAgentInterrupted: (turnId) => {
        tinHieuRef.current = { ...tinHieuRef.current, luotMo: false, coSuKienLuot: true }
        setLuanPhien((s) => xongLuot(s, performance.now()))
        tatSauKhiHetTieng()
        setDangTraLoi(false)
        ganTinNhan(`a:${turnId}`, 'agent', (m) => ({ ...m, ngat: true }))
      },
      onToolStart: (tool) => {
        const id = `a:${turnHienTaiRef.current ?? 'goi'}`
        ganTinNhan(id, 'agent', (m) => ({
          ...m,
          toolCalls: [...m.toolCalls, { tool, xong: false }],
        }))
      },
      onToolDone: (tool) => {
        const id = `a:${turnHienTaiRef.current ?? 'goi'}`
        ganTinNhan(id, 'agent', (m) => {
          const idx = m.toolCalls.findLastIndex((tc) => tc.tool === tool && !tc.xong)
          if (idx === -1) return m
          const toolCalls = m.toolCalls.map((tc, i) => (i === idx ? { ...tc, xong: true } : tc))
          return { ...m, toolCalls }
        })
      },
      onMedia: (media) => {
        const id = `a:${turnHienTaiRef.current ?? 'goi'}`
        ganTinNhan(id, 'agent', (m) => ({ ...m, media }))
        const ds = anhTuMedia(media)
        if (ds.length > 0) {
          // Album chỉ nhận ảnh ĐÃ TẢI XONG (`taiTruocAnh`): ảnh đầu tiên xong mở
          // album (+ người dẫn đưa tay), các ảnh sau chen vào đúng thứ tự gốc.
          // Không ảnh nào tải được ⇒ không mở album, nền giữ nguyên.
          huyTaiAnhRef.current?.()
          let dau = true
          huyTaiAnhRef.current = taiTruocAnh(ds, (u) => {
            if (dau) {
              dau = false
              setLuanPhien((s) => nhanBoAnh(s, [u], performance.now()))
              setLenhGioTay((n) => n + 1)
              phien.current?.gioTay?.() // nhân vật lip sync: đưa tay qua avatar service
            } else setLuanPhien((s) => themAnh(s, u, ds))
          })
        }
      },
      // `error` giữa lượt KHÔNG đóng phiên (doc §3.6: "phiên có thể vẫn tiếp
      // tục") — chỉ hiện banner, giống hệt lý lẽ Chat.
      onError: setLoi,
      onSessionEnded: (reason) =>
        setLoi(t({ vi: `Phiên đã kết thúc (${reason}).`, en: `Session ended (${reason}).` })),
      onDong: setLoi,
    }).then((p) => {
      phien.current = p
    })
  }

  function dung(): void {
    phien.current?.dong()
    phien.current = null
    datMucRef.current(0)
    huyHenTat()
    setAgentNoi(false)
    setCauNoi(null)
  }

  const dangChay = trangThai === 'song' || trangThai === 'dang_mo' || trangThai === 'dang_noi'
  // Hỏi đánh giá một cuộc gọi chưa từng thông là hỏi về thứ không xảy ra — và
  // thẻ còn bóp sân khấu xuống 180px ngay dưới dòng lỗi (critique 2026-10-07).
  const cuocGoiThong = sessionId !== null || tinNhan.length > 0

  const soLuot = tinNhan.filter((m) => m.vai === 'agent').length

  return (
    <BoCucVoice
      sanKhau={
        <>
          {/* Đưa tay theo HAI đường: có ảnh mới lên nền (`lenhGioTay`, luôn
              thực hiện, không chờ giãn cách) + tự đưa tay khi nói liên tục
              (~10–15s một lần, xem `GIAN_CACH_GIO_TAY_MS`) — CHỈ khi album
              đang mở: cử chỉ là chỉ sang màn chiếu bên trái, không có ảnh thì
              cô ấy chỉ vào tường trống (2026-10-07, sau khi bỏ ảnh dự án nền). */}
          <KhungNguoiDan>
            <SanKhauAgent
              tinHieuRef={tinHieuRef}
              veAvatarRef={veAvatarRef}
              anhChoAvatar={nguoiDan?.posterUrl}
              anhNen={anhNen}
              lenhGioTay={lenhGioTay}
              tuDongGioTay={album !== null}
              album={album}
              onLuotAlbum={(b) => setLuanPhien((s) => sangAnh(s, b, performance.now()))}
              toiDay={!!cauNoi}
              onGiuAlbum={(dang) => {
                giuAlbumRef.current = dang
                // Thả tay mà không lướt ⇒ ảnh này được thêm trọn một nhịp.
                if (!dang) setLuanPhien((s) => giuAnh(s, performance.now()))
              }}
            >
              <LopPhuSanKhau
                trucTiep={dangSong}
                agentNoi={agentNoi}
                cau={cauNoi}
                soAnh={luanPhien.ds.length}
                anhThu={luanPhien.i}
              />
            </SanKhauAgent>
          </KhungNguoiDan>
          <ThanhGoi
            nhan={t(
              doChuong && dangSong
                ? { vi: 'Đang gọi…', en: 'Calling…' }
                : NHAN_TRANG_THAI[trangThai],
            )}
            dangNghe={dangSong && !doChuong}
            giay={giay}
            datMucRef={datMucRef}
            dangChay={dangChay}
            onBatDau={batDau}
            onKetThuc={dung}
          />
          {/* Lỗi/thông báo kết thúc phiên đứng NGAY DƯỚI thanh cuộc gọi — nó nói
              về cuộc gọi đó (người dùng báo lệch 2026-08-24 khi nó rớt xuống đáy). */}
          {loi && <Loi>{loi}</Loi>}
          {/* Cúp máy xong mới hỏi — giữa cuộc gọi thì người dùng đang NÓI, không
              đọc màn hình. Cuộc gọi kết thúc bằng bấm Kết thúc, `session_ended`,
              hay WS đóng đều đưa `trangThai` về `nghi` (xem `dong()` ở `giongNoi.ts`). */}
          {/* Sân khấu (`flex-1`) tự thấp lại nhường chỗ cho thẻ này. */}
          {daGoi && cuocGoiThong && !dangChay && !boQuaDanhGia && (
            <DanhGiaPhien
              apiKey={cauHinh.apiKey}
              sessionId={sessionId}
              ghiChuThieuSession={t({
                vi: 'Chưa nhận được session_id của cuộc gọi này nên chưa gửi được đánh giá — thường là gateway voice đang chạy bản cũ, chưa có event session_id.',
                en: 'No session_id was received for this call, so feedback cannot be submitted — usually the voice gateway is still on an older build without the session_id event.',
              })}
              onBoQua={() => setBoQuaDanhGia(true)}
            />
          )}
        </>
      }
      hoiThoai={
        // `&& dangChay`: phiên đứt giữa lượt (không có `agent_done`) thì khung
        // không bị kẹt ở «bận» mãi.
        <KhungHoiThoaiVoice soLuot={soLuot} dangTraLoi={dangTraLoi && dangChay}>
          {tinNhan.length === 0 && phanTich === null ? (
            <HoiThoaiTrong />
          ) : (
            <>
              {tinNhan.map((m) => (
                <BongBong key={m.id} tin={m} />
              ))}
              {/* Transcript TẠM — ghi đè liên tục lúc khách đang nói (doc §3.1),
                  chưa phải một lượt chốt nên vẽ khác hẳn bong bóng thật (viền
                  đứt, chữ nghiêng) để không ai lầm là đã chốt. `aria-hidden`:
                  nó nằm trong vùng `role="log"`, mỗi lần ghi đè là một lần
                  trình đọc màn hình đọc chen vào lúc người dùng đang nói — lượt
                  chốt (`transcript`) mới là bản được đọc. */}
              {phanTich !== null && (
                <div
                  aria-hidden="true"
                  className="max-w-[80%] self-end rounded-lg border border-dashed border-border-field px-3.5 py-2.5 text-than italic leading-[1.55] text-muted-2"
                >
                  {phanTich}
                </div>
              )}
            </>
          )}
        </KhungHoiThoaiVoice>
      }
    />
  )
}

/** Sân khấu chờ trước Áp dụng — ảnh tĩnh, nhưng đúng người dẫn workspace đang dùng. */
function SanKhauChoNguoiDan() {
  const nguoiDan = useNguoiDanDangDung()
  return <SanKhauAgent video={false} anhChoAvatar={nguoiDan?.posterUrl} />
}

/**
 * Màn đầy đủ của tab «Voice». Cấu trúc SONG SONG với `CheChat` (cùng
 * `ThietLapPhien`, cùng lý lẽ "sửa ô sau khi áp dụng ⇒ ngủ lại") — khác ở
 * chỗ Áp dụng ở đây CHƯA mở WS/mic ngay, chỉ mở khoá cho nút «Bắt đầu trò
 * chuyện» bên trong `CheGiongNoi` (xem docstring component đó).
 *
 * `danhTinh`/`apiKey`/setter NHẬN từ `ThuAgentScreen` (2026-08-11, lần ba) —
 * dùng CHUNG với tab Chat, xem docstring đầu file. `daApDung` vẫn cục bộ.
 */
function CheGiongNoiManHinh({
  danhTinh,
  setDanhTinh,
  apiKey,
  setApiKey,
}: {
  danhTinh: FormDanhTinh
  setDanhTinh: (f: (c: FormDanhTinh) => FormDanhTinh) => void
  apiKey: string
  setApiKey: (v: string) => void
}) {
  const { t } = useLang()
  const khoa = useQuery({ queryKey: KHOA_QUERY, queryFn: taiKhoa })

  const [daApDung, setDaApDung] = useState(false)

  function doiDanhTinh(ma: string, v: string): void {
    setDanhTinh((c) => ({ ...c, [ma]: v }))
    setDaApDung(false)
  }
  function doiApiKey(v: string): void {
    setApiKey(v)
    setDaApDung(false)
  }

  function apDung(): void {
    if (!duDe) return
    setDaApDung(true)
  }

  if (khoa.isPending)
    return <p className="text-[14px] text-muted">{t({ vi: 'Đang tải…', en: 'Loading…' })}</p>

  const dungDuoc = khoaDungDuoc(khoa.data?.keys ?? [])
  const coKhoa = dungDuoc.length > 0

  const duDe = soTruongDaKhai(danhTinh) === O_DANH_TINH.length && apiKey.trim() !== ''

  // KHÔNG có khái niệm "agent sẵn sàng" ở tầng ngoài này nữa (khác bản trước
  // 2026-08-10 dựa vào `docTrangThai()`/cấu hình agent) — kênh voice giờ nối
  // thẳng như chat, "sẵn sàng" là chuyện của WS bên trong `CheGiongNoi`.
  const thuc = daApDung

  const chuNgu = !coKhoa
    ? t({ vi: 'Chưa có API Key.', en: 'No API key.' })
    : !duDe
      ? t({ vi: 'Điền đủ bốn trường bên trên.', en: 'Fill in all four fields above.' })
      : t({ vi: 'Bấm Áp dụng để bắt đầu.', en: 'Press Apply to start.' })

  // Fragment: các khối là con TRỰC TIẾP của vùng `KHUNG_VOICE` (flex dọc ở
  // `ThuAgentScreen`) — `BoCucVoice` phải là con trực tiếp để `flex-1` lấp chỗ.
  return (
    <>
      {!coKhoa && <ChuaCoKhoa />}

      {/* Form năm ô Ở LẠI sau Áp dụng (nút thành «Đã áp dụng»): bản thu gọn
          thành một dòng làm cả bố cục nhảy — thanh thiết lập co lại, sân khấu
          cao vọt lên (người dùng báo 2026-10-02). Sửa ô nào ⇒ phiên đóng. */}
      <ThietLapPhien
        form={danhTinh}
        doi={doiDanhTinh}
        apiKey={apiKey}
        doiApiKey={doiApiKey}
        khoa={dungDuoc}
        duDe={duDe}
        daApDung={daApDung}
        onApDung={apDung}
      />

      {thuc ? (
        <CheGiongNoi cauHinh={{ wsUrl: WS_URL_VOICE_MAC_DINH, apiKey }} danhTinh={danhTinh} />
      ) : (
        // Cùng bố cục với lúc đang gọi (sân khấu đứng chờ · nút gọi khoá · lời
        // nhắc) — bấm Áp dụng thì không có gì nhảy chỗ, chỉ nút gọi mở khoá.
        <BoCucVoice
          sanKhau={
            <>
              <KhungNguoiDan>
                <SanKhauChoNguoiDan />
              </KhungNguoiDan>
              <ThanhGoi
                nhan={t({ vi: 'Chưa kết nối', en: 'Not connected' })}
                dangNghe={false}
                giay={0}
                dangChay={false}
                khoa
                goiY={chuNgu}
                onBatDau={() => {}}
                onKetThuc={() => {}}
              />
            </>
          }
          hoiThoai={
            <KhungHoiThoaiVoice soLuot={0}>
              <div className="my-auto">
                <AgentNguThuc thuc={false} chu={chuNgu} />
              </div>
            </KhungHoiThoaiVoice>
          }
        />
      )}
    </>
  )
}

// ─── Màn ─────────────────────────────────────────────────────────────────────

export function ThuAgentScreen() {
  const [che, setChe] = useState<Che>('chat')
  // Danh tính + API Key DÙNG CHUNG cho cả hai tab — xem docstring đầu file
  // (2026-08-11, lần ba: người dùng phản hồi đổi tab mất hết chữ vừa gõ).
  // Vào màn là ĐIỀN SẴN đủ năm ô (người dùng chốt 2026-10-02): tên/SĐT ngẫu
  // nhiên + nam ngay lập tức; Role và API Key lấy lựa chọn ĐẦU TIÊN khi hai danh
  // sách tải xong — xem effect dưới.
  const [danhTinh, setDanhTinh] = useState<FormDanhTinh>(() => danhTinhMacDinh())
  const [apiKey, setApiKey] = useState('')

  // Cùng khoá cache với `ThietLapPhien`/`CheChat` ⇒ không thêm request nào.
  const khoa = useQuery({ queryKey: KHOA_QUERY, queryFn: taiKhoa })
  const cauHinh = useQuery({ queryKey: CAU_HINH_QUERY, queryFn: docCauHinh })
  const khoaDau = khoaDungDuoc(khoa.data?.keys ?? [])[0]?.api_key
  const roleDau = cauHinh.data?.vaiTro[0]?.key
  // Điền MỘT LẦN mỗi ô: người dùng chủ động xoá về «— chọn —» thì không tự điền
  // lại đè lên lựa chọn đó.
  const daDien = useRef({ khoa: false, role: false })
  useEffect(() => {
    if (khoaDau && !daDien.current.khoa) {
      daDien.current.khoa = true
      setApiKey((c) => c || khoaDau)
    }
    if (roleDau && !daDien.current.role) {
      daDien.current.role = true
      setDanhTinh((c) => (c['role'] ? c : { ...c, role: roleDau }))
    }
  }, [khoaDau, roleDau])

  const chung = { danhTinh, setDanhTinh, apiKey, setApiKey }
  // Hàng tab ở NGOÀI nhánh: hai nhánh là hai component khác nhau nên đổi tab là
  // gỡ cả cây — tab nằm trong nhánh thì nút vừa bấm bị gỡ theo và focus rơi về
  // `<body>` (audit a11y 05/10). Vùng tab cao đúng một màn tính CẢ hàng tab (`KHUNG_VOICE`) —
  // Voice từ trước, Chat từ 14/10 (khung chat co giãn kín phần còn lại, không còn 46vh trên desktop).
  return (
    <div className={`px-7 py-6 max-md:px-4 max-md:py-4 ${KHUNG_VOICE}`}>
      <div className="mb-3.5">
        <ChonChe che={che} doi={setChe} />
      </div>
      {/* Vùng tab bọc riêng: hàng tab ở trên nằm trong cùng khung nên khung đó không làm
          `tabpanel` được. Ở Voice nó phải tiếp tục chuỗi flex của `KHUNG_VOICE`. */}
      <div {...panelTab(ID_TAB_THU, che)} className="lg:flex lg:min-h-0 lg:flex-1 lg:flex-col">
        {che === 'chat' ? <CheChat {...chung} /> : <CheGiongNoiManHinh {...chung} />}
      </div>
    </div>
  )
}
