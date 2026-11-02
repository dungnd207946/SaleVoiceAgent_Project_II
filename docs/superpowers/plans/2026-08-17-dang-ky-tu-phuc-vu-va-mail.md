# Đăng ký tự phục vụ + gửi mail — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Người dùng tự đăng ký bằng email, nhận link qua thư để tự đặt mật khẩu; và một Quản trị workspace mời được người khác vào workspace của mình.

**Architecture:** Đăng ký tái dùng nguyên luồng lời mời đã có (`control.invites` → `GET /invites/{token}` → `POST /invites/accept`), khác biệt duy nhất là `invites.tenant_id IS NULL`. Thêm một bộ gửi mail ở `core/mailer.py` và bốn endpoint ghi trên seam `/members` — hôm nay chức năng mời không có đường nào chạy được (§0.3 của spec).

**Tech Stack:** FastAPI · asyncpg · Alembic · Redis · Pydantic v2 · aiosmtplib · React + TanStack Router/Query · Vitest

**Spec:** `docs/superpowers/specs/2026-08-15-dang-ky-tu-phuc-vu-va-mail-design.md`

## Global Constraints

- **Luật 4:** MỌI endpoint khai `action` qua `require(action)` hoặc `require(None, ly_do=...)`. Cổng `tests/unit/test_moi_route_khai_action.py`.
- **Luật 3:** module chỉ import `portal.core.*` và `portal.modules.<khác>.contracts`. Cổng `tests/test_module_boundaries.py` (đọc AST).
- **Luật 1:** mọi truy vấn `tenant_data` đi qua `tenant_conn()` trong một giao dịch. *(Đợt này chỉ chạm `control`, nhưng luật vẫn áp nếu phát sinh.)*
- **`tenant_id` LUÔN lấy từ `Principal`**, không bao giờ từ path/query/body.
- **Giao dịch mở ở tầng ROUTER**, không trong service — khuôn `repo.py` ("caller quyết định giao dịch").
- **Gửi mail NGOÀI giao dịch, sau commit.** Mail không rollback được.
- **Một alembic head.** Chạy `alembic heads` NGAY TRƯỚC khi tạo migration; `revision` id khác tên file. Cổng `tests/unit/test_alembic_mot_head.py`.
- **Phụ thuộc mới phải khai trong `[project].dependencies`.** Cổng `tests/unit/test_khai_bao_phu_thuoc.py`.
- **Test đo giá trị mặc định phải dùng `Settings(_env_file=None)`** — nếu không nó đo `.env` của lập trình viên.
- **`get_settings()` KHÔNG có `lru_cache` và không được thêm.** Nó dựng `Settings()` mới mỗi lần gọi — bất biến có chủ ý, ghi tường minh ở `tests/modules/enrollment/conftest.py` và `tests/modules/auth/conftest.py` ("Nếu ai đó thêm cache vào đó, mọi test ở đây sẽ đọc cấu hình của test chạy trước"), và `router._secure()` dựa vào nó. Test đổi cấu hình bằng `monkeypatch.setenv` là đủ; **không gọi `cache_clear()`** ở bất kỳ đâu.
- Sàn mật khẩu duy nhất còn lại: `NhanLoiMoiIn.password` = **10** ký tự.
- Cổng `make check` (lint + test) phải xanh trước khi mở MR.

---

## File Structure

**Backend — tạo mới**

| File | Trách nhiệm |
|---|---|
| `src/portal/core/mailer.py` | Gửi SMTP + ghép URL tuyệt đối. Không biết nghiệp vụ. |
| `src/portal/modules/auth/thanh_vien.py` | Nghiệp vụ 4 endpoint `/members` ghi. Tách khỏi `quan_tri_user.py` (đang bị cờ đóng, và đã dài). |
| `migrations/versions/<rev>_invites_tenant_id.py` | Thêm `invites.tenant_id`. |
| `tests/unit/test_mailer.py` · `tests/modules/auth/test_dang_ky.py` · `tests/modules/auth/test_thanh_vien.py` | |

**Backend — sửa**

| File | Việc |
|---|---|
| `src/portal/core/config.py` | 9 trường mới (SMTP · `portal_base_url` · `signup_enabled`) |
| `src/portal/modules/auth/contracts.py` | `VaoDangKy` bỏ `password`; `LoiMoiOut` + `kind`; contract `/members` ghi |
| `src/portal/modules/auth/repo.py` | `ghi_loi_moi` + `tenant_id`; `tao_user_tu_dang_ky` → `pending`; 5 hàm membership mới |
| `src/portal/modules/auth/service.py` | Viết lại `dang_ky` |
| `src/portal/modules/auth/router.py` | Viết lại `/auth/register`; thêm 4 route `/members` |
| `src/portal/modules/auth/quan_tri_user.py` | `xem_loi_moi` trả `kind`; 2 lời gọi `ghi_loi_moi` |
| `src/portal/modules/auth/loi.py` | 2 mã lỗi mới |
| `src/portal/cli/seed_owner.py` | 1 lời gọi `ghi_loi_moi` |
| `pyproject.toml` | `aiosmtplib` |

**Frontend — sửa**

| File | Việc |
|---|---|
| `src/features/auth/api.ts` | `dangKy` bỏ `matKhau`, trả trạng thái |
| `src/features/auth/components/DangKyForm.tsx` | bỏ ô mật khẩu, 3 màn kết quả |
| `src/features/auth/components/NhanLoiMoi.tsx` | đọc `kind` |
| `src/features/auth/thanhVien.ts` | thêm `loi[]` vào response mời |
| `src/lib/msw/handlers.ts` | 4 đường `/members`, `register` 201/200/409, `kind` |

---

### Task 1: Cấu hình SMTP · PORTAL_BASE_URL · SIGNUP_ENABLED

**Files:**
- Modify: `src/portal/core/config.py` (thêm sau khối `users_admin_enabled`, trước `cookie_secure`)
- Test: `tests/unit/test_config_mailer.py` (create)

**Interfaces:**
- Consumes: —
- Produces: `Settings.smtp_host: str`, `smtp_port: int`, `smtp_user: str`, `smtp_pass: str`, `smtp_from: str`, `smtp_from_name: str`, `smtp_starttls: bool`, `portal_base_url: str`, `signup_enabled: bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_mailer.py
from portal.core.config import Settings


def test_mac_dinh_mailer_tat_va_signup_mo():
    """`_env_file=None` BẮT BUỘC — nếu không bài này đo `.env` của lập trình viên."""
    c = Settings(_env_file=None)
    assert c.smtp_host == ""
    assert c.portal_base_url == ""
    assert c.smtp_port == 587
    assert c.smtp_from_name == "NobleX"
    assert c.smtp_starttls is True
    assert c.signup_enabled is True


def test_ten_truong_la_starttls_khong_phai_secure():
    """Neo quyết định spec §5.2: cổng 587 + `SMTP_SECURE=false` của Nodemailer
    nghĩa là STARTTLS, KHÔNG phải 'không mã hoá'. Đặt tên `smtp_secure` ở đây là
    mời người sau map thẳng sang `use_tls=False` và gửi credential dạng chữ thường."""
    assert not hasattr(Settings(_env_file=None), "smtp_secure")
    assert hasattr(Settings(_env_file=None), "smtp_starttls")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config_mailer.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'smtp_host'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/portal/core/config.py — chèn sau khối `users_admin_enabled`

    # ─── Gửi thư (spec dang-ky-tu-phuc-vu §5.2) ──────────────────────────────

    smtp_host: str = ""
    """RỖNG ⇒ mailer in thư ra stdout thay vì gửi. Cùng lối `public_base_url`:
    một môi trường chưa cấu hình phải chạy được, không phải nổ."""

    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    """Địa chỉ gửi, ví dụ `no-reply@noblex.vn`. Phải là identity đã verify ở SES."""
    smtp_from_name: str = "NobleX"

    smtp_starttls: bool = True
    """⚠ TÊN NÀY CỐ Ý KHÁC `SMTP_SECURE` của Nodemailer.

    Cổng 587 + `secure=false` bên Nodemailer nghĩa là STARTTLS: mở plaintext rồi
    nâng cấp TLS TRƯỚC khi gửi credential. `secure=true` mới là TLS ngầm (465).
    Ai map `SMTP_SECURE=false` thẳng thành `use_tls=False` sẽ đẩy user/pass của
    SES qua Internet dưới dạng chữ thường, và không có triệu chứng nào."""

    portal_base_url: str = ""
    """Gốc URL của FRONTEND (`https://portal.noblex.vn`), để mailer ghép link
    tuyệt đối từ `invitePath` tương đối. RỖNG ⇒ coi như mailer tắt: gửi một thư
    chứa link gãy còn tệ hơn không gửi."""

    signup_enabled: bool = True
    """Công tắc `POST /auth/register`. MẶC ĐỊNH BẬT — quyết định người yêu cầu
    2026-08-15 (spec §7.1: không rào chống lạm dụng).

    Nó KHÔNG phải một tầng an toàn; nó là khả năng tắt đăng ký mà không cần
    deploy khi có sự cố."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config_mailer.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/portal/core/config.py tests/unit/test_config_mailer.py
