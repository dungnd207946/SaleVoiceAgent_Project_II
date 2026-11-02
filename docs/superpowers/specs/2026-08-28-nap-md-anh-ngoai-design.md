# Nạp Markdown có ảnh ngoài — thiết kế

Ngày: 2026-08-28 · Ba repo: `odyssey-portal-backend`, `odyssey-agent`, `odyssey-portal-frontend`
Nhánh: `feat/kb-md-anh-ngoai` (cả ba, cắt từ `origin/develop`)

## 1. Vấn đề

Khách có sổ tay dạng Markdown, ảnh minh hoạ nằm trên S3 của họ:

```markdown
Ở màn đăng nhập, bấm **Quên mật khẩu**.

![Màn đăng nhập AINA](https://s3.khach.vn/hd/00-dang-nhap.png)
```

Hôm nay portal **từ chối** tệp `.md` ngay ở route tải lên. Kể cả nếu nhận, ba chỗ nữa sẽ
hỏng lặng: chunker cắt ảnh khỏi câu dẫn, URL đi thẳng vào vector làm nhiễu phép tìm, và
LLM phải **chép lại** URL khi trả lời — đo được 1/3 lượt chép sai (`127.0.0.1` →
`127.00.1`), ảnh vỡ, không lỗi nào phát ra.

Mục tiêu: tải một tệp `.md` lên, hỏi agent, và **thấy ảnh đúng chỗ, đúng thứ tự** trong
câu trả lời.

## 2. Quyết định đã chốt

Người yêu cầu chốt ngày 2026-08-28:

| Câu hỏi                                                     | Chốt                                                                                               |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Ảnh đi kèm (đường dẫn tương đối, zip, nhiều tệp) | **Không hỗ trợ.** Khách chỉ tải lên MỘT tệp md; ảnh trong đó là URL tuyệt đối |
| Ảnh gốc trỏ S3 khách                                      | **Tải về kho mình, viết lại link** (mirror), kèm thumb                                  |
| Chặn SSRF                                                    | **Không kiểm, làm sau** — xem §9                                                         |
| Phạm vi                                                      | Trọn đường, ba repo                                                                             |
| Phạm vi pipeline                                             | **Không riêng tab Tài liệu chung** — mọi đường text vào Qdrant                      |

⚠️ Hệ quả của lựa chọn mirror: tệp thử "link S3 khách" **không còn đo được** việc ảnh nằm
lại bên khách — nó trở thành phép thử rằng đường mirror với tới host ngoài. Vẫn có giá
trị, chỉ khác nghĩa. Ghi lại để người sau không đọc nhầm mục đích tệp thử.

## 3. Kiến trúc

Sơ đồ dưới vẽ đường `kb_files`; đường thứ hai (`documents.body`) khác ở hai đầu
nhưng dùng chung bước ★ — xem §3.1.

```
Tải .md  →  S3 (nguyên văn)  →  job kb_file_index
                                   │
                     extract ──────┤ nhánh md MỚI: decode utf-8, không bóc gì
                                   │
              ★ mirror ảnh ────────┤ tải từng URL → S3 mình → thumb → viết lại link
                                   │
                     chunk ────────┤ ảnh + chú thích + câu dẫn là MỘT khối
                                   │
                     nhúng ────────┤ chuỗi nhúng BỎ url, `text` giữ markdown đầy đủ
                                   │
                                Qdrant
```

Bước ★ là đơn vị mới duy nhất: `kb/clients/anh_ngoai.py`. Nhận một chuỗi Markdown, trả
chuỗi đã viết lại + danh sách ảnh đã mirror. Phần phân tích link là hàm thuần — test
được không cần Docker.

### 3.1 Bước mirror đặt ở đâu — và vì sao không đặt trong `index_kb_file`

Portal có **đúng hai** đường text vào Qdrant, cả hai trong `kb/service.py`:

| Điểm gọi        | Nguồn text                                        | Ai ghi                                                                                                     |
| ------------------ | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `service.py:330` | `kb_files`                                       | tab**Tài liệu chung**                                                                              |
| `service.py:117` | `documents.body` (`noi_dung_da_markdown=True`) | tab**Tài liệu dự án** — gõ tay ở `/pform` **và** cổng nạp API (`modules/ingest`) |
| ↳ cùng đường  | `projects.overview` / `amenities`              | form dự án                                                                                               |

Đặt mirror trong `index_kb_file` là chỉ phủ hàng đầu bảng. Nên nó là một phép biến đổi
trên `directive.text`, áp ở **cả hai** điểm gọi.

