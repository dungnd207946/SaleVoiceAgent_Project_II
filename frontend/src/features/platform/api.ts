/**
 * Client HTTP của màn API Keys — khoá đấu nối agent.
 *
 * ⚠️ KHOÁ THÔ (`apiKey` của `KhoaDaTao`) KHÔNG ĐƯỢC ĐI VÀO CACHE.
 * `taoKhoa()` cố ý KHÔNG phải một query — nó là mutation, và người gọi giữ kết
 * quả trong state của component rồi bỏ đi. Đưa nó vào React Query cache là để
 * khoá sống lại sau khi dialog đóng, và devtools của React Query thì in cache ra.
 */

import { gioPhut, ngayThangNam, truoc } from '@/lib/dinhDang'
import { goi } from '@/lib/http'

const GOC = '/api/v1/agent/keys'

/**
 * HAI trạng thái, theo mô hình Anthropic Admin API. `active` ⇔ backend
 * `revoked_at IS NULL` — cùng vị từ mà view `agent_api.tenant_keys` lộ cho
 * gateway và `repo.tra_khoa()` dùng cho `/bootstrap`.
 *
 * Anthropic còn có `archived`/`expired`; ở đây không có nghĩa (khoá không hết
 * hạn, không có vòng đời lưu trữ) nên backend trả 422 nếu nhận chúng.
 */
export type TrangThaiKhoa = 'active' | 'inactive'

/**
 * Một hàng trong bảng khoá.
 *
 * `api_key` (từ migration `0918` phía backend) là khoá THÔ — CÓ trả về, theo
 * yêu cầu tường minh của người vận hành: `/thu-agent` cần dựng `<select>`
 * chọn khoá theo tên mà vẫn nối WS thật được (WS nối THẲNG từ trình duyệt,
 * không qua backend đổi vé, nên cần khoá thật ngay tại đây — khác Voice, xem
 * `veThuGiongNoi`). `null` cho khoá tạo TRƯỚC migration đó — backend không
 * backfill được từ hash một chiều. Đánh đổi bảo mật đã ghi rõ ở CLAUDE.md.
 */
export interface Khoa {
  readonly id: number
  readonly api_key: string | null
  /** 12 ký tự đầu. Đủ để nhận ra khoá nào, không đủ để dùng. */
  readonly key_prefix: string
  readonly label: string
  readonly created_at: string
  /** `null` = chưa bootstrap lần nào. Khác hẳn "vừa dùng" — đừng gộp thành ''. */
  readonly last_used_at: string | null
  readonly status: TrangThaiKhoa
  /** Lúc bị tắt. `null` khi `status === 'active'`. */
  readonly revoked_at: string | null
}

export interface DanhSachKhoa {
  /** Có kể cả khi `keys` rỗng — trạng thái rỗng vẫn phải bàn giao được endpoint. */
  readonly endpoint_chat_url: string
  readonly endpoint_voice_url: string
  /** MỌI trạng thái — khoá tắt KHÔNG biến mất, nó mang `status: 'inactive'`. */
  readonly keys: readonly Khoa[]
}

/** ⚠️ Chứa khoá thô. Chỉ sống trong state của `KhoaMoiDialog`. */
export interface KhoaDaTao {
  readonly id: number
  readonly api_key: string
  readonly key_prefix: string
  readonly endpoint_chat_url: string
  readonly endpoint_voice_url: string
}

/**
 * Khoá cache của `taiKhoa`. MỘT hằng cho cả module, không phải chuỗi viết tay ở
 * từng màn.
 *
 * Trước 2026-08-08 đây là hai khoá KHÁC NHAU cho cùng một endpoint: `/api-keys`
 * đọc và invalidate `['agent-keys']`, còn `/thu-agent` đọc `['api-keys']`. Nên
 * tắt một khoá ở màn quản trị KHÔNG dọn cache của màn thử: quay sang đó, lần vẽ
 * đầu tiên vẫn dựng ô chọn từ danh sách cũ và vẫn mời chọn đúng cái khoá vừa
 * chết. Hiện `staleTime` mặc định là 0 nên refetch lúc mount vá lại sau đó vài
 * trăm ms — tức lỗi này đang được che bởi một mặc định mà ai cũng có thể đổi.
 */
export const KHOA_QUERY = ['agent-keys'] as const

