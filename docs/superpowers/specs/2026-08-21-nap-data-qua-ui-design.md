# Nạp data qua UI — sửa 8 điểm ở màn nhập dữ liệu BĐS

Ngày: 2026-08-21 · Nhánh: `feat/ingest-ui` (cả hai repo) · Màn chính: `/pform`

## 1. Bối cảnh

Tám nhận xét từ người dùng khi nhập một dự án qua `/pform` (bảy đợt đầu, cộng issue 8 về
câu chú thích thừa). Bốn trong số đó không phải yêu cầu tính năng mới mà là **chỗ code
đang nói sai về chính nó** — tab bị khoá rộng hơn lý do kỹ thuật, dấu `*` trên một trường
đã hết bắt buộc, nút xoá tồn tại nhưng vô hình, câu chú thích tả cơ chế nội bộ thay vì
giúp người điền. Spec này ghi cả tám cùng với những gì **đo được** trong code và trên dữ
liệu thật, để phần thi công không phải đoán lại.

## 2. Hiện trạng đo được

### 2.1 Chín tab, ba hạng — không phải "1 mở, 8 khoá"

`DuAnForm.tsx` khoá 8/9 tab khi chưa có `?code=`, lý do ghi trong docstring là *"tất cả
cần một dự án ĐÃ TỒN TẠI"*. Chỉ đúng với 6 tab:

| Hạng | Tab | Ghi vào |
|---|---|---|
Cột của hàng `projects` | Tổng quan (16 ô + `coverMedia`) · Ảnh 360 (`link360`) · Vị trí (`region`/`address`) | `POST /projects` — **đã nhận đủ cả 19 ô trong một request** |
Bộ sưu tập con | Phân khu · Quỹ căn · Tài liệu · Media · Tiến độ · Mặt bằng · vùng ảnh trong Vị trí | `POST /projects/{code}/…` — cần dự án tồn tại |

`ProjectIn` (`router.py:619`) khai sẵn `region`, `address`, `link_360`, `cover_media`,
`map_media`; type `DuAnGhi` (`api.ts:186`) cũng đã mang đủ. **Vị trí và Ảnh 360 bị khoá
không vì lý do kỹ thuật nào** — chỉ vì UI xếp chúng ra sau.

### 2.2 API đòi đúng một field

`ProjectIn.project_code: str = Field(alias="projectCode", min_length=1)`. Mọi field khác
có default. Dấu `*` trên **Tên thương mại** / **Khu vực** tới từ luật *phát hành*
(`completeness.ts`), không từ API. Dấu `*` trên **Tổng quan** là **dấu chết**: backend bỏ
`overview` khỏi `BAT_BUOC` ngày 2026-08-18 (`completeness.py` docstring), `completeness.ts`
đã theo, nhưng `TongQuanTab.tsx` vẫn vẽ `batBuoc` cho nó.

### 2.3 Mã dự án: nửa hệ thống đã tự sinh nó

`modules/ingest/chieu.py:72` — `ung_vien_ma("ERP-PRJ-14")` → `ERP_PRJ_14`
(`_KHONG_HOP_LE = [^A-Z0-9]+` → `_`, cắt 40 ký tự), rồi `_ma_du_an_moi()` thêm hậu tố
`_2`…`_99` nếu đụng. Đường nạp ngoài **chưa bao giờ** để khách gửi `project_code`.
Docstring nêu lý do suy từ tên chứ không ngẫu nhiên: mã hiện trên giao diện, đi vào SQL
của agent, và vào tên chunk trên Qdrant.

Hàm này **không có test nào** dù docstring tự nhận là hàm thuần test được.

### 2.4 Xoá media: có, nhưng 4 bước và bước đầu vô hình

`VungMedia.tsx` — mỗi ảnh có đúng một nút overlay `✎ Sửa` với class
`opacity-0 group-hover:opacity-100`. Xoá nằm trong `SuaMedia.tsx` sau một xác nhận. Đường
đầy đủ: hover → `✎ Sửa` → hộp thoại → Xoá → xác nhận. Trên thiết bị cảm ứng không có
bước đầu. `OMedia` (ảnh đơn, vd Ảnh cover) thì có nút *"Bỏ ảnh cover"* chạy tốt. Tab
**Ảnh 360** không có nút xoá nào — phải vào Sửa rồi xoá trắng ô.

### 2.5 Trạng thái chỉ sống trong một tab

`projects.status` là ô `OChon` bên trong form của `TongQuanTab`, lưu chung với 18 ô kia.
Backend PATCH dùng `_tach_payload` = `model_dump(exclude_unset=True)` (`router.py:789`),
nên **PATCH riêng `{status}` là hợp lệ** và không đụng ô nào khác.

`zones` · `units` · `documents` · `media` mỗi bảng có `status` **riêng của nó** — một ô
trạng thái treo cố định trên hàng tab có thể bị đọc thành trạng thái của thứ đang xem.

### 2.6 Hệ màu không còn sắc nhạt hơn

`theme.css:87-91` — `--color-muted-3` **hiện là cùng giá trị** với `--color-muted-2`
(`--color-n7` = `#666c76`). Sắc cũ `#a0a4ab` bị bỏ vì tương phản **2.50**. Đo lại
`#666c76` trên mặt thẻ `#fffefc`: **5.25:1**. Ngưỡng AA cho chữ thường là 4.5:1 — dư
0.75, tức nhạt thêm được nhưng gần như không thấy. Nhạt **thấy được** phải xuống ~3:1,
dưới AA.

## 3. Quyết định

| # | Issue | Quyết định |
|---|---|---|
1 | tab bị khoá lúc tạo | **Không khoá tab nào.** 9 tab bấm được từ đầu. Dự án nháp dựng **lười** — chỉ ghi khi người dùng làm việc đầu tiên cần tới nó |
2 | câu hướng dẫn "Tạo dự án trước" | **Xoá hẳn** `TEN_TAB_CON` + đoạn `{!code && …}` ở `DuAnForm.tsx` và hằng `VI_SAO_KHOA_TAB` ở `tabDuAn.ts` — sau (1) nó thành câu sai |
3 | text ví dụ | **Nghiêng + 13px, GIỮ nguyên độ tương phản.** Chỉ áp cho placeholder (`goiYTrongO`), không áp cho câu hướng dẫn (`goiY`) |
4 | không xoá được ảnh | **Hai nút `✎` và `✕` luôn hiện** ở góc mọi ảnh (phương án A). Xoá còn 2 bước. Không làm chọn-theo-lô |
5 | trạng thái chung | **Chip màu ở cột phải hàng tab**, nhỏ (11px), bấm mở menu, PATCH riêng `{status}` |
6 | field required | **Hai tầng, đừng lẫn.** Tầng *nhập*: dự án `name` · phân khu `name` · căn `unitCode` + `productType` — chỉ bấy nhiêu có dấu `*`. Tầng *phát hành*: năm trường + thước đo mềm 12 trường, xem §3.5 |
7 | UI đẹp hơn | Hai đầu **dán cố định**, chỉ vùng ô cuộn. Giữ chế độ Xem/Sửa. Thanh đáy thêm thước **Độ hoàn thiện n/12** |
8 | câu chú thích thừa | **Cắt 4, giữ 5, gộp 2** theo luật ở §3.4b — không cắt theo cảm giác, `goiY` là `aria-describedby` |

### 3.1 Vì sao mã dự án tự sinh

Ô "Mã dự án" **biến mất khỏi form**. Mã suy từ **Tên thương mại** bằng đúng hàm mà đường
nạp ngoài đang dùng — một luật, hai đường vào. "Vinhomes Ocean Park 2" →
`VINHOMES_OCEAN_PARK_2`.