**Bất biến tự canh:** `RagClient.index` **ném** nếu `text` còn sót `![](http…)` không trỏ
kho mình. Một đường thứ ba viết sau này mà quên gọi mirror sẽ vỡ to tiếng ở dev/CI, thay
vì âm thầm nhúng URL của khách vào vector và phát link kho khách cho người dùng cuối.

**Idempotent theo cấu tạo:** sau lượt mirror đầu, `text` chứa URL của mình, nên lượt quét
sau không tìm thấy ảnh lạ và không tải lại gì. `documents.body` được nhúng lại **mỗi lần
sửa**, nên tính chất này là bắt buộc, không phải tiện tay.

**Không đụng** `media.index` (`service.py:194`) — đó là caption của hàng `media`, ảnh ở đó
vốn đã là ảnh của mình.

### 3.2 Khoá và đặt tên

```
gốc   tenants/<tenant>/kb/anh/<sha256-nội-dung-ảnh>.<ext>
thumb  ─ theo thumbnail.thumb_key() sẵn có
```

Băm theo **nội dung ảnh**, không theo URL nguồn và không theo tệp md: hai tài liệu dùng
chung một ảnh chỉ tốn một bản, và nạp lại cùng tệp không sinh rác. Tiền tố `tenants/<t>/`
giữ nguyên lệ cách ly của `core/storage.tien_to_tenant()` — với kho tệp thì tiền tố CHÍNH
LÀ cơ chế cách ly.

## 4. Portal backend — bảy thay đổi

| # | Chỗ                                            | Việc                                                                      |
| - | ----------------------------------------------- | -------------------------------------------------------------------------- |
| 1 | `kb/contracts.py::LOAI_HO_TRO`                | thêm`"md"`                                                              |
| 2 | `kb/clients/extract.py::DUOI_HO_TRO`          | thêm`"md"`; nhánh bóc = `data.decode("utf-8")`                      |
| 3 | `kb/clients/anh_ngoai.py` (**mới**)    | mirror + thumb + viết lại link                                           |
| 4 | `kb/service.py`                               | gọi mirror ở cả hai điểm dựng directive                              |
| 5 | `kb/clients/rag.py::RagClient.index`          | bất biến §3.1;`_text_de_nhung` nhúng bản đã bỏ URL               |
| 6 | `kb/index/chunker.py::_tach_khoi`             | ảnh + chú thích + câu dẫn là một khối                              |
| 7 | `enrollment/tai_nguyen/gateway-protocol.json` | thêm`kb_search` vào `tool_results`; `MediaItem.image` thêm `so` |

**Thay đổi 5 làm `text` thôi bằng chuỗi đã nhúng**, mà `docs/contracts/payload-qdrant.md`
§3 đang khai `text` = «Nội dung đã nhúng». Sửa câu đó **cùng commit** — không thì người
sau đọc hợp đồng sẽ tin sai về nội dung vector.

**Thông điệp lỗi:** `.md` rỗng hiện rơi vào `THONG_DIEP_KHONG_CO_CHU` («không có lớp
chữ»). Câu đó nói về PDF scan và vô nghĩa với Markdown — cần thông điệp riêng.

### 4.1 Đo được, không phỏng đoán

Hai thay đổi 5 và 6 có số đo từ bài thử local (`exp/extract`, 33 chunk, 10 câu hỏi):

| Thay đổi                       | Đo được                                                                      |
| -------------------------------- | -------------------------------------------------------------------------------- |
| Bỏ URL khỏi chuỗi nhúng      | ảnh mong đợi ở**hạng 1: 7/10 → 8/10**                                |
| Chunker giữ ảnh với câu dẫn | **2/33 chunk** đang mở đầu bằng ảnh, câu dẫn nằm ở chunk trước |

Mức lợi thật của việc bỏ URL **lớn hơn** con số trên: URL trong bài đo dài 67 ký tự, URL
S3 thật ~130 — nhiễu ở production gấp đôi.

## 5. Agent — bốn thay đổi

Đường ảnh tới client đi qua `items`, **không** qua `text`. Lý lẽ đã ghi sẵn trong
docstring `_dinh_kem`: nhét link vào text nghĩa là LLM phải chép lại, mà chép sai là
chuyện sẽ xảy ra.

