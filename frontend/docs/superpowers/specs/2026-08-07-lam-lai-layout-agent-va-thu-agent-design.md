# Làm lại layout màn Agent + chuyển Thử agent sang màn API Keys

**Ngày:** 2026-08-07 · **Phạm vi:** FE (`odyssey-portal-frontend`), không đụng backend
**Trạng thái:** đã duyệt qua brainstorming với người dùng, chờ implementation plan

## 1. Vấn đề

Layout hiện tại xếp sai chỗ ba thứ so với bản chất của agent (agent = system prompt
+ tools + knowledge):

1. **Màn Agent Studio gộp mọi thứ**: danh tính · giọng điệu · phạm vi (system
   prompt — là thứ **chung** của agent) nằm lẫn với 12 toggle kỹ năng, trong khi
   9/12 kỹ năng là đồ nghề của riêng **lĩnh vực Bất động sản**. Lĩnh vực trong
   sidebar thì chỉ có knowledge, không thấy tools của lĩnh vực đâu.
2. **Nhãn nav "Agent & Kênh"** hứa quản lý kênh — không có kênh nào tồn tại.
3. **Panel "Thử ngay" nằm ở màn Agent** — nhưng thử agent phải đi qua đúng kênh
   khách dùng (HT01 BR03), tức là qua khoá API. Nó thuộc về màn khoá API, và chỉ
   có nghĩa khi đã có khoá.

## 2. Quyết định đã chốt (hỏi–đáp brainstorming)

| # | Câu hỏi | Chốt |
|---|---|---|
| 1 | Phạm vi thay đổi | **FE trước, backend sau** — UI dựng sẵn theo hướng per-domain, nhưng payload backend giữ nguyên (`tools.enabled` cấp agent) |
| 2 | 3 kỹ năng chung (tra tài liệu · ghi nhận khách · chuyển người thật) | Ở **tab Cấu hình chung** của màn Agent |
| 3 | Bố cục màn Agent | **Một màn duy nhất**, form + tabs: Cấu hình chung · mỗi lĩnh vực một tab |
| 4 | Bước xem trước | **Gộp vào dialog Lưu**: bấm «Lưu và áp dụng» → dialog xác nhận chứa bản render + trường sẽ đổi → xác nhận mới phát. Giữ lời hứa AG_01 «thấy trước khi phát» trong một bước |
| 5 | Thử agent lấy khoá từ đâu | **Tên khoá bắt buộc khi tạo** + panel thử **chọn khoá theo tên**; chat đi qua endpoint backend mới (đợt này MSW fake) |
| 6 | Nhãn màn khoá API | **"API Keys"** — bỏ "Tích hợp &" vì phần tích hợp/webhook chưa có gì |

## 3. Thiết kế

### 3.1 Sidebar (nav)

- `features/agent/nav.ts`: label `{ vi: 'Agent', en: 'Agent' }` (bỏ "& Kênh").
- `features/platform/nav.ts`: label `{ vi: 'API Keys', en: 'API keys' }`.
- Nhóm **Kiến thức** giữ nguyên — sau redesign nó thuần dữ liệu/knowledge, đúng vai.
- Không thêm/bớt màn nào ⇒ `screens.ts` chỉ sửa `note` của màn `api`. Giữ
  `mvp: 'partial'`: nhãn mới không còn hứa phần tích hợp, nhưng panel Thử agent
  chờ endpoint backend — note mới ghi đúng lý do đó.

### 3.2 Màn Agent — form + tabs

```
┌─ Header: Bản nháp · chip trạng thái agent · «khách đang dùng vN» · [Lưu và áp dụng]
├─ Tabs:  [ Cấu hình chung ] [ Bất động sản ] [ Tài chính 🔒 ]
│
│  Tab «Cấu hình chung»
│    · Danh tính  (tên agent · thương hiệu · tự xưng · gọi khách · lời chào, câu mẫu)
│    · Giọng điệu (giọng điệu · độ dài trả lời)
│    · Phạm vi    (làm gì · không làm gì · câu từ chối · phòng ban chuyển tiếp)
│    · Kỹ năng chung (3 toggle: kb_search · update_customer · escalate)
│    · Rào chắn  (6 dòng, chỉ đọc — giữ nguyên nội dung và luật «không tắt được»)
│
│  Tab «Bất động sản»
│    · Kỹ năng lĩnh vực (9 toggle, giữ nguyên cảnh báo phụ thuộc + cảnh báo tắt hết)
│    · Khối knowledge: tóm tắt dữ liệu lĩnh vực + link sang màn /projects và /kb
│
│  Tab «Tài chính»: khoá — «Lĩnh vực chưa kích hoạt» (không render form)
└─
```