Đổi lại: **mã bất biến sau khi tạo** (`ProjectPatch` không có ô đó; migration `0400`
không có `ON UPDATE CASCADE`), nên đổi tên dự án về sau **không** đổi mã. Chấp nhận vết
này và bù bằng cách **hạ mã xuống thứ nội bộ**: breadcrumb hiện TÊN, mã tụt xuống một
chip xám nhỏ. Đã cân nhắc cho đổi mã (thêm `ON UPDATE CASCADE` + `projectCode` vào
`ProjectPatch` + đồng bộ `anchor_code` bên Qdrant) và **loại** — một lượt đổi mã hỏng
giữa đường để lại KB trỏ sai anchor, im lặng.

`ung_vien_ma("__ALL__")` → `"ALL"` (dấu `_` bị strip), nên mã tự sinh **không bao giờ**
đụng sentinel `__ALL__`.

### 3.2 "Không field nào required" nghĩa chính xác là gì

Không phải zero field. Là **không ô nào chặn người dùng bắt đầu**. Vẫn cần đúng một thứ ở
đúng một thời điểm — Tên thương mại, lúc dự án được khai sinh, vì mã suy từ nó. Khác biệt
với hôm nay: nó được hỏi **lúc cần**, không phải một dấu `*` đứng chờ ngay khi mở form,
và các trường *cần để phát hành* nói bằng chữ ở thanh đáy chứ không bằng dấu đỏ.

### 3.3 Vì sao không nhạt thêm ở issue 3

Xem §2.6. Nghiêng + nhỏ đã đọc ra *"đây là ví dụ, không phải dữ liệu của bạn"* — đúng
mục tiêu — mà không đổi lại bằng khả năng đọc. Nhạt + nhỏ là dồn hai bước cùng chiều
xuống dưới ngưỡng AA.

### 3.4 Chống đọc nhầm chip trạng thái

Chip dùng `aria-label="Trạng thái dự án"`, và menu mở ra có tiêu đề *"Trạng thái dự án"*.
Không thêm chữ vào chip (người dùng chọn bản nhỏ nhất). Rủi ro còn lại được nhận: ở tab
Quỹ căn, chip nói về dự án còn mỗi căn có status riêng — chấp nhận, vì cột phải hàng tab
là chỗ người dùng chỉ định.

### 3.4b Dọn câu chú thích dưới ô (issue 8)

Luật để quyết, chứ không phải một danh sách sẽ mục: **cắt** câu chỉ nói lại nhãn, hoặc chỉ
tả cơ chế nội bộ (dữ liệu rơi vào bảng/danh mục nào, app lọc thế nào). **Giữ** câu cảnh báo
một cái sai đắt, hoặc nói một hệ quả người dùng không tự thấy được.

| Chỗ | Câu | Quyết |
|---|---|---|
`TongQuanTab:208` Ảnh cover | *"Lưu vào danh mục Tổng quan và gán làm ảnh đại diện dự án"* | **cắt** — người dùng bấm ô tên «Ảnh cover», không cần biết nó rơi vào danh mục nào |
`CanForm:305` Tầng | *"Căn nằm ở tầng số mấy"* | ~~cắt~~ → **GIỮ**. Quyết định ban đầu SAI, `realestate-uform.test.tsx:115` đã đỏ và nó đúng: câu này với *"khác ô trên"* là một CẶP phân biệt «Căn ở tầng» / «Số tầng của căn». Cắt một nửa là để câu còn lại trỏ vào thứ không tự giải thích |
`TaiLieuTab:468` Loại | *"Loại quyết định tài liệu nằm ở nhóm nào khi lọc"* | **cắt** — tả cơ chế lọc của chính app |
`Anh360Tab:57` Link 360 | *"Kuula, Matterport, hoặc bất cứ dịch vụ nào…"* | **cắt** — placeholder đã là `https://kuula.co/…` |
`TongQuanTab:186` Tiện ích | *"**Chỉ mô tả bằng chữ.** Ảnh tiện ích đặt ở tab Media…"* | **cắt nửa đầu** — ô text thì đương nhiên là chữ; nửa sau là chỉ đường thật |
`TongQuanTab:124` Mã dự án | *"Không đổi được sau khi tạo"* | **tự mất** — ô bị bỏ (§3.1) |
`TongQuanTab:258` · `CanForm:362` | *"Nguyên đồng, không phải tỷ"* | **giữ** — chống sai 9 chữ số |
`TaiLieuTab:481` Tệp đính kèm | *"…ảnh và PDF scan cần bấm Duyệt trước khi agent dùng"* | **giữ** — hệ quả không tự thấy |
`CanForm:317` Số tầng | *"Biệt thự/duplex có nhiều tầng — khác ô trên"* | **giữ** — hai ô «tầng» cạnh nhau |
`TongQuanTab:199` · `PhanKhuTab:234` · `TaiLieuTab:458` | ba câu *"Agent đọc/trích dẫn đoạn này…"* | **gộp thành một câu dùng chung** — ba chỗ đang nói cùng một điều bằng ba cách |

⚠️ `goiY` **là nội dung của `aria-describedby`** (`Truong.tsx::idMoTa`). Cắt một câu là cắt
thứ mà trình đọc màn hình đọc cho ô đó — nên chỉ cắt khi **nhãn đã tự nói hết**, đúng
những dòng trên. Đừng cắt tiếp theo cảm giác «trông gọn hơn».

### 3.5 Cổng phát hành: năm trường cứng + thước đo mềm mười hai

Nguồn để chọn là `kb/directive/verticals/real_estate.py`: **đúng 11 trường** của `projects`
được biến thành văn bản cho agent đọc (`region`, `investor`, `total_land_area_m2`,
`floor_area_m2`, `build_density_pct`, `product_scale`, `ownership_form`,
`handover_standard`, `total_investment_vnd`, `overview`, `amenities`) — cộng `name` là
danh tính của doc. Trường ngoài danh sách đó (`salePhase`, `developer`, `link360`) có điền
cũng không tới tay agent, nên không có lý do gì để chúng gác cổng.

**Cổng cứng — năm trường:**

```python
BAT_BUOC["project"] = ("name", "region", "overview", "investor", "product_scale")
```

Lý lẽ chia hai nhóm. Ba trường đầu là chỗ agent **nói sai hoặc không nói được**: thiếu
`name` thì doc không có danh tính · thiếu `region` thì không trả lời được câu hỏi số 1 của
BĐS, và tệ hơn là khách hỏi dự án Hà Nội có thể được gợi một dự án Sài Gòn · thiếu
`overview` thì doc thành một túi số, agent đọc được diện tích nhưng không nói được dự án
này *là gì*. Hai trường sau (`investor`, `product_scale`) là hai câu khách hỏi sớm mà
không trường nào khác trả lời thay: ai làm · bao nhiêu căn, loại gì.

⚠️ **`overview` là đảo lại một quyết định của 2026-08-18**, có ý thức. Lý do bỏ nó hồi đó
(«biên tập viên viết sau, chặn publish vì nó biến việc biên tập thành cửa chặn») vẫn đúng
— và đó chính là việc mà thước đo mềm dưới đây gánh cho phần còn lại.

**Thước đo mềm — mười hai trường**, hiện ở thanh đáy dạng `Độ hoàn thiện 7/12` kèm một câu
nói điền thêm thì agent trả lời được thêm gì. **Không chặn gì.** Nó tồn tại để bảy trường
mềm còn lại (`amenities`, `total_land_area_m2`, `floor_area_m2`, `build_density_pct`,
`ownership_form`, `handover_standard`, `total_investment_vnd`) được nhắc mà không bị biến
thành cửa.

Mẫu số là **12** — cả mười hai trường agent đọc, gồm năm trường cứng. Không đếm riêng bảy
trường mềm: một thước chỉ đếm phần tuỳ chọn thì `12/12` không còn nghĩa là «đầy đủ».

#### 3.5.1 `amenities` bị loại khỏi cổng cứng vì dữ liệu thật nói vậy

Bản đầu của quyết định này có `amenities` trong cổng (sáu trường). Đo trên hai môi trường
thì loại nó ra:

| Trường | Container local (55 dự án published) | **Aurora dev (94 dự án published)** |
|---|---|---|
`name` | 0 | 0 |
`region` | 3 | **0** |
`overview` | 9 | 20 |
`investor` | 5 | **0** |
`product_scale` | 5 | 16 |
**`amenities`** | 46 | **94 — toàn bộ** |

| Biến thể cổng | Local | Aurora dev |
|---|---|---|
Hiện tại (`name`+`region`) | 3 / 55 | 0 / 94 |
Ba ô (thêm `overview`) | 9 / 55 | 20 / 94 |
**Năm ô (đã chọn)** | **11 / 55** | **20 / 94** |
Sáu ô (có `amenities`) | 46 / 55 | **94 / 94 · 100%** |

`amenities` **rỗng ở 100% dự án trên hệ thống đã deploy** — không phải «thỉnh thoảng
thiếu» mà là chưa một ai từng điền, ở bất kỳ môi trường nào. Ba hệ quả nếu giữ nó: mọi dự
án hiện có gắn cờ thiếu dữ liệu ngay ngày đầu · ai đó phải viết văn xuôi tiện ích cho 94
dự án trước khi hệ thống trở lại bình thường · và **một cổng mà mọi thứ đều không qua thì
không còn phân biệt được gì** — nó thôi là cổng, thành tiếng ồn. Ngược lại `region` và
`investor` thiếu **0** dự án trên Aurora, nên đưa vào cổng không tốn gì.

Cách đo, để lặp lại được: `aws --profile odyssey ssm send-command` chạy `docker exec
odyssey-portal-backend python -c …` — container đã có `DATABASE_URL` nên không cần tunnel
cũng không cần xin DSN. ⚠️ Hai bẫy đã ăn: `tenant_data` bật FORCE RLS và `portal_api`
không có BYPASSRLS ⇒ phải `set_config('app.tenant_id', …)` **từng tenant** rồi cộng dồn,
không thì `count(*)` trả 0 và trông y như DB rỗng; và `portal_api` **không đọc được**
`public.alembic_version` (`InsufficientPrivilege`) — đừng chèn câu đó vào cùng script, nó
giết cả lượt đo trước khi kịp in gì.

⚠️ **Không đo được trên production.** Từ máy dev không có đường tới một DB prod:
`~/.aws/` chỉ có `default` (account `418295696099`, chỉ ECR, không SSM) và `odyssey`
(account `071732232185`, hạ tầng **dev**); `describe-db-clusters`/`describe-db-instances`
trả rỗng; SSM có đúng một instance `i-095b82ffdd7d6c630` = `noblex-dev-odyssey-ec2`. Con
số Aurora dev ở trên là bản gần nhất với dữ liệu thật mà đo được. **Trước khi deploy phần
này lên prod thì phải chạy lại phép đo ở đó** — nếu prod cũng có trường nào rỗng 100% thì
nó phải rời cổng cứng theo cùng lý lẽ.

#### 3.5.2 Siết cổng làm nổ một lỗi có sẵn — phải sửa cùng lượt

`_chan_publish_thieu` (`router.py:201`) tính `trang_thai_moi = payload.get("status",
hang["status"])`, nên với một dự án **đã** `published` thì **mọi** PATCH đi qua cổng, kể cả
PATCH chỉ sửa một ô không liên quan. Siết từ hai lên năm trường ⇒ 20 dự án Aurora trả
**422 ở mọi lần sửa**, không còn đường chữa từ giao diện. Đây đúng chế độ hỏng mà
`_bo_qua_completeness_du_an` đã ghi cho `__ALL__`: *"MỌI PATCH sau đó… kể cả chỉ sửa một
field không liên quan, sẽ bị 422 vĩnh viễn"*.

Cổng phải chặn *hành động phát hành*, không phải *mọi lần sửa một bản ghi đã phát hành*:

```
chặn nếu   trạng thái cuối == 'published'
      và ( trạng thái cũ != 'published'          # đang publish -> kiểm
        hoặc payload chạm một trong năm trường )  # đang published mà xoá trắng -> kiểm
```

Vế thứ hai không được bỏ: không có nó, một PATCH xoá trắng `overview` của dự án đang
published sẽ đi qua, và cổng thành thứ chỉ gác lúc vào cửa. Vế thứ nhất là thứ cứu 20 dự
án: chúng ở lại `published`, agent vẫn đọc, badge nói thiếu dữ liệu, và **sửa được** —
người biên tập điền dần chứ không bị khoá ngoài.

Lỗi này **đã có từ trước**, chỉ chưa nổ vì cổng cũ nhẹ (`name`+`region`, 0/94 trên
Aurora). Nó nổ ở đúng lượt siết đầu tiên.

## 4. Thay đổi backend (`odyssey-portal-backend`)

Nhỏ và độc lập. Nhánh `feat/ingest-ui`.

### 4.1 Chuyển hàm sinh mã sang `core/`

Mới: `src/portal/core/ma_ban_ghi.py`

```python
def candidate_code(source: str) -> str: ...        # nguyên văn ung_vien_ma
async def next_project_code(conn, source: str) -> str: ...   # nguyên văn _ma_du_an_moi
```

Định danh **tiếng Anh** (code mới). `modules/ingest/chieu.py` import từ đây, hai bản cũ
xoá. Luật 3 (`tests/test_module_boundaries.py`) cấm `realestate` import ruột `ingest`, và
`core/ten_tai_nguyen.py` đã ghi đúng tiền lệ này trong docstring của nó.

**Thêm test** cho `candidate_code` — hàm thuần, chưa từng có bài nào: ký tự lạ · rỗng →
`DU_AN` · cắt 40 · `"__ALL__"` → `"ALL"`.

### 4.2 `projectCode` thành tuỳ chọn

```python
project_code: str | None = Field(default=None, alias="projectCode")
```

Vắng hoặc rỗng ⇒ `next_project_code(conn, body.name)`. Còn nhận `projectCode` tường minh
nên **additive, không breaking** — đường nạp và test cũ không đổi.

`name` rỗng **và** `projectCode` rỗng ⇒ 422 mã `PROJECT_NAME_REQUIRED`. Không tự đúc
`DU_AN_n`: FE đã bảo đảm có tên (§5.2), và đúc một mã vô nghĩa là thứ người dùng phải
mang vĩnh viễn.

⚠️ `next_project_code` là SELECT-rồi-INSERT: hai request đồng thời cùng tên vẫn đụng
UNIQUE. Với mã **tự sinh** thì 409 `DUPLICATE_CODE` là thông điệp vô nghĩa với người dùng
— nên đường tự sinh phải **thử lại một lượt** rồi mới để lỗi nổi lên.

### 4.3 Phân khu

Cùng khuôn: `ZoneIn.zone_code` thành tuỳ chọn, suy từ `ZoneIn.name`, chống trùng trong
phạm vi `(tenant_id, project_code)`. ⚠️ **Giả định** — người dùng chốt "phân khu: `name`
required" nhưng chưa nói rõ mã phân khu tự sinh; làm theo đối xứng với dự án. Sai thì sửa
ở đây trước khi thi công.

### 4.4 Cổng phát hành — hai thay đổi, đi cùng nhau

**(a) `completeness.py`** — `BAT_BUOC["project"]` từ `("name","region")` thành
`("name","region","overview","investor","product_scale")`. Sửa luôn docstring đầu tệp: nó
đang giải thích vì sao `overview` **bị bỏ** ngày 2026-08-18, giờ thành sai. Ghi lý do đảo
lại (§3.5) ngay tại đó, đừng để chỗ lệch không có ai thừa nhận. `BAT_BUOC["unit"]` **không
đổi**.

**(b) `_chan_publish_thieu`** (`router.py:188`) — đổi ngữ nghĩa theo §3.5.2. Nhận thêm
thông tin «status cũ» và chỉ chặn khi *đang publish* hoặc *payload chạm một trong năm
trường*. Không có (b) thì (a) đóng băng 20 dự án Aurora — mọi PATCH 422.

