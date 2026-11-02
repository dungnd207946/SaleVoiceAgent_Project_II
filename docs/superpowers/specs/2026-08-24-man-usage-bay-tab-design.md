# Màn `/usage` — bảy tab lượng dùng theo ngày

Ngày: 2026-08-24 · Bản vẽ đã duyệt: `public/demo-usage.html` (vòng 6)
Repo liên quan: `odyssey-portal-frontend` (màn) + `odyssey-portal-backend` (1 endpoint mới, 1 endpoint mở rộng)

---

## 0. Bối cảnh, và cái gì KHÔNG phải phạm vi

`/usage` và `/billing` là **hai màn hai câu hỏi**, và ranh giới đó đã đảo chỗ một lần
nên phải nói rõ:

|            | `/billing` (đã có, đang chạy)                 | `/usage` (spec này)                         |
| ---------- | --------------------------------------------- | ------------------------------------------- |
| Câu hỏi    | **Tốn bao nhiêu TIỀN**                        | **Dùng bao nhiêu LƯỢNG**                    |
| Đơn vị     | `₫` — cộng chéo component được                | token · giây · ký tự — **không** cộng chéo  |
| Nguồn      | `billing.rated_usage` (`amount`)              | `billing.usage_events` (số đo thô)          |
| Trạng thái | `mvp: 'full'`, giữ NGUYÊN, spec này không sửa | `mvp: 'deferred'` → phải đổi thành `'full'` |

**Không có một con số tiền nào trên `/usage`.** Không `₫`, không phần trăm chi phí,
không dải cảnh báo `thieu_gia`. Tiền là màn kia. Đây không phải để cho gọn — nó là
điều kiện để `/usage` được phép hiển thị các số đo mà `/billing` không được phép
cộng lại.

---

## 1. Thiết kế usage CŨ — bỏ cái gì, và vì sao (đọc trước khi tham khảo code cũ)

Màn số liệu cũ (`features/billing/components/UsageScreen.tsx` và các component của
nó) **nay thuộc `/billing`** sau lần đổi chỗ 2026-08-24. Nó vẫn đúng cho `/billing`.
Nhưng **đừng lấy nó làm khuôn cho `/usage`** — sáu thứ dưới đây đã bị bỏ có chủ ý qua
sáu vòng thiết kế, và người dùng đã chốt bỏ. Dựng lại là đi ngược quyết định:

1. **Khuôn «bốn mục đánh số»** (`TieuDeMuc` với ô số ①②③④ + thẻ rời trôi trên nền
   trang). `/usage` còn **hai thẻ**, không ô số nào. Tiêu đề bảng nằm TRONG thẻ.
2. **Dải KPI ngang 4–5 ô** (`TheKpi`). Thay bằng **rail dọc bấm được** — mục rail vừa
   là con số tổng vừa là bộ chọn biểu đồ. Không còn khối nào chỉ để bày số.
3. **Small multiples / bảy khung nhỏ** và **biểu đồ gộp nhiều đường**. Một tab một
   đường, không ngoại lệ (§4.2).
4. **Bảng «Cường độ theo service»** (TB/ngày · đỉnh · ngày hoạt động · TB/phiên ·
   event) — bỏ hẳn. Đỉnh và số ngày hoạt động chuyển thành dòng phụ của mục rail.
5. **Mọi dòng chữ giải thích dưới tiêu đề** (`.tdmuc p`, khối `.ghi-luoi`, phụ đề
   nhóm). Màn này không có một câu giảng nghĩa nào. Cái gì là **bẫy làm sai số** thì
   nằm ở `title` (tooltip trình duyệt), không nằm trên màn.
6. **`DaiCanhBao`** (dải cảnh báo `thieu_gia` → link `/pricing`) — cảnh báo về ĐỊNH
   GIÁ, thuộc `/billing`.

**Được phép dùng lại nguyên trạng** (đừng viết lại):
`features/billing/dinh-dang.ts` (`tien`/`token`/`giay`, luật hậu tố viết liền số),
`components/ui/Bang.tsx` (`TheBang` · `TD_SO` · `HANG_NUT` · `NhomTab`),
`features/billing/components/ChiTietPhien.tsx` (slide-over một phiên — dùng chung),
`features/billing/components/lop.ts` (`SO_LON`).

