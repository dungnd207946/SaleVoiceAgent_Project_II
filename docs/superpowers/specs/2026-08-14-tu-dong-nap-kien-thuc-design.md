# Tự động nạp kiến thức — bỏ nút, nháp có point, chunker hierarchical

**Ngày:** 2026-08-14 · **Nhánh:** `kb-tab` (cả ba repo) · **Trạng thái:** đã chốt, đang thi công
**Phạm vi:** `odyssey-portal-backend` · `odyssey-portal-frontend` · `odyssey-agent`

## 1. Vấn đề

Màn dự án BĐS có nút **"Nạp kiến thức cho agent"**. Người nhập liệu phải hiểu rằng sau khi bấm Lưu
vẫn còn một bước thứ hai, và quên bấm thì agent trả lời khách bằng dữ liệu cũ.

Yêu cầu: **bỏ hẳn nút đó** — nhập liệu xong là nội dung tự tới agent, người dùng không cần biết đến
khái niệm ingest/Qdrant.

## 2. Spec này LẬT hai quyết định đã có

**D1 của [`2026-08-11-nap-kien-thuc-cho-agent-design.md`](2026-08-11-nap-kien-thuc-cho-agent-design.md)**
— *"nạp kiến thức chỉ chạy khi người dùng bấm"*. Spec đó **giữ nguyên, không sửa**; hai lý do của nó
được giải quyết bằng cơ chế khác:

| Lý do của D1 | Cách đợt này giải quyết |
|---|---|
| Embed tốn tiền | Phép thoát sớm theo dấu tay nội dung đã có sẵn (§6.2 spec ingest). Lưu mà không sửa gì ⇒ không tốn lượt nhúng nào. Thêm phép gộp job đang chờ. |
| Nội dung do AI sinh phải qua mắt người | Van **hạ xuống cấp từng mục**. Mô tả ảnh: đường mô tả nháp đã cho người đọc **trước khi lưu**, cú bấm "Thêm" chính là cú duyệt. Chữ bóc bằng OCR: cờ chờ duyệt trên bảng `documents`. |

**`CHUNK_MAX_CHARS = 1800`** trong `kb/settings.py` — comment hiện tại ghi *"1800 ≈ 450 token, vừa
cửa sổ 512 của e5-large. Số cũ (800) xé vụn vô cớ."* Đợt này hạ về **1000**. Đây là một quyết định
ngược, **không phải một lần gõ nhầm** — phải giữ lý do trong code để người sau không "sửa lại".

Lý do hạ: chunker mới cắt theo **cấp tiêu đề** nên mỗi chunk là một đơn vị ngữ nghĩa thật, không
phải một đoạn cắt theo độ dài; ở chế độ đó chunk nhỏ cho độ chính xác tra cứu cao hơn, và
`section_path` bù lại phần ngữ cảnh mà chunk nhỏ mất.

## 3. Quyết định