/**
 * Danh sách khoá, MỌI trạng thái.
 *
 * CHUẨN HOÁ `status` NGAY Ở BIÊN, không để component tự đoán. FE và BE là hai
 * repo git, deploy rời nhau, nên "FE mới gặp BE cũ" là trạng thái CÓ THẬT —
 * đo được ngay trên máy dev 2026-08-07: API ở cổng 8100 chạy uvicorn KHÔNG có
 * `--reload`, uptime 20h, nên nó vẫn trả response cũ không có trường `status`.
 *
 * `?? 'active'` là suy luận ĐÚNG chứ không phải mặc định cho có: BE cũ lọc
 * `revoked_at IS NULL` ngay trong SQL, nên mọi hàng nó trả về theo định nghĩa
 * đều là khoá còn sống. Thiếu chuẩn hoá này thì `k.status === 'active'` là
 * `undefined === 'active'` → false, và MỌI khoá đang chạy hiện ra là «Đã tắt» —
 * một màn hình nói ngược sự thật về credential, đúng loại làm người vận hành đi
 * bật lại thứ chưa bao giờ tắt.
 */
export async function taiKhoa(): Promise<DanhSachKhoa> {
  const d = await goi<DanhSachKhoa>(GOC)
  return {
    ...d,
    keys: d.keys.map((k) => ({
      ...k,
      status: k.status ?? 'active',
      revoked_at: k.revoked_at ?? null,
      // BE cũ (trước migration `0918`) không có trường này — `undefined` chứ
      // không phải `null`, cùng lý lẽ chuẩn hoá `status`/`revoked_at` ở trên.
      api_key: k.api_key ?? null,
    })),
  }
}

/**
 * Tạo khoá. Backend tự cấp phát hạ tầng (role Postgres + kho tệp) nếu workspace chưa có
 * khoá nào. Khái niệm "deployment" đã bỏ khỏi lược đồ ở migration `0941`.
 *
 * KHÔNG gửi `kind` hay `tenant_id`: payload khai `extra="forbid"` nên gửi thêm bị
 * 422. `kind` backend truyền cứng "chat"; tenant suy từ phiên.
 */
export function taoKhoa(label: string): Promise<KhoaDaTao> {
  return goi<KhoaDaTao>(GOC, { method: 'POST', body: JSON.stringify({ label }) })
}

/**
 * Bật/tắt khoá. MỘT hàm cho cả hai chiều — trạng thái là một giá trị, không
 * phải hai hành động.
 *
 * ⚠️ `POST {id}`, KHÔNG phải `DELETE` (đổi 2026-08-07). Backend chưa bao giờ xoá
 * hàng khoá — nó chỉ đặt `revoked_at` — nên `DELETE` là một động từ nói sai về
 * việc nó làm, và đã gây hiểu nhầm thật ("thu hồi này khác gì xoá đâu").
 *
 * 404 nếu khoá không tồn tại HOẶC thuộc workspace khác — backend không phân biệt.
 */
export function datTrangThaiKhoa(id: number, status: TrangThaiKhoa): Promise<Khoa> {
  return goi<Khoa>(`${GOC}/${id}`, { method: 'POST', body: JSON.stringify({ status }) })
}

/**
 * Xoay khoá: phát một khoá MỚI giữ nguyên nhãn, đồng thời thu hồi khoá CŨ ngay
 * lập tức — thay cho việc trước đây phải làm tay bằng hai bước (Tạo khoá mới,
 * rồi Tắt khoá cũ).
 *
 * Response CÙNG HÌNH DẠNG với `taoKhoa()` (`KhoaDaTao`, chứa khoá thô đúng một
 * lần) nên dùng lại được ĐÚNG `KhoaMoiDialog` đã có cho luồng tạo khoá.
 */
export function xoayKhoa(id: number): Promise<KhoaDaTao> {
  return goi<KhoaDaTao>(`${GOC}/${id}/rotate`, { method: 'POST' })
}

