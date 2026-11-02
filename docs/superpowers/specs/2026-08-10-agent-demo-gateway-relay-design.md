# Agent Demo — relay WebSocket tới gateway chat thật (thiết kế)

> ⚠️ **SUPERSEDED — module `agent_demo` đã XOÁ.** Tài liệu handoff chính thức
> của team gateway (`docs/build_test_agent/2026-08-10-frontend-chat-gateway-handoff.md`)
> xác nhận trình duyệt nối THẲNG được tới gateway qua `?key=` trong URL — relay
> ở spec này là dư, không phải bắt buộc như suy đoán lúc viết. Nguồn sự thật
> hiện hành: mục `agent_demo` trong `CLAUDE.md` (dòng Change Log 2026-08-10).
>
> **Ngày:** 2026-08-10 · **Trạng thái:** đã duyệt (chốt trong hội thoại, sửa hướng lần hai)
> **Repo:** `odyssey-portal-backend`
> **Repo liên quan khác:** `odyssey-portal-frontend` — spec `2026-08-10-thu-agent-noble-luna-design.md`

## 0. Đổi hướng — đọc trước khi đọc phần còn lại

Bản đầu của spec này (cùng ngày) thiết kế một **proxy REST** xin phiên chat từ
"noble_agent" — một service ngoài giả định, dựa trên tài liệu
`docs/build_test_agent/external-chat-integration.md`. **Đó là nhắm sai đích.**

Người dùng đưa ra một script vận hành thật (`chat_via_gateway.py`) chứng minh:
cái cần thử chính là **gateway thật của portal** (`/v1/chat`, đúng gateway mà
`/api-keys` đã phát khoá — token `ody_ag_...` trong script khớp
`control.agent_keys`), xác thực bằng **`Authorization: Bearer <khoá thô>`**
lúc mở WebSocket — không có bước "xin phiên" REST nào cả.

Tài liệu `external-chat-integration.md` (noble_agent, port 8766, session
provisioning) **không liên quan gì đến việc cần làm** — không sửa, không xoá,
chỉ không dùng ở đây.

## 1. Vấn đề thật: trình duyệt không đặt được header `Authorization`

Script vận hành mở WS bằng thư viện Python `websockets`, gắn thẳng header:

```python
async with websockets.connect(
    "ws://an-phu-land_q8w2_retail.lvh.me:9200/v1/chat",
    additional_headers={"Authorization": "Bearer " + TOKEN},
) as ws:
    await ws.send(json.dumps({"identity": {...}, "call_id": "c1"}))
    ...
```

**WebSocket API của trình duyệt không có cách đặt header tuỳ ý** (giới hạn
của Web API, không phải một chỗ FE code sai). Nên không thể mở đúng y script
này từ trình duyệt bằng bất kỳ cách viết code nào ở FE.

## 2. Giải pháp: relay câm ở backend

Portal đứng giữa, đóng đúng vai script — mở kết nối RA gateway bằng thư viện
`websockets` (Python), gắn header, rồi làm **ống dẫn câm**: chuyển tiếp
nguyên văn hai chiều, không đọc hiểu giao thức của gateway đích.

```
Trình duyệt                    odyssey-portal-backend                gateway thật
   │  1. WS → /api/v1/agent-demo/relay (cookie phiên portal)              │
   │  2. gửi {ws_url, api_key}  ─────────────►                            │
   │                             xác thực phiên (cookie)                  │
   │                             mở WS RA gateway, header Bearer  ───────►│
   │                             ◄── __relay_ready__ ─────────            │
   │  3. gửi {identity, call_id} (bắt tay THẬT của gateway) ─────────────►│
   │  4. chat hai chiều — relay chuyển tiếp NGUYÊN VĂN mọi frame ◄───────►│
```

## 3. Kiến trúc code

```
src/portal/modules/agent_demo/
  __init__.py
  contracts.py   CauHinhRelay — hình dạng frame ĐẦU TIÊN client gửi lên relay
  service.py     mo_upstream() · chuyen_tiep() — mở ra + bơm hai chiều
  router.py      MỘT route WebSocket, KHÔNG dùng require()
```

Không có `repo.py` — không truy vấn Postgres. Không migration.

### `contracts.py`

```python
class CauHinhRelay(BaseModel):
    ws_url: str
    api_key: str
```

Đúng MỘT model — mọi frame sau đó là chuyển tiếp nguyên văn, router không đọc
hiểu giao thức gateway đích (không biết `token`/`tool_start`/... là gì, và
không cần biết).

### `service.py`

