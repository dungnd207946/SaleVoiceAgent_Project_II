# Gói `kb/web` và schema `public_data`: crawl và search dữ liệu BĐS công khai bên ngoài

Ngày: 2026-09-29 · Trạng thái: thiết kế đã chốt qua brainstorm, chờ duyệt spec

## 1. Bối cảnh

Note review ngày 28/09/2026 (`odyssey-agent/docs/sale-scenario/Note review NobleX Agent – Trợ lý ảo AI tư vấn BĐS.md`, mục
"Trợ lý cho Sale") yêu cầu ba thứ:

- Tổng hợp tin thị trường BĐS trong ngày để Sale gửi cho khách.
- Tổng hợp thông tin có lợi về một dự án, kèm link nguồn. Ví dụ: hạ tầng quanh Noble Palace Tây Thăng Long.
- Thông tin các dự án lân cận để so sánh với dự án của mình.

Hiện cả ba repo (portal backend, portal frontend, agent) chưa có web search hay crawl nào. Tài liệu sản phẩm cũ xếp việc crawl
web vào nhóm "hoãn sau MVP".

**Phạm vi của spec này:** chỉ gồm crawl, search và chuẩn bị dữ liệu. Kênh phát cho Sale, giao diện, CRM và màn duyệt không
thuộc phạm vi.

**Nguyên tắc đã chốt:**
- Tiêu chí chọn nguồn chỉ có hai: nguồn đáng tin và lấy được dữ liệu. Không xét robots.txt/ToS.
- Không xử lý việc dữ liệu hiện chéo giữa các tenant.
- Chi phí càng thấp càng tốt, hạn chế gọi API.

## 2. Kiến trúc tổng

Luồng dữ liệu đi qua năm tầng:

1. **Nguồn.** Mỗi đêm tự crawl các báo trong whitelist. Nguồn chính là sitemap lưu trữ theo ngày; RSS và trang mục tin là
   nguồn phụ. Chủ đề nào của một dự án vẫn thiếu bài thì mới gọi thêm Gemini Grounding with Google Search.
2. **Tải trang.** Chia nhiều tầng theo domain: HTTP thường, trình duyệt headless, và unlocker trả phí (tầng này đang tắt).
3. **Lưu raw.** Một bảng Postgres dùng chung là `public_data.web_pages`. Bảng chỉ chứa bài gốc và hai cột nhãn.
4. **Tổng hợp.** qwen3.7-flash gắn nhãn cho từng bài, sau đó viết và cập nhật theo kiểu tăng dần ba loại nội dung: hồ sơ dự
   án, thẻ dự án lân cận và bản tin ngày.
5. **Phục vụ.** Một collection Qdrant dùng chung là `public_web`, chỉ chứa các bản tóm tắt. Agent đọc collection này qua
   `kb_search` sẵn có.

**Nơi đặt code.** Code nằm trong gói con `odyssey-portal-backend/src/portal/modules/kb/web/`, theo tiền lệ của `kb/hippo/`.
Không tách thành một module riêng, vì hai lý do:
- Luật 3 (`tests/test_module_boundaries.py`) chỉ cho một module import `portal.core.*` và `contracts` của module khác. Trong khi
  đó, những thứ cần dùng lại đều nằm trong ruột `kb`: `clients/embed.py`, `index/store.py`, `clients/extract.py`,
  `clients/rate_gate.py`, `clients/retry.py`, `clients/external_images.py`.
- Về bản chất, đây chỉ là thêm một nguồn tri thức cho agent, đúng việc của `kb`.

`realestate` và `ingest` gọi vào gói này qua mặt tiền `portal.modules.kb.contracts`, dùng cơ chế nạp muộn `_ENQUEUE_FACADE`
có sẵn. Gói phải nằm gọn trong thư mục riêng, không chèn thêm vào các file sẵn có của `kb`.

**Nơi chạy.** Gói chạy trong một **container riêng**: thêm vai `crawl` vào `deploy/entrypoint.sh`, cùng khuôn với vai `dinh-gia`.
Container này dùng image riêng, và các thư viện nặng (Playwright, Crawl4AI) là extra tuỳ chọn.
- Job của gói được đăng ký trong `kb/web/jobs.py`, và **không** được import từ `kb/jobs.py`. Trường hợp `hippo` thì ngược lại:
  `kb/jobs.py` import nó nên worker chính cũng chạy job của nó. Ở đây chỉ container `crawl` import `kb/web/jobs.py`, nên worker
  chính không nhặt những job này.
- Dữ liệu công khai (`public_data.web_pages`, `public_web`) không đi qua khuôn tenant của `kb` (`tenant_conn()`, collection
  `<tenant>_…`, `kb_index_state`). Chỉ bước đọc log hội thoại và đọc dữ liệu dự án mới dùng `tenant_conn()`.
- Nhờ tách container, crawl bị treo hay lỗi thì worker chính không bị ảnh hưởng, và image của portal không phình theo.

