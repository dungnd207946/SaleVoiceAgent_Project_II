# Gộp màn Users + Roles → "Thành viên & Phân quyền"

Ngày: 2026-08-06 · Trạng thái: **đã thi công xong** trên nhánh `feat/gop-users-roles`
(chưa mở MR). §6 · §7 · §8 · §11 đã được viết lại theo CODE CUỐI sau khi thi công —
những mục đó mô tả hiện trạng. §1 nêu vấn đề ở thì hiện tại là kể lại bối cảnh
TRƯỚC khi sửa, không phải hiện trạng.
Repo: `odyssey-portal-frontend`

> **Cập nhật 2026-08-07 — §12 ĐÃ GIẢI QUYẾT.** Backend trả kèm `roleId` ở cả
> `MembershipOut` và `MemberOut`, FE bỏ hẳn phép đối chiếu ngược TÊN → id. Ba mục
> đọc theo thì khác nhau kể từ đây:
> **§11 là KHẢO CỔ** (mô tả bản vá thời còn dò theo tên — bộ máy còn sống nhưng đã
> đổi mục tiêu) · **§12 là nợ ĐÃ ĐÓNG kèm nhật ký** · **§6 và §8 vẫn là hiện trạng**,
> phần thêm của vòng này đánh dấu `[+2026-08-07]` hoặc nằm trong khối trích dẫn.

## 1. Vì sao có tài liệu này

`/users` và `/roles` là hai màn top-level riêng trong nhóm nav "Cấu hình", nhưng
đang chồng chéo và gây nhầm ("nhập nhằng"):

- Nhãn nav của `/users` là **"Users & Phân quyền"**, nhưng UI phân quyền thật (ma
  trận 13 action) lại nằm ở `/roles`, không phải `/users`.
- Trên chính `/users`, hai bảng xếp chồng dùng chung ngôn ngữ hiển thị (pill
  badge) cho hai khái niệm khác nhau: cột "Quyền tổ chức" (`OrgRole`, chỉ
  `owner`/`member`) và cột "Vai trò" của `MemberList` (custom Role tự đặt, lấy
  từ `/roles`).
- `/roles` (`DanhSachVaiTro.tsx` dòng ~166) ghi "gán vai trò ở màn Users &
  Phân quyền", nhưng việc gán thật sự nằm ẩn ba tầng trong `UserForm` →
  bảng membership, không hiện ở bảng chính `/users`.
- Cả hai nav item dùng chung icon `users` và chung cổng quyền
  `ACTIONS.WORKSPACE_ADMIN` — không phân biệt được ở tầng quyền.
- Enum vai trò cũ `VaiTro` (`admin/care/editor/viewer`, chết từ migration 0104,
  có comment "đừng dùng lại") vẫn còn trong `auth/nhan.ts`.

Gốc rễ: ba tài liệu (bản đồ module, PQ_01 gốc, và quyết định 2026-08-04 đổi từ
4-vai-trò-cố-định sang vai-trò-tự-định-nghĩa) mô tả ba hình dạng khác nhau cho
khu vực này; code hiện tại là phần còn lại của quá trình tách dần, không khớp
hoàn toàn với bất kỳ tài liệu nào.

**Quyết định đã chốt với chủ sản phẩm** (không nằm trong phạm vi lần này):
tách nhỏ `WORKSPACE_ADMIN` thành quyền riêng cho từng màn, và một màn Permissions
độc lập — cả hai để sau, đây là việc backend/data-model, không phải layout.

## 2. Hai ràng buộc của repo ảnh hưởng tới thiết kế

**① `tests/nav-registry.test.ts` đối chiếu 1:1 route file ↔ `screens.ts`.**
Xoá file route hoặc xoá dòng trong `screens.ts` mà không xoá cả hai ⇒ đỏ. Vì
vậy **không xoá `src/routes/_app/roles.tsx`** — giữ file, chỉ đổi nội dung
thành redirect; giữ dòng `roles` trong `screens.ts` nhưng đổi `inNav: false`
(không còn là mục sidebar, nhưng vẫn là một "màn" hợp lệ với route thật).

**② CLAUDE.md: "Không đổi `lib/nav-registry.ts` trừ khi đổi nhãn menu."**
Việc này đổi *cấu trúc* (bỏ hẳn entry `rolesNav`), không chỉ đổi nhãn — vượt
quy tắc thông thường. Ghi nhận ở đây là **ngoại lệ có chủ đích**: đây chính là
việc chủ sản phẩm yêu cầu (gộp hai mục nav thành một), không phải một sửa đổi
tiện tay đi kèm task khác.

**Gotcha liên quan**: `MemberList.tsx` và `tests/vai-tro.test.tsx` (lúc lên spec
là 2 trong 5 file có nợ định dạng trước theo CLAUDE.md) nằm trong phạm vi sửa
của task này. Vì cả hai đều bị sửa nội dung thật (không phải "dọn giùm"), chạy
`prettier --write` trên chúng là hợp lệ — không tính là "sửa kèm việc khác".
**Đã làm** (commit `7f2059c`), nên nợ định dạng còn **3 file**:
`TaoKhoaDialog.tsx` · `TichHopApiScreen.tsx` · `khoa-dau-noi.test.tsx` — cả ba
đều NGOÀI phạm vi nhánh này, và chúng là lý do duy nhất `make lint` còn đỏ.

## 3. Phạm vi

Chỉ UI/routing. Không đổi API, không đổi data model, không đổi
`ACTIONS.WORKSPACE_ADMIN`, không thêm màn Permissions độc lập.

## 4. Route & Nav

```
/users                     → route giữ nguyên, UserAdmin giờ có 2 tab
/roles                     → redirect sang /users (mở tab "Vai trò")
```

`src/lib/nav-registry.ts`: bỏ entry `rolesNav` khỏi nhóm "Cấu hình". Còn lại
`usersNav`, đổi nhãn:

```ts
label: { vi: 'Thành viên & Phân quyền', en: 'Members & permissions' }
```

Icon giữ `users` (không còn trùng vì `rolesNav` đã biến mất).

`src/lib/screens.ts`: dòng `roles` giữ `path: '/roles'`, đổi `inNav: false`,
note giải thích là redirect sang `/users`.

## 5. Cấu trúc màn hình

**Sửa lại so với vòng chốt trước** (phát hiện khi đọc `auth/api.ts`): vai trò
là thuộc tính của một **membership** (cặp user×workspace), không phải của
user — một user có thể ở N workspace, mỗi workspace một vai trò khác nhau
(`UserDetail.memberships`). Bảng org (`taiDanhSachUser`) chỉ trả
`workspaceCount` (một số), không có breakdown vai trò theo workspace. Vì vậy
**không gộp thành 1 bảng/1 dòng-1 vai trò** — giữ 2 bảng như hiện tại, chỉ đổi
nơi hiển thị (vào trong 1 tab) và thêm sửa vai trò inline an toàn ở bảng dưới.

