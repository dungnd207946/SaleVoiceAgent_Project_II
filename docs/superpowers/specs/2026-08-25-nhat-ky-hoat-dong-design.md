# Màn «Nhật ký» (`/audit`) — đợt 1: đường ĐỌC `control.audit_log`

**Ngày:** 2026-08-25 · **Nhánh:** BE `feat/nhat-ky-doc` (từ `develop` @ `51f424a`) · FE `feat/man-nhat-ky` (từ `develop` @ `07b8a48`)

## 1. Bối cảnh

Phần GHI nhật ký đã xong từ M5: bảng `control.audit_log` (migration `0201`, chỉ
ghi thêm — `REVOKE UPDATE, DELETE` khỏi `portal_api`), hàm dùng chung
`core/nhat_ky.py` (`ghi` / `ghi_he_thong`), **50 điểm ghi với ~50 mã hành động**
trên 9 module (auth · thành viên · vai trò · khoá agent · publish/rollback · KB ·
BĐS · lĩnh vực · billing · cổng nạp · workspace). Cổng AST
`tests/modules/realestate/test_nhat_ky_day_du.py` bắt mọi route ghi của
realestate phải ghi nhật ký.

Phần ĐỌC chưa có gì: không endpoint nào `SELECT` từ `audit_log`; không action
đọc trong PQ_01; FE có mục nav «Nhật ký» (mảng Quản trị) trỏ tới
`routes/_app/audit.tsx` vẫn là `<ScreenStub/>` — ngõ cụt duy nhất còn nằm trong
sidebar. Có một luồng đang PHỤ THUỘC màn này: job đối soát cổng nạp
(`modules/ingest/jobs.py`) ghi cảnh báo `ingest.tenant_im_lang` vào `audit_log`
với ghi chú *«màn Nhật ký của portal đọc `control.audit_log`, không có kênh thứ
hai»* — cảnh báo đó hiện rơi vào chỗ không ai xem.

Số liệu thật (odyssey-dev, 20→25/08): 266 dòng · 8 workspace · 5 người dùng;
`agent.runtime_credentials` (actor `agent`, mỗi lần agent bootstrap) chiếm
101/266 = 38%. `actor` là `u_<id>` / `"agent"` / `"platform_admin"` / `""`
(job hệ thống). Cố ý KHÔNG có FK `actor → users` (0201: nhật ký sống lâu hơn tài
khoản).

Yêu cầu sản phẩm: PQ_01 YC06 · YC09 · BR-Q07 · BR-Q10; kiến trúc M8/gói F xếp
«tab Nhật ký» vào MVP (`phan-bien…md:308`).

## 2. Quyết định đã chốt (người dùng, 2026-08-25)

| # | Quyết định | Loại bỏ |
|---|---|---|
| 1 | **Thêm action `audit.read`** vào PQ_01, cấp mặc định cho «Quản trị» | Dùng lại `overview.read` + thu hẹp theo `workspace.admin` trong endpoint (rẻ hơn nửa ngày, nhưng quản trị không cấp/thu quyền xem nhật ký riêng được) |
| 2 | **Ẩn hành động máy mặc định** (`actor = 'agent'`), công tắc «Hiện hoạt động của agent». `actor='agent'` gồm CẢ `agent.feedback` (khách chấm điểm qua gateway) — chấp nhận ẩn theo mặc định ở đợt 1 (quyết định 2026-08-25 sau review), đợt 2 xem lại | Bỏ hẳn (mất đường điều tra khoá rò) · hiện tất cả (bảng bị agent chiếm 38%) |
| 3 | **Cổng parity BE↔FE cho sổ mã hành động** (`contracts/audit-actions.json`) | Chỉ sổ FE + fallback mã thô (thêm mã mới không ai bị nhắc) |
| 4 | Phân trang keyset `(luc DESC, id DESC)`, 50 dòng/lần, nút «Tải thêm» — cùng khuôn realestate | Offset (trang trôi khi có hàng mới chèn) |
| 5 | Lọc: **nhóm hành động** (tiền tố trước dấu chấm đầu) · **khoảng ngày** · công tắc agent | Tìm theo người (đợt 2) |
| 6 | **Bỏ qua hàng hệ thống `tenant_id IS NULL`** (đăng ký, sửa hồ sơ, đổi mật khẩu) — màn theo workspace | «Việc của chính mình» cho mọi vai trò (PQ_01 §3.1) — đợt 2 |
| 7 | `group_name = 'configure'`, `sort_order = 15` cho `audit.read` | `operate` (0945 xếp `billing.read` vào `operate` vì chỉ-đọc; nhưng ~90% nội dung nhật ký là sự kiện nhóm configure và PQ_01 §3.1 đặt «Quản trị xem toàn workspace» — người đi tìm «Xem nhật ký» tìm ở khu quản trị). Nối cuối để không đánh số lại như 0945 |

