# Backend màn «Nhật ký» — `GET /api/v1/audit` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dựng đường ĐỌC `control.audit_log` cho màn `/audit` của FE: action mới `audit.read`, endpoint `GET /api/v1/audit` (keyset, lọc nhóm/ngày/máy, join người), sổ mã hành động + artefact `contracts/audit-actions.json` để FE canh parity nhãn.

**Architecture:** Module mới `modules/audit/` (`router.py` khai `ROUTER`, registry tự quét — KHÔNG sửa `api/app.py`) gồm `contracts.py` (model + con trỏ) · `repo.py` (một câu SQL) · `router.py`. Không `service.py` — không có nghiệp vụ, chỉ đọc. Phần GHI (`core/nhat_ky.py`, 50 điểm ghi) KHÔNG đụng. Sổ mã `core/nhat_ky_ma.py` là nguồn sự thật cho artefact, được một test AST giữ cho khớp với các literal ở điểm ghi.

**Tech Stack:** FastAPI + asyncpg (SQL thuần) + alembic (migration SQL) + pydantic v2 + pytest (Docker cho `tests/modules`, không cần cho `tests/unit`).

**Spec:** `docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md` — plan này lập luận từ spec đó, executor đọc CẢ HAI.

## Global Constraints

- Nhánh `feat/nhat-ky-doc`, base `develop` @ `51f424a` (đã tạo, chứa commit spec `c41c2ce`). KHÔNG rebase/merge giữa chừng.
- Commit message `<type>: <subject>` (feat/fix/docs/test/chore), KHÔNG footer attribution. Stage theo ĐƯỜNG DẪN tường minh — cấm `git add -A`/`git add .`/`commit -a`.
- `tenant_id` LUÔN lấy từ `Principal` (`p.tenant_id`), KHÔNG từ query/path/body. SQL chạm `control.audit_log` chạy trong `tenant_conn(pool, p.tenant_id)` và mang vị từ LITERAL `a.tenant_id = portal.current_tenant()` trong chuỗi SQL. Hàng `tenant_id IS NULL` không bao giờ lọt.
- Hợp đồng HTTP đóng băng theo spec §4: tham số `limit`/`cursor`/`nhom`/`from`/`to`/`may`; response `{items:[{id,luc,hanhDong,actorId,actorTen,actorEmail,chiTiet}], nextCursor}`; mã lỗi `CURSOR_KHONG_HOP_LE` (400) · `NHOM_KHONG_HOP_LE` (422) · `KHOANG_KHONG_HOP_LE` (422).
- `chiTiet` trả NGUYÊN jsonb (`json.loads` — asyncpg trả jsonb dạng `str`, xem `modules/config/repo.py:55`), không lọc, không đổi tên khoá.
- Migration: literal đóng băng (`'Quản trị'`, `'audit.read'` viết thẳng), KHÔNG import `portal.*`; `down_revision = "0955_hop_nhat_hai_head"` (head duy nhất — đã kiểm `uv run alembic heads`; kiểm lại trước khi viết, `tests/unit/test_alembic_mot_head.py` sẽ đỏ nếu lệch).
- Mọi đổi ở `core/auth/actions.py` hoặc `core/nhat_ky_ma.py` PHẢI kèm `make contracts` trong cùng commit — `tests/api/test_contracts.py` canh byte-for-byte.
- Test chạy bằng `uv run pytest …` (KHÔNG `pytest` trần). `tests/modules` và `tests/api` cần Docker (Postgres/Redis/MinIO dựng từ `alembic upgrade head` — migration hỏng làm ĐỎ cả thư mục, đó là chủ ý). `tests/unit` không cần Docker.
- Lint: `make lint` (`ruff check . && ruff format --check .`, line-length 120). Chạy trước MỖI commit.
- Python: type annotation đủ trên chữ ký; docstring giải thích VÌ SAO theo nếp repo (tiếng Việt).
- KHÔNG chạm route/module khác ngoài các file liệt kê trong từng task.

---

### Task 1: Action `audit.read` — code + migration + cập nhật các test đếm 14→15

**Files:**
- Modify: `src/portal/core/auth/actions.py:51-53` (thêm hằng sau `BILLING_READ`) và `:81` (thêm dòng `NHAN_HANH_DONG`)
- Create: `migrations/versions/0956_audit_action.py`
- Create: `tests/modules/audit/__init__.py` (rỗng), `tests/modules/audit/test_action.py`
- Modify: `tests/api/test_actions.py:10` · `tests/api/test_contracts.py:43-50` · `tests/modules/enrollment/test_router.py:54-59` · `tests/modules/auth/test_vai_tro.py:262-268`

**Interfaces:**
- Produces: `ACTIONS.AUDIT_READ == "audit.read"` (dùng ở Task 5 `require(ACTIONS.AUDIT_READ)`); hàng `control.actions` code `audit.read` cấp cho vai trò «Quản trị».

- [ ] **Step 1: Viết test đỏ `tests/modules/audit/test_action.py`**

```bash
mkdir -p tests/modules/audit && : > tests/modules/audit/__init__.py
```

```python
"""Action `audit.read` phải có mặt ở CẢ code LẪN bảng control.actions.

Thiếu ở code: endpoint không khai được (`require()` ném ValueError lúc import).
Thiếu ở DB: `require()` trả 403 cho mọi người vì `action not in q.actions`, và
thông điệp nói về VAI TRÒ nên người dùng đi xin thêm quyền cho một action không
tồn tại. Khuôn y hệt `tests/modules/billing/test_action.py`.
"""

import asyncpg

from portal.core.auth.actions import ACTIONS, ALL_ACTIONS, NHAN_HANH_DONG


def test_action_co_trong_code() -> None:
    assert ACTIONS.AUDIT_READ == "audit.read"
    assert ACTIONS.AUDIT_READ in ALL_ACTIONS
    assert ACTIONS.AUDIT_READ in NHAN_HANH_DONG


async def test_action_co_trong_db(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        hang = await conn.fetchrow(
            "SELECT group_name, sort_order FROM control.actions WHERE code = 'audit.read'"
        )
        assert hang is not None, "0956_audit_action chưa chạy — hoặc chạy mà không INSERT"
        assert hang["group_name"] == "configure"
        assert hang["sort_order"] == 15, "nối CUỐI (15), không chen giữa như 0945"
        # `role_id` là `r_<md5>` sinh ra — JOIN qua `control.roles` rồi xét theo TÊN.
        ten_vai_tro = await conn.fetch(
            """SELECT r.name FROM control.role_actions ra
               JOIN control.roles r ON r.id = ra.role_id
               WHERE ra.action_code = 'audit.read'"""
        )
    assert {r["name"] for r in ten_vai_tro} == {"Quản trị"}, (
        "chỉ Quản trị được cấp audit.read (spec §2 #1) — thiếu thì không ai xem được "
        "nhật ký, thừa (Biên tập/CSKH/Người xem) là lộ «ai làm gì» cho người không có "
        "trách nhiệm giám sát"
    )
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/audit/test_action.py -v`
Expected: FAIL — `AttributeError: type object 'ACTIONS' has no attribute 'AUDIT_READ'`

- [ ] **Step 3: Thêm hằng vào `src/portal/core/auth/actions.py`**

Sau khối `BILLING_READ` (dòng 51-53) thêm:

```python
    AUDIT_READ: Final = "audit.read"
    """15 · Xem Nhật ký hoạt động của workspace (`control.audit_log`). Nằm ngoài 13
    nhóm gốc PQ_01 §3.1 như `billing.read`; thêm 2026-08-25 (`0956_audit_action`).
    Ai KHÔNG có action này thì không thấy mục nav «Nhật ký» và bị 403 ở
    `GET /audit` — phần «mọi vai trò xem việc của chính mình» (PQ_01 §3.1) là đợt 2,
    xem spec 2026-08-25-nhat-ky-hoat-dong-design.md §2 #6."""
```

Trong `NHAN_HANH_DONG`, sau dòng `ACTIONS.BILLING_READ: ...` thêm:

```python
    ACTIONS.AUDIT_READ: "Xem Nhật ký hoạt động",
```

Sửa docstring module dòng 1 `"""13 nhóm hành động của PQ_01 §3.1 — NGUỒN DUY NHẤT.` → `"""13 nhóm hành động của PQ_01 §3.1 + 2 action mọc sau (billing.read · audit.read) — NGUỒN DUY NHẤT.`

- [ ] **Step 4: Viết migration `migrations/versions/0956_audit_action.py`**