---

## 2. Giao diện chốt

```
[ Tháng này | Tháng trước | 7 ngày | 30 ngày ]                    01/08 – 21/08/2026

┌─ THẺ 1: BẢNG ĐIỀU KHIỂN ─────────────────────────────────────────────────────┐
│ RAIL 274px (7 mục)      │  Token theo ngày   đơn vị token ⓝ                  │
│ ● TOKEN                 │                                                    │
│   1.37M                 │        ╱╲      ╱╲          ╱╲                       │
│   in 1.07M out 152k …   │   ╲   ╱  ╲    ╱  ╲    ╲   ╱  ╲                     │
│ ─────────────────────── │    ╲ ╱    ╲  ╱    ╲    ╲ ╱    ╲                    │
│ ● STT   38m 57s         │     V      ○─╯      ╲   V       (vùng tô gradient) │
│   đỉnh 2m 59s 19/21…    │  0s ─────────────────────────────────────────────   │
│ ● TTS · VAD · Thời gian │     01/08   05/08   09/08   13/08   17/08   21/08   │
│   gọi · Embed · Xác     │                                                    │
│   thực giọng            │                                                    │
└─────────────────────────┴────────────────────────────────────────────────────┘

┌─ THẺ 2: Lượt dùng chi tiết          Gộp theo [Khoá|Người tạo|Phiên] ─────────┐
│ bảng + phân trang (chiều «Phiên»)                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Bảy tab, thứ tự CHỐT (người dùng chốt, đừng sắp lại theo độ lớn)

| #   | Tab            | `component` trong DB | Số đo hiển thị | Số dẫn =                      |
| --- | -------------- | -------------------- | -------------- | ----------------------------- |
| 1   | Token          | `llm`                | token          | `input + output + cache_read` |
| 2   | STT            | `stt`                | giây           | `sum(audio_sec)`              |
| 3   | TTS            | `tts`                | **ký tự**      | `sum(text_units)`             |
| 4   | VAD            | `vad`                | giây           | `sum(audio_sec)`              |
| 5   | Thời gian gọi  | `call`               | giây           | `sum(audio_sec)`              |
| 6   | Embed          | `embed`              | **ký tự**      | `sum(text_units)`             |
| 7   | Xác thực giọng | `speaker_verify`     | giây           | `sum(audio_sec)`              |

⚠️ **`speaker_verify`, không phải `sv`.** Bản demo viết `sv` cho ngắn; mã thật trong
`billing.usage_events.component` là `speaker_verify`. Bảng ánh xạ mã→nhãn phải là
**một chỗ duy nhất** ở FE (đề xuất: mở rộng `features/billing/component-hien.ts`,
tệp đã tồn tại và đang giữ nhãn + màu dùng chung cho `/billing`).

### 2.2 Mỗi mục rail chở gì

- **nhãn** (uppercase 10.5px) + **chấm gradient** định danh
- **số dẫn** (mono 23px, sắc `--c-<component>`)
- **dòng phụ, CHỈ chở số**: tab Token → `in … · out … · cache …`; sáu tab còn lại →
  `đỉnh <giá trị> · <n>/<N> ngày`. Không mục nào chở một câu giải thích.
- trạng thái đang chọn: nền `acs` + vạch accent 3px bên trái (KHÔNG in đậm chữ — con
  số vốn đã đậm, thêm một nấc nữa thì hai mục đọc ra hai kiểu chữ).

### 2.3 Biểu đồ — luật hình, đã chốt qua ba vòng

- **Line chart**, nét gradient NGANG (`--a-*` → `--b-*`, cùng hệ màu), 2.4px,
  `vector-effect="non-scaling-stroke"`.
- **Kiểu nét: `KIEU_NET = 'thang'`** — nối thẳng điểm-tới-điểm + chấm rỗng mỗi ngày.
  Nét nói đúng thứ có thật: `N` số đo, giữa hai ngày không có dữ liệu nào. Hai lựa
  chọn khác giữ trong code kèm lý do (`'bac'` bậc thang căn giữa ngày — đúng nhất về
  hợp đồng vì `theo_ngay` là XÔ theo ngày; `'muot'` monotone cubic — đẹp nhưng **vẽ ra
  dữ liệu không có**). Đổi kiểu = sửa một hằng.
- **Mỗi tab một đường ⇒ luôn có vùng tô gradient dọc + quầng sáng.**
- **Thang dọc riêng mỗi tab**, theo đỉnh của CHÍNH nó. Mốc «tròn số» theo đơn vị —
  thời gian có bậc riêng (`15s · 1m · 5m · 30m · 1h`), KHÔNG chia đều ra `1m 47s`.
  Mật độ mốc theo chiều cao đo được (~1 mốc/95px, kẹp 3–6).
- **Ngày = 0**: đường chạm đáy + **vòng tròn rỗng** — nói «đã ĐO và bằng 0», khác
  «thiếu dữ liệu» (không vẽ gì).
- **Mật độ nhãn ngày tự chọn** theo bề rộng đo được (~1 nhãn/74px), luôn giữ ngày đầu
  và ngày cuối, hai đầu mang cả tháng (`dd/MM`). **Đừng chốt cứng mốc 1·5·10·15·20** —
  `/billing` đã làm thế và phải sửa: kỳ «7 ngày» còn hai nhãn, kỳ «30 ngày» bắc qua
  hai tháng thì mốc lặp lại.
- **Tooltip**: `<ngày> · <n> phiên` + một dòng `<tên tab> <giá trị>`. Gắn ở `<body>`,
  `position: fixed` — thẻ có `overflow:hidden` (bo góc) và sẽ cắt nó.
- **KHÔNG có chip legend.** Một tab một đường ⇒ chip là công tắc mà bấm vào thì mất
  nội dung biểu đồ, còn tổng thì mục rail đã chở.

### 2.4 Bảng «Lượt dùng chi tiết»

Ba chiều gộp qua `NhomTab`, tiêu đề + tab nằm TRONG thẻ.

| Chiều     | Cột                                                                                                                           |
| --------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Khoá      | Khoá (nhãn + `key_prefix` + pill «đã thu hồi») · Người tạo · Phiên · In · Out · Cache read · Giây gọi · Event · **hàng Tổng** |
| Người tạo | Người tạo (tên + email) · Khoá · Phiên · In · Out · Cache read · Giây gọi · Event · **hàng Tổng**                             |
| Phiên     | Phiên (`session_id`) · Khách · Kênh (chip Chat/Voice) · Bắt đầu · Turn · In · Out · Giây gọi · **phân trang keyset**          |

- Hàng **«Chưa phân loại (không có khoá)»** luôn ở cuối, và bất biến của nó là: mọi
  cột cộng đúng bằng hàng Tổng. Ẩn hàng đó đi là tổng dòng < tổng hiển thị.
- Bấm một hàng ở chiều «Phiên» → mở slide-over `ChiTietPhien` qua search param
  `?phien=<session_id>` (dùng lại nguyên component + route param đã có ở `/billing`).
- `exact = false` → dấu `!` cạnh cột In kèm `title` «đo THIẾU token, không phải 0».

### 2.5 Search param của route

`/usage?tab=<khoa>&phien=<session_id>` — cùng khuôn `/billing`:

⚠️ **`validateSearch` phải LUÔN trả đủ MỌI khoá nó khai**, kể cả khoá đang mang giá
trị mặc định. Router **TRỘN** kết quả validate lên search thô chứ không THAY nó, nên
bỏ một khoá ra khỏi object trả về (`{}` cho mặc định) để giá trị lạ trên URL lọt
thẳng xuống component nguyên văn — `?tab=xyz` sẽ làm **không tab nào mở**. Bẫy này đã
sập thật ở `/projects` (CLAUDE.md, Change Log 2026-08-14) và ở `/billing`.

---

## 3. Bản đồ dữ liệu — mỗi con số trên màn ← nguồn nào

Bảng nguồn: **`billing.usage_events`** (số đo thô, một hàng mỗi lượt gọi) và
`tenant_data.conversations` (khách · SĐT · `agent_key_id`). Cột có sẵn:

```
usage_events: tenant_id · session_id · channel · seq · turn_idx · component · purpose
              provider · model · input_tokens · output_tokens · cache_write_tokens
              cache_read_tokens · audio_sec · wall_ms · units · text_units · exact
              occurred_at