git commit -m "feat(config): thêm cấu hình SMTP, PORTAL_BASE_URL và SIGNUP_ENABLED"
```

---

### Task 2: `core/mailer.py`

**Files:**
- Create: `src/portal/core/mailer.py`
- Modify: `pyproject.toml` (`[project].dependencies` += `aiosmtplib>=3.0`)
- Test: `tests/unit/test_mailer.py` (create)

**Interfaces:**
- Consumes: `Settings` từ Task 1
- Produces:
  - `mailer.dang_bat() -> bool`
  - `mailer.url_tuyet_doi(duong_dan: str) -> str` — `'/invite/x'` → `'https://.../invite/x'`
  - `async mailer.gui(*, den: str, tieu_de: str, than_text: str, than_html: str) -> bool` — **`True` = đã gửi; `False` = tắt hoặc lỗi (đã log). KHÔNG BAO GIỜ ném.**

`gui()` trả `bool` chứ không `None` vì người gọi cần biết để quyết định `invitePath` là `null` hay đường dẫn copy tay (spec §4.4).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_mailer.py
import pytest

from portal.core import mailer


def _cau_hinh(monkeypatch, **kw):
    """Thay THẲNG `get_settings` mà `mailer` nhìn thấy — không đụng cache nào.

    ⚠ `get_settings()` KHÔNG có `lru_cache` (bất biến có chủ ý của repo, xem
    `tests/modules/auth/conftest.py`). Đừng gọi `cache_clear()` ở đây, và đừng
    thêm cache vào `config.py` để "sửa" nó.
    """
    from portal.core.config import Settings

    c = Settings(_env_file=None, **kw)
    monkeypatch.setattr("portal.core.mailer.get_settings", lambda: c)
    return c


def test_tat_khi_thieu_smtp_host(monkeypatch):
    _cau_hinh(monkeypatch, portal_base_url="https://p.vn")
    assert mailer.dang_bat() is False


def test_tat_khi_thieu_portal_base_url(monkeypatch):
    """Gửi một thư chứa link gãy tệ hơn không gửi."""
    _cau_hinh(monkeypatch, smtp_host="smtp.vn", smtp_from="a@b.vn")
    assert mailer.dang_bat() is False


def test_bat_khi_du_ba_truong(monkeypatch):
    _cau_hinh(monkeypatch, smtp_host="smtp.vn", smtp_from="a@b.vn", portal_base_url="https://p.vn")
    assert mailer.dang_bat() is True


def test_url_tuyet_doi_khong_nhan_doi_dau_gach(monkeypatch):
    _cau_hinh(monkeypatch, smtp_host="s", smtp_from="a@b.vn", portal_base_url="https://p.vn/")
    assert mailer.url_tuyet_doi("/invite/abc") == "https://p.vn/invite/abc"


@pytest.mark.anyio
async def test_gui_tra_false_khi_tat_va_khong_nem(monkeypatch):
    _cau_hinh(monkeypatch)
    ok = await mailer.gui(den="x@y.vn", tieu_de="t", than_text="a", than_html="<p>a</p>")
    assert ok is False


@pytest.mark.anyio
async def test_gui_nuot_loi_smtp_va_tra_false(monkeypatch):
    """§5.4: giao dịch đã commit trước khi gửi. Ném ra ngoài = 500 mô tả sai
    trạng thái hệ thống (tài khoản ĐÃ được tạo)."""
    _cau_hinh(monkeypatch, smtp_host="smtp.vn", smtp_from="a@b.vn", portal_base_url="https://p.vn")

    async def _no(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr("portal.core.mailer.aiosmtplib.send", _no)
    ok = await mailer.gui(den="x@y.vn", tieu_de="t", than_text="a", than_html="<p>a</p>")
    assert ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_mailer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'portal.core.mailer'`

- [ ] **Step 3: Add dependency**

```bash
cd odyssey-portal-backend
uv add "aiosmtplib>=3.0"
```

Xác nhận `pyproject.toml` có dòng `aiosmtplib>=3.0` trong `[project].dependencies` (không phải `[dependency-groups].dev`) — cổng `tests/unit/test_khai_bao_phu_thuoc.py` đọc đúng khối đó.

- [ ] **Step 4: Write minimal implementation**

```python
# src/portal/core/mailer.py
"""Gửi thư SMTP. KHÔNG biết nghiệp vụ — nội dung thư dựng ở `modules/auth`.

VÌ SAO Ở `core/`: luật 3 của repo (module chỉ import `portal.core.*`). Đặt ở
`modules/` thì module thứ hai cần gửi thư sẽ phải import ruột module thứ nhất.

VÌ SAO KHÔNG HÀNG ĐỢI / KHÔNG RETRY: xem spec §5.4. Thư hỏng ⇒ log + trả False,
và đường phục hồi là người dùng đăng ký lại (nhánh `pending` phát token mới).
Một hàng đợi ở đây là một hệ thống phải vận hành, cho một tính năng chưa ai đo
được tần suất hỏng.
"""

import logging
from email.message import EmailMessage

import aiosmtplib

from portal.core.config import get_settings

log = logging.getLogger(__name__)


def dang_bat() -> bool:
    """Đủ điều kiện gửi chưa. Đọc cấu hình MỖI lần — test đổi được mà không nạp lại module."""
    c = get_settings()
    return bool(c.smtp_host and c.smtp_from and c.portal_base_url)


def url_tuyet_doi(duong_dan: str) -> str:
    """`/invite/abc` -> `https://portal.noblex.vn/invite/abc`.

    API cố ý trả `invitePath` TƯƠNG ĐỐI (docstring `TaoUserRaOut.invitePath`), nên
    chỗ ghép origin có hai người: FE dùng `location.origin`, mailer dùng cấu hình.
    """
    return f"{get_settings().portal_base_url.rstrip('/')}/{duong_dan.lstrip('/')}"


async def gui(*, den: str, tieu_de: str, than_text: str, than_html: str) -> bool:
    """True = đã gửi. False = mailer tắt HOẶC lỗi (đã log). KHÔNG BAO GIỜ ném.

    Người gọi đã commit giao dịch trước khi tới đây (spec §5.3) — ném ra ngoài
    cho người dùng một 500 trong khi tài khoản của họ ĐÃ tồn tại, tức mô tả sai
    trạng thái hệ thống.

    `multipart/alternative` (cả text lẫn html): thư chỉ có HTML bị nhiều bộ lọc
    chấm điểm spam cao hơn, và đây là thư PHẢI tới hộp thư chính.
    """
    c = get_settings()
    if not dang_bat():
        log.warning("mailer tắt (thiếu SMTP_HOST/SMTP_FROM/PORTAL_BASE_URL) — bỏ qua thư tới %s", den)
        return False

    msg = EmailMessage()
    msg["From"] = f"{c.smtp_from_name} <{c.smtp_from}>"
    msg["To"] = den
    msg["Subject"] = tieu_de
    msg.set_content(than_text)
    msg.add_alternative(than_html, subtype="html")

    try:
        await aiosmtplib.send(
            msg,
            hostname=c.smtp_host,
            port=c.smtp_port,
            username=c.smtp_user or None,
            password=c.smtp_pass or None,
            start_tls=c.smtp_starttls,
        )
    except Exception:
        # Nuốt CÓ CHỦ Ý — xem docstring. `exception()` giữ traceback để còn dò được.
        log.exception("gửi thư tới %s thất bại", den)
        return False
    return True
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_mailer.py tests/unit/test_khai_bao_phu_thuoc.py -v`
Expected: PASS (6 passed + cổng phụ thuộc xanh)

- [ ] **Step 6: Commit**

```bash
git add src/portal/core/mailer.py tests/unit/test_mailer.py pyproject.toml uv.lock
git commit -m "feat(core): thêm bộ gửi thư SMTP (aiosmtplib), tắt an toàn khi thiếu cấu hình"
```

---

### Task 3: Migration `invites.tenant_id` + chữ ký `ghi_loi_moi`

**Files:**
- Create: `migrations/versions/<rev>_invites_tenant_id.py`
- Modify: `src/portal/modules/auth/repo.py` (`ghi_loi_moi`)
- Modify: `src/portal/modules/auth/quan_tri_user.py` (2 lời gọi: trong `tao` và `moi_lai`)
- Modify: `src/portal/cli/seed_owner.py` (1 lời gọi)
- Test: `tests/modules/auth/test_migration_invites_tenant.py` (create)

**Interfaces:**
- Consumes: —
- Produces: `repo.ghi_loi_moi(conn, *, token_hash: str, user_id: str, tenant_id: str | None, expires_at: datetime, created_by: str) -> None`

- [ ] **Step 1: Lấy head THẬT — đừng tin con số trong tài liệu**

```bash
cd odyssey-portal-backend
uv run alembic heads
```

Ghi lại giá trị in ra (dự kiến `0106_bo_organizations`, đo 2026-08-17). Dùng đúng nó làm `down_revision` ở Step 3. Nếu ra **hai** dòng thì DỪNG — sửa hai head trước, đừng chồng thêm.

- [ ] **Step 2: Write the failing test**

```python
# tests/modules/auth/test_migration_invites_tenant.py
import pytest


@pytest.mark.anyio
async def test_invites_co_cot_tenant_id_nullable(pool):
    r = await pool.fetchrow(
        """SELECT is_nullable, data_type FROM information_schema.columns
            WHERE table_schema='control' AND table_name='invites' AND column_name='tenant_id'"""
    )
    assert r is not None, "chưa chạy migration invites.tenant_id"
    assert r["is_nullable"] == "YES", "NULL = token tự đăng ký; NOT NULL khoá chết luồng đó"
    assert r["data_type"] == "text"


@pytest.mark.anyio
async def test_xoa_workspace_thi_loi_moi_vao_no_cung_rung(pool, workspace_cfg):
    """ON DELETE CASCADE: lời mời vào một workspace đã xoá không còn nghĩa gì."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id, email, name, lifecycle) VALUES ('u_cas','cas@x.vn','Cas','pending')"
        )
        await conn.execute(
            """INSERT INTO control.tenants (id, name, created_by) VALUES ('t_cas','Cas WS','u_cas')"""
        )
        await conn.execute(
            """INSERT INTO control.invites (token_hash, user_id, tenant_id, expires_at, created_by)
               VALUES (repeat('a',64), 'u_cas', 't_cas', now() + interval '7 day', 'u_cas')"""
        )
        await conn.execute("DELETE FROM control.tenants WHERE id = 't_cas'")
        con = await conn.fetchval("SELECT count(*) FROM control.invites WHERE user_id = 'u_cas'")
        assert con == 0
        await conn.execute("DELETE FROM control.users WHERE id = 'u_cas'")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/modules/auth/test_migration_invites_tenant.py -v`
Expected: FAIL — `assert r is not None` (chưa có cột)

- [ ] **Step 4: Write the migration**

Tạo `migrations/versions/0107_invites_tenant_id.py` (đổi số nếu head khác):

```python
"""control.invites thêm tenant_id — phân biệt token ĐĂNG KÝ với token MỜI

NULL = người đó tự đăng ký (`POST /auth/register`), chưa thuộc workspace nào.
Có giá trị = một Quản trị mời họ vào ĐÚNG workspace đó.

VÌ SAO KHÔNG LƯU THÊM CỘT `kind`: `kind` của `LoiMoiOut` suy từ
`tenant_id IS NULL`. Hai cột nói cùng một sự thật là hai cột sẽ lệch nhau, và
cột suy được thì không phải cột.

VÌ SAO KHÔNG BACKFILL: mọi hàng đang sống lúc chạy migration đều là token mời,
nhưng để NULL là ĐÚNG — chúng sinh ra ở thời kỳ chưa có khái niệm này, và đoán
ngược `tenant_id` từ `memberships` sẽ sai với người thuộc nhiều workspace. Token
hạn 7 ngày; hàng cũ tự hết.

Revision ID: 0107_invites_tenant_id
Revises: 0106_bo_organizations
"""