```python
"""action `audit.read` vào control.actions + role_actions

Vai trò là DỮ LIỆU (0104), không phải enum — nên thêm action là một migration, và
danh sách vai trò được cấp phải khai TRONG file này chứ không import từ portal.*
(cùng lý lẽ `0945_billing_action`).

⚠ CẤP THEO TÊN, KHÔNG THEO ID: `control.roles.id` là `r_<md5>`; `roles.name` UNIQUE
toàn cục từ `0105_roles_thoat_org`, nên câu SELECT dưới đây trả đúng 0 hoặc 1 hàng.

CHỈ CẤP CHO Quản trị — nhật ký là «ai đổi cái gì» của cả workspace; Biên tập/CSKH/
Người xem không có trách nhiệm giám sát. Đóng băng theo thời điểm 2026-08-25;
nới thêm là một migration một dòng.

`group_name = 'configure'` (CHECK của 0104 chỉ cho 'operate'|'knowledge'|'configure'):
~90% nội dung nhật ký là sự kiện nhóm configure (publish, khoá, thành viên, vai
trò) và PQ_01 §3.1 đặt «Quản trị xem toàn workspace» — người đi tìm «Xem nhật ký»
tìm ở khu quản trị. Khác 0945 (xếp `billing.read` vào `operate` vì chỉ-đọc):
ở đây chỗ NGƯỜI TÌM thắng chỗ đọc/ghi.

`sort_order = 15`: NỐI CUỐI. 0945 chen số 7 và phải đánh số lại 7 hàng qua bước
âm; ở đây 14 hàng đang là 1..14 liền, 15 là ô trống kế tiếp — không đụng hàng nào.
`tests/modules/auth/test_vai_tro.py` canh dãy `1..15` liền.

Revision ID: 0956_audit_action
Revises: 0955_hop_nhat_hai_head
"""

from alembic import op

revision = "0956_audit_action"
down_revision = "0955_hop_nhat_hai_head"
branch_labels = None
depends_on = None

_TEN_VAI_TRO_DUOC_CAP = ("Quản trị",)
"""Đóng băng theo thời điểm 2026-08-25."""

_SORT_ORDER_AUDIT_READ = 15
"""Ô trống kế tiếp sau 14 hàng hiện có (13 gốc + billing.read)."""


def upgrade() -> None:
    op.execute(
        f"""INSERT INTO control.actions (code, group_name, label_vi, label_en, sort_order)
           VALUES ('audit.read', 'configure', 'Xem Nhật ký hoạt động',
                   'View audit log', {_SORT_ORDER_AUDIT_READ})
           ON CONFLICT (code) DO NOTHING"""
    )
    for ten_vai_tro in _TEN_VAI_TRO_DUOC_CAP:
        op.execute(
            f"""INSERT INTO control.role_actions (role_id, action_code)
                SELECT id, 'audit.read' FROM control.roles WHERE name = '{ten_vai_tro}'
                ON CONFLICT DO NOTHING"""
        )


def downgrade() -> None:
    op.execute("DELETE FROM control.role_actions WHERE action_code = 'audit.read'")
    op.execute("DELETE FROM control.actions WHERE code = 'audit.read'")
```

- [ ] **Step 5: Cập nhật bốn test đếm 14 → 15**

`tests/api/test_actions.py` — hàm `test_dung_14_nhom` đổi thành:

```python
def test_dung_15_nhom():
    """13 nhóm gốc của PQ_01 §3.1 + `billing.read` (`0945_billing_action`,
    2026-08-20) + `audit.read` (`0956_audit_action`, 2026-08-25). Đếm để bắt
    việc thêm/xoá vô ý."""
    assert len(ALL_ACTIONS) == 15
```

`tests/api/test_contracts.py` — hàm `test_dem_14_truoc_khi_so`: đổi tên thành `test_dem_15_truoc_khi_so`, assert `== 15`, thêm vào cuối docstring dòng: `14 → 15 (2026-08-25, `0956_audit_action`): `audit.read`, màn Nhật ký.`

`tests/modules/enrollment/test_router.py:54-59` — docstring: `14 = 13 nhóm gốc + billing.read` → `15 = 13 nhóm gốc PQ_01 §3.1 + billing.read (0945) + audit.read (0956_audit_action, 2026-08-25 — module audit, KHÔNG M10)`; assert `len(ALL_ACTIONS) == 15`.

`tests/modules/auth/test_vai_tro.py:262-268` — đổi tên hàm thành `test_danh_muc_action_tra_15_o_co_thu_tu`, docstring thêm `+ audit.read (0956_audit_action, 2026-08-25)`, `assert len(o) == 15`, `list(range(1, 16))`.

Hai comment ở `tests/modules/auth/test_login.py:70` và `tests/modules/workspace/test_tao.py:96` chỉ là chú thích (so bằng `len(ALL_ACTIONS)`) — KHÔNG sửa.

- [ ] **Step 6: Sinh lại contracts và chạy test**

Run: `make contracts && uv run pytest tests/modules/audit tests/api tests/modules/enrollment/test_router.py tests/modules/auth/test_vai_tro.py tests/unit/test_alembic_mot_head.py -v`
Expected: PASS toàn bộ. `git diff contracts/actions.json` phải hiện đúng MỘT dòng thêm `"audit.read",` (sắp alphabet — đứng đầu danh sách).

- [ ] **Step 7: Lint + commit**

Run: `make lint`
Expected: sạch.

```bash
git add src/portal/core/auth/actions.py migrations/versions/0956_audit_action.py \
  contracts/actions.json tests/modules/audit/__init__.py tests/modules/audit/test_action.py \
  tests/api/test_actions.py tests/api/test_contracts.py \
  tests/modules/enrollment/test_router.py tests/modules/auth/test_vai_tro.py
git commit -m "feat: action audit.read — quyền xem Nhật ký hoạt động, cấp cho Quản trị"
```

---

### Task 2: Sổ mã hành động `core/nhat_ky_ma.py` + cổng AST + artefact `contracts/audit-actions.json`

**Files:**
- Create: `src/portal/core/nhat_ky_ma.py`
- Create: `tests/unit/test_nhat_ky_ma.py`
- Modify: `scripts/gen_contracts.py:23` (thêm hàm) và `:125-136` (thêm ghi file)
- Modify: `tests/api/test_contracts.py` (thêm 4 test cho artefact mới)
- Modify: `contracts/README.md:57-60` (thêm một dòng vào bảng)
- Create (sinh ra): `contracts/audit-actions.json`

**Interfaces:**
- Produces: `MA_HANH_DONG: Final[frozenset[str]]`; `scripts.gen_contracts.noi_dung_audit_actions() -> str`; file `contracts/audit-actions.json` dạng `{"actions": [...sorted]}` — FE copy byte-for-byte (plan FE Task 1).

- [ ] **Step 1: Viết test đỏ `tests/unit/test_nhat_ky_ma.py`**

```python
"""Sổ mã hành động nhật ký (`core/nhat_ky_ma.py`) phải KHỚP các literal ở điểm ghi.

Vì sao có sổ: ~50 mã là chuỗi literal rải ở 50 điểm ghi, hai lối đặt tên
(`thanh_vien.go` vs `realestate.project.update`). FE cần một danh sách để dịch ra
tiếng Việt; artefact `contracts/audit-actions.json` sinh từ sổ này. Sổ mà lệch
điểm ghi thì FE hiện mã thô — và không ai bị nhắc. Cổng này là cái nhắc.

Cổng canh LITERAL: mã truyền qua biến (`HANH_DONG` của ingest, `hanh_dong` đi qua
service) thì bỏ qua — chiều ngược (mọi mã trong sổ phải có mặt dạng `"<mã>"` ở
đâu đó trong src) đỡ cho ca đó.
"""

import ast
import re
from pathlib import Path

from portal.core.nhat_ky_ma import MA_HANH_DONG

GOC = Path(__file__).resolve().parents[2] / "src" / "portal"

_VI_TRI_HANH_DONG = {"ghi": 2, "ghi_he_thong": 1, "_nhat_ky": 2}
"""Chỉ số đối số VỊ TRÍ mang `hanh_dong`: `nhat_ky.ghi(conn, tenant_id, hanh_dong, …)`,
`nhat_ky.ghi_he_thong(conn, hanh_dong, …)`, `_nhat_ky(conn, p, hanh_dong, …)` (realestate)."""


def _ten_goi(call: ast.Call) -> str | None:
    f = call.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "nhat_ky":
        return f.attr if f.attr in _VI_TRI_HANH_DONG else None
    if isinstance(f, ast.Name) and f.id == "_nhat_ky":
        return "_nhat_ky"
    return None


def _ma_literal(call: ast.Call, ten: str) -> str | None:
    for kw in call.keywords:
        if kw.arg == "hanh_dong":
            v = kw.value
            return v.value if isinstance(v, ast.Constant) and isinstance(v.value, str) else None
    i = _VI_TRI_HANH_DONG[ten]
    if len(call.args) > i:
        a = call.args[i]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    return None


def _quet() -> list[tuple[str, str]]:
    """[(đường dẫn tương đối, mã)] cho MỌI điểm ghi có mã literal."""
    ra: list[tuple[str, str]] = []
    for tep in sorted(GOC.rglob("*.py")):
        for n in ast.walk(ast.parse(tep.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call):
                continue
            ten = _ten_goi(n)
            if ten is None:
                continue
            ma = _ma_literal(n, ten)
            if ma is not None:
                ra.append((str(tep.relative_to(GOC)), ma))
    return ra


def test_moi_literal_o_diem_ghi_deu_co_trong_so() -> None:
    thieu = sorted({(tep, ma) for tep, ma in _quet() if ma not in MA_HANH_DONG})
    assert not thieu, f"mã ở điểm ghi chưa có trong core/nhat_ky_ma.py: {thieu}"


def test_so_khong_co_ma_chet() -> None:
    """Mã trong sổ phải xuất hiện dạng literal `"<mã>"` ở đâu đó trong src — kể cả
    khi điểm ghi truyền qua biến (`HANH_DONG = "ingest.tenant_im_lang"`)."""
    van_ban = "\n".join(p.read_text(encoding="utf-8") for p in GOC.rglob("*.py"))
    chet = sorted(ma for ma in MA_HANH_DONG if f'"{ma}"' not in van_ban)
    assert not chet, f"mã trong sổ không còn điểm ghi nào: {chet}"


def test_bo_quet_con_song() -> None:
    """Đổi tên `nhat_ky`/`_nhat_ky` hay đổi thứ tự tham số là bộ quét thấy 0 điểm
    ghi và test trên xanh vĩnh viễn. Neo một sàn."""
    assert len(_quet()) >= 40, f"chỉ quét được {len(_quet())} điểm ghi — bộ quét hỏng?"


def test_dang_ma() -> None:
    """`<nhóm>.<việc>[.<việc>]` chữ thường — `split_part(hanh_dong, '.', 1)` ở repo
    audit và `NHOM_LOC` bên FE dựa vào dạng này."""
    sai = sorted(ma for ma in MA_HANH_DONG if not re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", ma))
    assert not sai, sai
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/unit/test_nhat_ky_ma.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.core.nhat_ky_ma'`