Hệ quả nhận của #1 + #6: vai trò không có `audit.read` **không thấy mục nav và
bị 403** — «mọi vai trò xem được phần việc của chính mình» lùi đợt 2.

## 3. Action `audit.read` (BE + FE)

**BE**
- `core/auth/actions.py`: `AUDIT_READ: Final = "audit.read"` — docstring
  `"""15 · Xem Nhật ký hoạt động của workspace"""`; thêm dòng vào `NHAN_HANH_DONG`.
- Migration `0956_audit_action.py` (`down_revision = "0955_hop_nhat_hai_head"`,
  head duy nhất — đã kiểm `alembic heads`), theo khuôn `0945_billing_action.py`:
  - `INSERT INTO control.actions (code, group_name, label_vi, label_en, sort_order)
    VALUES ('audit.read', 'configure', 'Xem Nhật ký hoạt động', 'View audit log', 15)
    ON CONFLICT (code) DO NOTHING`
  - `INSERT INTO control.role_actions` cho MỌI `control.roles` có `name = 'Quản trị'`
    (cấp theo TÊN, không theo id — id là `r_<md5>`). Danh sách vai trò đóng băng
    trong file: `("Quản trị",)`.
  - `downgrade`: xoá `role_actions` rồi `actions` của `audit.read`.
- `make contracts` → `contracts/actions.json` 15 mã. Test đếm 14→15:
  `tests/api/test_actions.py:10` · `tests/api/test_contracts.py:50` ·
  `tests/modules/enrollment/test_router.py:59` · `tests/modules/auth/test_vai_tro.py:267`
  (và comment ở `auth/test_login.py:70`, `workspace/test_tao.py:96`).
- `tests/modules/audit/test_action.py` — khuôn `billing/test_action.py`: có trong
  code + `NHAN_HANH_DONG` + DB, và tập vai trò được cấp `== {"Quản trị"}`.

**FE**
- Copy `contracts/actions.json` (byte-for-byte) → `lib/actions.ts` thêm
  `AUDIT_READ: 'audit.read'`.
- Test đếm 14→15: `tests/actions-parity.test.ts` (2 chỗ) ·
  `tests/nav-registry.test.ts:328,338`. Phiên giả `lib/session.tsx` + MSW
  `lib/msw/handlers.ts:44` thêm `audit.read` («đủ 15 nhóm»).