## 3. Nguồn dữ liệu

### 3.1 Whitelist

Whitelist khai trong một file cấu hình. Mỗi domain gồm các trường:
- tên hiển thị;
- cách tải trang (`http`, `browser` hoặc `unlocker`);
- loại trang: `news` (bài báo, không đổi sau khi đăng) hoặc `living` (trang được cập nhật liên tục);
- danh sách RSS, danh sách sitemap;
- các đường dẫn chuyên mục BĐS.

Kết quả đo ngày 29/09/2026, gửi request HTTP thường với user-agent trình duyệt:

| Nhóm | Domain |
|---|---|
| Tải được bằng HTTP thường, cả trang mục lẫn bài chi tiết | cafef, vnexpress, dantri, baoxaydung, vneconomy, thanhnien, tuoitre, vietnamnet, cafeland, batdongsan (trang tin tức và wiki), reatimes, nhipsongkinhdoanh, baochinhphu, hanoi.gov.vn, quyhoach.hanoi.vn, savills, tienphong |
| Cần trình duyệt | laodong (chặn bằng cookie đặt qua JavaScript); các trang dự án của batdongsan (403 kèm challenge Cloudflare) |
| Không vào được | dkra.vn (tên miền không phân giải; cần tìm lại domain thật) |

Có 11/13 báo khai sitemap. Phần lớn có google-news-sitemap (bài mới kèm ngày đăng) và sitemap lưu trữ theo ngày hoặc tháng,
lùi về 2010–2016.

### 3.2 Cách tìm bài

- **Không dùng search API cho tầng whitelist.** Mỗi đêm, nguồn chính là **sitemap lưu trữ theo ngày của hôm qua**. RSS,
  google-news-sitemap và trang mục tin chỉ là nguồn phụ.
  - Không lấy RSS làm nguồn chính được: RSS chuyên mục BĐS chỉ giữ 50–100 bài gần nhất (CafeF 50, VnExpress 60, Dân trí 100).
    Nếu mỗi ngày chỉ quét một lần, báo nào đăng nhiều hơn số đó trong ngày sẽ bị sót bài.
  - Sitemap lưu trữ thì liệt kê đủ mọi bài trong một khoảng ngày. Ví dụ `sitemaps-2026-9-1-5.xml` của CafeF có 1.789 URL;
    Thanh Niên có 1.245 URL, Báo Xây dựng có 403 URL.
  - Mỗi báo đặt tên sitemap theo một kiểu (VnExpress khác hẳn), nên mỗi báo cần cấu hình riêng.
  - Cũng các sitemap lưu trữ này được dùng một lần để nạp ngược tin của 24 tháng.
  - Chỉ giữ bài thuộc chuyên mục BĐS.
- **Đo "đủ bài" theo từng chủ đề.** Có 18 chủ đề: đường bộ, cầu và vượt sông, giao thông công cộng, thời gian di chuyển, giáo
  dục, y tế, thương mại, cảnh quan và giải trí, việc làm và hành chính, quy hoạch, dự án lớn trong khu vực, dự án lân cận, mặt
  bằng giá, tin về chính dự án, tiện ích nội khu, tiện ích ngoại khu, pháp lý dự án, chủ đầu tư. Mỗi chủ đề của một dự án đi qua hai bước:
  - Bước 1: lọc trong kho tự crawl.
  - Bước 2: nếu vẫn thiếu bài, gọi Gemini grounding.
  - Chủ đề chỉ dùng để lập truy vấn và làm khung cho hồ sơ. Nó không được lưu vào Postgres hay Qdrant.
- **Câu search của bước 2** (`data/topics.yaml`) chỉ có hai biến: `{project}` (tên dự án, bỏ phần trong ngoặc,
  giữ hoa thường) và `{location}` (địa danh dự án = 3 phần cuối của `address` tách theo `,`, ` - `, ` – `, ` & `,
  sau khi bỏ số nhà ở đầu phần và bỏ phần
  trùng — giữ lần cuối; nối lại bằng ", "; địa chỉ rỗng thì dùng `region`, bỏ qua `mien_*`). Dự án không
  có địa danh thì bỏ các câu chứa `{location}`; câu chỉ có `{project}` vẫn chạy.
- **Trần cho bước 2** (giá trị khởi điểm, tinh chỉnh sau khi chạy thật):
  - mỗi chủ đề nhắm 5 bài, tối đa 4 truy vấn và 20 trang;
  - mỗi dự án, mỗi lượt tối đa 60 truy vấn và 150 trang;
  - dừng sớm khi 2 truy vấn liên tiếp không ra bài mới;
  - thêm một trần ngân sách theo ngày.
- **Link gốc từ Gemini.** Grounding trả về link chuyển hướng `vertexaisearch`. URL gốc đọc được từ header `Location` mà không
  cần tải trang; đo được 8/8 link, mỗi link mất 1–4 giây. Key Gemini dùng cho bước này thuộc một Google project riêng, để không
  tranh quota miễn phí với phần khác.