- [ ] **Step 3: Viết `src/portal/core/nhat_ky_ma.py`**

```python
"""Sổ mã hành động của `control.audit_log` — NGUỒN cho `contracts/audit-actions.json`.

Các điểm ghi (`core/nhat_ky.py` được gọi ở 9 module) vẫn dùng literal; sổ này
KHÔNG được import vào điểm ghi — nó là danh mục để FE dịch nhãn, không phải enum
cưỡng chế. `tests/unit/test_nhat_ky_ma.py` quét AST giữ hai bên khớp nhau: thêm
một điểm ghi với mã mới mà quên thêm vào đây ⇒ đỏ; xoá điểm ghi mà để mã lại ⇒ đỏ.

Thêm mã: thêm vào đúng nhóm dưới đây, chạy `make contracts`, copy artefact sang
repo FE, thêm nhãn vào `features/platform/so-hanh-dong.ts` (FE có cổng parity).
"""

from typing import Final

MA_HANH_DONG: Final[frozenset[str]] = frozenset(
    {
        # ── agent · khoá đấu nối (modules/enrollment) ──
        "agent.cap_phat",
        "agent.dat_trang_thai_khoa",
        "agent.feedback",
        "agent.phat_khoa",
        "agent.runtime_credentials",  # actor = 'agent' — hành động MÁY, màn ẩn mặc định
        "agent.thu_hoi_khoa",
        "agent.xoay_bi_mat",
        # ── agent_config (modules/config) ──
        "agent_config.publish",
        "agent_config.rollback",
        # ── billing ──
        "billing.price_version_kich_hoat",
        # ── ingest · cổng nạp ──
        "ingest.tenant_im_lang",  # job đối soát, actor = '' — cảnh báo cho NGƯỜI đọc
        "ingest.token_tao",
        "ingest.token_xoa",
        # ── kb ──
        "kb.delete",
        "kb.upload",
        # ── linh_vuc ──
        "linh_vuc.bat",
        "linh_vuc.tat",
        # ── owner (cli/seed_owner) ──
        "owner.bootstrap",
        # ── realestate ──
        "realestate.document.approve",
        "realestate.document.create",
        "realestate.document.delete",
        "realestate.document.update",
        "realestate.media.create",
        "realestate.media.delete",
        "realestate.media.draft_caption",
        "realestate.media.update",
        "realestate.project.create",
        "realestate.project.delete",
        "realestate.project.update",
        "realestate.unit.create",
        "realestate.unit.delete",
        "realestate.unit.update",
        "realestate.upload",
        "realestate.zone.create",
        "realestate.zone.delete",
        # ── role (modules/auth/quan_tri_vai_tro) ──
        "role.sua",
        "role.tao",
        "role.xoa",
        # ── thanh_vien (modules/auth/thanh_vien) ──
        "thanh_vien.doi_vai_tro",
        "thanh_vien.go",
        "thanh_vien.gui_lai_moi",
        "thanh_vien.moi",
        "thanh_vien.moi_lai",
        "thanh_vien.thu_hoi_moi",
        # ── user (modules/auth) — phần lớn ghi_he_thong, tenant_id NULL ──
        "user.dang_ky",
        "user.dang_ky_google",
        "user.dang_nhap_google",
        "user.doi_mat_khau",
        "user.lien_ket_google",
        "user.moi_lai",
        "user.nhan_moi",
        "user.nhan_moi_ws",
        "user.sua",
        "user.sua_ho_so",
        "user.tao",
        "user.tao_tu_loi_moi",
        "user.xoa_loi_moi",
        # ── workspace ──
        "workspace.doi_ten",
        "workspace.tao",
        "workspace.xoa",
    }
)
```

- [ ] **Step 4: Chạy test; sửa sổ theo báo cáo của cổng**

Run: `uv run pytest tests/unit/test_nhat_ky_ma.py -v`
Expected: hai khả năng — PASS 4/4; hoặc `test_moi_literal_o_diem_ghi_deu_co_trong_so` in ra danh sách `(tệp, mã)` chưa có trong sổ / `test_so_khong_co_ma_chet` in ra mã không còn điểm ghi. Danh sách trên được gom bằng grep ngày 2026-08-25 nên có thể lệch vài mã: **thêm đúng mã cổng báo thiếu vào đúng nhóm, xoá mã cổng báo chết**, chạy lại tới khi 4/4 PASS. KHÔNG nới `MIEN_TRU` hay hạ sàn `>= 40`.

- [ ] **Step 5: Mở rộng `scripts/gen_contracts.py`**

Thêm import sau dòng `from portal.core.auth.actions import ALL_ACTIONS`:

```python
from portal.core.nhat_ky_ma import MA_HANH_DONG
```

Thêm hàm ngay sau `noi_dung_actions()`:

```python
def noi_dung_audit_actions() -> str:
    """JSON sổ mã hành động của `control.audit_log` — FE dịch nhãn từ đây
    (`features/platform/so-hanh-dong.ts`, cổng `tests/audit-actions-parity.test.ts`).
    Sắp alphabet, cùng lý do `actions.json`."""
    return json.dumps({"actions": sorted(MA_HANH_DONG)}, indent=2, ensure_ascii=False) + "\n"
```

Trong `main()`, sau khối ghi `actions.json` thêm:

```python
    dich_audit = CONTRACTS / "audit-actions.json"
    dich_audit.write_text(noi_dung_audit_actions(), encoding="utf-8")
    print(f"đã ghi {dich_audit}")
```

(giữ đúng cách in của các khối trước đó trong `main()` — nếu chúng không `print`, bỏ dòng `print`).

- [ ] **Step 6: Thêm 4 test vào `tests/api/test_contracts.py`**

Thêm import: `from scripts.gen_contracts import noi_dung_actions, noi_dung_audit_actions` (thay dòng import cũ) và `from portal.core.nhat_ky_ma import MA_HANH_DONG`. Thêm hằng `AUDIT_JSON = CONTRACTS / "audit-actions.json"` cạnh `ACTIONS_JSON`. Thêm cuối file (trước khối `tools.json`):

```python
# ─── audit-actions.json — sổ mã hành động nhật ký, cùng cơ chế với actions.json ──


def test_audit_artefact_ton_tai():
    assert AUDIT_JSON.exists(), "thiếu contracts/audit-actions.json — chạy `make contracts`"


def test_audit_artefact_khop_nguon():
    trong_file = set(json.loads(AUDIT_JSON.read_text(encoding="utf-8"))["actions"])
    assert trong_file == set(MA_HANH_DONG)


def test_audit_artefact_dung_byte_ma_script_sinh_ra():
    assert AUDIT_JSON.read_text(encoding="utf-8") == noi_dung_audit_actions()


def test_audit_dem_truoc_khi_so():
    """Sàn 40 chứ không phải con số chính xác: sổ này mọc theo điểm ghi (khác
    `actions.json` cố định 15). Đếm để bắt artefact rỗng."""
    assert len(json.loads(AUDIT_JSON.read_text(encoding="utf-8"))["actions"]) >= 40
```

- [ ] **Step 7: Sinh artefact, thêm dòng README, chạy test**

Run: `make contracts && uv run pytest tests/unit/test_nhat_ky_ma.py tests/api/test_contracts.py -v`
Expected: PASS; file `contracts/audit-actions.json` xuất hiện.

Trong `contracts/README.md`, bảng «Có gì trong đây» thêm dòng sau `actions.json`:

```markdown
| `audit-actions.json` | `src/portal/core/nhat_ky_ma.py` (sổ mã hành động nhật ký) | `tests/audit-actions-parity.test.ts` của repo FE — mọi mã phải có nhãn tiếng Việt |
```

- [ ] **Step 8: Lint + commit**

