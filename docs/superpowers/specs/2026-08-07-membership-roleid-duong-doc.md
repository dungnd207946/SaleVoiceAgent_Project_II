# Đường ĐỌC của membership mang `roleId`, không chỉ mang tên

Ngày: 2026-08-07 · Trạng thái: đã thi công (`70f2f60`, nhánh `feat/membership-roleid`)
· Không migration, không đổi `contracts/`

Ghi lại ở đây vì **không có tài liệu nào khác mô tả hình dạng hai DTO này**. Đã
quét trước khi viết: `docs/contracts/auth.md` không nói về chúng,
`contracts/*.json` chỉ mang sổ action/kỹ năng chứ không mang hình dạng DTO, và
repo không có snapshot OpenAPI. Hai chỗ duy nhất nhắc tên `MemberOut` là spec
`2026-07-30-m2a-be-xac-thuc-phien-vo-api.md` (§ bản đồ file và bảng endpoint) —
cả hai chỉ nêu TÊN kiểu, không nêu trường, nên không có gì để đồng bộ ở đó.

## 1. Đổi cái gì

Hai DTO **đọc** của module `auth`, trong `src/portal/modules/auth/contracts.py`:

| DTO | Đường dùng | Thêm |
|---|---|---|
| `MembershipOut` | `GET/POST/PATCH /api/v1/users` | `roleId: str` |
| `MemberOut` | `GET /api/v1/members` | `roleId: str` |

`repo.py` đổi hai câu SELECT để thật sự lấy cột ra: `m.role_id` **đã có sẵn trên
bảng** và đã nằm trong mệnh đề JOIN, chỉ là chưa bao giờ được SELECT. Không đổi
lược đồ, không migration.

**Phải sửa CẢ HAI, không phải một.** `MembershipOut` phục vụ form sửa user;
`MemberOut` phục vụ bảng thành viên workspace — mà bảng đó cũng có đường GHI (ô
đổi vai trò inline). Vá một DTO thôi thì đường leo thang quyền qua bảng thành
viên vẫn mở nguyên. Đây chính là chỗ tài liệu phía FE lúc đầu đếm thiếu: nó chỉ
nêu `MembershipOut`.

## 2. Vì sao — id chứ không phải tên

Đường **GHI** đã neo vào id từ 2026-08-04: `MembershipIn.roleId`, với lý lẽ ghi
thẳng trong docstring — tên vai trò sửa được, `id` là handle ổn định duy nhất.
Migration `0104` biến vai trò thành thứ mỗi tổ chức tự đặt tên và **đổi tên được**;
đó là cả điểm của nó.

Đường **ĐỌC** thì chưa bao giờ được xem lại. Nó chỉ trả `role` (TÊN), nên FE buộc
phải dò ngược TÊN → id qua `/api/v1/roles` để chọn sẵn ô vai trò trên `<select>`.
Phép dò đó khớp **SAI** ngay khi hai vai trò trùng tên, hoặc khi một cái tên vừa
dời sang vai trò khác — và `<select>` thì im lặng hiện một vai trò khác thứ đã
cấp. Hậu quả đã **đo được** ở FE: leo thang quyền xuyên workspace, không một lỗi
nào, vì `PATCH /users/:id` thay TOÀN BỘ `memberships` trong một nhịp.

Nói gọn: **một hợp đồng bất đối xứng**. Ghi bằng id, đọc bằng tên, và khoảng
chênh giữa hai thứ đó bị đẩy sang cho client tự bắc cầu bằng một phép đoán.

`workspaceName` ngay cạnh đã áp đúng nguyên tắc đúng từ đầu — gửi kèm cái FE cần
để khỏi tra chéo. `roleId` là cùng nguyên tắc, ngược chiều: ở đó thiếu TÊN nên
gửi thêm tên, ở đây thiếu ID nên gửi thêm id. **Giữ cả hai: id để neo, tên để
hiện.** Không bỏ `role` — client vẫn cần chuỗi để hiển thị, và bỏ nó mới là
thay đổi phá vỡ.

## 3. Thay đổi THUẦN BỔ SUNG — khác precedent 2026-08-04