| # | Quyết định |
|---|---|
D01 | Route ghi **tự đặt việc nạp** trong **cùng giao dịch** với lệnh Lưu ⇒ không thể "lưu xong mà việc không được đặt", và không cần cột `dirty` hay sweeper. |
D02 | **Gộp lúc đặt việc**: record đã có việc `queued` thì không đặt thêm. |
D03 | **MỘT chiến lược chunking duy nhất**, hierarchical: cắt theo `#`→`##`→…→`\n\n`→…; trần **1000**, overlap **100** (chỉ trong đoạn văn liên tục), ngưỡng gộp **300**. Bỏ cả ba chiến lược cũ. |
D04 | **Bảng markdown cắt theo HÀNG, lặp lại hàng tiêu đề + dòng phân cách ở mỗi mảnh.** Luật cũ ("giữ nguyên khối bảng dù vượt trần") tự phá chính nó ở trần 1000: bảng 40 hàng ra chunk ~5000 ký tự ≈ 1250 token, vượt cửa sổ 512 ⇒ model **cắt cụt phần đuôi**, im lặng. |
D05 | **Mọi nguồn phải là markdown có tiêu đề.** Dự án: `# <tên>` + **mỗi field một `##`**. Phân khu: `# <tên dự án>` + `## Phân khu <tên>`. Tài liệu: chữ bóc ra vốn đã là markdown. Không có bước này thì cây section phẳng và chunker không có gì để bám. |
D06 | **Dấu tay tính trên nội dung THUẦN, không gồm nhãn.** Đổi tên dự án ⇒ dấu tay **không đổi** ⇒ chỉ cập nhật payload, **không nhúng lại** một chunk nào. Trước đây đổi tên làm nhúng lại cả cây (116 record) trong khi nội dung không đổi một chữ. |
D07 | **Hàng nháp CŨNG có point**, cùng collection, `status` **hiệu lực** trong payload, agent lọc lúc đọc ⇒ công bố thành **tức thì**. |
D08 | **Ẩn / lưu trữ KHÔNG xoá point nữa** — chỉ đổi `status` trong payload. Chỉ `DELETE` mới xoá point. |
D09 | Đổi trạng thái hoặc đổi tên ⇒ **cập nhật payload theo filter**, không nhúng lại. Một lời gọi mỗi collection cho cả dự án. |
D10 | Mệnh đề lọc phía agent **fail-closed**: `status == 'published'`, **không** `!= 'draft'` (ba giá trị, `!=` để `archived` lọt). Point **thiếu** khoá `status` bị ẩn ⇒ **bắt buộc nạp lại toàn bộ ở pha 1**. |
D11 | **VLM tạo mô tả ảnh đúng MỘT lần: lúc tải ảnh lên lần đầu.** Bỏ nút "Tạo lại mô tả" và nhánh tự tả lại khi đổi ảnh. VLM **không** bị bỏ — chỉ bỏ nhánh chạy-lại-sau-khi-lưu. |
D12 | **Không gọi VLM cho ảnh `vi_tri` và `mat_bang`** — bản đồ và bản vẽ, mô tả ra chữ không có giá trị tra cứu. Vẫn được nạp, chỉ là mô tả rỗng. |
D13 | **Resize trước MỌI lời gọi VLM.** `clients/vlm.py` hiện **không có một phép resize nào** — ảnh 98 MB đi thẳng sang model, đúng kiểu lỗi đã đo trên đường nhúng thị giác. Áp cho cả đường mô tả ảnh và đường OCR (render `scale=2`, tới 20 trang). |
D14 | **Tách việc sinh ảnh thu nhỏ ra khỏi chặng mô tả** — hai việc không liên quan đang nằm cùng một nhánh. Áp cho **cả ảnh và tệp** (trang 1 của PDF). Việc thumb **tự đặt việc nạp** khi xong. |
D15 | **Van duyệt chỉ áp cho chữ bóc bằng OCR** (PDF scan, ảnh CSBH). PDF có lớp chữ / docx / xlsx do thư viện bóc ⇒ chính xác ⇒ nạp ngay. Nguyên tắc: *model sinh ⇒ người xem; thư viện bóc ⇒ tự động.* |
D16 | **Tour 360 sang collection `media`.** Ở collection `documents` link nằm trong text nên LLM phải **chép lại** một URL dài nhiều tham số — chép sai là chuyện sẽ xảy ra. Ở media, link đi trong payload và client render, LLM không chạm vào chuỗi. |
D17 | **CSBH chỉ ở tab Tài liệu**, và dù là ảnh thì vẫn vào **collection documents**; ingest **OCR** ra chữ; trả lời **gửi kèm ảnh/tệp nguồn**. Di trú 34 hàng ảnh `csbh` sang bảng `documents`, bỏ `csbh` khỏi danh mục ảnh (còn **7**, đúng con số đã khai). |
D18 | `kb_search` **trả kèm tệp** qua `items[]`, dùng lại **danh sách cho phép** đã có của bộ điều phối công cụ (docstring của nó viết đúng chữ *"Add a new media tool here"*). |
D19 | **Bật retry cho MỌI loại việc trong phạm vi KB**, kèm **thời hạn mỗi việc** và **thu hồi việc `running` quá hạn**. Không có ba cái này thì chỉ báo mới có một trạng thái chết (xem §5). |
D20 | **Không fallback sang model nhúng khác.** Cùng số chiều **không** có nghĩa cùng không gian vector — đã đo: cùng collection, truy vấn e5 ~**0.82**, truy vấn Gemini ~**0.03**. Service chết ⇒ retry + hoãn ⇒ hết lượt thì việc thất bại và chỉ báo hiện lỗi. Ghi vector sai không gian tệ hơn thất bại, vì thất bại thì **nhìn thấy được**. |
D21 | **Ba route phục vụ tệp đổi sang chuyển hướng 307** tới URL kho có hạn, **giữ nguyên hình dạng đường dẫn** (nó đã nằm trong payload đã ghi, trong cột `media.public_url`, và trong link đã gửi cho khách). |
D22 | **Van duyệt bỏ qua được bằng một cờ TƯỜNG MINH trong request** (`autoApprove`, mặc định `false`), **không** bằng cách nhìn xem ai gọi. Xem §12. |
D23 | **Tải tệp giữ hai lượt gọi** (`POST uploads` → khoá, rồi `POST media/documents`). Không làm endpoint gộp multipart. Xem §12. |
D24 | **Tài khoản dịch vụ / API key: NGOÀI phạm vi đợt này**, dù đã xác nhận là lỗ thật. Xem §12. |