| # | Chỗ                                           | Việc                                                                                   |
| - | ---------------------------------------------- | --------------------------------------------------------------------------------------- |
| 1 | `rag/kb_service_adapter.py::_format_kb_hits` | thay`![alt](url)` → `[ảnh N — alt]`                                              |
| 2 | `rag/kb_service_adapter.py::_dinh_kem`       | ảnh trong`text` → item `kind:"image"` kèm `so` + `thumb`                     |
| 3 | sổ số ảnh                                   | sống ở`state.scratchpad` (đã có cơ chế, `recent_projects` dùng cùng kiểu) |
| 4 | prompt                                         | thêm luật nhắc số                                                                   |

### 5.1 Số ảnh đánh theo CẢ CUỘC, không theo lượt

Đo 2026-08-28 trên bản thử: đánh số lại mỗi lượt thì **2/3 kịch bản** có `ảnh 1` ở lượt
sau là một tấm khác `ảnh 1` ở lượt trước, và câu hỏi ngược *"ảnh lúc nãy là màn hình
nào"* bị trả lời bằng *"Bạn đang hỏi về ảnh nào?"*.

Sổ theo phiên (`url → số`) sửa cả hai: ảnh gặp lại giữ số cũ, ảnh mới lấy số kế tiếp.
Sau khi vá, đo lại: **0** trường hợp một số trỏ hai ảnh, câu hỏi ngược tra được.

Khối nhắc đi vào **cuối ngữ cảnh tool** (`kb_search` trả về), không phải system prompt —
chỗ đó nằm gọn trong một tệp thay vì mở một seam mới sang `runner.build_system_prompt`.
Tác dụng đo được không phụ thuộc nó nằm đâu, nó phụ thuộc ĐỘ DÀI.

⚠️ **Sổ nhắc phải chặn ở 6 mục gần nhất.** Thả tự do tới 20 mục thì tỉ lệ nhắc
ảnh của chính lượt đang trả lời **tụt còn 2/3** (sổ trống: 3/3, lặp 3 lần) — danh sách
dài kéo mô hình khỏi tài liệu. Chặn ở 6 đưa lại 3/3, và cũng chặn prompt phình theo độ
dài hội thoại. Chọn phần đuôi vì *"ảnh lúc nãy"* luôn là chuyện gần.

### 5.2 Cờ `kb_search_attach_source_files` giữ mặc định `False`

Cờ này đang `False`, nên `_dinh_kem` **chưa từng chạy ở production** — đó là lý do
`gateway-protocol.json` khai «ba kind agent thật sự phát» và không có `file`.

Giữ `False`, bật bằng env ở deployment thử. Đổi default là bật `items` cho **mọi** tenant,
gồm cả tệp PDF nguồn mà hôm nay chưa ai muốn hiện.

## 6. Frontend — bốn thay đổi

| Chỗ                                                | Việc                                                         |
| --------------------------------------------------- | ------------------------------------------------------------- |
| `features/kb/nav.ts:27`                           | nhãn →**"Tài liệu chung"** (`en: "General docs"`) |
| `features/ops/components/TheKienThuc.tsx:108`     | nhãn thẻ Dashboard, cùng chữ                              |
| `features/platform/chatGateway.ts`                | `MedItemAnh` thêm `so?: number`                          |
| `features/platform/components/ThuAgentScreen.tsx` | `TheMedia` in "Ảnh N" lên từng ô                        |

**Giữ nguyên khoá hợp đồng `taiLieuTraCuu`** trong `overview.kienThuc` — đổi khoá là đổi
một API đang chạy để đổi lấy lợi ích bằng không.

⚠️ `chuanHoaMedia` dựng lại từng item bằng **danh sách trường cứng** và bỏ mọi trường lạ.
Không khai `so` ở đó thì số bị nuốt im lặng — không lỗi, không cảnh báo.

⚠️ Portal **không render markdown**: bong bóng là `{tin.noiDung}` trần, và media là card
280px **dưới** cả tin nhắn. Nên cách chèn ảnh đúng chỗ dựng ở bản thử **không dùng lại
được** ở đây; tối thiểu phải in số lên từng ô, nếu không "(xem ảnh 4)" trỏ vào một lưới
không đánh số.

## 7. Lỗi và trần

Ảnh 404 / timeout / không phải ảnh ⇒ **giữ URL gốc, ghi cảnh báo, KHÔNG làm hỏng cả
tệp** — đúng lệ `_thumb_neu_thieu` đã ghi («thumbnail là tối ưu hiển thị»). Một tài liệu
27 ảnh mà hỏng 1 vẫn phải nạp được; đánh dấu cả tệp `loi` vì một ảnh chết là bắt người
dùng sửa thứ họ không gây ra.

