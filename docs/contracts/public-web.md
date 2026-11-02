# Hợp đồng collection Qdrant `<tenant_id>_public_web` — bàn giao repo `odyssey-agent`

> **Đối tượng:** đội agent (`kb_search`), đội làm kênh Sale. Đọc trước khi thêm `public_web` vào lượt tìm.
> **Sở hữu:** gói `src/portal/modules/kb/web/` (container `crawl`/`crawl-worker`, portal backend). Đổi
> payload/id ở `compose.py`/`contracts.py` mà không sửa tài liệu này là để tài liệu nói dối.
> **Nguồn:** đọc trực tiếp từ code lúc viết tài liệu này (2026-09-30) — `contracts.py`, `compose.py`,
> `index.py`, `pipeline.py`. Copy tay sang repo `odyssey-agent`, không có job CI nào so hai bên.

Ai ghi: gói `kb/web`, chạy trong container `crawl-worker` (lịch theo tenant đọc từ
`tenant_data.kbweb_schedules`, job `kbweb_run`/`kbweb_project`). Ai đọc: agent qua `kb_search` sẵn có;
người dùng xem/chỉnh qua màn «Dữ liệu ngoài» của portal (`docs/contracts/kb-web.md`).

**MỖI TENANT MỘT COLLECTION (từ 2026-10-05): `<tenant_id>_public_web`** — cùng khuôn `<tenant_id>_documents`
(`qdrant_search.collection_name(tenant_id, "public_web")`). Collection `public_web` dùng chung đã bỏ. Nguồn,
chủ đề, trang thô (`tenant_data.web_pages`) và hồ sơ đều là của riêng workspace; `kb.api_key` ở
`/runtime-credentials` mở quyền đọc cho collection này (`dau-noi-agent.md` §2). Trong collection không có
payload `tenant_id` — tên collection chính là phạm vi; lọc theo `projects`/`location`.

## Vector

- `dense`: cosine, cùng kích thước và cùng embed service tự host với `<tenant>_documents` (`DENSE_SIZE`
  ở `kb/index/store.py`).
- Sparse tên `SPARSE_NAME` (cùng hằng với `<tenant>_documents`), modifier IDF.

Một collection mỗi tenant; chưa có collection (tenant chưa chạy lượt nào) ⇒ bên đọc coi như không có nguồn ngoài.

## Payload (đúng 7 khoá, không có khoá nào khác)

| Khoá | Kiểu | Nghĩa |
|---|---|---|
| `kind` | keyword | Loại point: `ho_so_du_an` (mục hồ sơ dự án) · `du_an_lan_can` (thẻ dự án lân cận) · `ban_tin_thi_truong` (tin bản tin thị trường). Bên ghi suy từ dải ID, không bao giờ lệch với ID |
| `text` | string | Dòng 1: `(Cập nhật dd/mm/yyyy)`. Dòng 2: tiêu đề trong ngoặc vuông (xem «Dòng ngày ghi và tiêu đề» dưới). Sau đó là một mục đủ ý về một đối tượng (công trình, tiện ích, tin tức…). Trích dẫn bằng `[k]` — xem mục dưới |
| `location` | keyword[] | Nhãn địa danh ĐÃ CHUẨN HOÁ (xem «Nhãn `location`» dưới): tên đường/phố, khu đô thị, xã/phường, quận/huyện, tỉnh/thành, bỏ trùng. Không có cấp «vùng» tự định nghĩa |
| `projects` | keyword[] | Tên dự án (tên thương mại, không phải mã) mà mục này nói về, ĐÃ CHUẨN HOÁ (xem «Nhãn `projects`» dưới). Rỗng = tin bản tin thị trường, không gắn dự án nào |
| `sources` | object[] | Danh sách `{url, name, published_at}`, đúng thứ tự `[1]`, `[2]`, … của point này. Đây là các nguồn mục này DỰA VÀO — kể cả khi `text` không ghi `[k]` nào (xem dưới) |
| `published_at` | datetime (ISO 8601) hoặc `null` | Ngày đăng lớn nhất trong `sources` có ngày; `null` nếu không nguồn nào có ngày |
| `updated_at` | datetime (ISO 8601) | **Hồ sơ và thẻ:** watermark NỘI BỘ của bên ghi — mốc nạp (`fetched_at`) mới nhất của các bài đã dùng để viết (dựng ban đầu/dựng lại xong trọn: mốc nạp mới nhất của MỌI bài liên quan; dừng giữa chừng: ngay trước bài chưa gửi sớm nhất); luôn ≤ giờ ghi, KHÔNG phải giờ ghi hay giờ gọi LLM — đừng hiện nó như «ngày cập nhật». **Bản tin:** đúng giờ ghi bản tin. Ngày ghi của mọi loại point nằm ở dòng đầu `text` |