`UserAdmin.tsx` làm container 2 tab, dùng lại `NhomTab` (pill tab có sẵn trong
`components/ui/Bang.tsx`, đã dùng ở `DuAnList.tsx`) để đồng bộ convention:

```
/users
  ┌ tab Thành viên (mặc định)
  │   Owner: bảng tổ chức (như hiện tại, không đổi) xếp trên bảng thành viên
  │   workspace hiện tại (như hiện tại) — bảng dưới thêm dropdown sửa vai trò
  │   NGAY TẠI DÒNG (thay vì phải mở UserForm).
  │   Non-owner: chỉ bảng thành viên workspace, đọc-only — giữ nguyên nhánh
  │   `session.orgRole !== 'owner'` như hiện tại, không đổi.
  └ tab Vai trò
      DanhSachVaiTro + FormVaiTro giữ nguyên logic (CRUD role + ma trận 13
      action), chỉ đổi nơi hiển thị (trong tab, không phải route riêng)
```

**Sửa vai trò inline an toàn** (bảng thành viên workspace, chỉ owner thấy):
chọn vai trò mới trong dropdown ở dòng → gọi `taiChiTietUser(userId)` lấy
TOÀN BỘ `memberships` hiện tại → khớp tên vai trò cũ sang `roleId` bằng
`layDanhSachVaiTro()` (cùng cách `UserForm` đang làm) → thay đúng entry của
workspace hiện tại bằng `roleId` mới, giữ nguyên mọi entry workspace khác →
gọi `suaUser(userId, { ...UserDetail giữ nguyên, memberships: mảng đã ghép })`.
Không bao giờ gọi `suaUser` với `memberships` chỉ chứa 1 dòng — đó chính là
bug mất dữ liệu đã phát hiện ở vòng review này.

> **Cập nhật 2026-08-07 — bước giữa đã BIẾN MẤT.** Không còn khớp tên vai trò cũ
> sang `roleId` bằng `layDanhSachVaiTro()`: `MemberOut`/`MembershipOut` trả sẵn
> `roleId`, nên các dòng workspace KHÁC chép nguyên `mm.roleId`. `mutationFn` giờ
> chỉ gọi MỘT lệnh (`taiChiTietUser`), không còn `Promise.all` với `['roles']`.
> Bất biến quan trọng nhất của đoạn này thì KHÔNG đổi và vẫn phải giữ: `suaUser`
> thay TOÀN BỘ `memberships`, nên vẫn gửi đủ mọi dòng, không bao giờ gửi 1 dòng.
> Xem §12.

## 6. Thay đổi component

Bảng này đã được **đối chiếu lại với `git diff --stat develop...HEAD`** sau khi
thi công xong; ba dòng của bản chốt đầu sai hoặc thiếu và đã sửa tại chỗ, có ghi
chú. File test không nằm ở đây — xem §8.

> **Cập nhật 2026-08-07.** Ba commit đóng §12 (`22607ea` · `0da56e8` · `412de9c`)
> đụng thêm vào bảng này. Cột Thay đổi của các dòng liên quan có thêm một đoạn
> **[+2026-08-07]** — nội dung trước đoạn đó là việc của vòng gộp tab, sau đoạn
> đó là việc của vòng `roleId`. Không dòng nào MỚI: `roleId` không thêm file
> nguồn nào, chỉ có một file TEST mới (xem §8).

| File | Thay đổi |
|---|---|
| `src/features/auth/components/UserAdmin.tsx` | Thêm tab state (Thành viên / Vai trò); tab 1 render 2 bảng như hiện tại (tổ chức + `MemberList`), tab 2 render `DanhSachVaiTro` |
| `src/features/auth/components/MemberList.tsx` | Thêm cột sửa vai trò inline (dropdown, chỉ hiện khi được nhúng ở nhánh owner) — gọi mutation fetch-merge-patch mô tả ở §5, KHÔNG đổi cấu trúc bảng/API. `onSuccess` bắt buộc phải có `setQueryData` — xem §7. **[+2026-08-07]** `MemberOut` thêm `roleId` (+`export` interface để cổng hình dạng neo vào đúng khai báo); `OVaiTroThanhVien` bỏ CẢ HAI phép dò ngược tên → id — dòng workspace khác chép nguyên `mm.roleId`, nên nửa `fetchQuery(['roles'])` của `Promise.all` và nhánh ném `VAI_TRO_KHONG_DOI_CHIEU_DUOC` biến mất theo; guard dựng dropdown ĐỔI TIÊU CHÍ sang id có tồn tại, không bỏ — xem §12 |
| `src/features/auth/components/UserForm.tsx` | **CÓ ĐỔI** (bản chốt đầu ghi "không đổi", SAI). Vá lỗ leo thang quyền xuyên workspace: bỏ `roleId: …?.id ?? ''`, thay bằng hằng `KHOP_HUT` + `<option disabled>` mang nguyên văn tên server trả, và chặn ở `mutationFn` trước khi gửi. Kèm đổi link nội bộ `/roles` → `/users?tab=vai-tro`. Xem §11. **[+2026-08-07]** Initializer đọc thẳng `m.roleId` thay cho `vaiTroList.find((v) => v.name === m.role)?.id`; `KHOP_HUT` GIỮ cùng cả ba thứ bám vào nó, chỉ đổi TIÊU CHÍ sang id không còn tồn tại (`VAI_TRO_KHONG_DOI_CHIEU_DUOC` → `VAI_TRO_DA_BI_XOA`). Gate `vaiTroList` ở component NGOÀI vẫn còn tác dụng vì initializer vẫn phải PHÂN LOẠI dòng — xem §12. **[+`cfed40d`]** ⚠ Câu ngay trước là NHẬT KÝ của `412de9c`, KHÔNG phải hiện trạng: `KHOP_HUT` và mã `VAI_TRO_DA_BI_XOA` đã GỠ HẲN cùng phép chặn ở `mutationFn`. State giữ `roleId` THẬT, phán quyết phân giải được không tính lúc RENDER — nhờ đó một refetch nền tự chữa dòng đó. Gate `vaiTroList` vì thế mất lý do CŨ (initializer không phân loại gì nữa) và chỉ còn một lý do hẹp: `<select>` cần option, vào thẳng với danh sách rỗng là một cú nhấp nháy nói sai sự thật |
| `src/features/auth/components/DanhSachVaiTro.tsx` | Sửa dòng chú thích (đang trỏ sai tới "màn Users") cho khớp vị trí gán inline mới |
| `src/features/auth/api.ts` | **Thiếu ở bản chốt đầu.** Xoá `export type VaiTro = 'admin' \| 'care' \| 'editor' \| 'viewer'` (enum chết từ migration 0104) — nó sống ở ĐÂY, không phải `nhan.ts`; sửa các docstring `MembershipIn.roleId` và `VaiTroToChuc` vốn trỏ ngược vào kiểu vừa xoá. **[+2026-08-07]** `MembershipOut` thêm `roleId` + viết lại docstring (id để neo, tên để hiện) |
| `src/features/auth/nhan.ts` | Xoá `NHAN_VAI_TRO` + `VAI_TRO_THEO_THU_TU` (hai bảng nhãn dịch enum đó) và import `VaiTro`; ghi lại docstring đầu file. **Bản chốt đầu quy cả `VaiTro` cho file này — sai chỗ, xem dòng `api.ts` ngay trên** |
| `src/features/auth/nav.ts` | Xoá `rolesNav`; sửa nhãn `usersNav` |
| `src/lib/nav-registry.ts` | Xoá dòng `rolesNav` khỏi nhóm "Cấu hình" (ngoại lệ có chủ đích, xem §2) |
| `src/lib/screens.ts` | Dòng `roles`: `inNav: false` + note |
| `src/routes/_app/roles.tsx` | Đổi thành route redirect-only sang `/users` |
| `src/routes/_app/users.tsx` | Thêm `validateSearch` đọc `?tab=` (khuôn `?tab=` của `/pform`) |
| `src/features/auth/tabUsers.ts` | **File mới** — `TenTabUsers`, `TAB_USERS`, `tabHopLe()`; tách khỏi component vì route cần nó lúc `validateSearch` (cùng lý lẽ `realestate/tabDuAn.ts`) |
| `src/lib/msw/handlers.ts` | Vá `GET /api/v1/members` — xem §9. **[+2026-08-07]** `raMembershipOut` và `GET /members` trả `roleId`; trích `tenVaiTroGia()` làm MỘT nguồn dịch id → tên (trước đó `/members` lặp lại biểu thức đó dù comment tự nhận là một nguồn) |
| `CLAUDE.md` | **Thiếu ở bản chốt đầu** (không phải component, nhưng có trong diff của nhánh). Đo lại nợ định dạng 5 → 3 file sau khi dọn `MemberList.tsx`/`vai-tro.test.tsx`, và thêm gotcha `tsc --noEmit` là cổng rỗng ở repo này. **[+2026-08-07]** Ghi hợp đồng mới (`roleId`) + cổng cấu trúc thứ tư, 20 → 21 file test |
| `docs/superpowers/specs/2026-07-29-…-ban-do-module.md` | **Thiếu ở bản chốt đầu.** Bản đồ module là tài liệu mô tả kiến trúc HIỆN TẠI nên phải theo: đổi nhãn sidebar `users` sang Thành viên & Phân quyền và chú giải vì sao `roles` không có dòng riêng |
| `docs/superpowers/plans/2026-08-06-…` | Thêm khối cảnh báo đầu file: đây là nhật ký, và mẫu code `OVaiTroThanhVien` ở Task 3 mang đúng bốn khuyết tật đã bị thay thế — đừng chép lại |

