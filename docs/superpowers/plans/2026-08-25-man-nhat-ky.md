# Màn «Nhật ký» (`/audit`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thay `ScreenStub` ở `/audit` bằng màn thật đọc `GET /api/v1/audit`: bảng Thời gian · Người · Hành động · Chi tiết, lọc nhóm/khoảng ngày, công tắc «Hiện hoạt động của agent», «Tải thêm» keyset; kèm action mới `audit.read` và sổ nhãn tiếng Việt có cổng parity với artefact của BE.

**Architecture:** Toàn bộ nằm trong `features/platform/` (chủ sở hữu `audit` theo `features/platform/nav.ts`). Ba tệp thuần không-component (`nhatKy.ts` client + hook · `so-hanh-dong.ts` nhãn + nhóm lọc · `hienNhatKy.ts` hiển thị người/chi tiết) + `mswNhatKy.ts` fake CÓ xử lý tham số + ba component (`BoLocNhatKy` · `BangNhatKy` · `NhatKyScreen`). Bộ lọc là `useState` cục bộ (không search param — không phải link gửi đi được). Dùng `goi()`/`LoiApi`/`dinhDangLuc` sẵn có của `features/platform/api.ts` (cùng feature, không vi phạm Luật 3).

**Tech Stack:** React 19 + TanStack Router (file route) + TanStack Query v5 (`useInfiniteQuery`, cần `initialPageParam`) + MSW 2 + Vitest 3 + Testing Library + Tailwind 4 (token màu của `theme.css`, primitive ở `components/ui/Bang.tsx`).

**Spec:** `odyssey-portal-backend/docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md` (§3 action, §4 hợp đồng HTTP, §5 sổ mã + parity, §6 màn FE, §7 test FE). Hợp đồng bàn giao: `odyssey-portal-backend/docs/contracts/audit.md`. Executor đọc CẢ HAI.

## Global Constraints

- Nhánh `feat/man-nhat-ky`, base `develop` @ `07b8a48` (đã tạo). KHÔNG rebase/merge giữa chừng.
- **Phụ thuộc BE:** hai artefact `contracts/actions.json` (15 mã) và `contracts/audit-actions.json` phải copy byte-for-byte từ repo backend SAU KHI plan BE xong Task 1–2 (nhánh `feat/nhat-ky-doc`, hoặc `develop` nếu đã merge). Không sửa tay hai file này.
- Commit message `<type>: <subject>`, KHÔNG footer attribution. Stage theo ĐƯỜNG DẪN tường minh — cấm `git add -A`/`git add .`/`commit -a`.
- Hợp đồng HTTP đóng băng theo `docs/contracts/audit.md` của BE: `GET /api/v1/audit?limit&cursor&nhom&from&to&may`; `to` là cận trên MỞ ⇒ ô «Đến hết ngày D» gửi `to = D + 1`; response `{items:[{id,luc,hanhDong,actorId,actorTen,actorEmail,chiTiet}], nextCursor}`.
- `actorId` — các dạng THẬT (đã kiểm BE code + DB dev 2026-08-25, `docs/contracts/audit.md`): `u_<id>` · `agent` · `platform_admin` · `cron` · `ingest` / `ingest_token:<id>` · `token:<id>` (importer cũ) · `''`. Hiển thị: tên người nếu `actorTen` có; `agent` → «Agent»; `platform_admin` → «NobleX»; `cron` và `''` → «Hệ thống»; `ingest` / `ingest_token:*` / `token:*` → «Cổng nạp»; dạng khác (kể cả user đã xoá) → hiện `actorId` thô. KHÔNG lọc bỏ hàng nào ở FE — danh sách này có thể mọc.
- Luật 3 (`tests/module-boundaries.test.ts`): `features/platform/*` không import ruột feature khác; `lib/msw/handlers.ts` là điểm gom fake duy nhất.
- `eslint react-refresh/only-export-components` + `--max-warnings 0`: tệp `.tsx` export component thì KHÔNG export hằng/hàm — helper để ở tệp `.ts` riêng.
- Tiếng Việt thuần trên màn (như `/usage`); nhãn nav đã có vi/en.
- Chạy `make lint` (eslint 0 warning + prettier check + `tsc -b`) và `npx vitest run <tệp>` trước MỖI commit; `npx prettier --write` cho tệp MỚI của đợt này (28 tệp lệch prettier có sẵn là nợ cũ — không đụng).
- Không chạm route/màn khác ngoài các file liệt kê trong từng task.

---

### Task 1: Action `audit.read` — copy artefact, `lib/actions.ts`, nav gating, test đếm 14→15

**Files:**
- Modify (copy từ BE): `contracts/actions.json`, `contracts/audit-actions.json` (tệp mới)
- Modify: `src/lib/actions.ts` (thêm `AUDIT_READ`), `src/features/platform/nav.ts:35-45` (`auditNav`), `src/lib/session.tsx:7`, `src/lib/msw/handlers.ts:44` (chú thích «14 nhóm»)
- Modify: `tests/actions-parity.test.ts:2,28-35` · `tests/nav-registry.test.ts:328-340` · `tests/shell.test.tsx:279-292`

**Interfaces:**
- Produces: `ACTIONS.AUDIT_READ === 'audit.read'` (nav + test); `contracts/audit-actions.json` cho Task 2.

- [ ] **Step 1: Copy artefact từ BE**

```bash
cp ../odyssey-portal-backend/contracts/actions.json contracts/actions.json
cp ../odyssey-portal-backend/contracts/audit-actions.json contracts/audit-actions.json
git diff --stat contracts/
```

Expected: `actions.json` +1 dòng (`"audit.read",` đứng đầu — sắp alphabet); `audit-actions.json` là tệp mới, `{"actions": [...]}` ≥ 40 mã.

- [ ] **Step 2: Chạy parity để thấy đỏ**

Run: `npx vitest run tests/actions-parity.test.ts`
Expected: FAIL — «artefact có đúng 14 nhóm» (artefact nay 15) và «hai bên là cùng một tập».

- [ ] **Step 3: Thêm action vào `src/lib/actions.ts`**

Sau dòng `BILLING_READ: 'billing.read',` thêm:

```ts
  /** 15 · Xem Nhật ký hoạt động (`/audit`). BE `0956_audit_action`, cấp mặc định
   *  cho Quản trị. Ngoài 13 nhóm gốc PQ_01 §3.1 như `BILLING_READ`. */
  AUDIT_READ: 'audit.read',
```

(Nếu `lib/actions.ts` có docstring đầu tệp nhắc «14 nhóm», đổi thành «15 nhóm (13 gốc + billing.read + audit.read)».)

- [ ] **Step 4: Sửa ba test đếm và bộ quyền của bài shell**

`tests/actions-parity.test.ts`: dòng 2 `14 nhóm` → `15 nhóm`; hai bài `'artefact có đúng 14 nhóm'` / `'actions.ts có đúng 14 nhóm'` đổi tên `15` và `toHaveLength(15)`.

`tests/nav-registry.test.ts:328`: tên bài → `'mọi action dùng trong nav đều nằm trong 15 nhóm (PQ_01 §3.1 + billing.read + audit.read)'`; dòng 336-340: chú thích thêm `+ audit.read (spec BE 2026-08-25 nhat-ky-hoat-dong)`, tên bài `'có đúng 15 nhóm hành động'`, `toHaveLength(15)`.

`tests/shell.test.tsx:279-292` — bài `thiếu WORKSPACE_ADMIN thì mất Thành viên · API Keys · Gói cước`:

```ts
    withActions([ACTIONS.OVERVIEW_READ, ACTIONS.CONVOS_READ, ACTIONS.AUDIT_READ])
```

và sửa chú thích dòng 286-287 thành: `// Ba màn đó thuộc mảng Agent/Quản trị — kiểm qua rail: mảng Agent mất hết mục nên mất luôn icon, còn Quản trị chỉ còn Nhật ký (nhờ AUDIT_READ — từ 2026-08-25 mục này khoá theo audit.read, không còn overview.read).`

- [ ] **Step 5: Đổi gating của `auditNav` trong `src/features/platform/nav.ts`**

Thay toàn bộ `auditNav` bằng:

```ts
export const auditNav: NavLeaf = {
  kind: 'leaf',
  key: 'audit',
  path: '/audit',
  // «Nhật ký», bỏ vế «& Dữ liệu» (2026-08-09): vế đó hứa một phần màn chưa có.
  // Màn thật dựng 2026-08-25 (`components/NhatKyScreen.tsx`); ngày có phần dữ
  // liệu thì nó là một tab, y như `/users` đã làm với Vai trò.
  label: { vi: 'Nhật ký', en: 'Audit log' },
  icon: 'audit',
  // `audit.read` (action 15, BE `0956_audit_action`, cấp mặc định cho Quản trị).
  // Trước 2026-08-25 là `OVERVIEW_READ` vì PQ_01 §3.1 nói «mọi vai trò xem việc
  // của chính mình» — phần đó là ĐỢT 2 (spec BE §2 #6); đợt 1 endpoint chỉ trả
  // toàn workspace cho ai có action này, nên nav khoá theo đúng action đó.
  requiredActions: [ACTIONS.AUDIT_READ],
}
```

(bỏ `badge: { tone: 'warn', count: null }` — badge warn là dấu «màn chưa có».)

Chú thích `src/lib/session.tsx:7` «đủ 14 nhóm» → «đủ 15 nhóm»; `src/lib/msw/handlers.ts:44` `// Đủ 14 nhóm` → `// Đủ 15 nhóm`. `FAKE_SESSION.actions = ALL_ACTIONS` nên phiên giả tự có `audit.read` — không sửa gì thêm.

- [ ] **Step 6: Chạy test**

Run: `npx vitest run tests/actions-parity.test.ts tests/nav-registry.test.ts tests/shell.test.tsx tests/command-palette.test.tsx`
Expected: PASS toàn bộ.

- [ ] **Step 7: Lint + commit**

Run: `make lint`

```bash
git add contracts/actions.json contracts/audit-actions.json src/lib/actions.ts \
  src/features/platform/nav.ts src/lib/session.tsx src/lib/msw/handlers.ts \
  tests/actions-parity.test.ts tests/nav-registry.test.ts tests/shell.test.tsx
git commit -m "feat: action audit.read — mục nav Nhật ký khoá theo quyền xem nhật ký"
```

---

### Task 2: Sổ nhãn `so-hanh-dong.ts` + cổng parity với `contracts/audit-actions.json`

**Files:**
- Create: `src/features/platform/so-hanh-dong.ts`
- Create: `tests/audit-actions-parity.test.ts`

**Interfaces:**
- Produces: `NHAN_HANH_DONG: Readonly<Record<string, string>>`, `NHOM_LOC: readonly NhomLoc[]` (`{ma, nhan, tienTo}`), `nhanHanhDong(ma: string): string`, `tienToCua(ma: string): string`. Task 3 dùng `NHOM_LOC` để dịch nhóm → `?nhom=`; Task 4 dùng `nhanHanhDong`.

- [ ] **Step 1: Viết test đỏ `tests/audit-actions-parity.test.ts`**

```ts
/**
 * CỔNG PARITY sổ mã hành động nhật ký — BE ↔ FE.
 *
 * Nguồn: `core/nhat_ky_ma.py` của repo backend → artefact `contracts/audit-actions.json`
 * (copy byte-for-byte, cùng cơ chế `actions.json`). FE dịch mã ra tiếng Việt ở
 * `features/platform/so-hanh-dong.ts`. Thêm điểm ghi mới ở BE mà quên nhãn ở đây
 * ⇒ bài (b) đỏ; giữ nhãn cho mã đã bỏ ⇒ bài (c) đỏ; mã có tiền tố mới rơi ra ngoài
 * mọi bộ lọc ⇒ bài (d) đỏ.
 */
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { NHAN_HANH_DONG, NHOM_LOC, nhanHanhDong, tienToCua } from '../src/features/platform/so-hanh-dong'

const DUONG_JSON = resolve(import.meta.dirname, '../contracts/audit-actions.json')

function maTuArtefact(): string[] {
  return JSON.parse(readFileSync(DUONG_JSON, 'utf-8')).actions
}

describe('cổng parity sổ mã hành động nhật ký', () => {
  it('(a) artefact không rỗng', () => {
    // Đếm TRƯỚC khi so: tập rỗng ⊆ mọi tập, không đếm thì artefact rỗng làm cổng xanh mãi.
    expect(maTuArtefact().length).toBeGreaterThanOrEqual(40)
  })

  it('(b) mọi mã trong artefact có nhãn tiếng Việt', () => {
    const thieu = maTuArtefact().filter((ma) => !(ma in NHAN_HANH_DONG))
    expect(thieu, 'thêm nhãn vào so-hanh-dong.ts').toEqual([])
  })

  it('(c) sổ FE không có mã lạ ngoài artefact', () => {
    const co = new Set(maTuArtefact())
    const la = Object.keys(NHAN_HANH_DONG).filter((ma) => !co.has(ma))
    expect(la, 'mã không còn ở BE — bỏ nhãn').toEqual([])
  })

  it('(d) tiền tố của mọi mã thuộc ĐÚNG MỘT nhóm lọc', () => {
    for (const ma of maTuArtefact()) {
      const nhom = NHOM_LOC.filter((n) => n.tienTo.includes(tienToCua(ma)))
      expect(nhom.length, `mã ${ma} (tiền tố ${tienToCua(ma)})`).toBe(1)
    }
  })

  it('(e) nhãn không trùng mã, không rỗng', () => {
    for (const [ma, nhan] of Object.entries(NHAN_HANH_DONG)) {
      expect(nhan.trim().length, ma).toBeGreaterThan(0)
      expect(nhan, ma).not.toBe(ma)
    }
  })

  it('nhanHanhDong rơi về mã thô khi chưa có nhãn', () => {
    expect(nhanHanhDong('kb.upload')).toBe('Tải lên tài liệu kiến thức')
    expect(nhanHanhDong('x.y')).toBe('x.y')
  })
})
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npx vitest run tests/audit-actions-parity.test.ts`
Expected: FAIL — không resolve được `so-hanh-dong`.

- [ ] **Step 3: Viết `src/features/platform/so-hanh-dong.ts`**