- **Quy tắc chọn bài:**
  - Bài PR và bài tin tức được đối xử như nhau.
  - Bài chép lại (trùng băm nội dung) bị loại và không lưu.
  - Bài ngoài whitelist vẫn được dùng, kể cả khi nó là nguồn duy nhất của một mốc tiến độ.
- **Crawl lại:** bài báo đã có trong kho thì không crawl lại. Trang loại `living` (trang chủ đầu tư, cổng quy hoạch, trang giá)
  được kiểm lại hằng tháng.
- **Bài quá hạn giữ:** bài có ngày đăng cũ hơn 730 ngày (hạn giữ của `repo.purge`) không được gắn nhãn mà lưu thành dấu
  `irrelevant` — để grounding trả lại bài cũ đó ở lượt tuần sau thì `known_urls` bỏ qua thay vì tải và gắn nhãn lại (dấu bị
  dọn sau 90 ngày, nên tối đa một lần tải mỗi 90 ngày).
- **Chỉ tải URL công khai:** trước khi tải (Fetcher, và link redirect của grounding cùng đích `Location`), URL phải là
  http(s) với host không phải loopback/private/link-local/reserved (Discoverer cũng kiểm sitemap con và trang mục) — kiểm IP viết thẳng và IP phân giải ra; redirect tự theo
  tối đa 5 bước, mỗi bước kiểm lại host.
- **Phát hiện báo "im lặng":** một domain 2 ngày liền không có bài mới thì cảnh báo. Nguyên nhân thường là sitemap hoặc giao
  diện đã đổi.

### 3.3 Tải trang

| Tầng | Công cụ | Dùng cho | Chi phí |
|---|---|---|---|
| 1. http | httpx + trafilatura | Mặc định, mọi báo | 0 |
| 2. browser | Crawl4AI / Playwright chạy trong container crawl | laodong, trang dự án batdongsan | 0 (tốn khoảng 300–500 MB RAM) |
| 3. unlocker | Dịch vụ trả phí | Đang TẮT; chỉ chừa chỗ trong cấu hình | khoảng 1,5 USD cho 1.000 trang, nếu bật |

⚠️ **Đợt thi công này CHƯA làm tầng 2.** `config.py` khai `fetch_mode: browser` là một giá trị hợp lệ
(`laodong.vn` là nguồn duy nhất khai vậy), nhưng không có Crawl4AI/Playwright nào chạy — `Fetcher`
(`fetch.py`) chỉ có tầng http. Với domain `fetch_mode: browser`, `pipeline._crawl_source` KHÔNG gọi
`Fetcher` mà chỉ ghi dấu `status = 'needs_browser'` cho URL tìm được rồi bỏ qua (không tải nội dung,
không gắn nhãn). Domain `fetch_mode: http` mà tầng 1 gặp trang challenge (`looks_challenged`, dò theo
mã trạng thái + dấu hiệu Cloudflare) thì cũng đóng dấu `needs_browser` chứ KHÔNG tự chuyển sang tầng 2 —
vì tầng 2 không tồn tại. Không có tiến trình nào đọc lại các URL `needs_browser` để thử tầng khác; xây
tầng 2 và đường thử lại cho `needs_browser` đã dời sang **plan C** (tài liệu kế hoạch riêng, chưa viết).
Tầng 1 nhận về nội dung rỗng (không phải challenge) thì đóng dấu `fetch_failed` — loại URL DUY NHẤT
được thử lại tự động, ở lượt crawl đêm kế tiếp (xem §4).

## 4. Lịch chạy

**CLI xếp job cho phần theo dự án, tự làm hết phần còn lại.** `control.jobs.tenant_id` là cột bắt buộc
(NOT NULL) — bước quét sitemap và bước viết bản tin không thuộc về một tenant nào (chúng ghi vào
`public_data.web_pages`/point `digest` dùng chung), nên không xếp được vào `control.jobs`. Vì vậy
`src/portal/cli/kb_web_night.py` tự chạy trực tiếp hai bước đó trong tiến trình CLI (không qua hàng đợi);
chỉ phần theo dự án (lượt nhanh mỗi đêm, lượt sâu hằng tuần, dựng lại, dựng ban đầu) mới xếp thành job
`kind = "kbweb_project"`, do worker riêng `crawl-worker` (`src/portal/cli/kb_web_worker.py`) nhặt và
chạy — **không phải worker chính**: `kb/jobs.py` cố ý không import `kb/web/jobs.py`.

**Chuỗi đêm: một CLI, cron gọi khoảng 1h sáng (`OnCalendar=*-*-* 01:10:00`, giờ máy).** Bốn bước chạy
nối tiếp trong cùng một tiến trình; bước nào hỏng chỉ ghi log lỗi, các bước sau vẫn chạy trên dữ liệu đã
có (mã thoát tiến trình khác 0 nếu có bước hỏng, để cron/systemd ghi nhận).