Run: `make lint`

```bash
git add src/portal/core/nhat_ky_ma.py tests/unit/test_nhat_ky_ma.py scripts/gen_contracts.py \
  tests/api/test_contracts.py contracts/audit-actions.json contracts/README.md
git commit -m "feat: sổ mã hành động nhật ký + artefact contracts/audit-actions.json (cổng AST)"
```

---

### Task 3: `modules/audit/contracts.py` — model response, hằng phân trang, con trỏ keyset

**Files:**
- Create: `src/portal/modules/audit/__init__.py` (rỗng), `src/portal/modules/audit/contracts.py`
- Create: `tests/unit/test_audit_con_tro.py`

**Interfaces:**
- Produces: `TRANG_MAC_DINH = 50`, `GIOI_HAN_TRANG = 200`, `SO_NHOM_TOI_DA = 10`, `MA_ACTOR_MAY = "agent"`, `class LoiConTro(ValueError)`, `ma_con_tro(luc: datetime, id_: int) -> str`, `doc_con_tro(con_tro: str) -> tuple[datetime, int]`, `class DongNhatKyOut(BaseModel)`, `class TrangNhatKyOut(BaseModel)`.

- [ ] **Step 1: Viết test đỏ `tests/unit/test_audit_con_tro.py`**

```python
"""Con trỏ keyset của `GET /audit`: đục, tròn hai chiều, và mọi thứ không đúng
dạng là LỖI chứ không phải «trang đầu» (trả trang đầu âm thầm làm FE cuộn vô tận)."""

from datetime import UTC, datetime, timedelta

import pytest

from portal.modules.audit.contracts import LoiConTro, doc_con_tro, ma_con_tro

LUC = datetime(2026, 8, 25, 3, 12, 44, 120931, tzinfo=UTC)


def test_tron_hai_chieu() -> None:
    assert doc_con_tro(ma_con_tro(LUC, 412)) == (LUC, 412)


def test_giu_microsecond_va_mui_gio() -> None:
    """`luc` là timestamptz microsecond; mất một trong hai là keyset `(luc, id) <`
    lệch một hàng ở biên trang."""
    luc, _ = doc_con_tro(ma_con_tro(LUC + timedelta(microseconds=7), 1))
    assert luc == LUC + timedelta(microseconds=7)
    assert luc.tzinfo is not None


def test_duc_khong_doc_duoc_bang_mat() -> None:
    assert "2026" not in ma_con_tro(LUC, 412)
    assert "=" not in ma_con_tro(LUC, 412)


@pytest.mark.parametrize("rac", ["", "abc", "NDEy", "MjAyNi0wOC0yNXw0MTI", "bm90fGRhdGV8MQ"])
def test_rac_nem_loi_con_tro(rac: str) -> None:
    # "NDEy" = base64("412") — dạng CŨ chỉ có id; "MjAyNi0wOC0yNXw0MTI" = "2026-08-25|412"
    # thiếu múi giờ. Cả hai phải bị từ chối, không «đoán».
    with pytest.raises(LoiConTro):
        doc_con_tro(rac)
```

- [ ] **Step 2: Chạy để thấy đỏ**

Run: `uv run pytest tests/unit/test_audit_con_tro.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.modules.audit'`

- [ ] **Step 3: Viết `src/portal/modules/audit/contracts.py`**

```bash
mkdir -p src/portal/modules/audit && : > src/portal/modules/audit/__init__.py
```

```python
"""Hợp đồng HTTP của `GET /audit` — màn «Nhật ký» đọc `control.audit_log`.

Spec: docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md §4. Tài liệu
bàn giao FE: docs/contracts/audit.md. Đổi field ở đây mà không sửa hai chỗ đó là
để tài liệu nói dối.

CON TRỎ MÃ HOÁ CẢ `(luc, id)`, không chỉ `id` như realestate: `luc` là `now()` =
thời điểm BẮT ĐẦU giao dịch, nên hai giao dịch chồng nhau có thể cho `id` lớn
hơn mà `luc` nhỏ hơn. Sắp `(luc DESC, id DESC)` và keyset trên cả cặp thì trang
sau vẫn xác định; keyset theo `id` một mình thì sót hàng ở biên.

Sao chép khuôn `ma_con_tro`/`doc_con_tro`/`LoiConTro` của `realestate/contracts.py`
thay vì import: Luật 3 (`tests/test_module_boundaries.py`) cấm module này đọc ruột
module kia.
"""

import base64
import binascii
from datetime import datetime
from typing import Any

from pydantic import BaseModel

TRANG_MAC_DINH = 50
GIOI_HAN_TRANG = 200
"""Trần `limit`. Cũng là số hàng tối đa router xin repo — xem `_xin_du_phong`."""

SO_NHOM_TOI_DA = 10
"""`?nhom=a,b,c` — tối đa 10 tiền tố. Sổ hiện có 12 tiền tố; FE gộp thành 9 nhóm
lọc, nhóm lớn nhất 4 tiền tố. 10 đủ rộng và chặn một chuỗi 10 KB đi vào `ANY()`."""

MA_ACTOR_MAY = "agent"
"""`actor` mà `enrollment/service.py` ghi cho `agent.runtime_credentials` (agent
bootstrap lấy credential). Là hành động MÁY, chiếm ~38% số dòng trên dev — màn ẩn
mặc định (`?may=false`). `''` (job hệ thống) và `platform_admin` KHÔNG thuộc nhóm
này: chúng là việc cho người đọc."""


class LoiConTro(ValueError):
    """Cursor không đúng dạng — router dịch thành 400 `CURSOR_KHONG_HOP_LE`."""


def ma_con_tro(luc: datetime, id_: int) -> str:
    """`(luc, id)` của hàng CUỐI trang → chuỗi đục (base64url, bỏ đệm).

    Đục vì cursor là chi tiết cài đặt: để đọc được là mời FE tự chế, và ngày
    khoá sắp xếp đổi thì cách dùng đó gãy âm thầm. `isoformat()` giữ microsecond
    + múi giờ — cả hai đều cần cho phép so `(luc, id) <` ở repo."""
    tho = f"{luc.isoformat()}|{id_}"
    return base64.urlsafe_b64encode(tho.encode()).decode().rstrip("=")


def doc_con_tro(con_tro: str) -> tuple[datetime, int]:
    """Ngược của `ma_con_tro`. MỌI thứ không đúng dạng → `LoiConTro` — kể cả cursor
    dạng cũ chỉ có id, hay `luc` thiếu múi giờ (so với timestamptz sẽ lấy múi giờ
    phiên DB, tức kết quả tuỳ máy)."""
    try:
        tho = base64.urlsafe_b64decode(con_tro + "==").decode()
        luc_s, id_s = tho.rsplit("|", 1)
        luc = datetime.fromisoformat(luc_s)
        if luc.tzinfo is None:
            raise ValueError("luc thiếu múi giờ")
        return luc, int(id_s)
    except (ValueError, binascii.Error, UnicodeDecodeError) as e:
        raise LoiConTro("Con trỏ phân trang không hợp lệ") from e


class DongNhatKyOut(BaseModel):
    id: int
    luc: datetime
    hanhDong: str
    actorId: str
    """`control.audit_log.actor` NGUYÊN VĂN: `u_<id>`, `'agent'`, `'platform_admin'`
    hoặc `''`. FE dịch ba giá trị đặc biệt (spec §4)."""
    actorTen: str | None
    actorEmail: str | None
    """`None` khi `actor` không khớp `control.users` — người đã bị gỡ (0201 cố ý
    không FK), hoặc actor máy/hệ thống."""
    chiTiet: dict[str, Any]
    """jsonb NGUYÊN VĂN. Nhật ký là bằng chứng — đường đọc không «làm đẹp» nó."""


class TrangNhatKyOut(BaseModel):
    items: list[DongNhatKyOut]
    nextCursor: str | None = None
```

- [ ] **Step 4: Chạy test**

Run: `uv run pytest tests/unit/test_audit_con_tro.py -v`
Expected: PASS 8/8 (4 hàm, parametrize 5).

- [ ] **Step 5: Lint + commit**

Run: `make lint`

```bash
git add src/portal/modules/audit/__init__.py src/portal/modules/audit/contracts.py tests/unit/test_audit_con_tro.py
git commit -m "feat(audit): contracts + con trỏ keyset (luc, id) cho GET /audit"
```

---

### Task 4: `repo.py` + `router.py` — quyền, cách ly, ẩn máy, join người

**Files:**
- Create: `src/portal/modules/audit/repo.py`, `src/portal/modules/audit/router.py`
- Create: `tests/modules/audit/conftest.py`, `tests/modules/audit/test_router.py`

**Interfaces:**
- Consumes: `ACTIONS.AUDIT_READ` (Task 1); `contracts.*` (Task 3).
- Produces: `repo.liet_ke(conn, *, limit, con_tro, nhom, tu, den, may) -> list[asyncpg.Record]` (các cột `id, luc, hanh_dong, actor, chi_tiet, actor_ten, actor_email`); route `GET /api/v1/audit`. Task 5 chỉ THÊM test cho `nhom`/`from`/`to`/`cursor` — chữ ký không đổi.