- `features/platform/nav.ts` `auditNav`: `requiredActions: [ACTIONS.AUDIT_READ]`,
  **bỏ** `badge: { tone: 'warn', count: null }` (badge warn là dấu «màn chưa
  có»); sửa chú thích cho khớp (#6).

## 4. Hợp đồng HTTP — `GET /api/v1/audit`

Module mới `modules/audit/` (`router.py` khai `ROUTER`, registry tự quét;
`contracts.py`; `repo.py`). Không có `service.py` — không có nghiệp vụ, chỉ đọc.

**Quyền & phạm vi**
- `p: Principal = require(ACTIONS.AUDIT_READ)`.
- `tenant_id` CHỈ từ `p.tenant_id`; SQL chạy trong `tenant_conn(pool, p.tenant_id)`
  và mang vị từ LITERAL `tenant_id = portal.current_tenant()` (cùng cách
  `ingest/jobs.py` đọc bảng này). Hàng `tenant_id IS NULL` không bao giờ lọt (#6).

**Query**

| Tham số | Kiểu | Mặc định | Ràng buộc / nghĩa |
|---|---|---|---|
| `limit` | int | 50 | `ge=1, le=200` (`_LIMIT_Q` singleton mức module, tránh B008) |
| `cursor` | str | — | Đục (base64url) của `"{luc.isoformat()}|{id}"` hàng cuối trang trước. Sai định dạng → **400 `CURSOR_KHONG_HOP_LE`** |
| `nhom` | str | — | Danh sách tiền tố cách nhau dấu phẩy, mỗi phần tử `^[a-z_]{1,32}$`, tối đa 10; SQL `split_part(hanh_dong, '.', 1) = ANY($n::text[])`. Vi phạm → 422 |
| `from` | date | — | Cận DƯỚI đóng, ngày theo `Asia/Ho_Chi_Minh`: `luc >= ($n::date)::timestamp AT TIME ZONE 'Asia/Ho_Chi_Minh'` |
| `to` | date | — | Cận TRÊN **MỞ** (`< to`), cùng múi giờ — cùng nghĩa `_khoang()` của billing. FE gửi `ngàyChọn + 1` cho ô «đến hết ngày». Có cả hai mà `from >= to` → **422 `KHOANG_KHONG_HOP_LE`** |
| `may` | bool | `false` | `false` ⇒ thêm `actor <> 'agent'`. `true` ⇒ không lọc. Hàng `actor = ''` (job hệ thống, vd `ingest.tenant_im_lang`) và `platform_admin` LUÔN hiện — chúng là việc cho người đọc |

Không có mặc định khoảng ngày: thiếu `from`/`to` là «mới nhất trước», phân trang
tới đâu tuỳ người xem.

**SQL (repo)** — thứ tự `ORDER BY a.luc DESC, a.id DESC`, keyset
`(a.luc, a.id) < ($luc, $id)` khi có cursor, `LIMIT $xin` với `xin = min(limit+1, 200)`
(khuôn `_xin_du_phong`/`_trang` của realestate, sao chép — Luật 3 không import
ruột module khác). `LEFT JOIN control.users u ON u.id = a.actor`.
Index `audit_log_tenant_luc_idx (tenant_id, luc DESC)` phục vụ đúng thứ tự này;
`id` chỉ phá hoà khi cùng `luc` (cùng giao dịch / cùng mili-giây).

**Response 200** — `TrangNhatKyOut`

```json
{
  "items": [
    {
      "id": 412,
      "luc": "2026-08-25T03:12:44.120931+00:00",
      "hanhDong": "realestate.project.update",
      "actorId": "u_haidt",
      "actorTen": "Hải Đỗ",
      "actorEmail": "hai@noblex.vn",
      "chiTiet": { "project_code": "NT2", "truong": ["name", "price"] }
    }
  ],
  "nextCursor": "MjAyNi0wOC0yNVQwMzoxMjo0NC4xMjA5MzErMDA6MDB8NDEy"
}
```

- `actorTen`/`actorEmail` là `null` khi `actor` không khớp `users` (đã bị xoá,
  hoặc là `agent`/`platform_admin`/`""`). `actor` có các dạng thật: `u_<id>` ·
  `agent` · `platform_admin` · `cron` · `ingest` / `ingest_token:<id>` ·
  `token:<id>` (importer cũ) · `''` — xem `docs/contracts/audit.md`; FE hiện tên
  người nếu có, dịch các dạng đặc biệt, dạng lạ hiện nguyên.
- `chiTiet` trả NGUYÊN `jsonb` — không lọc, không đổi tên khoá. Nhật ký là bằng
  chứng; endpoint đọc không được «làm đẹp» nó.
- `nextCursor: null` khi hết.
- Lỗi: 401 không phiên · 403 thiếu action (envelope chuẩn `api/loi.py`, thông
  điệp có nhãn từ `NHAN_HANH_DONG`) · 400/422 như bảng trên.

Tài liệu cho FE: `docs/contracts/audit.md` (bảng tham số + mẫu JSON ở trên).

## 5. Sổ mã hành động + cổng parity

**Vì sao cần sổ:** ~50 mã là chuỗi literal rải ở 50 điểm ghi, hai lối đặt tên
(`thanh_vien.go` vs `realestate.project.update`). Không có nguồn nào để FE dịch
ra tiếng Việt, và thêm mã mới thì không ai bị nhắc.

**BE**
- `core/nhat_ky_ma.py`: `MA_HANH_DONG: Final[frozenset[str]]` — liệt kê TOÀN BỘ
  mã, gom theo tiền tố có chú thích. Đây là nguồn sự thật; các điểm ghi KHÔNG
  đổi (vẫn literal) — sửa 50 điểm ghi để đổi lấy một cổng test là quá tay.
- Test mới `tests/unit/test_nhat_ky_ma.py` (cổng AST, khuôn
  `test_nhat_ky_day_du.py`), quét mọi `.py` dưới `src/portal`:
  1. Mọi `ast.Call` tới `nhat_ky.ghi` (đối số vị trí 2 hoặc keyword `hanh_dong`),
     `nhat_ky.ghi_he_thong` (vị trí 1), `_nhat_ky` (vị trí 2) mà đối số là
     `ast.Constant` chuỗi ⇒ chuỗi đó **∈ `MA_HANH_DONG`**. Đối số không phải
     literal (biến, vd `HANH_DONG` của ingest, `hanh_dong` truyền qua service) thì
     bỏ qua — cổng canh literal, không giả vờ canh được mọi thứ.
  2. Chiều ngược: mọi mã trong `MA_HANH_DONG` phải xuất hiện dưới dạng chuỗi
     literal `"<mã>"` ở đâu đó trong `src/portal` (grep văn bản) — sổ không được
     có mã chết.
- **`MA_DA_NGHI_HUU: Final[frozenset[str]]`** (thêm 2026-08-25 sau review) — mã
  KHÔNG còn điểm ghi nào trong `src`, nhưng CÒN HÀNG trong `control.audit_log`
  (bảng chỉ ghi thêm, không bao giờ xoá). Khi một điểm ghi bị bỏ, mã của nó
  CHUYỂN từ `MA_HANH_DONG` xuống đây, không xoá — FE vẫn phải dịch được nhãn
  cho hàng lịch sử. Hai tập RỜI NHAU (`test_hai_tap_roi_nhau`); mã trong
  `MA_DA_NGHI_HUU` không được có điểm ghi thật nào ngoài chính sổ
  (`test_ma_nghi_huu_khong_con_diem_ghi`). `MA_TAT_CA = MA_HANH_DONG |
  MA_DA_NGHI_HUU` là nguồn cho artefact — FE dịch cả lịch sử, không chỉ mã
  đang ghi hôm nay.
- `scripts/gen_contracts.py` thêm `noi_dung_audit_actions()` →
  `contracts/audit-actions.json` `{"actions": [... sorted ...]}` (nguồn
  `MA_TAT_CA`); `tests/api/test_contracts.py` canh thêm file này (tồn tại ·
  khớp nguồn · đúng byte script sinh · đếm > 0 trước khi so). `contracts/README.md`
  thêm một dòng vào bảng artefact.

**FE**
- Copy `contracts/audit-actions.json`.
- `features/platform/so-hanh-dong.ts`:
  - `NHAN_HANH_DONG: Record<string, string>` mã → nhãn tiếng Việt (vd
    `thanh_vien.go` → «Gỡ thành viên», `agent_config.publish` → «Xuất bản cấu
    hình agent», `realestate.project.update` → «Sửa dự án»).
  - `NHOM_LOC: readonly {ma, nhan, tienTo: readonly string[]}[]` — nhóm hiển thị
    trên ô lọc, MỘT nhóm có thể gộp NHIỀU tiền tố: «Thành viên & vai trò»
    (`thanh_vien`, `user`, `role`, `owner`), «Agent & khoá» (`agent`), «Cấu hình
    agent» (`agent_config`), «Kiến thức» (`kb`), «Dữ liệu BĐS» (`realestate`),
    «Lĩnh vực» (`linh_vuc`), «Workspace» (`workspace`), «Cổng nạp» (`ingest`),
    «Bảng giá» (`billing`).
  - `nhanHanhDong(ma)`: nhãn, fallback chính mã thô (phòng hờ — cổng canh mã
    đang ghi + mã đã nghỉ hưu (`MA_DA_NGHI_HUU`); DB khác có thể còn mã ngoài
    hai tập ⇒ giữ fallback).
- `tests/audit-actions-parity.test.ts`: (a) artefact có > 0 mã; (b) MỌI mã trong
  artefact có nhãn trong `NHAN_HANH_DONG`; (c) `NHAN_HANH_DONG` không có mã lạ
  ngoài artefact; (d) tiền tố của MỌI mã thuộc đúng một nhóm trong `NHOM_LOC`
  (mã mới với tiền tố mới không được rơi ra ngoài mọi bộ lọc).

## 6. Màn FE — `features/platform/` (chủ sở hữu `audit`)

**Tệp mới**
- `features/platform/nhatKy.ts` — kiểu `DongNhatKy`/`TrangNhatKy`/`LocNhatKy`,
  `taiNhatKy(loc, cursor)` (dùng `goi()`/`LoiApi` sẵn có TRONG cùng feature
  `features/platform/api.ts` — không phải sao chép, cùng ranh giới), hook
  `useNhatKy(loc)` = `useInfiniteQuery` khoá `['audit', loc]`, `getNextPageParam
  = (trang) => trang.nextCursor ?? undefined`.
- `features/platform/so-hanh-dong.ts` (mục 5).
- `features/platform/mswNhatKy.ts` — `nhatKyHandlers`, dữ liệu giả tất định ~40
  hàng (đủ 2 trang với `limit=20` trong test, có hàng `agent`, hàng `""`, hàng
  user đã xoá, nhiều nhóm, trải ~10 ngày), **fake CÓ xử lý** `cursor`/`nhom`/
  `from`/`to`/`may` để test hành vi thật; đăng ký vào `lib/msw/handlers.ts` như
  `billingHandlers`.
- `features/platform/components/NhatKyScreen.tsx` — màn; giữ state lọc bằng
  `useState` (không search param: bộ lọc ở đây không phải link gửi đi được như
  `?tab=`).
- `features/platform/components/BoLocNhatKy.tsx` — `<select>` nhóm («Tất cả» +
  `NHOM_LOC`), hai `<input type=date>` từ/đến (đến = «đến hết ngày», màn cộng 1
  ngày khi gọi API), công tắc «Hiện hoạt động của agent» (checkbox có nhãn).
- `features/platform/components/BangNhatKy.tsx` — `TheBang` + bảng 4 cột
  **Thời gian · Người · Hành động · Chi tiết** + hàng cuối nút «Tải thêm» khi
  `hasNextPage`; trạng thái rỗng «Chưa có hoạt động nào trong khoảng đã chọn»;
  lỗi hiện `LoiApi.message` nguyên văn (không bịa câu chung).
  - Thời gian: `dinhDangLuc(iso)` sẵn có ở `features/platform/api.ts:270`.
  - Người: `actorTen ?? tênĐặcBiệt(actorId) ?? actorId`; `title` = email nếu có.
  - Hành động: `nhanHanhDong(hanhDong)`.
  - Chi tiết: `tomTatChiTiet(chiTiet)` — `khoá: giá trị` nối bằng « · », mảng
    nối bằng «, », object lồng → JSON; cắt 120 ký tự, `title` mang bản đầy đủ.
    Đợt 1 KHÔNG có formatter riêng theo mã.
- `routes/_app/audit.tsx`: bỏ `ScreenStub`, render `NhatKyScreen`.
- `lib/screens.ts:161`: `audit` → `mvp: 'full'`.

**Test cũ đổi theo**
- `tests/command-palette.test.tsx:162` KHÔNG đổi: bài đó dựng router riêng với
  `ScreenStub` cho mọi màn, không đi qua `routes/_app/audit.tsx`.
- `tests/shell.test.tsx:279-292` («thiếu WORKSPACE_ADMIN…») đang trông thấy «Nhật
  ký» với bộ quyền `[overview.read, convos.read]` → cấp thêm `audit.read` cho bài đó.
- `tests/boot.test.tsx` thêm dấu hiệu `audit` vào bảng màn đã có nội dung
  (dòng 113 nói stub «không có dòng nào» — cập nhật con số màn stub).
- `tests/nav-registry.test.ts`: gating của `audit` đổi từ `overview.read` sang
  `audit.read` — sửa bài nào so `requiredActions`.

## 7. Kiểm thử

**BE — `tests/modules/audit/`** (conftest theo nếp `billing/conftest.py`: KHÔNG
mock `tenant_conn`; seed 2 tenant, 2 user — một có membership «Quản trị» ở tenant
A, một vai trò không có `audit.read`; chèn thẳng ~12 hàng `audit_log` bằng
`pool`: nhiều nhóm, một hàng `agent`, một hàng `""`, một hàng `actor` không tồn
tại trong `users`, ba hàng CÙNG `luc`, một hàng của tenant B, một hàng
`tenant_id NULL`).
- 401 không phiên · 403 vai trò thiếu `audit.read` (thông điệp có nhãn).
- Cách ly: hàng tenant B và hàng `tenant_id NULL` không bao giờ xuất hiện.
- Mặc định không có `agent`; `may=true` có.
- `nhom=realestate` · `nhom=thanh_vien,user` · `nhom` sai định dạng → 422.
- `from`/`to` theo múi giờ VN (hàng 23:30 giờ VN ngày D phải thuộc `to = D+1`,
  không rơi sang ngày UTC hôm sau) · `from >= to` → 422.
- Phân trang: `limit=5` trên 12 hàng có 3 hàng cùng `luc` → gộp mọi trang không
  trùng, không sót, `nextCursor` cuối là `null`; cursor rác → 400.
- Join: `actorTen/actorEmail` đúng với user thật, `null` với user không tồn tại
  và với `agent`.
- `test_action.py` (mục 3) · `tests/unit/test_nhat_ky_ma.py` (mục 5) ·
  `tests/api/test_contracts.py` mở rộng.

**FE — `tests/nhat-ky.test.tsx`** (render `NhatKyScreen` trực tiếp trong
`QueryClientProvider` + `LangProvider`, MSW `server` của `vitest.setup`, khuôn
`khoa-dau-noi.test.tsx`):
- Hàng hiện nhãn tiếng Việt (không phải mã), tên người, «Agent»/«Hệ thống» cho
  hàng đặc biệt, `actorId` thô cho user đã xoá.
- Mặc định request KHÔNG có `may`; bật công tắc ⇒ request mới có `may=true` và
  hàng agent xuất hiện (đếm request qua `server.events` hoặc handler ghi lại).
- Đổi nhóm ⇒ request mang `nhom=` đúng danh sách tiền tố của nhóm.
- Chọn «đến» ngày D ⇒ request `to = D+1`.
- «Tải thêm» nối trang 2, biến mất khi `nextCursor: null`.
- Rỗng · lỗi 403 hiện message.
- `tests/audit-actions-parity.test.ts` (mục 5).

**Cổng chung:** BE `uv run pytest` xanh · `ruff` sạch; FE `tsc -b` + eslint 0
warning + prettier cho tệp mới + toàn suite vitest xanh.

## 8. Ngoài đợt 1

Xuất CSV (PQ_01 «xuất được») · job retention + chốt thời hạn giữ (PQ_01 dòng
297) · hàng `tenant_id NULL` / «việc của chính mình» cho mọi vai trò · tìm theo
người · formatter chi tiết theo mã · bày `ingest.tenant_im_lang` thành cảnh báo
riêng · BR-Q07 (module hội thoại chưa có ở BE) · gỡ nhiễu
`agent.dat_trang_thai_khoa` ghi dù trạng thái không đổi (finding QA mr-43).

## 9. Bẫy đã biết

- `luc` là `now()` = thời điểm BẮT ĐẦU giao dịch: hai giao dịch chồng nhau có thể
  cho `id` lớn hơn mà `luc` nhỏ hơn. Sắp `(luc, id)` và keyset trên cả cặp thì
  vẫn xác định — đừng «tối ưu» về keyset theo `id` một mình.
- `actor` KHÔNG có FK và không NOT NULL về nghĩa — LEFT JOIN, không INNER; và
  không được lọc bỏ hàng có `actor` lạ.
- `control.*` không có RLS: vị từ tenant là ở CÂU SQL, quên là lộ toàn nền tảng.
  `tests/isolation/test_isolation_catalog.py` đã liệt `audit_log` là bảng
  control-plane — cổng đó không canh hộ, test cách ly ở mục 7 mới canh.
- Thêm action = đổi contract: quên `make contracts` ⇒ `test_contracts.py` đỏ;
  quên copy sang FE ⇒ `actions-parity.test.ts` đỏ. Cả hai đỏ là ĐÚNG.
- Đổi `requiredActions` của `auditNav` mà quên thêm `audit.read` vào phiên giả
  ⇒ mục nav biến mất ở dev MSW và bài palette «nhat ky» đỏ.