1. Quét sitemap theo ngày, cho **cả hôm qua LẪN hôm kia** (thêm RSS làm nguồn phụ), tải bài mới và gắn
   nhãn. Crawl lại hôm kia để các URL từng `fetch_failed` (lỗi mạng thoáng qua) được thử lại một lần —
   URL đã có với trạng thái khác `fetch_failed` thì bỏ qua, nên lượt thử lại này rẻ.
2. Kiểm lại trang `living` quá hạn kiểm (30 ngày).
3. Viết bản tin thị trường từ các bài báo (tìm qua sitemap/RSS) có **ngày đăng** từ 00:00 giờ VN hôm qua
   tới lúc chạy — theo NGÀY LỊCH chứ không cửa sổ 24 giờ, vì trafilatura thường chỉ ra ngày (00:00) và
   chuỗi đêm chạy lúc ~1h. Bài grounding và bài không rõ ngày bị loại (mốc nạp không nói gì về độ mới của
   tin). Ngày đăng: trang không tự khai thì lấy ngày của mục sitemap/RSS; trang chỉ có NGÀY (00:00 VN)
   trùng ngày với mục sitemap/RSS thì lấy giờ chính xác của sitemap/RSS; khác ngày thì giữ ngày của trang. Bản tin mới ghi đè bản của hôm trước
   (cùng dải ID).
4. Dọn bài quá hạn giữ, rồi **xếp job `kind="kbweb_project"` cho các dự án đang được hỏi** (lượt
   `nightly`) — job này mới thật sự làm mới hồ sơ dự án, chạy ở `crawl-worker`, không chạy trong CLI.

**Lượt nhanh theo dự án (`mode=nightly`, chạy TRONG job, không phải bước riêng của CLI trên) KHÔNG gọi
Gemini** — nó chỉ lọc trong kho đã crawl (cửa sổ 48 giờ nếu dự án chưa từng có hồ sơ, hoặc mọi bài sau
watermark cũ nếu đã có) rồi viết lại hồ sơ, và **chỉ viết lại khi có ≥ 1 bài mới gắn tên dự án hoặc ≥ 5
bài mới chỉ cùng khu vực** (`NIGHTLY_MIN_AREA_PAGES`); ít hơn thì bỏ qua, không gọi LLM, watermark giữ nguyên
(bài đó được lượt sau hoặc lượt sâu nhặt). **Gemini grounding chỉ chạy ở ba lượt: `weekly`, `init`,
`rebuild`** — cho chủ đề của dự án còn thiếu bài, dưới trần `KB_WEB_GROUNDING_DAILY_CAP` (mặc định
**1.200** lượt gọi/ngày, đặt thấp hơn mức miễn phí 1.500/ngày của Gemini 2.5 Flash grounding để chừa dư
địa cho các lượt gọi thủ công/thử nghiệm; **cần xác nhận tier/billing của Google project trước khi bật
key** — mức miễn phí phụ thuộc tier). Hết trần, hoặc Gemini trả 429/5xx, thì `_fill_topics` dừng tìm thêm
cho lượt đó, không ném lỗi; hồ sơ vẫn được viết bằng những gì đã có. Lỗi tạm thời của LLM (qwen) thì vẫn
lan ra để job thử lại.

**Dựng ban đầu/dựng lại (`init`/`rebuild`)** lấy **200 bài liên quan mới nhất** (theo
`coalesce(published_at, fetched_at)`), viết cũ → mới qua tối đa 5 lượt, mỗi lượt ≤ 40 bài / 120.000 ký tự
nguồn — tin mới được viết sau cùng nên thắng khi mâu thuẫn. Không vừa 5 lượt thì bỏ bài cũ nhất. Sau khi
dựng xong trọn, watermark = mốc nạp mới nhất của MỌI bài liên quan: tồn đọng cũ hơn tập 200 bài bị bỏ có
chủ ý, lượt đêm/tuần sau không nhặt lại. Các lượt trước lượt cuối ghi watermark ngay trước bài nạp sớm nhất
còn CHƯA gửi (dựng ban đầu trên hồ sơ có sẵn: không thấp hơn watermark hồ sơ cũ; dựng lại: không có sàn,
vì nó ghi đè hồ sơ từ đầu) — dừng giữa chừng thì lượt đêm/tuần sau gửi tiếp phần còn
lại. Lượt đêm/tuần vẫn đi theo watermark, cũ trước mới sau.

**Trả lời LLM bị cắt hoặc JSON hỏng** (hồ sơ, thẻ, bản tin): ghi log lỗi kèm tên dự án, GIỮ bản cũ, không
dời watermark, job kết thúc bình thường với thông điệp `"<mã> <mode>: giữ hồ sơ cũ — trả lời LLM bị cắt"`
(hoặc "… không đọc được"; dựng dừng giữa chừng: `"<n> mục, dừng dựng giữa chừng — …"`) — thử lại cùng dữ
liệu cũng bị cắt y hệt, nên không để job lặp thử lại. Để ít bị cắt, prompt hồ sơ yêu cầu mỗi mục
100–220 từ (tối đa 25 mục, `max_tokens` 16.000). Mỗi lượt gọi LLM ghi log INFO số token (`prompt_tokens`/`completion_tokens`) để đo chi phí thật.

