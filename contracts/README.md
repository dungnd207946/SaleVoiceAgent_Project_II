# `contracts/` — artefact hợp đồng giữa repo BE và repo FE

Thư mục này có **hai chiều**, đừng gộp:

| Chiều | File | Nguồn sự thật | Cách cập nhật |
|---|---|---|---|
| Đi ra | `actions.json` · `audit-actions.json` · `tools.json` | `src/portal` | `make contracts`, **không sửa tay** |
| Đi vào | `gateway-protocol.json` — **không nằm ở đây**, xem mục cuối | repo `odyssey-agent` | chép tay về |

Với ba file đi ra: sửa nguồn rồi chạy

```bash
make contracts
```

## Vì sao thư mục này tồn tại

Thời monorepo, `apps/frontend/tests/actions-parity.test.ts` đọc thẳng
`apps/backend/src/portal/core/auth/actions.py` qua đường tương đối. Tách thành hai repo git thì
đường đó không còn.

Spec tổng §4① đã ghi nhận việc này và giao cho M2a-BE, kèm ba hướng: ① commit artefact vào repo FE
rồi sinh/so tại chỗ · ② publish npm package từ repo BE · ③ sinh trong CI của FE từ một backend đang
chạy. **Chọn ①**, và dùng cùng một cơ chế cho mọi hợp đồng BE→FE thay vì mỗi loại một kiểu — spec
nói "hai việc là cùng một đường nối, cân một lần".

Không chọn ② vì publish npm package cho 13 chuỗi là chi phí vận hành lớn hơn thứ nó bảo vệ. Không
chọn ③ vì nó bắt CI của FE phải dựng được backend — FE mất khả năng test offline, và một backend
hỏng làm pipeline FE đỏ vì lý do không liên quan.

## Luật

```
odyssey-portal-backend/contracts/     ← nguồn sinh ra, BE commit
odyssey-portal-frontend/contracts/    ← bản sao byte-for-byte
```

1. **BE sinh, BE commit.** `make contracts` ghi lại thư mục này từ `src/portal`.
2. **FE sao, FE commit.** Từ thư mục gốc chứa cả hai repo:
   ```bash
   cp odyssey-portal-backend/contracts/actions.json odyssey-portal-frontend/contracts/actions.json
   ```
3. **Mỗi repo test với bản sao của chính mình.**
   - BE: `tests/api/test_contracts.py` — artefact phải khớp `ALL_ACTIONS`. Sửa `actions.py` mà quên
     `make contracts` ⇒ đỏ.
   - FE: `tests/actions-parity.test.ts` — artefact phải khớp `src/lib/actions.ts`. Đổi một bên mà
     quên bên kia ⇒ đỏ.

## Khoảng hở còn lại — nói thẳng, đừng tưởng đã kín

Bước 2 là thao tác tay. **BE đổi `actions.py` + chạy `make contracts` + commit, mà không ai copy
sang FE ⇒ cả hai repo vẫn xanh.** Lệch chỉ lộ ra lúc chạy app: một mục nav hiện với người không có
quyền, hoặc một endpoint trả 403 mà FE không hiểu tại sao.

Đóng khoảng hở này cần một job CI trong pipeline **BE** (repo sở hữu nguồn) fetch
`contracts/actions.json` của repo FE qua GitLab raw API rồi so. Chưa làm vì cần CI token, và vì nó
kéo theo một đánh đổi phải chấp nhận có ý thức: MR của FE sẽ làm đỏ được pipeline BE và ngược lại.

Tới lúc đó, quy ước bù: **đổi action là một cặp MR, hai repo, mở cùng lúc**, ghi chéo link cho nhau
trong mô tả.

## Có gì trong đây

| File | Sinh từ | Ai đọc |
|---|---|---|
| `actions.json` | `src/portal/core/auth/actions.py` | `tests/actions-parity.test.ts` của repo FE |
| `audit-actions.json` | `src/portal/core/nhat_ky_ma.py` (sổ mã hành động nhật ký) | `tests/audit-actions-parity.test.ts` của repo FE — mọi mã phải có nhãn tiếng Việt |

## Còn `openapi.json` thì sao

Spec tổng §4① để mở "cách FE lấy type của backend" và giao cho M2a-BE. **Phần đã chốt ở đây là cơ
chế**: thư mục này, một phép copy, mỗi repo test với bản sao của mình — và nó đã được chứng minh
chạy được bằng `actions.json`.