## 4. Chunker mới

```
0  DỰNG NỘI DUNG CÓ TIÊU ĐỀ   (tầng dựng nội dung, không phải chunker) — D05
1  DỰNG CÂY      nhận diện dòng tiêu đề (# … ######) và khối bảng (| … |)
                 → cây section: { cấp, tiêu đề, đường dẫn tổ tiên, khối con }
2  GẤP TỪ LÁ LÊN section TOÀN BỘ ≤ trần → MỘT chunk (chống cắt vụn)
                 section < ngưỡng → gộp với section kế tiếp CÙNG CHA
                 (không gộp xuyên cha: hai section khác cha nói hai chuyện)
3  CẮT TRONG SECTION  ranh giới từ MẠNH tới YẾU:
                 tiêu đề con → \n\n → \n → ". " "! " "? " → "; " ": " ", " → dấu cách
                 BẢNG: cắt theo hàng, LẶP hàng tiêu đề + dòng phân cách mỗi mảnh (D04)
4  GẮN NHÃN     text nhúng = tiền tố rút gọn "<tên dự án> — <cấp cuối>" + nội dung thuần
                 payload    = project_name + section_path (đường dẫn đầy đủ)
                 dấu tay    = băm CHỈ nội dung thuần (D06)
```

**Bước đo bắt buộc trước khi chốt số:** chạy trên toàn bộ dữ liệu 4 tenant, in phân bố độ dài chunk,
tổng số chunk trước/sau, số chunk dưới ngưỡng và vì sao không gộp được, số bảng bị cắt và số mảnh
mỗi bảng, **độ dài tiền tố trung bình và % trần nó chiếm**.

## 5. Việc kẹt `running` — chỗ phá chỉ báo

Hàng đợi ghi `state='running'` trong **một giao dịch riêng** rồi mới gọi handler; bảng việc **không
có cột số lần thử**; **không có** hàm thu hồi, **không có** thời hạn. Nên một việc bị giết giữa đường
(SIGTERM lúc deploy trong khi handler đang chặn) hay treo ở một lời gọi mạng sẽ **kẹt `running` mãi**.

Chỉ báo của đợt này suy *đang chạy* từ đúng những hàng `queued|running` ⇒ một việc kẹt làm dấu quay
**xoay vĩnh viễn**, và người dùng không có nút nào bấm (nút Thử lại chỉ hiện ở nhánh lỗi).

Đã có sẵn một **khung nhìn** liệt kê việc `running` quá 15 phút — nhưng **không gì đọc nó**. Cho nó
một đường: quá hạn ⇒ về `queued` (nếu còn lượt) hoặc `failed`.

**Nghịch lý dọn cùng lúc:** lớp nhúng có cổng giới hạn 4 lời gọi song song, nhưng đó là **cổng chết**
— worker chạy một việc một lúc, mỗi việc dựng client mới, và trong một việc các lời gọi đi tuần tự;
cổng không bao giờ tới 2. Tốc độ phải đến từ **nhiều bản worker** (hàng đợi dùng `SKIP LOCKED`, và
compose cố ý không đặt tên container để cho phép nhân bản). Ghi vào bước nạp lại pha 1.

## 6. Chỗ còn chặn event loop (rà 2026-08-14)

Đường KB async gần như đúng hết — không có `requests`, `time.sleep`, `boto3` đồng bộ, `QdrantClient`
đồng bộ, hay SDK đồng bộ nào. Hai chỗ chặn thật:

| | Chỗ | Vấn đề |
|---|---|---|
🔴 | `storage/thumbnail.py:74` | `to_webp(goc)` **không** qua thread — Pillow mở ảnh + LANCZOS + encode WebP `method=6` (*"nén chậm nhất"* theo comment của chính nó) chạy trên event loop. Là **ngoại lệ duy nhất**: hai chỗ gọi `to_webp` khác đều đã `to_thread`. Và nó là **lượt encode thừa** — ảnh nội bộ đã là WebP 1600px do một lượt đã offload sinh ra, chỗ này giải mã và encode lại ở 512px. |
🔴 | `realestate/router.py:1877` | `sha256` của **tối đa 25 MB** trong request handler, trên event loop dùng chung với mọi API khác. |
🟠 | `clients/vlm.py:66,71` · `clients/embed.py:137` | `base64` ảnh nhiều MB trên loop; đường OCR làm **20 lượt tuần tự**. |

**Rò `httpx.AsyncClient` — 4 chỗ đi tắt** khỏi context manager vốn được viết đúng để chặn việc đó
(docstring của nó ghi: 116 job mỗi job bỏ lại một client là cách nó từng chết). Đợt này chạm đúng
những chỗ đó ⇒ sửa cùng lúc.

**Không có test nào canh việc offload** (`to_thread` xuất hiện 0 lần trong `tests/`). Khuôn để copy:
test canh `SKIP LOCKED` dùng `asyncio.wait_for` trên **chính hằng số SQL của production**.

## 7. Ba pha deploy — thứ tự bắt buộc

| Pha | Repo | Làm gì | Sau pha |
|---|---|---|---|
1 | backend | chunker mới · nội dung có tiêu đề · payload mới (**vẫn ghi cả `section`**) · payload index · 2 chỗ chặn P0 · resize VLM · đóng client rò. **Chưa** nạp hàng nháp. Rồi **nạp lại toàn bộ 4 tenant**. | mọi point có `status='published'`; agent chưa lọc ⇒ hành vi không đổi |
2 | agent | lọc `status == 'published'` · đọc `section_path` thay `section` · thẻ `tour` · `items` cho `kb_search` | mọi point đã có `status` ⇒ hành vi không đổi |
3 | backend + frontend | nạp hàng nháp · đường đổi status/nhãn · retry + thu hồi · tách việc thumb · 10 route đặt việc · van OCR · tour 360 · di trú CSBH · 307 · bỏ nút + chỉ báo mới · **bỏ khoá `section`** | xong |

Đảo 1↔2 ⇒ RAG câm cho tới khi nạp xong. Đảo 2↔3 ⇒ nội dung nháp tới khách giữa hai lần deploy.
Portal deploy **hai lần, cố ý** — phương án gộp bằng một công tắc bật tay đã bị loại: repo này có
đúng tiền lệ đó (publish từng trả 202 suốt trong khi worker chưa hề được deploy).

## 8. Giao diện

Không còn nút nạp, không có badge nhiều trạng thái. Mỗi dự án chỉ hai thứ có thể hiện:

```
◐ Đang nạp kiến thức cho agent…              có việc chờ/chạy — người không làm gì
✕ Lỗi nạp kiến thức cho agent · [Thử lại]    có mục lỗi sau 3 lượt, HOẶC có mục lệch
                                              mà không việc nào chờ (một việc bị mất)
(không hiện gì)                               mọi trường hợp còn lại
```

Chỉ báo **không kèm số**. Trạng thái bình thường **không nói gì** — một nhãn khẳng định điều mặc
định chỉ dạy người ta rằng có thứ cần theo dõi.

Còn **hai** nút cần người bấm: **Duyệt** (chữ đọc từ ảnh, ngay tại ô đó) và **Thử lại**.
Xoá dự án đổi sang **popup**. Từ vựng: *"nạp kiến thức cho agent"* là cách nói **đúng**; bộ bị cấm
vẫn là "index" · "kho vector" · "đồng bộ" · "Qdrant" · "embed".

## 9. Lỗ phát hiện khi kiểm kê — sửa cùng đợt

**Ảnh cover/map chưa từng được enqueue.** Chúng được tạo *bên trong* route dự án và route phân khu
(`_gan_anh_cover_map`), danh mục `tong_quan`/`mat_bang` — **cả hai thuộc phạm vi nạp** — nhưng không
route nào đặt việc gì cho chúng. Chúng chỉ lên kho nhờ việc cấp dự án liệt kê mọi ảnh published, tức
đúng cái việc đang bị bỏ khỏi giao diện. Bỏ sót ⇒ **ảnh bìa dự án ngừng tới agent**. Hàm đó hiện
không trả về gì nên 4 nơi gọi không biết vừa tạo hàng nào ⇒ cho nó trả danh sách id.