**Ngưỡng coi là kẹt:** job `kbweb_project` khai `stuck_minutes=120` với `core.jobs` (thu hồi của worker),
nhưng khung nhìn `control.jobs_stuck` (migration `0006`) vẫn dùng mốc cứng 15 phút — nó sẽ liệt kê một
lượt dựng ban đầu dài hơn 15 phút là "kẹt" dù worker chưa thu hồi.

Hệ quả của lịch trên: bản tin buổi sáng là tin của ngày hôm qua/hôm kia gộp lại (cửa sổ 24h tính từ giờ
CLI chạy), và hồ sơ dự án trễ tối đa khoảng một ngày.

| Việc | Nhịp | Gọi Gemini? |
|---|---|---|
| Chuỗi đêm (quét 2 ngày → kiểm living → bản tin → dọn → xếp job `nightly`) | hằng ngày, khoảng 1h10 sáng, chạy trong CLI | không |
| Job `kbweb_project` lượt `nightly` (lọc kho, viết lại hồ sơ) | xếp mỗi đêm cho dự án đang được hỏi, chạy ở `crawl-worker` | không |
| Job `kbweb_project` lượt `weekly` (đủ bộ truy vấn theo chủ đề còn thiếu + làm mới thẻ lân cận) | xếp **hằng ngày lúc 4h** cho 1/`KB_WEB_DEEP_SLICES` số dự án (mặc định 2 = một nửa), `id % N == ngày (theo số thứ tự ngày giờ VN) % N` — mỗi dự án được xử lý sâu một lần mỗi N ngày; tên "weekly" là tên cơ chế, không phải nhịp chạy | có, dưới trần ngày |
| Job `kbweb_project` lượt `rebuild` (dựng lại toàn bộ hồ sơ từ raw) | xếp mỗi quý cho mọi dự án published | có, dưới trần ngày |
| Job `kbweb_project` lượt `init` (dựng hồ sơ ban đầu) | xếp ngay khi dự án được tạo hoặc publish | có, dưới trần ngày |
| Kiểm lại trang living | mỗi lượt chuỗi đêm (nội bộ dùng ngưỡng 30 ngày/trang, không phải nhịp cron riêng) | không |

**Dựng hồ sơ ban đầu** được móc vào `realestate/router.tao_du_an` / `sua_du_an` và nhánh chiếu của `modules/ingest`. Các chỗ
này gọi qua `portal.modules.kb.contracts` để giữ đúng luật ranh giới module.

**Chỉ dự án có người hỏi mới được làm mới.** Lượt đêm và lượt sâu chỉ chạy cho dự án có người hỏi trong 4 tuần gần nhất. Tín
hiệu lấy từ log `tenant_data.conversation_messages`, đọc qua `tenant_conn()`:
- Nguồn chính: tên hoặc mã dự án nằm trong tham số `meta.tool_calls` của các tool find_project, discover_projects, search_units
  và kb_search. Agent vốn đã ghi các tham số này (`odyssey-agent/src/noble_agent/storage/pg_data_plane.py::_message_meta`).
- Nguồn phụ: câu của khách khớp với tên chuẩn, alias hoặc `tenant_data.project_hot_words`.
- Tenant nào không có dòng log nào trong 4 tuần thì crawl lại toàn bộ dự án của tenant đó. Như vậy khi log bị mất, dữ liệu vẫn
  được làm mới thay vì âm thầm dừng.
- Không phải sửa agent, không cần Redis, không cần endpoint mới.

### 4.1 Không làm chậm agent đang chạy

Chạy dồn vào ban đêm, lúc agent gần như không có khách, đã giảm phần lớn rủi ro. Bảng dưới vẫn liệt kê các biện pháp, để phòng
trường hợp có khách gọi lúc nửa đêm:

| Tài nguyên dùng chung | Rủi ro | Biện pháp |
|---|---|---|
| CPU/RAM máy chủ | Container crawl chung máy với agent; tầng trình duyệt tốn thêm 300–500 MB | Đặt giới hạn CPU và RAM cho container crawl |
| Embed service tự host | Agent cũng gọi service này để embed câu hỏi mỗi lần `kb_search` | Chỉ embed bản tóm tắt (vài trăm mỗi ngày), không embed bài gốc; giới hạn số request đồng thời |
| API qwen (DashScope) | Agent đang dùng cùng key cho suggestions và HippoRAG; crawl dồn request có thể làm cả tài khoản chạm giới hạn tốc độ | Dùng key hoặc workspace DashScope riêng; giới hạn số lượt gọi đồng thời |
| Hàng đợi `control.jobs` | Worker chính tự nạp `jobs.py` của mọi module, nên sẽ nhặt cả job của gói web; khi đó job index tài liệu của tenant phải chờ | Chỉ container crawl đăng ký các loại job của gói web; worker chính bỏ qua module này |
| Postgres | Rất nhỏ: crawl ghi vào schema riêng, còn việc đọc log không chặn agent ghi | Pool kết nối riêng, cỡ nhỏ |
| Qdrant | Nhỏ: ghi vào collection riêng, không đụng collection của tenant | Ghi theo lô nhỏ |
| API Gemini | Không có rủi ro: dùng key thuộc project riêng | — |

