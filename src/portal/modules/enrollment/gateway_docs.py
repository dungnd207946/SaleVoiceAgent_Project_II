"""Tài liệu Swagger của gateway WS — sinh từ `tai_nguyen/gateway-protocol.json`.

Artifact đó là hợp đồng ĐI VÀO: nguồn sự thật nằm ở repo `odyssey-agent` (các
tool tự khai shape result của chúng), portal chỉ chép tay về và trình bày —
ngược chiều với `actions.json`/`tools.json`/`agent-config.json` do `make
contracts` sinh ra rồi chép SANG repo khác. Xem `contracts/README.md`.

Nó nằm TRONG package chứ không trong `contracts/`, và đọc bằng
`importlib.resources` chứ không bằng đường dẫn tính từ `__file__` — xem
docstring `tai_nguyen/__init__.py`, chỗ đó ghi lại cái 500 trên UAT mà bản đầu
gây ra.

Phân công: artifact giữ HÌNH DẠNG (schema từng event, từng tool result), file
này giữ CÂU CHỮ (dẫn nhập, close code, thứ tự một lượt). Đổi một field ở agent
thì chỉ artifact đổi; đổi cách diễn đạt thì chỉ file này đổi.

Vì sao Swagger cho một giao thức WebSocket: mục Schemas của Swagger UI là thứ
render `oneOf` lồng nhau và enum tốt nhất, mà đó đúng là phần đáng tiền — client
cần biết `send_media` trả field nào. Đổi lại phải tắt Try-it-out tường minh:
handshake WS không gọi được bằng nút bấm, để nút đó lại là mời dev bên khách
bấm vào rồi kết luận endpoint chết.
"""

import json
from functools import lru_cache
from importlib import resources
from typing import Any

PHIEN_BAN = "v1"

_GOI_TAI_NGUYEN = "portal.modules.enrollment.tai_nguyen"
_TEN_ARTIFACT = "gateway-protocol.json"


@lru_cache(maxsize=1)
def _catalog() -> dict[str, Any]:
    """Đọc qua `importlib.resources`, KHÔNG qua đường dẫn tính từ `__file__`.

    Đường dẫn tương đối vỡ khi app chạy từ wheel đã cài, và nó vỡ ở production
    chứ không ở test — bản đầu của hàm này trỏ `parents[4]/contracts/` và trả 500
    trên UAT sau khi qua sạch 485 bài test trong repo.
    """
    return json.loads((resources.files(_GOI_TAI_NGUYEN) / _TEN_ARTIFACT).read_text(encoding="utf-8"))


def _bang_close(close_codes: list[dict]) -> str:
    return "\n".join(f"| `{c['code']}` | `{c['reason']}` | {c['nghia']} |" for c in close_codes)


def _lien_ket(ten: list[str]) -> str:
    return " · ".join(f"`{t}`" for t in ten)


def _intro(ws_base: str, cat: dict) -> str:
    tools = cat["tools"]
    return f"""
Giao thức WebSocket của gateway agent, phía server gửi về client.

Hai endpoint dưới đây ghi `GET` vì handshake WebSocket là một HTTP GET kèm header
`Upgrade: websocket`, theo RFC 6455. Đó là request HTTP duy nhất trong cả phiên.

Câu hỏi của người dùng không đi bằng HTTP. Sau khi socket mở, mọi thứ là WebSocket frame:
client gửi câu hỏi bằng một TEXT frame, server trả lời bằng chuỗi event. Cách gửi xem mục
`/v1/chat` bên dưới.

## Kết nối

| Kênh | URL |
|---|---|
| Chat | `{ws_base}/v1/chat` |
| Voice | `{ws_base}/v1/voice` |

Một domain dùng chung cho mọi workspace. Workspace được suy từ API key, không từ hostname.

Trình duyệt không set được header `Authorization` cho WebSocket nên dùng query param:

```js
const ws = new WebSocket(`${{url}}?key=${{encodeURIComponent(apiKey)}}`);
ws.binaryType = 'arraybuffer';
```

Backend và CLI dùng `Authorization: Bearer <key>`, thắng query param nếu có cả hai.

API key này cũng mở được endpoint runtime credentials của workspace, nên ứng dụng thật phải
để backend của mình giữ khoá thay vì đưa xuống trình duyệt người dùng cuối.

Sau khi mở kết nối, gửi một TEXT frame JSON trong vòng 10 giây. Gửi `{{}}` cũng hợp lệ,
không gửi thì bị đóng với code 4008.

## Loại frame

| Loại | Nội dung |
|---|---|
| TEXT | Một object JSON có khoá `type`. Xem `ChatEvent` và `VoiceEvent` ở mục Schemas. |
| BINARY | Audio PCM16 mono little-endian, raw không header. Chat chỉ có khi bật TTS, voice luôn có. |

Phân biệt bằng `event.data instanceof ArrayBuffer`.

## Close code

| Code | Reason | Nghĩa |
|---|---|---|
{_bang_close(cat["close_codes"])}

`reason` nằm ở `event.reason` của `onclose`. Phân biệt `bad_credential` với
`auth_api_unavailable`, nếu không người dùng sẽ đi đổi khoá trong khi lỗi thật là hạ tầng.

## Ba luật parse

1. `type` không nhận ra thì bỏ qua, không crash. Event mới được thêm không báo trước.
2. Mọi field ngoài `type` coi là tuỳ chọn. Nhiều field chỉ có ở một biến thể.
3. Luôn đặt timeout phía client cho trạng thái đang trả lời, vì worker có thể chết giữa
   lượt mà không gửi `done`.

## Tool

Luôn bật: {_lien_ket(tools["core"])}

Tuỳ workspace: {_lien_ket(tools["optional"])}

Chỉ {_lien_ket(tools["rendered"])} có schema result để dựng card. Các tool còn lại trả
payload dành cho model, client chỉ dùng để hiện chip đang xử lý.

## Giới hạn

| Giới hạn | Hệ quả |
|---|---|
| Không resume được phiên | Mất mạng hoặc reload là mất hội thoại. Lưu local thì hiện lại được nhưng agent không nhớ. |
| Không có API lấy lịch sử | Màn hình mở ra luôn trống. |
| Kênh chat không có câu chào từ server | Client tự hiện lời chào. Voice có, với `turn_id` là `greeting`. |
| Không huỷ được lượt đang chạy | Nút dừng chỉ có thể là đóng WS rồi nối lại. |
| Một API key ứng với một workspace | Đổi workspace là đổi khoá và nối lại. |
"""