Có payload index (keyword) trên `kind`/`location`/`projects`, và (datetime) trên `published_at`/`updated_at`.

### Dòng ngày ghi và tiêu đề

Mọi point có `text` mở đầu bằng hai dòng do code thêm lúc ghi (`compose.with_written`), không phải LLM viết:

1. `(Cập nhật dd/mm/yyyy)` — ngày (giờ VN) của LẦN GHI point đó.
2. `[tiêu đề]` — cho search chỉ dựa vào chữ biết point nói về cái gì, ở đâu:

| `kind` | Tiêu đề |
|---|---|
| `ho_so_du_an` | `[Dự án <tên dự án của tenant, bỏ phần trong ngoặc> — <3 phần cuối địa chỉ>]`, vd `[Dự án VINHOMES ROYAL ISLAND — Đảo Vũ Yên, Phường Thủy Nguyên, Thành phố Hải Phòng]` |
| `du_an_lan_can` | `[Dự án <tên đã chuẩn hoá> — <location của thẻ>]`, vd `[Dự án ecopark — xuân quan, văn giang, hưng yên]` |
| `ban_tin_thi_truong` | `[Tin thị trường bất động sản ngày dd/mm/yyyy]` (ngày ghi, giờ VN) |

Dự án không có địa danh thì tiêu đề chỉ là `[Dự án <tên>]`. **Vector (dense + bm25) được tính trên
tiêu đề + thân** (không gồm dòng ngày), nên câu hỏi chỉ có chữ vẫn khớp đúng tên/địa danh/loại.
Bên ghi bỏ cả hai dòng trước khi gửi lại nội dung cũ cho LLM, nên không bao giờ lặp. Bên đọc có thể hiện
nguyên `text`; muốn lấy riêng phần thân thì bỏ phần đầu khớp mẫu
`^\(Cập nhật \d{2}/\d{2}/\d{4}\)\n(?:\[[^\n]*\]\n)?`.

### Nhãn `location`

Mọi nhãn (Qdrant payload và cột `tenant_data.web_pages.location`) đi qua cùng một hàm
(`kb/web/locate.py::norm_place`), nên bên đọc lọc bằng `MatchAny` phải chuẩn hoá giá trị đem đi so
**đúng cùng cách** — lệch một tiền tố hay một chữ hoa là không khớp:

1. NFC, gộp khoảng trắng, hạ chữ (`casefold`); **giữ dấu tiếng Việt** ("Hoài Đức" → `hoài đức`).
2. Bỏ (lặp lại tới khi hết) tiền tố hành chính ở đầu chuỗi, không phân biệt hoa thường:
   `thành phố`, `tp`, `tp.`, `tỉnh`, `quận`, `huyện`, `thị xã`, `tx.`, `thị trấn`, `xã`, `phường`, `p.`,
   `q.`, `h.`, `đường`, `phố`, `đại lộ`, `khu đô thị`, `kđt`. Tiền tố có dấu chấm khớp cả khi viết liền
   ("P.Long Biên" → `long biên`, "TP.HCM" → `hcm`); tiền tố không dấu chấm phải có khoảng trắng theo sau
   ("Tphcm" giữ nguyên `tphcm`). "TP. Thành phố Hà Nội" → `hà nội`.
   **Ngoại lệ — địa danh đánh số:** phần còn lại chỉ là số (có thể kèm MỘT chữ cái, vd `7`, `7a`) thì GIỮ
   tiền tố và viết đầy đủ (`tp.`→`thành phố`, `tx.`→`thị xã`, `p.`→`phường`, `q.`→`quận`, `h.`→`huyện`):
   "Quận 7", "Q.7", "q. 7" → `quận 7`; "Phường 7", "P.7" → `phường 7` (khác `quận 7`).