`src/routeTree.gen.ts` **không** đổi: không thêm/xoá file route nào (`roles.tsx`
được giữ lại và đổi nội dung, đúng ràng buộc ① ở §2), nên không phải chạy
`make routes`.

## 7. Data flow

Không thêm endpoint mới. Sửa vai trò inline dùng lại 3 lệnh gọi đã có, ghép ở
client — `MemberList.tsx`, hàm `OVaiTroThanhVien`: `taiChiTietUser(userId)` (lấy
full `memberships`) + `layDanhSachVaiTro()` (khớp tên → id) →
`suaUser(userId, {...})`.

Một điểm code cuối chặt hơn bản chốt đầu: hai vế của phép khớp tên↔id phải đọc
trong CÙNG một nhịp — `Promise.all([taiChiTietUser(m.userId), queryClient
.fetchQuery({ queryKey: khoaVaiTro.tatCa, queryFn: layDanhSachVaiTro })])`. Lấy
một `chiTiet` MỚI rồi đem so với `list` CŨ nằm sẵn trong cache `['roles']`
(`refetchOnWindowFocus` tắt) chính là công thức sinh ra khớp hụt, và khớp hụt ở
đây từng nghĩa là ghi đè mất membership.

> **Cập nhật 2026-08-07 — hai đoạn trên nói về code ĐÃ THAY.** `mutationFn` nay
> gọi ĐÚNG MỘT lệnh: `taiChiTietUser(m.userId)`. Thân PATCH dựng hoàn toàn từ thứ
> server vừa trả, dòng workspace khác chép nguyên `mm.roleId`.
>
> Hệ quả đáng ghi: **ràng buộc cùng một nhịp đã tự tan.** Nó tồn tại vì phép
> khớp có HAI vế đọc ở hai thời điểm; còn một vế thì không có gì để lệch, nên
> `Promise.all` và cả ràng buộc ẩn về độ tươi của cache `['roles']` đều biến mất
> khỏi `mutationFn`. Đây là ví dụ sạch của việc sửa hợp đồng xoá được cả một lớp
> quy tắc ở client, thay vì thêm một lớp giữ cho quy tắc đó đúng.
>
> `vaiTroList` vẫn còn trong component — nhưng để DỰNG OPTION và để kiểm id có
> tồn tại, không còn để dò ngược. Xem §12.

### ⚠ `onSuccess` — bản chốt đầu của mục này NÓI SAI, đừng khôi phục nó

Bản đầu viết: invalidate `['members']` … không cần invalidate `['users']` vì
bảng tổ chức không hiện vai trò. Sai, và sai theo hướng nguy hiểm — ai đọc câu
đó rồi nhìn code sẽ tưởng dòng `setQueryData` là thừa so với thiết kế và gỡ đi.
Code cuối làm BỐN việc:

```ts
onSuccess: (daLuu) => {
  queryClient.setQueryData(['users', m.userId], daLuu)          // ①
  void queryClient.invalidateQueries({ queryKey: ['members'] })  // ②
  void queryClient.invalidateQueries({ queryKey: ['users'] })    // ③
  void queryClient.invalidateQueries({ queryKey: khoaVaiTro.tatCa }) // ④
}
```

**① `setQueryData(['users', m.userId], daLuu)` — DÒNG CHỐNG LẬT NGƯỢC DỮ LIỆU.**
Không phải tối ưu tốc độ, và KHÔNG phải bản trùng của ③. Lý do nằm ở `UserForm`:
nó dựng state bằng `useState` initializer, thứ chạy đúng MỘT lần ở render đầu —
mà render đầu lại do React Query phục vụ bằng CACHE (`['users', userId]`, xem
`UserAdmin.tsx`). Invalidate một query đang INACTIVE chỉ đánh dấu nó *stale*,
không nạp lại ngay: lần mount sau VẪN trả bản CŨ ở render đầu, đúng lúc
initializer chụp ảnh. Hậu quả đã đo: đổi vai trò inline → mở lại form Sửa →
form hiện vai trò CŨ → bấm Lưu là lật ngược thay đổi vừa làm, không một thông
báo nào. Có test khoá: `tests/user-admin.test.tsx` ② đổi vai trò inline rồi mở
lại form Sửa: form hiện vai trò MỚI, không lật ngược (repro 5 bước). **Gỡ ① thì
test đó đỏ — đừng gỡ.**