```ts
/**
 * Sổ mã hành động của nhật ký → nhãn tiếng Việt + nhóm lọc.
 *
 * Mã là chuỗi kỹ thuật BE ghi vào `control.audit_log.hanh_dong` (hai lối đặt
 * tên lẫn nhau: `thanh_vien.go` · `realestate.project.update`). Nguồn danh sách:
 * `contracts/audit-actions.json` (copy từ BE, sinh từ `core/nhat_ky_ma.py`).
 * Cổng `tests/audit-actions-parity.test.ts` giữ ba điều: mọi mã có nhãn · sổ
 * không có mã lạ · tiền tố của mọi mã thuộc đúng một nhóm dưới đây.
 *
 * NHÓM LỌC gộp NHIỀU tiền tố (thành viên = `thanh_vien` + `user` + `role` +
 * `owner`): người dùng hỏi «ai đụng vào thành viên», không hỏi theo tên module.
 * API nhận danh sách tiền tố cách nhau dấu phẩy (`?nhom=a,b`), nên gộp ở đây
 * không tốn gì phía BE.
 */

export const NHAN_HANH_DONG: Readonly<Record<string, string>> = {
  'agent.cap_phat': 'Cấp phát agent',
  'agent.dat_trang_thai_khoa': 'Bật/tắt khoá agent',
  'agent.feedback': 'Gửi phản hồi về agent',
  'agent.phat_khoa': 'Tạo khoá agent',
  'agent.runtime_credentials': 'Agent lấy credential',
  'agent.thu_hoi_khoa': 'Thu hồi khoá agent',
  'agent.xoay_bi_mat': 'Xoay bí mật agent',
  'agent_config.publish': 'Xuất bản cấu hình agent',
  'agent_config.rollback': 'Quay lui cấu hình agent',
  'billing.price_version_kich_hoat': 'Kích hoạt bảng giá',
  'ingest.nghi_mat_tich': 'Bản ghi nghi mất tích (đối soát cổng nạp)',
  'ingest.tenant_im_lang': 'Cổng nạp im lặng (cảnh báo)',
  'ingest.token_tao': 'Tạo token nạp dữ liệu',
  'ingest.token_xoa': 'Xoá token nạp dữ liệu',
  'kb.delete': 'Xoá tài liệu kiến thức',
  'kb.upload': 'Tải lên tài liệu kiến thức',
  'linh_vuc.bat': 'Bật lĩnh vực',
  'linh_vuc.tat': 'Tắt lĩnh vực',
  'owner.bootstrap': 'Khởi tạo chủ workspace',
  'realestate.document.approve': 'Duyệt tài liệu dự án',
  'realestate.document.create': 'Thêm tài liệu dự án',
  'realestate.document.delete': 'Xoá tài liệu dự án',
  'realestate.document.update': 'Sửa tài liệu dự án',
  'realestate.knowledge.sync': 'Đồng bộ kiến thức dự án',
  'realestate.media.create': 'Thêm media',
  'realestate.media.delete': 'Xoá media',
  'realestate.media.draft_caption': 'Soạn caption media',
  'realestate.media.update': 'Sửa media',
  'realestate.project.create': 'Thêm dự án',
  'realestate.project.delete': 'Xoá dự án',
  'realestate.project.update': 'Sửa dự án',
  'realestate.unit.create': 'Thêm căn',
  'realestate.unit.delete': 'Xoá căn',
  'realestate.unit.update': 'Sửa căn',
  'realestate.upload': 'Nhập tệp dữ liệu BĐS',
  'realestate.zone.create': 'Thêm phân khu',
  'realestate.zone.delete': 'Xoá phân khu',
  'realestate.zone.update': 'Sửa phân khu',
  'role.sua': 'Sửa vai trò',
  'role.tao': 'Tạo vai trò',
  'role.xoa': 'Xoá vai trò',
  'thanh_vien.doi_vai_tro': 'Đổi vai trò thành viên',
  'thanh_vien.go': 'Gỡ thành viên',
  'thanh_vien.gui_lai_moi': 'Gửi lại lời mời',
  'thanh_vien.moi': 'Mời thành viên',
  'thanh_vien.moi_lai': 'Mời lại thành viên',
  'thanh_vien.thu_hoi_moi': 'Thu hồi lời mời',
  'user.dang_ky': 'Đăng ký tài khoản',
  'user.dang_ky_google': 'Đăng ký bằng Google',
  'user.dang_nhap_google': 'Đăng nhập bằng Google',
  'user.doi_mat_khau': 'Đổi mật khẩu',
  'user.lien_ket_google': 'Liên kết Google',
  'user.moi_lai': 'Mời lại người dùng',
  'user.nhan_moi': 'Nhận lời mời',
  'user.nhan_moi_ws': 'Nhận lời mời vào workspace',
  'user.sua': 'Sửa người dùng',
  'user.sua_ho_so': 'Sửa hồ sơ',
  'user.tao': 'Tạo người dùng',
  'user.tao_tu_loi_moi': 'Tạo tài khoản từ lời mời',
  'user.xoa_loi_moi': 'Xoá lời mời',
  'workspace.doi_ten': 'Đổi tên workspace',
  'workspace.tao': 'Tạo workspace',
  'workspace.xoa': 'Xoá workspace',
  // ── Mã ĐÃ NGHỈ HƯU (BE `MA_DA_NGHI_HUU`): không còn điểm ghi nhưng còn hàng trong
  // lịch sử audit_log — vẫn phải dịch. Hậu tố «(cũ)» để người đọc biết đây là
  // luồng đã bỏ, không đi tìm màn tương ứng.
  'agent.bat_khoa': 'Bật khoá agent (cũ)',
  'agent.tat_khoa': 'Tắt khoá agent (cũ)',
  'realestate.import.mapping.create': 'Tạo ánh xạ nhập tệp (cũ)',
  'realestate.import.preview': 'Xem trước nhập tệp (cũ)',
  'realestate.import.probe': 'Dò tệp nhập (cũ)',
  'realestate.import.push': 'Đẩy dữ liệu nhập tệp (cũ)',
  'realestate.import.run': 'Chạy nhập tệp (cũ)',
  'workspace.token.create': 'Tạo token nạp (cũ)',
  'workspace.token.revoke': 'Thu hồi token nạp (cũ)',
}

export interface NhomLoc {
  /** Giá trị `<option>` — chỉ sống trong FE, KHÔNG gửi lên API. */
  readonly ma: string
  readonly nhan: string
  /** Tiền tố `hanhDong` (phần trước dấu chấm đầu) gộp vào nhóm này — gửi `?nhom=a,b`. */
  readonly tienTo: readonly string[]
}

export const NHOM_LOC: readonly NhomLoc[] = [
  { ma: 'thanh-vien', nhan: 'Thành viên & vai trò', tienTo: ['thanh_vien', 'user', 'role', 'owner'] },
  { ma: 'agent', nhan: 'Agent & khoá', tienTo: ['agent'] },
  { ma: 'cau-hinh', nhan: 'Cấu hình agent', tienTo: ['agent_config'] },
  { ma: 'kien-thuc', nhan: 'Kiến thức', tienTo: ['kb'] },
  { ma: 'bds', nhan: 'Dữ liệu BĐS', tienTo: ['realestate'] },
  { ma: 'linh-vuc', nhan: 'Lĩnh vực', tienTo: ['linh_vuc'] },
  { ma: 'workspace', nhan: 'Workspace', tienTo: ['workspace'] },
  { ma: 'cong-nap', nhan: 'Cổng nạp', tienTo: ['ingest'] },
  { ma: 'bang-gia', nhan: 'Bảng giá', tienTo: ['billing'] },
]

/** Nhãn tiếng Việt; mã chưa có nhãn hiện NGUYÊN mã — cổng parity làm ca này không xảy ra với mã đã biết. */
export function nhanHanhDong(ma: string): string {
  return NHAN_HANH_DONG[ma] ?? ma
}

export function tienToCua(ma: string): string {
  return ma.split('.')[0] ?? ma
}
```

- [ ] **Step 4: Chạy test; bù nhãn theo báo cáo**

Run: `npx vitest run tests/audit-actions-parity.test.ts`
Expected: PASS 7/7 — HOẶC bài (b) liệt kê mã của artefact chưa có nhãn / bài (c) liệt kê nhãn thừa / bài (d) tiền tố mới. Danh sách trên đã khớp 72 mã của `contracts/audit-actions.json` (63 đang ghi + 9 nghỉ hưu, BE sau review toàn nhánh 2026-08-25); nếu BE đổi sau đó, cổng sẽ báo. Mã ngoài artefact (DB khác có thể còn) hiện mã thô — đó là lý do `nhanHanhDong` giữ fallback. **Thêm nhãn cho đúng mã bài (b) báo, bỏ nhãn bài (c) báo, thêm tiền tố mới vào nhóm hợp nghĩa (hoặc nhóm mới) cho bài (d)** — chạy lại tới 7/7. KHÔNG nới sàn 40.

- [ ] **Step 5: Lint + commit**

Run: `npx prettier --write src/features/platform/so-hanh-dong.ts tests/audit-actions-parity.test.ts && make lint`

```bash
git add src/features/platform/so-hanh-dong.ts tests/audit-actions-parity.test.ts
git commit -m "feat(audit): sổ nhãn tiếng Việt cho mã hành động nhật ký + cổng parity với BE"
```

---

### Task 3: Client `nhatKy.ts` + helper hiển thị `hienNhatKy.ts` + fake MSW `mswNhatKy.ts`

**Files:**
- Create: `src/features/platform/nhatKy.ts`, `src/features/platform/hienNhatKy.ts`, `src/features/platform/mswNhatKy.ts`
- Modify: `src/lib/msw/handlers.ts:18` (import) và `:789` (spread sau `...billingHandlers`)
- Create: `tests/nhat-ky-thuan.test.ts`

**Interfaces:**
- Consumes: `NHOM_LOC` (Task 2); `goi`, `dinhDangLuc` từ `./api`.
- Produces:
  - `interface DongNhatKy {id; luc; hanhDong; actorId; actorTen; actorEmail; chiTiet}`, `interface TrangNhatKy {items; nextCursor}`, `interface LocNhatKy {nhom: string|null; tu: string|null; denHet: string|null; may: boolean}`, `LOC_MAC_DINH`, `SO_MOI_TRANG = 50`, `KHOA_NHAT_KY = ['audit']`, `duongNhatKy(loc, cursor?) => string`, `congMotNgay(iso) => string`, `taiNhatKy(loc, cursor?) => Promise<TrangNhatKy>`, `useNhatKy(loc)` (infinite query).
  - `tenNguoi(d: Pick<DongNhatKy,'actorId'|'actorTen'>) => string`, `tomTatChiTiet(ct) => {ngan; dayDu}`.
  - `NHAT_KY_GIA: readonly DongNhatKy[]`, `locNhatKyGia(hang, params: URLSearchParams) => TrangNhatKy`, `nhatKyHandlers`.

- [ ] **Step 1: Viết test đỏ `tests/nhat-ky-thuan.test.ts`**