## 5. Lưu trữ

### 5.1 Postgres: một bảng raw `public_data.web_pages`

Bảng chứa dữ liệu công khai nên không có `tenant_id`. Chỉ container crawl đọc và ghi.

| Cột | Ý nghĩa |
|---|---|
| `url` (khoá chính) | URL đã bỏ tham số theo dõi và phần neo |
| `source_url`, `domain`, `title` | `source_url` hiện luôn bằng `url` (chưa có trường hợp URL tải khác URL chuẩn) |
| `published_at` | ngày đăng; là trọng tài cho luật "tin mới nhất thắng" |
| `fetched_at` | mốc NỘI DUNG THẬT SỰ đổi lần gần nhất — không nhích ở mỗi lượt crawl lại nếu hash không đổi; đây là watermark các lượt viết tăng dần dùng để hỏi "bài nào mới hơn lần trước" |
| `last_checked_at` | mốc crawl CHẠM tới lần gần nhất, luôn cập nhật — dùng để tìm trang `living` quá hạn kiểm |
| `content_text` | toàn văn; `NULL` nếu bài bị loại (không lưu nội dung của bài `irrelevant`/lỗi — kể cả trang `living` kiểm lại mà thành không liên quan) |
| `content_hash` | phát hiện bài chép lại (`hash_taken`) và trang living có đổi nội dung hay không |
| `found_via` | `sitemap` \| `rss` \| `grounding` — danh sách ĐÓNG (CHECK), do gói `kb/web` quyết |
| `status` | `ok` \| `irrelevant` \| `fetch_failed` \| `needs_browser` — danh sách ĐÓNG (CHECK). `fetch_failed` KHÔNG tính là "đã biết" (`known_urls` loại nó ra) nên được thử lại ở lượt crawl sau; `needs_browser` hiện chưa có ai thử lại (không có tầng trình duyệt, xem §3.3) |
| `projects`, `location` | nhãn đã chuẩn hoá, dạng mảng, có GIN index |

Hạn giữ (`repo.purge`, chạy mỗi lượt chuỗi đêm): bài `status='ok'` quá 730 ngày (24 tháng) tính theo
`coalesce(published_at, fetched_at)` thì xoá; bài trạng thái khác (`irrelevant`/`fetch_failed`/
`needs_browser`) quá 90 ngày tính theo `last_checked_at` thì xoá. Migration `0969_public_data_web_pages`
(cha `0968_escalations_lead`) tạo schema `public_data` và cấp `SELECT, INSERT, UPDATE, DELETE` cho
`portal_api`. Bảng KHÔNG có `tenant_id` nên KHÔNG có RLS — đây là quyết định có chủ ý (dữ liệu công
khai, không phải dữ liệu nghiệp vụ của tenant), không phải bảng bị bỏ sót. Cổng cách ly
(`tests/isolation/test_isolation_catalog.py`) chỉ quét ba schema `control`/`tenant_data`/`billing` —
`public_data` nằm ngoài phạm vi của nó nên không cần khai báo gì thêm; đây cũng là lý do một schema
thiếu `tenant_id`/RLS như `public_data` không bị cổng đó bắt.

### 5.2 Qdrant: một collection dùng chung `public_web`

- **Vector:** dense + sparse, dùng lại embed service tự host sẵn có, nên không tốn thêm phí.
- **Payload** gồm 7 khoá: `kind` (`ho_so_du_an` / `du_an_lan_can` / `ban_tin_thi_truong`, suy từ ID) · `text` (dòng ngày ghi + dòng tiêu đề `[…]` được embed cùng thân) · `location` · `projects` · `sources` (danh sách url, tên nguồn, ngày đăng) · `published_at` ·
  `updated_at`. Dòng đầu `text` là `(Cập nhật dd/mm/yyyy)` — ngày ghi giờ VN, code thêm lúc ghi và bỏ trước khi gửi lại cho LLM.
- **Mỗi point là một mục đủ ý về một đối tượng** (hồ sơ: 100–220 từ/mục), giữ số liệu, lịch sử các mốc và số nguồn [n]:
  - Hồ sơ dự án: mỗi công trình hoặc nhóm tiện ích là một mục. Mục "Dự án lân cận" chứa phần so sánh theo từng cặp.
  - Thẻ dự án lân cận: **mỗi dự án chỉ có một thẻ**, dùng chung cho mọi dự án và mọi tenant.
  - Bản tin ngày: mỗi tin một point, trường `projects` để rỗng.
