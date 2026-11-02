# Làm lại layout portal — rail + panel + ⌘K

**Ngày:** 2026-08-07 · **Nhánh:** `feat/agent-layout-tabs` · **Phạm vi:** `components/shell/*`, `lib/nav-*`, `features/realestate/nav.ts`

## 1. Vấn đề

Sidebar một cột 250px hiện **13 mục cùng lúc** trong 3 nhóm (Vận hành · Kiến thức · Cấu hình). Phản hồi: điều hướng phẳng, khó tìm.

Hai chỗ sai cụ thể, đo được:

1. **Không có cấp phân loại thật.** 3 nhãn nhóm chỉ là chữ nhỏ in hoa xen giữa danh sách — mắt vẫn phải quét cả 13 dòng. Cấp mở/gập duy nhất («Lĩnh vực») bọc đúng 3 mục và **trùng tên với chính màn con của nó** (`domains` = «Quản lý lĩnh vực»), nên sidebar có hai dòng đọc gần như y hệt lồng vào nhau.
2. **Nhóm theo module sở hữu, không theo việc người dùng làm.** Câu hỏi thường gặp nhất — «agent trả lời sai, sửa ở đâu?» — bắt đi qua hai nhóm: cấu hình agent ở *Cấu hình*, còn tài liệu nó đọc (`kb`) và lỗ hổng nó gặp (`gaps`) ở *Kiến thức*.

## 2. Quyết định

| Trục | Chốt | Bỏ qua |
|---|---|---|
| Hình dạng shell | Rail 68px + panel ngữ cảnh 240px | sidebar gập được + ⌘K · rail thuần |
| Taxonomy | **3 mảng**, agent làm trục | chỉ tách Agent · giữ nguyên 3 nhóm |
| Phạm vi thêm | Command palette ⌘K | trạng thái agent trên rail · breadcrumb + hành động topbar · rail nền tối |

**Không đổi:** bảng token màu (đã đo 23/23 cặp WCAG), typography (Be Vietnam Pro + JetBrains Mono), chiều cao topbar 72px, responsive (vẫn chưa có — xem §7).

## 3. Hình học

```
┌────────┬──────────────────────┬────────────────────────────┐
│  RAIL  │        PANEL         │           MAIN             │
│  68px  │        240px         │            1fr             │
├────────┼──────────────────────┼────────────────────────────┤
│  [X]   │  workspace switcher  │  topbar 72px: h1 · ⌘K · VI │
│        ├──────────────────────┤                            │
│  ▣ Vận │   Tổng quan          │                            │
│    hành│   Hội thoại       ● │      nội dung màn          │
│  ▤ Agent   Lịch hẹn           │                            │
│  ▧ Quản│   Chất lượng      ⏸ │                            │
│    trị │                      │                            │
│        ├──────────────────────┤                            │
│        │  TĐ Trần Hải Đăng ⌄ │                            │
└────────┴──────────────────────┴────────────────────────────┘
```

Chrome tổng **308px** (trước 250px). Đo trên 1440×900: `main` = 1132px, không sinh cuộn ngang.

**Thứ tự dọc của panel = thứ tự phạm vi**, rộng trước hẹp sau: workspace → (rail: mảng) → màn → bạn là ai. Sidebar cũ đặt workspace switcher dưới đáy, tức phạm vi rộng nhất đọc sau cùng.

**Không có tiêu đề mảng ở đầu panel.** Tên mảng đã nằm cách 68px dưới icon rail; in lại là trang trí. Trình đọc màn hình lấy tên đó qua `aria-label` của `<nav>`.

## 4. Taxonomy — 15 mục / 3 mảng