```ts
/**
 * Phần THUẦN của màn Nhật ký — không DOM: dựng URL request, cộng ngày, hiển thị
 * người/chi tiết, và bộ lọc của fake MSW (fake CÓ xử lý tham số để test màn kiểm
 * được hành vi thật, cùng lý do `features/realestate/msw.ts`).
 */
import { describe, expect, it } from 'vitest'
import { LOC_MAC_DINH, SO_MOI_TRANG, congMotNgay, duongNhatKy } from '../src/features/platform/nhatKy'
import { tenNguoi, tomTatChiTiet } from '../src/features/platform/hienNhatKy'
import { NHAT_KY_GIA, locNhatKyGia } from '../src/features/platform/mswNhatKy'

function thamSo(duong: string): URLSearchParams {
  return new URL(duong, 'http://x').searchParams
}

describe('duongNhatKy', () => {
  it('mặc định: chỉ limit, KHÔNG có may/nhom/from/to', () => {
    const p = thamSo(duongNhatKy(LOC_MAC_DINH))
    expect(p.get('limit')).toBe(String(SO_MOI_TRANG))
    expect([...p.keys()]).toEqual(['limit'])
  })
  it('nhóm → danh sách tiền tố cách nhau dấu phẩy', () => {
    const p = thamSo(duongNhatKy({ ...LOC_MAC_DINH, nhom: 'thanh-vien' }))
    expect(p.get('nhom')).toBe('thanh_vien,user,role,owner')
  })
  it('«đến hết ngày D» gửi to = D + 1 (cận trên MỞ của API)', () => {
    const p = thamSo(duongNhatKy({ ...LOC_MAC_DINH, tu: '2026-08-01', denHet: '2026-08-31' }))
    expect(p.get('from')).toBe('2026-08-01')
    expect(p.get('to')).toBe('2026-09-01')
  })
  it('may=true và cursor', () => {
    const p = thamSo(duongNhatKy({ ...LOC_MAC_DINH, may: true }, 'abc'))
    expect(p.get('may')).toBe('true')
    expect(p.get('cursor')).toBe('abc')
  })
  it('congMotNgay qua cuối tháng/năm', () => {
    expect(congMotNgay('2026-02-28')).toBe('2026-03-01')
    expect(congMotNgay('2026-12-31')).toBe('2027-01-01')
  })
})

describe('tenNguoi / tomTatChiTiet', () => {
  it('các actor đặc biệt, người đã xoá, actor lạ', () => {
    expect(tenNguoi({ actorId: 'u_x', actorTen: 'Hải Đỗ' })).toBe('Hải Đỗ')
    expect(tenNguoi({ actorId: 'agent', actorTen: null })).toBe('Agent')
    expect(tenNguoi({ actorId: 'platform_admin', actorTen: null })).toBe('NobleX')
    expect(tenNguoi({ actorId: '', actorTen: null })).toBe('Hệ thống')
    expect(tenNguoi({ actorId: 'cron', actorTen: null })).toBe('Hệ thống')
    expect(tenNguoi({ actorId: 'ingest', actorTen: null })).toBe('Cổng nạp')
    expect(tenNguoi({ actorId: 'ingest_token:12', actorTen: null })).toBe('Cổng nạp')
    expect(tenNguoi({ actorId: 'token:5', actorTen: null })).toBe('Cổng nạp')
    expect(tenNguoi({ actorId: 'u_da_xoa', actorTen: null })).toBe('u_da_xoa')
    expect(tenNguoi({ actorId: 'la_hoac_moi', actorTen: null })).toBe('la_hoac_moi')
  })
  it('khoá: giá trị · mảng nối phẩy · object lồng JSON · cắt 120 ký tự', () => {
    const t = tomTatChiTiet({ project_code: 'NT2', truong: ['name', 'price'], meta: { a: 1 } })
    expect(t.dayDu).toBe('project_code: NT2 · truong: name, price · meta: {"a":1}')
    expect(t.ngan).toBe(t.dayDu)
    const dai = tomTatChiTiet({ x: 'a'.repeat(200) })
    expect(dai.ngan.length).toBe(120)
    expect(dai.ngan.endsWith('…')).toBe(true)
    expect(dai.dayDu.length).toBeGreaterThan(120)
    expect(tomTatChiTiet({})).toEqual({ ngan: '', dayDu: '' })
  })
})

describe('locNhatKyGia — fake xử lý tham số như BE', () => {
  const p = (s: string) => new URLSearchParams(s)
  it('mặc định ẩn agent; may=true gộp', () => {
    expect(locNhatKyGia(NHAT_KY_GIA, p('limit=100')).items.every((d) => d.actorId !== 'agent')).toBe(true)
    expect(locNhatKyGia(NHAT_KY_GIA, p('limit=100&may=true')).items.some((d) => d.actorId === 'agent')).toBe(true)
  })
  it('nhom lọc theo tiền tố', () => {
    const r = locNhatKyGia(NHAT_KY_GIA, p('limit=100&nhom=kb,ingest'))
    expect(r.items.length).toBeGreaterThan(0)
    expect(r.items.every((d) => ['kb', 'ingest'].includes(d.hanhDong.split('.')[0] ?? ''))).toBe(true)
  })
  it('phân trang: limit+cursor đi hết không trùng không sót', () => {
    const tatCa = locNhatKyGia(NHAT_KY_GIA, p('limit=100')).items.map((d) => d.id)
    const thay: number[] = []
    let cursor: string | null = null
    for (let i = 0; i < 20; i++) {
      const r = locNhatKyGia(NHAT_KY_GIA, p(`limit=7${cursor ? `&cursor=${cursor}` : ''}`))
      thay.push(...r.items.map((d) => d.id))
      cursor = r.nextCursor
      if (!cursor) break
    }
    expect(thay).toEqual(tatCa)
  })
  it('dữ liệu giả: mới nhất trước, có đủ ba loại actor đặc biệt', () => {
    const luc = NHAT_KY_GIA.map((d) => d.luc)
    expect(luc).toEqual([...luc].sort().reverse())
    expect(NHAT_KY_GIA.some((d) => d.actorId === 'agent')).toBe(true)
    expect(NHAT_KY_GIA.some((d) => d.actorId === '')).toBe(true)
    expect(NHAT_KY_GIA.some((d) => d.actorTen === null && d.actorId.startsWith('u_'))).toBe(true)
  })
})
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npx vitest run tests/nhat-ky-thuan.test.ts`
Expected: FAIL — không resolve được `nhatKy`/`hienNhatKy`/`mswNhatKy`.

- [ ] **Step 3: Viết `src/features/platform/nhatKy.ts`**

```ts
/**
 * Client + hook của màn «Nhật ký» — `GET /api/v1/audit`.
 * Hợp đồng: `odyssey-portal-backend/docs/contracts/audit.md`.
 *
 * `useInfiniteQuery` chứ không phải trang số: API là keyset (`nextCursor`), và
 * nhật ký là dòng thời gian — «Tải thêm» đúng nghĩa hơn «Trang 3/17».
 * Khoá query mang cả `loc`: đổi bộ lọc là một chuỗi trang MỚI, không nối vào
 * chuỗi cũ.
 */

import { useInfiniteQuery } from '@tanstack/react-query'
import { goi } from './api'
import { NHOM_LOC } from './so-hanh-dong'

export interface DongNhatKy {
  readonly id: number
  /** ISO có múi giờ, từ `timestamptz`. */
  readonly luc: string
  readonly hanhDong: string
  /** Nguyên văn cột `actor`: `u_<id>` · `agent` · `platform_admin` · `''`. */
  readonly actorId: string
  readonly actorTen: string | null
  readonly actorEmail: string | null
  readonly chiTiet: Readonly<Record<string, unknown>>
}

export interface TrangNhatKy {
  readonly items: readonly DongNhatKy[]
  readonly nextCursor: string | null
}

/** Trạng thái bộ lọc trên màn — `useState`, KHÔNG search param. */
export interface LocNhatKy {
  /** `NhomLoc.ma` hoặc null = tất cả. */
  readonly nhom: string | null
  /** `YYYY-MM-DD` hoặc null. */
  readonly tu: string | null
  /** «Đến HẾT ngày» — API nhận cận trên MỞ nên gửi `+1 ngày`, xem `duongNhatKy`. */
  readonly denHet: string | null
  /** Hiện hành động máy (`actorId = 'agent'`). Mặc định ẩn. */
  readonly may: boolean
}

export const LOC_MAC_DINH: LocNhatKy = { nhom: null, tu: null, denHet: null, may: false }

export const SO_MOI_TRANG = 50
export const KHOA_NHAT_KY = ['audit'] as const

/** `YYYY-MM-DD` + 1 ngày, tính bằng UTC để không lệ thuộc múi giờ máy. */
export function congMotNgay(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y ?? 1970, (m ?? 1) - 1, (d ?? 1) + 1)).toISOString().slice(0, 10)
}

export function duongNhatKy(loc: LocNhatKy, cursor?: string): string {
  const p = new URLSearchParams()
  p.set('limit', String(SO_MOI_TRANG))
  const nhom = loc.nhom ? NHOM_LOC.find((n) => n.ma === loc.nhom) : undefined
  if (nhom) p.set('nhom', nhom.tienTo.join(','))
  if (loc.tu) p.set('from', loc.tu)
  if (loc.denHet) p.set('to', congMotNgay(loc.denHet))
  if (loc.may) p.set('may', 'true')
  if (cursor) p.set('cursor', cursor)
  return `/api/v1/audit?${p.toString()}`
}

export function taiNhatKy(loc: LocNhatKy, cursor?: string): Promise<TrangNhatKy> {
  return goi<TrangNhatKy>(duongNhatKy(loc, cursor))
}

export function useNhatKy(loc: LocNhatKy) {
  return useInfiniteQuery({
    queryKey: [...KHOA_NHAT_KY, loc],
    queryFn: ({ pageParam }) => taiNhatKy(loc, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (cuoi) => cuoi.nextCursor ?? undefined,
  })
}
```