from alembic import op

revision = "0107_invites_tenant_id"
down_revision = "0106_bo_organizations"  # ⚠ thay bằng head đo được ở Step 1
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """ALTER TABLE control.invites
             ADD COLUMN tenant_id text
               REFERENCES control.tenants(id) ON DELETE CASCADE"""
    )


def downgrade() -> None:
    op.execute("ALTER TABLE control.invites DROP COLUMN tenant_id")
```

- [ ] **Step 5: Áp migration và chạy test**

```bash
uv run alembic upgrade head
uv run pytest tests/modules/auth/test_migration_invites_tenant.py tests/unit/test_alembic_mot_head.py -v
```
Expected: PASS (2 passed + một head)

- [ ] **Step 6: Sửa `ghi_loi_moi` nhận `tenant_id`**

Trong `src/portal/modules/auth/repo.py`, thêm tham số và cột:

```python
async def ghi_loi_moi(
    conn: asyncpg.Connection,
    *,
    token_hash: str,
    user_id: str,
    tenant_id: str | None,
    expires_at: datetime,
    created_by: str,
) -> None:
    """UPSERT theo `user_id` — token cũ của người đó CHẾT ngay tại đây.

    `tenant_id=None` = token tự đăng ký; có giá trị = token mời vào workspace đó.
    KHÔNG có mặc định cho tham số này: một `None` ngầm biến mọi lời mời thành
    lời mời "đăng ký", và triệu chứng chỉ là một dòng tiêu đề sai trên màn đặt
    mật khẩu — quá nhẹ để ai đó phát hiện.
    """
    await conn.execute(
        """INSERT INTO control.invites (token_hash, user_id, tenant_id, expires_at, created_by)
           VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT (user_id) DO UPDATE
               SET token_hash = EXCLUDED.token_hash,
                   tenant_id  = EXCLUDED.tenant_id,
                   expires_at = EXCLUDED.expires_at,
                   created_by = EXCLUDED.created_by,
                   used_at    = NULL""",
        token_hash,
        user_id,
        tenant_id,
        expires_at,
        created_by,
    )
```

Giữ nguyên phần docstring cũ nói về `ON CONFLICT (user_id)` và `used_at = NULL`.

- [ ] **Step 7: Sửa ba người gọi**

```bash
grep -rn "ghi_loi_moi(" --include=*.py src/portal/
```

Sửa từng chỗ:
- `src/portal/modules/auth/quan_tri_user.py` trong `tao()` → thêm `tenant_id=None` (đường `POST /users` không gắn workspace; Task 5 sẽ có đường gắn)
- `src/portal/modules/auth/quan_tri_user.py` trong `moi_lai()` → `tenant_id=None`
- `src/portal/cli/seed_owner.py` → `tenant_id=<id workspace vừa tạo>`; hàm `chay()` đã có biến từ `ws_service.tao(...)`, lấy `.id` của nó

- [ ] **Step 8: Chạy toàn bộ test auth**

Run: `uv run pytest tests/modules/auth tests/integration/test_seed_owner.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add migrations/versions/0107_invites_tenant_id.py src/portal/modules/auth/repo.py \
        src/portal/modules/auth/quan_tri_user.py src/portal/cli/seed_owner.py \
        tests/modules/auth/test_migration_invites_tenant.py
git commit -m "feat(db): invites.tenant_id phân biệt token đăng ký với token mời"
```

---

### Task 4: Contract và repo cho seam `/members` ghi

**Files:**
- Modify: `src/portal/modules/auth/contracts.py` (thêm sau `class MemberOut`)
- Modify: `src/portal/modules/auth/repo.py`
- Modify: `src/portal/modules/auth/loi.py`
- Test: `tests/modules/auth/test_repo_thanh_vien.py` (create)

**Interfaces:**
- Consumes: `MemberOut` (đã có)
- Produces:
  - `MoiThanhVienIn(emails: list[str], roleId: str)`
  - `KetQuaMoiOut(email: str, userId: str, invitePath: str | None, daCo: bool)`
  - `LoiMoiTungDongOut(email: str, ma: str)`
  - `MoiThanhVienRaOut(invites: list[KetQuaMoiOut], loi: list[LoiMoiTungDongOut])`
  - `DoiVaiTroThanhVienIn(roleId: str)`
  - `repo.role_ton_tai(conn, role_id: str) -> bool`
  - `repo.them_membership(conn, *, user_id: str, tenant_id: str, role_id: str) -> None`
  - `repo.doi_vai_tro_thanh_vien(conn, *, user_id: str, tenant_id: str, role_id: str) -> bool`
  - `repo.go_thanh_vien(conn, *, user_id: str, tenant_id: str) -> bool`
  - `repo.doc_thanh_vien(conn, *, tenant_id: str, user_id: str) -> MemberOut | None`
  - `loi.vai_tro_khong_ton_tai()` → 422 `ROLE_NOT_FOUND`
  - `loi.user_dang_cho_dang_ky()` → mã `USER_PENDING_SIGNUP`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/auth/test_repo_thanh_vien.py
import pytest

from portal.modules.auth import repo


@pytest.mark.anyio
async def test_them_roi_doc_lai_thanh_vien(pool, workspace_cfg, role_id_bien_tap):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle) VALUES ('u_tv','tv@x.vn','TV','pending')"
        )
        await repo.them_membership(conn, user_id="u_tv", tenant_id=workspace_cfg, role_id=role_id_bien_tap)

        m = await repo.doc_thanh_vien(conn, tenant_id=workspace_cfg, user_id="u_tv")
        assert m is not None
        assert m.userId == "u_tv"
        assert m.roleId == role_id_bien_tap


@pytest.mark.anyio
async def test_doi_vai_tro_chi_cham_MOT_workspace(pool, workspace_cfg, role_id_bien_tap, role_id_nguoi_xem):
    """Neo bug mất dữ liệu 2026-08-06: `dat_lai_membership` THAY THẾ TOÀN BỘ, nên
    dùng nó cho đường này là xoá sạch vai trò của người đó ở workspace khác."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle) VALUES ('u_hai','hai@x.vn','Hai','active')"
        )
        await conn.execute(
            "INSERT INTO control.tenants (id,name,created_by) VALUES ('t_khac','Khác','u_hai')"
        )
        await repo.them_membership(conn, user_id="u_hai", tenant_id=workspace_cfg, role_id=role_id_bien_tap)
        await repo.them_membership(conn, user_id="u_hai", tenant_id="t_khac", role_id=role_id_bien_tap)

        ok = await repo.doi_vai_tro_thanh_vien(
            conn, user_id="u_hai", tenant_id=workspace_cfg, role_id=role_id_nguoi_xem
        )
        assert ok is True

        con = await repo.doc_thanh_vien(conn, tenant_id="t_khac", user_id="u_hai")
        assert con is not None and con.roleId == role_id_bien_tap, "workspace khác bị đụng"


@pytest.mark.anyio
async def test_go_thanh_vien_giu_nguyen_tai_khoan(pool, workspace_cfg, role_id_bien_tap):
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle) VALUES ('u_go','go@x.vn','Go','active')"
        )
        await repo.them_membership(conn, user_id="u_go", tenant_id=workspace_cfg, role_id=role_id_bien_tap)

        assert await repo.go_thanh_vien(conn, user_id="u_go", tenant_id=workspace_cfg) is True
        assert await repo.doc_thanh_vien(conn, tenant_id=workspace_cfg, user_id="u_go") is None
        assert await conn.fetchval("SELECT 1 FROM control.users WHERE id='u_go'") == 1


@pytest.mark.anyio
async def test_go_nguoi_khong_phai_thanh_vien_tra_false(pool, workspace_cfg):
    async with pool.acquire() as conn, conn.transaction():
        assert await repo.go_thanh_vien(conn, user_id="u_khong_co", tenant_id=workspace_cfg) is False
```

Thêm fixture vào `tests/modules/auth/conftest.py`:

```python
@pytest.fixture
async def role_id_bien_tap(pool):
    return await pool.fetchval("SELECT id FROM control.roles WHERE name = 'Biên tập'")


@pytest.fixture
async def role_id_nguoi_xem(pool):
    return await pool.fetchval("SELECT id FROM control.roles WHERE name = 'Người xem'")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/auth/test_repo_thanh_vien.py -v`
Expected: FAIL — `AttributeError: module 'portal.modules.auth.repo' has no attribute 'them_membership'`

- [ ] **Step 3: Thêm hàm repo**

