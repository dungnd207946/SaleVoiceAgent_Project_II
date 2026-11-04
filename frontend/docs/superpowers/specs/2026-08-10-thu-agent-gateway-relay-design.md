# `/thu-agent` — chat qua gateway thật (thiết kế)

> ⚠️ **SUPERSEDED HOÀN TOÀN — cả UI ở §1 lẫn cơ chế relay ở §2–§4 đều không
> còn đúng.** Sau spec này: (1) UI revert về 4 ô gốc + 1 ô WS URL (không phải
> 2-ô). (2) Tài liệu handoff chính thức của team gateway
> (`odyssey-portal-backend/docs/build_test_agent/2026-08-10-frontend-chat-gateway-handoff.md`)
> xác nhận trình duyệt nối THẲNG được qua `?key=` — **relay ở backend đã XOÁ
> hoàn toàn**, không còn "VẪN ĐÚNG" như ghi chú superseded trước đó của chính
> file này. Nguồn sự thật hiện hành: mục **"Thử agent — chat qua gateway
> thật, nối THẲNG từ trình duyệt"** trong `CLAUDE.md` (Change Log 2026-08-10
> dòng mới nhất).
>
> **Ngày:** 2026-08-10 · **Trạng thái:** đã duyệt (chốt trong hội thoại, sửa hướng lần hai)
> **Repo:** `odyssey-portal-frontend`
> **Repo liên quan:** `odyssey-portal-backend` — spec `2026-08-10-agent-demo-gateway-relay-design.md`
>   (route WebSocket `/api/v1/agent-demo/relay` mà màn này gọi)

## 0. Đổi hướng — đọc trước khi đọc phần còn lại

Bản đầu của spec này (cùng ngày) nhắm màn `/thu-agent` vào "noble_agent" — một
service ngoài giả định, xin phiên qua REST với `noble_user_id` +
`X-Noble-App-Key`. **Đó là sai đích.**

Người dùng đưa ra một script vận hành thật (`chat_via_gateway.py`) cho thấy
cái cần thử là **gateway thật của chính portal** (`/v1/chat`) — đúng gateway
mà `/api-keys` đã phát khoá cho (`Khoa` mang tiền tố `ody_ag_...`, cùng họ
token script dùng). Không có REST "xin phiên" nào — chỉ MỘT WebSocket, xác
thực bằng `Authorization: Bearer <khoá thô>`.

## 1. Vì sao chỉ 2 ô, và vì sao phải qua relay

**Trình duyệt không đặt được header `Authorization` lúc mở WebSocket** —
giới hạn của Web API. Script làm được vì nó chạy bằng thư viện Python
`websockets` (server-side), không phải trong trình duyệt.

Nên FE không nối thẳng tới gateway — nó nối tới **relay của backend**
(`POST /api/v1/agent-demo/relay`, một WebSocket), gửi `{ws_url, api_key}` làm
frame đầu; backend mở kết nối RA gateway bằng đúng header đó, rồi chuyển tiếp
nguyên văn hai chiều.

```
Trình duyệt          odyssey-portal-backend (relay)         gateway thật
   │ mở WS /api/v1/agent-demo/relay (cookie phiên portal)        │
   │ gửi {ws_url, api_key} ───────────►                           │
   │                    mở WS ra gateway, header Bearer ────────► │
   │      ◄── __relay_ready__ ─────────                           │
   │ gửi {identity, call_id} (bắt tay THẬT) ──────────────────────►│
   │ ◄──────────────── token / tool_start / done / error ────────►│
```

**Hai ô, không hơn:**

| Ô | Là gì |
|---|---|
| **WS URL** | Địa chỉ `/v1/chat` của gateway (ví dụ `wss://acme.agents.noblex.vn/v1/chat`) — đúng URL đã hiện ở `/api-keys` |
| **API Key** | Khoá THÔ (`ody_ag_...`) — tạo ở `/api-keys`, dán trực tiếp. Portal không lưu lại khoá thô sau khi tạo nên đây LÀ ô dán, không phải ô chọn theo tên |

**Không còn:** Base URL/App Key/Noble User ID (3 ô của bản noble_agent, sai
đích) — cũng không còn 7-trường-khách-giả-lập noble. Khách giả lập rút về
**2 trường đúng hình dạng script**: `name` + `phone` (không phải `full_name`
— tên trường khác, service khác).

## 2. Kiến trúc code

```
src/features/platform/
  chatGateway.ts           moPhienChatGateway() — mở WS tới relay, quản lý bắt tay
  components/ThuAgentScreen.tsx   2 ô cấu hình + khách giả lập + khung chat
```

### `chatGateway.ts`