⚠️ Hai vế phải vào **cùng một commit**. Ship (a) trước là tự tay tạo ra sự cố mà (b) sửa.

**Thước đo mềm** không cần gì ở backend: cả 12 trường đã nằm trong `DuAnOut`, FE tự đếm.
Không thêm endpoint, không thêm cột.

### 4.5 KHÔNG đổi

Luồng lưu · `_tach_payload` · `ProjectPatch` · `UnitIn` · `control.*` · `BAT_BUOC["unit"]`.
**Không migration nào** — cổng phát hành là phép tính thuần trên bản ghi vừa đọc, không
phải cột (`completeness.py` docstring: *"KHÔNG LƯU CỘT"*).

## 5. Thay đổi frontend — ba đợt

Mọi form nhập data đi qua cùng một bộ primitive, nên **đợt 1 kéo theo phần lớn đợt 3**.

### 5.1 Đợt 1 — primitive dùng chung

| File | Việc | Issue |
|---|---|---|
`components/ui/Truong.tsx` | `O_CHUNG`: thêm `placeholder:italic placeholder:text-[13px]`. Giữ `placeholder:text-muted-3` | 3 |
`components/ui/Truong.tsx` | `Khung`: `batBuoc` giữ dấu `*`; thêm prop `canDePhatHanh` vẽ nhãn nhạt *"cần để phát hành"* thay vì `*` | 6 |
`realestate/components/VungMedia.tsx` | `NUT_SUA` bỏ `opacity-0 group-hover:opacity-100`; tách thành hai nút `✎` + `✕`, nút `✕` gọi thẳng `xoaMedia` sau một xác nhận tại chỗ | 4 |
`realestate/components/SuaMedia.tsx` | Giữ nút Xoá (đường thứ hai, dùng khi đang sửa chú thích) | 4 |
`realestate/components/Anh360Tab.tsx` | Thêm nút **Xoá link** khi `link360` có giá trị — PATCH `{link360: ''}` | 4 |
`TongQuanTab` · `CanForm` · `TaiLieuTab` · `PhanKhuTab` · `Anh360Tab` | Dọn `goiY` theo bảng §3.4b — 3 cắt · 1 cắt nửa · 2 gộp vào `hints.ts` | 8 |

Lan tới: `/pform`, `/uform`, form phân khu, form tài liệu, `/kb`, `/users`.

### 5.2 Đợt 2 — `/pform`

**Bố cục** (`KhungDuAn.tsx` + `DuAnForm.tsx`): ba tầng — khối dán trên (breadcrumb ·
hàng 9 tab · chip trạng thái bên phải), vùng cuộn ở giữa (các ô), khối dán dưới (câu
completeness bên trái + hàng nút Sửa / Huỷ / Lưu bên phải). `DauDuAn` dùng chung với
`/uform` nên khối trên phải nhận cả hai ngữ cảnh.

**Bỏ khoá tab**: `DauDuAn` thôi đặt `khoa`/`giaiThich`; `VI_SAO_KHOA_TAB` xoá khỏi
`tabDuAn.ts`.

**Dựng lười** — component mới `useEnsureProject()`:

1. Có `code` ⇒ trả về ngay.
2. Chưa có, và state form đã có `name` ⇒ `POST /projects` với **toàn bộ** state của ba tab
   cột-dự-án, rồi `nav({search:{code}})`.
3. Chưa có `name` ⇒ hiện một khối một-ô tại chỗ *"Dự án này tên gì?"* + nút tiếp tục;
   xong thì làm (2) rồi chạy tiếp việc gốc.

Sáu tab con nhận prop `ensureProject: () => Promise<string>` thay cho `projectCode: string`
trần. State của ba tab cột-dự-án phải **nâng lên `DuAnForm`** để bước (2) gửi được trọn
gói; sau khi tạo, mỗi tab quay về PATCH riêng của nó (giữ nguyên lợi ích `exclude_unset`
mà `ViTriTab` docstring đã nêu).

**Chip trạng thái**: component mới `StatusChip` — 11px, `--badge-warn` cho nháp, `--ac`
cho phát hành, `--badge-neutral` cho lưu trữ; mở menu 3 mục; PATCH `{status}`. Ô `OChon`
Trạng thái **rời khỏi** `TongQuanTab`. Câu chặn phát hành (422 `INCOMPLETE_DATA`) hiện ở
khối dán dưới.

**Bỏ ô Mã dự án** khỏi `TongQuanTab`; mã hiện thành chip mono nhỏ cạnh tên ở breadcrumb.

**`completeness.ts`** — `BAT_BUOC.project` theo đúng năm trường của backend
(`name`·`region`·`overview`·`investor`·`product_scale`), thêm nhãn `investor` /
`product_scale` vào `NHAN`. Docstring của tệp đã tự đặt luật: bản FE *"chỉ được phép
NGHIÊM BẰNG HOẶC LỎNG HƠN"* backend — nên hai danh sách phải khớp từng chuỗi, và **thêm ở
đây mà quên ở kia là đúng cái sai mà docstring đó cảnh báo**.

**Thước đo mềm** — hàm mới `doHoanThien(duAn)` trong `completeness.ts`: đếm bao nhiêu trong
**12 trường agent đọc** đã có giá trị. Danh sách 12 trường là bản chép tay của
`kb/directive/verticals/real_estate.py` — ⚠️ chưa có cổng nào canh hai bên khớp nhau (khác
`BAT_BUOC`, cũng chép tay nhưng ít nhất có docstring cảnh báo). Ghi cảnh báo tương tự.
Hiện ở khối dán dưới: `Độ hoàn thiện 7/12` + một câu nói điền thêm trường nào thì agent
trả lời được thêm câu gì. **Không disable nút nào.**

**Ô Tổng quan bỏ `batBuoc`** — nhưng nó **vào** cổng phát hành, nên nhãn đúng của nó là
*"cần để phát hành"* (prop `canDePhatHanh` của §5.1), không phải dấu `*` và cũng không phải
không có gì.

### 5.3 Đợt 3 — lan sang form còn lại

`/uform` (căn — giữ 2 ô required) · form phân khu trong `PhanKhuTab` (mã tự sinh) · form
tài liệu trong `TaiLieuTab`. Áp lại bố cục ba tầng + chip trạng thái.

## 6. Không làm

- Chọn-theo-lô để xoá nhiều ảnh (phương án C của issue 4) — người dùng không lấy.
- Tự lưu từng ô / bỏ chế độ Xem-Sửa — người dùng chọn giữ nút Sửa.
- Cho đổi `projectCode` sau khi tạo — xem §3.1.
- Sắc màu nhạt hơn cho placeholder — xem §2.6.
- Sinh tự động `unitCode` / `productType` — là dữ liệu có nghĩa thật, đúc ra là bịa.
- Cắt thêm `goiY` ngoài bảng §3.4b — chúng là `aria-describedby`, cắt bừa là bớt khả năng tiếp cận.
- `amenities` trong cổng phát hành — rỗng ở 94/94 dự án Aurora, xem §3.5.1.
- Đòi ≥1 ảnh mới cho phát hành — `completeness.py` là hàm thuần không I/O, thêm phép kiểm
  chạm bảng con là phá tính chất đó. Nếu về sau muốn thì là một spec riêng.
- Cổng canh «12 trường của thước đo khớp `real_estate.py`» — nên có, nhưng nó là một cổng
  xuyên hai repo như `actions-parity`, không nhét vào đợt này.

## 7. Test bị ảnh hưởng

**Frontend** — phải sửa, không phải hồi quy:

- `realestate-pform.test.tsx:45` *"chưa có `?code` thì chỉ mở tab Tổng quan, mọi tab con
  khác bị khoá"* → đảo ngược: **không** tab nào khoá.