```python
# src/portal/modules/auth/repo.py — thêm cạnh `liet_ke_thanh_vien`

async def role_ton_tai(conn: asyncpg.Connection, role_id: str) -> bool:
    """Vai trò TOÀN CỤC từ 0105 — không còn phạm vi tổ chức để kiểm.

    Vẫn phải kiểm tồn tại: FK sẽ chặn, nhưng bằng `ForeignKeyViolationError` -> 500
    thay vì 422 có tên field. Cùng lý lẽ `loc_role_ngoai_to_chuc` cũ đã ghi.
    """
    return await conn.fetchval("SELECT 1 FROM control.roles WHERE id = $1", role_id) is not None


async def them_membership(conn: asyncpg.Connection, *, user_id: str, tenant_id: str, role_id: str) -> None:
    """MỘT hàng. KHÔNG dùng `dat_lai_membership` — hàm đó THAY THẾ TOÀN BỘ.

    `ON CONFLICT DO UPDATE`: mời lại một người đã ở trong workspace là đổi vai trò
    của họ, không phải một lỗi. PK là (user_id, tenant_id).
    """
    await conn.execute(
        """INSERT INTO control.memberships (user_id, tenant_id, role_id)
           VALUES ($1, $2, $3)
           ON CONFLICT (user_id, tenant_id) DO UPDATE SET role_id = EXCLUDED.role_id""",
        user_id,
        tenant_id,
        role_id,
    )


async def doi_vai_tro_thanh_vien(
    conn: asyncpg.Connection, *, user_id: str, tenant_id: str, role_id: str
) -> bool:
    """False = không có hàng nào khớp (không phải thành viên workspace này).

    Vị từ `tenant_id` là thứ giữ đường này chỉ chạm ĐÚNG một workspace — xem
    `tests/modules/auth/test_repo_thanh_vien.py::test_doi_vai_tro_chi_cham_MOT_workspace`.
    """
    r = await conn.execute(
        "UPDATE control.memberships SET role_id = $3 WHERE user_id = $1 AND tenant_id = $2",
        user_id,
        tenant_id,
        role_id,
    )
    return r != "UPDATE 0"


async def go_thanh_vien(conn: asyncpg.Connection, *, user_id: str, tenant_id: str) -> bool:
    """Gỡ khỏi MỘT workspace. KHÔNG xoá `control.users` — xoá tài khoản là việc
    khác, và hiện không có chủ (khối `/users*` đang tắt sau 0106)."""
    r = await conn.execute(
        "DELETE FROM control.memberships WHERE user_id = $1 AND tenant_id = $2", user_id, tenant_id
    )
    return r != "DELETE 0"


async def doc_thanh_vien(conn: asyncpg.Connection, *, tenant_id: str, user_id: str) -> MemberOut | None:
    """Cùng cú JOIN với `liet_ke_thanh_vien`, một hàng — cho response của PATCH."""
    r = await conn.fetchrow(
        f"""SELECT u.id, u.name, u.email, m.role_id, r.name AS role
              FROM control.memberships m
              JOIN control.users u ON u.id = m.user_id
              JOIN control.roles r ON r.id = m.role_id
             WHERE m.tenant_id = $1 AND m.user_id = $2 AND {_CON_HIEU_LUC}""",
        tenant_id,
        user_id,
    )
    if r is None:
        return None
    return MemberOut(userId=r["id"], name=r["name"], email=r["email"], roleId=r["role_id"], role=r["role"])
```

- [ ] **Step 4: Thêm contract**

```python
# src/portal/modules/auth/contracts.py — thêm sau `class MemberOut`

class MoiThanhVienIn(BaseModel):
    """Mời NHIỀU email cùng MỘT vai trò, vào workspace ĐANG MỞ.

    KHÔNG có `workspaceId`: nó suy từ `Principal.tenant_id`. Nhận từ thân request
    là cho một Quản trị của workspace A đẩy người vào workspace B.
    """

    model_config = ConfigDict(extra="forbid")

    emails: list[str] = Field(min_length=1, max_length=50)
    roleId: str = Field(min_length=1)

    @field_validator("emails")
    @classmethod
    def _chuan_hoa(cls, v: list[str]) -> list[str]:
        """Chuẩn hoá + bỏ trùng GIỮ THỨ TỰ. Dán 40 dòng từ Excel thì trùng lặp là
        chuyện thường, và để nó xuống tới `ON CONFLICT` là hai dòng kết quả cho
        cùng một người."""
        thay: list[str] = []
        for x in v:
            e = x.strip().lower()
            if not e:
                continue
            if not _RE_EMAIL.match(e):
                raise ValueError(f"email không đúng dạng: {x}")
            if e not in thay:
                thay.append(e)
        if not thay:
            raise ValueError("cần ít nhất một email")
        return thay


class KetQuaMoiOut(BaseModel):
    """Một email mời THÀNH CÔNG."""

    email: str
    userId: str
    invitePath: str | None
    """`None` = backend đã gửi thư hộ. Có giá trị = mailer tắt/lỗi, admin copy tay.

    Hợp đồng này FE đã chừa sẵn từ 2026-08-09 (`thanhVien.ts`): backend đổi GIÁ TRỊ
    chứ không đổi HÌNH DẠNG.
    """
    daCo: bool
    """`True` = email đã có tài khoản `active`, chỉ thêm membership — KHÔNG phát
    token. `invitePath` luôn `None` khi cờ này bật, kể cả lúc mailer tắt: không có
    token nào tồn tại để copy."""


class LoiMoiTungDongOut(BaseModel):
    """Một email KHÔNG mời được. Lỗi theo TỪNG DÒNG, không phải cho cả lô:
    mời 40 người mà một người hỏng thì 39 người kia phải vào được."""

    email: str
    ma: str


class MoiThanhVienRaOut(BaseModel):
    invites: list[KetQuaMoiOut]
    loi: list[LoiMoiTungDongOut]


class DoiVaiTroThanhVienIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    roleId: str = Field(min_length=1)
```

- [ ] **Step 5: Thêm mã lỗi**

```python
# src/portal/modules/auth/loi.py

def vai_tro_khong_ton_tai() -> LoiPortal:
    """422 có tên field, không phải 500 từ FK.

    Thay `vai_tro_khong_thuoc_to_chuc()` (mã cũ `ROLE_NOT_IN_ORG`, chết cùng tầng
    tổ chức ở 0105): vai trò nay TOÀN CỤC, nên câu hỏi duy nhất còn lại là "có
    tồn tại không".
    """
    return LoiPortal("ROLE_NOT_FOUND", 422, "Vai trò không tồn tại")


USER_PENDING_SIGNUP = "USER_PENDING_SIGNUP"
"""Mã lỗi TỪNG DÒNG của `POST /members` — không phải một `LoiPortal`.

Người này đã tự đăng ký và đang chờ đặt mật khẩu. Phát token mời cho họ sẽ GIẾT
token đăng ký của họ (`invites.user_id` UNIQUE + DO UPDATE): họ bấm link trong
hộp thư và nhận `INVITE_INVALID` mà không hiểu vì sao.
"""
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/modules/auth/test_repo_thanh_vien.py tests/api/test_contracts.py -v`
Expected: PASS (4 passed)

- [ ] **Step 7: Commit**

```bash
git add src/portal/modules/auth/repo.py src/portal/modules/auth/contracts.py \
        src/portal/modules/auth/loi.py tests/modules/auth/test_repo_thanh_vien.py \
        tests/modules/auth/conftest.py
git commit -m "feat(auth): contract và repo cho seam /members ghi"
```

---

### Task 5: `POST /members` — mời vào workspace, ba nhánh

**Files:**
- Create: `src/portal/modules/auth/thanh_vien.py`
- Modify: `src/portal/modules/auth/router.py`
- Test: `tests/modules/auth/test_thanh_vien.py` (create)

**Interfaces:**
- Consumes: Task 2 (`mailer.gui`, `mailer.url_tuyet_doi`, `mailer.dang_bat`), Task 3 (`repo.ghi_loi_moi(..., tenant_id=...)`), Task 4 (contracts + repo)
- Produces: `thanh_vien.moi(conn, *, actor_id: str, tenant_id: str, vao: MoiThanhVienIn) -> tuple[MoiThanhVienRaOut, list[tuple[str, str]]]` — phần tử thứ hai là danh sách `(email, token_tho)` để router gửi thư **sau commit**

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/auth/test_thanh_vien.py
import pytest


@pytest.mark.anyio
async def test_moi_email_moi_tao_user_pending_va_token_gan_workspace(
    client_cfg, pool, workspace_cfg, role_id_bien_tap
):
    res = await client_cfg.post(
        "/api/v1/members", json={"emails": ["moi1@x.vn"], "roleId": role_id_bien_tap}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["loi"] == []
    assert len(body["invites"]) == 1
    assert body["invites"][0]["daCo"] is False

    uid = body["invites"][0]["userId"]
    r = await pool.fetchrow(
        """SELECT u.lifecycle, u.password_hash, i.tenant_id
             FROM control.users u JOIN control.invites i ON i.user_id = u.id
            WHERE u.id = $1""",
        uid,
    )
    assert r["lifecycle"] == "pending"
    assert r["password_hash"] is None
    assert r["tenant_id"] == workspace_cfg, "token mời PHẢI gắn workspace"


@pytest.mark.anyio
async def test_moi_nguoi_da_active_chi_them_membership_khong_phat_token(
    client_cfg, pool, workspace_cfg, role_id_bien_tap
):
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO control.users (id,email,name,password_hash,lifecycle)
               VALUES ('u_act','act@x.vn','Act','$argon2id$fake','active')"""
        )
    res = await client_cfg.post(
        "/api/v1/members", json={"emails": ["act@x.vn"], "roleId": role_id_bien_tap}
    )
    assert res.status_code == 201
    ket = res.json()["invites"][0]
    assert ket["daCo"] is True
    assert ket["invitePath"] is None, "không có token nào tồn tại để copy"
    assert await pool.fetchval("SELECT count(*) FROM control.invites WHERE user_id='u_act'") == 0
    assert (
        await pool.fetchval(
            "SELECT count(*) FROM control.memberships WHERE user_id='u_act' AND tenant_id=$1",
            workspace_cfg,
        )
        == 1
    )


@pytest.mark.anyio
async def test_moi_nguoi_dang_cho_dang_ky_bi_tu_choi_rieng_dong_do(
    client_cfg, pool, role_id_bien_tap
):
    """Phát token cho họ sẽ giết token đăng ký của chính họ."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle) VALUES ('u_pen','pen@x.vn','Pen','pending')"
        )
        await conn.execute(
            """INSERT INTO control.invites (token_hash,user_id,tenant_id,expires_at,created_by)
               VALUES (repeat('b',64),'u_pen',NULL, now() + interval '7 day','u_pen')"""
        )
    res = await client_cfg.post(
        "/api/v1/members", json={"emails": ["pen@x.vn", "khac@x.vn"], "roleId": role_id_bien_tap}
    )
    assert res.status_code == 201
    body = res.json()
    assert body["loi"] == [{"email": "pen@x.vn", "ma": "USER_PENDING_SIGNUP"}]
    assert [i["email"] for i in body["invites"]] == ["khac@x.vn"], "39 người kia phải vào được"
    assert (
        await pool.fetchval("SELECT token_hash FROM control.invites WHERE user_id='u_pen'")
        == "b" * 64
    ), "token đăng ký của họ bị giết"