```python
async def mo_upstream(ws_url: str, api_key: str) -> Any:
    return await asyncio.wait_for(
        websockets.connect(ws_url, additional_headers={"Authorization": f"Bearer {api_key}"}),
        timeout=TIMEOUT_MO_GIAY,
    )

async def chuyen_tiep(browser: WebSocket, upstream: Any) -> None:
    """Hai task chạy song song — browser→upstream, upstream→browser — huỷ
    nhau khi MỘT bên xong (đóng, lỗi, hoặc hết việc)."""
```

### `router.py`

```python
@ROUTER.websocket("/agent-demo/relay")
async def relay(websocket: WebSocket) -> None:
    sid = websocket.cookies.get(ss.TEN_COOKIE, "")
    phien = await ss.doc(websocket.app.state.redis, sid)
    if phien is None:
        await websocket.close(code=4401)          # chưa đăng nhập portal
        return
    await websocket.accept()
    cau_hinh = CauHinhRelay.model_validate_json(await websocket.receive_text())
    upstream = await service.mo_upstream(cau_hinh.ws_url, cau_hinh.api_key)   # lỗi ⇒ __relay_error__ + 1011
    async with upstream:
        await websocket.send_text(json.dumps({"type": "__relay_ready__"}))
        await service.chuyen_tiep(websocket, upstream)
```

## 4. Vì sao KHÔNG dùng `require()`

`require(action)` (`core/auth/require.py`) đọc `request: Request` — không tồn
tại trong ngữ cảnh WebSocket (Starlette tách hẳn `Request`/`WebSocket` ở tầng
ASGI; một dependency đòi `Request` không giải quyết được cho một route
`@router.websocket()`). Route này tự đọc cookie phiên bằng tay, gọi đúng
`core/auth/session.py` mà `require()` cũng gọi bên trong — cùng nguồn sự
thật, khác đường vào.

Hệ quả: route này **vô hình** với `test_moi_route_khai_action.py` — cổng đó
chỉ quét `APIRoute` (HTTP), và `api/registry.py` đã tự ghi rõ điều này
(`liet_ke_route()`, dùng `isinstance(ctx.route, APIRoute)`). Gác cổng ở đây
phải tự nghiêm, không dựa vào cổng ngoài.

## 5. Rủi ro SSRF — đã biết, đã đánh đổi có ghi lại

Relay nối ra bất kỳ `ws_url` mà client gửi lên. Đây **là** tính năng yêu cầu
("gõ URL bất kỳ để thử với gateway thật"), không phải lỗ hổng ngoài ý muốn.
Giảm rủi ro bằng đúng MỘT lớp: chỉ phục vụ người đã có phiên đăng nhập portal
hợp lệ. Không giới hạn host đích — giới hạn đó xoá thẳng tính năng.

Đây là công cụ nội bộ, dùng bởi người có quyền tương đương xem cấu hình agent
— đánh đổi chấp nhận được cho phạm vi đó, không chấp nhận được nếu route này
mở ra ngoài internet không cần đăng nhập.

## 6. Bí mật không vào log

`cau_hinh.api_key` chỉ sống trong tham số hàm và header gửi ra ngoài. Khi
`mo_upstream()` raise, log chỉ ghi `type(e).__name__` (tên lớp exception),
KHÔNG ghi `str(e)` nguyên văn nếu nó có thể phản chiếu lại thứ đã gửi.

## 7. Test

Không có gateway thật để test tựa vào — giả lập bằng `_FakeUpstream` (đủ
giao diện `send`/`__aiter__`/`async with`), monkeypatch `service.mo_upstream`.

| # | Cổng | File |
|---|---|---|
| 1 | Chưa đăng nhập ⇒ đóng `4401` | `test_agent_demo_relay.py` |
| 2 | Frame đầu sai định dạng ⇒ đóng `4400` | cùng file |
| 3 | Không mở được upstream ⇒ nhận `__relay_error__` rồi đóng `1011` | cùng file |
| 4 | Chuyển tiếp đúng CẢ HAI chiều, nguyên văn | cùng file |
| 5 | Upstream đóng ⇒ relay đóng đúng mã đó cho browser | cùng file |

`ws_client` (fixture riêng, `starlette.testclient.TestClient`) — `httpx.AsyncClient`
(`app_client` ở root conftest) **không mở được WebSocket**; `TestClient` có
`.websocket_connect()` và tự chạy lifespan qua `with`.

## 8. Việc kéo theo

- `pyproject.toml`: `websockets>=17.0` vào `[project.dependencies]` (đã có sẵn
  transitive qua `uvicorn[standard]`, giờ import trực tiếp nên khai tường
  minh). `httpx` VỀ LẠI nhóm `dev` — không còn dùng lúc chạy thật (bản REST
  proxy cũ dùng nó để gọi noble_agent; bản relay không gọi HTTP nào).
- Không action mới, không contract mới cho FE/agent (`contracts/*.json`
  không đổi).