- [ ] **Step 1: Viết `tests/modules/audit/conftest.py`**

```python
"""Fixture module audit — cùng nếp tests/modules/billing/conftest.py.

KHÔNG mock `tenant_conn()`: nó là seam của cách ly. Dữ liệu chèn TRỰC TIẾP vào
`control.audit_log` bằng `pool` (migrator) với `luc` TƯỜNG MINH — mọi test phân
trang/khoảng ngày neo vào các mốc dưới đây, đừng để `DEFAULT now()`.

Bộ hàng được dựng để MỖI test có đúng thứ nó cần trong CÙNG một fixture:
- tenant A (`audw`): 10 hàng, trong đó 1 hàng máy (`agent`), 1 hàng hệ thống
  (`''`), 1 hàng actor không còn trong `users`, 3 hàng CÙNG `luc`, 1 hàng lúc
  23:30 giờ VN (= 16:30 UTC) để kiểm múi giờ.
- tenant B (`audx`): 1 hàng — không bao giờ được lộ.
- `tenant_id NULL`: 1 hàng — hàng hệ thống, màn theo workspace không bày (spec §2 #6).
"""

from datetime import UTC, datetime, timedelta
import json

import asyncpg
import pytest

TENANT = "audw"
TENANT_KHAC = "audx"
USER_QT = "u_aud_qt"
USER_XEM = "u_aud_xem"
USER_DA_XOA = "u_aud_da_xoa"  # KHÔNG chèn vào users — actor đã bị gỡ
EMAIL_QT = "aud.qt@noblex.vn"
EMAIL_XEM = "aud.xem@noblex.vn"
MAT_KHAU = "MatKhauDaiVaManh!1"

MOC = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
CUNG_LUC = MOC + timedelta(hours=7)  # 16:00Z = 23:00 VN 20/08 — còn TRONG ngày 20 (VN)
MUON_VN = datetime(2026, 8, 22, 16, 30, tzinfo=UTC)  # 23:30 22/08 giờ VN

# (tenant, hanh_dong, actor, chi_tiet, luc) — thứ tự chèn KHÔNG phải thứ tự luc,
# cố ý: id tăng theo chèn, luc thì không, để keyset theo `id` một mình sẽ lộ sai.
HANG = [
    (TENANT, "realestate.project.update", USER_QT, {"project_code": "NT2", "truong": ["name"]}, MOC),
    (TENANT, "role.sua", USER_QT, {"role_id": "r_x"}, MUON_VN),
    (TENANT, "thanh_vien.moi", USER_QT, {"email": "moi@noblex.vn"}, MOC + timedelta(hours=1)),
    (TENANT, "user.nhan_moi_ws", USER_XEM, {}, MOC + timedelta(hours=2)),
    (TENANT, "agent.runtime_credentials", "agent", {"agent_key_id": 1}, MOC + timedelta(hours=3)),
    (TENANT, "ingest.tenant_im_lang", "", {"gio_im_lang": 26}, MOC + timedelta(hours=4)),
    (TENANT, "kb.upload", USER_DA_XOA, {"ten_file": "a.pdf"}, MOC + timedelta(hours=5)),
    (TENANT, "agent_config.publish", USER_QT, {"version": 3}, CUNG_LUC),
    (TENANT, "agent_config.publish", USER_QT, {"version": 4}, CUNG_LUC),
    (TENANT, "agent_config.publish", USER_QT, {"version": 5}, CUNG_LUC),
    (TENANT_KHAC, "kb.delete", USER_QT, {"ten_file": "b.pdf"}, MOC + timedelta(hours=6)),
    (None, "user.doi_mat_khau", USER_QT, {}, MOC + timedelta(hours=7)),
]
SO_HANG_A = 10
SO_HANG_A_KHONG_MAY = 9


@pytest.fixture
async def workspace_audit(pool: asyncpg.Pool):
    """Hai user (Quản trị · Người xem) cùng workspace A; tenant B chỉ để chứa
    hàng không được lộ. Trả dict id các hàng theo `hanh_dong`+`version` để
    test đối chiếu."""
    from portal.core.auth.password import bam

    async with pool.acquire() as conn, conn.transaction():
        for uid, ten, email in ((USER_QT, "Quản Trị Viên", EMAIL_QT), (USER_XEM, "Người Xem", EMAIL_XEM)):
            await conn.execute(
                "INSERT INTO control.users (id, name, email, password_hash) VALUES ($1, $2, $3, $4)",
                uid,
                ten,
                email,
                bam(MAT_KHAU),
            )
        for t, ten in ((TENANT, "Audit WS"), (TENANT_KHAC, "Audit Khac")):
            await conn.execute(
                "INSERT INTO control.tenants (id, name, created_by) VALUES ($1, $2, $3)", t, ten, USER_QT
            )
        r_qt = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Quản trị'")
        r_xem = await conn.fetchval("SELECT id FROM control.roles WHERE name = 'Người xem'")
        assert r_qt and r_xem, "0104/0105 chưa seed vai trò — fixture không dựng thay được"
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)", USER_QT, TENANT, r_qt
        )
        await conn.execute(
            "INSERT INTO control.memberships (user_id, tenant_id, role_id) VALUES ($1, $2, $3)",
            USER_XEM,
            TENANT,
            r_xem,
        )
        ids: dict[str, int] = {}
        for t, hd, actor, ct, luc in HANG:
            id_ = await conn.fetchval(
                "INSERT INTO control.audit_log (tenant_id, hanh_dong, actor, chi_tiet, luc) "
                "VALUES ($1, $2, $3, $4::jsonb, $5) RETURNING id",
                t,
                hd,
                actor,
                json.dumps(ct, ensure_ascii=False),
                luc,
            )
            ids[f"{hd}:{ct.get('version', '')}"] = id_
    yield ids
    async with pool.acquire() as conn, conn.transaction():
        # Hàng có tenant đi theo `ON DELETE CASCADE` của tenants; hàng NULL và
        # hàng login (nếu có) dọn theo actor.
        await conn.execute("DELETE FROM control.audit_log WHERE actor = ANY($1::text[])", [USER_QT, USER_XEM])
        await conn.execute("DELETE FROM control.tenants WHERE id = ANY($1::text[])", [TENANT, TENANT_KHAC])
        await conn.execute("DELETE FROM control.users WHERE id = ANY($1::text[])", [USER_QT, USER_XEM])


async def dang_nhap(client, email: str) -> None:
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": MAT_KHAU})
    assert r.status_code == 200, r.text
    r2 = await client.post("/api/v1/me/workspace", json={"workspaceId": TENANT})
    assert r2.status_code == 200, r2.text
```

⚠ Kiểm trước khi chạy: cột `control.users.password_hash` NOT NULL và hàm `portal.core.auth.password.bam` (billing conftest dùng đúng thế). Nếu `POST /api/v1/me/workspace` ở repo có tên khác, tra `tests/modules/billing/test_usage_theo_ngay.py::_dang_nhap` — copy y nguyên.

- [ ] **Step 2: Viết test đỏ `tests/modules/audit/test_router.py` (phần 1)**

```python
"""`GET /api/v1/audit` — quyền · cách ly · ẩn máy · join người.

Bài quan trọng nhất: `test_cach_ly_tenant_va_hang_he_thong` — hàng tenant B và
hàng `tenant_id NULL` KHÔNG BAO GIỜ lộ. `control.*` không có RLS đỡ phía sau; vị
từ tenant nằm ở câu SQL và đây là bài duy nhất canh nó.
"""

from tests.modules.audit.conftest import (
    EMAIL_QT,
    EMAIL_XEM,
    SO_HANG_A,
    SO_HANG_A_KHONG_MAY,
    USER_DA_XOA,
    USER_QT,
    dang_nhap,
)

DUONG = "/api/v1/audit"


async def test_401_khong_phien(app_client, workspace_audit) -> None:
    r = await app_client.get(DUONG)
    assert r.status_code == 401, r.text


async def test_403_nguoi_xem_khong_co_audit_read(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_XEM)
    r = await app_client.get(DUONG)
    assert r.status_code == 403, r.text
    assert "Xem Nhật ký hoạt động" in r.json()["error"]["message"], "403 phải nói LÝ DO bằng nhãn action"


async def test_cach_ly_tenant_va_hang_he_thong(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    r = await app_client.get(DUONG, params={"may": "true"})
    assert r.status_code == 200, r.text
    d = r.json()
    hanh_dong = [x["hanhDong"] for x in d["items"]]
    assert "kb.delete" not in hanh_dong, "hàng của tenant B lộ — vị từ tenant hỏng"
    assert "user.doi_mat_khau" not in hanh_dong, "hàng tenant_id NULL lộ (spec §2 #6)"
    assert len(d["items"]) == SO_HANG_A
    assert d["nextCursor"] is None


async def test_moi_nhat_truoc(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG)).json()
    luc = [x["luc"] for x in d["items"]]
    assert luc == sorted(luc, reverse=True)
    assert d["items"][0]["hanhDong"] == "role.sua", "hàng 22/08 phải đứng đầu dù id chèn nhỏ"


async def test_mac_dinh_an_hanh_dong_may(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG)).json()
    assert len(d["items"]) == SO_HANG_A_KHONG_MAY
    assert all(x["actorId"] != "agent" for x in d["items"])
    # Hàng hệ thống (`''`) và các hàng người VẪN hiện — chỉ `agent` bị ẩn.
    assert "ingest.tenant_im_lang" in [x["hanhDong"] for x in d["items"]]


async def test_may_true_hien_hanh_dong_may(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"may": "true"})).json()
    assert len(d["items"]) == SO_HANG_A
    may = next(x for x in d["items"] if x["actorId"] == "agent")
    assert may["hanhDong"] == "agent.runtime_credentials"
    assert may["actorTen"] is None and may["actorEmail"] is None


async def test_join_nguoi(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG)).json()
    theo = {x["hanhDong"]: x for x in d["items"]}
    assert theo["thanh_vien.moi"]["actorId"] == USER_QT
    assert theo["thanh_vien.moi"]["actorTen"] == "Quản Trị Viên"
    assert theo["thanh_vien.moi"]["actorEmail"] == EMAIL_QT
    # Người đã bị gỡ: actorId giữ NGUYÊN, tên/email null — không được lọc bỏ hàng.
    assert theo["kb.upload"]["actorId"] == USER_DA_XOA
    assert theo["kb.upload"]["actorTen"] is None
    assert theo["ingest.tenant_im_lang"]["actorId"] == ""


async def test_chi_tiet_nguyen_ven(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG)).json()
    hang = next(x for x in d["items"] if x["hanhDong"] == "realestate.project.update")
    assert hang["chiTiet"] == {"project_code": "NT2", "truong": ["name"]}
    assert isinstance(hang["id"], int)
    assert hang["luc"].endswith("+00:00") or hang["luc"].endswith("Z")
```