| Mảng | `key` | Mục | Đổi gì |
|---|---|---|---|
| Vận hành | `ops` | Tổng quan · Hội thoại · Lịch hẹn · Chất lượng | không đổi |
| Agent | `agent` | **khối chung:** Cấu hình chung · Tài liệu · Cần bổ sung · API Keys · Quản lý lĩnh vực<br>**khối «Bất động sản»:** Kiến thức · Kỹ năng<br>**khối «Tài chính»:** Kiến thức | `kb`+`gaps` từ Kiến thức, `api` từ Cấu hình, toàn bộ dữ liệu nghiệp vụ; bỏ cấp cha «Lĩnh vực»; **chia khối** (§4.2) |
| Quản trị | `admin` | Thành viên & Phân quyền · Nhật ký & Dữ liệu · Gói cước & Usage | phần còn lại của Cấu hình |

Thứ tự mảng theo **tần suất mở**, không theo vòng đời sản phẩm: người vận hành mở portal để xem hội thoại, không phải để chỉnh agent.

### 4.1 Vì sao dữ liệu nằm TRONG Agent

Một vòng thiết kế trước tách «Dữ liệu» (bất động sản · lĩnh vực · tài chính) thành mảng thứ tư đứng cạnh Agent — cân đối 4·4·3·3, trông gọn.

Sai. Dữ liệu nghiệp vụ **không song song với agent, nó là một phần của agent**: đó chính là thứ agent đọc để trả lời. Tách ra là bắt người dùng trả lời «agent nói sai giá căn hộ, sửa ở đâu?» bằng cách đoán xem giá căn hộ được xếp là "dữ liệu" hay là "agent" — đúng loại phân vân mà cả việc làm lại layout này sinh ra để xoá.

Nên thứ tự trong mảng Agent là một mạch, không phải một danh sách:

| | Mục | Câu hỏi nó trả lời |
|---|---|---|
| **LÀ GÌ** | Cấu hình agent | agent này là ai, nói năng thế nào |
| **BIẾT GÌ** | Tài liệu · Bất động sản · Quản lý lĩnh vực · Tài chính | nó đọc từ đâu |
| **THIẾU GÌ** | Cần bổ sung | nó đã không trả lời được cái gì |
| **GỌI THẾ NÀO** | API Keys | hệ thống ngoài gọi nó ra sao |

### 4.2 Chia khối: CHUNG ↔ RIÊNG TỪNG LĨNH VỰC

Vòng kế tiếp xếp 7 mục của Agent thành **một danh sách phẳng**. Cũng sai, và sai ở chỗ tinh hơn: nó xoá mất phân biệt quan trọng nhất của mảng Agent — **cái gì áp cho MỌI lĩnh vực, cái gì chỉ áp cho MỘT**.

Nên panel chia khối (`NavSegment`, `lib/nav-types.ts`):

```
▤ AGENT
┌──────────────────────┐
│  Cấu hình chung      │ ┐ khối CHUNG — không nhãn
│  Tài liệu            │ ┘ đổi ở đây là đổi cho MỌI lĩnh vực
│                      │
│ 🏢 Bất động sản   ⌄ │ ← dropdown, mở sẵn; tắt được ở /domains
│     Kiến thức        │   /projects — dự án, quỹ căn
│     Kỹ năng          │   /ky-nang-bds — 9 công tắc
│                      │
│ 🪙 Tài chính      ⌄ │   (đang TẮT ⇒ cả khối không hiện)
│     Kiến thức        │   /finance
│                      │
│  API Keys            │ ┐ khối HỆ THỐNG — dựng một lần rồi thôi
│  Quản lý lĩnh vực    │ ┘ nên xuống cuối
└──────────────────────┘
```

> **2026-08-08:** «Cần bổ sung» (`gaps`) đã **rời nav** theo yêu cầu — route + `ScreenStub` vẫn còn, `inNav: false` và có trong `OFF_NAV`. Nó là màn `inNav: false` **duy nhất hiện không có đường vào nào** từ giao diện; bốn màn còn lại đều vào được từ đâu đó.

Bốn quyết định:

**① Khối CÓ NHÃN là dropdown, mặc định mở** *(2026-08-08)*. Đầu khối mang icon lĩnh vực + caret, **không in đậm**; con **bỏ hẳn icon** và treo vào một **nét dọc** rơi thẳng từ tâm icon của đầu khối.