**② `['members']`** — chính bảng vừa sửa, đọc lại vai trò mới.

**③ `['users']`** — bảng tổ chức đúng là không hiện vai trò, nhưng khoá này khớp
theo TIỀN TỐ: nó phủ cả danh sách `['users']` lẫn MỌI `['users', id]` chi tiết.
Nó bổ sung cho ① chứ không thay được ①: đánh dấu stale chỉ sửa lần nạp SAU, còn
render đầu — chỗ `useState` chụp ảnh — vẫn đọc cache.

**④ `khoaVaiTro.tatCa`** (`['roles']`) — đổi vai trò một người làm đổi
`userCount` của HAI vai trò, và cột Đang gán ở tab Vai trò đọc từ đó. Trước
khi gộp tab, hai màn là hai route nên cache luôn nạp lại; chung một màn rồi thì
phải tự dọn.

## 8. Testing

Dưới đây là **thực tế đã làm** (đối chiếu `git diff develop...HEAD -- tests/`),
không phải dự kiến — hai gạch đầu dòng đầu của bản chốt đầu đã sai, ghi rõ ở chỗ
của chúng.

> **Cập nhật 2026-08-07 — ba con số và một bài dưới đây đã CŨ.** Vòng `roleId`
> (§12) đụng tiếp vào `tests/user-admin.test.tsx`. Đo lại trên HEAD:
>
> - `tests/user-admin.test.tsx`: **27 bài** (không còn là 26).
> - **Một bài đã XOÁ**: khớp hụt ở workspace KHÁC thì không gửi PATCH nào —
>   kịch bản không dựng được nữa sau khi bỏ phép dò ngược. Bất biến nó canh
>   (thấy bất thường thì KHÔNG PATCH) vẫn còn bài ⑤ và ⑥ khoá, nên không hở.
> - **Bài ④ đổi mục tiêu** sang `roleId` không có trong ảnh chụp `['roles']`,
>   với TÊN cố ý vẫn khớp một vai trò sống — đúng hình dạng lỗi mà id giết. Và
>   một bài MỚI đọc THÂN PATCH thật với một vai trò mạo danh trùng tên trong
>   `/api/v1/roles` (ĐỎ trên code cũ: gửi `role_gia_mao_danh` thay vì
>   `role_gia_xem`).
>   ⚠ Tên bài và comment của nó nói vai trò ĐÃ XOÁ cho tới `f03da45`; đó là lý
>   lẽ đã bị bác bỏ (xem §12) và đã được đính chính cùng commit ấy.
> - **Bốn bài `UF①`–`UF④`** dựng lại trên hai kịch bản tách đôi:
>   `dungKichBanAnhChupThieu()` (tên tới `f03da45`; trước đó là
>   `dungKichBanVaiTroDaXoa()`) và `dungKichBanDoiTen()` (đổi tên nay là dữ liệu
>   bình thường). `UF②` đổi mục tiêu và `UF④` là bài mới — hai bài này khoá lại
>   mục ② của §12 **cho riêng trigger ĐỔI TÊN**; trigger không phân giải được
>   phải chờ `UF⑤`/`UF⑥` ở `cfed40d`.
> - **File test MỚI**: `tests/membership-shape-parity.test.ts` — cổng cấu trúc
>   thứ tư, canh hình dạng `MembershipOut`/`MemberOut` giữa kiểu FE và fake MSW.
>   Tổng file test 20 → **21**. Nó KHÔNG so hai repo; xem cảnh báo ở §12.

- `tests/user-admin.test.tsx`: **13 → 26 test** (+13). Bốn hạng mục dự kiến ở bản
  chốt đầu (đổi tab · `/roles` redirect · hai bài sửa vai trò inline) đều có, ra
  **5 bài** — "đổi tab" tách làm hai (mặc định mở Thành viên · bấm sang Vai
  trò). **8 bài còn lại là phát sinh**, sinh từ những lỗi phát hiện lúc thi
  công: form Sửa lật ngược dữ liệu (bài ② — cổng khoá `setQueryData` ở §7) ·
  khớp hụt tên vai trò thì hiện pill tĩnh, không dựng dropdown nói dối · chủ tổ
  chức lọt vào bảng workspace · membership biến mất giữa chừng · khớp hụt ở
  workspace KHÁC thì không gửi PATCH nào · và **3 bài hồi quy** của bản vá leo
  thang quyền ở `UserForm` (xem §11).
- `tests/vai-tro.test.tsx`: **9 → 12 test**, và **có sửa test cũ** — bản chốt đầu
  ghi các test hiện có không cần sửa, SAI. Test ⑧ (dropdown rỗng) phải đổi kỳ
  vọng `href` từ `/roles` sang **`/users?tab=vai-tro`**: link nội bộ trỏ thẳng
  tab, không đi vòng qua shim redirect — và chốt cả query string vì `to`+`search`
  mà rơi mất `search` thì link vẫn xanh nhưng mở ra nhầm tab. Ba bài mới ⑩⑪⑫ canh
  hạ tầng MSW `/api/v1/members` (xem §9): ⑩ chỉ trả người còn hiệu lực ở workspace
  hiện tại kèm tên vai trò thật · ⑪ `roleId` RỖNG bị cổng `ROLE_NOT_IN_ORG` chặn
  (chuỗi rỗng là falsy nên từng lọt) · ⑫ fake đi theo workspace ĐANG MỞ, không
  ghim workspace khởi đầu. Kèm `RESET_WS_DANG_MO()` trong `beforeEach` vì ⑫ đổi
  trạng thái module-level đó.
- `tests/boot.test.tsx`: **có sửa** (bản chốt đầu không nhắc tới file này) — chỉ
  comment. Dòng `roles` trong `DAU_HIEU_MAN_THAT` nay canh việc redirect dẫn tới
  ĐÚNG tab, và lý do cũ (sidebar cũng có mục Vai trò nên nhãn nav trúng hai
  phần tử) đã hết đúng sau khi xoá `rolesNav`.
- `tests/nav-registry.test.ts`: **phải sửa** — bỏ `'roles'` khỏi
  `PROTOTYPE_SIDEBAR_ORDER`, đổi test "4 màn ngoài sidebar" thành 5 màn, xoá
  test "`roles` nằm trong nhóm Cấu hình ngay sau `users`" (tiền đề của nó
  không còn đúng). Hai phép kiểm cấu trúc quan trọng vẫn xanh nguyên trạng:
  "mỗi màn có đúng một route file" và "path nav khớp `screens.ts`".
- `tests/shell.test.tsx`: sửa một chuỗi nhãn nav (`'Users & Phân quyền'` →
  `'Thành viên & Phân quyền'`).