- `realestate-pform.test.tsx:95` *"tạo xong thì chín tab mở ra"* → chín tab mở **từ đầu**.
- `realestate-pform.test.tsx:180` *"lúc tạo mới, câu thiếu dữ liệu chỉ đường tới tab giữ ô
  Khu vực"* → không cần chỉ đường nữa, tab Vị trí đã mở.
- `realestate-pform.test.tsx:237` *"PATCH không gửi `projectCode`"* → còn đúng, giữ.
- `realestate-trang-thai-o-chon.test.tsx:37-101` — cả khối `describe` đổi đích từ ô
  `OChon` trong tab Tổng quan sang `StatusChip` ở hàng tab.
- `realestate-pform.test.tsx:271-374` — cổng canh XEM=SỬA so nhãn ô theo từng nhóm; bỏ ô
  Mã dự án và ô Trạng thái phải sửa cả hai phía cho khớp.

- `realestate-pform.test.tsx:160-222` (`describe` cổng completeness) — mọi bài đang dựng
  dữ liệu theo luật **hai** trường; siết lên năm trường làm chúng đỏ. Đây là hồi quy
  **đúng nghĩa**, không phải báo nhầm: sửa dữ liệu dựng, đừng nới cổng.

**Bài mới**: 9 tab bấm được khi chưa có `code` · dựng lười từ tab con có tên · dựng lười
từ tab con **chưa** có tên (hiện khối hỏi tên) · nút `✕` thấy được **không cần hover** ·
placeholder có class nghiêng · ô Tổng quan hiện *"cần để phát hành"* chứ không phải `*` ·
ô nào còn `goiY` thì `aria-describedby` vẫn trỏ đúng id sau khi dọn (issue 8) ·
`doHoanThien` đếm đúng 12 trường · thước đo **không** disable nút Lưu khi thiếu trường mềm.

**Backend**: `candidate_code` (4 bài, hàm thuần) · POST `/projects` không `projectCode` ⇒
mã suy từ `name` · trùng tên ⇒ hậu tố `_2` · thiếu cả hai ⇒ 422 `PROJECT_NAME_REQUIRED` ·
`__ALL__` không đụng sentinel.

**Backend, cổng phát hành** — bài quan trọng nhất của đợt này:

- `BAT_BUOC["project"]` đúng năm chuỗi (cổng chống trôi ngược).
- **PATCH một dự án ĐANG published mà thiếu trường bắt buộc, payload KHÔNG chạm trường
  nào trong năm → 200.** Đây là bài canh 20 dự án Aurora khỏi bị đóng băng; nó đỏ ngay nếu
  ai đó hoàn nguyên §3.5.2.
- PATCH cùng bản ghi đó nhưng **xoá trắng** `overview` → 422 (vế thứ hai của luật).
- `draft` → `published` khi thiếu → 422, kèm tên trường trong thông điệp.
- `__ALL__` vẫn miễn cổng (`_bo_qua_completeness_du_an` không đổi).

**Không đụng**: `nav-registry.test.ts` (khoá `routes/_app` ở 18 file) — không thêm route
nào.

## 8. Rủi ro

| Rủi ro | Chống |
|---|---|
Nâng state ba tab lên `DuAnForm` làm mất lợi ích PATCH riêng | Chỉ dùng state gộp lúc **tạo**; sau đó mỗi tab PATCH riêng như cũ |
Dựng lười tạo dự án nháp rác | Chỉ ghi khi người dùng đã đặt tên **và** làm một việc cần dự án — hai điều kiện, không phải một |
Mã sinh từ tên không đổi được khi tên đổi | Hạ mã xuống thứ nội bộ (§3.1); nếu về sau thành vấn đề thật thì đó là một spec riêng |
Chip trạng thái bị đọc thành status của căn/tài liệu | `aria-label` + tiêu đề menu nói rõ "dự án" (§3.4) |
Backend: đua khi sinh mã | Thử lại một lượt trước khi để 409 nổi lên (§4.2) |
Siết cổng đóng băng dự án đang published | §3.5.2 — sửa ngữ nghĩa cổng **cùng commit**; có bài canh riêng (§7) |
20 dự án Aurora gắn cờ thiếu dữ liệu ngay sau deploy | Chấp nhận có ý thức: chúng ở lại `published`, agent vẫn đọc, sửa được. Thiếu `overview` 20 · `product_scale` 16 |
Thước đo 12 trường chép tay từ `real_estate.py`, không cổng nào canh | Ghi cảnh báo trong docstring; cổng parity xuyên repo để lại spec sau (§6) |
Prod chưa được đo | §3.5.1 — chạy lại phép đo trên prod TRƯỚC khi deploy; trường nào rỗng 100% thì rời cổng cứng |

## 9. Ghi chú liên repo

Spec này nằm ở repo frontend vì phần lớn công việc ở đó. Phần backend (§4) cần **một
dòng Change Log trong `CLAUDE.md` của repo backend** lúc thi công, trỏ về đường dẫn spec
này.

---

## 10. Thi công — chỗ LỆCH khỏi spec, và vì sao

Ghi ở đây thay vì sửa lén các mục trên: một spec bị chỉnh cho khớp code sau khi
thi công thì không còn ghi lại được quyết định nào.

**Cả ba đợt đã xong.** Đợt 1 (`7846733`), đợt 2 (`f65c84f` · `4823778` · `8a91363`),
đợt 3 (dòng cuối cùng của nhánh).

| Spec nói | Thi công làm | Vì sao |
|---|---|---|
§3.1 mã suy từ tên bằng `ung_vien_ma` (slug) | **Mã VIẾT TẮT** — `"Vinhomes Ocean Park 2"` → `VOP2`. Hai hàm: `candidate_code` (viết tắt, đường nhập tay) · `slug_code` (giữ trọn từ, đường nạp) | Người yêu cầu chốt 2026-08-21. Đo trên 95 tên thật của Aurora: viết tắt đụng 10/95 so với 8/95 của slug (chênh lệch đến từ tên TRÙNG KHÍT, không luật nào cứu) mà rút độ dài trung bình 20.4 → 3.5. Tách hai hàm vì `external_id` của CRM thường là UUID, và viết tắt một UUID ra chuỗi vô nghĩa |
§4.1 `next_project_code(conn, source)` | `next_project_code(conn, **candidate**)` — nhận mã ĐÃ sinh | Vòng chống trùng không cần biết mã tới từ hình dạng nào; để nó biết là để nó có hai nhánh sẽ lệch nhau |
§4.1 chuyển hàm "nguyên văn" | Thêm **phép bỏ dấu** (`đ`/`Đ` thay tay vì NFD không phân rã nó) | Bài test đầu tiên viết cho hàm này tìm ra `"Khu đô thị"` → `KHU_TH` — mất chữ, và hai tên khác nhau rút về cùng một mã. Chỉ ảnh hưởng mã SINH MỚI |
§5.1 prop `canDePhatHanh` | **`neededToPublish`** | Người yêu cầu chốt định danh tiếng Anh cho code mới |
§5.2 `useEnsureProject` + nâng state ba tab lên `DuAnForm` | **`CongDatTen.tsx`** — sáu tab con hiện một ô hỏi tên THAY CHO nội dung. Không nâng state, không luồn prop qua 6 component | `ChanRoiTabProvider` đã canh ca «gõ ở Tổng quan rồi nhảy tab» bằng hộp xác nhận, nên thứ mà việc nâng state đi cứu đã được cứu |
§5.2 (không nói) | Lúc tạo mới, **ba tab cột-dự-án mở CÙNG một form** (`TongQuanTab` chế độ `moi` gom `region`/`address`/`link360`) | «19 ô một POST» chỉ thành thật nếu chúng nằm trong một form. Chia ra ba lần lưu là mời người dùng mất phần đã gõ ở hai tab kia |
§3.4b cắt câu của ô «Căn ở tầng» | **GIỮ** | `realestate-uform.test.tsx:115` đỏ và nó đúng: câu đó với «khác ô trên» là một CẶP phân biệt hai ô dễ lẫn. Bảng §3.4b đã sửa tại chỗ |
§3.5 cổng sáu trường (có `amenities`) | **Năm trường** | Đo được `amenities` rỗng ở 94/94 dự án published trên Aurora. §3.5.1 đã sửa tại chỗ |
§5.1 `HANG_NUT` sticky | Thêm **`HANG_NUT_DAN`** riêng, không đổi `HANG_NUT` | `HANG_NUT` có 53 chỗ dùng ở nhiều feature; làm nó sticky là làm mọi form trong app dán đáy |
§5.3 «áp lại bố cục ba tầng **+ chip trạng thái**» cho `/uform` | Dán đỉnh + dán đáy: **có**. Chip trạng thái: **KHÔNG** | `status` của một căn được SUY ra từ dữ liệu (`trangThaiCan`), không do người dùng chọn. Một chip đổi được nó sẽ đánh nhau với phép suy đó mỗi lần lưu — đúng lớp lỗi «hai người sở hữu một trường» mà §10.1 vừa phải đóng cho dự án. Tài liệu cũng vậy: `TaiLieuTab` luôn gửi `published` |
§5.3 `/uform` «giữ 2 ô required» | Giữ 2 ô `*` — nhưng là **`Phân khu` + `Mã căn`**, không phải `Mã căn` + `Loại sản phẩm` | `productType` và `saleStatus` là ô CHỌN đã có mặc định (`chung_cu` / `available`), người dùng không bỏ trống được chúng: một dấu `*` ở đó hứa một ràng buộc form không thể vi phạm. `zoneCode` thì trống được thật VÀ backend bắt buộc. Hai ô cổng phát hành (`Giá bán` · `DT thông thuỷ`) chuyển sang nhãn «cần để phát hành» |
§5.3 (không nói) | Form phân khu: **`Tên phân khu` nhận `chanTrong`** (thuộc tính `required` của HTML), không chỉ dấu `*` | Mã suy từ tên, nên tên rỗng ⇒ 422 `ZONE_NAME_REQUIRED`. Năm form của realestate cố ý để backend làm nguồn sự thật, nhưng ở đây FE biết chắc trước khi gửi, và một request chỉ để nhận về lỗi là một request phí |