- [ ] **Step 4: Viết `src/features/platform/hienNhatKy.ts`**

```ts
/**
 * Cách hiện một hàng nhật ký — người và chi tiết. Tách khỏi component vì
 * `react-refresh/only-export-components` cấm .tsx export hàm thuần.
 */

import type { DongNhatKy } from './nhatKy'

/**
 * `actorId` không phải người — các dạng THẬT BE ghi (docs/contracts/audit.md, kiểm
 * 2026-08-25): `agent` (agent bootstrap) · `platform_admin` (NobleX) · `cron` (job
 * định kỳ) · `ingest` / `ingest_token:<id>` (cổng nạp) · `token:<id>` (importer cũ) · `''`
 * (không ghi được người).
 * Danh sách có thể mọc — dạng lạ hiện NGUYÊN chuỗi, không bao giờ lọc bỏ hàng.
 */
const TEN_DAC_BIET: Readonly<Record<string, string>> = {
  agent: 'Agent',
  platform_admin: 'NobleX',
  cron: 'Hệ thống',
  ingest: 'Cổng nạp',
  '': 'Hệ thống',
}

const TIEN_TO_CONG_NAP = ['ingest_token:', 'token:'] as const

/** Tên người; người đã bị gỡ (tên null, id `u_…`) hiện id thô — vẫn là bằng chứng. */
export function tenNguoi(d: Pick<DongNhatKy, 'actorId' | 'actorTen'>): string {
  if (d.actorTen) return d.actorTen
  if (TIEN_TO_CONG_NAP.some((t) => d.actorId.startsWith(t))) return TEN_DAC_BIET.ingest ?? d.actorId
  return TEN_DAC_BIET[d.actorId] ?? d.actorId
}

const GIOI_HAN_NGAN = 120

function giaTri(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (Array.isArray(v)) return v.map(giaTri).join(', ')
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

/**
 * `khoá: giá trị` nối bằng « · ». Đợt 1 KHÔNG có formatter riêng theo mã —
 * `chiTiet` là jsonb nguyên văn với hình dạng khác nhau mỗi mã (spec §6).
 * `ngan` để hiện trong ô, `dayDu` cho `title`.
 */
export function tomTatChiTiet(ct: Readonly<Record<string, unknown>>): { ngan: string; dayDu: string } {
  const dayDu = Object.entries(ct)
    .map(([k, v]) => `${k}: ${giaTri(v)}`)
    .join(' · ')
  const ngan = dayDu.length > GIOI_HAN_NGAN ? `${dayDu.slice(0, GIOI_HAN_NGAN - 1)}…` : dayDu
  return { ngan, dayDu }
}
```

- [ ] **Step 5: Viết `src/features/platform/mswNhatKy.ts`**

```ts
/**
 * Fake MSW của `GET /api/v1/audit` — CÓ xử lý `limit`/`cursor`/`nhom`/`from`/`to`/`may`
 * như BE, để test màn kiểm được hành vi thật (bật công tắc → hàng agent hiện;
 * «Tải thêm» → nối trang). Cùng lối `features/realestate/msw.ts`.
 *
 * Con trỏ của fake = base64(id) — đủ vì dữ liệu giả có `luc` giảm cùng `id`;
 * BE thật mã hoá cả `(luc, id)`, FE không đọc ruột cursor nên khác nhau vô hại.
 */

import { http, HttpResponse } from 'msw'
import type { DongNhatKy, TrangNhatKy } from './nhatKy'

const HAI = { actorId: 'u_fake_hai', actorTen: 'Hải Đỗ', actorEmail: 'hai@anphu.vn' }
const DANG = { actorId: 'u_fake_dang', actorTen: 'Đặng Văn Dũng', actorEmail: 'dang@anphu.vn' }
const MAY = { actorId: 'agent', actorTen: null, actorEmail: null }
const CRON = { actorId: 'cron', actorTen: null, actorEmail: null }
const HE_THONG = { actorId: '', actorTen: null, actorEmail: null }
const CONG_NAP = { actorId: 'ingest_token:7', actorTen: null, actorEmail: null }
const DA_XOA = { actorId: 'u_da_xoa', actorTen: null, actorEmail: null }

type Ai = typeof HAI
/** Chu kỳ 15 mẫu; hàng đầu (i = 0) là «Sửa dự án» của Hải — test màn bám vào đó. */
const MAU: readonly [string, Ai, Record<string, unknown>][] = [
  ['realestate.project.update', HAI, { project_code: 'NT2', truong: ['name', 'price'] }],
  ['thanh_vien.moi', DANG, { email: 'moi@anphu.vn', role: 'CSKH' }],
  ['agent.runtime_credentials', MAY, { agent_key_id: 3 }],
  ['ingest.tenant_im_lang', CRON, { gio_im_lang: 26 }],
  ['kb.upload', DA_XOA, { ten_file: 'bang-gia-q3.pdf' }],
  ['agent_config.publish', DANG, { version: 12, truong_da_doi: ['persona', 'tools'] }],
  ['role.sua', DANG, { role_id: 'r_cskh', truong: ['actions'] }],
  ['linh_vuc.bat', HAI, { ma: 'bds' }],
  ['workspace.doi_ten', DANG, { ten_cu: 'An Phu', ten_moi: 'An Phú Land' }],
  ['billing.price_version_kich_hoat', DANG, { price_version: 'pv_2026_q3' }],
  ['ingest.token_tao', HE_THONG, { label: 'CRM nội bộ' }],
  ['ingest.nghi_mat_tich', CONG_NAP, { so_ban_ghi: 3 }],
  ['kb.delete', HAI, { ten_file: 'cu.docx' }],
  ['realestate.unit.create', HAI, { project_code: 'NT2', unit_code: 'A-12-05' }],
  ['agent.phat_khoa', DANG, { label: 'prod' }],
]

const SO_HANG = 45
const MOC = Date.UTC(2026, 7, 25, 10, 0)
const BUOC_MS = 5.5 * 3600 * 1000 // ~10 ngày cho 45 hàng

export const NHAT_KY_GIA: readonly DongNhatKy[] = Array.from({ length: SO_HANG }, (_, i) => {
  const [hanhDong, ai, chiTiet] = MAU[i % MAU.length] as (typeof MAU)[number]
  return { id: 1000 - i, luc: new Date(MOC - i * BUOC_MS).toISOString(), hanhDong, ...ai, chiTiet }
})

function ngayVN(iso: string): string {
  return new Date(new Date(iso).getTime() + 7 * 3600 * 1000).toISOString().slice(0, 10)
}

export function locNhatKyGia(hang: readonly DongNhatKy[], p: URLSearchParams): TrangNhatKy {
  const limit = Number(p.get('limit') ?? 50)
  const nhom = p.get('nhom')?.split(',') ?? null
  const may = p.get('may') === 'true'
  const from = p.get('from')
  const to = p.get('to')
  const cursor = p.get('cursor')
  let ds = hang.filter((h) => may || h.actorId !== 'agent')
  if (nhom) ds = ds.filter((h) => nhom.includes(h.hanhDong.split('.')[0] ?? ''))
  if (from) ds = ds.filter((h) => ngayVN(h.luc) >= from)
  if (to) ds = ds.filter((h) => ngayVN(h.luc) < to)
  if (cursor) {
    const sau = Number(atob(cursor))
    ds = ds.filter((h) => h.id < sau)
  }
  const trang = ds.slice(0, limit)
  const cuoi = trang[trang.length - 1]
  return { items: trang, nextCursor: ds.length > limit && cuoi ? btoa(String(cuoi.id)) : null }
}

export const nhatKyHandlers = [
  http.get('/api/v1/audit', ({ request }) =>
    HttpResponse.json(locNhatKyGia(NHAT_KY_GIA, new URL(request.url).searchParams)),
  ),
]
```

- [ ] **Step 6: Cắm fake vào `src/lib/msw/handlers.ts`**