- `tests/members.test.tsx`: **có sửa** (bản chốt đầu ghi không sửa, SAI) —
  nhưng chỉ comment, không đổi một assertion nào: hai chỗ nhắc `NHAN_VAI_TRO`
  được ghi thêm đã xoá 2026-08-06 để chú thích đừng trỏ vào một thứ không còn
  tồn tại. Phần hành vi đúng như dự kiến: `MemberList` giữ mặc định chỉ-đọc
  (`suaDuocVaiTro` mặc định `false`), nên dropdown inline không lọt vào file này.

## 9. Việc kèm theo bắt buộc — vá fake `/api/v1/members`

`GET /api/v1/members` trong `src/lib/msw/handlers.ts` hiện là **2 dòng viết
cứng, đứng ngoài `USERS_GIA`/`VAI_TRO_GIA`** — và một trong hai dòng gán
Quản trị cho chính chủ tổ chức, người mà `USERS_GIA` luôn để
`memberships: []` (đúng luật: owner không cần membership riêng). Không vá thì
sửa-vai-trò-inline không có dữ liệu thật để chạy: mọi `taiChiTietUser()` phát
từ một dòng của `MemberList` sẽ 404. Vá = tính từ `USERS_GIA`, lọc theo
workspace đang mở + `conHieuLuc()`, đọc tên vai trò từ `VAI_TRO_GIA`.

Đây là điều kiện để tính năng chạy được, không phải dọn dẹp ngoài lề.

## 10. Không nằm trong phạm vi

Tách quyền `WORKSPACE_ADMIN` thành quyền chi tiết theo màn; màn Permissions
độc lập để audit toàn bộ 13 action; bất kỳ đổi model dữ liệu backend.

## 11. Phát sinh trong lúc thi công — mở rộng phạm vi sang `UserForm`

> 🏛 **KHẢO CỔ (ghi 2026-08-07).** Mục này mô tả bản vá `KHOP_HUT` ở thời điểm FE
> còn phải **đối chiếu ngược TÊN → id**. Phép đối chiếu đó **không còn tồn tại**:
> §12 đã được giải quyết, `MembershipOut`/`MemberOut` trả thẳng `roleId`
> (backend `70f2f60`; FE `22607ea` · `0da56e8` · `412de9c`).
>
> Hằng `KHOP_HUT` cũng **không còn trong code** (gỡ 2026-08-07 — xem ô cập nhật ở
> §12). Trong ba thứ bám vào nó, chỉ `<option disabled>` mang nguyên văn tên
> server trả là sống tiếp: đó mới là phép chống leo thang quyền. State giữ
> `roleId` THẬT, phán quyết phân giải được không tính lúc RENDER, và phép chặn
> lúc Lưu đã bỏ hẳn.
>
> Đọc mục này để hiểu VÌ SAO có bộ máy đó, đừng đọc để biết nó đang kiểm gì.

Spec ban đầu ghi `UserForm.tsx` **không đổi** (§6). Nó đã đổi, có chủ đích. Ghi
lại ở đây vì việc mở rộng phạm vi là thứ phải giải trình, không phải thứ để lặng
lẽ trôi qua.

**Lớp lỗi.** Trong lúc dựng ô sửa vai trò inline ở `MemberList`, phép khớp ngược
TÊN vai trò → `roleId` lộ ra hai khuyết tật đi cùng nhau:

1. `?? ''` khi khớp hụt — bịa ra một `roleId` không tồn tại thay vì nói thật.
2. Dựng `<select>` mà không guard trường hợp `value` không khớp option nào —
   trình duyệt lẳng lặng hiện OPTION ĐẦU.

**Chỗ đau.** Hai khuyết tật đó có ở CẢ HAI nơi: `MemberList` (code MỚI của việc
này) lẫn `UserForm` (code CÓ TRƯỚC, ngoài phạm vi ban đầu). Và ở `UserForm` thì
nặng hơn, vì `suaUser` PATCH thay TOÀN BỘ `memberships` của MỌI workspace trong
một nhịp, không chỉ một dòng của workspace đang mở.

**Hậu quả đo được — leo thang quyền xuyên workspace, im lặng.** User có
`ws_anphu` = Quản trị + `ws_sunrise` = Người xem; đổi tên vai trò của
`ws_sunrise` ở tab Vai trò là đủ để dòng đó trong form HIỆN Quản trị. Owner
mở form ra vì việc khác, thấy ô đang hiện đúng thứ họ tưởng, bấm Lưu → PATCH
200, không một thông báo nào, và Sunrise bị NÂNG QUYỀN. Biến thể thứ hai của
cùng một lỗi: chỉ đổi số điện thoại, không chạm dropdown nào, thân PATCH vẫn
mang `roleId: ''` → 422 đổ lỗi cho một lựa chọn người dùng chưa hề làm.

Cả hai đã vá trong nhánh này: `MemberList` ở `7f0c94b`, `UserForm` ở `001c160`.

**Vì sao mở rộng phạm vi thay vì ghi một issue.** Bốn lý do, theo thứ tự sức
nặng:

- **Cùng một lớp lỗi, đã hiểu xong.** Sửa một nửa và để nửa kia lại nghĩa là
  giữ nguyên lỗ hổng, chỉ chuyển nó sang một file khác — trong khi phân tích
  đắt nhất (vì sao khớp hụt xảy ra được) vừa làm xong.
- **Cùng khu vực, cùng lần chạm.** `UserForm` nằm ngay trong tab Thành viên
  của chính màn đang gộp; hai đường vào của cùng một thao tác gán vai trò.
- **Đã có sẵn mẫu sửa.** `KHOP_HUT` + `<option disabled>` nói nguyên văn + chặn
  ở `mutationFn` là bản dịch trực tiếp của cách đã dùng ở `MemberList` (pill
  tĩnh thay vì dropdown nói dối). Không phải thiết kế lại.
- **Đã có sẵn hạ tầng test.** `tests/user-admin.test.tsx` vừa được dựng khuôn
  `RESET_USERS_GIA`/`RESET_VAI_TRO_GIA` cho hai bài inline; ba bài hồi quy của
  `UserForm` cắm thẳng vào đó. Hai bài đầu **đã quan sát ĐỎ trước khi sửa** (①
  ô hiện `role_gia_qt`, ② thân PATCH thật sự mang `roleId: ''`).

**Ranh giới đã giữ.** Mở rộng dừng ở đúng lớp lỗi này: không đụng API, không đổi
data model, không dọn kèm thứ gì khác trong `UserForm`.

## 12. Nợ CÓ CHỦ ĐỊNH — hai thứ FE không tự đóng được