3. Bỏ dấu `,` `.` `;` và khoảng trắng ở hai đầu; bỏ nhãn rỗng và nhãn trùng.

Ví dụ: "đường Lê Văn Lương" và "Lê Văn Lương" cùng ra `lê văn lương`; "Phường Long Biên" và
"P.Long Biên" cùng ra `long biên`; "Quận 7" ra `quận 7`, "Phường 7" ra `phường 7`.

`location` của mục hồ sơ = nhãn so khớp của dự án, lấy từ `address` của dự án: tách theo dấu phẩy và theo
` - `, ` – `, ` & ` (có khoảng trắng hai bên; gạch nối liền chữ không tách), bỏ số
nhà ở đầu mỗi phần, bỏ phần trùng (giữ lần cuối), lấy 3 phần cuối, rồi BỎ phần cuối cùng (tỉnh/thành —
quá rộng) khi có ≥ 2 phần. Địa chỉ rỗng thì dùng `region` của dự án (bỏ qua `mien_bac`/`mien_nam`/
`mien_trung`). `location` của thẻ dự án lân cận = vị trí của CHÍNH dự án đó (xã/phường, quận/huyện,
tỉnh/thành nơi dự án toạ lạc theo nguồn, tối đa 4), không phải mọi địa danh các bài nguồn nhắc tới.
`location` của mục bản tin = nhãn chung của các bài nguồn của mục đó (có ở ≥ 2 nguồn, tối đa 5; mục chỉ có
một nguồn thì 5 nhãn đầu của bài đó).

### Nhãn `projects`

Mọi tên dự án (Qdrant payload và cột `tenant_data.web_pages.projects`) đi qua cùng một hàm
(`kb/web/normalize.py::norm_project`): NFC, bỏ phần trong ngoặc tròn/vuông, gộp khoảng trắng, bỏ `,` `.` `;`
và khoảng trắng ở hai đầu, hạ chữ (`casefold`); **giữ dấu tiếng Việt**. Ví dụ: "VINHOMES GLOBAL GATE (TMDV)" →
`vinhomes global gate`; "Vinhomes Golden City Dương Kinh" → `vinhomes golden city dương kinh`.
`projects` chỉ chứa khu đô thị, chung cư, dự án nhà ở có tên thương mại — không chứa hạ tầng/tiện ích: nhãn
mà dạng chuẩn hoá mở đầu bằng một từ trong `normalize.NON_PROJECT_PREFIXES` (`tuyến`, `metro`, `đường`, `cầu`,
`sân bay`, `ga`, `khu công nghiệp`, `bệnh viện`, `vinmec`, `sân golf`, `trung tâm thương mại`, ...) bị bỏ.

Khớp tên dự án X với nhãn `p` (luật dùng ở mọi phía ghi, `normalize.project_matches` và SQL ở `repo.py`):
`p == norm(X)` HOẶC `p` bắt đầu bằng `norm(X) + " "` mà phần đuôi **không mở đầu bằng chữ số** (biến thể có
đuôi). "VINHOMES GOLDEN CITY" khớp `vinhomes golden city dương kinh`; "Vinhomes Ocean Park 3" khớp
`vinhomes ocean park 3 - the crown`; "Vinhomes Ocean Park" KHÔNG khớp `vinhomes ocean park 2` (dự án khác).
Bên đọc lọc theo một dự án nên chuẩn hoá tên đem đi so cùng cách và áp cùng luật đuôi.

### `[k]` là chỉ số CỤC BỘ của chính point đó

Trong `text`, `[k]` luôn trỏ vào `sources[k-1]` **của cùng point** — không phải một bảng nguồn toàn cục
dùng chung giữa các point. Hai point khác nhau có thể có `[1]` trỏ tới hai URL khác nhau. Khi hiện thị,
dựng link bằng `sources[k-1].url` của đúng point đang đọc; đừng gộp mọi `sources` của kết quả trả về
rồi tra `[k]` chéo point.