Sau `import { billingHandlers } from '@/features/billing/msw'` (dòng 18) thêm:

```ts
import { nhatKyHandlers } from '@/features/platform/mswNhatKy'
```

Sau `...billingHandlers,` (dòng ~789) thêm `...nhatKyHandlers,`.

- [ ] **Step 7: Chạy test**

Run: `npx vitest run tests/nhat-ky-thuan.test.ts tests/module-boundaries.test.ts`
Expected: PASS toàn bộ (13 bài + boundaries).

- [ ] **Step 8: Lint + commit**

Run: `npx prettier --write src/features/platform/nhatKy.ts src/features/platform/hienNhatKy.ts src/features/platform/mswNhatKy.ts tests/nhat-ky-thuan.test.ts && make lint`

```bash
git add src/features/platform/nhatKy.ts src/features/platform/hienNhatKy.ts \
  src/features/platform/mswNhatKy.ts src/lib/msw/handlers.ts tests/nhat-ky-thuan.test.ts
git commit -m "feat(audit): client GET /audit (infinite query), helper hiển thị, fake MSW xử lý tham số"
```

---

### Task 4: Ba component + route `/audit` + `screens.ts` + dấu hiệu màn

**Files:**
- Create: `src/features/platform/components/BoLocNhatKy.tsx`, `src/features/platform/components/BangNhatKy.tsx`, `src/features/platform/components/NhatKyScreen.tsx`
- Modify: `src/routes/_app/audit.tsx` (thay stub), `src/lib/screens.ts:161` (`mvp: 'full'`), `tests/boot.test.tsx` (thêm dấu hiệu `audit`)
- Create: `tests/nhat-ky.test.tsx`

**Interfaces:**
- Consumes: Task 2 (`NHOM_LOC`, `nhanHanhDong`), Task 3 (`useNhatKy`, `LocNhatKy`, `LOC_MAC_DINH`, `DongNhatKy`, `tenNguoi`, `tomTatChiTiet`, `NHAT_KY_GIA`, `locNhatKyGia`), `dinhDangLuc` từ `../api`, primitive `components/ui/Bang.tsx` (`TheBang`, `VungCuon`, `ChanBang`, `Bang`, `DauBang`, `Hang`, `TD`, `TD_PHU`, `NUT_PHU`, `O_LOC`, `HANG_NUT`) và `components/ui/TrangThai.tsx` (`KhoRong`).
- Produces: `NhatKyScreen` (không prop) — route dùng.

- [ ] **Step 1: Viết test đỏ `tests/nhat-ky.test.tsx`**

```tsx
/**
 * Màn «Nhật ký» (`/audit`, M8) — render component TRỰC TIẾP, không boot router
 * (cùng lý lẽ `khoa-dau-noi.test.tsx`). Fake MSW mặc định là `nhatKyHandlers`;
 * các bài cần đếm request thì `server.use` một handler GHI LẠI url rồi uỷ quyền
 * cho `locNhatKyGia` — hành vi giữ nguyên, chỉ thêm tai nghe.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { LangProvider } from '../src/i18n'
import { NhatKyScreen } from '../src/features/platform/components/NhatKyScreen'
import { NHAT_KY_GIA, locNhatKyGia } from '../src/features/platform/mswNhatKy'
import { server } from '../vitest.setup'

function boot() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <LangProvider>
        <NhatKyScreen />
      </LangProvider>
    </QueryClientProvider>,
  )
}

/** Ghi lại mọi URL gọi `/api/v1/audit`; `epLimit` ép trang nhỏ để test «Tải thêm». */
function ngheRequest(epLimit?: number): URLSearchParams[] {
  const goi: URLSearchParams[] = []
  server.use(
    http.get('/api/v1/audit', ({ request }) => {
      const p = new URL(request.url).searchParams
      goi.push(new URLSearchParams(p))
      if (epLimit !== undefined) p.set('limit', String(epLimit))
      return HttpResponse.json(locNhatKyGia(NHAT_KY_GIA, p))
    }),
  )
  return goi
}

async function bang() {
  return within(await screen.findByRole('table', { name: 'Nhật ký hoạt động' }))
}

function soHang(b: ReturnType<typeof within>): number {
  return b.getAllByRole('row').length - 1 // trừ hàng tiêu đề
}

describe('màn Nhật ký', () => {
  beforeEach(() => server.resetHandlers())

  it('hiện nhãn tiếng Việt, tên người, ba loại actor đặc biệt', async () => {
    boot()
    const b = await bang()
    expect(b.getByText('Sửa dự án')).toBeInTheDocument()
    expect(b.queryByText('realestate.project.update')).not.toBeInTheDocument()
    expect(b.getAllByText('Hải Đỗ').length).toBeGreaterThan(0)
    expect(b.getAllByText('Hệ thống').length).toBeGreaterThan(0)
    expect(b.getAllByText('Cổng nạp').length).toBeGreaterThan(0)
    expect(b.getAllByText('u_da_xoa').length).toBeGreaterThan(0)
    // Mặc định KHÔNG có hàng máy
    expect(b.queryByText('Agent')).not.toBeInTheDocument()
    expect(b.queryByText('Agent lấy credential')).not.toBeInTheDocument()
    // Chi tiết dạng khoá: giá trị
    expect(b.getAllByText('project_code: NT2 · truong: name, price').length).toBeGreaterThan(0)
  })

  it('mặc định request KHÔNG có may; bật công tắc ⇒ may=true và hàng agent hiện', async () => {
    const goi = ngheRequest()
    boot()
    await bang()
    expect(goi[0]?.has('may')).toBe(false)
    await userEvent.click(screen.getByRole('checkbox', { name: 'Hiện hoạt động của agent' }))
    await waitFor(() => expect(goi.at(-1)?.get('may')).toBe('true'))
    const b = await bang()
    await waitFor(() => expect(b.getAllByText('Agent lấy credential').length).toBeGreaterThan(0))
  })

  it('đổi nhóm ⇒ request mang đúng danh sách tiền tố', async () => {
    const goi = ngheRequest()
    boot()
    await bang()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Nhóm hành động' }), 'thanh-vien')
    await waitFor(() => expect(goi.at(-1)?.get('nhom')).toBe('thanh_vien,user,role,owner'))
    const b = await bang()
    await waitFor(() => expect(b.queryByText('Sửa dự án')).not.toBeInTheDocument())
    expect(b.getAllByText('Mời thành viên').length).toBeGreaterThan(0)
  })

  it('«đến hết ngày» D ⇒ to = D + 1; «từ ngày» gửi nguyên', async () => {
    const goi = ngheRequest()
    boot()
    await bang()
    await userEvent.type(screen.getByLabelText('Từ ngày'), '2026-08-18')
    await userEvent.type(screen.getByLabelText('Đến hết ngày'), '2026-08-20')
    await waitFor(() => {
      const p = goi.at(-1)
      expect(p?.get('from')).toBe('2026-08-18')
      expect(p?.get('to')).toBe('2026-08-21')
    })
  })

  it('«Tải thêm» nối trang và biến mất khi hết', async () => {
    const goi = ngheRequest(3)
    boot()
    let b = await bang()
    expect(soHang(b)).toBe(3)
    await userEvent.click(screen.getByRole('button', { name: 'Tải thêm' }))
    await waitFor(() => expect(soHang(bangDongBo())).toBe(6))
    expect(goi.at(-1)?.get('cursor')).toBeTruthy()
    // Bấm tới khi hết: 45 hàng − 3 hàng agent (i = 2, 17, 32) = 42 hàng ⇒ 14 trang.
    for (let i = 0; i < 20 && screen.queryByRole('button', { name: 'Tải thêm' }); i++) {
      await userEvent.click(screen.getByRole('button', { name: 'Tải thêm' }))
      await waitFor(() => expect(screen.queryByRole('button', { name: /Đang tải/ })).not.toBeInTheDocument())
    }
    b = await bang()
    expect(soHang(b)).toBe(42)
    expect(screen.queryByRole('button', { name: 'Tải thêm' })).not.toBeInTheDocument()
  })

  it('rỗng', async () => {
    server.use(http.get('/api/v1/audit', () => HttpResponse.json({ items: [], nextCursor: null })))
    boot()
    expect(await screen.findByText('Chưa có hoạt động nào')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('403 hiện message của API nguyên văn', async () => {
    server.use(
      http.get('/api/v1/audit', () =>
        HttpResponse.json(
          { error: { code: 'FORBIDDEN', message: 'Vai trò Người xem không có quyền Xem Nhật ký hoạt động' } },
          { status: 403 },
        ),
      ),
    )
    boot()
    const canh = await screen.findByRole('alert')
    expect(canh).toHaveTextContent('Vai trò Người xem không có quyền Xem Nhật ký hoạt động')
  })
})

function bangDongBo() {
  return within(screen.getByRole('table', { name: 'Nhật ký hoạt động' }))
}
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `npx vitest run tests/nhat-ky.test.tsx`
Expected: FAIL — không resolve được `NhatKyScreen`.

- [ ] **Step 3: Viết `src/features/platform/components/BoLocNhatKy.tsx`**

```tsx
/**
 * Thanh lọc màn Nhật ký: nhóm · từ ngày · đến hết ngày · công tắc hành động máy.
 *
 * `<select>`/`<input type=date>` trần với lớp `O_LOC` (như `realestate/ThanhTrang.tsx`),
 * không qua `OChon`/`Khung` của `Truong.tsx` — đó là primitive FORM (nhãn trên,
 * gợi ý, lỗi), còn đây là một thanh lọc nằm ngang.
 *
 * «Đến HẾT ngày»: người dùng nghĩ theo ngày đóng hai đầu; API nhận cận trên MỞ —
 * phép `+1` nằm ở `duongNhatKy`, không ở đây.
 */