> ## ✅ ĐÃ GIẢI QUYẾT — 2026-08-07 (đóng hẳn ở `cfed40d`, KHÔNG phải ở `412de9c`)
>
> Backend đã đóng gốc chung bằng **cách 1** của danh sách cuối mục này: đường ĐỌC
> trả kèm `roleId`. Phép đối chiếu ngược TÊN → id đã bị **xoá khỏi FE**, không
> phải bọc thêm một lớp đoán nữa.
>
> | Repo | Commit | Việc |
> |---|---|---|
> | backend | `70f2f60` | `MembershipOut` **và** `MemberOut` trả kèm `roleId` |
> | frontend | `22607ea` | Lớp HÌNH DẠNG: kiểu FE + fake MSW + cổng `membership-shape-parity.test.ts` |
> | frontend | `0da56e8` | `MemberList` đọc thẳng `roleId`, bỏ hai phép dò ngược trong `OVaiTroThanhVien` |
> | frontend | `412de9c` | `UserForm` đọc thẳng `roleId`; `KHOP_HUT` đổi TIÊU CHÍ, không xoá — **② mới khỏi MỘT trigger tới đây** |
> | frontend | `cfed40d` | **Gỡ HẲN phép chặn ở `mutationFn`** + bỏ `KHOP_HUT`, phán quyết chuyển sang lúc RENDER — chỗ ② thật sự đóng |
> | frontend | `f03da45` | Fake MSW đếm `userCount` như backend; đính chính lý lẽ vai trò đã xoá chép vào comment test |
>
> **① đã chết theo đúng nghĩa đen**: không còn phép dò nào để trượt.
>
> **② có HAI trigger, và chúng đóng ở HAI thời điểm khác nhau.** Bản chốt đầu của
> ô này viết ② tự khỏi như HỆ QUẢ rồi tuyên ĐÃ GIẢI QUYẾT — đúng cho trigger
> thứ nhất, sai cho tổng thể. Trình tự thật:
>
> | Trigger sinh ra một dòng hỏng | Khỏi khi nào | Bằng cái gì | Bài khoá |
> |---|---|---|---|
> | **ĐỔI TÊN vai trò** (dò ngược tên → id trượt) | `0da56e8` + `412de9c` | `roleId` giết lớp khớp SAI; đổi tên nay là dữ liệu hoàn toàn bình thường | UF② (đổi số điện thoại vẫn PATCH được) · UF④ (ĐÌNH CHỈ đi qua được) — cả hai dựng trên `dungKichBanDoiTen()` |
> | **KHÔNG PHÂN GIẢI ĐƯỢC** (`roleId` không có trong ảnh chụp `['roles']`) | `cfed40d`, **muộn hơn một commit** | Gỡ hẳn phép chặn ở `mutationFn` | UF⑤ (đình chỉ đi qua được khi CÓ dòng chưa phân giải được) · UF① (không leo thang quyền + Lưu không bị chặn) · UF⑥ (ảnh chụp về đủ thì ô tự lành) |
>
> Trigger thứ hai **còn sống nguyên** sau `412de9c`: một dòng thật sự không phân
> giải được VẪN chặn toàn bộ form, kể cả ĐÌNH CHỈ TÀI KHOẢN — tức nửa nặng nhất
> của ② (một trục trặc HIỂN THỊ chặn một thao tác THU HỒI QUYỀN) chưa mất đi
> đâu cả. UF②/UF④ không bắt được vì cả hai dựng trên kịch bản ĐỔI TÊN, thứ
> `roleId` đã giết — ở đó không còn dòng nào hỏng để mà chặn, nên hai bài xanh
> mà không chứng minh gì về trigger kia.
>
> Lý lẽ của việc gỡ (`cfed40d`): phép chặn có từ thời FE buộc phải phân giải được
> tên → id thì mới dựng nổi payload; `MembershipOut.roleId` xoá bỏ ràng buộc đó.
> Một dòng không đụng tới gửi lại NGUYÊN `m.roleId` — id server vừa phát ra qua
> INNER JOIN `control.roles` — nên là no-op an toàn theo định nghĩa. Hằng
> `KHOP_HUT` gộp hai chuyện vốn khác nhau: không hiện được nhãn đẹp (còn thật)
> và không gửi được an toàn (hết thật). Code chặn theo vế thứ hai.
>
> Phép bảo vệ THẬT — `<option disabled>` mang tên server trả và đang được chọn,
> để `<select>` không rơi về option đầu — giữ nguyên, và giờ là thứ duy nhất giữ
> vai trò đó.
>
> ### 📌 BÀI HỌC — đã giải quyết tuyên khi mới đóng MỘT trigger
>
> Một vấn đề nêu bằng HẬU QUẢ (một dòng hỏng chặn cả form) thường có nhiều
> NGUYÊN NHÂN dẫn tới cùng hậu quả đó. Vòng đầu diệt nguyên nhân áp đảo, thấy hai
> bài hồi quy xanh, rồi viết ✅ — nhưng hai bài đó chỉ dựng được trên đúng nguyên
> nhân vừa bị diệt, nên chúng **không thể** đỏ vì nguyên nhân còn lại. Test xanh ở
> đây là hệ quả của việc kịch bản không dựng được nữa, không phải bằng chứng bất
> biến còn đứng.
>
> Cách tránh, rẻ hơn nhiều so với một vòng nghiệm thu nữa: trước khi viết ✅, liệt
> kê MỌI đường sinh ra điều kiện kích hoạt, rồi hỏi từng đường bài nào đỏ nếu
> đường này còn sống. Đường nào không có bài nào ⇒ chưa đóng.
>
> ### Sự thật về BACKEND — ba phép đo, và đường đến được THẬT
>
> Ghi ngay ở đây vì lý lẽ SAI lan xa hơn nhiều so với chỗ nó được viết ra. Riêng
> `UserForm.tsx` từng có bản SAI nằm ngay tại ĐIỂM DÙNG (comment cạnh câu nhắc
> dưới ô vai trò) trong khi bản ĐÚNG nằm cách đó ~450 dòng ở docstring đầu file —
> người đọc lướt bắt được bản sai trước. Ba phép đo:
>
> 1. `repo.dem_nguoi_dung_vai_tro` = `SELECT count(*) FROM control.memberships
>    WHERE role_id = $1` — **KHÔNG có** vị từ `expires_at`. Nó đếm CẢ vé hết hạn.
> 2. Migration `0104_vai_tro_dong`: FK `(org_id, role_id)` là **`ON DELETE
>    RESTRICT`** — lưới thứ hai ở tầng DB.
> 3. `liet_ke_membership` và `liet_ke_thanh_vien` đều **INNER JOIN
>    `control.roles`** ⇒ backend **không bao giờ phát ra một `roleId` treo**.
>
> Điểm 3 là điểm NẶNG nhất và hay bị bỏ quên: nó làm vai trò đã bị xoá thành
> trạng thái không đến được **bất kể** luật xoá chặt hay lỏng. Đừng chống lại câu
> đã bị xoá bằng riêng điểm 1 — chính việc tin điểm 1 có kẽ hở đã đẻ ra cả lý lẽ
> sai này (xem ô ⛔ cuối mục).
>
> **Đường đến được THẬT: ảnh chụp `['roles']` của FE bị THIẾU.** `main.tsx` đặt
> `refetchOnWindowFocus: false`, nên một vai trò TẠO sau khi cache đầy rồi gán cho
> ai đó sẽ không có trong `vaiTroList`. `/roles` và `/users/:id` là hai phản hồi
> đọc ở hai thời điểm — FE không CHỨNG MINH được mọi `roleId` đều phân giải được,
> chỉ có thể kiểm. Guard vì thế vẫn phải giữ, chỉ là giữ vì lý do khác.
>
> ⚠ **KHÔNG có cổng CI nào canh hình dạng DTO giữa HAI REPO.**
> `membership-shape-parity.test.ts` chứng minh *fake MSW = kiểu FE* — cả hai đều
> nằm trong repo này. Không gì chứng minh kiểu FE = `contracts.py` của backend:
> `contracts/*.json` không mang hình dạng DTO, và repo không có snapshot OpenAPI.
> Backend đổi `MembershipOut`/`MemberOut` mà FE không theo thì **mọi cổng vẫn
> xanh** — đúng cái đã xảy ra với `roleId` suốt từ 2026-08-04 tới 2026-08-07.
> Cùng họ với khoảng hở §8.1② của spec `2026-08-04-phan-quyen-dong-design.md`
> (bản sao `contracts/actions.json`), chỉ khác là chỗ này không có cả một artefact
> để mà copy. Xem `docs/superpowers/specs/2026-08-07-membership-roleid-duong-doc.md`
> ở repo backend.
>
> Phần văn bản bên dưới **giữ nguyên làm nhật ký** — nó ghi lại nợ này là gì và
> vì sao FE không tự đóng được. Đọc nó ở thì QUÁ KHỨ.