@pytest.mark.anyio
async def test_role_khong_ton_tai_tra_422(client_cfg):
    res = await client_cfg.post("/api/v1/members", json={"emails": ["a@x.vn"], "roleId": "r_ma"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "ROLE_NOT_FOUND"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/auth/test_thanh_vien.py -v`
Expected: FAIL — 405 Method Not Allowed (chưa có route `POST /members`)

- [ ] **Step 3: Viết service**

```python
# src/portal/modules/auth/thanh_vien.py
"""Nghiệp vụ seam `/members` — người trong MỘT workspace.

VÌ SAO KHÔNG NẰM TRONG `quan_tri_user.py`: file đó là khối quản trị TOÀN HỆ THỐNG
và đang bị `USERS_ADMIN_ENABLED` đóng (0106). Khối này thì mở và gate bằng
`WORKSPACE_ADMIN`. Hai vòng đời khác nhau, hai cổng khác nhau — gộp lại thì bật
tắt một cái là chạm cái kia.

MỌI đường ở đây lấy `tenant_id` từ `Principal`, không bao giờ từ body.
"""

import secrets
from datetime import UTC, datetime

import asyncpg

from portal.core import nhat_ky
from portal.modules.auth import loi, repo
from portal.modules.auth.contracts import (
    KetQuaMoiOut,
    LoiMoiTungDongOut,
    MoiThanhVienIn,
    MoiThanhVienRaOut,
)
from portal.modules.auth.quan_tri_user import (
    HAN_MOI,
    _SO_BYTE_TOKEN,
    bam_token,
    duong_dan_moi,
    sinh_user_id,
)


async def moi(
    conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, vao: MoiThanhVienIn
) -> tuple[MoiThanhVienRaOut, list[tuple[str, str]]]:
    """Trả (kết quả, [(email, token_thô)]). Người gọi mở giao dịch VÀ gửi thư SAU commit.

    Token thô đi ra ngoài qua giá trị trả về chứ không đọc lại từ DB: DB chỉ có
    `sha256`, nên đây là lần duy nhất nó tồn tại ở dạng đọc được.
    """
    if not await repo.role_ton_tai(conn, vao.roleId):
        raise loi.vai_tro_khong_ton_tai()

    ok: list[KetQuaMoiOut] = []
    hong: list[LoiMoiTungDongOut] = []
    thu: list[tuple[str, str]] = []

    for email in vao.emails:
        u = await repo.tim_user_theo_email(conn, email)

        if u is not None and u.lifecycle == "pending":
            # Xem `loi.USER_PENDING_SIGNUP`: phát token ở đây giết token đăng ký của họ.
            hong.append(LoiMoiTungDongOut(email=email, ma=loi.USER_PENDING_SIGNUP))
            continue

        if u is not None:
            # Đã `active` (hoặc `suspended`): chỉ nối họ vào workspace. KHÔNG phát
            # token — đó là tạo một đường đặt lại mật khẩu không ai yêu cầu.
            await repo.them_membership(conn, user_id=u.id, tenant_id=tenant_id, role_id=vao.roleId)
            ok.append(KetQuaMoiOut(email=email, userId=u.id, invitePath=None, daCo=True))
            continue

        user_id = await sinh_user_id(conn, email)
        await repo.tao_user(conn, user_id=user_id, email=email, name=email.split("@")[0])
        await repo.them_membership(conn, user_id=user_id, tenant_id=tenant_id, role_id=vao.roleId)

        token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
        await repo.ghi_loi_moi(
            conn,
            token_hash=bam_token(token),
            user_id=user_id,
            tenant_id=tenant_id,
            expires_at=datetime.now(UTC) + HAN_MOI,
            created_by=actor_id,
        )
        thu.append((email, token))
        ok.append(
            KetQuaMoiOut(email=email, userId=user_id, invitePath=duong_dan_moi(token), daCo=False)
        )

    # SAU KHI việc đã xong. KHÔNG ghi token vào `chi_tiet` — nhật ký là bảng
    # chỉ-ghi-thêm mà nhiều người đọc được.
    await nhat_ky.ghi(
        conn,
        tenant_id,
        "thanh_vien.moi",
        actor_id,
        {"so_moi": len(ok), "so_hong": len(hong), "role_id": vao.roleId},
    )
    return MoiThanhVienRaOut(invites=ok, loi=hong), thu
```

⚠ `repo.tao_user` hiện nhận `org_id`/`org_role`/`phone`/`job_title`. Sau 0106 nó không còn `org_id`; kiểm chữ ký thật bằng `grep -n "async def tao_user" -A 12 src/portal/modules/auth/repo.py` và truyền đúng tham số đang có (tối thiểu `user_id`, `email`, `name`).

- [ ] **Step 4: Thêm route**

```python
# src/portal/modules/auth/router.py — ngay dưới `liet_ke_thanh_vien`

@ROUTER.post("/members", response_model=MoiThanhVienRaOut, status_code=201)
async def moi_thanh_vien(
    vao: MoiThanhVienIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MoiThanhVienRaOut:
    """Mời vào workspace ĐANG MỞ — `tenant_id` từ `Principal`, không từ body.

    Thư gửi SAU commit (spec §5.3): mail không rollback được, và giữ kết nối
    Postgres suốt lúc bắt tay TLS là cách làm cạn pool.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            ra, thu = await thanh_vien.moi(conn, actor_id=p.user_id, tenant_id=p.tenant_id, vao=vao)

    # Vòng lặp thường, KHÔNG comprehension: mỗi lượt là một lần bắt tay SMTP, và
    # một comprehension có `await` bên trong che mất điều đó khỏi người đọc.
    da_gui: set[str] = set()
    for email, token in thu:
        if await _gui_thu_moi(email, token):
            da_gui.add(email)

    return MoiThanhVienRaOut(
        invites=[
            i.model_copy(update={"invitePath": None}) if i.email in da_gui else i for i in ra.invites
        ],
        loi=ra.loi,
    )


async def _gui_thu_moi(email: str, token: str) -> bool:
    """True = đã gửi ⇒ `invitePath` về `None`. False ⇒ giữ đường dẫn để admin copy tay."""
    url = mailer.url_tuyet_doi(duong_dan_moi(token)) if mailer.dang_bat() else ""
    return await mailer.gui(
        den=email,
        tieu_de="Bạn được mời tham gia NobleX Portal",
        than_text=f"Bạn được mời tham gia một workspace trên NobleX Portal.\n\nĐặt mật khẩu: {url}\n\nLiên kết có hạn 7 ngày.",
        than_html=f'<p>Bạn được mời tham gia một workspace trên NobleX Portal.</p><p><a href="{url}">Đặt mật khẩu</a></p><p>Liên kết có hạn 7 ngày.</p>',
    )
```

Thêm import ở đầu `router.py`: `from portal.core import mailer`, `from portal.modules.auth import thanh_vien`, `from portal.modules.auth.quan_tri_user import duong_dan_moi`, và các contract mới.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/modules/auth/test_thanh_vien.py tests/unit/test_moi_route_khai_action.py -v`
Expected: PASS (4 passed + cổng khai action xanh)

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/auth/thanh_vien.py src/portal/modules/auth/router.py \
        tests/modules/auth/test_thanh_vien.py
git commit -m "feat(auth): POST /members — mời vào workspace, ba nhánh theo trạng thái email"
```

---

### Task 6: `PATCH` · `DELETE` · `POST .../invite` trên `/members`

**Files:**
- Modify: `src/portal/modules/auth/thanh_vien.py`
- Modify: `src/portal/modules/auth/router.py`
- Test: `tests/modules/auth/test_thanh_vien.py` (thêm)

**Interfaces:**
- Consumes: Task 4, Task 5
- Produces:
  - `thanh_vien.doi_vai_tro(conn, *, actor_id, tenant_id, user_id, role_id) -> MemberOut`
  - `thanh_vien.go(conn, *, actor_id, tenant_id, user_id) -> None`
  - `thanh_vien.moi_lai(conn, *, actor_id, tenant_id, user_id) -> str` (token thô)

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/auth/test_thanh_vien.py — thêm

@pytest.mark.anyio
async def test_patch_doi_vai_tro_tra_member_moi(client_cfg, role_id_bien_tap, role_id_nguoi_xem):
    r1 = await client_cfg.post("/api/v1/members", json={"emails": ["p@x.vn"], "roleId": role_id_bien_tap})
    uid = r1.json()["invites"][0]["userId"]

    r2 = await client_cfg.patch(f"/api/v1/members/{uid}", json={"roleId": role_id_nguoi_xem})
    assert r2.status_code == 200, r2.text
    assert r2.json()["roleId"] == role_id_nguoi_xem


@pytest.mark.anyio
async def test_patch_nguoi_ngoai_workspace_tra_404(client_cfg, role_id_nguoi_xem):
    r = await client_cfg.patch("/api/v1/members/u_khong_co", json={"roleId": role_id_nguoi_xem})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.anyio
async def test_delete_go_khoi_workspace_ma_tai_khoan_con(client_cfg, pool, role_id_bien_tap):
    r1 = await client_cfg.post("/api/v1/members", json={"emails": ["d@x.vn"], "roleId": role_id_bien_tap})
    uid = r1.json()["invites"][0]["userId"]

    r2 = await client_cfg.delete(f"/api/v1/members/{uid}")
    assert r2.status_code == 204
    assert await pool.fetchval("SELECT 1 FROM control.users WHERE id=$1", uid) == 1


@pytest.mark.anyio
async def test_moi_lai_giet_token_cu(client_cfg, pool, role_id_bien_tap):
    r1 = await client_cfg.post("/api/v1/members", json={"emails": ["m@x.vn"], "roleId": role_id_bien_tap})
    uid = r1.json()["invites"][0]["userId"]
    cu = await pool.fetchval("SELECT token_hash FROM control.invites WHERE user_id=$1", uid)

    r2 = await client_cfg.post(f"/api/v1/members/{uid}/invite")
    assert r2.status_code == 200, r2.text
    moi_hash = await pool.fetchval("SELECT token_hash FROM control.invites WHERE user_id=$1", uid)
    assert moi_hash != cu
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/auth/test_thanh_vien.py -k "patch or delete or moi_lai" -v`
Expected: FAIL — 405 Method Not Allowed

- [ ] **Step 3: Thêm ba hàm service**

```python
# src/portal/modules/auth/thanh_vien.py — thêm

async def doi_vai_tro(
    conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, user_id: str, role_id: str
) -> MemberOut:
    """Chạm ĐÚNG một hàng `memberships`.

    ĐỪNG thay bằng `repo.dat_lai_membership` — hàm đó THAY THẾ TOÀN BỘ membership
    của user, nên gọi nó với một dòng là xoá sạch vai trò của họ ở mọi workspace
    khác (bug mất dữ liệu thật, 2026-08-06).
    """
    if not await repo.role_ton_tai(conn, role_id):
        raise loi.vai_tro_khong_ton_tai()
    if not await repo.doi_vai_tro_thanh_vien(conn, user_id=user_id, tenant_id=tenant_id, role_id=role_id):
        raise loi.user_khong_ton_tai()

    await nhat_ky.ghi(conn, tenant_id, "thanh_vien.doi_vai_tro", actor_id, {"user_id": user_id, "role_id": role_id})
    m = await repo.doc_thanh_vien(conn, tenant_id=tenant_id, user_id=user_id)
    assert m is not None, "vừa UPDATE trong cùng giao dịch"
    return m


async def go(conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, user_id: str) -> None:
    """Gỡ khỏi WORKSPACE, KHÔNG xoá tài khoản.

    Tự gỡ chính mình bị chặn: một workspace mất Quản trị cuối cùng là một workspace
    không ai mời thêm được ai, và không có admin hệ thống để gỡ (0106).
    """
    if user_id == actor_id:
        raise loi.tu_khoa_cua_minh("Bạn không thể tự gỡ mình khỏi workspace đang mở")
    if not await repo.go_thanh_vien(conn, user_id=user_id, tenant_id=tenant_id):
        raise loi.user_khong_ton_tai()
    await nhat_ky.ghi(conn, tenant_id, "thanh_vien.go", actor_id, {"user_id": user_id})


async def moi_lai(conn: asyncpg.Connection, *, actor_id: str, tenant_id: str, user_id: str) -> str:
    """Trả token THÔ. Token cũ chết tại đây (`invites.user_id` UNIQUE + DO UPDATE).

    Chỉ áp cho người còn `pending`: sinh thư mời cho người đã có mật khẩu là tạo
    một đường đặt lại mật khẩu mà không ai yêu cầu.
    """
    m = await repo.doc_thanh_vien(conn, tenant_id=tenant_id, user_id=user_id)
    if m is None:
        raise loi.user_khong_ton_tai()
    u = await repo.tim_user_theo_id(conn, user_id)
    if u is None or u.lifecycle != "pending":
        raise loi.user_da_nhan_moi()

    token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
    await repo.ghi_loi_moi(
        conn,
        token_hash=bam_token(token),
        user_id=user_id,
        tenant_id=tenant_id,
        expires_at=datetime.now(UTC) + HAN_MOI,
        created_by=actor_id,
    )
    await nhat_ky.ghi(conn, tenant_id, "thanh_vien.moi_lai", actor_id, {"user_id": user_id})
    return token
```

Thêm import `MemberOut` vào khối import contracts của file này.

- [ ] **Step 4: Thêm ba route**

```python
# src/portal/modules/auth/router.py

@ROUTER.patch("/members/{user_id}", response_model=MemberOut)
async def doi_vai_tro_thanh_vien(
    user_id: str,
    vao: DoiVaiTroThanhVienIn,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MemberOut:
    async with pool.acquire() as conn, conn.transaction():
        return await thanh_vien.doi_vai_tro(
            conn, actor_id=p.user_id, tenant_id=p.tenant_id, user_id=user_id, role_id=vao.roleId
        )


@ROUTER.delete("/members/{user_id}", status_code=204)
async def go_thanh_vien(
    user_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> None:
    async with pool.acquire() as conn, conn.transaction():
        await thanh_vien.go(conn, actor_id=p.user_id, tenant_id=p.tenant_id, user_id=user_id)


@ROUTER.post("/members/{user_id}/invite", response_model=MoiLaiRaOut)
async def moi_lai_thanh_vien(
    user_id: str,
    p: Principal = require(ACTIONS.WORKSPACE_ADMIN),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> MoiLaiRaOut:
    """`invitePath` về `None` khi thư đã gửi — cùng hợp đồng với `POST /members`."""
    async with pool.acquire() as conn, conn.transaction():
        token = await thanh_vien.moi_lai(
            conn, actor_id=p.user_id, tenant_id=p.tenant_id, user_id=user_id
        )
        email = await conn.fetchval("SELECT email FROM control.users WHERE id = $1", user_id)

    if await _gui_thu_moi(email, token):
        return MoiLaiRaOut(invitePath=None)
    return MoiLaiRaOut(invitePath=duong_dan_moi(token))
```

⚠ `MoiLaiRaOut.invitePath` hiện là `str`; đổi thành `str | None` trong `contracts.py` kèm docstring giải thích `None` = đã gửi thư.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/modules/auth -v && uv run pytest tests/unit/test_moi_route_khai_action.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/portal/modules/auth/thanh_vien.py src/portal/modules/auth/router.py \
        src/portal/modules/auth/contracts.py tests/modules/auth/test_thanh_vien.py
git commit -m "feat(auth): PATCH/DELETE/invite trên /members — chức năng mời sống trở lại"
```

---

### Task 7: Viết lại `POST /auth/register` + `LoiMoiOut.kind`

**Files:**
- Modify: `src/portal/modules/auth/contracts.py` (`VaoDangKy`, `LoiMoiOut`, thêm `DangKyRaOut`)
- Modify: `src/portal/modules/auth/repo.py` (`tao_user_tu_dang_ky`, `doc_loi_moi_con_hieu_luc`)
- Modify: `src/portal/modules/auth/service.py` (`dang_ky`)
- Modify: `src/portal/modules/auth/quan_tri_user.py` (`xem_loi_moi`)
- Modify: `src/portal/modules/auth/router.py`
- Test: `tests/modules/auth/test_dang_ky.py` (create)

**Interfaces:**
- Consumes: Task 2, Task 3
- Produces:
  - `service.dang_ky(conn, *, email: str, name: str) -> tuple[str, str, bool]` — `(user_id, token_thô, da_gui_lai)`; ném `loi.email_da_ton_tai()` cho tài khoản đã có mật khẩu
  - `DangKyRaOut(daGuiLai: bool)`
  - `LoiMoiOut.kind: Literal["signup", "invite"]`

- [ ] **Step 1: Write the failing test**

```python
# tests/modules/auth/test_dang_ky.py
import pytest


@pytest.mark.anyio
async def test_dang_ky_moi_tra_201_va_khong_dat_cookie(client, pool):
    res = await client.post("/api/v1/auth/register", json={"email": "New@X.vn", "name": "Người Mới"})
    assert res.status_code == 201, res.text
    assert res.json() == {"daGuiLai": False}
    assert "sid" not in res.cookies, "đăng ký KHÔNG còn tự phát phiên — phải qua hộp thư"

    r = await pool.fetchrow(
        """SELECT u.lifecycle, u.password_hash, i.tenant_id
             FROM control.users u JOIN control.invites i ON i.user_id = u.id
            WHERE u.email = 'new@x.vn'"""
    )
    assert r["lifecycle"] == "pending"
    assert r["password_hash"] is None
    assert r["tenant_id"] is None, "token tự đăng ký KHÔNG gắn workspace"


@pytest.mark.anyio
async def test_dang_ky_lai_khi_pending_tra_200_va_giet_token_cu(client, pool):
    await client.post("/api/v1/auth/register", json={"email": "lai@x.vn", "name": "Lại"})
    cu = await pool.fetchval("SELECT token_hash FROM control.invites i JOIN control.users u ON u.id=i.user_id WHERE u.email='lai@x.vn'")

    res = await client.post("/api/v1/auth/register", json={"email": "lai@x.vn", "name": "Lại"})
    assert res.status_code == 200, res.text
    assert res.json() == {"daGuiLai": True}

    moi = await pool.fetchval("SELECT token_hash FROM control.invites i JOIN control.users u ON u.id=i.user_id WHERE u.email='lai@x.vn'")
    assert moi != cu


@pytest.mark.anyio
async def test_dang_ky_email_da_active_tra_409_va_khong_ghi_gi(client, pool):
    """Quyết định 2026-08-17: nói thẳng là trùng. Nhánh này KHÔNG được là một
    đường bắt server gửi thư."""
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO control.users (id,email,name,password_hash,lifecycle)
               VALUES ('u_da','da@x.vn','Da','$argon2id$fake','active')"""
        )
    res = await client.post("/api/v1/auth/register", json={"email": "da@x.vn", "name": "Da"})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "EMAIL_TAKEN"
    assert await pool.fetchval("SELECT count(*) FROM control.invites WHERE user_id='u_da'") == 0


@pytest.mark.anyio
async def test_signup_enabled_false_tra_403(client, monkeypatch):
    """`monkeypatch.setenv` LÀ ĐỦ — KHÔNG gọi `get_settings.cache_clear()`.

    ⚠ `get_settings()` dựng `Settings()` MỚI mỗi lần gọi, KHÔNG có `lru_cache`.
    Đó là bất biến có chủ ý, ghi tường minh ở `tests/modules/enrollment/conftest.py`
    và `tests/modules/auth/conftest.py`, và `router._secure()` dựa vào nó ("đọc
    cấu hình MỖI lần"). Đừng thêm cache để làm test này chạy — gọi `cache_clear()`
    ở đây sẽ `AttributeError`, và đó là tín hiệu đúng.
    """
    monkeypatch.setenv("SIGNUP_ENABLED", "false")
    res = await client.post("/api/v1/auth/register", json={"email": "z@x.vn", "name": "Z"})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FEATURE_DISABLED"


@pytest.mark.anyio
async def test_xem_loi_moi_tra_kind_signup(client):
    await client.post("/api/v1/auth/register", json={"email": "k@x.vn", "name": "K"})
    # token thô không đọc lại được từ DB — lấy qua mailer stub ở conftest (xem Step 3)
    from tests.modules.auth.conftest import THU_DA_GUI

    token = THU_DA_GUI[-1]["token"]
    res = await client.get(f"/api/v1/invites/{token}")
    assert res.status_code == 200
    assert res.json()["kind"] == "signup"


@pytest.mark.anyio
async def test_dang_nhap_van_gop_ba_tinh_huong_vao_mot_ma(client, pool):
    """Canh §4.2b: /auth/register lộ email tồn tại KHÔNG kéo theo nới lỏng ở login."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO control.users (id,email,name,lifecycle) VALUES ('u_p','p@x.vn','P','pending')"
        )
    a = await client.post("/api/v1/auth/login", json={"email": "p@x.vn", "password": "saibet123456"})
    b = await client.post("/api/v1/auth/login", json={"email": "khongcoai@x.vn", "password": "saibet123456"})
    assert a.status_code == b.status_code == 401
    assert a.json()["error"] == b.json()["error"]
```

Thêm vào `tests/modules/auth/conftest.py` một stub mailer ghi lại thư (để test lấy được token thô):

```python
THU_DA_GUI: list[dict] = []


@pytest.fixture(autouse=True)
def mailer_stub(monkeypatch):
    """Bắt thư thay vì gửi. Token thô CHỈ tồn tại trong link, DB chỉ có sha256."""
    THU_DA_GUI.clear()

    async def _gui(*, den, tieu_de, than_text, than_html):
        token = than_text.split("/invite/")[-1].split()[0] if "/invite/" in than_text else ""
        THU_DA_GUI.append({"den": den, "tieu_de": tieu_de, "token": token})
        return True

    monkeypatch.setattr("portal.core.mailer.gui", _gui)
    monkeypatch.setattr("portal.core.mailer.dang_bat", lambda: True)
    monkeypatch.setattr("portal.core.mailer.url_tuyet_doi", lambda p: f"https://test.local{p}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/modules/auth/test_dang_ky.py -v`
Expected: FAIL — `assert res.status_code == 201` nhận 422 (`password` là trường bắt buộc)

- [ ] **Step 3: Sửa contract**

```python
# src/portal/modules/auth/contracts.py

class VaoDangKy(BaseModel):
    """Tự đăng ký — đường công khai, không cần phiên.

    KHÔNG có `password`: mật khẩu đặt ở `POST /invites/accept` sau khi bấm link
    trong thư (sàn 10 ký tự của `NhanLoiMoiIn`). Đó là phép xác thực email, và nó
    miễn phí vì luồng lời mời đã có sẵn.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def _email_hop_le(cls, v: str) -> str:
        v = v.strip().lower()
        if not _RE_EMAIL.match(v):
            raise ValueError("email không đúng dạng")
        return v


class DangKyRaOut(BaseModel):
    daGuiLai: bool
    """`True` = tài khoản đã tồn tại ở trạng thái `pending` và thư vừa được GỬI LẠI.

    Tách khỏi nhánh 409: người mất thư có tài khoản `pending`, không có mật khẩu
    để đăng nhập, và đợt này chưa có "quên mật khẩu" — gộp họ vào 409 là nhốt họ
    trong ngõ cụt.
    """
```

`LoiMoiOut` thêm `kind`:

```python
class LoiMoiOut(BaseModel):
    # ... docstring cũ giữ nguyên ...
    email: str
    name: str
    kind: Literal["signup", "invite"]
    """Suy từ `invites.tenant_id IS NULL`. Từ 2026-08-17 có HAI loại token trên
    cùng một màn, và người tự đăng ký đọc "Bạn được mời tham gia" là câu SAI SỰ
    THẬT — không phải thiếu ngữ cảnh.

    KHÔNG kèm tên workspace: quyết định 2026-08-15 vẫn đúng (lời mời mở TRƯỚC khi
    có phiên, một cái tên lạ là thêm câu hỏi). `kind` là enum hai giá trị, không
    rò gì về workspace.
    """
```

- [ ] **Step 4: Sửa repo**

`tao_user_tu_dang_ky` bỏ `password_hash`, ghi `pending`:

```python
async def tao_user_tu_dang_ky(
    conn: asyncpg.Connection, *, user_id: str, email: str, name: str
) -> HangUser:
    """Tự đăng ký: user ra đời `pending` + `password_hash = NULL`.

    ĐỔI 2026-08-17: trước đây tạo thẳng `active` với mật khẩu từ form. Nay mật
    khẩu đặt qua link trong thư, nên CHECK `users_password_theo_lifecycle_check`
    (0103) buộc cặp (`pending`, NULL) đi cùng nhau — không có cách nào tạo sai.
    """
    r = await conn.fetchrow(
        f"""INSERT INTO control.users (id, email, name, password_hash, lifecycle)
                 VALUES ($1, $2, $3, NULL, 'pending')
              RETURNING {_COT_USER}""",
        user_id,
        email,
        name,
    )
    return HangUser(**dict(r))
```

`doc_loi_moi_con_hieu_luc` thêm `tenant_id` vào SELECT và vào dataclass hàng trả về (tìm bằng `grep -n "doc_loi_moi_con_hieu_luc" -A 25 src/portal/modules/auth/repo.py`).

- [ ] **Step 5: Viết lại service**

```python
# src/portal/modules/auth/service.py

async def dang_ky(conn: asyncpg.Connection, *, email: str, name: str) -> tuple[str, str, bool]:
    """Trả (user_id, token_thô, da_gui_lai). Người gọi mở giao dịch VÀ gửi thư sau commit.

    Ba nhánh (spec §4.1):
      · chưa tồn tại        -> tạo `pending`, phát token          -> da_gui_lai=False (201)
      · tồn tại, `pending`  -> phát token MỚI, token cũ chết      -> da_gui_lai=True  (200)
      · tồn tại, có mật khẩu-> ném `email_da_ton_tai()`           ->                 (409)

    Nhánh ba nói THẲNG là trùng — quyết định người yêu cầu 2026-08-17, spec §7.6.
    Nó KHÔNG kéo theo nới lỏng nào ở `dang_nhap`: xem spec §4.2b.
    """
    email = chuan_hoa_email(email)
    u = await repo.tim_user_theo_email(conn, email)

    if u is not None and u.lifecycle != "pending":
        raise loi_auth.email_da_ton_tai()

    if u is None:
        user_id = await sinh_user_id(conn, email)
        await repo.tao_user_tu_dang_ky(conn, user_id=user_id, email=email, name=name.strip())
        da_gui_lai = False
    else:
        user_id = u.id
        da_gui_lai = True

    token = secrets.token_urlsafe(_SO_BYTE_TOKEN)
    await repo.ghi_loi_moi(
        conn,
        token_hash=bam_token(token),
        user_id=user_id,
        tenant_id=None,
        expires_at=datetime.now(UTC) + HAN_MOI,
        created_by=user_id,  # không ai khác tạo hàng này
    )
    await nhat_ky.ghi_he_thong("user.dang_ky", user_id, {"email": email, "gui_lai": da_gui_lai})
    return user_id, token, da_gui_lai
```

⚠ Tên hàm nhật ký cấp hệ thống: kiểm bằng `grep -n "^async def ghi" src/portal/core/nhat_ky.py` và dùng đúng hàm đang có (sau 0106 `ghi_to_chuc` có thể đã đổi tên).

- [ ] **Step 6: Viết lại route + `xem_loi_moi`**

```python
# src/portal/modules/auth/router.py

@ROUTER.post("/auth/register", response_model=DangKyRaOut)
async def dang_ky(
    vao: VaoDangKy,
    res: Response,
    _: None = require(None, ly_do="chính đường này tạo ra tài khoản đầu tiên — đòi phiên là vòng tròn"),
    pool: asyncpg.Pool = Depends(lay_pool),
) -> DangKyRaOut:
    """201 = tài khoản mới · 200 = đã gửi lại thư · 409 = email đã có tài khoản.

    KHÔNG đặt cookie phiên: mật khẩu chưa tồn tại tại thời điểm này. Người dùng
    qua hộp thư -> `/invite/<token>` -> `/login`. Đây là bước LÙI có chủ ý so với
    bản trước (đăng ký xong vào thẳng) — cái giá của xác thực email.
    """
    if not get_settings().signup_enabled:
        raise loi.tinh_nang_dang_tat("đăng ký tài khoản")

    async with pool.acquire() as conn:
        async with conn.transaction():
            _, token, da_gui_lai = await service.dang_ky(conn, email=vao.email, name=vao.name)

    url = mailer.url_tuyet_doi(duong_dan_moi(token)) if mailer.dang_bat() else ""
    await mailer.gui(
        den=vao.email,
        tieu_de="Hoàn tất đăng ký NobleX Portal",
        than_text=f"Đặt mật khẩu để hoàn tất đăng ký:\n\n{url}\n\nLiên kết có hạn 7 ngày.",
        than_html=f'<p>Đặt mật khẩu để hoàn tất đăng ký:</p><p><a href="{url}">Đặt mật khẩu</a></p><p>Liên kết có hạn 7 ngày.</p>',
    )
    res.status_code = 200 if da_gui_lai else 201
    return DangKyRaOut(daGuiLai=da_gui_lai)
```

`quan_tri_user.xem_loi_moi` trả thêm `kind`:

```python
async def xem_loi_moi(conn: asyncpg.Connection, token: str) -> LoiMoiOut:
    """Cho màn đặt mật khẩu biết nó đang đặt cho tài khoản nào — và không hơn."""
    hang = await repo.doc_loi_moi_con_hieu_luc(conn, bam_token(token))
    if hang is None:
        raise loi.loi_moi_khong_hop_le()
    return LoiMoiOut(
        email=hang.email,
        name=hang.name,
        kind="signup" if hang.tenant_id is None else "invite",
    )
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/modules/auth -v`
Expected: PASS. Test cũ nào còn khẳng định `/auth/register` trả `SessionOut`/201-với-cookie phải sửa theo §4.1 — sửa, đừng xoá.

- [ ] **Step 8: Chạy cổng toàn repo**

Run: `make check`
Expected: lint + test xanh (trừ 1 dòng đỏ đã biết ở `tests/isolation`, xem `CLAUDE.md`)

- [ ] **Step 9: Commit**

```bash
git add src/portal/modules/auth/ tests/modules/auth/
git commit -m "feat(auth): đăng ký gửi link qua email thay vì nhận mật khẩu trực tiếp"
```

---

### Task 8: Frontend

**Files:**
- Modify: `src/features/auth/api.ts`
- Modify: `src/features/auth/components/DangKyForm.tsx`
- Modify: `src/features/auth/components/NhanLoiMoi.tsx`
- Modify: `src/features/auth/thanhVien.ts`
- Modify: `src/lib/msw/handlers.ts`
- Test: `tests/dang-ky.test.tsx` (create), `tests/nhan-loi-moi.test.tsx` (modify)

**Interfaces:**
- Consumes: Task 5, 6, 7 (hợp đồng HTTP)
- Produces: `dangKy(email: string, ten: string): Promise<{ daGuiLai: boolean }>`

- [ ] **Step 1: Write the failing test**

```tsx
// tests/dang-ky.test.tsx
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { DangKyForm } from '@/features/auth/components/DangKyForm'

describe('DangKyForm', () => {
  it('không còn ô mật khẩu — mật khẩu đặt ở màn /invite', () => {
    render(<DangKyForm />)
    expect(screen.queryByLabelText(/mật khẩu/i)).toBeNull()
  })

  it('gửi xong hiện màn kiểm tra hộp thư có ĐÚNG địa chỉ vừa nhập', async () => {
    render(<DangKyForm />)
    await userEvent.type(screen.getByLabelText(/email/i), 'moi@x.vn')
    await userEvent.type(screen.getByLabelText(/họ tên/i), 'Người Mới')
    await userEvent.click(screen.getByRole('button', { name: /đăng ký/i }))

    await waitFor(() => {
      expect(screen.getByText(/moi@x\.vn/)).toBeInTheDocument()
    })
  })

  it('409 hiện lỗi trùng email KÈM nút Đăng nhập', async () => {
    render(<DangKyForm />)
    await userEvent.type(screen.getByLabelText(/email/i), 'trung@x.vn')
    await userEvent.type(screen.getByLabelText(/họ tên/i), 'Trùng')
    await userEvent.click(screen.getByRole('button', { name: /đăng ký/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/đã có tài khoản/i)
    })
    expect(screen.getByRole('link', { name: /đăng nhập/i })).toBeInTheDocument()
  })
})
```

Trong `src/lib/msw/handlers.ts` thêm handler: `trung@x.vn` → 409 `{error:{code:'EMAIL_TAKEN',message:'Email này đã có tài khoản.'}}`; email khác → 201 `{daGuiLai:false}`.

- [ ] **Step 2: Run test to verify it fails**

Run: `npm test -- dang-ky` (trong `odyssey-portal-frontend`)
Expected: FAIL — vẫn tìm thấy ô mật khẩu

- [ ] **Step 3: Sửa seam API**

```ts
// src/features/auth/api.ts
/**
 * Tự đăng ký. KHÔNG còn trả `Session` và KHÔNG còn đặt cookie (đổi 2026-08-17):
 * mật khẩu đặt ở `/invite/<token>` sau khi bấm link trong thư.
 *
 * 201 -> `{daGuiLai:false}` · 200 -> `{daGuiLai:true}` (tài khoản `pending`, thư
 * vừa gửi lại) · 409 `EMAIL_TAKEN` -> ném `LoiApi`.
 */
export function dangKy(email: string, ten: string): Promise<{ daGuiLai: boolean }> {
  return goi<{ daGuiLai: boolean }>('/api/v1/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, name: ten }),
  })
}
```

- [ ] **Step 4: Sửa `DangKyForm.tsx`**

Bỏ state mật khẩu và ô nhập. Sau `mutate` thành công, **không** `navigate` — render một trong hai màn:

```tsx
if (ketQua) {
  return (
    <Khung>
      <h1 className="text-[20px] font-semibold text-fg">Kiểm tra hộp thư</h1>
      <p className="mx-auto mt-3 max-w-[420px] text-[14px] text-muted">
        {ketQua.daGuiLai
          ? 'Tài khoản này chưa hoàn tất đăng ký. Chúng tôi vừa gửi lại liên kết đặt mật khẩu tới '
          : 'Đã gửi liên kết đặt mật khẩu tới '}
        <strong className="text-fg">{email}</strong>. Kiểm tra cả mục spam. Liên kết có hạn 7 ngày.
      </p>
    </Khung>
  )
}
```

Nhánh lỗi 409:

```tsx
{gui.error instanceof LoiApi && gui.error.code === 'EMAIL_TAKEN' ? (
  <>
    <p role="alert" className="mt-3 text-[13.5px] text-badge-alert-fg">Email này đã có tài khoản.</p>
    <Link to="/login" className="mt-2 inline-block text-[13.5px] font-semibold text-ac">Đăng nhập</Link>
  </>
) : gui.error ? (
  <p role="alert" className="mt-3 text-[13.5px] text-badge-alert-fg">{gui.error.message}</p>
) : null}
```

- [ ] **Step 5: Sửa `NhanLoiMoi.tsx` đọc `kind`**

```tsx
// thêm `kind` vào interface LoiMoi trong api.ts:
//   readonly kind: 'signup' | 'invite'
const laDangKy = loiMoi.kind === 'signup'
// tiêu đề:  laDangKy ? 'Hoàn tất đăng ký' : 'Bạn được mời tham gia'
// nút:      laDangKy ? 'Đặt mật khẩu' : 'Đặt mật khẩu và tham gia'
```

Sửa `tests/nhan-loi-moi.test.tsx`: mock thêm `kind`, và thêm một bài khẳng định `kind:'signup'` render "Hoàn tất đăng ký".

- [ ] **Step 6: Sửa `thanhVien.ts`**

```ts
/** Một email KHÔNG mời được. Lỗi theo TỪNG DÒNG: mời 40 người mà một người hỏng
 *  thì 39 người kia vẫn phải vào được. */
export interface LoiMoiTungDong {
  readonly email: string
  readonly ma: string
}

export function moiThanhVien(
  emails: readonly string[],
  roleId: string,
): Promise<{ invites: KetQuaMoi[]; loi: LoiMoiTungDong[] }> {
  return goi<{ invites: KetQuaMoi[]; loi: LoiMoiTungDong[] }>('/api/v1/members', {
    method: 'POST',
    body: JSON.stringify({ emails, roleId }),
  })
}
```

`MoiThanhVienDialog.tsx` panel kết quả hiện thêm khối `loi` với câu cho `USER_PENDING_SIGNUP`: *"{email} đang chờ hoàn tất đăng ký. Khi họ đặt xong mật khẩu, hãy thêm lại."*

- [ ] **Step 7: Run tests**

Run: `npm test && npm run build`
Expected: PASS. (`npm run build` chứ không `tsc --noEmit` — repo dùng tsconfig solution-style.)

- [ ] **Step 8: Commit**

```bash
git add src/features/auth src/lib/msw/handlers.ts tests/
git commit -m "feat(auth): màn đăng ký gửi link qua thư, NhanLoiMoi phân biệt signup/invite"
```

---

### Task 9: Tài liệu

**Files:**
- Modify: `CLAUDE.md` (backend) — mục Commands nếu đổi, một dòng Change Log
- Modify: `odyssey-portal-frontend/CLAUDE.md` nếu có nhắc luồng đăng ký

- [ ] **Step 1: Thêm dòng Change Log**

Thêm vào đầu bảng Change Log của `odyssey-portal-backend/CLAUDE.md`:

```markdown
| 2026-08-17 | **Đăng ký gửi link qua email + seam `/members` ghi sống lại.** `POST /auth/register` bỏ trường `password` và KHÔNG còn tự phát phiên: tài khoản ra đời `pending`, mật khẩu đặt ở `/invite/<token>` (sàn 10 ký tự) — xác thực email thành miễn phí vì tái dùng nguyên luồng lời mời. Ba mã: **201** mới · **200** `daGuiLai` (tài khoản `pending`, gửi lại thư) · **409 `EMAIL_TAKEN`** (nói thẳng là trùng — quyết định người yêu cầu; KHÔNG kéo theo nới lỏng nào ở `dang_nhap`, chỗ đó vẫn gộp ba tình huống vào một mã và vẫn gọi `pw.kiem_gia()`). Mới: `core/mailer.py` (aiosmtplib, tắt an toàn khi thiếu `SMTP_HOST`/`PORTAL_BASE_URL`, **nuốt lỗi** vì giao dịch đã commit trước khi gửi), cờ `SIGNUP_ENABLED` (mặc định **bật**), `invites.tenant_id` (NULL = token đăng ký, có giá trị = token mời ⇒ `LoiMoiOut.kind`). ⚠ Phát hiện lúc rà: sau `0106` chức năng MỜI **không có đường nào chạy** — `/users*` bị `USERS_ADMIN_ENABLED` đóng, `seed_owner` chết sau người `active` đầu tiên, và `/members` mới chỉ có `GET`. Đợt này dựng 4 endpoint ghi `/members` (gate `WORKSPACE_ADMIN`) theo đúng hợp đồng FE đã chốt từ 2026-08-09. ⚠ `SMTP_SECURE=false` của Nodemailer nghĩa là **STARTTLS**, không phải "không mã hoá" — trường trong `Settings` vì thế tên `smtp_starttls`. Spec: `docs/superpowers/specs/2026-08-15-dang-ky-tu-phuc-vu-va-mail-design.md`, plan: `docs/superpowers/plans/2026-08-17-dang-ky-tu-phuc-vu-va-mail.md`. |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: ghi nhận luồng đăng ký qua email và seam /members ghi"
```

---

## Ngoài phạm vi plan này

Theo spec §11 — **không** làm ở đợt này: quên mật khẩu · rate limit (`SIGNUP_ENABLED` là công tắc duy nhất) · bật lại `USERS_ADMIN_ENABLED`/`ROLES_CRUD_ENABLED` · đổi email tài khoản · thư nhắc hết hạn · hàng đợi/retry mail · template engine · xin SES production access (việc vận hành).