```

| Chỗ trên màn                           | Nguồn                                                                                                 | Trạng thái                      |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------- | ------------------------------- |
| Biểu đồ: chuỗi N ngày mỗi tab          | `GET /billing/usage-by-day` (MỚI)                                                                     | ❌ **PHẢI LÀM — §4.1**          |
| Tooltip: `<n> phiên` của một ngày      | `usage-by-day` → `theo_ngay[].so_phien`                                                               | ❌ **PHẢI LÀM — §4.1**          |
| Rail: tổng kỳ mỗi tab                  | **cộng chuỗi ngày** của `usage-by-day` — tổng theo ngày = tổng cả kỳ                                  | dẫn xuất ở FE                   |
| Rail: `in / out / cache` của Token     | cùng chuỗi, hàng `component='llm'`, cộng ba cột token qua các ngày                                    | dẫn xuất ở FE                   |
| Rail: **đỉnh** + **số ngày hoạt động** | cùng chuỗi ngày (`max`, và `count(v > 0)`)                                                            | dẫn xuất ở FE                   |
| Khoảng ngày của kỳ                     | tham số `tu`/`den` (`_khoang()` ở router)                                                             | ✅                              |
| Bảng, chiều **Khoá**                   | `GET /billing/by-key` → `DongKeyOut`                                                                  | ✅ **CÓ ĐỦ 8/8 cột**            |
| Bảng, chiều **Phiên**                  | `GET /billing/sessions` → `PhienUsageOut`                                                             | ✅ **CÓ ĐỦ 8/8 cột**            |
| Bảng, chiều **Người tạo**              | `GET /billing/by-owner` → `DongOwnerOut` chỉ có `user_id · ten · email · so_key · so_phien · chi_phi` | ⚠️ **THIẾU 5 cột lượng — §4.2** |
| Slide-over chi tiết phiên              | `GET /billing/sessions/{id}` → `ChiTietPhienOut` + `EventOut`                                         | ✅                              |

⚠️ **`/usage` KHÔNG gọi `GET /billing/breakdown`.** `theo_component[]` của endpoint đó
đã có sẵn đúng bộ số đo tổng kỳ, nhưng lấy tổng từ đó là **hai nguồn cho một con số**:
tổng cả kỳ và tổng của chuỗi ngày phải bằng nhau, mà hai câu SQL khác nhau (một gộp
theo component, một gộp theo ngày+component) thì ngày nào lệch sẽ lệch ÂM THẦM — rail
nói một số, biểu đồ vẽ một số khác, không cổng nào đỏ. Cộng chuỗi ngày ở FE thì hai con
số **không thể** lệch nhau.

⚠️ **`modules/billing` trả `snake_case`**, khác `modules/ops` (camelCase). Copy pattern
`res.chiPhiTong` từ màn ops sang đây đọc ra `undefined` → `NaN` → UI hiện «—», mà
`tsc` xanh và test xanh. **Không có gì đỏ.** Kiểu FE phải khai đúng `snake_case`.

---

## 4. Ba khoảng trống, và đề xuất

### 4.1 THIẾU: số đo theo NGÀY theo COMPONENT (chặn cả biểu đồ + hai dòng phụ rail)

`GET /billing/breakdown` đã trả `theo_ngay[]`, nhưng mỗi ngày chỉ mang **`chi_phi`**
và `phan[] = {component, chi_phi}` — **tiền, không có số đo nào**. Không endpoint nào
trả token/giây/ký tự theo ngày. Đây là toàn bộ nội dung của thẻ 1.

**CHỐT: endpoint MỚI `GET /api/v1/billing/usage-by-day`** (không mở rộng
`breakdown`: `breakdown` là câu hỏi TIỀN, phục vụ `/billing`, và nhồi số đo vào nó
làm mỗi lần mở `/billing` phải quét thêm cột mà nó không dùng).

```
GET /api/v1/billing/usage-by-day?tu=YYYY-MM-DD&den=YYYY-MM-DD
gác bằng  require('billing.read')          trả snake_case