_CHAT = """
Kênh văn bản.

## Gửi câu hỏi

`GET` ở trên là handshake WebSocket. Câu hỏi gửi bằng TEXT frame sau khi socket đã mở, không
bằng HTTP body.

```js
ws.send(JSON.stringify({ type: 'user_text', text: 'Dự án Noble Crystal giá bao nhiêu?' }));
```

Ba message client gửi được:

| Message | Ý nghĩa |
|---|---|
| `{"type":"user_text","text":"...","tts":false}` | Một lượt hỏi. `tts: true` thì kèm audio PCM16 cho câu trả lời. |
| `{"type":"reset"}` | Xoá hội thoại, giữ nguyên `session_id`. Server trả `reset_ok`. |
| `{"type":"set_customer","identity":{...}}` | Cập nhật hồ sơ khách giữa phiên. Server trả `customer_ok`. |

JSON sai hoặc `type` lạ bị bỏ qua im lặng, không có phản hồi lỗi. Không có message huỷ lượt
đang chạy; muốn dừng thì đóng WS.

## Thứ tự một lượt trả lời

| Event | Ý nghĩa |
|---|---|
| `user_text` | Echo câu vừa gửi |
| `metrics` | Ngay trước token đầu tiên |
| `token` | Lặp nhiều lần, nối vào bong bóng đang mở |
| `tool_start` | Chốt bong bóng, hiện chip |
| `tool_done` | Chỗ duy nhất mang dữ liệu card |
| `token` | Lặp tiếp, bong bóng mới |
| `done` | Kết thúc lượt, mở lại ô nhập |
| `suggestions` | Sau `done`, có thể không đến |

Một lượt có thể có nhiều cụm token xen kẽ tool, tối đa 5 vòng.
"""

_VOICE = """
Kênh thoại. Client đẩy audio khách lên, server đẩy audio agent về kèm event JSON để hiển thị.

## Audio

`GET` ở trên là handshake WebSocket. Sau khi socket mở, client đẩy audio bằng BINARY frame.

| Chiều | Định dạng |
|---|---|
| Client gửi lên | PCM16 mono 16 kHz, raw không header. Khuyến nghị frame 20 ms, tức 640 byte. |
| Server gửi về | PCM16 mono 48 kHz, raw không header. Phát và ghép tuần tự. |

Kênh này không nhận câu hỏi dạng văn bản: mọi TEXT frame client gửi lên đều bị bỏ qua, trừ
frame handshake đầu tiên.

Chiều xuống là 48 kHz: worker publish TTS ở 24 kHz nhưng gateway resample về 48000 trước
khi đẩy ra WS. Frame không mang header nên client phải cố định giá trị này. Phát ở 24 kHz
sẽ nghe chậm một nửa và trầm.

## Thứ tự một lượt

| Event | Ý nghĩa |
|---|---|
| `partial_transcript` | Lặp nhiều lần khi khách đang nói, ghi đè bản trước |
| `transcript` | Chốt lời khách, mở đầu turn |
| `tool_start`, `tool_done` | Nếu agent gọi tool. `tool_done` không mang `result`. |
| `media` | Nếu tool trả về ảnh hoặc video |
| `agent_speaking` | Lặp theo từng câu, ngay trước khi audio câu đó phát |
| `agent_done` | Kết thúc turn |

Khách ngắt lời thì `agent_interrupted` chen vào, sau đó vẫn có `agent_done`.

Đầu phiên có câu chào với `turn_id` là `greeting`. Đóng WS là cúp máy.

## Độ tin cậy

Event ở kênh này là best-effort: chúng đi qua queue 256 phần tử và bị drop khi đầy để không
bao giờ chặn audio. Không suy trạng thái cuộc gọi từ event; âm thanh và trạng thái WS mới là
nguồn sự thật, event chỉ để hiển thị.
"""