import { O_LOC } from '@/components/ui/Bang'
import { NHOM_LOC } from '../so-hanh-dong'
import type { LocNhatKy } from '../nhatKy'

const NHAN = 'flex flex-col gap-1 text-[12.5px] text-muted'

export function BoLocNhatKy({ loc, doi }: { readonly loc: LocNhatKy; readonly doi: (l: LocNhatKy) => void }) {
  return (
    <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Bộ lọc nhật ký">
      <label className={NHAN}>
        Nhóm
        <select
          aria-label="Nhóm hành động"
          className={`${O_LOC} bg-surface`}
          value={loc.nhom ?? ''}
          onChange={(e) => doi({ ...loc, nhom: e.target.value || null })}
        >
          <option value="">Tất cả</option>
          {NHOM_LOC.map((n) => (
            <option key={n.ma} value={n.ma}>
              {n.nhan}
            </option>
          ))}
        </select>
      </label>
      <label className={NHAN}>
        Từ ngày
        <input
          type="date"
          aria-label="Từ ngày"
          className={`${O_LOC} bg-surface`}
          value={loc.tu ?? ''}
          onChange={(e) => doi({ ...loc, tu: e.target.value || null })}
        />
      </label>
      <label className={NHAN}>
        Đến hết ngày
        <input
          type="date"
          aria-label="Đến hết ngày"
          className={`${O_LOC} bg-surface`}
          value={loc.denHet ?? ''}
          onChange={(e) => doi({ ...loc, denHet: e.target.value || null })}
        />
      </label>
      <label className="flex h-9 items-center gap-2 text-[13.5px]">
        <input type="checkbox" checked={loc.may} onChange={(e) => doi({ ...loc, may: e.target.checked })} />
        Hiện hoạt động của agent
      </label>
    </div>
  )
}
```

- [ ] **Step 4: Viết `src/features/platform/components/BangNhatKy.tsx`**

```tsx
/**
 * Bảng nhật ký: Thời gian · Người · Hành động · Chi tiết + chân «Tải thêm».
 * Không sắp xếp, không chọn hàng — nhật ký đọc theo dòng thời gian, mới nhất trước.
 */
import {
  Bang,
  ChanBang,
  DauBang,
  HANG_NUT,
  Hang,
  NUT_PHU,
  TD,
  TD_PHU,
  TheBang,
  VungCuon,
} from '@/components/ui/Bang'
import { dinhDangLuc } from '../api'
import { tenNguoi, tomTatChiTiet } from '../hienNhatKy'
import { nhanHanhDong } from '../so-hanh-dong'
import type { DongNhatKy } from '../nhatKy'

const COT = [{ nhan: 'Thời gian' }, { nhan: 'Người' }, { nhan: 'Hành động' }, { nhan: 'Chi tiết', rong: 'w-full' }]

export function BangNhatKy({
  dong,
  conNua,
  dangTaiThem,
  taiThem,
}: {
  readonly dong: readonly DongNhatKy[]
  readonly conNua: boolean
  readonly dangTaiThem: boolean
  readonly taiThem: () => void
}) {
  return (
    <TheBang>
      <VungCuon>
        <Bang nhan="Nhật ký hoạt động">
          <DauBang cot={COT} />
          <tbody>
            {dong.map((d) => {
              const tt = tomTatChiTiet(d.chiTiet)
              return (
                <Hang key={d.id}>
                  <td className={TD_PHU}>{dinhDangLuc(d.luc)}</td>
                  <td className={`${TD} whitespace-nowrap`} title={d.actorEmail ?? undefined}>
                    {tenNguoi(d)}
                  </td>
                  <td className={`${TD} whitespace-nowrap`}>{nhanHanhDong(d.hanhDong)}</td>
                  <td className={`${TD} font-mono text-[12.5px] text-muted`} title={tt.dayDu}>
                    {tt.ngan}
                  </td>
                </Hang>
              )
            })}
          </tbody>
        </Bang>
      </VungCuon>
      {conNua ? (
        <ChanBang>
          <div className={HANG_NUT}>
            <button type="button" className={NUT_PHU} disabled={dangTaiThem} onClick={taiThem}>
              {dangTaiThem ? 'Đang tải…' : 'Tải thêm'}
            </button>
          </div>
        </ChanBang>
      ) : null}
    </TheBang>
  )
}
```

⚠ Kiểm `Cot` ở `components/ui/Bang.tsx:391` — nếu `rong` không phải tên trường (có thể là `rong?: string` hay khác), dùng đúng tên thật; `BangLuotDungUsage.tsx` đã dùng `{ nhan: 'Khoá', rong: 'w-full' }`.

- [ ] **Step 5: Viết `src/features/platform/components/NhatKyScreen.tsx`**

```tsx
/**
 * Màn «Nhật ký» (`/audit`, M8) — đọc `control.audit_log` của workspace hiện tại.
 * Spec: odyssey-portal-backend/docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md §6.
 *
 * Bộ lọc là `useState`, KHÔNG search param: bộ lọc ở đây không phải link gửi đi
 * được (khác `?tab=` của /projects) và không cần Back.
 *
 * LỖI HIỆN MESSAGE CỦA API NGUYÊN VĂN (không dùng `LoiTai` — nó in câu chung
 * «Không tải được …»): 403 của BE nói đúng vai trò và tên quyền còn thiếu, đó là
 * thứ người dùng cần để đi xin quyền.
 */
import { useState } from 'react'
import { KhoRong } from '@/components/ui/TrangThai'
import { NUT_PHU } from '@/components/ui/Bang'
import { LOC_MAC_DINH, useNhatKy, type LocNhatKy } from '../nhatKy'
import { BangNhatKy } from './BangNhatKy'
import { BoLocNhatKy } from './BoLocNhatKy'

export function NhatKyScreen() {
  const [loc, datLoc] = useState<LocNhatKy>(LOC_MAC_DINH)
  const q = useNhatKy(loc)
  const dong = q.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="flex max-w-[1420px] flex-col gap-4 px-7 pt-[22px] pb-15">
      <BoLocNhatKy loc={loc} doi={datLoc} />
      {q.isError ? (
        <div className="rounded-lg border border-badge-alert-fg/40 bg-badge-alert-bg p-4 text-[14px]" role="alert">
          <p>{q.error.message}</p>
          <button type="button" className={`${NUT_PHU} mt-2`} onClick={() => void q.refetch()}>
            Thử lại
          </button>
        </div>
      ) : null}
      {q.isPending ? <p className="text-[14px] text-muted">Đang tải…</p> : null}
      {q.isSuccess && dong.length === 0 ? (
        <KhoRong tieuDe="Chưa có hoạt động nào" huongDan="Không có hoạt động nào trong khoảng đã chọn." />
      ) : null}
      {dong.length > 0 ? (
        <BangNhatKy
          dong={dong}
          conNua={q.hasNextPage}
          dangTaiThem={q.isFetchingNextPage}
          taiThem={() => void q.fetchNextPage()}
        />
      ) : null}
    </div>
  )
}
```

- [ ] **Step 6: Thay stub ở `src/routes/_app/audit.tsx`**

```tsx
import { createFileRoute } from '@tanstack/react-router'
import { NhatKyScreen } from '@/features/platform/components/NhatKyScreen'