Vòng nghiệm thu cuối tìm ra hai vấn đề còn sống. Cả hai có CÙNG một gốc, và gốc
đó nằm ở hợp đồng API chứ không ở FE — nên chúng được ghi lại ở đây thay vì vá
tạm bằng thêm một lớp đoán mò nữa.

**Gốc chung**: `MembershipOut` trả **TÊN** vai trò (`role: string`), không trả
`roleId`. FE buộc phải đối chiếu ngược tên → id qua danh sách `/api/v1/roles`.
Tên là khoá **đổi được**; id thì không. Chính `api.ts` (docstring
`MembershipIn.roleId`) đã viết `id` là handle ổn định duy nhất — nhưng đường
đọc lại không có id để dùng.

> **Bổ sung 2026-08-07 — mục này ĐẾM THIẾU một DTO.** Bản gốc chỉ nêu
> `MembershipOut` (`GET/POST/PATCH /users`). Còn **`MemberOut`** (`GET
> /api/v1/members`) — nguồn của bảng thành viên workspace, tức chỗ đối chiếu
> ngược **thứ ba** và cũng là chỗ có đường GHI (ô sửa vai trò inline ở §5). Sót
> nó là sót đúng nửa mà người dùng chạm vào nhiều hơn: `UserForm` phải mở ba tầng
> mới tới, còn bảng thành viên thì nằm ngay tab mặc định.
>
> Vá một DTO thôi thì đường qua bảng thành viên vẫn mở nguyên — nên **cả hai đã
> sửa trong cùng một commit backend** (`70f2f60`), và FE theo bằng `22607ea`
> (hình dạng, cả hai kiểu) → `0da56e8` (`MemberList`) → `412de9c` (`UserForm`).

**① Khớp SAI (khác khớp HỤT) vẫn im lặng.** Bản vá chặn được trường hợp không
tìm thấy tên. Nhưng nếu cache `['roles']` cũ và một cái TÊN đã dời sang một id
khác, `find()` trả về một id **hợp lệ** — không có `KHOP_HUT`, không có option
cảnh báo, không có chặn. Đo được giống hệt nhau ở cả hai phía bản vá, tức đây là
nợ có trước, không phải hồi quy. Có ở `UserForm` và `MemberList`.

**② Một dòng khớp hụt chặn TOÀN BỘ form.** Không đổi được số điện thoại, không
đổi được vai trò ở workspace khác vốn hợp lệ, và — nặng nhất — không **đình chỉ**
được tài khoản: một trục trặc HIỂN THỊ đang chặn một thao tác THU HỒI QUYỀN.
Chặn là đúng về mặt dữ liệu (`suaUser` thay TOÀN BỘ `memberships`; gửi thiếu hay
gửi bịa đều hỏng) và không mới — trước bản vá server cũng chặn bằng 422, chỉ khác
là câu lỗi đổ lỗi sai chỗ. Nhưng cái giá thì vẫn còn nguyên.

**Cách đóng, theo thứ tự ưu tiên** (đều cần backend):

1. `MembershipOut` trả thêm `roleId`. Xoá hẳn phép đối chiếu ngược theo tên ⇒
   diệt cả ① lẫn nguyên nhân sinh ra ②. Đây là cách sửa tận gốc.
   → **Đã chọn và đã làm 2026-08-07** (kèm `MemberOut`, xem ô bổ sung ở trên).
2. Hoặc: cho `PATCH /users/:id` nhận một dấu giữ nguyên dòng này cho từng
   membership, để FE không phải gửi lại `roleId` của những dòng người dùng không
   đụng tới ⇒ hạ riêng ②.
   → **Không làm, và không cần nữa**: cách 1 đã hạ ② như hệ quả. Nếu ngày nào đó
   quay lại, biết rằng nó giải quyết một vấn đề KHÁC còn sống — `suaUser` thay
   TOÀN BỘ `memberships`, thứ khiến mọi lần Lưu là một phép ghi đè trọn gói.

Không làm ở nhánh này vì cả hai đổi hợp đồng HTTP, tức đổi phạm vi từ layout
sang API — đúng thứ §3 đã loại trừ.

### ⚠ Cái `roleId` KHÔNG diệt — không phân giải được (bổ sung 2026-08-07)

`roleId` diệt lớp **khớp SAI** (một cái TÊN dời sang id khác, `find()` trả về
một id hợp lệ nhưng của vai trò khác). Nó **không** diệt lớp **không phân giải
được**: `roleId` server trả không có mặt trong `vaiTroList` mà FE đang cầm.

Vì sao lớp này vẫn phải được canh, dù id đã ổn định: `<select>` có `value` không
khớp `<option>` nào **vẫn im lặng hiện OPTION ĐẦU** — đúng cơ chế leo thang quyền
mà §11 mô tả, chỉ đổi nguyên nhân đầu vào. Cơ chế nổ không đổi thì guard không
được bỏ.

Nên bộ máy cảnh báo có sẵn được **ĐỔI MỤC TIÊU, không xoá**: `KHOP_HUT` +
`<option disabled>` mang nguyên văn tên + phép chặn ở `mutationFn` giữ nguyên cả
ba, chỉ đổi TIÊU CHÍ từ tên server trả không đối chiếu ngược được sang id
server trả không còn tồn tại (`UserForm.tsx`; guard song sinh ở `MemberList.tsx`
dựng pill tĩnh thay vì dropdown). Mã lỗi client đổi theo:
`VAI_TRO_KHONG_DOI_CHIEU_DUOC` → `VAI_TRO_DA_BI_XOA`.