def _kenh(ten: str, events: dict, mo_ta: str) -> dict:
    return {
        "title": f"{ten}Event",
        "description": mo_ta,
        "oneOf": [{"$ref": f"#/components/schemas/Event_{ten.lower()}_{k}"} for k in events],
        "discriminator": {"propertyName": "type"},
    }


def _op(tag: str, mo_ta: str, ref: str) -> dict:
    return {
        "tags": [tag],
        "summary": f"Mở phiên {tag}",
        "description": mo_ta,
        "responses": {
            "101": {
                "description": f"Nâng cấp lên WebSocket. Mọi TEXT frame server gửi khớp `{ref}`.",
                "content": {"application/json": {"schema": {"$ref": f"#/components/schemas/{ref}"}}},
            },
            "4001": {"description": "Đóng WS: thiếu key, key sai, hoặc hệ thống auth lỗi."},
            "4008": {"description": "Đóng WS: không gửi frame handshake trong 10 giây."},
        },
    }


@lru_cache(maxsize=4)
def spec(ws_base: str) -> dict[str, Any]:
    """OpenAPI 3.1 của gateway. Cache theo `ws_base` vì nó đến từ settings."""
    cat = _catalog()
    ev = cat["events"]

    schemas: dict[str, Any] = {"MediaItem": cat["media_item"]}
    schemas.update({f"ToolResult_{k}": v for k, v in cat["tool_results"].items()})
    for nhan in ("chat", "voice"):
        for ten, sch in ev[nhan].items():
            schemas[f"Event_{nhan}_{ten}"] = {"title": ten, **sch}
    schemas["ChatEvent"] = _kenh("Chat", ev["chat"], "Mọi TEXT frame server gửi ở kênh chat.")
    schemas["VoiceEvent"] = _kenh("Voice", ev["voice"], "Mọi TEXT frame server gửi ở kênh voice.")

    thieu = [r["$ref"] for r in _moi_ref(schemas) if r["$ref"].rsplit("/", 1)[-1] not in schemas]
    if thieu:
        raise RuntimeError(f"gateway-protocol.json có $ref không đích: {sorted({t for t in thieu})}")

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "NobleX Agent Platform — Gateway WebSocket",
            "version": cat["version"],
            "description": _intro(ws_base, cat),
        },
        "servers": [{"url": ws_base}],
        "tags": [
            {"name": "chat", "description": "Kênh văn bản"},
            {"name": "voice", "description": "Kênh thoại"},
        ],
        "paths": {
            "/v1/chat": {"get": _op("chat", _CHAT, "ChatEvent")},
            "/v1/voice": {"get": _op("voice", _VOICE, "VoiceEvent")},
        },
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "bearer": {"type": "http", "scheme": "bearer", "description": "Backend và CLI."},
                "queryKey": {"type": "apiKey", "in": "query", "name": "key", "description": "Trình duyệt."},
            },
        },
        "security": [{"bearer": []}, {"queryKey": []}],
    }


def _moi_ref(node: Any):
    """Mọi `$ref` trong cây — dùng để bắt artifact trỏ vào schema không tồn tại."""
    if isinstance(node, dict):
        if "$ref" in node:
            yield node
        for v in node.values():
            yield from _moi_ref(v)
    elif isinstance(node, list):
        for v in node:
            yield from _moi_ref(v)


_CDN = "https://unpkg.com/swagger-ui-dist@5"

_TRANG = f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NobleX Agent Platform — Gateway WebSocket</title>
<link rel="stylesheet" href="{_CDN}/swagger-ui.css">
<style>
  /* Swagger UI mặc định tô inline code màu tím #9012fe. Description ở đây dày
     tên field trong backtick nên cả trang thành tím. */
  .swagger-ui .markdown code,
  .swagger-ui .renderedMarkdown code {{ color: inherit }}
</style>
</head>
<body>
<div id="ui"></div>
<script src="{_CDN}/swagger-ui-bundle.js"></script>
<script>
SwaggerUIBundle({{
  url: 'openapi.json',
  dom_id: '#ui',
  // Handshake WebSocket không gọi được bằng nút bấm; để Try-it-out lại là mọi
  // operation có một nút trả 426.
  supportedSubmitMethods: [],
}});
</script>
</body>
</html>
"""


def trang() -> str:
    """Swagger UI. `url` TƯƠNG ĐỐI nên module không phải biết tiền tố `/api/v1`."""
    return _TRANG


def ten_tep_spec() -> str:
    return f"noblex-gateway-{PHIEN_BAN}.openapi.json"