// Màn `audit` của M8 — «Nhật ký» (2026-08-25, thay ScreenStub). Đọc GET /api/v1/audit,
// quyền `audit.read`. Không search param: bộ lọc là state cục bộ của màn.
export const Route = createFileRoute('/_app/audit')({
  component: NhatKyScreen,
})
```

`src/lib/screens.ts:161` → `{ key: 'audit', path: '/audit', owner: 'M8', mvp: 'full', inNav: true },`

- [ ] **Step 7: Thêm dấu hiệu màn vào `tests/boot.test.tsx`**

Trong `DAU_HIEU_MAN_THAT`, sau mục `usage:` thêm:

```ts
  // M8 — NhatKyScreen (2026-08-25, thay ScreenStub). Dấu hiệu là nhãn công tắc
  // «Hiện hoạt động của agent», KHÔNG phải nhãn nav «Nhật ký» (Topbar render
  // nhãn đó thành <h1>, panel cũng có — cùng bẫy đã ghi ở kb/users/…). Chuỗi này
  // hiện NGAY lúc mount (thanh lọc không đợi request), nên chỉ chứng minh route
  // mở đúng component — cùng hạng `pricing`.
  audit: 'Hiện hoạt động của agent',
```

- [ ] **Step 8: Sinh lại route tree (nếu cần) và chạy test**

Run: `npx tsr generate && git diff --stat src/routeTree.gen.ts`
Expected: KHÔNG đổi (file route đã tồn tại, chỉ đổi component) — nếu có diff, xem lại rồi giữ.

Run: `npx vitest run tests/nhat-ky.test.tsx tests/boot.test.tsx tests/nav-registry.test.ts tests/command-palette.test.tsx tests/module-boundaries.test.ts`
Expected: PASS. Bẫy đã biết: (1) `getByRole('checkbox', {name})` cần nhãn bao ngoài `<label>` — đã có; (2) `userEvent.type` vào `input[type=date]` dưới jsdom nhận chuỗi `YYYY-MM-DD` — nếu không bắn `change`, thay bằng `fireEvent.change(el, { target: { value: '2026-08-18' } })`; (3) bài «Tải thêm» đếm 42 = 45 − 3 hàng agent (i = 2, 17, 32 vì `MAU[2]` là hàng máy, chu kỳ 15) — nếu đổi `MAU`/`SO_HANG` thì tính lại con số này.

- [ ] **Step 9: Lint + commit**

Run: `npx prettier --write src/features/platform/components/BoLocNhatKy.tsx src/features/platform/components/BangNhatKy.tsx src/features/platform/components/NhatKyScreen.tsx src/routes/_app/audit.tsx tests/nhat-ky.test.tsx && make lint`

```bash
git add src/features/platform/components/BoLocNhatKy.tsx src/features/platform/components/BangNhatKy.tsx \
  src/features/platform/components/NhatKyScreen.tsx src/routes/_app/audit.tsx src/lib/screens.ts \
  tests/boot.test.tsx tests/nhat-ky.test.tsx
git commit -m "feat(audit): màn Nhật ký — bảng + lọc nhóm/ngày + công tắc agent + Tải thêm"
```

---

### Task 5: Change Log + toàn bộ cổng + soi trên trình duyệt

**Files:**
- Modify: `CLAUDE.md` (bảng «Change Log», thêm MỘT dòng ngay dưới `|---|---|` ở dòng ~433 — mới nhất trên cùng)

- [ ] **Step 1: Thêm dòng Change Log**

```markdown
| 2026-08-25 | **Màn `/audit` («Nhật ký») XÂY MỚI thay `ScreenStub`** (spec BE `docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md`, plan `docs/superpowers/plans/2026-08-25-man-nhat-ky.md`, hợp đồng `odyssey-portal-backend/docs/contracts/audit.md`). `screens.ts`: `audit` → `mvp: 'full'`; nav khoá theo **action thứ 15 `audit.read`** (trước là `overview.read` placeholder — bài `shell.test` «thiếu WORKSPACE_ADMIN…» phải cấp thêm `AUDIT_READ`), bỏ `badge warn`. `features/platform/`: `nhatKy.ts` (`useInfiniteQuery`, khoá `['audit', loc]`, «đến hết ngày» ⇒ `to = D+1` vì API cận trên MỞ) · `so-hanh-dong.ts` (mã→nhãn + 9 nhóm lọc gộp tiền tố; **cổng parity `tests/audit-actions-parity.test.ts`** với `contracts/audit-actions.json` copy từ BE — thêm điểm ghi ở BE mà quên nhãn là đỏ) · `hienNhatKy.ts` (`agent`→«Agent», `platform_admin`→«NobleX», `cron`/`''`→«Hệ thống», `ingest`/`ingest_token:*`/`token:*`→«Cổng nạp», user đã xoá/actor lạ hiện id thô — không lọc bỏ; 9 mã nghỉ hưu có nhãn «(cũ)»; chi tiết `khoá: giá trị`, cắt 120) · `mswNhatKy.ts` (fake CÓ xử lý `limit/cursor/nhom/from/to/may`). Ba component `BoLocNhatKy`/`BangNhatKy`/`NhatKyScreen`; bộ lọc là `useState`, không search param. Mặc định ẨN hàng `actor='agent'` (38% số dòng trên dev), công tắc «Hiện hoạt động của agent». Lỗi hiện `LoiApi.message` NGUYÊN VĂN (không `LoiTai`) — 403 của BE nói đúng quyền thiếu. Chưa có: CSV, tìm theo người, formatter chi tiết theo mã, «việc của chính mình» cho vai trò không có `audit.read` (đợt 2). |
```

- [ ] **Step 2: Toàn bộ cổng**

Run: `make check`
Expected: eslint 0 warning · prettier check sạch (chỉ tệp mới của đợt này đã `--write`; 28 tệp lệch cũ giữ nguyên nếu `make lint` vốn đã xanh trên develop — nếu `prettier --check` đỏ ở tệp KHÔNG thuộc đợt này, đó là nợ cũ, ghi vào báo cáo, không sửa) · `tsc -b` sạch · vitest toàn suite xanh (kỳ vọng ≈ 1087 + ~27 bài mới).

- [ ] **Step 3: Soi bằng mắt trên MSW**

Run: `npm run dev` rồi mở `http://localhost:5173/audit` (MSW bật, không cần BE). Kiểm: bảng 4 cột có 42 hàng người + nút «Tải thêm» không hiện (fake 45 hàng < 50); bật công tắc ⇒ thêm 3 hàng «Agent»; chọn nhóm «Kiến thức» ⇒ chỉ còn Tải lên/Xoá tài liệu; chọn ngày; rail «Quản trị» có «Nhật ký» không còn chấm cảnh báo. Nếu Chrome headless không nắm được service worker (đã ghi ở Change Log 2026-08-24) thì mở bằng trình duyệt thường.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: Change Log màn Nhật ký"
```

- [ ] **Step 5: Soi với BE thật (khi BE nhánh `feat/nhat-ky-doc` chạy local ở :8100)**

`VITE_MSW=0 npm run dev`, đăng nhập bằng tài khoản có vai trò Quản trị, mở `/audit`: hàng thật, tên người thật, `nextCursor` thật đi qua «Tải thêm» (đặt `limit` nhỏ tạm thời trong DevTools nếu dev có < 50 hàng). Không commit gì ở bước này.

---

## Self-review (đã chạy lúc viết plan)

- **Spec coverage:** §3 FE (copy artefact, `lib/actions.ts`, test đếm, `auditNav`) → Task 1 · §5 FE (`so-hanh-dong.ts`, parity test a–d) → Task 2 · §6 tệp mới (`nhatKy.ts`, `mswNhatKy.ts`, ba component, route, `screens.ts`) → Task 3–4 · §6 «Test cũ đổi theo» (`boot.test.tsx` dấu hiệu; `nav-registry` gating; `command-palette` KHÔNG đổi — dựng stub riêng) → Task 1, 4 · §7 test FE (nhãn/actor đặc biệt, `may`, `nhom`, `to=D+1`, Tải thêm, rỗng, 403, parity) → Task 4, 2. Thêm ngoài spec: `shell.test.tsx` cấp `AUDIT_READ` (phát hiện lúc viết plan), `hienNhatKy.ts` tách riêng vì luật react-refresh.
- **Placeholder:** không TBD; vòng «bù nhãn theo báo cáo» (Task 2 Step 4) có tiêu chí dừng rõ.
- **Type consistency:** `LocNhatKy {nhom, tu, denHet, may}` dùng thống nhất ở `nhatKy.ts`/`BoLocNhatKy`/`NhatKyScreen`; `locNhatKyGia(hang, URLSearchParams)` cùng chữ ký ở fake, test thuần, test màn; `tenNguoi(Pick<DongNhatKy,'actorId'|'actorTen'>)` nhận nguyên `DongNhatKy` được; `NHOM_LOC[].ma` là giá trị `<option>`, `tienTo` là thứ gửi đi — test bám đúng hai chiều đó.