```
🏢 Bất động sản      ⌄
 │
 ├── Kiến thức
 └── Kỹ năng
```

Nét gạch làm việc mà chữ đậm từng làm, và làm tốt hơn: đậm chỉ nói "dòng này quan trọng hơn", nét gạch nói đúng thứ cần nói — "hai mục kia thuộc về dòng này".

Ba số buộc vào nhau: `ml-[19px]` (padding 11 + nửa icon 8) + `pl-px` + `pl-[17px]` = chữ con ở 37px, thẳng hàng chữ đầu khối. Sửa một thì sửa cả ba.

Vạch là `<span>` định vị tuyệt đối với `inset-y-1` (cắt 4px mỗi đầu), **không** phải `border-l`: viền luôn cao đúng bằng khối, nên rút ngắn nó đồng nghĩa với bóp khối và đẩy mục con đi. Đo lại sau khi đổi: vạch cao 71px trong khối 79px, chữ con vẫn ở 37px.

Icon «API Keys» đổi từ hai mắt xích sang **chìa khoá** — hình cũ nói "liên kết/tích hợp", đúng với nhãn cũ «Tích hợp & API» nhưng lệch với nhãn hiện tại: thứ màn này phát ra là khoá.

Đây không phải sự quay lại của cấp cha «Lĩnh vực» đã bỏ ở §4.1. Cái cũ bọc **trọn** mảng chứa nó — một cú bấm để mở ra đúng thứ vốn đã là toàn bộ nội dung, tức không nói thêm gì. Cái này bọc ruột của **một** lĩnh vực trong khi còn lĩnh vực khác bên cạnh, nên quan hệ cha/con là thật và đáng vẽ ra.

Mặc định **mở**, không đóng: khối tồn tại để cho thấy Kiến thức và Kỹ năng thuộc về lĩnh vực nào; gập sẵn thì cái đầu khối thành một dòng chữ vô nghĩa. Gập là để dọn khi có nhiều lĩnh vực.

Đang đứng ở một màn CON thì khối luôn mở, kể cả vừa bấm gập. Đánh đổi có thật — lúc đó nút gập bấm vào không thấy gì đổi — nhưng nhánh kia tệ hơn: gập lại là giấu mất chính cái mục đang sáng.

**② `/kb` («Tài liệu») ở khối CHUNG.** Nó là tài liệu của cả workspace, agent tra nó ở mọi lĩnh vực. Xếp vào khối «Bất động sản» là nav hứa một phạm vi mà backend không có. Ngày nào KB chia theo lĩnh vực thật thì chuyển vào, không phải trước — canh bởi `nav-registry.test.ts`.

**③ Khối rỗng biến mất cùng NHÃN của nó.** `useNavGroups` lọc ba tầng: mục → khối → mảng. Một nhãn «BẤT ĐỘNG SẢN» đứng trên khoảng trống nói với người dùng rằng có thứ gì đó ở đó mà họ không thấy — đúng thứ mà việc ẩn-cho-đỡ-rối-mắt định tránh.

**④ Nhãn mục CỐ Ý trùng nhau giữa các lĩnh vực.** «Kiến thức» là nhãn của cả `projects` lẫn `finance`; mỗi cái nằm dưới nhãn khối của lĩnh vực mình, nên nhắc lại tên lĩnh vực trong mục là đọc thành «Bất động sản › Bất động sản». Hệ quả: test phải truy vấn theo `data-nav`, không theo tên.

Palette cũng chia theo khối — tiêu đề thành «Agent · Bất động sản». Gộp «Kỹ năng» của BĐS chung một tiêu đề «AGENT» với kỹ năng chung là xoá đúng phân biệt mà khối sinh ra để giữ.

### 4.3 Kéo theo: màn Agent tách đôi

| Màn | Route | Nội dung |
|---|---|---|
| Cấu hình chung | `/agent` | danh tính · giọng · phạm vi · 6 rào chắn · **3 kỹ năng chung** |
| Kỹ năng BĐS | `/ky-nang-bds` | **9 kỹ năng** riêng vertical #1 (MỚI) |