> **Đoạn trên đã LỖI THỜI 2026-08-07 (vòng sau).** Giữ hai trong ba, bỏ một —
> không phải giữ cả ba. `<option disabled>` sống tiếp (nó là phép chống leo thang
> quyền). `KHOP_HUT` bị gỡ: state giữ `roleId` THẬT và phán quyết chuyển sang lúc
> RENDER, nhờ đó một refetch nền tự chữa lành dòng đó thay vì đóng băng cả phiên
> form. **Phép chặn ở `mutationFn` bỏ hẳn**, cùng mã lỗi `VAI_TRO_DA_BI_XOA` —
> xem ô ⚠ ② chỉ đóng HẲN khi phép chặn bị GỠ ở đầu §12.

**Trạng thái đó đến được bằng đường nào — đã kiểm lại trong code backend, và câu
trả lời KHÁC với điều nhánh này từng ghi.** Xem ô dưới.

> #### ⛔ Đính chính — membership hết hạn trỏ tới vai trò đã xoá KHÔNG đến được
>
> Lý lẽ ghi trong commit `0da56e8`/`412de9c` và trong comment của hai component
> nói rằng: backend chỉ chặn xoá vai trò khi `userCount > 0`, mà `userCount` chỉ
> đếm membership CÒN HIỆU LỰC, nên một membership ĐÃ HẾT HẠN trỏ tới vai trò vừa
> xoá là trạng thái đến được. **Đọc lại code backend 2026-08-07: sai.** Backend
> chặn đường đó ở BA lớp — hai lớp đầu đều đếm/giữ cả dòng đã hết hạn, lớp thứ ba
> làm cả câu hỏi xoá có chặt không thành không liên quan:
>
> 1. `repo.dem_nguoi_dung_vai_tro` — `SELECT count(*) FROM control.memberships
>    WHERE role_id = $1`, **không có** vị từ `expires_at`. Docstring của
>    `liet_ke_vai_tro` ngay cạnh nói thẳng chủ ý: Đếm CẢ membership đã hết hạn:
>    xoá vai trò sẽ vỡ FK vì hàng đó vẫn tồn tại.
> 2. Migration `0104`: `FOREIGN KEY (org_id, role_id) REFERENCES control.roles
>    (org_id, id) **ON DELETE RESTRICT**` — lưới cuối ở tầng DB.
> 3. `liet_ke_membership` và `liet_ke_thanh_vien` đều **INNER JOIN
>    `control.roles`** — một `roleId` treo KHÔNG RA KHỎI backend được. Kể cả giả
>    sử lớp 1 và 2 đều thủng, FE vẫn không bao giờ NHÌN THẤY một membership trỏ
>    tới vai trò không tồn tại: hàng đó rụng khỏi kết quả JOIN.
>
> Vé hết hạn vẫn là một HÀNG trong `control.memberships`; FK không quan tâm nó
> còn hiệu lực hay không.
>
> ⚠ Lớp 3 mới là lớp NẶNG, và nó bị bỏ quên suốt vòng đầu. Chống lại câu đã bị
> xoá bằng riêng lớp 1 là chống bằng đúng cái vế mà lý lẽ sai đang tấn công —
> hễ ai tin lớp 1 có kẽ hở (như vòng đầu đã tin) là kết luận sụp theo.
>
> **Đường đến được THẬT là ảnh chụp của FE, không phải phép xoá của BE.**
> `vaiTroList` là dữ liệu của query `['roles']`, và `main.tsx` đặt
> `refetchOnWindowFocus: false`. Một vai trò được TẠO sau khi cache đó đầy, rồi
> được gán cho ai đó, thì `roleId` của membership ấy không có trong danh sách FE
> đang cầm — dòng đó không phân giải được dù không ai xoá gì (câu gốc viết dòng
> đó `KHOP_HUT`; hằng ấy đã gỡ ở `cfed40d`). Tổng quát hơn: `/roles` và
> `/users/:id` là hai phản hồi đọc ở hai thời điểm, nên FE không bao giờ CHỨNG
> MINH được mọi `roleId` đều phân giải được; nó chỉ có thể kiểm.
>
> Guard vì thế **vẫn đúng và vẫn phải giữ** — chỉ là giữ vì ảnh chụp có thể
> thiếu, không phải vì BE cho xoá. Cái giá của guard là một pill tĩnh; cái giá
> của việc bỏ nó là một lần nâng quyền im lặng.
>
> Tên hằng `VAI_TRO_DA_BI_XOA` và câu lỗi đã bị xoá khỏi danh sách vai trò của
> tổ chức vì thế hơi HẸP hơn sự thật (đúng nghĩa phải là không còn thấy trong
> danh sách vai trò). Không đổi trong lần cập nhật tài liệu này vì đó là code
> thực thi + chuỗi hiển thị + tên trong test; ghi lại ở đây để lần chạm sau biết.
>
> → **Đã làm 2026-08-07 (vòng sau).** Cả mã lỗi lẫn phép chặn sinh ra nó đều bị
> gỡ, nên không còn chuỗi nào phải thu hẹp. Câu duy nhất còn hiện là nhãn của
> `<option disabled>` và dòng nhắc dưới ô — cả hai nói chưa có trong danh sách
> vai trò đã tải / danh sách có thể vừa đổi, không nói đã bị xoá.
>
> ⚠ **Fake MSW từng mã hoá luật NGƯỢC với backend — ĐÃ SỬA ở `f03da45`.**
> `soNguoiDungVaiTro()` (handlers.ts) lọc `conHieuLuc`, tức `userCount` KHÔNG đếm
> vé đã hết hạn — ngược hẳn `repo.dem_nguoi_dung_vai_tro`. **Đó chính là chỗ lý
> lẽ sai ở trên bắt nguồn**: một vòng thiết kế đọc hành vi của fake và tưởng đó
> là hành vi của backend. Fake vì thế cho xoá một vai trò mà backend thật từ chối
> (409 `ROLE_IN_USE`, và FK `ON DELETE RESTRICT` chặn lần nữa).
>
> `f03da45` bỏ bộ lọc đó khỏi `soNguoiDungVaiTro` (hàm `conHieuLuc` GIỮ NGUYÊN —
> `workspaceCount` và `GET /members` vẫn cần, ở hai chỗ đó nó đúng), và **đảo bài
> `⑨` của `tests/vai-tro.test.tsx`**, thứ trước đó đang khoá đúng hành vi sai:
> kỳ vọng cũ `userCount` 0, xoá được → mới `userCount` 1, 409 `ROLE_IN_USE`,
> vai trò còn nguyên trong bảng. Một bài test khoá hành vi của fake thay vì của
> backend là bài test bảo vệ chính cái nó sinh ra để bắt.