Đây là điểm đáng ghi nhất của lần này, và nó **khác** với tiền lệ gần nhất.

Spec `2026-08-04-phan-quyen-dong-design.md` §8.1① ghi lại rằng lần đổi
`role` → `roleId` ở đường **GHI** **không có cửa sổ tương thích**: `POST/PATCH
/users` bắt buộc `roleId` và từ chối `role`, nên bên nào deploy trước thì màn
quản trị người dùng trả 422 cho tới khi bên kia theo — hai deploy đó là **một
đơn vị**, phải ghi vào runbook.

Lần này thì không như vậy:

- Chỉ **thêm trường vào response**. Không bỏ, không đổi tên, không đổi kiểu.
- Không đụng một model **request** nào. `MembershipIn` giữ nguyên.
- Client cũ bỏ qua trường lạ, nên nó chạy y như trước khi có `roleId`.

⇒ **Backend deploy trước được, một mình, bất kỳ lúc nào.** FE theo sau lúc nào
cũng được, và **không có cửa sổ 422**. Trong khoảng giữa, FE cũ vẫn dò ngược theo
tên như cũ — tức là bug leo thang quyền vẫn còn cho tới khi FE lên, nhưng nó
không hỏng THÊM. Thứ tự đúng và duy nhất khả dĩ: BE trước, FE sau.

> Nói cho đủ: điều làm lần này an toàn không phải là ai đó cẩn thận hơn, mà là
> **hình dạng của thay đổi**. Thêm vào response thì tương thích ngược theo cấu
> trúc; đổi trường bắt buộc của request thì không, bất kể quy trình có kỹ tới đâu.
> Khi cần cắt một trường ở đường ghi, quay lại đọc §8.1① — nó nêu cả cách nới:
> nhận trường cũ làm alias phế bỏ trong một release.

## 4. ⚠ Không có cổng CI nào canh hình dạng DTO giữa hai repo

`MembershipOut`/`MemberOut` là hợp đồng giữa hai repo git tách rời, và **không gì
chứng minh hai bên còn khớp**:

- `contracts/*.json` (`actions` · `tools` · `agent-config`) **không** mang hình
  dạng DTO — chúng là sổ action và sổ kỹ năng, không phải lược đồ payload.
- Repo không sinh, không lưu **snapshot OpenAPI** nào.
- Phía FE có `tests/membership-shape-parity.test.ts` (thêm cùng đợt này), nhưng nó
  chỉ chứng minh *fake MSW = kiểu TypeScript* — **cả hai đều nằm trong repo FE**.

Nên nếu backend đổi hai DTO này mà FE không theo, **mọi cổng ở cả hai repo vẫn
xanh**. Đó không phải giả thuyết: đúng điều đó đã xảy ra suốt từ 2026-08-04 tới
2026-08-07 — đường ghi neo vào id, đường đọc trả tên, và không cổng nào đỏ trong
ba ngày đó.

Cùng họ với khoảng hở §8.1② của spec 2026-08-04 (bản sao `contracts/actions.json`
copy tay giữa hai repo, không có job `diff`), nhưng **nặng hơn một bậc**: ở đó ít
ra còn có một artefact chung để mà so; ở đây không có artefact nào cả. Cách đóng
nếu ngày nào đó quyết định đóng: xuất OpenAPI thành artefact biên trong
`contracts/` rồi sinh/so kiểu FE từ nó — đúng thứ package `packages/contracts` định
làm trước khi việc tách hai repo làm nó bất khả thi.

## 5. Test

`tests/modules/auth/` — thêm bất biến **round-trip id gửi lên = id nhận về** ở
cả `POST` và `PATCH` (`test_tao_user.py`, `test_sua_user.py`), và một assert
`roleId` cho `liet_ke_thanh_vien` (`test_repo.py`). Round-trip là phép kiểm đúng
cho lớp lỗi này: nó neo chính cái vòng khép kín mà `roleId` sinh ra để bảo đảm,
thay vì chỉ kiểm trường có mặt.

Đo trên nhánh (2026-08-07, sau `70f2f60`): `uv run pytest tests/modules/auth -q`
→ **165 passed**. Module này cần Docker (testcontainers).