```ts
export interface CauHinhGateway {
  readonly wsUrl: string
  readonly apiKey: string
}

export interface DanhTinhGateway {
  readonly name?: string
  readonly phone?: string
}

export function moPhienChatGateway(o: TuyChonChatGateway): PhienChatGatewayMo {
  const ws = new WebSocket(duongRelay())   // duongRelay() = same-origin /api/v1/agent-demo/relay

  ws.onopen = () => ws.send(JSON.stringify({ ws_url: o.cauHinh.wsUrl, api_key: o.cauHinh.apiKey }))

  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.type === '__relay_ready__') {
      ws.send(JSON.stringify({ identity: locTrongDanhTinh(o.danhTinh), call_id: `portal-${Date.now()}` }))
      o.onTrangThai('song')
      return
    }
    if (m.type === '__relay_error__') { o.onRelayError(m.message); return }
    xuLySuKienGateway(m, o)   // token / tool_start / tool_done / done / suggestions / error
  }
  ...
}
```

Hai loại frame KHÔNG thuộc giao thức gateway — `__relay_ready__` /
`__relay_error__` — do backend tự chế để nói "tôi (relay) mở được/không mở
được upstream". FE phải phân biệt chúng khỏi event thật của gateway trước khi
đưa vào `xuLySuKienGateway()`.

### Đóng WS — ba nghĩa khác nhau, phân biệt bằng CODE

| Code | Nghĩa | FE hiện gì |
|---|---|---|
| `4401` | Relay từ chối vì portal CHƯA CÓ phiên đăng nhập (cookie hết hạn…) | "Chưa đăng nhập portal — tải lại trang" |
| khác, sau khi đã `song` | Gateway đích đóng, hoặc mất mạng | "Mất kết nối tới phiên chat" (chung — không đoán lý do cụ thể) |
| bất kỳ, ngay sau `__relay_error__` | Đã có câu báo cụ thể từ `__relay_error__` | KHÔNG hiện gì thêm — cờ `daBaoLoiRelay` chặn ghi đè |

⚠️ Bản noble_agent cũ gán nghĩa "token hết hạn" cho code `4401` theo tài liệu
noble_agent — **nghĩa đó không áp dụng ở đây**. `4401` của relay này là chuyện
khác hẳn (phiên portal, không phải phiên chat).

## 3. Không còn REST nào trong luồng này

Khác bản noble_agent (có `POST /api/v1/agent-demo/session`), bản này **không
gọi REST nào để "xin phiên"** — mở WS là xong, không có bước trung gian. Đơn
giản hơn, và đúng với cách script vận hành thật hoạt động (không hề có bước
"xin phiên" nào trong đó).

## 4. MSW — không có fake, và đó là đúng

MSW không giả lập được WebSocket. Route `/api/v1/agent-demo/relay` là WS, nên
**không có fake nào để viết** — dưới `VITE_MSW=1`, màn mở được, form điền
được, nhưng bấm «Bắt đầu phiên» sẽ không kết nối được gì (không có handler
nào bắt request WS, trình duyệt cố nối thật tới `/api/v1/agent-demo/relay`
của dev server và thất bại vì backend không chạy). Đây là hành vi ĐÚNG, không
phải thiếu fake — không có gì hợp lý để giả ở tầng này.

## 5. Test

`FakeWebSocket` (`vi.stubGlobal`) — từ góc nhìn FE chỉ có MỘT kết nối WS (tới
relay), nên test mô phỏng CẢ giao thức relay (`__relay_ready__`/`__relay_error__`)
VÀ giao thức gateway đích (`token`, `tool_start`…) trên cùng một fake, không
cần hai lớp mock.

| # | Ca |
|---|---|
| 1 | Thiếu WS URL hoặc API Key ⇒ Bắt đầu phiên khoá |
| 2 | WS mở tới relay của backend, KHÔNG tới WS URL đã gõ |
| 3 | Frame đầu gửi lên relay đúng `{ws_url, api_key}` |
| 4 | `__relay_ready__` ⇒ FE gửi ngay bắt tay `{identity, call_id}`, identity lọc field rỗng |
| 5 | `__relay_error__` ⇒ hiện đúng câu báo, KHÔNG bao giờ hiện "Sẵn sàng" |
| 6 | Đóng `4401` ⇒ báo "chưa đăng nhập portal" |
| 7 | Chat hai chiều: gửi `user_text`, ghép `token`, hiện `tool_start`/`tool_done`, `suggestions` (chip không tự gửi), `error` (không đóng phiên), `reset`, ngắt kết nối thủ công (không báo lỗi), đóng bất thường sau khi đã `song` (báo mất kết nối) |
| 8 | Cấu hình nhớ qua `localStorage` |

## 6. Việc kéo theo

- Xoá `features/platform/nobleAgent.ts` (bản REST sai đích) → thay bằng
  `chatGateway.ts`.
- `lib/msw/handlers.ts`: bỏ hẳn fake `POST /api/v1/agent-demo/session` (không
  còn endpoint đó) — không thêm fake khác, vì không có gì để giả ở WS (§4).
- `tests/boot.test.tsx`: dấu hiệu màn `thu-agent` đổi sang nhãn ô «WS URL».