{
  "theo_ngay": [
    { "ngay": "2026-08-01",
      "so_phien": 12,
      "phan": [
        { "component": "llm", "input_tokens": 41000, "output_tokens": 5800,
          "cache_read_tokens": 5300, "audio_sec": 0.0, "text_units": 0,
          "units": 118, "so_event": 118 },
        { "component": "call", "input_tokens": 0, …, "audio_sec": 612.4, … }
      ] }
  ]
}
```

SQL (bám đúng ba bất biến của `repo.theo_ngay()` đang chạy):

```sql
WITH ngay AS (
  SELECT generate_series($2::date, $3::date - 1, '1 day')::date AS ngay
), so AS (
  SELECT date_trunc('day', occurred_at)::date AS ngay, component,
         sum(input_tokens)::bigint      AS input_tokens,
         sum(output_tokens)::bigint     AS output_tokens,
         sum(cache_read_tokens)::bigint AS cache_read_tokens,
         sum(audio_sec)::float          AS audio_sec,
         sum(text_units)::bigint        AS text_units,
         sum(units)::bigint             AS units,
         count(*)::int                  AS so_event
    FROM billing.usage_events
   WHERE tenant_id = $1 AND occurred_at >= $2 AND occurred_at < $3
   GROUP BY 1, 2
), phien AS (
  SELECT date_trunc('day', occurred_at)::date AS ngay,
         count(DISTINCT session_id)::int AS so_phien
    FROM billing.usage_events
   WHERE tenant_id = $1 AND occurred_at >= $2 AND occurred_at < $3
   GROUP BY 1
)
SELECT n.ngay, COALESCE(p.so_phien, 0) AS so_phien, s.*
  FROM ngay n LEFT JOIN so s ON s.ngay = n.ngay
              LEFT JOIN phien p ON p.ngay = n.ngay
 ORDER BY n.ngay, s.component;