**Chưa ship `openapi.json`, có chủ ý.** Sinh nó bây giờ là thêm một artefact phải regenerate mỗi lần
đổi endpoint mà **chưa ai đọc**: FE hiện khai tay kiểu `Session` trong `src/lib/session.tsx`, và sinh
type từ OpenAPI cần thêm một bộ codegen (`openapi-typescript`) cộng một bước build ở repo FE — cả
hai đều ngoài phạm vi M2a.

Điều kiện để làm: khi module đầu tiên có DTO đủ phức tạp để khai tay hai lần là sai lệch thật (M3
hoặc M4). Lúc đó `make contracts` thêm một dòng, FE thêm bước codegen, luật ở trên không đổi.


## `gateway-protocol.json` — artefact ĐI VÀO, chiều ngược lại

Ba file trên sinh ở portal rồi chép sang repo khác. File này thì ngược: nguồn sự thật là code của
repo `odyssey-agent` — các tool tự quyết định result của chúng có field gì — và portal chỉ chép về
để **trình bày**.

⚠️ **Nó KHÔNG nằm trong thư mục này.** Đường dẫn thật:

```
src/portal/modules/enrollment/tai_nguyen/gateway-protocol.json
```

Lý do là đóng gói, không phải phân loại: `Dockerfile` build bằng `uv sync --no-editable` rồi runtime
stage chỉ copy `.venv`, `alembic.ini` và `migrations` — **`contracts/` không bao giờ vào image**. Bản
đầu đặt file ở `contracts/` và đọc bằng `Path(__file__).parents[4]`; nó chạy trong repo, qua sạch
485 bài test, rồi trả **500 trên UAT** vì tệp không tồn tại ở đó. Nay nó là package data, đọc bằng
`importlib.resources` — cùng khuôn `modules/auth/tai_nguyen/logo-nx-agent-96.png`.

Nhắc ở đây vì đây là chỗ người ta sẽ tới tìm nó.

Ai đọc: `src/portal/modules/enrollment/gateway_docs.py`, sinh ra Swagger ở
`GET /api/v1/agent/gateway/docs`. Trang đó bàn giao cho dev bên khách cùng lúc với API key.

Phân công cố ý: artefact giữ **hình dạng** (schema từng event, từng tool result), `gateway_docs.py`
giữ **câu chữ** (dẫn nhập, close code, thứ tự một lượt). Đổi một field ở agent thì chỉ artefact đổi;
đổi cách diễn đạt thì chỉ portal đổi.

### Khoảng hở, nói thẳng

**Bản hiện tại được viết tay**, bằng cách đọc source repo agent (`agent/tools/support_ops.py`,
`schedule_viewing.py`, `data/media_data.py`, `server/text_chat.py`, `voice/voice_agent.py`). Chưa
có script sinh nó, và chưa có cổng nào bắt được lệch.

Đó chính là cách tài liệu markdown cũ (`docs/build_test_agent/*`) đã lệch, và lệch im lặng — đo
được ba chỗ lúc viết file này:

| Lệch | Hệ quả cho client viết theo tài liệu cũ |
|---|---|
| `items[].kind` khai `image`/`video`, thật ra có bốn: thêm `tour` và `file` | Bỏ qua im lặng tour 360 và video Google Drive |
| `video` mang caption ở `title`, ba loại kia ở `label` | Mất caption của đúng video |
| Event `agent_switch` phát ra thật, không có trong tài liệu nào | Không biết tồn tại |

Kế hoạch đóng, đã chốt nhưng **chưa làm**: khai catalog thành hằng ở
`odyssey-agent/src/noble_agent/gateway/protocol.py`, validate nó tại `dispatcher.py` chỗ
`on_tool_done` (điểm nghẽn duy nhất mọi result đi qua) với một cờ bật trong test, rồi export ra
đúng file này. Khi đó mọi bài test sẵn có chạm tool trở thành bài canh catalog, và `gateway_docs.py`
không phải đổi một dòng — nó vẫn đọc cùng một JSON.

Tới lúc đó, quy ước bù giống hệt `actions.json`: **đổi shape result của một tool là một cặp MR, hai
repo, mở cùng lúc.**