### 10.1 Hai thứ PHÁT SINH mà spec không thấy trước

**`validateSearch` bỏ mất `?tab=` khi chưa có `?code=`** (`routes/_app/pform.tsx`).
Nó trả `{}` cho mọi URL không có code, và `diToiTab` cũng gửi `search: {}` — nên
bấm một tab lúc tạo mới KHÔNG đi đâu cả. Vô hình suốt thời gian 8 tab còn bị khoá
(không ai bấm được chúng), chết hẳn ngay khi mở chúng ra. Không có bài test nào
phủ, và nó không phải hồi quy của đợt này — nó là điều kiện tiền đề bị lộ.

**Chip trạng thái tạo ra một người sở hữu thứ hai cho `status`.** `TongQuanTab`
đọc `v.status` một lần lúc mount, nên mỗi lần lưu tab đó sẽ hoàn nguyên thứ chip
vừa đổi — 200, không lỗi nào, người dùng chỉ thấy trạng thái nhảy về. Đã đóng
bằng cách cho PATCH của `TongQuanTab` **thôi gửi** `status`.

⚠️ Việc đó đòi **sửa một lý lẽ SAI trong test cũ**:
`realestate-trang-thai-suy-ra.test.tsx` đòi thân PATCH luôn mang `status`, viện lý
«bỏ trống thì DB dùng DEFAULT 'draft'». Không đúng với PATCH — `exclude_unset=True`
nên trường vắng mặt không được cập nhật, DEFAULT chỉ áp lúc INSERT. Giữ bất biến
đó là giữ mở đúng cái lỗ vừa nói. POST thì VẪN gửi tường minh.

### 10.2 Kiểm chứng

| | Trước đợt 1 | Sau đợt 2 | Sau đợt 3 |
|---|---|---|---|
Frontend | 748 passed · 60 file | 792 · 65 file | **809 passed · 68 file** (`npm run build` + `npm run lint` sạch) |
Backend | 1895 passed | 1895 passed | **1963 passed** (đo trên TOÀN BỘ `tests/`; hai cột trước đo trên tập hẹp hơn nên đừng đọc chênh lệch là «thêm 68 bài») |
Cổng cách ly | 51/51 | 51/51 | **51/51** |

⚠️ Backend còn **11 failed + 17 errors** ở `auth/test_dang_ky.py` ·
`auth/test_migration_invites_tenant.py` · `kb/test_index_client_that.py` ·
`test_heartbeat.py` · `test_worker_retry.py`. Đã `git stash` thay đổi của đợt này
và chạy lại: **cùng số, cùng tập file** — baseline, không phải hồi quy. Đo lại sau
đợt 3: **vẫn 11 + 17, vẫn đúng năm tệp đó**.

⚠️ Tệp nào đỏ thì ổn định, nhưng bài NÀO trong tệp thì không: hai lượt chạy liên
tiếp cho hai tập bài đỏ khác nhau trong cùng năm tệp (một lượt còn xanh sạch). Cả
năm đều chạm hạ tầng dùng chung (container Postgres, hàng đợi `control.jobs`), nên
đây là phụ thuộc thứ tự / trạng thái container, không phải logic. Đừng dùng danh
sách BÀI của một lượt làm baseline — chỉ danh sách TỆP là đáng tin.

`npm run lint` bên frontend từng đỏ **1 lỗi có sẵn** (`useDraftCaption.ts:42 Empty
block statement`, xác nhận baseline bằng cùng phép stash) — đã sửa ở đợt 3: `catch`
rỗng đó là chủ ý (chú thích nháp hỏng thì bỏ qua), nên bản vá là viết lý do đó vào
trong block, không phải đổi hành vi.

### 10.3 Còn nợ

- **Đo cổng phát hành trên prod** trước khi deploy (§3.5.1). Không đo được từ máy
  thi công: chỉ có hai profile AWS (một account chỉ ECR, một account hạ tầng dev),
  không thấy cluster RDS nào, và instance SSM duy nhất là máy dev. Cần profile /
  endpoint / DSN.
- **Một dòng Change Log trong `CLAUDE.md` của repo backend**, trỏ về spec này.
  Không tự ghi: file đó nhiều người cùng sửa nên dễ conflict.

### 10.4 Đợt 3 — đã làm gì

| Việc | File |
|---|---|
Mã phân khu tự sinh (`ZoneIn.zone_code` thành tuỳ chọn, lỗi mới `ZONE_NAME_REQUIRED`) | `realestate/router.py` |
Ô «Mã phân khu» rời form; «Tên phân khu» thành ô bắt buộc | `PhanKhuTab.tsx` |
Dán đáy cho ba form còn lại (phân khu · tài liệu · căn), cả bản XEM lẫn bản SỬA | `PhanKhuTab.tsx` · `TaiLieuTab.tsx` · `CanForm.tsx` |
Dán đỉnh cho `/uform` (breadcrumb + hàng 9 tab) | `CanForm.tsx` |
`/uform` còn 2 ô `*`, 2 ô «cần để phát hành» | `CanForm.tsx` · `Truong.tsx` (`OSo` nhận `neededToPublish`) |
Sửa lỗi lint có sẵn | `useDraftCaption.ts` |

Test mới: `test_ma_phan_khu_tu_sinh.py` (7) · `realestate-ma-phan-khu-tu-sinh.test.tsx`
(6) · `realestate-day-dan-tab-con.test.tsx` (6) · `realestate-uform-dot-3.test.tsx` (5).

⚠️ **Ba bài test cũ phải sửa, cả ba là đổi hành vi thật chứ không phải test hỏng:**
`realestate-pform.test.tsx` (một bài gõ `zoneCode`, một bài đòi ô mã bị `disabled`
lúc sửa) và `realestate-tab-chuyen-de.test.tsx` (ba bài gõ `zoneCode` để làm form
dirty). Chúng nay gõ «Tên phân khu» — cùng mục đích, ô khác.