- **Id tất định.** Chạy lại thì ghi đè đúng point cũ. Id của bản tin không chứa ngày, nên bản tin mỗi sáng ghi đè bản hôm qua.
- **Không có job dọn:**
  - Viết lại hồ sơ gồm upsert rồi xoá các mục thừa của chính dự án đó, trong cùng lượt ghi.
  - Point của dự án đã unpublish/gỡ/đổi tên KHÔNG bị xoá — chỉ thôi được làm mới; `updated_at` cho biết đã cũ bao lâu.
  - Thẻ lân cận được giữ lại; `updated_at` cho agent biết thẻ đã cũ bao lâu.
  - Id tính theo TÊN dự án, không theo tenant: hai tenant có dự án cùng tên thương mại dùng chung một hồ sơ.
- **Hợp đồng payload** viết ở `docs/contracts/public-web.md`, sau đó chép tay sang repo agent.

## 6. Tổng hợp nội dung

Dùng **một model** là qwen3.7-flash (endpoint dashscope-intl, tắt thinking), chi phí khoảng 2–3 USD mỗi tháng.

**Cập nhật tăng dần.** Đầu vào của mỗi lần viết gồm:
1. Dữ liệu tenant: đứng đầu và có quyền cao nhất.
2. Hồ sơ hiện có, kèm nguồn của từng mục.
3. Các bài mới, lọc theo `projects` và `location`.
4. Ngày hôm nay.

Tuần nào không có bài mới thì không gọi LLM.

**Trích nguồn.** LLM chỉ ghi số [n] theo danh sách bài được đưa vào; code đổi các số đó thành link. Ý nào ghi số không có trong
danh sách thì bị loại. Nhờ vậy không có link bịa.

**Luật xử lý mâu thuẫn:**
1. **Tenant thắng.** Không nói ngược dữ liệu của đối tác; chỉ bổ sung phần đối tác chưa có. Bài raw không bị sửa.
2. **Khác thời điểm:** tin mới nhất thắng, và giữ một dòng lịch sử, ví dụ "mốc cũ quý II/2026 đã lùi".
3. **Mốc "dự kiến" đã qua mà không có tin mới:** ghi "chưa có cập nhật", đồng thời chạy thêm một truy vấn nhắm vào mốc đó.
4. **Cùng thời điểm, khác số:** nguồn trong whitelist thắng, sau đó xét đa số; vẫn hoà thì hiện cả hai hoặc gộp thành một khoảng.
5. **Hai nguồn trái ngược hoàn toàn:** hiện cả hai; nguồn chính thống thắng nếu có.
6. **Mâu thuẫn giả** (khác đơn vị, khác phạm vi, khác khái niệm, làm tròn số, tên hành chính cũ và mới): chuẩn hoá trước khi so,
   và giữ nguyên định ngữ.
7. **Hồ sơ và bài gốc nói khác nhau:** hồ sơ thắng.

**Bù điểm yếu đo được của qwen.** Bài thử cho thấy qwen hay thêm nhận định không có trong bài và đổi tên hành chính. Cách bù:
- Prompt cấm thêm nhận định ngoài bài, và yêu cầu giữ nguyên tên hành chính như trong bài.
- Code chuẩn hoá `location` và `projects`: bỏ trùng, bỏ giá trị rỗng. `location` còn bỏ tiền tố hành chính
  và hạ chữ (`locate.norm_place`, quy tắc ở `docs/contracts/public-web.md`) tại đúng một chỗ trước khi lưu
  Postgres và payload Qdrant, để hai phía của mọi phép so cùng một dạng. `projects` cũng vậy (`normalize.norm_project`:
  bỏ phần trong ngoặc, hạ chữ, giữ dấu) và tên dự án khớp cả biến thể có đuôi không mở đầu bằng chữ số (2026-10-01).
- `location` của thẻ = vị trí của chính dự án (LLM trả, ≤ 4); của mục bản tin = nhãn chung ≥ 2 nguồn (≤ 5); `projects` bỏ hạ tầng/tiện ích (`normalize.NON_PROJECT_PREFIXES`) cả lúc gắn nhãn lẫn lúc lưu (2026-10-01).

## 7. Dự án lân cận

Xác định bằng **trùng địa danh**, không dùng toạ độ.

- `location` của bài là các địa danh LLM đọc thấy trong bài (tên đường/phố, khu đô thị, xã/phường, quận/huyện, tỉnh/thành,
  viết như trong bài), code chuẩn hoá. Không có file danh mục hành chính hay vùng tự định nghĩa nào — địa danh của dự án lấy
  thẳng từ `address` (xem §3.2).
- **Nhãn so khớp của dự án:** các phần địa danh của dự án đã chuẩn hoá, TRỪ phần cuối (tỉnh/thành) khi có ≥ 2 phần. Bài thuộc
  khu vực của dự án khi `projects` chứa tên dự án hoặc `location` giao với nhãn so khớp.