Mọi `k` xuất hiện trong `text` đều nằm trong khoảng `1..len(sources)` — code ghi (`compose.parse_items`)
loại bỏ trước khi upsert bất kỳ mục nào trích số ngoài khoảng, hoặc không trích số nào ở CẢ `text` lẫn
danh sách `cites` LLM trả kèm.

⚠️ Mục chỉ trích qua `cites` (không ghi `[k]` trong câu) **vẫn được nhận**: `text` khi đó không có `[k]`
nào, còn `sources` là các nguồn mục đó dựa vào. Bên hiển thị đừng giả định mọi mục đều có `[k]` trong
câu — không có thì gắn link từ `sources` ở cuối mục.

## Ba loại nội dung — khoá `kind`, và ID mã hoá sẵn loại

ID là `uuid5(uuid.NAMESPACE_URL, key)`, và `key` luôn chuẩn hoá tên trước khi ghép: tên dự án qua
`norm_project` (xem «Nhãn `projects`» — "(TMDV)" không tạo họ ID khác), vùng bản tin qua:

```python
def norm(name: str) -> str:
    return " ".join(name.split()).casefold()  # gộp khoảng trắng, hạ chữ hoa/dấu
```

Bên đọc muốn tự tính lại một ID (để `retrieve` trực tiếp thay vì `search`) phải chuẩn hoá **đúng cùng
công thức** — khác một khoảng trắng thừa hay hoa/thường là ra UUID khác. Luật đuôi KHÔNG áp cho ID: biến thể
có đuôi là một họ ID riêng.

| Loại | Công thức key | Số point mỗi họ | `projects` |
|---|---|---|---|
| Mục hồ sơ dự án | `f"kbweb:dossier:{norm_project(project_name)}:{i}"`, `i` từ `0` tới `MAX_DOSSIER_ITEMS - 1` | tối đa **25** (`MAX_DOSSIER_ITEMS`) | `[tên dự án]` |
| Thẻ dự án lân cận | `f"kbweb:card:{norm_project(project_name)}"` | đúng 1 | `[tên dự án]` |
| Tin bản tin thị trường | `f"kbweb:digest:{norm(region)}:{i}"`, `region` cố định `"toan_quoc"`, `i` từ `0` tới `MAX_DIGEST_ITEMS - 1` | tối đa **30** (`MAX_DIGEST_ITEMS`) | `[]` (luôn rỗng) |

⚠️ Trần dossier là **25**, không phải 100 — một dự án có nhiều mục hơn 25 thì các mục thừa không được
ghi (`WebIndex.replace` cắt theo độ dài dải ID); dưới 25 thì phần dư của dải ID được xoá ở mỗi lượt ghi
(`replace` gọi lại toàn bộ dải, không chỉ phần đã thay), nên không có "point rác" sót lại từ một hồ sơ
đã từng dài hơn.

Thẻ dự án lân cận và mục hồ sơ **dùng chung `location`** và có thể cùng `projects` (hồ sơ của dự án A và
thẻ "A" khi A là lân cận của dự án khác) — luôn lọc thêm `kind` để không lẫn.

## Cách đọc gợi ý

- **Mỗi lượt tìm: lấy top 5 cho TỪNG `kind`** (ba lượt query cùng vector câu hỏi, mỗi lượt lọc một `kind`),
  rồi gộp — một loại có điểm cao không chèn mất loại khác.

- **Hỏi về một dự án cụ thể:** lọc `projects` chứa tên thương mại của dự án ĐÃ CHUẨN HOÁ (`norm_project`;
  không phải mã nội bộ của tenant — `projects` trong payload không biết gì về mã tenant). `MatchAny` chỉ so
  đúng chuỗi; muốn lấy cả biến thể có đuôi thì áp luật khớp ở «Nhãn `projects`».
- **Bản tin hôm nay:** `projects` rỗng, lọc `updated_at` từ khoảng đầu ngày hôm nay theo giờ VN. Bản tin
  ghi đè theo ngày (cùng dải ID `digest`, không có ngày trong ID) — chỉ bản mới nhất tồn tại, không có
  lịch sử bản tin cũ. Bản tin chỉ viết từ bài báo (sitemap/RSS) đăng từ 00:00 giờ VN hôm qua tới lúc chạy — bài tìm
  qua Gemini hay bài không rõ ngày không vào bản tin.