Cảnh báo ghi ở `log.warning` **và** trong `JobResult.message` của job nạp. ⚠️ Đường
`documents.body` không có chỗ nào bày lỗi mức-từng-ảnh cho người dùng, nên ở đó cảnh báo
chỉ tới người trực. Giới hạn có ý thức, không phải sót.

Trần: **100 ảnh mỗi tệp · 10 MB mỗi ảnh · timeout 15 giây · chỉ nhận `Content-Type: image/*`**. URL trùng tải một lần (tính theo URL đã chuẩn hoá, trước khi tải).

Vượt trần số ảnh: mirror 100 ảnh **đầu theo thứ tự xuất hiện trong văn bản**, phần còn
lại giữ URL gốc + một dòng cảnh báo. Không từ chối cả tệp — cùng lý lẽ trên.

## 8. Kiểm thử

| Tầng                  | Bài                                                                                                                                              |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `anh_ngoai` (thuần) | tìm đúng mọi`![](url)`; bỏ qua link không phải ảnh; URL trùng gom một; viết lại đúng vị trí; text không ảnh trả nguyên văn |
| `anh_ngoai` (kho)    | tải → đẩy S3 → thumb; ảnh 404 giữ URL gốc; vượt trần; content-type sai bị từ chối                                                   |
| `RagClient.index`    | ném khi text còn URL ảnh lạ —**bài quan trọng nhất**, nó là cổng của §3.1                                                      |
| `chunker`            | ảnh không rời câu dẫn                                                                                                                        |
| `extract`            | `.md` bóc ra nguyên văn; md rỗng ra thông điệp riêng                                                                                    |
| agent                  | mốc thay đúng chỗ; sổ giữ số qua lượt; sổ chặn 6 mục; items có`so`                                                                 |
| FE                     | `chuanHoaMedia` giữ `so`                                                                                                                     |

Đầu–cuối: tải `hdsd-s3.md` lên tab Tài liệu chung → hỏi *"đổi mật khẩu thế nào"* → câu
trả lời nhắc "(xem ảnh N)" và đúng tấm đó tới client.

## 9. Rủi ro có tên: SSRF, cố ý chưa vá

Portal sẽ **tự gọi HTTP tới URL do bên ngoài cung cấp**. Máy chủ portal đứng trong mạng
nội bộ, nên một dòng markdown như

```markdown
![x](http://169.254.169.254/latest/meta-data/iam/security-credentials/)
```

khiến portal tải khoá IAM về, lưu vào S3 như một "tấm ảnh", rồi phát lại qua URL công
khai. Cùng cách đó đọc được `http://localhost:8100/…` và mọi dịch vụ nội bộ.

**Phạm vi rộng hơn "người bấm nút tải tệp":** vì mirror áp cả ở `documents.body`, một hệ
thống CRM bên khách đẩy payload qua cổng nạp API cũng khiến portal đi tải URL.

**Quyết định:** người yêu cầu chốt 2026-08-28 là **không kiểm, làm sau**.

**Cách vá khi làm:** phân giải DNS trước khi tải, từ chối nếu IP thuộc loopback /
link-local / dải riêng (`127/8`, `169.254/16`, `10/8`, `172.16/12`, `192.168/16`, `::1`,
`fc00::/7`); không đi theo redirect ra các dải đó; chỉ nhận scheme `http`/`https`. Khoảng
30 dòng, không thêm bảng, không thêm màn cấu hình.

Ghi ở đây để nó là **nợ có chủ ý**, không phải sơ suất — cùng lệ repo đã làm với
`agent_demo`.

## 10. Tệp thử

`exp/extract/out/hdsd-s3.md` đã có sẵn: sổ tay CTV, 27 ảnh, link tuyệt đối. Dựng hai bản:

1. trỏ MinIO dev — chạy được ngay trên máy lập trình viên;
2. trỏ một host ngoài — chứng minh đường mirror với tới Internet thật.

## 11. Ngoài phạm vi

- Chặn SSRF (§9).
- Ảnh đi kèm dạng zip / nhiều tệp.
- App AINA trên điện thoại: chưa rõ có render `items` của `kb_search` không — không đọc
  được mã ở đây.
- Kênh voice: *"xem ảnh 1"* đọc lên vẫn tự nhiên nhưng vô nghĩa; prompt voice nên tắt
  luật nhắc ảnh. Chưa làm.
- Semantic cache: lượt replay gọi `on_tool_done` bằng bản **đã strip**, nên cache hit
  không bao giờ kèm `items`. Lỗi **có sẵn** (`send_media` cũng dính), đang tắt mặc định.