Tab «Lĩnh vực» trong màn bỏ hẳn — ranh giới nó từng thể hiện giờ nằm trong nav.

**Cả hai sửa CÙNG một `ConfigPayload`, cùng một bản nháp server, cùng một `POST /publish`.** Tách ở tầng màn, không ở tầng hợp đồng. Nên vòng đọc-sửa-lưu rút vào **`useBanNhap.ts`** (một chỗ) và vỏ màn vào **`KhungSuaAgent.tsx`** (thanh trạng thái + nút Lưu và áp dụng + cảnh báo toàn cục + dialog).

Chép vòng đó ra hai màn là mở đúng một lớp lỗi: màn A giữ ảnh chụp payload lúc mở, người dùng sang màn B sửa và lưu, quay lại A bấm Lưu — A ghi đè bản của B bằng ảnh chụp cũ của chính nó.

`TabLinhVuc.tsx` xoá. Khối «Kiến thức» trong nó chưa bao giờ là ô sửa được — chỉ là mô tả + hai link sang `/projects` và `/kb`; hai link ấy giờ **là** hai mục nav, giữ lại đoạn mô tả là dựng biển chỉ đường thứ hai cạnh biển thứ nhất.

### 4.4 Lĩnh vực bật/tắt được (2026-08-08)

Khối lĩnh vực không còn viết cứng: `NavSegment.linhVuc` buộc nó vào công tắc ở màn **«Quản lý lĩnh vực»** (`/domains`, từ `ScreenStub` thành màn thật; sở hữu M4 → M5).

**Tắt là tắt thật, hai tầng:**

| Tầng | Chỗ làm | Hiệu lực |
|---|---|---|
| Nav — khối rời panel Agent | `useNavGroups` | **ngay** |
| Agent — kỹ năng không vào `tools.enabled` | `locKyNangTheoLinhVuc`, gọi trong `useBanNhap` lúc xuất bản | sau lần «Lưu và áp dụng» kế tiếp |

Màn `/domains` **nói trước** độ trễ ở tầng hai. Một công tắc trông như tức thời mà thật ra chờ một hành động ở màn khác là đúng loại hứa hẹn sai mà AG_01 §BR09 cấm.

**Lọc lúc XUẤT BẢN, không lúc gõ.** Tắt một lĩnh vực rồi bật lại mà mất sạch lựa chọn kỹ năng là một cú xoá dữ liệu không ai xin phép. Bản nháp giữ nguyên; chỉ thứ *gửi đi* mới bị lọc.

**Kỹ năng chung không bao giờ bị tắt theo lĩnh vực** — tra tài liệu · cập nhật khách · chuyển người thật là việc agent làm bất kể đang nói về cái gì.

⚠️ **`GET`/`PATCH /api/v1/linh-vuc` do FE định hợp đồng trước, backend chưa có** — cùng lối `/agent/try`. Hình dạng ở `features/agent/linhVuc.ts`, fake **có trạng thái** ở `lib/msw/handlers.ts` (cần trạng thái vì màn bật/tắt rồi đọc lại ngay; fake trả hằng số sẽ làm công tắc bật lên rồi tự nhảy về).

**Vì sao không nhét vào `ConfigPayload`** — đó là chỗ đúng cả về nghĩa lẫn về luồng (đã có Lưu và áp dụng). Nhưng backend đặt `extra="forbid"`: thêm một khoá lạ là **422 ngay**, không có đường ra từ UI. Việc *gating* thì không phải chờ ai — nó chỉ là bớt phần tử khỏi một mảng backend vốn đã nhận tập con bất kỳ.

**Không có thêm/xoá lĩnh vực.** Sổ lĩnh vực hôm nay là hằng số của sản phẩm, không phải thứ tenant tự đẻ ra; một nút «Thêm lĩnh vực» sẽ hứa rằng thêm xong là agent biết làm gì đó, trong khi kỹ năng và dữ liệu của một vertical mới là việc của backend.