/**
 * Tên biến môi trường bên agent phải đặt khoá vào. Thứ DUY NHẤT bên đó không tự
 * đoán được, nên `KhoaMoiDialog` phải nói ra nó thành lời.
 *
 * ⚠ TRƯỚC 2026-08-24 ĐÂY LÀ `khoiEnv()`, trả về trọn dòng `AGENT_API_KEY=<khoá>`
 * cho dialog in ra dưới dạng `<pre>`. Dialog nay hiện KHOÁ TRẦN trong một ô có
 * nút copy (kiểu OpenAI, người dùng chốt) và nhắc tên biến trong câu dẫn — nên
 * chỗ duy nhất còn cần là cái tên, không phải cả dòng.
 *
 * ⚠ VÀ TRƯỚC 2026-08-21 `khoiEnv()` TRẢ BA DÒNG (`ENDPOINT_CHAT_URL` ·
 * `ENDPOINT_VOICE_URL` · `AGENT_API_KEY`). Hai dòng endpoint đã bỏ — người dùng
 * chốt, và hai URL đó vốn đã SAI: backend sinh chúng theo `url_endpoint_agent()`,
 * tức một subdomain riêng mỗi tenant, mô hình mà cả `gateway-voice-ws-spec.md` §1
 * lẫn handoff Chat §1 tuyên bố lỗi thời từ 2026-08-10 (giờ là MỘT domain chung,
 * tenant suy từ khoá Bearer). Chính FE đã né chúng từ trước — `/thu-agent` fix
 * cứng `WS_URL_CHAT_MAC_DINH`/`WS_URL_VOICE_MAC_DINH` thay vì đọc field. Dialog là chỗ
 * CUỐI CÙNG còn phát tán hai URL đó ra ngoài, nên bỏ là dọn nốt một hợp đồng đã
 * chết chứ không phải cắt bớt tiện ích.
 *
 * Hai field `endpoint_*_url` VẪN về từ `GET`/`POST /agent/keys` và vẫn nằm trong
 * `KhoaDaTao` — hợp đồng backend không đổi, chỉ FE thôi hiện chúng.
 *
 * Ở `api.ts` chứ không ở `KhoaMoiDialog.tsx`: eslint `react-refresh/only-export-components`
 * cảnh báo khi một file component export thêm thứ không phải component.
 *
 * `PORTAL_URL` CỐ Ý KHÔNG có ở dialog: nó là hằng số nền tảng, giống nhau cho mọi
 * tenant, ops đặt sẵn trong pod. Dialog chỉ đưa thứ THAY ĐỔI theo workspace. Xem
 * `docs/contracts/dau-noi-agent.md` §1 ở repo backend.
 */
export const TEN_BIEN_KHOA = 'AGENT_API_KEY'

/**
 * Hai WS URL của gateway — FIX CỨNG trong code, và ở ĐÂY chứ không ở
 * `ThuAgentScreen.tsx` vì từ 2026-08-24 có HAI chỗ đọc chúng: màn `/thu-agent`
 * mở phiên bằng chúng, và `KhoaMoiDialog` in chúng ra cạnh khoá vừa tạo (người
 * dùng chốt — bên agent cần cả ba giá trị để đấu nối, mà chỉ khoá là thứ không
 * đoán được thì hai URL kia họ cũng không đoán được). Hai bản sao của cùng một
 * domain là hai chỗ phải sửa ngày đổi domain, và chỗ thứ hai sẽ bị quên.
 *
 * ⚠ ĐÂY KHÔNG PHẢI `ENDPOINT_*_URL` QUAY LẠI (bỏ 2026-08-21, xem docstring
 * `TEN_BIEN_KHOA` ngay trên). Hai field ĐÓ do backend sinh theo
 * `url_endpoint_agent()`, tức một subdomain RIÊNG mỗi tenant — mô hình mà cả
 * `gateway-voice-ws-spec.md` §1 lẫn handoff Chat §1 tuyên bố lỗi thời từ
 * 2026-08-10. Hai hằng này là mô hình ĐÚNG: MỘT domain chung, tenant suy từ
 * khoá Bearer. Bỏ cái sai rồi in cái đúng không phải đảo quyết định — đó là vế
 * còn lại của cùng một quyết định, và lý lẽ cũ («một URL sai kèm một khoá đúng
 * thì nó BẢO ĐẢM ghép sai») nay đọc theo chiều ngược: URL đúng kèm khoá đúng
 * là bỏ được một lượt hỏi lại.
 *
 * CÙNG ORIGIN với portal (đổi 2026-10-01): `wss://<host portal>/v1/{chat,voice}`.
 * nginx của image này chuyển `/v1/` sang gateway của CHÍNH môi trường đó qua
 * `odyssey-network` (`deploy/odyssey-portal-frontend.conf.template`), giống `/api/`.
 * Trước đó hằng build-time trỏ cứng `wss://agent-uat.noble.vn` — một image cho mọi
 * môi trường nên dev và uat cùng gọi gateway uat.
 *
 * `VITE_AGENT_WS_URL_CHAT`/`_VOICE` (build-time) vẫn ghi đè được khi cần trỏ chỗ khác.
 */