---

## 11. Đảo chiều 2026-08-21 (cùng ngày): TỰ LƯU TỪNG Ô

Người dùng dùng thử bản vừa ship rồi chốt đảo lại **quyết định lớn nhất của spec
này** — «giữ nút Sửa» ở §6. Ghi thành mục riêng chứ không sửa §6: một spec bị chỉnh
cho khớp code sau khi thi công thì không còn ghi lại được quyết định nào.

### 11.1 Cái gì kích hoạt

Ba câu, theo đúng thứ tự người dùng gõ:

1. *«why you make it too complicated, it should be auto save, no need show like that»* — kèm ảnh hộp «Bỏ thay đổi chưa lưu?».
2. *«i cant click other tab except for Tong Quan»*.
3. *«why the infor of Vi Tri in tab Tong quan ?????»*

Cả ba là MỘT nguyên nhân. Hộp xác nhận bật theo cờ dirty, nên gõ một chữ ở Tổng
quan là mọi lần bấm tab sau đó phải đi qua hộp — và ở chế độ TẠO MỚI hộp chỉ có
một lựa chọn thật: **mất phần vừa gõ**. Không phải bug; là thiết kế sai cho ca tạo
mới. Còn ô Vị trí nằm trong Tổng quan là hệ quả của §5.2 «19 ô một POST».

### 11.2 Thiết kế mới

| | Trước | Sau |
|---|---|---|
Sửa | Bấm Sửa → gõ → bấm Lưu | Ô nhập luôn mở; **rời ô là lưu** |
Ô chọn / media | Chờ bấm Lưu | Lưu ngay lúc đổi |
Nhảy tab khi đang gõ | Hộp xác nhận | Đi luôn; `blur` chạy trước `click` nên đã lưu |
Tạo dự án | Form 19 ô ở tab Tổng quan | Một ô tên (`CongDatTen`), hiện ở **mọi** tab |
Ô Vị trí / Ảnh 360 lúc tạo | Trong form Tổng quan | Về đúng tab của chúng |
Thân PATCH | Cả form | **Đúng ô vừa đổi** |

**RỜI Ô, KHÔNG DEBOUNCE.** Trình duyệt phát `blur` trước `click`, nên bấm sang tab
khác là phần vừa gõ đã lên đường — đúng chỗ cái hộp đang chặn. Debounce theo thời
gian thì phải chọn một con số, và mọi con số đều sai ở đâu đó: ngắn thì mỗi chữ
một request, dài thì nhảy tab vẫn mất.

**PATCH ĐÚNG MỘT Ô.** Backend `exclude_unset=True`, nên gửi cả form là gửi lại 15
giá trị không ai sửa — trong đó có thể có ô vừa bị đổi ở nơi khác.

**Tạo vẫn cần một nút.** Chưa có hàng thì không có gì để PATCH. Đây là ranh giới
duy nhất giữa hai chế độ, và nó là ranh giới KỸ THUẬT chứ không phải lựa chọn.

### 11.3 Cái gì mất theo, và có mất thật không

| Mất | Đánh giá |
|---|---|
Hộp «Bỏ thay đổi chưa lưu?» + `useChanRoiTab` | Không còn gì chưa lưu để hỏi |
`TomTatDuAn` · `TomTatCan` · bản XEM của phân khu/tài liệu | Một chế độ thì không có bản thứ hai |
**3 bài cổng «XEM = SỬA»** | Canh một lớp lỗi THẬT (một ô rơi khỏi một trong hai chế độ). Với một chế độ, lớp lỗi đó không còn chỗ tồn tại |
Câu «Agent chưa đọc dữ liệu này» | Người dùng yêu cầu bỏ. Dự án nháp thì đương nhiên agent chưa đọc |
Nhãn «cần để phát hành» (prop `neededToPublish` của §5.1) | Người dùng yêu cầu bỏ. Sống đúng một ngày |
Câu «Đủ dữ liệu rồi — bấm Lưu…» | Nhắc một nút không còn |
Nút gập «Hiện nội dung đã đọc» của tài liệu | Nội dung nay ở ngay trong ô nhập |
**3 bài «PATCH vẫn phải gửi `status: published`»** (phân khu · tài liệu) | Lý lẽ của chúng SAI: `exclude_unset` nghĩa là trường vắng mặt không bị cập nhật. Cùng lỗi đã sửa cho dự án ở đợt 2 |

**GIỮ LẠI, không phải sót:** câu «Agent sẽ thôi đọc dự án này» (dự án ĐANG
published mà thiếu trường — nói về thứ đang chạy) và «Agent đã đọc dữ liệu này».
Chỉ biến thể «chưa đọc» bị bỏ. `ViTriTab` giữ câu đầu vì sửa `region` ở đó chính
là thứ làm hỏng một dự án đã published.

### 11.4 Hai chỗ suýt mất âm thầm

**`status` của CĂN phải đi kèm mọi lượt PATCH.** Nó được SUY ra (`trangThaiCan`),
không ai chọn — nên không gửi nó thì điền nốt Giá bán mà căn vẫn nằm `draft` và
agent không đọc. Ngược hẳn với dự án: dự án có chip, và chip là người sở hữu duy
nhất nên PATCH ở đó KHÔNG được mang `status`. Hai luật trái nhau, cùng một chữ.

**Nhãn khu vực tiếng Việt.** Bản chỉ-đọc dịch `mien_nam` → «Miền Nam»; một ô nhập
thì buộc hiện đúng thứ sẽ lưu. Không có gì thay thế thì người dùng chỉ thấy giá
trị máy. Phần dịch chuyển xuống một dòng cạnh ô (`aria-describedby`).

### 11.5 Khoảng hở còn lại, có chủ ý

Form TẠO một hàng mới (phân khu · tài liệu · căn) gõ dở rồi nhảy tab thì **mất,
không báo** — không còn hộp nào, mà cũng chưa có hàng để tự lưu. Đã ghim bằng một
bài test ở `realestate-tab-chuyen-de.test.tsx` để nó là một quyết định chứ không
phải một chỗ sót. Vá được (giữ state theo tab, hoặc tạo hàng rỗng ngay khi gõ ô
đầu) nhưng cả hai đều mở ra vấn đề mới: một là state sống lâu hơn màn, hai là hàng
rác trong DB mỗi lần ai đó bấm thử «Thêm phân khu».

### 11.6 Kiểm chứng

Frontend **819 passed · 70 tệp**, `npm run build` + `npm run lint` sạch. Backend
KHÔNG đổi một dòng nào ở đợt này.

Số test giảm 810 → 809 rồi lên 819: bỏ 6 bài (3 cổng XEM=SỬA + 3 bài `status`
sai lý lẽ), thêm 24 bài mới ở `realestate-tu-luu.test.tsx` (13) và
`realestate-tu-luu-hang.test.tsx` (11).

## 12. Đảo chiều 2026-08-21 (lượt hai): nút Sửa/Lưu ở lại, và dọn phần còn lại

§11 ghi «bỏ luôn nút Sửa». Người dùng đảo lại ngay sau đó — đây là vị trí **thứ
ba** của cùng một câu hỏi, và cả ba đều ghi ở đây để thấy nó đã đi đường nào.

### 12.1 Nút Sửa/Lưu

Chốt: **một nút cho CẢ chín tab**, không phải mỗi tab một nút («nút sửa hay lưu là
cho toàn bộ các tab chứ ko phải theo từng tab»). Mở form ra là bản chỉ-đọc; bấm
Sửa mở khoá mọi tab; **bên trong chế độ sửa vẫn tự lưu từng ô** — không nút Lưu
nào gửi request, không hộp «chưa lưu».

Lượt hai đổi thêm hai điểm:

| | Trước | Nay |
|---|---|---|
Chữ trên nút | «Xong» | «Lưu» — chữ người dùng đi tìm; «Xong» nói về việc đóng một chế độ |
Khi chưa sửa gì | bấm được | **xám, không bấm được** |

⚠️ Hệ quả có chủ ý: bấm Sửa rồi không sửa gì thì **không còn đường quay về chỉ
đọc** trên màn đó. Vô hại (chế độ sửa không giữ gì trong tay) nhưng nó là cái giá
của «không sửa thì không bấm được», và có test ghi lại.

Cờ `coDoi` ở cấp FORM, không cấp tab — cùng lý lẽ với công tắc xem/sửa. `useLuuTungO`
bật nó, vì đó là chỗ duy nhất mọi lượt đổi ô đi qua.

### 12.2 Hàng nút phải ở MỘT chỗ — hai lần vá, lần đầu SAI

`HANG_NUT_DAN` `sticky bottom-0` không đủ: nội dung ngắn thì vị trí tự nhiên của
hàng nút đã nằm trên mép dưới viewport, nên `sticky` không làm gì và hàng nút đứng
ngay dưới ô cuối — tab Vị trí (hai ô) thấp hơn tab Tổng quan (16 ô) nửa màn.

**Vá lần đầu, không đủ:** `mt-auto` trên hàng nút + một chiều cao SÀN đoán bằng
`min-h-[calc(100vh-310px)]`. Nó chỉ dịch chỗ đoán: cả trang vẫn cuộn, nên hàng nút
và chân bảng vẫn ở độ cao khác nhau trên mỗi tab và vẫn **nhảy** khi đổi tab.
Người dùng báo lại đúng chỗ đó.

**Vá thật:** dùng khuôn `DuAnList`/`TongQuanScreen` đã có — chặn chiều cao ở GỐC
(`KHUNG_MAN` = `h-[calc(100dvh-72px)]`, 72px là Topbar), đỉnh và hàng nút cố định,
**chỉ vùng giữa cuộn** (`VUNG_TAB` = `min-h-0 flex-1 overflow-y-auto`). Không còn
cuộn trang thì không còn gì để nhảy.

Nội dung tab tự khai chiều cao: `TAB_DAY` (`min-h-full`) cho tab-form (ngắn thì
`mt-auto` đẩy hàng nút xuống đáy, dài thì cuộn), và thẻ bảng đổi từ `CAO_TAB` (một
con số) sang `CAO_MAN` (`min-h-0 flex-1`) để **danh sách cao bằng vùng cuộn** và
chân bảng («Hiện 0–0 / 0») ở đáy kể cả khi rỗng. `CAO_TAB` xoá.

⚠️ **Vùng cuộn phải là KHỐI, không phải flex.** `min-h-full` của `TAB_DAY` **thay**
`min-height: auto`, tức mất cái sàn theo nội dung; trong một flex container có
chiều cao xác định (đúng cái `flex-1` vừa tạo ra) thì flex item bị BÓP về đúng
100% và nhóm ô cuối của tab dài bị cắt — đo được: tab Tổng quan, nhóm «Sở hữu &
bàn giao» còn trơ tiêu đề. Đây là lỗi lần vá thứ ba, cùng họ với hai lần trên:
mỗi lần đều là một lớp CSS mang hai nghĩa. Là khối thì không phép co nào chạy.

Cùng lý do đó, đừng thêm `min-h-0` vào lớp của tab-form: `min-height: auto` là thứ
duy nhất kéo khung cao bằng nội dung.

Hai cạnh sắc nữa lộ ra sau khi vùng cuộn thành một vùng cuộn THẬT:

* **`-mx-4` của hàng nút phải bỏ.** `overflow-y: auto` ép trục x thành `auto` theo
  spec, nên 16px lề âm mỗi bên sinh một thanh cuộn NGANG cho cả vùng, ở mọi tab.
* **Ở `/uform` hàng nút phải NGOÀI vùng cuộn.** Khối «Ảnh căn» nằm SAU form, nên
  một hàng nút `sticky bottom-0` bên trong form trôi lên **đè** khối ảnh đó. Nút
  «Tạo căn» vì thế submit bằng thuộc tính `form="uform-can"` — nó không còn nằm
  trong `<form>`. Ở `/pform` hàng nút là thứ CUỐI của tab nên dán bên trong vẫn
  đúng; khác biệt này có test canh.

Bài học chung của cả bốn lần vá: `h-[calc(100vh-<số>)]` chỉ đúng khi nó ở GỐC màn
và mọi thứ bên trong đo theo `flex-1`; và mỗi lớp CSS mang hai nghĩa (`sticky` ·
`min-h-full` · `-mx-4` · `overflow-y-auto`) là một lần phải đo lại trên màn thật —
jsdom không tính layout nên không cổng nào bắt được.

### 12.3 Bỏ cổng phát hành ở FE

Chip trạng thái làm mờ mục «Đã phát hành» khi `thieuTruongDuAn()` còn trường. Cổng
đó tồn tại để thay một 422 mờ mịt bằng một câu kể tên trường — rồi chính câu đó bị
bỏ khỏi menu (§11), nên còn lại một mục xám không giải thích gì: **đổi sang Bản
nháp rồi không phát hành lại được, không biết vì sao.** Đây là lỗi người dùng báo,
không phải suy đoán.

Nay mọi mục đều gửi; 422 `INCOMPLETE_DATA` qua `cauLoi()` nói đúng thứ đã mất.
Backend vẫn là nguồn sự thật (`_chan_publish_thieu`); hai bản chép tay của
`BAT_BUOC` giờ chỉ còn một bên cưỡng chế.

### 12.4 Dọn chữ

Bỏ mười câu chú thích tả cơ chế của chính app hoặc nói lại tiêu đề ngay trên nó
(«Số đếm và bộ lọc chỉ tính trang đang xem», «Phân khu của dự án này», «Ảnh và
video tiến độ thi công»…), kèm `HINT_OVERVIEW` và tệp `hints.ts` — tệp đó tồn tại
để hai ô `overview` không nói cùng một điều bằng hai câu; không ô nào còn chú thích
thì không còn gì để dùng chung.

Bỏ bốn câu «Agent đã / chưa đọc dữ liệu này» (dự án + căn). Giữ ca **lưu trữ**: nó
là ca duy nhất không chỗ nào khác nói — chip ghi «Lưu trữ» nhưng không nói rằng đổi
lại là việc làm ở chip.

### 12.5 Hai control đọc sai thứ chúng là, và một dải công cụ đôi

`OChonNhieu` khoá: khung ô nhập cao 42px tô xám với hai token bên trong đọc thành
một ô nhập bị hỏng. Khoá thì **bỏ hẳn khung**, còn token; rỗng thì một dấu gạch.
Nhãn thôi đếm «· đã chọn n» — token nằm ngay đó.

Chip lọc loại tài liệu: bốn pill màu rời nhau đọc thành bốn nút hành động. Nay nằm
trong cùng rãnh xám của hàng tab, chip đang chọn nổi lên, **giữ màu cũ**.

Nút «Thêm tài liệu» về **cùng hàng** với chip đó. Trước nó đứng riêng một hàng
phía trên, và hàng đó trống hoác — hai dải công cụ cho một bảng.

### 12.6 Kiểm chứng

Frontend **878 passed · 76 tệp**, `npm run build` + `npm run lint` sạch. Backend
KHÔNG đổi một dòng nào ở cả hai lượt của ngày.

Thêm `realestate-nut-luu.test.tsx` (10), `realestate-khung-cuon.test.tsx` (6) và
`realestate-dai-cong-cu-tai-lieu.test.tsx` (3). Bốn bài bị viết lại vì tiền đề đảo
chiều, và một bài bị **xoá vì xanh sai**: «câu còn-thiếu có `role="status"`» vẫn
xanh sau khi câu đó bị bỏ, vì hàng dán đáy có một `role="status"` riêng
(«Đang lưu…» / «Đã lưu.») và `findByRole('status')` bắt được nó.