## 5. Bảy quyết định có đánh đổi

**① Bấm rail = điều hướng, không phải chỉ đổi panel.** Mảng đang sáng luôn suy ra từ route ⇒ một nguồn sự thật, không có state "đang xem mảng khác". *Giá:* không ngó được mảng khác mà không rời màn. Đó chính là lý do ⌘K nằm trong cùng đợt này chứ không phải một tính năng rời.

**② `useNavGroups()` — một phép lọc quyền cho ba chỗ đọc.** Rail, panel, palette dùng chung. Ba bản sao của cùng luật quyền là ba chỗ để lệch; palette lọt một màn mà rail đã ẩn là cửa sau vào đúng thứ vừa ẩn. Canh bởi `tests/command-palette.test.tsx`.

**③ `OFF_NAV` thay `EXTRA_TITLES`.** 5 màn không có mục nav cần trả lời hai câu: rail tô sáng mảng nào, topbar hiện tiêu đề gì. Một bảng, hai câu — không phải hai bảng cùng danh sách path.

**④ Bỏ cấp 2 (`NavParent`), không giữ kiểu "để dành".** Giữ union `NavEntry` buộc rail + panel + palette mỗi chỗ mang một nhánh `kind === 'parent'` cho hình dạng không tồn tại. Cần lại thì viết lại 6 dòng kiểu — rẻ hơn ba nhánh chết. *(Thay đổi so với bản thiết kế trình bày ban đầu, nơi định giữ kiểu.)*

**⑤ Tách `UserMenu` khỏi `WorkspaceSwitcher`.** Comment cũ cấm đúng việc này: "hai menu cách nhau 8px là hai chỗ để người dùng phải đoán". Lý do ấy nói về **kề nhau**, không về **tách**. Hai menu giờ ở hai đầu một cột cao ngang màn hình, mỗi cái ở đúng phạm vi của nó.

**⑥ Rail dùng `data-current`, không `aria-current`.** `<Link>` của TanStack tự đặt `aria-current="page"` khi `to` khớp route và **ghi đè** giá trị truyền vào — nên `aria-current="true"` viết tay cho ra `"page"` lúc đang ở màn đầu của mảng và `"true"` lúc ở màn khác cùng mảng. Để router giữ `aria-current` (nó không bao giờ nói dối); "mảng nào đang mở" thì lấy từ `aria-label` của panel.

**⑦ Panel 240px là số đo trên trình duyệt.** Bản đầu đặt 228px theo phép **nhẩm** bề rộng chữ (~154px). Đo thật: «Thành viên & Phân quyền» có `scrollWidth` = 167px ở 13.5px ⇒ bị `truncate` cắt mất «& Phân quyền», tức cắt đúng nửa phân biệt mục này với mục khác. Đổi cỡ chữ / font / thêm nhãn dài hơn ⇒ **đo lại**, đừng nhẩm.

## 6. Signature — ⌘K là tấm gương của rail

Palette **không** phải danh sách phẳng 14 dòng: nó chia đúng 4 mảng ấy, đúng thứ tự ấy, đúng icon ấy. Học palette là học rail và ngược lại — cấu trúc nhóm ở đây mã hoá một sự thật, không trang trí.

**Tìm bỏ dấu.** Gõ `hoi thoai` ra «Hội thoại», `dong san` ra «Bất động sản». Người Việt gõ nhanh thì không bỏ dấu. `normalize('NFD')` + `\p{M}` để tách dấu tổ hợp, **cộng** hai lần thay tay cho `đ`/`Đ` — chữ đó không phải dấu tổ hợp, NFD không tách được gì ra khỏi nó.

Regex dùng `\p{M}` chứ không viết thẳng dải `[U+0300-U+036F]`: dấu tổ hợp đứng một mình không hiện gì, nên một regex chứa chúng trông như `/[-]/` với người đọc sau.

## 7. Chuyển động