Tab «Tài chính» **khoá cứng** đợt này (vertical #2 đang hoãn) — hiện diện để nói
khuôn per-domain, không có công tắc nào bật nó từ FE.

**Luồng lưu.** Một nút «Lưu và áp dụng» duy nhất ở header — luôn bấm được (không
còn khoá theo bước xem trước; dialog đảm nhận việc «thấy trước khi phát»). Khi
`truongDaDoi` rỗng, dialog nói «Không có thay đổi so với bản đang chạy»:

1. Bấm nút → mở dialog xác nhận; dialog gọi `POST /config/preview` (API xem trước
   hiện có) ngay khi mở.
2. Dialog hiện: bản render đọc được (`tenAgent · thuongHieu · giongDieu · doDai ·
   cauTuChoi · phongBan · kyNang`) + danh sách `truongDaDoi` + câu «Khách đang
   trong cuộc hội thoại vẫn dùng bản cũ tới khi kết thúc» (BR10 của AG_01).
3. Preview lỗi (422) → dialog hiện khối lỗi «Chưa áp dụng được — không có gì thay
   đổi» (ER_04), không có nút xác nhận.
4. Bấm «Xác nhận» → `PUT /config/draft` + `POST /config/publish` (đúng chuỗi
   `mApDung` hiện tại). Thành công → đóng dialog, header hiện «Đã áp dụng vN».
5. Sửa form khi dialog đã đóng ⇒ trạng thái «Đã áp dụng vN» tắt (giữ luật hiện
   tại: không nói bản đang gõ đã ra khách).

**Chia 12 kỹ năng ra tab — quy tắc một chiều.** Hằng số mới trong
`features/agent/` (KHÔNG sửa `lib/tools.ts` — nó là bản sao hợp đồng backend, có
cổng parity canh):

```ts
/** 3 kỹ năng chung của agent — phần còn lại của MUOI_HAI_KY_NANG là kỹ năng lĩnh vực BĐS. */
const KY_NANG_CHUNG = ['kb_search', 'update_customer', 'escalate'] as const
```

Tab BĐS = `MUOI_HAI_KY_NANG` trừ `KY_NANG_CHUNG`. Kỹ năng mới backend thêm sau
này tự rơi vào tab BĐS (mặc định đúng cho vertical #1); muốn nó là kỹ năng chung
thì thêm tên vào `KY_NANG_CHUNG`. Lưu vẫn gộp về một mảng `tools.enabled`.

**Trạng thái giữa các tab.** Cả 3 tab đọc/ghi **cùng một** `form: ConfigPayload`
(state ở component cha) — chuyển tab không mất sửa đổi, «Lưu và áp dụng» phát
trọn bản nháp bất kể đang đứng tab nào. Hàm `chuanHoa()` (đỡ bản nháp schema cũ)
và cảnh báo `nhapSchemaCu` giữ nguyên, đặt ở tab Cấu hình chung cạnh hai ô xưng hô.

**Bỏ khỏi màn này:** panel «Thử ngay» (sang màn API Keys) và cột phải sticky —
màn mới một cột, form full-width, các thẻ xếp dọc trong tab.

### 3.3 Màn API Keys — thêm panel Thử agent

- **Tên khoá bắt buộc:** `TaoKhoaDialog` validate nhãn không rỗng trước khi gọi
  tạo; ô nhãn đánh dấu bắt buộc. (Chỉ FE — backend đã nhận `label` sẵn.)
- **Panel Thử agent** (panel nền tối, bê phong cách từ AgentStudio hiện tại):
  - Dropdown **chọn khoá** — liệt kê khoá đang hiệu lực theo tên.
  - Khung chat tối giản: danh sách tin nhắn trong bộ nhớ (mất khi rời màn), ô
    nhập, nút gửi. Không lưu lịch sử.
  - **Gate hai điều kiện**, mỗi điều kiện một câu giải thích riêng khi thiếu:
    - Chưa có khoá hiệu lực → «Tạo khoá API trước rồi mới thử được agent.»
    - Agent chưa `san_sang` → «Agent chưa sẵn sàng để thử.» (4 trạng thái suy từ
      nhịp tim — HT01 §2.5)
- **Trạng thái agent đi xuyên module:** màn này thuộc `features/platform`, trạng
  thái agent thuộc `features/agent` ⇒ thêm `features/agent/contracts.ts` export
  hàm đọc trạng thái (`docTrangThai` + type `TrangThaiAgent`). Đúng luật ranh
  giới: module khác chỉ import `contracts`.
- **Hợp đồng endpoint thử (FE định, MSW fake, backend làm sau):**

  ```
  POST /api/v1/agent/try   { keyId: string, message: string }
  → 200 { reply: string }
  → 409 khi agent không san_sang · 404 khi khoá không còn hiệu lực
  ```

  MSW trả lời giả để màn chạy được ở dev. Với backend thật chưa có endpoint
  (request trả 404/501), panel hiện «Chức năng thử chưa đấu nối» — không giả vờ
  chat được.

### 3.4 Không đổi

- Hợp đồng backend hiện có: `contracts/tools.json` · `contracts/actions.json` ·
  chuỗi draft/preview/publish · payload `ConfigPayload`.
- `lib/tools.ts` (bản sao có cổng parity) — không thêm trường.
- Màn dữ liệu BĐS (`/projects`, pform, uform), Tài liệu (`/kb`), Quản lý lĩnh vực
  (`/domains` — vẫn stub của M4), và mọi màn khác.
- Sáu rào chắn: nội dung, tính chỉ-đọc, chỗ cưỡng chế (backend) — giữ nguyên.

## 4. Tác động test & i18n

| Chỗ | Việc |
|---|---|
| `tests/agent-studio.test.tsx` | Sửa theo bố cục mới: tabs, một nút Lưu, dialog xác nhận thay nút Xem trước; luật «tên tool không lộ ra giao diện» giữ nguyên và phải vẫn xanh |
| Test màn api-keys (`khoa-dau-noi.test.tsx`) | Thêm case: nhãn rỗng không tạo được khoá; panel thử khoá/mở theo gate |
| Test mới cho panel Thử agent | Gate 2 điều kiện · gửi tin qua MSW · trạng thái «Chưa đấu nối» |
| `tests/nav-registry.test.ts` | Không đổi cấu trúc — chỉ chạy lại xác nhận nhãn mới |
| i18n | Nhãn nav mới (Agent · API Keys) + chuỗi mới của dialog, panel thử, tab |

Không thêm màn mới ⇒ không đụng quy trình «bốn việc» của `screens.ts`/nav-registry
(ngoài sửa nhãn và note).

## 5. Open questions — để lại cho backend, KHÔNG giải trong đợt này

1. **Tools per-domain thật sự:** payload đổi từ `tools.enabled: string[]` sang
   cấu trúc theo lĩnh vực. UI tab đã sẵn khuôn; khi backend đổi, chỉ tầng
   `features/agent/api.ts` map lại.
2. **Endpoint `/agent/try` và BR03:** backend đại diện gọi agent bằng khoá đã
   chọn (backend chỉ giữ hash khoá) phải thiết kế sao cho bài thử vẫn đi **đúng
   kênh khách hàng cuối dùng** — nếu đi đường tắt riêng thì bài thử không chứng
   minh gì (HT01 BR03). Phương án khả dĩ (ký lại bằng token nội bộ ngắn hạn, hay
   giữ bản mã hoá của khoá) do backend quyết.
3. **Trạng thái `dang_cap` lúc chưa có pod:** panel thử ở màn API Keys hiện tiến
   trình gì khi workspace mới cấp — theo bảng 4 trạng thái HT01 §2.5.