- **Tìm ứng viên:** truy vấn theo khu vực, cộng với những bài nhắc tới nhiều dự án cùng lúc.
- **Lúc đọc:** mỗi nhãn so khớp là một cấp, theo thứ tự trong địa chỉ từ hẹp ra rộng (vd `lê văn lương`, rồi `nam từ liêm`;
  không dùng tỉnh/thành), dừng khi có ít nhất 3 dự án, và loại chính dự án đang hỏi. Việc này tính lúc đọc nên không cần bảng
  lưu quan hệ lân cận.
- **Tên chuẩn** lấy từ ba nguồn: tên dự án của các tenant, catalog alias của agent, và các tên đã gặp trong kho raw.

## 8. Phía agent

Dữ liệu được gộp vào `kb_search` sẵn có, **không khai báo tool mới**.

- `kb_search` tìm thêm trong `public_web`, sau lượt tìm trong `<tenant>_documents`.
- Kết quả gộp theo thứ tự: dữ liệu đối tác đứng trước; dữ liệu ngoài đứng sau, được gắn nhãn là nguồn ngoài và kèm link.
- Câu hỏi về dự án lân cận thì lọc theo `location` từ cấp hẹp ra cấp rộng.
- File cần sửa phía agent: `src/noble_agent/agent/rag/kb_service_adapter.py`, `src/noble_agent/data/qdrant_search.py`.
- ⚠️ **BỎ Ý "portal thêm `public_web` vào token Qdrant" của bản thiết kế đầu.** Agent hiện đọc Qdrant
  bằng key đặt trong biến môi trường của chính nó (`QDRANT_API_KEY`/tương đương phía agent), KHÔNG dùng
  token do `enrollment/qdrant_jwt.py::ky_token_doc` phát cho pod — cơ chế đó tồn tại nhưng phạm vi token
  (`{"collection": "kb_<tenant>", "access": "r"}`) đã LỆCH tên thật của collection agent ghi/đọc
  (`<tenant>_documents`/`<tenant>_media`, không phải `kb_<tenant>`) TỪ TRƯỚC đợt này — xem
  `src/portal/modules/enrollment/ha_tang.py` (đoạn "VÌ SAO KHÔNG CHẠM QDRANT"). Sửa `qdrant_jwt.py` để
  thêm `public_web` vào một cơ chế đã không được dùng đúng cách sẽ không thay đổi gì cho agent thật; để
  ngoài phạm vi spec này, không phải việc bị quên.
- **Đợt này chưa có tra web trực tiếp trong hội thoại.** Kho không có câu trả lời thì agent xử lý như hiện nay.
- `kb_search` luôn bật, nên mọi tenant đều tự có tính năng này.

## 9. Chi phí ước tính mỗi tháng (100 dự án)

| Khoản | Ước tính |
|---|---|
| Search | 0 cho tầng whitelist; Gemini grounding cho bước 2 dưới trần 1.200/ngày, trong mức miễn phí 1.500 truy vấn/ngày (cần xác nhận tier/billing của Google project trước khi bật key) |
| Tải trang | 0 |
| LLM (qwen3.7-flash) | khoảng 2–3 USD — ước tính, chưa đo; mỗi lượt gọi ghi log số token để đo tuần đầu |
| Embed | 0 |
| Tổng | dưới 5 USD, chưa tính máy chủ |

## 10. Kiểm chứng

- **Unit test:** chuẩn hoá URL, location, projects; sinh id tất định; kiểm số nguồn [n]; nhận diện trang challenge; đọc sitemap
  và RSS.
- **Integration trên dev:** chạy container crawl với 3 domain rồi kiểm:
  - có hàng mới trong `public_data.web_pages`;
  - point trong `public_web` đủ 7 khoá;
  - `kb_search` trả về kết quả thị trường có link cho câu hỏi về Noble Palace Tây Thăng Long.
- **Bộ đánh giá:** khoảng 30 bài có đáp án chuẩn, để kiểm chất lượng gắn nhãn và tóm tắt của qwen3.7-flash. Bài thử 3 bài ngày
  29/09 đã cho thấy model này hay thêm nhận định ngoài bài.
- **Cổng hiện có:** `make check`, `make test-isolation`, `tests/test_module_boundaries.py`.

## 11. Còn mở

- **Luật "tenant thắng" (mục 6.1):** đang tạm áp cách "bỏ tin trái chiều". Hai cách khác chưa được chọn hay loại một cách tường
  minh: "ghi thêm một dòng về tin trái chiều", và "hiện cả hai ngang nhau".
- **Bên làm kênh Sale đọc dữ liệu qua đâu:** đọc thẳng `public_web`, hay qua một endpoint của portal.
- **Search ở bước 2:** nếu Gemini grounding thường xuyên không tìm đủ bài thì chuyển sang Serper (1 USD cho 1.000 truy vấn).