- [ ] **Step 3: Chạy để thấy đỏ**

Run: `uv run pytest tests/modules/audit/test_router.py -v`
Expected: `test_401_khong_phien` có thể PASS sẵn (route chưa có → FastAPI 404, KHÔNG phải 401 — nếu thấy 404 thì đó là đỏ đúng); các bài còn lại FAIL vì 404.

- [ ] **Step 4: Viết `src/portal/modules/audit/repo.py`**

```python
"""SQL của `GET /audit` — một câu SELECT, dựng vị từ theo tham số có mặt.

VỊ TỪ TENANT LÀ LITERAL trong chuỗi (`a.tenant_id = portal.current_tenant()`),
không phải tham số: `control.audit_log` KHÔNG có RLS, và `tenant_conn()` chỉ đặt
`app.tenant_id` — câu SQL nào quên vị từ này là đọc toàn nền tảng không lỗi nào.
Cùng cách `modules/ingest/jobs.py` đọc bảng này.

LEFT JOIN `users`, KHÔNG INNER: 0201 cố ý không FK `actor → users` để nhật ký sống
lâu hơn tài khoản. INNER JOIN là xoá dấu vết của người đã bị gỡ — đúng thứ nhật ký
tồn tại để giữ.
"""

from datetime import date, datetime

import asyncpg

from portal.modules.audit.contracts import MA_ACTOR_MAY

MUI_GIO = "Asia/Ho_Chi_Minh"
"""`from`/`to` là NGÀY theo giờ người dùng (cùng lý lẽ `_NGAY` của `ops/repo.py`):
một hàng 23:30 giờ VN không được rơi sang ngày UTC hôm sau."""

_COT = (
    "a.id, a.luc, a.hanh_dong, a.actor, a.chi_tiet, u.name AS actor_ten, u.email AS actor_email"
)


async def liet_ke(
    conn: asyncpg.Connection,
    *,
    limit: int,
    con_tro: tuple[datetime, int] | None,
    nhom: list[str] | None,
    tu: date | None,
    den: date | None,
    may: bool,
) -> list[asyncpg.Record]:
    """`limit` hàng mới nhất trước, sau con trỏ (nếu có). Router xin `limit + 1`
    để biết còn trang sau — xem `router._trang`."""
    dk = ["a.tenant_id = portal.current_tenant()"]
    tham_so: list[object] = []

    def them(gia_tri: object) -> str:
        tham_so.append(gia_tri)
        return f"${len(tham_so)}"

    if not may:
        dk.append(f"a.actor <> {them(MA_ACTOR_MAY)}")
    if nhom:
        dk.append(f"split_part(a.hanh_dong, '.', 1) = ANY({them(nhom)}::text[])")
    if tu is not None:
        dk.append(f"a.luc >= ({them(tu)}::date)::timestamp AT TIME ZONE '{MUI_GIO}'")
    if den is not None:
        dk.append(f"a.luc < ({them(den)}::date)::timestamp AT TIME ZONE '{MUI_GIO}'")
    if con_tro is not None:
        luc, id_ = con_tro
        dk.append(f"(a.luc, a.id) < ({them(luc)}::timestamptz, {them(id_)}::bigint)")

    sql = f"""
        SELECT {_COT}
          FROM control.audit_log a
          LEFT JOIN control.users u ON u.id = a.actor
         WHERE {" AND ".join(dk)}
         ORDER BY a.luc DESC, a.id DESC
         LIMIT {them(limit)}
    """
    return await conn.fetch(sql, *tham_so)
```

- [ ] **Step 5: Viết `src/portal/modules/audit/router.py`**

```python
"""`GET /audit` — màn «Nhật ký» đọc `control.audit_log`. Một route, chỉ đọc.

Quyền: `ACTIONS.AUDIT_READ` (0956, cấp cho «Quản trị»). Phạm vi = workspace của
`Principal`; hàng `tenant_id IS NULL` (đăng ký, đổi mật khẩu…) không thuộc
workspace nào nên không bao giờ lọt — spec §2 #6.

KHÔNG có `/api/v1` ở đây — `create_app()` thêm tiền tố lúc include_router.
"""

import json
import re
from datetime import date

import asyncpg
from fastapi import APIRouter, Depends, Query

from portal.api import loi
from portal.core.auth.actions import ACTIONS
from portal.core.auth.principal import Principal
from portal.core.auth.require import lay_pool, require
from portal.core.db.session import tenant_conn
from portal.modules.audit import repo
from portal.modules.audit.contracts import (
    GIOI_HAN_TRANG,
    SO_NHOM_TOI_DA,
    TRANG_MAC_DINH,
    DongNhatKyOut,
    LoiConTro,
    TrangNhatKyOut,
    doc_con_tro,
    ma_con_tro,
)

ROUTER = APIRouter(tags=["audit"])

_LIMIT_Q = Query(TRANG_MAC_DINH, ge=1, le=GIOI_HAN_TRANG)
"""Singleton mức module — `Query(...)` trong default là B008 (ruff)."""

_NHOM_RE = re.compile(r"^[a-z_]{1,32}$")


def _con_tro_khong_hop_le() -> loi.LoiPortal:
    return loi.LoiPortal("CURSOR_KHONG_HOP_LE", 400, "Con trỏ phân trang không hợp lệ")


def _tach_nhom(nhom: str | None) -> list[str] | None:
    """`?nhom=thanh_vien,user` → `["thanh_vien", "user"]`. Rỗng/None → None (không lọc)."""
    if not nhom:
        return None
    ds = [x.strip() for x in nhom.split(",") if x.strip()]
    if not ds or len(ds) > SO_NHOM_TOI_DA or any(not _NHOM_RE.fullmatch(x) for x in ds):
        raise loi.LoiPortal(
            "NHOM_KHONG_HOP_LE", 422, f"`nhom` là tối đa {SO_NHOM_TOI_DA} tiền tố [a-z_], cách nhau dấu phẩy"
        )
    return ds


def _xin_du_phong(lim: int) -> int:
    """Xin `lim + 1` để biết còn trang sau — trừ khi đã chạm trần."""
    return min(lim + 1, GIOI_HAN_TRANG)


def _trang(hang: list[asyncpg.Record], lim: int, xin: int) -> tuple[list[asyncpg.Record], str | None]:
    if len(hang) >= xin:
        cuoi = hang[lim - 1]
        return list(hang[:lim]), ma_con_tro(cuoi["luc"], cuoi["id"])
    return list(hang), None


def _ra_dong(r: asyncpg.Record) -> DongNhatKyOut:
    return DongNhatKyOut(
        id=r["id"],
        luc=r["luc"],
        hanhDong=r["hanh_dong"],
        actorId=r["actor"],
        actorTen=r["actor_ten"],
        actorEmail=r["actor_email"],
        chiTiet=json.loads(r["chi_tiet"]),
    )


@ROUTER.get("/audit", response_model=TrangNhatKyOut)
async def liet_ke_nhat_ky(
    limit: int = _LIMIT_Q,
    cursor: str | None = None,
    nhom: str | None = None,
    tu: date | None = Query(None, alias="from"),
    den: date | None = Query(None, alias="to"),
    may: bool = False,
    p: Principal = require(ACTIONS.AUDIT_READ),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> TrangNhatKyOut:
    """Trang nhật ký của workspace hiện tại, mới nhất trước.

    `to` là cận TRÊN MỞ (`< to`) — cùng nghĩa `_khoang()` của billing; FE gửi
    `ngày chọn + 1` cho ô «đến hết ngày». KHÔNG có khoảng mặc định: thiếu cả hai
    là «mới nhất trước», cuộn tới đâu tuỳ người xem.
    `may=false` (mặc định) ẩn `actor = 'agent'` — xem `contracts.MA_ACTOR_MAY`.
    """
    if tu is not None and den is not None and tu >= den:
        raise loi.LoiPortal("KHOANG_KHONG_HOP_LE", 422, "`from` phải trước `to`")
    ds_nhom = _tach_nhom(nhom)
    try:
        con_tro = doc_con_tro(cursor) if cursor else None
    except LoiConTro as e:
        raise _con_tro_khong_hop_le() from e

    xin = _xin_du_phong(limit)
    async with tenant_conn(pool, p.tenant_id) as conn:
        hang = await repo.liet_ke(conn, limit=xin, con_tro=con_tro, nhom=ds_nhom, tu=tu, den=den, may=may)
    items, ke_tiep = _trang(hang, limit, xin)
    return TrangNhatKyOut(items=[_ra_dong(r) for r in items], nextCursor=ke_tiep)
```