**Đúng một chỗ:** đổi mảng → danh sách panel fade 120ms (`key` theo mảng ⇒ dựng lại ⇒ animation chạy lại). Không stagger — stagger bắt người dùng chờ hết chuỗi mới đọc được mục cuối, đắt hơn thứ nó nói. `prefers-reduced-motion: reduce` ⇒ tắt hẳn.

## 8. Cái CHƯA làm (cố ý)

- **Responsive.** Vẫn nằm trong danh sách "chưa có, không phải thiếu sót" của CLAUDE.md. Shell 3 cột dưới 1100px để lại ~800px cho `main` — dùng được, chưa tối ưu. Bước tiếp nếu cần: dưới 1100px panel thành overlay bật khi bấm rail.
- **Breadcrumb + khe hành động trên topbar.** Không chọn. Topbar chỉ thêm nút mở ⌘K (một tính năng chỉ có phím tắt là một tính năng không ai tìm ra).
- **Trạng thái agent trên rail.** Không chọn — cần endpoint mới.
- **Rail nền tối.** Không chọn; rail giữ `bg-surface` cùng tông panel.

## 9. Nghiệm thu

| Cổng | Kết quả |
|---|---|
| `tsc -b --force` | sạch |
| `eslint .` | sạch |
| `prettier --check` | 3 tệp nợ **có sẵn**, không thuộc việc này: `routeTree.gen.ts` (tệp sinh), `PhienKhach.tsx`, `khoa-dau-noi.test.tsx` |
| `vitest run` | **319 pass · 1 fail · 6 skip** |

**Mốc trước khi sửa: 282 pass · 1 fail · 6 skip.** Bài đỏ là cùng một bài — `tests/convos-phien.test.tsx` («cuộc gọi tool ghép từ hai hàng thành MỘT khối»), đỏ sẵn trên cây sạch. **+37 test**, không nhận thêm cái đỏ nào.

> ⚠️ Cả hai lần đo đều chạy với `NODE_OPTIONS="--no-experimental-webstorage"`. Không có cờ đó, Node 25 trên máy dev cho `210 failed` với lỗi trỏ nhầm vào `i18n` — xem Gotchas trong CLAUDE.md.

Đo trên trình duyệt thật (Playwright, 1440×900): rail 68 · panel 240 · main 1132 · topbar 72 · không cuộn ngang · không nhãn nào bị cắt · panel Agent render đúng 5 mục khối chung + nhãn «Bất động sản» (2 mục) + nhãn «Tài chính» (1 mục), không cuộn dọc · `/ky-nang-bds` có 9 công tắc, không còn `role="tablist"`, vẫn có thanh trạng thái + nút Lưu và áp dụng · ⌘K mở đúng, focus vào ô nhập · `hoi thoai` → «Hội thoại» → ↵ → `/convos`.

**Chưa nghiệm thu:** thẩm mỹ. Ảnh chụp nằm trong sandbox của Playwright nên không xem được — mới xác nhận hình học và hành vi, chưa xác nhận nó *đẹp*.

## 10. Ba bài test đỏ vì thiết kế mới, không vì code hỏng

Panel giờ **luôn** hiện tên người đăng nhập (UserMenu) và **luôn** hiện mục «Bất động sản» khi ở mảng Dữ liệu. Trước kia cả hai bị giấu (menu đóng / cấp cha gập), nên vài truy vấn không khoanh vùng xanh nhờ một thứ chúng không hề định kiểm:

- `realestate-pform`: `getByRole('link', {name: /Bất động sản/})` → khoanh vào `<main>`
- `user-admin` (4 chỗ): `findByText(user.name).closest('tr')` → helper `hangCua()` tìm trong `<main>`
- `dang-xuat`: mở menu qua nút tên workspace → giờ qua nút tên người dùng

Kèm một sửa thật: ô initials trong `UserMenu` nhận `aria-hidden` — nó lặp lại đúng cái tên bên cạnh, không có nó thì tên nút đọc lên là «TĐ Trần Hải Đăng».