- **Dự án lân cận:** mỗi nhãn so khớp của dự án là một cấp, theo thứ tự trong địa chỉ từ hẹp ra rộng
  (vd `lê văn lương`, rồi `nam từ liêm`; không dùng tỉnh/thành, quá rộng để coi là "cùng khu vực"). Lọc
  `location` theo cấp hẹp trước, loại chính dự án đang hỏi, chưa đủ ứng viên thì mở cấp sau. Thẻ chỉ được
  viết cho tên dự án gắn trên ≥ 2 bài cùng khu vực, không phải biến thể/tiền tố/hậu tố của chính dự án
  ("Royal Island" là "Vinhomes Royal Island"), và mỗi thẻ phải nhắc tên dự án của nó (tên đầy đủ, hoặc tên
  ≥ 3 từ bỏ từ đầu) — thẻ không nhắc tên không được ghi.
- **Luôn xếp `public_web` SAU** kết quả từ `<tenant>_documents`/tài liệu của đối tác, và gắn nhãn rõ đây
  là nguồn ngoài kèm link (`sources[k].url`) — dữ liệu chưa được đối tác xác nhận.

## Độ tươi

- Chuỗi đêm chạy theo lịch «Cập nhật mỗi đêm» của tenant (mặc định 01:10 giờ VN) (crawl 2 ngày gần nhất + lượt nhanh theo dự án, không gọi
  Gemini + bản tin) — hồ sơ dự án trễ tối đa khoảng một ngày so với bài báo gốc. Lượt nhanh chỉ viết lại
  hồ sơ khi có ≥ 1 bài mới gắn tên dự án hoặc ≥ 5 bài mới cùng khu vực (`location` giao nhãn so khớp của dự án); ít hơn thì chờ lượt sau/lượt sâu.
- Lượt sâu (gọi Gemini grounding cho chủ đề còn thiếu) chạy **hằng ngày** cho 1/`KB_WEB_DEEP_SLICES`
  số dự án mỗi ngày (mặc định 2 = một nửa), `id % N == ngày (theo số thứ tự ngày giờ VN) % N` — mỗi dự
  án được xử lý sâu một lần mỗi N ngày, không phải "vào Chủ nhật".
- Dựng lại toàn bộ hồ sơ từ raw mỗi quý (xoá lỗi tích luỹ của cách viết tăng dần).
- Dựng hồ sơ ban đầu chạy ngay khi dự án được tạo/publish: lấy 200 bài liên quan mới nhất theo ngày đăng,
  viết cũ → mới qua tối đa 5 lượt nối tiếp (tin mới viết sau cùng). Tồn đọng cũ hơn tập đó bị bỏ có chủ ý.

## Không có

- **Không xoá point** của dự án đã unpublish, đã bị gỡ hay đã đổi tên — hồ sơ/thẻ cũ nằm nguyên, chỉ
  không được làm mới nữa. `updated_at` cho biết mục đã cũ bao lâu; bên đọc tự quyết ngưỡng bỏ qua.
- **Một hồ sơ cho mỗi TÊN dự án trong collection của tenant.** ID tính từ tên thương mại đã chuẩn hoá;
  hai tenant có dự án cùng tên có hai bộ point ở hai collection khác nhau, không còn dùng chung.
- Job theo dự án có kind `kbweb_project` (không có tiền tố `kb_` — chỉ báo "đang nạp" của trang dự án
  lọc `kb\_%` và không được thấy việc này).

## Điều KHÔNG có trong đợt này

- Tầng trình duyệt (Playwright/Chromium, image `-crawl`) có từ 2026-10-05: trang bị chặn/dựng bằng JS được
  tải lại bằng trình duyệt dưới trần `browser_daily` của tenant; vẫn chặn thì giữ dấu `needs_browser` trong
  `tenant_data.web_pages` và thử lại hai ngày kế tiếp.
- Không có endpoint portal đọc `public_web` cho kênh Sale — câu hỏi "đọc thẳng collection hay qua một
  endpoint portal" chưa chốt (spec §11).
- Không có tool mới phía agent — dữ liệu gộp vào `kb_search` sẵn có.