export function wsUrlCungOrigin(
  duong: string,
  loc: Pick<Location, 'protocol' | 'host'> = window.location,
): string {
  return `${loc.protocol === 'https:' ? 'wss' : 'ws'}://${loc.host}${duong}`
}
export const WS_URL_CHAT_MAC_DINH =
  import.meta.env.VITE_AGENT_WS_URL_CHAT || wsUrlCungOrigin('/v1/chat')
export const WS_URL_VOICE_MAC_DINH =
  import.meta.env.VITE_AGENT_WS_URL_VOICE || wsUrlCungOrigin('/v1/voice')

/**
 * Swagger của gateway, backend serve. Nằm dưới `/api/v1` nên đi qua proxy của
 * vite ở dev — `/docs` trần sẽ rơi vào SPA.
 *
 * Hằng ở FE chứ không phải field trong response: đường dẫn này cố định, không
 * suy theo workspace. Khác `docsUrl` của cổng nạp, chỗ đó URL mang lĩnh vực và
 * phiên bản nên backend phải tự ghép.
 */
export const DUONG_TAI_LIEU_GATEWAY = '/api/v1/agent/gateway/docs'

/** Body của `POST /api/v1/agent/feedback` — đúng `enrollment.contracts.FeedbackIn`
 *  ở backend: KHÔNG có `tenant_id` (suy từ khoá), `rating` 1-5, `comment` rỗng
 *  hợp lệ. Schema khai `extra="forbid"` nên thêm khoá lạ là 422. */
export interface FeedbackAgentIn {
  readonly sessionId: string
  readonly rating: number
  readonly comment: string
}

/**
 * Ghi feedback cuối phiên — **mô phỏng đúng cách một app ngoài gọi**.
 *
 * Xác thực bằng `Authorization: Bearer <api_key>` của workspace, KHÔNG phải
 * cookie phiên portal (`goi()` không dùng được: nó không đặt header này, và
 * endpoint này không nhận phiên người dùng — xem `enrollment/router.py`, ba cổng
 * xác thực cố ý không dùng chung).
 *
 * ⚠️ `docs/contracts/dau-noi-agent.md` §2b nói rõ: khoá này KHÔNG được chạm
 * trình duyệt end-user (nó cũng mở được `/runtime-credentials`, tức mật khẩu
 * Postgres của tenant), nên một app thật phải để BE của nó gọi endpoint này.
 * Ở `/thu-agent` thì khác: khoá thô VỐN đã nằm trong trình duyệt để mở WS
 * (`gopKhoaVaoUrl`), màn này là công cụ nội bộ của người quản trị workspace, và
 * nó tồn tại để THỬ đúng đường mà app ngoài sẽ đi. Không có rủi ro mới nào phát
 * sinh ở đây — nhưng đừng bê hàm này sang một màn dành cho khách.
 */
export function guiFeedbackAgent(apiKey: string, d: FeedbackAgentIn): Promise<void> {
  return goi<void>('/api/v1/agent/feedback', {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ session_id: d.sessionId, rating: d.rating, comment: d.comment }),
  })
}

// ─── Hai hàm thuần định dạng thời gian ────────────────────────────────────────
//
// Nhận `bayGio` làm THAM SỐ chứ không gọi `new Date()` bên trong: một hàm đọc
// đồng hồ hệ thống thì test của nó xanh hay đỏ tuỳ lúc chạy. Cùng lý lẽ
// `bi_mat.dan_xuat()` ở backend nhận `master` thay vì tự đọc config.

/** `dd/MM/yyyy HH:mm` theo giờ máy người dùng. */
export function dinhDangLuc(iso: string): string {
  const d = new Date(iso)
  return `${ngayThangNam(d)} ${gioPhut(d)}`
}

/**
 * Nhãn cột Dùng cuối.
 *
 * TƯƠNG ĐỐI cho mốc dưới một ngày, TUYỆT ĐỐI cho cũ hơn. Vì câu hỏi thật của
 * người vận hành ở cột này là "pod còn sống không" — và "2 phút trước" trả lời
 * được câu đó ngay, còn "05/08/2026 14:32" thì bắt họ tự trừ.
 */
export function nhanDungCuoi(iso: string | null, bayGio: Date, chuaDung: string): string {
  if (iso === null) return chuaDung
  const giay = Math.floor((bayGio.getTime() - new Date(iso).getTime()) / 1000)
  return giay < 86_400 ? truoc(giay) : dinhDangLuc(iso)
}