```

Ba bất biến, mỗi cái là một chỗ đã sai một lần ở chỗ khác:

1. **`generate_series` TRẢ ĐỦ MỌI NGÀY, kể cả ngày không có dữ liệu.** Trả chỉ ngày có
   dữ liệu thì FE nối thẳng hai điểm hai bên và **ngày nghỉ biến mất khỏi hình** —
   vòng tròn rỗng «đã đo và bằng 0» của §2.3 không có gì để vẽ.
2. **`date_trunc('day', occurred_at)` KHÔNG kèm `AT TIME ZONE`** — giống nguyên
   `repo.theo_ngay()`. Đổi múi giờ ở đây mà không đổi ở đó là hai biểu đồ của cùng
   một tenant lệch nhau một ngày ở hai màn, và không cổng nào bắt được.
3. **CHỈ đọc `usage_events`, KHÔNG `JOIN rated_usage`.** Một event LLM sinh tới **4
   hàng** `rated_usage` (4 metric), nên `JOIN` rồi `sum(input_tokens)` là **nhân bản
   số đo lên 4 lần**. `repo.py` đã có nguyên một docstring cảnh báo đúng chỗ này.
4. **`so_phien` dùng `count(DISTINCT session_id)` trên `usage_events`** — CÙNG định
   nghĩa với `TongQuanOut.so_phien` đang chạy. Đếm từ `conversations` sẽ ra con số
   khác (phiên không phát sinh usage) và tooltip không khớp bảng dưới.

FE: hook `useUsageTheoNgay(from, to)` + kiểu `UsageTheoNgay` trong
`features/billing/kieu.ts`. Một request cho cả bảy tab — **đổi tab KHÔNG gọi lại
API**, chỉ đổi chuỗi đang vẽ. `staleTime` theo lệ của module.

### 4.2 THIẾU: 5 cột lượng ở chiều «Người tạo»

`DongOwnerOut` chỉ có `so_key · so_phien · chi_phi`. Bảng cần thêm `input_tokens ·
output_tokens · cache_read_tokens · voice_sec · so_event` — đúng bộ mà `DongKeyOut`
đã có.

**CHỐT: mở rộng `DongOwnerOut` + `repo.theo_owner()`**, không làm ở FE. Gộp ở FE
nghĩa là tải trọn danh sách khoá rồi cộng theo `nguoi_tao` trong trình duyệt — sai
ngay khi bảng khoá có phân trang, và nó nhân đôi một phép gộp mà SQL làm đúng một
câu. `repo.theo_key()` đã có sẵn đúng phép cộng đó, chỉ cần `GROUP BY` theo owner.

⚠️ `voice_sec` **CHỈ đếm `component='call'`** (BE sửa ở `9d78d04`; đo được `386,38s`
khi cộng chéo mọi component vs `142,44s` thời lượng gọi thật). Cột mới phải dùng đúng
vị từ đó, đừng `sum(audio_sec)` trần.

### 4.3 Đơn vị TTS và Embed — ĐÃ SỬA BẢN VẼ (chốt: ký tự)

Bản demo vẽ **TTS theo giây** và **Embed theo token**. Cơ sở tính tiền trong DB
(`billing.pricing_basis` sau migration `0948`) nói khác:

| component            | metric                         | nghĩa                                                 |
| -------------------- | ------------------------------ | ----------------------------------------------------- |
| `tts`                | `text_units`                   | **ký tự ĐƯA VÀO** TTS (`units` nay = số clause synth) |
| `embed`              | `text_units`                   | **ký tự** đem embed (`units` nay = số lời gọi)        |
| `stt` (conversation) | `audio_sec` **+** `text_units` | hai vế ĐỘC LẬP, cộng thêm                             |

Và `test_doi_chieu_cong_thuc_agent.py` xác nhận công thức của bên agent không có vế
`audio_sec` nào cho `tts`. Nghĩa là **nếu vẽ TTS theo giây thì rất có thể vẽ một
đường phẳng bằng 0** — `audio_sec` của `tts` không phải thứ agent gửi.

→ **Đã chốt 2026-08-24: hiển thị KÝ TỰ.** `public/demo-usage.html` đã sửa theo (hai
chip đơn vị + hai số dẫn + `FMT.kytu`/`NHAN_DV.kytu`), và bảng `SV` của bản vẽ nay
mang một chú thích dẫn nguồn `pricing_basis` để lần sau không ai tự chọn lại đơn vị.

---

## 5. Câu hỏi cần chốt trước khi code

| #      | Câu hỏi                                                | Quyết định                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| ------ | ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Q1** | Đơn vị hiển thị của TTS và Embed                       | ✅ **CHỐT 2026-08-24: theo cơ sở tính tiền — KÝ TỰ.** Bản vẽ đã sửa hai chip đơn vị + hai số dẫn. Lý do: `text_units` là số đo agent thật sự gửi và là thứ tenant bị tính tiền theo; vẽ giây cho TTS thì ra đường phẳng 0                                                                                                                                                                                                                                                                |
| **Q2** | `usage-by-day` là endpoint mới hay mở rộng `breakdown` | ✅ **CHỐT 2026-08-24: endpoint MỚI.** `/usage` gọi đúng MỘT request và **không gọi `breakdown`** — nó tự cộng chuỗi ngày ra tổng kỳ/đỉnh/số ngày hoạt động. `/billing` + `breakdown` không đổi một dòng. Lý do quyết định không phải hiệu năng mà là chỗ ĐẶT LUẬT: hai payload tách nhau thì «`/usage` không hiện tiền · `/billing` không cộng số đo chéo component» nằm trong HỢP ĐỒNG; một payload hai chủ thì nó chỉ còn nằm trong một comment, và comment không đỏ khi ai đó vẽ nhầm |
| **Q3** | Chiều «Người tạo» của bảng                             | ✅ **CHỐT 2026-08-24: mở rộng `DongOwnerOut` + `repo.theo_owner()` ở BE** (thêm 5 cột lượng). KHÔNG gộp ở FE — sai ngay khi bảng khoá có phân trang                                                                                                                                                                                                                                                                                                                                      |
| **Q4** | Dòng «`<n>` phiên» trong tooltip                       | ✅ **CHỐT 2026-08-24: `so_phien` mỗi ngày đi cùng dữ liệu theo ngày**, dùng `count(DISTINCT session_id)` trên `usage_events` — CÙNG định nghĩa với `TongQuanOut.so_phien` nên tooltip khớp bảng dưới                                                                                                                                                                                                                                                                                     |

---

## 6. Kế hoạch thực thi

### 6.1 Backend (`odyssey-portal-backend`)

| #   | Việc                                                                                                            | Tệp                                  |
| --- | --------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| B1  | `repo.usage_theo_ngay(tenant, tu, den)` — SQL §4.1                                                              | `src/portal/modules/billing/repo.py` |
| B2  | `UsageNgayOut` · `PhanUsageNgayOut` · `UsageTheoNgayOut`                                                        | `.../billing/contracts.py`           |
| B3  | `GET /billing/usage-by-day`, gác `billing.read`, dùng `_khoang()` sẵn có                                        | `.../billing/router.py`              |
| B4  | Mở rộng `DongOwnerOut` + `repo.theo_owner()` (Q3)                                                               | `contracts.py` · `repo.py`           |
| B5  | Test: ngày rỗng vẫn có hàng · không nhân bản số đo LLM · `so_phien` khớp `summary` · `voice_sec` chỉ đếm `call` | `tests/modules/billing/`             |

### 6.2 Frontend (`odyssey-portal-frontend`)

| #   | Việc                                                                                                                                                         | Tệp                                            |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------- |
| F1  | `lib/screens.ts`: `usage` → `owner: 'M8'`, `mvp: 'full'`, xoá `note`                                                                                         | `src/lib/screens.ts`                           |
| F2  | Kiểu + hook `useUsageTheoNgay` (snake_case!). MỘT request cho cả màn — tổng kỳ · đỉnh · số ngày hoạt động DẪN XUẤT từ chuỗi ngày, KHÔNG gọi `breakdown` (§3) | `features/billing/kieu.ts` · `api.ts`          |
| F3  | Bảng mã→nhãn→đơn vị→màu của 7 component, MỘT chỗ                                                                                                             | `features/billing/component-hien.ts` (mở rộng) |
| F4  | `theme.css`: 7 hệ `--c-* / --a-* / --b-*`. Đo tương phản `--c-*` ≥ 4.5 trên `surface` — **hai bậc kia không chở chữ nào**                                    | `src/styles/theme.css`                         |
| F5  | `UsageRail.tsx` — 7 mục, `aria-pressed`, dòng phụ chỉ số                                                                                                     | `features/billing/components/`                 |
| F6  | `BieuDoLuongDung.tsx` — line chart; `ResizeObserver` đo CẢ HAI chiều, prop `co` làm seam test (jsdom trả `clientWidth = 0`)                                  | `features/billing/components/`                 |
| F7  | `BangLuotDungUsage.tsx` — 3 chiều gộp, bộ cột LƯỢNG, phân trang keyset                                                                                       | `features/billing/components/`                 |
| F8  | `UsageLuongDungScreen.tsx` — vỏ màn, nhận `tim`/`datTim` qua prop (component THUẦN, route chỉ là cầu nối)                                                    | `features/billing/components/`                 |
| F9  | `routes/_app/usage.tsx` — `validateSearch` trả ĐỦ mọi khoá (§2.5)                                                                                            | `src/routes/_app/usage.tsx`                    |
| F10 | Xuất qua `features/billing/contracts.ts` (mặt tiền) — route không import ruột                                                                                | `features/billing/contracts.ts`                |
| F11 | Fake MSW cho endpoint mới                                                                                                                                    | `features/billing/msw.ts`                      |

### 6.3 Cổng phải xanh

- `tests/nav-registry.test.ts` — `usage` rời danh sách `deferred` (bài «màn hoãn ngoài
  MVP» đang lấy `usage` làm ví dụ, phải đổi sang màn `deferred` khác)
- `tests/boot.test.tsx` — thêm dấu hiệu màn thật cho `usage` (một chuỗi chỉ hiện SAU
  khi dữ liệu về, KHÔNG phải nhãn nav «Usage» — `Topbar` render nhãn đó thành `<h1>`
  và panel cũng có đúng chữ ấy)
- `tests/vien-tran.test.ts` · `tests/o-chon.test.ts` — mọi `border` kèm token màu
- `make lint` (`eslint . && prettier --check src tests && tsc -b`) — nhớ `tsc -b`,
  **`--noEmit` là cổng rỗng ở repo này**
- Chạy test bằng Node 22, hoặc `NODE_OPTIONS="--no-experimental-webstorage"`

### 6.4 Bài test màn mới (`tests/usage-luong-dung.test.tsx`)

Boot qua router thật (`routeTree.gen`), fixture riêng, không dựa vào fake mặc định.

1. Bảy mục rail, đúng thứ tự, đúng số dẫn
2. Bấm mục rail → đổi tiêu đề + đơn vị biểu đồ, **KHÔNG gọi lại API** (đếm request)
3. `?tab=` lạ → rơi về tab đầu, không phải «không tab nào mở»
4. Ngày 0 → vòng tròn rỗng có mặt, và **chuỗi `NaN` không lọt vào DOM**
5. Tooltip: ngày + số phiên + đúng một dòng giá trị
6. Ba chiều gộp: đủ cột, hàng «Chưa phân loại» ở cuối, tổng cột = hàng Tổng
7. Bấm hàng phiên → `?phien=` + slide-over mở; Esc/× xoá param
8. `exact = false` → dấu `!` xuất hiện
9. `usage-by-day` lỗi ⇒ thẻ 1 báo lỗi kèm nút thử lại, **thẻ 2 vẫn render** (hai
   endpoint khác nhau, hỏng cái này không được kéo cái kia xuống)

---

## 7. Rủi ro đã biết

- **`text_units` = 0 với dữ liệu cũ.** Migration `0948` `ADD COLUMN … DEFAULT 0`, và
  event ghi trước đó không có ký tự nào. Tab TTS/Embed sẽ phẳng trên dữ liệu cũ — đó
  là **sự thật của dữ liệu**, không phải bug. Đừng "chữa" bằng cách suy ký tự từ
  `units`.
- ~~**`purpose='stream'` của STT tính theo `wall_ms`**, không theo `audio_sec`. Nếu
  tenant có luồng stream thì tab STT (đang vẽ `audio_sec`) không phản ánh phần đó.
  Cần thì tách theo `purpose` ở vòng sau — **đừng cộng `wall_ms` vào `audio_sec`**.~~
  → **ĐÃ ĐÓNG 2026-08-25.** «Vòng sau» đã tới: BE trả `wall_ms_stream` +
  `text_units_hoi_thoai` (lọc theo `purpose`), tab STT vẽ HAI đường —
  **Stream** = `wall_ms` của `purpose='stream'`, **Conversation** = `text_units`
  của `purpose='conversation'`. Vẫn KHÔNG cộng `wall_ms` vào `audio_sec`: hai
  chuỗi riêng, hai trục riêng.
  ⚠️ Việc chọn `audio_sec` ở bản đầu là **suy luận của người viết spec**, không
  có tài liệu nào chỉ định — `pricing_basis` khai cả hai và ghi «CHỌN MỘT».
  ⚠️ Hệ quả còn treo: `audio_sec` của `stt` nay không hiện ở đâu trên màn, mà
  theo bảng giá trên DB dev thì nó mới là vế THU TIỀN (`stt/conversation/
audio_sec` có `unit_price` 2,6/4,8/6,0 · mọi dòng `stt/stream/wall_ms` đều
  `unit_price = 0`, và `billing.purpose` ghi «stream … giá 0 vì STT thu theo
  giây»). `/usage` là màn LƯỢNG nên chấp nhận được — nhưng **đừng suy chi phí
  từ con số dẫn của tab STT**.
- **Fake MSW không phải nguồn sự thật về backend** và không có cổng parity nào canh
  `features/billing/msw.ts`. Một vòng thiết kế trước đã lấy hành vi fake làm sự thật
  rồi dựng cả một lý lẽ lên đó. Câu hỏi «backend làm gì» chỉ có một chỗ trả lời: code
  backend.