⚠ `require(...)` kiểm `action in ALL_ACTIONS` lúc import — Task 1 phải xong trước. ⚠ Nếu `tests/test_module_boundaries.py` có danh sách module phải khai, thêm `audit` theo đúng cách các module khác (đọc lỗi của test đó nếu đỏ).

- [ ] **Step 6: Chạy test**

Run: `uv run pytest tests/modules/audit -v`
Expected: PASS 8 bài router + 2 bài action. Nếu `test_403_nguoi_xem_khong_co_audit_read` đỏ vì message: tra `api/loi.py` xem 403 của `require()` ghép nhãn từ `NHAN_HANH_DONG` thế nào và sửa assert theo CHUỖI THẬT (không đổi code lỗi).

- [ ] **Step 7: Cách ly + boundaries + lint, rồi commit**

Run: `uv run pytest tests/isolation tests/test_module_boundaries.py -v && make lint`
Expected: PASS, lint sạch.

```bash
git add src/portal/modules/audit/repo.py src/portal/modules/audit/router.py \
  tests/modules/audit/conftest.py tests/modules/audit/test_router.py
git commit -m "feat(audit): GET /audit — đọc nhật ký workspace, ẩn hành động máy, join người"
```

---

### Task 5: Lọc `nhom` · khoảng ngày theo giờ VN · phân trang keyset

**Files:**
- Modify: `tests/modules/audit/test_router.py` (thêm phần 2)
- (Không sửa code nếu Task 4 đúng — task này là CỔNG cho phần logic đã viết; sửa `repo.py`/`router.py` chỉ khi test chỉ ra sai.)

- [ ] **Step 1: Thêm test vào cuối `tests/modules/audit/test_router.py`**

```python
# ─── Lọc nhóm ────────────────────────────────────────────────────────────────


async def test_loc_mot_nhom(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"nhom": "realestate"})).json()
    assert [x["hanhDong"] for x in d["items"]] == ["realestate.project.update"]


async def test_loc_nhieu_nhom(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"nhom": "thanh_vien,user"})).json()
    assert sorted(x["hanhDong"] for x in d["items"]) == ["thanh_vien.moi", "user.nhan_moi_ws"]


async def test_nhom_khop_tien_to_chinh_xac(app_client, workspace_audit) -> None:
    """`agent` KHÔNG khớp `agent_config` — split_part, không LIKE."""
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"nhom": "agent", "may": "true"})).json()
    assert [x["hanhDong"] for x in d["items"]] == ["agent.runtime_credentials"]


async def test_nhom_sai_dang_422(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    for xau in ("Thanh_Vien", "a;b", ",".join(["a"] * 11), "x" * 33):
        r = await app_client.get(DUONG, params={"nhom": xau})
        assert r.status_code == 422, (xau, r.text)
        assert r.json()["error"]["code"] == "NHOM_KHONG_HOP_LE"


# ─── Khoảng ngày theo giờ VN ─────────────────────────────────────────────────


async def test_khoang_ngay_theo_gio_vn(app_client, workspace_audit) -> None:
    """Hàng 16:30 UTC 22/08 = 23:30 giờ VN 22/08 ⇒ thuộc ngày 22 (VN), KHÔNG
    phải 22 theo UTC-rồi-lệch. `to` là cận trên MỞ."""
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"from": "2026-08-22", "to": "2026-08-23"})).json()
    assert [x["hanhDong"] for x in d["items"]] == ["role.sua"]
    d2 = (await app_client.get(DUONG, params={"from": "2026-08-23", "to": "2026-08-24"})).json()
    assert d2["items"] == []
    # Ngày 20/08 VN = [19/08 17:00Z, 20/08 17:00Z): các hàng 09Z..16Z ⇒ 8 hàng không-máy
    d3 = (await app_client.get(DUONG, params={"from": "2026-08-20", "to": "2026-08-21"})).json()
    assert len(d3["items"]) == SO_HANG_A_KHONG_MAY - 1  # trừ role.sua (22/08)


async def test_chi_from_hoac_chi_to(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"from": "2026-08-22"})).json()
    assert [x["hanhDong"] for x in d["items"]] == ["role.sua"]
    d2 = (await app_client.get(DUONG, params={"to": "2026-08-22"})).json()
    assert len(d2["items"]) == SO_HANG_A_KHONG_MAY - 1


async def test_from_lon_hon_bang_to_422(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    r = await app_client.get(DUONG, params={"from": "2026-08-22", "to": "2026-08-22"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "KHOANG_KHONG_HOP_LE"


# ─── Phân trang keyset ───────────────────────────────────────────────────────


async def test_phan_trang_khong_trung_khong_sot(app_client, workspace_audit) -> None:
    """`limit=3` trên 9 hàng, ba hàng CÙNG `luc` bị cắt giữa trang 1 và 2 —
    keyset trên `(luc, id)` phải đi qua biên đó không trùng không sót."""
    await dang_nhap(app_client, EMAIL_QT)
    thay: list[int] = []
    cursor = None
    so_trang = 0
    while True:
        params = {"limit": 3, **({"cursor": cursor} if cursor else {})}
        d = (await app_client.get(DUONG, params=params)).json()
        so_trang += 1
        thay.extend(x["id"] for x in d["items"])
        cursor = d["nextCursor"]
        if cursor is None:
            break
        assert so_trang < 10, "không bao giờ hết trang — cursor không tiến"
    assert so_trang == 3
    assert len(thay) == SO_HANG_A_KHONG_MAY
    assert len(set(thay)) == SO_HANG_A_KHONG_MAY, "có hàng lặp giữa các trang"
    # Trang đầu: role.sua rồi 2 trong 3 hàng cùng luc; trang 2 bắt đầu bằng hàng cùng luc còn lại.
    d1 = (await app_client.get(DUONG, params={"limit": 3})).json()
    assert d1["items"][0]["hanhDong"] == "role.sua"
    assert [x["hanhDong"] for x in d1["items"][1:]] == ["agent_config.publish"] * 2
    d2 = (await app_client.get(DUONG, params={"limit": 3, "cursor": d1["nextCursor"]})).json()
    assert d2["items"][0]["hanhDong"] == "agent_config.publish"
    assert d2["items"][0]["id"] not in {x["id"] for x in d1["items"]}


async def test_trang_cuoi_dung_bang_limit_khong_co_cursor(app_client, workspace_audit) -> None:
    """9 hàng, `limit=9` ⇒ xin 10, nhận 9 < 10 ⇒ `nextCursor` null ngay trang đầu."""
    await dang_nhap(app_client, EMAIL_QT)
    d = (await app_client.get(DUONG, params={"limit": SO_HANG_A_KHONG_MAY})).json()
    assert len(d["items"]) == SO_HANG_A_KHONG_MAY and d["nextCursor"] is None


async def test_cursor_rac_400(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    for rac in ("abc", "NDEy", "MjAyNi0wOC0yNXw0MTI"):
        r = await app_client.get(DUONG, params={"cursor": rac})
        assert r.status_code == 400, (rac, r.text)
        assert r.json()["error"]["code"] == "CURSOR_KHONG_HOP_LE"


async def test_limit_ngoai_bien_422(app_client, workspace_audit) -> None:
    await dang_nhap(app_client, EMAIL_QT)
    assert (await app_client.get(DUONG, params={"limit": 0})).status_code == 422
    assert (await app_client.get(DUONG, params={"limit": GIOI_HAN_TRANG_PLUS})).status_code == 422
```

Thêm vào đầu file: `from portal.modules.audit.contracts import GIOI_HAN_TRANG` và hằng `GIOI_HAN_TRANG_PLUS = GIOI_HAN_TRANG + 1`.

- [ ] **Step 2: Chạy**