**Portal không ghi hai khoá mà agent đang đọc** — `project_name` và `updated_at`. Agent render chúng
trong tiêu đề mỗi khối ngữ cảnh ⇒ hôm nay mọi khối **thiếu tên dự án và thiếu mốc thời gian**, im
lặng, và không test nào ở hai đầu bắt được (test phía agent tự dựng dict hit nên luôn xanh).

## 10. Hợp đồng payload

Xem [`docs/contracts/payload-qdrant.md`](../../contracts/payload-qdrant.md) — hợp đồng hai đầu,
bản đối chiếu nằm ở cả repo agent.

## 11. Ngoài phạm vi, cố ý

- Màn `/kb` "Tài liệu tra cứu" — endpoint tải tệp của nó chưa tồn tại ở backend.
- Đổi tên khoá `project_id` (nó mang mã neo, đặt tên sai) — đường dọn an toàn đã có.
- Công bố từng phần (mở ô trạng thái ở mức phân khu/tài liệu/ảnh).
- `handle_reconcile` — chỉ báo *có lỗi* đã cho thấy lệch và có nút chữa.
- Phân quyền thật cho route tệp công khai — 307 chỉ đưa byte ra khỏi tiến trình API, **không** thêm
  xác thực. Thêm xác thực sẽ làm chết link đã nằm trong payload và đã gửi cho khách.
- Hai vector dày song song để chịu được embed service chết (phương án B của D20).
- Dọn file local sang `experiments/` — commit riêng, làm sau. Trừ dòng `.gitignore` đang chưa commit.
- `units` vẫn không nhúng vector.
- **Tài khoản dịch vụ / API key** (D24) — xem §12.
- **Endpoint gộp tải tệp một lượt** (D23) — xem §12.

## 12. Nhập liệu qua API — ba quyết định

Đợt này bỏ nút nạp khỏi giao diện, nên câu hỏi "còn nhập qua API thì sao" trở thành câu hỏi thật.
Câu trả lời chung: **được, không cần đường riêng** — móc nối đặt việc nằm ở **tầng route**, không ở
nút bấm, nên mọi client gọi cùng bộ endpoint đều được đối xử như nhau. Ba chỗ cần quyết:

### D22 — bỏ van duyệt bằng cờ tường minh, không bằng danh tính người gọi

Van duyệt (D15) tồn tại vì chữ do model đọc từ ảnh **có thể sai**. Nó trả lời câu **"đã có người
đọc chưa"**, KHÔNG phải câu "gọi từ đâu". Hai câu đó hôm nay trùng nhau — chỉ vì hôm nay client duy
nhất là web — nhưng chúng tách ra ngay khi ai đó dựng một giao diện chạy bằng khoá máy.

| Cách | Phán |
|---|---|
Suy từ danh tính (khoá máy ⇒ bỏ qua, phiên người ⇒ bắt duyệt) | **Không.** Giao diện chạy bằng khoá máy sẽ tự tắt van mà không ai biết; ngược lại script chạy bằng tài khoản người lại bị chặn. Cả hai đều là kết luận sai từ một dấu hiệu sai. |
Bỏ van hẳn | **Không.** Mất luôn khả năng chặn với đường nhập tay — đúng chỗ cần nó nhất. |
**Cờ `autoApprove` trong body, mặc định `false`** | **Chọn.** Web không gửi ⇒ hành vi không đổi. Script nhập hàng loạt gửi `true` ⇒ vào thẳng. Nhật ký ghi **ai đã tự nhận trách nhiệm**. |

Áp cho `POST`/`PATCH` tài liệu — chỗ DUY NHẤT có van. Không có cờ tương ứng cho mô tả ảnh: đường
mô tả không có van nào để bỏ (người gọi tự truyền `caption`).

Lý lẽ phụ nhưng quyết định: không có cờ này thì người viết script vẫn gọi endpoint duyệt trong một
vòng lặp — **cùng kết quả**, thêm một lượt gọi mỗi tài liệu, và mất hẳn dấu vết phân biệt "chủ ý
bỏ qua" với "bấm duyệt cho xong".

### D23 — tải tệp giữ hai lượt

`POST /realestate/uploads` → khoá → `POST /projects/{code}/media|documents`. Ba lý do giữ nguyên,
hai trong đó đã ghi sẵn trong docstring của route upload:

- Form dự án có 2 ảnh, form căn tới **6**. Gộp multipart vào lệnh Lưu ⇒ mỗi lần Lưu là một request
  vài chục MB và người dùng **mất trắng cả form** nếu nó đứt.
- Khoá **content-addressed** (`sha256`) ⇒ tải lại cùng một tệp cho **cùng một khoá** ⇒ gọi lại sau
  khi mất mạng là an toàn, không sinh bản sao.
- Endpoint gộp sẽ là **đường ghi thứ hai** cho cùng loại dữ liệu: kiểm tra hợp lệ, tiền tố tenant
  và đặt việc đều phải có bản sao. Đúng vấn đề mà `kb/ops/enqueue.py` được lập ra để tránh.

Với nhập hàng loạt, hai lượt gọi mỗi tài liệu không phải chi phí đáng kể — đó là việc chạy nền.
Nếu sau này thật sự vướng, thêm một endpoint mỏng **gọi lại đúng hai đường đã có** là việc rẻ và
cộng thêm, không phá gì.

### D24 — xác thực cho máy: lỗ thật, nhưng để đợt riêng

Đã kiểm: Portal có **đúng một cách xác thực — cookie phiên người dùng, TTL 12 giờ**
(`core/auth/session.py`), quyền đọc từ `control.memberships` mỗi request. **Không có** API key,
không có tài khoản dịch vụ. Nên hệ thống ngoài muốn ghi phải **mượn tài khoản một người thật**:

| | Hệ quả |
|---|---|
Nhật ký | Mọi thay đổi ghi tên người đó, dù máy làm |
Bí mật | Mật khẩu một nhân viên nằm trong cấu hình script |
Nghỉ việc | Khoá tài khoản ⇒ tích hợp **chết im lặng** |
Phạm vi | Script được **đúng** quyền của người đó, không thu hẹp được |

**Không làm trong đợt này.** Nó là thiết kế riêng (cấp phát, xoay khoá, thu hẹp phạm vi, màn quản
lý) và đụng tầng xác thực dùng chung cho **toàn Portal**, không riêng tab kiến thức. Nhét vào đây
là biến một đợt về nạp dữ liệu thành một đợt về bảo mật.

**Cách chống đỡ tạm:** một tài khoản riêng cho tích hợp (`bot-import@…`) gán đúng quyền ghi danh
mục. Vẫn xấu, nhưng có ranh giới và **thu hồi được độc lập** — khác hẳn mượn tài khoản người thật.

## 13. Kiểm chứng chạy thật ở local (2026-08-15)

Chạy trên stack `docker-compose.local.yml` (Postgres 5442 · Qdrant 6343 · MinIO 9002), API +
worker thật, **embed service GIẢ** (`scratchpad/embed_gia.py` — vector băm nội dung, đúng số
chiều 1024/768). Vector giả nên KHÔNG kết luận gì về chất lượng tìm kiếm; nó kiểm hình dạng
payload, đường đặt việc và phép so dấu tay.

`alembic upgrade head`: `0927`→`0930` chạy sạch trên DB thật, một head duy nhất.

| Kiểm | Kết quả |
|---|---|
Tạo dự án qua API | `kb_index` tự vào hàng đợi, worker nạp xong, **không bấm nút nào** |
Payload `documents` | đúng bộ khoá hợp đồng + `section` (bản trùng của pha 1, bỏ ở pha 3) |
Payload `media` | đúng **10** khoá |
**Công bố** | `kb_doi_co`, `status`→`published`, **0 lượt embed** |
**Đổi tên** | `kb_doi_nhan`, `project_name` + tiền tố trong `text` đổi, **0 lượt embed** |
**Lưu trữ** | `status`→`archived` ở CẢ hai collection, **số point KHÔNG giảm** (D08) |
Tour 360 | 1 hàng `media` `tour_360` + 1 point ở `<tenant>_media`, link nguyên văn |
Chunker | `section_path` 3 cấp (tiêu đề tài liệu → `#` → `##`), bảng giữ nguyên hàng tiêu đề |
Trạng thái hiệu lực | hàng `published` dưới dự án `archived` ⇒ payload `archived` (đúng bảng §… ) |
Mệnh đề lọc agent | point `archived` ⇒ agent thấy **0**; point thiếu khoá `status` ⇒ cũng **0** |
Endpoint duyệt | cờ bật ⇒ `{"approved": true}` + đặt việc nạp; gọi lại ⇒ `{"approved": false}` |
Xoá dự án | cascade dọn sạch point của cả cây, kể cả point tour |