Run: `uv run pytest tests/modules/audit -v`
Expected: PASS toàn bộ (20 bài). Nếu `test_khoang_ngay_theo_gio_vn` đỏ ở `d3`: đếm lại — hàng ngày 20/08 gồm `realestate.project.update`(09Z) · `thanh_vien.moi`(10Z) · `user.nhan_moi_ws`(11Z) · `ingest.tenant_im_lang`(13Z) · `kb.upload`(14Z) · 3×`agent_config.publish`(16Z) = 8 = `SO_HANG_A_KHONG_MAY - 1`; hàng máy 12Z bị ẩn. Nếu vẫn lệch thì lỗi ở `AT TIME ZONE` — kiểm câu SQL bằng `psql` trực tiếp trước khi sửa.

- [ ] **Step 3: Lint + commit**

Run: `make lint`

```bash
git add tests/modules/audit/test_router.py
git commit -m "test(audit): lọc nhóm, khoảng ngày giờ VN, phân trang keyset qua biên cùng luc"
```

---

### Task 6: Tài liệu bàn giao + Change Log + docstring lỗi thời

**Files:**
- Create: `docs/contracts/audit.md`
- Modify: `src/portal/core/nhat_ky.py:1-12` (docstring: màn đọc đã có), `CLAUDE.md` (Change Log, thêm MỘT dòng ngay dưới header bảng ở dòng ~433 — mới nhất trên cùng)

- [ ] **Step 1: Viết `docs/contracts/audit.md`**

```markdown
# Hợp đồng Nhật ký hoạt động — bàn giao FE

> **Đối tượng:** frontend team, ghép màn `/audit` («Nhật ký», `features/platform`).
> **Sở hữu:** module `audit` (backend). Đổi field/route ở `src/portal/modules/audit/*` mà không sửa
> tài liệu này là để tài liệu nói dối.
> **Spec:** `docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md`.

Xác thực: phiên đăng nhập, action **`audit.read`** (`ACTIONS.AUDIT_READ`, migration `0956`, cấp mặc
định cho «Quản trị»). Không có action ⇒ 403 với message «… Xem Nhật ký hoạt động …». Mục nav
`auditNav.requiredActions = ['audit.read']`.

## `GET /api/v1/audit`

| Tham số | Kiểu | Mặc định | Nghĩa |
|---|---|---|---|
| `limit` | int 1..200 | 50 | Số hàng một trang |
| `cursor` | string | — | `nextCursor` của trang trước, gửi NGUYÊN VĂN. Sai dạng → **400 `CURSOR_KHONG_HOP_LE`** |
| `nhom` | string | — | Tiền tố (phần trước dấu chấm đầu của `hanhDong`), nhiều tiền tố cách nhau dấu phẩy, mỗi tiền tố `[a-z_]{1,32}`, tối đa 10. Sai → **422 `NHOM_KHONG_HOP_LE`** |
| `from` | `YYYY-MM-DD` | — | Cận dưới ĐÓNG, ngày theo giờ Việt Nam |
| `to` | `YYYY-MM-DD` | — | Cận trên **MỞ** (`< to`), giờ Việt Nam. Ô «đến hết ngày D» ⇒ gửi `to = D + 1 ngày`. `from >= to` → **422 `KHOANG_KHONG_HOP_LE`** |
| `may` | bool | `false` | `false` ẩn hàng `actorId = "agent"` (agent bootstrap lấy credential, ~38% số dòng). `true` gộp lại |

Không có khoảng ngày mặc định. Thứ tự luôn **mới nhất trước** (`luc DESC, id DESC`).

**200**

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

- `actorId` nguyên văn cột `actor`: `u_<id>` · `"agent"` (máy) · `"platform_admin"` (NobleX qua token
  quản trị) · `""` (job hệ thống, ví dụ `ingest.tenant_im_lang`). FE hiện tương ứng «Agent» ·
  «NobleX» · «Hệ thống».
- `actorTen`/`actorEmail` là `null` khi `actor` không còn trong `control.users` (người đã bị gỡ — cố
  ý không FK) hoặc là giá trị đặc biệt ở trên. **Đừng lọc bỏ** hàng có tên null.
- `chiTiet` là jsonb nguyên văn, hình dạng KHÁC NHAU theo `hanhDong`; FE tóm tắt `khoá: giá trị`.
- `nextCursor: null` = hết.

## Sổ mã `hanhDong`

Nguồn: `src/portal/core/nhat_ky_ma.py` → artefact `contracts/audit-actions.json` (copy sang repo FE,
cổng `tests/audit-actions-parity.test.ts`). Dạng `<nhóm>.<việc>[.<việc>]`; `nhom` lọc theo `<nhóm>`.

Lỗi chung: 401 không phiên · 403 thiếu action · 422 validate — envelope `{"error": {"code", "message"}}`.
```

- [ ] **Step 2: Sửa docstring `src/portal/core/nhat_ky.py`**

Dòng 3-5 hiện ghi `M8 sẽ dựng màn hình đọc nó và thêm retention.` — đổi thành:

```
M8 đã dựng đường đọc: `modules/audit/` (`GET /audit`, 2026-08-25, spec
docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md). Retention vẫn chưa có.
Thêm một mã hành động mới ⇒ thêm vào `core/nhat_ky_ma.py` (cổng AST bắt buộc).
```

Dòng 11-12 `Bảng ... do migration 0201 tạo và M8 sẽ tiếp quản` → `Bảng ... do migration 0201 tạo; đường đọc ở modules/audit.`

- [ ] **Step 3: Thêm dòng Change Log vào `CLAUDE.md`**

Ngay dưới dòng `|---|---|` của bảng «Change Log» (mới nhất trên cùng):

```markdown
| 2026-08-25 | **Đường ĐỌC nhật ký — `GET /audit` + action `audit.read` + sổ mã** (spec `docs/superpowers/specs/2026-08-25-nhat-ky-hoat-dong-design.md`, plan `docs/superpowers/plans/2026-08-25-nhat-ky-doc-backend.md`). Module mới `modules/audit/` (router · repo · contracts, KHÔNG service). Keyset `(luc DESC, id DESC)` — cursor mã hoá CẢ cặp vì `luc = now()` là mốc BẮT ĐẦU giao dịch, `id` một mình sót hàng ở biên. `?may=false` mặc định ẩn `actor='agent'` (`agent.runtime_credentials`, 38% số dòng trên dev); `''`/`platform_admin` vẫn hiện. `from`/`to` là NGÀY giờ VN, `to` MỞ (như billing). LEFT JOIN `users` — người đã gỡ vẫn có hàng, tên null. Hàng `tenant_id NULL` không bao giờ lọt (màn theo workspace; «việc của chính mình» là đợt 2). **Action thứ 15 `audit.read`** (`0956_audit_action`, `configure`, sort_order 15 NỐI CUỐI — không đánh số lại như 0945; chỉ «Quản trị»); 4 test đếm 14→15. **Sổ mã `core/nhat_ky_ma.py`** + cổng AST `tests/unit/test_nhat_ky_ma.py` (literal ở điểm ghi ⊆ sổ; sổ không mã chết) → artefact mới `contracts/audit-actions.json` (`make contracts`, copy sang FE cùng `actions.json`). Tài liệu bàn giao `docs/contracts/audit.md`. Chưa có: CSV, retention, tìm theo người. |
```

- [ ] **Step 4: Chạy toàn bộ cổng rồi commit**

Run: `make lint && uv run pytest tests/unit tests/api tests/isolation tests/modules/audit tests/modules/auth/test_vai_tro.py tests/modules/enrollment/test_router.py -v`
Expected: PASS toàn bộ.

```bash
git add docs/contracts/audit.md src/portal/core/nhat_ky.py CLAUDE.md
git commit -m "docs: hợp đồng GET /audit cho FE, Change Log, docstring nhat_ky"
```

- [ ] **Step 5: Bàn giao cho plan FE**

Hai artefact FE cần copy byte-for-byte (plan FE Task 1):

```bash
cp contracts/actions.json ../odyssey-portal-frontend/contracts/actions.json
cp contracts/audit-actions.json ../odyssey-portal-frontend/contracts/audit-actions.json
```

(Chỉ chạy khi bắt đầu plan FE; không commit gì ở repo BE cho bước này.)

---

## Self-review (đã chạy lúc viết plan)

- **Spec coverage:** §3 action → Task 1 · §4 endpoint (tham số, mã lỗi, response, SQL) → Task 3-5 · §5 sổ mã + parity BE → Task 2 · §7 test BE → Task 1/2/4/5 · docs → Task 6. §5/§6 phần FE và §7 test FE → plan FE riêng (`odyssey-portal-frontend/docs/superpowers/plans/2026-08-25-man-nhat-ky.md`). §8 ngoài phạm vi: không có task, đúng.
- **Placeholder:** không có TBD; bước duy nhất «lặp tới khi xanh» (Task 2 Step 4) có tiêu chí dừng rõ (4/4 PASS, không nới sàn).
- **Type consistency:** `repo.liet_ke(conn, *, limit, con_tro, nhom, tu, den, may)` — router gọi đúng tên keyword; `ma_con_tro(luc, id_)`/`doc_con_tro` dùng ở router và test unit cùng chữ ký; cột SQL `actor_ten`/`actor_email` khớp `_ra_dong`.