### Hai điều đo được, không suy ra được

**1. Nạp lại toàn bộ ở pha 1 là bắt buộc — có số.** Trước khi nạp lại, trên DB local:
**27/30** point `documents` và **97/98** point `media` KHÔNG có khoá `status`. Với mệnh đề
fail-closed, agent sẽ thấy gần như không gì. Sau khi `sync-kb?mode=full` cho MỌI dự án:
**0** point có hàng Postgres sống mà thiếu `status`.

**2. Point mồ côi không bị nạp lại dọn — nhưng fail-closed tự ẩn chúng.** 14 point
`documents` và 97 point `media` không có hàng Postgres nào phía sau (rác từ các lượt thử
trước). Nạp lại không chạm tới chúng vì nạp lại đi từ Postgres. Chúng thiếu `status` nên
agent không thấy — chỉ tốn dung lượng. Muốn sạch thì phải drop-rồi-dựng-lại collection.

### Lỗi tìm được nhờ chạy thật

`handle_doi_nhan` chỉ đổi `project_name` trong payload, để nguyên tiền tố tên dự án nằm
trong `text`. Nhưng **LLM đọc `text`**, nên tiêu đề khối mang tên mới trong khi thân bài vẫn
nói tên cũ — khách nghe được tên cũ. Đã sửa: `QdrantStore.doi_ten_trong_text` ghi lại tiền tố
từng point (vẫn 0 lượt embed). So khớp NGUYÊN VĂN với tiền tố cũ dựng từ `ten_cu` do route
truyền vào, không đoán theo hình dạng — một chunk hoàn toàn có thể mở đầu bằng một dòng ngắn
rồi dòng trống, và đoán sai ở đó là ghi đè nội dung khách. Point không khớp thì **ghi log
cảnh báo** thay vì bỏ qua im lặng: `text` mang tên cũ vĩnh viễn phải nhìn thấy được.

⚠ VECTOR vẫn nhúng từ chuỗi mang tên cũ tới lần nội dung thật đổi — đánh đổi đã chấp nhận
(§Luồng 2): đường tìm theo tên dự án đi qua `find_project` (tên → mã) rồi lọc theo mã.

### Ba lỗi nữa chỉ lộ ra khi chạy thật

**1. `thumb_url` của tài liệu rỗng vĩnh viễn.** `0928` thêm cột, `handle_thumb` ghi vào cột,
`resolve_text` đọc `row["thumb_url"]` — nhưng `thumb_url` KHÔNG có trong `extra_cols` của spec
`documents`, nên đường đọc không select cột và `row.get()` trả `None`. Cột có dữ liệu, payload
có khoá, khoá rỗng, **không lỗi ở đâu cả**. Đã thêm vào `extra_cols` + test ghim.

**2. `file_name` mang tiền tố loại.** `documents.title` lưu `"CSBH — Bảng giá Q3"` và payload
rơi về `title` (bảng này không có cột `file_name`), nên tên hiện cho khách là một mã nội bộ.
Giao diện vẫn tách tiền tố ra nên người dùng chưa từng thấy nó — chỉ khách của agent thấy.
Đã bỏ tiền tố qua `split_title`.

**3. `PUBLIC_BASE_URL` là cổng SỐNG-CHẾT của cả tính năng gửi kèm tệp.** Chưa cấu hình thì
`public_url_of()` trả **rỗng** (cố ý: thà agent coi là "không có tệp" còn hơn gửi link không mở
được), nên `file_public_url` và `thumb_url` đều rỗng và đường gửi kèm **im lặng không làm gì**.
`kiem_base` từ chối `localhost` — đúng, một link localhost trong payload gửi cho khách là vô
dụng. Phải cấu hình biến này ở mọi môi trường có agent trả lời khách.

### Đường CHƯA kiểm được ở local

- **OCR ảnh / PDF scan** — cần VLM thật (đường thư viện bóc đã kiểm bằng PDF có lớp chữ).
- **Chất lượng tìm kiếm sau chunker mới** — embed giả nên hai câu gần nghĩa cho hai vector
  không liên quan. Bước đo ở §4 vẫn phải chạy với embed thật.
- **307 phục vụ tệp** — cần host kho mở được từ Internet (cổng kiểm chứng của D21).
